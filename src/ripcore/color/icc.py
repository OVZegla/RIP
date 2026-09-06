"""Gestion couleur ICC, par table de correspondance interpolée.

Pourquoi une LUT plutôt qu'une transformation ICC pixel à pixel : Pillow (donc
lcms2, tel qu'exposé ici) ne travaille en CMJN qu'en 8 bits. Transformer chaque
pixel donnerait des séparations quantifiées sur 256 pas, et les courbes de
linéarisation appliquées ensuite étireraient ces pas en marches visibles dans
les dégradés doux.

On échantillonne donc la transformation une fois sur une grille, puis on
interpole en flottant. C'est exactement le fonctionnement interne d'un profil
ICC (tables A2B/B2A + interpolation), et la sortie est continue.

Les profils utilisés sont ceux livrés avec la machine
(`ICC Profile/Output/Epson-W5113/…`, un par résolution × hauteur de tête).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..errors import RipError

DEFAULT_GRID_3D = 33
DEFAULT_GRID_4D = 17
_CHUNK_PIXELS = 1 << 20  # borne la mémoire des gathers multilinéaires

INTENTS = {
    "perceptual": 0,
    "relative": 1,
    "relative-colorimetric": 1,
    "saturation": 2,
    "absolute": 3,
    "absolute-colorimetric": 3,
}

_MODE_CHANNELS = {"RGB": 3, "CMYK": 4, "L": 1}


def _require_pillow():
    try:
        from PIL import Image, ImageCms  # noqa: PLC0415
    except ImportError:  # pragma: no cover - dépend de l'installation
        raise RipError(
            "la gestion couleur ICC requiert Pillow : pip install 'ripcore[images]'"
        ) from None
    return Image, ImageCms


@dataclass(frozen=True, slots=True)
class IccLut:
    """Transformation échantillonnée : (Ci,…) 0..1 → (Co,…) 0..1."""

    table: np.ndarray  # (grid**Ci, Co) float32
    grid: int
    in_channels: int
    out_channels: int
    label: str = ""

    def __post_init__(self) -> None:
        expected = self.grid**self.in_channels
        if self.table.shape != (expected, self.out_channels):
            raise RipError(
                f"table LUT {self.table.shape}, "
                f"({expected}, {self.out_channels}) attendu"
            )

    def apply(self, src: np.ndarray) -> np.ndarray:
        """(Ci, H, W) → (Co, H, W), interpolation multilinéaire en flottant."""
        a = np.clip(np.asarray(src, dtype=np.float32), 0.0, 1.0)
        if a.ndim != 3 or a.shape[0] != self.in_channels:
            raise RipError(
                f"entrée ({self.in_channels}, H, W) attendue, reçu {a.shape}"
            )
        _, h, w = a.shape
        flat = a.reshape(self.in_channels, -1)
        out = np.empty((self.out_channels, flat.shape[1]), dtype=np.float32)
        for start in range(0, flat.shape[1], _CHUNK_PIXELS):
            sl = slice(start, start + _CHUNK_PIXELS)
            out[:, sl] = self._interpolate(flat[:, sl])
        return out.reshape(self.out_channels, h, w)

    def _interpolate(self, pts: np.ndarray) -> np.ndarray:
        g = self.grid
        pos = pts * (g - 1)
        i0 = np.floor(pos).astype(np.int32)
        np.clip(i0, 0, g - 2, out=i0)
        frac = pos - i0

        strides = np.array(
            [g ** (self.in_channels - 1 - i) for i in range(self.in_channels)],
            dtype=np.int64,
        )
        acc = np.zeros((pts.shape[1], self.out_channels), dtype=np.float32)
        for corner in itertools.product((0, 1), repeat=self.in_channels):
            weight = np.ones(pts.shape[1], dtype=np.float32)
            index = np.zeros(pts.shape[1], dtype=np.int64)
            for axis, bit in enumerate(corner):
                weight *= frac[axis] if bit else (1.0 - frac[axis])
                index += (i0[axis] + bit) * strides[axis]
            acc += self.table[index] * weight[:, None]
        return acc.T


def build_icc_lut(
    input_profile: str | Path,
    output_profile: str | Path,
    *,
    intent: str = "perceptual",
    in_mode: str = "RGB",
    out_mode: str = "CMYK",
    grid: int | None = None,
    black_point_compensation: bool = True,
) -> IccLut:
    """Échantillonne une transformation ICC sur une grille régulière."""
    Image, ImageCms = _require_pillow()

    if in_mode not in _MODE_CHANNELS or out_mode not in _MODE_CHANNELS:
        raise RipError(f"modes ICC non supportés : {in_mode} → {out_mode}")
    ci = _MODE_CHANNELS[in_mode]
    co = _MODE_CHANNELS[out_mode]
    if grid is None:
        # Une entrée à un seul canal est une simple rampe : on l'échantillonne
        # finement, 17 points laisseraient des marches dans un dégradé de gris.
        grid = {1: 256, 3: DEFAULT_GRID_3D}.get(ci, DEFAULT_GRID_4D)
    try:
        intent_id = INTENTS[intent]
    except KeyError:
        raise RipError(
            f"intention de rendu inconnue : {intent!r} "
            f"({' | '.join(sorted(set(INTENTS)))})"
        ) from None

    in_path, out_path = Path(input_profile), Path(output_profile)
    for p in (in_path, out_path):
        if not p.is_file():
            raise RipError(f"profil ICC introuvable : {p}")

    axes = np.linspace(0, 255, grid).round().astype(np.uint8)
    mesh = np.stack(np.meshgrid(*([axes] * ci), indexing="ij"), axis=-1)
    samples = mesh.reshape(-1, ci)

    src = Image.frombytes(
        in_mode, (samples.shape[0], 1), np.ascontiguousarray(samples).tobytes()
    )
    flags = 0
    if black_point_compensation:
        flags |= getattr(ImageCms, "FLAGS", {}).get("BLACKPOINTCOMPENSATION", 0x2000)
    try:
        transform = ImageCms.buildTransform(
            ImageCms.getOpenProfile(str(in_path)),
            ImageCms.getOpenProfile(str(out_path)),
            in_mode,
            out_mode,
            renderingIntent=intent_id,
            flags=flags,
        )
        dst = ImageCms.applyTransform(src, transform)
    except Exception as exc:  # lcms remonte des erreurs variées
        raise RipError(
            f"transformation ICC {in_path.name} → {out_path.name} impossible : {exc}"
        ) from exc

    table = (
        np.frombuffer(dst.tobytes(), dtype=np.uint8).reshape(-1, co).astype(np.float32)
        / 255.0
    )
    return IccLut(
        table=np.ascontiguousarray(table),
        grid=grid,
        in_channels=ci,
        out_channels=co,
        label=f"{in_path.stem}→{out_path.stem}/{intent}",
    )


def naive_rgb_to_cmyk(rgb: np.ndarray, gcr: float = 0.8) -> np.ndarray:
    """Séparation de secours, **non colorimétrique**.

    À n'utiliser que pour les mires et le développement, jamais pour une
    production : sans profil ICC de sortie, les couleurs ne sont pas gérées.
    ``gcr`` règle la part de gris remplacée par du noir.
    """
    a = np.clip(np.asarray(rgb, dtype=np.float32), 0.0, 1.0)
    if a.shape[0] != 3:
        raise RipError(f"entrée RGB (3, H, W) attendue, reçu {a.shape}")
    cmy = 1.0 - a
    k = cmy.min(axis=0) * np.float32(np.clip(gcr, 0.0, 1.0))
    denom = np.maximum(1.0 - k, 1e-6)
    cmy = np.clip((cmy - k) / denom, 0.0, 1.0)
    return np.concatenate([cmy, k[None]], axis=0).astype(np.float32)
