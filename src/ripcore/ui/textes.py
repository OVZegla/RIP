"""Tout le texte affiché à l'opérateur, au même endroit.

Deux raisons de centraliser :

1. **Relecture.** Un imprimeur peut relire ce fichier d'un bout à l'autre et
   corriger un mot qui ne se dit pas dans le métier, sans toucher au code.
2. **Cohérence.** Le même objet doit porter le même nom sur tous les écrans.
   « Encre blanche » ici et « sous-couche » deux écrans plus loin, et
   l'opérateur croit qu'il s'agit de deux choses.

Règle de rédaction : **aucun terme d'ingénieur dans l'interface.** Pas de
« RIP », « tramage », « linéarisation », « canal », « dpi », « TAC ». Ce que
l'opérateur voit, ce sont des mots d'atelier.
"""

from __future__ import annotations

APP_NOM = "Atelier d'impression"
APP_SOUS_TITRE = "Préparation des fichiers pour la presse"

# -- navigation --------------------------------------------------------------

NAV = [
    ("impression", "Imprimer", "Préparer un visuel et l'envoyer à la presse"),
    ("tests", "Tests machine", "Vérifier et régler la presse"),
    ("machine", "Ma presse", "Encres, quantité d'encre, réglages"),
    ("travaux", "Historique", "Les fichiers déjà préparés"),
]

# -- traduction des termes techniques ---------------------------------------
# À gauche ce que dit le code, à droite ce que lit l'opérateur.

QUALITES = [
    ("720x900", "Standard", "Le plus courant. Bon rendu, vitesse normale.", 720, 900),
    ("720x1200", "Supérieure", "Plus fin, plus lent. Pour les petits détails.", 720, 1200),
]

GRAINS = [
    ("bluenoise", "Lisse", "Grain régulier et discret. À utiliser par défaut."),
    ("errdiff", "Détaillé", "Restitue mieux les petits détails et le texte fin."),
]

ORIENTATIONS = [
    (0, "Normal"),
    (90, "Quart de tour à droite"),
    (180, "À l'envers"),
    (270, "Quart de tour à gauche"),
]

# Noms d'encre lisibles, pour les listes déroulantes du test des couleurs.
ENCRES = {
    "C": "Cyan (bleu)",
    "M": "Magenta (rose)",
    "Y": "Jaune",
    "K": "Noir",
    "W": "Blanc",
    "V": "Vernis",
    "LC": "Cyan clair",
    "LM": "Magenta clair",
}


def nom_encre(code: str) -> str:
    return ENCRES.get(code, code)


# -- écran Imprimer ----------------------------------------------------------

IMPRESSION_TITRE = "Préparer un visuel"
IMPRESSION_CHOISIR = "Choisir un fichier…"
IMPRESSION_AUCUN = "Aucun fichier choisi"
IMPRESSION_FORMATS = "Images et PDF"
IMPRESSION_TAILLE = "Taille à imprimer"
IMPRESSION_LARGEUR = "Largeur (mm)"
IMPRESSION_HAUTEUR = "Hauteur (mm)"
IMPRESSION_PROPORTIONS = "Garder les proportions"
IMPRESSION_QUALITE = "Qualité"
IMPRESSION_GRAIN = "Rendu"
IMPRESSION_ORIENTATION = "Orientation"
IMPRESSION_MIROIR = "Image en miroir"
IMPRESSION_MIROIR_AIDE = "Pour l'impression sur l'envers d'un support transparent."
IMPRESSION_BLANC = "Poser du blanc sous l'image"
IMPRESSION_BLANC_AIDE = (
    "Indispensable sur support foncé ou transparent : sans blanc dessous, "
    "les couleurs ne ressortent pas."
)
IMPRESSION_SUPPORT = "Support"
IMPRESSION_PREPARER = "Préparer le fichier"
IMPRESSION_PREPARATION = "Préparation en cours…"
IMPRESSION_ENVOYER = "Envoyer à la presse"
IMPRESSION_OUVRIR_DOSSIER = "Ouvrir le dossier"
IMPRESSION_PRET = "Fichier prêt"

# -- écran Tests -------------------------------------------------------------

TESTS_TITRE = "Tests machine"
TESTS_INTRO = (
    "Trois tests à imprimer une fois, dans l'ordre. Ils apprennent au logiciel "
    "comment votre presse se comporte réellement. Tant qu'ils ne sont pas faits, "
    "les couleurs ne peuvent pas être justes."
)

