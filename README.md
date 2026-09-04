# ripcore — RIP pour presses murales UV à têtes Epson I1600

Remplace **UltraPrint** dans la chaîne d'impression. Produit des fichiers `.prn`
que **BetterPrinter** consomme tels quels : la machine, le weave, la plume, le
nettoyage, les lampes UV et le dongle restent gérés par le logiciel d'origine.
Nous ne reprenons que la partie où il y a un intérêt métier — couleur, trame,
limitation d'encre, blanc et vernis.

```
votre fichier → ripcore → .prn → BetterPrinterApp → carte → machine
```

Ce périmètre est un choix, pas une limite subie : le canal image de la carte
(port 8001) n'est pas spécifié par la rétro-ingénierie disponible, et écrire
soi-même dans les registres moteur d'une machine de 2 m sans banc d'essai n'est
pas un projet, c'est un accident. Voir [docs/architecture.md](docs/architecture.md).

---

## Installation

```bash
pip install -e ".[images]"     # numpy + Pillow (Pillow embarque lcms2 pour l'ICC)
apt install ghostscript        # seulement si vous rippez des PDF / PS
```

Python 3.11 ou plus.

## En deux minutes

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

## Tests

```bash
python -m pytest -q
```

Les tests ne se contentent pas de vérifier que le code fait ce qu'il fait : ils
rejouent la géométrie des 5 `.prn` de production, simulent une machine à réponse
connue pour vérifier que la calibration la retrouve, et vérifient l'invariance
du tramage au découpage en bandes.
