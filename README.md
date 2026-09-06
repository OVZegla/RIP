# ripcore — RIP pour machines d'impression murale UV

RIP maison pour le parc **Symp's / Friankor** à têtes Epson I1600. Remplace
**UltraPrint** dans la chaîne : produit des fichiers `.prn` que **BetterPrinter**
consomme tels quels, la machine, le weave, la plume, le nettoyage, les lampes UV
et le dongle restant gérés par le logiciel d'origine. Nous ne reprenons que la
partie à valeur métier — couleur, trame, encre, blanc, découpe en panneaux.

```
votre fichier → ripcore → .prn → BetterPrinterApp → carte → machine
```

Ce périmètre est un choix, pas une limite subie : le canal image de la carte
(port 8001) n'est pas spécifié par la rétro-ingénierie disponible, et écrire
soi-même dans les registres moteur d'une machine de 2 m sans banc d'essai n'est
pas un projet, c'est un accident. Voir [docs/architecture.md](docs/architecture.md).

---

## Une machine murale, pas une table

C'est la contrainte qui structure tout le reste, et elle s'inverse par rapport à
une machine à plat :

| | Machine à plat | **Machine murale** |
|---|---|---|
| Hauteur | libre | **bornée par la colonne** — limite dure |
| Largeur | bornée par la table | **illimitée**, par repositionnement |

Sur une murale, le chariot balaie une **bande** (2 m sur ce parc) et la colonne
monte jusqu'à sa course (2 m ici, jusqu'à 3 m sur certains modèles Friankor).

Et le chariot balaie **verticalement**. L'axe X d'un fichier `.prn` étant par
construction l'axe de balayage, il correspond donc au **vertical du mur** — les
deux repères sont à angle droit. C'est le quart de tour que les opérateurs
faisaient à la main dans UltraPrint avant chaque travail. `ripcore` l'applique
lui-même (`carriage_axis` dans le profil) : on donne des dimensions sur le mur,
et l'aperçu s'affiche d'aplomb.

| Axe du fichier | Sur le mur | Résolution | Borne |
|---|---|---|---|
| X — octets par ligne | vertical | 720 dpi | course de la colonne |
| Y — lignes | horizontal | 900 / 1200 dpi | illimitée, par panneaux |
Une fresque plus haute que la colonne est **impossible** : `ripcore` refuse le
travail plutôt que de produire un fichier tronqué. Une fresque plus large est
**découpée en panneaux**, imprimés l'un après l'autre en déplaçant la machine.

La découpe répartit la largeur **également** entre les panneaux plutôt que de
remplir les premiers à ras bord : un dernier panneau réduit à un ruban de 4 cm
est difficile à raccorder, et le déséquilibre se voit sur le mur. Le
recouvrement (10 mm par défaut) absorbe l'imprécision du repositionnement — sans
lui, la moindre erreur laisse un filet de mur nu au raccord, le défaut le plus
visible qui soit sur une fresque.

```
fresque 6 m, bande 2 m, recouvrement 10 mm
  → 4 panneaux de 1508 mm, la machine est repositionnée 3 fois
```

**Les formats sont réellement grands.** Mesure sur un panneau de 1,5 m × 0,44 m
en 720 × 900 dpi : **42 520 × 15 502 px, soit 659 Mpx par encre**, et un `.prn`
de **0,82 Go**. Toute la chaîne travaille donc en flux — la lecture de la source
comprise, rééchantillonnée bande par bande via le `box` de Pillow — et la
hauteur de bande s'adapte à la largeur pour tenir un budget mémoire fixe :

| largeur du panneau | hauteur de bande retenue |
|---|---|
| 5 670 px (0,2 m) | 443 lignes |
| 42 724 px (1,5 m) | 58 lignes |
| 127 559 px (4,5 m) | 19 lignes |

Résultat mesuré sur le panneau de 1,5 m : **402 Mo de mémoire au pic**, 156 s.
Charger le raster d'un bloc en aurait demandé une vingtaine de gigaoctets — ce
que faisait la première version, et que seul un essai à taille réelle a révélé.

### Pourquoi UltraPrint tombe en panne de mémoire

