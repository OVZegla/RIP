"""Limitation d'encre.

Deux limites, à ne pas confondre :

* **par canal** — au-delà, l'encre ne fait plus monter la densité, elle coule et
  bouche les buses ;
* **totale (TAC)** — somme sur tous les canaux d'un même pixel. C'est celle qui
  compte en UV : une surcharge ne polymérise pas à cœur, reste poisseuse, et
  colle au support suivant.

Le dossier RIP décrit un limiteur dans `dither.dll` piloté par des chartes
(`Ink Limited.tif`, `InkSplit.tif`) et `ColorCoefficient.ini`. On ne reproduit
pas ces réglages : on applique nos propres limites, mesurées sur nos supports.
"""

from __future__ import annotations

import numpy as np

from ..errors import RipError

# Stratégies de réduction quand le TAC est dépassé.
SCALE_ALL = "scale-all"  # réduit tous les canaux proportionnellement
PRESERVE_BLACK = "preserve-black"  # réduit les chromatiques, préserve le noir
STRATEGIES = (SCALE_ALL, PRESERVE_BLACK)


def limit_per_channel(ink: np.ndarray, limits: np.ndarray) -> np.ndarray:
    """Écrase chaque canal à sa limite propre.

    On *comprime* la plage au lieu de l'écrêter : écrêter à 90 % rendrait
    identiques toutes les valeurs de 90 à 100 %, ce qui aplatit les ombres.
    """
    a = np.asarray(ink, dtype=np.float32)
    lim = np.asarray(limits, dtype=np.float32).reshape(-1, 1, 1)
    if lim.shape[0] != a.shape[0]:
        raise RipError(f"{a.shape[0]} canaux, {lim.shape[0]} limites fournies")
    return a * lim


def limit_total(
    ink: np.ndarray,
    total: float,
    *,
    strategy: str = SCALE_ALL,
    protected: np.ndarray | None = None,
) -> np.ndarray:
    """Ramène la somme par pixel sous ``total``.

    ``protected`` est un masque booléen (C,) des canaux à préserver dans la
    stratégie ``preserve-black`` — typiquement le noir, dont la réduction coûte
    plus de densité qu'elle ne gagne en encre.
    """
    if strategy not in STRATEGIES:
        raise RipError(
            f"stratégie de limitation inconnue : {strategy!r} "
            f"({' | '.join(STRATEGIES)})"
        )
    a = np.asarray(ink, dtype=np.float32)
    if total <= 0:
        raise RipError(f"limite totale invalide : {total}")

    summed = a.sum(axis=0)
    over = summed > total
    if not over.any():
        return a

    out = a.copy()
    if strategy == SCALE_ALL or protected is None or not protected.any():
        factor = np.ones_like(summed)
        np.divide(total, summed, out=factor, where=over)
        out *= factor
        return out

    # preserve-black : on n'entame les canaux protégés qu'une fois les autres
    # ramenés à zéro — ce qui n'arrive qu'avec une limite très basse.
    prot = np.asarray(protected, dtype=bool)
    keep = a[prot].sum(axis=0)
    reducible = a[~prot].sum(axis=0)
    budget = np.maximum(total - keep, 0.0)

    factor = np.ones_like(summed)
    np.divide(budget, reducible, out=factor, where=over & (reducible > 0))
    np.clip(factor, 0.0, 1.0, out=factor)
    out[~prot] = a[~prot] * factor

    # Cas extrême : même à zéro de chromatiques, les canaux protégés dépassent.
    still = out.sum(axis=0) > total
    if still.any():
        f2 = np.ones_like(summed)
        s = out.sum(axis=0)
        np.divide(total, s, out=f2, where=still & (s > 0))
        out *= f2
    return out


def apply_limits(
    ink: np.ndarray,
    per_channel: np.ndarray,
    total: float,
    *,
    strategy: str = SCALE_ALL,
    protected: np.ndarray | None = None,
) -> np.ndarray:
    """Limite par canal puis limite totale, dans cet ordre."""
    return limit_total(
        limit_per_channel(ink, per_channel),
        total,
        strategy=strategy,
        protected=protected,
    )
