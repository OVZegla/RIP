"""Écriture des profils imprimante.

L'interface doit pouvoir enregistrer ce que l'opérateur règle — au premier chef
l'ordre des encres, relevé sur le test d'impression. On régénère le fichier
complet à partir du profil, commentaires compris : un TOML écrit par la machine
doit rester lisible et modifiable à la main.

Une sauvegarde `.bak` est déposée avant tout écrasement. Un profil est le
document qui décrit la machine ; le perdre coûte une journée de recalibration.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .errors import ProfileError
from .profiles import PrinterProfile

_ROLE_LABELS = {
    "process": "couleur",
    "white": "blanc",
    "varnish": "vernis",
    "spot": "ton direct",
}


def _fmt(x: float) -> str:
    """Flottant TOML : toujours un point décimal, jamais d'entier déguisé."""
    s = f"{x:.6f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def render_profile(profile: PrinterProfile) -> str:
    """Profil → texte TOML commenté."""
    lines: list[str] = [
        "# Profil imprimante — généré par ripcore, modifiable à la main.",
        "#",
        "# Les drapeaux `*_verified` / `calibrated` disent si la valeur a été",
        "# confirmée sur la machine. Ne les passez à true qu'après un tirage.",
        "",
        "[printer]",
        f'name = "{profile.name}"',
        f'head = "{profile.head}"',
        f"bits_per_pixel = {profile.bits_per_pixel}"
        "          # tailles de goutte = 2^bits",
        f"max_width_mm = {_fmt(profile.max_width_mm)}"
        "     # largeur d'une bande balayée par le chariot",
        f"max_height_mm = {_fmt(profile.max_height_mm)}"
        "    # course de la colonne — limite infranchissable",
        "",
        "# Ordre des plans dans le fichier machine, du premier au dernier.",
        "# Se relève avec le « test des couleurs » (mire channel-id).",
        f"channel_order_verified = {str(profile.channel_order_verified).lower()}",
    ]

    if profile.notes.strip():
        lines += ["", 'notes = """', profile.notes.strip(), '"""']

    for ch in profile.channels:
        label = ch.label or _ROLE_LABELS.get(ch.role, ch.role)
        lines += [
            "",
            "[[channels]]",
            f'name = "{ch.name}"',
            f'role = "{ch.role}"',
            f'label = "{label}"',
        ]

    lines += [
        "",
        "# Valeur du champ « mode de passes » selon la résolution verticale.",
        "# Relevée sur des fichiers produits par UltraPrint : n'inventez pas",
        "# d'entrée, elle décalerait l'impression sur toute la longueur.",
        "[pass_mode_by_dpi_y]",
    ]
    for dpi in sorted(profile.pass_mode_by_dpi_y):
        lines.append(f"{dpi} = {profile.pass_mode_by_dpi_y[dpi]}")

    lines += [
        "",
        "# Quantité d'encre réellement déposée par chaque taille de goutte.",
        "# Se mesure avec le « test des gouttes ».",
        "[drop_levels]",
        "densities = [" + ", ".join(_fmt(d) for d in profile.drop_levels.densities) + "]",
        f"calibrated = {str(profile.drop_levels.calibrated).lower()}",
        "",
        "# Quantité d'encre maximale. `total` ne concerne que les couleurs ;",
        "# `total_all`, si présent, borne l'ensemble blanc et vernis compris.",
        "[ink_limits]",
        f"total = {_fmt(profile.ink_limit_total)}",
    ]
    if profile.ink_limit_total_all is not None:
        lines.append(f"total_all = {_fmt(profile.ink_limit_total_all)}")

    if profile.ink_limit_channel:
        lines += ["", "[ink_limits.per_channel]"]
        for name in profile.channel_names:
            if name in profile.ink_limit_channel:
                lines.append(f"{name} = {_fmt(profile.ink_limit_channel[name])}")

    return "\n".join(lines) + "\n"


def save_profile(profile: PrinterProfile, path: str | Path | None = None) -> Path:
    """Écrit le profil. Sauvegarde l'ancien en `.bak`, écriture atomique."""
    target = Path(path) if path is not None else profile.source
    if target is None:
        raise ProfileError(
            "aucun chemin de destination : ce profil n'a pas été chargé depuis "
            "un fichier, précisez où l'enregistrer"
        )
    text = render_profile(profile)

    # Relecture immédiate : on n'écrase jamais un profil valide par un profil
    # que l'on ne saurait pas relire.
    try:
        PrinterProfile.from_dict(_parse(text))
    except ProfileError as exc:
        raise ProfileError(
            f"le profil régénéré est invalide, enregistrement annulé : {exc}"
        ) from None

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    return target


def _parse(text: str) -> dict:
    import tomllib  # noqa: PLC0415

    return tomllib.loads(text)


def reorder_channels(profile: PrinterProfile, order: list[str]) -> PrinterProfile:
    """Nouveau profil dont les plans suivent l'ordre donné (noms de canaux).

    C'est l'opération que fait l'écran « test des couleurs » une fois le tirage
    lu : l'opérateur dit quelle encre sort sur quelle barre, et les plans sont
    remis dans cet ordre.
    """
    known = set(profile.channel_names)
    if sorted(order) != sorted(known):
        raise ProfileError(
            f"l'ordre proposé ({', '.join(order)}) ne reprend pas exactement les "
            f"encres du profil ({', '.join(sorted(known))}) — chaque encre doit "
            f"apparaître une fois et une seule"
        )
    by_name = {c.name: c for c in profile.channels}
    return PrinterProfile(
        name=profile.name,
        head=profile.head,
        bits_per_pixel=profile.bits_per_pixel,
        channels=tuple(by_name[n] for n in order),
        pass_mode_by_dpi_y=dict(profile.pass_mode_by_dpi_y),
        drop_levels=profile.drop_levels,
        ink_limit_channel=dict(profile.ink_limit_channel),
        ink_limit_total=profile.ink_limit_total,
        max_width_mm=profile.max_width_mm,
        max_height_mm=profile.max_height_mm,
        ink_limit_total_all=profile.ink_limit_total_all,
        channel_order_verified=True,  # l'ordre vient d'un tirage : il est vérifié
        drop_levels_verified=profile.drop_levels_verified,
        source=profile.source,
        notes=profile.notes,
    )
