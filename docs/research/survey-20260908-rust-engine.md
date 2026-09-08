# Revue vivante des moteurs ARM64 Android et des hôtes d’interface

Date : 2026-09-08. Périmètre : moteurs Rust/Codex Android, Bionic, V8/Node, Electron et interfaces reliées à app-server. Recherche menée en lecture seule avec les outils GitHub : recherches de dépôts/code/issues, puis lecture des fichiers et commentaires primaires. Le navigateur intégré n’était pas disponible ; aucun navigateur externe n’a été ouvert.

Cette revue ne prétend pas couvrir tout Internet. Les versions ci-dessous sont celles des fichiers réellement lus sur les branches indiquées, et ne doivent pas être présentées comme les dernières versions publiées sans interrogation supplémentaire des releases. Aucun binaire n’a été téléchargé ou exécuté, aucune installation ni activité sur le Fold n’a été réalisée. Les seuls tests de cette revue sont huit contrôles de cohérence des sources, détaillés plus bas.

## Conclusion utile pour FoldGPT

Un moteur Codex natif Android avec un vrai V8 est aujourd’hui une piste concrète de réemploi. Les sources actuelles de **DioNanos/codex-termux et de wallentx/codex-termux contiennent toutes deux le vrai code-mode-runtime**. Affirmer que wallentx utilise encore forcément un stub serait périmé pour la branche examinée.

Ces ports règlent plusieurs incompatibilités réelles : ABI Android/Bionic, artefacts V8 Android cohérents avec les options Cargo, PTY, chemins temporaires, recherche du véritable exécutable et particularités Termux. **Ils ne reconstruisent pas les fonctions de bwrap.** Dans le sélecteur de sandbox lu chez DioNanos, Android aboutit à l’absence de sandbox Codex de plateforme. La fonction correspondante est identique à celle de l’amont OpenAI lu le même jour : ce n’est donc pas une preuve d’un nouveau confinement Android fourni par le fork.

La compatibilité du moteur, la possibilité de lancer des processus depuis une application Android moderne et la conservation de l’interface officielle sont trois validations distinctes. Une réussite en ligne de commande Termux ne les établit pas simultanément. Le V8 sandbox traite la mémoire V8 ; il n’applique pas à lui seul les droits d’accès aux fichiers et processus des outils.

L’amont OpenAI contient un vrai protocole expérimental de jumelage remote-control, mais la vérification produit effectuée ensuite par le coordinateur dans le navigateur intégré rétrograde cette piste : **la documentation Remote prend en charge des hôtes ChatGPT desktop macOS/Windows et indique que la configuration mobile ne peut pas partir de la CLI Codex**. Elle ne documente pas un hôte Android local. Cette piste reste une référence de code, hors du plan d’essais actuel ; aucun jumelage n’est à lancer. Cela ne démontre pas une impossibilité d’ingénierie dans le code.

## Composants et valeur de réemploi

