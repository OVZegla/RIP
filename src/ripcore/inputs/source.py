"""Chargement des images source et mise à l'échelle vers la grille machine.

Deux points décident du bon fonctionnement sur des formats muraux.

**La grille n'est pas carrée** (720 × 900 ou 720 × 1200 dpi). Une image
redimensionnée avec le même facteur en X et en Y sort déformée : le
rééchantillonnage vise toujours les dimensions en *pixels machine* calculées
séparément sur chaque axe.

**Rien n'est chargé en entier.** Une fresque de 4,5 m en 720 × 900 dpi fait
127 000 pixels de large : la rééchantillonner d'un bloc demanderait des dizaines
de gigaoctets. L'image est donc rééchantillonnée **bande par bande**, à la
demande, via le paramètre ``box`` de Pillow — qui rééchantillonne une région
source vers une taille cible sans matérialiser l'image complète.

La rotation, elle, s'applique une fois à la source (quelques mégapixels), pas au
raster machine (quelques gigapixels).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..errors import RipError

MM_PER_INCH = 25.4

RASTER_SUFFIXES = frozenset(
    {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp", ".webp"}
)
PDF_SUFFIXES = frozenset({".pdf", ".ps", ".eps", ".ai"})

_MODES_SUPPORTES = ("RGB", "CMYK", "L")


def _pillow():
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        raise RipError(
            "la lecture d'images requiert Pillow : pip install 'ripcore[images]'"
        ) from None
    # La garde anti-« bombe de décompression » de Pillow gêne ici : les formats
    # muraux dépassent légitimement ses seuils.
    Image.MAX_IMAGE_PIXELS = None
    return Image


def pixels_for(size_mm: float, dpi: int) -> int:
    """Millimètres → pixels machine, arrondi au supérieur (on ne rogne pas)."""
    if size_mm <= 0:
        raise RipError(f"dimension invalide : {size_mm} mm")
    return max(1, math.ceil(size_mm / MM_PER_INCH * dpi))


@dataclass(slots=True)
class SourceImage:
    """Image source, rééchantillonnée à la demande vers la grille machine.

    ``band(y0, y1)`` rend un bloc (C, h, W) float32 dans [0, 1] à la résolution
    machine. L'objet garde l'image ouverte : refermez-le avec ``close()`` ou
    utilisez-le comme gestionnaire de contexte.
    """

    width_px: int
    height_px: int
    mode: str
    source: Path | None = None
    embedded_icc: bytes | None = None
    _image: Any = field(default=None, repr=False)
    _alpha: Any = field(default=None, repr=False)
    _filtre: Any = field(default=None, repr=False)

    @property
    def channels(self) -> int:
        return {"RGB": 3, "CMYK": 4, "L": 1}[self.mode]

    @property
    def has_alpha(self) -> bool:
        return self._alpha is not None

    def band(self, y0: int, y1: int) -> tuple[np.ndarray, np.ndarray | None]:
        """Bande [y0, y1) de la sortie → (données (C, h, W), alpha (h, W) | None)."""
        if not 0 <= y0 < y1 <= self.height_px:
            raise RipError(
                f"bande [{y0}, {y1}) hors de l'image ({self.height_px} lignes)"
            )
        boite = self._boite_source(y0, y1)
        cible = (self.width_px, y1 - y0)

        bloc = self._image.resize(cible, self._filtre, box=boite)
        données = np.asarray(bloc, dtype=np.uint8)
        if données.ndim == 2:
            données = données[:, :, None]
        données = np.ascontiguousarray(
            données.transpose(2, 0, 1)
        ).astype(np.float32) / 255.0

        alpha = None
        if self._alpha is not None:
            canal = self._alpha.resize(cible, self._filtre, box=boite)
            alpha = np.asarray(canal, dtype=np.float32) / 255.0
        return données, alpha

    def _boite_source(self, y0: int, y1: int) -> tuple[float, float, float, float]:
        """Région source correspondant à une bande de sortie, en coordonnées réelles.

        Des bornes flottantes évitent l'accumulation d'un décalage d'un pixel
        d'une bande à l'autre, qui se verrait comme une ligne à chaque raccord.
        """
        hauteur_source = self._image.height
        echelle = hauteur_source / self.height_px
        return (0.0, y0 * echelle, float(self._image.width), y1 * echelle)

    def close(self) -> None:
        for image in (self._image, self._alpha):
            if image is not None:
                image.close()
        self._image = None
        self._alpha = None

    def __enter__(self) -> SourceImage:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


FILTRES = {
    "lanczos": "LANCZOS",
    "bicubic": "BICUBIC",
    "bilinear": "BILINEAR",
    "nearest": "NEAREST",
}


def load_source(
    path: str | Path,
    *,
    width_px: int,
    height_px: int,
    resample: str = "lanczos",
    rotate: int = 0,
    mirror: bool = False,
) -> SourceImage:
    """Ouvre une image et prépare son rééchantillonnage vers la grille machine.

    La rotation et le miroir sont appliqués ici, **à la résolution source** :
    quelques mégapixels, contre plusieurs gigapixels une fois à la résolution
    machine.
    """
    Image = _pillow()
    p = Path(path)
    if p.suffix.lower() not in RASTER_SUFFIXES:
        raise RipError(
            f"{p.name} : format non pris en charge par ce chargeur "
            f"({', '.join(sorted(RASTER_SUFFIXES))}). Pour un PDF/PS, passez par "
            f"ripcore.inputs.pdf.render_pdf()."
        )
    if resample not in FILTRES:
        raise RipError(
            f"filtre de rééchantillonnage inconnu : {resample!r} "
            f"({' | '.join(FILTRES)})"
        )
    if rotate not in (0, 90, 180, 270):
        raise RipError(f"rotation {rotate}° non supportée (0, 90, 180, 270)")

    filtre = getattr(Image.Resampling, FILTRES[resample])
    image = Image.open(p)

    # Un JPEG peut être décodé directement à échelle réduite par le décodeur
    # lui-même : c'est gratuit, et ça évite de matérialiser des pixels que le
    # rééchantillonnage jetterait de toute façon.
    besoin = (height_px, width_px) if rotate in (90, 270) else (width_px, height_px)
    try:
        image.draft(None, besoin)
    except (AttributeError, ValueError):
        pass
    image.load()
    icc = image.info.get("icc_profile")

    image = _reduire_si_surdimensionnee(image, besoin, Image)

    alpha = None
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        image = rgba.convert("RGB")
    elif image.mode not in _MODES_SUPPORTES:
        image = image.convert("RGB")

    if rotate:
        transposition = {
            90: Image.Transpose.ROTATE_270,   # sens horaire
            180: Image.Transpose.ROTATE_180,
            270: Image.Transpose.ROTATE_90,
        }[rotate]
        image = image.transpose(transposition)
        if alpha is not None:
            alpha = alpha.transpose(transposition)
    if mirror:
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if alpha is not None:
            alpha = alpha.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    return SourceImage(
        width_px=width_px,
        height_px=height_px,
        mode=image.mode,
        source=p,
        embedded_icc=icc,
        _image=image,
        _alpha=alpha,
        _filtre=filtre,
    )


def _reduire_si_surdimensionnee(image, besoin: tuple[int, int], Image):
    """Réduit une source qui a plus de pixels que la machine n'en imprimera.

    Ce détail n'est **pas** le contournement que l'on fait dans certains RIP —
    réduire puis ré-agrandir, qui détruit du détail réel. Ici on ne retire que
    des pixels que le rééchantillonnage vers la grille machine jetterait de
    toute façon : la sortie est inchangée, seule la mémoire baisse.

    On garde une marge de 2× avant réduction, et on réduit par facteur entier
    (filtre moyenneur) avant le Lanczos final — un enchaînement qui produit
    moins de crénelage qu'un Lanczos unique depuis une source énorme.
    """
    besoin_l, besoin_h = besoin
    facteur = min(image.width // max(1, besoin_l * 2),
                  image.height // max(1, besoin_h * 2))
    if facteur < 2:
        return image
    try:
        return image.reduce(facteur)
    except (AttributeError, ValueError):  # pragma: no cover - Pillow ancien
        return image


def mesurer(path: str | Path, rotate: int = 0) -> tuple[int, int, float | None, float | None]:
    """(largeur, hauteur, dpi_x, dpi_y) de la source, rotation prise en compte."""
    Image = _pillow()
    with Image.open(path) as image:
        largeur, hauteur = image.size
        dpi = image.info.get("dpi")
    dpi_x = float(dpi[0]) if dpi else None
    dpi_y = float(dpi[1]) if dpi and len(dpi) > 1 else dpi_x
    if rotate in (90, 270):
        largeur, hauteur = hauteur, largeur
        dpi_x, dpi_y = dpi_y, dpi_x
    return largeur, hauteur, dpi_x, dpi_y


def fit_size_mm(
    src_width: int,
    src_height: int,
    *,
    src_dpi_x: float | None = None,
    src_dpi_y: float | None = None,
    width_mm: float | None = None,
    height_mm: float | None = None,
) -> tuple[float, float]:
    """Taille demandée, en millimètres, d'après la source et ce qui est imposé.

    Priorité : dimensions demandées > dpi de la source > 300 dpi par défaut. Si
    une seule dimension est donnée, l'autre suit le rapport d'aspect.
    """
    if width_mm is None and height_mm is None:
        sx = src_dpi_x or 300.0
        sy = src_dpi_y or sx
        return (src_width / sx * MM_PER_INCH, src_height / sy * MM_PER_INCH)
    if width_mm is None:
        assert height_mm is not None
        return (height_mm * src_width / src_height, height_mm)
    if height_mm is None:
        return (width_mm, width_mm * src_height / src_width)
    return (width_mm, height_mm)


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
    """Détermine la taille de sortie en pixels machine et en millimètres.

    Priorité : dimensions demandées > dpi de la source > 300 dpi par défaut. Si
    une seule dimension est donnée, l'autre suit le rapport d'aspect de la source.
    """
    width_mm, height_mm = fit_size_mm(
        src_width, src_height, src_dpi_x=src_dpi_x, src_dpi_y=src_dpi_y,
        width_mm=width_mm, height_mm=height_mm,
    )
    return (
        pixels_for(width_mm, dpi_x),
        pixels_for(height_mm, dpi_y),
        width_mm,
        height_mm,
    )
