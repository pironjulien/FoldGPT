'use strict';
const english = document.documentElement.lang === 'en';
const t = (fr,en) => english ? en : fr;
const captures = {
  desktop: {file:'codex-desktop-anonymized.png',title:t('Le bureau Codex, au complet.','The complete Codex desktop.'),
    description:t('Navigation, projets et composeur du client Linux ARM64, affichés localement sur l’écran intérieur. Seuls le nom et l’avatar du compte ont été anonymisés.','Navigation, projects and the Linux ARM64 composer, displayed locally on the inner screen. Only the account name and avatar have been anonymized.'),
    alt:t('Capture de l’accueil Codex sur le Fold, informations de compte masquées.','Codex home captured on the Fold, with account information redacted.')},
  runtime: {file:'workspace-runtime.png',title:t('Le workspace, dans le client.','The workspace, inside the client.'),
    description:t('Capture réelle des dépendances Codex et du bundle FoldGPT ARM64 dans les paramètres de l’application.','A real capture of Codex dependencies and the FoldGPT ARM64 bundle in the application settings.'),
    alt:t('Paramètres réels des dépendances de l’espace de travail FoldGPT ARM64.','Real FoldGPT ARM64 workspace dependency settings.')},
  keyboard: {file:'android-keyboard.png',title:t('Le clavier Samsung, dans Codex.','The Samsung keyboard, inside Codex.'),
    description:t('Capture d’un essai de saisie réelle avec le clavier Android partagé, le composeur Codex et le navigateur intégré.','A real typing test with the split Android keyboard, Codex composer and integrated browser.'),
    alt:t('Clavier Samsung partagé et texte saisi dans le composeur Codex.','Samsung split keyboard and text entered in the Codex composer.')}
};
const layers = {
  android:{label:'01 / ANDROID HOST', title:t('Android reste le point d’ancrage.','Android is the foundation.'),
    description:t('L’application FoldGPT possède son propre UID Android. Le service gère le runtime ; l’activité, l’affichage et la saisie s’adaptent à l’expérience mobile.','FoldGPT runs under its own Android UID. The service manages the runtime; the activity, display and input adapt to the mobile experience.'),
    path:'android/app/src/main/',link:'tree/main/android/app/src/main'},
  display:{label:'02 / LINUX DESKTOP',title:t('Un bureau Linux sur la puce du Fold.','A Linux desktop on the Fold’s chip.'),
    description:t('Debian et PRoot apportent la compatibilité Linux ARM64. Termux:X11 embarqué affiche le client desktop localement. Le client officiel est obtenu séparément ; l’adaptateur dépend de sa version.','Debian and PRoot provide Linux ARM64 compatibility. Embedded Termux:X11 displays the desktop client locally. The official client is acquired separately; the adapter is version-specific.'),
    path:'vendor/termux-x11/ + vendor/proot/',link:'tree/main/vendor'},
  tools:{label:'03 / NATIVE EXECUTOR',title:t('Des commandes. Des fichiers. Des résultats.','Commands. Files. Results.'),
    description:t('L’exécuteur fait le lien entre la conversation et les opérations locales sur le projet. Les outils utilisent le runtime adapté ; cette compatibilité n’équivaut pas à l’isolation complète d’un bureau Linux.','The executor connects conversations to local project operations. Tools use the adapted runtime; this compatibility does not provide full desktop Linux isolation.'),
    path:'tools/executor/',link:'tree/main/tools/executor'}
};
let selected = 'desktop';
const image = document.getElementById('capture-image');
const dialog = document.getElementById('capture-dialog');
const original = document.getElementById('dialog-image');
function selectCapture(key) {
  selected = key;
  const c = captures[key];
  image.src = '/foldgpt/assets/' + c.file;
  image.alt = c.alt;
  document.getElementById('capture-file').textContent = String(Object.keys(captures).indexOf(key) + 1).padStart(2,'0') + ' — ' + c.file;
  document.getElementById('capture-title').textContent = c.title;
  document.getElementById('capture-description').textContent = c.description;
  document.getElementById('capture-source').href = image.src;
  document.querySelectorAll('[data-capture]').forEach(b => b.setAttribute('aria-pressed',String(b.dataset.capture === key)));
  if (!matchMedia('(prefers-reduced-motion: reduce)').matches) image.animate([{opacity:.25},{opacity:1}],{duration:260});
}
document.querySelectorAll('[data-capture]').forEach(b=>b.addEventListener('click',()=>selectCapture(b.dataset.capture)));
document.getElementById('capture-zoom').addEventListener('click',()=>{
  original.src=image.src; original.alt=image.alt;
  document.getElementById('dialog-title').textContent=captures[selected].title;
  dialog.showModal();
});
document.getElementById('close-dialog').addEventListener('click',()=>dialog.close());
dialog.addEventListener('click',e=>{
  const b=dialog.getBoundingClientRect();
  if(e.clientX<b.left||e.clientX>b.right||e.clientY<b.top||e.clientY>b.bottom) dialog.close();
});
document.querySelectorAll('[data-layer]').forEach(b=>b.addEventListener('click',()=>{
  const l=layers[b.dataset.layer];
  document.querySelectorAll('[data-layer]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));
  for (const [id,val] of Object.entries({label:l.label,title:l.title,description:l.description,path:l.path})) document.getElementById('layer-'+id).textContent=val;
  document.getElementById('layer-source').href='https://github.com/pironjulien/FoldGPT/'+l.link;
}));
selectCapture('desktop');
