"""Exploitation des mesures : tailles de goutte et linéarisation.

Un point de méthode qui décide de la qualité finale.

Le tramage mélange des pixels de niveaux voisins. Ce mélange est linéaire **en
réflectance**, pas en densité optique : deux fois plus de gouttes ne fait pas
deux fois plus de densité. Convertir les mesures par la relation de
Murray–Davies avant de construire les échelles est ce qui rend un aplat à 50 %
réellement à mi-chemin :

    couverture = (1 − 10^−D) / (1 − 10^−D_aplat)

Le mode ``density`` reste disponible pour comparer avec un flux existant, mais
``coverage`` (défaut) est la bonne physique et se marie avec la quantification
multi-niveaux de ``halftone.levels``.

Format de mesures : CSV à quatre colonnes, en-tête obligatoire ::

    channel,kind,value,measurement
    C,level,0,0.06
    C,level,1,0.42
    ...
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .color.curves import Linearization, TransferCurve
from .errors import CalibrationError

COVERAGE = "coverage"
DENSITY = "density"
METRICS = (COVERAGE, DENSITY)

_FIELDS = ("channel", "kind", "value", "measurement")


@dataclass(frozen=True, slots=True)
class Measurement:
    channel: str
    kind: str  # "level" (aplat d'un niveau) | "tone" (palier tramé)
    value: float
    measurement: float


def read_measurements(path: str | Path) -> list[Measurement]:
    """Lit un CSV de mesures. Tolère l'ordre des colonnes, pas leur absence."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise CalibrationError(f"fichier de mesures introuvable : {p}") from None

    reader = csv.DictReader(text.splitlines())
    missing = [f for f in _FIELDS if f not in (reader.fieldnames or [])]
    if missing:
        raise CalibrationError(
            f"{p} : colonnes manquantes {missing}. En-tête attendu : "
            f"{','.join(_FIELDS)}"
        )

    out: list[Measurement] = []
    for lineno, row in enumerate(reader, start=2):
        try:
            out.append(
                Measurement(
                    channel=row["channel"].strip(),
                    kind=row["kind"].strip().lower(),
                    value=float(row["value"]),
                    measurement=float(row["measurement"]),
                )
            )
        except (TypeError, ValueError) as exc:
            raise CalibrationError(f"{p} ligne {lineno} : {exc}") from None
    if not out:
        raise CalibrationError(f"{p} : aucune mesure")
    return out


def _to_metric(values: np.ndarray, paper: float, solid: float, metric: str) -> np.ndarray:
    """Mesures brutes → échelle 0..1, relative au support et à l'aplat."""
    if metric not in METRICS:
        raise CalibrationError(f"métrique inconnue : {metric!r} ({' | '.join(METRICS)})")
    d = np.asarray(values, dtype=np.float64) - paper
    d_solid = solid - paper
    if d_solid <= 1e-6:
        raise CalibrationError(
            "l'aplat ne se distingue pas du support : mesures inexploitables "
            "(mauvais canal mesuré, mire non imprimée, ou densitomètre non calé)"
        )
    if metric == DENSITY:
        return np.clip(d / d_solid, 0.0, 1.0)
    cov = (1.0 - np.power(10.0, -np.maximum(d, 0.0))) / (1.0 - 10.0**-d_solid)
    return np.clip(cov, 0.0, 1.0)


def _by_channel(
    measurements: list[Measurement], kind: str
) -> dict[str, list[Measurement]]:
    grouped: dict[str, list[Measurement]] = defaultdict(list)
    for m in measurements:
        if m.kind == kind:
            grouped[m.channel].append(m)
    if not grouped:
        raise CalibrationError(f"aucune mesure de type {kind!r} dans le fichier")
    return {k: sorted(v, key=lambda m: m.value) for k, v in grouped.items()}


def drop_densities(
    measurements: list[Measurement],
    n_levels: int,
    *,
    metric: str = COVERAGE,
) -> tuple[float, ...]:
    """Échelle des tailles de goutte, moyennée sur tous les canaux mesurés.

    Le niveau 0 (support nu) doit figurer dans les mesures : c'est la référence
    de blanc, et sans elle l'échelle est décalée.
    """
    grouped = _by_channel(measurements, "level")
    scales = []
    for channel, rows in grouped.items():
        levels = np.array([m.value for m in rows])
        if not np.array_equal(levels, np.arange(n_levels, dtype=float)):
            raise CalibrationError(
                f"canal {channel} : niveaux {levels.tolist()} mesurés, "
                f"{list(range(n_levels))} attendus (le niveau 0 = support nu est "
                f"obligatoire)"
            )
        raw = np.array([m.measurement for m in rows])
        scales.append(_to_metric(raw, paper=raw[0], solid=raw[-1], metric=metric))

    mean = np.mean(scales, axis=0)
    mean[0], mean[-1] = 0.0, 1.0
    if np.any(np.diff(mean) <= 0):
        raise CalibrationError(
            f"échelle de gouttes non croissante : {mean.round(4).tolist()}. "
            f"Une taille de goutte dépose moins que la précédente — vérifiez la "
            f"mire, la buse concernée, ou l'ordre des plages mesurées."
        )
    return tuple(round(float(v), 6) for v in mean)


def build_linearization(
    measurements: list[Measurement],
    *,
    metric: str = COVERAGE,
    notes: str = "",
) -> Linearization:
    """Construit une courbe par canal à partir d'un coin dégradé mesuré."""
    grouped = _by_channel(measurements, "tone")
    curves = {}
    for channel, rows in grouped.items():
        tones = np.array([m.value for m in rows], dtype=np.float64)
        raw = np.array([m.measurement for m in rows], dtype=np.float64)
        if tones.size < 3:
            raise CalibrationError(
                f"canal {channel} : {tones.size} paliers, 3 au minimum"
            )
        if abs(tones[0]) > 1e-9:
            raise CalibrationError(
                f"canal {channel} : le palier 0 % (support nu) est obligatoire"
            )
        scaled = _to_metric(raw, paper=raw[0], solid=raw[-1], metric=metric)
        curves[channel] = TransferCurve.from_measurements(tones, scaled)
    return Linearization(curves, notes=notes)


def render_profile_snippet(densities: tuple[float, ...]) -> str:
    """Bloc TOML prêt à coller dans le profil imprimante."""
    # Toujours un point décimal : TOML lirait « 0 » comme un entier.
    values = ", ".join(f"{v:.6f}".rstrip("0").ljust(3, "0") for v in densities)
    return (
        "[drop_levels]\n"
        f"densities = [{values}]\n"
        "calibrated = true\n"
    )
