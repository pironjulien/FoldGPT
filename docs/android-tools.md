# Outils Android FoldGPT

Le plugin Android relie l'espace de travail Linux à des fonctions du téléphone
sous les permissions Android normales. Ce document décrit son intégration et
conserve les observations bornées du 9 septembre 2026. Pour le périmètre produit,
consulter la [matrice de compatibilité](compatibility.md).

Un contrôle global des applications complète des outils spécialisés, en
commençant par les SMS. Les envois exigent une demande explicite de l'utilisateur
avec le destinataire et le contenu voulu.

Le plugin `plugins/foldgpt-android` est propre à FoldGPT. Le client officiel Linux
n'inclut pas encore le Computer Use natif macOS/Windows ; le navigateur `iab`
reste indépendant et a été revalidé par la conversation du téléphone.
Référence officielle lue :
https://learn.chatgpt.com/docs/linux/linux-app#compatibility-and-limitations

## Capacités implémentées

- Contrôle global : applications lançables, arbre d'accessibilité, capture PNG,
  clic, saisie de texte, défilement, gestes, retour/accueil/applications récentes.
  Le contrôle visuel reprend le cycle des versions PC : observer, agir, vérifier.
  La surface Linux visible reçoit texte et accords clavier via son entrée X11
  existante ; les champs Android utilisent leurs actions d'accessibilité.
  Les coordonnées sont en pixels de l'affichage ; les captures indiquent aussi
  leur échelle. Chaque action exige une observation récente. Une acceptation
  Android ne constitue pas la vérification du résultat attendu.
- SMS : recherche littérale par texte, numéro exact, conversation et dates ;
  lecture paginée sans modifier l'état lu ; brouillon immuable ; envoi sur
  demande explicite et suivi par les callbacks téléphonie. Jamais d'envoi de test.
  Un résultat `submitted` n'est pas `sent`, et `sent` n'est pas `delivered`.
  Les doublons de draftId sont refusés et aucun résultat incertain n'est rejoué.
- Google Messages reste l'application SMS par défaut. Le fournisseur SMS peut
  contenir des SMS archivés, mais ne fournit ni leur appartenance aux archives,
  ni tout le RCS, ni le rangement. Ces fonctions nécessitent son interface.
  Un résultat vide dans le fournisseur SMS ne prouve pas l'absence du message.

## Accès et limites

L'écran **Outils Android** est disponible dans le raccourci du lanceur FoldGPT.
Il n'y a plus d'interrupteur FoldGPT supplémentaire. Le service d'accessibilité
nécessite l'activation Android ; READ_SMS/SEND_SMS nécessitent les permissions
correspondantes. `android_request_access` présente le consentement système pour
la seule fonction demandée et retourne immédiatement. Il ne l'accorde pas,
ne relance pas automatiquement l'action et ne boucle pas après un refus.
Une fois l'accès accordé, recherches/lectures demandées et brouillons s'utilisent
depuis la conversation ; aucune confirmation redondante n'est imposée. La
permission d'envoi n'est demandée que pour un envoi explicitement souhaité.
L'installation seule ne les accorde pas.
L'application ne demande pas le rôle de gestionnaire SMS. Aucun root Android,
bootloader, firmware, Knox, SELinux ou mécanisme de sécurité n'est modifié.

Le transport est un socket Unix abstrait `foldgpt-android-<UID>` ; le client et
le serveur vérifient leurs identités noyau. Même UID n'isole pas le modèle des
autres processus invités. Les corps des messages/images ne sont pas journalisés
par le transport, mais une lecture par le modèle figure dans sa conversation et
est transmise au service du modèle distant. Les instructions du plugin limitent
la lecture à la demande utile, jamais un export général de la boîte SMS.

La lecture/action exige le téléphone déverrouillé et interactif. Les contrôles
du système/permissions et l'écran d'accès FoldGPT ne sont pas modifiables par
le plugin. Les champs déclarés mots de passe sont masqués et leur saisie refusée.
Les écrans sécurisés restent protégés. Une application qui ne déclare pas
correctement ses champs secrets ne peut pas bénéficier d'une garantie absolue
de masquage. L'arbre Android ne décrit pas les champs internes Linux : les
outils de saisie Linux ne doivent pas servir aux mots de passe/secrets. La
capture porte actuellement sur l'affichage Android par défaut
et l'accès au contenu de la fenêtre active. Ni la saisie Linux par gestes ni
chaque application tierce n'est certifiée par la compilation.

