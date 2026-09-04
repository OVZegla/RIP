# Format `.prn` — spécification d'écriture

Source : dossier « RIP UltraPrint (HK i1600) — fonctionnement interne » v4 (2026-09-03),
§7 à §9. Les faits sont étiquetés **[confirmé]** (lu dans le code du lecteur
`PreviewPrn.dll` et/ou recoupé sur les 5 `.prn` de production) ou **[ouvert]**
(non établi par l'analyse statique — à lever par l'expérience, cf.
`docs/calibration.md`).

Cette page est la référence normative pour `ripcore.prn`. Toute divergence entre
le code et cette page est un bug de l'un ou de l'autre.

---

## 1. Dialectes

Le lecteur reconnaît quatre dialectes selon les 4 premiers octets **[confirmé]** :

| Magic (u32 LE) | ASCII  | En-tête | Statut ici |
|---|---|---|---|
| `0x7A646379` | `ycdz` | 64 o | lecture seule |
| `0x58485942` | `BYHX` | 84 o | lecture seule |
| `0x4D435441` | `ATCM` | 84 o | lecture seule (ordre canaux inversé 3,2,1,0) |
| tout le reste | — | **48 o** | **celui que nous écrivons** |

Le dialecte générique est celui des `.prn` de production d'UltraPrint. Son premier
dword vaut `0x00005555` mais **le lecteur ne le valide pas** : il stocke la valeur
et passe. `5555` n'est donc pas un vrai magic, c'est une convention. Nous
l'écrivons quand même à l'identique — il n'y a aucun gain à s'en écarter.

`srip.dll` sait aussi écrire un en-tête de 56 octets avec le magic `0x9527`
(mode 1) **[confirmé]**. Nous ne l'utilisons pas : le mode 48 octets est celui
dont on a 5 échantillons de production validés.

---

## 2. En-tête générique (48 octets, little-endian)

Le lecteur recopie chaque champ vers `obj+0x208..0x228` **[confirmé]** :

| Offset | Type | Champ | Notes |
|---|---|---|---|
| `0x00` | u32 | `marker` = `0x00005555` | non validé par le lecteur |
| `0x04` | u32 | `dpi_x` | **contrôlé ≠ 0** |
| `0x08` | u32 | `dpi_y` | **contrôlé ≠ 0** ; ratio pixel = `dpi_x / dpi_y` |
| `0x0C` | u32 | `bytes_per_line_per_channel` | stride total = `0x0C × 0x1C` |
| `0x10` | u32 | `lines` | hauteur en pixels |
| `0x14` | u32 | `height_720` | hauteur en unités 720 dpi |
| `0x18` | f32 | `height_m` | hauteur en mètres — **ignoré par le lecteur** |
| `0x1C` | u32 | `channels` | 5 sur les jobs de production (CMJN + Blanc) |
| `0x20` | u32 | `bits_per_pixel` | 2 (4 tailles de goutte) |
| `0x24` | u32 | `pass_mode` | entrelacement / passes — voir §5 |
| `0x28` | u32 × 2 | — | inutilisés, à zéro |

### Invariants vérifiés sur les 5 fichiers de production

```
taille_fichier - 48 == lines × (bytes_per_line_per_channel × channels)   [division exacte]
height_720     == round(lines / dpi_y × 720)
height_m       == height_720 / 720 × 0.0254
```

