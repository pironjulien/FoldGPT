# Validation réelle r26b dans l'interface — 8 septembre 2026

**Le démarrage du propriétaire natif par l'application et deux commandes demandées
depuis l'interface fonctionnent dans les observations r26b.** Les cinq tests du
projet Python passent ; le terminal reçoit une entrée, renvoie la réponse et
transmet le code de sortie volontaire `23`. La reprise après arrêt brutal ou
redémarrage physique n'est pas démontrée par ce dossier.

Cette revue indépendante lit les captures déjà collectées sous
`work/app-transport-20260908`. Elle n'exécute aucune commande sur le téléphone.
Les preuves sélectionnées sont conservées sous
[`recovery/verification/r26b-20260908`](../../recovery/verification/r26b-20260908),
avec un manifeste SHA256 et les origines de chaque extraction. Les constats
ci-dessous reposent sur les événements d'outils et les résultats de collecte,
pas sur le texte de conclusion produit par le modèle.

## Périmètre exact

| Élément | Observation |
| --- | --- |
| APK FoldGPT collecté | SHA256 `632012aa8dd355fcede9a11b2483e8c48d22d2d170c9f4803c3d55cdd8e2723f` |
| Conversation | `01a07fe2-4dc0-7791-adc0-fb3fe079872c` |
| Tour de validation | `01a08287-665b-74e3-9d93-018afdf57f1e` |
| Répertoire de travail | `/data/data/app.foldgpt/files/projects/ui-python-caae3a83d156` |
| Origine du propriétaire | `android-app` |
| Identité du propriétaire dans le relevé de processus | PID `29060`, parent `28958` (`app.foldgpt:runtime`), UID `10412` |
| Boot des captures | `348d453e-f4e5-40e0-8ef0-030f4d5e38af` |
| Fin du tour | `completed`, `error:null`, durée `32317 ms` |

L'empreinte installée est issue du résultat réel `sha256sum` et correspond au
rapport de vérification du paquet. Le champ `androidProductionExecuted:false`
de ce rapport désigne sa vérification statique ; ce rapport seul ne prouve
aucune exécution sur Android. Les événements et relevés séparés apportent cette
preuve d'exécution.

Le processus Python natif est un enfant direct du service Android. Le même
relevé montre `libproot.so`, puis la chaîne qui héberge l'interface et son
contrôleur. **Les commandes validées passent par l'exécuteur natif ; l'ensemble
de l'application n'est donc pas intégralement natif.** L'absence de nom Shizuku
dans les relevés est cohérente avec l'origine `android-app` ; elle ne prouve pas
que Shizuku a été désinstallé ou n'a jamais servi auparavant.

## Commandes réellement observées

### Tests Python et utilisation du projet existant

L'événement `exec-adcda63d-d4f5-476c-8558-a68b37fdd3d8` utilise le Bash Bionic
`libfoldgpt_bash.so` du paquet. La sortie conservée contient les cinq tests :

- `test_cli_process_json_stable_and_codes` ;
- `test_compound_constraint` ;
- `test_invalid_entries` ;
- `test_invalid_installed_version` ;
- `test_statuses`.

Résultat exact : `Ran 5 tests in 0.637s`, puis `OK`. La durée de l'élément de
commande complet est `1893 ms`.

Le zipapp existant `dependency-inspector.pyz` produit les deux formats demandés,
JSON et Markdown. Les résultats distinguent `requests 2.32.5` compatible,
`urllib3 1.26.20` incompatible avec `<3,>=2`, et `colorama` absent. `rg --files`
énumère ensuite les fichiers du projet, dont les sources, tests, scripts de
construction et données. La dernière ligne réelle est :

```text
statuses: environment=0 rg=0 tests=0 json=1 markdown=1 rg_files=0
```

Les codes `1` des sorties JSON et Markdown correspondent aux dépendances
incompatibles ou absentes de l'exemple. Le code global `0` ne les efface pas :
le script collecte chaque code et termine explicitement avec `exit 0`.

Ce tour **réexécute un projet et un zipapp existants**. Il ne contient ni création
complète d'un nouveau projet ni nouvelle construction du zipapp. Les preuves
antérieures de création/construction doivent être citées séparément.

### Terminal interactif et code de sortie non nul

L'événement `exec-b30605e3-a0c1-4e5a-945a-c95a377b92ff` lance un Python qui lit
une ligne, la renvoie et termine volontairement avec `SystemExit(23)`.
L'événement `terminalInteraction` contient exactement `bonjour autonome\n`.
La sortie réelle contient :

```text
bonjour autonome
FOLD_APP_REPLY=bonjour autonome
```

L'événement final indique `exitCode:23`, `durationMs:3813`, `status:"failed"`.
Ce statut correspond ici au code non nul demandé par le test ; le conserver
permet de vérifier sa propagation. Le `processId` de l'interface (`5081`, ou
`27554` pour l'autre commande) est un identifiant de session d'exécution et
n'est pas établi comme un PID Android par ces événements.

