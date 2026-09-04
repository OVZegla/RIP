"""Tests de la logique de l'interface, sans Tk.

L'affichage n'est pas testé ici — il l'est par un parcours à l'écran. Ce qui
est testé, c'est tout ce qui décide : réécriture des profils, traduction des
messages, fabrication d'un travail à partir des choix de l'opérateur.

Le test le plus important est ``test_reordonner_les_encres`` : c'est
l'opération que fait le test d'impression n° 1, celle qui empêche la presse de
poser le blanc à la place du noir.
"""

from __future__ import annotations

import tomllib

import pytest

from ripcore.errors import ProfileError, RipError
from ripcore.profiles import DropLevels, MediaProfile, PrinterProfile
from ripcore.profiles_io import (
    render_profile,
    reorder_channels,
    save_profile,
)
from ripcore.ui import textes
from ripcore.ui.session import Session, _lire_manifeste

PROFIL = "profiles/friankor-i1600.toml"


@pytest.fixture
def profil() -> PrinterProfile:
    return PrinterProfile.load(PROFIL)


class TestEcritureProfil:
    def test_aller_retour(self, profil):
        """Un profil réécrit doit se relire à l'identique."""
        relu = PrinterProfile.from_dict(tomllib.loads(render_profile(profil)))
        assert relu.channel_names == profil.channel_names
        assert relu.bits_per_pixel == profil.bits_per_pixel
        assert relu.pass_mode_by_dpi_y == profil.pass_mode_by_dpi_y
        assert relu.drop_levels.densities == pytest.approx(
            profil.drop_levels.densities
        )
        assert relu.ink_limit_total == pytest.approx(profil.ink_limit_total)
        assert relu.max_width_mm == pytest.approx(profil.max_width_mm)
        assert relu.channel_order_verified == profil.channel_order_verified

    def test_les_nombres_restent_des_flottants(self, profil):
        """TOML lirait « 0 » comme un entier, ce que DropLevels refuse."""
        données = tomllib.loads(render_profile(profil))
        for valeur in données["drop_levels"]["densities"]:
            assert isinstance(valeur, float)
        assert isinstance(données["ink_limits"]["total"], float)

    def test_sauvegarde_avant_ecrasement(self, tmp_path, profil):
        cible = tmp_path / "presse.toml"
        cible.write_text("# version précédente\n", encoding="utf-8")
        save_profile(profil, cible)
        assert cible.with_suffix(".toml.bak").read_text().startswith("# version")
        assert PrinterProfile.load(cible).channel_names == profil.channel_names

    def test_ecriture_atomique(self, tmp_path, profil):
        cible = tmp_path / "presse.toml"
        save_profile(profil, cible)
        assert not list(tmp_path.glob("*.part"))

    def test_refuse_un_profil_qui_ne_se_relit_pas(self, tmp_path, profil):
        """Garde-fou : on n'écrase jamais un profil valide par un profil cassé."""
        casse = PrinterProfile(
            name='guillemet " dans le nom',  # casserait le TOML produit
            head=profil.head,
            bits_per_pixel=profil.bits_per_pixel,
            channels=profil.channels,
            pass_mode_by_dpi_y=dict(profil.pass_mode_by_dpi_y),
            drop_levels=profil.drop_levels,
            ink_limit_channel={},
            ink_limit_total=profil.ink_limit_total,
            max_width_mm=profil.max_width_mm,
        )
        cible = tmp_path / "presse.toml"
        save_profile(profil, cible)
        avant = cible.read_text(encoding="utf-8")
        with pytest.raises(Exception):
            save_profile(casse, cible)
        assert cible.read_text(encoding="utf-8") == avant


class TestReordonnerLesEncres:
    def test_reordonner_les_encres(self, profil):
        """Le résultat du test d'impression n° 1."""
        nouveau = reorder_channels(profil, ["M", "C", "Y", "K", "W"])
        assert nouveau.channel_names == ("M", "C", "Y", "K", "W")
        assert nouveau.channel_order_verified is True
        # Les rôles suivent leur encre : le blanc reste le blanc.
        assert nouveau.channels[4].role == "white"
        assert nouveau.channels[0].role == "process"

    def test_ordre_incomplet_refuse(self, profil):
        with pytest.raises(ProfileError, match="une fois et une seule"):
            reorder_channels(profil, ["C", "M", "Y", "K"])

    def test_doublon_refuse(self, profil):
        with pytest.raises(ProfileError, match="une fois et une seule"):
            reorder_channels(profil, ["C", "C", "Y", "K", "W"])

    def test_encre_inconnue_refusee(self, profil):
        with pytest.raises(ProfileError):
            reorder_channels(profil, ["C", "M", "Y", "K", "ROSE"])

    def test_le_reste_du_profil_est_intact(self, profil):
        nouveau = reorder_channels(profil, ["W", "K", "Y", "M", "C"])
        assert nouveau.ink_limit_total == profil.ink_limit_total
        assert nouveau.pass_mode_by_dpi_y == profil.pass_mode_by_dpi_y
        assert nouveau.drop_levels.densities == profil.drop_levels.densities
        assert nouveau.max_width_mm == profil.max_width_mm


