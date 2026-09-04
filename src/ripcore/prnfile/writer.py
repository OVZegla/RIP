"""Écriture de fichiers `.prn` (dialecte générique 48 octets).

Deux garanties tenues par ce module :

1. **Atomicité.** On écrit dans un `.part` puis on renomme. Un `.prn` présent sur
   le disque est un `.prn` complet — pas de tirage lancé sur un fichier tronqué.
2. **Streaming.** Le raster n'est jamais entièrement en mémoire : un job
   300 × 300 mm en 720×900 dpi × 5 canaux fait déjà 113 Mo, et les grands
   formats muraux montent à plusieurs Go.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType

import numpy as np

from ..errors import PrnFormatError
from .header import HEADER_SIZE, PrnHeader, bytes_per_line
from .pack import pack_levels


@dataclass(slots=True)
class WriteStats:
    """Statistiques accumulées pendant l'écriture, pour le manifeste et la QA."""

    lines: int = 0
    pixels: int = 0
    level_histogram: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 0), dtype=np.int64)
    )

    def coverage(self, densities: tuple[float, ...]) -> np.ndarray:
        """Taux d'encre moyen par canal, en unités « pixel plein », 0..1."""
        if self.pixels == 0:
            return np.zeros(self.level_histogram.shape[0])
        d = np.asarray(densities, dtype=np.float64)
        return self.level_histogram @ d / self.pixels


class PrnWriter:
    """Écrivain `.prn` en flux.

    Usage::

        with PrnWriter(path, dpi_x=720, dpi_y=900, width_px=5680,
                       channels=5, bits_per_pixel=2, pass_mode=0) as w:
            for band in bands:                 # (C, H, W) uint8
                w.write_block(band)
        header = w.header
    """

    def __init__(
        self,
        path: str | Path,
        *,
        dpi_x: int,
        dpi_y: int,
        width_px: int,
        channels: int,
        bits_per_pixel: int,
        pass_mode: int,
    ) -> None:
        self.path = Path(path)
        self.dpi_x = int(dpi_x)
        self.dpi_y = int(dpi_y)
        self.width_px = int(width_px)
        self.channels = int(channels)
        self.bits_per_pixel = int(bits_per_pixel)
        self.pass_mode = int(pass_mode)
        self.bytes_per_line = bytes_per_line(self.width_px, self.bits_per_pixel)

        if self.channels <= 0:
            raise PrnFormatError(f"channels={self.channels}")

        self._tmp = self.path.with_name(self.path.name + ".part")
        self._fh = None
        self._closed = False
        self._header: PrnHeader | None = None
        self.stats = WriteStats(
            level_histogram=np.zeros(
                (self.channels, 1 << self.bits_per_pixel), dtype=np.int64
            )
        )

    # -- cycle de vie --------------------------------------------------------

    def __enter__(self) -> PrnWriter:
        self._tmp.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._tmp, "wb")
        # Place réservée : l'en-tête définitif dépend du nombre de lignes écrites.
        self._fh.write(b"\x00" * HEADER_SIZE)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self.abort()
        else:
            self.close()

    def abort(self) -> None:
        """Referme et supprime le fichier partiel."""
        if self._fh is not None and not self._fh.closed:
            self._fh.close()
        self._tmp.unlink(missing_ok=True)
        self._closed = True

    def close(self) -> PrnHeader:
        """Réécrit l'en-tête définitif, fsync, puis renomme atomiquement."""
        if self._closed:
            if self._header is None:
                raise PrnFormatError("écrivain déjà abandonné")
            return self._header
        if self._fh is None:
            raise PrnFormatError("écrivain non ouvert (utilisez le context manager)")
        if self.stats.lines == 0:
            self.abort()
            raise PrnFormatError("aucune ligne écrite : .prn vide refusé")

        header = PrnHeader(
            dpi_x=self.dpi_x,
            dpi_y=self.dpi_y,
            bytes_per_line_per_channel=self.bytes_per_line,
            lines=self.stats.lines,
            channels=self.channels,
            bits_per_pixel=self.bits_per_pixel,
            pass_mode=self.pass_mode,
        )
        self._fh.flush()
        written = self._fh.tell()
        if written != header.file_size:
            self.abort()
            raise PrnFormatError(
                f"incohérence interne : {written} octets écrits, "
                f"{header.file_size} attendus"
            )
        self._fh.seek(0)
        self._fh.write(header.pack())
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()
        os.replace(self._tmp, self.path)
        self._closed = True
        self._header = header
        return header

    @property
    def header(self) -> PrnHeader:
        if self._header is None:
            raise PrnFormatError("en-tête disponible seulement après close()")
        return self._header

    # -- écriture ------------------------------------------------------------

    def write_line(self, levels: np.ndarray) -> None:
        """Une ligne raster : tableau (channels, width_px) de niveaux uint8."""
        self.write_block(np.asarray(levels)[:, None, :])

    def write_block(self, levels: np.ndarray) -> None:
        """Une bande : tableau (channels, height, width_px) de niveaux uint8.

        Les plans sont écrits dans l'ordre du profil, canal après canal à
        l'intérieur de chaque ligne.
        """
        if self._fh is None or self._closed:
            raise PrnFormatError("écrivain fermé")
        a = np.asarray(levels)
        if a.ndim != 3:
            raise PrnFormatError(f"bloc (C, H, W) attendu, reçu {a.shape}")
        if a.shape[0] != self.channels:
            raise PrnFormatError(
                f"{a.shape[0]} canaux dans le bloc, {self.channels} déclarés"
            )
        if a.shape[2] != self.width_px:
            raise PrnFormatError(
                f"largeur {a.shape[2]} px, {self.width_px} déclarés"
            )
        if a.dtype != np.uint8:
            raise PrnFormatError(f"niveaux uint8 attendus, reçu {a.dtype}")

        packed = pack_levels(a, self.bits_per_pixel)  # (C, H, L)
        # Ordre fichier : pour chaque ligne, les canaux à la suite.
        interleaved = np.ascontiguousarray(packed.transpose(1, 0, 2))
        self._fh.write(interleaved.tobytes())

        self.stats.lines += a.shape[1]
        self.stats.pixels += a.shape[1] * self.width_px
        for c in range(self.channels):
            self.stats.level_histogram[c] += np.bincount(
                a[c].ravel(), minlength=1 << self.bits_per_pixel
            )


def write_prn(
    path: str | Path,
    levels: np.ndarray,
    *,
    dpi_x: int,
    dpi_y: int,
    bits_per_pixel: int,
    pass_mode: int,
) -> PrnHeader:
    """Écriture en un appel d'un raster complet (C, H, W) déjà en mémoire."""
    a = np.asarray(levels)
    if a.ndim != 3:
        raise PrnFormatError(f"raster (C, H, W) attendu, reçu {a.shape}")
    with PrnWriter(
        path,
        dpi_x=dpi_x,
        dpi_y=dpi_y,
        width_px=a.shape[2],
        channels=a.shape[0],
        bits_per_pixel=bits_per_pixel,
        pass_mode=pass_mode,
    ) as w:
        w.write_block(a)
    return w.header
