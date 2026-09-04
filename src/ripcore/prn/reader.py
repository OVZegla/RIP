"""Lecture de fichiers `.prn`.

Sert à trois choses : relire ce qu'on vient d'écrire (contrôle avant envoi),
inspecter les `.prn` produits par UltraPrint (comparaison de référence), et
alimenter le rendu d'aperçu.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..errors import PrnFormatError
from .header import HEADER_SIZE, PrnHeader, detect_dialect
from .pack import unpack_levels


@dataclass(frozen=True, slots=True)
class PrnProbe:
    """Ce qu'on apprend d'un `.prn` sans lire le corps."""

    path: Path
    dialect: str
    header_size: int
    file_size: int
    header: PrnHeader | None
    body_size: int

    @property
    def supported(self) -> bool:
        return self.dialect == "generic" and self.header is not None

    def describe(self) -> str:
        if self.header is None:
            return (
                f"{self.path.name} : dialecte {self.dialect} "
                f"(en-tête {self.header_size} o) — lecture non implémentée"
            )
        return f"{self.path.name} : {self.header.describe()}"


def probe(path: str | Path) -> PrnProbe:
    p = Path(path)
    size = p.stat().st_size
    with open(p, "rb") as fh:
        head = fh.read(HEADER_SIZE)
    dialect, hsize = detect_dialect(head)
    header = None
    if dialect == "generic":
        header = PrnHeader.unpack(head)
    return PrnProbe(
        path=p,
        dialect=dialect,
        header_size=hsize,
        file_size=size,
        header=header,
        body_size=size - hsize,
    )


class PrnReader:
    """Lecteur en flux du dialecte générique."""

    def __init__(self, path: str | Path, *, width_px: int | None = None) -> None:
        self.path = Path(path)
        self.probe = probe(self.path)
        if not self.probe.supported:
            raise PrnFormatError(
                f"{self.path.name} : dialecte {self.probe.dialect} non pris en charge "
                f"en lecture (seul le générique 48 o l'est)"
            )
        assert self.probe.header is not None
        self.header = self.probe.header
        # La largeur utile n'est pas dans le fichier ; à défaut on prend la
        # largeur paddée, ce qui n'ajoute que des pixels nuls à droite.
        self.width_px = width_px if width_px is not None else self.header.width_px
        if self.width_px > self.header.width_px:
            raise PrnFormatError(
                f"width_px={self.width_px} > largeur paddée {self.header.width_px}"
            )
        expected = self.header.file_size
        if self.probe.file_size != expected:
            raise PrnFormatError(
                f"{self.path.name} : taille {self.probe.file_size} o, "
                f"{expected} o attendus d'après l'en-tête "
                f"({self.header.lines} lignes × {self.header.stride} o)"
            )

    def bands(self, lines_per_band: int = 512) -> Iterator[np.ndarray]:
        """Itère le raster par bandes (C, h, W) de niveaux uint8."""
        h = self.header
        with open(self.path, "rb") as fh:
            fh.seek(HEADER_SIZE)
            remaining = h.lines
            while remaining > 0:
                n = min(lines_per_band, remaining)
                raw = fh.read(n * h.stride)
                if len(raw) != n * h.stride:
                    raise PrnFormatError(
                        f"lecture tronquée à {h.lines - remaining} lignes"
                    )
                buf = np.frombuffer(raw, dtype=np.uint8).reshape(
                    n, h.channels, h.bytes_per_line_per_channel
                )
                yield unpack_levels(
                    buf.transpose(1, 0, 2), h.bits_per_pixel, self.width_px
                )
                remaining -= n

    def read_all(self) -> np.ndarray:
        """Raster complet (C, H, W). À réserver aux petits fichiers / tests."""
        parts = list(self.bands())
        if not parts:
            raise PrnFormatError("fichier sans ligne")
        return np.concatenate(parts, axis=1)