Les brouillons et états d'envoi sont conservés en mémoire, au maximum 24 heures.
Après perte du processus, leur état est inconnu et le token ne doit jamais être
reconstruit pour renvoyer. Préparation valable 30 minutes. Le plugin ne peut pas
s'autoaccorder ses permissions. Les observations sur le téléphone de développement
ne valent pas consentement sur une autre installation : chaque utilisateur garde
le contrôle de ses accès Android.

## Navigateur et connexions

`xdg-open` HTTP(S) ouvre le navigateur Android choisi par le système ; il ne
fournit pas l'automatisation desktop Chrome ni le partage de cookies/mots de passe
Android dans l'iab. Le coffre GNOME déverrouillé par Android Keystore concerne
le client Linux, pas Google Password Manager/Samsung Pass.

Le callback officiel de connecteur `codex://connector/oauth_callback` est reçu
par FoldActivity, borné et transmis en argument au client existant. Ses contrôles
OAuth restent ceux du client officiel. Les erreurs sont explicites, les secrets
ne sont pas journalisés et une exécution incertaine n'est pas réessayée.
Une fixture de transport ne certifie pas la connexion à un service réel.

## Validation sur le téléphone, 9 septembre 2026

### État r41/versionCode31

R41 est installé et son APK relu sur le téléphone correspond au build. SHA256 :
`669224ac498f2b6ccc85ba9db8693e8c7f8e8cfd7afd36142cfe36883606a357`.
Le manifeste binaire indique `app.foldgpt`, versionCode31 et targetSdk37.
La source d'accessibilité correspond au rapport des neuf tests sémantiques
réussis ; les empreintes APK/source ont été revérifiées indépendamment dans
`work/android-extension-20260909/r41-source-report-consistency.json`.

Les événements `TYPE_WINDOW_CONTENT_CHANGED` ne détruisent plus à eux seuls
un instantané. Avant une action ou la restitution d'une capture, une nouvelle
lecture bornée compare les identités Android, la hiérarchie, le contenu, les
bounds, les actions et les indicateurs de mot de passe. Tout changement ou
contrôle incomplet impose une nouvelle observation. Les événements de clic et
les actions émises invalident toujours les anciens identifiants. La validation
ne renouvelle pas la durée initiale de 30 secondes et conserve les contrôles de
fenêtre, d'affichage et de rotation. Les valeurs des mots de passe restent
illisibles ; seule leur déclaration et leur zone de masquage sont contrôlées.
L'échange 22 de « Analyser le logiciel » exécute avec les vrais outils MCP
le calcul **7 + 8 = 15**, vérifie le résultat dans l'arbre puis sur la capture,
constate le refus d'un ancien identifiant et vérifie le retour à FoldGPT.
Deux refus avant action demandent une réobservation ; aucune action acceptée
n'est rejouée. Preuves : `work/android-extension-20260909/r41-phone-calculator.json`
et `r41-phone-calculator-0.png`. Le propriétaire reste `ready`, les 355 fichiers
de projets et le préfixe d'historique restent intacts ; 32 processus sous l'UID
au relevé de fin. Ceci ne résout pas la pression des processus Android.

Un geste de 100 ms atteint réellement le champ de la page locale d'essai dans
le navigateur Linux. `TouchInputHandler` accepte désormais aussi les événements
touchscreen de type UNKNOWN, émis par le service d'accessibilité. En revanche,
la saisie de « FoldGPT contrôle écran 123 » y perd le « é » malgré un transport
complet. Le focus réel et le texte final sont contrôlés par le document d'essai.
Preuve négative conservée : `work/android-extension-20260909/r41-linux-input.json`.
Un geste reçu ne suffit donc pas à qualifier la saisie Linux.

### R42 installé : saisie du composeur vérifiée, défaut navigateur reproduit

Le chemin Unicode modifiait la table XKB et envoyait ses notifications depuis
le thread d'entrée, en concurrence avec les requêtes des clients X11. Le correctif
fait traiter la socket Lorie par le répartiteur du serveur X (`SetNotifyFd`),
conservant l'ordre des événements et les contrôles natifs de saturation, sans
ajouter de délai arbitraire. Les journaux de symboles clavier sont supprimés.
La compilation native (535 étapes), 25 tests de transport et la construction
de l'APK passent. L'APK r42 contient exactement le nouveau natif vérifié :
SHA256 APK `16fdf6892abe6ea5054d24fb8c0243ab1e54bbdc90fbd3dd578eb0cf9bd18d2f`,
SHA256 X11 `60756957af83e93cc98e2adb92ff1300aa4c26f336eea249702ff98e0a1a9bef`.
R42 est installé et relu sur le téléphone. L'échange 23 de « Analyser le logiciel »
emploie ses vrais MCP pour cliquer dans le composeur initialement vide, saisir
« Contrôle prêt : à ç ù œ É », contrôler la capture puis sélectionner et effacer
ce seul brouillon. Les captures `r42-phone-input-2.png` et `r42-phone-input-4.png`
confirment le texte et le retour au champ vide ; aucun message de test envoyé.
Les sorties sont conservées dans `work/android-extension-20260909/r42-phone-input.json`.

