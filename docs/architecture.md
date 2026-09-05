# Architecture et décisions

## La machine est murale — ce que ça change

Le parc est constitué de machines **Symp's** et **Friankor** à têtes Epson
I1600 : un chariot qui balaie une bande horizontale, une colonne qui monte, et
la machine que l'on déplace le long du mur entre deux bandes.

La conséquence structurante, et elle est contre-intuitive quand on vient de
l'impression à plat : **la hauteur est la limite dure, pas la largeur.** La
colonne ne s'allonge pas. La largeur, elle, n'a pas de limite — elle se paie en
repositionnements.

Cela se traduit dans le code par deux champs de profil et un module :

* `max_height_mm` — course de la colonne. `panneaux.verifier_hauteur()` refuse
  tout travail qui la dépasse, plutôt que de produire un fichier tronqué dont
  le haut manquerait sur le mur.
* `max_width_mm` — largeur d'une bande. Au-delà, `panneaux.decouper()` répartit
  la fresque en panneaux **de largeur égale**, avec recouvrement.

La première version de ce dépôt ne connaissait que `max_width_mm` et la
traitait comme une limite absolue : c'était le modèle d'une machine à plat,
appliqué à une machine murale. La correction a aussi révélé que le pipeline
chargeait la source entière en mémoire — invisible sur un format de 20 cm,
fatal à 4,5 m.

## Les formats muraux imposent le flux

Un panneau de 1,5 m en 720 × 900 dpi fait 42 520 × 15 502 px, soit 659 Mpx par
encre. Trois conséquences dans le code :

1. **La source est rééchantillonnée bande par bande** (`inputs/source.py`), via
   le paramètre `box` de Pillow, qui rééchantillonne une région source vers une
   taille cible sans matérialiser l'image complète. Les bornes de bande sont
   flottantes : des bornes entières accumuleraient un décalage d'un pixel d'une
   bande à l'autre, visible comme une ligne à chaque raccord.
2. **La rotation s'applique à la source**, pas au raster machine : quelques
   mégapixels au lieu de quelques gigapixels.
3. **La hauteur de bande s'adapte à la largeur** (`_hauteur_de_bande`), pour
   tenir un budget mémoire fixe quelle que soit la taille de la fresque.

Mesuré : 402 Mo au pic sur le panneau de 1,5 m, contre une vingtaine de
gigaoctets avant correction.

## Où nous nous branchons

Le dossier SAV (§30) décrit deux points d'entrée pour un logiciel tiers :

**(a) Parler directement à la carte** — TCP 8000 (commandes) et 8001 (image),
trame `0xA595`. Contrôle total, BetterPrinter n'a plus besoin de tourner.

**(b) Parler à l'application** — UDP 8999 (commandes) et TCP 9100 (fichier),
protocole texte. Plus simple, dépend de BetterPrinterApp lancé et connecté.

**Nous prenons (b).** Trois raisons :

1. Le **format du raster sur le canal image n'est pas spécifié** — en-tête de
   bloc, pagination, adresses mémoire carte, ordre des colonnes de buses sont
   listés comme « à extraire » au §34 du dossier SAV. Sans ça, (a) n'imprime
   rien.
2. Le weave, la plume, le calage des têtes, les séquences de nettoyage, les
   lampes UV et l'anti-collision sont déjà écrits, éprouvés, et couverts par le
   dongle. Les réécrire, c'est plusieurs mois pour retrouver l'existant.
3. Le protocole carte n'a **jamais été validé sur banc**. Une écriture de
   registre fausse sur un axe de 2 m casse du matériel.

La voie (a) reste ouverte plus tard, et le §32 du dossier SAV donne de quoi
écrire un outil de diagnostic **en lecture seule** qui accumulerait la
connaissance sans risque. Ce n'est pas dans ce dépôt.

## Carte des modules

```
ripcore/
├── profiles.py       PrinterProfile, MediaProfile — tout le spécifique machine
├── errors.py         hiérarchie d'exceptions
│
├── prnfile/          LE CONTENEUR — la partie qui doit être exacte au bit près
│   ├── header.py       en-tête 48 o, sans numpy, trivial à relire
│   ├── pack.py         empaquetage 1/2/4/8 bpp, MSB d'abord
│   ├── writer.py       écriture en flux, atomique
│   ├── reader.py       lecture + détection des 4 dialectes
│   └── validate.py     contrôle avant vol
│
├── halftone/         LA QUALITÉ
│   ├── bluenoise.py    masque void-and-cluster (Ulichney), mis en cache
│   ├── levels.py       quantification multi-niveaux en densité
│   └── engines.py      bruit bleu (défaut) | diffusion d'erreur (fronts d'onde)
│
├── color/
│   ├── icc.py          transformation ICC échantillonnée puis interpolée
│   ├── curves.py       linéarisation, courbes monotones
│   ├── inklimit.py     limite par canal + limite totale
│   └── white.py        sous-couche blanche, vernis, érosion (choke)
│
├── inputs/           lecture en flux (bande par bande), rendu PDF Ghostscript
├── panneaux.py       DÉCOUPE MURALE — largeur illimitée, hauteur bornée
├── targets/          mires de calibration
├── calibration.py    mesures → échelles et courbes
├── blocks.py         statistiques par blocs (l'encre est une grandeur de surface)
├── pipeline.py       orchestration d'un job, manifeste
├── preview.py        aperçu PNG
├── profiles_io.py    réécriture d'un profil (sauvegarde .bak, relecture)
├── transport/        client RipReceive
├── cli.py            ligne de commande
└── ui/               interface d'atelier (Tkinter)
    ├── textes.py       TOUT le vocabulaire affiché, à relire par un imprimeur
    ├── theme.py        palettes sombre / claire, styles ttk
    ├── widgets.py      briques dessinées (segments, interrupteurs, cartes)
    ├── session.py      état et décisions, sans Tk — donc testable
    ├── worker.py       fil d'arrière-plan, file de messages vers Tk
    └── ecrans/         Imprimer · Tests machine · Ma machine · Historique
```

