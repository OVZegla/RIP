"""Tests de la chaîne couleur, de la calibration et du pipeline complet.

Le test central est ``TestCalibration`` : on simule une machine dont on connaît
la réponse exacte, on fabrique les mesures qu'elle produirait, et on vérifie que
la calibration retrouve les paramètres de départ. C'est la seule façon de savoir
que la boucle de calibration est juste avant d'avoir consommé de l'encre.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from ripcore.blocks import block_means
from ripcore.calibration import (
    build_linearization,
    drop_densities,
    read_measurements,
)
from ripcore.color import (
    Linearization,
    TransferCurve,
    apply_luts,
    limit_per_channel,
    limit_total,
    naive_rgb_to_cmyk,
    underbase,
)
from ripcore.color.inklimit import PRESERVE_BLACK
from ripcore.errors import CalibrationError, ProfileError, RipError
from ripcore.halftone import BlueNoiseHalftoner, density_of
from ripcore.pipeline import JobSpec, run_job
from ripcore.prnfile import PrnReader, validate_prn
from ripcore.profiles import Channel, DropLevels, MediaProfile, PrinterProfile

PROFILE_PATH = "profiles/friankor-i1600.toml"

# Réponse d'une machine fictive mais réaliste : gouttes non linéaires, et une
# courbe de réponse qui bouche les clairs (le défaut classique en jet d'encre).
TRUE_DROPS = (0.0, 0.24, 0.61, 1.0)
SOLID_DENSITY = 1.45


def _machine_response(coverage: np.ndarray) -> np.ndarray:
    """Densité optique mesurée pour une couverture d'encre donnée.

    Murray–Davies avec engraissement : la machine dépose plus que demandé dans
    les tons moyens.
    """
    cov = np.clip(coverage, 0.0, 1.0)
    gained = cov ** 0.72  # engraissement de point
    reflect = 1.0 - gained * (1.0 - 10.0**-SOLID_DENSITY)
    return -np.log10(np.maximum(reflect, 1e-9))


@pytest.fixture
def printer() -> PrinterProfile:
    return PrinterProfile.load(PROFILE_PATH)


class TestProfiles:
    def test_chargement(self, printer):
        assert printer.channel_names == ("C", "M", "Y", "K", "W")
        assert printer.bits_per_pixel == 2
        assert printer.process_mask.tolist() == [True, True, True, True, False]

    def test_avertissements_tant_que_non_verifie(self, printer):
        assert any("ordre des canaux" in w for w in printer.warnings())
        assert any("goutte" in w for w in printer.warnings())

    def test_pass_mode_refuse_d_extrapoler(self, printer):
        assert printer.pass_mode(900) == 0
        assert printer.pass_mode(1200) == 4
        with pytest.raises(ProfileError, match="pass_mode inconnu"):
            printer.pass_mode(600)

    def test_drop_levels_doivent_etre_croissants(self):
        with pytest.raises(ProfileError, match="croissante"):
            DropLevels((0.0, 0.6, 0.3, 1.0))

    def test_drop_levels_bornes(self):
        with pytest.raises(ProfileError, match="niveau 0"):
            DropLevels((0.1, 0.5, 1.0))
        with pytest.raises(ProfileError, match="niveau max"):
            DropLevels((0.0, 0.5, 0.9))

    def test_role_inconnu_refuse(self):
        with pytest.raises(ProfileError, match="rôle"):
            Channel(name="X", role="fantaisie")

    def test_nombre_de_niveaux_coherent_avec_bpp(self, printer):
        with pytest.raises(ProfileError, match="implique 4 niveaux"):
            PrinterProfile(
                name="x", head="", bits_per_pixel=2, channels=printer.channels,
                pass_mode_by_dpi_y={900: 0},
                drop_levels=DropLevels((0.0, 0.5, 1.0)),
                ink_limit_channel={}, ink_limit_total=2.0, max_width_mm=100.0,
            )


class TestCurves:
    def test_monotonie_imposee(self):
        """Le bruit de mesure ne doit pas produire d'inversion dans un dégradé."""
        curve = TransferCurve(
            np.array([0.0, 0.25, 0.5, 0.75, 1.0]),
            np.array([0.0, 0.30, 0.28, 0.70, 1.0]),  # creux à 0,5
        )
        assert np.all(np.diff(curve.y) >= 0)

    def test_identite(self):
        curve = TransferCurve.identity()
        v = np.linspace(0, 1, 17, dtype=np.float32)
        assert np.allclose(curve.apply(v), v, atol=1e-6)

    def test_domaine_impose(self):
        with pytest.raises(CalibrationError, match=r"\[0, 1\]"):
            TransferCurve(np.array([0.1, 1.0]), np.array([0.0, 1.0]))

    def test_application_par_lut(self):
        lin = Linearization({"C": TransferCurve(np.array([0.0, 1.0]),
                                                np.array([0.0, 0.5]))})
        luts = lin.luts(("C",))
        out = apply_luts(np.full((1, 4, 4), 0.8, np.float32), luts)
        assert out.mean() == pytest.approx(0.4, abs=1e-3)

    def test_persistance(self, tmp_path):
        lin = Linearization(
            {"C": TransferCurve(np.linspace(0, 1, 5), np.array([0, 0.1, 0.4, 0.8, 1.0]))},
            notes="essai",
        )
        path = tmp_path / "lin.json"
        lin.save(path)
        again = Linearization.load(path)
        assert again.notes == "essai"
        assert np.allclose(again.for_channel("C").y, lin.for_channel("C").y)

    def test_format_inconnu_refuse(self, tmp_path):
        path = tmp_path / "faux.json"
        path.write_text(json.dumps({"format": "autre", "curves": {}}))
        with pytest.raises(CalibrationError, match="non reconnu"):
            Linearization.load(path)


