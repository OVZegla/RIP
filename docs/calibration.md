# Calibration

Trois mires, dans cet ordre. Chacune dépend de la précédente : calibrer la
linéarisation avant de connaître l'échelle des gouttes donne une courbe qui
compense deux erreurs à la fois et ne tient pas.

Matériel : un densitomètre ou un spectrophotomètre. À défaut, un scanner
correctement profilé dépanne pour la linéarisation, pas pour les gouttes.

---

## 0. Préalables

- Machine stable : têtes propres (test de buses sans manque), hauteur Z fixée et
  notée, lampes UV en régime.
- Le support et l'encre de production, pas un chute d'essai d'un autre lot.
- **Notez la hauteur Z et la résolution** : la calibration ne vaut que pour ce
  triplet (support, résolution, hauteur). C'est aussi pourquoi les profils ICC
  livrés avec la machine existent en `5MM` et `10MM`.

---

## 1. Ordre des canaux — `channel-id`

```bash
rip target channel-id -o mire-canaux.prn --profile profiles/ma-machine.toml
rip send mire-canaux.prn --host <PC BetterPrinter> --execute --print \
    --allow-unverified
```

`--allow-unverified` est nécessaire ici, et seulement ici : c'est précisément la
mire qui lève l'inconnue.

Lecture : cinq barres, chacune précédée de *n* carrés. La barre à *n* carrés est
le plan *n−1*. Relevez la couleur sortie en face de chaque barre.

Exemple : si la barre à 1 carré sort en magenta et celle à 2 carrés en cyan,
l'ordre réel des plans commence par M puis C. Réordonnez les blocs
`[[channels]]` du profil dans cet ordre, puis :

```toml
channel_order_verified = true
```

**Ne passez pas ce drapeau à true « pour voir ».** Il est là pour empêcher un
tirage grand format avec le blanc posé à la place du noir.

---

## 2. Tailles de goutte — `drop-wedge`

```bash
rip target drop-wedge -o mire-gouttes.prn --profile … --csv gouttes.csv
```

La mire donne, par canal, un aplat par taille de goutte. Les plages ne sont
**pas tramées** : tous les pixels d'une plage portent le même niveau. La densité
mesurée est donc celle de cette taille de goutte, sans contribution du tramage.

Mesurez chaque plage, **y compris le support nu** (les lignes `value,0` du CSV,
qui ne correspondent à aucune plage imprimée : c'est votre blanc de référence).
Remplissez la colonne `measurement`, puis :

```bash
rip calibrate drops gouttes.csv --profile profiles/ma-machine.toml
```

La commande sort le bloc TOML à coller :

```toml
[drop_levels]
densities = [0.0, 0.241, 0.607, 1.0]
calibrated = true
```

Si la commande refuse en disant que l'échelle n'est pas croissante, c'est un
signal, pas un bug : une taille de goutte qui dépose moins que la précédente
veut dire une buse en défaut, une forme d'onde inadaptée, ou des plages mesurées
dans le désordre.

---

## 3. Linéarisation — `lin-wedge`

```bash
rip target lin-wedge -o mire-lin.prn --profile … --csv lin.csv --steps 21
```

Cette mire-ci est tramée normalement, avec l'échelle de gouttes que vous venez
de calibrer. Elle mesure la réponse **du système complet**.

Mesurez les 21 paliers de chaque canal, puis :

```bash
rip calibrate lin lin.csv -o calib/rigide-uv-720x900.json
```

Référencez le fichier dans le profil média :

```toml
linearization = "../calib/rigide-uv-720x900.json"
```

Contrôle : réimprimez la mire avec la linéarisation active. Les paliers doivent
maintenant monter régulièrement. Un ou deux points à ±2 % sont normaux ; un
palier qui n'avance pas indique une saturation — baissez la limite du canal.

---

## 4. Limites d'encre

À faire à l'œil et au toucher, la mesure ne suffit pas.

Imprimez des aplats composés (CM, CMY, CMYK, et les mêmes avec sous-couche
blanche) en faisant varier `ink_limits.total` de 2,0 à 3,2. Cherchez le point
juste avant :

- l'encre qui coule ou se rassemble en gouttelettes ;
- une surface qui reste collante après passage sous UV (non-polymérisation à
  cœur) ;
- un aplat qui ne gagne plus en densité quand on ajoute de l'encre.

Prenez la valeur juste en dessous, et retirez-en 5 % de marge pour les
variations de température et de lot d'encre.

Si vous imprimez avec sous-couche blanche, réglez aussi `ink_limits.total_all`,
qui borne l'ensemble blanc compris.

---

## Pourquoi Murray–Davies

Le tramage place des gouttes de tailles différentes côte à côte. L'œil et le
densitomètre voient la moyenne de ce mélange — et cette moyenne est linéaire en
**réflectance**, pas en densité optique, parce que la densité est un logarithme.

Un exemple. Un aplat plein mesure D = 1,50. Une plage à moitié couverte ne
mesure pas 0,75 : elle mesure

    D = −log₁₀(1 − 0,5 × (1 − 10^−1,50)) = 0,31

Construire l'échelle des gouttes sur les densités brutes reviendrait donc à
croire que cette plage dépose 21 % d'encre au lieu de 50 %. Toute la chaîne
serait décalée, et les dégradés sortiraient bouchés dans les clairs.

`ripcore` convertit donc les mesures en couverture avant de construire les
échelles :

    couverture = (1 − 10^−D) / (1 − 10^−D_aplat)

C'est le défaut (`--metric coverage`). Le mode `--metric density` reste
disponible pour comparer avec un flux existant qui aurait fait l'autre choix,
mais ne le prenez pas pour la production.

---

## Quand tout recalibrer

- changement de support ou de lot d'encre ;
- changement de hauteur Z ou de résolution ;
- remplacement d'une tête ;
- dérive visible : une couleur qui s'écarte alors que le fichier n'a pas changé.

Gardez un jeu de fichiers de calibration par (support × résolution × hauteur) et
nommez-les explicitement. Un profil média par combinaison est plus sûr qu'un
profil que l'on édite.
