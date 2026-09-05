"""Briques d'interface.

Tk ne sait pas arrondir un cadre : ce qui doit l'être (interrupteurs, puces
d'état, sélecteur de mode, boutons d'action) est dessiné au canevas. Le reste
assume des angles droits, une bordure de 1 px et beaucoup d'air — c'est ce que
font la plupart des outils professionnels sombres, et c'est net.

Les widgets lisent la palette active via ``theme.courante()`` : une seule
fenêtre à la fois, donc pas besoin de la faire transiter partout.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from . import theme


def _rect_arrondi(canevas: tk.Canvas, x0, y0, x1, y1, r, **kw) -> None:
    """Rectangle à coins arrondis : un polygone lissé, sans dépendance."""
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    points = [
        x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
        x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
        x0, y1, x0, y1 - r, x0, y0 + r, x0, y0,
    ]
    canevas.create_polygon(points, smooth=True, splinesteps=24, **kw)


# ---------------------------------------------------------------- conteneurs


class Carte(tk.Frame):
    """Panneau de contenu : fond de surface, bordure fine, marges généreuses."""

    def __init__(
        self,
        parent: tk.Misc,
        titre: str = "",
        aide: str = "",
        polices: theme.Polices | None = None,
        marge: int = 20,
        **kw,
    ) -> None:
        p = theme.courante()
        super().__init__(
            parent, bg=p.surface, highlightthickness=1,
            highlightbackground=p.bordure, highlightcolor=p.bordure, **kw,
        )
        self.interieur = tk.Frame(self, bg=p.surface, padx=marge, pady=marge)
        self.interieur.pack(fill="both", expand=True)

        if titre:
            ttk.Label(self.interieur, text=titre, style="Section.TLabel").pack(
                anchor="w", pady=(0, 4 if aide else 14)
            )
        if aide:
            ttk.Label(
                self.interieur, text=aide, style="Doux.TLabel",
                wraplength=560, justify="left",
            ).pack(anchor="w", pady=(0, 14))

    # Les enfants se posent dans ``interieur`` sans avoir à le savoir.
    def corps(self) -> tk.Frame:
        return self.interieur


class Bandeau(tk.Frame):
    """Message pleine largeur. ``niveau`` : ``info`` (bleu) ou ``alerte`` (rouge).

    Deux niveaux et pas trois : un cran intermédiaire n'aide personne à décider
    quoi faire.
    """

    def __init__(
        self,
        parent: tk.Misc,
        texte: str,
        polices: theme.Polices,
        niveau: str = "info",
        action: tuple[str, Callable[[], None]] | None = None,
    ) -> None:
        p = theme.courante()
        alerte = niveau == "alerte"
        fond = p.danger_pale if alerte else p.accent_pale
        plume = p.danger if alerte else p.accent
        super().__init__(parent, bg=fond, highlightthickness=1,
                         highlightbackground=plume if alerte else p.accent_pale)

        interieur = tk.Frame(self, bg=fond, padx=16, pady=12)
        interieur.pack(fill="x")
        tk.Label(
            interieur, text=("!" if alerte else "i"), bg=plume,
            fg=p.accent_texte, font=polices.etiquette, width=2,
        ).pack(side="left", ipady=2)
        tk.Label(
            interieur, text=texte, bg=fond, fg=plume, font=polices.corps,
            wraplength=700, justify="left", anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(12, 0))
        if action is not None:
            libelle, rappel = action
            ttk.Button(interieur, text=libelle, command=rappel).pack(
                side="right", padx=(16, 0)
            )


# ------------------------------------------------------------------ commandes


class Segments(tk.Canvas):
    """Sélecteur à segments — le « Simple / Avancé » de la barre supérieure.

    Deux boutons radio feraient le même travail, mais un sélecteur segmenté dit
    d'un coup d'œil qu'il s'agit de deux vues d'une même chose, et non de deux
    réglages indépendants.
    """

    def __init__(
        self,
        parent: tk.Misc,
        options: list[tuple[str, str]],
        variable: tk.StringVar,
        polices: theme.Polices,
        sur_changement: Callable[[str], None] | None = None,
        largeur_segment: int = 96,
        hauteur: int = 34,
    ) -> None:
        p = theme.courante()
        self._segments = options  # ne pas nommer _options : réservé par Tk
        self._variable = variable
        self._police = polices.corps_gras
        self._largeur = largeur_segment
        self._hauteur = hauteur
        self._rappel = sur_changement
        super().__init__(
            parent, width=largeur_segment * len(options) + 6, height=hauteur,
            bg=p.fond, highlightthickness=0, cursor="hand2",
        )
        self.bind("<Button-1>", self._clic)
        variable.trace_add("write", lambda *_: self._dessiner())
        self._dessiner()

    def _clic(self, event: tk.Event) -> None:
        index = min(len(self._segments) - 1, max(0, (event.x - 3) // self._largeur))
        cle = self._segments[index][0]
        if cle != self._variable.get():
            self._variable.set(cle)
            if self._rappel is not None:
                self._rappel(cle)

    def _dessiner(self) -> None:
        p = theme.courante()
        self.delete("all")
        self.configure(bg=p.fond)
        h = self._hauteur
        _rect_arrondi(self, 0, 0, self._largeur * len(self._segments) + 6, h, 9,
                      fill=p.surface_haute, outline=p.bordure)
        actif = self._variable.get()
        for i, (cle, libelle) in enumerate(self._segments):
            x0 = 3 + i * self._largeur
            x1 = x0 + self._largeur
            choisi = cle == actif
            if choisi:
                _rect_arrondi(self, x0, 3, x1, h - 3, 7,
                              fill=p.accent, outline=p.accent)
            self.create_text(
                (x0 + x1) / 2, h / 2, text=libelle, font=self._police,
                fill=p.accent_texte if choisi else p.texte_doux,
            )

    def rafraichir(self) -> None:
        self._dessiner()


class Interrupteur(tk.Frame):
    """Interrupteur oui/non, cliquable sur toute sa ligne.

    La case à cocher ttk fait 13 px de côté : trop petite à viser debout, et son
    état se lit mal de loin.
    """

    LARGEUR = 46
    HAUTEUR = 26

    def __init__(
        self,
        parent: tk.Misc,
        texte: str,
        variable: tk.BooleanVar,
        polices: theme.Polices,
        aide: str = "",
        largeur_aide: int = 460,
        fond: str | None = None,
    ) -> None:
        p = theme.courante()
        self._fond = fond or p.surface
        super().__init__(parent, bg=self._fond)
        self.variable = variable

        ligne = tk.Frame(self, bg=self._fond, cursor="hand2")
        ligne.pack(fill="x")
        self._piste = tk.Canvas(
            ligne, width=self.LARGEUR, height=self.HAUTEUR, bg=self._fond,
            highlightthickness=0, cursor="hand2",
        )
        self._piste.pack(side="left")
        self._libelle = tk.Label(
            ligne, text=texte, bg=self._fond, fg=p.texte, font=polices.corps,
            cursor="hand2", anchor="w",
        )
        self._libelle.pack(side="left", padx=(12, 0))

        if aide:
            tk.Label(
                self, text=aide, bg=self._fond, fg=p.texte_doux,
                font=polices.petit, wraplength=largeur_aide, justify="left",
                anchor="w",
            ).pack(anchor="w", padx=(self.LARGEUR + 12, 0), pady=(3, 0))

        for w in (ligne, self._piste, self._libelle):
            w.bind("<Button-1>", self._basculer)
        variable.trace_add("write", lambda *_: self._dessiner())
        self._dessiner()

    def _basculer(self, _event: tk.Event) -> None:
        self.variable.set(not self.variable.get())

    def _dessiner(self) -> None:
        p = theme.courante()
        actif = bool(self.variable.get())
        c = self._piste
        c.delete("all")
        h, r = self.HAUTEUR, self.HAUTEUR // 2
        fond = p.accent if actif else p.surface_haute
        contour = p.accent if actif else p.bordure
        _rect_arrondi(c, 1, 1, self.LARGEUR - 1, h - 1, r, fill=fond, outline=contour)
        x = self.LARGEUR - r - 1 if actif else r + 1
        c.create_oval(
            x - r + 4, 5, x + r - 4, h - 5,
            fill=p.accent_texte if actif else p.texte_doux, outline="",
        )


class BoutonAction(tk.Canvas):
    """Bouton d'action principal, dessiné : coins arrondis et hauteur fixe."""

    def __init__(
        self,
        parent: tk.Misc,
        texte: str,
        commande: Callable[[], None],
        polices: theme.Polices,
        variante: str = "accent",
        hauteur: int = 46,
        fond_parent: str | None = None,
    ) -> None:
        p = theme.courante()
        self._variante = variante
        self._commande = commande
        self._police = polices.bouton
        self._texte = texte
        self._hauteur = hauteur
        self._survol = False
        self._actif = True
        self._fond_parent = fond_parent or p.surface
        super().__init__(
            parent, height=hauteur, bg=self._fond_parent,
            highlightthickness=0, cursor="hand2",
        )
        self.bind("<Button-1>", self._clic)
        self.bind("<Enter>", lambda _e: self._etat_survol(True))
        self.bind("<Leave>", lambda _e: self._etat_survol(False))
        self.bind("<Configure>", lambda _e: self._dessiner())

    def _couleurs(self) -> tuple[str, str]:
        p = theme.courante()
        if not self._actif:
            return p.surface_haute, p.texte_faible
        if self._variante == "accent":
            return (p.accent_fonce if self._survol else p.accent), p.accent_texte
        if self._variante == "danger":
            return (p.danger_fonce if self._survol else p.danger), p.accent_texte
        return (p.bordure if self._survol else p.surface_haute), p.texte

    def _etat_survol(self, dessus: bool) -> None:
        self._survol = dessus and self._actif
        self._dessiner()

    def _clic(self, _event: tk.Event) -> None:
        if self._actif:
            self._commande()

    def _dessiner(self) -> None:
        self.delete("all")
        fond, plume = self._couleurs()
        w = max(self.winfo_width(), 40)
        h = self._hauteur
        _rect_arrondi(self, 0, 0, w, h, 8, fill=fond, outline=fond)
        self.create_text(w / 2, h / 2, text=self._texte, font=self._police, fill=plume)

    def configurer_texte(self, texte: str) -> None:
        self._texte = texte
        self._dessiner()

    def activer(self, actif: bool) -> None:
        self._actif = actif
        self.configure(cursor="hand2" if actif else "")
        self._dessiner()

    def rafraichir(self) -> None:
        p = theme.courante()
        self._fond_parent = p.surface
        self.configure(bg=self._fond_parent)
        self._dessiner()


