"""Chargement des images source et mise à l'échelle vers la grille machine.

Point sensible : la grille de sortie n'est **pas carrée** (720 × 900 ou
720 × 1200 dpi). Une image redimensionnée avec le même facteur en X et en Y
sort déformée. Le rééchantillonnage se fait donc toujours vers les dimensions
en *pixels machine* calculées séparément sur chaque axe.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..errors import RipError

MM_PER_INCH = 25.4

RASTER_SUFFIXES = frozenset(
    {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp", ".webp"}
)
PDF_SUFFIXES = frozenset({".pdf", ".ps", ".eps", ".ai"})


def _require_pillow():
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        raise RipError(
            "la lecture d'images requiert Pillow : pip install 'ripcore[images]'"
        ) from None
    Image.MAX_IMAGE_PIXELS = None  # gros formats : la garde anti-bombe gêne ici
    return Image


@dataclass(frozen=True, slots=True)
class SourceImage:
    """Image source normalisée, prête pour la séparation.

    ``data`` est en (C, H, W) float32 dans [0, 1], à la résolution machine.
    ``mode`` vaut ``RGB``, ``CMYK`` ou ``L``.
    """

    data: np.ndarray
    mode: str
    alpha: np.ndarray | None = None
    source: Path | None = None
    embedded_icc: bytes | None = None

    @property
    def height(self) -> int:
        return self.data.shape[1]

    @property
    def width(self) -> int:
        return self.data.shape[2]


def pixels_for(size_mm: float, dpi: int) -> int:
    """Millimètres → pixels machine, arrondi au supérieur (on ne rogne pas)."""
    if size_mm <= 0:
        raise RipError(f"dimension invalide : {size_mm} mm")
    return max(1, math.ceil(size_mm / MM_PER_INCH * dpi))


def load_source(
    path: str | Path,
    *,
    width_px: int,
    height_px: int,
    resample: str = "lanczos",
) -> SourceImage:
    """Charge et met à l'échelle une image matricielle vers la grille machine."""
    Image = _require_pillow()
    p = Path(path)
    if p.suffix.lower() not in RASTER_SUFFIXES:
        raise RipError(
            f"{p.name} : format non pris en charge par ce chargeur "
            f"({', '.join(sorted(RASTER_SUFFIXES))}). Pour un PDF/PS, passez par "
            f"ripcore.inputs.pdf.render_pdf()."
        )

    filters = {
        "lanczos": Image.Resampling.LANCZOS,
        "bicubic": Image.Resampling.BICUBIC,
        "bilinear": Image.Resampling.BILINEAR,
        "nearest": Image.Resampling.NEAREST,
    }
    if resample not in filters:
        raise RipError(
            f"filtre de rééchantillonnage inconnu : {resample!r} "
            f"({' | '.join(filters)})"
        )

    with Image.open(p) as im:
        im.load()
        icc = im.info.get("icc_profile")
        alpha_img = None
        if im.mode in ("RGBA", "LA") or "transparency" in im.info:
            rgba = im.convert("RGBA")
            alpha_img = rgba.getchannel("A")
            im = rgba.convert("RGB")
        elif im.mode not in ("RGB", "CMYK", "L"):
            im = im.convert("RGB")

        mode = im.mode
        if (im.width, im.height) != (width_px, height_px):
            im = im.resize((width_px, height_px), filters[resample])
            if alpha_img is not None:
                alpha_img = alpha_img.resize((width_px, height_px), filters[resample])

        arr = np.asarray(im, dtype=np.uint8)
        alpha = (
            np.asarray(alpha_img, dtype=np.float32) / 255.0
            if alpha_img is not None
            else None
        )

    if arr.ndim == 2:
        arr = arr[:, :, None]
    data = np.ascontiguousarray(arr.transpose(2, 0, 1)).astype(np.float32) / 255.0

    if mode == "CMYK":
        # Pillow stocke le CMJN des TIFF/JPEG Adobe en valeurs inversées selon
        # les cas ; on ne devine pas. Un TIFF CMJN produit par un flux
        # prépresse standard arrive ici en « 0 = pas d'encre ».
        pass

    return SourceImage(
        data=data, mode=mode, alpha=alpha, source=p, embedded_icc=icc
    )


def fit_geometry(
    src_width: int,
    src_height: int,
    *,
    dpi_x: int,
    dpi_y: int,
    src_dpi_x: float | None = None,
    src_dpi_y: float | None = None,
    width_mm: float | None = None,
    height_mm: float | None = None,
) -> tuple[int, int, float, float]:
    """Détermine la taille de sortie en pixels machine et en mm.

    Priorité : dimensions demandées explicitement > dpi de la source > 300 dpi
    par défaut. Si une seule dimension est donnée, l'autre suit le rapport
    d'aspect de la source.
    """
    if width_mm is None and height_mm is None:
        sx = src_dpi_x or 300.0
        sy = src_dpi_y or sx
        width_mm = src_width / sx * MM_PER_INCH
        height_mm = src_height / sy * MM_PER_INCH
    elif width_mm is None:
        assert height_mm is not None
        width_mm = height_mm * src_width / src_height
    elif height_mm is None:
        height_mm = width_mm * src_height / src_width

    return (
        pixels_for(width_mm, dpi_x),
        pixels_for(height_mm, dpi_y),
        width_mm,
        height_mm,
    )
