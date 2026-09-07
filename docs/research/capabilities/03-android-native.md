# Capacités natives Android utiles à FoldGPT

État documentaire du 7 septembre 2026. Ce fichier inventorie les mécanismes
pertinents pour exécuter et protéger de vrais outils dans FoldGPT ; **ce n'est
pas une liste exhaustive de chaque API Android, symbole de bibliothèque ou
appel système**. Aucun appel, test ni changement sur le téléphone n'a été
effectué par cette sous-tâche. Elle exploite les preuves historiques du
6 septembre et le relevé descriptif effectué en lecture seule par la tâche
principale le **7 septembre à 00:52:19 +02:00**, soit
`2026-09-06T22:52:19Z` [E9]. Ce relevé ne relance pas le test d'exécution.

Une API présente dans le NDK définit comment l'appeler. Elle ne prouve ni que
le noyau la fournit, ni que SELinux/seccomp l'autorise, ni que FoldGPT compose
correctement les droits nécessaires. Les droits sont ceux du **processus qui
exécute réellement l'opération** ; transférer une requête à un service ne
transfère pas automatiquement l'identité de ce service au demandeur.

## Niveaux de preuve

- **Observé Fold** : résultat ou contexte Android conservé et identifié.
- **Amont** : contrat Android/Linux documenté ou en-tête NDK relu ; la politique
  fournisseur exacte n'en est pas déduite.
- **PC seulement** : artefact compilé ou test hôte, sans validation Samsung.
- **À qualifier** : comportement ou composition non établi dans notre contexte.

Les différences entre application ordinaire, service isolé et shell sont
conservées ci-dessous. Le shell ADB est un autre contexte Android, pas un noyau
différent ; le rôle éventuel de Shizuku fait l'objet de l'étude séparée.

## Identité, droits et communication

| Mécanisme | Ce qu'Android/Linux fournit | Application FoldGPT et shell | Preuve et conséquence |
| --- | --- | --- | --- |
| UID/GID, DAC et identité des enfants | Une identité Linux par application et des permissions de fichiers/processus ; `fork` conserve normalement cette identité | Une application ne choisit pas un nouvel UID privilégié par `setuid`. Le shell a ses propres droits, sans accès général aux données de toutes les apps | **Observé Fold** : UID/GID 10412, `CapPrm=CapEff=0` dans le superviseur Bionic [E1]. Sépare FoldGPT des autres apps ; ne sépare pas à lui seul ses commandes de ses secrets |
| SELinux et catégories MLS | Contrôle obligatoire supplémentaire sur fichiers, processus, Binder, sockets et périphériques | Applicable au Java comme au C/ARM64 ; un contexte shell distinct conserve ses propres restrictions | **Observé Fold** : `untrusted_app` avec catégories et système `Enforcing` [E1,E4]. Les politiques AOSP relues ne constituent pas un export de la politique Samsung |
| `isolatedProcess=true` | Android crée un service sous une identité isolée sans permissions applicatives propres | Accessible par l'API Service. Ses droits sont plus restreints que ceux de l'application hôte ; ses fichiers doivent être fournis selon un protocole explicite | **Amont, à qualifier Fold** : Binder/FDs, code APK et traçage interne ont une base AOSP ; démarrage des outils, chargement de toutes leurs bibliothèques et broker non prouvés [A3,E5] |
| Binder/AIDL, JNI, `AIBinder`/`AParcel` | RPC avec identité de l'appelant ; frontière Java/natif ; transfert explicite de descripteurs | Une transaction n'accorde que l'opération autorisée par le service. Chaque API garde ses permissions et AppOps | **Amont** : permet un contrôleur Android et un superviseur natif. Pas d'API générale d'ajout de namespaces au noyau [A3,E5] |
| `ParcelFileDescriptor`, socket UNIX, `SCM_RIGHTS` | Transport de descripteurs déjà ouverts ; socket privée entre composants | Le FD conserve son objet et son étiquette ; les vérifications SELinux restent applicables. Une application ne transforme pas un FD de données en fichier APK exécutable | **Observé Fold** : transport natif privé et acquisition brokerée dans les tests limités [E1,E2]. **À qualifier** entre UID ordinaire et service isolé |
| Permissions Android, AppOps, rôles d'administration | Autorisations accordées pour les API documentées | Le rôle Device Owner, une permission de signature ou un service shell ne signifie pas `CAP_SYS_ADMIN`, `CAP_SYS_MODULE` ou accès à toute API | **Amont** : étudier une API précise avec son autorisation ; aucune API de namespace supplémentaire identifiée [E5] |

