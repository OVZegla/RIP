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


MODE_SURFACE = "surface"  # blanc sous toute la surface imprimée
MODE_ENCRE = "encre"  # blanc seulement là où il y a de la couleur
MODES_BLANC = (MODE_SURFACE, MODE_ENCRE)


def underbase(
    process_ink: np.ndarray,
    *,
    density: float = 1.0,
    choke_px: int = 2,
    threshold: float = 0.004,
    alpha: np.ndarray | None = None,
    mode: str = MODE_SURFACE,
) -> np.ndarray:
    """Sous-couche blanche (H, W) 0..1.

    Trois sources d'information, dans cet ordre :

    1. **La transparence**, si l'image en porte une. C'est la seule indication
       fiable de « où il y a de l'image », y compris dans les zones si claires
       qu'elles ne déposent presque pas d'encre.
    2. **La surface imprimée** (``mode="surface"``, le défaut). Sans
       transparence, le visuel est un rectangle plein : ses zones blanches font
       partie de l'image et doivent recevoir du blanc. Les laisser nues
       reviendrait à y montrer le mur — brique, béton ou bois — à la place du
       blanc voulu.
    3. **La couverture d'encre** (``mode="encre"``). Le blanc ne va que là où il
       y a de la couleur. Utile pour poser une forme sur un mur sans le
       rectangle blanc autour, mais à ne pas prendre par défaut : une photo avec
       un ciel clair y perdrait son ciel.
    """
    a = np.asarray(process_ink, dtype=np.float32)
    if a.ndim != 3:
        raise RipError(f"couches process (C, H, W) attendues, reçu {a.shape}")
    if mode not in MODES_BLANC:
        raise RipError(
            f"mode de blanc inconnu : {mode!r} ({' | '.join(MODES_BLANC)})"
        )

    if alpha is not None:
        cover = np.clip(np.asarray(alpha, dtype=np.float32), 0.0, 1.0)
        if cover.shape != a.shape[1:]:
            raise RipError(
                f"alpha {cover.shape} incompatible avec l'image {a.shape[1:]}"
            )
    elif mode == MODE_SURFACE:
        cover = np.ones(a.shape[1:], dtype=np.float32)
    else:
        # Le max, pas la somme : sinon un jaune clair seul ne déclencherait pas
        # de blanc et laisserait voir le mur.
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
