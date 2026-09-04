"""Charte visuelle : bleu, blanc, rouge.

Le rouge est **réservé aux problèmes et aux actions irréversibles**. Un rouge
décoratif rend le rouge d'alerte invisible, et sur une machine qui dépose de
l'encre à 2 m de haut, l'alerte doit se voir.

Le bleu porte donc tout le reste, y compris la réussite : « prêt » est bleu,
« problème » est rouge. Deux états, deux couleurs, aucune ambiguïté — et ça
reste lisible pour un daltonien, le contraste de luminosité suffisant à les
séparer.

Les cibles cliquables font au moins 44 px de haut : un atelier se manipule
debout, parfois avec des gants.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

# -- couleurs ----------------------------------------------------------------

BLEU = "#0B4A9B"  # bleu principal — barre de navigation, actions
BLEU_FONCE = "#083A7A"  # survol et appui
BLEU_PALE = "#EAF1FB"  # fonds d'information, sélection
BLEU_TRAIT = "#C3D8F2"

ROUGE = "#C8102E"  # problèmes, actions irréversibles
ROUGE_FONCE = "#A00D25"
ROUGE_PALE = "#FDECEE"

BLANC = "#FFFFFF"
FOND = "#F2F4F7"  # fond général de la fenêtre
TRAIT = "#D6DAE2"
TEXTE = "#1C2331"
TEXTE_DOUX = "#5A6478"
TEXTE_INVERSE = "#FFFFFF"
DESACTIVE = "#9AA2B1"

# -- dimensions --------------------------------------------------------------

HAUTEUR_BOUTON = 44
RAYON_MARGE = 16
NAV_LARGEUR = 232


def _famille(root: tk.Misc) -> str:
    """Police système lisible, avec repli si elle n'existe pas."""
    dispo = set(tkfont.families(root))
    for nom in ("Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", "Helvetica"):
        if nom in dispo:
            return nom
    return "TkDefaultFont"


class Polices:
    """Échelle typographique. Un seul endroit pour agrandir tout le texte."""

    def __init__(self, root: tk.Misc, echelle: float = 1.0) -> None:
        f = _famille(root)
        t = lambda p: max(8, round(p * echelle))  # noqa: E731
        self.titre = tkfont.Font(root=root, family=f, size=t(22), weight="bold")
        self.sous_titre = tkfont.Font(root=root, family=f, size=t(14))
        self.section = tkfont.Font(root=root, family=f, size=t(13), weight="bold")
        self.corps = tkfont.Font(root=root, family=f, size=t(11))
        self.corps_gras = tkfont.Font(root=root, family=f, size=t(11), weight="bold")
        self.petit = tkfont.Font(root=root, family=f, size=t(10))
        self.bouton = tkfont.Font(root=root, family=f, size=t(12), weight="bold")
        self.nav = tkfont.Font(root=root, family=f, size=t(13), weight="bold")
        self.nav_aide = tkfont.Font(root=root, family=f, size=t(9))
        self.chiffre = tkfont.Font(root=root, family=f, size=t(28), weight="bold")


