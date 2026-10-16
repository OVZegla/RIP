// Mode vidéo : une vraie personne filmée (fond vert, bleu ou uni, ou WebM transparent).
// Le fond est retiré en direct, la personne est posée sur blanc et son ombre est
// projetée sur le mur derrière elle. Deux clips : « repos » en boucle, « parle » pendant les réponses.
import * as THREE from 'three';

// --- Réglages ---------------------------------------------------------------
const TOLERANCE = 0.11;   // écart de teinte en dessous duquel un pixel est considéré comme fond
const DOUCEUR = 0.09;     // largeur du dégradé de bord (cheveux)
const OMBRE = { opacite: 0.20, flou: 3.5, decalageX: 0.10, decalageY: 0.03, inclinaison: 0.10 };
const HAUTEUR = 0.92;     // part de la hauteur d'écran occupée par la vidéo
// ----------------------------------------------------------------------------

const vertex = /* glsl */`
  varying vec2 vUv;
  uniform float inclinaison;
  void main() {
    vUv = uv;
    vec3 p = position;
    p.x += p.y * inclinaison;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }`;

const detourage = /* glsl */`
  uniform sampler2D repos, parle;
  uniform float melange, tolerance, douceur, aCle, flou;
  uniform vec3 cle;
  varying vec2 vUv;
  vec2 chroma(vec3 c) {
    return vec2(-0.1687 * c.r - 0.3313 * c.g + 0.5 * c.b, 0.5 * c.r - 0.4187 * c.g - 0.0813 * c.b);
  }
  vec4 detourer(vec4 c) {
    if (aCle < 0.5) return c; // vidéo déjà transparente
    float d = distance(chroma(c.rgb), chroma(cle));
    float a = smoothstep(tolerance, tolerance + douceur, d);
    // Retire le reflet coloré du fond sur les bords (cheveux, épaules).
    vec3 rgb = c.rgb;
    if (cle.g > cle.r && cle.g > cle.b) rgb.g = min(rgb.g, max(rgb.r, rgb.b) * 1.05);
    else if (cle.b > cle.r && cle.b > cle.g) rgb.b = min(rgb.b, max(rgb.r, rgb.g) * 1.05);
    return vec4(rgb, c.a * a);
  }
  vec4 lire(vec2 uv) {
    vec4 a = detourer(texture2D(repos, uv, flou));
    vec4 b = detourer(texture2D(parle, uv, flou));
    return mix(a, b, melange);
  }`;

function materiau(ombre) {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: {
      repos: { value: null }, parle: { value: null }, melange: { value: 0 },
      cle: { value: new THREE.Color(0, 1, 0) }, aCle: { value: 1 },
      tolerance: { value: TOLERANCE }, douceur: { value: DOUCEUR },
      flou: { value: ombre ? OMBRE.flou : 0 },
      inclinaison: { value: ombre ? OMBRE.inclinaison : 0 },
      opacite: { value: OMBRE.opacite },
    },
    vertexShader: vertex,
    fragmentShader: detourage + (ombre
      ? `uniform float opacite;
         void main() { gl_FragColor = vec4(0.0, 0.0, 0.0, lire(vUv).a * opacite); }`
      : `void main() { vec4 c = lire(vUv); gl_FragColor = vec4(c.rgb, c.a);
         }`),
  });
}

async function videoDepuis(url) {
  // Chargée entièrement en mémoire : la boucle reste fluide même avec un serveur minimal.
  const blob = await (await fetch(url)).blob();
  const v = document.createElement('video');
  v.src = URL.createObjectURL(blob);
  v.muted = true; v.loop = true; v.playsInline = true; v.crossOrigin = 'anonymous';
  await v.play().catch(() => {});
  if (v.readyState < 2) await new Promise((r) => v.addEventListener('loadeddata', r, { once: true }));
  return v;
}

function texture(v) {
  const t = new THREE.VideoTexture(v);
  // Pas de conversion de couleur : les pixels de la vidéo sont affichés tels quels.
  t.colorSpace = THREE.NoColorSpace;
  t.generateMipmaps = true; // sert au flou de l'ombre
  t.minFilter = THREE.LinearMipmapLinearFilter;
  return t;
}