class TestInkLimits:
    def test_limite_par_canal(self):
        ink = np.ones((2, 4, 4), dtype=np.float32)
        out = limit_per_channel(ink, np.array([0.9, 0.5], dtype=np.float32))
        assert out[0].max() == pytest.approx(0.9)
        assert out[1].max() == pytest.approx(0.5)

    def test_limite_totale_proportionnelle(self):
        ink = np.full((4, 2, 2), 0.9, dtype=np.float32)  # somme = 3,6
        out = limit_total(ink, 2.0)
        assert out.sum(axis=0).max() == pytest.approx(2.0, abs=1e-5)
        # Le rapport entre canaux est conservé : pas de virage de teinte.
        assert out[0] == pytest.approx(out[1])

    def test_limite_totale_ne_touche_pas_ce_qui_est_sous_la_limite(self):
        ink = np.full((4, 2, 2), 0.2, dtype=np.float32)
        assert np.array_equal(limit_total(ink, 2.0), ink)

    def test_preserve_black(self):
        ink = np.array([[[0.9]], [[0.9]], [[0.9]], [[0.9]]], dtype=np.float32)
        protected = np.array([False, False, False, True])
        out = limit_total(ink, 2.0, strategy=PRESERVE_BLACK, protected=protected)
        assert out[3] == pytest.approx(0.9)  # noir intact
        assert out.sum(axis=0).max() == pytest.approx(2.0, abs=1e-5)

    def test_strategie_inconnue_refusee(self):
        with pytest.raises(RipError, match="stratégie"):
            limit_total(np.zeros((2, 1, 1), np.float32), 1.0, strategy="au-pif")


