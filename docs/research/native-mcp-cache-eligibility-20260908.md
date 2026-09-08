# Éligibilité des services Node au démarrage différé

Revue statique du moteur canonique `work/worktrees/FoldgptEngine` et du client
installé `26.901.41600`, après identification des scripts dans
`work/process-pressure-20260908/node-identities-r28.json`. Aucun appel au
téléphone, aucune modification du moteur ou du client, aucun lancement de serveur.

## Résultat

Les deux contributions identifiées ne sont **pas exclues par principe** de
`LazyWhenCached`. Le gestionnaire global enregistre normalement
`unified-computer-use` comme `Plugin`, alors que l’exclusion vise uniquement une
source gagnante `SelectedPlugin` explicitement sélectionnée par une capability
root de conversation. Le sélecteur de modèles d’artefacts est injecté par le main
comme configuration `mcp_servers.openai_artifact_template_picker`.

En revanche, les deux déclarations observées omettent un `cwd` explicite. Le cache
ajoute alors le dossier réel de la conversation à son identité. Un cache rempli
dans un projet ne couvre donc pas automatiquement les autres projets. Changer
seulement `Eager` en `LazyWhenCached` réduit les reprises disposant d’un catalogue
valide de **même identité** ; cela ne garantit pas la réduction pour cinq dossiers
distincts, après un redémarrage du moteur ou après expiration du cache.

## Prédicat exact du moteur

Dans `codex-rs/codex-mcp/src/connection_manager.rs:258` et `:559`, en dehors d’une
connexion existante déjà réutilisable :

```text
defer_startup =
    startup_policy == LazyWhenCached
    AND previous.is_some()
    AND NOT winning_source_is_SelectedPlugin(server_name)
    AND tool_catalog_cache_context exists
    AND current_tools() contains at least one tool
        allowed by the configured tool filter
        AND tool_is_model_visible(tool)
```

`previous.is_some()` n’exige pas une connexion précédente de ce même serveur :
un runtime neuf est créé vide, puis `replace()` fournit `Some(empty_set)`.
Le cache partagé du processus peut donc servir dès la première publication d’une
nouvelle session. Une reconnexion explicite utilise `None` et reste immédiate
(`codex-mcp/src/runtime.rs:259`).

L’exclusion de provenance utilise les **sources gagnantes** du catalogue résolu
(`codex-mcp/src/catalog.rs:585`). Installer un plugin ou le rendre disponible par
défaut n’est pas la même chose que le sélectionner pour une conversation.
Une sélection explicite ultérieure peut cependant remplacer cette provenance :
les seuls chemins de script relevés dans r28 ne prouvent pas la source gagnante
de chaque runtime. Il faut conserver cette exclusion existante.

`omit_tools_from: ["code_mode", "deferred"]` dans le plugin CUA ne correspond
pas à ce démarrage différé : ce réglage désigne les surfaces d’exposition des
outils. Ici, `tool_is_model_visible` lit seulement `_meta.ui.visibility` ; sans
ce champ l’outil est visible, avec ce champ la liste doit contenir `model`.

Un serveur requis dormant avec un catalogue existant n’est pas démarré par
`validate_required_servers` (`connection_manager/required.rs:26`). Il demeure
`NotStarted` dans `connection_statuses`. L’appel réel passe par
`McpServerConnection::client()`, déclenche le démarrage et attend son résultat.
Les erreurs de première utilisation restent de vraies erreurs. Le cache retire
les annotations influençant permissions et parallélisme ; seule la connexion
vivante fournit ces annotations.

## Identité et durée du cache

`codex-mcp/src/tool_catalog_cache.rs` définit un cache partagé en mémoire par
`McpManager`, de capacité 32 identités et de durée 30 minutes. Le cache survit aux
sessions individuelles, pas à l’arrêt du processus app-server.

Pour les transports stdio concernés, l’identité comprend :

- le nom du serveur, sa commande, ses arguments et son `cwd` configuré ;
- les valeurs `env`, les déclarations `env_vars` et les valeurs courantes des
  variables héritées explicitement déclarées ;
- `environment_id`, les capacités d’elicitation et les extensions MCP clientes ;
- l’identité par pointeur faible de l’`Environment` résolu ;
- le `local_process_cwd` du runtime lorsque le transport n’a pas de `cwd` explicite.

Des variables stdio provenant d’un environnement distant empêchent la création
du contexte de cache actuel. Les exclusions OAuth/headers concernent la branche
HTTP, pas ces deux serveurs stdio. Le champ de version de protocole explicitement
haché dans cette fonction appartient à HTTP ; ne pas décrire cet ensemble comme
un fingerprint complet de tous les octets exécutables. Pour stdio, un chemin
versionné dans les arguments et les valeurs d’environnement différencient les
versions lorsqu’ils changent ; le contenu du script n’est pas haché ici.

Le serveur peut refuser le partage via
`initialize.capabilities.experimental["codex/tool-catalog-cache"].cacheable=false`.
Cette réponse invalide le snapshot pour cette identité. L’absence de ce refus
n’exige pas un opt-in positif. Un catalogue manquant, expiré, refusé ou sans outil
autorisé et visible entraîne la découverte réelle et le démarrage normal.

## Contributions effectivement inspectées

