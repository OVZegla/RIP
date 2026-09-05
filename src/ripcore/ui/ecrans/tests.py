"""Écran « Tests machine ».

Les trois mires, présentées comme une progression numérotée plutôt que comme
une liste d'outils. Chaque carte dit à quoi sert le test, combien de temps ça
prend, ce qu'il faut comme matériel — et propose ensuite de saisir le résultat.

La saisie du test n° 1 est le moment le plus important de toute l'application :
c'est là que la presse cesse d'être une inconnue.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ...calibration import build_linearization, drop_densities, read_measurements
from ...errors import RipError
from ...halftone.engines import make_halftoner
from ...pipeline import write_target_prn
from ...profiles import DropLevels, PrinterProfile
from ...profiles_io import reorder_channels, save_profile
from ...targets import channel_id, drop_wedge, lin_wedge
from .. import textes, theme
from ..session import ouvrir_dossier
from ..widgets import BoutonAction, Carte, cadre_defilant


class EcranTests(tk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        p = theme.courante()
        super().__init__(parent, bg=p.fond)
        self.app = app
        self.session = app.session
        self.polices = app.polices
        self._etats: dict[str, tk.Label] = {}
        self._construire()
        self.rafraichir()

    def _construire(self) -> None:
        p = theme.courante()
        entete = tk.Frame(self, bg=p.fond, padx=28, pady=22)
        entete.pack(fill="x")
        tk.Label(entete, text=textes.TESTS_TITRE, bg=p.fond, fg=p.texte,
                 font=self.polices.titre, anchor="w").pack(anchor="w")
        tk.Label(entete, text=textes.TESTS_INTRO, bg=p.fond, fg=p.texte_doux,
                 font=self.polices.petit, wraplength=820, justify="left",
                 anchor="w").pack(anchor="w", pady=(6, 0))

        hote = tk.Frame(self, bg=p.fond, padx=28, pady=8)
        hote.pack(fill="both", expand=True)
        _, corps = cadre_defilant(hote)

        for test in textes.TESTS:
            self._carte_test(corps, test)

    def _carte_test(self, parent: tk.Misc, test: dict) -> None:
        p = theme.courante()
        carte = Carte(parent, polices=self.polices)
        carte.pack(fill="x", pady=(0, 14))
        corps = carte.corps()

        haut = tk.Frame(corps, bg=p.surface)
        haut.pack(fill="x")

        tk.Label(haut, text=test["numero"], bg=p.accent, fg=p.accent_texte,
                 font=self.polices.chiffre_grand, width=2,
                 ).pack(side="left", padx=(0, 18), ipady=8)

        titres = tk.Frame(haut, bg=p.surface)
        titres.pack(side="left", fill="x", expand=True)
        tk.Label(titres, text=test["titre"], bg=p.surface, fg=p.texte,
                 font=self.polices.section, anchor="w").pack(anchor="w")
        tk.Label(titres, text=test["resume"], bg=p.surface, fg=p.texte_doux,
                 font=self.polices.petit, anchor="w").pack(anchor="w")

        etat = tk.Label(haut, text="", bg=p.surface, fg=p.texte_doux,
                        font=self.polices.etiquette)
        etat.pack(side="right", anchor="n", pady=4)
        self._etats[test["cle"]] = etat

        self._detail = tk.Label(
            corps, text=test["detail"], bg=p.surface, fg=p.texte_doux,
            font=self.polices.petit, wraplength=740, justify="left", anchor="w",
        )
        self._detail.pack(anchor="w", pady=(16, 8))
        carte._detail = self._detail  # type: ignore[attr-defined]

        tk.Label(corps, text=test["duree"], bg=p.surface, fg=p.texte_faible,
                 font=self.polices.minuscule, anchor="w").pack(anchor="w",
                                                               pady=(0, 16))

        boutons = tk.Frame(corps, bg=p.surface)
        boutons.pack(fill="x")
        bouton = BoutonAction(boutons, test["bouton"],
                              lambda t=test: self._creer(t), self.polices)
        bouton.configure(width=self.polices.bouton.measure(test["bouton"]) + 48)
        bouton.pack(side="left")
        ttk.Button(boutons, text=test["saisie"],
                   command=lambda t=test: self._saisir(t)).pack(side="left",
                                                                padx=(12, 0))

    # -- création des mires ---------------------------------------------------

    def _creer(self, test: dict) -> None:
        if self.app.tache.en_cours:
            return
        cle = test["cle"]
        profil = self.session.profil
        dossier = self.session.dossier_tests
        dossier.mkdir(parents=True, exist_ok=True)
        sortie = dossier / f"test-{cle}.prn"

        def travail(_avancement):
            if cle == "channel-id":
                mire = channel_id(profil)
            elif cle == "drop-wedge":
                mire = drop_wedge(profil)
            else:
                trameur = make_halftoner(
                    "bluenoise", profil.drop_levels.densities, profil.n_channels
                )
                mire = lin_wedge(profil, trameur)
            write_target_prn(mire, profil, sortie)
            if cle != "channel-id":
                _ecrire_grille(dossier / f"mesures-{cle}.csv", profil, mire, cle)
            return sortie

        self.app.statut(f"Création du {test['titre'].lower()}…")
        self.app.tache.lancer(
            travail, sur_fin=lambda p: self._cree(test, p),
            sur_erreur=self.app.montrer_erreur,
        )

    def _cree(self, test: dict, chemin: Path) -> None:
        self.app.statut("")
        suite = (
            "Ouvrez-le dans BetterPrinter et imprimez-le sur une chute."
            if test["cle"] == "channel-id"
            else "Imprimez-le, mesurez les cases, puis remplissez le tableau "
                 "déposé à côté du fichier."
        )
        messagebox.showinfo(
            test["titre"],
            f"Fichier créé :\n{chemin.name}\n\n{suite}",
        )
        ouvrir_dossier(chemin.parent)

    # -- saisie des résultats -------------------------------------------------

    def _saisir(self, test: dict) -> None:
        if test["cle"] == "channel-id":
            DialogueCouleurs(self, self.app)
        else:
            self._charger_mesures(test)

    def _charger_mesures(self, test: dict) -> None:
        chemin = filedialog.askopenfilename(
            title="Ouvrir le tableau de mesures",
            initialdir=str(self.session.dossier_tests),
            filetypes=[("Tableau de mesures", "*.csv"), ("Tous les fichiers", "*.*")],
        )
        if not chemin:
            return
        try:
            mesures = read_measurements(chemin)
            if test["cle"] == "drop-wedge":
                self._appliquer_gouttes(mesures)
            else:
                self._appliquer_degrade(mesures)
        except RipError as exc:
            messagebox.showerror(textes.ERREUR_TITRE, str(exc))

    def _appliquer_gouttes(self, mesures) -> None:
        profil = self.session.profil
        valeurs = drop_densities(mesures, 1 << profil.bits_per_pixel)
        nouveau = _remplacer_gouttes(profil, valeurs)
        save_profile(nouveau, self.session.profil_chemin)
        self.session.recharger_profil()
        self.app.profil_modifie()
        messagebox.showinfo(
            "Tailles de goutte enregistrées",
            "Le logiciel connaît maintenant la quantité d'encre de chaque "
            "taille de goutte :\n\n"
            + "\n".join(
                f"  goutte {i} : {v * 100:.0f} %"
                for i, v in enumerate(valeurs) if i
            ),
        )

    def _appliquer_degrade(self, mesures) -> None:
        lin = build_linearization(mesures, notes="Saisi depuis l'interface")
        dossier = self.session.dossier_tests / "reglages"
        dossier.mkdir(parents=True, exist_ok=True)
        cible = dossier / "reglage-couleurs.json"
        lin.save(cible)
        messagebox.showinfo(
            "Réglage des couleurs enregistré",
            f"Enregistré dans :\n{cible}\n\n"
            "Indiquez ce fichier dans le profil de support "
            "(ligne « linearization ») pour qu'il s'applique aux impressions.",
        )

    # -- état -----------------------------------------------------------------

    def mode_change(self) -> None:
        """En mode simple, le détail des tests reste replié à l'essentiel."""

    def rafraichir(self) -> None:
        p = theme.courante()
        profil = self.session.profil
        faits = {
            "channel-id": profil.channel_order_verified,
            "drop-wedge": profil.drop_levels.calibrated,
            "lin-wedge": None,  # dépend du profil de support, pas de la presse
        }
        for cle, etat in self._etats.items():
            fait = faits.get(cle)
            if fait is True:
                etat.configure(text="FAIT", fg=p.accent)
            elif fait is False:
                etat.configure(text="À FAIRE", fg=p.danger)
            else:
                etat.configure(text="", fg=p.texte_doux)


