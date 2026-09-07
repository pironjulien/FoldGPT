# Préparation native séparée après l'échec V10

Le V10 reste une qualification échouée, avec propriétaire retenu. V11 est
désormais compilé, installé et son runtime est vérifié. L'autorisation
Shizuku est en attente derrière le verrouillage du Fold. Aucune tentative
native V11 n'est réservée ni lancée ; les commandes ordinaires restent à valider.

## Pourquoi conserver V10

La revue du code extrait de l'APK figé
`46049fd8d2f381c2680023c12005a4d57cf4c9a51c829a447eb88642e6b3a6a4`
confirme que l'erreur `factory_construct` intervient avant le lancement d'une
commande. `NativeExecutorBackend.__init__` ferme le descripteur du workspace
si la construction de `Processes` échoue ; la façade ferme celui d'evidence.
Le lancement réel passe par `_start` et `_run`, après construction et RPC.
Le relevé des descripteurs du bootstrap corrobore cette analyse.

Cela ne crée pas une sortie de quarantaine : le bootstrap V10 attend un
événement sans déclencheur, et `SessionState` conserve son résultat terminal
négatif. Son protocole n'offre aucune récupération normale. Le marker contient
PID, UID et identité du workspace, mais aucun boot ID ni starttime ; il ne
suffit donc pas à identifier un processus contre une réutilisation de PID.

Aucun `kill`, effacement de marker, remplacement du runtime ou réinstallation
du paquet V10 n'est effectué pour transformer cet échec en succès.
Une récupération externe exigerait une identité stable et un véritable reaping
par son parent ; elle resterait distincte d'une clôture propre du protocole.

## Correctif du client bloqué au démarrage

Avant `ready`, aucun lecteur RPC n'a été lancé. Après avoir publié la
quarantaine, le bootstrap courant ferme ses seuls FD0/1. Le client reçoit
EOF/EPIPE et peut lire le vrai statut ; FD2/3, propriétaire, backend, verrou et
marker restent conservés. Aucune preuve de nettoyage n'est ajoutée.

Le test réel sous UID ordinaire passe pour cinq erreurs de configuration ou de
construction, dont un vrai EACCES sur un fichier privé sans droit de lecture.
Il vérifie EOF, refus d'une nouvelle écriture, propriétaire vivant et verrou
toujours exclusif. Les parcours de fermeture propre et de nettoyage échoué
passent aussi. Une revue indépendante a forcé le premier initialize après EOF,
validant l'autre ordonnancement de la course d'écriture.
Preuves : `downloads/native-kernel-trial/pc-v11-startup-eof`.

## Séparation prévue

Le nouveau profil utilise `app.foldgpt.kernelqualification.v11`, une autre
identité de service Shizuku, des rapports propres et la base
`/data/local/tmp/foldgpt-bionic-supervisor-qualification-v3`.
La CLI Python est recompilée avec ce nouveau préfixe ; modifier le seul nom du
paquet ne suffirait pas. Le build correspondant est conservé dans
`downloads/native-kernel-trial/python-cli-v11` et n'a pas encore été exécuté
sur le téléphone au moment de cette préparation.

Les deux UserServices restent UID2000. Cette séparation de fichiers n'est pas
une séparation de droits Unix : le quota natif `RLIMIT_NPROC` compte les autres
threads du même UID. Le propriétaire V10 retenu entre dans cette base.

Le snapshot indépendant `before-v11-preparation` conserve le boot
`348d453e-f4e5-40e0-8ef0-030f4d5e38af`, warranty0, verifiedbootgreen,
flashlocked1 et SELinuxEnforcing. Il ne traverse pas le workspace V10.
Ces observations ne qualifient ni `/proc/TID/mem` ni `pidfd_getfd` sur Android.

## Résultats du build et de l'installation

Le résolveur Python ouvre l'objet final par `openat2(O_PATH)` et vérifie son
nom physique via `/proc/self/fd`, ses identités d'inode et les noms lexical et
physique. Les alias magiques, objets supprimés, noms ambigus et changements de
cible détectés sont refusés. Les exclusions du workspace et les refus explicites
de la politique sont conservés. Le superviseur C applique la même approche
pour les accès runtime avec et sans suivi du dernier lien.

Le build figé `foldgpt-bionic-supervisor-KvSGBnzP` passe 16 tests Python de
résolution, les tests C, deux scénarios noyau et la qualification main/pthread
sous UID65534. La suite factory passe 17 tests ; deux tests du shim cwd sont
ignorés car ce shim optionnel n'a pas été fourni. Le nouveau superviseur Android
vaut `879caa311b5a672a067514b50c5ffd37e9c06d66cafc7a30ff8acea0787d7c47`.
La revue indépendante n'a relevé aucun blocage. Ces essais Linux ne reproduisent
pas SELinux Samsung. Six tests réels supplémentaires de la façade passent.

La première compilation Gradle rencontre un doublon des deux bibliothèques JNI
dans le merger. L'inspection des source sets confirme un seul répertoire JNI
figé, mais deux racines Gradle utilisaient le même dossier de sorties du module
transport. Ses sorties sont maintenant sous le build de chaque racine, dans
`modules/<nom du projet>`. La reconstruction réussit sans suppression de cache
ni exclusion d'une bibliothèque. Les 24 tests JVM passent dans ce nouveau build.
Les deux journaux et l'inspection sont conservés dans `pc-v11-apk`.

APK figé : `tools/executor/shizuku-service/build/qualification-v11-independent/qualification-debug.apk`.
SHA256 : `1f8609c9a837d6923a464dda0a94153c874d6eaa5bda18cc7cf1d93245cdffd9`.
Certificat : `30930ffce7c10b673e95e69f2d78bb9e60aa71132db3c21cdc15cf56df77fa16`.
Le vérificateur contrôle le manifest fusionné, la signature, les 84 ELF,
les 24 sources Python et tous les assets contre le stage. Les sources du build
sont figées avec sa provenance ; `qualification-inputs-v11.json` épingle les
inventaires natifs et la CLI Python du nouveau préfixe.

L'installation utilise le nouveau UID client10399. La préparation vérifie
2 447 fichiers Python, 81 alias et 82 bibliothèques du déploiement, sans
démarrer l'interprète. `KERNEL_AUTHORIZE` ouvre la demande officielle Shizuku ;
le rapport reste `pending`, avec `showing=true` et `inputRestricted=true` pour
le verrouillage. Le répertoire broker V3 est vide et aucun `attempt-started`
n'existe dans les rapports V11. Il faut déverrouiller le Fold pour poursuivre
l'autorisation normale ; aucune identité ou permission n'est copiée de V10.

Preuves : `fixture-v11`, `python-v11`, `v11-awaiting-authorization`,
`pc-v11-facade`, `pc-v11-identity` sous `downloads/native-kernel-trial`.
Le snapshot après installation conserve le même boot et les indicateurs
d'intégrité, ainsi que les APK `app.foldgpt` et `app.foldgpt.shizukuprobe`.
L'ancien owner V10 n'a pas été arrêté ni remplacé.