| Composant inspecté | Version et licence constatées | Problème effectivement traité dans les sources | Réemploi précis et limite |
| --- | --- | --- | --- |
| DioNanos/codex-termux, main | Cargo 0.153.3 ; README base OpenAI rust-v0.153.2 ; Apache-2.0 déclaré | Compilation aarch64-linux-android/API29 ; V8 réel ; adaptations PTY/chemins/exécutable | Meilleure base récente de comparaison des deltas Android. Ne pas importer aveuglément les changements de verrouillage et de mise à jour ; pas de sandbox Codex Android fourni par le sélecteur. |
| wallentx/codex-termux, branche wallentx/termux-target | Cargo 0.149.0 ; Apache-2.0 déclaré | Runtime V8 réel et audit des sites de verrouillage | Source de delta Android alternatif. La branche dev est surtout l’automatisation, avec un badge plus ancien ; utiliser la branche de compatibilité pour la comparaison. |
| Artefacts rusty_v8 du port DioNanos | Manifeste : 146.4.0, 147.4.0, 149.2.0 et 150.4.0 ; profil ptrcomp_sandbox_release présent pour 150.4.0 | Archive Android et bindings correspondant au sandbox mémoire/pointer compression attendus | Réutiliser le manifeste et la vérification SHA-256, puis auditer provenance et licences des composants V8 avant distribution. Présence du manifeste ne prouve pas que les archives téléchargées/builds fonctionnent sur le Fold. |
| Rust, documentation Android officielle | aarch64-linux-android, Tier 2, bibliothèque standard disponible | Chaîne NDK et ABI native Android officiellement définies | Confirme que compiler nativement pour Android est une voie normale. Ce support ne rend pas un ELF GNU/Linux ARM64 compatible avec Bionic. |
| nodejs-mobile/nodejs-mobile, main | En-tête source Node 18.20.4 ; texte de licence Node de type MIT lu, notices tierces à conserver | Intégration de libnode.so dans une application Android via JNI | Architecture utile pour héberger Node sans terminal externe. Version source vieillissante ; compatibilité avec le Node attendu par l’interface à mesurer. Les permissions des processus enfants restent un problème distinct. |
| Electron officiel, main et issue 48761 | README : MIT ; versions binaires Android non proposées dans la matrice lue | Aucun hôte Android officiel établi | L’issue fournit une proposition avec hello-world annoncé par son auteur, pas une distribution Android maintenue et compatible avec l’interface officielle. |
| friuns2/codex-mobile | package.json 0.1.87, nom npm codexapp, Node >=18, MIT | Pont HTTP/WebSocket et stdio vers app-server ; UI Vue mobile | Le mécanisme de pont est concret. C’est une autre interface ; dépendances facultatives node-pty et fonctions annexes à auditer. Ne pas installer pour prétendre conserver l’interface officielle. |
| DioNanos/codex-vl | README : 0.153.2-vl.2 sur next ; ligne conservatrice 0.144.5 ; Apache-2.0 déclaré | Autre dérivé Android avec fonctions ajoutées et documentation du jumelage mobile | Source de piste protocolaire. Delta produit plus grand que codex-termux ; ne constitue pas la base minimale recommandée. |
| openai/codex, protocole remote-control | Snapshot vivant ; API pairing marquée expérimentale dans le résultat de recherche du code amont | Jumelage manuel, app-server distant, gestion des clients | Référence expérimentale de faible priorité. Produit Remote documenté pour hôtes desktop macOS/Windows, sans configuration mobile depuis CLI/IDE ; relais distant, aucun support Android-local établi. Aucun essai de jumelage retenu. |

## Ce que contient réellement le port Codex Android

### V8 n’est plus un substitut vide

Les deux fichiers code-mode-runtime/Cargo.toml lus déclarent directement :

~~~toml
v8 = { workspace = true, features = ["v8_enable_sandbox"] }
~~~

Les deux lib.rs exposent les modules runtime, service, session_runtime et l’implémentation InProcessCodeModeSession. Le v8_init.rs de DioNanos initialise véritablement la plateforme V8 et V8 lui-même, avec ICU. V8JitMode::Disabled applique --jitless ; Enabled est le défaut. Le choix est figé à l’initialisation, donc il ne faut pas supposer pouvoir basculer librement après le premier démarrage.

Le helper fetch_rusty_v8_android.py choisit par défaut **ptrcomp_sandbox_release**, vérifie la présence des deux empreintes dans le manifeste, puis compare les empreintes de l’archive et du fichier de bindings téléchargés. C’est une correction pertinente : une archive V8 ordinaire peut être incohérente avec les features Cargo même si une compilation aboutit.

Le manifeste 150.4.0 annonce pour ce profil :

- Archive SHA-256 : 6fb02f1669dbb85f7265a1cba05ac31b683295be7db9651f1db2b7b082794a09.
- Bindings SHA-256 : 639421ae6a0d125dde076cdb4c5d5b3afc9e3ce764acad4a772b7182ea77da66.

