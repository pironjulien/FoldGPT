# V11 sur le Fold : lancement atteint, échec du chargeur Bionic

Essai unique du 7 septembre 2026 à 17:02 UTC. **La qualification échoue** :
le processus de travail sort avec 127 avant de produire son résultat.
Les commandes ordinaires depuis FoldGPT restent à raccorder et à valider.

## Ce qui a réellement progressé

Après reconnexion, le serveur Shizuku était absent. Le lanceur officiel
`libshizuku.so` de son APK installé a démarré le serveur par ADB UID2000.
Le script historique `start.sh` n'existe pas dans cette installation 13.6.0 ;
le chemin utilisé correspond au `Starter.kt` officiel collecté.
La nouvelle Activity V11 a obtenu sa propre autorisation par le dialogue
officiel, sans copier celle du laboratoire V10. Le rapport frais indique
`authorized=true`, serveur UID2000, client UID10399 et aucune réservation,
liaison de UserService ni tentative native pendant l'autorisation seule.

Le préflight V11 passe, contrôle les chemins PackageManager et le runtime
figé. L'absence du marker et le broker vide sont vérifiés avant l'unique
`KERNEL_RUN_FIXED_V11`. Une attente de 35 secondes n'envoie aucune commande
ADB parallèle. Le bootstrap Bionic passe cette fois la construction du backend,
initialise le vrai RPC et lance le superviseur puis le processus de travail.

## Échec observé, sans extrapolation au noyau

Le stderr réel est :

```text
unable to stat either "/proc/self/exe" or "kernel-qualification": No such file or directory
libc: unable to stat either "/proc/self/exe" or "kernel-qualification": No such file or directory
```

`nativeResult` donne `started=true`, `outcome=exited`, `exitCode=127`,
`stdoutBytes=0`, `stderrBytes=190`, un accès accordé et quatre refus.
Le rapport indépendant conserve `success=false`. Son erreur de parsing JSON
provient du stdout vide ; le stderr ci-dessus est le diagnostic de lancement
à examiner. Aucun résultat du worker n'est déduit de ce parsing échoué.

Cela ne mesure toujours pas les opérations `/proc/TID/mem`, `pidfd_getfd`
et `PIDFD_THREAD` du worker. L'erreur ne prouve pas à elle seule un refus
SELinux : le superviseur applique également sa propre politique de fichiers.
La prochaine analyse porte sur l'identification de l'exécutable par Bionic
et sa représentation dans notre médiation. Aucun accès global à `/proc`,
aucune modification SELinux et aucun nouvel essai téléphone ne sont introduits
par ce résultat.

La revue statique indépendante retrouve un traitement spécial de
`/proc/self/exe` uniquement pour `readlink` dans `runner.c`, pas pour les
opérations `stat/newfstatat/statx`. Le chemin passe alors par la politique
générique, qui le refuse hors du workspace. Le repli `argv[0]` reste la clé
logique `kernel-qualification`, sans fichier correspondant. Cette lacune est
cohérente avec le diagnostic ; l'ordre exact des appels et leurs errno ne sont
pas enregistrés dans ce rapport. Une correction doit fournir les vraies
métadonnées de l'exécutable autorisé, avec descripteur et identité de tâche
vérifiés, tout en respectant les sémantiques de lien et les refus des autres
chemins `/proc`. Ce correctif est désormais vérifié sur PC comme décrit
ci-dessous ; aucune correction n'est encore qualifiée sur Android.

