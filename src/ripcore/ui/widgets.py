"""Briques d'interface réutilisables.

Rien de spectaculaire, mais tout est ici pour que les écrans se lisent comme
une description de ce qu'ils montrent, pas comme du code de disposition.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from . import theme


class Carte(ttk.Frame):
    """Bloc blanc titré. L'unité de composition de tous les écrans."""

    def __init__(
        self, parent: tk.Misc, titre: str = "", aide: str = "", **kw
    ) -> None:
        super().__init__(parent, style="Carte.TFrame", padding=20, **kw)
        self.corps = self
        if titre:
            ttk.Label(self, text=titre, style="Section.TLabel").pack(
                anchor="w", pady=(0, 4 if aide else 12)
            )
        if aide:
            ttk.Label(
                self, text=aide, style="Doux.TLabel", wraplength=560, justify="left"
            ).pack(anchor="w", pady=(0, 12))


class Bandeau(ttk.Frame):
    """Message d'information ou d'alerte, pleine largeur.

    ``niveau`` vaut ``info`` (bleu) ou ``alerte`` (rouge). Rien d'autre : un
    troisième niveau intermédiaire n'aiderait personne à décider quoi faire.
    """

    def __init__(
        self,
        parent: tk.Misc,
        texte: str,
        niveau: str = "info",
        action: tuple[str, Callable[[], None]] | None = None,
    ) -> None:
        alerte = niveau == "alerte"
        super().__init__(
            parent, style="Alerte.TFrame" if alerte else "Info.TFrame", padding=(16, 12)
        )
        ttk.Label(
            self,
            text=("⚠  " if alerte else "ℹ  ") + texte,
            style="Alerte.TLabel" if alerte else "Info.TLabel",
            wraplength=680,
            justify="left",
        ).pack(side="left", fill="x", expand=True)
        if action is not None:
            libelle, rappel = action
            ttk.Button(self, text=libelle, command=rappel).pack(
                side="right", padx=(16, 0)
            )


class Champ(ttk.Frame):
    """Étiquette au-dessus, saisie en dessous, aide facultative en petit."""

    def __init__(
        self,
        parent: tk.Misc,
        etiquette: str,
        variable: tk.Variable,
        aide: str = "",
        largeur: int = 12,
        valeurs: list[str] | None = None,
        sur_changement: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, style="Carte.TFrame")
        ttk.Label(self, text=etiquette, style="Carte.TLabel").pack(anchor="w")
        if valeurs is None:
            self.saisie: ttk.Widget = ttk.Entry(
                self, textvariable=variable, width=largeur, font=None
            )
            if sur_changement is not None:
                variable.trace_add("write", lambda *_: sur_changement())
        else:
            self.saisie = ttk.Combobox(
                self,
                textvariable=variable,
                values=valeurs,
                state="readonly",
                width=largeur,
            )
            if sur_changement is not None:
                self.saisie.bind("<<ComboboxSelected>>", lambda _e: sur_changement())
        self.saisie.pack(anchor="w", pady=(4, 0), fill="x")
        if aide:
            ttk.Label(
                self, text=aide, style="Doux.TLabel", wraplength=340, justify="left"
            ).pack(anchor="w", pady=(4, 0))