Ces empreintes sont des valeurs de référence lues, **pas le résultat d’une vérification locale des archives**.

### bwrap et le confinement des outils restent une question séparée

Le BUILDING.md de DioNanos contient CODEX_SKIP_VENDORED_BWRAP=1. À lui seul ce réglage dit seulement de ne pas construire le bwrap embarqué. L’élément décisif est le code de sandboxing/src/manager.rs, lignes 62-76 :

~~~rust
pub fn get_platform_sandbox(windows_sandbox_enabled: bool) -> Option<SandboxType> {
    if cfg!(target_os = "macos") {
        Some(SandboxType::MacosSeatbelt)
    } else if cfg!(target_os = "linux") {
        Some(SandboxType::LinuxSeccomp)
    } else if cfg!(target_os = "windows") {
        if windows_sandbox_enabled {
            Some(SandboxType::WindowsRestrictedToken)
        } else {
            None
        }
    } else {
        None
    }
}
~~~

Le target Rust Android vaut android et non linux, même si le noyau appartient à la famille Linux. select_initial appelle ensuite unwrap_or(SandboxType::None). Le module bwrap est aussi sous cfg(target_os = "linux"). La fonction ci-dessus est textuellement identique à celle du snapshot OpenAI comparé.

Cela permet de conclure que **ce sélecteur ne fournit pas de backend de sandbox Android**. Cela ne permet pas de conclure que toute l’application est dépourvue des protections Android, ni de prédire le comportement de tous les niveaux de politique Codex sans exécution. Pour FoldGPT, il reste nécessaire de raccorder les commandes à un exécuteur Android dont les droits réels correspondent à ceux annoncés.

### Autres adaptations réutilisables, avec leur portée

- Le shim openpty Android appelle posix_openpt, grantpt, unlockpt, ptsname_r et open. Il résout une différence libc concrète. Les retours tcsetattr/ioctl optionnels sont ignorés dans le code lu : tester le redimensionnement, le mode terminal, l’annulation et la disparition des groupes enfants.
- CODEX_SELF_EXE et le bundle libc++_shared.so avec RUNPATH $ORIGIN traitent respectivement le chemin du vrai ELF et ses dépendances dynamiques.
- La documentation des patches remplace des usages de /tmp par temp_dir(), évite ps -o lstart absent du toybox visé et lit le champ 22 de /proc/<pid>/stat.
- L’ouverture du navigateur de connexion utilise termux-open-url. À remplacer par un lancement Android explicite dans un hôte APK ; cela n’autorise pas à modifier l’application officielle.
- Plusieurs sites tolèrent Unsupported pour les verrous. Une tolérance n’est pas une implémentation de l’exclusion mutuelle. Le daemon codex-vl lu retourne explicitement Ok(true) après ENOTSUP/EOPNOTSUPP, en acceptant une dégradation de l’exclusion. Importer ce comportement sans qualification violerait notre exigence de corriger la cause.
- Le script wallentx termux-lock-audit.sh est un audit statique heuristique : par défaut il produit un rapport sans faire échouer la commande ; --strict vérifie des marqueurs de traitement des erreurs. Il ne prouve pas la cohérence de deux writers concurrents.
- Le port intervient dans les mécanismes d’auto-update du moteur pour éviter l’installation d’un binaire officiel incompatible avec son fork. Cette maintenance du moteur séparé doit être distinguée de la mise à jour normale du paquet ChatGPT officiel.
- Clipboard Android désactivé dans les adaptations décrites ; audio CLI temps réel retiré en amont et historiquement non utilisable sans contexte JavaVM/Activity. Ces différences contredisent une affirmation de parité universelle.
- La note de patch sur les certificats précise qu’un ancien changement Android a été retiré après évolution amont et que la confiance native n’a pas été mesurée. Ne pas convertir une affirmation générale du README sur TLS en preuve sur le Fold.

