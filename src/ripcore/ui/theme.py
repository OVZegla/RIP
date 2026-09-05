"""Charte visuelle.

Deux palettes, sombre par défaut. Un poste d'atelier tourne souvent en lumière
basse et l'écran reste allumé toute la journée : le fond sombre fatigue moins et
fait ressortir l'aperçu du visuel, qui est la seule chose colorée de l'écran.

Le **rouge reste réservé aux problèmes** et aux actions irréversibles. Un rouge
décoratif rendrait le rouge d'alerte invisible, et sur une machine qui projette
de l'encre sur un mur de client, l'alerte doit se voir. Le bleu porte tout le
reste, réussite comprise.

Les cibles cliquables font au moins 44 px de haut : un atelier se manipule
debout, parfois avec des gants.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk


@dataclass(frozen=True, slots=True)
class Palette:
    """Un jeu de couleurs complet. Le reste du code n'en connaît que les noms."""

    nom: str
    fond: str  # arrière-plan général
    surface: str  # cartes et panneaux
    surface_haute: str  # champs, survols
    bordure: str
    bordure_douce: str
    texte: str
    texte_doux: str
    texte_faible: str
    accent: str
    accent_fonce: str
    accent_pale: str  # fond des zones d'information
    accent_texte: str  # texte sur fond accent
    danger: str
    danger_fonce: str
    danger_pale: str
    rail: str  # colonne de navigation et barre supérieure
    rail_actif: str
    # Le rail reste sombre dans les deux palettes : son texte a donc ses
    # propres couleurs, sinon le mode clair écrit en noir sur bleu nuit.
    rail_texte: str
    rail_texte_doux: str
    rail_texte_faible: str
    ombre: str  # trait de séparation sous la barre supérieure


SOMBRE = Palette(
    nom="sombre",
    fond="#0D1017",
    surface="#151A23",
    surface_haute="#1D2430",
    bordure="#28303D",
    bordure_douce="#1F2632",
    texte="#E9EDF4",
    texte_doux="#9AA5B8",
    texte_faible="#6B7688",
    accent="#3B82F6",
    accent_fonce="#2563EB",
    accent_pale="#132038",
    accent_texte="#FFFFFF",
    danger="#F0475F",
    danger_fonce="#D22B44",
    danger_pale="#2A121A",
    rail="#0A0D13",
    rail_actif="#151A23",
    rail_texte="#E9EDF4",
    rail_texte_doux="#9AA5B8",
    rail_texte_faible="#5E6878",
    ombre="#000000",
)

CLAIR = Palette(
    nom="clair",
    fond="#F4F6F9",
    surface="#FFFFFF",
    surface_haute="#F0F3F7",
    bordure="#DDE3EC",
    bordure_douce="#E9EDF3",
    texte="#101725",
    texte_doux="#5A6579",
    texte_faible="#8A94A6",
    accent="#1D5FD0",
    accent_fonce="#164BA8",
    accent_pale="#E8F0FE",
    accent_texte="#FFFFFF",
    danger="#C8102E",
    danger_fonce="#A00D25",
    danger_pale="#FDECEF",
    rail="#0D1524",
    rail_actif="#1B2740",
    rail_texte="#F5F8FC",
    rail_texte_doux="#A8B4C8",
    rail_texte_faible="#6F7C92",
    ombre="#D5DBE5",
)

PALETTES = {"sombre": SOMBRE, "clair": CLAIR}

# Palette active. Une seule fenêtre à la fois : un registre de module évite de
# faire transiter la palette dans chaque constructeur de widget.
_courante: Palette = SOMBRE


def courante() -> Palette:
    return _courante


def definir(palette: Palette) -> None:
    global _courante
    _courante = palette

# -- géométrie ---------------------------------------------------------------

PAS = 8  # tout l'espacement est un multiple de 8 px
RAIL_LARGEUR = 216
BARRE_HAUTEUR = 60
RAYON = 10  # rayon des coins arrondis dessinés au canevas


