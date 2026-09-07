# Audit du contrôleur GNU et de l’exécuteur Bionic : chemins ExecutorOnly

Date : 2026-09-07. État : audit des sources sur PC, sans modification Rust, build ni accès au téléphone.

## Conclusion

Le moteur possède déjà les interfaces nécessaires pour envoyer une commande modèle et un `apply_patch` à un exécuteur distinct. Il ne possède pas encore le routage complet permettant à son environnement **local** de travailler dans un dossier qu’il ne peut pas ouvrir lui-même. Le refus explicite de `ControllerPathAccess::ExecutorOnly` protège aujourd’hui cette limite. Retirer ce refus ou déclarer `Shared` ne corrigerait pas les chemins restants.

La prochaine preuve utile est une boucle app-server réelle : ouvrir un projet dont les fichiers sont inaccessibles au contrôleur, lire ses instructions, créer et modifier des fichiers, exécuter Bash → Python, tester et construire un artefact, puis le relire par l’interface. Un test où contrôleur et exécuteur partagent effectivement les fichiers ne prouve pas cette propriété.

Cette intégration est un bloc de travail distinct de la qualification du noyau/SELinux Android et du bootstrap Shizuku. Une compilation ARM64 réussie ne démontre aucune de ces deux propriétés.

## Sources et périmètre

Le moteur audité est le **working tree** `C:\Dev\FoldgptEngine`, basé sur `rust-v0.153.4`, HEAD `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`, avec des modifications et fichiers locaux non commités. Les lignes ci-dessous désignent ce working tree lu pendant cet audit ; elles ne désignent pas uniquement le tag upstream et peuvent évoluer après édition.

Le backend audité est `C:\Dev\ChatgptFold\tools\executor`, HEAD observé `32dca0d601fbea3d25bbed1cc52e7297740e68e4`. Les résultats Android antérieurs ne sont pas réinterprétés ici ; aucun statut de processus, mémoire ou téléphone n’a été mesuré par cet audit.

