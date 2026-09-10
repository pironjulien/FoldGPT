# FoldGPT r31 — démarrage et notifications

R31/versionCode21 est installée sur le Samsung Galaxy Z Fold `SM_F971B`.
L'ancien menu « Bureau non connecté / Réglages / Aide / Fermer » est remplacé
par un chargement automatique, puis par le client ChatGPT. La notification
« Commandes de l'affichage » et l'ancien libellé « Espace Linux actif »
ne sont plus publiés.

| Situation | Comportement |
| --- | --- |
| Ouverture | « Ouverture de ChatGPT… », puis le client sans choix intermédiaire. |
| Application active | Une notification silencieuse « ChatGPT est en cours d'exécution ». |
| Réponse en cours | « Une conversation en cours », ou le nombre de conversations actives. |
| Réponse terminée | Notification avec le titre affiché par le client et « Réponse disponible ». |
| Réponse interrompue | « Réponse interrompue », issue d'un événement réel d'interruption. |
| Clic sur une réponse | Ouverture de la conversation existante via le lien officiel du client. |
| Arrêt explicite | « Fermer ChatGPT » conserve le service jusqu'au nettoyage effectif, puis retire sa notification. |
| Échec du lancement | Message d'échec, « Réessayer » et diagnostic accessible. |

Les réglages de clavier, tactile et affichage restent disponibles dans le
raccourci « Réglages de FoldGPT » déclaré sur l'icône de lancement.
Les notifications de réponse masquent le titre sur l'écran verrouillé via
leur version publique ; le texte de la réponse n'est pas recopié.

## Implémentation

Le service Android possède l'unique notification de fonctionnement.
Un point d'extension restreint de `MainActivity` permet à FoldGPT de retirer
la notification d'affichage héritée sans changer le comportement par défaut
de Termux:X11. Son ancien canal FoldGPT est retiré.

Le chargement attend la découverte de la vraie fenêtre du client par `wmctrl`
et la connexion de la surface X11. Le signal porte un identifiant propre au
lancement : un fichier laissé par une session précédente ne suffit pas.
L'attente de fenêtre est bornée à 90 secondes, comme la préparation native.
Cette disponibilité désigne la fenêtre ; elle ne prétend pas que tout le
contenu réseau du client est déjà chargé.

`FoldConversationMonitor` suit les écritures des journaux officiels avec les
observateurs de fichiers Android et un thread Java. Aucun processus Linux
permanent n'est ajouté. Seuls les couples réels `task_started` /
`task_complete`, et les interruptions correspondantes, changent l'état.
Les journaux existants sont positionnés à leur fin au lancement pour éviter
de rejouer les anciennes notifications. Le titre vient de `session_index.jsonl`,
puis de la base locale en lecture seule si nécessaire.

## Vérification sur le téléphone

- APK compilée et installée sans désinstallation ni effacement de données.
  SHA-256 : `29de65e696af8b6144cb478ecfd049470ecf3293fb25db42ddfb4f95bbbe5154`.
- Le contrôle du paquet valide 91 bibliothèques natives, 2 447 fichiers de
  données Python et la fermeture des dépendances natives attendues.
  Ce contrôle statique est distinct des essais Android ci-dessous.
- Les **31 tests JVM** passent, dont les événements de conversations concurrentes,
  les doublons et la fin d'un ancien tour. Les différences Git passent le
  contrôle d'espaces.
- Démarrage normal sur l'écran intérieur réellement ouvert, sans extra de
  contournement de posture. Le chargement capturé ne contient aucun des anciens
  boutons. Après arrêt propre, la fenêtre apparaît au relevé à **8,33 secondes**.
  Cette mesure ponctuelle inclut les commandes de collecte ; ce n'est pas un benchmark.
- Deux vrais tours dans **« Analyser le logiciel »** produisent des résultats
  Python sous Android, UID10412. Le second confirme la transition complète
  de la notification pendant que l'Activity est en arrière-plan : fonctionnement,
  conversation active, puis réponse disponible avec le bon titre.
- Le client est ramené à son accueil avant de toucher la notification Android.
  Le clic ouvre ensuite la bonne conversation et retire sa notification de fin.
  Le regroupement intermédiaire visible est celui de Samsung/Android.
- L'activité des réglages s'ouvre et son retour conserve le service actif.
  Le raccourci statique est enregistré par Android ; le geste physique d'appui
  long sur l'icône n'a pas été utilisé pendant cet essai.
- Le bouton réel « Fermer ChatGPT » de la notification ferme proprement le
  propriétaire natif : état `closed`, nettoyage terminé, ancien PID disparu,
  aucune notification FoldGPT restante. La réouverture réussit.
- Une panne réelle de composant manquant est provoquée par le déplacement
  temporaire du seul script de lancement, conservé puis restauré dans un bloc
  `finally`. L'écran d'erreur apparaît ; toucher « Réessayer » après restauration
  ouvre le client. Le script restauré est identique octet pour octet.
- **197/197 fichiers de projets inchangés**, aucun ajouté ou supprimé par ces
  essais ; les **1 207 161 octets** d'historique antérieurs à l'installation
  gardent exactement leur empreinte. Les vrais tours de test sont ajoutés ensuite.
- État final vérifié : versionCode21, propriétaire natif `ready`, une seule
  notification de fonctionnement, client laissé ouvert.

Le script de lancement installé a l'empreinte
`c627b5642d01615b28a13071fd4775cb4225e7584293225a1486da342a85e36a`.
Il doit être livré avec l'APK pour le signal de disponibilité.

Les preuves locales sont dans
`C:\Dev\ChatgptFold\work\startup-notifications-20260909` :
`verification-summary.json`, `response-live-transitions.json`,
`notification-click-final.json`, `stop-final-via-notification.json`,
`r31-restart-launch.json`, `failure-retry.json`, `preservation.json`,
captures et événements complets des échanges 3 et 4.

## Portée et problèmes encore ouverts

Le suivi porte sur les conversations locales qui produisent ces événements
officiels. Les chats cloud sans journal local ne sont pas couverts par cet
observateur. L'interruption et le comptage concurrent sont vérifiés dans les
tests JVM ; le parcours réel Android exécuté ici utilise une conversation.
L'expiration exacte des 90 secondes n'a pas été attendue sur le téléphone.

La revue précédant cette correction, avec deux échanges supplémentaires dans
la conversation du téléphone, est conservée dans
`work/conversation-review-20260909/bilan.md`. Python et le terminal du modèle
fonctionnent, mais Git/Make/Node/npm indisponibles dans ce shell, les 404 du
runtime officiel et les incohérences de chemins/contexte restent ouverts.
Le filtre des avertissements Xlib et la conservation des états lors du
déchargement des conversations ne sont pas corrigés par r31.
Un comptage de processus dans l'UID ne démontre pas le respect du plafond global
Android ni une stabilité prolongée. Aucun réglage de protection Android n'a été
désactivé pour ces corrections.
