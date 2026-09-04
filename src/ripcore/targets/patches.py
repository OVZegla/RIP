"""Mires de calibration.

Trois mires, dans l'ordre où il faut les imprimer. Chacune répond à *une*
question laissée ouverte par la rétro-ingénierie, et chacune se lit sans
instrument pour la première, avec un densitomètre pour les deux autres.

1. ``channel-id`` — **quel plan du fichier commande quelle encre ?** Le dossier
   RIP marque ce point comme irréductible sans exécution (§12). Un tirage suffit
   à le lever. Les repères sont géométriques, pas typographiques : on compte des
   carrés, ce qui reste lisible même si la tête décale.
2. ``drop-wedge`` — **que dépose réellement chaque taille de goutte ?** Les
   plages sont écrites en niveaux bruts, sans tramage : chaque plage est un
   aplat d'un seul niveau. La densité mesurée donne directement l'échelle
   ``drop_levels`` du profil.
3. ``lin-wedge`` — **la réponse est-elle linéaire ?** Plages tramées
   normalement, de 0 à 100 %. Les mesures alimentent ``Linearization``.

Toutes contournent la gestion couleur : ce sont des mires *machine*, exprimées
directement en encre.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..errors import RipError
from ..halftone.engines import Halftoner
from ..profiles import PrinterProfile

MM_PER_INCH = 25.4


def _px(mm: float, dpi: int) -> int:
    return max(1, round(mm / MM_PER_INCH * dpi))


@dataclass(frozen=True, slots=True)
class Patch:
    """Une plage mesurable, repérée pour la saisie des mesures."""

    channel: str
    kind: str  # "level" | "tone"
    value: float  # niveau brut, ou tonalité demandée 0..1
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float


@dataclass(slots=True)
class Target:
    """Mire prête à écrire : niveaux bruts + plan de lecture."""

    name: str
    levels: np.ndarray  # (C, H, W) uint8
    dpi_x: int
    dpi_y: int
    description: str
    patches: list[Patch] = field(default_factory=list)

    @property
    def width_mm(self) -> float:
        return self.levels.shape[2] / self.dpi_x * MM_PER_INCH

    @property
    def height_mm(self) -> float:
        return self.levels.shape[1] / self.dpi_y * MM_PER_INCH


def channel_id(
    profile: PrinterProfile,
    *,
    dpi_x: int = 720,
    dpi_y: int = 900,
    bar_mm: float = 30.0,
    gap_mm: float = 6.0,
    margin_mm: float = 10.0,
) -> Target:
    """Une barre pleine par plan, numérotée par des carrés de comptage.

    Lecture : la barre accompagnée de *n* carrés correspond au plan *n−1* du
    fichier. On note la couleur sortie en face de chaque barre, et on reporte
    l'ordre obtenu dans ``channel_order`` du profil.
    """
    n = profile.n_channels
    top_level = (1 << profile.bits_per_pixel) - 1

    mark_mm = 4.0
    mark_gap_mm = 2.0
    counter_mm = n * (mark_mm + mark_gap_mm) + 4.0
    width_mm = margin_mm * 2 + counter_mm + bar_mm * 3
    height_mm = margin_mm * 2 + n * bar_mm + (n - 1) * gap_mm

    w, h = _px(width_mm, dpi_x), _px(height_mm, dpi_y)
    levels = np.zeros((n, h, w), dtype=np.uint8)
    patches: list[Patch] = []

    for i in range(n):
        y0_mm = margin_mm + i * (bar_mm + gap_mm)
        y0, y1 = _px(y0_mm, dpi_y), _px(y0_mm + bar_mm, dpi_y)

        # Carrés de comptage : i+1 marques, alignées à gauche de la barre.
        for k in range(i + 1):
            mx_mm = margin_mm + k * (mark_mm + mark_gap_mm)
            mx0, mx1 = _px(mx_mm, dpi_x), _px(mx_mm + mark_mm, dpi_x)
            my0 = _px(y0_mm + bar_mm / 2 - mark_mm / 2, dpi_y)
            my1 = my0 + _px(mark_mm, dpi_y)
            levels[i, my0:my1, mx0:mx1] = top_level

        bx_mm = margin_mm + counter_mm
        bx0, bx1 = _px(bx_mm, dpi_x), _px(bx_mm + bar_mm * 3, dpi_x)
        levels[i, y0:y1, bx0:bx1] = top_level
        patches.append(
            Patch(
                channel=profile.channel_names[i],
                kind="level",
                value=float(top_level),
                x_mm=bx_mm,
                y_mm=y0_mm,
                w_mm=bar_mm * 3,
                h_mm=bar_mm,
            )
        )

    return Target(
        name="channel-id",
        levels=levels,
        dpi_x=dpi_x,
        dpi_y=dpi_y,
        description=(
            f"Identification des plans — {n} barres. La barre précédée de n "
            f"carrés est le plan n-1 du fichier .prn. Notez la couleur sortie "
            f"en face de chaque barre, puis reportez l'ordre dans le profil."
        ),
        patches=patches,
    )


def drop_wedge(
    profile: PrinterProfile,
    *,
    dpi_x: int = 720,
    dpi_y: int = 900,
    patch_mm: float = 20.0,
    gap_mm: float = 4.0,
    margin_mm: float = 10.0,
) -> Target:
    """Un aplat par (canal × taille de goutte), sans tramage.

    Chaque plage est un aplat d'un seul niveau : tous ses pixels portent la même
    taille de goutte. La densité mesurée est donc *exactement* la densité de
    cette taille de goutte, sans contribution du tramage. C'est ce qui remplit
    ``drop_levels.densities``.
    """
    n = profile.n_channels
    n_levels = 1 << profile.bits_per_pixel
    cols = n_levels - 1  # le niveau 0 est le support nu, inutile de l'imprimer

    width_mm = margin_mm * 2 + cols * patch_mm + (cols - 1) * gap_mm
    height_mm = margin_mm * 2 + n * patch_mm + (n - 1) * gap_mm
    w, h = _px(width_mm, dpi_x), _px(height_mm, dpi_y)
    levels = np.zeros((n, h, w), dtype=np.uint8)
    patches: list[Patch] = []

    for i in range(n):
        y_mm = margin_mm + i * (patch_mm + gap_mm)
        y0, y1 = _px(y_mm, dpi_y), _px(y_mm + patch_mm, dpi_y)
        for j in range(cols):
            level = j + 1
            x_mm = margin_mm + j * (patch_mm + gap_mm)
            x0, x1 = _px(x_mm, dpi_x), _px(x_mm + patch_mm, dpi_x)
            levels[i, y0:y1, x0:x1] = level
            patches.append(
                Patch(
                    channel=profile.channel_names[i],
                    kind="level",
                    value=float(level),
                    x_mm=x_mm,
                    y_mm=y_mm,
                    w_mm=patch_mm,
                    h_mm=patch_mm,
                )
            )

    return Target(
        name="drop-wedge",
        levels=levels,
        dpi_x=dpi_x,
        dpi_y=dpi_y,
        description=(
            f"Tailles de goutte — {n} lignes (canaux) × {cols} colonnes "
            f"(niveaux 1 à {cols}). Aplats non tramés : mesurez la densité de "
            f"chaque plage, normalisez sur la colonne de droite."
        ),
        patches=patches,
    )


def lin_wedge(
    profile: PrinterProfile,
    halftoner: Halftoner,
    *,
    dpi_x: int = 720,
    dpi_y: int = 900,
    steps: int = 21,
    patch_mm: float = 12.0,
    gap_mm: float = 2.0,
    margin_mm: float = 10.0,
) -> Target:
    """Coin dégradé tramé, ``steps`` paliers par canal, pour la linéarisation."""
    if steps < 3:
        raise RipError("au moins 3 paliers sont nécessaires")
    n = profile.n_channels

    width_mm = margin_mm * 2 + steps * patch_mm + (steps - 1) * gap_mm
    height_mm = margin_mm * 2 + n * patch_mm + (n - 1) * gap_mm
    w, h = _px(width_mm, dpi_x), _px(height_mm, dpi_y)

    ink = np.zeros((n, h, w), dtype=np.float32)
    patches: list[Patch] = []
    tones = np.linspace(0.0, 1.0, steps)

    for i in range(n):
        y_mm = margin_mm + i * (patch_mm + gap_mm)
        y0, y1 = _px(y_mm, dpi_y), _px(y_mm + patch_mm, dpi_y)
        for j, tone in enumerate(tones):
            x_mm = margin_mm + j * (patch_mm + gap_mm)
            x0, x1 = _px(x_mm, dpi_x), _px(x_mm + patch_mm, dpi_x)
            ink[i, y0:y1, x0:x1] = tone
            patches.append(
                Patch(
                    channel=profile.channel_names[i],
                    kind="tone",
                    value=float(tone),
                    x_mm=x_mm,
                    y_mm=y_mm,
                    w_mm=patch_mm,
                    h_mm=patch_mm,
                )
            )

    halftoner.reset()
    levels = halftoner.process(ink, 0)
    return Target(
        name="lin-wedge",
        levels=levels,
        dpi_x=dpi_x,
        dpi_y=dpi_y,
        description=(
            f"Linéarisation — {n} lignes (canaux) × {steps} paliers de 0 à 100 %. "
            f"Mesurez chaque palier, puis « rip calibrate lin » construit les "
            f"courbes."
        ),
        patches=patches,
    )
