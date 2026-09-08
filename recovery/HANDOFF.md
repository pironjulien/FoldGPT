# Reprise technique du 8 septembre 2026

**Pause demandée par Julien : lire d'abord [le point d'arrêt r24](PAUSE-20260908-r24.md).**
R23 reste installé ; sa session6893 est maintenant fermée proprement et le
téléphone remis en veille. Rg est compilé et empaqueté sur PC, pas installé.
Une sonde PTY fixe réussit sur le Fold ; le backend PTY reste à intégrer.
La dernière archive distante complète reste v15. Le reste de ce document
décrit le parcours r23 précédemment validé et ses preuves historiques.

L'[ancien état r21 et ses détails](HANDOFF-r21-20260908.md) est conservé comme
historique. Les consignes opérationnelles actuelles figurent ci-dessous.

## État actuel : parcours Python, éditeur et reprise validé sur r23

Le Fold est en **r23/versionCode13, moteur GNU R5**. Le petit projet Python
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
session et elle n'est pas déclarée fermée. Preuve :
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
6893 laissée ouverte ne reçoit pas les reçus des anciennes sessions ; ne pas
rejouer les anciens essais ou la maintenance pour ouvrir l'application.

## Architecture et limites

Les commandes Bash/Python s'exécutent nativement sous Android/Bionic et l'UID
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

`rg` était absent lors de la création r22 et n'a pas été ajouté par r23.
Le PTY (`tty=true`), les programmes interactifs, tous les outils du runtime,
les autres profils et l'ensemble des comportements de reprise ne sont pas
qualifiés par ce petit projet. Le [choix des adaptations communautaires](../docs/research/community-selection-20260908.md)
conserve les pistes Bionic/V8/verrous sans les présenter comme déployées.
L'[audit historique des traces r20](../docs/research/device-evidence-audit-20260908.md)
et le [bilan des blocages](../docs/research/blockers-and-community-20260908.md)
restent des preuves datées ; leurs anciennes prochaines étapes ne remplacent
pas l'état r22/r23 ci-dessus.

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
[complément v15](supplement-v15.md) : **8 707 fichiers et 1 219 sources Git
vérifiés**, APK r23 restauré revérifié. Le checkpoint
`6337c98e93e70d302ed7098549735dc9bfd4b783` contient les nouveautés r22/r23,
les recherches et les preuves de reprise. Les conversations et journaux privés
sont chiffrés. Les sources GPU/PTY en attente sont inchangées depuis v13.

Commencer par la [procédure de restauration](README.md). Conserver l'archive
principale et tous les compléments : [v10](supplement-v10.md),
[v11](supplement-v11.md), [v12](supplement-v12.md),
[v13](supplement-v13.md), [v14](supplement-v14.md) et [v15](supplement-v15.md), ainsi que les précédents
référencés dans cette procédure. V13 conserve notamment r20, R5 et Bash
production ; v14 ne remplace pas ces archives. La [restauration v9](README.md#complément-v9--python-natif-v2-réussi-sur-le-fold)
et son [rapport exact](verification/github-supplement-v9-restoration.json)
restent accessibles. La clé de déchiffrement reste au coffre, jamais dans GitHub.

Le [protocole r21](android-return-r21.md) reste historique : ne pas réinstaller
ce candidat ni réutiliser ses PID/empreintes comme état actuel. Pendant le
travail actif, conserver le maintien éveillé demandé ; à l'arrêt, utiliser
`tools/runtime/protect-idle-screens.ps1 -ActivateNow` pour rétablir la protection
des écrans.
