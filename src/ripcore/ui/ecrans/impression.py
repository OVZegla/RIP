"""Écran « Imprimer » — celui qui sert tous les jours.

Deux niveaux : **Simple** ne pose que les trois questions qui comptent (quel
visuel, quelle taille, du blanc dessous ou non) ; **Avancé** déplie tout le
reste. Les réglages avancés gardent leur valeur quand on repasse en simple —
basculer de mode ne doit jamais changer silencieusement ce qui va s'imprimer.

Le récapitulatif de découpe est permanent, dans les deux modes : sur une machine
murale, savoir qu'une fresque va demander quatre positions de machine change
l'organisation du chantier, pas seulement le fichier.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ...errors import RipError
from ...panneaux import verifier_hauteur
from ...pipeline import run_job
from ...preview import render_preview
from .. import textes, theme
from ..session import Session, ouvrir_dossier
from ..widgets import (
    Bandeau,
    BoutonAction,
    Carte,
    Champ,
    Interrupteur,
    ZoneApercu,
    cadre_defilant,
    titre_section,
    trait,
)

FORMATS = [
    ("Images et PDF", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.webp *.pdf"),
    ("Images", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.webp"),
    ("PDF", "*.pdf"),
    ("Tous les fichiers", "*.*"),
]


class EcranImpression(tk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        p = theme.courante()
        super().__init__(parent, bg=p.fond)
        self.app = app
        self.session: Session = app.session
        self.polices = app.polices

        self.source: Path | None = None
        self.resultats: list = []
        self._proportions = 1.0  # hauteur / largeur du visuel

        self.var_largeur = tk.StringVar(value="2000")
        self.var_hauteur = tk.StringVar(value="1200")
        self.var_lier = tk.BooleanVar(value=True)
        self.var_qualite = tk.StringVar(value=textes.QUALITES[0][1])
        self.var_grain = tk.StringVar(value=textes.GRAINS[0][1])
        self.var_orientation = tk.StringVar(value=textes.ORIENTATIONS[0][1])
        self.var_intention = tk.StringVar(value=textes.INTENTIONS[0][1])
        self.var_strategie = tk.StringVar(value=textes.STRATEGIES_ENCRE[0][1])
        self.var_miroir = tk.BooleanVar(value=False)
        self.var_blanc = tk.BooleanVar(value=True)
        self.var_support = tk.StringVar()
        self.var_recouvrement = tk.StringVar(value="10")
        self.var_encre = tk.StringVar(value="")
        self.var_densite_blanc = tk.StringVar(value="100")
        self.var_retrait_blanc = tk.StringVar(value="2")
        self._maj_en_cours = False

        self._construire()
        self.rafraichir()

    # -- construction ---------------------------------------------------------

    def _construire(self) -> None:
        p = theme.courante()

        entete = tk.Frame(self, bg=p.fond, padx=28, pady=22)
        entete.pack(fill="x")
        tk.Label(
            entete, text=textes.IMPRESSION_TITRE, bg=p.fond, fg=p.texte,
            font=self.polices.titre, anchor="w",
        ).pack(anchor="w")
        self.lbl_mode = tk.Label(
            entete, text="", bg=p.fond, fg=p.texte_doux,
            font=self.polices.petit, anchor="w",
        )
        self.lbl_mode.pack(anchor="w", pady=(4, 0))

        self.zone_bandeau = tk.Frame(self, bg=p.fond, padx=28)
        self.zone_bandeau.pack(fill="x")

        corps = tk.Frame(self, bg=p.fond, padx=28, pady=16)
        corps.pack(fill="both", expand=True)

        droite = tk.Frame(corps, bg=p.fond, width=400)
        droite.pack(side="right", fill="y", padx=(20, 0))
        droite.pack_propagate(False)

        gauche_hote = tk.Frame(corps, bg=p.fond)
        gauche_hote.pack(side="left", fill="both", expand=True)
        _, self.colonne = cadre_defilant(gauche_hote)

        self._carte_fichier(self.colonne)
        self._carte_taille(self.colonne)
        self._carte_rendu(self.colonne)      # avancé
        self._carte_couleur(self.colonne)    # avancé
        self._carte_blanc(self.colonne)
        self._carte_action(self.colonne)
        self._colonne_droite(droite)

    def _carte_fichier(self, parent: tk.Misc) -> None:
        p = theme.courante()
        carte = Carte(parent, titre="Le visuel", polices=self.polices)
        carte.pack(fill="x", pady=(0, 14))
        corps = carte.corps()

        ligne = tk.Frame(corps, bg=p.surface)
        ligne.pack(fill="x")
        ttk.Button(
            ligne, text=textes.IMPRESSION_CHOISIR, command=self._choisir
        ).pack(side="left")
        self.lbl_fichier = tk.Label(
            ligne, text=textes.IMPRESSION_AUCUN, bg=p.surface, fg=p.texte_faible,
            font=self.polices.petit, anchor="w",
        )
        self.lbl_fichier.pack(side="left", padx=(16, 0), fill="x", expand=True)

    def _carte_taille(self, parent: tk.Misc) -> None:
        p = theme.courante()
        carte = Carte(parent, titre=textes.IMPRESSION_TAILLE, polices=self.polices)
        carte.pack(fill="x", pady=(0, 14))
        corps = carte.corps()

        ligne = tk.Frame(corps, bg=p.surface)
        ligne.pack(fill="x")
        Champ(ligne, "Largeur sur le mur", self.var_largeur, self.polices,
              largeur=9, suffixe="mm", sur_changement=self._largeur_changee,
              ).pack(side="left", padx=(0, 28))
        Champ(ligne, "Hauteur sur le mur", self.var_hauteur, self.polices,
              largeur=9, suffixe="mm", sur_changement=self._hauteur_changee,
              ).pack(side="left")

        Interrupteur(corps, textes.IMPRESSION_PROPORTIONS, self.var_lier,
                     self.polices).pack(anchor="w", pady=(16, 0))

        # Récapitulatif de découpe : combien de positions de machine, et la
        # hauteur tient-elle sous la colonne.
        self.cadre_geo = tk.Frame(corps, bg=p.surface_haute, padx=14, pady=12)
        self.cadre_geo.pack(fill="x", pady=(16, 0))
        self.lbl_panneaux = tk.Label(
            self.cadre_geo, text="", bg=p.surface_haute, fg=p.texte,
            font=self.polices.corps, anchor="w", justify="left", wraplength=460,
        )
        self.lbl_panneaux.pack(anchor="w")
        self.lbl_hauteur = tk.Label(
            self.cadre_geo, text="", bg=p.surface_haute, fg=p.texte_doux,
            font=self.polices.petit, anchor="w", justify="left", wraplength=460,
        )
        self.lbl_hauteur.pack(anchor="w", pady=(4, 0))

        self.champ_recouvrement = Champ(
            corps, textes.MURAL_RECOUVREMENT, self.var_recouvrement, self.polices,
            largeur=6, suffixe="mm", aide=textes.MURAL_RECOUVREMENT_AIDE,
            largeur_aide=520, sur_changement=self._maj_geometrie,
        )

    def _carte_rendu(self, parent: tk.Misc) -> None:
        p = theme.courante()
        self.carte_rendu = Carte(parent, titre="Rendu", polices=self.polices)
        corps = self.carte_rendu.corps()

        ligne = tk.Frame(corps, bg=p.surface)
        ligne.pack(fill="x")
        self.champ_qualite = Champ(
            ligne, textes.IMPRESSION_QUALITE, self.var_qualite, self.polices,
            valeurs=[q[1] for q in textes.QUALITES], largeur=14,
            sur_changement=self._maj_aides,
        )
        self.champ_qualite.pack(side="left", fill="x", expand=True, padx=(0, 14))
        self.champ_grain = Champ(
            ligne, textes.IMPRESSION_GRAIN, self.var_grain, self.polices,
            valeurs=[g[1] for g in textes.GRAINS], largeur=14,
            sur_changement=self._maj_aides,
        )
        self.champ_grain.pack(side="left", fill="x", expand=True)

        self.lbl_aide_rendu = tk.Label(
            corps, text="", bg=p.surface, fg=p.texte_faible,
            font=self.polices.minuscule, wraplength=520, justify="left", anchor="w",
        )
        self.lbl_aide_rendu.pack(anchor="w", pady=(10, 0))

        trait(corps)
        ligne2 = tk.Frame(corps, bg=p.surface)
        ligne2.pack(fill="x")
        Champ(ligne2, textes.IMPRESSION_ORIENTATION, self.var_orientation,
              self.polices, valeurs=[o[1] for o in textes.ORIENTATIONS],
              largeur=20).pack(side="left", fill="x", expand=True, padx=(0, 14))
        tk.Frame(ligne2, bg=p.surface, width=1).pack(side="left")
        Interrupteur(corps, textes.IMPRESSION_MIROIR, self.var_miroir, self.polices,
                     aide=textes.IMPRESSION_MIROIR_AIDE, largeur_aide=480,
                     ).pack(anchor="w", fill="x", pady=(16, 0))

    def _carte_couleur(self, parent: tk.Misc) -> None:
        p = theme.courante()
        self.carte_couleur = Carte(parent, titre="Couleur et encrage",
                                   polices=self.polices)
        corps = self.carte_couleur.corps()

        ligne = tk.Frame(corps, bg=p.surface)
        ligne.pack(fill="x")
        self.champ_support = Champ(
            ligne, textes.IMPRESSION_SUPPORT, self.var_support, self.polices,
            valeurs=[], largeur=22,
        )
        self.champ_support.pack(side="left", fill="x", expand=True, padx=(0, 14))
        self.champ_intention = Champ(
            ligne, "Rendu des couleurs", self.var_intention, self.polices,
            valeurs=[i[1] for i in textes.INTENTIONS], largeur=14,
            sur_changement=self._maj_aides,
        )
        self.champ_intention.pack(side="left", fill="x", expand=True)

        self.lbl_aide_intention = tk.Label(
            corps, text="", bg=p.surface, fg=p.texte_faible,
            font=self.polices.minuscule, wraplength=520, justify="left", anchor="w",
        )
        self.lbl_aide_intention.pack(anchor="w", pady=(10, 0))

        trait(corps)
        titre_section(corps, "Quantité d'encre", self.polices).pack(anchor="w")
        ligne2 = tk.Frame(corps, bg=p.surface)
        ligne2.pack(fill="x", pady=(10, 0))
        Champ(ligne2, "Encre maximale", self.var_encre, self.polices, largeur=8,
              aide="Vide = la valeur réglée pour la machine.",
              ).pack(side="left", padx=(0, 14))
        Champ(ligne2, "Si dépassement", self.var_strategie, self.polices,
              valeurs=[s[1] for s in textes.STRATEGIES_ENCRE], largeur=24,
              sur_changement=self._maj_aides,
              ).pack(side="left", fill="x", expand=True)
        self.lbl_aide_encre = tk.Label(
            corps, text="", bg=p.surface, fg=p.texte_faible,
            font=self.polices.minuscule, wraplength=520, justify="left", anchor="w",
        )
        self.lbl_aide_encre.pack(anchor="w", pady=(10, 0))

    def _carte_blanc(self, parent: tk.Misc) -> None:
        p = theme.courante()
        self.carte_blanc = Carte(parent, polices=self.polices)
        self.carte_blanc.pack(fill="x", pady=(0, 14))
        corps = self.carte_blanc.corps()

        Interrupteur(corps, textes.IMPRESSION_BLANC, self.var_blanc, self.polices,
                     aide=textes.IMPRESSION_BLANC_AIDE, largeur_aide=480,
                     ).pack(anchor="w", fill="x")

        self.reglages_blanc = tk.Frame(corps, bg=p.surface)
        ligne = tk.Frame(self.reglages_blanc, bg=p.surface)
        ligne.pack(fill="x", pady=(16, 0))
        Champ(ligne, "Densité du blanc", self.var_densite_blanc, self.polices,
              largeur=6, suffixe="%",
              aide="Baissez si le blanc bave ou met trop de temps à sécher.",
              ).pack(side="left", padx=(0, 14))
        Champ(ligne, "Retrait des bords", self.var_retrait_blanc, self.polices,
              largeur=6, suffixe="px",
              aide="Rentre le blanc sous la couleur pour éviter un liseré clair "
                   "au bord des motifs.",
              ).pack(side="left", fill="x", expand=True)

    def _carte_action(self, parent: tk.Misc) -> None:
        p = theme.courante()
        carte = Carte(parent, polices=self.polices, marge=16)
        carte.pack(fill="x")
        corps = carte.corps()

        self.bouton_preparer = BoutonAction(
            corps, textes.IMPRESSION_PREPARER, self._preparer, self.polices,
            hauteur=50,
        )
        self.bouton_preparer.pack(fill="x")
        self.bouton_preparer.activer(False)

        self.barre = ttk.Progressbar(corps, mode="determinate", maximum=100)
        self.lbl_avancement = tk.Label(
            corps, text="", bg=p.surface, fg=p.texte_doux, font=self.polices.petit,
        )

    def _colonne_droite(self, parent: tk.Misc) -> None:
        p = theme.courante()
        carte = Carte(parent, titre="Aperçu", polices=self.polices)
        carte.pack(fill="both", expand=True)
        corps = carte.corps()

        self.apercu = ZoneApercu(corps, largeur=340, hauteur=270)
        self.apercu.pack()
        tk.Label(
            corps, text="Ce qui sera réellement déposé sur le mur, grain compris.",
            bg=p.surface, fg=p.texte_faible, font=self.polices.minuscule,
            wraplength=340, justify="left", anchor="w",
        ).pack(anchor="w", pady=(10, 0))

        self.cadre_resultat = tk.Frame(corps, bg=p.surface)
        self.cadre_resultat.pack(fill="both", expand=True, pady=(16, 0))

    # -- mode ------------------------------------------------------------------

    def mode_change(self) -> None:
        """Affiche ou masque les cartes avancées, sans rien réinitialiser."""
        avance = self.app.avance
        self.lbl_mode.configure(text=textes.MODE_AIDE.get(self.app.mode.get(), ""))

        for carte in (self.carte_rendu, self.carte_couleur):
            carte.pack_forget()
        if avance:
            self.carte_rendu.pack(fill="x", pady=(0, 14),
                                  before=self.carte_blanc)
            self.carte_couleur.pack(fill="x", pady=(0, 14),
                                    before=self.carte_blanc)
            self.reglages_blanc.pack(fill="x")
        else:
            self.reglages_blanc.pack_forget()
        self._maj_geometrie()

    # -- réactions -------------------------------------------------------------

    def _choisir(self) -> None:
        p = theme.courante()
        chemin = filedialog.askopenfilename(
            title=textes.IMPRESSION_CHOISIR, filetypes=FORMATS
        )
        if not chemin:
            return
        self.source = Path(chemin)
        self.lbl_fichier.configure(text=self.source.name, fg=p.texte)
        self._lire_proportions()
        self.bouton_preparer.activer(True)
        self._vider_resultat()
        self.apercu.vider("Cliquez sur « Préparer le fichier »")

    def _lire_proportions(self) -> None:
        if self.source is None or self.source.suffix.lower() == ".pdf":
            return  # une page PDF n'est mesurée qu'au rendu
        try:
            from PIL import Image  # noqa: PLC0415

            with Image.open(self.source) as im:
                largeur, hauteur = im.size
        except Exception:
            return  # un fichier illisible sera signalé à la préparation
        if largeur:
            self._proportions = hauteur / largeur
            self._appliquer_proportions("largeur")

    def _largeur_changee(self) -> None:
        self._appliquer_proportions("largeur")

    def _hauteur_changee(self) -> None:
        self._appliquer_proportions("hauteur")

    def _appliquer_proportions(self, depuis: str) -> None:
        if self._maj_en_cours or not self.var_lier.get():
            self._maj_geometrie()
            return
        self._maj_en_cours = True
        try:
            if depuis == "largeur":
                largeur = _nombre(self.var_largeur.get())
                if largeur is not None:
                    self.var_hauteur.set(f"{largeur * self._proportions:.0f}")
            else:
                hauteur = _nombre(self.var_hauteur.get())
                if hauteur is not None and self._proportions:
                    self.var_largeur.set(f"{hauteur / self._proportions:.0f}")
        finally:
            self._maj_en_cours = False
        self._maj_geometrie()

    def _maj_geometrie(self) -> None:
        """Récapitulatif : combien de panneaux, et la hauteur passe-t-elle."""
        p = theme.courante()
        profil = self.session.profil
        largeur = _nombre(self.var_largeur.get())
        hauteur = _nombre(self.var_hauteur.get())
        recouvrement = _nombre(self.var_recouvrement.get()) or 0.0

        if largeur is None or largeur <= 0:
            self.lbl_panneaux.configure(text="Indiquez une largeur.", fg=p.texte_doux)
            self.lbl_hauteur.configure(text="")
            return

        try:
            panneaux = self.session.decouper_fresque(largeur, recouvrement)
        except RipError as exc:
            self.lbl_panneaux.configure(text=str(exc), fg=p.danger)
            self.lbl_hauteur.configure(text="")
            return

        if len(panneaux) == 1:
            self.lbl_panneaux.configure(
                text=textes.MURAL_UN_PANNEAU.format(bande=profil.max_width_mm),
                fg=p.texte,
            )
            self.champ_recouvrement.pack_forget()
        else:
            self.lbl_panneaux.configure(
                text=textes.MURAL_PANNEAUX.format(
                    n=len(panneaux), bande=panneaux[0].largeur_mm,
                    n_moins=len(panneaux) - 1,
                ),
                fg=p.texte,
            )
            if self.app.avance:
                self.champ_recouvrement.pack(anchor="w", pady=(16, 0))

        if hauteur is None:
            self.lbl_hauteur.configure(text="")
        elif profil.max_height_mm and hauteur > profil.max_height_mm:
            self.lbl_hauteur.configure(
                text=textes.MURAL_TROP_HAUT.format(
                    demande=hauteur, max=profil.max_height_mm
                ),
                fg=p.danger,
            )
        else:
            self.lbl_hauteur.configure(
                text=textes.MURAL_HAUTEUR_MAX.format(max=profil.max_height_mm),
                fg=p.texte_doux,
            )

    def _maj_aides(self) -> None:
        qualite = _trouver(textes.QUALITES, self.var_qualite.get(), 1)
        grain = _trouver(textes.GRAINS, self.var_grain.get(), 1)
        intention = _trouver(textes.INTENTIONS, self.var_intention.get(), 1)
        strategie = _trouver(textes.STRATEGIES_ENCRE, self.var_strategie.get(), 1)
        self.lbl_aide_rendu.configure(text=f"{qualite[2]}\n{grain[2]}")
        self.lbl_aide_intention.configure(text=intention[2])
        self.lbl_aide_encre.configure(text=strategie[2])

    # -- préparation ------------------------------------------------------------

    def _preparer(self) -> None:
        if self.source is None or self.app.tache.en_cours:
            return
        largeur = _nombre(self.var_largeur.get())
        hauteur = _nombre(self.var_hauteur.get())
        if largeur is None or largeur <= 0:
            messagebox.showwarning(textes.ERREUR_TITRE,
                                   "Indiquez une largeur en millimètres.")
            return
        profil = self.session.profil
        try:
            if hauteur is not None:
                verifier_hauteur(hauteur, profil.max_height_mm)
        except RipError as exc:
            messagebox.showerror(textes.ERREUR_TITRE, str(exc))
            return

        recouvrement = _nombre(self.var_recouvrement.get()) or 0.0
        try:
            panneaux = self.session.decouper_fresque(largeur, recouvrement)
        except RipError as exc:
            messagebox.showerror(textes.ERREUR_TITRE, str(exc))
            return

        if len(panneaux) > 1 and not messagebox.askyesno(
            textes.MURAL_PANNEAUX_TITRE,
            f"Cette fresque demande {len(panneaux)} positions de machine.\n\n"
            f"{len(panneaux)} fichiers vont être préparés, un par panneau, "
            f"numérotés de gauche à droite.\n\nContinuer ?",
        ):
            return

        # Tout ce qui vient de Tk est lu ICI, dans le fil de l'interface.
        # Le fil de travail ne doit toucher aucune variable Tk : Tkinter n'est
        # pas sûr entre fils, et l'erreur ne se voit qu'au moment où elle casse
        # un job en cours.
        options = self._reglages()
        hauteur_job = None if self.var_lier.get() else hauteur
        source = self.source
        session = self.session
        self._mode_travail(True)

        def travail(avancement):
            chemin = source
            if chemin.suffix.lower() in {".pdf", ".ps", ".eps", ".ai"}:
                from ...inputs.pdf import render_pdf  # noqa: PLC0415

                chemin = render_pdf(chemin, dpi_x=options["dpi_x"],
                                    dpi_y=options["dpi_y"], mode="CMYK")

            resultats = []
            total = len(panneaux)
            for panneau in panneaux:
                morceau = chemin
                if total > 1:
                    # Le découpage nomme déjà le fichier « …-p2 » et le job en
                    # hérite : sans ça le numéro apparaîtrait deux fois.
                    morceau = session.extraire_panneau(chemin, panneau, largeur)
                spec = session.preparer_job(
                    morceau,
                    largeur_mm=panneau.largeur_mm,
                    hauteur_mm=hauteur_job,
                    **options,
                )

                def relais(fait, lignes, i=panneau.index, n=total):
                    avancement(i * lignes + fait, n * lignes)

                resultat = run_job(spec, progress=relais)
                apercu = spec.output.with_suffix(".apercu.png")
                render_preview(spec.output, apercu, session.profil, max_side=900)
                resultats.append((resultat, apercu, panneau))
            return resultats

        self.app.tache.lancer(
            travail, sur_avancement=self._avancement, sur_fin=self._termine,
            sur_erreur=self._echec,
        )

    def _reglages(self) -> dict:
        """Réglages du job. En mode simple, les valeurs par défaut s'appliquent."""
        qualite = _trouver(textes.QUALITES, self.var_qualite.get(), 1)
        grain = _trouver(textes.GRAINS, self.var_grain.get(), 1)
        orientation = _trouver(textes.ORIENTATIONS, self.var_orientation.get(), 1)
        intention = _trouver(textes.INTENTIONS, self.var_intention.get(), 1)
        strategie = _trouver(textes.STRATEGIES_ENCRE, self.var_strategie.get(), 1)
        densite = _nombre(self.var_densite_blanc.get())
        retrait = _nombre(self.var_retrait_blanc.get())
        return {
            "dpi_x": qualite[3],
            "dpi_y": qualite[4],
            "grain": grain[0],
            "rotation": orientation[0],
            "miroir": self.var_miroir.get(),
            "support": self.session.support_par_nom(self.var_support.get()),
            "blanc": self.var_blanc.get(),
            "intention": intention[0],
            "strategie_encre": strategie[0],
            "encre_totale": _nombre(self.var_encre.get()),
            "densite_blanc": None if densite is None else max(0.0, densite / 100),
            "retrait_blanc": None if retrait is None else max(0, int(retrait)),
        }

    def _mode_travail(self, actif: bool) -> None:
        self.bouton_preparer.activer(not actif)
        self.bouton_preparer.configurer_texte(
            textes.IMPRESSION_PREPARATION if actif else textes.IMPRESSION_PREPARER
        )
        if actif:
            self.barre.pack(fill="x", pady=(14, 6))
            self.lbl_avancement.pack(anchor="w")
            self.barre["value"] = 0
            self._vider_resultat()
        else:
            self.barre.pack_forget()
            self.lbl_avancement.pack_forget()

    def _avancement(self, av) -> None:
        self.barre["value"] = av.pourcentage
        self.lbl_avancement.configure(text=f"{av.pourcentage} %")

    def _termine(self, charge) -> None:
        self.resultats = charge
        self._mode_travail(False)
        try:
            self.apercu.montrer(charge[0][1])
        except Exception:
            self.apercu.vider("Aperçu indisponible")
        self._montrer_resultat(charge)
        self.app.rafraichir_historique()

    def _echec(self, exc: Exception) -> None:
        self._mode_travail(False)
        self.app.montrer_erreur(exc)

    def _vider_resultat(self) -> None:
        for enfant in self.cadre_resultat.winfo_children():
            enfant.destroy()

    def _montrer_resultat(self, resultats: list) -> None:
        p = theme.courante()
        self._vider_resultat()
        cadre = self.cadre_resultat
        premier = resultats[0][0]

        tk.Label(cadre, text=textes.IMPRESSION_PRET, bg=p.surface, fg=p.accent,
                 font=self.polices.section, anchor="w").pack(anchor="w")

        if len(resultats) == 1:
            detail = (f"{premier.output.name}\n"
                      f"{premier.width_mm:.0f} × {premier.height_mm:.0f} mm")
        else:
            total = sum(r.seconds for r, _, _ in resultats)
            detail = (f"{len(resultats)} panneaux — "
                      f"{premier.width_mm:.0f} mm chacun\n"
                      f"préparés en {total:.0f} s")
        tk.Label(cadre, text=detail, bg=p.surface, fg=p.texte_doux,
                 font=self.polices.petit, justify="left", anchor="w",
                 ).pack(anchor="w", pady=(4, 12))

        # Couches préparées dans Photoshop : dire ce qu'elles sont devenues.
        # Une couche ignorée en silence se découvre devant le mur, panneau perdu.
        for message, niveau in textes.resume_tons_directs(premier.spot_channels):
            Bandeau(cadre, message, self.polices, niveau=niveau,
                    ).pack(fill="x", pady=(0, 8))

        for nom, valeur in premier.coverage.items():
            ligne = tk.Frame(cadre, bg=p.surface)
            ligne.pack(fill="x", pady=1)
            tk.Label(ligne, text=textes.nom_encre(nom).split(" ")[0], bg=p.surface,
                     fg=p.texte_doux, font=self.polices.petit, width=9, anchor="w",
                     ).pack(side="left")
            jauge = tk.Frame(ligne, bg=p.surface_haute, height=6)
            jauge.pack(side="left", fill="x", expand=True, padx=(0, 8))
            remplissage = tk.Frame(jauge, bg=p.accent, height=6)
            remplissage.place(relwidth=min(1.0, valeur), relheight=1)
            tk.Label(ligne, text=f"{valeur * 100:4.0f} %", bg=p.surface, fg=p.texte,
                     font=self.polices.chiffre).pack(side="right")

        BoutonAction(cadre, textes.IMPRESSION_ENVOYER, self._envoyer,
                     self.polices).pack(fill="x", pady=(16, 0))
        ttk.Button(cadre, text=textes.IMPRESSION_OUVRIR_DOSSIER,
                   command=lambda: ouvrir_dossier(self.session.dossier_sortie),
                   ).pack(fill="x", pady=(8, 0))

    def _envoyer(self) -> None:
        if not self.resultats:
            return
        if not messagebox.askyesno(textes.CONFIRMER_ENVOI_TITRE,
                                   textes.CONFIRMER_ENVOI):
            return
        self.app.envoyer(self.resultats[0][0].output)

    # -- mise à jour depuis l'extérieur ----------------------------------------

    def rafraichir(self) -> None:
        for enfant in self.zone_bandeau.winfo_children():
            enfant.destroy()
        # Un seul bandeau, même quand plusieurs réglages manquent : deux pavés
        # rouges empilés alarment sans informer davantage.
        manquants = self.session.avertissements()
        if manquants:
            texte = (
                manquants[0] if len(manquants) == 1
                else f"Machine pas encore réglée ({len(manquants)} points). "
                     + manquants[0]
            )
            Bandeau(self.zone_bandeau, texte, self.polices, niveau="alerte",
                    action=("Voir les tests", lambda: self.app.aller_a("tests")),
                    ).pack(fill="x", pady=(0, 12))

        noms = [m.name for m in self.session.supports]
        self.champ_support.saisie.configure(values=noms or ["Aucun profil"])
        if noms and self.var_support.get() not in noms:
            self.var_support.set(noms[0])
        elif not noms:
            self.var_support.set("Aucun profil")

        if not self.var_encre.get():
            self.var_encre.set(f"{self.session.profil.ink_limit_total:.2f}"
                               .replace(".", ","))
        self._maj_aides()
        self.mode_change()


def _nombre(texte: str) -> float | None:
    try:
        return float(texte.replace(",", ".").strip())
    except (ValueError, AttributeError):
        return None


def _trouver(table, libelle: str, index_libelle: int):
    """Retrouve la ligne d'une table de textes à partir du libellé affiché."""
    for ligne in table:
        if ligne[index_libelle] == libelle:
            return ligne
    return table[0]
