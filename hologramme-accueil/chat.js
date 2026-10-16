// Conversation : petit modèle gratuit exécuté dans le navigateur (WebLLM, WebGPU),
// micro (reconnaissance vocale) et voix de synthèse française.

// --- À personnaliser ---------------------------------------------------------
const PRENOM = 'Léa';
const CONSIGNE = `Tu es ${PRENOM}, hôtesse d'accueil virtuelle affichée en hologramme à l'entrée d'une entreprise.
Tu accueilles les visiteurs avec chaleur et professionnalisme.
Réponds toujours en français, en une à trois phrases courtes, car tes réponses sont lues à voix haute.
Pas de listes, pas de mise en forme, pas d'émojis.
Si on te demande une information que tu ne connais pas (nom d'un employé, horaire précis, salle),
dis poliment que tu vas prévenir quelqu'un de l'accueil, sans inventer.`;
const ACCUEIL = `Bonjour et bienvenue ! Je suis ${PRENOM}, votre hôtesse d'accueil. Comment puis-je vous aider ?`;
// -----------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const fil = $('fil'), texte = $('texte'), etat = $('etat'), barre = $('progression').firstElementChild;
const choixModele = $('modele'), boutonCharger = $('charger'), boutonMicro = $('micro'), caseVoix = $('voix');

let moteur = null;
let occupe = false;
const historique = [];

function memoire(cle, valeur) {
  try {
    if (valeur === undefined) return localStorage.getItem(cle);
    localStorage.setItem(cle, valeur);
  } catch { return null; }
}

function bulle(classe, contenu = '') {
  const d = document.createElement('div');
  d.className = 'bulle ' + classe;
  d.textContent = contenu;
  fil.appendChild(d);
  fil.scrollTop = fil.scrollHeight;
  return d;
}

// --- Voix ---------------------------------------------------------------------
let voixFr = null;
function choisirVoix() {
  const voix = speechSynthesis.getVoices().filter((v) => v.lang?.toLowerCase().startsWith('fr'));
  const feminines = /denise|amelie|amélie|julie|hortense|audrey|aurelie|aurélie|marie|léa|lea|vivienne|eloise|brigitte|celine|céline|google français|female|femme/i;
  voixFr = voix.find((v) => feminines.test(v.name) && /natural|online|neural/i.test(v.name))
    || voix.find((v) => feminines.test(v.name)) || voix[0] || null;
}
if ('speechSynthesis' in window) {
  choisirVoix();
  speechSynthesis.onvoiceschanged = choisirVoix;
}

let enAttente = 0;
function dire(phrase) {
  phrase = phrase.trim();
  if (!phrase || !caseVoix.checked || !('speechSynthesis' in window)) return;
  const u = new SpeechSynthesisUtterance(phrase);
  u.lang = 'fr-FR';
  if (voixFr) u.voice = voixFr;
  u.rate = 1.02;
  u.pitch = 1.05;
  enAttente++;
  u.onstart = () => window.avatar?.parler(true);
  u.onend = u.onerror = () => { if (--enAttente <= 0) { enAttente = 0; window.avatar?.parler(false); } };
  speechSynthesis.speak(u);
}

// Découpe le flux en phrases pour commencer à parler sans attendre la fin.
function decoupeur() {
  let tampon = '';
  return {
    ajouter(morceau) {
      tampon += morceau;
      let m;
      while ((m = tampon.match(/^([\s\S]*?[.!?…:;])(\s+)/))) {
        dire(m[1]);
        tampon = tampon.slice(m[0].length);
      }
    },
    finir() { dire(tampon); tampon = ''; },
  };
}

