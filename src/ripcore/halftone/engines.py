"""Moteurs de tramage.

Deux familles, comme dans `ipht.dll`, mais réimplémentées — on ne clone pas le
module d'origine (c'est justement celui qui interroge le dongle USB, et son
comportement fin n'est pas établi par l'analyse statique).

* :class:`BlueNoiseHalftoner` — trame ordonnée à masque de bruit bleu. Sans
  état, donc reproductible et **incapable de produire une couture entre bandes**.
  C'est le défaut, et le bon choix par défaut sur une machine à passes.
* :class:`ErrorDiffusionHalftoner` — diffusion d'erreur multi-niveaux. Rend un
  peu mieux le micro-détail, au prix d'un état qui se propage. Vectorisée par
  fronts d'onde : le résultat est identique, au bit près, à un traitement de
  l'image entière en une fois — le découpage en bandes ne change rien.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from ..errors import RipError
from . import bluenoise
from .levels import quantize_nearest, quantize_ordered

# (dr, dc, poids) — poids normalisés à la construction.
FLOYD_STEINBERG = ((0, 1, 7.0), (1, -1, 3.0), (1, 0, 5.0), (1, 1, 1.0))
JARVIS = (
    (0, 1, 7.0), (0, 2, 5.0),
    (1, -2, 3.0), (1, -1, 5.0), (1, 0, 7.0), (1, 1, 5.0), (1, 2, 3.0),
    (2, -2, 1.0), (2, -1, 3.0), (2, 0, 5.0), (2, 1, 3.0), (2, 2, 1.0),
)
STUCKI = (
    (0, 1, 8.0), (0, 2, 4.0),
    (1, -2, 2.0), (1, -1, 4.0), (1, 0, 8.0), (1, 1, 4.0), (1, 2, 2.0),
    (2, -2, 1.0), (2, -1, 2.0), (2, 0, 4.0), (2, 1, 2.0), (2, 2, 1.0),
)
KERNELS = {
    "floyd-steinberg": FLOYD_STEINBERG,
    "jarvis": JARVIS,
    "stucki": STUCKI,
}


class Halftoner(Protocol):
    """Contrat commun : un raster contone en entrée, des niveaux en sortie."""

    def process(self, ink: np.ndarray, y0: int) -> np.ndarray:
        """(C, H, W) float 0..1 → (C, H, W) uint8 de niveaux.

        ``y0`` est l'ordonnée absolue de la première ligne de la bande dans le
        job complet.
        """
        ...

    def reset(self) -> None:
        """Repart d'un état vierge (nouveau job)."""
        ...

    @property
    def name(self) -> str: ...


