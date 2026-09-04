"""Tramage : contone → niveaux de goutte."""

from .bluenoise import generate_mask, load_mask, thresholds
from .engines import (
    FLOYD_STEINBERG,
    JARVIS,
    KERNELS,
    STUCKI,
    BlueNoiseHalftoner,
    ErrorDiffusionHalftoner,
    Halftoner,
    make_halftoner,
)
from .levels import density_of, quantize_nearest, quantize_ordered

__all__ = [
    "FLOYD_STEINBERG",
    "JARVIS",
    "KERNELS",
    "STUCKI",
    "BlueNoiseHalftoner",
    "ErrorDiffusionHalftoner",
    "Halftoner",
    "density_of",
    "generate_mask",
    "load_mask",
    "make_halftoner",
    "quantize_nearest",
    "quantize_ordered",
    "thresholds",
]
