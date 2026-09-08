# R25 : terminal du modèle et projet Python sur le Fold

## Résultat du 8 septembre 2026, 16:14 UTC

**R25/versionCode15 est installé. Depuis la conversation habituelle, le modèle
utilise un véritable terminal Android/Bionic : saisie avec `write_stdin`,
réponse du programme et interruption Ctrl+C réussies.** Les commandes sans
terminal, les cinq tests du projet avec dépendance, son archive JSON/Markdown
et la recherche rg fonctionnent après cette intégration. Les 104 fichiers du
projet sont identiques avant et après r25.

Le panneau de terminal ouvert directement par l'utilisateur reste à raccorder.
Le redimensionnement est vérifié dans le backend Android isolé, pas dans ce
panneau. L'interface et le contrôleur GNU restent sous PRoot ; Bash/Python/rg
et le nouveau propriétaire PTY sont Android/Bionic. Ce résultat ne démontre
pas un port intégral de l'interface vers Android.

## Preuves

| Contrôle | Résultat mesuré |
| --- | --- |
| APK r25 | SHA256 `2618abba092af33ac387906d75b57ecfd7b76ec7aa02d80b6c20fee4f44a28a3`, signature inchangée, installation `-r` sans désinstallation |
| Paquet | 90 bibliothèques natives, 2447 fichiers Python, 87 alias, 97 sources ; sélection explicite `ordinaryUid.ptyProcessRunner` |
| Raccordement PC | 16 cas : 7 routages/registres, 5 vrais cycles PTY Linux, 4 résolutions du bootstrap avec fichiers réels |
| Packaging | 29 cas d'admission/refus ; compatibilité de l'APK r24 vérifiée ; 14 tests des entrées de commande r25 réussis |
| Backend Android isolé | 9 tests réussis, huit propriétaires attendus avec code 0 et constatés absents ; saisie binaire, taille/SIGWINCH, groupes de processus, Ctrl+C, descendants détachés et sorties saturées |
| Première session depuis la conversation | Python : `platform=android`, UID10412, `isatty(0/1/2)=true` ; le modèle écrit « bonjour FoldGPT », lit la réponse et reçoit le code 23 |
| Deuxième session depuis la conversation | Le programme attend un signal ; le modèle écrit Ctrl+C dans la vraie session et reçoit le code 130 |
| Régression sans terminal | Cinq tests réussis ; archive existante JSON/Markdown avec code métier 1 attendu ; recherche rg réussie |
| Fichiers | 104 fichiers et archive de collecte strictement identiques avant/après les essais r25 |
| Arrêt/reprise | Propriétaire19391 fermé, attendu, ressources absentes ; nouveau handshake réussi, propriétaire26951 prêt à16:14 UTC |
| Téléphone | Même boot, bootloader verrouillé, boot vérifié vert, warranty bit0 et quatre APK de ChatGPT officiel inchangés |

Les PID sont des observations datées, jamais des valeurs à reprendre pour une
commande ultérieure. Aucun redémarrage du téléphone pendant ces essais. Le
démarrage final n'a pas reçu une nouvelle commande modèle ; il ne compte pas
comme une répétition du test PTY.

Le [reçu indépendant r25](../../work/r24-native-20260908/ui/r25-milestone.json)
relie les sorties réelles de l'interface, la régression, les fichiers et la
fermeture. Les commandes ont été demandées au modèle depuis la zone de saisie
réelle ; les scripts de collecte lisent les fichiers et journaux.

- [APK](../../work/r24-native-20260908/r25-apk-verification.json),
  [signature](../../work/r24-native-20260908/r25-signature.txt),
  [installation](../../work/r24-native-20260908/r25-install.json).
- [Backend Android](../../work/native-pty-20260908/device-run-84339a6123c94addbb4c411995222350/report.json),
  [raccordement PC](../../work/native-pty-20260908/model-integration-host-v3/report.json),
  [packaging](../../work/native-pty-20260908/package-review-tests-v1/report.json).
- [Arrêt r25](../../work/r24-native-20260908/ui/stop-r25-model/report.json),
  [dernière ouverture](../../work/root-artifacts-20260907/native-ui-validation-20260908/r25-ready-for-user/report.json),
  [intégrité](../../work/r24-native-20260908/integrity-afterr25.json).

## Échec initial du harnais conservé

Le premier essai Android a passé huit tests et échoué au neuvième avec
`AttributeError: module 'os' has no attribute 'pidfd_open'`. CPython officiel
vise API24 et omet ces bindings avant API31 ; Bionic les fournit sur le Fold.
Le harnais corrigé appelle les vrais symboles Bionic par ctypes, conserve les
erreurs natives et toutes les assertions. Le produit et l'ELF n'ont pas changé.
Les huit propriétaires et le harnais du premier essai ont aussi été constatés
absents. [Cause et revue](../../work/native-pty-20260908/android-pidfd-review.md).

## Suite précise

1. Raccorder le panneau de terminal utilisateur à son propriétaire natif
   distinct : Bash interactif, saisie, taille, interruption et fermeture avec
   descendants. Le canal utilisateur reste séparé de celui du modèle.
2. Qualifier le démarrage et la reprise sans PC, puis les mises à jour réelles
   en conservant compte, conversation et fichiers.
3. Traiter explicitement le contrôleur Bionic et l'hôte de l'interface. Les
   recettes communautaires de CLI ne fournissent pas cet hôte Electron Android.

La [comparaison communautaire](community-selection-20260908.md) et les
[critères de réussite](functional-milestones-20260908.md) conservent ces limites.
La suite Rust générale R5 reste en échec documenté : 16933 réussites,
238 échecs, deux timeouts et 35 ignorés. Ce lot ciblé ne la rend pas verte.
