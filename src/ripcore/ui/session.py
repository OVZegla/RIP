"""État de l'application, sans dépendance à Tk.

Tout ce qui décide de quelque chose vit ici : où sont les profils, où vont les
fichiers produits, comment un choix d'opérateur devient un job, quelles erreurs
méritent une phrase compréhensible plutôt qu'une trace technique.

C'est aussi ce qui rend l'interface testable : les écrans ne font qu'afficher.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..errors import ProfileError, RipError
from ..pipeline import JobSpec
from ..profiles import MediaProfile, PrinterProfile
from . import textes

DOSSIER_PROFILS = "profiles"
DOSSIER_SORTIE = "Impressions"
DOSSIER_TESTS = "Tests machine"


def racine_projet() -> Path:
    """Racine du dépôt, quelle que soit la façon dont l'appli a été lancée."""
    return Path(__file__).resolve().parents[3]


def dossier_documents() -> Path:
    """Dossier de travail de l'opérateur, dans ses documents."""
    if platform.system() == "Windows":
        base = Path(os.environ.get("USERPROFILE", Path.home())) / "Documents"
    else:
        base = Path.home()
    return base / "Atelier impression"


@dataclass(slots=True)
class Travail:
    """Une entrée d'historique, relue depuis le manifeste d'un fichier produit."""

    fichier: Path
    source: str
    largeur_mm: float
    hauteur_mm: float
    date: datetime
    encre: dict[str, float]

    @property
    def encre_totale(self) -> float:
        return sum(self.encre.values())

    def taille(self) -> str:
        return f"{self.largeur_mm:.0f} × {self.hauteur_mm:.0f} mm"

    def date_lisible(self) -> str:
        return self.date.strftime("%d/%m/%Y à %H:%M")