Les documents du même dépôt sont décalés entre eux : Cargo annonce 0.153.3, patches/README.md décrit encore une base 0.147.0, et BUILDING.md contient une ancienne note 0.146.0. Les décisions d’intégration doivent partir d’un commit figé et du code, puis vérifier le build correspondant.

## Node embarqué et interface

La FAQ nodejs-mobile décrit un modèle réellement exploitable dans un APK : Node exécute sa boucle libuv sur un thread séparé, pendant que la WebView exécute sa propre boucle. Node ne tourne pas « dans » la WebView. L’exemple JNI native-lib.cpp prépare argv et invoque node::Start(argc, argv), en redirigeant stdout/stderr par pipes vers logcat.

Limites explicites de cette documentation :

- Une seule instance Node par processus.
- Modules npm préparés et embarqués au build de l’application.
- Addons natifs à compiler pour Android et chaque architecture ; build scripts ou hypothèses de plateforme parfois à adapter.
- child_process.spawn/fork susceptibles de rencontrer des refus de permission.
- Fichiers inscriptibles limités au stockage autorisé de l’application.
- Support d’internationalisation limité selon cette FAQ.

Le header source lu vaut 18.20.4 ; le BUILDING.md mentionne NDK24. Il faut évaluer actualisation et dépendances avant de choisir ce moteur pour une interface exigeant Node22 ou une ABI plus récente. L’exemple JNI est une preuve d’architecture, pas un wrapper prêt à embarquer tel quel avec gestion complète des ressources.

Chez friuns2/codex-mobile, le pont lu est concret : src/server/codexAppServerBridge.ts lance le processus avec trois pipes, découpe stdout par lignes, transmet les objets JSON-RPC et rejette les requêtes en attente à la sortie du processus. httpServer.ts expose /codex-api/ws et sert le build Vue. Le projet possède aussi beaucoup de fonctions hors pont, dont gestion des jetons, intégrations tierces et chemins de transcription ; le périmètre de cette revue ne les valide pas. La réutilisation raisonnable serait l’étude du transport et de ses tests, pas l’adoption globale comme substitut silencieux à l’expérience officielle.

## Electron Android : possibilité d’ingénierie, maturité non établie

Le README officiel liste les plateformes de distribution macOS, Windows et Linux. Linux ARM64 n’implique pas Android/Bionic.

L’issue officielle **electron/electron#48761**, ouverte le 2025-11-03 et fermée le 2025-11-04 avec la raison **not_planned**, est plus informative qu’une affirmation générale d’impossibilité :

1. L’auteur dit avoir obtenu un hello-world dans un émulateur Android.
2. Le mainteneur jkleinsc répond que l’équipe ne dispose pas des ressources, de l’infrastructure et des mainteneurs mobiles nécessaires ; les cycles Chromium/Node et les APIs propres au desktop augmenteraient la maintenance.
3. Le mainteneur encourage un fork externe et envisage de petites contributions à faible coût de maintenance, sans annoncer de support officiel.
4. L’auteur cherche ensuite des sociétés ou une communauté intéressées.

Cette source interdit de dire « un port Electron Android est impossible ». Elle ne livre pas une implémentation maintenue permettant de prendre notre interface officielle et de la faire fonctionner sans adaptations. Une recherche bornée chez l’auteur n’a pas localisé de dépôt réutilisable ; ce résultat vide ne démontre pas son inexistence.

L’issue **45485** propose aussi un mode serveur et un renderer externe, avec une preuve de concept QRookieNode référencée. C’est une proposition à étudier si un inventaire IPC rend cette voie utile ; cette revue n’a pas exécuté le PoC ni établi qu’il s’agit d’une feature Electron officielle. Le dépôt au nom prometteur wind-hx/electron-android ne fournit, dans le README lu, que des instructions electron-vue desktop : son nom n’est pas une preuve de runtime Android.

## Jumelage avec le client mobile officiel : référence expérimentale rétrogradée

