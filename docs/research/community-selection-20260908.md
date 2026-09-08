# Ce que FoldGPT retient des portages Android — 8 septembre 2026

## Décision

Conserver le moteur R5 actuel : le parcours Python, éditeur et reprise a
maintenant réussi sur le Fold. Après la création et la sauvegarde en r22,
r23 a repris la même conversation et les fichiers existants, exécuté les trois
tests et le zipapp affichant 42 après deux ouvertures, puis fermé chaque session proprement.
Le cache CPython est actif et séparé du runtime inventorié. Le
[rapport r23](r23-device-validation-20260908.md) distingue ces preuves du reste
des fonctions encore non qualifiées.

Réutiliser les adaptations Android individuellement, après un test de leur cause.
La compilation Bionic du contrôleur reste une piste distincte. Elle n'est pas
nécessaire pour corriger l'emplacement des caches et n'est pas livrée dans r23.
L'interface et le contrôleur GNU restent sous PRoot ; seules les commandes
Bash/Python sont natives Android/Bionic. Aucune VM sur le téléphone.

| Sujet | Preuve comparée | Décision FoldGPT |
| --- | --- | --- |
| V8 natif Android | DioNanos publie V8 150.4.0 `ptrcomp_sandbox_release`, avec binding et archive correspondant à notre dépendance et Rust 1.95.0 | Retenir cette recette pour un build isolé ; vérifier les octets et le fonctionnement réel de V8 avant intégration. Ne pas réduire la version ou retirer la sandbox V8. |
| Base du moteur | La release wallentx `rust-v0.153.4-termux` est deux commits devant notre base officielle, sans modification du protocole app-server/exec-server dans le delta | Référence proche pour les ajustements de compilation. Elle ne contient pas notre raccordement natif FoldGPT. |
| Recette V8 wallentx | Le workflow publié télécharge V8 147.4.0/profil `release`, alors que Cargo demande 150.4.0 avec sandbox | Ne pas reprendre cette recette telle quelle ; le test `--help` ne démontre pas V8 fonctionnel. |
| Verrous Rust | Rust 1.95.0 omet Android du `cfg` des fonctions `File::lock`/`try_lock`/`unlock` utilisant flock ; le chemin Android retourne Unsupported sans syscall | Pour un contrôleur Bionic, appeler réellement `libc::flock`, puis tester contention et libération. L'erreur Rust seule ne démontre pas une absence du noyau. Notre exécuteur Python utilise déjà flock réel. |
| Terminaux PTY | Le NDK r29 exporte `openpty`/`forkpty` depuis API23 ; le Fold a UNIX98_PTYS activé | Tester l'API Bionic existante. Ne pas importer le shim qui ignore des erreurs de configuration. Une probe ARM64 a été compilée, mais pas exécutée sur Android dans cette revue. |
| DNS/TLS | Des utilisateurs de Codex Linux dans Termux résolvent leur DNS en compilant pour Bionic ; le modèle a répondu dans nos scénarios r20 et r22 | Piste pour un contrôleur Bionic, pas diagnostic établi de l'incident de cache. Pas de proxy ajouté par analogie. |
| Mises à jour | Les forks mettent à jour leurs propres exécutables ; notre moteur porte aussi un patch FoldGPT | Garder les applications officielles intactes et maintenir notre moteur séparé. Ne pas utiliser l'auto-updater d'un fork qui remplacerait notre intégration. |

## Références vérifiées

