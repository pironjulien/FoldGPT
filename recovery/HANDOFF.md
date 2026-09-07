# Reprise technique du 7 septembre 2026

Le dépôt de travail est **privé** : `pironjulien/FoldGPT-workspace`, branche
`codex/foldgpt-beta`. Commencer par [README.md](README.md) pour restaurer sources,
sous-modules, moteur séparé et données locales. Le dépôt public `FoldGPT` est un
ancien checkpoint ; il ne reçoit pas cette sauvegarde privée.

## État courant : canal natif et configuration entre deux UID prouvés sur PC

Le [canal privé](../tools/executor/native-bootstrap-channel.md) relie maintenant
le Rust du moteur à l'autorité Python/native. Les [preuves exactes](verification/native-bootstrap-channel-20260907/manifest.json)
conservent 17 tests Rust, 108 exécutions de régression Python/native et le
[rapport entre deux UID](verification/native-bootstrap-channel-20260907/isolation/report.json).
Le contrôleur UID1000 reçoit un vrai `PermissionDenied` en accès direct au
projet UID65534, puis lit les 70 000 octets attendus et la configuration projet
via le canal. Le vrai chargeur borné conserve la provenance `Project` et le
modèle attendu. Les refus restent des refus ; les deux processus terminent
avec code0, sans helper survivant ni quarantaine.

Le dernier export du moteur est un checkpoint de développement : le chargeur
public et le canal sont qualifiés, mais les suites complètes du ConfigBuilder,
les rôles, AGENTS et la sélection d'environnement sont encore en cours.
`ExecutorOnly` reste fermé. Aucune tâche complète depuis l'interface n'est
encore validée, et le canal n'est pas encore déployé sur Android.

Le moteur courant se trouve sous `C:\Dev\ChatgptFold\work\worktrees\FoldgptEngine`.
Les anciens chemins `C:\Dev\FoldgptEngine` dans les preuves sont historiques.
Le lien Git du worktree est relatif et vérifié sous Windows et WSL. Les logs
locaux sont sous `work/root-artifacts-20260907` ; le snapshot complet du canal
est sous `downloads/native-bootstrap-channel-20260907`.

## Acquis téléphone : projet Python natif V2 réussi, 7 septembre vers 21:07

Le [rapport V2](../docs/research/native-runtime-v2-device-result-2026-09-07.md)
et ses [preuves exactes](verification/native-runtime-v2-20260907/manifest.json)
conservent création/modification du projet, trois tests, zipapp construit et
exécuté, flux binaires, environnement enfant vide et refus réels. Les 20
contrôles indépendants passent. Nettoyage natif/JNI complet, propriétaires 2636
et 2676 absents ; boot/APK/fixture inchangés, aucun redémarrage pendant l'essai.

La correction RUNPATH fonctionne sur le Fold. Package
`app.foldgpt.runtimequalification.v2`, base
`/data/local/tmp/foldgpt-bionic-runtime-qualification-v2`, gel `qKM94iHA`.
APK vérifié : `downloads/runtime-qualification/apk-v2-independent/runtimequalification-debug.apk`,
SHA256 `8572ecc3ed975e6eb8dc98e1df5247931e5354aa6dd737f400c4e7c699674b2c`.
Action `.RUNTIME_RUN_FIXED_V2` consommée : ne pas rejouer ni effacer marker.

Poursuivre le raccordement des chemins/autorités et du lancement du moteur à
l'interface habituelle. Aucun succès ordinaire UI.
Le maintien éveillé USB reste activé durant la session active.