class TestWhite:
    def test_par_defaut_le_blanc_couvre_toute_la_surface(self):
        """Sans transparence, le visuel est un rectangle plein.

        Ses zones blanches font partie de l'image : les laisser nues montrerait
        la brique ou le béton à la place du blanc voulu.
        """
        ink = np.zeros((4, 20, 20), dtype=np.float32)
        ink[0, 5:15, 5:15] = 0.5
        w = underbase(ink, choke_px=0)
        assert w[10, 10] == pytest.approx(1.0)
        assert w[0, 0] == pytest.approx(1.0)  # y compris hors du dessin

    def test_mode_encre_suit_le_dessin(self):
        """Pour poser une forme sur un mur sans rectangle blanc autour."""
        ink = np.zeros((4, 20, 20), dtype=np.float32)
        ink[0, 5:15, 5:15] = 0.5
        w = underbase(ink, choke_px=0, mode="encre")
        assert w[10, 10] == pytest.approx(1.0)
        assert w[0, 0] == pytest.approx(0.0)

    def test_choke_retracte_les_bords(self):
        ink = np.zeros((4, 20, 20), dtype=np.float32)
        ink[0, 5:15, 5:15] = 1.0
        sans = underbase(ink, choke_px=0, mode="encre")
        avec = underbase(ink, choke_px=2, mode="encre")
        assert avec.sum() < sans.sum()
        assert avec[10, 10] == pytest.approx(1.0)  # le cœur reste plein
        assert avec[5, 5] == pytest.approx(0.0)  # le bord est retiré

    def test_mode_de_blanc_inconnu_refuse(self):
        with pytest.raises(RipError, match="mode de blanc"):
            underbase(np.zeros((4, 4, 4), dtype=np.float32), mode="fantaisie")

    def test_jaune_clair_seul_declenche_du_blanc(self):
        """Le max, pas la somme : sinon un aplat jaune pâle sort sans blanc."""
        ink = np.zeros((4, 8, 8), dtype=np.float32)
        ink[2] = 0.05
        assert underbase(ink, choke_px=0, mode="encre").mean() == pytest.approx(1.0)

    def test_alpha_prime_sur_la_couverture(self):
        ink = np.zeros((4, 10, 10), dtype=np.float32)
        alpha = np.zeros((10, 10), dtype=np.float32)
        alpha[2:8, 2:8] = 1.0
        w = underbase(ink, choke_px=0, alpha=alpha)
        assert w[5, 5] == pytest.approx(1.0)
        assert w[0, 0] == pytest.approx(0.0)


class TestCalibration:
    """Boucle fermée : machine simulée → mesures → calibration → vérification."""

    def _drop_measurements(self, tmp_path):
        paper = 0.06
        rows = ["channel,kind,value,measurement"]
        for ch in ("C", "M"):
            for level, cov in enumerate(TRUE_DROPS):
                # Un aplat non tramé de niveau k dépose la couverture TRUE_DROPS[k]
                # sans engraissement supplémentaire lié au tramage.
                reflect = 1.0 - cov * (1.0 - 10.0**-SOLID_DENSITY)
                d = paper + -np.log10(max(reflect, 1e-9))
                rows.append(f"{ch},level,{level},{d:.4f}")
        path = tmp_path / "gouttes.csv"
        path.write_text("\n".join(rows) + "\n")
        return path

    def test_retrouve_l_echelle_des_gouttes(self, tmp_path):
        path = self._drop_measurements(tmp_path)
        got = drop_densities(read_measurements(path), 4)
        assert got == pytest.approx(TRUE_DROPS, abs=0.005), (
            f"échelle reconstruite {got}, attendue {TRUE_DROPS}"
        )

    def test_niveau_zero_obligatoire(self, tmp_path):
        path = tmp_path / "sans-zero.csv"
        path.write_text(
            "channel,kind,value,measurement\n"
            "C,level,1,0.4\nC,level,2,0.9\nC,level,3,1.4\n"
        )
        with pytest.raises(CalibrationError, match="niveau 0"):
            drop_densities(read_measurements(path), 4)

    def test_linearisation_corrige_l_engraissement(self, tmp_path):
        paper = 0.06
        tones = np.linspace(0, 1, 21)
        rows = ["channel,kind,value,measurement"]
        for tone in tones:
            rows.append(f"C,tone,{tone:.4f},{paper + _machine_response(tone):.4f}")
        path = tmp_path / "lin.csv"
        path.write_text("\n".join(rows) + "\n")

        lin = build_linearization(read_measurements(path))
        curve = lin.for_channel("C")

        # Après correction, une demande de x % doit mesurer x % de couverture.
        for target in (0.2, 0.4, 0.5, 0.6, 0.8):
            asked = float(curve.apply(np.array([target], dtype=np.float32))[0])
            obtained = asked**0.72  # la machine engraisse
            assert obtained == pytest.approx(target, abs=0.02), (
                f"{target:.0%} demandé → {obtained:.1%} obtenu après linéarisation"
            )

    def test_mesures_plates_refusees(self, tmp_path):
        path = tmp_path / "plat.csv"
        path.write_text(
            "channel,kind,value,measurement\n"
            "C,tone,0,0.06\nC,tone,0.5,0.06\nC,tone,1,0.06\n"
        )
        with pytest.raises(CalibrationError, match="ne se distingue pas"):
            build_linearization(read_measurements(path))

    def test_colonnes_manquantes_refusees(self, tmp_path):
        path = tmp_path / "casse.csv"
        path.write_text("channel,value\nC,0\n")
        with pytest.raises(CalibrationError, match="colonnes manquantes"):
            read_measurements(path)