Recoupement géométrique (calculé, non fourni par le dossier — c'est une
vérification indépendante de l'interprétation ci-dessus) :

| fichier | o/ligne/canal | largeur px | largeur mm | lignes | hauteur mm |
|---|---|---|---|---|---|
| `22.prn` | 852 | 3408 | 120,3 | 5669 @1200 | 120,0 |
| `666.prn` | 1420 | 5680 | 200,4 | 7088 @900 | 200,0 |
| `22222.prn` | 2128 | 8512 | 300,4 | 10632 @900 | 300,0 |

Trois carrés exacts. L'interprétation « `0x0C` = octets par ligne **et par
canal**, `0x10` = lignes, 2 bpp » est démontrée, pas supposée.

---

## 3. Corps raster

À partir de l'offset `0x30`. Brut, **non compressé**, ligne par ligne du haut vers
le bas. À l'intérieur d'une ligne les données sont **planaires par canal**
**[confirmé]** (correction explicite de la v1 du dossier, qui supposait un
entrelacement par pixel) :

```
ligne N = [canal 0 : L octets][canal 1 : L octets] … [canal C-1 : L octets]
          L = bytes_per_line_per_channel        stride = L × C
```

Empaquetage à l'intérieur d'un plan : **MSB d'abord** **[confirmé]** — les masques
de `ipht.dll` sont `{0xFF,0x3F,0x0F,0x03}` pour le 2 bits, soit 4 pixels par
octet, le pixel 0 dans les bits 7-6.

```
octet[i] = (px[4i] << 6) | (px[4i+1] << 4) | (px[4i+2] << 2) | px[4i+3]
```

`L = ceil(largeur_px × bpp / 8)`. Les octets de queue au-delà de la largeur utile
sont à zéro.

---

## 4. Ordre des canaux — **[ouvert]**

Le mécanisme est connu (un plan par canal, dans l'ordre), **les étiquettes ne le
sont pas**. Le dossier RIP le liste explicitement comme irréductible sans
exécution (§12).

`ripcore` ne devine pas : l'ordre est une donnée du profil imprimante
(`channel_order` dans `profiles/*.toml`), et le profil livré porte
`channel_order_verified = false`. La mire `channel-id` (`rip target channel-id`)
lève l'inconnue en un tirage. Tant que le drapeau est faux, le CLI refuse
l'envoi machine sans `--allow-unverified`.

Ce que l'on sait : les jobs de production utilisent **5 canaux** (CMJN + Blanc) ;
d'anciens échantillons `TestFile` en 6 et 8 canaux incluaient vernis et encres
claires. Le dialecte `ATCM` inverse l'ordre (3,2,1,0), ce qui confirme qu'aucun
ordre n'est universel.

---

## 5. Champ `pass_mode` (`0x24`) — **[partiellement ouvert]**

Observé sur les 5 fichiers de production :

| `dpi_y` | `pass_mode` |
|---|---|
| 900 | 0 |
| 1200 | 4 |

Corrélation parfaite sur l'échantillon, mais 5 fichiers et 2 valeurs ne font pas
une règle générale. `ripcore` encode cette table dans le profil
(`pass_mode_by_dpi_y`) et **lève une erreur pour toute résolution non tabulée**
plutôt que d'extrapoler. Ajouter une entrée est une décision explicite, pas un
défaut silencieux.

---

## 6. Ce que nous n'écrivons pas

- **Pas de weave / entrelacement de passes.** Le raster est une image pleine page ;
  le découpage en passes, l'avance Y, la plume (`EclosionProc.dll`,
  `BP_ECLOSION_CONFIG`) et le calage des têtes sont faits en aval par
  BetterPrinter et la carte. C'est cohérent avec le fait que `pass_mode` soit un
  simple sélecteur dans l'en-tête plutôt qu'une géométrie décrite.
- **Pas de compression.** `ipcompre.dll` est un wrapper d'archive ZIP pour les
  projets, pas un codec raster **[confirmé]**.
- **Pas de métadonnées de job.** Elles passent par le protocole RipReceive (§30 du
  dossier SAV), pas par le fichier.

---

## 7. Divergence `srip.dll` — pourquoi on suit le lecteur

`srip.dll` écrit un en-tête dont les champs `0x0C/0x10/0x14/0x1C` sont des
**constantes** (4, 1, 8, 4), incompatibles avec les échantillons. Deux hypothèses
au dossier : une fonction de finalize qui réécrit l'en-tête, ou des échantillons
issus du générateur de mires de BetterPrinter.

La question est sans objet pour nous : **c'est le lecteur qui définit ce que la
machine consomme**, et le lecteur est décompilé et recoupé sur 5 fichiers réels.
Nous écrivons ce que le lecteur sait lire.
