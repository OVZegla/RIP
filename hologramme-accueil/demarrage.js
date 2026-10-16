// Choisit l'avatar : la vidéo d'une vraie personne si elle est présente dans videos/,
// sinon le personnage 3D de démonstration.
async function existe(url) {
  try { return (await fetch(url, { method: 'HEAD' })).ok; } catch { return false; }
}
async function trouver(nom) {
  for (const ext of ['webm', 'mp4']) if (await existe(`videos/${nom}.${ext}`)) return `videos/${nom}.${ext}`;
  return null;
}

const repos = await trouver('repos');
if (repos) {
  const { demarrer } = await import('./video.js');
  await demarrer(repos, await trouver('parle'));
} else {
  await import('./avatar.js');
}
