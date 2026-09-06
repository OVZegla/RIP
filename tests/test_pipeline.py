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
    def test_sous_couche_suit_la_couverture(self):
        ink = np.zeros((4, 20, 20), dtype=np.float32)
        ink[0, 5:15, 5:15] = 0.5
        w = underbase(ink, choke_px=0)
        assert w[10, 10] == pytest.approx(1.0)
        assert w[0, 0] == pytest.approx(0.0)

    def test_choke_retracte_les_bords(self):
        ink = np.zeros((4, 20, 20), dtype=np.float32)
        ink[0, 5:15, 5:15] = 1.0
        sans = underbase(ink, choke_px=0)
        avec = underbase(ink, choke_px=2)
        assert avec.sum() < sans.sum()
        assert avec[10, 10] == pytest.approx(1.0)  # le cœur reste plein
        assert avec[5, 5] == pytest.approx(0.0)  # le bord est retiré

    def test_jaune_clair_seul_declenche_du_blanc(self):
        """Le max, pas la somme : sinon un aplat jaune pâle sort sans blanc."""
        ink = np.zeros((4, 8, 8), dtype=np.float32)
        ink[2] = 0.05
        assert underbase(ink, choke_px=0).mean() == pytest.approx(1.0)

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
        # Le blanc doit avoir été généré sous les zones imprimées, et nulle part ailleurs.
        assert 0.0 < result.coverage["W"] < 1.0

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