Le relevé E9 sépare explicitement trois contextes ; un test réussi via `run-as`
ne valide donc pas automatiquement le contexte Zygote de l'application :

| Contexte réellement lu | UID / domaine SELinux | Seccomp | Capabilities |
| --- | --- | --- | --- |
| `app.foldgpt` PID 16917 et `app.foldgpt:runtime` PID 17419, enfants de Zygote PID 1903 | 10412 ; `untrusted_app` avec catégories `c156,c257,c512,c768` | mode 2, un filtre | `CapPrm=CapEff=CapBnd=0` |
| Commande ADB shell | 2000 ; `shell` | mode 0, aucun filtre | `CapPrm=CapEff=0` ; bounding set `0x8000c0` |
| Commande `run-as app.foldgpt` issue du shell | 10412 ; `runas_app` avec les catégories de l'application | mode 0, aucun filtre | `CapPrm=CapEff=0` ; bounding set `0x8000c0` |

Le bounding set est un plafond de capabilities, **pas un ensemble de droits
effectifs**. L'absence de filtre seccomp du shell est une différence réelle
à étudier pour un broker ; elle ne désactive ni SELinux ni les vérifications
Linux et ne crée pas `USER_NS`/`PID_NS`. Les groupes supplémentaires de `run-as`
diffèrent également de ceux des deux processus Zygote. Le relevé ne prouve pas
qu'un service Shizuku porterait exactement ces attributs à l'exécution.

## Exécution, fichiers et confinement

