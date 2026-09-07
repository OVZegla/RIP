"""Comparer notre `.prn` à celui d'UltraPrint, sans rien imprimer.

Deux questions coûtent un panneau si on y répond sur la machine :

* **Quel plan commande quelle encre ?** Marquée inconnue dans le profil, elle se
  lève d'habitude avec la mire ``channel-id`` — donc avec de l'encre et un
  support. Mais quand on dispose d'un fichier produit par UltraPrint pour le
  **même visuel**, la réponse est déjà dans les deux fichiers : il suffit de
  chercher quel plan de l'un ressemble à quel plan de l'autre.
* **Pourquoi la taille annoncée par BetterPrinter ne correspond-elle pas ?** Le
  `.prn` ne porte pas de taille en millimètres : elle se déduit des pixels et
  des dpi. Mettre les deux en-têtes côte à côte montre lequel des deux nombres
  diverge.

La comparaison se fait sur une grille grossière : on cherche des ressemblances
de forme, pas des pixels identiques. Deux RIP ne tramant pas de la même façon,
comparer au pixel près ne dirait rien.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .halftone.levels import density_of
from .prnfile.reader import PrnReader
from .profiles import PrinterProfile

GRILLE = 96  # côté de la grille de comparaison


@dataclass(slots=True)
class Empreinte:
    """Ce qu'on retient d'un fichier pour le comparer à un autre."""

    chemin: Path
    largeur_px: int
    lignes: int
    dpi_x: int
    dpi_y: int
    canaux: int
    bits: int
    pass_mode: int
    couverture: np.ndarray  # (C,) part d'encre déposée, 0..1
    vignettes: np.ndarray  # (C, GRILLE, GRILLE) densité moyenne

    @property
    def largeur_mm(self) -> float:
        return self.largeur_px / self.dpi_x * 25.4

    @property
    def hauteur_mm(self) -> float:
        return self.lignes / self.dpi_y * 25.4


def empreinte(chemin: str | Path, densites: np.ndarray | None = None) -> Empreinte:
    """Lit un `.prn` en flux et en retient une empreinte comparable."""
    p = Path(chemin)
    lecteur = PrnReader(p)
    h = lecteur.header
    if densites is None:
        # À défaut de l'échelle mesurée, un escalier linéaire suffit : on
        # compare des formes, et toute échelle monotone les conserve.
        densites = np.linspace(0.0, 1.0, 1 << h.bits_per_pixel, dtype=np.float32)

    somme = np.zeros((h.channels, GRILLE, GRILLE), dtype=np.float64)
    poids = np.zeros((GRILLE, GRILLE), dtype=np.float64)
    total = np.zeros(h.channels, dtype=np.float64)
    lignes_vues = 0

    # Les colonnes tombent toujours dans les mêmes cases : on calcule l'index
    # une fois. np.add.at serait plus court mais bien plus lent.
    col = np.minimum((np.arange(h.width_px) * GRILLE) // h.width_px, GRILLE - 1)

    for y0, bande in _bandes_avec_origine(lecteur):
        densite = density_of(bande, np.asarray(densites, dtype=np.float32))
        total += densite.sum(axis=(1, 2))
        lignes_vues += bande.shape[1]
        lig = np.minimum(
            ((np.arange(y0, y0 + bande.shape[1]) * GRILLE) // h.lines), GRILLE - 1
        )
        for c in range(h.channels):
            # Somme par case : d'abord les colonnes, puis les lignes.
            par_colonne = np.zeros((bande.shape[1], GRILLE), dtype=np.float64)
            np.add.at(par_colonne.T, col, densite[c].T)
            np.add.at(somme[c], lig, par_colonne)
        np.add.at(poids, lig, np.bincount(col, minlength=GRILLE).astype(np.float64))

    couverture = total / max(1, lignes_vues * h.width_px)
    vignettes = somme / np.maximum(poids, 1.0)
    return Empreinte(
        chemin=p, largeur_px=h.width_px, lignes=h.lines, dpi_x=h.dpi_x,
        dpi_y=h.dpi_y, canaux=h.channels, bits=h.bits_per_pixel,
        pass_mode=h.pass_mode, couverture=couverture.astype(np.float32),
        vignettes=vignettes.astype(np.float32),
    )


def _bandes_avec_origine(lecteur: PrnReader):
    y0 = 0
    for bande in lecteur.bands(512):
        yield y0, bande
        y0 += bande.shape[1]


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Corrélation de deux vignettes, dans [-1, 1]. 0 si l'une est vide."""
    x = a.ravel().astype(np.float64) - a.mean()
    y = b.ravel().astype(np.float64) - b.mean()
    n = float(np.linalg.norm(x) * np.linalg.norm(y))
    return 0.0 if n < 1e-12 else float(x @ y / n)


