"""Tons directs Photoshop : blanc et vernis dessinés dans le fichier.

L'atelier prépare ses sous-couches et son relief dans Photoshop, en couches de
ton direct, et exporte en TIFF. Deux choses doivent tenir :

* le fichier doit être **lisible** — Pillow refuse tout TIFF à plus de quatre
  canaux, c'est-à-dire tout fichier portant un ton direct ;
* la couche dessinée doit partir **telle quelle**, sans être remplacée par la
  sous-couche que le logiciel sait générer. Elle porte une intention — un
  vernis sélectif, un blanc volontairement débordant, un relief localisé —
  qu'aucun calcul ne devine.
"""

from __future__ import annotations

import json
import struct

import numpy as np
import pytest

from ripcore.inputs import photoshop
from ripcore.pipeline import JobSpec, run_job
from ripcore.profiles import MediaProfile, PrinterProfile

PROFILE_PATH = "profiles/friankor-i1600.toml"

tifffile = pytest.importorskip("tifffile", reason="lecture des TIFF multicanaux")


@pytest.fixture
def printer() -> PrinterProfile:
    return PrinterProfile.load(PROFILE_PATH)


def bloc_de_ressources(noms: list[str]) -> bytes:
    """Ressource 8BIM 1006 telle que Photoshop l'écrit : noms des canaux extra."""
    donnees = b"".join(bytes([len(n)]) + n.encode("latin-1") for n in noms)
    if len(donnees) % 2:
        donnees += b"\x00"
    return (
        b"8BIM"
        + struct.pack(">H", photoshop.RESSOURCE_NOMS_CANAUX)
        + b"\x00\x00"  # nom du bloc, chaîne Pascal vide complétée à une longueur paire
        + struct.pack(">I", len(donnees))
        + donnees
    )


def ecrire_tiff(chemin, base, couches: dict[str, np.ndarray], mode="separated"):
    """TIFF à canaux supplémentaires nommés, à la façon de Photoshop."""
    pile = np.dstack([base, *couches.values()])
    tifffile.imwrite(
        chemin,
        pile,
        photometric=mode,
        extrasamples=("unassalpha",) * len(couches),
        extratags=[(photoshop.TAG_PHOTOSHOP, "B", 0,
                    bloc_de_ressources(list(couches)), True)],
    )
    return chemin


def visuel(h=300, w=200):
    """Aplat cyan plein, sur lequel les couches viendront se poser."""
    cmjn = np.zeros((h, w, 4), np.uint8)
    cmjn[:, :, 0] = 180
    return cmjn


def rectangle(h, w, boite) -> np.ndarray:
    y0, x0, y1, x1 = boite
    couche = np.zeros((h, w), np.uint8)
    couche[y0:y1, x0:x1] = 255
    return couche


class TestLectureDesNoms:
    def test_noms_extraits_du_bloc_de_ressources(self):
        brut = bloc_de_ressources(["White", "Vernis sélectif"])
        assert photoshop.lire_noms_de_canaux(brut) == ["White", "Vernis sélectif"]

    def test_un_bloc_tronque_ne_fait_pas_echouer_la_lecture(self):
        """Mieux vaut une couche anonyme qu'un fichier refusé."""
        brut = bloc_de_ressources(["White", "Vernis"])[:-3]
        photoshop.lire_noms_de_canaux(brut)  # ne lève pas

    def test_un_bloc_qui_n_est_pas_du_photoshop_rend_une_liste_vide(self):
        assert photoshop.lire_noms_de_canaux(b"\x00" * 40) == []

    @pytest.mark.parametrize(
        "nom, encre",
        [
            ("White", "W"), ("blanc", "W"), ("BLANCHE", "W"), ("Sous-couche", "W"),
            ("Underbase", "W"), ("Vernis", "V"), ("varnish", "V"), ("Relief", "V"),
            ("Brillance", "V"),
        ],
    )
    def test_noms_usuels_reconnus(self, nom, encre):
        assert photoshop.encre_pour(nom) == encre

    def test_un_nom_inconnu_n_est_pas_devine(self):
        """Poser une encre au hasard coûte un tirage : mieux vaut ne rien poser."""
        assert photoshop.encre_pour("Pantone 485 C") is None

    def test_la_table_du_profil_prime(self):
        """Un atelier nomme ses couches comme il l'entend."""
        assert photoshop.encre_pour("Couche 1", {"Couche 1": "W"}) == "W"
        # Et elle peut contredire les correspondances usuelles.
        assert photoshop.encre_pour("Vernis", {"Vernis": "W"}) == "W"


