# Validation r23 sur le Fold — 8 septembre 2026

## Résultat et périmètre

**Le parcours du petit projet Python fonctionne sur le Fold : création depuis
la conversation, trois tests, construction/exécution du zipapp, sauvegarde
dans l'éditeur, puis reprise de l'exécution après deux ouvertures successives.**
La création et la sauvegarde proviennent de r22 ; les deux reprises r23 utilisent
ces mêmes fichiers, sans recréer le programme, les tests ou l'archive.
Les sessions de validation ont toutes un arrêt réellement confirmé.

Le défaut r22 `Python runtime directory is not admitted` est corrigé : les
caches Python restent actifs et sont écrits hors du runtime signé. Les nouvelles
admissions et les appels modèle après réouverture le démontrent sur l'appareil.
Cette preuve concerne le parcours décrit ; elle ne qualifie pas le produit
entier ni toutes les fonctions de ChatGPT/Codex.

L'application a ensuite été relancée normalement pour Julien, sur la même
conversation, à 11:46 UTC : propriétaire 6893 `ready`, handshake réussi et même
boot. Cette dernière session reste ouverte ; aucune commande modèle
supplémentaire n'a été lancée. Les reçus de fermeture ci-dessous ne concernent
pas 6893.

## Version et architecture

| Élément | Identité vérifiée |
| --- | --- |
| Application | FoldGPT r23/versionCode13 |
| Téléphone | Samsung SM-F971B, Android 17, ARM64 |
| Moteur | GNU R5 avec raccordement FoldGPT |
| APK installé | `downloads/native-production-20260908/foldgpt-native-candidate-r23.apk` |
| SHA256 APK | `3a1bb00e73a828fa298884941514ad421a5f888c7fe483303b0ad514f2122c74` |
| Paquet vérifié | 87 ELF, 2 447 fichiers Python, 86 alias, 95 sources et signature Android |
| CLI Python | Deux builds NDK 29.0.14206865, API 35, octets identiques |
| SHA256 CLI | `0a0d95ebca43d0cce2e77dd8f288c9783933508edf33e66b4645791726102c76` |

Les commandes Bash/Python s'exécutent nativement avec Android/Bionic sous
l'UID 10412 de FoldGPT. **L'interface et le contrôleur GNU restent sous PRoot ;
aucune VM ne tourne sur le téléphone.** Le moteur séparé porte nos adaptations.
Cette validation ne démontre pas un produit complet « tout Bionic ».

