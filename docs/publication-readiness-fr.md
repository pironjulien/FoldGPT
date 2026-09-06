# FoldGPT : état avant publication

Point du 6 septembre 2026. Ce document décrit le prototype et les conditions de
publication ; il ne constitue pas une validation d'APK ou une promesse de garantie.

## Ce qui peut être montré

Le client officiel Linux ARM64 et son interface Codex fonctionnent dans FoldGPT
sur le Samsung Fold, avec exécution ARM64 sur son CPU et rendu Adreno. Les points
noirs reproduits dans les paramètres ont été corrigés et les parcours de référence
ont passé les contrôles visuels. Le clavier Samsung, le lancement du coffre et
les opérations de base du navigateur intégré ont des preuves sur le téléphone.

Cela permet une démonstration explicitement présentée comme un prototype.
La construction d'un projet complet dans une tâche modèle ordinaire protégée,
l'installation autonome et les mises à jour préservant les données restent des
conditions non satisfaites pour annoncer une bêta utilisable.

La contribution démontrée est le portage de l'environnement de travail desktop
officiel et de ses outils sur Android sans root. Il existe déjà des applications
d'IA et de l'inférence locale sur téléphone. Le rendu GPU du client ne prouve pas
que les poids du modèle Astra sont exécutés sur l'Adreno : l'emplacement du modèle
doit être distingué de celui de l'interface et des commandes.

## Réponses aux vérifications demandées

| Question | État établi |
| --- | --- |
| Un projet complet a-t-il été créé, compilé et testé par Astra sur le Fold ? | Aucune preuve complète par la route normale protégée. Les tests existants sont des composants, fixtures et échanges de protocole. |
| Les logs sont-ils sans erreur ? | Non. Une lecture récente de 2000 lignes du runtime montre le manifeste officiel HTTP 404, l'échantillonneur Electron dont `ps` ne peut pas lire l'heure de démarrage système, des refus `pthread_getschedparam` et un endpoint GCM obsolète. Leur impact doit être qualifié. Le défaut bwrap de l'ancien chemin reste documenté. Les échecs précédents sont conservés ; un test plus récent n'efface pas leur historique. |
| Le nouveau moteur fonctionne-t-il ? | L'acquisition native protégée a passé ses 17 tests Android. Le nouveau cycle de vie a passé 20 tests Android avec collecte indépendante ; sa composition avec le transport est une étape distincte. Ce n'est pas encore la route d'une tâche modèle ordinaire. |
| A-t-on testé la mise à jour du client officiel ? | Le nouveau paquet 26.901.51231 est authentifié et son téléchargement/cache passe sur le Fold. Il n'a pas remplacé le client actif ; compte, projets et reprise après mise à jour ne sont pas qualifiés. |
| A-t-on testé les mises à jour FoldGPT ? | Des remplacements de l'APK de développement via ADB ont fonctionné. La signature et le canal de distribution, ainsi que le cycle complet de mise à jour/retour de version, restent à qualifier. |
| Astra sait-elle qu'elle travaille sur Android ? | La carte d'environnement est en cours de raccordement. Son chargement dans une vraie tâche doit être observé avant de le déclarer acquis. |
| Les SMS sont-ils accessibles ? | Aucun outil SMS Android n'est actuellement raccordé. L'application n'hérite pas des données privées des autres applications. |

## Ordre de travail et critères de sortie

1. Composer le moteur de fichiers et de processus protégés, le pont natif et la
   route effectivement sélectionnée par le client officiel. Vérifier commandes,
   stdin, sorties, annulation, descendants et refus d'accès avec la politique
   réelle, puis le shell, les programmes dynamiques et les capacités nécessaires.
2. Raccorder une carte de l'environnement aux instructions chargées par Codex :
   téléphone hôte, Linux invité, chemins, programmes, navigation, protections,
   limites, preuves datées et outils réellement exposés. Vérifier le chargement
   dans une nouvelle tâche sans donner la réponse dans son message initial.
3. Faire créer un projet réel dans cette tâche, installer ses dépendances,
   compiler, lancer les tests, appliquer une modification et ouvrir le résultat
   local avec le navigateur intégré. Inspecter les fichiers et les sorties
   indépendamment de la réponse du modèle, puis corréler les logs à ce parcours.
4. Terminer l'installation autonome et séparer les données durables des versions
   remplaçables. Tester l'interruption/reprise, le démarrage et l'authentification
   depuis une zone dédiée vide en conservant le prototype courant.
5. Qualifier la mise à jour du client officiel, du runtime et de l'APK avec leurs
   trois identités séparées : signatures, lancement, commandes, même compte,
   mêmes fichiers, coffre intact et récupération en cas d'échec. Un rollback de
   programme ne doit pas écraser un profil converti par une version plus récente.
6. Vérifier tâche active pendant pliage/verrouillage/reprise, transferts navigateur,
   authentification et pages locales. Préparer ensuite APK signé, inventaire des
   composants/licences et démonstration correspondant exactement aux tests passés.

## Extension Android après le fonctionnement général

La carte décrit les capacités ; elle ne les accorde pas. Les futures fonctions
Android passent par des outils natifs nommés et bornés : sélection de documents,
partage, état du téléphone puis, selon les permissions réellement disponibles,
contacts, calendrier, notifications ou SMS. Chaque outil doit distinguer absent,
permission requise, disponible et refusé, et supporter la révocation.

Les données de messageries tierces ne deviennent pas accessibles parce que
FoldGPT est installé. Lecture et envoi sont des capacités distinctes ; la
construction d'un connecteur n'autorise pas un envoi de message. Aucun outil ne
doit proposer root, modification du bootloader, désactivation de SELinux ou
modification du système Android. Les vérifications actuelles indiquent Verified
Boot green, SELinux Enforcing et Knox warranty bit zéro, sans garantie commerciale
inférée de ces seules valeurs.

## Références

- [Périmètre public et résultats détaillés](../PUBLICATION.md)
- [Architecture, installation et mises à jour](install/end-to-end-architecture.md)
- [Acquisition HTTPS réelle](../tools/install/https-acquisition/README.md)
- [Cycle de vie des commandes natives](../tools/executor/native-process-lifecycle.md)
- [Chargement officiel des instructions Codex](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