class TestTextes:
    def test_avertissements_traduits(self):
        """Aucun terme technique ne doit atteindre l'opérateur."""
        profil = PrinterProfile.load(PROFIL)
        for brut in profil.warnings():
            traduit = textes.traduire_avertissement(brut)
            assert traduit != brut, f"non traduit : {brut}"
            for mot in ("canal", "canaux", "linéarisation", "densitométrique", "RIP"):
                assert mot not in traduit, f"terme technique dans : {traduit}"

    def test_message_inconnu_passe_tel_quel(self):
        assert textes.traduire_avertissement("truc inédit") == "truc inédit"

    def test_encres_nommees_en_clair(self):
        assert textes.nom_encre("C") == "Cyan (bleu)"
        assert textes.nom_encre("W") == "Blanc"
        assert textes.nom_encre("XX") == "XX"  # repli sur le code

    def test_pas_de_jargon_dans_les_libelles_visibles(self):
        """Balayage large : les termes d'ingénieur n'ont rien à faire à l'écran."""
        interdits = ("tramage", "linéarisation", "raster", "dpi", "TAC", "ICC",
                     "canal", "bitmap", "halftone")
        visibles = [
            textes.IMPRESSION_TITRE, textes.IMPRESSION_QUALITE,
            textes.IMPRESSION_GRAIN, textes.IMPRESSION_BLANC,
            textes.IMPRESSION_BLANC_AIDE, textes.MACHINE_ENCRE_MAX,
            textes.MACHINE_ENCRE_MAX_AIDE, textes.TESTS_INTRO,
            *(t["titre"] for t in textes.TESTS),
            *(t["detail"] for t in textes.TESTS),
            *(t["resume"] for t in textes.TESTS),
        ]
        for texte in visibles:
            for mot in interdits:
                assert mot not in texte, f"« {mot} » dans : {texte[:60]}…"

    def test_chaque_test_est_complet(self):
        for test in textes.TESTS:
            for champ in ("cle", "numero", "titre", "resume", "detail", "duree",
                          "bouton", "saisie"):
                assert test.get(champ), f"{test.get('cle')} : {champ} manquant"


class TestSession:
    @pytest.fixture
    def session(self, tmp_path) -> Session:
        s = Session.ouvrir(PROFIL)
        s.dossier_sortie = tmp_path / "sorties"
        s.dossier_tests = tmp_path / "mires"
        s.dossier_sortie.mkdir()
        s.dossier_tests.mkdir()
        return s

    def test_ouvre_le_profil_par_defaut(self):
        assert Session.ouvrir(PROFIL).profil.name == "FRIANKOR I1600"

    def test_avertissements_en_clair(self, session):
        messages = session.avertissements()
        assert messages
        assert all("canal" not in m for m in messages)
        assert session.presse_reglee is False

    def test_fabrication_d_un_travail(self, session, tmp_path):
        source = tmp_path / "visuel.png"
        source.write_bytes(b"peu importe, seule l'existence compte ici")
        spec = session.preparer_job(
            source, largeur_mm=400, hauteur_mm=None, dpi_x=720, dpi_y=900,
            grain="bluenoise", rotation=0, miroir=False, support=None, blanc=True,
        )
        assert spec.width_mm == 400
        assert spec.output.parent == session.dossier_sortie
        assert spec.output.name == "visuel.prn"
        assert spec.media.white_underbase is True

    def test_fichier_absent_refuse_en_clair(self, session, tmp_path):
        with pytest.raises(RipError, match="n'existe plus"):
            session.preparer_job(
                tmp_path / "fantome.png", largeur_mm=100, hauteur_mm=None,
                dpi_x=720, dpi_y=900, grain="bluenoise", rotation=0,
                miroir=False, support=None, blanc=False,
            )

    def test_trop_large_refuse_en_clair(self, session, tmp_path):
        source = tmp_path / "grand.png"
        source.write_bytes(b"x")
        with pytest.raises(RipError, match="plus large que"):
            session.preparer_job(
                source, largeur_mm=5000, hauteur_mm=None, dpi_x=720, dpi_y=900,
                grain="bluenoise", rotation=0, miroir=False, support=None,
                blanc=False,
            )

    def test_le_blanc_ne_modifie_pas_le_profil_support(self, session, tmp_path):
        source = tmp_path / "v.png"
        source.write_bytes(b"x")
        support = MediaProfile(name="rigide", white_underbase=True)
        spec = session.preparer_job(
            source, largeur_mm=100, hauteur_mm=None, dpi_x=720, dpi_y=900,
            grain="bluenoise", rotation=0, miroir=False, support=support,
            blanc=False,
        )
        assert spec.media.white_underbase is False
        assert support.white_underbase is True  # l'original est intact

    def test_historique_vide_au_depart(self, session):
        assert session.historique() == []

    def test_historique_ignore_un_manifeste_illisible(self, session):
        (session.dossier_sortie / "casse.prn.json").write_text("{pas du json")
        assert session.historique() == []


def test_manifeste_illisible_ne_leve_pas(tmp_path):
    fichier = tmp_path / "x.prn.json"
    fichier.write_text('{"geometry": {}}', encoding="utf-8")
    assert _lire_manifeste(fichier) is None


def test_drop_levels_relus_depuis_un_profil_ecrit(tmp_path, profil):
    """Une échelle calibrée doit survivre à l'aller-retour disque."""
    mesure = PrinterProfile(
        name=profil.name, head=profil.head,
        bits_per_pixel=profil.bits_per_pixel, channels=profil.channels,
        pass_mode_by_dpi_y=dict(profil.pass_mode_by_dpi_y),
        drop_levels=DropLevels((0.0, 0.239913, 0.610021, 1.0), calibrated=True),
        ink_limit_channel=dict(profil.ink_limit_channel),
        ink_limit_total=profil.ink_limit_total,
        max_width_mm=profil.max_width_mm,
    )
    cible = tmp_path / "presse.toml"
    save_profile(mesure, cible)
    relu = PrinterProfile.load(cible)
    assert relu.drop_levels.calibrated is True
    assert relu.drop_levels.densities == pytest.approx((0.0, 0.239913, 0.610021, 1.0))
