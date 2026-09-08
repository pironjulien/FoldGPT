# Conversations reprises et libération des processus

L’augmentation de processus après des reprises RPC de maintenance peut provenir
du cycle normal de conservation des conversations. Une réponse réussie à
`thread/resume` charge une session et abonne la connexion appelante. La création
de cette session installe son runtime MCP, même sans nouveau tour utilisateur.
Cela ne prouve pas à lui seul l’origine de chaque PID : la corrélation avec les
identifiants de conversation et les processus observés reste une mesure distincte.

## Sources identifiées

Client réellement installé : `26.901.41600`, ASAR SHA-256
`1306be560e77fbfb68dd8b0bccac58d52396a3d445f12810a50438fb05f2e61d`.
Le renderer examiné est `app-initial-36a3a1b7313c.js`, SHA-256
`5e4b002d1b6a5cb2edef63e0e8bde74613d78124f487f054d7047744a501bcdc`.
Le moteur est le checkout `work/worktrees/FoldgptEngine`, HEAD
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`. Les empreintes des fichiers réellement
lus, y compris les modifications locales éventuelles, sont conservées dans
`work/desktop-audit-20260908/thread-lifecycle-evidence.json`.

## Ce que font les API

| Opération | Effet établi dans les sources |
| --- | --- |
| `thread/resume` | Reprend/charge le thread puis attache automatiquement un listener à `request_id.connection_id`. La session initialise son runtime MCP et son préchauffage. |
| `thread/unsubscribe` avec `{threadId}` | Retire l’abonnement de cette connexion uniquement. Retourne `unsubscribed`, `notSubscribed` ou `notLoaded`. Ne détruit pas immédiatement le runtime chargé. |
| `thread/closed` | Notification publiée après l’arrêt réussi et le retrait du runtime par le déchargement automatique. Elle apporte une preuve différente de la simple réponse `unsubscribed`. |
| Fermeture d’une connexion | Retire ses abonnements. Sur un serveur conservant d’autres connexions, cela ne signifie pas arrêt immédiat de tous les threads. |
| Fin normale du serveur en mode stdio à client unique | La fermeture stdio entraîne la sortie puis l’arrêt encadré de tous les threads. Le code prévoit aussi un arrêt forcé qui n’offre pas ce même nettoyage. |

Les sources du moteur inspecté ne déclarent pas de requête publique
`thread/unload` ou `thread/stop` équivalente à une fermeture immédiate. Une chaîne
`thread/stop` existe dans une table du renderer ; sa présence ne crée pas une API
dans ce moteur. Archiver/supprimer une conversation ou interrompre un tour n’est
pas une opération neutre de nettoyage de maintenance.

Références moteur, sous `codex-rs` :

- `app-server/src/request_processors/thread_processor.rs:1014` et `:3898` :
  unsubscribe et abonnement automatique de reprise.
- `app-server/src/thread_state.rs:490` : suppression par identifiant de connexion.
- `core/src/session/session.rs:1589` et `core/src/session/mcp_runtime.rs:104` :
  installation initiale du runtime MCP.
- `core/src/session/handlers.rs:402` : arrêt des tâches, processus, code mode,
  préchauffage et runtime MCP lors de la fermeture réelle.
- `app-server/src/lib.rs:1070` et `:1220` : fermeture stdio et arrêt des threads.

## Délais et conditions observés

Le renderer installé utilise `xtn`, son gestionnaire des conversations inactives.
Il conserve un thread propriétaire repris pendant **une heure** avant de le
désabonner automatiquement, lorsque ce thread n’a plus de vue active ni de
followers et ne doit pas rester chargé. Une activité, une demande en attente ou
une conversation vide non persistée peut modifier l’éligibilité. Le nombre
`btn=4` sert ici au calcul d’un dépassement journalisé ; la sélection retournée
reste celle des threads dont le TTL a expiré. Ce code n’impose donc pas une
éviction immédiate dès la cinquième conversation.

Après disparition du dernier abonnement, le moteur attend **trente minutes**
sans activité avant de fermer le thread. Le délai commence au plus tardif des
instants « aucun abonné » et « inactif ». Le listener vérifie à nouveau l’activité
avant l’arrêt. Un arrêt dépassant dix secondes laisse le thread chargé et émet
un avertissement ; la fermeture ne doit pas être annoncée si elle n’a pas abouti.
Le délai d’une heure du renderer et celui de trente minutes du moteur sont donc
deux mécanismes successifs, pas une garantie de délai global en présence d’activité.

Références : renderer ligne 1936, méthodes
`getInactiveOwnerConversationIdsToUnsubscribe`, `unsubscribeInactiveConversation`
et constantes `vtn`, `ytn`, `btn` ; moteur
`app-server/src/request_processors/thread_lifecycle.rs:7`, `:59` et `:423`.

## Fin correcte des vérifications de maintenance

Pour une reprise effectuée directement par RPC, conserver la connexion utilisée
et les seuls IDs effectivement repris par la maintenance. Une fois les contrôles
terminés, envoyer sur cette même connexion :

```json
{"method":"thread/unsubscribe","params":{"threadId":"ID_EFFECTIVEMENT_REPRIS"}}
```

L’enveloppe complète doit utiliser le transport déjà en service et un identifiant
de requête unique. Le pont officiel observé est le message renderer `mcp-request`
contenant la requête ; le main l’achemine via `handleClientRequest`. Le retour
`notSubscribed` demande de vérifier la connexion et l’état de chargement, sans
présumer que la session a été libérée. Enregistrer le résultat et observer
`thread/closed` ou la disparition du thread de `thread/loaded/list` pour établir
le déchargement, puis mesurer les processus restants.

Le helper renderer `unsubscribeInactiveConversation` contrôle d’abord que son
cache connaît le thread comme `resumed` et qu’il en possède le flux. Il peut donc
ignorer une reprise brute de maintenance qui n’a pas alimenté ce cache.
`discardConversationFromCache` peut interrompre une conversation active avant
unsubscribe ; ce n’est pas le bon appel aveugle pour nettoyer les vérifications.
Si le thread est actuellement utilisé par l’interface sur la même connexion,
laisser son gestionnaire normal gérer l’abonnement.

Pour des tests futurs nécessitant un retour immédiat à zéro session, utiliser un
serveur de validation distinct dont on ferme normalement l’entrée stdio après
avoir vérifié ses opérations. Dans le serveur de production, observer les délais
normaux ou fermer puis rouvrir normalement l’application lorsqu’aucun travail
n’est actif. Aucun arrêt de processus par nom, modification de l’application
officielle ou réglage arbitraire des délais n’est requis par cette analyse.

Cette inspection n’a envoyé aucune commande au téléphone et n’a exécuté aucun
nettoyage. Le résultat décrit des comportements présents dans les sources ; la
confirmation des PID libérés appartient à la vérification réelle sur le Fold.
