"""Conteneur `.prn` — lecture, écriture, contrôle.

Spécification : ``docs/prn-format.md``.
"""

from .header import HEADER_SIZE, MARKER, PrnHeader, bytes_per_line, detect_dialect
from .pack import pack_levels, pixels_per_byte, unpack_levels
from .reader import PrnProbe, PrnReader, probe
from .validate import ERROR, INFO, WARNING, Finding, Report, validate_prn
from .writer import PrnWriter, WriteStats, write_prn

__all__ = [
    "ERROR",
    "HEADER_SIZE",
    "INFO",
    "MARKER",
    "WARNING",
    "Finding",
    "PrnHeader",
    "PrnProbe",
    "PrnReader",
    "PrnWriter",
    "Report",
    "WriteStats",
    "bytes_per_line",
    "detect_dialect",
    "pack_levels",
    "pixels_per_byte",
    "probe",
    "unpack_levels",
    "validate_prn",
    "write_prn",
]
