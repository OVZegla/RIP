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
from .inputs import photoshop
from .inputs.source import (
    MM_PER_INCH,
    SourceImage,
    fit_size_mm,
    load_source,
    mesurer,
    pixels_for,
)
from .panneaux import verifier_hauteur
from .prnfile.writer import PrnWriter
from .profiles import (
    ROLE_PROCESS,
    ROLE_VARNISH,
    ROLE_WHITE,
    MediaProfile,
    PrinterProfile,
)

DEFAULT_BAND_LINES = 512
# Mémoire visée par bande. Une fresque murale fait plusieurs dizaines de milliers
# de pixels de large : une hauteur de bande fixe ferait exploser la mémoire sur
# les grands formats et la gaspillerait sur les petits.
BUDGET_BANDE_OCTETS = 96 << 20
MIN_BAND_LINES = 16
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
    # Couches nommées trouvées dans le fichier source → encre employée, ou ""
    # quand la couche n'a pas été reconnue et a donc été ignorée.
    spot_channels: dict[str, str] = field(default_factory=dict)

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


def _build_color_transform(
    spec: JobSpec, img: SourceImage
) -> tuple[Callable[[np.ndarray], np.ndarray], str]:
    """Renvoie (fonction de séparation, libellé) pour le manifeste."""
    media = spec.media
    if media.icc_output is None:
        if img.mode == "CMYK":
            return (lambda a: a), "aucun profil (CMJN source passé tel quel)"
        if img.mode == "L":
            # Un gris est un RGB neutre : on le développe plutôt que d'ajouter
            # un second chemin de séparation à maintenir.
            def _gris(a: np.ndarray) -> np.ndarray:
                return icc_mod.naive_rgb_to_cmyk(np.repeat(a, 3, axis=0))

            return _gris, "SÉPARATION NAÏVE — aucun profil ICC de sortie"
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
    tons_directs: dict[str, np.ndarray] | None = None,
) -> np.ndarray:
    """Répartit le CMJN séparé sur les canaux du profil, génère blanc et vernis.

    **Un ton direct dessiné dans le fichier prime sur toute génération.** Si
    l'opérateur a préparé une couche « White » ou « Vernis » dans Photoshop,
    c'est elle qui part sur la machine : elle porte une intention que le
    logiciel ne saurait pas deviner — un vernis sélectif, un blanc qui déborde
    volontairement, un relief localisé.
    """
    h, w = cmyk.shape[1:]
    out = np.zeros((profile.n_channels, h, w), dtype=np.float32)
    fournis = _tons_par_encre(tons_directs or {}, media)
    for i, ch in enumerate(profile.channels):
        if ch.name in fournis:
            out[i] = fournis[ch.name]
            continue
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
                    mode=media.white_mode,
                )
        elif ch.role == ROLE_VARNISH:
            out[i] = varnish(cmyk, mode="flood", density=1.0)
        # ROLE_SPOT : laissé à zéro tant qu'aucune source de ton direct n'est
        # branchée — mieux vaut un canal vide qu'une encre posée au hasard.
    return out