def appliquer(root: tk.Misc, polices: Polices) -> ttk.Style:
    """Installe les styles ttk. À appeler une fois, au démarrage."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")  # le seul thème ttk réellement stylable
    except tk.TclError:  # pragma: no cover - dépend de l'installation Tk
        pass

    style.configure(".", background=FOND, foreground=TEXTE, font=polices.corps)
    style.configure("TFrame", background=FOND)
    style.configure("Carte.TFrame", background=BLANC, relief="flat")
    style.configure("Nav.TFrame", background=BLEU)
    style.configure("Info.TFrame", background=BLEU_PALE)
    style.configure("Alerte.TFrame", background=ROUGE_PALE)

    style.configure("TLabel", background=FOND, foreground=TEXTE)
    style.configure("Carte.TLabel", background=BLANC, foreground=TEXTE)
    style.configure(
        "Titre.TLabel", background=FOND, foreground=TEXTE, font=polices.titre
    )
    style.configure(
        "SousTitre.TLabel",
        background=FOND,
        foreground=TEXTE_DOUX,
        font=polices.sous_titre,
    )
    style.configure(
        "Section.TLabel", background=BLANC, foreground=TEXTE, font=polices.section
    )
    style.configure(
        "Doux.TLabel", background=BLANC, foreground=TEXTE_DOUX, font=polices.petit
    )
    style.configure(
        "DouxFond.TLabel", background=FOND, foreground=TEXTE_DOUX, font=polices.petit
    )
    style.configure(
        "Info.TLabel", background=BLEU_PALE, foreground=BLEU, font=polices.corps
    )
    style.configure(
        "Alerte.TLabel", background=ROUGE_PALE, foreground=ROUGE, font=polices.corps
    )

    style.configure(
        "TButton",
        background=BLANC,
        foreground=BLEU,
        bordercolor=BLEU_TRAIT,
        font=polices.bouton,
        padding=(18, 11),
        relief="flat",
        focuscolor=BLEU,
    )
    style.map(
        "TButton",
        background=[("pressed", BLEU_PALE), ("active", BLEU_PALE)],
        foreground=[("disabled", DESACTIVE)],
    )

    style.configure(
        "Primaire.TButton",
        background=BLEU,
        foreground=TEXTE_INVERSE,
        bordercolor=BLEU,
        font=polices.bouton,
        padding=(22, 13),
    )
    style.map(
        "Primaire.TButton",
        background=[
            ("disabled", DESACTIVE),
            ("pressed", BLEU_FONCE),
            ("active", BLEU_FONCE),
        ],
        foreground=[("disabled", BLANC)],
    )

    style.configure(
        "Danger.TButton",
        background=ROUGE,
        foreground=TEXTE_INVERSE,
        bordercolor=ROUGE,
        font=polices.bouton,
        padding=(22, 13),
    )
    style.map(
        "Danger.TButton",
        background=[
            ("disabled", DESACTIVE),
            ("pressed", ROUGE_FONCE),
            ("active", ROUGE_FONCE),
        ],
    )

    style.configure(
        "TCheckbutton",
        background=BLANC,
        foreground=TEXTE,
        font=polices.corps,
        indicatorbackground=BLANC,
        indicatorforeground=BLEU,
        indicatormargin=(0, 0, 8, 0),
        padding=4,
        focuscolor=BLEU,
    )
    style.map(
        "TCheckbutton",
        background=[("active", BLANC)],
        indicatorbackground=[("selected", BLEU), ("active", BLEU_PALE)],
        indicatorforeground=[("selected", BLANC)],
    )
    style.configure(
        "TRadiobutton", background=BLANC, foreground=TEXTE, font=polices.corps
    )
    style.map("TRadiobutton", background=[("active", BLANC)])

    style.configure(
        "TEntry",
        fieldbackground=BLANC,
        bordercolor=TRAIT,
        lightcolor=TRAIT,
        darkcolor=TRAIT,
        padding=8,
    )
    style.map("TEntry", bordercolor=[("focus", BLEU)])

    style.configure(
        "TCombobox",
        fieldbackground=BLANC,
        background=BLANC,
        bordercolor=TRAIT,
        arrowcolor=BLEU,
        padding=7,
    )
    style.map(
        "TCombobox",
        bordercolor=[("focus", BLEU)],
        # Sans ce réglage, une liste en lecture seule s'affiche en gris et
        # paraît désactivée alors qu'elle est parfaitement cliquable.
        fieldbackground=[("readonly", BLANC), ("disabled", FOND)],
        background=[("readonly", BLANC)],
        foreground=[("readonly", TEXTE)],
        selectbackground=[("readonly", BLANC)],
        selectforeground=[("readonly", TEXTE)],
    )
    root.option_add("*TCombobox*Listbox.background", BLANC)
    root.option_add("*TCombobox*Listbox.foreground", TEXTE)
    root.option_add("*TCombobox*Listbox.selectBackground", BLEU)
    root.option_add("*TCombobox*Listbox.selectForeground", BLANC)

    style.configure(
        "Horizontal.TProgressbar",
        background=BLEU,
        troughcolor=BLEU_PALE,
        bordercolor=BLEU_PALE,
        lightcolor=BLEU,
        darkcolor=BLEU,
        thickness=10,
    )

    style.configure(
        "Treeview",
        background=BLANC,
        fieldbackground=BLANC,
        foreground=TEXTE,
        rowheight=34,
        bordercolor=TRAIT,
    )
    style.configure(
        "Treeview.Heading",
        background=FOND,
        foreground=TEXTE_DOUX,
        font=polices.corps_gras,
        relief="flat",
    )
    style.map("Treeview", background=[("selected", BLEU_PALE)],
              foreground=[("selected", TEXTE)])

    style.configure("TSeparator", background=TRAIT)
    return style