@dataclass(slots=True)
class BlueNoiseHalftoner:
    """Trame ordonnée à masque de bruit bleu, multi-niveaux."""

    densities: np.ndarray
    channels: int
    mask_size: int = bluenoise.DEFAULT_SIZE
    sigma: float = bluenoise.DEFAULT_SIGMA
    seed: int = 0
    _thresholds: np.ndarray = field(init=False, repr=False)
    _offsets: tuple[tuple[int, int], ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.densities = np.asarray(self.densities, dtype=np.float32)
        mask = bluenoise.load_mask(self.mask_size, self.sigma, self.seed)
        self._thresholds = bluenoise.thresholds(mask)
        # Décalage propre à chaque canal : sans lui, tous les canaux placent
        # leurs gouttes aux mêmes endroits, ce qui surcharge certains pixels,
        # en laisse d'autres nus et fait virer la couleur dans les clairs.
        # Suite de Fibonacci décalée = répartition régulière et déterministe.
        s = self.mask_size
        self._offsets = tuple(
            ((i * 47) % s, (i * 89) % s) for i in range(self.channels)
        )

    @property
    def name(self) -> str:
        return f"bluenoise-{self.mask_size}"

    def reset(self) -> None:
        """Sans état : rien à réinitialiser."""

    def process(self, ink: np.ndarray, y0: int) -> np.ndarray:
        a = np.asarray(ink, dtype=np.float32)
        if a.ndim != 3 or a.shape[0] != self.channels:
            raise RipError(
                f"bande ({self.channels}, H, W) attendue, reçu {a.shape}"
            )
        c_n, h, w = a.shape
        s = self.mask_size
        out = np.empty((c_n, h, w), dtype=np.uint8)
        rows = (y0 + np.arange(h)) % s
        cols = np.arange(w) % s
        for c in range(c_n):
            dy, dx = self._offsets[c]
            th = self._thresholds[np.ix_((rows + dy) % s, (cols + dx) % s)]
            out[c] = quantize_ordered(a[c], self.densities, th)
        return out


@dataclass(slots=True)
class ErrorDiffusionHalftoner:
    """Diffusion d'erreur multi-niveaux, vectorisée par fronts d'onde.

    Les pixels d'un même front ``k = pente·y + x`` ne dépendent que de fronts
    strictement antérieurs : ils peuvent donc être quantifiés en une seule
    opération numpy. Le résultat est *exactement* celui d'un balayage
    ligne par ligne, pas une approximation.
    """

    densities: np.ndarray
    channels: int
    kernel_name: str = "floyd-steinberg"
    _kernel: tuple[tuple[int, int, float], ...] = field(init=False, repr=False)
    _slope: int = field(init=False, repr=False)
    _pad: int = field(init=False, repr=False)
    _depth: int = field(init=False, repr=False)
    _carry: np.ndarray | None = field(init=False, default=None, repr=False)
    _carry_y: int = field(init=False, default=-1, repr=False)

    def __post_init__(self) -> None:
        self.densities = np.asarray(self.densities, dtype=np.float32)
        try:
            raw = KERNELS[self.kernel_name]
        except KeyError:
            raise RipError(
                f"noyau de diffusion inconnu : {self.kernel_name!r} "
                f"(disponibles : {', '.join(sorted(KERNELS))})"
            ) from None
        total = sum(w for _, _, w in raw)
        self._kernel = tuple((dr, dc, w / total) for dr, dc, w in raw)
        self._depth = max(dr for dr, _, _ in raw)
        self._pad = max(abs(dc) for _, dc, _ in raw)
        # Pente minimale garantissant que toute dépendance est sur un front
        # antérieur (cf. docstring de la classe).
        self._slope = max(
            [1] + [(-dc) // dr + 1 for dr, dc, _ in raw if dr > 0 and dc < 0]
        )

    @property
    def name(self) -> str:
        return f"errdiff-{self.kernel_name}"

    def reset(self) -> None:
        self._carry = None
        self._carry_y = -1

    def process(self, ink: np.ndarray, y0: int) -> np.ndarray:
        a = np.asarray(ink, dtype=np.float32)
        if a.ndim != 3 or a.shape[0] != self.channels:
            raise RipError(f"bande ({self.channels}, H, W) attendue, reçu {a.shape}")
        c_n, h, w = a.shape
        if self._carry is not None and y0 != self._carry_y:
            raise RipError(
                f"bandes non contiguës : y0={y0}, {self._carry_y} attendu. "
                f"La diffusion d'erreur exige un balayage continu — appelez "
                f"reset() pour démarrer un nouveau job."
            )

        pad, depth, slope = self._pad, self._depth, self._slope
        err = np.zeros((c_n, h + depth, w + 2 * pad), dtype=np.float32)
        if self._carry is not None:
            err[:, :depth, :] = self._carry

        out = np.zeros((c_n, h, w), dtype=np.uint8)
        d = self.densities
        for k in range(slope * (h - 1) + w):
            r_lo = max(0, -((w - 1 - k) // slope))
            r_hi = min(h - 1, k // slope)
            if r_lo > r_hi:
                continue
            r = np.arange(r_lo, r_hi + 1)
            c = k - slope * r
            valid = (c >= 0) & (c < w)
            if not valid.all():
                r, c = r[valid], c[valid]
                if r.size == 0:
                    continue
            v = a[:, r, c] + err[:, r, c + pad]
            level, got = quantize_nearest(v, d)
            out[:, r, c] = level
            e = v - got
            for dr, dc, weight in self._kernel:
                err[:, r + dr, c + dc + pad] += weight * e

        self._carry = err[:, h : h + depth, :].copy()
        self._carry_y = y0 + h
        return out


def make_halftoner(
    engine: str, densities: np.ndarray, channels: int, **kwargs: object
) -> Halftoner:
    """Fabrique : ``bluenoise`` (défaut) ou ``errdiff[:noyau]``."""
    if engine in ("bluenoise", "blue-noise", "ordered"):
        return BlueNoiseHalftoner(densities, channels, **kwargs)  # type: ignore[arg-type]
    if engine.startswith("errdiff"):
        _, _, kern = engine.partition(":")
        return ErrorDiffusionHalftoner(
            densities, channels, kernel_name=kern or "floyd-steinberg"
        )
    raise RipError(
        f"moteur de tramage inconnu : {engine!r} "
        f"(bluenoise | errdiff | errdiff:jarvis | errdiff:stucki)"
    )
