"""Courbes de transfert : linéarisation et calage d'encre.

Rôle : faire qu'un aplat demandé à 50 % *mesure* 50 % de densité sur le support.
Sans cette étape, la réponse de la machine est fortement non linéaire (les
clairs bouchent, les foncés s'écrasent) et aucun profil ICC ne peut rattraper.

On ne décode pas les `.cuv` d'UltraPrint : leur structure est connue (magic
`0x88440001`, enregistrements de float64) mais les offsets exacts sont marqués
« ouverts » dans le dossier de rétro-ingénierie. Reconstruire notre propre
linéarisation à partir de mesures est plus rapide, plus sûr, et donne un
résultat calé sur *nos* encres et *notre* support.

Format de stockage : JSON, lisible et éditable à la main.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..errors import CalibrationError

LUT_SIZE = 1024


def _enforce_monotone(y: np.ndarray) -> np.ndarray:
    """Rend une suite non décroissante en conservant sa forme générale.

    Une courbe de linéarisation non monotone produit des inversions visibles
    dans les dégradés — un pas plus clair au milieu d'une rampe. Le bruit de
    mesure en produit régulièrement dans les hautes lumières ; on le corrige
    plutôt que de le laisser passer.
    """
    return np.maximum.accumulate(np.asarray(y, dtype=np.float64))


@dataclass(frozen=True, slots=True)
class TransferCurve:
    """Courbe monotone [0,1] → [0,1], échantillonnée puis interpolée."""

    x: np.ndarray
    y: np.ndarray

    def __post_init__(self) -> None:
        x = np.asarray(self.x, dtype=np.float64)
        y = np.asarray(self.y, dtype=np.float64)
        if x.ndim != 1 or x.shape != y.shape or x.size < 2:
            raise CalibrationError("courbe : x et y doivent être 1-D et de même taille")
        if np.any(np.diff(x) <= 0):
            raise CalibrationError("courbe : les abscisses doivent être croissantes")
        if x[0] != 0.0 or x[-1] != 1.0:
            raise CalibrationError(
                f"courbe : le domaine doit être [0, 1], reçu [{x[0]}, {x[-1]}]"
            )
        if np.any(y < 0.0) or np.any(y > 1.0):
            raise CalibrationError("courbe : les ordonnées doivent tenir dans [0, 1]")
        object.__setattr__(self, "x", x)
        object.__setattr__(self, "y", _enforce_monotone(y))

    @classmethod
    def identity(cls) -> TransferCurve:
        return cls(np.array([0.0, 1.0]), np.array([0.0, 1.0]))

    @classmethod
    def from_measurements(
        cls, requested: np.ndarray, measured: np.ndarray
    ) -> TransferCurve:
        """Construit la courbe inverse à partir d'un coin mesuré.

        ``requested`` = valeurs demandées au RIP (0..1), ``measured`` = densités
        relevées (unité libre : on normalise sur le maximum). La courbe renvoyée
        associe à chaque *tonalité voulue* la *valeur à demander* pour l'obtenir.
        """
        req = np.asarray(requested, dtype=np.float64)
        mes = _enforce_monotone(np.asarray(measured, dtype=np.float64))
        if req.shape != mes.shape or req.size < 3:
            raise CalibrationError(
                "au moins 3 paliers appariés (demandé, mesuré) sont nécessaires"
            )
        span = mes[-1] - mes[0]
        if span <= 0:
            raise CalibrationError(
                "mesures plates : le coin n'a pas imprimé, ou le densitomètre "
                "n'a pas vu de différence entre le blanc et l'aplat"
            )
        norm = (mes - mes[0]) / span
        # Inversion : pour chaque tonalité cible régulière, la valeur à demander.
        target = np.linspace(0.0, 1.0, LUT_SIZE)
        # np.interp exige des abscisses croissantes ; norm l'est par construction,
        # mais les paliers dupliqués (zones bouchées) doivent être dédoublonnés.
        uniq, idx = np.unique(norm, return_index=True)
        if uniq.size < 2:
            raise CalibrationError("mesures dégénérées après dédoublonnage")
        values = np.interp(target, uniq, req[idx])
        return cls(target, np.clip(values, 0.0, 1.0))

    def lut(self, size: int = LUT_SIZE) -> np.ndarray:
        """Table de correspondance float32 prête pour l'application."""
        xs = np.linspace(0.0, 1.0, size)
        return np.interp(xs, self.x, self.y).astype(np.float32)

    def apply(self, values: np.ndarray) -> np.ndarray:
        """Applique la courbe à un tableau de valeurs 0..1."""
        v = np.clip(values, 0.0, 1.0)
        return np.interp(v, self.x, self.y).astype(np.float32)


@dataclass(frozen=True, slots=True)
class Linearization:
    """Un jeu de courbes, une par canal."""

    curves: dict[str, TransferCurve]
    source: Path | None = None
    notes: str = ""

    @classmethod
    def identity(cls, channels: tuple[str, ...]) -> Linearization:
        return cls({c: TransferCurve.identity() for c in channels})

    def for_channel(self, name: str) -> TransferCurve:
        return self.curves.get(name, TransferCurve.identity())

    def luts(self, channels: tuple[str, ...], size: int = LUT_SIZE) -> np.ndarray:
        """Matrice (C, size) de LUT, dans l'ordre des canaux demandé."""
        return np.stack([self.for_channel(c).lut(size) for c in channels])

    @property
    def is_identity(self) -> bool:
        return all(
            np.array_equal(c.x, np.array([0.0, 1.0]))
            and np.array_equal(c.y, np.array([0.0, 1.0]))
            for c in self.curves.values()
        )

    # -- persistance ---------------------------------------------------------

    def save(self, path: str | Path) -> None:
        p = Path(path)
        payload = {
            "format": "ripcore-linearization-1",
            "notes": self.notes,
            "curves": {
                name: {"x": c.x.tolist(), "y": c.y.tolist()}
                for name, c in self.curves.items()
            },
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        tmp.replace(p)

    @classmethod
    def load(cls, path: str | Path) -> Linearization:
        p = Path(path)
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise CalibrationError(f"linéarisation introuvable : {p}") from None
        except json.JSONDecodeError as exc:
            raise CalibrationError(f"linéarisation {p} illisible : {exc}") from None
        if payload.get("format") != "ripcore-linearization-1":
            raise CalibrationError(
                f"{p} : format {payload.get('format')!r} non reconnu"
            )
        curves = {
            name: TransferCurve(np.asarray(c["x"]), np.asarray(c["y"]))
            for name, c in payload["curves"].items()
        }
        return cls(curves, source=p, notes=payload.get("notes", ""))


def apply_luts(ink: np.ndarray, luts: np.ndarray) -> np.ndarray:
    """Applique une LUT par canal à un bloc (C, H, W), interpolation linéaire.

    L'interpolation évite le crénelage qu'une simple indexation entière
    provoquerait dans les dégradés doux.
    """
    a = np.clip(np.asarray(ink, dtype=np.float32), 0.0, 1.0)
    if a.shape[0] != luts.shape[0]:
        raise CalibrationError(
            f"{a.shape[0]} canaux à traiter, {luts.shape[0]} LUT fournies"
        )
    size = luts.shape[1]
    pos = a * (size - 1)
    i0 = np.floor(pos).astype(np.int32)
    np.clip(i0, 0, size - 2, out=i0)
    frac = (pos - i0).astype(np.float32)
    out = np.empty_like(a)
    for c in range(a.shape[0]):
        lo = luts[c][i0[c]]
        hi = luts[c][i0[c] + 1]
        out[c] = lo + (hi - lo) * frac[c]
    return out
