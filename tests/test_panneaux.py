"""Découpe d'une fresque en panneaux.

Sur une machine murale, la largeur ne se limite pas : elle se découpe. Ces tests
vérifient les deux propriétés qui décident du rendu d'un raccord — la couverture
exacte du mur, et l'égalité des panneaux.
"""

from __future__ import annotations

import pytest

from ripcore.errors import RipError
from ripcore.panneaux import (
    decouper,
    nombre_de_panneaux,
    verifier_hauteur,
)

BANDE = 2000.0


class TestNombre:
    @pytest.mark.parametrize(
        "largeur,attendu",
        [(500, 1), (1999, 1), (2000, 1), (2001, 2), (4000, 2), (6000, 3),
         (12000, 6)],
    )
    def test_sans_recouvrement(self, largeur, attendu):
        assert nombre_de_panneaux(largeur, BANDE) == attendu

    def test_le_recouvrement_peut_ajouter_un_panneau(self):
        """Chaque chevauchement coûte de l'avance : à la limite, il en faut un de plus."""
        assert nombre_de_panneaux(4000, BANDE) == 2
        assert nombre_de_panneaux(4000, BANDE, recouvrement_mm=50) == 3


class TestDecoupe:
    @pytest.mark.parametrize("largeur", [800, 2000, 3500, 6000, 15000])
    @pytest.mark.parametrize("recouvrement", [0, 10, 40])
    def test_couvre_exactement_le_mur(self, largeur, recouvrement):
        """Le dernier panneau doit finir pile au bord : pas de mur nu, pas de débord."""
        panneaux = decouper(largeur, BANDE, recouvrement)
        assert panneaux[0].debut_mm == pytest.approx(0.0)
        assert panneaux[-1].fin_mm == pytest.approx(largeur, abs=0.01)

    @pytest.mark.parametrize("largeur", [3500, 6000, 15000])
    def test_panneaux_de_largeur_egale(self, largeur):
        """Un dernier panneau réduit à un ruban serait difficile à raccorder."""
        panneaux = decouper(largeur, BANDE, 20)
        largeurs = {round(p.largeur_mm, 3) for p in panneaux}
        assert len(largeurs) == 1

    @pytest.mark.parametrize("largeur", [2500, 6000, 15000])
    def test_aucun_panneau_ne_depasse_la_bande(self, largeur):
        for panneau in decouper(largeur, BANDE, 20):
            assert panneau.largeur_mm <= BANDE + 1e-6

    def test_recouvrement_effectif(self):
        panneaux = decouper(6000, BANDE, 30)
        for gauche, droite in zip(panneaux, panneaux[1:]):
            assert gauche.fin_mm - droite.debut_mm == pytest.approx(30, abs=0.01)

    def test_une_seule_position_si_ca_tient(self):
        panneaux = decouper(1500, BANDE, 20)
        assert len(panneaux) == 1
        assert panneaux[0].largeur_mm == pytest.approx(1500)

    def test_numerotation_lisible(self):
        panneaux = decouper(6000, BANDE)
        assert [p.numero for p in panneaux] == [1, 2, 3]
        assert all(p.total == 3 for p in panneaux)
        assert "Panneau 1/3" in panneaux[0].describe()


class TestRefus:
    def test_recouvrement_superieur_a_la_bande(self):
        with pytest.raises(RipError, match="n'avancerait jamais"):
            decouper(6000, BANDE, recouvrement_mm=2000)

    def test_largeur_nulle(self):
        with pytest.raises(RipError, match="largeur de fresque"):
            decouper(0, BANDE)

    def test_recouvrement_negatif(self):
        with pytest.raises(RipError, match="négatif"):
            decouper(3000, BANDE, -5)


class TestHauteur:
    def test_hauteur_dans_la_course(self):
        verifier_hauteur(1800, 2000)  # ne doit rien lever

    def test_hauteur_hors_course(self):
        with pytest.raises(RipError, match="la machine monte à"):
            verifier_hauteur(2600, 2000)

    def test_sans_course_declaree_on_ne_bloque_pas(self):
        """Un profil qui n'annonce pas sa course ne doit pas empêcher de travailler."""
        verifier_hauteur(9000, 0)
