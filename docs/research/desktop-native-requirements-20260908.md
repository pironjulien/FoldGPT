# Dépendances natives du client desktop : inventaire du 8 septembre 2026

La collecte du client **réellement installé sur le Fold, 26.901.41600**, et
le paquet de référence **26.901.51231** contiennent chacun **57 ELF, dont
38 modules `.node` et 46 contenus différents**. Parmi les 57 chemins communs,
**51 ELF sont identiques octet pour octet** ; les six autres conservent les
mêmes dépendances et exigences de versions observées. Le programme
graphique `ChatGPT` dépend du chargeur
GNU, de glibc et de bibliothèques de bureau Linux. En revanche, ses moteurs
officiels `codex` et `codex-code-mode-host` sont des ELF statiques, sans
interpréteur ELF ni `DT_NEEDED`. Il serait donc faux de décrire tous ces
composants comme des exécutables GNU liés dynamiquement.

**Résoudre l'exécution des commandes du modèle ne porte pas automatiquement
l'interface desktop sur Bionic.** L'audit identifie les dépendances à traiter
pour chaque fonction ; il ne conclut ni que ces bibliothèques sont absentes
du Fold, ni que tous les composants du paquet sont nécessaires à chaque
démarrage. Aucun programme, module ou script du client n'a été exécuté.
L'analyseur fonctionne uniquement sur les copies PC. La collecte préalable
du téléphone, réalisée séparément, fournit le reçu et les fichiers utilisés.
L'analyse n'effectue aucune opération ADB ni modification du téléphone.

## Provenance et limite de version

L'analyse couvre le paquet de référence **26.901.51231** extrait dans
`work/desktop-audit-20260908/extracted-r2` et les ELF de la collecte
**26.901.41600** dans `work/desktop-audit-20260908/installed-files/files`.
Leurs versions proviennent des manifestes `linux-package-metadata.json` et
des `package.json` des ASAR correspondants.

| Objet | SHA-256 vérifié ou relevé dans le reçu indiqué |
| --- | --- |
| Paquet Debian, hash du reçu d'extraction | `02a2f5c6cb69509c62abcbdd13c76b139cdb2ca9edde7537239ddde024077ea0` |
| ASAR du paquet de référence, relu par l'analyseur | `4b34e3fec936b52641591644d0574f5f73f95d797d04b25f8ec60bc05378905a` |
| ASAR observé sur le Fold, reçu `installed-r2/report.json` | `1306be560e77fbfb68dd8b0bccac58d52396a3d445f12810a50438fb05f2e61d` |
| Archive de collecte du client installé, hash du reçu `installed-files/report.json` | `d15cb1fdf1798bb3be22cfb2bdeab07a67178f814a9550631954f5f33207f106` |

**Les deux ASAR sont différents.** Le reçu téléphone déclare 292 764 321
octets et les mêmes hashes avant lecture, après lecture et sur la copie PC,
avec `stableDuringRead=true`. L'analyseur vérifie cette cohérence du reçu.
Le reçu de collecte complète porte ce même ASAR et
`stableAsarDuringCollection=true`. L'ASAR est conservé séparément de
l'arborescence extraite ; les ELF analysés ont été vérifiés contre
l'inventaire de cette collecte. Ce n'est pas une mesure atomique de tous
les fichiers vivants du téléphone : la stabilité individuelle des ELF
pendant l'analyse concerne les copies PC.

Les deux manifestes déclarent `electron: 42.3.0` comme dépendance de
développement ; il ne s'agit pas d'une version du runtime mesurée à
l'exécution. Le manifeste `resources/cua_node/manifest.json` déclare
Node **24.19.0**, cible `linux-arm64`, archive
`cua-node-0.0.9-20260829001140-68931e022688-linux-arm64.tar.gz`.
Le manifeste CUA est identique dans les deux versions. Les métadonnées Owl
portent `runtimeName=owl`, mais leur hash d'archive runtime diffère :
`01a999b66c4b496b77275f46e926d6e9ff4d051d7ea5e396083e62e4b144d13d`
pour l'installation et
`de0dcc23233007e55f8dd2e4d8249dfc5a25bd2a08c6760b22f183faa2491df0`
pour la référence. Le manifeste `owl-shell-runtime.json` existe dans la
référence et y déclare Linux/ARM64 ; il n'est pas présent dans la collecte
installée.

