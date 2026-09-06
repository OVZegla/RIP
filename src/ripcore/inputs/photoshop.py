"""Lecture des tons directs d'un TIFF Photoshop.

Photoshop enregistre un ton direct comme un **canal supplémentaire** du TIFF —
un CMJN + blanc fait donc cinq échantillons par pixel. Deux conséquences :

* **Pillow refuse purement et simplement** un TIFF à plus de quatre canaux :
  « cannot identify image file ». Il faut passer par ``tifffile``.
* **Le nom du canal n'est pas dans le TIFF standard** mais dans un bloc de
  ressources propriétaire (tag 34377), ressource 1006 : la liste des noms des
  canaux supplémentaires, en chaînes Pascal.

Sans ce nom, un canal n'est qu'une couche de gris de plus et rien ne dit si
c'est du blanc, du vernis ou un ton direct. C'est pourtant l'information qui
décide de l'encre employée.
"""

from __future__ import annotations

import struct
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..errors import RipError

TAG_PHOTOSHOP = 34377
RESSOURCE_NOMS_CANAUX = 1006

# Photométries TIFF → mode de travail.
_PHOTOMETRIE = {"separated": "CMYK", "rgb": "RGB", "miniswhite": "L",
                "minisblack": "L", "palette": "RGB"}

# Un atelier n'écrit pas toujours ses couches en anglais. La correspondance se
# fait sur un nom normalisé (sans accent, sans casse, sans ponctuation).
ALIAS = {
    "W": ("white", "blanc", "blanche", "souscouche", "sous couche", "underbase",
          "weiss", "wit", "blanco", "bianco", "spotwhite", "whiteink"),
    "V": ("varnish", "vernis", "gloss", "brillant", "brillance", "oil", "relief",
          "lack", "barniz", "vernice", "clear", "coat"),
}


def normaliser(nom: str) -> str:
    """« Vernis sélectif » → « vernisselectif ». Pour comparer des noms."""
    sans_accent = unicodedata.normalize("NFKD", nom)
    sans_accent = "".join(c for c in sans_accent if not unicodedata.combining(c))
    return "".join(c for c in sans_accent.lower() if c.isalnum())


def encre_pour(nom: str, alias: dict[str, str] | None = None) -> str | None:
    """Nom de couche → code d'encre, ou None si on ne reconnaît pas.

    ``alias`` permet à un profil média d'imposer sa propre table : c'est lui qui
    prime, un atelier nommant ses couches comme il l'entend.
    """
    cle = normaliser(nom)
    if alias:
        for source, cible in alias.items():
            if normaliser(source) == cle:
                return cible
    for encre, formes in ALIAS.items():
        if cle in {normaliser(f) for f in formes}:
            return encre
    return None


def lire_noms_de_canaux(brut: bytes) -> list[str]:
    """Noms des canaux supplémentaires, extraits du bloc de ressources.

    Format d'un bloc : ``8BIM``, identifiant sur 2 octets, nom en chaîne Pascal
    complétée à une longueur paire, taille sur 4 octets, données complétées à une
    longueur paire. Un bloc illisible n'est pas une erreur : on rend ce qu'on a
    su lire et l'opérateur nommera les canaux à la main.
    """
    noms: list[str] = []
    i = 0
    try:
        while i + 12 <= len(brut):
            if brut[i : i + 4] != b"8BIM":
                break
            identifiant = struct.unpack(">H", brut[i + 4 : i + 6])[0]
            i += 6
            longueur_nom = brut[i]
            i += 1 + longueur_nom
            if (1 + longueur_nom) % 2:
                i += 1
            taille = struct.unpack(">I", brut[i : i + 4])[0]
            i += 4
            donnees = brut[i : i + taille]
            i += taille + (taille % 2)
            if identifiant == RESSOURCE_NOMS_CANAUX:
                j = 0
                while j < len(donnees):
                    n = donnees[j]
                    j += 1
                    if n == 0:
                        break
                    noms.append(donnees[j : j + n].decode("latin-1"))
                    j += n
    except (IndexError, struct.error, UnicodeDecodeError):
        pass  # bloc tronqué ou d'une variante inconnue : on garde l'acquis
    return noms


@dataclass(slots=True)
class TiffMulticanal:
    """Un TIFF à canaux supplémentaires, décomposé."""

    base: np.ndarray  # (H, W, C) uint8 — les couches process
    mode: str  # RGB | CMYK | L
    tons_directs: dict[str, np.ndarray] = field(default_factory=dict)
    anonymes: list[np.ndarray] = field(default_factory=list)
    source: Path | None = None

    @property
    def a_des_tons_directs(self) -> bool:
        return bool(self.tons_directs or self.anonymes)

    def describe(self) -> str:
        détail = ", ".join(self.tons_directs) or "aucun"
        reste = f" + {len(self.anonymes)} sans nom" if self.anonymes else ""
        return f"{self.mode} + tons directs : {détail}{reste}"


def _tifffile():
    try:
        import tifffile  # noqa: PLC0415
    except ImportError:  # pragma: no cover - dépend de l'installation
        raise RipError(
            "ce TIFF contient des canaux supplémentaires (ton direct). Leur "
            "lecture requiert tifffile : pip install 'ripcore[images]'"
        ) from None
    return tifffile


def compte_de_canaux(chemin: str | Path) -> int:
    """Nombre d'échantillons par pixel, sans décoder l'image."""
    tifffile = _tifffile()
    try:
        with tifffile.TiffFile(str(chemin)) as tf:
            return int(tf.pages[0].samplesperpixel)
    except Exception:  # pas un TIFF, ou variante illisible
        return 0


def lire(chemin: str | Path) -> TiffMulticanal:
    """Lit un TIFF Photoshop et sépare couches process et tons directs."""
    tifffile = _tifffile()
    p = Path(chemin)
    try:
        with tifffile.TiffFile(str(p)) as tf:
            page = tf.pages[0]
            tableau = page.asarray()
            photometrie = str(getattr(page.photometric, "name", "")).lower()
            brut = page.tags[TAG_PHOTOSHOP].value if TAG_PHOTOSHOP in page.tags else b""
    except RipError:
        raise
    except Exception as exc:
        raise RipError(f"{p.name} : TIFF illisible ({exc})") from exc

    if tableau.ndim == 2:
        tableau = tableau[:, :, None]
    if tableau.dtype != np.uint8:
        # Même piège que côté Pillow : une image 16 bits doit être remise à
        # l'échelle, pas tronquée.
        maximum = 65535.0 if tableau.dtype == np.uint16 else float(
            max(tableau.max(), 1)
        )
        tableau = np.clip(tableau / maximum * 255.0, 0, 255).astype(np.uint8)

    mode = _PHOTOMETRIE.get(photometrie, "RGB")
    n_process = {"CMYK": 4, "RGB": 3, "L": 1}[mode]
    if tableau.shape[2] < n_process:
        raise RipError(
            f"{p.name} : {tableau.shape[2]} canaux pour une image {mode}, "
            f"{n_process} attendus"
        )

    base = tableau[:, :, :n_process]
    extras = [tableau[:, :, i] for i in range(n_process, tableau.shape[2])]

    noms = lire_noms_de_canaux(bytes(brut) if brut else b"")
    tons: dict[str, np.ndarray] = {}
    anonymes: list[np.ndarray] = []
    for i, canal in enumerate(extras):
        if i < len(noms) and noms[i].strip():
            tons[noms[i].strip()] = canal
        else:
            anonymes.append(canal)

    return TiffMulticanal(
        base=np.ascontiguousarray(base), mode=mode, tons_directs=tons,
        anonymes=anonymes, source=p,
    )