Les nouveaux binaires, stages et preuves sont également publiés dans le
complément privé v9 : 8 958 fichiers retéléchargés, authentifiés et vérifiés
après extraction. Voir [la procédure](README.md#complément-v9--python-natif-v2-réussi-sur-le-fold)
et [le rapport exact](verification/github-supplement-v9-restoration.json).

## Historique : Python runtime V1 échoue au chargement, 7 septembre vers 20:49

Le [rapport runtime V1](../docs/research/native-runtime-v1-device-result-2026-09-07.md)
et ses [preuves exactes](verification/native-runtime-v1-20260907/manifest.json)
conservent le test réel : Bash démarre, puis le chargement de `libpython3.14.so`
échoue. Nettoyage natif/JNI complet, propriétaires absents, boot/APK/fixture
inchangés. L'action V1 est consommée : ne pas la rejouer ni effacer son marker.

La correction candidate ajoute au RUNPATH le vrai préfixe des bibliothèques.
Le CLI V2 est compilé sous `downloads/runtime-qualification/python-cli-v2`,
SHA256 `b0709f801f95739b1a6988d51f22d8df1373316595ce19df8ce329d5c84628f2`.
La revue et le packaging V2 séparé sont en cours ; aucun résultat Android V2.
Le bootstrap app-server passe six nouveaux tests réels et29 régressions API sur
PC. Il est exporté dans le patch moteur. Les couches projet/autorités restent à
raccorder, et `ExecutorOnly` reste refusé jusqu'à leur preuve réelle.

Priorité inchangée : un projet Python créé et testé depuis l'interface habituelle.
Le maintien éveillé USB reste activé pendant la session de travail.

## Historique : V12 réussit sur le Fold, 7 septembre vers 19:49

La qualification fixe Shizuku/Bionic V12 réussit, avec les 24 vérifications
indépendantes, nettoyage réel et boot/APK/fixture inchangés. Lire le
[rapport V12](../docs/research/native-v12-device-result-2026-09-07.md) et les
[preuves suivies](verification/native-v12-20260907/manifest.json).
L'action V12 a été consommée : conserver son marker et ne pas la rejouer.

Le projet Python complet passe sur PC avec Bash natif, création/modification,
trois tests et zipapp. La prochaine identité séparée est
`app.foldgpt.runtimequalification.v1`, base
`/data/local/tmp/foldgpt-bionic-runtime-qualification-v1`. Avant son déploiement,
la course annulation/expiration du canal SOCK_SEQPACKET est maintenant corrigée
et vérifiée : six tests de synchronisation et cinq tests du projet passent sur
le nouveau gel `N0kMFS8z`, avec les contrôles canoniques. Conserver le build V12
`PHREPY0u` intact. La fixture runtime-v1 est créée et vérifiée sur le téléphone ;
son worker n'est pas encore lancé. Lire le
[contrat et les preuves PC](../tools/executor/bionic-supervisor/runtime_qualification.md).

L'incrément de métadonnées/shell du moteur passe 41 tests ciblés et une
intégration modèle/commande/apply-patch réelle sur PC. Le patch moteur exporté
inclut ce résultat. L'injection app-server interne est l'étape suivante ; les
accès `ExecutorOnly` restent refusés jusqu'à leur raccordement réel.

Les commandes ordinaires depuis l'interface ne sont pas encore démontrées.
Le moteur auxiliaire et ses accès projet/autorités restent à raccorder selon
l'audit du contrôleur. La priorité reste ce fonctionnement, finitions suspendues.

## Historique : résultat V11, 7 septembre vers 19:03

Priorité confirmée par Julien vers 19:36 : démontrer le fonctionnement réel
du petit projet Python depuis l'interface avant toute finition. L'enquête sur
les points noirs est suspendue : corruption capturée aujourd'hui malgré les
bibliothèques foldgpt5 effectivement mappées. Aucun correctif GPU nouveau ni
changement de pilote n'a été appliqué. Les captures privées et mesures sont
dans `downloads/menu-points-20260907`; les nouvelles sondes sous `tools/gpu`
sont des préparations non validées sur l'appareil, pas une résolution.

Julien a repris le travail et reconnecté le Fold. Le maintien éveillé USB est
activé et vérifié sans entrée injectée ; conserver ce réglage pendant la session
active et rétablir sa valeur initiale0 à la fin, conformément au
[rapport courant](../docs/research/native-v11-device-result-2026-09-07.md).

L'autorisation Shizuku officielle et le préflight V11 passent. L'unique essai
natif a lancé son processus, qui échoue au démarrage Bionic avec le code127 :
`unable to stat either "/proc/self/exe" or "kernel-qualification"`.
**La qualification n'est pas réussie** et aucun nouveau lancement V11 n'est
admis. Le nettoyage natif et JNI est réel et complet, sans quarantaine V11.
Le boot, la fixture, les APK et les indicateurs d'intégrité restent inchangés.
Les preuves V10 restent conservées indépendamment. Lire le rapport et ses
[preuves exactes](verification/native-v11-20260907/manifest.json) avant la suite.

Le correctif des métadonnées de l'exécutable passe désormais sur PC dans le
build `foldgpt-bionic-supervisor-PHREPY0u`, avec comparaison au runner précédent
et au noyau réel, y compris depuis un pthread. Les sources et preuves sont
suivies dans Git. Aucun nouvel APK n'est empaqueté ni installé. La résolution
`realpath` Bionic et l'effet de son repli dans le chargeur restent à établir ;
ne pas considérer l'ajout d'`O_PATH` comme une correction, car l'injection de
ce type de FD est refusée par le noyau. Lire les limites du rapport courant.
Les mécanismes du worker et les commandes ordinaires restent à valider ;
ne pas réactiver l'ancien diagnostic GNU/PRoot.
La [comparaison statique ARM64](../docs/research/native-engine-arm64-library-compatibility-2026-09-07.md)
a également été terminée sur PC ; elle ne prouve pas le chargement Android.

## Historique de clôture à la demande de Julien, 7 septembre vers 07:16

Julien part au travail et a demandé d'arrêter les essais, de tout consigner et
de finaliser la sauvegarde pour reprendre sur l'autre PC. Aucun nouvel essai
sur le Fold ne doit être déduit de cette clôture. La session de nuit est close ;
**le projet et les commandes ordinaires depuis l'interface restent inachevés**.

Le moteur auxiliaire GNU ARM64 et son compagnon ont réellement compilé en
release, sortie 0, en 18 min 08 s. Le compagnon a exécuté `text(6 * 7)` donnant
42 sur PC, puis fermé la session et quitté avec 0. Lire le
[rapport du build ARM64](../docs/research/native-engine-arm64-build-2026-09-07.md)
pour l'état final des autres vérifications ; aucune exécution de ce moteur sur
le Fold n'est établie. Les sources du build et celles restaurées par Git ont
le même contenu, avec des différences de matérialisation Windows documentées.

Le dernier contrôle mémoire en lecture seule, à 07:00, mesure 10,83 Gio utilisables
par Android, 3,49 Gio disponibles à cet instant et 695,74 Mio PSS pour les 23
processus de l'UID FoldGPT. Voir le
[rapport mémoire](verification/android-memory-20260907.json) et ses limites.
Il ne démontre aucun plafond global de 2 Gio pour FoldGPT.

Des copies exactes de cinq bibliothèques GNU du téléphone ont été collectées
en lecture seule dans `downloads/engine-arm64-device-libs-20260907` pour une
future comparaison des exigences ELF. Cette comparaison n'a pas été effectuée
avant l'arrêt ; aucune bibliothèque ni commande GNU n'a été exécutée sur le
téléphone pour cette collecte.

Pour reprendre : restaurer le clone et les compléments avec `recovery/README.md`,
puis lire le point V11 ci-dessous et l'audit des accès du contrôleur. Le premier
verrou téléphone reste son déverrouillage normal et l'autorisation officielle
Shizuku. Préserver V10, les fixtures et toutes les preuves existantes.

La clôture est sauvegardée dans le complément privé v8 : 7 169 fichiers
retéléchargés, authentifiés et vérifiés après extraction. Les 27 éléments de
la release correspondent à leurs tailles et empreintes. Les sources et cette
reprise sont sur la branche `codex/foldgpt-beta`. Le build ARM64 et ses entrées
exactes sont sous `downloads/engine-gnu-arm64-20260907` après restauration.

## Historique avant reprise : V11 attendait l'autorisation Shizuku

Le correctif des chemins runtime passe sur PC ; le superviseur figé courant
est `foldgpt-bionic-supervisor-KvSGBnzP`. L'APK séparé
`app.foldgpt.kernelqualification.v11` est installé, son runtime V3 vérifié et
la demande officielle Shizuku attend derrière le verrouillage du Fold.
**Aucune commande native V11 n'est lancée.** Le V10 reste intact en quarantaine.

Lire le [résultat V11](../docs/research/native-v11-isolated-preparation-2026-09-07.md)
et le [plan de fixture indépendante](../docs/research/native-independent-fixture-plan-2026-09-07.md).
Après déverrouillage et autorisation normale, contrôler `authorization.json`,
puis exécuter le préflight V11 avant l'unique action `KERNEL_RUN_FIXED_V11`.
Utiliser explicitement package V11, base
`/data/local/tmp/foldgpt-bionic-supervisor-qualification-v3` et report-version11.
Ne pas utiliser les commandes historiques V2 ci-dessous pour ce nouvel essai.

APK : `tools/executor/shizuku-service/build/qualification-v11-independent/qualification-debug.apk`.
SHA256 `1f8609c9a837d6923a464dda0a94153c874d6eaa5bda18cc7cf1d93245cdffd9`.
Stage : `tools/executor/shizuku-service/build/qualification-stage-v11`.
Les journaux `pc-v11-*`, `fixture-v11`, `python-v11` et
`v11-awaiting-authorization` sont dans `downloads/native-kernel-trial`.

## Résultats réellement obtenus

- Sur le Fold, l'essai fixe Shizuku/Bionic a créé et modifié un projet Python,
  passé trois tests et construit/exécuté un zipapp donnant 42. Les flux, refus,
  nettoyage et identité du runtime sont vérifiés indépendamment. Voir le
  [rapport téléphone](../docs/research/shizuku-bionic-trial-2026-09-07.md).
- Les commandes ordinaires depuis l'interface ne sont **pas encore reliées** à
  cet exécuteur. L'ancien chemin peut donc encore afficher l'erreur Bubblewrap.
- Le transport Shizuku est inclus dans notre APK, avec un point de préparation
  explicite et inactif, des entrées d'APK contrôlées et une terminaison qui
  conserve les propriétaires tant que le nettoyage n'est pas établi.
- Le shim Bionic `chdir` est compilé, testé sur PC et empaqueté dans l'APK.
  L'APK `c9a83886ebdfeba7f28ecbc37a383252cc91ad6e5c3ad3dc7189cc81e35694a1`
  est signé avec l'identité existante et **n'a pas été installé** sur le Fold.
- Le superviseur natif corrigé `8Kd8xQRE` passe 19 tests de processus réels,
  deux tests noyau directs et une qualification main/pthread sur PC nonroot.
  Sa lecture de dossiers par threads et son attente du superviseur ont été
  corrigées après revue indépendante. Les anciens builds ZBbervqT/UwX0Qj9H
  précèdent ces corrections et ne doivent pas servir au prochain essai.
- Le moteur séparé possède une injection d'environnement véritablement local et
  un flux de processus borné utilisable depuis un backend externe. Les tests
  ciblés passent avec vrais processus et octets. Trois échecs de la suite large
  sont également reproduits sur la base amont intacte : aucune suite complète
  verte n'est revendiquée. Voir `FOLDGPT-INTEGRATION.md` après restauration.
- Le nouveau `ExecServerLocalRuntime` a ensuite relié le client Rust au vrai
  serveur Python et au superviseur C `8Kd8xQRE` sur PC : commandes, cwd/env,
  stdin binaire, stdout/stderr/EOF, exit 23, opérations fichiers et refus avant
  mutation passent. Une coupure ferme l'admission sans rejeu ni faux événement
  de terminaison ; le nettoyage est constaté séparément côté natif. Les 27
  régressions ciblées et Clippy passent. Les [preuves de ce test réel](verification/engine-native-runtime/tests.txt)
  sont conservées dans Git. Cela ne sélectionne aucun exécuteur sur Android.

## Historique V10 et dépendances de l'intégration

**État V10 conservé, distinct du V11 courant décrit en tête.** Le démarrage
stdio dépasse le refus de socket. Le statut authentifié du service PID11821
confirme `factory_construct`, `PermissionError`, errno13, refus de
`/linkerconfig`. Le bootstrap PID11978 reste vivant ; son nettoyage n'est pas
établi. `evidence.json` est vide, `broker/process-session.json` et
`files/kernel-v6/attempt-started` restent en place. Ne pas réinstaller, tuer
l'ancien propriétaire, effacer le marqueur ou rejouer cette fixture.

L'APK figé est `tools/executor/shizuku-lab/build/kernel-v10-stdio/app-debug.apk`,
SHA-256 `46049fd8d2f381c2680023c12005a4d57cf4c9a51c829a447eb88642e6b3a6a4`.
Le stage est `kernel-stage-v10`. Lire le
[rapport v10 et la prochaine correction](../docs/research/native-v10-retained-session-2026-09-07.md).
La vérification des chemins runtime a depuis été corrigée et préparée dans V11,
sans retirer le contrôle du chevauchement avec le workspace. Les mécanismes
noyau du worker restent non mesurés. Les étapes v6 à v9 ci-dessous sont
historiques et ne doivent pas être rejouées après la quarantaine v10.

1. Le laboratoire autorisé `app.foldgpt.shizukuprobe` est passé au v9. V6 a
   réellement lancé le bootstrap UID2000, sorti70 avant `ready` et avant le
   worker, avec attente JNI et nettoyage complets. Les rapports de refus v7/v8
   ont été produits automatiquement lors des mises à jour, par restauration
   de l'ancien Intent **avant le restaging des alias**. Ils ne prouvent pas de
   nouveaux essais explicites après ce restaging. Les dates conservées dans
   `downloads/native-kernel-trial/lab-v8-inspection/report-times.txt` établissent
   cette distinction. Le préflight v8 après restaging passe ; son premier refus
   identifiait un alias Python pointant vers l'ancien APK.
   V9 refuse réellement l'ancien `KERNEL_RUN_FIXED` restauré, sans créer
   `attempt-started` : voir `lab-v9-inspection/inherited-intent-refusal.json`
   et `inherited-intent-directory.txt` sous le même dossier de preuves.
   Son préflight passe également, sans lancement natif. Seule l'action explicite
   `KERNEL_RUN_FIXED_V9` peut réserver l'essai, dans `files/kernel-v5`, avec le
   service tag/version5. Cet essai explicite a ensuite réellement atteint le
   bootstrap : `broker_open` échoue avec `PermissionError`, errno13, sur le
   `bind()` AF_UNIX de `private_exec_broker.py:93`, avant tout worker. Le bootstrap
   a été attendu et nettoyé (`waitStatus=17920`, `bootstrapReaped` et
   `cleanupComplete` vrais, sans owner retenu ni quarantaine). La collecte
   `lab-v9-cleanup-inspection` constate PID9798 absent, broker.lock seul, fixture,
   boot, indicateurs et APK inchangés. Le collecteur reste `success:false` faute
   de preuve native. Résoudre ce refus de bind avant de qualifier le noyau.
   Conserver toutes les réservations et preuves v2/v3/v4/v5. Voir le
   [rapport actuel](../docs/research/native-kernel-qualification-2026-09-07.md)
   et la [procédure v9](../tools/executor/shizuku-lab/ADMISSION-DIAGNOSTIC.md).
   Recalculer les 81 alias contre le vrai `nativeLibraryDir` après chaque
   installation. Le libellé RPC `preflight_v4` est historique ; il ne désigne
   pas la version installée. Ne pas réutiliser l'Activity après un timeout :
   `finished` peut être fixé par le délai avant la fin du worker Java et ne
   constitue pas une preuve de fin des opérations ou du nettoyage natif.
2. Après résolution de ce démarrage, qualifier `/proc/TID/mem`, `pidfd_getfd` et les mêmes accès depuis un thread
   secondaire dans le **véritable UserService Shizuku**. La
   [qualification minimale](../tools/executor/bionic-supervisor/qualification.md)
   décrit la fixture vierge, l'unique requête, les empreintes, les résultats
   attendus et le nettoyage. Les preuves PC ne constituent pas des preuves
   Android et ne doivent pas être rebaptisées.
3. Relier au service Android la liaison moteur/ExecServer maintenant prouvée sur
   PC. Le transport doit conserver politiques, flux, erreurs et ownership. Le runtime reste
   local (`is_remote=false`) ; les chemins invisibles au contrôleur sont
   actuellement refusés avant les routes qui supposent encore un accès direct.
   L'[audit du contrôleur](../docs/research/native-executor-controller-path-audit-2026-09-07.md)
   détaille les routes encore directes, leurs autorités et les preuves nécessaires.
   Retirer le refus `ExecutorOnly` seul serait incorrect.
4. Compléter les opérations de fichiers/processus nécessaires. Le superviseur
   refuse encore notamment suppression/renommage/liens, exécution de fichiers
   compilés dans le projet, TTY et réseau. Les quotas actuels sont des limites
   de processus/UID, pas une limite mémoire agrégée d'un workspace.
5. Prouver depuis l'interface ordinaire une vraie demande de création, tests et
   construction du petit projet Python choisi par Julien. Cette preuve manque.

Le travail Rust peut continuer entre deux exports : vérifier le patch actuel
dans `recovery/engine/manifest.json`. Exporter et vérifier un nouveau point
stable avant de changer de PC ; ne pas remplacer les sources Git par leur
version plus ancienne dans l'archive.

## Contraintes conservées

- Aucun root, déverrouillage, changement de noyau/SELinux ou action Knox.
- Aucun retour à une VM sur le téléphone. WSL sert uniquement au build PC.
- Client officiel et ses fichiers conservés, mises à jour officielles normales.
- Aucun succès simulé, politique désactivée ou fonctionnalité omise présentée
  comme terminée ; MCP/plugin restent le dernier recours demandé par Julien.
- Ne pas relancer l'ancien diagnostic GNU/PRoot/ptrace/seccomp associé aux deux
  redémarrages inexpliqués. Les nouveaux essais utilisent des fixtures propres.
- Ne pas tuer un propriétaire encore nécessaire au nettoyage, effacer une
  quarantaine ou relancer automatiquement après un résultat de nettoyage inconnu.
- Le SDK Shizuku ne recrée pas les droits ADB après un reboot. Le démarrage
  automatique modifiant la durée de confiance ADB n'a pas été activé.

Inspection archivée du téléphone, en lecture seule le 7 septembre vers 03:27 :
boot `348d453e-f4e5-40e0-8ef0-030f4d5e38af` inchangé, warranty bit 0,
verified boot green, flash locked 1, SELinux Enforcing. Mémoire totale visible
11 351 456 kB, disponible à cet instant 4 663 908 kB ; ce dernier chiffre varie.
Il n'existe pas de réservation générale de seulement 2 Gio pour une application
native démontrée par ces mesures. Ne pas assimiler RAM physique, mémoire
disponible, zram et plafonds du lanceur.

La protection des écrans est gérée par `tools/runtime/protect-idle-screens.ps1`.
L'exécuter avec `-ActivateNow` à la fin du travail ou lors d'un arrêt, conformément
à la demande de Julien. Le script remet aussi le Fold en veille d'affichage.