class TestLectureDuFichier:
    def test_pillow_seul_ne_sait_pas_ouvrir_un_tiff_a_cinq_canaux(self, tmp_path):
        """La raison d'être de ce chemin de lecture, vérifiée plutôt que supposée."""
        from PIL import Image, UnidentifiedImageError

        src = ecrire_tiff(tmp_path / "cinq.tif", visuel(),
                          {"White": rectangle(300, 200, (0, 0, 150, 200))})
        with pytest.raises((UnidentifiedImageError, OSError, ValueError)):
            Image.open(src).load()

    def test_les_couches_sont_separees_des_couleurs(self, tmp_path):
        src = ecrire_tiff(
            tmp_path / "deux.tif", visuel(),
            {"White": rectangle(300, 200, (0, 0, 150, 200)),
             "Vernis": rectangle(300, 200, (150, 0, 300, 200))},
        )
        lecture = photoshop.lire(src)
        assert lecture.mode == "CMYK"
        assert lecture.base.shape == (300, 200, 4)
        assert list(lecture.tons_directs) == ["White", "Vernis"]
        assert lecture.tons_directs["White"].mean() / 255 == pytest.approx(0.5, abs=0.01)

    def test_une_couche_sans_nom_reste_anonyme(self, tmp_path):
        """Sans nom, rien ne dit quelle encre poser : la couche est mise de côté."""
        src = tmp_path / "sansnom.tif"
        tifffile.imwrite(
            src, np.dstack([visuel(), rectangle(300, 200, (0, 0, 150, 200))]),
            photometric="separated", extrasamples="unassalpha",
        )
        lecture = photoshop.lire(src)
        assert lecture.tons_directs == {}
        assert len(lecture.anonymes) == 1

    def test_le_compte_de_canaux_ne_decode_pas_l_image(self, tmp_path):
        src = ecrire_tiff(tmp_path / "c.tif", visuel(),
                          {"White": rectangle(300, 200, (0, 0, 150, 200))})
        assert photoshop.compte_de_canaux(src) == 5
        assert photoshop.compte_de_canaux(tmp_path / "absent.tif") == 0