| Mécanisme | Interface native disponible | Accès effectif et limites | Preuve FoldGPT |
| --- | --- | --- | --- |
| Bionic, NDK, ELF AArch64 | libc, libm, libdl, pthreads et syscalls ; chargeur `/system/bin/linker64` | Du code machine local, sur le noyau Android. Bionic n'est pas l'ABI glibc ; compiler en ARM64 ne suffit pas à porter un ELF GNU | **Observé Fold** : superviseur Python/Bionic et outils natifs APK [E1,E2]. **PC seulement** : Bash 5.3.15 + nouvelle CLI CPython 3.14.7 [E6] |
| Exécutables et bibliothèques installés dans l'APK | Native library directory géré par Package Manager, PIE et bibliothèques partagées | Chemin d'installation variable à chaque mise à jour ; provenance, dépendances et politique doivent être vérifiées | **Observé Fold** : vrais exécutables APK sous `lib/arm64/lib*.so` [E1]. La nouvelle fermeture de 79 ELF Bionic reste **PC seulement** [E6] |
| `execve`/`execveat` depuis les données inscriptibles | Les syscalls existent dans l'ABI ARM64 | Android cible API 29+ interdit l'`execve` direct depuis le home applicatif inscriptible. La présence du syscall, un renommage ou un FD ne supprime pas la règle. Le shell a un autre domaine, sans équivalence garantie avec l'app | **Amont** [A2] ; cible FoldGPT API 37. Une compilation native produisant un ELF ne prouve pas qu'il puisse être lancé comme une commande |
| `dlopen`, mappings exécutables et mode direct du chargeur Bionic | Android distingue chargement d'une bibliothèque et transition `execve` ; Bionic implémente aussi le lancement direct du linker | `untrusted_app` peut charger du code selon les droits de mapping applicables ; `isolated_app` a des règles différentes. Le mode direct change notamment `/proc/self/exe` et auxv. Cela ne fournit aucune isolation | **Observé Fold limité** : le contexte conservé montre des extensions Python mappées depuis les données [E1]. **À qualifier** : lancement de productions natives, identité du processus, descendants, politique et durabilité [A4,E6] |
| Interpréteurs APK | Python, Bash, JavaScript peuvent lire du texte depuis le workspace | Le fichier texte n'a pas besoin d'être un ELF directement exécutable ; les accès et sous-processus restent confinés | **PC seulement pour le nouvel ensemble Bash/Python** [E6]. La création/test/zipapp via l'interface ordinaire du téléphone reste non validée |
| Namespaces `clone`/`unshare`/`setns` | Numéros et flags Linux présents dans les en-têtes | `USER_NS` et `PID_NS` absents du noyau Fold ; autres namespaces soumis aux capabilities/SELinux/seccomp. Shell ou API native n'ajoutent pas le code manquant | **Observé Fold** : configuration sans `CONFIG_USER_NS`/`CONFIG_PID_NS` [E4]. C'est le blocage structurel de la route Bubblewrap, distinct d'un exécutable absent |
| Landlock | API Linux de restrictions supplémentaires sur fichiers, TCP et scopes suivant l'ABI | Une application peut réduire ses droits avec `no_new_privs`. Ne desserre pas SELinux ; ni namespace PID ni changement d'identité. Restrictions héritées ; pas de TSYNC à l'ABI 6 | **Observé Fold : ABI 6** et refus réels de profils limités [E2,E4]. Les fonctionnalités d'ABI plus récentes ne sont pas acquises |
| Seccomp BPF | Filtre sur les appels système, hérité par les descendants | Filtre Zygote déjà en place ; le filtre ajouté ne peut pas réautoriser un appel refusé par l'ancien. Installer avant le lancement des commandes | **Observé Fold** : seccomp 2 hérité et restrictions additionnelles [E1,E2] |
| `SECCOMP_RET_USER_NOTIF`, `ADDFD_FLAG_SEND` | Un superviseur reçoit une demande ; il peut effectuer une opération validée et injecter le FD atomiquement avec sa réponse | Copier les pointeurs, ancrer les FDs et appliquer la vraie politique ; `CONTINUE` après simple vérification d'un chemin mutable ne suffit pas. Annulation et effets de création/troncature demandent un contrat précis | **Observé Fold** dans des profils natifs limités [E1,E2]. La composition GNU/PRoot qui a redémarré n'est pas validée [E7] |
| `openat2`, `O_PATH`, `fstat`, résolveur d'inodes | Résolution ancrée et inspection des objets du noyau | Doit couvrir liens, alias, répertoires courants, dirfds, métadonnées et refus explicites sans substituer un chemin différent | **Observé Fold** pour contrats bornés de fichiers [E1]. **À qualifier** pour shell dynamique avec `chdir`, outils complets et chemin courant de la tâche réelle [E6] |
| PRoot/ptrace | Traduction utilisateur des chemins et ABI sur le même noyau | Compatibilité ; ne remplace pas le confinement. Le traceur est lui-même à confiner et peut interagir avec seccomp et les registres ARM64 | Anciennes preuves partielles et **deux redémarrages non expliqués** dans une nouvelle composition. Fixture suspecte suspendue ; aucune nouvelle exécution [E7] |

## Processus, réseau et ressources