class BoutonGeant(tk.Frame):
    """Grand bouton d'action, dessiné à la main.

    ttk ne permet pas de fixer une hauteur en pixels ni d'empiler deux lignes
    de texte ; or l'action principale d'un écran doit être évidente et large.
    """

    def __init__(
        self,
        parent: tk.Misc,
        texte: str,
        commande: Callable[[], None],
        polices: theme.Polices,
        sous_texte: str = "",
        variante: str = "primaire",
    ) -> None:
        couleurs = {
            "primaire": (theme.BLEU, theme.BLEU_FONCE, theme.BLANC),
            "danger": (theme.ROUGE, theme.ROUGE_FONCE, theme.BLANC),
            "neutre": (theme.BLANC, theme.BLEU_PALE, theme.BLEU),
        }[variante]
        self._fond, self._survol, self._texte_couleur = couleurs
        self._commande = commande
        self._actif = True

        super().__init__(parent, bg=self._fond, cursor="hand2",
                         highlightthickness=1,
                         highlightbackground=theme.BLEU_TRAIT
                         if variante == "neutre" else self._fond)
        pad = 14 if sous_texte else 16
        self._titre = tk.Label(
            self, text=texte, bg=self._fond, fg=self._texte_couleur,
            font=polices.bouton,
        )
        self._titre.pack(pady=(pad, 0), padx=24)
        self._sous = None
        if sous_texte:
            self._sous = tk.Label(
                self, text=sous_texte, bg=self._fond, fg=self._texte_couleur,
                font=polices.petit,
            )
            self._sous.pack(pady=(2, pad), padx=24)
        else:
            self._titre.pack_configure(pady=(pad, pad))

        for w in self._parties():
            w.bind("<Button-1>", self._clic)
            w.bind("<Enter>", lambda _e: self._peindre(self._survol))
            w.bind("<Leave>", lambda _e: self._peindre(self._fond))

    def _parties(self) -> list[tk.Widget]:
        return [w for w in (self, self._titre, self._sous) if w is not None]

    def _peindre(self, couleur: str) -> None:
        if not self._actif:
            return
        for w in self._parties():
            w.configure(bg=couleur)

    def _clic(self, _event: tk.Event) -> None:
        if self._actif:
            self._commande()

    def configurer_texte(self, texte: str) -> None:
        self._titre.configure(text=texte)

    def activer(self, actif: bool) -> None:
        self._actif = actif
        couleur = self._fond if actif else theme.DESACTIVE
        for w in self._parties():
            w.configure(bg=couleur)
        self.configure(cursor="hand2" if actif else "")


class Interrupteur(tk.Frame):
    """Interrupteur oui/non, dessiné à la main.

    La case à cocher ttk fait 13 px de côté : trop petite à viser debout, et
    son état se lit mal de loin. Un interrupteur montre sa position d'un coup
    d'œil et se clique n'importe où sur sa ligne, libellé compris.
    """

    LARGEUR = 52
    HAUTEUR = 28

    def __init__(
        self,
        parent: tk.Misc,
        texte: str,
        variable: tk.BooleanVar,
        polices: theme.Polices,
        aide: str = "",
        largeur_aide: int = 480,
    ) -> None:
        super().__init__(parent, bg=theme.BLANC)
        self.variable = variable

        ligne = tk.Frame(self, bg=theme.BLANC, cursor="hand2")
        ligne.pack(fill="x")

        self._piste = tk.Canvas(
            ligne, width=self.LARGEUR, height=self.HAUTEUR,
            bg=theme.BLANC, highlightthickness=0, cursor="hand2",
        )
        self._piste.pack(side="left")

        self._libelle = tk.Label(
            ligne, text=texte, bg=theme.BLANC, fg=theme.TEXTE,
            font=polices.corps, cursor="hand2", anchor="w",
        )
        self._libelle.pack(side="left", padx=(12, 0))

        if aide:
            tk.Label(
                self, text=aide, bg=theme.BLANC, fg=theme.TEXTE_DOUX,
                font=polices.petit, wraplength=largeur_aide, justify="left",
                anchor="w",
            ).pack(anchor="w", padx=(self.LARGEUR + 12, 0), pady=(2, 0))

        for w in (ligne, self._piste, self._libelle):
            w.bind("<Button-1>", self._basculer)
        variable.trace_add("write", lambda *_: self._dessiner())
        self._dessiner()

    def _basculer(self, _event: tk.Event) -> None:
        self.variable.set(not self.variable.get())

    def _dessiner(self) -> None:
        actif = bool(self.variable.get())
        c = self._piste
        c.delete("all")
        h = self.HAUTEUR
        r = h // 2
        fond = theme.BLEU if actif else theme.TRAIT
        # Piste en forme de gélule : deux disques et un rectangle.
        c.create_oval(0, 0, h, h, fill=fond, outline=fond)
        c.create_oval(self.LARGEUR - h, 0, self.LARGEUR, h, fill=fond, outline=fond)
        c.create_rectangle(r, 0, self.LARGEUR - r, h, fill=fond, outline=fond)
        x = self.LARGEUR - r if actif else r
        c.create_oval(
            x - r + 3, 3, x + r - 3, h - 3, fill=theme.BLANC, outline=theme.BLANC
        )