`UltraPrint.exe` charge `gsdll32.dll`, `ZIP32.DLL` et `boxiqoky.x86` : un
processus ne peut charger des DLL 32 bits que s'il est lui-même 32 bits. Compilé
en VC6/MFC, il plafonne donc à **2 Go d'espace d'adressage**, quelle que soit la
RAM de la machine. Ce n'est pas un réglage, c'est une limite d'architecture.

Mesure sur un travail modeste — 800 × 333 mm, source de 60 Mpx :

| | |
|---|---|
| Raster complet en mémoire | **5 692 Mo** |
| Plafond d'un processus 32 bits | 2 048 Mo → **dépassé** |
| Pic mesuré avec `ripcore` | **615 Mo** |

D'où le contournement d'atelier : réduire le visuel à l'import, puis le
ré-agrandir dans le RIP. Il évite le plantage **au prix du détail** — le
ré-agrandissement n'invente pas ce que la réduction a jeté.

`ripcore` n'en a pas besoin : **donnez l'original à sa résolution native.** Si
la source contient plus de pixels que la machine n'en imprimera, elle est
réduite automatiquement — mais seulement de ce que le rééchantillonnage jetait
déjà, avec une marge de 2×. Un test vérifie que l'encre déposée est identique,
canal par canal, entre une source à l'échelle et la même 16 fois plus grande.

---

## Installation

```bash
pip install -e ".[images]"     # numpy + Pillow (Pillow embarque lcms2 pour l'ICC)
apt install ghostscript        # seulement si vous rippez des PDF / PS
```

Python 3.11 ou plus. Tkinter est fourni avec Python sur Windows et macOS ; sous
Linux, `apt install python3-tk`.

---

## L'interface

C'est par là que passe l'atelier. Double-cliquez sur **« Lancer l'atelier.bat »**,
ou :

```bash
python -m ripcore.ui
```

Quatre écrans, pas de menus déroulants, tout dans la colonne de gauche en
permanence :

| Écran | Ce qu'on y fait |
|---|---|
| **Imprimer** | Le visuel, sa taille sur le mur, le rendu ; préparer ; envoyer |
| **Tests machine** | Les trois tests de réglage, expliqués et numérotés |
| **Ma machine** | Encres, encrage, courses de la machine |
| **Historique** | Retrouver et renvoyer un travail déjà préparé |

### Simple et Avancé

Sur le principe du « Lite / Pro » des plateformes financières, un sélecteur en
barre supérieure bascule entre deux densités du même écran :

* **Simple** — le visuel, la taille sur le mur, le blanc dessous. Trois
  questions, un bouton.
* **Avancé** — qualité, grain, profil de surface, intention colorimétrique,
  encre maximale et stratégie de réduction, densité et retrait du blanc,
  orientation, miroir, recouvrement entre panneaux.

Les réglages avancés **gardent leur valeur** quand on repasse en simple :
changer de mode ne modifie jamais silencieusement ce qui va s'imprimer. Le mode
et la palette sont mémorisés d'une session à l'autre.

Le récapitulatif de découpe reste visible **dans les deux modes** : savoir
qu'une fresque demandera quatre positions de machine change l'organisation du
chantier, pas seulement le fichier.

### Sombre et clair

Palette sombre par défaut — un poste d'atelier tourne souvent en lumière basse,
et le fond sombre fait ressortir l'aperçu du visuel, seule chose colorée de
l'écran. Bascule en un clic dans la barre supérieure.

Trois partis pris :

**Aucun terme d'ingénieur à l'écran.** Pas de « RIP », « tramage », « dpi »,
« canal », « linéarisation ». Le vocabulaire visible est rassemblé dans
`src/ripcore/ui/textes.py` — un imprimeur peut relire ce fichier d'un bout à
l'autre et corriger un mot qui ne se dit pas dans le métier, sans toucher au
code. Un test vérifie qu'aucun jargon ne repasse par la fenêtre.

**Le rouge est réservé aux problèmes.** Bleu pour tout le reste, réussite
comprise. Un rouge décoratif rendrait le rouge d'alerte invisible — et sur une
machine qui projette de l'encre sur le mur d'un client, l'alerte doit se voir.

**Rien ne fige la fenêtre.** Les travaux tournent dans un fil séparé avec une
barre d'avancement : un mural de 2 m met plusieurs minutes, et une fenêtre qui
ne répond plus se fait fermer au milieu de l'écriture du fichier.

