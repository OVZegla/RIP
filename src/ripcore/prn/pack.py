"""Empaquetage / dépaquetage des niveaux de goutte dans les plans .prn.

Convention **MSB d'abord** confirmée par les masques de `ipht.dll`
(`{0xFF,0x3F,0x0F,0x03}` en 2 bits) : le pixel 0 occupe les bits de poids fort
du premier octet.
"""

from __future__ import annotations

import numpy as np

from ..errors import PrnFormatError

_SUPPORTED_BPP = (1, 2, 4, 8)


def pixels_per_byte(bits_per_pixel: int) -> int:
    if bits_per_pixel not in _SUPPORTED_BPP:
        raise PrnFormatError(f"bits_per_pixel={bits_per_pixel} non supporté")
    return 8 // bits_per_pixel


def pack_levels(levels: np.ndarray, bits_per_pixel: int) -> np.ndarray:
    """(..., W) niveaux uint8 → (..., ceil(W·bpp/8)) octets, MSB d'abord.

    Les pixels de remplissage en fin de ligne sont à zéro.
    """
    ppb = pixels_per_byte(bits_per_pixel)
    a = np.asarray(levels)
    if a.dtype != np.uint8:
        raise PrnFormatError(f"niveaux attendus en uint8, reçu {a.dtype}")
    max_level = (1 << bits_per_pixel) - 1
    if a.size and int(a.max()) > max_level:
        raise PrnFormatError(
            f"niveau {int(a.max())} hors domaine pour {bits_per_pixel} bpp "
            f"(max {max_level})"
        )

    width = a.shape[-1]
    pad = (-width) % ppb
    if pad:
        a = np.pad(a, [(0, 0)] * (a.ndim - 1) + [(0, pad)], mode="constant")

    grouped = a.reshape(*a.shape[:-1], a.shape[-1] // ppb, ppb)
    out = np.zeros(grouped.shape[:-1], dtype=np.uint8)
    for i in range(ppb):
        shift = (ppb - 1 - i) * bits_per_pixel
        out |= grouped[..., i] << shift
    return out


def unpack_levels(packed: np.ndarray, bits_per_pixel: int, width: int) -> np.ndarray:
    """Inverse de :func:`pack_levels`, tronqué à ``width`` pixels."""
    ppb = pixels_per_byte(bits_per_pixel)
    a = np.asarray(packed, dtype=np.uint8)
    mask = np.uint8((1 << bits_per_pixel) - 1)
    out = np.empty((*a.shape, ppb), dtype=np.uint8)
    for i in range(ppb):
        shift = (ppb - 1 - i) * bits_per_pixel
        out[..., i] = (a >> shift) & mask
    flat = out.reshape(*a.shape[:-1], a.shape[-1] * ppb)
    if width > flat.shape[-1]:
        raise PrnFormatError(
            f"largeur demandée {width} > {flat.shape[-1]} pixels disponibles"
        )
    return flat[..., :width]
