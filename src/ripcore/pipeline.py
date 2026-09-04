"""Orchestration d'un job : source → `.prn`.

L'enchaînement reprend celui de `riper.dll` (§3 du dossier RIP), à ceci près que
les étapes 6 (géométrie) et 7 (écriture) sont chez nous, et que le weave reste
à BetterPrinter :

    source → [rendu] → [ICC] → [linéarisation] → [limite d'encre]
           → [blanc / vernis] → [tramage] → [.prn]

Tout est traité **par bandes**. Un mural 3 m en 720 × 900 dpi sur 5 canaux fait
plusieurs gigaoctets : rien de tout cela ne tient en mémoire, et un RIP qui
sature la machine au milieu d'un job est un RIP qui ne sert à rien.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import __version__
from .color import icc as icc_mod
from .color.curves import Linearization, apply_luts
from .color.inklimit import SCALE_ALL, limit_per_channel, limit_total
from .color.white import underbase, varnish
from .errors import RipError
from .halftone.engines import Halftoner, make_halftoner
from .inputs.source import MM_PER_INCH, SourceImage, fit_geometry, load_source
from .prn.writer import PrnWriter
from .profiles import (
    ROLE_PROCESS,
    ROLE_VARNISH,
    ROLE_WHITE,
    MediaProfile,
    PrinterProfile,
)

DEFAULT_BAND_LINES = 512
_ICC_MODE_BY_SOURCE = {"RGB": "RGB", "CMYK": "CMYK", "L": "L"}
_CMYK_ORDER = ("C", "M", "Y", "K")


@dataclass(slots=True)
class JobSpec:
    """Tout ce qui définit un tirage. Sérialisé tel quel dans le manifeste."""

    source: Path
    output: Path
    printer: PrinterProfile
    media: MediaProfile
    dpi_x: int = 720
    dpi_y: int = 900
    width_mm: float | None = None
    height_mm: float | None = None
    halftone: str = "bluenoise"
    ink_limit_strategy: str = SCALE_ALL
    rotate: int = 0  # 0, 90, 180, 270 — sens horaire
    mirror: bool = False
    band_lines: int = DEFAULT_BAND_LINES
    resample: str = "lanczos"
    page: int = 1

    def __post_init__(self) -> None:
        if self.rotate not in (0, 90, 180, 270):
            raise RipError(f"rotation {self.rotate}° non supportée (0, 90, 180, 270)")
        if self.band_lines < 1:
            raise RipError(f"band_lines={self.band_lines}")


@dataclass(slots=True)
class JobResult:
    output: Path
    width_px: int
    height_px: int
    width_mm: float
    height_mm: float
    channels: tuple[str, ...]
    coverage: dict[str, float]
    halftone: str
    icc: str
    seconds: float
    warnings: list[str] = field(default_factory=list)
    manifest: Path | None = None

    def describe(self) -> str:
        cov = "  ".join(f"{k}={v * 100:.1f}%" for k, v in self.coverage.items())
        return (
            f"{self.output.name}\n"
            f"  {self.width_px}×{self.height_px} px  "
            f"{self.width_mm:.1f}×{self.height_mm:.1f} mm\n"
            f"  tramage {self.halftone}  |  couleur {self.icc}\n"
            f"  encre : {cov}\n"
            f"  {self.seconds:.1f} s"
        )


def _orient(img: SourceImage, rotate: int, mirror: bool) -> SourceImage:
    """Rotation / miroir, appliqués une fois pour toutes avant le traitement."""
    data, alpha = img.data, img.alpha
    if rotate:
        k = {90: 3, 180: 2, 270: 1}[rotate]  # np.rot90 tourne dans le sens direct
        data = np.rot90(data, k=k, axes=(1, 2))
        if alpha is not None:
            alpha = np.rot90(alpha, k=k, axes=(0, 1))
    if mirror:
        data = data[:, :, ::-1]
        if alpha is not None:
            alpha = alpha[:, ::-1]
    return SourceImage(
        data=np.ascontiguousarray(data),
        mode=img.mode,
        alpha=None if alpha is None else np.ascontiguousarray(alpha),
        source=img.source,
        embedded_icc=img.embedded_icc,
    )


def _build_color_transform(
    spec: JobSpec, img: SourceImage
) -> tuple[Callable[[np.ndarray], np.ndarray], str]:
    """Renvoie (fonction de séparation, libellé) pour le manifeste."""
    media = spec.media
    if media.icc_output is None:
        if img.mode == "CMYK":
            return (lambda a: a), "aucun profil (CMJN source passé tel quel)"
        return (
            icc_mod.naive_rgb_to_cmyk,
            "SÉPARATION NAÏVE — aucun profil ICC de sortie",
        )

    in_profile = {
        "RGB": media.icc_input_rgb,
        "CMYK": media.icc_input_cmyk,
        "L": media.icc_input_rgb,
    }.get(img.mode)
    if in_profile is None:
        raise RipError(
            f"source en {img.mode} mais le profil média {media.name!r} ne déclare "
            f"pas de profil d'entrée pour cet espace "
            f"(icc_input_rgb / icc_input_cmyk)"
        )
    lut = icc_mod.build_icc_lut(
        in_profile,
        media.icc_output,
        intent=media.rendering_intent,
        in_mode=_ICC_MODE_BY_SOURCE[img.mode],
        out_mode="CMYK",
    )
    return lut.apply, lut.label


def _assemble(
    profile: PrinterProfile,
    cmyk: np.ndarray,
    media: MediaProfile,
    alpha: np.ndarray | None,
) -> np.ndarray:
    """Répartit le CMJN séparé sur les canaux du profil, génère blanc et vernis."""
    h, w = cmyk.shape[1:]
    out = np.zeros((profile.n_channels, h, w), dtype=np.float32)
    for i, ch in enumerate(profile.channels):
        if ch.role == ROLE_PROCESS:
            try:
                out[i] = cmyk[_CMYK_ORDER.index(ch.name)]
            except ValueError:
                raise RipError(
                    f"canal process {ch.name!r} : la séparation produit du CMJN, "
                    f"un canal nommé C, M, Y ou K est attendu. Pour une encre "
                    f"supplémentaire, déclarez le rôle 'spot'."
                ) from None
        elif ch.role == ROLE_WHITE:
            if media.white_underbase:
                out[i] = underbase(
                    cmyk,
                    density=media.white_density,
                    choke_px=media.white_choke_px,
                    alpha=alpha,
                )
        elif ch.role == ROLE_VARNISH:
            out[i] = varnish(cmyk, mode="flood", density=1.0)
        # ROLE_SPOT : laissé à zéro tant qu'aucune source de ton direct n'est
        # branchée — mieux vaut un canal vide qu'une encre posée au hasard.
    return out


def run_job(
    spec: JobSpec,
    *,
    progress: Callable[[int, int], None] | None = None,
    halftoner: Halftoner | None = None,
) -> JobResult:
    """Exécute le job et écrit le `.prn`. Ne parle jamais à la machine."""
    started = time.monotonic()
    profile, media = spec.printer, spec.media
    warnings = list(profile.warnings())

    pass_mode = profile.pass_mode(spec.dpi_y)  # lève tôt si la résolution est inconnue

    # -- géométrie -----------------------------------------------------------
    from PIL import Image  # noqa: PLC0415 — import tardif : Pillow est optionnel

    with Image.open(spec.source) as probe_img:
        src_w, src_h = probe_img.size
        dpi_info = probe_img.info.get("dpi")
    src_dpi_x = float(dpi_info[0]) if dpi_info else None
    src_dpi_y = float(dpi_info[1]) if dpi_info else None
    if spec.rotate in (90, 270):
        src_w, src_h = src_h, src_w
        src_dpi_x, src_dpi_y = src_dpi_y, src_dpi_x

    width_px, height_px, width_mm, height_mm = fit_geometry(
        src_w,
        src_h,
        dpi_x=spec.dpi_x,
        dpi_y=spec.dpi_y,
        src_dpi_x=src_dpi_x,
        src_dpi_y=src_dpi_y,
        width_mm=spec.width_mm,
        height_mm=spec.height_mm,
    )
    if profile.max_width_mm and width_mm > profile.max_width_mm:
        raise RipError(
            f"largeur demandée {width_mm:.1f} mm > course machine "
            f"{profile.max_width_mm:.1f} mm"
        )

    # -- chargement ----------------------------------------------------------
    load_w, load_h = (
        (height_px, width_px) if spec.rotate in (90, 270) else (width_px, height_px)
    )
    img = _orient(
        load_source(spec.source, width_px=load_w, height_px=load_h,
                    resample=spec.resample),
        spec.rotate,
        spec.mirror,
    )
    if img.data.shape[1:] != (height_px, width_px):
        raise RipError(
            f"géométrie incohérente après orientation : "
            f"{img.data.shape[1:]}, ({height_px}, {width_px}) attendu"
        )

    separate, icc_label = _build_color_transform(spec, img)
    if icc_label.startswith("SÉPARATION NAÏVE"):
        warnings.append(
            "aucun profil ICC de sortie : les couleurs ne sont pas gérées, "
            "réservez ce tirage aux essais"
        )

    lin = (
        Linearization.load(media.linearization)
        if media.linearization
        else Linearization.identity(profile.channel_names)
    )
    if lin.is_identity:
        warnings.append(
            "aucune linéarisation : la réponse de la machine n'est pas corrigée "
            "(mire « lin-wedge » puis « rip calibrate lin »)"
        )
    # Une linéarisation identité coûterait une interpolation par canal pour ne
    # rien changer : on la court-circuite.
    luts = None if lin.is_identity else lin.luts(profile.channel_names)

    limits = np.array(
        [profile.limit_for(c) for c in profile.channel_names], dtype=np.float32
    )
    # La limite totale porte sur les canaux process. Le blanc est une couche
    # distincte : le comptabiliser dans le TAC ferait maigrir les couleurs à
    # chaque fois qu'une sous-couche est posée, ce qui n'a pas de sens.
    process_mask = profile.process_mask
    total_limit = (
        media.ink_limit_total
        if media.ink_limit_total is not None
        else profile.ink_limit_total
    )
    total_all_limit = profile.ink_limit_total_all
    protected = np.array(
        [c.name == "K" and c.role == ROLE_PROCESS for c in profile.channels],
        dtype=bool,
    )[process_mask]

    ht = halftoner or make_halftoner(
        spec.halftone,
        np.asarray(profile.drop_levels.densities, dtype=np.float32),
        profile.n_channels,
    )
    ht.reset()

    # -- traitement par bandes ----------------------------------------------
    spec.output.parent.mkdir(parents=True, exist_ok=True)
    with PrnWriter(
        spec.output,
        dpi_x=spec.dpi_x,
        dpi_y=spec.dpi_y,
        width_px=width_px,
        channels=profile.n_channels,
        bits_per_pixel=profile.bits_per_pixel,
        pass_mode=pass_mode,
    ) as writer:
        for y0 in range(0, height_px, spec.band_lines):
            y1 = min(y0 + spec.band_lines, height_px)
            band = img.data[:, y0:y1]
            alpha = img.alpha[y0:y1] if img.alpha is not None else None

            cmyk = separate(band)
            ink = _assemble(profile, cmyk, media, alpha)
            if luts is not None:
                ink = apply_luts(ink, luts)
            ink = limit_per_channel(ink, limits)
            ink[process_mask] = limit_total(
                ink[process_mask],
                total_limit,
                strategy=spec.ink_limit_strategy,
                protected=protected,
            )
            if total_all_limit is not None:
                ink = limit_total(ink, total_all_limit, strategy=SCALE_ALL)
            writer.write_block(ht.process(ink, y0))
            if progress is not None:
                progress(y1, height_px)

    header = writer.header
    coverage = dict(
        zip(
            profile.channel_names,
            writer.stats.coverage(profile.drop_levels.densities).tolist(),
        )
    )

    result = JobResult(
        output=spec.output,
        width_px=width_px,
        height_px=height_px,
        width_mm=width_mm,
        height_mm=height_mm,
        channels=profile.channel_names,
        coverage=coverage,
        halftone=ht.name,
        icc=icc_label,
        seconds=time.monotonic() - started,
        warnings=warnings,
    )
    result.manifest = write_manifest(spec, result, header)
    return result


def write_manifest(spec: JobSpec, result: JobResult, header) -> Path:
    """Manifeste JSON à côté du `.prn`.

    Il porte la **largeur utile en pixels**, que le format `.prn` ne conserve
    pas : sans lui, impossible de savoir si les derniers pixels d'une ligne sont
    de l'image ou du remplissage.
    """
    path = result.output.with_suffix(result.output.suffix + ".json")
    payload = {
        "format": "ripcore-manifest-1",
        "ripcore_version": __version__,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": str(spec.source),
        "output": str(result.output),
        "geometry": {
            "width_px": result.width_px,
            "padded_width_px": header.width_px,
            "height_px": result.height_px,
            "width_mm": round(result.width_mm, 3),
            "height_mm": round(result.height_mm, 3),
            "dpi_x": spec.dpi_x,
            "dpi_y": spec.dpi_y,
            "rotate": spec.rotate,
            "mirror": spec.mirror,
        },
        "prn": {
            "bytes_per_line_per_channel": header.bytes_per_line_per_channel,
            "lines": header.lines,
            "channels": header.channels,
            "bits_per_pixel": header.bits_per_pixel,
            "pass_mode": header.pass_mode,
            "file_size": header.file_size,
        },
        "printer": {
            "name": spec.printer.name,
            "profile": str(spec.printer.source) if spec.printer.source else None,
            "channels": list(result.channels),
            "channel_order_verified": spec.printer.channel_order_verified,
            "drop_levels": list(spec.printer.drop_levels.densities),
            "drop_levels_calibrated": spec.printer.drop_levels.calibrated,
        },
        "media": {
            "name": spec.media.name,
            "profile": str(spec.media.source) if spec.media.source else None,
            "icc": result.icc,
            "linearization": (
                str(spec.media.linearization) if spec.media.linearization else None
            ),
        },
        "halftone": result.halftone,
        "coverage": {k: round(v, 5) for k, v in result.coverage.items()},
        "warnings": result.warnings,
        "seconds": round(result.seconds, 2),
    }
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def write_target_prn(
    target, profile: PrinterProfile, output: Path
) -> tuple[Path, object]:
    """Écrit une mire (niveaux déjà calculés) en `.prn`."""
    pass_mode = profile.pass_mode(target.dpi_y)
    with PrnWriter(
        output,
        dpi_x=target.dpi_x,
        dpi_y=target.dpi_y,
        width_px=target.levels.shape[2],
        channels=profile.n_channels,
        bits_per_pixel=profile.bits_per_pixel,
        pass_mode=pass_mode,
    ) as w:
        w.write_block(target.levels)
    return output, w.header


__all__ = [
    "DEFAULT_BAND_LINES",
    "MM_PER_INCH",
    "JobResult",
    "JobSpec",
    "run_job",
    "write_manifest",
    "write_target_prn",
]
