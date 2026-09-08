# Ce que FoldGPT retient des portages Android — 8 septembre 2026

**Actualisation r25, 16:14 UTC :** les neuf tests du backend PTY passent sur
Android et les vraies sessions du modèle sont exercées depuis la conversation
(saisie, Ctrl+C, codes23/130). Les commandes Python/rg ordinaires passent
ensuite. Le panneau de terminal humain reste distinct et inachevé.
Voir le [rapport r25](r25-device-validation-20260908.md). La comparaison des
ports CLI et la limite Electron/PRoot ci-dessous restent applicables.

## Décision

**FoldGPT a démontré un vrai parcours Python sur le Fold ; le produit complet
n'est pas terminé.** R24 a désormais passé 15 cas rg/PCRE2/JIT sur le Fold,
ainsi que la régression Python. Le projet avec dépendance a passé cinq tests,
deux builds identiques et la réexécution de son archive après fermeture puis
réouverture. Les fichiers précédents sont conservés par collecte indépendante.
Conserver le moteur R5 actuel pendant ce lot et l’intégration du terminal.
Voir le [rapport r24](r24-device-validation-20260908.md). Le parcours Python, éditeur et reprise a
maintenant réussi sur le Fold. Après la création et la sauvegarde en r22,
r23 a repris la même conversation et les fichiers existants, exécuté les trois
tests et le zipapp affichant 42 après deux ouvertures, puis fermé chaque session proprement.
Le cache CPython est actif et séparé du runtime inventorié. Le
[rapport r23](r23-device-validation-20260908.md) distingue ces preuves du reste
des fonctions encore non qualifiées.

Réutiliser les adaptations Android individuellement, après un test de leur cause.
La compilation Bionic du contrôleur reste une piste distincte. Elle n'est pas
nécessaire pour corriger l'emplacement des caches et n'est pas livrée dans r24.
L'interface et le contrôleur GNU restent sous PRoot ; seules les commandes
Bash/Python/rg sont natives Android/Bionic. Aucune VM sur le téléphone.

Le [plan de réussite mesurable](functional-milestones-20260908.md) fixe les
preuves nécessaires et les conditions d'arrêt. Son nombre de lignes n'est pas
une estimation de charge ; le port de l'interface représente un autre chantier
que l'ajout d'une commande.

## Ce que nous utilisons déjà

| Apport amont | Adoption réelle dans FoldGPT | Ce que cela ne prouve pas |
| --- | --- | --- |
| Bash et adaptations Termux | Bash 5.3.15 reconstruit pour le préfixe privé FoldGPT, avec correctifs de chemins examinés ; commandes Bash/Python exercées dans les sessions r23 | Copier des paquets liés à `/data/data/com.termux/files` ne fournirait pas notre runtime ; Termux complet n'est pas requis pour exécuter ce parcours |
| CPython Android officiel | CPython 3.14.7 Android, lanceur Bionic et cache extérieur ; Packaging 26.3 téléchargé/installé, cinq tests et zipapp avec reprise réussis dans la conversation r24 | Ce wheel universel et ce projet ne qualifient pas toutes les dépendances, extensions compilées ou fonctions du produit |
| Shizuku officiel et son API | UserService réel dans les essais initiaux, puis lancement de production séparé avec commandes sous l'UID Android 10412 de FoldGPT | Le SDK ne transforme pas une application ordinaire en root et ne démontre pas un démarrage autonome après chaque redémarrage Android |
| ripgrep et PCRE2, versions également utilisées par Termux | Sources rg 15.2.0 et PCRE2 10.47 épinglées, deux builds ARM64 Bionic identiques et PCRE2 lié statiquement avec JIT dans `work/native-ripgrep-20260908/build-v4/build.json` | Le manifeste de compilation conserve sa portée PC ; le rapport Android a0ec1f9f ajoute 15 cas réels avec JIT, fermeture et nouvelle admission, sans qualifier à lui seul l’interface |
| PTY fourni par Bionic | Après la sonde v4a, le backend candidat passe neuf tests Android séparés : saisie, taille, interruptions, descendants et saturation, huit propriétaires attendus et absents | Le candidat est testé dans son propre répertoire ; il n'est pas installé dans r24 ni qualifié depuis le terminal de l'interface |

