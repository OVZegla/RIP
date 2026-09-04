"""Masque de bruit bleu par la méthode « void-and-cluster » (Ulichney, 1993).

Pourquoi du bruit bleu plutôt qu'une matrice de Bayer ou l'écran 16×16 d'origine :
un masque void-and-cluster n'a pas de structure périodique visible, ne crée pas
de moiré avec la trame de buses, et — décisif ici — il est **déterministe et
sans état**. Sur une machine qui imprime en N passes avec avance mécanique entre
chaque, un tramage sans état ne peut pas produire de couture de bande. C'est
exactement le problème que `ipht.dll` doit contourner en conservant ses tampons
d'erreur entre bandes.

Le masque est coûteux à générer (quelques secondes) et strictement reproductible :
on le met en cache sur disque.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

DEFAULT_SIZE = 128
DEFAULT_SIGMA = 1.5


def _gaussian_kernel(size: int, sigma: float) -> np.ndarray:
    """Noyau gaussien torique centré en (0, 0), pour un filtrage cyclique."""
    idx = np.arange(size)
    # distance minimale sur le tore
    d = np.minimum(idx, size - idx).astype(np.float64)
    g1 = np.exp(-(d**2) / (2.0 * sigma**2))
    k = np.outer(g1, g1)
    k[0, 0] = 0.0  # un point ne compte pas dans sa propre énergie
    return k


class _EnergyField:
    """Champ d'énergie du motif binaire, maintenu par mises à jour incrémentales.

    Recalculer une convolution complète à chaque étape coûterait O(n⁴) ; ajouter
    ou retirer un point ne fait que translater le noyau, donc O(n²).
    """

    __slots__ = ("size", "_kernel", "field")

    def __init__(self, size: int, sigma: float) -> None:
        self.size = size
        self._kernel = _gaussian_kernel(size, sigma)
        self.field = np.zeros((size, size), dtype=np.float64)

    def add(self, r: int, c: int) -> None:
        self.field += np.roll(self._kernel, (r, c), axis=(0, 1))

    def remove(self, r: int, c: int) -> None:
        self.field -= np.roll(self._kernel, (r, c), axis=(0, 1))

    def tightest_cluster(self, pattern: np.ndarray) -> tuple[int, int]:
        """Le point à 1 dont le voisinage est le plus dense."""
        masked = np.where(pattern, self.field, -np.inf)
        return np.unravel_index(int(np.argmax(masked)), masked.shape)  # type: ignore[return-value]

    def largest_void(self, pattern: np.ndarray) -> tuple[int, int]:
        """Le point à 0 dont le voisinage est le plus vide."""
        masked = np.where(pattern, np.inf, self.field)
        return np.unravel_index(int(np.argmin(masked)), masked.shape)  # type: ignore[return-value]


def _initial_pattern(size: int, sigma: float, seed: int) -> tuple[np.ndarray, _EnergyField]:
    """Motif binaire prototype : ~10 % de points, puis relaxation void-and-cluster."""
    rng = np.random.default_rng(seed)
    n = size * size
    count = max(1, n // 10)
    flat = rng.permutation(n)[:count]
    pattern = np.zeros((size, size), dtype=bool)
    pattern.flat[flat] = True

    energy = _EnergyField(size, sigma)
    for r, c in zip(*np.nonzero(pattern)):
        energy.add(int(r), int(c))

    # Déplacer le point le plus « en grappe » vers le plus grand vide, jusqu'à
    # ce que l'opération devienne un point fixe.
    for _ in range(10 * n):
        cr, cc = energy.tightest_cluster(pattern)
        pattern[cr, cc] = False
        energy.remove(cr, cc)
        vr, vc = energy.largest_void(pattern)
        if (vr, vc) == (cr, cc):
            pattern[cr, cc] = True
            energy.add(cr, cc)
            break
        pattern[vr, vc] = True
        energy.add(vr, vc)
    return pattern, energy


def generate_mask(
    size: int = DEFAULT_SIZE, sigma: float = DEFAULT_SIGMA, seed: int = 0
) -> np.ndarray:
    """Matrice de rangs 0..size²-1 en bruit bleu, périodique en x et en y."""
    if size < 8 or (size & (size - 1)):
        raise ValueError("size doit être une puissance de 2 >= 8")

    prototype, _ = _initial_pattern(size, sigma, seed)
    n = size * size
    rank = np.full((size, size), -1, dtype=np.int64)

    # Phase 1 — on retire les points du prototype du plus « en grappe » au moins,
    # en leur attribuant les rangs décroissants.
    pattern = prototype.copy()
    energy = _EnergyField(size, sigma)
    for r, c in zip(*np.nonzero(pattern)):
        energy.add(int(r), int(c))
    remaining = int(pattern.sum())
    for k in range(remaining - 1, -1, -1):
        r, c = energy.tightest_cluster(pattern)
        pattern[r, c] = False
        energy.remove(r, c)
        rank[r, c] = k
    ones = remaining

    # Phase 2 — on remplit les plus grands vides à partir du prototype.
    pattern = prototype.copy()
    energy = _EnergyField(size, sigma)
    for r, c in zip(*np.nonzero(pattern)):
        energy.add(int(r), int(c))
    for k in range(ones, n):
        r, c = energy.largest_void(pattern)
        pattern[r, c] = True
        energy.add(r, c)
        rank[r, c] = k

    if (rank < 0).any():
        raise AssertionError("masque incomplet — bug de génération")
    return rank


def thresholds(mask: np.ndarray) -> np.ndarray:
    """Rangs → seuils dans ]0, 1[, centrés sur les milieux d'intervalle."""
    n = mask.size
    return ((mask.astype(np.float32) + 0.5) / n).astype(np.float32)


def _cache_dir() -> Path:
    env = os.environ.get("RIPCORE_CACHE")
    base = Path(env) if env else Path.home() / ".cache" / "ripcore"
    return base


def load_mask(
    size: int = DEFAULT_SIZE,
    sigma: float = DEFAULT_SIGMA,
    seed: int = 0,
    cache: bool = True,
) -> np.ndarray:
    """Masque de rangs, depuis le cache disque ou fraîchement généré."""
    if not cache:
        return generate_mask(size, sigma, seed)
    key = hashlib.sha256(
        f"vac-v1-{size}-{sigma!r}-{seed}".encode()
    ).hexdigest()[:16]
    path = _cache_dir() / f"bluenoise-{size}-{key}.npy"
    if path.exists():
        try:
            m = np.load(path)
            if m.shape == (size, size):
                return m
        except (OSError, ValueError):
            pass  # cache corrompu : on régénère
    mask = generate_mask(size, sigma, seed)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".npy.part")
        np.save(tmp, mask)
        os.replace(tmp, path)
    except OSError:
        pass  # cache indisponible : sans conséquence sur le résultat
    return mask
