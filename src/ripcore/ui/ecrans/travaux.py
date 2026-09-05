"""Écran « Historique » — les fichiers déjà préparés.

Sert à deux choses concrètes : retrouver un travail pour le renvoyer sans tout
refaire, et vérifier après coup ce qui a été consommé en encre sur un chantier.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .. import textes, theme
from ..session import ouvrir_dossier
from ..widgets import BoutonAction, Carte


class EcranTravaux(tk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        p = theme.courante()
        super().__init__(parent, bg=p.fond)
        self.app = app
        self.session = app.session
        self.polices = app.polices
        self._travaux: list = []
        self._construire()
        self.rafraichir()

    def _construire(self) -> None:
        p = theme.courante()
        entete = tk.Frame(self, bg=p.fond, padx=28, pady=22)
        entete.pack(fill="x")
        tk.Label(entete, text=textes.TRAVAUX_TITRE, bg=p.fond, fg=p.texte,
                 font=self.polices.titre).pack(side="left")
        ttk.Button(entete, text=textes.IMPRESSION_OUVRIR_DOSSIER,
                   command=lambda: ouvrir_dossier(self.session.dossier_sortie),
                   ).pack(side="right")

        carte = Carte(self, polices=self.polices, marge=16)
        carte.pack(fill="both", expand=True, padx=28, pady=(8, 20))
        corps = carte.corps()

        colonnes = ("fichier", "taille", "date", "encre")
        self.table = ttk.Treeview(corps, columns=colonnes, show="headings",
                                  selectmode="browse")
        for cle, titre, largeur in zip(colonnes, textes.TRAVAUX_COLONNES,
                                       (340, 160, 190, 110)):
            self.table.heading(cle, text=titre)
            self.table.column(cle, width=largeur, anchor="w")
        self.table.pack(fill="both", expand=True)
        self.table.bind("<Double-1>", lambda _e: self._renvoyer())

        self.lbl_vide = tk.Label(corps, text="", bg=p.surface, fg=p.texte_faible,
                                 font=self.polices.petit)

        boutons = tk.Frame(corps, bg=p.surface)
        boutons.pack(fill="x", pady=(16, 0))
        bouton = BoutonAction(boutons, "Renvoyer à la machine", self._renvoyer,
                              self.polices, variante="neutre")
        bouton.configure(width=self.polices.bouton.measure("Renvoyer à la machine") + 48)
        bouton.pack(side="left")

    def mode_change(self) -> None:
        """Rien à replier ici : l'historique dit la même chose dans les deux modes."""

    def _renvoyer(self) -> None:
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo("Aucun travail choisi",
                                "Cliquez d'abord sur une ligne de la liste.")
            return
        travail = self._travaux[self.table.index(selection[0])]
        if not Path(travail.fichier).is_file():
            messagebox.showwarning(
                textes.ERREUR_TITRE,
                "Ce fichier n'est plus sur le disque. Préparez-le à nouveau.",
            )
            return
        if messagebox.askyesno(textes.CONFIRMER_ENVOI_TITRE, textes.CONFIRMER_ENVOI):
            self.app.envoyer(Path(travail.fichier))

    def rafraichir(self) -> None:
        for ligne in self.table.get_children():
            self.table.delete(ligne)
        self._travaux = self.session.historique()

        if not self._travaux:
            self.table.pack_forget()
            self.lbl_vide.configure(text=textes.TRAVAUX_VIDE)
            self.lbl_vide.pack(anchor="w")
            return

        self.lbl_vide.pack_forget()
        self.table.pack(fill="both", expand=True)
        for travail in self._travaux:
            self.table.insert("", "end", values=(
                travail.fichier.name,
                travail.taille(),
                travail.date_lisible(),
                f"{travail.encre_totale * 100:.0f} %",
            ))
