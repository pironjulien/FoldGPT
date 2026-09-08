# Pression de processus Android : deux corrections ciblées

Revue du moteur canonique `work/worktrees/FoldgptEngine`, sans modification de
ses sources ni commande sur le téléphone. Proposition du 8 septembre 2026.

## Cause établie et limite du comptage

Les deux relevés r26b contiennent respectivement **25 puis 45 processus de
l'UID 10412**. Le second ajoute `10 node`, `10 node_repl` et un
`codex-code-mode-host` ; un ancien `xfconfd` a disparu. La croissance accompagne
les cinq reprises de conversations réalisées pour la maintenance. À
`21:48:16.885`, Android commence effectivement à tuer les descendants avec
`Trimming phantom processes`, avant l'arrêt Java déjà corrigé.

Le moteur conserve une conversation sans abonné pendant 30 minutes sans
activité. Le délai de désabonnement de l'interface, confirmé séparément par la
revue d'`arm_engine`, est d'une heure. La reprise d'une conversation ordinaire
sélectionne actuellement le démarrage MCP immédiat. L'hypothèse directement
testable est donc une accumulation de services MCP démarrés pour des reprises
qui ne les utilisent pas, puis conservés par ces deux durées.

Le parent a relevé `max_phantom_processes=32` sur le Fold. **Ce plafond ne donne
pas 32 places réservées à FoldGPT** : les comptes d'UID incluent aussi des
processus Android gérés et ne sont pas le compteur global des descendants
surveillés par Android. Le nombre de processus n'est pas un budget de RAM.

## 1. Démarrage MCP à la première utilisation pour les reprises

C'est la première correction recommandée, car elle conserve les conversations
et leurs états existants. Réutiliser `McpStartupPolicy::LazyWhenCached` pour les
conversations racines reprises dans l'intégration FoldGPT : publier les
définitions d'outils du catalogue partagé, puis démarrer le serveur concerné
seulement lors de son premier appel. Ne pas déclarer un serveur « prêt » avant
sa véritable initialisation. Un serveur sans catalogue valide conserve la
découverte réelle ; un reconnect explicite reste immédiat.

Les mécanismes existent déjà :

- `core/src/session/mcp_runtime.rs:384` choisit `LazyWhenCached` pour les
  sous-agents et `Eager` pour les autres sources ;
- `codex-mcp/src/connection_manager.rs:258` et `:559` différèrent un serveur si
  sa configuration et son catalogue le permettent ; les plugins explicitement
  sélectionnés restent exclus de ce report ;
- `codex-mcp/src/tool_catalog_cache.rs:35` possède un cache de définitions partagé
  dans le processus, avec identités de transport, arguments, environnement,
  protocole et capacités ; `core/src/mcp.rs:74` en porte le propriétaire ;
- `core/tests/suite/mcp_tool_cache.rs:562` couvre déjà le démarrage immédiat des
  racines et différé des sous-agents avec de vrais serveurs de test.

**Portée testable :** remplir une fois le catalogue, reprendre cinq conversations
sans outil MCP, vérifier l'absence de nouveaux enfants ; appeler un outil dans
une conversation et constater un seul démarrage, une sortie réelle et le même
catalogue. Tester aussi cache froid/expiré, changement d'environnement ou
d'authentification, plugin sélectionné, appels simultanés et première utilisation
interrompue. Les états des conversations déjà utilisées doivent rester intacts.

**Risques :** il faut d'abord identifier les deux contributions qui lancent
`node/node_repl` et vérifier qu'elles autorisent le cache. Le cache peut varier
par répertoire ou configuration ; le réutiliser hors de son identité serait
incorrect. Cette correction évite le coût des outils inutilisés, mais ne réduit
pas celui de plusieurs sessions JavaScript réellement utilisées.

Le partage existant de MCP concerne les **définitions** et la réutilisation des
connexions d'un même runtime. Il ne prouve pas qu'un serveur MCP stateful accepte
plusieurs conversations sur une seule connexion. Partager aveuglément ces
connexions mélangerait potentiellement état JS, notifications et autorisations.
Le `codex-code-mode-host`, lui, possède déjà un hôte unique partagé et des sessions
isolées (`code-mode/src/remote_session.rs:35`, `core/src/thread_manager.rs:463`) ;
il ne représente qu'un processus dans le second relevé et n'est pas la source
des vingt nouveaux processus Node.

## 2. Libération anticipée des conversations réellement jetables

Compléter la première correction par une fermeture transactionnelle des
conversations devenues inutiles, en réutilisant `thread/closed`, plutôt qu'en
raccourcissant arbitrairement le délai de toutes les conversations.

La voie existe dans `app-server/src/request_processors/thread_lifecycle.rs` :
elle observe abonnements et activité, réserve `pending_thread_unloads`, attend
`shutdown_and_wait`, vérifie l'identité du runtime par
`remove_thread_if_matches`, puis émet `thread/closed`. Un délai dépassé laisse
le thread chargé. Les tests API existent dans
`app-server/tests/suite/v2/thread_unsubscribe.rs` et `thread_resume.rs`.

**Il manque un critère essentiel pour une éviction accélérée :** une conversation
inactive peut encore posséder un terminal ou un état JS. La fermeture centrale
(`core/src/session/handlers.rs:402`) arrête les tâches, termine les processus,
ferme Code Mode et MCP. `CodeModeSession` conserve explicitement les valeurs
entre cellules et n'expose pas de méthode qui certifie que la session est
jetable (`code-mode-protocol/src/session.rs:146`). « Aucun tour en cours » ne
suffit donc pas.

Ajouter une réservation de fermeture qui bloque les nouvelles admissions et
atteste, atomiquement, l'absence de tour actif ou en attente, de requête client,
de terminal vivant, de cellule active et d'état stateful à conserver. Pour une
première portée sûre, seules les conversations chargées pour lecture/maintenance
**sans aucune utilisation de runtime stateful** sont éligibles. Toute session
JS déjà utilisée reste protégée tant qu'un contrat explicite ne certifie pas
qu'elle est réinitialisée ou transférable. Ne pas reconstruire cet état à partir
du seul historique textuel.

Pour nos opérations de maintenance, employer les RPC de lecture lorsqu'ils
suffisent, puis apparier toute vraie `thread/resume` temporaire avec son
désabonnement. Cela ne modifie pas l'application officielle. Pour les vues
officielles encore abonnées, l'absence d'activité ne prouve pas l'absence d'un
client intéressé : une éviction sous pression demanderait un contrat additionnel
explicite entre cache d'interface et moteur, pas un désabonnement inventé.

**Portée testable :** fermeture d'une reprise inutilisée, `thread/closed` unique
après nettoyage, réouverture depuis le même historique ; aucune fermeture d'un
tour, d'un terminal, d'un JS utilisé ou d'un sous-agent actif ; courses
nouvel-abonné/nouveau-tour/fermeture et erreur de fermeture. Vérifier les PID
réels et la conservation de valeurs JS avec deux conversations distinctes.

**Risques :** la voie actuelle de fermeture interrompt délibérément les runtimes ;
elle ne doit être réutilisée qu'après le nouveau contrôle d'éligibilité. Le
véritable besoin de nombreuses sessions JS vivantes devra ensuite être géré
par admission/attente ou par un hôte multi-session qualifié. Les préserver
toutes tout en promettant un nombre illimité de processus serait incompatible
avec la limite Android observée.

Ces deux propositions conservent les outils et les données. Elles n'impliquent
ni changement du plafond Android ni désactivation d'une protection. Elles ne
sont pas encore implémentées ou qualifiées sur le Fold.
