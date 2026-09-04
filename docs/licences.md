# Licences et cadre juridique

Ce document résume ce dont il faut tenir compte. **Il ne remplace pas l'avis
d'un avocat en propriété intellectuelle**, en particulier si vous envisagez un
jour de vendre ce RIP.

## Rétro-ingénierie

Les deux dossiers dont ce projet est issu relèvent de l'interopérabilité : vous
êtes propriétaires des machines et vous écrivez un logiciel qui doit dialoguer
avec elles. C'est le cas prévu par l'article L.122-6-1 IV du code de la
propriété intellectuelle et par l'article 6 de la directive 2009/24/CE.

Les dossiers restent du bon côté de la ligne et ce dépôt aussi :

- protection **documentée**, jamais contournée ;
- aucune émulation de dongle, aucun keygen, aucun dépaquetage ;
- aucun code décompilé recopié — tout est réimplémenté à partir de la
  description du format.

**Gardez cette ligne.** Elle est ce qui distingue l'interopérabilité de la
contrefaçon.

## Dépendances

| Composant | Licence | Conséquence |
|---|---|---|
| NumPy | BSD | aucune |
| Pillow | MIT-CMU | aucune |
| lcms2 (embarqué dans Pillow) | MIT | aucune |
| Ghostscript | **AGPL v3** | usage interne : sans conséquence. Distribution à des tiers : licence commerciale Artifex, ou remplacement de l'interpréteur. |

Ghostscript n'est utilisé que pour rendre les PDF et PostScript, via un appel de
processus externe. Si vous ne rippez que des images matricielles, il n'est pas
installé et la question ne se pose pas.

## Profils ICC et fichiers de configuration

Les profils ICC de sortie (`ICC Profile/Output/Epson-W5113/*.icm`), les matrices
de trame (`Moths/*.mht`), les fichiers de configuration et les formes d'onde
sont livrés avec la machine. Vous pouvez les utiliser sur vos machines ; vous ne
pouvez pas les redistribuer avec un logiciel vendu à des tiers.

Ce dépôt n'en contient aucun. Les chemins des profils média y sont des
références, pas des copies.

## Si vous distribuez ce RIP un jour

Trois points à traiter avant, pas après :

1. Remplacer Ghostscript, ou prendre une licence Artifex.
2. Produire vos propres profils ICC, mesurés sur vos machines.
3. Faire relire le cadre de rétro-ingénierie par un conseil, en particulier la
   frontière entre interopérabilité et produit concurrent.
