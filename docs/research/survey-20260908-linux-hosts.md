# Hôtes Linux ARM64 sur Android : sources vérifiées le 8 septembre 2026

Cette étude compare du code amont consulté en direct, pas seulement les pages
de présentation. Elle ne contient aucun nouvel essai téléphone. Aucun paquet
n'a été installé, aucun accès ADB utilisé et aucun fichier officiel modifié.
Les observations FoldGPT proviennent des rapports locaux explicitement cités.

**La piste courte reste le démarrage autonome de notre exécuteur Android dans
FoldGPT. Local Desktop apporte un autre hôte graphique réel et du code de
cycle de vie, mais son propre remplacement de bwrap supprime le confinement :
ce composant ne constitue donc pas une solution à reprendre.** Les solutions
Andronix, AnLinux et UserLAnd utilisent PRoot et le noyau Android existant.
Elles ne recréent pas les namespaces absents. Le chargeur glibc de Termux
Pacman est une piste distincte, sans VM, qui mérite une sélection de composants
précise ; sa bibliothèque complète ne respecte pas nos contrats telle quelle.

La même exigence s'applique à FoldGPT : notre hôte GNU comporte historiquement
un shim de compatibilité dont le retrait et le confinement Chromium n'ont
pas été qualifiés en r25. Les commandes Bionic démontrées sont une voie
distincte ; elles ne rendent pas cette interface qualifiée par extension.

## Périmètre et état de départ

La priorité actuelle est de démarrer FoldGPT et travailler avec le PC éteint.
Le terminal manuel est reporté ; le terminal du modèle fonctionne déjà dans
le parcours r25. Voir les [critères de réussite](functional-milestones-20260908.md)
et les [preuves r25](r25-device-validation-20260908.md).

R25 a exécuté depuis la conversation des commandes Bash/Python/rg sous Android,
un projet Python avec une dépendance réellement téléchargée, ses cinq tests et
son zipapp, ainsi que saisie et Ctrl+C dans deux sessions PTY. L'interface
Electron Linux ARM64 et le contrôleur GNU utilisent encore PRoot. Ce n'est
ni une VM, ni un port entièrement Bionic. Le lancement du backend sélectionné
attend actuellement Shizuku ; le succès r25 ne démontre pas encore la reprise
après reboot sans préparation depuis le PC.