class Puce(tk.Canvas):
    """Petite pastille d'état : « Prête » ou « À régler »."""

    def __init__(
        self, parent: tk.Misc, texte: str, polices: theme.Polices,
        niveau: str = "info", fond_parent: str | None = None,
    ) -> None:
        p = theme.courante()
        self._police = polices.etiquette
        self._texte = texte
        self._niveau = niveau
        largeur = self._police.measure(texte) + 24
        super().__init__(
            parent, width=largeur, height=22,
            bg=fond_parent or p.fond, highlightthickness=0,
        )
        self._dessiner()

    def _dessiner(self) -> None:
        p = theme.courante()
        self.delete("all")
        fond = p.danger_pale if self._niveau == "alerte" else p.accent_pale
        plume = p.danger if self._niveau == "alerte" else p.accent
        w = int(self["width"])
        _rect_arrondi(self, 0, 0, w, 22, 11, fill=fond, outline=plume)
        self.create_text(w / 2, 11, text=self._texte, font=self._police, fill=plume)

    def definir(self, texte: str, niveau: str) -> None:
        self._texte, self._niveau = texte, niveau
        self.configure(width=self._police.measure(texte) + 24)
        self._dessiner()


# --------------------------------------------------------------------- saisie


class Champ(tk.Frame):
    """Étiquette au-dessus, saisie en dessous, aide facultative."""

    def __init__(
        self,
        parent: tk.Misc,
        etiquette: str,
        variable: tk.Variable,
        polices: theme.Polices,
        aide: str = "",
        largeur: int = 12,
        valeurs: list[str] | None = None,
        sur_changement: Callable[[], None] | None = None,
        suffixe: str = "",
        fond: str | None = None,
        largeur_aide: int = 320,
    ) -> None:
        p = theme.courante()
        self._fond = fond or p.surface
        super().__init__(parent, bg=self._fond)

        tk.Label(
            self, text=etiquette.upper(), bg=self._fond, fg=p.texte_doux,
            font=polices.etiquette, anchor="w",
        ).pack(anchor="w", pady=(0, 5))

        ligne = tk.Frame(self, bg=self._fond)
        ligne.pack(fill="x")
        if valeurs is None:
            self.saisie: ttk.Widget = ttk.Entry(
                ligne, textvariable=variable, width=largeur, font=polices.corps
            )
            if sur_changement is not None:
                variable.trace_add("write", lambda *_: sur_changement())
        else:
            self.saisie = ttk.Combobox(
                ligne, textvariable=variable, values=valeurs,
                state="readonly", width=largeur, font=polices.corps,
            )
            if sur_changement is not None:
                self.saisie.bind("<<ComboboxSelected>>", lambda _e: sur_changement())
        self.saisie.pack(side="left", fill="x", expand=True)
        if suffixe:
            tk.Label(
                ligne, text=suffixe, bg=self._fond, fg=p.texte_doux,
                font=polices.petit,
            ).pack(side="left", padx=(8, 0))

        self.aide = None
        if aide:
            self.aide = tk.Label(
                self, text=aide, bg=self._fond, fg=p.texte_faible,
                font=polices.minuscule, wraplength=largeur_aide,
                justify="left", anchor="w",
            )
            self.aide.pack(anchor="w", pady=(5, 0))

    def definir_aide(self, texte: str) -> None:
        if self.aide is not None:
            self.aide.configure(text=texte)