class TestBlocks:
    def test_moyenne_par_bloc(self):
        densities = np.array([0.0, 1.0], dtype=np.float32)
        band = np.zeros((1, 4, 4), dtype=np.uint8)
        band[0, :2, :2] = 1  # un quart des pixels
        out = list(block_means([band], densities, block=4))
        assert out[0].shape == (1, 1, 1)
        assert out[0][0, 0, 0] == pytest.approx(0.25)

    def test_report_de_lignes_entre_bandes(self):
        """Aucune ligne ne doit échapper au contrôle, même en fin de raster."""
        densities = np.array([0.0, 1.0], dtype=np.float32)
        bands = [np.ones((1, 3, 8), dtype=np.uint8) for _ in range(3)]  # 9 lignes
        out = list(block_means(bands, densities, block=4))
        total_lines = sum(b.shape[1] * 4 for b in out[:-1]) + 1
        assert total_lines >= 9
        assert all(np.allclose(b, 1.0) for b in out)


class TestEndToEnd:
    def _make_source(self, tmp_path, size=(120, 90)):
        from PIL import Image, ImageDraw

        im = Image.new("RGB", size, (255, 255, 255))
        d = ImageDraw.Draw(im)
        d.rectangle([10, 10, 60, 50], fill=(0, 120, 200))
        d.rectangle([60, 40, 110, 80], fill=(200, 40, 0))
        path = tmp_path / "src.png"
        im.save(path, dpi=(300, 300))
        return path

    def test_job_complet(self, tmp_path, printer):
        src = self._make_source(tmp_path)
        out = tmp_path / "job.prn"
        media = MediaProfile(name="test", white_underbase=True)
        result = run_job(
            JobSpec(
                source=src, output=out, printer=printer, media=media,
                dpi_x=720, dpi_y=900, width_mm=40.0,
            )
        )
        assert out.is_file()
        assert result.width_mm == pytest.approx(40.0, abs=0.2)

        report = validate_prn(out, printer)
        assert report.ok, report.render(verbose=True)
        # Sans transparence, le blanc couvre toute la surface imprimée.
        assert result.coverage["W"] == pytest.approx(1.0, abs=0.02)

    def test_manifeste_porte_la_largeur_utile(self, tmp_path, printer):
        """Le .prn ne conserve pas la largeur réelle : le manifeste, si."""
        src = self._make_source(tmp_path)
        out = tmp_path / "job.prn"
        result = run_job(
            JobSpec(source=src, output=out, printer=printer,
                    media=MediaProfile(name="t"), width_mm=37.3)
        )
        manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
        geo = manifest["geometry"]
        assert geo["width_px"] == result.width_px
        assert geo["padded_width_px"] >= geo["width_px"]
        assert PrnReader(out).header.width_px == geo["padded_width_px"]

    def test_resolution_non_tabulee_refusee_avant_tout_calcul(self, tmp_path, printer):
        src = self._make_source(tmp_path)
        out = tmp_path / "jamais.prn"
        with pytest.raises(ProfileError, match="pass_mode inconnu"):
            run_job(
                JobSpec(source=src, output=out, printer=printer,
                        media=MediaProfile(name="t"), dpi_y=600, width_mm=20.0)
            )
        assert not out.exists()

    def test_rotation_echange_les_dimensions(self, tmp_path, printer):
        src = self._make_source(tmp_path, size=(200, 100))
        media = MediaProfile(name="t")
        droit = run_job(JobSpec(source=src, output=tmp_path / "a.prn",
                                printer=printer, media=media, width_mm=50.0))
        tourne = run_job(JobSpec(source=src, output=tmp_path / "b.prn",
                                 printer=printer, media=media, width_mm=50.0,
                                 rotate=90))
        assert droit.width_mm / droit.height_mm == pytest.approx(2.0, abs=0.05)
        assert tourne.width_mm / tourne.height_mm == pytest.approx(0.5, abs=0.05)

    def test_validateur_detecte_un_pass_mode_faux(self, tmp_path, printer):
        from ripcore.prnfile import PrnWriter

        out = tmp_path / "mauvais.prn"
        with PrnWriter(out, dpi_x=720, dpi_y=900, width_px=64, channels=5,
                       bits_per_pixel=2, pass_mode=4) as w:  # 0 attendu à 900
            w.write_block(np.ones((5, 8, 64), dtype=np.uint8))
        report = validate_prn(out, printer)
        assert not report.ok
        assert any("pass_mode" in f.check for f in report.errors)

    def test_validateur_detecte_un_raster_vide(self, tmp_path, printer):
        from ripcore.prnfile import PrnWriter

        out = tmp_path / "vide.prn"
        with PrnWriter(out, dpi_x=720, dpi_y=900, width_px=64, channels=5,
                       bits_per_pixel=2, pass_mode=0) as w:
            w.write_block(np.zeros((5, 8, 64), dtype=np.uint8))
        report = validate_prn(out, printer)
        assert not report.ok
        assert any("vide" in f.message for f in report.errors)

    def test_validateur_detecte_un_depassement_d_encre(self, tmp_path, printer):
        """Un raster saturé sur les 4 canaux process dépasse forcément le TAC."""
        from ripcore.prnfile import PrnWriter

        out = tmp_path / "sature.prn"
        levels = np.zeros((5, 64, 64), dtype=np.uint8)
        levels[:4] = 3  # C, M, Y, K à fond → 4,0 d'encre process
        with PrnWriter(out, dpi_x=720, dpi_y=900, width_px=64, channels=5,
                       bits_per_pixel=2, pass_mode=0) as w:
            w.write_block(levels)
        report = validate_prn(out, printer)
        assert not report.ok
        assert any(f.check == "encre/process" for f in report.errors)


