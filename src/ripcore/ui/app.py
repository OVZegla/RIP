"""Fenêtre principale : navigation, barre d'état, erreurs.

Une seule fenêtre, quatre écrans, pas de menus déroulants. Un opérateur ne doit
jamais avoir à chercher où se trouve une fonction : tout est dans la colonne de
gauche, en permanence.
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ..errors import RipError
from ..prnfile.validate import validate_prn
from . import textes, theme
from .ecrans import EcranImpression, EcranMachine, EcranTests, EcranTravaux
from .session import Session

from .worker import Tache

TAILLE_MINIMALE = (1120, 720)
TAILLE_DEFAUT = "1240x820"


class Application(tk.Tk):
    def __init__(self, profil: Path | None = None) -> None:
        super().__init__()
        self.title(f"{textes.APP_NOM} — {textes.APP_SOUS_TITRE}")
        self.geometry(TAILLE_DEFAUT)
        self.minsize(*TAILLE_MINIMALE)
        self.configure(bg=theme.FOND)

        self.polices = theme.Polices(self)
        theme.appliquer(self, self.polices)

        self.session = Session.ouvrir(profil)
        self.tache = Tache(self)
        self.ecrans: dict[str, ttk.Frame] = {}
        self._boutons_nav: dict[str, tk.Frame] = {}
        self._actif = ""

        self._construire()
        self.aller_a("impression")

    # -- construction ---------------------------------------------------------

    def _construire(self) -> None:
        nav = tk.Frame(self, bg=theme.BLEU, width=theme.NAV_LARGEUR)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)

        titre = tk.Frame(nav, bg=theme.BLEU)
        titre.pack(fill="x", pady=(26, 8), padx=20)
        tk.Label(
            titre, text=textes.APP_NOM, bg=theme.BLEU, fg=theme.BLANC,
            font=self.polices.section, anchor="w", justify="left",
            wraplength=theme.NAV_LARGEUR - 44,
        ).pack(fill="x")

        # Filet bleu-blanc-rouge : repère visuel discret, pas un décor.
        drapeau = tk.Frame(nav, bg=theme.BLEU, height=4)
        drapeau.pack(fill="x", padx=20, pady=(6, 20))
        for couleur, poids in ((theme.BLEU_PALE, 1), (theme.BLANC, 1), (theme.ROUGE, 1)):
            bande = tk.Frame(drapeau, bg=couleur, height=4)
            bande.pack(side="left", fill="both", expand=True)

        for cle, libelle, aide in textes.NAV:
            self._boutons_nav[cle] = self._bouton_nav(nav, cle, libelle, aide)

        bas = tk.Frame(nav, bg=theme.BLEU)
        bas.pack(side="bottom", fill="x", padx=20, pady=18)
        self.lbl_presse = tk.Label(
            bas, text="", bg=theme.BLEU, fg=theme.BLEU_PALE,
            font=self.polices.nav_aide, anchor="w", justify="left", wraplength=190,
        )
        self.lbl_presse.pack(fill="x")

        principal = ttk.Frame(self, style="TFrame")
        principal.pack(side="left", fill="both", expand=True)

        self.conteneur = ttk.Frame(principal, style="TFrame")
        self.conteneur.pack(fill="both", expand=True)

        barre = ttk.Frame(principal, style="TFrame", padding=(28, 8))
        barre.pack(fill="x", side="bottom")
        ttk.Separator(principal, orient="horizontal").pack(
            fill="x", side="bottom"
        )
        self.lbl_statut = ttk.Label(barre, text="", style="DouxFond.TLabel")
        self.lbl_statut.pack(side="left")

        self.ecrans = {
            "impression": EcranImpression(self.conteneur, self),
            "tests": EcranTests(self.conteneur, self),
            "machine": EcranMachine(self.conteneur, self),
            "travaux": EcranTravaux(self.conteneur, self),
        }
        self._maj_pied()

    def _bouton_nav(self, parent: tk.Misc, cle: str, libelle: str, aide: str) -> tk.Frame:
        cadre = tk.Frame(parent, bg=theme.BLEU, cursor="hand2")
        cadre.pack(fill="x")

        barre = tk.Frame(cadre, bg=theme.BLEU, width=4)
        barre.pack(side="left", fill="y")

        contenu = tk.Frame(cadre, bg=theme.BLEU, padx=16, pady=12)
        contenu.pack(side="left", fill="x", expand=True)

        titre = tk.Label(
            contenu, text=libelle, bg=theme.BLEU, fg=theme.BLANC,
            font=self.polices.nav, anchor="w",
        )
        titre.pack(fill="x")
        sous = tk.Label(
            contenu, text=aide, bg=theme.BLEU, fg=theme.BLEU_PALE,
            font=self.polices.nav_aide, anchor="w", justify="left", wraplength=170,
        )
        sous.pack(fill="x")

        cadre._parties = (cadre, contenu, titre, sous)  # type: ignore[attr-defined]
        cadre._barre = barre  # type: ignore[attr-defined]
        for w in (cadre, contenu, titre, sous):
            w.bind("<Button-1>", lambda _e, c=cle: self.aller_a(c))
            w.bind("<Enter>", lambda _e, c=cle: self._survol_nav(c, True))
            w.bind("<Leave>", lambda _e, c=cle: self._survol_nav(c, False))
        return cadre

    def _survol_nav(self, cle: str, dessus: bool) -> None:
        if cle == self._actif:
            return
        couleur = theme.BLEU_FONCE if dessus else theme.BLEU
        cadre = self._boutons_nav[cle]
        for w in cadre._parties:  # type: ignore[attr-defined]
            w.configure(bg=couleur)

    # -- navigation -----------------------------------------------------------

    def aller_a(self, cle: str) -> None:
        if cle not in self.ecrans:
            return
        for autre, cadre in self._boutons_nav.items():
            actif = autre == cle
            fond = theme.BLEU_FONCE if actif else theme.BLEU
            for w in cadre._parties:  # type: ignore[attr-defined]
                w.configure(bg=fond)
            cadre._barre.configure(bg=theme.BLANC if actif else fond)  # type: ignore[attr-defined]

        for ecran in self.ecrans.values():
            ecran.pack_forget()
        ecran = self.ecrans[cle]
        if hasattr(ecran, "rafraichir"):
            ecran.rafraichir()
        ecran.pack(fill="both", expand=True)
        self._actif = cle

    # -- services offerts aux écrans -----------------------------------------

    def statut(self, message: str) -> None:
        self.lbl_statut.configure(text=message)

    def profil_modifie(self) -> None:
        """Le profil vient de changer : tous les écrans doivent se remettre à jour."""
        for ecran in self.ecrans.values():
            if hasattr(ecran, "session"):
                ecran.session = self.session
            if hasattr(ecran, "rafraichir"):
                ecran.rafraichir()
        self._maj_pied()

    def rafraichir_historique(self) -> None:
        self.ecrans["travaux"].rafraichir()

    def _maj_pied(self) -> None:
        profil = self.session.profil
        etat = textes.ETAT_PRET if self.session.presse_reglee else textes.ETAT_A_REGLER
        self.lbl_presse.configure(text=f"{profil.name}\n{etat}")

    def montrer_erreur(self, exc: Exception) -> None:
        """Erreur en langage d'atelier, détail technique disponible mais replié."""
        self.statut("")
        if isinstance(exc, RipError):
            messagebox.showerror(textes.ERREUR_TITRE, str(exc))
            return
        detail = self.tache.derniere_trace or repr(exc)
        message = (
            "Une erreur inattendue s'est produite.\n\n"
            f"{textes.ERREUR_GENERIQUE}\n{type(exc).__name__} : {exc}\n\n"
            "Voulez-vous voir le détail complet ? Il aide à corriger le problème."
        )
        if messagebox.askyesno(textes.ERREUR_TITRE, message):
            DetailErreur(self, detail)

    # -- envoi ----------------------------------------------------------------

    def envoyer(self, fichier: Path) -> None:
        """Contrôle puis dépose le fichier là où BetterPrinter le trouvera.

        L'envoi réseau n'est pas encore activé : la syntaxe exacte attendue par
        BetterPrinter n'a pas été relevée. En attendant, on garantit ce qui est
        garantissable — un fichier valide, dans un dossier connu — plutôt que
        d'envoyer à l'aveugle une commande qui pourrait être mal comprise.
        """
        rapport = validate_prn(fichier, self.session.profil)
        if not rapport.ok:
            messagebox.showerror(
                textes.ERREUR_TITRE,
                "Ce fichier n'a pas passé le contrôle et n'a pas été envoyé.\n\n"
                + "\n".join(f.message for f in rapport.errors),
            )
            return
        from .session import ouvrir_dossier  # noqa: PLC0415

        messagebox.showinfo(
            "Fichier prêt pour la presse",
            f"{fichier.name} est contrôlé et valide.\n\n"
            "Ouvrez-le dans BetterPrinter pour lancer l'impression.",
        )
        ouvrir_dossier(fichier.parent)