- [DioNanos, source examinée](https://github.com/DioNanos/codex-termux/tree/235ec42906fbeb1a5c17f0a9e596e1f86fd5a8df)
- [wallentx, release réellement publiée](https://github.com/wallentx/codex-termux/releases/tag/rust-v0.153.4-termux)
- [Delta wallentx depuis notre base](https://github.com/wallentx/codex-termux/compare/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a...f3b937747529a52ff0bc8111e1088e422e3c6cfb)
- [Rust 1.95.0, implémentation Unix des verrous](https://github.com/rust-lang/rust/blob/1.95.0/library/std/src/sys/fs/unix.rs)
- [Ticket Codex Android DNS/verrous](https://github.com/openai/codex/issues/11809)

Les rapports détaillés, extraits et empreintes se trouvent dans
`work/native-port-review-20260908/` : `README.md`, `candidate-recipe.md`,
`inputs-manifest.json`, `pty-lock-review.md`, `pty-lock/capture-verification.json`,
`dns-launch/comparison.md` et `dns-launch/source-evidence.json`. Aucun témoignage
Reddit directement vérifié n'est ajouté à ces conclusions.

## Résultats du retour du Fold

Le défaut r20 de contrat Full access a été corrigé par la route UID ordinaire.
Le défaut suivant, `OrdinaryUidFilesBackend.close(None)`, empêchait l'arrêt d'une
session r21 inutilisée. Le correctif r22 accepte cette absence d'identité
uniquement lorsqu'aucune session ni aucun handle n'ont été acquis. Les contrôles
d'identité après acquisition et les diagnostics de nettoyage restent présents.
L'incident r21/PID29981 et sa récupération sont conservés dans
`work/r21-device-return-20260908/` ; cet arrêt raté n'est pas rebaptisé `closed/0`.

**r22b/versionCode12 a été qualifié pour les étapes suivantes** :
préparation/arrêt sans client, workload natif ordinaire, création réelle du projet
Python par la conversation, trois unittest, zipapp affichant 42, sauvegarde puis
réouverture dans l'éditeur et fermeture propre du propriétaire UI PID8815.
Les sorties modèle indiquent Android/aarch64/UID 10412 et les fichiers sont
collectés indépendamment. Preuves :
`work/r21-device-return-20260908/r22-idle-device-v1/report.json` et
`work/r21-device-return-20260908/ui-r22/`, notamment `model-tool-evidence.json`,
`project-after-create/report.json`, `project-after-editor-flushed/report.json`
et `stop-first/report.json`.

La reprise r22 a ensuite été refusée par l'admission : Python avait ajouté
14 répertoires `__pycache__` dans sa stdlib signée. Ce refus révèle une erreur
d'emplacement des données générées. Il ne justifie ni l'abandon de l'inventaire
ni la désactivation générale du bytecode.

Le lanceur r23 configure `PyConfig.pycache_prefix` après `PyConfig_Read()` vers
le dossier frère `python-cache`. CPython conserve ses options explicites et
ses règles `-I`/`-E`/environnement. Deux compilations NDK r29 produisent le même
ELF, et onze tests Windows CPython 3.14.7 créent 55 caches hors runtime en
préservant 2 477 fichiers. Le code et les sources CPython utilisés sont détaillés
dans `work/r22-cache-20260908/CLI-README.md`.

**r23/versionCode13 est installé et le parcours de reprise est vérifié.** APK
`downloads/native-production-20260908/foldgpt-native-candidate-r23.apk`, SHA256
`3a1bb00e73a828fa298884941514ad421a5f888c7fe483303b0ad514f2122c74` ;
87 ELF, 2 447 fichiers Python, 86 alias, 95 sources et signature vérifiés dans
`work/r22-cache-20260908/r23-apk-verification.json` et `r23-signature.txt`.
La maintenance a archivé 81 fichiers dans 14 répertoires de caches sans changer leurs
octets, les 2 447 sources ni les 86 alias, puis le runtime a été réadmis. Les six
commandes de production passent avec Python normal et caches actifs hors runtime,
suivies d'une nouvelle admission et d'une fermeture propre. Preuve :
`downloads/native-ordinary-production-device-20260908/9d653b2d/report.json`.

Les échanges modèle de 11:41 et 11:43 UTC exécutent réellement les trois tests
et l'ancien zipapp affichant 42 ; les fichiers et le commentaire de l'éditeur restent
identiques après les deux reprises. Les propriétaires UI 22808 et 29860 ont
leurs reçus propres et leurs ressources sont absentes. Ces preuves sont dans
`work/r22-cache-20260908/ui-r23/`. Le rapport `integrity-comparison.json` conserve
un boot, des propriétés contrôlées et quatre APK ChatGPT officiels inchangés.
À 11:46 UTC, l'application est relancée sur la même conversation pour Julien :
handshake réussi, propriétaire 6893 `ready`, boot inchangé. Cette nouvelle session
reste ouverte et aucune exécution modèle supplémentaire ne lui est attribuée.

## Portée des validations

Le CI natif ciblé `34215637059` passe 25 commandes et 193 unittest. Les tests
cleanup Python (7), protocole Java (18) et observation Java (6) passent aussi.
L'échec initial de fixture CI `34215414532` et celui du lanceur Gradle global
inadapté aux tests HTTPS JVM restent conservés ; leurs causes ont été corrigées
ou le lanceur canonique approprié exécuté, sans effacer ces résultats.

La suite Rust générale R5 `34192652057` reste en **échec** : 16 933 réussites,
238 échecs, deux timeouts et 35 ignorés. Le [triage des 240 cas](r5-failure-audit-20260908.md)
ne conclut pas que toutes leurs causes ou conséquences Android sont résolues.
`rg` était absent lors de la création r22 et r23 ne l'ajoute pas.
Le parcours Python ciblé ne qualifie pas les PTY, tous les outils, les autres
profils, toutes les reprises ou les mises à jour futures. Cette recherche
communautaire ne démontre pas un produit complet « tout Bionic ».

L'[état de reprise](../../recovery/HANDOFF.md) conserve les prochaines étapes
et les liens de sauvegarde. La dernière restauration documentée est encore
le [complément v14](../../recovery/supplement-v14.md), qui porte r21 ; la
publication de cette nouvelle passe r22/r23 doit être vérifiée séparément.