// Analyse une image : couleur du fond (coins), transparence, et boîte englobant la personne.
function analyser(v) {
  const l = 160, h = Math.round(160 * v.videoHeight / v.videoWidth);
  const c = document.createElement('canvas');
  c.width = l; c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(v, 0, 0, l, h);
  const px = ctx.getImageData(0, 0, l, h).data;
  const at = (x, y) => px.subarray((y * l + x) * 4, (y * l + x) * 4 + 4);
  const coins = [[2, 2], [l - 3, 2], [2, Math.floor(h / 2)], [l - 3, Math.floor(h / 2)]].map(([x, y]) => at(x, y));
  const transparente = coins.every((p) => p[3] < 128);
  const moy = [0, 1, 2].map((i) => coins.reduce((s, p) => s + p[i], 0) / coins.length / 255);
  const cle = new THREE.Color(...moy);
  // Personne = pixels nettement différents du fond.
  let bas = 0, gauche = l, droite = 0;
  for (let y = 0; y < h; y++) for (let x = 0; x < l; x++) {
    const p = at(x, y);
    const diff = transparente ? p[3] / 255
      : Math.abs(p[0] / 255 - moy[0]) + Math.abs(p[1] / 255 - moy[1]) + Math.abs(p[2] / 255 - moy[2]);
    if (diff > 0.35) { bas = Math.max(bas, y); gauche = Math.min(gauche, x); droite = Math.max(droite, x); }
  }
  return { transparente, cle, bas: bas / (h - 1), centre: (gauche + droite) / 2 / (l - 1) };
}

export async function demarrer(urlRepos, urlParle) {
  const conteneur = document.getElementById('scene');
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0xffffff, 1);
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
  conteneur.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(0, 1, 1, 0, -10, 10);

  const vRepos = await videoDepuis(urlRepos);
  const vParle = urlParle ? await videoDepuis(urlParle) : vRepos;
  const info = analyser(vRepos);
  const pleinPied = info.bas < 0.97; // les pieds sont visibles dans le cadre

  const tRepos = texture(vRepos), tParle = vParle === vRepos ? tRepos : texture(vParle);
  const personne = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), materiau(false));
  const ombre = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), materiau(true));
  for (const m of [personne, ombre]) {
    const u = m.material.uniforms;
    u.repos.value = tRepos; u.parle.value = tParle;
    u.cle.value.copy(info.cle); u.aCle.value = info.transparente ? 0 : 1;
  }
  // La géométrie part du bas (y = 0) pour que l'inclinaison de l'ombre pivote aux pieds.
  personne.geometry.translate(0, 0.5, 0);
  ombre.geometry.translate(0, 0.5, 0);
  ombre.renderOrder = 0; personne.renderOrder = 2;
  scene.add(ombre, personne);

  // Ombre de contact au sol si la personne est en pied.
  const sol = new THREE.Mesh(new THREE.CircleGeometry(0.5, 64), new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
    fragmentShader: 'varying vec2 vUv; void main(){ float d = length(vUv - 0.5) * 2.0; gl_FragColor = vec4(0.0,0.0,0.0, 0.22 * (1.0 - smoothstep(0.2, 1.0, d))); }',
  }));
  sol.renderOrder = 1;
  sol.visible = pleinPied;
  scene.add(sol);

  function cadrer() {
    const L = innerWidth, H = innerHeight;
    renderer.setSize(L, H);
    camera.right = L; camera.top = H; camera.updateProjectionMatrix();
    const ratio = vRepos.videoWidth / vRepos.videoHeight;
    let h = H * (pleinPied ? HAUTEUR : 1), l = h * ratio;
    if (l > L) { l = L; h = l / ratio; }
    const large = L / H > 1.1;
    // Centre de la personne vers 40 % de la largeur sur grand écran (le chat est à droite).
    const cx = (large ? 0.4 : 0.5) * L - (info.centre - 0.5) * l;
    const y0 = pleinPied ? H * 0.05 - (1 - info.bas) * h : 0;
    personne.scale.set(l, h, 1);
    personne.position.set(cx, y0, 0);
    ombre.scale.set(l * 1.02, h * 0.99, 1);
    ombre.position.set(cx + l * OMBRE.decalageX, y0 + h * OMBRE.decalageY, -1);
    sol.scale.set(l * 0.55, h * 0.035, 1);
    sol.position.set(cx + (info.centre - 0.5) * l + l * 0.04, y0 + (1 - info.bas) * h, -0.5);
  }
  addEventListener('resize', cadrer);
  cadrer();

  let parle = false, m = 0;
  renderer.setAnimationLoop(() => {
    m += ((parle ? 1 : 0) - m) * 0.12;
    personne.material.uniforms.melange.value = m;
    ombre.material.uniforms.melange.value = m;
    renderer.render(scene, camera);
  });

  window.avatar = {
    parler(actif) {
      if (actif && !parle && vParle !== vRepos) { vParle.currentTime = 0; vParle.play().catch(() => {}); }
      parle = actif;
    },
  };
  // Lecture bloquée sans interaction sur certains navigateurs : relance au premier clic.
  addEventListener('pointerdown', () => { vRepos.play().catch(() => {}); vParle.play().catch(() => {}); }, { once: true });
  window.dispatchEvent(new Event('avatar-pret'));
}
