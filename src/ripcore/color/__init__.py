"""Chaîne couleur : séparation ICC, linéarisation, limitation d'encre, blanc."""

from .curves import (
    LUT_SIZE,
    Linearization,
    TransferCurve,
    apply_luts,
)
from .icc import (
    DEFAULT_GRID_3D,
    DEFAULT_GRID_4D,
    INTENTS,
    IccLut,
    build_icc_lut,
    naive_rgb_to_cmyk,
)
from .inklimit import (
    PRESERVE_BLACK,
    SCALE_ALL,
    STRATEGIES,
    apply_limits,
    limit_per_channel,
    limit_total,
)
from .white import erode, underbase, varnish

__all__ = [
    "DEFAULT_GRID_3D",
    "DEFAULT_GRID_4D",
    "INTENTS",
    "LUT_SIZE",
    "PRESERVE_BLACK",
    "SCALE_ALL",
    "STRATEGIES",
    "IccLut",
    "Linearization",
    "TransferCurve",
    "apply_limits",
    "apply_luts",
    "build_icc_lut",
    "erode",
    "limit_per_channel",
    "limit_total",
    "naive_rgb_to_cmyk",
    "underbase",
    "varnish",
]
