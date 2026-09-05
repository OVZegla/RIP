"""Découpe d'une fresque en panneaux.

Une machine murale balaie une bande à la fois. Une fresque plus large que la
bande s'imprime en plusieurs positions successives : on imprime, on déplace la
machine, on imprime la suite.

Deux points décident de la qualité du raccord :

* **Le recouvrement.** Repositionner une machine à la main sur un chantier ne se
  fait pas au dixième de millimètre. Quelques millimètres de chevauchement
  absorbent l'écart. Sans recouvrement, la moindre erreur laisse un filet de mur
  nu entre deux panneaux — le défaut le plus visible qui soit sur une fresque.
* **La répartition.** On ne remplit pas les premiers panneaux à ras bord en
  laissant un ruban de 4 cm pour le dernier : un panneau étroit est plus difficile
  à raccorder, et le déséquilibre se voit. La découpe répartit donc la largeur
  également entre tous les panneaux.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import RipError


@dataclass(frozen=True, slots=True)
class Panneau:
    """Un panneau de la fresque, repéré sur le mur."""

    index: int  # 0 pour le panneau le plus à gauche
    total: int
    debut_mm: float  # position du bord gauche sur la fresque complète
    largeur_mm: float

    @property
    def fin_mm(self) -> float:
        return self.debut_mm + self.largeur_mm

    @property
    def numero(self) -> int:
        return self.index + 1

    def describe(self) -> str:
        return (
            f"Panneau {self.numero}/{self.total} — "
            f"{self.largeur_mm:.0f} mm, de {self.debut_mm:.0f} à {self.fin_mm:.0f} mm"
        )


def nombre_de_panneaux(
    largeur_mm: float, bande_mm: float, recouvrement_mm: float = 0.0
) -> int:
    """Combien de positions de machine pour couvrir cette largeur."""
    _verifier(largeur_mm, bande_mm, recouvrement_mm)
    if largeur_mm <= bande_mm:
        return 1
    avance = bande_mm - recouvrement_mm
    return max(1, math.ceil((largeur_mm - recouvrement_mm) / avance - 1e-9))


def decouper(
    largeur_mm: float, bande_mm: float, recouvrement_mm: float = 0.0
) -> list[Panneau]:
    """Découpe la fresque en panneaux de largeur égale, avec recouvrement.

    Le dernier panneau ne se retrouve jamais réduit à un ruban : la largeur est
    répartie également, quitte à ce que chaque panneau soit un peu plus étroit
    que la bande machine.
    """
    _verifier(largeur_mm, bande_mm, recouvrement_mm)
    n = nombre_de_panneaux(largeur_mm, bande_mm, recouvrement_mm)
    if n == 1:
        return [Panneau(0, 1, 0.0, largeur_mm)]

    # largeur_totale = n × largeur_panneau − (n−1) × recouvrement
    largeur_panneau = (largeur_mm + (n - 1) * recouvrement_mm) / n
    if largeur_panneau > bande_mm + 1e-6:  # garde-fou : ne doit pas arriver
        raise RipError(
            f"découpe impossible : {largeur_panneau:.0f} mm par panneau pour une "
            f"bande de {bande_mm:.0f} mm"
        )
    avance = largeur_panneau - recouvrement_mm
    return [
        Panneau(i, n, round(i * avance, 4), round(largeur_panneau, 4))
        for i in range(n)
    ]


def verifier_hauteur(hauteur_mm: float, hauteur_max_mm: float) -> None:
    """La hauteur est une limite dure : la colonne ne s'allonge pas.

    Contrairement à la largeur, aucun découpage automatique ne la contourne —
    superposer deux registres demande de recaler la machine en hauteur, ce qui
    est une décision d'opérateur, pas un réglage de logiciel.
    """
    if hauteur_max_mm > 0 and hauteur_mm > hauteur_max_mm + 1e-6:
        raise RipError(
            f"Cette fresque fait {hauteur_mm:.0f} mm de haut, la machine monte à "
            f"{hauteur_max_mm:.0f} mm. Réduisez la hauteur, ou découpez le visuel "
            f"en deux registres superposés."
        )


def _verifier(largeur_mm: float, bande_mm: float, recouvrement_mm: float) -> None:
    if largeur_mm <= 0:
        raise RipError(f"largeur de fresque invalide : {largeur_mm} mm")
    if bande_mm <= 0:
        raise RipError(f"largeur de bande invalide : {bande_mm} mm")
    if recouvrement_mm < 0:
        raise RipError(f"recouvrement négatif : {recouvrement_mm} mm")
    if recouvrement_mm >= bande_mm:
        raise RipError(
            f"recouvrement de {recouvrement_mm:.0f} mm pour une bande de "
            f"{bande_mm:.0f} mm : la machine n'avancerait jamais"
        )
