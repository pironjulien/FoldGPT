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
chemins `/proc`. Ce correctif est en cours sur PC ; aucune correction n'est
encore qualifiée sur Android.

Le [source officiel Bionic consulté](https://android.googlesource.com/platform/bionic/+/refs/heads/main/linker/linker_main.cpp#214),
blob `425bcda67fe7f342222c02a74d3f13bb059825ac`, confirme aux lignes214–237
la séquence `stat("/proc/self/exe")`, repli sur `stat(argv[0])`, puis exactement
le message observé si les deux échouent. Les lignes326–327 appellent cette
fonction avec `args.argv[0]`. Le chargeur appelle ensuite `realpath` pour
choisir sa configuration ; cette étape doit aussi être examinée. Le source
amont consulté explique le diagnostic, sans prétendre être le source exact
du binaire Samsung installé.

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