Le lancement configure `PyConfig.pycache_prefix` après `PyConfig_Read()` vers
`/data/user/0/app.foldgpt/files/native-runtime-v1/python-cache`, frère du runtime.
L'inventaire du runtime reste strict. Les options explicites CPython, les modes
`-I`/`-E` et `subprocess(env={})` sont couverts par les tests hôtes ; les commandes
Android de cette qualification utilisent Python normal avec bytecode actif.
Voir les [sources et preuves de compilation](../../work/r22-cache-20260908/CLI-README.md)
et la [vérification de l'APK](../../work/r22-cache-20260908/r23-apk-verification.json).

## Réparation conservant les preuves r22

La fermeture UI r22 du propriétaire 8815 était propre. La relance a ensuite
refusé les 14 répertoires `__pycache__` que Python avait générés dans la stdlib.
Les ajouts étaient hors inventaire ; le refus d'admission n'a pas été supprimé.

La maintenance dédiée a vérifié la fermeture, les verrous, le manifeste signé
et les sources avant d'archiver uniquement ces caches. Les 81 fichiers des
14 répertoires restent conservés avec les mêmes octets dans le journal privé.
Les 2 447 fichiers de données et 86 alias du runtime ont été revérifiés ; aucune
permission existante n'a été modifiée. Le répertoire parent `files` avait
déjà le mode 0777 sous la racine d'application 0700 : le helper a reconnu cet
état précisément, sans changer ses permissions ni assouplir le contrôle des
répertoires du runtime. Les refus des préparations antérieures sont conservés.

Preuves indépendantes : [reçu de maintenance](../../work/r22-cache-20260908/device-archive-v2/receipt.json)
et [lecture des 81 fichiers archivés](../../work/r22-cache-20260908/device-archive-v2/independent-readback.json).
Les caches locaux déjà présents dans le projet utilisateur n'ont pas été
supprimés. Les nouveaux caches stdlib et projet utilisent le préfixe extérieur.

## Qualification de production r23

Commande exécutée depuis le PC :

```powershell
python -B tools/runtime/qualify-production-device.py --qualification ordinary-uid --verify-restart --apk-sha256 3a1bb00e73a828fa298884941514ad421a5f888c7fe483303b0ad514f2122c74
```

Le `-B` concerne le pilote PC. Les six commandes exécutées sur Android ne
reçoivent ni `-B` ni `-I` : identité via Bash `-lc`, identité via Bash `-c`,
trois unittest, construction zipapp, exécution affichant 42, puis lecture des caches.
Toutes terminent avec code 0. `dont_write_bytecode=false`, `isolated=0` et
`ignore_environment=0` sont observés. Les caches de `unittest`, `zipapp` et
`app.addition` existent, sont lus et hachés hors du runtime réel.

Le propriétaire 22244 est arrêté et attendu proprement. Une nouvelle PREPARE,
sans connexion du client de qualification, admet le runtime et crée 22535,
ensuite arrêté et attendu à son tour. Les deux étapes vérifient les reçus,
l'absence des ressources et le boot inchangé.

Le [rapport 9d653b2d](../../downloads/native-ordinary-production-device-20260908/9d653b2d/report.json)
porte `passed=true`, `firstCyclePassed=true` et `restart.passed=true`.
Sa portée exclut explicitement app-server et UI : les preuves de conversation
ci-dessous sont distinctes.

## Deux reprises dans l'interface

Projet **« Validation Python FoldGPT »**, conversation
**« Créer et tester une addition Python »**, mode **Accès complet**, dossier
`/data/user/0/app.foldgpt/files/projects/ui-python-caae3a83d156`.
Les heures ci-dessous sont UTC ; Paris est deux heures plus tard ce jour-là.

| Étape | Observation réelle | Preuve |
| --- | --- | --- |
| Première ouverture r23 à 11:39 | Handshake réussi, 370 ms | [lancement](../../work/root-artifacts-20260907/native-ui-validation-20260908/r23-first-ui/report.json) |
| Conversation à 11:41 | Commentaire relu ; trois tests OK ; zipapp existant affichant 42 ; Android/aarch64/UID 10412 ; caches unittest/zipapp existants hors `sys.prefix` ; trois codes 0 | [appels et sorties modèle](../../work/r22-cache-20260908/ui-r23/model-tool-evidence.json) |
| Fermeture après cette reprise | Propriétaire 22808, deux reçus propres, ressources absentes, boot inchangé | [rapport d'arrêt](../../work/r22-cache-20260908/ui-r23/stop-resumed/report.json) |
| Seconde ouverture à 11:42 | Nouveau handshake réussi, 227 ms | [lancement](../../work/root-artifacts-20260907/native-ui-validation-20260908/r23-second-ui/report.json) |
| Nouvel échange à 11:43 | Même commentaire ; trois tests OK ; même zipapp affichant 42 ; trois codes 0 | [nouveaux appels et sorties modèle](../../work/r22-cache-20260908/ui-r23/model-tool-evidence-second.json) |
| Réouverture du fichier dans l'éditeur | Commentaire sauvegardé réellement visible dans le contenu éditable | [capture de l'éditeur](../../work/r22-cache-20260908/ui-r23/editor-second-reopened.json) |
| Fermeture après la seconde reprise | Propriétaire 29860, deux reçus propres, ressources absentes, boot inchangé | [rapport d'arrêt](../../work/r22-cache-20260908/ui-r23/stop-second-resumed/report.json) |

Les contrôles de fermeture exigent, pour le propriétaire de chaque essai,
`bootstrapReaped=true`, `cleanupComplete=true`, `ownerRetained=false`,
`waitStatus=0`, aucune erreur de setup/cleanup ni quarantaine. Les PID,
socket, manifeste de démarrage et marqueur de session sont réellement absents.
Un `am start: Status ok` seul n'est jamais utilisé comme reçu de fermeture.

La collecte [avant ouverture](../../work/r22-cache-20260908/ui-r23/project-before-ui/report.json),
celle [après la première reprise](../../work/r22-cache-20260908/ui-r23/project-after-resume/report.json)
et celle [après la seconde](../../work/r22-cache-20260908/ui-r23/project-second-resume/report.json)
contiennent les six mêmes fichiers avec les mêmes tailles et empreintes.
Les trois `project.tar` ont le même SHA256 :
`c6a77ffdbf39fc3187c261db6fa2e2b72073859fc53de185dd5222ef2b6284a4`.
`addition.py` fait 89 octets, SHA256
`f9d6616102991bd0b4debba05ced51b1d37ce447b467f76159cdb26af38da205`.
Son commentaire reste : `# Sauvegarde depuis l'editeur FoldGPT r22 verifiee.`

Les collecteurs de fichiers gardent volontairement `executionQualified=false`
et les captures de handshake `uiWorkflowQualified=false` : chacun atteste sa
portée propre. La conclusion du parcours provient de leur combinaison avec
les vrais appels modèle, l'éditeur et les reçus de fermeture.

## Intégrité et état laissé ouvert

La [comparaison avant/après](../../work/r22-cache-20260908/integrity-comparison.json)
constate le même boot, les mêmes propriétés contrôlées et les mêmes quatre APK
ChatGPT officiels. Les valeurs observées restent `verifiedbootstate=green`,
`flash.locked=1`, `vbmeta.device_state=locked` et `warranty_bit=0`.
Le SHA256 de l'APK FoldGPT installée correspond exactement à r23. Aucun root,
flash, déverrouillage ou changement des protections du téléphone n'a été réalisé.
Ces mesures portent sur cet intervalle d'essai.

Le [dernier lancement à 11:46](../../work/root-artifacts-20260907/native-ui-validation-20260908/r23-ready-for-user/report.json)
a un handshake réussi en 285 ms. Le [statut de cette nouvelle session](../../work/root-artifacts-20260907/native-ui-validation-20260908/r23-ready-for-user/native-status.json)
identifie 6893 `ready`, sous le même boot. La conversation est laissée ouverte
pour Julien, sans nouvel appel modèle ; aucun arrêt de 6893 n'est revendiqué.

## Limites et sauvegarde

`rg` était absent lors de la création r22 et r23 ne l'ajoute pas. Les PTY et
programmes interactifs, tous les outils, les autres profils, toutes les formes
de reprise et les futures mises à jour ne sont pas qualifiés par ce scénario.
L'interface et le contrôleur GNU restent sous PRoot.

Le CI natif ciblé `34215637059` passe 193 unittest et 25 commandes, mais la suite
Rust générale R5 `34192652057` reste en échec : 16 933 réussites, 238 échecs,
deux timeouts et 35 ignorés. Le [triage des 240 cas](r5-failure-audit-20260908.md)
reste applicable. Cette réussite Android ciblée n'annule pas ces échecs.

Le [complément privé v15](../../recovery/supplement-v15.md) conserve maintenant
ces éléments r22/r23, après envoi chiffré, téléchargement et restauration :
8 707 fichiers vérifiés, 1 219 sources Git et APK r23 restauré revérifié.
L'[état de reprise](../../recovery/HANDOFF.md) conserve les liens cumulatifs
nécessaires et la suite de la livraison ; les finitions sont distinctes du
parcours fonctionnel validé ici.