La capture d'événements de l'interface ne conserve pas les premières sorties
de ces commandes. Elles ont ensuite été retrouvées dans les **vrais résultats
d'outils persistés** sous `r26b-functional/native-conversation.jsonl`. Les quatre
records de `r26b-functional/tool-outputs.json` ont été comparés aux records
originaux ; ce sont des sorties d'outils, pas une conclusion du modèle.

Ces résultats établissent `sys.platform=android`, `platform.machine()=aarch64`,
`os.getuid()=10412`, le répertoire natif indiqué plus haut et `sys.executable`
pointant vers le `libfoldgpt_python_cli.so` du paquet. `command -v rg` retourne
`/data/data/app.foldgpt/files/native-runtime-v1/python/bin/rg`. Le premier chunk
du terminal contient exactement `FOLD_APP_READY\r\n`, avant l'entrée et la
réponse déjà observées. `persisted-tool-output-audit.json` conserve les index
de records et les chunks décodés. Aucun `Ctrl+C` n'est testé dans ce tour r26b.

## Démarrage, chemins et préservation des données

Le journal de l'interface contient un `initialize_handshake_result` réussi sur
le transport `stdio`. Le manifeste de démarrage annonce les chemins natifs,
le socket privé et le même propriétaire que le relevé de processus.

Les vues `/data/user/0/app.foldgpt/files/projects` et
`/data/data/app.foldgpt/files/projects` ont le même device `65097`, inode
`471258`, UID et inventaire de `288` entrées dans le relevé examiné. Cette
égalité a été recalculée à partir des deux objets complets ; ce nombre est un
instantané, pas un compte final après toutes les opérations suivantes.

Les captures du fichier de conversation avant et après correction du répertoire
sont comparées octet par octet : les `882971` octets antérieurs sont inchangés.
Les `675` octets ajoutés forment un seul événement `thread_settings_applied`
qui fixe le répertoire natif. Le fichier atteint `883646` octets. Cette première
preuve porte sur la correction du répertoire avant le tour de validation. La
capture persistée après validation atteint `957836` octets et conserve également
ce préfixe corrigé à l'identique, vérification octet par octet distincte.

La copie des anciens projets vers
`/data/data/app.foldgpt/files/projects/imported-codex` préserve le contenu
observé : **39 répertoires, racine comprise, et zéro fichier**. Les résultats
d'inventaire source avant/après sont identiques ; les empreintes de contenu
source/destination recalculées sont toutes deux
`f514214696c7c1591bd990bc3dbd32492c9d3ed4bb07c335840dd10c15dc22c5`.
Les fichiers de conversation ne font pas partie de cet arbre de projets.

La qualification Android de l'outil de copie a exécuté **21 cas : 20 réussites
et une erreur**, code global `1`. Le cas des liens physiques échoue pendant la
création de sa fixture `os.link`, avec `PermissionError: [Errno 13]`, avant
d'exercer l'assertion de refus. Le résultat intégral est conservé ; il ne permet
pas de déclarer toute la suite Android réussie. Le passage des ancêtres en
`O_PATH` traite les répertoires traversables mais non lisibles ; les contrôles
de liens ne sont pas supprimés. Les résultats Linux de l'outil restent des
preuves distinctes, non recomptées comme des réussites Android.

## Ce que cette réussite ne ferme pas encore

Dans les instantanés de réussite examinés, le propriétaire est `ready`, sélectionné,
`ownerRetained:true`, `bootstrapReaped:false`, `cleanupComplete:false`, sans
erreur déclarée. C'est l'état d'une session active. **Ce n'est pas un reçu de
nettoyage ni une preuve de redémarrage réussi.**

La reprise avec compteur de boot a une implémentation et des tests PC décrits
dans [la note dédiée](android-boot-recovery-20260908.md). Elle doit être qualifiée
sur le Fold avec une version qui embarque réellement cette implémentation. Les
preuves r26b ci-dessus ne qualifient pas cette modification ultérieure.

## Incident ultérieur de 21:48 et correction du service

Un relevé ultérieur établit un arrêt réel qui invalide toute interprétation
de `ready` comme état permanent. Les lignes ciblées de
`unexpected-stop-r26b/lifecycle-logcat.txt` montrent cet ordre :

| Horodatage du journal | Événement |
| --- | --- |
| `21:48:16.885` | Android tue le propriétaire Python `29060` : `Trimming phantom processes` |
| `21:48:16.886` | Android tue `libproot.so` et d'autres descendants |
| `21:48:16.896` | Le worker Java rapporte `Linux exited with 137` |
| `21:48:16.920` | Android tue `app.foldgpt:runtime`, PID `28958`, `adj 905`, motif `remove task` |

Le record `ApplicationExitInfo` confirme `USER REQUESTED / REMOVE TASK` pour
le dernier événement. Le nom Android de cette raison ne démontre pas qui a
initié l'action. Le statut natif persistant est alors `stopping`, avec
`cleanupComplete:false`, et le marqueur v1 existe encore. Aucun nettoyage réussi
n'est déduit de cette mort de processus.

Le code du service avait un défaut indépendant : à la fin du worker, il appelait
`stopSelfResult` avant d'attendre la future native de `requestStop`. Il ne lançait
la fermeture asynchrone que dans `onDestroy`, après avoir abandonné la protection
du service au premier plan. Cette séquence pouvait interrompre le nettoyage.
**Elle n'explique pas le premier kill de `21:48:16.885`, qui la précède.**

