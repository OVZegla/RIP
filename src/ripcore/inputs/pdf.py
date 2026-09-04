"""Interprétation PDF / PostScript par Ghostscript.

UltraPrint utilise Xpdf pour cette étape (`RIP.dll`) plus un Ghostscript en
second interpréteur. On garde Ghostscript seul : il est mieux tenu à jour, gère
les séparations et le CMJN natif, et évite d'avoir deux interpréteurs aux
comportements divergents.

Deux points d'attention :

* **Licence** — Ghostscript est en AGPL. Usage interne : sans conséquence. Si le
  RIP est un jour distribué à des tiers, il faut soit une licence commerciale
  Artifex, soit un autre interpréteur. Voir ``docs/licences.md``.
* **CMJN natif** — un PDF déjà séparé en CMJN doit être rendu en CMJN
  (``tiff32nc``), surtout pas transité par du RGB : un aller-retour détruit la
  génération de noir choisie par le prépresse.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ..errors import RipError

GS_CANDIDATES = ("gs", "gswin64c", "gswin32c", "ghostscript")

# tiff24nc = RGB 8 bits ; tiff32nc = CMJN 8 bits.
DEVICE_BY_MODE = {"RGB": "tiff24nc", "CMYK": "tiff32nc", "L": "tiffgray"}


def find_ghostscript() -> str:
    for name in GS_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    raise RipError(
        "Ghostscript introuvable (cherché : "
        + ", ".join(GS_CANDIDATES)
        + "). Installez-le (apt install ghostscript) ou fournissez une image "
        "matricielle déjà rendue."
    )


def render_pdf(
    path: str | Path,
    out_dir: str | Path | None = None,
    *,
    dpi_x: int,
    dpi_y: int,
    mode: str = "CMYK",
    page: int = 1,
    gs_binary: str | None = None,
    timeout: int = 3600,
) -> Path:
    """Rend une page en TIFF à la résolution machine. Renvoie le chemin produit.

    Le rendu se fait directement en dpi non carrés : c'est Ghostscript qui
    applique le rapport d'aspect, ce qui évite un rééchantillonnage
    supplémentaire de notre côté.
    """
    src = Path(path)
    if not src.is_file():
        raise RipError(f"fichier source introuvable : {src}")
    if mode not in DEVICE_BY_MODE:
        raise RipError(
            f"mode de rendu inconnu : {mode!r} ({' | '.join(DEVICE_BY_MODE)})"
        )
    if page < 1:
        raise RipError(f"numéro de page invalide : {page}")

    gs = gs_binary or find_ghostscript()
    out_dir = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="ripcore-"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{src.stem}-p{page}-{dpi_x}x{dpi_y}.tif"

    cmd = [
        gs,
        "-dSAFER",
        "-dBATCH",
        "-dNOPAUSE",
        "-dQUIET",
        f"-sDEVICE={DEVICE_BY_MODE[mode]}",
        f"-r{dpi_x}x{dpi_y}",
        f"-dFirstPage={page}",
        f"-dLastPage={page}",
        "-dTextAlphaBits=4",
        "-dGraphicsAlphaBits=4",
        "-dUseCropBox",
        f"-sOutputFile={out}",
        str(src),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired:
        raise RipError(
            f"Ghostscript n'a pas terminé en {timeout} s sur {src.name}"
        ) from None
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
        raise RipError(
            f"Ghostscript a échoué sur {src.name} (code {proc.returncode})\n{detail}"
        )
    if not out.is_file():
        raise RipError(f"Ghostscript n'a produit aucun fichier pour {src.name}")
    return out
