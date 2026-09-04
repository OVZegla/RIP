# Architecture et décisions

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
├── prn/              LE CONTENEUR — la partie qui doit être exacte au bit près
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
├── inputs/           chargement image, rendu PDF par Ghostscript
├── targets/          mires de calibration
├── calibration.py    mesures → échelles et courbes
├── blocks.py         statistiques par blocs (l'encre est une grandeur de surface)
├── pipeline.py       orchestration d'un job, manifeste
├── preview.py        aperçu PNG
├── transport/        client RipReceive
└── cli.py            interface
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
- File de tâches et reprise sur incident.
- Épreuvage écran avec le profil de sortie.

### Long terme — seulement si vous voulez vous affranchir du fournisseur

- Outil de diagnostic **lecture seule** sur la carte (§32 du dossier SAV) :
  heartbeat, températures, entrées/sorties, positions. Aucune écriture.
- Rétro-ingénierie du canal image 8001 à partir de `bpSendImage`.
- Contrôleur de mouvement, sur banc, avec les fins de course câblées.

Dans cet ordre, jamais dans l'autre.