class DialogueCouleurs(tk.Toplevel):
    """Saisie de l'ordre des encres, d'après le tirage du test n° 1."""

    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent)
        self.app = app
        self.session = app.session
        profil = self.session.profil

        p = theme.courante()
        self.title(textes.SAISIE_COULEURS_TITRE)
        self.configure(bg=p.fond)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.resizable(False, False)

        cadre = tk.Frame(self, bg=p.fond, padx=26, pady=26)
        cadre.pack(fill="both", expand=True)

        tk.Label(cadre, text=textes.SAISIE_COULEURS_TITRE, bg=p.fond, fg=p.texte,
                 font=app.polices.titre, anchor="w").pack(anchor="w")
        tk.Label(cadre, text=textes.SAISIE_COULEURS_AIDE, bg=p.fond,
                 fg=p.texte_doux, font=app.polices.petit, wraplength=520,
                 justify="left", anchor="w").pack(anchor="w", pady=(8, 22))

        self.choix: list[tk.StringVar] = []
        noms = [textes.nom_encre(c) for c in profil.channel_names]
        self._codes = {textes.nom_encre(c): c for c in profil.channel_names}

        grille = tk.Frame(cadre, bg=p.fond)
        grille.pack(fill="x")
        for i, code in enumerate(profil.channel_names):
            ligne = tk.Frame(grille, bg=p.fond)
            ligne.pack(fill="x", pady=6)

            tk.Label(
                ligne,
                text=textes.SAISIE_COULEURS_BARRE.format(n=i + 1, s="s" if i else ""),
                bg=p.fond, fg=p.texte, font=app.polices.corps, width=18,
                anchor="w",
            ).pack(side="left")
            reperes = tk.Frame(ligne, bg=p.fond, width=110)
            reperes.pack(side="left")
            reperes.pack_propagate(False)
            for _ in range(i + 1):
                tk.Frame(reperes, bg=p.texte_doux, width=11, height=11).pack(
                    side="left", padx=2, pady=6
                )

            var = tk.StringVar(value=textes.nom_encre(code))
            self.choix.append(var)
            ttk.Combobox(
                ligne, textvariable=var, values=noms, state="readonly", width=20
            ).pack(side="left", padx=(10, 0))

        boutons = tk.Frame(cadre, bg=p.fond)
        boutons.pack(fill="x", pady=(26, 0))
        ttk.Button(boutons, text="Annuler", command=self.destroy).pack(side="right")
        ttk.Button(
            boutons, text=textes.SAISIE_COULEURS_VALIDER,
            command=self._valider, style="Accent.TButton",
        ).pack(side="right", padx=(0, 10))

        self.update_idletasks()
        _centrer(self, parent.winfo_toplevel())

    def _valider(self) -> None:
        ordre = [self._codes[v.get()] for v in self.choix]
        if len(set(ordre)) != len(ordre):
            messagebox.showwarning(
                textes.ERREUR_TITRE, textes.SAISIE_COULEURS_DOUBLON, parent=self
            )
            return
        try:
            nouveau = reorder_channels(self.session.profil, ordre)
            save_profile(nouveau, self.session.profil_chemin)
        except RipError as exc:
            messagebox.showerror(textes.ERREUR_TITRE, str(exc), parent=self)
            return

        self.session.recharger_profil()
        self.app.profil_modifie()
        self.destroy()
        messagebox.showinfo(
            "Machine identifiée",
            "L'ordre des encres est enregistré :\n\n"
            + "\n".join(
                f"  {i + 1}. {textes.nom_encre(c)}" for i, c in enumerate(ordre)
            )
            + "\n\nVous pouvez imprimer normalement.",
        )