class ZoneApercu(tk.Canvas):
    """Cadre d'aperçu, avec un texte d'attente tant qu'il n'y a rien à montrer."""

    def __init__(self, parent: tk.Misc, largeur: int = 380, hauteur: int = 300) -> None:
        p = theme.courante()
        super().__init__(
            parent, width=largeur, height=hauteur, bg=p.surface_haute,
            highlightthickness=1, highlightbackground=p.bordure,
        )
        self._largeur = largeur
        self._hauteur = hauteur
        self._image = None  # référence gardée : Tk ne la retient pas lui-même
        self.vider()

    def vider(self, message: str = "L'aperçu s'affichera ici") -> None:
        p = theme.courante()
        self.delete("all")
        self._image = None
        self.configure(bg=p.surface_haute, highlightbackground=p.bordure)
        self.create_text(
            self._largeur // 2, self._hauteur // 2, text=message,
            fill=p.texte_faible, width=self._largeur - 40, justify="center",
        )

    def montrer(self, chemin) -> None:
        from PIL import Image, ImageTk  # noqa: PLC0415

        with Image.open(chemin) as im:
            im = im.convert("RGB")
            im.thumbnail((self._largeur - 16, self._hauteur - 16),
                         Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(im)
        self.delete("all")
        self._image = photo  # sans cette référence, l'image disparaît
        self.create_image(self._largeur // 2, self._hauteur // 2, image=photo)


# ------------------------------------------------------------------ structure


def titre_section(parent: tk.Misc, texte: str, polices: theme.Polices,
                  fond: str | None = None) -> tk.Label:
    """Petite étiquette majuscule qui sépare deux groupes de réglages."""
    p = theme.courante()
    return tk.Label(
        parent, text=texte.upper(), bg=fond or p.surface, fg=p.texte_faible,
        font=polices.etiquette, anchor="w",
    )


def trait(parent: tk.Misc, fond: str | None = None) -> tk.Frame:
    p = theme.courante()
    ligne = tk.Frame(parent, bg=p.bordure_douce, height=1)
    ligne.pack(fill="x", pady=16)
    return ligne


def cadre_defilant(parent: tk.Misc) -> tuple[tk.Canvas, ttk.Frame]:
    """Zone défilante verticale. Renvoie (canevas, cadre où empiler le contenu).

    La molette est branchée sur toute la zone : viser la barre de défilement
    debout devant une machine est pénible. La barre disparaît quand il n'y a
    rien à faire défiler.
    """
    p = theme.courante()
    canevas = tk.Canvas(parent, bg=p.fond, highlightthickness=0)
    barre = ttk.Scrollbar(parent, orient="vertical", command=canevas.yview)
    interieur = ttk.Frame(canevas, style="TFrame", padding=(0, 0, 14, 0))

    fenetre = canevas.create_window((0, 0), window=interieur, anchor="nw")
    canevas.configure(yscrollcommand=barre.set)

    def _maj(_event=None) -> None:
        boite = canevas.bbox("all")
        canevas.configure(scrollregion=boite)
        canevas.itemconfigure(fenetre, width=canevas.winfo_width())
        if boite is not None and boite[3] <= canevas.winfo_height():
            barre.pack_forget()
        else:
            barre.pack(side="right", fill="y")

    interieur.bind("<Configure>", _maj)
    canevas.bind("<Configure>", _maj)

    def _molette(event: tk.Event) -> None:
        if event.num == 4:
            pas = -1
        elif event.num == 5:
            pas = 1
        else:
            pas = -1 if event.delta > 0 else 1
        canevas.yview_scroll(pas, "units")

    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        canevas.bind_all(sequence, _molette, add="+")

    barre.pack(side="right", fill="y")
    canevas.pack(side="left", fill="both", expand=True)
    return canevas, interieur