Le [source officiel Bionic consulté](https://android.googlesource.com/platform/bionic/+/refs/heads/main/linker/linker_main.cpp#214),
blob `425bcda67fe7f342222c02a74d3f13bb059825ac`, confirme aux lignes214–237
la séquence `stat("/proc/self/exe")`, repli sur `stat(argv[0])`, puis exactement
le message observé si les deux échouent. Les lignes326–327 appellent cette
fonction avec `args.argv[0]`. Le chargeur appelle ensuite `realpath` pour
choisir sa configuration ; cette étape doit aussi être examinée. Le source
amont consulté explique le diagnostic, sans prétendre être le source exact
du binaire Samsung installé.

Le [source officiel de `realpath`](https://android.googlesource.com/platform/bionic/+/refs/heads/main/libc/bionic/realpath.cpp#46),
blob `e43d8e2ff0702618e463eb02805e324bb3860446`, précise l'étape suivante :
ouvrir le chemin avec `O_PATH|O_CLOEXEC`, lire ses métadonnées via le FD,
résoudre ce FD par `readlink`, puis vérifier que la cible possède toujours le
même device/inode. Le runner V11 refuse `O_PATH` et ne traite pas spécialement
la lecture du lien d'un FD de la tâche. Le refus `O_PATH` est une limite déjà
établie : l'injection noyau `SECCOMP_IOCTL_NOTIF_ADDFD` rejette ces descripteurs,
comme expliqué et testé dans le [contrat du superviseur](../../tools/executor/bionic-supervisor/README.md).
Ajouter seulement le flag ne corrige pas cette limite ; retourner un FD
`O_RDONLY` à sa place falsifierait le contrat de l'appel. Aucun de ces
changements n'est introduit. Dans le chargeur amont, l'échec de `realpath`
n'est pas immédiatement fatal : il conserve le chemin d'entrée. Le chargement
effectif des dépendances dans ce cas reste à mesurer sur Android. Le succès
des tests de métadonnées sur PC ne qualifie donc ni `realpath` Bionic ni le
démarrage complet du chargeur installé sur Samsung.

## Correction vérifiée sur PC après le résultat téléphone

Build final : `foldgpt-bionic-supervisor-PHREPY0u`. Le helper épingle la tâche
émettrice et, pour une requête sans suivi, son lien de groupe TGID. Il vérifie
le fichier exécutable réellement épinglé contre le runtime autorisé, puis
retourne ses vraies métadonnées ou celles du lien selon les flags. Les
notifications périmées et les cibles devenues non attestables sont refusées.
Cette restriction ne reproduit pas toutes les sémantiques POSIX après
disparition du leader ou suppression de la cible. `argv[0]` reste inchangé.

Le même travailleur réel échoue avec l'ancien runner KvSGBnzP sur
`stat("/proc/self/exe")`, errno13, et passe avec le nouveau. Le test compare
également ses résultats à une lecture indépendante du noyau pendant que le
travailleur est encore vivant, puis le libère par son entrée standard et
vérifie sa terminaison. Il couvre les métadonnées cible/lien depuis le thread
principal et un pthread, les flags invalides, mauvais pointeurs et refus des
autres chemins proc. Les 20 tests factory comprennent 18 succès et 2 cas du
shim optionnel non fourni ignorés ; les 16 tests Python de résolution et les
tests C/noyau passent aussi. Les [preuves exactes](../../recovery/verification/native-executable-metadata-20260907/manifest.json)
sont conservées dans Git. Le build intermédiaire t256JoQD et son premier
rapport de contrôle restent historiques.

Superviseur ARM64 compilé et inspecté :
`7ed43a09ad5e22cb5e5e1ae347d83947f1f6167a797c8aa8b9d399bf09645a03`.
Il n'est ni empaqueté dans un nouvel APK ni installé sur le Fold. L'essai V11
en échec et son marker sont conservés ; aucun second lancement n'a eu lieu.

## Nettoyage et intégrité vérifiés séparément du succès

Le superviseur a réellement été attendu, et le bootstrap a été récolté par
JNI : `cleanupComplete=true` aux deux niveaux, `bootstrapReaped=true`,
`ownerRetained=false`, `quarantined=false`, `waitStatus=0`. Le code 0 du
superviseur/transport ne remplace pas le code 127 du programme de travail.
La disparition des PID31861 et PID31871 est corroborée par le snapshot après.
Le marker d'essai unique reste conservé ; aucun second lancement V11 n'a lieu.

Les snapshots indépendants avant/après établissent le même boot
`348d453e-f4e5-40e0-8ef0-030f4d5e38af`, les mêmes fichiers de fixture et les
mêmes APK FoldGPT, laboratoire V10 et V11. Les indicateurs observés restent
warranty bit0, verified bootgreen, flash locked1 et SELinuxEnforcing.
Ce sont des observations techniques, pas une promesse contractuelle de garantie.
Le marker et les preuves V10 restent conservés ; l'absence de ses anciens
processus dans la reprise n'est pas présentée comme sa clôture protocolaire.

Les [neuf preuves exactes et leur manifeste](../../recovery/verification/native-v11-20260907/manifest.json)
sont suivis dans Git. Les sorties ADB brutes restent sous
`downloads/native-kernel-trial/v11-resume-shizuku-20260907`,
`v11-immediately-before-fixed-20260907` et `v11-fixed-collection-20260907`.

## Maintien éveillé demandé pendant le travail

`svc power stayon usb` est appliqué : réglage global2, alimentation USB,
`mStayOn=true`, écran éveillé et keyguard non affiché. Le délai système de
30 000 ms, le code et les biométries restent inchangés. La vérification sans
entrée injectée, de 16:55:24 à 16:56:00 UTC, constate le téléphone éveillé et
déverrouillé aux deux bornes, avec un timestamp de dernière veille inchangé.

Ce maintien concerne la veille automatique sous alimentation USB. Il ne
neutralise pas un verrouillage manuel. **Conserver ce réglage pendant la
session de travail active**, puis rétablir sa valeur initiale0 à la fin de
la session, et non à chaque réponse conversationnelle :

```powershell
& "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" -s R3GL808JN4A shell -T svc power stayon false
```

Le manager Shizuku possédait déjà `WRITE_SECURE_SETTINGS` avant ce redémarrage
de serveur. Ce constat actuel remplace l'hypothèse que la révocation antérieure
serait toujours effective. `adb_allowed_connection_time` reste `null` et
`adb_wifi_enabled` reste1 avant/après l'autorisation ; ces réglages n'ont pas
été modifiés par les commandes de cette reprise.
