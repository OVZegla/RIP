"""Écran « Ma presse » — les réglages, en clair.

Ce que l'opérateur peut changer ici est délibérément restreint : la quantité
d'encre et la largeur maximale. Tout le reste (ordre des encres, tailles de
goutte) s'affiche en lecture seule, parce que ces valeurs se relèvent sur un
tirage et ne se devinent pas au clavier — un champ modifiable inviterait à les
bricoler.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ...errors import RipError
from ...profiles import PrinterProfile
from ...profiles_io import save_profile
from .. import textes, theme
from ..widgets import Bandeau, BoutonGeant, Carte, Champ, cadre_defilant


class EcranMachine(ttk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, style="TFrame")
        self.app = app
        self.session = app.session
        self.polices = app.polices

        self.var_encre = tk.StringVar()
        self.var_largeur = tk.StringVar()

        self._construire()
        self.rafraichir()

    def _construire(self) -> None:
        entete = ttk.Frame(self, style="TFrame", padding=(28, 24, 28, 4))
        entete.pack(fill="x")
        ttk.Label(entete, text=textes.MACHINE_TITRE, style="Titre.TLabel").pack(
            anchor="w"
        )
        self.lbl_presse = ttk.Label(entete, text="", style="SousTitre.TLabel")
        self.lbl_presse.pack(anchor="w", pady=(4, 0))

        hote = ttk.Frame(self, style="TFrame", padding=(28, 14, 28, 20))
        hote.pack(fill="both", expand=True)
        _, corps = cadre_defilant(hote)

        # -- ordre des encres, lecture seule ---------------------------------
        self.carte_encres = Carte(
            corps, titre=textes.MACHINE_ENCRES, aide=textes.MACHINE_ENCRES_AIDE
        )
        self.carte_encres.pack(fill="x", pady=(0, 16))
        self.liste_encres = ttk.Frame(self.carte_encres, style="Carte.TFrame")
        self.liste_encres.pack(fill="x")

        # -- quantité d'encre -------------------------------------------------
        carte_encre = Carte(
            corps, titre=textes.MACHINE_ENCRE_MAX, aide=textes.MACHINE_ENCRE_MAX_AIDE
        )
        carte_encre.pack(fill="x", pady=(0, 16))
        Champ(
            carte_encre,
            "Encre maximale, toutes couleurs cumulées",
            self.var_encre,
            aide="Exprimée en « couches d'encre » : 2,6 signifie au plus "
                 "2,6 fois un aplat plein sur un même endroit. "
                 "Entre 2,0 (support fermé, encre lente) et 3,0 (support "
                 "absorbant, lampe puissante).",
            largeur=10,
        ).pack(anchor="w")

        # -- tailles de goutte, lecture seule --------------------------------
        self.carte_gouttes = Carte(corps, titre=textes.MACHINE_GOUTTES)
        self.carte_gouttes.pack(fill="x", pady=(0, 16))
        self.liste_gouttes = ttk.Frame(self.carte_gouttes, style="Carte.TFrame")
        self.liste_gouttes.pack(fill="x")

        # -- largeur ----------------------------------------------------------
        carte_largeur = Carte(corps, titre=textes.MACHINE_LARGEUR)
        carte_largeur.pack(fill="x", pady=(0, 16))
        Champ(
            carte_largeur,
            "Largeur maximale (mm)",
            self.var_largeur,
            aide="Course du chariot. Au-delà, l'interface refuse le travail "
                 "plutôt que de laisser la presse buter.",
            largeur=10,
        ).pack(anchor="w")

        # -- enregistrement ---------------------------------------------------
        carte_action = Carte(corps)
        carte_action.pack(fill="x")
        BoutonGeant(
            carte_action, textes.MACHINE_ENREGISTRER, self._enregistrer, self.polices,
        ).pack(anchor="w")
        self.lbl_fichier = ttk.Label(carte_action, text="", style="Doux.TLabel")
        self.lbl_fichier.pack(anchor="w", pady=(10, 0))

    # -- affichage ------------------------------------------------------------

    def rafraichir(self) -> None:
        profil = self.session.profil
        self.lbl_presse.configure(text=f"{profil.name} — {profil.head}")
        self.var_encre.set(f"{profil.ink_limit_total:.2f}".replace(".", ","))
        self.var_largeur.set(f"{profil.max_width_mm:.0f}")
        self.lbl_fichier.configure(text=f"Fichier de réglages : {self.session.profil_chemin}")

        for enfant in self.liste_encres.winfo_children():
            enfant.destroy()
        if not profil.channel_order_verified:
            Bandeau(
                self.liste_encres,
                "Cet ordre n'a pas encore été confirmé sur la presse.",
                niveau="alerte",
                action=("Faire le test", lambda: self.app.aller_a("tests")),
            ).pack(fill="x", pady=(0, 12))
        for i, canal in enumerate(profil.channels, start=1):
            ligne = ttk.Frame(self.liste_encres, style="Carte.TFrame")
            ligne.pack(fill="x", pady=3)
            tk.Label(
                ligne, text=str(i), bg=theme.BLEU_PALE, fg=theme.BLEU,
                font=self.polices.corps_gras, width=3,
            ).pack(side="left", ipady=3)
            ttk.Label(
                ligne, text="  " + textes.nom_encre(canal.name), style="Carte.TLabel"
            ).pack(side="left")

        for enfant in self.liste_gouttes.winfo_children():
            enfant.destroy()
        gouttes = profil.drop_levels
        if not gouttes.calibrated:
            Bandeau(
                self.liste_gouttes,
                "Valeurs supposées : les gouttes n'ont pas été mesurées.",
                niveau="alerte",
                action=("Faire le test", lambda: self.app.aller_a("tests")),
            ).pack(fill="x", pady=(0, 12))
        noms = ["aucune goutte", "petite", "moyenne", "grosse"]
        for i, densite in enumerate(gouttes.densities):
            if i == 0:
                continue
            nom = noms[i] if i < len(noms) else f"goutte {i}"
            ligne = ttk.Frame(self.liste_gouttes, style="Carte.TFrame")
            ligne.pack(fill="x", pady=3)
            ttk.Label(ligne, text=nom, style="Carte.TLabel", width=14).pack(side="left")
            ttk.Label(
                ligne, text=f"{densite * 100:.0f} % d'un aplat plein",
                style="Doux.TLabel",
            ).pack(side="left")

    # -- enregistrement -------------------------------------------------------

    def _enregistrer(self) -> None:
        encre = _nombre(self.var_encre.get())
        largeur = _nombre(self.var_largeur.get())
        profil = self.session.profil
        nb_couleurs = len(profil.channels_with_role("process"))

        if encre is None or not 0 < encre <= nb_couleurs:
            messagebox.showwarning(
                textes.ERREUR_TITRE,
                f"La quantité d'encre doit être comprise entre 0 et "
                f"{nb_couleurs} (le nombre de couleurs de la presse).",
            )
            return
        if largeur is None or largeur <= 0:
            messagebox.showwarning(
                textes.ERREUR_TITRE, "Indiquez une largeur maximale en millimètres."
            )
            return

        nouveau = PrinterProfile(
            name=profil.name,
            head=profil.head,
            bits_per_pixel=profil.bits_per_pixel,
            channels=profil.channels,
            pass_mode_by_dpi_y=dict(profil.pass_mode_by_dpi_y),
            drop_levels=profil.drop_levels,
            ink_limit_channel=dict(profil.ink_limit_channel),
            ink_limit_total=encre,
            max_width_mm=largeur,
            ink_limit_total_all=profil.ink_limit_total_all,
            channel_order_verified=profil.channel_order_verified,
            drop_levels_verified=profil.drop_levels_verified,
            source=profil.source,
            notes=profil.notes,
        )
        try:
            save_profile(nouveau, self.session.profil_chemin)
        except RipError as exc:
            messagebox.showerror(textes.ERREUR_TITRE, str(exc))
            return

        self.session.recharger_profil()
        self.app.profil_modifie()
        messagebox.showinfo(textes.MACHINE_ENREGISTRE, "Les réglages sont enregistrés.")


def _nombre(texte: str) -> float | None:
    try:
        return float(texte.replace(",", ".").strip())
    except (ValueError, AttributeError):
        return None