### `unified-computer-use` / `cua_repl`

Le manifeste livré contient `enabled:false`, mais le main installé possède le
gestionnaire `Gi`, qui met à jour la copie active `.mcp.json` après sélection des
surfaces disponibles. Il remplace notamment commande, arguments, `env_vars`,
`CUA_REPL_NODE_REPL_PATH` et `CUA_REPL_ENABLED_SURFACES`. La valeur du manifeste
livré ne décrit donc pas l’état courant du plugin démarré.

`scripts/launch.mjs` lit les ressources du plugin, compose les descriptions des
outils selon les surfaces, puis lance immédiatement un enfant `node_repl` avec
`stdio:inherit`. Différer ce serveur évite donc aussi le démarrage de cet enfant
tant que le serveur reste inutilisé. Le launcher transmet les signaux à l’enfant.

La déclaration ne fixe pas de cwd et le normaliseur de plugin hôte n’en ajoute
pas lorsqu’il est absent (`codex-mcp/src/plugin_config.rs`). Elle conserve les
outils `js` et `js_reset`. La voie de chargement global est
`core/src/config/mod.rs:1718`, via `McpServerRegistration::from_plugin`.

**Limite précise :** le handshake MCP n’est pas implémenté dans ce launcher, mais
dans le binaire `resources/cua_node/bin/node_repl`. Les fichiers copiés permettent
de prouver la configuration et l’arbre de lancement, pas de certifier sa réponse
`initialize` effective ni un cache chaud r28. Aucun refus de cache n’est ajouté
par le launcher inspecté. Une mesure du cache réel doit encore attester cette
condition et la provenance gagnante de `cua_repl`.

### `openai_artifact_template_picker`

Le main, fonctions `lk`/`uk`, construit `{command:node,args:[server.mjs],env:{...}}`
et l’injecte sous `mcp_servers.openai_artifact_template_picker`. Il ne fixe aucun
cwd. La variable `CODEX_ARTIFACT_TEMPLATE_SKILLS` peut différer selon les skills
détectés pour le dossier ; cette différence appartient légitimement à l’identité.

Le source complet `resources/artifact-template-picker/server.mjs` répond à
`initialize` avec `capabilities.tools.listChanged=false` et sans refus de cache.
`tools/list` retourne les schémas de `choose_artifact_template` et
`list_artifact_templates`, sans métadonnée les réservant à l’interface. Le mode
`--work` peut changer le schéma et figure déjà dans les arguments du transport.
La source inspectée est donc compatible avec le mécanisme de cache existant,
sous réserve de l’identité et des filtres réellement effectifs.

## Modification minimale applicable

Le choix central actuel est dans `core/src/session/mcp_runtime.rs:384` : seuls
les sous-agents reçoivent `LazyWhenCached`. Pour le moteur séparé FoldGPT,
sélectionner cette politique aussi pour les sessions racines suffit à rendre les
deux types de contribution **éligibles**, sans changer leurs fichiers, leurs
outils, les clés de cache, les exclusions ou leur authentification. Cette variante
minimale affecte aussi les nouvelles sessions racines dont le cache est chaud.

Pour limiter strictement le changement aux reprises, mémoriser à la construction
de `Session` le fait `matches!(initial_history, InitialHistory::Resumed(_))`, puis
utiliser cette politique conservée dans `build_mcp_runtime_input`, y compris lors
des publications suivantes. Un choix uniquement dans l’installation initiale
serait insuffisant si le rafraîchissement suivant repasse en `Eager` avant tout
appel d’outil. Le reconnect explicite garde sa sémantique `previous=None`.

Cette modification doit commencer par une vérification dans **le même dossier,
le même app-server et avec la même configuration** : découverte initiale réelle,
plusieurs reprises sans nouveau processus, mêmes outils visibles, puis premier
appel réel avec démarrage unique et résultat valide. Tester ensuite les identités
différentes, le cache froid/expiré, le refus serveur, la sélection explicite d’un
plugin, la reconnexion et les appels concurrents. Ne pas supprimer le cwd de la
clé ou fixer un cwd factice pour obtenir artificiellement des cache hits.

Pour attester les décisions sans exposer de secrets, une trace du moteur peut
enregistrer : nom du serveur, source gagnante, politique, présence de `previous`,
présence d’un contexte, motif de cache manquant/expiré/refusé, nombre d’outils
visibles et décision finale. Comparer des identités calculées en mémoire suffit ;
ne pas journaliser les valeurs d’environnement ni les credentials.

## API d’état qui peut fausser la mesure

`mcpServerStatus/list` n’est pas un simple lecteur de PID :
`app-server/src/request_processors/mcp_processor.rs:328` appelle un collecteur
qui crée des connexions temporaires `Eager` avec `previous=None`, **même avec
`threadId` et `detail:toolsAndAuthOnly`**. Le statut de connexion du vrai thread
est lu ensuite. Ce sondage peut lui-même démarrer les services et réchauffer un
cache avec une autre identité de capacités clientes.

Pendant la mesure des démarrages évités, employer le relevé des processus et les
événements existants, ou une lecture directe du `connection_statuses` déjà prévu
pour être sans effet de démarrage. Un résultat catalogue provenant de l’API
globale ne démontre pas à lui seul que la session cible utilisait le cache.