Le README codex-vl mentionne /remote-control pair et un code demandé par ChatGPT mobile. Cette affirmation de fork a été confrontée au code amont :

- openai/codex contient remote_control_cmd.rs avec start, stop et pair ; pair appelle start_remote_control_pairing et affiche le code manuel.
- Le protocole expose remoteControl/pairing/start avec une annotation expérimentale.
- Le client de daemon inspecté utilise un socket app-server, envoie manual_code: true et traite une réponse RemoteControlPairingStartResponse.
- Le transport amont enroll.rs envoie un POST vers remote_control_target.pair_url avec bearer_auth(remote_control_token). Il valide notamment la correspondance server_id/environment_id de la réponse.

Il y a donc une vraie implémentation publique à étudier, pas seulement une idée de plugin. Le chemin lu dépend toutefois d’un enrôlement distant et n’établit pas une API localhost exposée par ChatGPT Android.

**Mise à jour produit vérifiée le même jour par le coordinateur, en direct dans le navigateur intégré :** [developers.openai.com/codex/remote-connections](https://developers.openai.com/codex/remote-connections) redirige vers [learn.chatgpt.com/docs/remote-connections](https://learn.chatgpt.com/docs/remote-connections). Dans « Before you set up Remote », la page indique exactement :

> Remote supports hosts running the ChatGPT desktop app on macOS and Windows

> Mobile setup starts from the app; you can't set it up from the Codex CLI or IDE extension.

Le produit décrit un relais sécurisé distant, pas un transport localhost vers notre moteur Android. Le code CLI expérimental constaté et le support produit documenté sont donc deux preuves différentes. **Remote ne fournit pas aujourd’hui une solution Android-local documentée pour FoldGPT.** La piste est rétrogradée à la veille de compatibilité, sans essai de jumelage à lancer ; le prochain test utile reste le lancement Bionic depuis un service Android ordinaire. Cette conclusion ne signifie pas que le code rendrait un tel développement impossible. Aucun code de jumelage réel, token ni compte utilisateur n’a été sollicité pendant cette recherche.

## Tests minimaux proposés, non exécutés dans cette revue

Ordre destiné à fermer les portes rapidement avant un développement lourd :

1. **Compatibilité moteur seule.** Sur un binaire Android épinglé, vérifier ELF/interpréteur/dépendances et lancer app-server avec initialize, puis un vrai appel JS code-mode comportant await et sortie observable. Exécuter sous l’UID cible du futur hôte, pas seulement via adb shell ou Termux. Critère : échange complet et résultat réel, sans stub.
2. **Chaîne de commandes protégée.** Raccorder le moteur au mécanisme FoldGPT autorisé ; créer, tester et construire le petit projet Python demandé. Vérifier cwd, environnement, stdout/stderr, code retour, fichier généré, refus d’écriture hors périmètre et absence d’accès aux données d’authentification. Le succès de Python doit être accompagné des refus attendus ; un sandbox None renommé ne passe pas.
3. **Processus et durée de vie.** Un enfant Python qui engendre un sous-processus, une commande PTY, un resize et une annulation ; contrôler le groupe de processus après fin/annulation. Puis relancer après destruction/recréation du service Android. Critère : aucun descendant survivant et sessions isolées selon le contrat.
4. **V8/JIT.** Vérifier le profil d’archive exact au build, puis effectuer le même mini-test code-mode dans le mode permis par le Fold. Un éventuel mode jitless doit être mesuré et déclaré ; il ne remplace pas le confinement des outils.
5. **Hôte d’interface si encore nécessaire.** Inventorier les APIs Electron/IPC réellement utilisées par le renderer officiel, puis tester les chemins essentiels dans un hôte Android : connexion, tâche, streaming, commande, fichiers, annulation, reprise. Pour Node JNI, tester fs/réseau et child_process séparément sous l’UID de l’app. Une WebView qui affiche une page ne prouve pas le fonctionnement des APIs desktop.
6. **Concurrence et mise à jour.** Deux sessions écrivant les mêmes états, contention des verrous, interruption puis reprise et décalage de version moteur/client. Critère : exclusion réelle ou architecture à writer unique vérifiable, récupération sans corruption et erreurs explicites sur une version incompatible.

Le jumelage Remote a été retiré de cette liste après la vérification produit ci-dessus. Aucune tentative de jumelage n’est prévue dans ce lot.

Ces tests se font avec les protections normales du téléphone, sans root, flash ni déverrouillage. Les tests susceptibles de modifier la sécurité du système ne sont pas proposés.

## Contrôles de cohérence réellement effectués

Huit contrôles programmatiques sur les contenus GitHub fraîchement récupérés, tous vrais :

| Contrôle statique | Résultat |
| --- | --- |
| DioNanos expose module runtime et InProcessCodeModeSession | PASS |
| wallentx/termux-target expose module runtime et InProcessCodeModeSession | PASS |
| Cargo wallentx active v8_enable_sandbox | PASS |
| Helper DioNanos choisit ptrcomp_sandbox_release et compare SHA-256 | PASS |
| Exemple JNI appelle réellement node::Start | PASS |
| Pont web lance trois pipes et route les lignes stdout vers handleLine | PASS |
| Jumelage amont utilise POST pair_url et bearer_auth | PASS |
| Fonction get_platform_sandbox identique entre DioNanos et OpenAI lus | PASS |

Il s’agit de contrôles de présence et de cohérence de code, **pas de tests de fonctionnement ni d’une qualification de sécurité**. L’absence d’un résultat de code search n’a jamais été utilisée comme preuve d’absence d’implémentation.

## Sources primaires effectivement lues

Les SHA indiqués sont des **SHA de blob renvoyés par fetch_file**, pas des commits de release. Les URLs de branche restent mobiles ; les SHA consignent le contenu observé.

### Moteurs Android / Rust / V8

- [DioNanos README](https://github.com/DioNanos/codex-termux/blob/main/README.md), blob 01cc44f79ba13bf4212d9543d5bd079524695086 : version annoncée, périmètre Android et limites.
- [DioNanos Cargo](https://github.com/DioNanos/codex-termux/blob/main/codex-rs/Cargo.toml), blob 957c78343931c22ee55acf08005934a8ee18fc21 : version et licence workspace.
- [DioNanos code-mode Cargo](https://github.com/DioNanos/codex-termux/blob/main/codex-rs/code-mode-runtime/Cargo.toml), blob 5a4d9e1d0930806689a04bc5857b177656bd775b ; [lib.rs](https://github.com/DioNanos/codex-termux/blob/main/codex-rs/code-mode-runtime/src/lib.rs), blob 819636ef0da2d57ab8988395c0e8182d42a55955 : vrai runtime V8.
- [Initialisation V8](https://github.com/DioNanos/codex-termux/blob/main/codex-rs/code-mode-runtime/src/v8_init.rs), blob 0d00d9fad523611e3d99f1fdeacc38afe6d06d6c : JIT/ICU/initialisation.
- [Manifeste Android V8](https://github.com/DioNanos/codex-termux/blob/main/third_party/v8/android-artifacts.toml), blob 33721e2ec67f9ec21efffbbd56d60a9874cc4572 ; [helper de récupération](https://github.com/DioNanos/codex-termux/blob/main/scripts/fetch_rusty_v8_android.py), blob 1cfe4cfe8cff7deef8901fd2aaef3eb1147af587 : profil et empreintes.
- [BUILDING](https://github.com/DioNanos/codex-termux/blob/main/BUILDING.md), blob 8f0a80694f37bc9d94589b525a27c01127f20bc0 ; [patches](https://github.com/DioNanos/codex-termux/blob/main/patches/README.md), blob d0ce99c57158e4dd2cefc6d6a8715a2fac794077 : chaîne de compilation et deltas documentés, avec décalages de versions.
- [PTY Android](https://github.com/DioNanos/codex-termux/blob/main/codex-rs/utils/pty/src/pty.rs), blob 7b6ff981c207ffd7f5d2b3df6659ebbbca51447e : shim openpty et cycle de vie.
- [Sandbox lib](https://github.com/DioNanos/codex-termux/blob/main/codex-rs/sandboxing/src/lib.rs), blob fc390fdf951a8407e9d38b52b48121ba89df51d7 ; [manager](https://github.com/DioNanos/codex-termux/blob/main/codex-rs/sandboxing/src/manager.rs), blob 12456223921a4b2b78133071bb78ec0d37f7495f : cfg Linux et absence de backend Android dans le sélecteur.
- [Manager OpenAI comparé](https://github.com/openai/codex/blob/main/codex-rs/sandboxing/src/manager.rs), blob b633e8f7793f4a008ecb952adfb80dac8c415e84 : même sélecteur de plateforme.
- [wallentx README dev](https://github.com/wallentx/codex-termux/blob/dev/README.md), blob 9e26b8fae7268ad7125650026c80bcdacad6c643 : choix de branche.
- [wallentx Cargo de compatibilité](https://github.com/wallentx/codex-termux/blob/wallentx/termux-target/codex-rs/Cargo.toml), blob 898f13428fbbb143395c45ec4b2ea0e94979d0ce : version 0.149.0.
- [wallentx code-mode Cargo](https://github.com/wallentx/codex-termux/blob/wallentx/termux-target/codex-rs/code-mode-runtime/Cargo.toml), blob 5a4d9e1d0930806689a04bc5857b177656bd775b ; [lib.rs](https://github.com/wallentx/codex-termux/blob/wallentx/termux-target/codex-rs/code-mode-runtime/src/lib.rs), blob 819636ef0da2d57ab8988395c0e8182d42a55955.
- [wallentx audit locks](https://github.com/wallentx/codex-termux/blob/wallentx/termux-target/scripts/termux-lock-audit.sh), blob ac40f8e5724684059d93d9f4baf6ab75a45a7686.
- [Support Android Rust](https://github.com/rust-lang/rust/blob/main/src/doc/rustc/src/platform-support/android.md), blob 570379e1572484280561d31007a55ff066476423.

### Node / Electron / interfaces

- [nodejs-mobile README](https://github.com/nodejs-mobile/nodejs-mobile/blob/main/README.md), blob d674c5d3e8a413441c3cb42de36f221803bad7e4 ; [FAQ](https://github.com/nodejs-mobile/nodejs-mobile/blob/main/doc_mobile/FAQ.md), blob a5d2da96e10464dd46a29e0f02e1072933b59f70.
- [nodejs-mobile BUILDING](https://github.com/nodejs-mobile/nodejs-mobile/blob/main/doc_mobile/BUILDING.md), blob 85538bb866cd2ce98754d16c57714d5fb312f612 ; [version header, portion de définition](https://github.com/nodejs-mobile/nodejs-mobile/blob/main/src/node_version.h), blob 6e85c96f5482a5578d6a8b4b0cc07aff2388528f ; [licence, début](https://github.com/nodejs-mobile/nodejs-mobile/blob/main/LICENSE), blob 511343a8dfd4bbb58e1955787ea41481b56cc91d.
- [Exemple JNI native-lib.cpp](https://github.com/JaneaSystems/nodejs-mobile-samples/blob/master/android/native-gradle-node-folder/app/src/main/cpp/native-lib.cpp), blob 59f52a52ebd6de718617113ace86fe53c34fc990.
- [Electron README](https://github.com/electron/electron/blob/main/README.md), blob 128071b9bc690c361f62a12b180824f195832c7d.
- [Electron issue 48761](https://github.com/electron/electron/issues/48761), issue complète et commentaires lus ; [réponse mainteneur](https://github.com/electron/electron/issues/48761#issuecomment-3488144373) et [suivi auteur](https://github.com/electron/electron/issues/48761#issuecomment-3522382465).
- [Electron issue 45485](https://github.com/electron/electron/issues/45485), corps de proposition lu via recherche ; PoC référencé, non exécuté.
- [wind-hx/electron-android README](https://github.com/wind-hx/electron-android/blob/master/README.md), blob 1dfd2694b6ca1659120c8e2008348e0fd20521bf : exemple de résultat non probant.
- [codex-mobile README](https://github.com/friuns2/codex-mobile/blob/main/README.md), blob b5b2fe519be40b79e7ec94e9be6eec1c7501cb61 ; [package](https://github.com/friuns2/codex-mobile/blob/main/package.json), blob 84ee9d051242021c1ed6bf55dc231cb34bbfc44e ; [licence](https://github.com/friuns2/codex-mobile/blob/main/LICENSE), blob edc465fba051e24ae9761591fd72e2e6846f7133.
- [Pont app-server](https://github.com/friuns2/codex-mobile/blob/main/src/server/codexAppServerBridge.ts), blob da20b374d30f35356fc066d1a3c95bee33b8f51d, portions lancement/stdio/cycle de vie lues ; [HTTP/WebSocket](https://github.com/friuns2/codex-mobile/blob/main/src/server/httpServer.ts), blob 90f2cdbd2eb970db73c58f4953a5d3a0d0349b7b.
- [Autre UI zxia520/codex-web-ui README](https://github.com/zxia520/codex-web-ui/blob/main/README.md), blob f3a1c72baf39220f9ebe88e3b3f24bf548def0e5 : se déclare non officielle, MIT, Node22+, CLI requis ; ne démontre pas la conservation de l’interface officielle.

### Jumelage mobile

- [Documentation produit Remote](https://learn.chatgpt.com/docs/remote-connections), lue en direct par le coordinateur dans le navigateur intégré le 2026-09-08 après redirection de developers.openai.com/codex/remote-connections : hôtes desktop macOS/Windows, configuration mobile depuis l’application et non CLI/IDE, relais sécurisé distant.
- [codex-vl README](https://github.com/DioNanos/codex-vl/blob/main/README.md), blob 6883e17520a17d67e32d7b466dd3b8c1b098f151.
- [codex-vl daemon](https://github.com/DioNanos/codex-vl/blob/main/codex-rs/app-server-daemon/src/lib.rs), blob cc039a68e8da4090f4dab6ea6ef5f8f269825613 ; [client pairing](https://github.com/DioNanos/codex-vl/blob/main/codex-rs/app-server-daemon/src/remote_control_client.rs), blob 74c978f21930ed242b004c0213135ca730c3ed7d.
- [OpenAI daemon](https://github.com/openai/codex/blob/main/codex-rs/app-server-daemon/src/lib.rs), blob 49774272cf636f76411232b7b569bdb2f446e8f0 ; [CLI remote-control](https://github.com/openai/codex/blob/main/codex-rs/cli/src/remote_control_cmd.rs), blob bd0f16b82f04f1c5171b35e6fa45e53d8e933c99.
- [OpenAI remote-control transport](https://github.com/openai/codex/blob/main/codex-rs/app-server-transport/src/transport/remote_control/mod.rs), blob 32d8bf2ccf9cfd6a35dcc363bc5bf51a4ab91b86 ; [enrollment HTTP](https://github.com/openai/codex/blob/main/codex-rs/app-server-transport/src/transport/remote_control/enroll.rs), blob be10fffb84c7d960285fa05e4e7a37a787961e14.
- [Déclaration expérimentale de pairing](https://github.com/openai/codex/blob/ce254df05a3162a93d8f3357ff4dd86582c534b7/codex-rs/app-server-protocol/src/protocol/common.rs), extrait primaire renvoyé par code search au commit ce254df05a3162a93d8f3357ff4dd86582c534b7.