def _famille(root: tk.Misc, *candidats: str) -> str:
    dispo = set(tkfont.families(root))
    for nom in candidats:
        if nom in dispo:
            return nom
    return "TkDefaultFont"


class Polices:
    """Échelle typographique. Un seul endroit pour tout agrandir."""

    def __init__(self, root: tk.Misc, echelle: float = 1.0) -> None:
        f = _famille(root, "Segoe UI Variable", "Segoe UI", "Inter",
                     "Noto Sans", "DejaVu Sans", "Helvetica")
        # Chiffres à chasse fixe pour les tableaux et les mesures : sans ça les
        # colonnes de pourcentages dansent d'une ligne à l'autre.
        m = _famille(root, "Cascadia Mono", "Consolas", "JetBrains Mono",
                     "DejaVu Sans Mono", "Courier")
        t = lambda p: max(8, round(p * echelle))  # noqa: E731

        self.affiche = tkfont.Font(root=root, family=f, size=t(26), weight="bold")
        self.titre = tkfont.Font(root=root, family=f, size=t(19), weight="bold")
        self.sous_titre = tkfont.Font(root=root, family=f, size=t(12))
        self.section = tkfont.Font(root=root, family=f, size=t(13), weight="bold")
        self.corps = tkfont.Font(root=root, family=f, size=t(11))
        self.corps_gras = tkfont.Font(root=root, family=f, size=t(11), weight="bold")
        self.petit = tkfont.Font(root=root, family=f, size=t(10))
        self.minuscule = tkfont.Font(root=root, family=f, size=t(9))
        self.etiquette = tkfont.Font(root=root, family=f, size=t(9), weight="bold")
        self.bouton = tkfont.Font(root=root, family=f, size=t(11), weight="bold")
        self.nav = tkfont.Font(root=root, family=f, size=t(11), weight="bold")
        self.marque = tkfont.Font(root=root, family=f, size=t(15), weight="bold")
        self.chiffre = tkfont.Font(root=root, family=m, size=t(11))
        self.chiffre_grand = tkfont.Font(root=root, family=m, size=t(22), weight="bold")


