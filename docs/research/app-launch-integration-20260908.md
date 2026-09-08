# Intégration d'un propriétaire lancé par Android — 8 septembre 2026

Analyse PC bornée, sans changement de production ni opération téléphone.
**Le diagnostic app-context a réussi sur le Fold ; l'étape suivante est un
nouveau profil de lancement depuis Zygote, avec les mêmes contrats de données,
d'exécution et de fermeture.** Ne pas rendre le profil run-as existant
permissif : les deux origines ont des identités et filtres hérités différents.

Le [diagnostic séparé](../../tools/runtime/app-context-probe/README.md) utilise
les ELF et adaptateurs pipe/PTY r25, avec Python relocalisé dans une autre APK.
Le [reçu indépendant du second essai](../../work/feasibility-survey-20260908/app-context/device-run-2/independent-verification.json)
confirme `passed=true`, Shizuku absent avant et après, parent Java `zygote64`
lu dans `/proc`, boot inchangé et APK de production/officielles inchangées.
Les [résultats collectés](../../work/feasibility-survey-20260908/app-context/device-run-2/collected/report.json)
prouvent, sous le même UID app non root et seccomp 2 hérité : fichiers et
sous-processus Python, entrée pipe avec sortie 23, PTY 80×24 et interruption
par `process/signal` avec `signal=interrupt`, donnant sortie 130. Ce dernier
cas ne teste pas l'envoi de l'octet Ctrl+C au PTY ; cette preuve distincte
appartient à r25 et devra être rejouée sous la nouvelle origine.

Les deux cas ont produit fermeture, wait du propriétaire à 0, EOF et absence
de quarantaine. La [lecture externe des cinq PID](../../work/feasibility-survey-20260908/app-context/device-run-2/pid-observations.json)
(superviseur Python, deux propriétaires natifs et deux workers) retourne
ENOENT après la fin. Ce retour seul ne prouve pas l'absence : l'accès au
propriétaire était déjà masqué pendant le test. Une énumération shell
indépendante voit Java mais aucun des cinq processus terminés ; elle corrobore
les vraies attentes et EOF. Les [preuves sélectionnées](../../recovery/verification/app-context-20260908/manifest.json)
sont versionnées. Ces PID sont datés, jamais des identités à réutiliser.
Ce succès ne qualifie encore ni le bootstrap de production, ni les trois
canaux directs, ni tous les descendants détachés, ni les profils managed/host,
ni la reprise de FoldGPT après reboot ; la production était déjà indisponible
avant le diagnostic et celui-ci ne démontre pas sa remise en service.

## Dépendances exactes au lancement actuel

