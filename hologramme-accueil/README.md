# Hôtesse d'accueil en hologramme (prototype)

Avatar 3D d'une femme sur fond blanc, avec son ombre portée sur le mur derrière elle,
et un petit chatbot **gratuit** pour tester la conversation au clavier ou à la voix.

## Lancer

Double-cliquer sur **`Lancer l'hologramme.bat`** (Python doit être installé), ou depuis ce dossier :

```
python -m http.server 8765
```

puis ouvrir <http://localhost:8765/> dans **Chrome ou Edge**.
(Ouvrir `index.html` directement par double-clic ne marche pas : le navigateur bloque le chargement du modèle 3D.)

## Le chatbot

- **Mode démonstration** dès l'ouverture : quelques réponses toutes faites (bonjour, rendez-vous, toilettes, horaires, wifi…).
- **« Charger le modèle »** : télécharge un petit modèle de langage libre (Qwen 2.5 ou Llama 3.2) qui tourne
  **entièrement dans le navigateur** via WebLLM/WebGPU. Aucun compte, aucune clé, aucun coût.
  Premier chargement : 400 Mo à 1 Go selon le modèle ; ensuite il reste en cache et se recharge seul.
- **Micro** : bouton à gauche du champ, reconnaissance vocale en français (Chrome / Edge).
- **Voix** : les réponses sont lues par une voix française du système (case « Réponse vocale »).
  Sur Windows, Edge propose les voix naturelles « Denise » / « Vivienne », les plus agréables.

Pour changer le prénom, le ton ou les consignes de l'hôtesse : en haut de `chat.js` (`PRENOM`, `CONSIGNE`, `ACCUEIL`).
Les réponses de démonstration sont dans le tableau `DEMO` du même fichier.

## Avatar réaliste : une vraie personne filmée

Déposez deux vidéos dans le dossier `videos/` et la page les utilise automatiquement à la place du personnage 3D :

| Fichier | Contenu | Durée |
|---|---|---|
| `videos/repos.mp4` | la personne attend : sourire, regard caméra, petits mouvements naturels | 10 à 20 s |
| `videos/parle.mp4` | la personne parle naturellement face caméra (n'importe quel texte) | 10 à 20 s |

`.webm` est aussi accepté, y compris avec transparence. Sans `parle`, la vidéo `repos` sert pour tout.

**Le tournage** (un smartphone suffit) :
- fond **vert uni** (tissu ou papier, 20 à 30 € en ligne), bien éclairé et sans plis ; un mur blanc ou bleu uni marche aussi, moins proprement ;
- la personne à 1 m du fond pour éviter son ombre et les reflets verts, pas de vêtement vert ;
- téléphone sur pied, **à la verticale**, sans zoom ni mouvement ; cadrage en pied ou en buste, au choix ;
- pour `repos`, terminer dans la même position qu'au début : la boucle ne se verra pas ;
- exporter en MP4 (H.264) 720p ou 1080p.

La page détecte seule la couleur du fond, la retire, pose la personne sur blanc, projette son ombre sur le mur
derrière elle et ajoute une ombre au sol si les pieds sont visibles. Elle bascule en fondu de `repos` à `parle`
pendant les réponses. Réglages (tolérance du détourage, ombre, taille) en haut de `video.js`.

À savoir :
- **Droit à l'image** : la personne filmée doit avoir donné son accord écrit pour cet usage.
- **Synchronisation des lèvres** : la vidéo `parle` est générique, les lèvres ne suivent pas exactement les mots.
  Pour une vraie synchronisation, il faut un service d'avatar IA à partir d'une photo ou d'une vidéo de la personne
  (HeyGen, D-ID : payants au-delà de l'essai) ou un outil libre comme LivePortrait ou MuseTalk (gratuit, mais il
  faut une carte graphique NVIDIA).

## L'avatar 3D (démonstration, sans vidéo)

`avatar/Michelle.glb` est le personnage d'exemple de three.js (Mixamo). La pose d'accueil (mains jointes),
la respiration et les hochements de tête quand elle parle sont calculés dans `avatar.js`.
Pour une tenue plus « hôtesse », remplacer ce fichier par un autre personnage `.glb` au squelette Mixamo
(par exemple exporté depuis mixamo.com) en gardant le même nom.

Pour un vrai hologramme (vitre Pepper's ghost, écran transparent), passer le navigateur en plein écran (F11).