Le [préflight pip Android](../../work/r24-native-20260908/pip-preflight-63a2aba2/report.json)
a exécuté pip 26.2.1 depuis son wheel réel avec code 0, `viaModel=false`. Depuis,
la conversation r24 a téléchargé puis installé Packaging 26.3 ; le
[rapport r24](r24-device-validation-20260908.md) sépare ces preuves, les
corrections de revue et les limites des contrôles. La
[sonde PTY v4a](../../work/r24-native-20260908/pty-probe-bc976fd3/report.json)
conserve aussi les refus `tcgetsid`/`TIOCGSID` avec errno 13. Son contrôle de
session repose sur les observations réelles `getsid`, `tcgetpgrp` et `/dev/tty` ;
ces refus ne deviennent pas des appels réussis.

## CLI natives étudiées, sans adoption globale

| Sujet | Preuve comparée | Décision FoldGPT |
| --- | --- | --- |
| V8 natif Android | DioNanos publie V8 150.4.0 `ptrcomp_sandbox_release`, avec binding et archive correspondant à notre dépendance et Rust 1.95.0 | Retenir cette recette pour un build isolé ; vérifier les octets et le fonctionnement réel de V8 avant intégration. Ne pas réduire la version ou retirer la sandbox V8. |
| Base du moteur | La release wallentx `rust-v0.153.4-termux` est deux commits devant notre base officielle, sans modification du protocole app-server/exec-server dans le delta | Référence proche pour les ajustements de compilation. Elle ne contient pas notre raccordement natif FoldGPT. |
| Recette V8 wallentx | Le workflow publié télécharge V8 147.4.0/profil `release`, alors que Cargo demande 150.4.0 avec sandbox | Ne pas reprendre cette recette telle quelle ; le test `--help` ne démontre pas V8 fonctionnel. |
| Verrous Rust | Rust 1.95.0 omet Android du `cfg` des fonctions `File::lock`/`try_lock`/`unlock` utilisant flock ; le chemin Android retourne Unsupported sans syscall | Pour un contrôleur Bionic, appeler réellement `libc::flock`, puis tester contention et libération. L'erreur Rust seule ne démontre pas une absence du noyau. Notre exécuteur Python utilise déjà flock réel. |
| Terminaux PTY | Le NDK r29 exporte `openpty`/`forkpty` depuis API23 ; la sonde v4a a désormais exécuté les primitives réelles sur le Fold | Utiliser l'API Bionic existante. Ne pas importer le shim qui ignore des erreurs de configuration ; finir le backend et la qualification dans l'interface. |
| DNS/TLS | Des utilisateurs de Codex Linux dans Termux résolvent leur DNS en compilant pour Bionic ; le modèle a répondu dans nos scénarios r20 et r22 | Piste pour un contrôleur Bionic, pas diagnostic établi de l'incident de cache. Pas de proxy ajouté par analogie. |
| Mises à jour | Les forks mettent à jour leurs propres exécutables ; notre moteur porte aussi un patch FoldGPT | Garder les applications officielles intactes et maintenir notre moteur séparé. Ne pas utiliser l'auto-updater d'un fork qui remplacerait notre intégration. |

La release V8 DioNanos a été relue via GitHub pendant cette passe : elle publie
bien l'archive `ptrcomp_sandbox_release` 150.4.0 et son binding Android. Ses
empreintes publiées correspondent à celles de la recette conservée. Cette
nouvelle lecture de métadonnées n'est ni un téléchargement des octets, ni une
compilation du contrôleur FoldGPT, ni une exécution V8 sur le téléphone.

## Pourquoi une CLI native ne porte pas l'interface

Electron annonce des distributions macOS, Windows et Linux ; son README
ne propose pas de cible Android. FoldGPT héberge actuellement le client desktop
Linux ARM64 avec Electron, X11 et PRoot. Remplacer le contrôleur GNU par un
contrôleur Bionic peut supprimer PRoot pour ce contrôleur ; cela ne change pas
le moteur graphique Electron qui fait fonctionner l'interface.

Un port intégral de l'interface demanderait soit un hôte Electron/Chromium
compatible Android, soit une nouvelle intégration Android des composants web
et de leurs services : IPC, fichiers, éditeur, terminal, authentification,
navigation, clavier, cycle de vie et mises à jour. Afficher une page dans une
WebView ne reproduit pas à lui seul ces contrats. Une interface réécrite serait
un changement de produit à exposer à Julien, pas une preuve que le client
officiel inchangé est devenu natif Android. Aucune solution intégrée et
qualifiée de ce type n'est livrée dans le projet.

Les fichiers officiels peuvent rester intacts tout en exigeant des adaptations
de notre interfaçage lors d'une nouvelle version. Préserver leur mise à jour ne
signifie pas garantir à l'avance la compatibilité avec toutes les versions
futures. Cette différence doit rester visible dans le bilan de fin de projet.

