// Avatar 3D : scène blanche, ombre portée sur le mur derrière et au sol,
// pose d'accueil calculée sur le squelette, respiration et gestes quand elle parle.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const conteneur = document.getElementById('scene');

const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.setClearColor(0xffffff, 1);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
conteneur.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, innerWidth / innerHeight, 0.1, 50);

// Lumières : une principale en hauteur, devant et à gauche, qui projette l'ombre
// en arrière à droite sur le mur ; le reste reste doux pour garder le blanc.
scene.add(new THREE.HemisphereLight(0xffffff, 0xdfe6ee, 1.6));
const cle = new THREE.DirectionalLight(0xffffff, 2.4);
cle.position.set(-1.6, 3.2, 3.0);
cle.castShadow = true;
cle.shadow.mapSize.set(2048, 2048);
cle.shadow.camera.left = -2; cle.shadow.camera.right = 2;
cle.shadow.camera.top = 3; cle.shadow.camera.bottom = -1;
cle.shadow.camera.near = 0.5; cle.shadow.camera.far = 10;
cle.shadow.bias = -0.0004;
scene.add(cle);
const contre = new THREE.DirectionalLight(0xbfefff, 1.2); // liseré bleuté « hologramme »
contre.position.set(1.5, 2, -2);
scene.add(contre);

// Sol et mur invisibles : seule l'ombre s'y dessine, sur fond blanc.
const ombreSol = new THREE.Mesh(new THREE.PlaneGeometry(12, 6),
  new THREE.ShadowMaterial({ opacity: 0.22 }));
ombreSol.rotation.x = -Math.PI / 2;
ombreSol.position.z = 2.3; // s'arrête au pied du mur, sans recouvrement
ombreSol.receiveShadow = true;
scene.add(ombreSol);
const ombreMur = new THREE.Mesh(new THREE.PlaneGeometry(12, 8),
  new THREE.ShadowMaterial({ opacity: 0.16 }));
ombreMur.position.set(0, 4, -0.7);
ombreMur.receiveShadow = true;
scene.add(ombreMur);

// Socle lumineux discret sous les pieds.
const socle = new THREE.Mesh(new THREE.RingGeometry(0.36, 0.42, 96),
  new THREE.MeshBasicMaterial({ color: 0x19b6d8, transparent: true, opacity: 0.55, side: THREE.DoubleSide }));
socle.rotation.x = -Math.PI / 2;
socle.position.y = 0.002;
scene.add(socle);
const halo = new THREE.Mesh(new THREE.CircleGeometry(0.36, 96),
  new THREE.MeshBasicMaterial({ color: 0x19b6d8, transparent: true, opacity: 0.08 }));
halo.rotation.x = -Math.PI / 2;
halo.position.y = 0.001;
scene.add(halo);

const os = {};
const repos = new Map();
let parle = false;
let intensiteParole = 0;

function cadrer() {
  const aspect = innerWidth / innerHeight;
  camera.aspect = aspect;
  // Sur écran large, l'avatar se décale à gauche pour laisser la place au chat.
  const decalage = aspect > 1.1 ? 0.45 : 0;
  camera.position.set(decalage, 1.15, aspect > 1.1 ? 4.6 : 5.6);
  camera.lookAt(decalage, 0.95, 0);
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
}
addEventListener('resize', cadrer);
cadrer();

// Oriente un os pour que le segment os → enfant pointe dans la direction voulue (repère monde).
function viser(nom, nomEnfant, direction) {
  const b = os[nom], e = os[nomEnfant];
  scene.updateMatrixWorld(true);
  const pB = b.getWorldPosition(new THREE.Vector3());
  const pE = e.getWorldPosition(new THREE.Vector3());
  const actuel = pE.sub(pB).normalize();
  const rot = new THREE.Quaternion().setFromUnitVectors(actuel, direction.clone().normalize());
  const monde = rot.multiply(b.getWorldQuaternion(new THREE.Quaternion()));
  const parent = b.parent.getWorldQuaternion(new THREE.Quaternion()).invert();
  b.quaternion.copy(parent.multiply(monde));
  scene.updateMatrixWorld(true);
}