def _tons_par_encre(
    tons_directs: dict[str, np.ndarray], media: MediaProfile
) -> dict[str, np.ndarray]:
    """Couches nommées du fichier → encres de la machine.

    La table du profil média prime sur les correspondances usuelles : un atelier
    nomme ses couches comme il l'entend, et le logiciel n'a pas à en décider.
    """
    resultat: dict[str, np.ndarray] = {}
    for nom, couche in tons_directs.items():
        encre = photoshop.encre_pour(nom, media.spot_map)
        if encre is not None:
            resultat[encre] = couche
    return resultat


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
    # Deux repères à ne pas confondre : celui du MUR (ce que voit l'opérateur)
    # et celui du FICHIER machine. Sur une machine à chariot vertical, l'axe X
    # du fichier est le vertical du mur : les deux sont donc à angle droit.
    src_w, src_h, src_dpi_x, src_dpi_y = mesurer(spec.source, spec.rotate)
    mur_l_mm, mur_h_mm = fit_size_mm(
        src_w, src_h, src_dpi_x=src_dpi_x, src_dpi_y=src_dpi_y,
        width_mm=spec.width_mm, height_mm=spec.height_mm,
    )

    verifier_hauteur(mur_h_mm, profile.max_height_mm)
    if profile.max_width_mm and mur_l_mm > profile.max_width_mm + 1e-6:
        raise RipError(
            f"largeur demandée {mur_l_mm:.0f} mm > bande de la machine "
            f"{profile.max_width_mm:.0f} mm — découpez la fresque en panneaux"
        )

    rotation = (spec.rotate + profile.machine_rotation) % 360
    if profile.machine_rotation in (90, 270):
        prn_l_mm, prn_h_mm = mur_h_mm, mur_l_mm
    else:
        prn_l_mm, prn_h_mm = mur_l_mm, mur_h_mm
    width_px = pixels_for(prn_l_mm, spec.dpi_x)
    height_px = pixels_for(prn_h_mm, spec.dpi_y)

    # -- chargement ----------------------------------------------------------
    img = load_source(
        spec.source, width_px=width_px, height_px=height_px,
        resample=spec.resample, rotate=rotation, mirror=spec.mirror,
    )

    separate, icc_label = _build_color_transform(spec, img)
    # Consigné dans le manifeste : quelle couche du fichier a alimenté quelle
    # encre. C'est la trace qui permet, devant un tirage raté, de savoir si le
    # blanc venait de Photoshop ou de la génération automatique.
    #
    # Une couche n'est « reconnue » que si l'encre visée existe VRAIMENT sur la
    # machine : annoncer qu'un vernis est parti sur une presse qui n'en a pas
    # serait pire que de se taire.
    spots_detectes = {}
    for nom in img.tons_directs:
        encre = photoshop.encre_pour(nom, media.spot_map)
        spots_detectes[nom] = encre if encre in profile.channel_names else ""
    if spots_detectes:
        reconnus = [n for n, encre in spots_detectes.items() if encre]
        ignores = [n for n, encre in spots_detectes.items() if not encre]
        if reconnus:
            warnings.append(
                "couches du fichier utilisées telles quelles : "
                + ", ".join(f"{n} → encre {spots_detectes[n]}" for n in reconnus)
                + " (aucune génération automatique sur ces canaux)"
            )
        if ignores:
            warnings.append(
                "couches du fichier non reconnues et ignorées : "
                + ", ".join(ignores)
                + " — nommez-les dans la table des tons directs du profil "
                "support, et vérifiez que la machine porte bien cette encre"
            )
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
    band_lines = _hauteur_de_bande(spec.band_lines, width_px, profile.n_channels)
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
        for y0 in range(0, height_px, band_lines):
            y1 = min(y0 + band_lines, height_px)
            bande = img.band(y0, y1)

            cmyk = separate(bande.donnees)
            ink = _assemble(profile, cmyk, media, bande.alpha, bande.tons_directs)
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
    img.close()

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
        width_mm=mur_l_mm,
        height_mm=mur_h_mm,
        channels=profile.channel_names,
        coverage=coverage,
        halftone=ht.name,
        icc=icc_label,
        seconds=time.monotonic() - started,
        warnings=warnings,
        spot_channels=spots_detectes,
    )
    result.manifest = write_manifest(spec, result, header)
    return result


def _hauteur_de_bande(demande: int, width_px: int, channels: int) -> int:
    """Hauteur de bande tenant dans le budget mémoire, pour cette largeur.

    Les tableaux vivants pendant une bande sont de l'ordre de deux fois
    (canaux × largeur × hauteur) en float32 : entrée séparée, encre assemblée,
    plus les intermédiaires du tramage.
    """
    par_ligne = max(1, width_px * max(channels, 4) * 4 * 2)
    plafond = max(MIN_BAND_LINES, BUDGET_BANDE_OCTETS // par_ligne)
    return max(MIN_BAND_LINES, min(demande, plafond))


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
        # Deux repères, explicitement séparés : ce qui est mesuré sur le mur,
        # et ce qui est écrit dans le fichier machine.
        "wall": {
            "width_mm": round(result.width_mm, 3),
            "height_mm": round(result.height_mm, 3),
            "carriage_axis": spec.printer.carriage_axis,
            "machine_rotation_deg": spec.printer.machine_rotation,
        },
        "geometry": {
            "width_px": result.width_px,
            "padded_width_px": header.width_px,
            "height_px": result.height_px,
            "width_mm": round(result.width_px / spec.dpi_x * MM_PER_INCH, 3),
            "height_mm": round(result.height_px / spec.dpi_y * MM_PER_INCH, 3),
            "dpi_x": spec.dpi_x,
            "dpi_y": spec.dpi_y,
            "rotate": spec.rotate,
            "total_rotation_deg": (spec.rotate + spec.printer.machine_rotation) % 360,
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
        "spot_channels": {
            "trouvés": {
                nom: (encre or None) for nom, encre in result.spot_channels.items()
            },
            "table": dict(spec.media.spot_map or {}),
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
