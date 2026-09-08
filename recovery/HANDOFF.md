# Reprise technique du 8 septembre 2026

## Dernier état : r25, 16:14 UTC

**Réexamen après la question sur une application Android ordinaire :** la
[revue des alternatives](../docs/research/phone-only-options-20260908.md)
distingue le contrat Shizuku/run-as r25 du lancement direct sous l'application.
Le reçu historique Bionic (34 RPC sous contexte applicatif normal) et ses
empreintes sont vérifiés. Il motive une qualification du propriétaire actuel
sans Shizuku, sans prétendre qu'elle a déjà réussi. Préserver r25 ; aucun
bootstrap/admission n'a été modifié dans cette revue. Le Store, une signature
OpenAI ou AVF ne sont pas des solutions équivalentes à ce lancement.

**R25/versionCode15 est installé**, APK
`2618abba092af33ac387906d75b57ecfd7b76ec7aa02d80b6c20fee4f44a28a3`.
Le terminal du modèle a réussi saisie et Ctrl+C depuis la conversation ;
la régression Python/rg passe, les 104 fichiers du projet sont inchangés.
Le propriétaire19391 est fermé et réapé ; une nouvelle ouverture a donné un
handshake réussi et un propriétaire26951 prêt à16:14 UTC. Lire le statut réel
avant toute action, ces PID sont historiques. Aucun reboot du Fold.

Le [rapport r25](../docs/research/r25-device-validation-20260908.md) et le
[reçu indépendant](../work/r24-native-20260908/ui/r25-milestone.json)
définissent la portée acquise. **Priorité corrigée selon Julien : ouvrir
FoldGPT et travailler PC éteint.** Le panneau de terminal manuel est reporté
et ne conditionne pas cette preuve. FoldActivity lance déjà FoldRuntimeService
sur le téléphone ; FoldExecutorRuntime attend cependant un serveur Shizuku
actif et autorisé. Le dernier lot a démarré ce serveur via ADB depuis le PC
(`work/r24-native-20260908/shizuku-start.json`). Cela ne démontre ni une
exécution des commandes sur PC ni une obligation de garder le câble branché.
Le démarrage de Shizuku et la reprise complète depuis le téléphone, notamment
après reboot normal, restent à qualifier avant d'annoncer l'autonomie acquise.
Le manuel officiel Shizuku relu documente un démarrage depuis Android 11+
sans ordinateur via le débogage sans fil, avec étapes à refaire après reboot.
Le SDK/UserService intégré ne remplace pas ce démarrage du serveur ; notre
propre lanceur peut l'intégrer mais ne reçoit pas automatiquement ses droits.
Voir les [critères et la source officielle](../docs/research/functional-milestones-20260908.md).
Les contraintes du contrôleur/interface entièrement Android restent ouvertes.
Les nouveautés r24/r25 sont conservées
dans le [complément v16](supplement-v16.md), publié et restauré : 39 584 fichiers
et 1 252 sources Git vérifiés, avec revérification des deux APK.

## Historique r24

