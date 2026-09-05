"""Écran « Ma machine » — les réglages, en clair.

Ce que l'opérateur peut changer est délibérément restreint : l'encrage et les
courses. L'ordre des encres et les tailles de goutte s'affichent en lecture
seule, parce que ces valeurs se relèvent sur un tirage et ne se devinent pas au
clavier — un champ modifiable inviterait à les bricoler.

En mode avancé s'ajoutent les limites par encre et les résolutions connues de la
machine, qui n'ont rien à faire sous les yeux d'un opérateur au quotidien.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ...errors import RipError
from ...profiles import PrinterProfile
from ...profiles_io import save_profile
from .. import textes, theme
from ..widgets import (
    Bandeau,
    BoutonAction,
    Carte,
    Champ,
    cadre_defilant,
    titre_section,
    trait,
)


class EcranMachine(tk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        p = theme.courante()
        super().__init__(parent, bg=p.fond)
        self.app = app
        self.session = app.session
        self.polices = app.polices

        self.var_encre = tk.StringVar()
        self.var_largeur = tk.StringVar()
        self.var_hauteur = tk.StringVar()
        self.vars_encres: dict[str, tk.StringVar] = {}

        self._construire()
        self.rafraichir()

    def _construire(self) -> None:
        p = theme.courante()
        entete = tk.Frame(self, bg=p.fond, padx=28, pady=22)
        entete.pack(fill="x")
        tk.Label(entete, text=textes.MACHINE_TITRE, bg=p.fond, fg=p.texte,
                 font=self.polices.titre, anchor="w").pack(anchor="w")
        self.lbl_presse = tk.Label(entete, text="", bg=p.fond, fg=p.texte_doux,
                                   font=self.polices.petit, anchor="w")
        self.lbl_presse.pack(anchor="w", pady=(4, 0))

        hote = tk.Frame(self, bg=p.fond, padx=28, pady=8)
        hote.pack(fill="both", expand=True)
        _, corps = cadre_defilant(hote)

        # -- encres ------------------------------------------------------------
        self.carte_encres = Carte(corps, titre=textes.MACHINE_ENCRES,
                                  aide=textes.MACHINE_ENCRES_AIDE,
                                  polices=self.polices)
        self.carte_encres.pack(fill="x", pady=(0, 14))
        self.liste_encres = tk.Frame(self.carte_encres.corps(), bg=p.surface)
        self.liste_encres.pack(fill="x")

        # -- courses -----------------------------------------------------------
        carte_courses = Carte(corps, titre="Courses de la machine",
                              polices=self.polices)
        carte_courses.pack(fill="x", pady=(0, 14))
        c = carte_courses.corps()
        ligne = tk.Frame(c, bg=p.surface)
        ligne.pack(fill="x")
        Champ(ligne, textes.MACHINE_LARGEUR, self.var_largeur, self.polices,
              largeur=8, suffixe="mm", aide=textes.MACHINE_LARGEUR_AIDE,
              ).pack(side="left", padx=(0, 20))
        Champ(ligne, textes.MACHINE_HAUTEUR, self.var_hauteur, self.polices,
              largeur=8, suffixe="mm", aide=textes.MACHINE_HAUTEUR_AIDE,
              ).pack(side="left", fill="x", expand=True)

        # -- encrage -----------------------------------------------------------
        carte_encre = Carte(corps, titre=textes.MACHINE_ENCRE_MAX,
                            aide=textes.MACHINE_ENCRE_MAX_AIDE,
                            polices=self.polices)
        carte_encre.pack(fill="x", pady=(0, 14))
        ce = carte_encre.corps()
        Champ(ce, "Encre maximale, toutes couleurs cumulées", self.var_encre,
              self.polices, largeur=8,
              aide="Exprimée en « couches d'encre » : 2,6 signifie au plus "
                   "2,6 fois un aplat plein au même endroit. Entre 2,0 (mur "
                   "fermé, encre lente) et 3,0 (mur absorbant, lampe puissante).",
              ).pack(anchor="w")

        self.cadre_par_encre = tk.Frame(ce, bg=p.surface)
        trait(self.cadre_par_encre)
        titre_section(self.cadre_par_encre, "Limite par encre",
                      self.polices).pack(anchor="w", pady=(0, 10))
        self.liste_limites = tk.Frame(self.cadre_par_encre, bg=p.surface)
        self.liste_limites.pack(fill="x")

        # -- gouttes -----------------------------------------------------------
        self.carte_gouttes = Carte(corps, titre=textes.MACHINE_GOUTTES,
                                   polices=self.polices)
        self.carte_gouttes.pack(fill="x", pady=(0, 14))
        self.liste_gouttes = tk.Frame(self.carte_gouttes.corps(), bg=p.surface)
        self.liste_gouttes.pack(fill="x")

        # -- résolutions (avancé) ---------------------------------------------
        self.carte_resolutions = Carte(corps, titre="Résolutions connues",
                                       aide="Relevées sur des fichiers produits "
                                            "par le logiciel d'origine. Une "
                                            "résolution absente est refusée "
                                            "plutôt que devinée.",
                                       polices=self.polices)
        self.liste_resolutions = tk.Frame(self.carte_resolutions.corps(),
                                          bg=p.surface)
        self.liste_resolutions.pack(fill="x")

        # -- enregistrement ----------------------------------------------------
        carte_action = Carte(corps, polices=self.polices, marge=16)
        carte_action.pack(fill="x")
        ca = carte_action.corps()
        BoutonAction(ca, textes.MACHINE_ENREGISTRER, self._enregistrer,
                     self.polices).pack(fill="x")
        self.lbl_fichier = tk.Label(ca, text="", bg=p.surface, fg=p.texte_faible,
                                    font=self.polices.minuscule, anchor="w",
                                    justify="left", wraplength=640)
        self.lbl_fichier.pack(anchor="w", pady=(12, 0))

    # -- affichage --------------------------------------------------------------

    def mode_change(self) -> None:
        if self.app.avance:
            self.cadre_par_encre.pack(fill="x", pady=(16, 0))
            self.carte_resolutions.pack(fill="x", pady=(0, 14),
                                        before=self.lbl_fichier.master.master)
        else:
            self.cadre_par_encre.pack_forget()
            self.carte_resolutions.pack_forget()

    def rafraichir(self) -> None:
        p = theme.courante()
        profil = self.session.profil
        self.lbl_presse.configure(text=f"{profil.name} — {profil.head}")
        self.var_encre.set(f"{profil.ink_limit_total:.2f}".replace(".", ","))
        self.var_largeur.set(f"{profil.max_width_mm:.0f}")
        self.var_hauteur.set(f"{profil.max_height_mm:.0f}")
        self.lbl_fichier.configure(text=f"Réglages : {self.session.profil_chemin}")

        for enfant in self.liste_encres.winfo_children():
            enfant.destroy()
        if not profil.channel_order_verified:
            Bandeau(self.liste_encres,
                    "Cet ordre n'a pas encore été confirmé sur la machine.",
                    self.polices, niveau="alerte",
                    action=("Faire le test", lambda: self.app.aller_a("tests")),
                    ).pack(fill="x", pady=(0, 14))
        for i, canal in enumerate(profil.channels, start=1):
            ligne = tk.Frame(self.liste_encres, bg=p.surface)
            ligne.pack(fill="x", pady=2)
            tk.Label(ligne, text=str(i), bg=p.surface_haute, fg=p.accent,
                     font=self.polices.chiffre, width=3).pack(side="left", ipady=4)
            tk.Label(ligne, text="  " + textes.nom_encre(canal.name), bg=p.surface,
                     fg=p.texte, font=self.polices.corps).pack(side="left")

        for enfant in self.liste_limites.winfo_children():
            enfant.destroy()
        self.vars_encres.clear()
        for canal in profil.channels:
            var = tk.StringVar(
                value=f"{profil.limit_for(canal.name) * 100:.0f}"
            )
            self.vars_encres[canal.name] = var
            ligne = tk.Frame(self.liste_limites, bg=p.surface)
            ligne.pack(fill="x", pady=3)
            tk.Label(ligne, text=textes.nom_encre(canal.name), bg=p.surface,
                     fg=p.texte_doux, font=self.polices.petit, width=16,
                     anchor="w").pack(side="left")
            ttk.Entry(ligne, textvariable=var, width=6,
                      font=self.polices.corps).pack(side="left")
            tk.Label(ligne, text="%", bg=p.surface, fg=p.texte_faible,
                     font=self.polices.petit).pack(side="left", padx=(6, 0))

        for enfant in self.liste_gouttes.winfo_children():
            enfant.destroy()
        gouttes = profil.drop_levels
        if not gouttes.calibrated:
            Bandeau(self.liste_gouttes,
                    "Valeurs supposées : les gouttes n'ont pas été mesurées.",
                    self.polices, niveau="alerte",
                    action=("Faire le test", lambda: self.app.aller_a("tests")),
                    ).pack(fill="x", pady=(0, 14))
        noms = ["aucune goutte", "petite", "moyenne", "grosse"]
        for i, densite in enumerate(gouttes.densities):
            if i == 0:
                continue
            ligne = tk.Frame(self.liste_gouttes, bg=p.surface)
            ligne.pack(fill="x", pady=3)
            tk.Label(ligne, text=noms[i] if i < len(noms) else f"goutte {i}",
                     bg=p.surface, fg=p.texte, font=self.polices.corps, width=14,
                     anchor="w").pack(side="left")
            jauge = tk.Frame(ligne, bg=p.surface_haute, height=6)
            jauge.pack(side="left", fill="x", expand=True, padx=(0, 10))
            tk.Frame(jauge, bg=p.accent, height=6).place(
                relwidth=min(1.0, densite), relheight=1
            )
            tk.Label(ligne, text=f"{densite * 100:3.0f} %", bg=p.surface,
                     fg=p.texte_doux, font=self.polices.chiffre).pack(side="right")

        for enfant in self.liste_resolutions.winfo_children():
            enfant.destroy()
        for dpi_y, mode in sorted(profil.pass_mode_by_dpi_y.items()):
            ligne = tk.Frame(self.liste_resolutions, bg=p.surface)
            ligne.pack(fill="x", pady=2)
            tk.Label(ligne, text=f"720 × {dpi_y}", bg=p.surface, fg=p.texte,
                     font=self.polices.chiffre, width=14, anchor="w"
                     ).pack(side="left")
            tk.Label(ligne, text=f"mode de passes {mode}", bg=p.surface,
                     fg=p.texte_faible, font=self.polices.minuscule).pack(side="left")

        self.mode_change()

    # -- enregistrement ---------------------------------------------------------

    def _enregistrer(self) -> None:
        profil = self.session.profil
        encre = _nombre(self.var_encre.get())
        largeur = _nombre(self.var_largeur.get())
        hauteur = _nombre(self.var_hauteur.get())
        nb_couleurs = len(profil.channels_with_role("process"))

        if encre is None or not 0 < encre <= nb_couleurs:
            messagebox.showwarning(
                textes.ERREUR_TITRE,
                f"La quantité d'encre doit être comprise entre 0 et "
                f"{nb_couleurs} (le nombre de couleurs de la machine).",
            )
            return
        for nom, libelle in (("largeur", largeur), ("hauteur", hauteur)):
            if libelle is None or libelle <= 0:
                messagebox.showwarning(
                    textes.ERREUR_TITRE,
                    f"Indiquez une {nom} de course en millimètres.",
                )
                return

        limites = dict(profil.ink_limit_channel)
        if self.app.avance:
            for cle, var in self.vars_encres.items():
                valeur = _nombre(var.get())
                if valeur is None or not 0 < valeur <= 100:
                    messagebox.showwarning(
                        textes.ERREUR_TITRE,
                        f"La limite de l'encre « {textes.nom_encre(cle)} » doit "
                        f"être comprise entre 1 et 100 %.",
                    )
                    return
                limites[cle] = valeur / 100

        nouveau = PrinterProfile(
            name=profil.name, head=profil.head,
            bits_per_pixel=profil.bits_per_pixel, channels=profil.channels,
            pass_mode_by_dpi_y=dict(profil.pass_mode_by_dpi_y),
            drop_levels=profil.drop_levels,
            ink_limit_channel=limites,
            ink_limit_total=encre,
            max_width_mm=largeur,
            max_height_mm=hauteur,
            ink_limit_total_all=profil.ink_limit_total_all,
            channel_order_verified=profil.channel_order_verified,
            drop_levels_verified=profil.drop_levels_verified,
            source=profil.source, notes=profil.notes,
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