La correction conserve le service au premier plan jusqu'à deux confirmations :
fin réelle du worker et réussite de la future native. Une future en attente,
une exception ou un délai expiré ne valent pas réussite. Une demande de reprise
attend ces deux fins, puis crée un nouveau propriétaire natif ; un propriétaire
ayant reçu `requestStop` n'est pas réutilisé. Les callbacks d'anciennes
générations, les nouvelles commandes arrivant avant la livraison d'un
`startId`, et l'annulation d'une reprise par un nouvel arrêt sont traités.

Le worker attend désormais la fin réelle du processus après sa demande de
terminaison forcée, au lieu de traiter une seconde attente bornée comme une
fin implicite. En cas de destruction imposée par Android, la demande de
nettoyage est immédiate ; la sortie volontaire du processus passe encore par
le contrôle global des générations et attend également le worker.

Validation PC de cette correction : **24 tests JVM passent, dont 14 nouveaux
cas du contrôle d'arrêt ; le service compile contre Android 37**. Les preuves
sont `lifecycle-foreground-r2` et `lifecycle-foreground-service-r2`, recopiées
dans le dossier de vérification. Ce contrôle ne construit pas d'APK et
n'exécute pas le code sur Android. La correction de l'ordre de fermeture reste
distincte de l'enquête sur la suppression initiale des processus par Android.

## Arrêt brutal pendant le même boot : voie praticable

La difficulté restante concerne le propriétaire de session, pas la disponibilité
de Python ou de Bash. Une fermeture ordinaire peut couper le canal de durée de
vie, arrêter les processus suivis, attendre leur fin et retirer le marqueur
seulement après succès. La connexion à un propriétaire encore vivant peut
également être rétablie après vérification de son identité et de sa session.
Ce sont les deux voies à privilégier pour les arrêts/reprises usuels.

Si Android tue le propriétaire avant qu'il ait fini et attesté ce travail, le
marqueur persiste. L'absence d'un PID observable depuis l'application ne prouve
pas que tous les descendants natifs sont morts. Un historique de sortie tel
qu'`ApplicationExitInfo`, un socket sans réponse ou un verrou désormais libre
ne constituent pas, seuls, un inventaire complet des descendants. Faire hériter
un descripteur de verrou aux outils ne suffirait pas non plus : des commandes
ordinaires peuvent fermer les descripteurs hérités.

Une récupération automatique sûre dans le même boot demanderait une preuve
indépendante de fin de **toute** l'ancienne session : soit un superviseur vivant
qui possède et attend réellement tous ses processus, soit une autorité capable
de constater et contrôler l'ensemble des processus concernés, sous exclusion
de nouvelles admissions. Ce contrat n'est pas actuellement démontré pour le
redémarrage ordinaire de l'application après un `force-stop` générique. Un autre
service du même paquet peut être tué avec celui-ci ; le simple fait d'ajouter
ce service ne fournit donc pas la preuve manquante.

La voie autonome actuellement implémentée et vérifiable sur PC conserve le
refus lorsqu'une ancienne session du même boot n'est pas qualifiée, puis permet
un nouvel essai après avancement réel du compteur Android. Elle archive le
marqueur v2 original sous verrou, avec `previousCleanupClaimed:false`, et
préserve les projets et anciens dossiers de session. Un marqueur v1 dépourvu
d'epoch n'est pas attribué rétroactivement à un ancien boot.

Le script de maintenance
`tools/runtime/recover-legacy-native-session.py` fournit une autre preuve dans
un cadre distinct : arrêt Android de FoldGPT, inventaire complet de son UID
depuis le shell externe, contrôle positif, verrou exclusif et acquittement
avant archivage. Cette maintenance assistée par le PC ne doit pas être annoncée
comme une récupération autonome de l'application.

Le prochain critère d'acceptation utile est donc un arrêt ordinaire/reprise
avec reçu de nettoyage réel, puis un redémarrage physique/reprise avec compteur
avancé, projets et historique préservés. Une reprise générique après arrêt
brutal dans le même boot reste un critère séparé tant que son autorité de preuve
n'est pas mise en œuvre et qualifiée.

## Intégrité des preuves

`package-r26b-evidence.py`, conservé dans le dossier de preuves, reproduit les
extractions depuis les captures locales et vérifie les relations décrites
ci-dessus. Ses assertions passent. `provenance.json` enregistre les tailles et
empreintes SHA256 des sources, les index d'événements ou lignes sélectionnés,
et distingue copies exactes, extractions JSON et calculs de revue.
`manifest.json` donne la taille et l'empreinte de chacun des fichiers livrés
hors manifeste lui-même.

Les extractions JSON conservent les valeurs et l'ordre des éléments retenus ;
elles ne sont pas présentées comme des copies octet par octet de la capture
entière. Les conversations complètes, textes visibles de l'interface, prompts,
secrets, sources tierces et relevés complets des autres applications du
téléphone ne sont pas recopiés dans ce dossier de preuves.
