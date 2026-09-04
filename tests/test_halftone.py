"""Tests du tramage.

Les deux propriétés qui décident de la qualité d'un tirage :

* **fidélité de densité** — un aplat demandé à x % doit déposer x % d'encre,
  y compris avec une échelle de gouttes fortement non linéaire ;
* **invariance au découpage en bandes** — le résultat ne doit pas dépendre de
  la façon dont le job a été tronçonné en mémoire, sans quoi on voit des
  coutures horizontales sur la sortie.
"""

from __future__ import annotations

import numpy as np
import pytest

from ripcore.errors import RipError
from ripcore.halftone import (
    BlueNoiseHalftoner,
    ErrorDiffusionHalftoner,
    density_of,
    generate_mask,
    make_halftoner,
    quantize_nearest,
    quantize_ordered,
    thresholds,
)

# Échelle volontairement non linéaire : c'est le cas réel d'une tête à
# 4 tailles de goutte, et le cas qui casse les implémentations naïves.
NONLINEAR = np.array([0.0, 0.22, 0.58, 1.0], dtype=np.float32)
LINEAR = np.array([0.0, 1 / 3, 2 / 3, 1.0], dtype=np.float32)

ENGINES = ["bluenoise", "errdiff", "errdiff:jarvis", "errdiff:stucki"]


def _engine(name: str, densities: np.ndarray, channels: int):
    kwargs = {"mask_size": 64} if name == "bluenoise" else {}
    return make_halftoner(name, densities, channels, **kwargs)


class TestQuantization:
    def test_ordered_respecte_la_densite_moyenne(self):
        """Le seuil doit répartir entre les deux niveaux encadrants."""
        rng = np.random.default_rng(0)
        v = np.full((200, 200), 0.40, dtype=np.float32)
        th = rng.random((200, 200)).astype(np.float32)
        levels = quantize_ordered(v, NONLINEAR, th)
        # 0.40 est entre 0.22 et 0.58 : seuls les niveaux 1 et 2 sont admissibles.
        assert set(np.unique(levels).tolist()) <= {1, 2}
        assert density_of(levels, NONLINEAR).mean() == pytest.approx(0.40, abs=0.005)

    def test_ordered_aux_bornes(self):
        th = np.full((4,), 0.5, dtype=np.float32)
        assert quantize_ordered(np.zeros(4, np.float32), NONLINEAR, th).tolist() == [0] * 4
        assert quantize_ordered(np.ones(4, np.float32), NONLINEAR, th).tolist() == [3] * 4

    def test_nearest_choisit_le_niveau_le_plus_proche(self):
        v = np.array([0.0, 0.10, 0.12, 0.30, 0.45, 0.90, 1.5, -0.5], dtype=np.float32)
        levels, got = quantize_nearest(v, NONLINEAR)
        # milieux : 0.11, 0.40, 0.79
        assert levels.tolist() == [0, 0, 1, 1, 2, 3, 3, 0]
        assert np.array_equal(got, NONLINEAR[levels])


