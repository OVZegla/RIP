"""Génération du blanc et du vernis.

Sur support non blanc — le cas courant en impression murale et sur panneaux —
les couleurs ne tiennent que sur une sous-couche blanche. Cette sous-couche est
calculée à partir de l'image, pas fournie par le fichier source.

Le point délicat est le **débord** : imprimé à l'identique de la couleur, le
blanc dépasse d'un poil aux bords à cause du jeu mécanique entre passes et se
voit comme un liseré clair. On le rétracte donc de quelques pixels (« choke »).
"""

from __future__ import annotations

import numpy as np

from ..errors import RipError


def erode(mask: np.ndarray, radius: int) -> np.ndarray:
    """Érosion par un carré (2r+1), en flottant, sans dépendance externe.

    Séparable : un minimum glissant horizontal puis vertical. Pour les rayons
    utiles ici (1 à 5 px), la version par décalages successifs est plus rapide
    qu'une fenêtre glissante et se lit en trois lignes.
    """
    if radius <= 0:
        return mask
    out = np.asarray(mask, dtype=np.float32)
    for _ in range(radius):
        out = np.minimum.reduce(
            [
                out,
                np.roll(out, 1, axis=0),
                np.roll(out, -1, axis=0),
                np.roll(out, 1, axis=1),
                np.roll(out, -1, axis=1),
            ]
        )
        # Les bords ne doivent pas se contaminer par le rebouclage de np.roll.
        out[0, :] = np.minimum(out[0, :], mask[0, :])
        out[-1, :] = np.minimum(out[-1, :], mask[-1, :])
        out[:, 0] = np.minimum(out[:, 0], mask[:, 0])
        out[:, -1] = np.minimum(out[:, -1], mask[:, -1])
    return out


def underbase(
    process_ink: np.ndarray,
    *,
    density: float = 1.0,
    choke_px: int = 2,
    threshold: float = 0.004,
    alpha: np.ndarray | None = None,
) -> np.ndarray:
    """Sous-couche blanche (H, W) 0..1 déduite de la couverture couleur.

    ``alpha`` — si l'image source porte une transparence, elle prime : c'est la
    seule information fiable sur « où il y a de l'image », y compris dans les
    zones très claires que la couverture d'encre ne détecte pas.
    """
    a = np.asarray(process_ink, dtype=np.float32)
    if a.ndim != 3:
        raise RipError(f"couches process (C, H, W) attendues, reçu {a.shape}")

    if alpha is not None:
        cover = np.clip(np.asarray(alpha, dtype=np.float32), 0.0, 1.0)
        if cover.shape != a.shape[1:]:
            raise RipError(
                f"alpha {cover.shape} incompatible avec l'image {a.shape[1:]}"
            )
    else:
        # Un pixel est « couvert » dès qu'un canal y dépose quelque chose : le
        # max, pas la somme, sinon un jaune clair seul ne déclencherait pas de
        # blanc et laisserait voir le support.
        cover = (a.max(axis=0) > threshold).astype(np.float32)

    return erode(cover, choke_px) * np.float32(np.clip(density, 0.0, 1.0))


def varnish(
    process_ink: np.ndarray,
    *,
    mode: str = "flood",
    density: float = 1.0,
    choke_px: int = 0,
    threshold: float = 0.004,
) -> np.ndarray:
    """Couche de vernis (H, W) 0..1.

    ``flood`` — vernis plein sur toute la surface (finition uniforme).
    ``spot`` — vernis seulement là où il y a de l'image (effet sélectif).
    """
    a = np.asarray(process_ink, dtype=np.float32)
    if mode == "flood":
        return np.full(a.shape[1:], np.clip(density, 0.0, 1.0), dtype=np.float32)
    if mode == "spot":
        cover = (a.max(axis=0) > threshold).astype(np.float32)
        return erode(cover, choke_px) * np.float32(np.clip(density, 0.0, 1.0))
    raise RipError(f"mode de vernis inconnu : {mode!r} (flood | spot)")