## Prochaine amélioration communautaire justifiée

La priorité reste **rg, le terminal et le projet avec dépendance**, puis une
décision explicite sur le contrôleur et l’interface natifs. Aucun chantier Git
ne s’ajoute à ce lot. Pour une extension ultérieure, **Git natif Bionic adapté
au préfixe FoldGPT** est une piste communautaire justifiée : il permet de
reprendre un vrai dépôt, voir les différences, créer un commit local et gérer
le travail courant. La recette Termux relue fournit Git 2.55.0 et vérifie la
présence effective de `git-remote-https`. Elle dépend aussi de bibliothèques et
de chemins de shell ; copier son seul exécutable ne suffit pas. Il faut vérifier
les sources, la fermeture des dépendances, le stockage des identifiants,
les certificats et le contrat Git depuis la même interface. Ce Git n'a pas été
construit, installé ou qualifié par cette revue.

Après le lot fonctionnel en cours, le contrôleur Bionic/V8 doit faire l’objet
d’une décision explicite puis d’une qualification distincte,
car il vise la réduction de PRoot plutôt qu'une commande manquante. Il doit
conserver le raccordement FoldGPT et passer le même parcours utilisateur avant
adoption. Ni Git natif ni le contrôleur Bionic ne résolvent à eux seuls le port
complet de l'interface. Aucune nouvelle compilation n'est engagée par ce bilan.

## Références vérifiées

- [DioNanos, source examinée](https://github.com/DioNanos/codex-termux/tree/235ec42906fbeb1a5c17f0a9e596e1f86fd5a8df)
- [wallentx, release réellement publiée](https://github.com/wallentx/codex-termux/releases/tag/rust-v0.153.4-termux)
- [Delta wallentx depuis notre base](https://github.com/wallentx/codex-termux/compare/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a...f3b937747529a52ff0bc8111e1088e422e3c6cfb)
- [Rust 1.95.0, implémentation Unix des verrous](https://github.com/rust-lang/rust/blob/1.95.0/library/std/src/sys/fs/unix.rs)
- [Ticket Codex Android DNS/verrous](https://github.com/openai/codex/issues/11809)
- [Release V8 DioNanos relue](https://github.com/DioNanos/codex-termux/releases/tag/rusty-v8-v150.4.0) : métadonnées d'assets, pas exécution des binaires
- [Recette Termux rg relue](https://github.com/termux/termux-packages/blob/master/packages/ripgrep/build.sh), blob `d8e243c04d0964afefe93efb4bfe34acc7398236`
- [Recette Termux Git relue](https://github.com/termux/termux-packages/blob/master/packages/git/build.sh), blob `f3be7d87939e5b8ea9f6c5273c72495cfae280c6`
- [Plateformes Electron relues](https://github.com/electron/electron/blob/main/README.md), blob `128071b9bc690c361f62a12b180824f195832c7d`
- [Exigences du SDK Shizuku relues](https://github.com/RikkaApps/Shizuku-API/blob/master/README.md), blob `3ebe9fee660873cb4ac31f5b3e54a99d625ffa23` ; démarrage ADB à rétablir après reboot en mode sans root

Les rapports détaillés, extraits et empreintes se trouvent dans
`work/native-port-review-20260908/` : `README.md`, `candidate-recipe.md`,
`inputs-manifest.json`, `pty-lock-review.md`, `pty-lock/capture-verification.json`,
`dns-launch/comparison.md` et `dns-launch/source-evidence.json`. Aucun témoignage
Reddit directement vérifié n'est ajouté à ces conclusions.

## Historique des preuves r22/r23

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

**r23/versionCode13 a été installé et son parcours de reprise est vérifié.** APK
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
À 11:46 UTC, l'application a été relancée sur la même conversation pour Julien :
handshake réussi, propriétaire 6893 `ready`, boot inchangé. Cette nouvelle session
était alors ouverte et aucune exécution modèle supplémentaire ne lui est attribuée.
Ce paragraphe décrit cet instant ; il ne remplace pas le dernier état opérationnel
consigné par la tâche principale dans le dossier `recovery/`.

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
et les liens de sauvegarde. Le [complément v15](../../recovery/supplement-v15.md)
a été publié chiffré sur GitHub privé, retéléchargé et restauré : 8 707 fichiers,
1 219 sources Git et APK r23 vérifiés. Il conserve cette passe r22/r23 et dépend
de l'archive principale et des compléments 1 à 14.