| Mécanisme | Utilité et limites de droits | État |
| --- | --- | --- |
| `fork`/`clone`, `exec`, `waitid`, pipes et pthreads | Création et observation des enfants de même UID ; ce n'est pas un PID namespace. Ne pas reprendre arbitrairement un runtime Java/Binder multithreadé après `fork` | **Observé Fold** sur lanceurs et fixtures limités [E2,E3]. API de service isolé et shell complet restent à qualifier |
| `pidfd_open`, `pidfd_send_signal`, subreaper | Identité stable du processus, signalisation autorisée, adoption et récolte des descendants. `pidfd_getfd` a ses propres contrôles ptrace ; sa déclaration NDK n'en prouve pas l'accès | **Observé Fold** : cycle de vie, arrêt et récolte dans les profils limités [E2,E3]. NDK expose les trois fonctions pidfd depuis API 31 |
| `ptrace`, `process_vm_readv` | Inspection soumise à UID/dumpable, SELinux, seccomp, Landlock et état du processus. Sans droit général de tracer le système | **Observé Fold** : handshake/traceur dans des cas historiques. Matrice des rétroportages ARM64 Samsung inconnue ; pas de nouvelle reproduction [E5,E7] |
| `memfd_create`, seals, `mmap` | Contrôle/transfert de données et mémoire partagée ; un memfd scellé protège ses octets contre les modifications prévues par les seals | **Observé Fold** : création Bionic, seals et refus `EPERM` contrôlés [E3]. Aucun droit d'exécution arbitraire ne s'en déduit |
| TCP/UDP/UNIX, permission `INTERNET` | Android contrôle le domaine et les permissions ; Landlock ABI 6 ne filtre pas tous les protocoles/destinations | **Observé Fold** : refus réseau dans profils bornés. TCP par port ne signifie pas contrôle par domaine ; réseau géré complet et exceptions doivent être médiatisés. Service isolé n'a pas les droits réseau ordinaires [E4,E5] |
| PTY, termios et `ioctl` | Console interactive et taille de fenêtre ; opérations dangereuses et accès aux autres TTY à exclure par politique explicite | **À qualifier Fold** pour commandes gérées. Le transport borné actuel refuse TTY ; on ne peut pas annoncer une console complète [E4] |
| `setrlimit`/`prlimit`, mémoire virtuelle et FDs | Une app peut réduire ses limites ; les limites dures, limites par UID et décisions Android subsistent | **Observé Fold** : besoin réel d'espace virtuel Scudo ; espace virtuel différent de RAM. Pas de plafond global FoldGPT de 2 GiB trouvé [E2,E8] |
| Contrôleur cgroup `pids` | Limitation du nombre de tâches d'un cgroup lorsqu'il est compilé et délégué | **Observé Fold : `CONFIG_CGROUP_PIDS=n`** [E9]. On ne peut pas promettre `pids.max` pour nos commandes. Les mécanismes existants de supervision et `RLIMIT_NPROC` par UID sont distincts, sans prétendre à un quota cgroup absent |
| ActivityManager, LMKD et services | Cycle de vie Android, priorité mémoire, restrictions d'arrière-plan et informations de sortie | La fin d'un service ou une limite mémoire n'est pas équivalente à un reboot du système. Audit mémoire distinct de l'enquête sur les redémarrages [E7,E8] |

## Autres familles natives : disponibles comme API, sans lever ce blocage

Le NDK expose aussi assets, logging, looper, fenêtres/surfaces, buffers matériels,
EGL/OpenGL ES/Vulkan, codecs/médias, audio, capteurs, entrée et tracing. Leur
disponibilité réelle dépend du niveau API, du périphérique, du pilote et des
permissions de la fonction concernée. Elles sont utiles à l'interface, aux
performances et aux diagnostics ; aucune n'implémente les user/PID namespaces
Linux manquants. Elles n'ont pas fait l'objet d'un audit fonction par fonction
dans ce document. Le catalogue officiel des API natives est la référence [A1].

## Sources et reproductibilité documentaire

NDK local relu : `29.0.14206865` (`source.properties`, release r29), racine
`%LOCALAPPDATA%/Android/Sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/windows-x86_64/sysroot/usr/include`.
`aarch64-linux-android/asm/unistd_64.h` contient **318 définitions de numéros
`__NR_*`** dans cette version. C'est un catalogue d'ABI précis, pas « 318
fonctions autorisées sur le Fold ». Par exemple `unshare=97`, `ptrace=117`,
`clone=220`, `execve=221`, `setns=268`, `finit_module=273`, `seccomp=277`,
`bpf=280`, `execveat=281`, `pidfd_open=434`, `landlock_create_ruleset=444`.