new GLTFLoader().load('avatar/Michelle.glb', (gltf) => {
  const perso = gltf.scene;
  perso.traverse((o) => {
    if (o.isBone) os[o.name.replace(/^mixamorig:?/, '')] = o;
    if (o.isMesh) {
      o.castShadow = true;
      o.frustumCulled = false;
      if (o.material) o.material.envMapIntensity = 1;
    }
  });
  scene.add(perso);

  // Taille réelle : 1,68 m, pieds au sol.
  scene.updateMatrixWorld(true);
  let boite = new THREE.Box3().setFromObject(perso);
  const echelle = 1.68 / (boite.max.y - boite.min.y);
  perso.scale.multiplyScalar(echelle);
  scene.updateMatrixWorld(true);
  boite = new THREE.Box3().setFromObject(perso);
  perso.position.y -= boite.min.y;
  perso.position.x -= (boite.min.x + boite.max.x) / 2;
  perso.position.z -= (boite.min.z + boite.max.z) / 2;
  scene.updateMatrixWorld(true);

  // Pose d'accueil : bras le long du corps, avant-bras légèrement vers l'avant.
  for (const cote of ['Left', 'Right']) {
    const x = os[cote + 'Arm'].getWorldPosition(new THREE.Vector3()).x;
    const s = Math.sign(x) || (cote === 'Left' ? 1 : -1);
    viser(cote + 'Arm', cote + 'ForeArm', new THREE.Vector3(s * 0.2, -1, 0.06));
    viser(cote + 'ForeArm', cote + 'Hand', new THREE.Vector3(-s * 0.32, -0.75, 0.6));
    viser(cote + 'Hand', cote + 'HandMiddle1', new THREE.Vector3(-s * 0.45, -0.6, 0.55));
  }
  for (const [nom, b] of Object.entries(os)) repos.set(nom, b.quaternion.clone());

  window.dispatchEvent(new Event('avatar-pret'));
}, undefined, (err) => {
  console.error(err);
  document.getElementById('etat').textContent = "Impossible de charger l'avatar (lancez via « Lancer l'hologramme.bat »).";
});

const tmp = new THREE.Quaternion();
const eul = new THREE.Euler();
function ajouter(nom, x, y, z) {
  const b = os[nom];
  if (!b) return;
  b.quaternion.multiply(tmp.setFromEuler(eul.set(x, y, z)));
}

const horloge = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const t = horloge.getElapsedTime();
  intensiteParole += ((parle ? 1 : 0) - intensiteParole) * 0.08;
  const p = intensiteParole;

  if (repos.size) {
    for (const [nom, q] of repos) os[nom].quaternion.copy(q);
    const souffle = Math.sin(t * 1.6);
    ajouter('Spine', 0, Math.sin(t * 0.5) * 0.02, Math.sin(t * 0.37) * 0.012);
    ajouter('Spine2', souffle * 0.012, 0, 0);
    ajouter('LeftShoulder', 0, 0, souffle * 0.01);
    ajouter('RightShoulder', 0, 0, -souffle * 0.01);
    // Tête : regard qui flotte un peu, hochements quand elle parle.
    ajouter('Neck', Math.sin(t * 0.7) * 0.02 + p * Math.sin(t * 5.3) * 0.025, Math.sin(t * 0.43) * 0.05, 0);
    ajouter('Head', p * (Math.sin(t * 7.1) * 0.035 + Math.sin(t * 3.2) * 0.02),
      p * Math.sin(t * 1.9) * 0.06, Math.sin(t * 0.31) * 0.03 + p * Math.sin(t * 2.4) * 0.03);
    // Geste de la main droite pendant la parole.
    ajouter('RightForeArm', p * (0.25 + Math.sin(t * 2.6) * 0.12), 0, 0);
    ajouter('RightHand', p * Math.sin(t * 3.4) * 0.15, 0, 0);
  }

  socle.material.opacity = 0.45 + Math.sin(t * 2) * 0.1 + p * 0.2;
  socle.scale.setScalar(1 + p * Math.sin(t * 6) * 0.02);
  renderer.render(scene, camera);
});

window.avatar = {
  parler(actif) { parle = actif; },
};