class TestBlueNoiseMask:
    def test_masque_est_une_permutation(self):
        mask = generate_mask(size=32, seed=1)
        assert sorted(mask.ravel().tolist()) == list(range(32 * 32))

    def test_seuils_dans_l_intervalle_ouvert(self):
        th = thresholds(generate_mask(size=16, seed=2))
        assert th.min() > 0.0 and th.max() < 1.0

    def test_spectre_est_bien_du_bruit_bleu(self):
        """Peu d'énergie en basses fréquences : c'est la définition du bruit bleu.

        Un masque aléatoire blanc aurait une énergie uniforme, et une matrice de
        Bayer des pics marqués. On vérifie que le creux central existe.
        """
        mask = generate_mask(size=64, seed=3)
        binary = (mask < mask.size // 2).astype(np.float64)
        spectrum = np.abs(np.fft.fftshift(np.fft.fft2(binary - binary.mean()))) ** 2
        c = 32
        low = spectrum[c - 4 : c + 5, c - 4 : c + 5].mean()
        high = spectrum.mean()
        assert low < high * 0.5, f"énergie basse fréquence {low:.1f} vs {high:.1f}"


@pytest.mark.parametrize("engine", ENGINES)
class TestEngines:
    def test_densite_moyenne_fidele(self, engine):
        """Sur une échelle de gouttes non linéaire, l'aplat doit rester juste."""
        ht = _engine(engine, NONLINEAR, 1)
        for target in (0.05, 0.25, 0.5, 0.75, 0.95):
            ht.reset()
            ink = np.full((1, 256, 256), target, dtype=np.float32)
            out = ht.process(ink, 0)
            got = float(density_of(out, NONLINEAR).mean())
            assert got == pytest.approx(target, abs=0.01), f"{engine} @ {target}"

    def test_invariance_au_decoupage_en_bandes(self, engine):
        rng = np.random.default_rng(42)
        ink = rng.random((3, 300, 180)).astype(np.float32)

        ht = _engine(engine, NONLINEAR, 3)
        ht.reset()
        full = ht.process(ink, 0)

        ht2 = _engine(engine, NONLINEAR, 3)
        ht2.reset()
        parts = [ht2.process(ink[:, y : y + 64], y) for y in range(0, 300, 64)]
        split = np.concatenate(parts, axis=1)

        assert np.array_equal(full, split), (
            f"{engine} : le découpage en bandes change le résultat — "
            f"couture garantie sur la sortie"
        )

    def test_niveaux_dans_le_domaine(self, engine):
        ht = _engine(engine, NONLINEAR, 2)
        rng = np.random.default_rng(7)
        out = ht.process(rng.random((2, 64, 64)).astype(np.float32), 0)
        assert out.dtype == np.uint8
        assert out.max() <= 3

    def test_extremes_sont_purs(self, engine):
        """Le blanc doit rester vierge et l'aplat plein : pas de bruit parasite."""
        ht = _engine(engine, NONLINEAR, 1)
        ht.reset()
        assert not ht.process(np.zeros((1, 64, 64), np.float32), 0).any()
        ht.reset()
        assert (ht.process(np.ones((1, 64, 64), np.float32), 0) == 3).all()


class TestBlueNoiseSpecifics:
    def test_sans_etat(self):
        """Le résultat ne dépend que de y0, jamais de l'historique des appels."""
        ht = BlueNoiseHalftoner(NONLINEAR, 2, mask_size=64)
        ink = np.full((2, 32, 32), 0.37, dtype=np.float32)
        a = ht.process(ink, 37)
        b = ht.process(ink, 0)
        c = ht.process(ink, 37)
        assert np.array_equal(a, c)
        # 37 n'est pas un multiple de la taille du masque : le motif diffère.
        assert not np.array_equal(a, b)

    def test_periodicite_du_masque(self):
        """Un décalage d'un multiple de la taille du masque redonne le motif."""
        ht = BlueNoiseHalftoner(NONLINEAR, 1, mask_size=64)
        ink = np.full((1, 16, 16), 0.4, dtype=np.float32)
        assert np.array_equal(ht.process(ink, 5), ht.process(ink, 5 + 64 * 3))

    def test_canaux_decorreles(self):
        """Deux canaux à la même valeur ne doivent pas dotter au même endroit."""
        ht = BlueNoiseHalftoner(LINEAR, 2, mask_size=64)
        ink = np.full((2, 128, 128), 0.5, dtype=np.float32)
        out = ht.process(ink, 0)
        identiques = float((out[0] == out[1]).mean())
        assert identiques < 0.8, (
            f"{identiques:.0%} de pixels identiques entre canaux — les gouttes se "
            f"superposent, ce qui surcharge le support et fait virer les clairs"
        )

    def test_uniformite_ligne_a_ligne(self):
        ht = BlueNoiseHalftoner(LINEAR, 1, mask_size=64)
        out = ht.process(np.full((1, 512, 512), 0.5, np.float32), 0)
        par_ligne = density_of(out, LINEAR)[0].mean(axis=1)
        assert par_ligne.std() < 0.02


class TestErrorDiffusionSpecifics:
    def test_bandes_non_contigues_refusees(self):
        ht = ErrorDiffusionHalftoner(LINEAR, 1)
        ink = np.zeros((1, 8, 8), dtype=np.float32)
        ht.process(ink, 0)
        with pytest.raises(RipError, match="non contiguës"):
            ht.process(ink, 999)

    def test_noyau_inconnu_refuse(self):
        with pytest.raises(RipError, match="noyau"):
            ErrorDiffusionHalftoner(LINEAR, 1, kernel_name="inexistant")

    def test_pente_de_front_par_noyau(self):
        """La pente doit garantir la causalité, sinon le résultat est faux."""
        assert ErrorDiffusionHalftoner(LINEAR, 1, kernel_name="floyd-steinberg")._slope == 2
        assert ErrorDiffusionHalftoner(LINEAR, 1, kernel_name="jarvis")._slope == 3
        assert ErrorDiffusionHalftoner(LINEAR, 1, kernel_name="stucki")._slope == 3


def test_moteur_inconnu_refuse():
    with pytest.raises(RipError, match="moteur de tramage inconnu"):
        make_halftoner("magique", LINEAR, 1)
