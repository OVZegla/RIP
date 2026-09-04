"""Écran « Imprimer » — le seul que l'opérateur utilisera tous les jours.

Principe de disposition : la colonne de gauche pose les questions dans l'ordre
où on se les pose (quel visuel, quelle taille, sur quoi), la colonne de droite
montre le résultat. Le bouton d'action est unique et en bas à gauche, toujours
au même endroit.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ...errors import RipError
from ...pipeline import run_job
from ...preview import render_preview
from .. import textes
from ..session import Session, ouvrir_dossier
from ..widgets import (
    Bandeau,
    BoutonGeant,
    Carte,
    Champ,
    Interrupteur,
    ZoneApercu,
    cadre_defilant,
)

FORMATS = [
    ("Images et PDF", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.webp *.pdf"),
    ("Images", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.webp"),
    ("PDF", "*.pdf"),
    ("Tous les fichiers", "*.*"),
]


class EcranImpression(ttk.Frame):
    def __init__(self, parent: tk.Misc, app) -> None:
        super().__init__(parent, style="TFrame")
        self.app = app
        self.session: Session = app.session
        self.polices = app.polices

        self.source: Path | None = None
        self.resultat = None
        self._apercu_source: Path | None = None
        self._proportions = 1.0  # hauteur / largeur du visuel

        self.var_largeur = tk.StringVar(value="500")
        self.var_hauteur = tk.StringVar(value="500")
        self.var_lier = tk.BooleanVar(value=True)
        self.var_qualite = tk.StringVar(value=textes.QUALITES[0][1])
        self.var_grain = tk.StringVar(value=textes.GRAINS[0][1])
        self.var_orientation = tk.StringVar(value=textes.ORIENTATIONS[0][1])
        self.var_miroir = tk.BooleanVar(value=False)
        self.var_blanc = tk.BooleanVar(value=True)
        self.var_support = tk.StringVar()
        self._maj_en_cours = False

        self._construire()
        self.rafraichir()

    # -- construction --------------------------------------------------------

    def _construire(self) -> None:
        entete = ttk.Frame(self, style="TFrame", padding=(28, 24, 28, 8))
        entete.pack(fill="x")
        ttk.Label(entete, text=textes.IMPRESSION_TITRE, style="Titre.TLabel").pack(
            anchor="w"
        )

        self.zone_bandeau = ttk.Frame(self, style="TFrame", padding=(28, 0, 28, 0))
        self.zone_bandeau.pack(fill="x")

        corps = ttk.Frame(self, style="TFrame")
        corps.pack(fill="both", expand=True, padx=28, pady=(12, 20))

        gauche_hote = ttk.Frame(corps, style="TFrame")
        gauche_hote.pack(side="left", fill="both", expand=True)
        _, gauche = cadre_defilant(gauche_hote)

        droite = ttk.Frame(corps, style="TFrame", padding=(20, 0, 0, 0))
        droite.pack(side="right", fill="y")

        self._carte_fichier(gauche)
        self._carte_taille(gauche)
        self._carte_rendu(gauche)
        self._carte_action(gauche)
        self._colonne_droite(droite)

    def _carte_fichier(self, parent: tk.Misc) -> None:
        carte = Carte(parent, titre="1. Le visuel")
        carte.pack(fill="x", pady=(0, 14))

        ligne = ttk.Frame(carte, style="Carte.TFrame")
        ligne.pack(fill="x")
        ttk.Button(
            ligne, text=textes.IMPRESSION_CHOISIR, command=self._choisir
        ).pack(side="left")
        self.lbl_fichier = ttk.Label(
            ligne, text=textes.IMPRESSION_AUCUN, style="Doux.TLabel"
        )
        self.lbl_fichier.pack(side="left", padx=(14, 0))

    def _carte_taille(self, parent: tk.Misc) -> None:
        carte = Carte(parent, titre="2. La taille imprimée")
        carte.pack(fill="x", pady=(0, 14))

        ligne = ttk.Frame(carte, style="Carte.TFrame")
        ligne.pack(fill="x")
        Champ(
            ligne, textes.IMPRESSION_LARGEUR, self.var_largeur, largeur=10,
            sur_changement=self._largeur_changee,
        ).pack(side="left")
        ttk.Label(ligne, text="×", style="Carte.TLabel").pack(
            side="left", padx=12, pady=(18, 0)
        )
        Champ(
            ligne, textes.IMPRESSION_HAUTEUR, self.var_hauteur, largeur=10,
            sur_changement=self._hauteur_changee,
        ).pack(side="left")

        Interrupteur(
            carte, textes.IMPRESSION_PROPORTIONS, self.var_lier, self.polices
        ).pack(anchor="w", pady=(14, 0))
        self.lbl_taille = ttk.Label(carte, text="", style="Doux.TLabel")
        self.lbl_taille.pack(anchor="w", pady=(8, 0))

    def _carte_rendu(self, parent: tk.Misc) -> None:
        carte = Carte(parent, titre="3. Le rendu")
        carte.pack(fill="x", pady=(0, 14))

        ligne = ttk.Frame(carte, style="Carte.TFrame")
        ligne.pack(fill="x")
        Champ(
            ligne, textes.IMPRESSION_QUALITE, self.var_qualite,
            valeurs=[q[1] for q in textes.QUALITES], largeur=16,
            sur_changement=self._maj_aides,
        ).pack(side="left", fill="x", expand=True, padx=(0, 12))
        Champ(
            ligne, textes.IMPRESSION_GRAIN, self.var_grain,
            valeurs=[g[1] for g in textes.GRAINS], largeur=16,
            sur_changement=self._maj_aides,
        ).pack(side="left", fill="x", expand=True)

        # Une aide qui décrit l'option réellement choisie, et non la première
        # de la liste : sinon elle induit en erreur dès qu'on change de valeur.
        self.lbl_aide_rendu = ttk.Label(
            carte, text="", style="Doux.TLabel", wraplength=520, justify="left"
        )
        self.lbl_aide_rendu.pack(anchor="w", pady=(8, 0))

        ligne2 = ttk.Frame(carte, style="Carte.TFrame")
        ligne2.pack(fill="x", pady=(14, 0))
        Champ(
            ligne2, textes.IMPRESSION_ORIENTATION, self.var_orientation,
            valeurs=[o[1] for o in textes.ORIENTATIONS], largeur=22,
        ).pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.champ_support = Champ(
            ligne2, textes.IMPRESSION_SUPPORT, self.var_support, valeurs=[], largeur=22,
        )
        self.champ_support.pack(side="left", fill="x", expand=True)

        Interrupteur(
            carte, textes.IMPRESSION_BLANC, self.var_blanc, self.polices,
            aide=textes.IMPRESSION_BLANC_AIDE, largeur_aide=460,
        ).pack(anchor="w", fill="x", pady=(18, 0))
        Interrupteur(
            carte, textes.IMPRESSION_MIROIR, self.var_miroir, self.polices,
            aide=textes.IMPRESSION_MIROIR_AIDE, largeur_aide=460,
        ).pack(anchor="w", fill="x", pady=(14, 0))

    def _carte_action(self, parent: tk.Misc) -> None:
        carte = Carte(parent)
        carte.pack(fill="x")

        self.bouton_preparer = BoutonGeant(
            carte, textes.IMPRESSION_PREPARER, self._preparer, self.polices,
            sous_texte="Transforme le visuel en fichier pour la presse",
        )
        self.bouton_preparer.pack(fill="x")
        self.bouton_preparer.activer(False)

        self.barre = ttk.Progressbar(carte, mode="determinate", maximum=100)
        self.lbl_avancement = ttk.Label(carte, text="", style="Doux.TLabel")

    def _colonne_droite(self, parent: tk.Misc) -> None:
        carte = Carte(parent, titre="Aperçu")
        carte.pack(fill="both", expand=True)

        self.apercu = ZoneApercu(carte, largeur=360, hauteur=290)
        self.apercu.pack()
        ttk.Label(
            carte,
            text="L'aperçu montre ce qui sera réellement déposé, trame comprise.",
            style="Doux.TLabel", wraplength=360, justify="left",
        ).pack(anchor="w", pady=(10, 0))

        self.cadre_resultat = ttk.Frame(carte, style="Carte.TFrame")
        self.cadre_resultat.pack(fill="x", pady=(16, 0))

    # -- réactions ------------------------------------------------------------

    def _choisir(self) -> None:
        chemin = filedialog.askopenfilename(
            title=textes.IMPRESSION_CHOISIR, filetypes=FORMATS
        )
        if not chemin:
            return
        self.source = Path(chemin)
        self.lbl_fichier.configure(text=self.source.name, style="Carte.TLabel")
        self._lire_proportions()
        self.bouton_preparer.activer(True)
        self._vider_resultat()
        self.apercu.vider("Cliquez sur « Préparer le fichier » pour voir l'aperçu")

    def _lire_proportions(self) -> None:
        """Renseigne le rapport hauteur/largeur du visuel choisi."""
        if self.source is None:
            return
        if self.source.suffix.lower() == ".pdf":
            return  # la page n'est mesurée qu'au rendu
        try:
            from PIL import Image  # noqa: PLC0415

            with Image.open(self.source) as im:
                largeur, hauteur = im.size
        except Exception:  # un fichier illisible sera signalé à la préparation
            return
        if largeur:
            self._proportions = hauteur / largeur
            self._appliquer_proportions(depuis="largeur")

    def _maj_aides(self) -> None:
        qualite = _trouver(textes.QUALITES, self.var_qualite.get(), 1)
        grain = _trouver(textes.GRAINS, self.var_grain.get(), 1)
        self.lbl_aide_rendu.configure(text=f"{qualite[2]}  —  {grain[2]}")

    def _largeur_changee(self) -> None:
        self._appliquer_proportions(depuis="largeur")

    def _hauteur_changee(self) -> None:
        self._appliquer_proportions(depuis="hauteur")

    def _appliquer_proportions(self, depuis: str) -> None:
        if self._maj_en_cours or not self.var_lier.get():
            self._maj_taille()
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
        self._maj_taille()

    def _maj_taille(self) -> None:
        largeur = _nombre(self.var_largeur.get())
        maxi = self.session.profil.max_width_mm
        if largeur is not None and maxi and largeur > maxi:
            self.lbl_taille.configure(
                text=f"Trop large : la presse imprime jusqu'à {maxi:.0f} mm.",
                style="Alerte.TLabel",
            )
        else:
            self.lbl_taille.configure(
                text=f"La presse imprime jusqu'à {maxi:.0f} mm de large."
                if maxi else "",
                style="Doux.TLabel",
            )

    # -- préparation ----------------------------------------------------------

    def _preparer(self) -> None:
        if self.source is None or self.app.tache.en_cours:
            return
        largeur = _nombre(self.var_largeur.get())
        hauteur = _nombre(self.var_hauteur.get())
        if largeur is None or largeur <= 0:
            messagebox.showwarning(
                textes.ERREUR_TITRE, "Indiquez une largeur en millimètres."
            )
            return

        qualite = _trouver(textes.QUALITES, self.var_qualite.get(), 1)
        grain = _trouver(textes.GRAINS, self.var_grain.get(), 1)
        orientation = _trouver(textes.ORIENTATIONS, self.var_orientation.get(), 1)

        try:
            spec = self.session.preparer_job(
                self.source,
                largeur_mm=largeur,
                hauteur_mm=None if self.var_lier.get() else hauteur,
                dpi_x=qualite[3],
                dpi_y=qualite[4],
                grain=grain[0],
                rotation=orientation[0],
                miroir=self.var_miroir.get(),
                support=self.session.support_par_nom(self.var_support.get()),
                blanc=self.var_blanc.get(),
            )
        except RipError as exc:
            messagebox.showerror(textes.ERREUR_TITRE, str(exc))
            return

        self._mode_travail(True)

        def travail(avancement):
            source = spec.source
            if source.suffix.lower() in {".pdf", ".ps", ".eps", ".ai"}:
                from ...inputs.pdf import render_pdf  # noqa: PLC0415

                spec.source = render_pdf(
                    source, dpi_x=spec.dpi_x, dpi_y=spec.dpi_y, mode="CMYK"
                )
            resultat = run_job(spec, progress=avancement)
            apercu = spec.output.with_suffix(".apercu.png")
            render_preview(spec.output, apercu, self.session.profil, max_side=900)
            return resultat, apercu

        self.app.tache.lancer(
            travail,
            sur_avancement=self._avancement,
            sur_fin=self._termine,
            sur_erreur=self._echec,
        )

    def _mode_travail(self, actif: bool) -> None:
        self.bouton_preparer.activer(not actif)
        self.bouton_preparer.configurer_texte(
            textes.IMPRESSION_PREPARATION if actif else textes.IMPRESSION_PREPARER
        )
        if actif:
            self.barre.pack(fill="x", pady=(14, 4))
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
        resultat, apercu = charge
        self.resultat = resultat
        self._mode_travail(False)
        try:
            self.apercu.montrer(apercu)
        except Exception:
            self.apercu.vider("Aperçu indisponible")
        self._montrer_resultat(resultat)
        self.app.rafraichir_historique()

    def _echec(self, exc: Exception) -> None:
        self._mode_travail(False)
        self.app.montrer_erreur(exc)

    def _vider_resultat(self) -> None:
        for enfant in self.cadre_resultat.winfo_children():
            enfant.destroy()

    def _montrer_resultat(self, resultat) -> None:
        self._vider_resultat()
        cadre = self.cadre_resultat

        ttk.Label(cadre, text=textes.IMPRESSION_PRET, style="Section.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            cadre,
            text=f"{resultat.output.name}\n"
                 f"{resultat.width_mm:.0f} × {resultat.height_mm:.0f} mm — "
                 f"préparé en {resultat.seconds:.0f} s",
            style="Doux.TLabel", justify="left",
        ).pack(anchor="w", pady=(4, 10))

        encre = "   ".join(
            f"{textes.nom_encre(k).split(' ')[0]} {v * 100:.0f} %"
            for k, v in resultat.coverage.items()
        )
        ttk.Label(cadre, text="Encre : " + encre, style="Doux.TLabel",
                  wraplength=340, justify="left").pack(anchor="w", pady=(0, 12))

        BoutonGeant(
            cadre, textes.IMPRESSION_ENVOYER, self._envoyer, self.polices,
        ).pack(fill="x")
        ttk.Button(
            cadre, text=textes.IMPRESSION_OUVRIR_DOSSIER,
            command=lambda: ouvrir_dossier(self.session.dossier_sortie),
        ).pack(fill="x", pady=(8, 0))

    def _envoyer(self) -> None:
        if self.resultat is None:
            return
        if not messagebox.askyesno(
            textes.CONFIRMER_ENVOI_TITRE, textes.CONFIRMER_ENVOI
        ):
            return
        self.app.envoyer(self.resultat.output)

    # -- mise à jour depuis l'extérieur --------------------------------------

    def rafraichir(self) -> None:
        """Recharge ce qui dépend du profil et des supports."""
        for enfant in self.zone_bandeau.winfo_children():
            enfant.destroy()
        # Un seul bandeau, même s'il y a plusieurs réglages en attente : deux
        # pavés rouges empilés en haut de l'écran principal alarment sans
        # informer davantage.
        manquants = self.session.avertissements()
        if manquants:
            texte = (
                manquants[0]
                if len(manquants) == 1
                else f"La presse n'est pas encore réglée ({len(manquants)} points). "
                     + manquants[0]
            )
            Bandeau(
                self.zone_bandeau, texte, niveau="alerte",
                action=("Voir les tests", lambda: self.app.aller_a("tests")),
            ).pack(fill="x", pady=(0, 8))

        noms = [m.name for m in self.session.supports]
        self.champ_support.saisie.configure(values=noms or ["Aucun profil de support"])
        if noms and self.var_support.get() not in noms:
            self.var_support.set(noms[0])
        elif not noms:
            self.var_support.set("Aucun profil de support")
        self._maj_aides()
        self._maj_taille()


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
