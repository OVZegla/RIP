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

## L'avatar

`avatar/Michelle.glb` est le personnage d'exemple de three.js (Mixamo). La pose d'accueil (mains jointes),
la respiration et les hochements de tête quand elle parle sont calculés dans `avatar.js`.
Pour une tenue plus « hôtesse », remplacer ce fichier par un autre personnage `.glb` au squelette Mixamo
(par exemple exporté depuis mixamo.com) en gardant le même nom.

Pour un vrai hologramme (vitre Pepper's ghost, écran transparent), passer le navigateur en plein écran (F11).
