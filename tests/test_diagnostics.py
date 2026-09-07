"""Comparer deux `.prn` pour lever l'ordre des canaux sans imprimer.

L'ordre des plans est marqué inconnu dans le profil, et la façon normale de le
lever coûte un tirage. Quand on possède un `.prn` produit par UltraPrint pour le
même visuel, la réponse est déjà dans les deux fichiers : c'est ce que ces tests
vérifient, sur des permutations qu'on fabrique nous-mêmes et dont on connaît
donc la réponse.
"""

from __future__ import annotations

import numpy as np
import pytest

from ripcore.diagnostics import correspondances, empreinte, rapport
from ripcore.prnfile import PrnReader, PrnWriter
from ripcore.profiles import PrinterProfile

PROFILE_PATH = "profiles/friankor-i1600.toml"


@pytest.fixture
def printer() -> PrinterProfile:
    return PrinterProfile.load(PROFILE_PATH)


def visuel(canaux: int = 5, h: int = 200, w: int = 160) -> np.ndarray:
    """Cinq plans bien distincts : sans quoi aucune correspondance n'a de sens."""
    rng = np.random.default_rng(7)
    niveaux = np.zeros((canaux, h, w), dtype=np.uint8)
    niveaux[0, : h // 2, : w // 2] = 3          # C : un quart en haut à gauche
    niveaux[1, h // 3 :, w // 3 :] = 2          # M : un pavé décalé
    niveaux[2, :, ::3] = 1                      # Y : des rayures
    niveaux[3] = (rng.random((h, w)) > 0.85) * 3  # K : un semis
    if canaux > 4:
        niveaux[4, 20:-20, 20:-20] = 3          # W : un cadre plein
    return niveaux


def ecrire(chemin, niveaux, *, dpi_x=720, dpi_y=900):
    with PrnWriter(chemin, dpi_x=dpi_x, dpi_y=dpi_y,
                   width_px=niveaux.shape[2], channels=niveaux.shape[0],
                   bits_per_pixel=2, pass_mode=0) as w:
        w.write_block(niveaux)
    return chemin


class TestCorrespondances:
    def test_un_fichier_se_reconnait_lui_meme(self, tmp_path):
        a = ecrire(tmp_path / "a.prn", visuel())
        couples = correspondances(empreinte(a), empreinte(a))
        assert all(i == j for i, j, _ in couples)
        assert all(r > 0.99 for _, _, r in couples)

    @pytest.mark.parametrize(
        "permutation",
        [(0, 2, 1, 3, 4),          # magenta et jaune échangés
         (2, 1, 0, 3, 4),          # cyan et jaune échangés
         (1, 2, 3, 0, 4),          # décalage circulaire des quatre couleurs
         (0, 1, 2, 4, 3)],         # noir et blanc échangés
    )
    def test_une_permutation_est_retrouvee(self, tmp_path, permutation):
        niveaux = visuel()
        a = ecrire(tmp_path / "ref.prn", niveaux)
        b = ecrire(tmp_path / "nous.prn", niveaux[list(permutation)])

        couples = correspondances(empreinte(a), empreinte(b))
        # Le plan i de la référence doit être retrouvé là où on l'a mis.
        attendu = {i: permutation.index(i) for i in range(len(permutation))}
        assert {i: j for i, j, _ in couples} == attendu
        assert all(r > 0.99 for _, _, r in couples)

    def test_le_rapport_nomme_l_ordre_a_ecrire(self, tmp_path, printer):
        niveaux = visuel()
        a = ecrire(tmp_path / "ref.prn", niveaux)
        b = ecrire(tmp_path / "nous.prn", niveaux[[0, 2, 1, 3, 4]])

        texte = rapport(empreinte(a), empreinte(b), printer)
        assert "ne sont PAS dans le même ordre" in texte
        assert "C, Y, M, K, W" in texte

    def test_un_ordre_correct_est_annonce_comme_tel(self, tmp_path, printer):
        a = ecrire(tmp_path / "ref.prn", visuel())
        texte = rapport(empreinte(a), empreinte(a), printer)
        assert "l'ordre est bon" in texte


class TestGeometrie:
    def test_l_ecart_de_taille_est_chiffre(self, tmp_path, printer):
        """Le cas vécu : BetterPrinter annonce une taille plus petite que voulu."""
        a = ecrire(tmp_path / "ref.prn", visuel(h=200, w=160))
        b = ecrire(tmp_path / "nous.prn", visuel(h=179, w=143))

        texte = rapport(empreinte(a), empreinte(b), printer)
        assert "rapport de pixels" in texte
        # Même facteur sur les deux axes : c'est une affaire de résolution.
        assert "question de résolution" in texte

    def test_la_couverture_est_celle_du_fichier(self, tmp_path):
        niveaux = np.zeros((5, 100, 80), dtype=np.uint8)
        niveaux[0, :50] = 3  # moitié du plan à la goutte pleine
        e = empreinte(ecrire(tmp_path / "x.prn", niveaux))
        assert e.couverture[0] == pytest.approx(0.5, abs=0.01)
        assert e.couverture[1] == pytest.approx(0.0, abs=1e-6)

    def test_la_taille_deduite_suit_les_dpi(self, tmp_path):
        e = empreinte(ecrire(tmp_path / "x.prn", visuel(h=900, w=720)))
        assert e.largeur_mm == pytest.approx(25.4, abs=0.2)   # 720 px à 720 dpi
        assert e.hauteur_mm == pytest.approx(25.4, abs=0.2)   # 900 px à 900 dpi


def test_un_prn_relu_apres_ecriture_donne_la_meme_empreinte(tmp_path):
    """L'empreinte se calcule en flux : elle doit valoir la lecture d'un bloc."""
    niveaux = visuel(h=700, w=300)
    chemin = ecrire(tmp_path / "x.prn", niveaux)
    e = empreinte(chemin)
    direct = PrnReader(chemin).read_all()
    attendu = (direct.astype(np.float32) / 3.0).mean(axis=(1, 2))
    assert e.couverture == pytest.approx(attendu, abs=0.01)