L'écran « Tests machine » porte le moment le plus important de l'installation :
après avoir imprimé le test n° 1, l'opérateur indique dans une simple liste
déroulante quelle couleur est sortie sur chaque barre. C'est ce qui transforme
la presse d'inconnue en machine réglée — et ça remplace l'édition d'un fichier
de configuration à la main.

---

## La ligne de commande

Tout ce que fait l'interface est disponible en ligne de commande, pour le
réglage fin et les scripts.

### En deux minutes

```bash
# 1. Décrire un .prn existant (le vôtre, ou un produit par UltraPrint)
rip info fichier.prn

# 2. Ripper une image
rip rip visuel.tif -o job.prn \
   --profile profiles/friankor-i1600.toml \
   --media   profiles/media-rigide-uv.toml \
   --width-mm 1200

# 3. Regarder avant d'imprimer
rip preview job.prn --profile profiles/friankor-i1600.toml -o apercu.png

# 4. Contrôler, puis envoyer (simulation par défaut)
rip check job.prn --profile profiles/friankor-i1600.toml
rip send  job.prn --host 192.168.0.10 --profile profiles/friankor-i1600.toml
```

Aucune commande ne met la machine en mouvement sans `--execute`, et seule
`--print` dépose de l'encre.

---

## Avant la première production : trois mires

Le profil livré porte deux drapeaux à `false`. Tant qu'ils y sont, `ripcore`
prévient à chaque job et refuse l'envoi machine sans `--allow-unverified`.
C'est volontaire : ces deux inconnues viennent de la rétro-ingénierie et se
lèvent en trois tirages.

### 1. Quel plan commande quelle encre ? (30 min)

Le dossier de rétro-ingénierie marque ce point comme impossible à établir sans
faire tourner la machine. Une mire suffit.

```bash
rip target channel-id -o mire-canaux.prn --profile profiles/friankor-i1600.toml
```

Cinq barres, chacune précédée de *n* carrés de comptage : la barre à *n* carrés
est le plan *n−1* du fichier. Vous imprimez, vous notez la couleur sortie en
face de chaque barre, vous remettez les canaux dans cet ordre dans le profil, et
vous passez `channel_order_verified = true`.

Aucune typographie sur la mire : on compte des carrés, ce qui reste lisible même
si les têtes sont décalées.

### 2. Que dépose chaque taille de goutte ? (1 h)

```bash
rip target drop-wedge -o mire-gouttes.prn --profile … --csv gouttes.csv
# … impression, puis mesure au densitomètre, remplir la colonne measurement
rip calibrate drops gouttes.csv --profile …
```

Les plages sont des aplats **non tramés** : chaque plage est un seul niveau de
goutte, donc la densité mesurée est directement celle de cette taille de goutte.
La commande sort le bloc TOML à coller dans le profil.