TESTS = [
    {
        "cle": "channel-id",
        "numero": "1",
        "titre": "Test des couleurs",
        "resume": "Quelle encre sort à quel endroit",
        "detail": (
            "Imprime cinq barres. Chaque barre est précédée de petits carrés : "
            "une barre à 3 carrés correspond à la 3ᵉ position dans le fichier.\n\n"
            "Après impression, vous indiquez la couleur sortie en face de chaque "
            "barre. Sans ce test, le logiciel risque de poser le blanc à la place "
            "du noir."
        ),
        "duree": "30 minutes",
        "bouton": "Créer le test des couleurs",
        "saisie": "J'ai imprimé — saisir les couleurs",
    },
    {
        "cle": "drop-wedge",
        "numero": "2",
        "titre": "Test des gouttes",
        "resume": "Combien d'encre dépose chaque taille de goutte",
        "detail": (
            "La tête sait projeter quatre tailles de goutte. Une goutte moyenne "
            "ne dépose pas les deux tiers d'une grosse, et le logiciel doit "
            "connaître les vraies proportions.\n\n"
            "Imprimez, mesurez chaque case au densitomètre, y compris le support "
            "nu, puis reportez les mesures dans le tableau fourni."
        ),
        "duree": "1 heure, densitomètre nécessaire",
        "bouton": "Créer le test des gouttes",
        "saisie": "J'ai les mesures — les charger",
    },
    {
        "cle": "lin-wedge",
        "numero": "3",
        "titre": "Test du dégradé",
        "resume": "Régler la justesse des couleurs",
        "detail": (
            "Imprime un dégradé de 21 cases par encre, du plus clair au plus "
            "foncé. Sur une presse non réglée, le milieu du dégradé sort trop "
            "foncé et les clairs se bouchent.\n\n"
            "Vos mesures permettent au logiciel de corriger, pour que 50 % "
            "demandé donne bien 50 % imprimé."
        ),
        "duree": "2 heures, densitomètre nécessaire",
        "bouton": "Créer le test du dégradé",
        "saisie": "J'ai les mesures — les charger",
    },
]

SAISIE_COULEURS_TITRE = "Quelle couleur est sortie sur chaque barre ?"
SAISIE_COULEURS_AIDE = (
    "Regardez votre tirage. Pour chaque barre, choisissez la couleur que vous "
    "voyez. Comptez les petits carrés à gauche pour ne pas vous tromper de ligne."
)
SAISIE_COULEURS_BARRE = "Barre à {n} carré{s}"
SAISIE_COULEURS_VALIDER = "Enregistrer"
SAISIE_COULEURS_DOUBLON = (
    "Chaque couleur ne peut être choisie qu'une seule fois. Vérifiez votre "
    "tirage : deux barres ne peuvent pas sortir dans la même encre."
)

# -- écran Ma presse ---------------------------------------------------------

MACHINE_TITRE = "Ma presse"
MACHINE_ENCRES = "Ordre des encres"
MACHINE_ENCRES_AIDE = (
    "L'ordre dans lequel la presse attend les couleurs. Se règle par le test "
    "des couleurs, pas à la main."
)
MACHINE_ENCRE_MAX = "Quantité d'encre maximale"
MACHINE_ENCRE_MAX_AIDE = (
    "Au-delà, l'encre coule et ne sèche pas à cœur sous la lampe UV. "
    "Baissez si vous voyez des coulures ou une surface qui reste collante."
)
MACHINE_GOUTTES = "Tailles de goutte"
MACHINE_LARGEUR = "Largeur maximale imprimable"
MACHINE_ENREGISTRER = "Enregistrer les réglages"
MACHINE_ENREGISTRE = "Réglages enregistrés"

# -- écran Historique --------------------------------------------------------

TRAVAUX_TITRE = "Historique"
TRAVAUX_VIDE = "Aucun fichier préparé pour l'instant."
TRAVAUX_COLONNES = ("Fichier", "Taille", "Préparé le", "Encre")

# -- états et messages -------------------------------------------------------

ETAT_PRET = "Prêt"
ETAT_A_REGLER = "Presse à régler"

AVERTISSEMENTS = {
    "ordre des canaux": (
        "Les encres ne sont pas encore identifiées. Faites le test n° 1 avant "
        "d'imprimer un vrai travail."
    ),
    "goutte": (
        "Les tailles de goutte ne sont pas mesurées. Les dégradés seront "
        "approximatifs. Test n° 2."
    ),
    "linéarisation": (
        "Les couleurs ne sont pas encore réglées sur votre presse. Test n° 3."
    ),
    "profil ICC": (
        "Aucun profil de couleurs pour ce support : les couleurs ne sont pas "
        "gérées. À réserver aux essais."
    ),
}


def traduire_avertissement(message: str) -> str:
    """Message technique → phrase d'atelier, ou le message d'origine."""
    for cle, texte in AVERTISSEMENTS.items():
        if cle in message:
            return texte
    return message


# -- erreurs -----------------------------------------------------------------

ERREUR_TITRE = "Ça n'a pas marché"
ERREUR_FICHIER_INTROUVABLE = "Ce fichier n'existe plus à cet emplacement."
ERREUR_TROP_LARGE = (
    "Ce visuel est plus large que ce que la presse peut imprimer "
    "({demande:.0f} mm pour {max:.0f} mm au maximum). Réduisez la largeur."
)
ERREUR_GENERIQUE = "Détail technique :"

CONFIRMER_ENVOI_TITRE = "Envoyer à la presse ?"
CONFIRMER_ENVOI = (
    "Le fichier va être transmis à BetterPrinter.\n\n"
    "L'impression ne démarre pas toute seule : vous la lancerez depuis "
    "BetterPrinter quand le support sera en place."
)
