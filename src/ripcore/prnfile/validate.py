"""Contrôle avant vol d'un `.prn`.

Rien ne part vers la machine sans être passé par ici. Le principe est celui du
double calcul : le fichier est **relu depuis le disque** et re-vérifié
indépendamment du code qui l'a produit. Un bug de l'écrivain qui se contenterait
de relire ses propres variables ne serait pas détecté ; celui-ci l'est.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..blocks import DEFAULT_BLOCK, block_means
from ..profiles import PrinterProfile
from .reader import PrnReader, probe

# Marge sur les contrôles d'encre : le tramage introduit une variance locale
# inévitable autour de la valeur visée.
_TOLERANCE = 0.02

ERROR = "error"
WARNING = "warning"
INFO = "info"
_RANK = {ERROR: 0, WARNING: 1, INFO: 2}


@dataclass(frozen=True, slots=True)
class Finding:
    severity: str
    check: str
    message: str

    def __str__(self) -> str:
        tag = {ERROR: "ERREUR ", WARNING: "ATTENTION", INFO: "ok      "}[self.severity]
        return f"[{tag}] {self.check} — {self.message}"


@dataclass(slots=True)
class Report:
    path: Path
    findings: list[Finding] = field(default_factory=list)
    coverage: dict[str, float] = field(default_factory=dict)
    max_block: dict[str, float] = field(default_factory=dict)
    max_total_ink: float = 0.0
    max_process_ink: float = 0.0
    block: int = DEFAULT_BLOCK

    def add(self, severity: str, check: str, message: str) -> None:
        self.findings.append(Finding(severity, check, message))

    @property
    def ok(self) -> bool:
        return not any(f.severity == ERROR for f in self.findings)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARNING]

    def render(self, verbose: bool = False) -> str:
        items = sorted(self.findings, key=lambda f: _RANK[f.severity])
        if not verbose:
            items = [f for f in items if f.severity != INFO]
        lines = [str(f) for f in items]
        if self.coverage:
            cov = "  ".join(f"{k}={v * 100:.1f}%" for k, v in self.coverage.items())
            lines.append(
                f"[couverture] moyenne {cov}\n"
                f"[encre] pointe locale (blocs de {self.block} px) : "
                f"process {self.max_process_ink:.2f}  |  "
                f"tous canaux {self.max_total_ink:.2f}"
            )
        verdict = "CONFORME" if self.ok else "NON CONFORME"
        lines.append(f"→ {self.path.name} : {verdict}")
        return "\n".join(lines)


def validate_prn(
    path: str | Path,
    profile: PrinterProfile | None = None,
    *,
    inspect_body: bool = True,
    lines_per_band: int = 256,
    tac_block: int = DEFAULT_BLOCK,
) -> Report:
    """Relit un `.prn` et vérifie conteneur, cohérence profil et charge d'encre."""
    p = Path(path)
    report = Report(path=p)

    pr = probe(p)
    if not pr.supported:
        report.add(
            ERROR,
            "dialecte",
            f"{pr.dialect} (en-tête {pr.header_size} o) — nous n'écrivons que le "
            f"générique 48 o",
        )
        return report
    header = pr.header
    assert header is not None

    # -- conteneur -----------------------------------------------------------
    if pr.file_size != header.file_size:
        report.add(
            ERROR,
            "taille",
            f"{pr.file_size} o sur disque, {header.file_size} o annoncés "
            f"(48 + {header.lines} × {header.stride})",
        )
    else:
        report.add(INFO, "taille", f"{pr.file_size} o, cohérente avec l'en-tête")

    if header.body_size % header.lines:
        report.add(ERROR, "géométrie", "corps non divisible par le nombre de lignes")
    else:
        report.add(INFO, "géométrie", header.describe())

    # -- cohérence avec le profil -------------------------------------------
    if profile is not None:
        if header.channels != profile.n_channels:
            report.add(
                ERROR,
                "canaux",
                f"{header.channels} dans le fichier, {profile.n_channels} au profil "
                f"({', '.join(profile.channel_names)})",
            )
        if header.bits_per_pixel != profile.bits_per_pixel:
            report.add(
                ERROR,
                "bpp",
                f"{header.bits_per_pixel} dans le fichier, "
                f"{profile.bits_per_pixel} au profil",
            )
        try:
            expected_pm = profile.pass_mode(header.dpi_y)
        except Exception as exc:  # ProfileError : résolution non tabulée
            report.add(ERROR, "pass_mode", str(exc))
        else:
            if header.pass_mode != expected_pm:
                report.add(
                    ERROR,
                    "pass_mode",
                    f"{header.pass_mode} dans le fichier, {expected_pm} attendu "
                    f"pour dpi_y={header.dpi_y}",
                )
            else:
                report.add(INFO, "pass_mode", f"{header.pass_mode} (dpi_y={header.dpi_y})")

        if profile.max_width_mm and header.width_mm > profile.max_width_mm + 0.5:
            report.add(
                ERROR,
                "largeur",
                f"{header.width_mm:.1f} mm > course machine "
                f"{profile.max_width_mm:.1f} mm",
            )
        for w in profile.warnings():
            report.add(WARNING, "profil", w)

    if not inspect_body:
        return report

    # -- contenu -------------------------------------------------------------
    n_levels = 1 << header.bits_per_pixel
    hist = np.zeros((header.channels, n_levels), dtype=np.int64)
    densities = (
        np.asarray(profile.drop_levels.densities, dtype=np.float64)
        if profile is not None
        else np.linspace(0.0, 1.0, n_levels)
    )
    total_pixels = 0

    # L'encre se juge sur une surface, jamais sur un pixel isolé : après
    # tramage, un pixel portant une grosse goutte sur tous les canaux est
    # normal. On mesure donc la moyenne locale par blocs (cf. ripcore.blocks).
    max_block_total = 0.0
    max_block_process = 0.0
    max_block_channel = np.zeros(header.channels)
    process_mask = (
        profile.process_mask
        if profile is not None
        else np.ones(header.channels, dtype=bool)
    )

    reader = PrnReader(p)
    bands = reader.bands(lines_per_band=lines_per_band)

    def _counting(source):
        nonlocal total_pixels
        for band in source:
            total_pixels += band.shape[1] * band.shape[2]
            for c in range(header.channels):
                hist[c] += np.bincount(band[c].ravel(), minlength=n_levels)
            yield band

    for blocks in block_means(_counting(bands), densities, block=tac_block):
        max_block_channel = np.maximum(max_block_channel, blocks.max(axis=(1, 2)))
        total = blocks.sum(axis=0)
        if total.size:
            max_block_total = max(max_block_total, float(total.max()))
        if process_mask.any():
            proc = blocks[process_mask].sum(axis=0)
            if proc.size:
                max_block_process = max(max_block_process, float(proc.max()))

    report.max_total_ink = max_block_total
    report.max_process_ink = max_block_process
    report.block = tac_block

    names = (
        profile.channel_names
        if profile is not None
        else tuple(f"ch{i}" for i in range(header.channels))
    )
    for i, name in enumerate(names):
        report.coverage[name] = (
            float(hist[i] @ densities) / total_pixels if total_pixels else 0.0
        )
        report.max_block[name] = float(max_block_channel[i])
        if profile is not None:
            limit = profile.limit_for(name)
            if max_block_channel[i] > limit + _TOLERANCE:
                report.add(
                    ERROR,
                    f"encre/{name}",
                    f"pointe locale {max_block_channel[i] * 100:.1f}% > limite canal "
                    f"{limit * 100:.0f}% (blocs de {tac_block} px) — le limiteur "
                    f"n'a pas été appliqué",
                )

    if total_pixels and all(v == 0.0 for v in report.coverage.values()):
        report.add(ERROR, "contenu", "raster entièrement vide — rien à imprimer")

    if profile is not None:
        if max_block_process > profile.ink_limit_total + _TOLERANCE:
            report.add(
                ERROR,
                "encre/process",
                f"encre process locale {max_block_process:.2f} > limite "
                f"{profile.ink_limit_total:.2f} — risque de coulure et de "
                f"non-polymérisation",
            )
        else:
            report.add(
                INFO,
                "encre/process",
                f"pointe locale {max_block_process:.2f} / "
                f"{profile.ink_limit_total:.2f}",
            )
        if profile.ink_limit_total_all is not None:
            if max_block_total > profile.ink_limit_total_all + _TOLERANCE:
                report.add(
                    ERROR,
                    "encre/total",
                    f"encre totale locale {max_block_total:.2f} > limite "
                    f"{profile.ink_limit_total_all:.2f}",
                )
            else:
                report.add(
                    INFO,
                    "encre/total",
                    f"pointe locale {max_block_total:.2f} / "
                    f"{profile.ink_limit_total_all:.2f}",
                )
        else:
            report.add(
                INFO,
                "encre/total",
                f"pointe locale tous canaux {max_block_total:.2f} (aucune limite "
                f"globale déclarée : ink_limits.total_all)",
            )
    else:
        report.add(INFO, "encre/total", f"pointe locale {max_block_total:.2f}")

    return report