Le champ de test du navigateur intégré reçoit en revanche
« FoldGPT contrôle cran 123  été Noël, Ω 中 🙂 » pour
« FoldGPT contrôle écran 123 — été Noël, Ω 中 🙂 » : premier é et tiret cadratin
absents malgré 44 trames acceptées. Le document a le focus réel après clic ;
les événements clavier sont enregistrés dans `r42-linux-input.json`. Le déplacement
sur le thread serveur ne suffit donc pas à corriger ce défaut.

À la reprise, tous les processus FoldGPT avaient disparu sans reboot Android,
avec un marqueur persistant encore `ready`. La récupération existante a archivé
le marqueur après deux recensements vides de l'UID et prise exclusive du verrou
natif (`r41-absence-owner-recovery`). Les 355 fichiers et le préfixe d'historique
sont préservés. La cause de cette disparition n'est pas établie ; la récupération
ne constitue pas une correction du redémarrage autonome après arrêt brutal.
L'accessibilité a été réactivée par les paramètres Android ordinaires suivant
l'autorisation déjà donnée ; READ_SMS et SEND_SMS restent non accordées.

### R43 : transport corrigé, cache clavier du navigateur encore périmé

R43/versionCode33 a été installé et relu : APK
`206d0841ec7f76717f9461743fe08e637ce495b09b659034f0018921a82e51ff`,
natif `e5ab5ad0df7c938bccc9c7ba776fba4a382c9e727542503b20d85edf5cc4a3d3`.
Le lecteur serveur conserve les fragments et valide une trame complète avant
dispatch, sans lecture bloquante ; les actions et les marqueurs sync respectent
l'ordre du flux. Un verrou par connexion sérialise les producteurs Android/GPU,
y compris corps variables et SCM_RIGHTS. La voie checked conserve trylock et
MSG_DONTWAIT. Le corps clipboard retour utilise exactement sa longueur annoncée,
avec une allocation heap bornée ; aucun contenu clipboard n'est journalisé.
Cette lecture retour et les écritures legacy restent synchrones : les gros
transferts simultanés dans les deux sens ne sont pas qualifiés.

Les suites hôtes ASan/UBSan testent fragmentation, EOF, possession et rejet des
descripteurs, 1 280 trames concurrentes, contention checked, reconnexion,
ordre réel du dispatcher et durée de vie des mappings XKB. La compilation NDK29
et les contrôles APK/JNI/alignement16K passent. L'allocation du lecteur utilise
libc et placement new comme l'activité existante, sans ajouter de runtime C++.

Le premier essai navigateur après redémarrage perd néanmoins le « ë » de
« Noël » (`r43-linux-input.json`), avec 44 trames reçues. Les nouveaux symboles
produisent des événements DOM `key=U+0000`, même lorsqu'un texte est inséré.
La mise en cohérence des tables master/source n'a donc pas suffi.

