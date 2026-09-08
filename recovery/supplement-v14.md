# Sauvegarde v14 : candidat r21 et préparation des essais Android

Le [complément privé v14](https://github.com/pironjulien/FoldGPT-workspace/releases/tag/recovery-2026-09-07)
conserve les sources au commit `9e1feeaff2e2501299f272c95ab5b2641d2044df`,
l'APK **r21/versionCode11**, les stages/admissions/paquets natifs v1 et v2,
la compilation Android NDK v7 et les preuves PC. Le candidat à utiliser est
`downloads/native-production-20260908/foldgpt-native-candidate-r21.apk`, construit
avec **production-package-v2**. Les entrées v1 restent des preuves historiques.

La sauvegarde a été retéléchargée, authentifiée, déchiffrée et restaurée sous
`C:\Dev\ChatgptFold` : **10 695 fichiers vérifiés**, soit 469 825 889 octets.
Les **1 198 fichiers** du tar source exact ont également été extraits et contrôlés.
Le vérificateur provenant des sources restaurées a revérifié l'APK restauré :
87 bibliothèques natives, 2447 données Python, 86 alias et 95 sources.

| Fichier | Octets | SHA-256 |
| --- | ---: | --- |
| `native-checkpoint-v14.tar.gz.age.part001` | 159 873 765 | `912077718c5546a17b76677dc44e15a9e857945ede02512ed69694f37b985da8` |
| APK r21 | 78 846 377 | `cdfbe23c7ce9e89d499bf4fcbfdf97a9380ab4b7d1faa95db78b52aa8149e4a0` |

La CI Linux `34203936964`, snapshot `f87566908e7245550ebc59783b0d85f80264b437`,
a terminé ses 25 commandes avec code0 et ses **190 tests Python/natifs sans
échec ni test ignoré**. Les deux essais précédents et leurs causes d'échec sont
conservés. Ces tests incluent un véritable projet Python à travers les canaux
de production, mais pas une conversation dans l'interface Android. La suite
Rust générale du moteur R5 est distincte ; consulter son état dans [HANDOFF.md](HANDOFF.md).

**r21 n'est pas installé sur le téléphone.** Le mode Accès complet natif et le
mode managed sont sélectionnés séparément ; aucun basculement automatique ne
remplace un refus. Le [protocole de retour](android-return-r21.md) exige la
résolution de l'ancienne session8507, puis les preuves d'exécution, conversation,
éditeur/sauvegarde et fermeture/reprise. Le projet complet reste non qualifié.

Conserver l'archive principale et les compléments1à13. Leurs manifestes et les
métadonnées distantes ont été revérifiés ; seule v14 a été retéléchargée lors
de cette passe. Les 15 sources GPU/PTY non qualifiées correspondent toujours
octet par octet à celles déjà restaurées depuis v13 ; voir
[leur contrôle](verification/pending-sources-v14-audit.json).

Rapports : [publication](verification/github-supplement-v14-publication.json),
[restauration](verification/github-supplement-v14-restoration.json),
[APK restauré](verification/github-supplement-v14-r21-apk.json) et
[manifeste](verification/supplement-v14-manifest.json).

Pour restaurer ce complément, utiliser `tools/recovery/restore-archive.py`
avec `native-checkpoint-v14-manifest.json`, l'identité existante
`%OneDrive%\Documents\NexusSecure\projects\FoldGPT\recovery.agekey` et une
destination neuve sous `C:\Dev\ChatgptFold\work\FoldGPT-recovery`.
La clé reste dans NexusSecure ; seuls la partie chiffrée et son manifeste ont
été téléversés. La branche Git conserve les mises à jour documentaires
postérieures à ce checkpoint source.
