# Reprise technique du 7 septembre 2026

Le dépôt de travail est **privé** : `pironjulien/FoldGPT-workspace`, branche
`codex/foldgpt-beta`. Commencer par [README.md](README.md) pour restaurer sources,
sous-modules, moteur séparé et données locales. Le dépôt public `FoldGPT` est un
ancien checkpoint ; il ne reçoit pas cette sauvegarde privée.

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

## Suite concrète

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
