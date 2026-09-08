# Inventaire du client réellement installé

Le client du Fold contient **9 737 fichiers JavaScript collectés** : 7 176 dans
l’ASAR et 2 561 externes, tous analysés syntaxiquement sans erreur dans la copie
vérifiée. Le paquet de référence local
a été analysé séparément, ainsi que les deux grands bundles du renderer chargé.
Ce travail donne une base vérifiable pour identifier les besoins de FoldGPT ;
il ne prouve pas que chaque fonctionnalité fonctionne déjà sur Android.

L’[inventaire JSON](installed-client-inventory.json) contient les noms, paramètres
observés, implémentations de service, dépendances, positions et empreintes des
sources. Le [rapport de couverture](analysis-report.json) donne les corpus,
catégories complètes et noms dynamiques non résolus. Les sources officielles
n’ont été ni exécutées ni modifiées par cet inventaire.

## Quelle version a été analysée

| Source | Identification vérifiée |
| --- | --- |
| Copie de l’ASAR installé | Version `26.901.41600`, déclarée dans son propre `package.json` ; 292 764 321 octets ; SHA-256 `1306be560e77fbfb68dd8b0bccac58d52396a3d445f12810a50438fb05f2e61d`. |
| Paquet Debian de référence | Version `26.901.51231` ; SHA-256 du paquet `02a2f5c6cb69509c62abcbdd13c76b139cdb2ca9edde7537239ddde024077ea0` ; ASAR `4b34e3fec936b52641591644d0574f5f73f95d797d04b25f8ec60bc05378905a`. |
| Renderer observé via CDP | `app-initial-36a3a1b7313c.js` et `app-primary-804f738d362c.js`, égaux aux textes de l’archive installée après normalisation des fins de ligne CRLF/LF. Les octets des copies Windows diffèrent ; leurs empreintes restent distinctes. |
| Fichiers externes installés | 6 195 fichiers réguliers recensés, dont 57 ELF ; collecte de 1 363 441 152 octets, SHA-256 `d15cb1fdf1798bb3be22cfb2bdeab07a67178f814a9550631954f5f33207f106`. ASAR stable pendant la collecte. |

Les deux archives ont 8 985 entrées. Leur comparaison trouve 3 592 fichiers
intégrés identiques au même chemin, cinq fichiers différents au même chemin et
5 018 noms remplacés de chaque côté, notamment les assets nommés par empreinte.
Le catalogue de commandes, services et routes est stable entre ces deux versions
pour les catégories recensées, à l’exception d’une méthode RpcTarget
`acknowledgeReceipt` présente dans la référence et de noms liés aux reçus de crédit
plugin. Les noms minifiés d’expressions de routes et les imports de bundles nommés
par empreinte diffèrent également. Cette comparaison de noms ne prouve pas une
équivalence des comportements.

## Surfaces recensées

| Surface | Résultat installé | Interprétation |
| --- | --- | --- |
| Handlers fetch du main revu | 130 | Noms `vscode://codex/<nom>`, paramètres et fonction de traitement observés. Certains handlers peuvent retourner une indisponibilité. |
| Cas de messages reçus par le main | 168 | Branches de `kxe.handleMessage`. Comprend des cas sans action et des refus explicites ; ce ne sont pas 168 fonctions qualifiées. |
| Propriétés du service app-host | 95 | Services, indicateurs, valeurs conditionnelles ou absentes. Expressions d’implémentation conservées. |
| Méthodes publiques RpcTarget | 560 déclarations, 388 noms distincts | Détail par classe et paramètres dans `reviewedMainSurfaces.rpcTargetMethodsByClass`. Les noms seuls ne suffisent pas à identifier le bon service. |
| Registre intégré de commandes renderer | 25 | Table de callbacks explicitement revue ; d’autres commandes sont enregistrées par des composants ou calculées à l’exécution. |
| Chemins de routes statiques reconnus | 36 | Inclut les chemins relatifs ; les expressions de chemin et les imports dynamiques sont recensés séparément. |
| Réglages déclarés | 76 | 51 `read-write`, quatre `read-only`, 21 `hidden`, selon la définition de chaque réglage. |
| Noms littéraux de protocole moteur | 177 | Chaînes présentes dans le code ; chaque nom doit être rapproché de son appel, notification ou garde de version. |
| Cibles littérales de `require` | 2 114 | Mélange de modules Node, modules natifs et dépendances applicatives, y compris les distributions Node externes. Les imports ES sont également conservés dans les preuves brutes. |

