"""Le dépôt doit pouvoir se cloner sur Windows.

Ce test existe à cause d'un vrai incident : un paquet avait été nommé ``prn``,
ce qui est parfaitement légitime sous Linux et **impossible sous Windows** —
``PRN`` est l'alias historique du port imprimante, réservé par le système au
même titre que ``CON`` ou ``NUL``. `git clone` échouait avec « invalid path »,
sur le PC d'atelier, pour un projet d'impression.

L'ironie mise à part : c'est le genre de défaut qu'aucun test fonctionnel ne
voit, puisque le code marche parfaitement — jusqu'au moment où il ne s'installe
pas là où il doit tourner.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Noms de périphériques réservés par Windows, quelle que soit l'extension.
WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul", "clock$"}
    | {f"com{i}" for i in range(10)}
    | {f"lpt{i}" for i in range(10)}
)

# Caractères interdits dans un nom de fichier Windows.
WINDOWS_FORBIDDEN_CHARS = set('<>:"|?*')


def tracked_paths() -> list[Path]:
    """Fichiers suivis par git — la liste exacte de ce qu'un clone doit écrire."""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(p) for p in out.stdout.split("\0") if p]


@pytest.fixture(scope="module")
def paths() -> list[Path]:
    found = tracked_paths()
    assert found, "aucun fichier suivi : le test ne vérifie rien"
    return found


def test_aucun_nom_reserve_windows(paths):
    """Aucun segment de chemin ne doit porter un nom de périphérique réservé."""
    coupables = [
        (p, part)
        for p in paths
        for part in p.parts
        if part.split(".")[0].lower() in WINDOWS_RESERVED
    ]
    assert not coupables, (
        "noms réservés sous Windows — le clone échouera avec « invalid path » :\n"
        + "\n".join(f"  {p} (segment « {part} »)" for p, part in coupables)
    )


def test_aucun_caractere_interdit(paths):
    coupables = [
        p for p in paths if WINDOWS_FORBIDDEN_CHARS & set(str(p))
    ]
    assert not coupables, f"caractères interdits sous Windows : {coupables}"


def test_aucun_point_ou_espace_final(paths):
    """Windows supprime silencieusement les points et espaces de fin."""
    coupables = [
        p for p in paths for part in p.parts if part != part.rstrip(". ")
    ]
    assert not coupables, f"point ou espace final : {coupables}"


def test_aucune_collision_de_casse(paths):
    """Windows et macOS ne distinguent pas la casse : deux fichiers qui ne
    diffèrent que par elle s'écrasent au clone."""
    seen: dict[str, Path] = {}
    collisions = []
    for p in paths:
        key = str(p).lower()
        if key in seen and seen[key] != p:
            collisions.append((seen[key], p))
        seen[key] = p
    assert not collisions, f"collisions de casse : {collisions}"