| Couche actuelle | Hypothèse réellement codée | Adaptation propre proposée |
| --- | --- | --- |
| [FoldExecutorRuntime](../../android/app/src/main/java/app/foldgpt/FoldExecutorRuntime.java), `prepare`, `attachBinder`, `bind` | Shizuku Binder disponible ; UID 2000 exigé ; `UserServiceArgs` et durée de vie liées au serveur. | Sélection explicite d'un propriétaire app depuis un asset signé/versionné. Conserver le chemin Shizuku strict ; aucun essai de secours silencieux après refus. |
| [Deployment](../../tools/executor/shizuku-service/transport/src/main/java/app/foldgpt/shizukuexec/Deployment.java), constructeur directNative | Lance `/system/bin/run-as app.foldgpt bootstrap ...`, avec PID parent du UserService. | Nouveau déploiement app : bootstrap APK directement exécuté, UID de PackageManager, parent réel du service app, cwd privé explicite. Inventaires et `PythonRuntime.verifyApplication` restent nécessaires. |
| [spawn.c](../../tools/executor/shizuku-service/transport/src/main/cpp/spawn.c), `admitted_identity` et `NativeSpawn_launch` | UID/GID réels/effectifs/sauvés 2000 ; aucune capacité ; fork puis FD0–3, close_range et cwd `/`. | Entrée native distincte pour l'UID exact de l'application, sans capacité ; même fermeture des FD JVM/Binder et waitpid. Le nouveau chemin doit faire chdir dans le DATA canonique : run-as accomplissait cette transition implicitement. |
| [native-bootstrap.c](../../tools/executor/runas-runtime/native-bootstrap.c), `main` lignes110–120 | Même UID/GID application, parent exact, **NoNewPrivs=0 et Seccomp=0** ; nom d'ELF/argv run-as fixes. | Bootstrap app séparé ou compilation avec contrat distinct, sélectionné à la construction. Exiger le contexte app effectivement qualifié, seccomp 2 hérité et absence de capacités ; conserver le contrôle d'inventaire avant imports. Ne jamais accepter indifféremment 0 ou 2 dans l'ancien contrat. |
| [foldgpt_native_bootstrap.py](../../tools/executor/shizuku-service/transport/src/main/assets/foldgpt-executor/foldgpt_native_bootstrap.py), `identity` lignes29–48 | Python isolé/no-site, cwd DATA, UID/GID, parent, nonce et launch path ; **NoNewPrivs/Seccomp/Seccomp_filters=0**, domaine `runas_app`. | Entrée d'admission app distincte, puis corps commun contrôlé pour deployment, acquisition et fermeture. Conserver toutes les vérifications partagées et refuser une origine inconnue. |
| [SessionState](../../tools/executor/shizuku-service/transport/src/main/java/app/foldgpt/shizukuexec/SessionState.java) et [ExecutorService](../../tools/executor/shizuku-service/transport/src/main/java/app/foldgpt/shizukuexec/ExecutorService.java) | Service UID 2000, client UID application, Binder death, FD3 et reçus privés ; libération seulement après nettoyage et wait réels. | Contrat d'identité app distinct. Extraire éventuellement une machine d'état de fermeture commune, en gardant des constructeurs stricts pour chaque origine. Aucun client UID 2000 admis par défaut au nouveau service. |

Les exigences seccomp 0 identifiées concernent **l'admission du propriétaire
run-as**, pas les runners directs r25. [direct-runner.c](../../tools/executor/bionic-supervisor/direct-runner.c)
et [tty-runner.c](../../tools/executor/bionic-supervisor/tty-runner.c) exigent une
identité non root uniforme et aucune capacité, puis appliquent NoNewPrivs=1
aux workers ; ils ne réclament pas seccomp 0. Ils dépendent réellement de
fork/exec, close_range, subreaper, waitid, pidfd, signaux et lecture de leurs
processus ; le PTY ajoute setsid et les ioctl du terminal. Le diagnostic
app-context est pertinent pour ces appels, sans démontrer tous leurs cas.

Le profil managed constitue une autre frontière : [runner.c](../../tools/executor/bionic-supervisor/runner.c)
installe un listener seccomp, utilise les notifications/ADDFD et certains
pidfd_getfd. Les filtres hérités de Zygote restent appliqués. Une admission
app ne doit ni tenter de les enlever, ni considérer le succès du profil
direct comme une preuve du profil managed. Les canaux host existants et les
helpers de fichiers doivent aussi être réexécutés sous la nouvelle origine.

## Contrat minimal du nouveau propriétaire

1. **Origine explicitement admise.** Service app non exporté, dans un processus
   propriétaire dédié ou le `:runtime` existant, démarré par Android ; UID/GID
   réels/effectifs/sauvés exactement ceux de l'application, aucun root/shell,
   aucune capacité. Relever groupe supplémentaires, contexte Android,
   NoNewPrivs, seccomp et parenté ; admettre le contexte mesuré, sans fabriquer
   un nom de domaine ni un nombre de filtres. Une nouvelle version Android
   inconnue doit conserver un diagnostic explicite.
2. **Code et données préadmis.** Garder [NativeLaunch](../../android/app/src/main/java/app/foldgpt/NativeLaunch.java),
   nonce, chemins privés, ownership/modes, inventaire complet sans fichiers
   supplémentaires, alias vers les ELF de l'APK, hash et refus de liens/path
   substitués. Python démarre avec environnement vide, `-I -S -B -u`, depuis
   le bootstrap C APK. Le script du diagnostic relocalisé n'est pas un
   remplaçant de cette admission de production.
3. **Propriété avant exécution.** Enregistrer l'enfant et ses canaux avant
   admission ; FD3 indépendant ferme la séance quand son propriétaire meurt.
   FD0–3 seuls traversent fork/exec. Le pont Java observe diagnostics/wait et
   annulation ; les commandes continuent via les sockets natives et SCM_RIGHTS,
   sans relais de commandes ou réponse simulée. `ProcessBuilder` du diagnostic
   ne fournit pas à lui seul ce contrat FD3 de production.