@dataclass
class Session:
    """Ce que l'application sait, entre deux clics."""

    profil: PrinterProfile
    profil_chemin: Path
    supports: list[MediaProfile] = field(default_factory=list)
    dossier_sortie: Path = field(default_factory=lambda: dossier_documents() / DOSSIER_SORTIE)
    dossier_tests: Path = field(default_factory=lambda: dossier_documents() / DOSSIER_TESTS)

    @classmethod
    def ouvrir(cls, profil: Path | None = None) -> Session:
        chemin = Path(profil) if profil else cls._profil_par_defaut()
        session = cls(profil=PrinterProfile.load(chemin), profil_chemin=chemin)
        session.recharger_supports()
        session.dossier_sortie.mkdir(parents=True, exist_ok=True)
        session.dossier_tests.mkdir(parents=True, exist_ok=True)
        return session

    @staticmethod
    def _profil_par_defaut() -> Path:
        dossier = racine_projet() / DOSSIER_PROFILS
        candidats = sorted(
            p for p in dossier.glob("*.toml") if not p.name.startswith("media-")
        )
        if not candidats:
            raise ProfileError(
                f"aucun profil de presse trouvé dans {dossier}. "
                f"Un fichier .toml décrivant la machine est nécessaire."
            )
        return candidats[0]

    def recharger_profil(self) -> None:
        self.profil = PrinterProfile.load(self.profil_chemin)

    def recharger_supports(self) -> None:
        dossier = racine_projet() / DOSSIER_PROFILS
        trouves = []
        for chemin in sorted(dossier.glob("media-*.toml")):
            try:
                trouves.append(MediaProfile.load(chemin))
            except RipError:
                continue  # un profil support cassé ne doit pas bloquer l'appli
        self.supports = trouves

    def support_par_nom(self, nom: str) -> MediaProfile | None:
        return next((m for m in self.supports if m.name == nom), None)

    # -- avertissements ------------------------------------------------------

    def avertissements(self) -> list[str]:
        """Ce qui n'est pas réglé, dit en mots d'atelier."""
        return [textes.traduire_avertissement(a) for a in self.profil.warnings()]

    @property
    def presse_reglee(self) -> bool:
        return self.profil.channel_order_verified

    # -- fabrication d'un job -----------------------------------------------

    def preparer_job(
        self,
        source: Path,
        *,
        largeur_mm: float | None,
        hauteur_mm: float | None,
        dpi_x: int,
        dpi_y: int,
        grain: str,
        rotation: int,
        miroir: bool,
        support: MediaProfile | None,
        blanc: bool,
    ) -> JobSpec:
        """Choix d'écran → JobSpec, avec les vérifications à faire tôt."""
        source = Path(source)
        if not source.is_file():
            raise RipError(textes.ERREUR_FICHIER_INTROUVABLE)
        if largeur_mm is not None and self.profil.max_width_mm:
            if largeur_mm > self.profil.max_width_mm:
                raise RipError(
                    textes.ERREUR_TROP_LARGE.format(
                        demande=largeur_mm, max=self.profil.max_width_mm
                    )
                )

        media = support or MediaProfile(name="Sans profil de support")
        # Le blanc est une décision d'écran : on ne modifie pas le fichier de
        # support pour autant, on en dérive une copie.
        if media.white_underbase != blanc:
            media = MediaProfile(
                name=media.name,
                icc_output=media.icc_output,
                icc_input_rgb=media.icc_input_rgb,
                icc_input_cmyk=media.icc_input_cmyk,
                rendering_intent=media.rendering_intent,
                linearization=media.linearization,
                ink_limit_total=media.ink_limit_total,
                white_underbase=blanc,
                white_density=media.white_density,
                white_choke_px=media.white_choke_px,
                notes=media.notes,
                source=media.source,
            )

        self.dossier_sortie.mkdir(parents=True, exist_ok=True)
        return JobSpec(
            source=source,
            output=self.dossier_sortie / f"{source.stem}.prn",
            printer=self.profil,
            media=media,
            dpi_x=dpi_x,
            dpi_y=dpi_y,
            width_mm=largeur_mm,
            height_mm=hauteur_mm,
            halftone=grain,
            rotate=rotation,
            mirror=miroir,
        )

    # -- historique ----------------------------------------------------------

    def historique(self, limite: int = 200) -> list[Travail]:
        """Travaux déjà préparés, du plus récent au plus ancien."""
        travaux: list[Travail] = []
        for manifeste in self.dossier_sortie.glob("*.prn.json"):
            travail = _lire_manifeste(manifeste)
            if travail is not None:
                travaux.append(travail)
        travaux.sort(key=lambda t: t.date, reverse=True)
        return travaux[:limite]


def _lire_manifeste(chemin: Path) -> Travail | None:
    """Un manifeste illisible est ignoré : l'historique n'est pas critique."""
    try:
        données = json.loads(chemin.read_text(encoding="utf-8"))
        geo = données["geometry"]
        fichier = Path(données["output"])
        return Travail(
            fichier=fichier,
            source=Path(données.get("source", "")).name,
            largeur_mm=float(geo["width_mm"]),
            hauteur_mm=float(geo["height_mm"]),
            date=datetime.fromtimestamp(chemin.stat().st_mtime),
            encre={k: float(v) for k, v in données.get("coverage", {}).items()},
        )
    except (OSError, ValueError, KeyError):
        return None


def ouvrir_dossier(chemin: Path) -> None:
    """Ouvre l'explorateur de fichiers du système sur ce dossier."""
    chemin = Path(chemin)
    système = platform.system()
    try:
        if système == "Windows":
            os.startfile(chemin)  # type: ignore[attr-defined]  # noqa: S606
        elif système == "Darwin":
            subprocess.run(["open", str(chemin)], check=False)
        else:
            subprocess.run(["xdg-open", str(chemin)], check=False)
    except OSError as exc:
        raise RipError(f"impossible d'ouvrir {chemin} : {exc}") from exc
