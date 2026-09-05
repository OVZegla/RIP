"""Fenêtre principale : barre supérieure, rail de navigation, écrans.

Deux niveaux de lecture, sur le principe du « Lite / Pro » des outils
financiers : **Simple** ne montre que ce qu'il faut pour sortir une fresque,
**Avancé** ouvre tous les réglages. C'est la même application et le même moteur ;
seule la densité de l'écran change, et le mode est mémorisé d'une session à
l'autre.
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ..errors import RipError
from ..prnfile.validate import validate_prn
from . import textes, theme
from .ecrans import EcranImpression, EcranMachine, EcranTests, EcranTravaux
from .session import Session, dossier_documents
from .widgets import Puce, Segments
from .worker import Tache

TAILLE_MINIMALE = (1180, 760)
TAILLE_DEFAUT = "1400x880"
FICHIER_PREFERENCES = "preferences.json"


class Application(tk.Tk):
    def __init__(self, profil: Path | None = None) -> None:
        super().__init__()
        self.title(f"{textes.MARQUE} · {textes.APP_NOM}")
        self.geometry(TAILLE_DEFAUT)
        self.minsize(*TAILLE_MINIMALE)

        self._prefs = _lire_preferences()
        theme.definir(theme.PALETTES.get(self._prefs.get("palette", "sombre"),
                                         theme.SOMBRE))
        self.polices = theme.Polices(self)
        theme.appliquer(self, self.polices, theme.courante())
        self.configure(bg=theme.courante().fond)

        self.session = Session.ouvrir(profil)
        self.tache = Tache(self)
        self.mode = tk.StringVar(value=self._prefs.get("mode", textes.MODE_SIMPLE))
        self.ecrans: dict[str, ttk.Frame] = {}
        self._boutons_nav: dict[str, tk.Frame] = {}
        self._actif = ""

        self._construire()
        self.aller_a("impression")
        self.protocol("WM_DELETE_WINDOW", self._fermer)

    # -- construction ---------------------------------------------------------

    def _construire(self) -> None:
        p = theme.courante()

        barre = tk.Frame(self, bg=p.rail, height=theme.BARRE_HAUTEUR)
        barre.pack(fill="x", side="top")
        barre.pack_propagate(False)
        self._barre = barre
        self._construire_barre(barre)

        tk.Frame(self, bg=p.bordure, height=1).pack(fill="x", side="top")

        bas = tk.Frame(self, bg=p.fond)
        bas.pack(fill="both", expand=True)

        rail = tk.Frame(bas, bg=p.rail, width=theme.RAIL_LARGEUR)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        self._rail = rail
        for cle, libelle, aide in textes.NAV:
            self._boutons_nav[cle] = self._bouton_nav(rail, cle, libelle, aide)

        pied = tk.Frame(rail, bg=p.rail)
        pied.pack(side="bottom", fill="x", padx=18, pady=16)
        self.lbl_machine = tk.Label(
            pied, text="", bg=p.rail, fg=p.rail_texte_faible, font=self.polices.minuscule,
            anchor="w", justify="left", wraplength=theme.RAIL_LARGEUR - 36,
        )
        self.lbl_machine.pack(fill="x")

        principal = tk.Frame(bas, bg=p.fond)
        principal.pack(side="left", fill="both", expand=True)

        self.conteneur = tk.Frame(principal, bg=p.fond)
        self.conteneur.pack(fill="both", expand=True)

        tk.Frame(principal, bg=p.bordure, height=1).pack(fill="x", side="bottom")
        etat = tk.Frame(principal, bg=p.fond, height=30)
        etat.pack(fill="x", side="bottom")
        etat.pack_propagate(False)
        self.lbl_statut = tk.Label(
            etat, text="", bg=p.fond, fg=p.texte_faible,
            font=self.polices.minuscule, anchor="w",
        )
        self.lbl_statut.pack(side="left", padx=24)

        self.ecrans = {
            "impression": EcranImpression(self.conteneur, self),
            "tests": EcranTests(self.conteneur, self),
            "machine": EcranMachine(self.conteneur, self),
            "travaux": EcranTravaux(self.conteneur, self),
        }
        self._maj_machine()

    def _construire_barre(self, barre: tk.Frame) -> None:
        p = theme.courante()

        gauche = tk.Frame(barre, bg=p.rail)
        gauche.pack(side="left", fill="y", padx=(24, 0))
        tk.Label(
            gauche, text=textes.MARQUE, bg=p.rail, fg=p.rail_texte,
            font=self.polices.marque,
        ).pack(side="left", pady=16)
        tk.Frame(gauche, bg=p.accent, width=3, height=20).pack(
            side="left", padx=12, pady=20
        )
        tk.Label(
            gauche, text=textes.APP_NOM, bg=p.rail, fg=p.rail_texte_doux,
            font=self.polices.corps,
        ).pack(side="left")

        droite = tk.Frame(barre, bg=p.rail)
        droite.pack(side="right", fill="y", padx=(0, 24))

        self._bouton_palette = tk.Label(
            droite, text=self._icone_palette(), bg=p.rail, fg=p.rail_texte_doux,
            font=self.polices.corps_gras, cursor="hand2", padx=10, pady=4,
        )
        self._bouton_palette.pack(side="right", pady=14, padx=(16, 0))
        self._bouton_palette.bind("<Button-1>", lambda _e: self.basculer_palette())

        self.segments = Segments(
            droite, textes.MODES, self.mode, self.polices,
            sur_changement=self._mode_change,
        )
        self.segments.configure(bg=p.rail)
        self.segments.pack(side="right", pady=13)

        centre = tk.Frame(barre, bg=p.rail)
        centre.pack(side="right", fill="y", padx=(0, 28))
        self.puce_etat = Puce(
            centre, textes.ETAT_PRET, self.polices, fond_parent=p.rail
        )
        self.puce_etat.pack(side="right", pady=19)
        self.lbl_presse = tk.Label(
            centre, text="", bg=p.rail, fg=p.rail_texte_doux, font=self.polices.petit,
        )
        self.lbl_presse.pack(side="right", padx=(0, 10))

    def _bouton_nav(self, parent: tk.Misc, cle: str, libelle: str,
                    aide: str) -> tk.Frame:
        p = theme.courante()
        cadre = tk.Frame(parent, bg=p.rail, cursor="hand2")
        cadre.pack(fill="x")

        barre = tk.Frame(cadre, bg=p.rail, width=3)
        barre.pack(side="left", fill="y")

        contenu = tk.Frame(cadre, bg=p.rail, padx=18, pady=13)
        contenu.pack(side="left", fill="x", expand=True)

        titre = tk.Label(
            contenu, text=libelle, bg=p.rail, fg=p.rail_texte, font=self.polices.nav,
            anchor="w",
        )
        titre.pack(fill="x")
        sous = tk.Label(
            contenu, text=aide, bg=p.rail, fg=p.rail_texte_faible,
            font=self.polices.minuscule, anchor="w", justify="left",
            wraplength=theme.RAIL_LARGEUR - 46,
        )
        sous.pack(fill="x")

        cadre._parties = (cadre, contenu, titre, sous)  # type: ignore[attr-defined]
        cadre._barre = barre  # type: ignore[attr-defined]
        cadre._titre = titre  # type: ignore[attr-defined]
        for w in (cadre, contenu, titre, sous):
            w.bind("<Button-1>", lambda _e, c=cle: self.aller_a(c))
            w.bind("<Enter>", lambda _e, c=cle: self._survol_nav(c, True))
            w.bind("<Leave>", lambda _e, c=cle: self._survol_nav(c, False))
        return cadre

    def _survol_nav(self, cle: str, dessus: bool) -> None:
        if cle == self._actif:
            return
        p = theme.courante()
        couleur = p.rail_actif if dessus else p.rail
        for w in self._boutons_nav[cle]._parties:  # type: ignore[attr-defined]
            w.configure(bg=couleur)

    # -- navigation -----------------------------------------------------------

    def aller_a(self, cle: str) -> None:
        if cle not in self.ecrans:
            return
        p = theme.courante()
        for autre, cadre in self._boutons_nav.items():
            actif = autre == cle
            fond = p.rail_actif if actif else p.rail
            for w in cadre._parties:  # type: ignore[attr-defined]
                w.configure(bg=fond)
            cadre._titre.configure(fg=p.rail_texte if actif else p.rail_texte_doux)  # type: ignore[attr-defined]
            cadre._barre.configure(bg=p.accent if actif else fond)  # type: ignore[attr-defined]

        for ecran in self.ecrans.values():
            ecran.pack_forget()
        ecran = self.ecrans[cle]
        if hasattr(ecran, "rafraichir"):
            ecran.rafraichir()
        ecran.pack(fill="both", expand=True)
        self._actif = cle

    # -- mode et palette -------------------------------------------------------

    @property
    def avance(self) -> bool:
        return self.mode.get() == textes.MODE_AVANCE

    def _mode_change(self, _cle: str) -> None:
        for ecran in self.ecrans.values():
            if hasattr(ecran, "mode_change"):
                ecran.mode_change()
        self.statut(textes.MODE_AIDE.get(self.mode.get(), ""))
        self._enregistrer_preferences()

    def basculer_palette(self) -> None:
        """Sombre ↔ clair. Reconstruit la fenêtre : ttk ne re-stylise pas à chaud."""
        suivante = theme.CLAIR if theme.courante().nom == "sombre" else theme.SOMBRE
        theme.definir(suivante)
        self._enregistrer_preferences()
        self._reconstruire()

    def _icone_palette(self) -> str:
        return "☾" if theme.courante().nom == "sombre" else "☀"

    def _reconstruire(self) -> None:
        """Refait toute la fenêtre avec la palette courante.

        Changer un thème ttk à chaud ne repeint pas les widgets tk classiques
        déjà créés. Tout reconstruire est brutal mais parfaitement fiable, et
        l'opération est rare : c'est le bon compromis.
        """
        actif = self._actif
        mode = self.mode.get()
        for enfant in self.winfo_children():
            enfant.destroy()
        theme.appliquer(self, self.polices, theme.courante())
        self.configure(bg=theme.courante().fond)
        self._boutons_nav.clear()
        self.mode = tk.StringVar(value=mode)
        self._construire()
        self.aller_a(actif or "impression")

    # -- services offerts aux écrans -----------------------------------------

    def statut(self, message: str) -> None:
        self.lbl_statut.configure(text=message)

    def profil_modifie(self) -> None:
        for ecran in self.ecrans.values():
            if hasattr(ecran, "session"):
                ecran.session = self.session
            if hasattr(ecran, "rafraichir"):
                ecran.rafraichir()
        self._maj_machine()

    def rafraichir_historique(self) -> None:
        self.ecrans["travaux"].rafraichir()

    def _maj_machine(self) -> None:
        profil = self.session.profil
        self.lbl_presse.configure(text=profil.name)
        if self.session.presse_reglee:
            self.puce_etat.definir(textes.ETAT_PRET, "info")
        else:
            self.puce_etat.definir(textes.ETAT_A_REGLER, "alerte")
        self.lbl_machine.configure(
            text=f"Bande {profil.max_width_mm:.0f} mm\n"
                 f"Hauteur max {profil.max_height_mm:.0f} mm"
        )

    def montrer_erreur(self, exc: Exception) -> None:
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

        L'envoi réseau n'est pas activé : la syntaxe exacte attendue par
        BetterPrinter n'a pas été relevée. On garantit donc ce qui est
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
            "Fichier prêt pour la machine",
            f"{fichier.name} est contrôlé et valide.\n\n"
            "Ouvrez-le dans BetterPrinter pour lancer l'impression.",
        )
        ouvrir_dossier(fichier.parent)

    # -- préférences -----------------------------------------------------------

    def _enregistrer_preferences(self) -> None:
        _ecrire_preferences({
            "mode": self.mode.get(),
            "palette": theme.courante().nom,
        })

    def _fermer(self) -> None:
        self._enregistrer_preferences()
        self.destroy()


class DetailErreur(tk.Toplevel):
    """Détail technique, à copier-coller pour demander de l'aide."""

    def __init__(self, parent: tk.Misc, texte: str) -> None:
        p = theme.courante()
        super().__init__(parent)
        self.title("Détail technique")
        self.geometry("860x480")
        self.configure(bg=p.fond)

        cadre = tk.Frame(self, bg=p.fond, padx=20, pady=20)
        cadre.pack(fill="both", expand=True)
        tk.Label(
            cadre,
            text="Copiez ce texte et transmettez-le : il indique où le problème "
                 "s'est produit.",
            bg=p.fond, fg=p.texte_doux, font=parent.polices.petit,  # type: ignore[attr-defined]
            anchor="w",
        ).pack(anchor="w", pady=(0, 12))

        zone = tk.Text(
            cadre, wrap="none", bg=p.surface, fg=p.texte, relief="flat",
            padx=14, pady=14, insertbackground=p.texte,
            font=parent.polices.chiffre,  # type: ignore[attr-defined]
        )
        zone.insert("1.0", texte)
        zone.configure(state="disabled")
        zone.pack(fill="both", expand=True)

        ttk.Button(cadre, text="Fermer", command=self.destroy).pack(
            anchor="e", pady=(14, 0)
        )


def _fichier_preferences() -> Path:
    return dossier_documents() / FICHIER_PREFERENCES


def _lire_preferences() -> dict:
    try:
        return json.loads(_fichier_preferences().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _ecrire_preferences(valeurs: dict) -> None:
    chemin = _fichier_preferences()
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(valeurs, indent=1), encoding="utf-8")
    except OSError:
        pass  # préférences indisponibles : sans conséquence sur le travail


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    profil = Path(args[0]) if args else None
    try:
        app = Application(profil)
    except RipError as exc:
        racine = tk.Tk()
        racine.withdraw()
        messagebox.showerror(textes.ERREUR_TITRE, str(exc))
        racine.destroy()
        return 2
    app.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