def _centrer(fenetre: tk.Toplevel, parent: tk.Misc) -> None:
    fenetre.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - fenetre.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - fenetre.winfo_height()) // 3
    fenetre.geometry(f"+{max(0, x)}+{max(0, y)}")


def _remplacer_gouttes(
    profil: PrinterProfile, valeurs: tuple[float, ...]
) -> PrinterProfile:
    return PrinterProfile(
        name=profil.name,
        head=profil.head,
        bits_per_pixel=profil.bits_per_pixel,
        channels=profil.channels,
        pass_mode_by_dpi_y=dict(profil.pass_mode_by_dpi_y),
        drop_levels=DropLevels(valeurs, calibrated=True),
        ink_limit_channel=dict(profil.ink_limit_channel),
        ink_limit_total=profil.ink_limit_total,
        max_width_mm=profil.max_width_mm,
        ink_limit_total_all=profil.ink_limit_total_all,
        channel_order_verified=profil.channel_order_verified,
        drop_levels_verified=True,
        source=profil.source,
        notes=profil.notes,
    )


def _ecrire_grille(chemin: Path, profil, mire, cle: str) -> None:
    """Tableau de saisie des mesures, à côté de la mire."""
    lignes = ["channel,kind,value,measurement"]
    if cle == "drop-wedge":
        for nom in profil.channel_names:
            lignes.append(f"{nom},level,0,")
    for plage in mire.patches:
        lignes.append(f"{plage.channel},{plage.kind},{plage.value:g},")
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