// --- Réponses de démonstration (sans modèle) ----------------------------------
const DEMO = [
  [/bonjour|salut|bonsoir|hello/i, `Bonjour ! Ravie de vous accueillir. Que puis-je faire pour vous ?`],
  [/rendez-vous|rdv|réunion|rencontre/i, `Très bien. Pouvez-vous me donner votre nom et celui de la personne que vous venez voir ? Je la préviens de votre arrivée.`],
  [/toilettes|wc/i, `Les toilettes sont au fond du couloir, sur votre droite.`],
  [/horaire|heure|ouvert|ferm/i, `Nous sommes ouverts du lundi au vendredi, de 9 heures à 18 heures.`],
  [/wifi|wi-fi|internet/i, `Le réseau invité s'appelle Visiteurs. Le code vous sera remis par l'accueil.`],
  [/café|boisson|eau/i, `Un distributeur de boissons se trouve dans l'espace d'attente, juste à côté.`],
  [/merci/i, `Avec plaisir ! N'hésitez pas si vous avez une autre question.`],
  [/au revoir|bonne journée|à bientôt/i, `Au revoir et très bonne journée !`],
  [/qui es-tu|qui êtes-vous|ton nom|votre nom|tu t'appelles/i, `Je m'appelle ${PRENOM}, je suis l'hôtesse d'accueil virtuelle de l'entreprise.`],
];
function reponseDemo(q) {
  for (const [motif, r] of DEMO) if (motif.test(q)) return r;
  return `Je suis en mode démonstration. Chargez le modèle en haut de l'écran pour que je puisse vraiment vous répondre.`;
}

// --- Envoi --------------------------------------------------------------------
async function envoyer(question) {
  question = question.trim();
  if (!question || occupe) return;
  occupe = true;
  boutonMicro.disabled = true;
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  bulle('visiteur', question);
  const b = bulle('agent', '…');

  try {
    if (!moteur) {
      await new Promise((r) => setTimeout(r, 350));
      const r = reponseDemo(question);
      b.textContent = r;
      if (caseVoix.checked) dire(r);
      else { window.avatar?.parler(true); setTimeout(() => window.avatar?.parler(false), 1800); }
      return;
    }

    historique.push({ role: 'user', content: question });
    // Les petits modèles s'égarent sur de longs contextes : on garde les derniers échanges.
    const messages = [{ role: 'system', content: CONSIGNE }, ...historique.slice(-8)];
    const flux = await moteur.chat.completions.create({
      messages, stream: true, temperature: 0.6, max_tokens: 160,
    });
    const voix = decoupeur();
    let reponse = '';
    if (!caseVoix.checked) window.avatar?.parler(true);
    for await (const morceau of flux) {
      const delta = morceau.choices[0]?.delta?.content || '';
      if (!delta) continue;
      reponse += delta;
      b.textContent = reponse;
      fil.scrollTop = fil.scrollHeight;
      voix.ajouter(delta);
    }
    voix.finir();
    if (!caseVoix.checked) window.avatar?.parler(false);
    historique.push({ role: 'assistant', content: reponse });
  } catch (e) {
    console.error(e);
    b.textContent = "Désolée, j'ai eu un souci technique. Pouvez-vous reformuler ?";
    window.avatar?.parler(false);
  } finally {
    occupe = false;
    boutonMicro.disabled = !Reconnaissance;
  }
}

$('saisie').addEventListener('submit', (e) => {
  e.preventDefault();
  const q = texte.value;
  texte.value = '';
  envoyer(q);
});

// --- Chargement du modèle -----------------------------------------------------
async function chargerModele() {
  if (!navigator.gpu) {
    etat.textContent = 'WebGPU indisponible : utilisez Chrome ou Edge récent. Mode démonstration actif.';
    return;
  }
  const id = choixModele.value;
  boutonCharger.disabled = choixModele.disabled = true;
  etat.textContent = 'Chargement de la bibliothèque…';
  try {
    const webllm = await import('@mlc-ai/web-llm');
    moteur = await webllm.CreateMLCEngine(id, {
      initProgressCallback: (p) => {
        barre.style.width = Math.round((p.progress || 0) * 100) + '%';
        etat.textContent = p.text.length > 70 ? p.text.slice(0, 70) + '…' : p.text;
      },
    });
    memoire('modele', id);
    barre.style.width = '100%';
    etat.textContent = `Modèle prêt : ${choixModele.selectedOptions[0].text.split(' (')[0]} (gratuit, local).`;
    boutonCharger.textContent = 'Modèle chargé';
  } catch (e) {
    console.error(e);
    moteur = null;
    etat.textContent = 'Échec du chargement : ' + (e.message || e) + ' — mode démonstration.';
    boutonCharger.disabled = choixModele.disabled = false;
  }
}
boutonCharger.addEventListener('click', chargerModele);

// --- Micro --------------------------------------------------------------------
const Reconnaissance = window.SpeechRecognition || window.webkitSpeechRecognition;
let ecoute = null;
if (!Reconnaissance) {
  boutonMicro.disabled = true;
  boutonMicro.title = 'Reconnaissance vocale non prise en charge par ce navigateur (utilisez Chrome ou Edge)';
} else {
  boutonMicro.addEventListener('click', () => {
    if (ecoute) { ecoute.stop(); return; }
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    ecoute = new Reconnaissance();
    ecoute.lang = 'fr-FR';
    ecoute.interimResults = true;
    ecoute.maxAlternatives = 1;
    boutonMicro.classList.add('actif');
    let final = '';
    ecoute.onresult = (e) => {
      let provisoire = '';
      for (const r of e.results) (r.isFinal ? (final = r[0].transcript) : (provisoire += r[0].transcript));
      texte.value = final || provisoire;
    };
    ecoute.onerror = (e) => { if (e.error !== 'no-speech' && e.error !== 'aborted') etat.textContent = 'Micro : ' + e.error; };
    ecoute.onend = () => {
      boutonMicro.classList.remove('actif');
      ecoute = null;
      const q = texte.value;
      texte.value = '';
      if (q.trim()) envoyer(q);
    };
    ecoute.start();
  });
}

// --- Démarrage ----------------------------------------------------------------
const dejaCharge = memoire('modele');
if (dejaCharge && [...choixModele.options].some((o) => o.value === dejaCharge)) {
  choixModele.value = dejaCharge;
  chargerModele(); // déjà en cache du navigateur : rechargement rapide
}
window.addEventListener('avatar-pret', () => {
  bulle('agent', ACCUEIL);
  // Les navigateurs bloquent la voix avant toute interaction : on la joue au premier clic.
  const lire = () => { dire(ACCUEIL); removeEventListener('pointerdown', lire); };
  addEventListener('pointerdown', lire, { once: true });
}, { once: true });
