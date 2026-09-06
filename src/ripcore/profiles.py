"""Profils imprimante et média.

Tout ce qui est propre à *cette* machine vit ici, dans un fichier TOML relu à
chaque job — jamais en dur dans le code. Les valeurs non établies par la
rétro-ingénierie portent un drapeau ``*_verified`` qui reste faux tant qu'un
tirage ne l'a pas levé.
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .errors import ProfileError

# Rôles de canal. Le rôle pilote le traitement, pas le nom de l'encre.
ROLE_PROCESS = "process"  # C, M, Y, K — passent par la conversion ICC
ROLE_WHITE = "white"  # sous-couche / réserve blanche, générée
ROLE_VARNISH = "varnish"  # vernis, généré
ROLE_SPOT = "spot"  # ton direct piloté par un canal source dédié

# Orientation du balayage du chariot, dans le repère du MUR.
#
# L'axe X d'un fichier .prn (les octets d'une ligne) est structurellement l'axe
# de balayage du chariot : c'est la définition d'un raster d'imprimante. Sur une
# machine murale à colonne, ce balayage est **vertical** — le chariot monte et
# descend, et c'est la machine qui avance le long du mur entre deux passes.
#
# Conséquence : un visuel préparé « à plat » sort couché d'un quart de tour. Le
# RIP applique donc lui-même la rotation, plutôt que de la laisser à l'opérateur
# à chaque travail.
CHARIOT_VERTICAL = "vertical"
CHARIOT_HORIZONTAL = "horizontal"
_AXES = frozenset({CHARIOT_VERTICAL, CHARIOT_HORIZONTAL})
_ROLES = frozenset({ROLE_PROCESS, ROLE_WHITE, ROLE_VARNISH, ROLE_SPOT})


@dataclass(frozen=True, slots=True)
class Channel:
    """Un plan du fichier .prn."""

    name: str
    role: str = ROLE_PROCESS
    label: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ProfileError("nom de canal vide")
        if self.role not in _ROLES:
            raise ProfileError(
                f"canal {self.name!r} : rôle {self.role!r} inconnu "
                f"(attendu : {', '.join(sorted(_ROLES))})"
            )


@dataclass(frozen=True, slots=True)
class DropLevels:
    """Volumes d'encre relatifs des tailles de goutte.

    ``densities[k]`` = quantité d'encre réellement déposée par un pixel de
    niveau ``k``, normalisée : 0 pour le niveau 0, 1 pour le niveau max.

    Ces valeurs ne sont *pas* linéaires sur une vraie tête — une goutte moyenne
    ne fait pas 2/3 d'une grosse. Elles se mesurent avec la mire ``drop-wedge``.
    Tant que ``calibrated`` est faux on utilise un escalier linéaire, qui donne
    une image correcte mais des dégradés imparfaits.
    """

    densities: tuple[float, ...]
    calibrated: bool = False

    def __post_init__(self) -> None:
        d = self.densities
        if len(d) < 2:
            raise ProfileError("drop_levels : au moins 2 niveaux attendus")
        if d[0] != 0.0:
            raise ProfileError(f"drop_levels : le niveau 0 doit valoir 0.0, reçu {d[0]}")
        if d[-1] != 1.0:
            raise ProfileError(
                f"drop_levels : le niveau max doit valoir 1.0, reçu {d[-1]}"
            )
        if any(b <= a for a, b in zip(d, d[1:])):
            raise ProfileError(f"drop_levels : suite non strictement croissante : {d}")

    @property
    def levels(self) -> int:
        return len(self.densities)

    @classmethod
    def linear(cls, levels: int) -> DropLevels:
        """Escalier linéaire — valeur de repli, explicitement non calibrée."""
        if levels < 2:
            raise ProfileError("levels >= 2 attendu")
        step = 1.0 / (levels - 1)
        return cls(tuple(round(i * step, 12) for i in range(levels)), calibrated=False)


@dataclass(frozen=True, slots=True)
class PrinterProfile:
    """Description complète de la machine côté fichier de sortie."""

    name: str
    head: str
    bits_per_pixel: int
    channels: tuple[Channel, ...]
    pass_mode_by_dpi_y: dict[int, int]
    drop_levels: DropLevels
    ink_limit_channel: dict[str, float]
    ink_limit_total: float
    # Machine murale : le chariot balaie une bande de largeur ``max_width_mm``,
    # la tête monte jusqu'à ``max_height_mm``. La hauteur est un mur infranchissable
    # — la colonne ne s'allonge pas. La largeur, elle, s'étend en repositionnant
    # la machine le long du mur : au-delà d'une bande, on découpe en panneaux.
    max_width_mm: float
    max_height_mm: float = 0.0
    carriage_axis: str = CHARIOT_VERTICAL
    ink_limit_total_all: float | None = None
    channel_order_verified: bool = False
    drop_levels_verified: bool = False
    source: Path | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.bits_per_pixel not in (1, 2, 4, 8):
            raise ProfileError(
                f"bits_per_pixel={self.bits_per_pixel} non supporté (1, 2, 4 ou 8)"
            )
        expected = 1 << self.bits_per_pixel
        if self.drop_levels.levels != expected:
            raise ProfileError(
                f"bits_per_pixel={self.bits_per_pixel} implique {expected} niveaux, "
                f"drop_levels en déclare {self.drop_levels.levels}"
            )
        if not self.channels:
            raise ProfileError("aucun canal déclaré")
        names = [c.name for c in self.channels]
        if len(set(names)) != len(names):
            raise ProfileError(f"noms de canaux dupliqués : {names}")
        for name, limit in self.ink_limit_channel.items():
            if name not in names:
                raise ProfileError(f"ink_limit_channel : canal inconnu {name!r}")
            if not 0.0 < limit <= 1.0:
                raise ProfileError(
                    f"ink_limit_channel[{name}]={limit} hors ]0, 1]"
                )
        if self.carriage_axis not in _AXES:
            raise ProfileError(
                f"carriage_axis={self.carriage_axis!r} inconnu "
                f"({' | '.join(sorted(_AXES))})"
            )
        n_process = len(self.channels_with_role(ROLE_PROCESS))
        if not 0.0 < self.ink_limit_total <= max(n_process, 1):
            raise ProfileError(
                f"ink_limit_total={self.ink_limit_total} hors ]0, {n_process}] — "
                f"cette limite porte sur les seuls canaux process "
                f"({', '.join(c.name for c in self.channels_with_role(ROLE_PROCESS))})"
            )
        if self.ink_limit_total_all is not None and not (
            0.0 < self.ink_limit_total_all <= len(self.channels)
        ):
            raise ProfileError(
                f"ink_limit_total_all={self.ink_limit_total_all} hors "
                f"]0, {len(self.channels)}]"
            )

    # -- accès ---------------------------------------------------------------

    @property
    def channel_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.channels)

    @property
    def n_channels(self) -> int:
        return len(self.channels)

    def index_of(self, name: str) -> int:
        try:
            return self.channel_names.index(name)
        except ValueError:
            raise ProfileError(
                f"canal {name!r} absent du profil {self.name!r} "
                f"(canaux : {', '.join(self.channel_names)})"
            ) from None

    def channels_with_role(self, role: str) -> tuple[Channel, ...]:
        return tuple(c for c in self.channels if c.role == role)

    def role_mask(self, role: str) -> np.ndarray:
        """Masque booléen (C,) des canaux portant ce rôle."""
        return np.array([c.role == role for c in self.channels], dtype=bool)

    @property
    def process_mask(self) -> np.ndarray:
        """Canaux soumis à la limite d'encre totale (TAC)."""
        return self.role_mask(ROLE_PROCESS)

    @property
    def machine_rotation(self) -> int:
        """Quart de tour à appliquer pour poser le visuel droit sur le mur.

        90° quand le chariot balaie verticalement : la largeur du mur part alors
        dans les *lignes* du fichier, sa hauteur dans les *octets par ligne*.
        """
        return 90 if self.carriage_axis == CHARIOT_VERTICAL else 0

    @property
    def dpi_mur(self) -> tuple[str, str]:
        """Quel dpi s'applique à quelle direction du mur, pour l'affichage."""
        if self.machine_rotation:
            return ("dpi_y", "dpi_x")  # (horizontal, vertical)
        return ("dpi_x", "dpi_y")

    def panneaux_pour(self, largeur_mm: float) -> int:
        """Nombre de bandes verticales nécessaires pour couvrir cette largeur."""
        if self.max_width_mm <= 0:
            return 1
        return max(1, math.ceil(largeur_mm / self.max_width_mm - 1e-9))

    def limit_for(self, name: str) -> float:
        return self.ink_limit_channel.get(name, 1.0)

    def pass_mode(self, dpi_y: int) -> int:
        """Valeur du champ 0x24 pour cette résolution verticale.

        Table observée sur 5 fichiers de production, pas une règle démontrée :
        on refuse d'extrapoler vers une résolution non tabulée.
        """
        try:
            return self.pass_mode_by_dpi_y[dpi_y]
        except KeyError:
            known = ", ".join(str(k) for k in sorted(self.pass_mode_by_dpi_y))
            raise ProfileError(
                f"pass_mode inconnu pour dpi_y={dpi_y}. Résolutions tabulées : {known}. "
                f"Ajoutez l'entrée dans le profil après l'avoir relevée sur un .prn "
                f"produit par UltraPrint à cette résolution — ne la devinez pas."
            ) from None

    # -- chargement ----------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> PrinterProfile:
        p = Path(path)
        try:
            raw = tomllib.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ProfileError(f"profil introuvable : {p}") from None
        except tomllib.TOMLDecodeError as exc:
            raise ProfileError(f"profil {p} illisible : {exc}") from None
        return cls.from_dict(raw, source=p)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], source: Path | None = None) -> PrinterProfile:
        try:
            printer = raw["printer"]
            channels = tuple(
                Channel(
                    name=c["name"],
                    role=c.get("role", ROLE_PROCESS),
                    label=c.get("label", ""),
                )
                for c in raw["channels"]
            )
            bpp = int(printer["bits_per_pixel"])
            drop_raw = raw.get("drop_levels", {})
            if "densities" in drop_raw:
                drops = DropLevels(
                    tuple(float(x) for x in drop_raw["densities"]),
                    calibrated=bool(drop_raw.get("calibrated", False)),
                )
            else:
                drops = DropLevels.linear(1 << bpp)
            pass_modes = {
                int(k): int(v) for k, v in raw.get("pass_mode_by_dpi_y", {}).items()
            }
            limits = raw.get("ink_limits", {})
            return cls(
                name=printer["name"],
                head=printer.get("head", ""),
                bits_per_pixel=bpp,
                channels=channels,
                pass_mode_by_dpi_y=pass_modes,
                drop_levels=drops,
                ink_limit_channel={
                    str(k): float(v) for k, v in limits.get("per_channel", {}).items()
                },
                ink_limit_total=float(
                    limits.get(
                        "total",
                        len([c for c in channels if c.role == ROLE_PROCESS]) or 1,
                    )
                ),
                ink_limit_total_all=(
                    float(limits["total_all"]) if "total_all" in limits else None
                ),
                max_width_mm=float(printer.get("max_width_mm", 0.0)),
                max_height_mm=float(printer.get("max_height_mm", 0.0)),
                carriage_axis=str(
                    printer.get("carriage_axis", CHARIOT_VERTICAL)
                ),
                channel_order_verified=bool(
                    printer.get("channel_order_verified", False)
                ),
                drop_levels_verified=bool(drops.calibrated),
                source=source,
                notes=printer.get("notes", raw.get("notes", "")),
            )
        except KeyError as exc:
            raise ProfileError(
                f"profil {source or '<dict>'} : champ obligatoire manquant {exc}"
            ) from None
        except (TypeError, ValueError) as exc:
            raise ProfileError(f"profil {source or '<dict>'} invalide : {exc}") from None

    def warnings(self) -> list[str]:
        """Ce qui n'est pas encore validé sur machine."""
        out: list[str] = []
        if not self.channel_order_verified:
            out.append(
                "ordre des canaux NON VÉRIFIÉ — imprimez la mire « channel-id » "
                "et renseignez channel_order_verified dans le profil"
            )
        if not self.drop_levels.calibrated:
            out.append(
                "tailles de goutte NON CALIBRÉES (escalier linéaire supposé) — "
                "mire « drop-wedge » puis mesure densitométrique"
            )
        return out