class DetailErreur(tk.Toplevel):
    """Fenêtre de détail technique, à copier-coller pour demander de l'aide."""

    def __init__(self, parent: tk.Misc, texte: str) -> None:
        super().__init__(parent)
        self.title("Détail technique")
        self.geometry("820x460")
        self.configure(bg=theme.FOND)

        cadre = ttk.Frame(self, style="TFrame", padding=16)
        cadre.pack(fill="both", expand=True)
        ttk.Label(
            cadre,
            text="Copiez ce texte et transmettez-le : il indique où le problème "
                 "s'est produit.",
            style="DouxFond.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        zone = tk.Text(cadre, wrap="none", bg=theme.BLANC, fg=theme.TEXTE,
                       relief="flat", padx=12, pady=12)
        zone.insert("1.0", texte)
        zone.configure(state="disabled")
        zone.pack(fill="both", expand=True)

        ttk.Button(cadre, text="Fermer", command=self.destroy).pack(
            anchor="e", pady=(12, 0)
        )


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée de l'interface."""
    args = list(sys.argv[1:] if argv is None else argv)
    profil = Path(args[0]) if args else None
    try:
        app = Application(profil)
    except RipError as exc:
        # Avant que la fenêtre existe, il faut quand même dire ce qui manque.
        racine = tk.Tk()
        racine.withdraw()
        messagebox.showerror(textes.ERREUR_TITRE, str(exc))
        racine.destroy()
        return 2
    app.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
