# Qualification v10 : session conservée après refus de chemin

Le test dépasse le refus de socket du v9, mais **aucun succès d'exécution
noyau ou de commande ordinaire n'est établi**. Le service conserve une session
en quarantaine, sans nettoyage confirmé.

## Composition et préparation

APK installé vers 05:49 :
`46049fd8d2f381c2680023c12005a4d57cf4c9a51c829a447eb88642e6b3a6a4`.
Les 84 ELF et le déploiement sont identiques au v9. Seuls le bootstrap, le
propriétaire de session Python et leur manifeste changent parmi les assets.
Le bootstrap stdio conserve le verrou et le marqueur sans créer de listener.
Les 12 tests réels nonroot et le cycle de vie bootstrap passent sur PC ;
les 24 résultats JVM sont réutilisés. La garde Activity conserve `running=true`
après timeout et capture l'action dans `onCreate` : correction revue sur PC,
sans test Android de cette transition.

Android a restauré l'ancien `KERNEL_RUN_FIXED` pendant la mise à jour. V10
l'a refusé sans réservation. Le collecteur supposait initialement une action
V9 restaurée ; les octets réellement reçus sont conservés et font foi.
Après préparation vérifiée des 2 447 fichiers et 81 alias, le préflight passe
en UID2000, version10, PID11821. L'unique action `KERNEL_RUN_FIXED_V10`
réserve ensuite `files/kernel-v6/attempt-started`.

## Résultat réel

Le délai de rapport de 30 secondes expire avec
`transportCleanupComplete:false`. Le bootstrap PID11978 reste vivant, fils
du service PID11821, avec un seul thread en `do_epoll_wait`, environ 32 Mo RSS,
aucun traceur et seccomp0. Le broker conserve `process-session.json` ;
`evidence.json` existe mais est vide. Aucun superviseur ou worker de
qualification n'est visible. Le collecteur garde `success:false` et
n'inspecte pas le workspace dont la session est retenue.

Le statut du même service a été récupéré par l'API authentifiée existante,
sans réinstallation ni arrêt, avec une seconde instance en lecture seule :

```text
am start -W -f 0x18000000 -n app.foldgpt.shizukuprobe/app.foldgpt.kernelqualification.QualificationActivity -a app.foldgpt.shizukuprobe.KERNEL_PREFLIGHT
```

`NEW_TASK | MULTIPLE_TASK` conserve l'instance portant le Binder propriétaire.
Le tag/version6 réutilise le service. Le préflight refuse sa session active,
puis rapporte le statut réel : `ready:false`, `quarantined:true`,
`ownerRetained:true`, `bootstrapReaped:false`, `waitStatus:-1` et :

```json
{"stage":"factory_construct","errorType":"PermissionError","errno":13,"source":"unknown","line":457,"message":"[Errno 13] Permission denied: '/linkerconfig'"}
```

Le détachement SDK `remove=false` retire les callbacks du tag, sans destruction
du service ou du propriétaire. Cette portée a été vérifiée dans les sources
officielles SDK/serveur conservées. Les PID restent présents après inspection.
Le dernier snapshot conserve le même boot ID et les mêmes indicateurs d'intégrité.

## Cause et prochaine correction

`Processes.__init__` résout chaque runtime avec `Path.resolve(strict=True)`,
notamment `/linkerconfig/ld.config.txt`. Cette résolution inspecte les parents,
alors que la restriction Android sur `/linkerconfig` était déjà documentée.
Le statut confirme désormais le refus réel pendant la construction du backend.

La correction doit conserver l'interdiction du chevauchement physique avec le
workspace et vérifier une résolution permise par Android. Supprimer ce
contrôle ou élargir les droits système n'est pas une correction. Les mécanismes
`/proc/TID/mem`, `pidfd_getfd` et leurs variantes depuis un thread secondaire
restent non mesurés dans ce worker Android.

Conserver le propriétaire, son marqueur, les rapports et le runtime. Ne pas
réinstaller, effacer ou relancer sur cette fixture tant qu'une récupération
explicite et vérifiée n'est pas définie. L'absence de worker visible ne remplace
pas les preuves de nettoyage requises.

Preuves sous `downloads/native-kernel-trial` : `lab-v10-native-result`,
`lab-v10-retained-owner/authenticated-service-status.json`,
`lab-v10-after-status`, `python-lab-v10` et `pc-v10-session-owner`.
APK et sources figés : `tools/executor/shizuku-lab/build/kernel-v10-stdio`.