Le [catalogue CSV complet des 318 noms et numéros](catalogs/arm64-syscalls-ndk-r29.csv)
est conservé dans le dépôt avec son [manifeste de sources et SHA-256](catalogs/arm64-ndk-r29-sources.json).
Il est extrait de cet en-tête précis sans appeler aucun syscall. Il ne couvre
pas tous les symboles Bionic, toutes les APIs Java/NDK ou une révision ultérieure
du noyau. Le [catalogue ARM HWCAP](catalogs/arm64-hwcaps-ndk-r29.csv) complète
ce relevé avec les 96 bits nommés du même NDK ; son interprétation est détaillée
dans [l'inventaire ARM64](04-arm64.md).

| En-tête relu | SHA-256 |
| --- | --- |
| `aarch64-linux-android/asm/unistd_64.h` | `c20aeb2e83c223a11acbde8505309333c60f122d23e719c4b569298a1d7c38ec` |
| `linux/landlock.h` | `32c05d50b656c254e37ce2a8b49af0a174af72ed9898488fc6ae8fc75e2be675` |
| `linux/seccomp.h` | `649f690e2cb956b546231c7342df8e359494713802cd056ac1cdfcc475c4628a` |
| `sys/pidfd.h` | `94d2c4812a928085b6528444e84a7471458dc13e4d312be01b82f3b4d662d57a` |

Références Android primaires déjà consultées dans la recherche du projet :

- **A1** [NDK : API natives stables](https://developer.android.com/ndk/guides/stable_apis) et [sandbox Android](https://source.android.com/docs/security/app-sandbox).
- **A2** [Android 10 : permission d'exécuter depuis le home applicatif](https://developer.android.com/about/versions/10/behavior-changes-10#execute-permission).
- **A3** [Android : service isolé](https://developer.android.com/guide/topics/manifest/service-element#isolated). Les sources SELinux/Binder et leurs révisions exactes sont indexées dans E5.
- **A4** [Bionic : ajout du lancement direct du linker](https://github.com/aosp-mirror/platform_bionic/commit/8f639a40966c630c64166d2657da3ee641303194), relu précédemment par la tâche principale ; ne promet pas l'identité `/proc` d'un `execve` direct.

Preuves locales relues :

- **E1** [Contexte Android](../../../downloads/native-executor/android-environment-20260906/collected/android-context-before.json) et [vérification indépendante](../../../downloads/native-executor/android-environment-20260906/collected/independent-verification.json) : APK `3ba18fd629681f075cf2d827717e5dc1484963518b84366d03f55938040b99c8`, profil statique/composite limité.
- **E2** [Diagnostic natif Android et assertions réelles](../../../tools/executor/native-runner-android-test.md).
- **E3** [Cycle de vie natif Android](../../../tools/executor/native-processes-android.md).
- **E4** [Contraintes Android/Fold relevées le 6 septembre](../android-native-constraints-2026-09-06.md).
- **E5** [Extensions du noyau et service isolé](../kernel-extension-options-2026-09-07.md).
- **E6** [Bash/Python Bionic compilés sur PC et intégration restante](../bionic-native-route-2026-09-07.md).
- **E7** [Deux redémarrages : preuves et absence de cause établie](../gnu-managed-reboot-2026-09-06.md).
- **E8** [Audit mémoire FoldGPT](../foldgpt-memory-2026-09-06.md).
- **E9** [Inventaire descriptif v2](../../../downloads/runtime/capabilities-20260907-v2/inventory.json), [synthèse](../../../downloads/runtime/capabilities-20260907-v2/brief.json) et [configuration noyau](../../../downloads/runtime/capabilities-20260907-v2/kernel.config), observation `2026-09-06T22:52:19Z`. SHA-256 `inventory.json` : `6c37597ffdb58299bfdad3aeebb652580aefcb6ff375ba8cb7288926933e182d`. Le collecteur v2 conserve les codes distants et erreurs via shell-v2 ; il remplace le premier relevé ambigu, sans activation de Shizuku ni test de charge.
