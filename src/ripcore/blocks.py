"""Statistiques par blocs sur un raster tramé.

La limitation d'encre est une contrainte de **volume par unité de surface**, pas
une contrainte par pixel : après tramage, un pixel isolé portant une grosse
goutte sur les cinq canaux est parfaitement normal. Ce qui compte, et ce qui
coule sur le support, c'est la moyenne locale.

On mesure donc sur des blocs. À 720 × 900 dpi, un bloc de 16 × 16 pixels couvre
≈ 0,56 × 0,45 mm — l'ordre de grandeur sur lequel l'encre s'étale et se
polymérise réellement.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import numpy as np

DEFAULT_BLOCK = 16


def block_means(
    bands: Iterable[np.ndarray], densities: np.ndarray, block: int = DEFAULT_BLOCK
) -> Iterator[np.ndarray]:
    """Convertit un flux de bandes de niveaux en moyennes de densité par bloc.

    Les lignes qui ne complètent pas un bloc sont reportées sur la bande
    suivante ; la dernière bande incomplète est traitée sur sa hauteur réelle,
    de sorte qu'aucune ligne n'échappe au contrôle.
    """
    if block < 1:
        raise ValueError("block >= 1 attendu")
    d = np.asarray(densities, dtype=np.float32)
    carry: np.ndarray | None = None

    for band in bands:
        stacked = band if carry is None else np.concatenate([carry, band], axis=1)
        full = (stacked.shape[1] // block) * block
        if full:
            yield _reduce(stacked[:, :full], d, block)
        carry = stacked[:, full:] if stacked.shape[1] > full else None

    if carry is not None and carry.shape[1]:
        yield _reduce(carry, d, carry.shape[1], width_block=block)


def _reduce(
    chunk: np.ndarray, densities: np.ndarray, block: int, width_block: int | None = None
) -> np.ndarray:
    """(C, h, w) niveaux → (C, h/block, w/wblock) moyennes de densité."""
    wb = width_block or block
    c, h, w = chunk.shape
    usable_w = (w // wb) * wb
    if usable_w == 0:  # image plus étroite qu'un bloc : un seul bloc partiel
        usable_w, wb = w, w
    dens = densities[chunk[:, :, :usable_w]]
    return dens.reshape(c, h // block, block, usable_w // wb, wb).mean(axis=(2, 4))