class TestPipeline:
    """Ce qui compte au bout : l'encre déposée sur le mur."""

    def _job(self, printer, src, out, media=None, **kw):
        return run_job(JobSpec(
            source=src, output=out, printer=printer,
            media=media or MediaProfile(name="t", white_underbase=True),
            width_mm=30.0, **kw,
        ))

    def test_la_couche_dessinee_prime_sur_la_generation(self, tmp_path, printer):
        """Le blanc généré couvrirait tout ; le blanc dessiné ne couvre qu'un quart."""
        h, w = 300, 200
        blanc = rectangle(h, w, (0, 0, h // 2, w // 2))  # un quart de la surface
        src = ecrire_tiff(tmp_path / "avec.tif", visuel(h, w), {"White": blanc})

        result = self._job(printer, src, tmp_path / "avec.prn")
        assert result.coverage["W"] == pytest.approx(0.25, abs=0.02)
        assert result.spot_channels == {"White": "W"}

        # Le même visuel sans la couche : le blanc est généré, et couvre tout.
        sans = tmp_path / "sans.tif"
        tifffile.imwrite(sans, visuel(h, w), photometric="separated")
        temoin = self._job(printer, sans, tmp_path / "sans.prn")
        assert temoin.coverage["W"] > 0.95
        assert temoin.spot_channels == {}

    def test_les_niveaux_de_gris_de_la_couche_sont_respectes(self, tmp_path, printer):
        """C'est ce qui permet de doser le blanc : 50 % dessiné, 50 % déposé.

        L'atelier peint sa couche à 50 % sur une zone et à 100 % sur une autre
        pour obtenir un blanc translucide ici et couvrant là. La couche n'est
        donc pas un masque : c'est un dosage, et il doit traverser la chaîne
        sans être arrondi ni seuillé.
        """
        from ripcore.halftone import density_of
        from ripcore.prnfile import PrnReader

        niveaux_voulus = (0, 64, 128, 191, 255)
        h, w = 300, len(niveaux_voulus) * 40
        couche = np.zeros((h, w), np.uint8)
        for i, v in enumerate(niveaux_voulus):
            couche[:, i * 40 : (i + 1) * 40] = v
        # Aucune couleur : on isole le blanc de tout autre effet.
        src = ecrire_tiff(tmp_path / "degres.tif", np.zeros((h, w, 4), np.uint8),
                          {"White": couche})

        out = tmp_path / "degres.prn"
        result = self._job(printer, src, out)
        assert result.coverage["W"] == pytest.approx(
            np.mean(niveaux_voulus) / 255, abs=0.02
        )

        # Le RIP a tourné le visuel d'un quart de tour horaire : les colonnes
        # de la source sont devenues les lignes du fichier machine, dans le
        # même ordre (colonne de gauche → première ligne). On relit là-dedans.
        plan = PrnReader(out).read_all()[4:5]
        encre = density_of(
            plan, np.asarray(printer.drop_levels.densities, dtype=np.float32)
        )[0]
        bande = encre.shape[0] // len(niveaux_voulus)
        for i, voulu in enumerate(niveaux_voulus):
            zone = encre[i * bande + 8 : (i + 1) * bande - 8]
            assert zone.mean() == pytest.approx(voulu / 255, abs=0.02), (
                f"palier {voulu} mal restitué"
            )

    def test_les_couleurs_ne_sont_pas_touchees_par_la_couche(self, tmp_path, printer):
        """La couche supplémentaire ne doit pas être confondue avec du process."""
        h, w = 300, 200
        src = ecrire_tiff(tmp_path / "cyan.tif", visuel(h, w),
                          {"White": rectangle(h, w, (0, 0, h, w))})
        result = self._job(printer, src, tmp_path / "cyan.prn")
        assert result.coverage["C"] == pytest.approx(180 / 255, abs=0.03)
        assert result.coverage["M"] == pytest.approx(0.0, abs=0.005)

    def test_une_couche_inconnue_est_ignoree_et_signalee(self, tmp_path, printer):
        """Silence exclu : l'opérateur doit savoir que sa couche n'est pas partie."""
        h, w = 300, 200
        src = ecrire_tiff(tmp_path / "pantone.tif", visuel(h, w),
                          {"Pantone 485 C": rectangle(h, w, (0, 0, h, w))})
        result = self._job(printer, src, tmp_path / "pantone.prn")
        assert result.spot_channels == {"Pantone 485 C": ""}
        assert any("non reconnues" in a for a in result.warnings)
        # Le blanc reprend alors son chemin habituel : il est généré.
        assert result.coverage["W"] > 0.95

    def test_la_table_du_profil_support_rattrape_un_nom_maison(
        self, tmp_path, printer
    ):
        h, w = 300, 200
        src = ecrire_tiff(tmp_path / "maison.tif", visuel(h, w),
                          {"Couche 1": rectangle(h, w, (0, 0, h // 2, w))})
        media = MediaProfile(name="t", white_underbase=True,
                             spot_map={"Couche 1": "W"})
        result = self._job(printer, src, tmp_path / "maison.prn", media=media)
        assert result.spot_channels == {"Couche 1": "W"}
        assert result.coverage["W"] == pytest.approx(0.5, abs=0.02)

    def test_la_couche_suit_l_image_dans_la_rotation(self, tmp_path, printer):
        """Un ton direct décalé d'un pixel se voit : il tourne avec le visuel.

        La machine étant murale, le RIP applique déjà un quart de tour. On pose
        la couche sur une moitié franche et on vérifie qu'elle recouvre bien la
        même moitié du visuel — donc qu'elle a subi la même transformation.
        """
        h, w = 300, 200
        cmjn = np.zeros((h, w, 4), np.uint8)
        cmjn[: h // 2, :, 0] = 255  # cyan sur la moitié haute seulement
        src = ecrire_tiff(tmp_path / "moitie.tif", cmjn,
                          {"White": rectangle(h, w, (0, 0, h // 2, w))})
        out = tmp_path / "moitie.prn"
        self._job(printer, src, out)

        from ripcore.prnfile import PrnReader

        niveaux = PrnReader(out).read_all()
        cyan, blanc = niveaux[0] > 0, niveaux[4] > 0
        # Hors du remplissage de fin de ligne, blanc et cyan coïncident.
        utile = blanc.shape[1] // 2
        commun = (cyan[:, :utile] == blanc[:, :utile]).mean()
        assert commun > 0.97

    def test_une_encre_absente_de_la_machine_ne_passe_pas_pour_imprimee(
        self, tmp_path, printer
    ):
        """La presse n'a pas de vernis : le dire, plutôt que laisser croire."""
        h, w = 300, 200
        src = ecrire_tiff(tmp_path / "vernis.tif", visuel(h, w),
                          {"Vernis": rectangle(h, w, (0, 0, h, w))})
        result = self._job(printer, src, tmp_path / "vernis.prn")
        assert "V" not in printer.channel_names
        assert result.spot_channels == {"Vernis": ""}
        assert any("non reconnues" in a for a in result.warnings)

    def test_le_sens_de_la_couche_se_regle_au_profil(self, tmp_path, printer):
        """Photoshop n'écrit pas toujours 255 pour la pleine encre.

        Une couche lue à l'envers sort en négatif. Le sens est donc un réglage
        du profil support, pas une supposition enfouie dans le code.
        """
        from ripcore.profiles import SPOT_INVERSE

        h, w = 300, 200
        couche = np.full((h, w), 64, np.uint8)  # 25 % en lecture directe
        src = ecrire_tiff(tmp_path / "sens.tif", np.zeros((h, w, 4), np.uint8),
                          {"White": couche})

        direct = self._job(printer, src, tmp_path / "direct.prn")
        assert direct.coverage["W"] == pytest.approx(64 / 255, abs=0.02)

        inverse = self._job(
            printer, src, tmp_path / "inverse.prn",
            media=MediaProfile(name="t", white_underbase=True,
                               spot_polarity=SPOT_INVERSE),
        )
        assert inverse.coverage["W"] == pytest.approx(1 - 64 / 255, abs=0.02)

    def test_un_sens_mal_orthographie_est_refuse(self, tmp_path):
        """Une faute de frappe qui retomberait sur le défaut sortirait en négatif."""
        from ripcore.errors import ProfileError

        profil = tmp_path / "m.toml"
        profil.write_text('[media]\nname = "x"\nspot_polarity = "inversé"\n',
                          encoding="utf-8")
        with pytest.raises(ProfileError, match="spot_polarity"):
            MediaProfile.load(profil)

    def test_le_manifeste_consigne_les_couches(self, tmp_path, printer):
        """Devant un tirage raté, savoir d'où venait le blanc."""
        h, w = 300, 200
        src = ecrire_tiff(tmp_path / "m.tif", visuel(h, w),
                          {"White": rectangle(h, w, (0, 0, h, w)),
                           "Pantone 485 C": rectangle(h, w, (0, 0, h, w))})
        media = MediaProfile(name="t", white_underbase=True,
                             spot_map={"Ma couche": "V"})
        result = self._job(printer, src, tmp_path / "m.prn", media=media)
        manifeste = json.loads(result.manifest.read_text(encoding="utf-8"))
        assert manifeste["spot_channels"]["trouvés"] == {
            "White": "W", "Pantone 485 C": None,
        }
        assert manifeste["spot_channels"]["table"] == {"Ma couche": "V"}


class TestCommandeLayers:
    """`rip layers` : trancher le sens d'une couche sur un fichier de l'atelier."""

    def test_les_deux_lectures_sont_affichees(self, tmp_path, capsys):
        from ripcore.cli import main

        h, w = 300, 200
        couche = np.zeros((h, w), np.uint8)
        couche[: h // 2] = 128  # 50 % sur la moitié → 25 % de la surface
        src = ecrire_tiff(tmp_path / "x.tif", np.zeros((h, w, 4), np.uint8),
                          {"White": couche})

        assert main(["layers", str(src)]) == 0
        sortie = capsys.readouterr().out
        assert "White" in sortie and "encre W" in sortie
        assert "25.1 %" in sortie   # lecture directe
        assert "74.9 %" in sortie   # lecture inverse

    def test_un_fichier_sans_couche_le_dit(self, tmp_path, capsys):
        from ripcore.cli import main

        plat = tmp_path / "plat.tif"
        tifffile.imwrite(plat, np.zeros((50, 50, 4), np.uint8),
                         photometric="separated")
        assert main(["layers", str(plat)]) == 0
        assert "aucune couche de ton direct" in capsys.readouterr().out

    def test_un_fichier_illisible_ne_fait_pas_tomber_la_commande(
        self, tmp_path, capsys
    ):
        from ripcore.cli import main

        faux = tmp_path / "faux.tif"
        faux.write_bytes(b"pas un tiff")
        assert main(["layers", str(faux)]) == 0
        assert "pas un TIFF lisible" in capsys.readouterr().out