class TestFormatsEntree:
    """Ce qu'on peut réellement donner à manger au RIP.

    Deux défauts trouvés en dressant cette matrice, dont un grave : une image
    16 bits était acceptée et ressortait entièrement blanche. Une sortie muette
    et fausse est bien pire qu'un refus — d'où ces tests.
    """

    def _gradient(self, tmp_path, mode, nom):
        from PIL import Image

        brut = np.tile(np.linspace(0, 65535, 400, dtype=np.uint16), (250, 1))
        if mode == "L":
            im = Image.fromarray((brut // 257).astype(np.uint8), "L")
        elif mode == "I;16":
            im = Image.fromarray(brut)  # uint16 -> I;16
        elif mode == "1":
            im = Image.fromarray((brut > 32767).astype(np.uint8) * 255, "L").convert("1")
        elif mode == "P":
            im = Image.fromarray((brut // 257).astype(np.uint8), "L").convert("P")
        elif mode == "RGB":
            im = Image.fromarray(
                np.dstack([(brut // 257).astype(np.uint8)] * 3), "RGB"
            )
        else:
            raise AssertionError(mode)
        chemin = tmp_path / nom
        im.save(chemin)
        return chemin

    def _couverture(self, source, sortie, printer):
        return run_job(JobSpec(
            source=source, output=sortie, printer=printer,
            media=MediaProfile(name="t"), width_mm=25.0,
        )).coverage

    @pytest.mark.parametrize("mode,nom", [
        ("L", "gris8.tif"), ("I;16", "gris16.tif"),
        ("1", "trait.tif"), ("P", "palette.tif"), ("RGB", "couleur.tif"),
    ])
    def test_les_modes_courants_passent(self, tmp_path, printer, mode, nom):
        src = self._gradient(tmp_path, mode, nom)
        couverture = self._couverture(src, tmp_path / f"{mode}.prn", printer)
        assert sum(couverture.values()) > 0.01, (
            f"le mode {mode} produit un fichier vide — perte de données silencieuse"
        )

    def test_le_16_bits_donne_le_meme_resultat_que_le_8_bits(self, tmp_path, printer):
        """Pillow tronque les modes 16 bits à 255 : l'image sortait blanche.

        Le gradient est identique, seule la profondeur change : la couverture
        doit l'être aussi.
        """
        huit = self._gradient(tmp_path, "L", "h.tif")
        seize = self._gradient(tmp_path, "I;16", "s.tif")
        a = self._couverture(huit, tmp_path / "h.prn", printer)
        b = self._couverture(seize, tmp_path / "s.prn", printer)
        for encre in a:
            assert a[encre] == pytest.approx(b[encre], abs=0.01), (
                f"encre {encre} : 8 bits {a[encre]:.3f} vs 16 bits {b[encre]:.3f}"
            )

    def test_le_gris_se_separe_comme_un_rgb_neutre(self, tmp_path, printer):
        gris = self._gradient(tmp_path, "L", "g.tif")
        couleur = self._gradient(tmp_path, "RGB", "c.tif")
        a = self._couverture(gris, tmp_path / "g.prn", printer)
        b = self._couverture(couleur, tmp_path / "c.prn", printer)
        for encre in a:
            assert a[encre] == pytest.approx(b[encre], abs=0.01)

    def test_la_transparence_retient_le_blanc(self, tmp_path, printer):
        """Sans alpha, le blanc couvre tout ; avec, il suit le dessin."""
        from PIL import Image, ImageDraw

        opaque = tmp_path / "opaque.png"
        Image.new("RGB", (400, 300), (255, 255, 255)).save(opaque)
        transparent = tmp_path / "alpha.png"
        im = Image.new("RGBA", (400, 300), (250, 250, 248, 0))
        ImageDraw.Draw(im).ellipse([40, 30, 200, 260], fill=(220, 50, 40, 255))
        im.save(transparent)

        media = MediaProfile(name="t", white_underbase=True)
        def blanc(source, sortie):
            return run_job(JobSpec(
                source=source, output=sortie, printer=printer, media=media,
                width_mm=25.0,
            )).coverage["W"]

        assert blanc(opaque, tmp_path / "o.prn") > 0.9
        assert 0.05 < blanc(transparent, tmp_path / "a.prn") < 0.6

    def test_un_mode_illisible_est_refuse_clairement(self, tmp_path):
        from ripcore.inputs.source import _normaliser_mode

        class Faux:
            mode = "CMYKA"

        with pytest.raises(RipError, match="n'est pas pris en charge"):
            _normaliser_mode(Faux(), None)

    def test_un_fichier_qui_n_est_pas_une_image_est_refuse(self, tmp_path, printer):
        faux = tmp_path / "doc.png"
        faux.write_bytes(b"ceci n'est pas une image")
        with pytest.raises(Exception):
            self._couverture(faux, tmp_path / "x.prn", printer)


class TestMemoire:
    """Formats muraux : rien ne doit être chargé en entier.

    UltraPrint est un exécutable 32 bits (il charge gsdll32.dll, ZIP32.DLL et
    boxiqoky.x86) : son espace d'adressage plafonne à 2 Go, ce qui l'oblige à
    tomber en panne de mémoire sur les grands formats. Le contournement d'usage
    — réduire le visuel à l'import puis le ré-agrandir dans le RIP — détruit du
    détail réel. Ces tests garantissent qu'on n'a pas à le faire.
    """

    def _visuel(self, tmp_path, taille, nom):
        from PIL import Image, ImageDraw

        im = Image.new("RGB", (600, 400), (255, 255, 255))
        d = ImageDraw.Draw(im)
        d.ellipse([50, 40, 320, 300], fill=(220, 50, 40))
        d.rectangle([360, 60, 560, 340], fill=(30, 110, 200))
        if taille != (600, 400):
            im = im.resize(taille, Image.Resampling.LANCZOS)
        chemin = tmp_path / nom
        im.save(chemin, dpi=(300, 300))
        return chemin

    def _rip(self, source, sortie, printer):
        run_job(JobSpec(
            source=source, output=sortie, printer=printer,
            media=MediaProfile(name="t"), dpi_x=720, dpi_y=900, width_mm=40.0,
        ))
        return PrnReader(sortie).read_all()

    def test_une_source_surdimensionnee_depose_la_meme_encre(
        self, tmp_path, printer
    ):
        """Réduire une source trop détaillée ne change pas ce qui sort sur le mur.

        C'est ce qui distingue notre réduction du contournement manuel : on ne
        retire que des pixels que le rééchantillonnage jetait déjà.

        On ne vérifie pas l'égalité au bit près, et ce serait une mauvaise
        exigence : passer par une réduction entière puis un Lanczos n'est pas le
        même chemin de calcul qu'un Lanczos direct, et quelques valeurs tombent
        de l'autre côté d'un seuil de trame. Ce qui doit être conservé, c'est
        l'encre déposée.
        """
        petit = self._visuel(tmp_path, (600, 400), "petit.png")
        enorme = self._visuel(tmp_path, (9600, 6400), "enorme.png")  # 16 fois plus
        a = self._rip(petit, tmp_path / "a.prn", printer)
        b = self._rip(enorme, tmp_path / "b.prn", printer)

        assert a.shape == b.shape
        # Aucun pixel ne saute plus d'une taille de goutte.
        assert int(np.abs(a.astype(np.int16) - b.astype(np.int16)).max()) <= 1
        # Et moins d'un pixel sur cent bouge, y compris d'un seul niveau.
        assert float((a != b).mean()) < 0.01
        # L'encre déposée, canal par canal, est la même.
        densites = np.asarray(printer.drop_levels.densities, dtype=np.float64)
        for i, nom in enumerate(printer.channel_names):
            assert densites[a[i]].mean() == pytest.approx(
                densites[b[i]].mean(), abs=0.002
            ), f"encre {nom} modifiée par la réduction de source"

    def test_la_hauteur_de_bande_suit_la_largeur(self):
        """Le budget mémoire est tenu quelle que soit la taille de la fresque."""
        from ripcore.pipeline import BUDGET_BANDE_OCTETS, _hauteur_de_bande

        precedente = None
        for largeur in (5_670, 42_724, 127_559):
            lignes = _hauteur_de_bande(512, largeur, 5)
            octets = lignes * largeur * 5 * 4 * 2
            assert octets <= BUDGET_BANDE_OCTETS * 1.05, (
                f"bande de {lignes} lignes à {largeur} px = {octets / 1e6:.0f} Mo"
            )
            if precedente is not None:
                assert lignes <= precedente  # plus c'est large, plus la bande est courte
            precedente = lignes

    def test_une_source_deja_a_l_echelle_n_est_pas_touchee(self, tmp_path, printer):
        """La marge de 2× évite de dégrader une source à peine plus grande."""
        from ripcore.inputs.source import load_source

        source = self._visuel(tmp_path, (1200, 800), "juste.png")
        img = load_source(source, width_px=900, height_px=600)
        try:
            assert img._image.size == (1200, 800)
        finally:
            img.close()

    def test_la_source_n_est_jamais_agrandie_avant_le_tramage(
        self, tmp_path, printer
    ):
        """Une petite source agrandie sur le mur ne doit pas être pré-agrandie.

        L'agrandissement se fait bande par bande vers la grille machine ; le
        matérialiser d'un bloc est précisément ce qui fait exploser la mémoire.
        """
        from ripcore.inputs.source import load_source

        petit = self._visuel(tmp_path, (600, 400), "p.png")
        img = load_source(petit, width_px=20_000, height_px=9_000, rotate=90)
        try:
            # La source reste à sa taille d'origine (tournée), pas agrandie.
            assert sorted(img._image.size) == [400, 600]
            bande = img.band(0, 8)
            # La bande, elle, est bien à l'échelle machine.
            assert bande.donnees.shape == (3, 8, 20_000)
        finally:
            img.close()


class TestReperes:
    """Repère du mur et repère du fichier machine.

    Sur une machine à chariot vertical, l'axe X du fichier .prn est le vertical
    du mur : les deux repères sont à angle droit. C'est ce quart de tour qui
    était fait à la main dans UltraPrint ; le RIP doit s'en charger, sinon la
    fresque sort couchée.
    """

    def _source(self, tmp_path, taille):
        from PIL import Image

        chemin = tmp_path / f"src{taille[0]}x{taille[1]}.png"
        Image.new("RGB", taille, (200, 30, 30)).save(chemin, dpi=(300, 300))
        return chemin

    def test_le_fichier_est_a_angle_droit_du_mur(self, tmp_path, printer):
        """Une fresque paysage doit produire un fichier machine portrait."""
        assert printer.machine_rotation == 90
        src = self._source(tmp_path, (1200, 400))
        out = tmp_path / "paysage.prn"
        result = run_job(JobSpec(
            source=src, output=out, printer=printer, media=MediaProfile(name="t"),
            dpi_x=720, dpi_y=900, width_mm=60.0,
        ))
        manifeste = json.loads(result.manifest.read_text(encoding="utf-8"))
        mur, fichier = manifeste["wall"], manifeste["geometry"]

        # Le mur reste paysage : c'est ce que voit l'opérateur.
        assert mur["width_mm"] > mur["height_mm"]
        # Le fichier, lui, est portrait : hauteur du mur dans les octets/ligne.
        assert fichier["width_mm"] < fichier["height_mm"]
        assert fichier["width_mm"] == pytest.approx(mur["height_mm"], abs=1.0)
        assert fichier["height_mm"] == pytest.approx(mur["width_mm"], abs=1.0)
        assert fichier["total_rotation_deg"] == 90

    def test_la_rotation_operateur_s_ajoute_a_celle_de_la_machine(
        self, tmp_path, printer
    ):
        src = self._source(tmp_path, (1200, 400))
        result = run_job(JobSpec(
            source=src, output=tmp_path / "r.prn", printer=printer,
            media=MediaProfile(name="t"), width_mm=40.0, rotate=90,
        ))
        manifeste = json.loads(result.manifest.read_text(encoding="utf-8"))
        assert manifeste["geometry"]["total_rotation_deg"] == 180

    def test_chariot_horizontal_ne_tourne_rien(self, tmp_path, printer):
        """Une machine dont le chariot balaie horizontalement n'a rien à tourner."""
        a_plat = PrinterProfile(
            name=printer.name, head=printer.head,
            bits_per_pixel=printer.bits_per_pixel, channels=printer.channels,
            pass_mode_by_dpi_y=dict(printer.pass_mode_by_dpi_y),
            drop_levels=printer.drop_levels,
            ink_limit_channel=dict(printer.ink_limit_channel),
            ink_limit_total=printer.ink_limit_total,
            max_width_mm=printer.max_width_mm,
            max_height_mm=printer.max_height_mm,
            carriage_axis="horizontal",
        )
        assert a_plat.machine_rotation == 0
        src = self._source(tmp_path, (1200, 400))
        result = run_job(JobSpec(
            source=src, output=tmp_path / "h.prn", printer=a_plat,
            media=MediaProfile(name="t"), width_mm=60.0,
        ))
        manifeste = json.loads(result.manifest.read_text(encoding="utf-8"))
        assert manifeste["geometry"]["width_mm"] == pytest.approx(60.0, abs=1.0)
        assert manifeste["geometry"]["total_rotation_deg"] == 0

    def test_la_hauteur_du_mur_reste_la_limite_dure(self, tmp_path, printer):
        """Même après le quart de tour, c'est la hauteur du MUR qui est bornée."""
        src = self._source(tmp_path, (400, 1200))
        out = tmp_path / "trop-haut.prn"
        with pytest.raises(RipError, match="la machine monte à"):
            run_job(JobSpec(
                source=src, output=out, printer=printer,
                media=MediaProfile(name="t"), height_mm=2600.0,
            ))
        assert not out.exists()

    def test_axe_de_chariot_inconnu_refuse(self, printer):
        with pytest.raises(ProfileError, match="carriage_axis"):
            PrinterProfile(
                name="x", head="", bits_per_pixel=printer.bits_per_pixel,
                channels=printer.channels,
                pass_mode_by_dpi_y={900: 0}, drop_levels=printer.drop_levels,
                ink_limit_channel={}, ink_limit_total=2.0, max_width_mm=100.0,
                carriage_axis="diagonal",
            )


class TestNaiveSeparation:
    def test_blanc_ne_depose_rien(self):
        out = naive_rgb_to_cmyk(np.ones((3, 4, 4), dtype=np.float32))
        assert out.max() == pytest.approx(0.0)

    def test_noir_passe_par_le_canal_noir(self):
        out = naive_rgb_to_cmyk(np.zeros((3, 4, 4), dtype=np.float32), gcr=1.0)
        assert out[3].min() == pytest.approx(1.0)
        assert out[:3].max() == pytest.approx(0.0)


def test_halftone_conserve_la_densite_apres_limitation():
    """Enchaînement réel : limitation puis tramage doivent rester cohérents."""
    drops = np.array(TRUE_DROPS, dtype=np.float32)
    ht = BlueNoiseHalftoner(drops, 4, mask_size=64)
    ink = np.full((4, 128, 128), 0.9, dtype=np.float32)
    limited = limit_total(ink, 2.4)
    out = ht.process(limited, 0)
    deposited = density_of(out, drops).sum(axis=0).mean()
    assert deposited == pytest.approx(2.4, abs=0.05)
