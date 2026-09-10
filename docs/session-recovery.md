# Reprise de session — r45, 9 septembre 2026

R45/versionCode35 conserve l'intention de démarrage dans
`runtime-user-intent.json`. Un arrêt explicite l'enregistre avant le nettoyage.
Android peut recréer le service interrompu avec `START_STICKY` uniquement si
l'utilisateur souhaitait conserver ChatGPT ouvert. Les reprises partagent le
délai de démarrage existant de 90 secondes, avec temporisation croissante.
Une session prête pendant 90 secondes remet ce budget à zéro. Aucun message,
outil ou callback OAuth n'est rejoué par FoldGPT.

Le lancement v3 porte les processus Java fournis par ActivityManager, leurs PID
et dates de création noyau. Le propriétaire natif revalide ces identités. Il
conserve le verrou exclusif pendant toute admission. En présence d'un marqueur
du même démarrage Android, il exige aussi le même workspace et l'absence de
processus de l'ancienne session avant d'archiver le marqueur original.

Une liste `/proc` vide ne suffit pas : l'échange 25 depuis l'exécuteur du
téléphone a montré un enfant non dumpable vivant mais invisible dans `/proc`.
La reprise complète donc le recensement par deux passages de `kill(pid, 0)` sur
tous les identifiants possibles du noyau Linux 64 bits. Ce signal nul ne tue
rien. Les threads des processus autorisés sont reconnus par leur appartenance
noyau `/proc/TGID/task/TID`, avec nouvelle vérification du processus principal.
Le fichier original est archivé avec son inode et une preuve qui conserve
`previousCleanupClaimed: false` et `previousBootEnded: false`.

## Vérifications effectuées

- 42 tests du transport Java, dont 7 sur l'époque et la population Android.
- 50 tests JVM de cycle de vie, dont 19 sur les reprises et l'arrêt explicite.
- 40 tests Python existants et 7 nouveaux essais de crash, verrou, survivant,
  remplacement du workspace, identité PID et threads, en UID Linux ordinaire.
- Compilation de l'application, inventaire APK et provenance de 99 modules
  Python vérifiés. Les 89 fichiers natifs du paquet sélectionné sont identiques
  à la base précédente ; le client officiel et le plugin Android sont inchangés.
- Premier essai téléphone : crash de la VM du service, nouvelle autorité native
  prête après 9,6 secondes. Le marqueur avait disparu avant la reprise : ce seul
  essai ne qualifiait pas la récupération d'un marqueur orphelin.
- Deuxième essai : une instrumentation séparée, sous l'UID ordinaire 10412,
  envoie SIGKILL au propriétaire natif puis au service Java. Le client devient
  prêt après **18 286 ms**, sans nouveau Start ni réparation d'un fichier.
  Le marqueur est retrouvé avec les mêmes octets et le même inode dans
  `recovered-same-boot-87d2667e10d3267a3229b4ed529ce0c1`. La preuve porte
  deux passages complets et 49 identifiants de threads autorisés.
  L'APK d'instrumentation est ensuite désinstallée. Sa terminaison arrête le
  processus cible ; une ouverture normale de FoldGPT a également réussi ensuite.
- Arrêt explicite : après 122 secondes, le propriétaire reste `closed`,
  l'intention persistée est `wanted: false`, seul le processus de l'interface
  demeure et aucune notification FoldGPT n'est présente. L'ouverture normale
  suivante retrouve la conversation. Preuve : `r45-stop-confirmed.json` dans
  `work/dependencies-fix-20260909`.

Preuve principale : `work/android-extension-20260909/r45-hard-crash.json`.
Autres traces : `r45-crash-1/`, `r45-recovery-tests.log`,
`r45-transport-tests.json`, `r45-apk-verification.json`, et
`work/runtime-recovery-20260909/android-policy-final/report.json`.
Le lancement global des tests Gradle Windows reste bloqué par le test HTTPS
préexistant `TrustedHttpsArtifactTest` (`com.sun.net.httpserver` absent de son
classpath Android). Les suites JVM dédiées et la compilation de production
passent ; cette limite n'est pas présentée comme une suite globale réussie.

## Portée

Un propriétaire encore vivant ou en quarantaine conserve ses protections. Un
timeout ne certifie jamais son nettoyage. La panne du seul broker avec des
descendants survivants n'est donc pas assimilée à la disparition complète
testée ici. L'arrêt forcé demandé à Android reste un arrêt volontaire au niveau
système, qui peut exiger une nouvelle ouverture de l'application.

Cette reprise ne prouve ni l'absence de futurs arrêts Android, ni la stabilité
prolongée en veille/pliage, ni la compatibilité universelle des plugins. Aucun
réglage du noyau, root, bootloader, Knox, SELinux ou permission SMS n'a changé.
Les 355 fichiers de projet et le préfixe d'historique de 16 402 254 octets sont
contrôlés par `pre-r45`.

Pour reconstruire après une modification Python, régénérer un nouveau paquet
avec `work/android-extension-20260909/stage-executor.py --release rNN`, puis
le sélectionner explicitement dans `build.py --executor-package ...`.
La commande de construction courante utilise désormais `executor-r45`.