Sources locales : [reçu d'extraction](../../work/desktop-audit-20260908/extracted-r2/report.json),
[inventaire du paquet](../../work/desktop-audit-20260908/extracted-r2/package-inventory.json),
[reçu ASAR téléphone](../../work/desktop-audit-20260908/installed-r2/report.json),
[reçu de collecte native](../../work/desktop-audit-20260908/installed-files/report.json),
[inventaire de collecte](../../work/desktop-audit-20260908/installed-files/inventory.json).
Ces sources extraites restent dans `work`, ignoré par Git.

## Différences entre installation et référence

Les **57 chemins ELF correspondent** après retrait du préfixe Debian
`usr/lib/chatgpt/`. Aucun ELF n'est ajouté ou retiré. Les moteurs `codex`,
`codex-code-mode-host`, Node, `node_repl`, `rg`, Tectonic, les trois copies
de Sky, tous les 38 addons et les deux shims Qt ont les mêmes hashes dans
les deux versions. Les identités de manifeste des modules natifs sont
également identiques.

Les six différences de contenu sont :

| Fichier | Octets installés, 26.901.41600 | Octets de référence, 26.901.51231 |
| --- | ---: | ---: |
| `ChatGPT` | 304 549 160 | 304 483 624 |
| `browser_crashpad_handler` | 1 529 256 | 1 529 064 |
| `libEGL.so` | 237 848 | 237 896 |
| `libGLESv2.so` | 237 848 | 237 912 |
| `libvk_swiftshader.so` | 17 084 056 | 17 084 088 |
| `libvulkan.so.1` | 673 232 | 673 280 |

Pour ces six ELF, le comparateur ne relève **aucun changement** dans
l'architecture, la classe, l'interpréteur, `DT_NEEDED`, le SONAME,
RPATH/RUNPATH, les alignements et permissions des segments chargés,
les exigences de versions, les imports dynamiques avec leurs liaisons,
les exports sélectionnés, les imports N-API et les fonctions système
structurantes définies ou importées. Cette égalité de dépendances
**n'établit pas une égalité du comportement, du code ni du confinement**.
Les ASAR restent différents et leur JavaScript relève de l'audit séparé
des surfaces du client.

Le [comparatif complet des 57 chemins](desktop-client-inventory-20260908/native-comparison.json)
conserve les hashes entiers et les champs comparés. Les tableaux natifs
ci-dessous s'appliquent aux deux versions pour les propriétés décrites.

## Couverture vérifiée

Pour le paquet de référence, l'analyseur a contrôlé les signatures des **3 073 fichiers effectivement
extraits** et retrouvé les **57 ELF déclarés** par l'inventaire d'archive.
Les 3 127 autres fichiers ordinaires sont des fichiers non ELF que
l'extracteur inventorie sans les matérialiser. Un ELF absent ou dont le hash
diffère fait échouer l'analyse. Les 57 hashes ont été contrôlés avant et
après lecture, avec taille et date de modification stables.
Pour la collecte installée, **6 194 signatures de fichiers** ont été
contrôlées et les **57 ELF** ont passé les mêmes contrôles avant et après.
Le seul fichier ordinaire absent de cette arborescence est l'ASAR conservé
et vérifié séparément. Les deux passes n'ont produit aucun avertissement
LLVM.

Les chemins Windows étendus `\\?\` sont nécessaires : onze ELF ont des
chemins de 261 à 297 caractères dans cette extraction. Une recherche
ordinaire omettait ces fichiers et ne trouvait que 46 ELF. L'analyseur suit
donc l'inventaire d'archive et ouvre tous les chemins en forme étendue.

| Architecture | GNU/glibc | musl | Convention Android/Bionic | ELF statique, libc non identifiée | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| AArch64 | 29 | 0 | 3 | 4 | 36 |
| ARM 32 bits | 8 | 0 | 3 | 0 | 11 |
| x86-64 | 5 | 5 | 0 | 0 | 10 |
| Total | 42 | 5 | 6 | 4 | 57 |

Huit ELF possèdent l'interpréteur `/lib/ld-linux-aarch64.so.1` ; quatre
exécutables statiques n'ont ni interpréteur ni dépendance dynamique déclarée.
Les autres fichiers sont les 38 addons et sept bibliothèques partagées.
L'ensemble référence **51 noms distincts de bibliothèques `DT_NEEDED`**.
Les variantes ARM32 et x86-64 sont des précompilations embarquées ; leur
présence ne signifie pas qu'elles sont choisies dans un processus ARM64.

La classification Bionic repose sur les dépendances de forme `libc.so`,
`libdl.so`, `libm.so`, `liblog.so` et les répertoires Android ; elle ne vaut
pas test de chargement. Le champ ELF `OS/ABI=SystemV` ne suffit pas à
distinguer GNU, musl et Android.

## Exécutables et bibliothèques principales

Les chemins du tableau sont relatifs à `usr/lib/chatgpt/`. Les colonnes
GLIBC/GLIBCXX donnent la plus haute **référence de version observée**, pas
une version du noyau, une exigence globale de toutes les fonctions ni un
résultat de chargement sur Android.

| Composant | Liaison et versions observées | Fonctions ou dépendances structurantes |
| --- | --- | --- |
| `ChatGPT` | AArch64 GNU ; GLIBC 2.25 ; 34 `DT_NEEDED` ; 1 454 symboles dynamiques non définis | GTK3/GLib/GIO, X11/XCB/xkbcommon, DBus, NSS/NSPR, ATK/AT-SPI, ALSA, CUPS, GBM, udev, Cairo/Pango |
| `browser_crashpad_handler` | AArch64 GNU ; GLIBC 2.17 | Imports `fork`, `posix_spawn`, `prctl`, `ptrace`, `syscall`, `waitpid` ; droits de diagnostic à qualifier séparément |
| `resources/codex` | AArch64 statique ; 222 567 456 octets ; symboles retirés | Littéraux `bwrap`, `bubblewrap`, `landlock_`, `pidfd_`, `/proc/`, `/dev/`, `/sys/` ; aucun appel effectif déduit de leur seule présence |
| `resources/codex-code-mode-host` | AArch64 statique ; 63 381 656 octets ; symboles retirés | Littéraux `/proc/`, `/dev/`, `pidfd_` ; aucune dépendance dynamique déclarée |
| `resources/cua_node/bin/node` | AArch64 GNU ; GLIBC 2.28 ; GLIBCXX 3.4.21 | Processus, signaux, sockets, threads, `epoll`, `inotify`, `dlopen` |
| `resources/cua_node/bin/node_repl` | AArch64 statique ; 100 126 entrées de tables de symboles | Définitions `fork`/`exec`/`posix_spawn`, sockets, `epoll`, `eventfd`, `mmap`, `mprotect`, threads ; définition ne signifie pas exécution |
| `resources/rg` | AArch64 GNU ; GLIBC 2.18 | Fichiers, threads et processus ; les imports `pidfd_getpid`, `pidfd_spawnp` et spawn-chdir relevés sont faibles et non versionnés |
| `resources/plugins/.../latex/bin/tectonic` | AArch64 statique ; 119 484 entrées de tables de symboles | Définitions de fonctions fichiers, spawn, mémoire, sockets, inotify |
| `resources/plugins/.../chrome/extension-host/linux/arm64/extension-host` | AArch64 GNU ; GLIBC 2.25 | Processus et sockets |
| `resources/cua_node/.../sky_linux_arm64` | Trois copies de même hash ; AArch64 GNU ; GLIBC 2.35 | `libX11.so.6`, `XOpenDisplay`, clavier X11 ; aucune preuve de contrôle de l'interface Android |
| `libEGL.so`, `libGLESv2.so`, `libvulkan.so.1`, `libvk_swiftshader.so` | AArch64 GNU ; GLIBC 2.17 | Bibliothèques graphiques du paquet ; un nom identique à une bibliothèque Android ne rend pas leurs ABI interchangeables |
| `libqt5_shim.so`, `libqt6_shim.so` | AArch64 GNU ; GLIBC 2.17 ; ABI C++ | Dépendent respectivement de Qt5 et Qt6 Core/Gui/Widgets ; le chargement de chaque chemin reste conditionnel |

La présence des imports faibles de `rg` ne justifie pas d'annoncer
« glibc 2.39 minimum ». La table des exigences versionnées atteint 2.18 ;
les chemins utilisant les fonctions faibles doivent être examinés
séparément. De même, l'absence de `DT_NEEDED` des quatre ELF statiques
n'exclut pas un chargement conditionnel de bibliothèques à l'exécution.

Les 34 dépendances directes de `ChatGPT` sont :

```text
libdl.so.2           libpthread.so.0     libglib-2.0.so.0     libgobject-2.0.so.0
libnspr4.so          libnss3.so          libnssutil3.so       libsmime3.so
libgio-2.0.so.0      libatk-1.0.so.0     libatk-bridge-2.0.so.0
libdbus-1.so.3       libcups.so.2        libexpat.so.1       libxcb.so.1
libxkbcommon.so.0    libasound.so.2      libgbm.so.1         libX11.so.6
libXext.so.6        libcairo.so.2       libpango-1.0.so.0   libudev.so.1
libm.so.6           libXcomposite.so.1  libXdamage.so.1     libXfixes.so.3
libXrandr.so.2      libatspi.so.0       libgdk_pixbuf-2.0.so.0
libgtk-3.so.0       libgcc_s.so.1       libc.so.6           ld-linux-aarch64.so.1
```

Ces noms ne disposent pas de fournisseurs ELF dans le paquet analysé.
Ils sont attendus dans son environnement Debian. Ce constat **ne signifie
pas** qu'ils sont absents de l'environnement GNU déjà installé sur le Fold.
Les fournisseurs de même architecture trouvés dans le paquet sont seulement
des candidats : l'analyse ne simule pas la résolution du chargeur.

## Addons : liaison système et ABI Node

| Module et version de manifeste | Version native observée | Couplage concret |
| --- | --- | --- |
| `node-pty` 1.1.0 | GLIBC 2.17 ; GLIBCXX 3.4.22 ; 38 imports N-API | `libutil.so.1`, `forkpty`, `openpty`, `ptsname`, `ioctl`, `execvp`, `setuid`, `setgid`, `waitpid` ; export `napi_register_module_v1` |
| `better-sqlite3` 12.9.0 | GLIBC 2.17 ; GLIBCXX 3.4.20 ; aucun import N-API | Export **`node_register_module_v143`** : ABI du runtime hôte à respecter ; `fcntl`, `fsync`, `pread64`, `pwrite64`, `ftruncate64`, `open64`, familles stat |
| `@parcel/watcher-linux-arm64-glibc` 2.5.6 | GLIBC 2.17 ; GLIBCXX 3.4.22 ; 49 imports N-API | `inotify_init1`, `inotify_add_watch`, `inotify_rm_watch` |
| `resources/native/hid-topology-watcher.node` | GLIBC 2.17 ; GLIBCXX 3.4.26 ; 48 imports N-API | `socket`, `bind`, `poll`, `recv`, `eventfd` ; le nom du module ne prouve aucun droit sur un périphérique |
| `@worklouder/wl-device-kit` 0.2.2 / `node-hid` 3.4.0 | Variantes Linux ARM64 GNU | `HID` dépend de libusb ; `HID_hidraw` de libusb et udev ; imports d'énumération, ouverture, claim, detach et contrôle USB ou `ioctl` |
| `@serialport/bindings-cpp` 12.0.1 | Linux ARM64 GNU ; variante Android ARM64 distincte | Termios et ioctl ; la variante Android réclame `liblog.so`, `libc++_shared.so`, `libm.so`, `libdl.so`, `libc.so` |
| `classic-level` 3.0.0 | Linux ARM64 : GLIBC 2.17 / GLIBCXX 3.4.11 ; variantes Android présentes | Deux copies Android ARM64 identiques, avec les mêmes cinq dépendances Bionic que serialport ; verrouillage et persistance à préserver |
| `@img/sharp-linux-arm64` 0.35.3 | Addon GLIBC 2.17 / GLIBCXX 3.4.21 | Dépend du `libvips-cpp.so.8.18.3` livré ; cette bibliothèque demande GLIBC 2.28 / GLIBCXX 3.4.22 et `libresolv.so.2` |
| `@napi-rs/canvas-linux-arm64-gnu` 0.1.91 | GLIBC 2.17 ; 70 imports N-API | Mémoire, threads, fichiers et chargement dynamique GNU |

Le paquet npm `@img/sharp-libvips-linux-arm64` porte la version **1.3.2** ;
la bibliothèque qu'il livre porte **8.18.3**. Ces deux versions ne désignent
pas le même objet. `better-sqlite3` n'annonce pas de dépendance externe
`libsqlite3` : son moteur SQLite est embarqué dans l'addon, mais son stockage
dépend toujours des garanties du système de fichiers.

Les six précompilations Android sont trois variantes AArch64 et leurs trois
variantes ARM32. Aucun fournisseur `libc++_shared.so` n'a été trouvé dans
les ELF de ce paquet. Cela ne prouve pas l'absence de cette bibliothèque
dans une installation Android externe et ne constitue pas un port Android
du client Electron.

Les sélecteurs JavaScript lus sur PC confirment que la variante choisie
dépend du **processus hôte** :

- `asar/node_modules/@parcel/watcher/index.js`, lignes 3–10 :
  `process.platform`, `process.arch` et détection glibc/musl ;
- `package/usr/lib/chatgpt/resources/cua_node/lib/node_modules/node-gyp-build/node-gyp-build.js`,
  lignes 14–15, 63–65 et 109 et suivantes : plateforme, architecture,
  libc et tuple du répertoire `prebuilds`.

Un Node GNU rapportant `linux` reste un processus Linux/GNU pour ces
sélecteurs même s'il tourne sur le CPU d'un téléphone Android. La présence
d'un addon N-API réduit une partie du couplage Node ; elle n'efface ni les
dépendances de libc/C++ ni les droits et services du système.

## Ce que ces dépendances impliquent pour FoldGPT

| Domaine | Exigence observée | Vérification fonctionnelle correspondante |
| --- | --- | --- |
| Affichage et saisie | GTK/X11/XCB, services graphiques, CUA lié à X11 | Affichage des fenêtres, saisie, presse-papiers, ouverture et navigation dans le parcours réellement utilisé ; le contrôle X11 ne prouve pas le contrôle Android |
| Fichiers et bases | `open/stat/rename`, verrous `fcntl`, synchronisation disque, SQLite/LevelDB | Créer, rouvrir, modifier et reprendre un projet après arrêt ; absence de corruption et de dérive des chemins |
| Surveillance | Inotify dans Node et watcher | Détecter réellement les créations, modifications et suppressions dans le stockage utilisé |
| Processus et terminal | Fork/spawn/exec, PTY, signaux, groupes et attente des enfants | Démarrer depuis l'application, saisir, interrompre, attendre et nettoyer les processus ; le PTY du modèle et `node-pty` du terminal de l'interface sont deux chemins distincts |
| Bureau, son, périphériques | DBus, ALSA, udev/libusb/HID, fonctions de diagnostic | Qualifier la fonction quand elle est utilisée ; une bibliothèque ne donne pas l'accès Android au service ou au périphérique |
| GPU | EGL/GLES/Vulkan GNU, GBM et SwiftShader livré | Identifier le backend réellement choisi et mesurer son résultat ; la présence de SwiftShader ne prouve ni son utilisation ni ses performances |
| Isolation | Fonctions de processus, `prctl`/`syscall` et littéraux de sandbox | Vérifier les protections effectives du chemin concerné ; un succès annoncé par un shim ne démontre aucune isolation |

L'interface GNU et les commandes Bionic doivent garder des preuves
distinctes. Le [relevé r25](r25-device-validation-20260908.md) documente
son propre parcours de commandes Python et PTY ; il ne qualifie pas par
extension l'addon `node-pty`, tous les plugins ou le renderer Chromium.
Le raccordement d'un autre exécuteur de commandes ne remplace pas les
bibliothèques et services dont le client se sert lui-même.

L'[audit historique](../../NATIVE-AUDIT.md) et le
[relevé des hôtes Linux](survey-20260908-linux-hosts.md) signalent le shim
`fake_userns`/preload utilisé par l'hôte GNU. Ce mécanisme ne constitue pas
une preuve de confinement Chromium. Le présent audit ne démontre ni son
retrait, ni la qualification de la sandbox des renderers. Conserver les
octets officiels du client ne suffit pas à démontrer que leur comportement
n'est pas influencé par l'environnement de lancement.

Cette liste ne préconise aucun root, flash, déverrouillage ou changement
des protections du téléphone. Elle ne promet pas non plus qu'un autre
chargeur, Shizuku ou une recompilation peut créer une fonctionnalité
absente du noyau. Les voies utilisateur doivent être évaluées avec leurs
capacités réelles et le même critère de réussite observable.

## Reproduction, livrables et limites

Analyseur : [inventory-native.py](../../tools/desktop-audit/inventory-native.py).
Comparateur : [compare-native.py](../../tools/desktop-audit/compare-native.py).
Métadonnées versionnables des deux ensembles de 57 ELF :
[installation 26.901.41600](desktop-client-inventory-20260908/native-metadata-installed.json),
[référence 26.901.51231](desktop-client-inventory-20260908/native-metadata-reference.json),
[différences](desktop-client-inventory-20260908/native-comparison.json).
Ces copies excluent les dumps complets et les extraits de chaînes intégrées
au client. Elles conservent les chemins, tailles, hashes, identités de modules,
dépendances, exigences de versions, symboles structurants et provenance de
l'analyse. La commande complète est également inscrite dans chaque champ
`invocation`.

Depuis `C:\Dev\ChatgptFold`, utiliser un répertoire de sortie neuf :

```powershell
python -B tools/desktop-audit/inventory-native.py `
  --package-root work/desktop-audit-20260908/extracted-r2/package `
  --inventory work/desktop-audit-20260908/extracted-r2/package-inventory.json `
  --provenance work/desktop-audit-20260908/extracted-r2/report.json `
  --asar-root work/desktop-audit-20260908/extracted-r2/asar `
  --installed-asar-receipt work/desktop-audit-20260908/installed-r2/report.json `
  --readelf C:/Users/julie/AppData/Local/Android/Sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-readelf.exe `
  --output work/desktop-audit-20260908/native-r7
```

Pour la collecte installée :

```powershell
python -B tools/desktop-audit/inventory-native.py `
  --layout installed `
  --package-root work/desktop-audit-20260908/installed-files/files `
  --inventory work/desktop-audit-20260908/installed-files/inventory.json `
  --provenance work/desktop-audit-20260908/installed-files/report.json `
  --asar-root work/desktop-audit-20260908/installed-extracted/asar `
  --asar-file work/desktop-audit-20260908/installed-r2/app.asar `
  --installed-asar-receipt work/desktop-audit-20260908/installed-r2/report.json `
  --readelf C:/Users/julie/AppData/Local/Android/Sdk/ndk/29.0.14206865/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-readelf.exe `
  --output work/desktop-audit-20260908/native-installed-r1

python -B tools/desktop-audit/compare-native.py `
  --installed work/desktop-audit-20260908/native-installed-r1/native-inventory.json `
  --reference work/desktop-audit-20260908/native-r7/native-inventory.json `
  --output work/desktop-audit-20260908/native-comparison-r1.json
```

Les passes r7 et installed-r1 utilisent LLVM readelf **21.0.0**, avec les
mêmes hashes de l'analyseur et
du lecteur enregistrés dans
[invocation de référence](../../work/desktop-audit-20260908/native-r7/invocation.json)
et [invocation installée](../../work/desktop-audit-20260908/native-installed-r1/invocation.json).
Les fichiers de lecture et extraits restent en local :
[résumé installé](../../work/desktop-audit-20260908/native-installed-r1/summary.json),
[inventaire installé complet](../../work/desktop-audit-20260908/native-installed-r1/native-inventory.json),
[index installé des dépendances](../../work/desktop-audit-20260908/native-installed-r1/dependencies.json),
[dumps LLVM installés](../../work/desktop-audit-20260908/native-installed-r1/raw).
Le répertoire `native-r7` contient les mêmes sorties pour la référence.

Les [trois tests de l'analyseur](../../tools/desktop-audit/test_inventory_native.py)
passent : rejet des chemins qui sortiraient de l'archive, lecture de
littéraux à cheval sur les blocs et dans de longues chaînes, ordre
numérique des versions et reconnaissance des ELF statiques. Commande :

```powershell
python -B -m unittest discover -s tools/desktop-audit -p test_inventory_native.py -v
```

Les **114 lectures** ont terminé sans avertissement LLVM et sans divergence
de hash. Ce résultat établit la couverture des ELF **des deux collectes**.
Il n'établit pas une fermeture complète des dépendances du Fold ni un
graphe exhaustif des appels noyau. Les imports peuvent appartenir à des
branches conditionnelles ; les fonctions définies ne sont pas forcément
appelées ; les chaînes ne sont pas des appels ; `syscall()`, les appels
inline et les cibles conditionnelles de `dlopen` demandent une analyse
supplémentaire ou des traces autorisées du parcours réel. L'absence
d'import dans un binaire statique ne prouve pas l'absence de l'opération.