class ZoneApercu(tk.Canvas):
    """Cadre d'aperçu, avec un texte d'attente tant qu'il n'y a rien à montrer."""

    def __init__(self, parent: tk.Misc, largeur: int = 380, hauteur: int = 300) -> None:
        super().__init__(
            parent,
            width=largeur,
            height=hauteur,
            bg=theme.BLANC,
            highlightthickness=1,
            highlightbackground=theme.TRAIT,
        )
        self._largeur = largeur
        self._hauteur = hauteur
        self._image = None  # référence gardée : Tk ne la retient pas lui-même
        self.vider()

    def vider(self, message: str = "L'aperçu s'affichera ici") -> None:
        self.delete("all")
        self._image = None
        self.create_text(
            self._largeur // 2,
            self._hauteur // 2,
            text=message,
            fill=theme.TEXTE_DOUX,
            width=self._largeur - 40,
            justify="center",
        )

    def montrer(self, chemin) -> None:
        """Affiche une image, redimensionnée pour tenir dans le cadre."""
        from PIL import Image, ImageTk  # noqa: PLC0415

        with Image.open(chemin) as im:
            im = im.convert("RGB")
            im.thumbnail((self._largeur - 16, self._hauteur - 16),
                         Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(im)
        self.delete("all")
        self._image = photo  # sans cette référence, l'image disparaît
        self.create_image(self._largeur // 2, self._hauteur // 2, image=photo)


def separateur(parent: tk.Misc) -> ttk.Separator:
    s = ttk.Separator(parent, orient="horizontal")
    s.pack(fill="x", pady=14)
    return s


def cadre_defilant(parent: tk.Misc) -> tuple[tk.Canvas, ttk.Frame]:
    """Zone défilante verticale. Renvoie (canevas, cadre où empiler le contenu).

    La molette est branchée sur toute la zone : sans ça, l'opérateur doit viser
    la barre de défilement, ce qui est pénible debout devant une machine.
    """
    canevas = tk.Canvas(parent, bg=theme.FOND, highlightthickness=0)
    barre = ttk.Scrollbar(parent, orient="vertical", command=canevas.yview)
    interieur = ttk.Frame(canevas, style="TFrame", padding=(0, 0, 12, 0))

    fenetre = canevas.create_window((0, 0), window=interieur, anchor="nw")
    canevas.configure(yscrollcommand=barre.set)

    def _maj(_event=None) -> None:
        boite = canevas.bbox("all")
        canevas.configure(scrollregion=boite)
        canevas.itemconfigure(fenetre, width=canevas.winfo_width())
        # Une barre de défilement affichée alors qu'il n'y a rien à faire
        # défiler encombre et laisse croire qu'un contenu est caché.
        if boite is not None and boite[3] <= canevas.winfo_height():
            barre.pack_forget()
        else:
            barre.pack(side="right", fill="y")

    interieur.bind("<Configure>", _maj)
    canevas.bind("<Configure>", _maj)

    def _molette(event: tk.Event) -> None:
        delta = event.delta
        pas = -1 if delta > 0 else 1
        if delta in (4, 5):  # X11 renvoie des boutons, pas un delta
            pas = -1 if delta == 4 else 1
        canevas.yview_scroll(pas, "units")

    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        canevas.bind_all(sequence, _molette, add="+")

    barre.pack(side="right", fill="y")
    canevas.pack(side="left", fill="both", expand=True)
    return canevas, interieur