def correspondances(ref: Empreinte, notre: Empreinte) -> list[tuple[int, int, float]]:
    """Pour chaque plan du fichier de référence, le plan le plus ressemblant.

    Rendu : (plan de référence, plan chez nous, corrélation), du plus sûr au
    moins sûr. Un plan vide des deux côtés ne prouve rien et sort avec 0.
    """
    n = min(ref.canaux, notre.canaux)
    table = np.zeros((n, n), dtype=np.float64)
    for i in range(n):
        for j in range(n):
            table[i, j] = _correlation(ref.vignettes[i], notre.vignettes[j])

    # Affectation gloutonne : le meilleur couple d'abord, puis on retire sa
    # ligne et sa colonne. Sur cinq plans, l'optimum global n'en vaut pas la
    # complexité, et un glouton se relit.
    restant = table.copy()
    resultat: list[tuple[int, int, float]] = []
    for _ in range(n):
        i, j = np.unravel_index(int(np.argmax(restant)), restant.shape)
        resultat.append((int(i), int(j), float(table[i, j])))
        restant[i, :] = -np.inf
        restant[:, j] = -np.inf
    return sorted(resultat, key=lambda t: -t[2])


def rapport(
    ref: Empreinte, notre: Empreinte, profil: PrinterProfile | None = None
) -> str:
    """Rapport lisible, à recopier tel quel dans un message."""
    noms = list(profil.channel_names) if profil else []

    def nom(i: int) -> str:
        return noms[i] if i < len(noms) else f"plan {i}"

    lignes = [
        "Comparaison de deux .prn",
        "=" * 62,
        "",
        f"  référence : {ref.chemin.name}",
        f"  le nôtre  : {notre.chemin.name}",
        "",
        "GÉOMÉTRIE",
        "-" * 62,
        f"{'':22}{'référence':>18}{'le nôtre':>18}",
    ]
    for etiquette, a, b in (
        ("pixels", f"{ref.largeur_px} × {ref.lignes}", f"{notre.largeur_px} × {notre.lignes}"),
        ("dpi", f"{ref.dpi_x} × {ref.dpi_y}", f"{notre.dpi_x} × {notre.dpi_y}"),
        ("taille déduite", f"{ref.largeur_mm:.1f} × {ref.hauteur_mm:.1f} mm",
         f"{notre.largeur_mm:.1f} × {notre.hauteur_mm:.1f} mm"),
        ("canaux", str(ref.canaux), str(notre.canaux)),
        ("bits/pixel", str(ref.bits), str(notre.bits)),
        ("pass_mode", str(ref.pass_mode), str(notre.pass_mode)),
    ):
        lignes.append(f"{etiquette:22}{a:>18}{b:>18}")

    if ref.largeur_px and notre.largeur_px:
        fx = notre.largeur_px / ref.largeur_px
        fy = notre.lignes / ref.lignes if ref.lignes else 0.0
        lignes += ["", f"  rapport de pixels : {fx:.4f} en X, {fy:.4f} en Y"]
        if abs(fx - fy) < 0.01 and abs(fx - 1.0) > 0.005:
            lignes.append(
                f"  → même facteur sur les deux axes : c'est une question de "
                f"résolution,\n    pas de cadrage. Pour la même taille physique "
                f"il faudrait {ref.dpi_x / fx:.0f} × {ref.dpi_y / fy:.0f} dpi."
            )

    lignes += ["", "ENCRE PAR PLAN", "-" * 62,
               f"{'':22}{'référence':>18}{'le nôtre':>18}"]
    for i in range(max(ref.canaux, notre.canaux)):
        a = f"{ref.couverture[i] * 100:.1f} %" if i < ref.canaux else "—"
        b = f"{notre.couverture[i] * 100:.1f} %" if i < notre.canaux else "—"
        lignes.append(f"{nom(i):22}{a:>18}{b:>18}")

    lignes += ["", "QUEL PLAN RESSEMBLE À QUEL PLAN", "-" * 62]
    couples = correspondances(ref, notre)
    permute = False
    for i, j, r in couples:
        marque = "  " if i == j else "≠ "
        if i != j and r > 0.5:
            permute = True
        lignes.append(
            f"{marque}référence {nom(i):<8} ↔ chez nous {nom(j):<8} "
            f"ressemblance {r:+.3f}"
        )

    lignes += ["", "LECTURE", "-" * 62]
    if permute:
        ordre = [nom(j) for _, j, _ in sorted(couples, key=lambda t: t[0])]
        lignes += [
            "  Les plans ne sont PAS dans le même ordre. Nos couleurs sortent",
            "  permutées — c'est très probablement la cause d'une dominante.",
            "",
            f"  Ordre à écrire dans le profil imprimante : {', '.join(ordre)}",
            "  (bloc [[channels]], dans cet ordre), puis reripper et recomparer.",
        ]
    elif all(r > 0.5 for _, _, r in couples[: min(4, len(couples))]):
        lignes.append("  Les plans se correspondent un à un : l'ordre est bon.")
    else:
        lignes += [
            "  Ressemblance trop faible pour conclure. Vérifiez qu'il s'agit du",
            "  MÊME visuel, à la MÊME taille, dans les deux fichiers.",
        ]
    return "\n".join(lignes)


__all__ = ["Empreinte", "correspondances", "empreinte", "rapport"]
