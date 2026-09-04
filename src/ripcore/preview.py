"""Aperçu visuel d'un `.prn`.

Le meilleur filet de sécurité avant un tirage grand format : regarder ce qu'on
s'apprête à imprimer. Un canal inversé, un blanc en négatif, une image
retournée — ça se voit en une seconde sur un aperçu et ça coûte deux heures de
support et d'encre sinon.

Le rendu est **indicatif** : simulation soustractive simple, pas une épreuve
colorimétrique. Il sert à valider la structure, pas la couleur.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .errors import RipError
from .prnfile.reader import PrnReader
from .profiles import ROLE_VARNISH, ROLE_WHITE, PrinterProfile

# Couleurs d'encre approchées, en sRGB linéaire de travail.
INK_RGB = {
    "C": (0.05, 0.60, 0.85),
    "M": (0.88, 0.10, 0.45),
    "Y": (0.98, 0.88, 0.05),
    "K": (0.08, 0.08, 0.08),
    "LC": (0.55, 0.80, 0.93),
    "LM": (0.94, 0.60, 0.75),
    "W": (1.00, 1.00, 1.00),
    "V": (0.92, 0.92, 0.92),
}
DEFAULT_INK = (0.5, 0.5, 0.5)
PAPER = (0.62, 0.62, 0.64)  # support neutre non blanc : le blanc doit se voir


def render_preview(
    prn_path: str | Path,
    out_path: str | Path,
    profile: PrinterProfile,
    *,
    max_side: int = 1600,
    show_white: bool = True,
) -> Path:
    """Écrit un PNG d'aperçu. Le raster est lu par bandes et sous-échantillonné."""
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        raise RipError(
            "l'aperçu requiert Pillow : pip install 'ripcore[images]'"
        ) from None

    reader = PrnReader(prn_path)
    hdr = reader.header
    if hdr.channels != profile.n_channels:
        raise RipError(
            f"{hdr.channels} canaux dans le fichier, {profile.n_channels} au profil"
        )

    step = max(1, int(np.ceil(max(hdr.width_px, hdr.lines) / max_side)))
    densities = np.asarray(profile.drop_levels.densities, dtype=np.float32)

    # Réduction par moyenne de blocs step×step : on conserve la densité moyenne,
    # ce qui rend visible la trame sans crénelage.
    out_w = hdr.width_px // step
    rows: list[np.ndarray] = []
    carry: list[np.ndarray] = []
    band_lines = max(step, (512 // step) * step)

    for band in reader.bands(lines_per_band=band_lines):
        carry.append(band)
        stacked = np.concatenate(carry, axis=1) if len(carry) > 1 else carry[0]
        usable = (stacked.shape[1] // step) * step
        if usable == 0:
            carry = [stacked]
            continue
        chunk = stacked[:, :usable, : out_w * step]
        dens = densities[chunk]
        reduced = dens.reshape(
            dens.shape[0], usable // step, step, out_w, step
        ).mean(axis=(2, 4))
        rows.append(reduced)
        carry = [stacked[:, usable:]] if stacked.shape[1] > usable else []

    if not rows:
        raise RipError("aperçu impossible : image plus petite que le pas de réduction")
    ink = np.concatenate(rows, axis=1)  # (C, h, w) densités moyennes 0..1

    rgb = np.empty((*ink.shape[1:], 3), dtype=np.float32)
    rgb[:] = PAPER

    # Le blanc d'abord (c'est une sous-couche), puis les couleurs par-dessus.
    order = sorted(
        range(profile.n_channels),
        key=lambda i: 0 if profile.channels[i].role == ROLE_WHITE else 1,
    )
    for i in order:
        ch = profile.channels[i]
        if ch.role == ROLE_VARNISH:
            continue  # invisible sur un aperçu plat
        if ch.role == ROLE_WHITE and not show_white:
            continue
        color = np.asarray(INK_RGB.get(ch.name, DEFAULT_INK), dtype=np.float32)
        a = ink[i][..., None]
        rgb = rgb * (1.0 - a) + color * a

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray((np.clip(rgb, 0, 1) * 255).round().astype(np.uint8), "RGB")
    # Le fichier est en pixels machine non carrés : on rétablit le rapport réel.
    # Un pixel machine est plus haut que large quand dpi_y > dpi_x : on élargit
    # l'aperçu du même rapport pour retrouver les proportions réelles.
    aspect = (hdr.dpi_y / hdr.dpi_x) if hdr.dpi_x else 1.0
    if abs(aspect - 1.0) > 0.01:
        img = img.resize(
            (max(1, round(img.width * aspect)), img.height), Image.Resampling.LANCZOS
        )
    img.save(out)
    return out