**Travail repris : r24/versionCode14 est installé et le projet Python avec
dépendance a réellement repris après fermeture/réouverture.** Le
[point d'arrêt précédent](PAUSE-20260908-r24.md) reste historique. Il ne décrit
plus le paquet installé ni le statut de rg. La dernière archive distante
retéléchargée et restaurée reste v15 ; les nouveautés r24 sont locales jusqu'à
la vérification d'un nouveau complément.

L'[ancien état r21 et ses détails](HANDOFF-r21-20260908.md) est conservé comme
historique. Les consignes opérationnelles actuelles figurent ci-dessous.

## État historique r24, recherche et projet avec dépendance

Photographie à **15:58:54 UTC** : r24, moteur GNU R5, propriétaire natif **4217
`ready`** après reprise. Le propriétaire précédent **12780 est fermé**, avec
ressources absentes et boot inchangé. La session 4217 est alors ouverte : les
reçus de 12780 ne lui sont pas attribués. Ne pas réutiliser ces PID comme état
courant sans relire le statut du propriétaire.

| Étape r24 | Résultat vérifié |
| --- | --- |
| APK installé | `064b8302093361aee3c5b8bb0107dc12781fc4b63b794174a1d17144906421af`, versionCode14, signature et inventaire vérifiés |
| Recherche native | 15 cas Android rg/PCRE2/JIT réussis ; arrêt puis nouvelle admission/arrêt propres |
| Régression Python | Six commandes de production réussies avec caches actifs hors runtime ; arrêt et nouvelle admission propres |
| Projet Dependency Inspector dans la conversation | Packaging 26.3 réellement téléchargé, installé et importé ; cinq tests passent ; deux constructions du zipapp sont identiques |
| Reprise du projet existant | Après fermeture/réouverture, cinq tests code 0, archive JSON/Markdown code métier 1 attendu ; wheel et archive inchangés |
| Fichiers indépendamment relus | Les 103 fichiers de la collecte précédente sont conservés ; seul `validation-resume.json` est ajouté |
| Intégrité à 15:58:54 UTC | Même boot, propriétés contrôlées et quatre APK ChatGPT officiels identiques à la collecte de reprise du travail |

APK : `downloads/native-production-20260908/foldgpt-native-candidate-r24.apk`.
Projet : `ui-python-caae3a83d156/dependency-inspector`, sous le projet d'addition
conservé. Zipapp : **133266 octets**, SHA256
`b9fb352580451e18a5c9166a3c5dc99e1988cc8110101afc9db07423f98966c1`.
Les preuves et limites sont reliées dans le
[rapport r24](../docs/research/r24-device-validation-20260908.md).
Le nom de collecte `project-after-editor` ne constitue pas une nouvelle preuve
de sauvegarde dans l'éditeur : celle-ci reste démontrée par les essais r22/r23.

Le prochain travail fonctionnel est l'intégration et la qualification du vrai
terminal PTY, puis le parcours sans PC et la décision sur le contrôleur/interface
entièrement Android. À 16:08 UTC, le candidat PTY séparé a aussi passé neuf
tests Android, avec huit propriétaires attendus code 0 et absents ; cette
exécution dans un dossier d'essai ne valide pas encore son installation ni
le terminal de l'application. Voir les
[critères de réussite](../docs/research/functional-milestones-20260908.md).

## Historique r23 : parcours Python, éditeur et reprise

Le Fold était en **r23/versionCode13, moteur GNU R5** lors de ces essais. Le petit projet Python
créé depuis la conversation en r22 a été retrouvé et réellement exécuté après
deux ouvertures successives en r23. La modification sauvegardée dans l'éditeur
est conservée ; les trois tests et le zipapp affichant 42 passent à chaque
reprise. Les deux sessions UI ont ensuite fermé proprement.

**Ce parcours concret est démontré sur le téléphone.** Le défaut de caches
qui bloquait la reprise r22 est corrigé et vérifié par de nouvelles admissions,
des commandes réelles et la reprise de la même conversation. Voir le
[rapport r23 et ses preuves](../docs/research/r23-device-validation-20260908.md).
Les autres fonctions ne sont pas toutes qualifiées.

**État laissé à Julien à 11:46 UTC : application r23 ouverte sur la même
conversation, propriétaire 6893 `ready`, handshake réussi, boot inchangé.**
Aucune commande modèle supplémentaire n'a été lancée dans cette dernière
session à cet instant. Elle a ensuite fermé proprement au point d'arrêt lié
en tête de ce document ; ne plus la traiter comme active. Preuve de lancement :
`work/root-artifacts-20260907/native-ui-validation-20260908/r23-ready-for-user/`.

| Étape | Dernière preuve vérifiée |
| --- | --- |
| Conversation → création du projet Python en r22 | PASS, trois tests et zipapp affichant 42 ; fichiers collectés indépendamment |
| Sauvegarde dans l'éditeur en r22 | PASS, commentaire relu après réouverture en r23 |
| Six commandes ordinaires r23 avec cache actif | PASS, Android/aarch64/UID 10412, caches réellement lus hors runtime |
| Admission après les commandes et nouvelle fermeture | PASS, propriétaires 22244 puis 22535 nettoyés et attendus, ressources absentes |
| Première reprise dans la conversation, 11:41 UTC | PASS, trois unittest, zipapp existant affichant 42, cache extérieur confirmé |
| Seconde ouverture et nouvel échange, 11:43 UTC | PASS, commentaire conservé, trois unittest et zipapp existant affichant 42 |
| Fermetures des deux sessions UI r23 | PASS, propriétaires 22808 et 29860, deux reçus propres et ressources absentes |
| Intégrité pendant l'essai | Boot, propriétés contrôlées et quatre APK ChatGPT officiels inchangés |

Projet à conserver : **« Validation Python FoldGPT »**, conversation
**« Créer et tester une addition Python »**, dossier
`/data/user/0/app.foldgpt/files/projects/ui-python-caae3a83d156`, mode
**Accès complet**. Les tests portent sur 20 + 22, -2 + 2 et 1 + 2. Après sauvegarde dans
l'éditeur, `addition.py` fait 89 octets et son SHA256 est
`f9d6616102991bd0b4debba05ced51b1d37ce447b467f76159cdb26af38da205`.

Les preuves r23 sont sous `work/r22-cache-20260908/ui-r23/` :
`model-tool-evidence.json`, `model-tool-evidence-second.json`,
`editor-second-reopened.json`, les trois collectes `project-*` et les deux
rapports `stop-*/report.json`. Les trois archives du projet ont le même SHA256 :
`c6a77ffdbf39fc3187c261db6fa2e2b72073859fc53de185dd5222ef2b6284a4`.
Les sorties des outils modèle prouvent l'exécution ; les collectes indépendantes
prouvent séparément la conservation des fichiers. Les preuves r22 de création,
sauvegarde et fermeture restent dans `work/r21-device-return-20260908/ui-r22/`.

## Correctif r23 installé et vérifié

Le lanceur configure le cache CPython par défaut dans
`/data/user/0/app.foldgpt/files/native-runtime-v1/python-cache`, frère du
runtime signé. Le bytecode reste activé et l'inventaire du runtime reste strict.
Les options explicites `-X pycache_prefix` et l'environnement autorisé gardent
leurs règles CPython. Les tests hôtes couvrent aussi `-I`, `-E` et
`subprocess(env={})` ; les commandes Android de qualification utilisent Python
normal, avec `dont_write_bytecode=false`, `isolated=0`, `ignore_environment=0`.

APK : `downloads/native-production-20260908/foldgpt-native-candidate-r23.apk`.
SHA256 : `3a1bb00e73a828fa298884941514ad421a5f888c7fe483303b0ad514f2122c74`.
Paquet : `downloads/native-ordinary-uid-20260908/production-package-r23`.
Vérifications : **87 ELF, 2 447 fichiers Python, 86 alias, 95 sources** et
signature Android contrôlés. Deux builds NDK29/API 35 du CLI sont identiques,
SHA256 `0a0d95ebca43d0cce2e77dd8f288c9783933508edf33e66b4645791726102c76`.
Onze tests réels Windows CPython 3.14.7 produisent 55 caches tout en préservant
les 2 477 fichiers du runtime de test. Ce test hôte ne valide pas Android.

Les rapports, commandes exactes et vérifications du paquet sont sous
`work/r22-cache-20260908/` : `CLI-README.md`, `host-v1/verification.json`,
`r23-packaging-and-validation.md`, `r23-apk-verification.json` et
`r23-signature.txt`. La maintenance Android a préservé les 81 fichiers des
14 répertoires stdlib `__pycache__` hors du runtime. La lecture indépendante
confirme leurs octets ; l'inventaire vérifie les 2 447 sources et 86 alias.
Aucune permission existante n'a été modifiée. Preuves :
`device-archive-v2/receipt.json` et `device-archive-v2/independent-readback.json`.

Commande de qualification déjà exécutée avec succès :

```powershell
python -B tools/runtime/qualify-production-device.py --qualification ordinary-uid --verify-restart --apk-sha256 3a1bb00e73a828fa298884941514ad421a5f888c7fe483303b0ad514f2122c74
```

Le `-B` concerne ce pilote PC, pas les commandes natives du projet. Rapport :
`downloads/native-ordinary-production-device-20260908/9d653b2d/report.json`.
Les reprises UI ont ensuite été exécutées et vérifiées séparément : le succès
du pilote n'est pas utilisé comme substitut de conversation ou d'éditeur.
Les reçus de fermeture concernent chaque propriétaire identifié. La session
6893 avait son propre arrêt au point de pause ; ne pas rejouer les anciens
essais ou la maintenance des caches pour ouvrir l'application.

## Architecture et limites

Les commandes Bash/Python/rg s'exécutent nativement sous Android/Bionic et l'UID
ordinaire de FoldGPT. **L'interface et le contrôleur GNU restent sous PRoot ;
aucune VM ne tourne sur le téléphone.** Le produit complet n'est donc pas encore
« tout Bionic ». Le moteur séparé conserve nos adaptations ; l'application
officielle reste intacte et peut suivre ses mises à jour normales. Le maintien
de notre interfaçage après chaque version future reste un travail à vérifier.

Le CI natif ciblé `34215637059` passe 193 unittest et 25 commandes. La suite Rust
générale R5 `34192652057` est terminée en **échec** : 16 933 tests réussis,
238 échecs, deux timeouts et 35 ignorés. Le [triage des 240 cas](../docs/research/r5-failure-audit-20260908.md)
conserve ces limites ; les succès ciblés ne valident pas cette suite générale.
Les preuves sont sous `work/ci-results/34192652057`.

`rg` était absent lors de la création r22 ; r24 l'ajoute et le qualifie sur Android.
Le PTY (`tty=true`), les programmes interactifs, tous les outils du runtime,
les autres profils et l'ensemble des comportements de reprise ne sont pas
qualifiés par ce petit projet. Le [choix des adaptations communautaires](../docs/research/community-selection-20260908.md)
conserve les pistes Bionic/V8/verrous sans les présenter comme déployées.
L'[audit historique des traces r20](../docs/research/device-evidence-audit-20260908.md)
et le [bilan des blocages](../docs/research/blockers-and-community-20260908.md)
restent des preuves datées ; leurs anciennes prochaines étapes ne remplacent
pas l'état r24 ci-dessus.

Aucun root, flash, déverrouillage du bootloader ou changement des protections
du téléphone. Ne pas rejouer l'ancien diagnostic GNU/PRoot/ptrace associé aux
redémarrages inexpliqués, ni effacer une quarantaine pour fabriquer une fermeture.
L'incident r21/PID29981 et sa récupération restent conservés séparément dans
`work/r21-device-return-20260908/`. Le SDK Shizuku ne recrée pas les droits ADB
après un reboot. Les anciennes mesures mémoire ne prouvent aucun plafond
général de 2 Gio : voir le [rapport mémoire](verification/android-memory-20260907.json).

## Sauvegarde et reprise sur un autre PC

Dossier unique : **`C:\Dev\ChatgptFold`**. Dépôt privé de sauvegarde :
**`pironjulien/FoldGPT-workspace`**, branche **`codex/foldgpt-beta`**.
Le dépôt public historique `FoldGPT` ne reçoit pas cette sauvegarde privée.
Le remote nommé `origin` doit être vérifié avant publication : son nom seul
ne désigne pas le dépôt privé. Le moteur de travail reste dans
`work/worktrees/FoldgptEngine`, sous le dossier du projet.

La dernière sauvegarde privée retéléchargée et restaurée est le
[complément v16](supplement-v16.md) : **39 584 fichiers et 1 252 sources Git
vérifiés**, APK r24/r25 restaurés revérifiés. Le checkpoint
`c674ad714d44b98c1baee3a370a75d16f08185f8` contient les nouveautés r24/r25,
les recherches et les preuves de reprise et PTY. Les conversations et journaux
privés sont chiffrés. Les sources GPU/PTY en attente sont inchangées depuis v13.

Commencer par la [procédure de restauration](README.md). Conserver l'archive
principale et tous les compléments : [v10](supplement-v10.md),
[v11](supplement-v11.md), [v12](supplement-v12.md),
[v13](supplement-v13.md), [v14](supplement-v14.md), [v15](supplement-v15.md)
et [v16](supplement-v16.md), ainsi que les précédents
référencés dans cette procédure. V13 conserve notamment r20, R5 et Bash
production ; v14 ne remplace pas ces archives. La [restauration v9](README.md#complément-v9--python-natif-v2-réussi-sur-le-fold)
et son [rapport exact](verification/github-supplement-v9-restoration.json)
restent accessibles. La clé de déchiffrement reste au coffre, jamais dans GitHub.

Le [protocole r21](android-return-r21.md) reste historique : ne pas réinstaller
ce candidat ni réutiliser ses PID/empreintes comme état actuel. Pendant le
travail actif, conserver le maintien éveillé demandé ; à l'arrêt, utiliser
`tools/runtime/protect-idle-screens.ps1 -ActivateNow` pour rétablir la protection
des écrans.