Les chemins abrégés `core/`, `exec-server/`, `app-server/`, `config/`, `shell-command/` ci-dessous sont tous relatifs à **`C:\Dev\FoldgptEngine\codex-rs\`**. Les liens renvoient aux fichiers complets du moteur. Les chemins `tools/` sont relatifs à **`C:\Dev\ChatgptFold\`**.

L’inventaire concerne les routes nécessaires à l’exécution, aux fichiers et à l’initialisation du projet. Il n’est pas un inventaire exhaustif de chaque processus auxiliaire Git, hook, MCP, plugin, aperçu ou terminal du produit.

## Les trois propriétés à conserver distinctes

- **Localité du produit** : le runtime tourne physiquement sur le Fold. `Environment::local_with_runtime` conserve `remote_client: None` ; `is_remote()` reste donc faux.
- **Responsable des protections** : `SandboxOwner::Executor` signifie que le backend natif applique la politique complète. Cela ne dit rien de la visibilité des fichiers par le contrôleur.
- **Visibilité des chemins** : `ControllerPathAccess::ExecutorOnly` signifie que les chemins annoncés sont ceux de l’exécuteur et que le contrôleur doit passer par ses interfaces. Un chemin POSIX convertible en `AbsolutePathBuf` peut rester inaccessible au processus GNU.

Ces distinctions existent dans [local_runtime.rs](C:/Dev/FoldgptEngine/codex-rs/exec-server/src/environment/local_runtime.rs:35), notamment les méthodes `process_sandbox_owner`, `filesystem_sandbox_owner` et `controller_path_access` aux lignes 75, 84 et 93. Il ne faut pas remplacer mécaniquement tous les `is_remote()` par le même prédicat : certains sélectionnent le transport réseau, d’autres le filesystem, d’autres le shell.

## Priorité 0 — enregistrement et métadonnées réelles

| Route | Preuve actuelle | Contrat manquant ou réutilisable |
| --- | --- | --- |
| Enregistrement local | [environment.rs:291](C:/Dev/FoldgptEngine/codex-rs/exec-server/src/environment.rs:291), `from_snapshot_with_runtime` : refus si `include_local=false`, puis refus `ExecutorOnly` aux lignes 307–313. | Garder le refus tant que les routes obligatoires restent directes. L’état « runtime prêt » ne vaut pas preuve d’accès filesystem ni preuve de nettoyage. |
| Point d’injection | [environment_bootstrap.rs:33](C:/Dev/FoldgptEngine/codex-rs/exec-server/src/environment_bootstrap.rs:33), `build_with_local_runtime`. Le bootstrap doit déjà avoir démarré et authentifié le runtime ; une configuration Noise-only est refusée. | Réutiliser cette injection, avec identité du vrai runtime et transports possédés. Elle n’authentifie pas Shizuku à elle seule. |
| Démarrage de l’application | [app-server/src/lib.rs:573](C:/Dev/FoldgptEngine/codex-rs/app-server/src/lib.rs:573) construit encore via `EnvironmentManager::from_env` ou `from_codex_home`. | Le point d’injection n’est pas encore choisi par ce chemin de production. Le raccordement doit refuser un bootstrap indisponible, sans retomber sur le lancement GNU/bwrap. |
| Transport réutilisable | [exec_server_runtime.rs:52](C:/Dev/FoldgptEngine/codex-rs/exec-server/src/environment/exec_server_runtime.rs:52), `ExecServerLocalRuntime::connect` accepte des streams authentifiés, installe `RemoteProcess::for_local_runtime` et `RemoteFileSystem::for_local_runtime` aux lignes 72–73. | Le mot `Remote` désigne ici l’adaptateur RPC réutilisé ; il n’oblige pas à déclarer le Fold distant. Le propriétaire conserve les streams et le cycle de vie. Pas de replay implicite après rupture. |
| Shell, home, tmp, OS, capacités | [environment_selection.rs:632](C:/Dev/FoldgptEngine/codex-rs/core/src/environment_selection.rs:632) lit `environment.info()` seulement si `is_remote()`. La branche locale, lignes 661–668, prend shell, home et tmp du contrôleur et suppose snapshot V2 via `cfg!(unix)`. | Un runtime injecté doit fournir ses vraies métadonnées. `Environment::info()` et `force_info()` délèguent déjà au runtime, dans [environment.rs:944](C:/Dev/FoldgptEngine/codex-rs/exec-server/src/environment.rs:944) et :1002. Ne pas supposer une capacité Android à partir de la cible GNU. |

Le backend RPC sait déjà publier des métadonnées explicites : `tools/executor/exec_server.py:295–319` tire les capacités du backend et refuse leur injection dans le dictionnaire d’information. Son autodétection de shell à `:268–278` décrit le processus serveur ; un déploiement Bionic doit fournir un shell **effectivement admis par son mapping**, pas seulement un binaire trouvé dans le PATH.

## Priorité 1 — cwd, configuration, instructions et fichiers

### Configuration du projet

[ConfigManager::load_config_layers](C:/Dev/FoldgptEngine/codex-rs/app-server/src/config_manager.rs:264) appelle `load_config_layers_state(LOCAL_FS.as_ref(), ...)` aux lignes 268–269. Le chargeur de couches accepte pourtant déjà `&dyn ExecutorFileSystem` dans [config/src/loader/mod.rs:132](C:/Dev/FoldgptEngine/codex-rs/config/src/loader/mod.rs:132). `Config::load_config_with_layer_stack` accepte aussi cette interface dans [core/src/config/mod.rs:3144](C:/Dev/FoldgptEngine/codex-rs/core/src/config/mod.rs:3144).

Il faut séparer les fichiers du contrôleur — compte, configuration utilisateur, état — des couches du projet appartenant à l’exécuteur. Envoyer tout le `codex_home` au broker du workspace serait une erreur inverse. Il faut conserver la provenance et les règles de confiance des couches projet lors du routage.

Le chargeur effectue encore des lectures et metadata avec `sandbox=None` (`config/src/loader/mod.rs:608,704,1562,1592,1728,1747`) ainsi que des canonicalisations natives pour les clés de confiance et `.codex` (`:1451,1706,1740`). Même après injection de `ExecutorFileSystem`, ces canonicalisations et l’autorité de lecture doivent être adaptées. Un échec de canonicalisation remplacé par la même chaîne n’établit pas l’identité réelle du chemin executor.

### AGENTS.md et contexte des lectures

[agents_md.rs:71](C:/Dev/FoldgptEngine/codex-rs/core/src/agents_md.rs:71) obtient déjà le filesystem de l’environnement. La découverte des parents/markers et les lectures utilisent cette interface (`:133,146,210,246`). C’est réutilisable.

En revanche, `:72–76` supprime le contexte de sandbox lorsque la politique autorise la lecture intégrale ; `:94–99` peut ensuite seulement journaliser une erreur de lecture sans instruction chargée. Le backend natif strict exige un contexte managed complet. Il faut un contrat réel de lecture d’initialisation, sans faire disparaître silencieusement les instructions du projet et sans remplacer `None` par une autorisation shell universelle.

### FS de l’interface

[FsRequestProcessor::file_system](C:/Dev/FoldgptEngine/codex-rs/app-server/src/request_processors/fs_processor.rs:53) renvoie déjà le filesystem de l’environnement local. `read_file`, `write_file`, `create_directory`, `get_metadata`, `read_directory`, `remove` et `copy` passent cependant `sandbox=None` (`:64–189`).

Le backend `tools/executor/native_files.py:401–409` appelle systématiquement `prepare_policy_intent` puis `parse_context`, vérifie le mapping de workspace et décide les droits. `native_file_streams.py:242–247` fait de même pour `fs/open`. `policy_intent.py:96` et `tools/policy/managed_policy.py:343–361` exigent un objet complet et n’acceptent que `managed`, filesystem restreint et intention réseau restreinte. Ces routes ne sont donc pas directement compatibles avec le contrat UI sans contexte.

Contrat à construire : opérations humaines de l’interface, lectures du contrôleur et opérations du modèle ont des autorités distinctes. L’origine doit être établie côté serveur/bootstrap et liée à la connexion et à la requête, pas choisie librement par un champ du modèle. Les limites Android et le mapping du workspace restent appliqués. Une requête sans contexte ne doit pas devenir arbitrairement « tout autoriser » ni être faussement présentée comme une commande modèle protégée.

### apply_patch

Le chemin principal est déjà bien placé : [handlers/apply_patch.rs:390](C:/Dev/FoldgptEngine/codex-rs/core/src/tools/handlers/apply_patch.rs:390) sélectionne le filesystem, calcule le contexte puis appelle `verify_apply_patch_args_with_mode` à :413. Le runtime [runtimes/apply_patch.rs:153](C:/Dev/FoldgptEngine/codex-rs/core/src/tools/runtimes/apply_patch.rs:153) consulte `filesystem_sandbox_owner`, conserve le contexte et appelle `apply_patch_with_options` à :180.

La préparation conserve les décisions d’approbation dans [core/src/apply_patch.rs:22](C:/Dev/FoldgptEngine/codex-rs/core/src/apply_patch.rs:22). Les vérifications de chemins dans [safety.rs:121](C:/Dev/FoldgptEngine/codex-rs/core/src/safety.rs:121) projettent encore les `PathUri` en chemins natifs, mais la normalisation visible à :135–149 est lexicale. Pour GNU/Linux et Android POSIX, la conversion seule ne prouve ni ne nécessite que les fichiers soient partagés. La véritable autorité et la résolution sûre doivent rester côté backend.

Il n’y a pas lieu de reconstruire un faux programme `apply_patch` qui exécuterait une chaîne shell. Réutiliser la bibliothèque et `ExecutorFileSystem`, conserver les erreurs et les modifications partielles réellement commises. Vérifier create/update/delete/move avec un dossier réellement invisible au contrôleur, ainsi que les refus des chemins protégés.

## Priorité 2 — shell et boucle Bash → Python

| Route | Preuve | Travail restant |
| --- | --- | --- |
| Commande du modèle | [process_manager.rs:1192](C:/Dev/FoldgptEngine/codex-rs/core/src/unified_exec/process_manager.rs:1192) choisit `attempt.env_for_exec_server` si le sandbox appartient à l’exécuteur ; :1245–1256 utilise `get_exec_backend` et le vrai contrat ExecParams. | Conserver cette voie et la politique portable entière. Elle évite déjà le besoin de transformer la commande avec bwrap côté contrôleur. |
| Choix du shell | [unified_exec.rs:99](C:/Dev/FoldgptEngine/codex-rs/core/src/tools/handlers/unified_exec.rs:99) appelle le helper local si le modèle fournit un shell ; [shell_detect.rs:329](C:/Dev/FoldgptEngine/codex-rs/shell-command/src/shell_detect.rs:329) redécouvre le binaire avec `get_shell`, donc filesystem/PATH du contrôleur. | Pour le runtime injecté, valider le type demandé par rapport au vrai shell executor et utiliser son chemin admis. `Shell::from_environment_shell_info`, [shell.rs:62](C:/Dev/FoldgptEngine/codex-rs/core/src/shell.rs:62), construit déjà le shell sans probe contrôleur. |
| Mode du shell | `core/src/tools/handlers/unified_exec.rs:146–155` choisit Direct seulement pour remote ; `exec_command.rs:248–281` réserve aussi le traitement spécial du shell demandé aux remotes. | Faire dépendre ce choix de la capacité réelle du runtime. Ne pas injecter zsh-fork ou un shell GNU dans un exécuteur Bionic. |
| Snapshot V1 | [shell_snapshot.rs:70](C:/Dev/FoldgptEngine/codex-rs/core/src/shell_snapshot.rs:70) évite seulement les remotes ; cwd devient natif, puis filesystem Tokio et `Command::new` à :287 tournent côté contrôleur. | Capturer/restaurer le vrai environnement et le vrai shell côté executor. Ne pas annoncer une capture faite sur l’autre côté comme celle du workspace. |
| Snapshot V2 | [unified_exec/shell_snapshot.rs:73](C:/Dev/FoldgptEngine/codex-rs/core/src/unified_exec/shell_snapshot.rs:73) préchauffe selon `is_remote` et capacité ; construit ensuite un vrai `ShellSnapshotRequest` et passe par le backend. | Interface à réutiliser, mais Bionic refuse encore `shellSnapshot`. Publier une capacité fausse n’est pas une implémentation. L’absence de cette capacité doit rester explicite jusqu’à son développement ; ne pas désactiver globalement la fonctionnalité pour annoncer le port terminé. |

`tools/executor/bionic-supervisor/processes.py:66–89` est une vraie sous-classe du backend processus, avec `_run` à :173 pour les exécutables dynamiques. Elle **hérite** de `_start` dans `native_processes.py:336–353`, qui refuse TTY, snapshots et réseau géré, vérifie l’exécutable admis et exige un contexte matching-cwd. Le commentaire « static native profile » de l’erreur héritée ne signifie pas que son `_run` Bionic est encore limité aux exécutables statiques.

`bionic-supervisor/factory.py:6–24` reçoit le mapping d’exécutables et runtime du bootstrap. Il impose les chemins de workspace réellement natifs ; `processes.py:72–73` refuse une autre représentation annoncée. La compatibilité `chdir` passe par le shim indépendant attesté, dont la provenance est vérifiée. Ces contrats ne permettent pas de mapper arbitrairement un faux `/workspace` vers un dossier invisible et d’affirmer `Shared`.

La façade `bionic-supervisor/qualification_factory.py:105–123` ne laisse passer qu’un unique diagnostic exact, puis sa lecture/terminaison. `qualification_factory_v11.py` ne change que l’identité de base. Cette façade n’est pas la connexion de production à laquelle envoyer un shell choisi par le modèle. L’activer comme si elle acceptait le projet Python produirait un refus attendu, pas une preuve de défaut du moteur natif général.

Le README du backend documente encore des opérations de namespace fichier refusées (rename/link/symlink, certaines mutations par FD), les alias git/worktree, les exécutables créés dans le workspace, le réseau et TTY. Le test Python proposé peut prouver un périmètre précis ; il ne prouvera pas automatiquement pip avec réseau, compilateurs arbitraires ou tous les projets Git. Il faut choisir un build réel, vérifier ses sorties et déclarer exactement ses dépendances, sans remplacer les opérations indisponibles par un succès simulé.

## Priorité 3 — autres routes requises pour l’expérience complète

Ces routes ne bloquent pas nécessairement chaque commande Python sans TTY, mais restent à intégrer avant de présenter le produit comme entièrement fonctionnel.

| Fonction | Source exacte | Contrat à conserver |
| --- | --- | --- |
| `command/exec` de l’interface | [command_exec_processor.rs:312](C:/Dev/FoldgptEngine/codex-rs/app-server/src/request_processors/command_exec_processor.rs:312) prépare encore un ExecRequest contrôleur ; [command_exec.rs:271](C:/Dev/FoldgptEngine/codex-rs/app-server/src/command_exec.rs:271) lance directement PTY/pipe. `require_local_environment` ne vérifie que la présence du local. | Router vers ExecBackend avec la vraie politique et le vrai cwd, conserver flux, caps, stdin, annulation, terminaison et dimensions de terminal. |
| `process/spawn` de l’interface | [process_exec_processor.rs:74](C:/Dev/FoldgptEngine/codex-rs/app-server/src/request_processors/process_exec_processor.rs:74) vérifie le local ; :310–324 lance directement PTY/pipe. | L’existence d’un local injecté ne doit jamais faire tourner ces commandes dans le contrôleur GNU par accident. TTY nécessite une implémentation native réelle. |
| `/shell` utilisateur | [tasks/user_shell.rs:136](C:/Dev/FoldgptEngine/codex-rs/core/src/tasks/user_shell.rs:136) prend le local, :157 convertit cwd, :166–180 prépare snapshot/env contrôleur ; :210–246 construit `PermissionProfile::Disabled`, `SandboxType::None` et appelle directement `execute_exec_request`. | Upstream distingue cette commande explicitement humaine des outils modèle. Préserver cette distinction et les limites UID/SELinux ; ne pas interpréter son accès comme un droit root ni le présenter comme le sandbox managed du modèle. |
| Surveillance filesystem | [fs_processor.rs:196](C:/Dev/FoldgptEngine/codex-rs/app-server/src/request_processors/fs_processor.rs:196) délègue à FsWatchManager ; [fs_watch.rs:87](C:/Dev/FoldgptEngine/codex-rs/app-server/src/fs_watch.rs:87) enregistre un chemin hôte dans FileWatcher. | Déporter la surveillance réelle et ses événements, conserver ownership connexion, unwatch, ordre des notifications et nettoyage. Une surveillance hôte silencieuse n’observe pas le workspace executor. |
| Watcher des skills | [skills_watcher.rs:108](C:/Dev/FoldgptEngine/codex-rs/app-server/src/skills_watcher.rs:108) exclut seulement remote, puis convertit les racines executor en chemins du watcher contrôleur à :126–130. | Conserver découverte et mise à jour des skills sur le bon filesystem. |
| Attribution et métriques plugins | [process_manager.rs:528](C:/Dev/FoldgptEngine/codex-rs/core/src/unified_exec/process_manager.rs:528), [turn_context.rs:369](C:/Dev/FoldgptEngine/codex-rs/core/src/session/turn_context.rs:369), [plugins/metrics.rs:24](C:/Dev/FoldgptEngine/codex-rs/core/src/plugins/metrics.rs:24) choisissent chacun executor versus contrôleur par `is_remote`. | Réutiliser `plugin_attribution_for_executor_command`, `resolve_metrics_operation_in_filesystem` et le sidecar executor selon la visibilité réelle. Ne pas désactiver plugins/métriques pour contourner leurs accès aux fichiers. |
| Hooks | [session/mod.rs:4661](C:/Dev/FoldgptEngine/codex-rs/core/src/session/mod.rs:4661) construit `HooksConfig` avec le shell du seul environnement local, mais sans interface backend dans cette structure. | Le shell ne doit pas devenir un chemin Bionic lancé directement par les hooks du contrôleur. Auditer leur implémentation de lancement et garder séparés hooks du contrôleur et du projet. Ce dernier audit de dépendance reste à faire. |

## Ordre d’implémentation proposé et preuves de sortie

1. **Bootstrap et identité, sur PC** : implémenter la sélection du runtime réellement authentifié avec `ExecutorOnly`, en conservant le verrou d’activation jusqu’aux adaptations requises. Informations de shell/home/tmp/capacités issues du runtime. Aucun changement d’identité locale en remote pour forcer les branches.
2. **Autorités filesystem et configuration** : connecter les lectures projet, cwd, metadata, confiance et AGENTS aux bonnes interfaces. Définir les opérations UI/bootstrap séparément des requêtes modèle, avec autorité détenue par le serveur et refus explicites. Conserver compte/configuration du contrôleur de son côté.
3. **Boucle outils du modèle** : utiliser la route ExecBackend déjà ajoutée, compléter sélection du shell et snapshots côté executor, puis vérifier `apply_patch` via le backend. Ne pas mettre le contrôleur dans le workspace pour faire passer le test.
4. **Preuve PC indépendante de l’UID du contrôleur** : dossier accessible au processus executor mais réellement refusé au contrôleur ; app-server JSON-RPC réel ; vérifier ouverture du projet, instructions, création/modification/relecture des fichiers, Bash → Python, unittest et artefact de build. Instrumenter les accès directs pour démontrer leur absence sur les chemins executor. Conserver un test négatif de refus backend sans repli local.
5. **Cycle de vie et sémantique des refus** : stdout/stderr et stdin réels, EOF, interruption, timeout, rupture de transport, descendants, état de quarantaine. Une disparition de PID ne remplace pas l’attente du vrai propriétaire ni un rapport de nettoyage final. Les erreurs FS/sandbox ne doivent jamais devenir « fichier absent » ou dossier vide fabriqué.
6. **Routes UI et fonctionnalités restantes** : command/exec, process/spawn, shell humain, TTY, watchers, plugins/hooks puis opérations Git et réseau nécessaires au périmètre produit. Les capacités non réalisées doivent rester décrites comme non réalisées ; un test partiel n’autorise pas une déclaration de victoire générale.
7. **Activation Android distincte** : seulement après les preuves PC et la qualification native appropriée au contexte UID2000/SELinux, raccorder le runtime de production puis répéter le projet Python depuis l’interface. Ce document n’autorise ni ne lance cette activation et ne réévalue pas le verrou actuel du Fold.

## Ce qui est prouvé par cet audit

La source contient un verrou `ExecutorOnly` explicite, des interfaces réutilisables, les branches directes décrites et des refus natifs précis. Les fixtures du moteur `core/tests/suite/injected_local_runtime.rs:72` et `exec-server/tests/native_local_runtime.rs:140` déclarent encore `ControllerPathAccess::Shared` ; elles ne valident donc pas l’invisibilité du filesystem au contrôleur.

Aucun test Rust ni backend n’a été exécuté pour cet audit documentaire. Aucun résultat Android, aucun nettoyage, aucune stabilité du téléphone et aucun fonctionnement modèle → Python complet n’est nouvellement démontré ici. Les changements à réaliser sont identifiés ; ils ne sont pas effectués par ce rapport.