def appliquer(root: tk.Misc, polices: Polices, p: Palette) -> ttk.Style:
    """Installe les styles ttk pour la palette donnée."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")  # le seul thème ttk réellement stylable
    except tk.TclError:  # pragma: no cover - dépend de l'installation Tk
        pass

    style.configure(".", background=p.fond, foreground=p.texte, font=polices.corps,
                    borderwidth=0, focuscolor=p.accent)

    for nom, fond in (
        ("TFrame", p.fond),
        ("Surface.TFrame", p.surface),
        ("Haute.TFrame", p.surface_haute),
        ("Info.TFrame", p.accent_pale),
        ("Alerte.TFrame", p.danger_pale),
        ("Rail.TFrame", p.rail),
    ):
        style.configure(nom, background=fond)

    for nom, fond, plume, police in (
        ("TLabel", p.fond, p.texte, polices.corps),
        ("Titre.TLabel", p.fond, p.texte, polices.titre),
        ("Affiche.TLabel", p.fond, p.texte, polices.affiche),
        ("SousTitre.TLabel", p.fond, p.texte_doux, polices.sous_titre),
        ("DouxFond.TLabel", p.fond, p.texte_doux, polices.petit),
        ("Surface.TLabel", p.surface, p.texte, polices.corps),
        ("Section.TLabel", p.surface, p.texte, polices.section),
        ("Etiquette.TLabel", p.surface, p.texte_doux, polices.etiquette),
        ("Doux.TLabel", p.surface, p.texte_doux, polices.petit),
        ("Faible.TLabel", p.surface, p.texte_faible, polices.minuscule),
        ("Chiffre.TLabel", p.surface, p.texte, polices.chiffre),
        ("Info.TLabel", p.accent_pale, p.accent, polices.corps),
        ("Alerte.TLabel", p.danger_pale, p.danger, polices.corps),
    ):
        style.configure(nom, background=fond, foreground=plume, font=police)

    # -- boutons -------------------------------------------------------------
    style.configure(
        "TButton", background=p.surface_haute, foreground=p.texte,
        bordercolor=p.bordure, font=polices.bouton, padding=(16, 10),
        relief="flat", borderwidth=1,
    )
    style.map(
        "TButton",
        background=[("pressed", p.bordure), ("active", p.bordure)],
        foreground=[("disabled", p.texte_faible)],
        bordercolor=[("active", p.accent)],
    )
    style.configure(
        "Accent.TButton", background=p.accent, foreground=p.accent_texte,
        bordercolor=p.accent, font=polices.bouton, padding=(18, 11),
    )
    style.map(
        "Accent.TButton",
        background=[("disabled", p.surface_haute), ("pressed", p.accent_fonce),
                    ("active", p.accent_fonce)],
        foreground=[("disabled", p.texte_faible)],
    )
    style.configure(
        "Discret.TButton", background=p.surface, foreground=p.accent,
        bordercolor=p.surface, font=polices.corps_gras, padding=(10, 6),
    )
    style.map("Discret.TButton",
              background=[("active", p.surface_haute), ("pressed", p.surface_haute)])

    # -- saisies -------------------------------------------------------------
    style.configure(
        "TEntry", fieldbackground=p.surface_haute, foreground=p.texte,
        bordercolor=p.bordure, lightcolor=p.bordure, darkcolor=p.bordure,
        insertcolor=p.texte, padding=9, borderwidth=1,
    )
    style.map("TEntry",
              bordercolor=[("focus", p.accent)],
              lightcolor=[("focus", p.accent)],
              darkcolor=[("focus", p.accent)])

    style.configure(
        "TCombobox", fieldbackground=p.surface_haute, background=p.surface_haute,
        foreground=p.texte, bordercolor=p.bordure, arrowcolor=p.texte_doux,
        arrowsize=14, padding=8, borderwidth=1,
    )
    style.map(
        "TCombobox",
        bordercolor=[("focus", p.accent)],
        # Sans ces états, une liste en lecture seule s'affiche en gris et paraît
        # désactivée alors qu'elle est parfaitement cliquable.
        fieldbackground=[("readonly", p.surface_haute), ("disabled", p.surface)],
        background=[("readonly", p.surface_haute)],
        foreground=[("readonly", p.texte), ("disabled", p.texte_faible)],
        selectbackground=[("readonly", p.surface_haute)],
        selectforeground=[("readonly", p.texte)],
        arrowcolor=[("active", p.accent)],
    )
    for option, valeur in (
        ("*TCombobox*Listbox.background", p.surface_haute),
        ("*TCombobox*Listbox.foreground", p.texte),
        ("*TCombobox*Listbox.selectBackground", p.accent),
        ("*TCombobox*Listbox.selectForeground", p.accent_texte),
        ("*TCombobox*Listbox.borderWidth", 0),
    ):
        root.option_add(option, valeur)

    # -- divers --------------------------------------------------------------
    style.configure(
        "Horizontal.TProgressbar", background=p.accent, troughcolor=p.surface_haute,
        bordercolor=p.surface_haute, lightcolor=p.accent, darkcolor=p.accent,
        thickness=6, borderwidth=0,
    )
    style.configure(
        "Treeview", background=p.surface, fieldbackground=p.surface,
        foreground=p.texte, rowheight=36, bordercolor=p.bordure, borderwidth=0,
        font=polices.corps,
    )
    style.configure(
        "Treeview.Heading", background=p.fond, foreground=p.texte_doux,
        font=polices.etiquette, relief="flat", padding=(8, 8), borderwidth=0,
    )
    style.map("Treeview.Heading", background=[("active", p.fond)])
    style.map("Treeview",
              background=[("selected", p.accent_pale)],
              foreground=[("selected", p.texte)])

    style.configure(
        "Vertical.TScrollbar", background=p.bordure, troughcolor=p.fond,
        bordercolor=p.fond, arrowcolor=p.fond, arrowsize=0, borderwidth=0,
        relief="flat",
    )
    style.map("Vertical.TScrollbar", background=[("active", p.texte_faible)])
    style.configure("TSeparator", background=p.bordure)
    return style