**Comparaison honnête de la sécurité de l'interface :** le
[README FoldGPT](../../README.md) décrit encore `fake_userns.c` comme un
contournement de compatibilité, et [l'audit historique](../../NATIVE-AUDIT.md)
a constaté `libfake_userns.so` dans le processus principal et un renderer.
Ce preload supprime les demandes de namespaces et simule certains succès.
Le test de chroot a confirmé l'absence du confinement annoncé par ce shim,
sans constituer un test d'évasion du renderer Chromium. Aucun relevé r25
consulté ne prouve le retrait du shim ou la qualification de ces protections
du renderer. La conservation des fichiers officiels ne démontre pas une
absence de modification du comportement par preload. Il serait donc inexact
d'écarter Local Desktop pour ce seul principe tout en présentant notre hôte
GNU historique comme une solution de confinement déjà validée. Les résultats
Bionic r25 qualifient leur chemin de commandes et de PTY explicitement testé,
pas l'hôte Chromium dans son ensemble. Le refus de reprendre un faux bwrap
pour la nouvelle autorité d'exécution reste justifié ; il ne clôt pas cette
dette existante de l'interface.

Dans [NATIVE-AUDIT.md](../../NATIVE-AUDIT.md), les mesures hors PRoot ont donné
`CLONE_NEWUSER=EINVAL`, `CLONE_NEWNS=EPERM`, `/proc/self/ns/user` et `pid` absents,
Landlock ABI 6 et présence de seccomp USER_NOTIF. La [configuration récupérée](android-native-constraints-2026-09-06.md)
indique `CONFIG_USER_NS` et `CONFIG_PID_NS` désactivés. Un errno de permission
n'est pas la preuve qu'une opération est utilisable. Les mesures obtenues
depuis `run-as` ne démontrent pas les droits d'un processus créé par Zygote.
Un autre environnement utilisateur ne remplace pas le noyau Samsung.

## Versions et provenance

Les identifiants ci-dessous sont les révisions de branche lues via l'API
GitHub. Les fichiers effectivement ouverts sont liés dans chaque section.
Les licences sont celles déclarées par le projet ou son fichier LICENSE ;
les bibliothèques, distributions et composants embarqués gardent leurs licences.

| Projet et branche consultée | Révision | Licence constatée |
| --- | --- | --- |
| Local Desktop, main | `546915fa44d7fe1b93bb313996bf2cdf45a5e303` | GPLv3 ; Smithay embarqué MIT, autres dépendances séparées |
| Termux:X11, master | `9df8b767645aa0d0a2f2576767449df55b41962f` | GPLv3 |
| UserLAnd, master | `ba4cb39e2233e196f7aba9766dc4dc700481a8ed` | Aucune licence racine déterminée dans cette révision ; sous-module principal inaccessible |
| UserLAnd-Assets-Support, staging | `007b4e2ab2c273d04bc2277479a877b5ad95d2b8` | MIT pour le dépôt ; binaires PRoot et autres séparés |
| AndronixOrigin, master | `dc67784511a166b503f75630d71af3fd4c7a5a79` | MIT ; application Android et distributions payantes fermées selon le README |
| AnLinux-App, master | `4d4b212a9b253b26863d304582078c40ca1ac39c` | Apache 2 |
| AnLinux-Resources, master | `feafd3f87b3290e17767f18e81f7ba8e268edc43` | GPLv2 |
| Asombi, main | `ab1e1e2760482b69cea20a867ca37a7090fb4432` | MIT |
| Winlator, main | `5949297d9dc83ad24ce3f5119fe382da7c899a78` | LGPL 2.1 |
| Winlator-app, main, lu séparément | `4f55d117fff1542944e5b91f433470445160ce08` | LGPL 2.1 |
| Box64, main | `e2219d8facce7d6223da1a28c12388d3a05a2327` | MIT |
| termux-pacman/glibc-packages, main | `c7f8dc1fe5d91443205e7915b443484915db775c` | Par paquet ; glibc-runner déclare GPL3, glibc déclare GPL3/LGPL3 |

Le dépôt Winlator épingle son sous-module app à
`c03f6ab558c6f94cbac6ec0c791b12f3428fbdf6`, distinct du main consulté.
Le code main décrit ci-dessous ne prouve donc pas le contenu de l'APK 11.1.

## Local Desktop : hôte alternatif concret, pas remplacement de la sécurité

Sources ouvertes : [README](https://github.com/localdesktop/localdesktop.github.io/blob/546915fa44d7fe1b93bb313996bf2cdf45a5e303/README.md),
[Cargo.toml](https://github.com/localdesktop/localdesktop.github.io/blob/546915fa44d7fe1b93bb313996bf2cdf45a5e303/Cargo.toml),
[process.rs](https://github.com/localdesktop/localdesktop.github.io/blob/546915fa44d7fe1b93bb313996bf2cdf45a5e303/src/android/proot/process.rs),
[launch.rs](https://github.com/localdesktop/localdesktop.github.io/blob/546915fa44d7fe1b93bb313996bf2cdf45a5e303/src/android/proot/launch.rs),
[run.rs](https://github.com/localdesktop/localdesktop.github.io/blob/546915fa44d7fe1b93bb313996bf2cdf45a5e303/src/android/app/run.rs),
[setup.rs](https://github.com/localdesktop/localdesktop.github.io/blob/546915fa44d7fe1b93bb313996bf2cdf45a5e303/src/android/proot/setup.rs),
[architecture](https://github.com/localdesktop/localdesktop.github.io/blob/546915fa44d7fe1b93bb313996bf2cdf45a5e303/gh-pages/docs/developer/5-how-it-works.md),
[patches](https://github.com/localdesktop/localdesktop.github.io/blob/546915fa44d7fe1b93bb313996bf2cdf45a5e303/gh-pages/docs/developer/7-patches.md).

- La version source est 2.1.1. L'application NDK/Rust fournit un compositeur
  Wayland Smithay et une fenêtre Android via winit. Arch ARM64 s'exécute sous
  PRoot ; Xfce démarre avec `startxfce4 --wayland`, labwc imbriqué et Xwayland
  pour les clients X11. Cela conserve le noyau Android et n'émule pas le CPU.
- `ArchProcess::run` lance `native_library_dir/libproot.so`, avec son loader
  APK, `--link2symlink`, `--sysvipc`, `--kill-on-exit`, puis le shell invité.
  Le code examiné ne demande pas Shizuku pour ce lancement. C'est une preuve
  de mécanisme d'hébergement autonome, pas une preuve que notre exécuteur
  complet aura les mêmes droits ou fonctionnera sans adaptation.
- `ArchProcess::is_supported` extrait un chargeur GNU et l'exécute sous PRoot
  avec `--help`. Ce contrôle n'est pas un essai Electron, de travail modèle,
  de confinement ni de compatibilité générale du Fold.
- `launch` évite les doubles sessions par AtomicBool. `suspended` détruit le
  renderer et coupe l'audio ; `resumed` recrée le renderer et reconfigure les
  sorties. Ces séparations surface/session sont des références utiles au
  pliage et à DeX. Aucun gain de performance n'a été mesuré pour FoldGPT.
- `process.rs` avertit que des binds redondants `/dev/pts` et `/dev/ptmx` avec
  `/dev` avaient entraîné une double traduction d'ioctl PTY. Notre service
  courant lie déjà `/dev` sans ces sous-binds : il ne faut pas ajouter ce
  correctif à l'aveugle au PTY Bionic qui est une autre voie.

**Point décisif : `setup_fake_bwrap`, lignes 690–734, écrit un faux bwrap.** Il
supprime les options bind, namespaces, seccomp et autres, puis fait simplement
`exec "$@"`. Cette recette débloque un chargement SVG, mais n'implémente pas les
protections demandées. Elle est exclue de notre sélection. Le même setup
exporte `ELECTRON_DISABLE_SANDBOX=1` et ajoute `--no-sandbox` aux lanceurs
Chromium/Electron ; la [page VS Code](https://github.com/localdesktop/localdesktop.github.io/blob/546915fa44d7fe1b93bb313996bf2cdf45a5e303/gh-pages/docs/user/app-compatibility/visual-studio-code.md)
l'annonce. L'explication générique de la documentation sur Android ne remplace
pas la configuration et les mesures spécifiques du Fold.

Les problèmes Samsung sont concrets, sans être des mesures sur notre modèle :
[issue 292](https://github.com/localdesktop/localdesktop.github.io/issues/292)
rapporte Firefox et terminal opérationnels sur S25+/OneUI 8.5 en DeX, mais
Thunar, accès aux fichiers, utilisateur et logout défectueux ; l'auteur avait
modifié le réglage de restriction des processus enfants.
[Issue 90](https://github.com/localdesktop/localdesktop.github.io/issues/90)
rapporte une perte des entrées après perte de focus sur S25 Ultra ;
[issue 287](https://github.com/localdesktop/localdesktop.github.io/issues/287)
signale des métadonnées PRoot perturbant pacman/makepkg sur A22/Android 13.
Les trois étaient ouvertes sans commentaire lors de la consultation.

Sélection : réutiliser des idées de gestion des surfaces et de packaging après
revue, ou essayer un hôte graphique isolé si notre affichage devient bloquant.
Changer aujourd'hui toute la distribution et l'hôte n'éliminerait ni le
besoin de notre exécuteur, ni les preuves de reprise et de mises à jour.

## Termux:X11 : composant déjà adopté et correctif de classement Android

Sources ouvertes : [README](https://github.com/termux/termux-x11/blob/9df8b767645aa0d0a2f2576767449df55b41962f/README.md),
[Loader.java](https://github.com/termux/termux-x11/blob/9df8b767645aa0d0a2f2576767449df55b41962f/shell-loader/src/main/java/com/termux/x11/Loader.java),
[CmdEntryPoint.java](https://github.com/termux/termux-x11/blob/9df8b767645aa0d0a2f2576767449df55b41962f/lorie/src/main/java/com/termux/x11/CmdEntryPoint.java),
[commit d24418e4](https://github.com/termux/termux-x11/commit/d24418e4fdc2a84313048d787430d1d69ad6dab8).

Termux:X11 est un serveur X compilé avec le NDK, pas une distribution Linux.
Le mode PRoot doit partager son répertoire temporaire. Son loader localise
l'APK, vérifie la signature attendue et charge son point d'entrée ; le serveur
et l'activité ont des cycles de vie distincts. Quitter l'activité seule ne
termine pas nécessairement le processus serveur.

Le correctif d24418e4 du 1er août 2026 ajoute seulement un flavor `sharedUid`, un
manifest avec `android:sharedUserId="com.termux"` et
`MainActivity android:process="com.termux"`, cible SDK 28, plus les chemins de
build et la documentation. Il n'ajoute aucun ordonnanceur ni contrôle cpuset.
L'objectif annoncé est de conserver le classement de l'application visible
quand Termux:X11 est affiché. L'APK partagé exige les signatures Termux GitHub
correspondantes ; il ne s'applique pas aux variantes F-Droid et Play.

Comparaison locale en lecture seule : ce flavor existe déjà dans
`vendor/termux-x11/lorie-app`; FoldGPT n'inclut pas ce module application.
[settings.gradle](../../android/settings.gradle) inclut le module bibliothèque
`:lorie`. [Le manifest FoldGPT](../../android/app/src/main/AndroidManifest.xml)
possède sa propre activité et un service `:runtime`, sous un seul UID et avec
SDK 37. [FoldRuntimeService](../../android/app/src/main/java/com/termux/x11/FoldRuntimeService.java)
charge Xlorie dans le service et lance PRoot lui-même.
[FoldActivity](../../android/app/src/main/java/app/foldgpt/FoldActivity.java)
appelle `startForegroundService`, sans liaison de service constatée dans ce
fichier. Même UID ne prouve pas même classement de chaque processus.

Conséquence : ne pas importer le flavor partagé ou baisser le SDK. Mesurer le
classement effectif de l'activité, `:runtime`, PRoot et du propriétaire natif
avant de modifier la relation de cycle de vie. La présence de l'ancien code
vendored n'est pas une raison de remplacer l'ensemble de l'intégration.

## UserLAnd, Andronix et AnLinux

| Projet | Code lu et mécanisme réel | Utilité et limites pour FoldGPT |
| --- | --- | --- |
| UserLAnd | [README](https://github.com/CypherpunkArmory/UserLAnd/blob/ba4cb39e2233e196f7aba9766dc4dc700481a8ed/README.md), [build.gradle](https://github.com/CypherpunkArmory/UserLAnd/blob/ba4cb39e2233e196f7aba9766dc4dc700481a8ed/app/build.gradle), [.gitmodules](https://github.com/CypherpunkArmory/UserLAnd/blob/ba4cb39e2233e196f7aba9766dc4dc700481a8ed/.gitmodules) et [execInProot.sh](https://github.com/CypherpunkArmory/UserLAnd-Assets-Support/blob/007b4e2ab2c273d04bc2277479a877b5ad95d2b8/assets/all/execInProot.sh). APK cible SDK 35 ; extraction réelle des exécutables en bibliothèques natives ; lancement PRoot et version de métadonnées enregistrée. | Référence intéressante pour packaging et migrations du stockage. Le sous-module officiel UserLAndLibrary a répondu 404 : le service Android actuel n'a donc pas été inspecté et sa licence/réutilisation complète restent indéterminées. Le build mentionne maintenant des compagnons VM/QEMU téléchargés séparément ; ils sont exclus de notre voie. |
| Andronix | [README](https://github.com/AndronixApp/AndronixOrigin/blob/dc67784511a166b503f75630d71af3fd4c7a5a79/README.md) et [installateur Debian](https://github.com/AndronixApp/AndronixOrigin/blob/dc67784511a166b503f75630d71af3fd4c7a5a79/Installer/Debian/debian.sh). Télécharge un rootfs ARM64, extrait via PRoot, écrit un lanceur PRoot `--link2symlink`, `/dev`, `/proc`, shell invité. | Recettes de distribution MIT, dernier push du dépôt observé en 2024. Dépend de Termux. Ne fournit pas un nouvel exécuteur Bionic ni un hôte Electron Android. Le script ignore explicitement le résultat d'extraction avec `||:` ; ne pas reprendre ce comportement. |
| AnLinux | [README](https://github.com/EXALAB/AnLinux-App/blob/4d4b212a9b253b26863d304582078c40ca1ac39c/README.md) et [installateur Debian](https://github.com/EXALAB/Anlinux-Resources/blob/feafd3f87b3290e17767f18e81f7ba8e268edc43/Scripts/Installer/Debian/debian.sh). Même famille Termux/PRoot, plus configuration PulseAudio et bureaux VNC. | Application Apache 2, scripts GPLv2 : distinguer les licences. Le lanceur n'utilise pas Shizuku mais reste un script Termux. Il ne prouve pas notre lancement depuis Zygote, nos permissions ou l'exécution de tout ELF nouvellement construit. |

UserLAnd choisit son backend `.proot_version` et expose certains fichiers
compatibles aux programmes invités. Il ne faut ni prendre des statistiques
simulées pour des mesures matérielles, ni remplacer le backend de stockage
FoldGPT sans migration : notre [format Termux PRoot](../install/proot-hardlinks.md)
est déjà qualifié et diffère du format USERLAND.

## Asombi : la voie Rust réclame précisément les fonctions absentes

Sources ouvertes : [README](https://github.com/WFStudio-app/Asombi/blob/ab1e1e2760482b69cea20a867ca37a7090fb4432/README.md),
[probe.rs](https://github.com/WFStudio-app/Asombi/blob/ab1e1e2760482b69cea20a867ca37a7090fb4432/loader/src/probe.rs),
[namespace.rs](https://github.com/WFStudio-app/Asombi/blob/ab1e1e2760482b69cea20a867ca37a7090fb4432/loader/src/namespace.rs),
[loader.rs](https://github.com/WFStudio-app/Asombi/blob/ab1e1e2760482b69cea20a867ca37a7090fb4432/loader/src/loader.rs),
[boot/main.c](https://github.com/WFStudio-app/Asombi/blob/ab1e1e2760482b69cea20a867ca37a7090fb4432/boot/src/main.c).

La voie Android annoncée utilise PRoot/Termux. La voie alternative Rust
`setup_user_namespace` appelle réellement `unshare(CLONE_NEWUSER)`, écrit les
maps UID/GID, puis tente mount/pivot_root/chroot. Elle ne construit pas ces
fonctions en espace utilisateur. Le probe compte `EPERM` comme présence du
namespace et l'absence de `ENOSYS` comme présence de mount/chroot ; sa sélection
peut donc retenir une stratégie que l'appelant ne peut pas exécuter. Les erreurs
de certains montages sont également ignorées. Les accès à `__errno_location`
nécessitent en outre une revue de portabilité Bionic.

Le lanceur C fait `execl` du loader si présent, puis `execlp("proot",...)`
uniquement si cet exec retourne. Un loader démarré qui échoue ensuite ne fait
pas revenir au processus C pour essayer PRoot. L'impression «Loading Asombi
kernel» est une étape d'affichage avec délai, pas le chargement d'un noyau.
Pas de composant retenu pour résoudre bwrap ou l'autonomie actuelle.

## Glibc direct, Winlator et Box64 : trois choses distinctes

Le [README glibc-packages](https://github.com/termux-pacman/glibc-packages/blob/c7f8dc1fe5d91443205e7915b443484915db775c/README.md)
annonce des paquets glibc pour Termux ARM64 et autres architectures. Le
[glibc-runner](https://github.com/termux-pacman/glibc-packages/blob/c7f8dc1fe5d91443205e7915b443484915db775c/gpkg/glibc-runner/glibc-runner.sh)
exécute directement `ld.so programme`; `--configure` modifie l'interpréteur
et rpath du programme via patchelf, et `--teg` ajoute termux-exec-glibc.
**Ne jamais utiliser ce mode de modification sur le client officiel.**
Les chemins sont générés pour le préfixe Termux : ce n'est pas un chargeur
universel substituable immédiatement dans une autre APK.

Le [build glibc 2.44](https://github.com/termux-pacman/glibc-packages/blob/c7f8dc1fe5d91443205e7915b443484915db775c/gpkg/glibc/build.sh)
apporte des adaptations utiles : NSS Android, chemins, journalisation,
mémoire partagée et appels compatibles. Mais
[fakesyscall.json](https://github.com/termux-pacman/glibc-packages/blob/c7f8dc1fe5d91443205e7915b443484915db775c/gpkg/glibc/fakesyscall.json)
force plusieurs changements UID/GID à retourner 0 et Landlock/pidfd_send_signal
à retourner ENOSYS. Ce n'est pas acceptable pour notre autorité d'exécution
qualifiée. Son [mprotect.c](https://github.com/termux-pacman/glibc-packages/blob/c7f8dc1fe5d91443205e7915b443484915db775c/gpkg/glibc/mprotect.c)
traite aussi une région de mémoire comme une chaîne avec strlen avant de la
remapper ; il ne constitue pas une implémentation générique fidèle de mprotect.
La sélection éventuelle doit préserver nos erreurs, identités et protections,
sans reprendre cette glibc entière. La [comparaison glibc locale](bionic-native-route-2026-09-07.md)
explique déjà les problèmes de PT_INTERP, exec des enfants et chemins système.

[Winlator](https://github.com/brunodev85/winlator/blob/5949297d9dc83ad24ce3f5119fe382da7c899a78/README.md)
vise Windows x86_64 via Wine et Box64. Dans le code app main consulté,
[GuestProgramLauncherComponent](https://github.com/brunodev85/winlator-app/blob/4f55d117fff1542944e5b91f433470445160ce08/app/src/main/java/com/winlator/xenvironment/components/GuestProgramLauncherComponent.java)
prépare les chemins glibc/X11 puis lance `box64` via
[ProcessHelper](https://github.com/brunodev85/winlator-app/blob/4f55d117fff1542944e5b91f433470445160ce08/app/src/main/java/com/winlator/core/ProcessHelper.java).
Il suspend/reprend des processus identifiés par nom Wine/EXE ; son helper
masque les exceptions et utilise notamment `pid > parentPID` dans sa sélection.
Ne pas reprendre cette gestion pour nos contrats de propriété/fermeture.

[Box64](https://github.com/ptitSeb/box64/blob/e2219d8facce7d6223da1a28c12388d3a05a2327/README.md)
est un émulateur de programmes Linux x86_64 en espace utilisateur ; son
[main.c](https://github.com/ptitSeb/box64/blob/e2219d8facce7d6223da1a28c12388d3a05a2327/src/main.c)
initialise un émulateur puis appelle `emulate`. Ce n'est pas une VM à noyau
invité, mais cela traduit une autre architecture alors que notre client existe
déjà en ARM64. Wine traduit les API Windows ; PRoot traduit des interactions
avec le système de fichiers/processus ; glibc direct conserve le code ARM64
et fournit une ABI GNU. Aucun de ces noms ne signifie «toutes les fonctions du
noyau sont disponibles». Une VM complète/Microdroid fournirait un autre noyau
avec ses propres restrictions et reste hors du périmètre demandé.

## Trois essais courts pour décider, sans installation massive

Ces essais sont proposés, non exécutés par cette étude. Leur préparation doit
utiliser les artefacts existants et les protections déjà qualifiées, sous la
responsabilité du coordinateur téléphone.

1. **Démarrage réel depuis l'application sans Shizuku.** Démarrer dans un
   service Android ordinaire un propriétaire natif empaqueté dans l'APK, puis
   la même commande Python et une session PTY que r25. Vérifier UID réel,
   répertoire, communication, application effective des restrictions, sortie
   et disparition des descendants. Comparer les appels refusés avec ceux du
   chemin r25, sans interpréter un simple `--help` comme réussite. Un refus
   ferme ce mécanisme de lancement précis, pas tous les hôtes. Ce test porte
   directement sur la dépendance restante au démarrage Shizuku.
2. **Hôte alternatif seulement sur le défaut démontré.** Si le problème est
   le démarrage GNU hors PRoot, essayer d'abord un chargeur GNU APK avec une
   petite fermeture de dépendances et de vrais exec d'enfants, sans patcher
   les fichiers officiels ni installer la glibc communautaire complète. Si le
   problème est l'affichage/reprise, un prototype du compositeur Local Desktop
   peut afficher le même client ARM64 et exécuter la même tâche modèle/PTY.
   Ne pas ajouter son faux bwrap. Relever précisément la première frontière
   qui échoue ; une capture d'écran seule ne qualifie aucun de ces chemins.
3. **Reprise autonome et classement des processus.** Sur la voie retenue,
   lancer le projet depuis l'application, fermer et rouvrir, changer de focus,
   plier/déplier et répéter après un reboot Android normal. Relever UID,
   parenté, cgroup/cpuset accessibles et état de l'activité/service afin de
   déterminer si le problème Termux:X11 partagé existe réellement ici.
   Réexécuter les cinq tests, vérifier fichiers et arrêts. La réussite sans PC
   exige un lancement qui ne dépend pas d'un ancien serveur préparé par ADB ;
   si Shizuku est conservé, qualifier et documenter son démarrage sur appareil.

Les contraintes restent inchangées : pas de root, flash, déverrouillage,
modification des protections Android ou des fichiers ChatGPT officiels ; pas
de VM téléphone. Un ajustement de notre interface ne démontre pas à lui seul
la compatibilité des prochaines mises à jour officielles.
