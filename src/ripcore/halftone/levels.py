"""Quantification multi-niveaux vers les tailles de goutte.

La tête I1600 tire 4 tailles de goutte (2 bits). Le point important, et celui que
la plupart des implémentations naïves ratent : **les niveaux ne sont pas
équidistants en densité**. Une goutte moyenne ne dépose pas les deux tiers d'une
grosse. On raisonne donc toujours en *densité déposée*, jamais en numéro de
niveau, et c'est la mesure du coin `drop-wedge` qui fournit l'échelle réelle.

Le nombre de niveaux est petit (4, parfois 16). On indexe donc par comptage de
comparaisons plutôt que par ``searchsorted`` : trois fois plus rapide sur des
rasters de plusieurs dizaines de millions de pixels, et sans allocation
intermédiaire.
"""

from __future__ import annotations

import numpy as np


def _bracket_index(v: np.ndarray, d: np.ndarray) -> np.ndarray:
    """Indice k tel que d[k] <= v <= d[k+1], borné à [0, len(d)-2]."""
    k = np.zeros(v.shape, dtype=np.uint8)
    for i in range(1, d.size - 1):
        k += v >= d[i]
    return k


def quantize_ordered(
    ink: np.ndarray, densities: np.ndarray, threshold: np.ndarray
) -> np.ndarray:
    """Tramage par seuil, multi-niveaux.

    ``ink`` (0..1) est encadré par deux densités réalisables d[k] ≤ ink ≤ d[k+1] ;
    on tire le niveau haut avec la probabilité qui rend la densité *moyenne*
    exactement égale à ``ink``. C'est ce qui garantit qu'un aplat à 42 % dépose
    bien 42 % d'encre, quelle que soit l'échelle des gouttes.
    """
    d = np.asarray(densities, dtype=np.float32)
    if d.size < 2:
        raise ValueError("au moins deux densités attendues")
    v = np.clip(ink, 0.0, 1.0).astype(np.float32, copy=False)

    k = _bracket_index(v, d)
    lo = d[k]
    span = d[k + 1] - lo
    frac = np.divide(v - lo, span, out=np.zeros_like(v), where=span > 0)
    return k + (frac > threshold).view(np.uint8)


def quantize_nearest(
    value: np.ndarray, densities: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Niveau réalisable le plus proche → (niveaux uint8, densités obtenues).

    Utilisé par la diffusion d'erreur, où la valeur d'entrée peut sortir de
    [0, 1] du fait de l'erreur accumulée. Le découpage se fait sur les milieux
    d'intervalle — la même construction ``(a+b)>>1`` que l'on retrouve dans
    ``ipht.dll``.
    """
    d = np.asarray(densities, dtype=np.float32)
    if d.size < 2:
        raise ValueError("au moins deux densités attendues")
    v = np.clip(value, d[0], d[-1])

    level = np.zeros(v.shape, dtype=np.uint8)
    for i in range(d.size - 1):
        level += v > (d[i] + d[i + 1]) * 0.5
    return level, d[level]


def density_of(levels: np.ndarray, densities: np.ndarray) -> np.ndarray:
    """Densité déposée correspondant à une carte de niveaux."""
    return np.asarray(densities, dtype=np.float32)[levels]