## Décisions et leurs raisons

### On suit le lecteur, pas l'écrivain

`srip.dll` écrit un en-tête dont plusieurs champs sont des constantes
incompatibles avec les fichiers de production. Le dossier hésite entre deux
explications. La question est sans objet : **c'est le lecteur qui définit ce que
la machine consomme**, et il est décompilé et recoupé sur 5 fichiers réels.

### On ne clone pas `ipht.dll`

Le moteur de tramage d'origine est justement le module qui interroge le dongle
USB, et son comportement fin n'est pas établi par l'analyse statique. Le
réimplémenter était de toute façon nécessaire ; l'écrire nous-mêmes donne en
prime un tramage sans état, donc sans couture de bande — un problème que le
moteur d'origine doit contourner en conservant des tampons d'erreur entre
bandes (§6 du dossier RIP).

### On ne décode pas les `.cuv`

La structure est connue (magic `0x88440001`, enregistrements de float64) mais
les offsets exacts sont marqués ouverts. Reconstruire notre propre linéarisation
à partir de mesures est plus rapide, plus sûr, et cale la machine sur *nos*
encres et *nos* supports plutôt que sur ceux du constructeur.

### On ne devine jamais

Chaque valeur non établie est soit un champ de profil avec un drapeau
`*_verified`, soit une erreur explicite. `pass_mode` à 600 dpi lève plutôt que
d'interpoler entre 900 et 1200. C'est plus pénible et c'est le but : une valeur
fausse dans l'en-tête décale l'entrelacement sur toute la longueur du job.

### Tk ne se touche que depuis le fil principal

`worker.py` fait tourner les travaux longs dans un fil séparé et communique par
une file ; l'interface n'est modifiée que dans `_pomper`, côté fil principal.

Cette règle a été enfreinte une fois, dans l'écran d'impression, en lisant une
variable Tk depuis le fil de travail. Le symptôme (« main thread is not in main
loop ») n'apparaît qu'au moment où un job casse. Tout ce qui vient de Tk est
désormais lu **avant** de démarrer le fil, et passé comme valeurs simples.

### Deux niveaux d'interface plutôt que deux applications

Simple et Avancé sont deux densités du **même** écran, pas deux chemins de code :
les réglages avancés gardent leur valeur quand on repasse en simple, et le job
produit est identique à réglages égaux. Basculer de mode ne doit jamais changer
silencieusement ce qui va s'imprimer.

### Le tramage est sans état par défaut

Sur une machine à passes, un tramage à état propage l'erreur d'une bande à
l'autre et rend le résultat dépendant du découpage mémoire. Le bruit bleu
supprime la classe entière de bugs. La diffusion d'erreur reste disponible et
satisfait la même propriété grâce au découpage par fronts d'onde, mais elle
impose des bandes contiguës — et le dit si on lui en donne d'autres.

## Ce qui reste à faire

### Court terme — lève les derniers inconnus

1. **Capturer le dialogue UltraPrint ↔ BetterPrinter au Wireshark** pendant une
   impression réelle (UDP 8999 et TCP 9100, souvent sur la boucle locale). Une
   après-midi donne la syntaxe exacte de `SetPrintFile`, `SetPrintPara` et
   `SetRipPara`, que `transport/ripreceive.py` documente aujourd'hui comme non
   vérifiée. C'est de loin l'action la plus rentable du projet.
2. Imprimer les trois mires, remplir le profil.
3. Profiler la machine avec un spectrophotomètre pour produire un vrai ICC de
   sortie par (support × résolution × hauteur Z), ou repartir de ceux livrés.

### Moyen terme — qualité

- Tons directs : lire les séparations nommées d'un PDF pour piloter un canal
  `spot` (aujourd'hui laissé à zéro plutôt que rempli au hasard).
- Vernis sélectif à partir d'un calque nommé.
- Mise en page : imbrication, répétition, marges, repères de coupe.
- Repères de raccord imprimés en bord de panneau, pour caler la machine à la
  position suivante sans mesurer.
- Registres superposés : découper aussi en hauteur quand la fresque dépasse la
  course de la colonne, avec la reprise de calage que cela suppose.
- File de tâches et reprise sur incident.
- Épreuvage écran avec le profil de sortie.

### Long terme — seulement si vous voulez vous affranchir du fournisseur

- Outil de diagnostic **lecture seule** sur la carte (§32 du dossier SAV) :
  heartbeat, températures, entrées/sorties, positions. Aucune écriture.
- Rétro-ingénierie du canal image 8001 à partir de `bpSendImage`.
- Contrôleur de mouvement, sur banc, avec les fins de course câblées.

Dans cet ordre, jamais dans l'autre.