Les catégories `Candidate` sont volontairement séparées. Par exemple un tableau
`args` peut représenter une commande système, les arguments d’une sous-commande ou
une donnée d’éditeur. Le script conserve sa provenance sans le convertir en faux
besoin exécutable. Les expressions dynamiques restent signalées ; aucune valeur
n’a été inventée pour compléter le catalogue.

## Points directement utiles au raccordement natif

| Besoin du client | Preuve et conséquence pour FoldGPT |
| --- | --- |
| Racines des projets locaux | `services.projects.editLocal({projectId,name,sources})` met à jour le même projet et avertit les fenêtres. Modifier seulement `project/update` côté moteur peut laisser des données de navigation incohérentes. |
| Dossier des nouvelles tâches sans projet | Réglage `projectlessWorkspaceRoot` via le service `settings`. Il ne déplace pas les conversations existantes. |
| Anciennes références de navigation | Les handlers globaux fusionnent `thread-workspace-root-hints` et `thread-projectless-output-directories`. La racine de travail et le dossier de sortie doivent être vérifiés séparément. |
| Cwd durable d’une conversation | `thread/settings/update` et notification `thread/settings/updated`, suivis d’une reprise froide. Le helper renderer possède un fallback en mémoire : son retour seul ne prouve pas la persistance. |
| Exécution et fichiers | Le code utilise `process/spawn`, les flux d’entrée/sortie, les terminaisons et les opérations de fichiers. Des chemins de lecture/écriture passent par `cat` ou `sh` suivant le backend. Valider les octets et les résultats réels. |
| Terminal | Service `terminal`, dépendance `node-pty`, redimensionnement et annulation font partie du besoin. Un test Python seul ne qualifie pas tous ces mécanismes. |
| Surveillance, bases, périphériques | Le paquet déclare notamment `@parcel/watcher`, `better-sqlite3`, `node-pty`, des intégrations de périphériques et des dépendances OpenAI internes. Leur présence dans le catalogue n’établit pas leur compatibilité Bionic. |

Les [appels exacts de réparation des chemins](../desktop-project-path-handlers-20260908.md)
détaillent les payloads et les vérifications. Le catalogue préserve la séparation
entre interfaces utilisateur, services app-host et protocole moteur : ces trois
couches n’emploient pas toujours les mêmes noms ou schémas.

## Limites établies dans le code

`customRuntime` vaut explicitement `undefined` dans l’objet app-host de ce main.
Les propriétés `notificationPermissionsSupported` et `systemPermissions` sont
conditionnées à `darwin` ou `win32` ; leur présence dans la liste n’annonce donc
pas une API équivalente sur Linux/Android. D’autres branches d’erreur sont
inventoriées, mais leur existence ne prouve pas qu’elles sont atteintes lors des
tests du Fold.

Aucune source map n’est intégrée parmi les fichiers collectés. Les scripts
JavaScript minifiés restent analysables, mais les noms et fichiers d’origine ne
sont pas reconstitués intégralement. Les composants C/C++, Electron/Chromium et
les modules natifs ne sont pas désassemblés par cet outil.

Les **370 entrées externes** déclarées par l’ASAR ont toutes été collectées et
leur taille comparée au manifeste : aucun membre manquant ou de taille différente.
Cela comprend 65 scripts JavaScript et 27 modules `.node`. Le catalogue garde
l’empreinte réelle de chaque membre sous `unpackedMemberCollectionChecks`.
Les 57 ELF de la collecte complète font l’objet de l’inspection native séparée
dans `work/desktop-audit-20260908/native-installed-r1` ; le présent parseur ne les
qualifie pas.

La couverture JavaScript externe compte 2 561 fichiers : le chemin supplémentaire
`resources/cua_node/lib/node_modules/tesseract.js` est un dossier, pas un script.
Les sources sont des copies du client installé, distinctes des sources du moteur
FoldGPT et de l’état courant d’exécution sur le téléphone.

## Reproduction et preuves

Les [outils d’inspection](../../../tools/desktop-audit/README.md) précisent les
commandes. Le parseur Acorn 8.18.0 et huit tests ciblés vérifient notamment la
non-exécution des sources, la distinction entre appels statiques/dynamiques et
les positions des observations. Les sources sont empreintées avant et après le
parcours. L’analyse complète de syntaxe ne remplace pas les essais des fonctions
dans l’interface habituelle sur le Fold.
