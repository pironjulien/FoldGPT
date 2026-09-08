# Comparables GitHub : Codex Android natif, état lu le 8 septembre 2026

Il existe des projets comparables utiles. Le plus pertinent nouvellement identifié est **DioNanos/codex-termux**, un port récent du moteur Codex vers Android/Bionic, avec le vrai runtime V8 et son exécutable auxiliaire. Il peut fournir une base de portage du contrôleur qui éviterait certaines adaptations GNU. Cela ne démontre pas encore le scénario FoldGPT : interface habituelle, commandes natives, fichiers partagés, arrêt propre et reprise sur le Fold Samsung.

Cette recherche est en lecture seule. Aucun programme tiers n'a été installé, exécuté ou intégré, aucune publication/commentaire n'a été effectué, aucun téléphone n'a été manipulé. Le navigateur intégré a été essayé : `cua.createBrowserTab("iab", ...)` retourne `Browser is not available: iab`. L'inventaire CUA ne présente que Chrome externe ; il n'a pas été utilisé. Les lectures distantes ont donc utilisé le **connecteur GitHub de code**, déjà employé dans les études précédentes du projet. Les documents locaux et les réponses effectivement lues sont distingués ci-dessous. Une page wiki Termux a été refusée par le connecteur ; son contenu n'est pas présenté comme relu aujourd'hui.

## Cinq références à conserver en priorité

### 1. DioNanos/codex-termux — candidat réel pour le portage Bionic du moteur

