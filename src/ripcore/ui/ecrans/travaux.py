"""Écran « Historique » — les fichiers déjà préparés.

Sert à deux choses concrètes : retrouver un travail pour le renvoyer sans tout
refaire, et vérifier après coup ce qui a été consommé en encre.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from .. import textes
from ..session import ouvrir_dossier
from ..widgets import BoutonGeant, Carte


class EcranTravaux(ttk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, style="TFrame")
        self.app = app
        self.session = app.session
        self.polices = app.polices
        self._travaux: list = []
        self._construire()
        self.rafraichir()

    def _construire(self) -> None:
        entete = ttk.Frame(self, style="TFrame", padding=(28, 24, 28, 4))
        entete.pack(fill="x")
        ttk.Label(entete, text=textes.TRAVAUX_TITRE, style="Titre.TLabel").pack(
            side="left"
        )
        ttk.Button(
            entete, text=textes.IMPRESSION_OUVRIR_DOSSIER,
            command=lambda: ouvrir_dossier(self.session.dossier_sortie),
        ).pack(side="right")

        carte = Carte(self)
        carte.pack(fill="both", expand=True, padx=28, pady=(12, 20))

        colonnes = ("fichier", "taille", "date", "encre")
        self.table = ttk.Treeview(
            carte, columns=colonnes, show="headings", selectmode="browse"
        )
        for cle, titre, largeur in zip(
            colonnes, textes.TRAVAUX_COLONNES, (300, 150, 170, 110)
        ):
            self.table.heading(cle, text=titre)
            self.table.column(cle, width=largeur, anchor="w")
        self.table.pack(fill="both", expand=True)
        self.table.bind("<Double-1>", lambda _e: self._renvoyer())

        self.lbl_vide = ttk.Label(carte, text="", style="Doux.TLabel")

        boutons = ttk.Frame(carte, style="Carte.TFrame")
        boutons.pack(fill="x", pady=(16, 0))
        BoutonGeant(
            boutons, "Renvoyer à la presse", self._renvoyer, self.polices,
            variante="neutre",
        ).pack(side="left")

    def _renvoyer(self) -> None:
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo(
                "Aucun travail choisi",
                "Cliquez d'abord sur une ligne de la liste.",
            )
            return
        index = self.table.index(selection[0])
        travail = self._travaux[index]
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
            self.table.insert(
                "", "end",
                values=(
                    travail.fichier.name,
                    travail.taille(),
                    travail.date_lisible(),
                    f"{travail.encre_totale * 100:.0f} %",
                ),
            )