Sans cette étape, `ripcore` suppose un escalier linéaire (une goutte moyenne =
2/3 d'une grosse), ce qui est faux sur toutes les têtes et se voit dans les
dégradés.

### 3. La réponse est-elle linéaire ? (2 h)

```bash
rip target lin-wedge -o mire-lin.prn --profile … --csv lin.csv
# … impression, mesure des 21 paliers par canal
rip calibrate lin lin.csv -o calib/rigide-uv-720x900.json
```

Puis référencez le fichier dans le profil média (`linearization = "…"`).

C'est l'étape qui fait la différence entre « ça imprime » et « ça imprime
bien » : sans elle, aucun profil ICC ne peut donner une couleur juste.

> **Méthode.** Les mesures sont converties par la relation de Murray–Davies
> avant d'alimenter les échelles. Le tramage mélange les niveaux linéairement en
> *réflectance*, pas en densité optique ; convertir est ce qui rend un aplat à
> 50 % réellement à mi-chemin. Détail dans [docs/calibration.md](docs/calibration.md).

---

## Ce qui est établi et ce qui ne l'est pas

| Point | État |
|---|---|
| En-tête `.prn` 48 o, champ par champ | **confirmé** — code du lecteur `PreviewPrn.dll` + 5 fichiers de production, recoupés par un contrôle géométrique indépendant (3 carrés exacts) |
| Raster planaire par canal, MSB d'abord | **confirmé** — lecteur + masques `ipht.dll` |
| `pass_mode` (champ 0x24) à 900 et 1200 dpi | **observé** sur 5 fichiers — toute autre résolution est refusée, pas extrapolée |
| Ordre des canaux | **inconnu** — mire `channel-id` |
| Échelle des tailles de goutte | **inconnue** — mire `drop-wedge` |
| Syntaxe de `SetPrintFile` / `SetPrintPara` | **inconnue** — capture Wireshark d'une impression UltraPrint (voir [docs/architecture.md](docs/architecture.md)) |

Rien de ce qui est inconnu n'est deviné silencieusement : le code lève une
erreur explicite qui dit quoi faire.

---

## Choix techniques qui pèsent sur la qualité

**Tramage par bruit bleu, sans état.** Le masque est généré par void-and-cluster
et le résultat ne dépend que de la position absolue dans le job. Conséquence
directe : le découpage en bandes ne peut pas produire de couture horizontale.
C'est vérifié par un test qui compare le traitement en un bloc et en tranches —
les deux doivent être identiques au bit près. Une diffusion d'erreur
multi-niveaux (Floyd–Steinberg, Jarvis, Stucki) est disponible en option,
vectorisée par fronts d'onde, et satisfait la même propriété.

**Quantification en densité, pas en niveau.** Un aplat demandé à 42 % dépose
42 % d'encre même avec une échelle de gouttes fortement non linéaire, parce que
le tramage répartit entre les deux niveaux qui encadrent la valeur avec la
proportion qui rend la moyenne exacte.

**Gestion couleur par LUT interpolée.** lcms2 ne travaille en CMJN qu'en 8 bits.
On échantillonne la transformation ICC sur une grille une fois, puis on
interpole en flottant : les séparations restent continues et les courbes de
linéarisation ne créent pas de marches dans les dégradés.

**La limite d'encre est une grandeur de surface.** Elle est mesurée et appliquée
sur des blocs de 16 px (≈ 0,5 mm), pas pixel par pixel — après tramage, un pixel
portant une grosse goutte sur cinq canaux est normal. Elle porte sur les canaux
process ; le blanc, qui est une couche distincte, a sa propre limite.

**Traitement en flux.** Un mural de 3 m fait plusieurs gigaoctets. Rien n'est
chargé en entier, ni à l'écriture, ni à la relecture de contrôle, ni à l'aperçu.

**Écriture atomique.** Le `.prn` est écrit dans un `.part` puis renommé. Un
fichier présent sur le disque est un fichier complet.

---

## Sécurité

- `rip send` **simule** par défaut. `--execute` envoie, `--print` imprime.
- Tout `.prn` est **relu depuis le disque** et re-contrôlé avant envoi,
  indépendamment du code qui l'a produit.
- Un profil dont l'ordre des canaux n'est pas vérifié bloque l'envoi.
- La carte n'accepte qu'une connexion : BetterPrinterApp doit tourner et être le
  seul à parler à la machine.

## Documentation

| | |
|---|---|
| [docs/prn-format.md](docs/prn-format.md) | Spécification du conteneur, étiquetée confirmé / ouvert |
| [docs/architecture.md](docs/architecture.md) | Carte des modules, décisions de conception, ce qui reste |
| [docs/calibration.md](docs/calibration.md) | Procédure de calibration détaillée |
| [docs/licences.md](docs/licences.md) | Dépendances, ICC, cadre de la rétro-ingénierie |
| `src/ripcore/ui/textes.py` | Tout le vocabulaire affiché, à relire et corriger |

## Tests

```bash
python -m pytest -q
```

Les tests ne se contentent pas de vérifier que le code fait ce qu'il fait : ils
rejouent la géométrie des 5 `.prn` de production, simulent une machine à réponse
connue pour vérifier que la calibration la retrouve, vérifient l'invariance du
tramage au découpage en bandes, et refusent qu'un terme technique atteigne
l'écran de l'opérateur.

L'interface elle-même est vérifiée par un parcours à l'écran (fenêtre réelle,
sans affichage) : les quatre écrans s'ouvrent, un travail complet est préparé
dans le fil d'arrière-plan, l'aperçu s'affiche et l'historique se remplit.