- [README du port](https://github.com/DioNanos/codex-termux/blob/main/README.md), blob lu `01cc44f79ba13bf4212d9543d5bd079524695086`.
- [Release v0.153.3](https://github.com/DioNanos/codex-termux/releases/tag/v0.153.3), publiée le **5 septembre 2026** ; base annoncée OpenAI `rust-v0.153.2`, Android ARM64 API 29+. HEAD observé : `235ec42906fbeb1a5c17f0a9e596e1f86fd5a8df`.
- [Pipeline Android effectivement lu](https://github.com/DioNanos/codex-termux/blob/235ec42906fbeb1a5c17f0a9e596e1f86fd5a8df/.github/workflows/termux-npm-build-publish.yml), lignes 1–200, blob `d38f7f63983ee0d29bc30c859f1c639834b88643`.
- [Inventaire des patches](https://github.com/DioNanos/codex-termux/blob/235ec42906fbeb1a5c17f0a9e596e1f86fd5a8df/patches/README.md), blob `d0ce99c57158e4dd2cefc6d6a8715a2fac794077`.

**Ce qui est concret :** la CI compile pour `aarch64-linux-android` avec NDK 28.2, cible API 29, construit les paquets `codex-cli` et `codex-code-mode-host`, puis exige que les deux exécutables et `libc++_shared.so` existent dans le tarball npm. Elle utilise un prébuild Android de rusty_v8 dont les empreintes sont épinglées ; ajoute le runtime compiler-rt nécessaire à `__clear_cache` ; conserve `RUNPATH=$ORIGIN`. Le manifeste Cargo de `code-mode-runtime` lu séparément contient réellement `v8` sans exclusion Android, avec `v8_enable_sandbox`.

**Précision nécessaire :** le README et l'inventaire emploient encore « in-process V8 ». Le pipeline indique explicitement qu'à partir de `rust-v0.147.0` le code mode utilise un processus séparé et doit embarquer `codex-code-mode-host`. Son architecture actuelle ne doit donc pas être déduite de cette formule du README. L'en-tête de l'inventaire cite aussi encore 0.147.0 ; la release et le HEAD observés sont 0.153.3. Le sandbox interne V8 protège son runtime ; ce n'est pas Bubblewrap ni une preuve d'isolation des commandes du modèle par le noyau Android.

**Réutilisation réaliste :** les recettes de compilation rusty_v8 Android, la liaison Bionic/C++, la résolution de son propre exécutable, les adaptations `openpty` et les chemins Android sont des pistes solides à comparer à notre moteur séparé. Le code `openpty` lu utilise `posix_openpt`, `grantpt`, `unlockpt`, `ptsname_r` et l'ouverture du slave : mécanismes Android ordinaires, sans root. Cela pourrait servir au futur PTY ; r21 refuse actuellement les demandes TTY explicitement.

**Ce qu'il ne faut pas importer indistinctement :** l'inventaire décrit plusieurs sites de verrouillage où `ENOTSUP` est traité comme un verrou acquis et un installateur automatique neutralisé. Ces choix ne satisfont pas automatiquement nos invariants de concurrence et de mise à jour. Les correctifs de portage sont à examiner individuellement ; adopter tout le fork n'est pas une correction démontrée. L'asset npm est publié, mais ses octets et son exécution sur le Fold n'ont pas été testés dans cette recherche. Les logs device internes sont exclus de l'arbre public selon l'inventaire ; aucune qualification équivalente à notre projet Python depuis l'UI n'a été trouvée dans les fichiers lus.

### 2. Termux User Repository — une recette native, mais une version en retard et des blocages documentés

- [Recette TUR codex](https://github.com/termux-user-repository/tur/blob/master/tur/codex/build.sh), blob lu `f7a93c065f589f933eb6e84f8dfe367c808070cd`.
- [Demande et discussion de paquet Termux #27014](https://github.com/termux/termux-packages/issues/27014), corps et huit commentaires lus.

La recette actuelle lue est **0.122.0, révision 1**, dépend de libc++ et OpenSSL, et compile V8 et Codex pour Android. Elle montre qu'il ne faut pas assimiler « absent du dépôt principal Termux » à « impossible nativement ». Le ticket explique que le paquet existe dans TUR et discute aussi la politique du dépôt principal.

Mais la même discussion contient des erreurs concrètes de mise à jour V8 (`cstring` absent, `android_ndk_version` indéfini) et le mainteneur écrit que le paquet est encore cassé. Le témoignage initial de compilation réussie visait **Codex 0.50.0**, pas le moteur actuel. C'est une source de recettes et de problèmes connus, **pas une solution prête à installer pour terminer FoldGPT**. Le port DioNanos plus récent semble un meilleur objet d'étude pour le moteur actuel.

### 3. friuns2/codex-mobile — interface web au-dessus d'app-server

- [README codex-mobile](https://github.com/friuns2/codex-mobile/blob/main/README.md), blob lu `b5b2fe519be40b79e7ec94e9be6eec1c7501cb61`.

Ce projet décrit une passerelle Express/Vue vers **Codex app-server**, utilisable dans le navigateur avec Termux sur Android. Il est issu de `pavel-voronin/codex-web-local` et propose notamment historique, projets, export/import et interface mobile.

**Réutilisable :** le découpage UI/passerelle/app-server est un comparable architectural concret. Les échanges RPC et les détails de reprise peuvent être étudiés si nous rencontrons un problème d'interface.

**Preuve partielle seulement :** ses prérequis comprennent un environnement app-server déjà disponible ; afficher sa page ne résout pas le moteur ni l'exécution Android. Il utilise une UI propre et recommande de maintenir Termux actif. Il démarre un tunnel cloudflared par défaut : aucune reprise de ce comportement n'est nécessaire pour notre objectif local, et rien de ce projet n'a été lancé. Cette solution ne prouve pas que l'application officielle reste inchangée avec notre intégration après chaque mise à jour.

### 4. OpenAI codex-exec-server — le vrai contrat amont déjà utilisé

- [README amont exec-server](https://github.com/openai/codex/blob/main/codex-rs/exec-server/README.md), blob lu `c3d0f3210bea6a1aecb186429fee70dd4dab7afd`.

L'amont fournit bien le protocole JSON-RPC séparant le contrôleur des processus/fichiers : handshake `initialize` puis `initialized`, `environmentInfo`, `process/start/read/write/terminate`, notifications de sortie/fermeture et méthodes `fs/*` en URI `file:`. Le serveur prend également en charge des transports distants ; les inscriptions Noise/registry nécessitent un service qui accepte leur contrat, ce n'est pas un accès automatique garanti depuis n'importe quelle application.

**Déjà appliqué :** notre exécuteur et son backend de fichiers emploient ce type de contrat, avec handles de session et politique explicite. Le dernier blocage réel r20 venait du contexte sandbox absent/null en mode Full access, refusé par notre backend managed. Le profil r21 ordinaryUid corrige précisément ce contrat sans faire passer une commande sans confinement pour une commande managed.

**Limite :** le README amont est une spécification/implémentation générique, pas une qualification Android. Sa présence n'implique pas qu'une application officielle possède un bouton permettant d'enregistrer notre exécuteur local arbitraire. Le raccordement précis au client et les commandes réelles restent à valider sur le Fold.

### 5. Shizuku API — le service natif est réel, ses pouvoirs restent bornés

- [README Shizuku-API](https://github.com/RikkaApps/Shizuku-API/blob/master/README.md), lignes 65–150 relues, blob `3ebe9fee660873cb4ac31f5b3e54a99d625ffa23`.

L'API documente un UserService capable d'exécuter Java/JNI dans un processus distinct avec l'identité shell **UID 2000** en mode ADB. Elle précise que cette identité n'est pas root, qu'elle ne lit pas librement les fichiers privés des autres applications et qu'un UserService n'est pas un processus d'application Android normal disposant de toutes les API de Context.

**Déjà appliqué :** le projet a réellement utilisé Shizuku/Bionic pour ses qualifications natives, selon les preuves du 7 septembre. Ce n'est donc plus seulement une idée externe à essayer. Shizuku apporte le lancement et un contexte d'exécution documenté ; il n'ajoute pas `CONFIG_USER_NS` ou `CONFIG_PID_NS` à un noyau qui en est dépourvu. Inclure son SDK ne donne pas à lui seul une autorisation ADB persistante après redémarrage.

## Rapport avec les recherches déjà faites dans FoldGPT

Documents relus : `docs/research/android-native-constraints-2026-09-06.md`, `bionic-native-route-2026-09-07.md`, `kernel-extension-options-2026-09-07.md`, `capabilities/05-shizuku.md`, `ordinary-uid-execution-20260908.md`, ainsi que les contrats locaux de l'exécuteur.

- Les correctifs de chemins **Termux Bash** sont déjà incorporés à notre Bash Bionic, avec leurs empreintes dans `tools/executor/bionic-runtime/bash-inputs.json` et les sources adjacentes. Référence précédemment lue : [recette Termux Bash](https://github.com/termux/termux-packages/blob/master/packages/bash/build.sh).
- Le runtime **CPython Android officiel** est déjà utilisé et empaqueté dans notre APK. Référence conservée : [CPython Android 3.14.7](https://github.com/python/cpython/blob/v3.14.7/Doc/using/android.rst). Ces deux liens proviennent des recherches antérieures relues localement, pas d'une nouvelle récupération distante aujourd'hui.
- Les documents du noyau expliquent pourquoi reconstruire seulement le binaire Bubblewrap ne fournit pas les namespaces absents. Aucun comparable lu ne démontre leur création depuis une application ordinaire sans changer le noyau.
- Un autre fork, [wallentx/codex-termux](https://github.com/wallentx/codex-termux/blob/dev/README.md), a également été lu : automatisation des releases et branche dédiée aux patches Android, avec un lien vers 0.124.0-alpha.3-termux. Le README général conserve beaucoup d'instructions upstream ; sans vérification de ses patches/artefacts, il est moins probant que DioNanos pour notre version actuelle.

## Décision proposée à la tâche principale

Conserver le test Android r21 déjà prêt comme prochain arbitre du projet Python dans l'interface réelle. En parallèle ou si le contrôleur GNU devient le prochain blocage identifié, **comparer les patches Bionic/V8 de DioNanos à notre moteur 0.153.4** et établir un petit plan de portage du contrôleur séparé. Cette nouvelle source peut éviter de reconstruire seul une chaîne V8 Android ; elle ne justifie ni une promesse de réussite immédiate ni l'abandon du test r21 déjà préparé.

Avant une intégration éventuelle, le critère est un binaire Bionic de provenance vérifiée, version/protocole compatibles, puis le même test réel de création, tests, build, lecture/édition et reprise sur le Fold. Les forks CLI, les pages web et les succès de compilation ne remplacent pas ce critère.