SPOT_DIRECT = "direct"    # 255 = pleine encre, comme les canaux CMJN
SPOT_INVERSE = "inverse"  # 0 = pleine encre
SPOT_POLARITES = (SPOT_DIRECT, SPOT_INVERSE)


def _polarite(valeur: Any, source: Path) -> str:
    """Valide le sens de lecture des couches de ton direct.

    Refuser une valeur inconnue plutôt que retomber sur le défaut : une faute de
    frappe qui passe inaperçue ici sort le blanc en négatif sur le mur.
    """
    v = str(valeur).strip().lower()
    if v not in SPOT_POLARITES:
        raise ProfileError(
            f"{source} : spot_polarity = {valeur!r} inconnu "
            f"({' | '.join(SPOT_POLARITES)})"
        )
    return v


@dataclass(frozen=True, slots=True)
class MediaProfile:
    """Support + jeu d'encre : ce qui change d'un média à l'autre."""

    name: str
    icc_output: Path | None = None
    icc_input_rgb: Path | None = None
    icc_input_cmyk: Path | None = None
    rendering_intent: str = "perceptual"
    linearization: Path | None = None
    ink_limit_total: float | None = None
    white_underbase: bool = False
    white_density: float = 1.0
    white_choke_px: int = 2
    white_mode: str = "surface"  # "surface" | "encre" — voir color.white
    # Noms de couche Photoshop → encre machine, p. ex. {"Blanc" = "W"}.
    # Prime sur les correspondances usuelles reconnues par inputs.photoshop.
    spot_map: dict[str, str] = field(default_factory=dict)
    # Sens de la couche : "direct" = 255 pleine encre (comme les canaux CMJN du
    # même fichier), "inverse" = 0 pleine encre. Photoshop n'écrit pas ses
    # canaux supplémentaires de la même façon selon la version et l'option
    # d'export ; une couche lue à l'envers sort en négatif, ce qui se voit
    # immédiatement. `rip layers` tranche la question sur un de vos fichiers.
    spot_polarity: str = SPOT_DIRECT
    notes: str = ""
    source: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> MediaProfile:
        p = Path(path)
        try:
            raw = tomllib.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ProfileError(f"profil média introuvable : {p}") from None
        except tomllib.TOMLDecodeError as exc:
            raise ProfileError(f"profil média {p} illisible : {exc}") from None
        media = raw.get("media", raw)
        base = p.parent

        def _path(key: str) -> Path | None:
            v = media.get(key)
            return None if v is None else (base / v).resolve()

        return cls(
            name=media.get("name", p.stem),
            icc_output=_path("icc_output"),
            icc_input_rgb=_path("icc_input_rgb"),
            icc_input_cmyk=_path("icc_input_cmyk"),
            rendering_intent=media.get("rendering_intent", "perceptual"),
            linearization=_path("linearization"),
            ink_limit_total=(
                float(media["ink_limit_total"]) if "ink_limit_total" in media else None
            ),
            white_underbase=bool(media.get("white_underbase", False)),
            white_density=float(media.get("white_density", 1.0)),
            white_choke_px=int(media.get("white_choke_px", 2)),
            white_mode=str(media.get("white_mode", "surface")),
            spot_map={
                str(k): str(v) for k, v in (media.get("spot_map") or {}).items()
            },
            spot_polarity=_polarite(media.get("spot_polarity", SPOT_DIRECT), p),
            notes=media.get("notes", ""),
            source=p,
            extra={k: v for k, v in media.items() if k not in _MEDIA_KNOWN},
        )


_MEDIA_KNOWN = frozenset(
    {
        "name",
        "icc_output",
        "icc_input_rgb",
        "icc_input_cmyk",
        "rendering_intent",
        "linearization",
        "ink_limit_total",
        "white_underbase",
        "white_density",
        "white_choke_px",
        "white_mode",
        "spot_map",
        "spot_polarity",
        "notes",
    }
)
