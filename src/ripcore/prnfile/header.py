"""En-tête `.prn` générique (48 octets).

Référence normative : ``docs/prn-format.md``. Ce module est délibérément sans
dépendance à numpy : c'est la couche qui doit rester triviale à relire.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..errors import PrnFormatError

HEADER_SIZE = 48
MARKER = 0x00005555
MM_PER_INCH = 25.4
METRE_PER_INCH = 0.0254
REFERENCE_DPI = 720  # unité du champ 0x14

# Dialectes reconnus par PreviewPrn.dll, d'après les 4 premiers octets.
DIALECTS: dict[int, tuple[str, int]] = {
    0x7A646379: ("ycdz", 64),
    0x58485942: ("BYHX", 84),
    0x4D435441: ("ATCM", 84),
}
GENERIC = ("generic", HEADER_SIZE)

_STRUCT = struct.Struct("<IIIIIIfIIIII")
assert _STRUCT.size == HEADER_SIZE


def detect_dialect(first4: bytes) -> tuple[str, int]:
    """(nom, taille d'en-tête) à partir des 4 premiers octets d'un .prn."""
    if len(first4) < 4:
        raise PrnFormatError("fichier trop court pour contenir un magic")
    magic = struct.unpack_from("<I", first4)[0]
    return DIALECTS.get(magic, GENERIC)


def bytes_per_line(width_px: int, bits_per_pixel: int) -> int:
    """Octets par ligne **et par canal** (champ 0x0C)."""
    if width_px <= 0:
        raise PrnFormatError(f"largeur invalide : {width_px}")
    if bits_per_pixel not in (1, 2, 4, 8):
        raise PrnFormatError(f"bits_per_pixel={bits_per_pixel} non supporté")
    return (width_px * bits_per_pixel + 7) // 8


@dataclass(frozen=True, slots=True)
class PrnHeader:
    """En-tête générique. Les champs dérivés sont recalculés, jamais stockés."""

    dpi_x: int
    dpi_y: int
    bytes_per_line_per_channel: int
    lines: int
    channels: int
    bits_per_pixel: int
    pass_mode: int
    marker: int = MARKER

    def __post_init__(self) -> None:
        # Les deux seuls champs que le lecteur contrôle réellement.
        if self.dpi_x <= 0:
            raise PrnFormatError(f"dpi_x={self.dpi_x} : le lecteur exige != 0")
        if self.dpi_y <= 0:
            raise PrnFormatError(f"dpi_y={self.dpi_y} : le lecteur exige != 0")
        if self.bytes_per_line_per_channel <= 0:
            raise PrnFormatError(
                f"bytes_per_line_per_channel={self.bytes_per_line_per_channel}"
            )
        if self.lines <= 0:
            raise PrnFormatError(f"lines={self.lines}")
        if self.channels <= 0:
            raise PrnFormatError(f"channels={self.channels}")
        if self.bits_per_pixel not in (1, 2, 4, 8):
            raise PrnFormatError(f"bits_per_pixel={self.bits_per_pixel} non supporté")
        for name in ("dpi_x", "dpi_y", "bytes_per_line_per_channel", "lines",
                     "channels", "bits_per_pixel", "pass_mode", "marker"):
            v = getattr(self, name)
            if not 0 <= v <= 0xFFFFFFFF:
                raise PrnFormatError(f"{name}={v} déborde d'un u32")

    # -- géométrie dérivée ---------------------------------------------------

    @property
    def stride(self) -> int:
        """Octets par ligne, tous canaux confondus."""
        return self.bytes_per_line_per_channel * self.channels

    @property
    def body_size(self) -> int:
        return self.stride * self.lines

    @property
    def file_size(self) -> int:
        return HEADER_SIZE + self.body_size

    @property
    def width_px(self) -> int:
        """Largeur *paddée* : le fichier ne conserve pas la largeur utile.

        Si la largeur d'origine n'était pas un multiple de ``8 // bpp`` pixels,
        les derniers pixels de chaque ligne sont du remplissage à zéro. La
        largeur utile est consignée dans le manifeste du job.
        """
        return self.bytes_per_line_per_channel * 8 // self.bits_per_pixel

    @property
    def height_720(self) -> int:
        """Champ 0x14 : hauteur exprimée en unités 720 dpi."""
        return round(self.lines * REFERENCE_DPI / self.dpi_y)

    @property
    def height_m(self) -> float:
        """Champ 0x18 : hauteur en mètres (ignoré par le lecteur, écrit juste)."""
        return self.height_720 / REFERENCE_DPI * METRE_PER_INCH

    @property
    def width_mm(self) -> float:
        return self.width_px / self.dpi_x * MM_PER_INCH

    @property
    def height_mm(self) -> float:
        return self.lines / self.dpi_y * MM_PER_INCH

    # -- sérialisation -------------------------------------------------------

    def pack(self) -> bytes:
        return _STRUCT.pack(
            self.marker,
            self.dpi_x,
            self.dpi_y,
            self.bytes_per_line_per_channel,
            self.lines,
            self.height_720,
            _f32(self.height_m),
            self.channels,
            self.bits_per_pixel,
            self.pass_mode,
            0,
            0,
        )

    @classmethod
    def unpack(cls, buf: bytes) -> PrnHeader:
        if len(buf) < HEADER_SIZE:
            raise PrnFormatError(
                f"en-tête tronqué : {len(buf)} octets, {HEADER_SIZE} attendus"
            )
        (marker, dpi_x, dpi_y, bpl, lines, h720, hm, channels, bpp, pass_mode,
         _r0, _r1) = _STRUCT.unpack_from(buf)
        hdr = cls(
            dpi_x=dpi_x,
            dpi_y=dpi_y,
            bytes_per_line_per_channel=bpl,
            lines=lines,
            channels=channels,
            bits_per_pixel=bpp,
            pass_mode=pass_mode,
            marker=marker,
        )
        # Champs redondants : on ne les stocke pas, mais une divergence signale
        # soit un fichier d'un autre producteur, soit une mauvaise lecture.
        if h720 != hdr.height_720:
            raise PrnFormatError(
                f"champ 0x14 incohérent : {h720} lu, {hdr.height_720} attendu "
                f"(lines={lines}, dpi_y={dpi_y})"
            )
        if abs(hm - hdr.height_m) > 1e-6 * max(1.0, abs(hdr.height_m)):
            raise PrnFormatError(
                f"champ 0x18 incohérent : {hm!r} lu, {hdr.height_m!r} attendu"
            )
        return hdr

    def describe(self) -> str:
        return (
            f"{self.width_px}×{self.lines} px  "
            f"{self.width_mm:.1f}×{self.height_mm:.1f} mm  "
            f"{self.dpi_x}×{self.dpi_y} dpi  "
            f"{self.channels} canaux  {self.bits_per_pixel} bpp  "
            f"pass_mode={self.pass_mode}  "
            f"{self.file_size / 1e6:.1f} Mo"
        )


def _f32(x: float) -> float:
    """Arrondi au float32 le plus proche, pour que pack/unpack soit stable."""
    return struct.unpack("<f", struct.pack("<f", x))[0]