4. **Même protocole et mêmes droits déclarés.** Réutiliser le corps contrôlé
   de `run`, [NativeRuntimeAcquisition](../../tools/executor/native_runtime_acquisition.py),
   [StartupManifest](../../tools/executor/native_runtime_startup.py),
   [PrivateSessionOwner](../../tools/executor/private_exec_broker.py), mapping
   d'exécutables et limites existants. Préserver les trois canaux et leur
   authentification UID, session et identité vivante ; ne pas appeler un PID
   persisté une preuve d'identité actuelle.
5. **Fermeture réelle.** Conserver lock/lease, cancellation, attente de tous
   les enfants, reçus bornés, EOF et wait ; quarantaine si une propriété reste
   inconnue. Pas de redémarrage d'un propriétaire concurrent après timeout.
   [RuntimeExitGate](../../android/app/src/main/java/app/foldgpt/RuntimeExitGate.java)
   et `NativeSessionObservation` restent la référence des arrêts/reprises.

La sélection [NativeModelProfiles](../../tools/executor/native_model_profiles.py)
reste inchangée : une demande de sandbox explicite va au backend managed ;
elle ne retombe jamais sur DirectProcesses après échec. Le profil ordinary UID
renvoie déjà `sandboxType=none` et s'appuie sur l'isolation Android de l'UID,
pas sur une sandbox Linux inventée. Ce périmètre n'isole pas un programme
hostile des autres données accessibles au même UID ; l'intégration app ne
doit pas transformer cette limite existante en promesse plus forte.

## Fichiers et vérifications à traiter dans l'ordre

- **Nouveau contrat de lancement** : asset/version, bootstrap C et Python app,
  propriétaire Java/JNI. Factoring limité des routines communes d'inventaire
  et fermeture ; conserver les entrées et refus run-as existants. Mettre à
  jour les recettes [build-bootstrap-windows.py](../../tools/executor/runas-runtime/build-bootstrap-windows.py),
  [stage-production-package.py](../../tools/executor/runas-runtime/stage-production-package.py),
  [verify-production-apk.py](../../tools/executor/runas-runtime/verify-production-apk.py)
  pour les deux identités d'artefacts, sans remplacer silencieusement un hash.
- **Contrôles PC ciblés** : refus des mélanges app/run-as, origine/contextes
  incorrects, argv/nonce/paths/hashes corrompus, FD hérités, fork/exec refusé,
  annulation avant readiness, EOF, frame tronquée, double start et génération
  précédente encore propriétaire. Réutiliser les cas de `SessionStateTest`,
  `NativeSessionObservationTest`, `RuntimeExitGateTest`,
  `test_native_runtime_startup.py`, `test_native_runtime_acquisition.py`,
  `test_private_session_owner.py` et les tests de packaging direct/PTY.
- **Qualification app réelle avant bascule UI** : même bootstrap de production
  installé ; acquisition des trois canaux ; fichiers, pipe et PTY avec les
  mêmes bytes r25. Exécuter les cas de descendants détachés, Ctrl+C, saturation,
  fermeture du contrôleur et décès du service, puis prouver wait/nettoyage et
  reprise. Rejouer les profils managed et host concernés ; tout refus reste
  visible, sans retirer leurs gardes pour annoncer une parité.
- **Bascule explicite et parcours quotidien** : FoldExecutorRuntime choisit le
  propriétaire app qualifié ; tests depuis la vraie conversation, projet avec
  dépendance, pip/rg, cinq tests et zipapp ; fermeture complète et reprise,
  arrière-plan/pliage puis reboot Android normal sans PC. Pour une mise à jour
  APK, anciennes générations fermées avant renouvellement des alias et
  inventaires ; vérifier compte, conversation et fichiers inchangés.

Le résultat positif vérifié du diagnostic justifie cette intégration. Il n'autorise
pas à annoncer le projet terminé, le renderer Chromium qualifié ou toutes les
mises à jour compatibles. Aucun délai de réalisation n'est déduit du seul
nombre de gardes à adapter.