Cause supplémentaire retrouvée : `InitializeXkb` de Chromium souscrit seulement
`NewKeyboardNotify`, avec `affectMap=0xff` mais sans `MapNotify` dans affectWhich.
Dans ce serveur XKB, cela laisse `mapNotifyMask` à zéro et supprime aussi les
MappingNotify core. Le cache Chromium reste ancien ; la connexion Xlib de saisie
est distincte et souscrit aux modifications détaillées. Les sources consultées :
[abonnement Chromium](https://chromium.googlesource.com/chromium/src/+/main/ui/events/platform/x11/x11_event_source.cc),
[conversion synchrone XKB](https://chromium.googlesource.com/chromium/src/+/main/ui/gfx/x/keyboard_state.cc),
[rechargement avant dispatch](https://chromium.googlesource.com/chromium/src/+/main/ui/gfx/x/connection.cc),
et les fichiers locaux `xserver/xkb/xkbEvents.c` et `libx11/src/xkb/XKBBind.c`.
R44 publie la nouvelle description du clavier virtuel lors de l'ajout/recyclage
d'une touche logique, avec identifiants et bornes réels. Les deux tables sont
cohérentes avant notification et avant frappe ; aucune temporisation ou répétition
n'est ajoutée. Les symboles déjà présents ne provoquent pas de remplacement.
R44/versionCode34 est installé et relu : APK
`ed9d1a68d63ebd33f53ead3cf3842c001b30229fd769107b28ed447cf28b69f9`,
natif `6955e9b377263a6f28b133a2f803c7b9b9086394ed581641960157871ee62e63`,
provenant du build `downloads/gpu/x11/build-AfibPN40/artifact`.

Le premier essai après redémarrage reçoit exactement
« FoldGPT contrôle écran 123 — été Noël, Ω 中 🙂 » dans le vrai champ du
navigateur, après clic et vérification du focus. Les événements DOM reconnaissent
notamment ô, é, ë, —, Ω et 中 ; l'emoji passe par la composition normale. Preuve :
`work/android-extension-20260909/r44-linux-input.json`. L'onglet Example Domain
est restauré après le test.

Le composeur reçoit ensuite 4 096 caractères exacts en 21,53 secondes, avec
statut interrogé en moins de 28 ms. L'annulation laisse un préfixe de 40 caractères
qui ne continue pas à grandir. Le champ initialement vide est restauré vide,
sans soumettre de message (`r44-linux-composer.json`). Le premier lancement du
script composeur avait refusé de taper car le WebContents navigateur gardait le
focus ; un vrai clic dans le composeur observé a permis le test. Ce refus protège
les autres champs, il ne prouve pas une perte de saisie.

L'échange 24 est terminé : les propres outils MCP de la conversation du téléphone
ont cliqué dans le composeur, saisi « Saisie vérifiée : æ ÿ Ж Œ € ✅ », puis
contrôlé la capture. CTRL+A et BACKSPACE ont effacé ce seul brouillon ; la capture
finale confirme le champ vide. Le modèle distingue bien l'acceptation X11 de la
vérification visuelle et n'a rencontré aucune difficulté dans cet essai.
Sorties et captures relues : `r44-phone-input.json`, `r44-phone-input-2.png` et
`r44-phone-input-4.png`. Aucun SMS consulté et onglet Example Domain préservé.

Dernier relevé `work/dependencies-fix-20260909/r44-final.json` : propriétaire
`ready`, 33 processus sous l'UID, conversation terminée, 355 fichiers et
préfixe de l'historique préservés (historique final 12 641 382 octets). La pression
des processus Android et la reprise autonome après un arrêt brutal restent
ouvertes. Ces essais ne qualifient pas tous les plugins ni tous les parcours UI.

### Résultats acquis sur r39

- Le composeur Linux initialement vide reçoit exactement le texte Unicode
  attendu puis 4 096 caractères, vérifiés dans le contenu réel du composeur.
  Cette dernière saisie prend 20,954 s ; le plus long appel de suivi mesuré
  prend 25,779 ms. L'annulation laisse un préfixe stable de 41 caractères,
  sans touche retenue signalée. Aucun message n'est soumis et le brouillon
  redevient vide. Preuve :
  `work/android-extension-20260909/r39-linux-composer.json`.
- Le chemin natif gère la saturation du socket sans bloquer le thread UI :
  une trame non acceptée reste à émettre, sans considérer le texte comme reçu.
  Les contrôles natifs sont distincts de la vérification du composeur ;
  `sent_to_x11` seul ne prouve toujours pas le résultat dans chaque application.
- L'affichage Android 0 et sa fenêtre active sont cohérents à 2 448 × 1 848
  pixels. La capture PNG rendue mesure 1 600 × 1 208 pixels et indique son
  échelle ; les métriques viennent du `WindowContext` de cet affichage.
  Preuve : `work/android-extension-20260909/r39-display-probe.json`.
- Après fermeture puis un vrai retour de focus lié au volet de notifications,
  le propriétaire reste `closed`, avec nettoyage complet, processus natif
  récolté et seul le processus d'affichage Android présent. Preuve :
  `work/dependencies-fix-20260909/r39-stays-stopped-after-real-focus.json`.

Ces résultats ne qualifient ni toutes les applications Android, ni toutes les
surfaces Linux. Le parcours calculatrice a ensuite réussi sur r41 ; la perte
d'un accent dans le navigateur Linux demeure à résoudre et à retester.

### Historique r38

R38/versionCode28 est installé avec le plugin `0.1.0+codex.20260909132129`.
Le client officiel redémarre sur l'écran intérieur et le propriétaire natif
est `ready` sous l'UID ordinaire. L'accès écran est actif et les deux permissions
SMS restent désactivées. Le transport natif X11 ne journalise plus les contenus
de saisie ; les entrées texte/clavier sont asynchrones, suivies par inputId et
annulables. `sent_to_x11` prouve le transport, pas le texte effectivement affiché.
Vingt-cinq tests natifs, vingt tests de lancement/arrêt, seize tests SMS/connexion
et huit tests de contexte passent. Les essais positifs d'écran sont en cours.

Un retour de focus après fermeture pouvait lancer une nouvelle session avant
l'installation suivante. R38 consomme une demande de lancement explicite une
seule fois ; les changements de focus/posture et la restauration de l'affichage
ne créent plus de demande de redémarrage. Le service expose une lecture de statut
sans lancement et conserve la réouverture volontaire pendant la fermeture.
Le marqueur laissé avant r38 a été archivé après arrêt Android de tout l'UID,
deux recensements vides et contrôle sous verrou natif exclusif. Ceci ne qualifie
pas la reprise automatique après une destruction brutale par Android.

APK r38 : `f5e93e4267a182d2218821ab5b6fedff74bd6303cc3cde710cd1c0000c53d72a`.
La fermeture après la correction et les saisies réelles restent à vérifier.

### Historique r36, avant l'accord utilisateur

R36/versionCode26 ajoute le consentement à la demande, supprime les doubles
interrupteurs et ajoute les entrées Linux `ui_type_text`/`ui_press_keys`. Chaque
entrée exige une observation fraîche de la surface Linux visible et invalide
ensuite l'observation. Les accords clavier relâchent toutes les touches. Les
observations et captures vérifient également la rotation, y compris à 180°.
La compilation et les vérifications de l'APK passent ; les actions avec accès
accordé ne sont pas encore qualifiées. Plugin `0.1.0+codex.20260909130358`.
L'échange 17 prouve l'exposition des outils clavier/texte et les erreurs Android
`permission_required` (READ_SMS) / `accessibility_not_connected`. L'échange 18
appelle réellement `android_request_access(screen_control)` ; l'Activity publique
des paramètres d'accessibilité Samsung est constatée au premier plan et sur une
capture indépendante. Le raccourci initial vers une fiche privée refusée par
Android a été supprimé. Aucun accès n'a été accordé ; aucun SMS lu ou envoyé.

L'APK final est identifié par SHA256
`cf485f30b6438b5c6492ece75546e0f88bf80c7fc01f2254351568079286f7ef`.
L'installation et les quatre fichiers du plugin dans son cache ont été
comparés aux sources locales. Huit tests de contexte et seize tests de callbacks
/ SMS passent. Les 355 fichiers de projets et le préfixe d'historique sont
préservés. Ces vérifications ne remplacent pas l'essai des actions autorisées.

Preuve précédente r35, conservée pour le défaut de chargement :

La révision `0.1.0+codex.20260909125234` est installée via le mécanisme personnel
standard du client. Le format natif `.codex-plugin/plugin.json` n'interpole pas
`${PLUGIN_ROOT}` dans les arguments MCP : `.mcp.json` fixe `cwd: "."`, que le
chargeur résout au dossier installé du plugin, et lance `scripts/server.py`.
Les versions précédentes échouaient au handshake car Python recevait une variable
littérale ; changer seulement son nom ne corrigeait pas le problème.

L'échange 16 dans la conversation du téléphone a découvert et appelé les vrais
outils MCP : `android_status` a répondu, avec les deux interrupteurs et les
permissions SMS désactivés, puis `android_ui_state` a refusé avec
`global_control_disabled` et `android_sms_search` avec `sms_disabled`. Aucun
contenu d'écran ou SMS n'a été lu par ces appels. Le panneau r35 avait encore
deux interrupteurs ; le panneau r36 a été revérifié visuellement sans ces
interrupteurs, avec les permissions SMS non autorisées.

Les plugins officiels sont conservés. Les skills de documents et leur moteur
de dépendances ARM64 ont leurs preuves distinctes dans `workspace-dependencies.md`.
Le présent plugin complète Android ; il ne remplace pas les connecteurs officiels
et ne garantit pas la compatibilité d'un MCP exigeant Windows/macOS ou un binaire
x64. Le panneau navigateur affiche encore une indisponibilité malgré un iab
fonctionnel ; Cloudflare demande encore une connexion. La pression des processus
a provoqué un arrêt Android pendant la séance et reste un défaut de fiabilité.
