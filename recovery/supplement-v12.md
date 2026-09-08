# Sauvegarde v12 : exécution des fichiers Python par le modèle

Le [complément privé v12](https://github.com/pironjulien/FoldGPT-workspace/releases/tag/recovery-2026-09-07)
conserve l'APK r16, les entrées natives figées v4 et le commit source exact
`ceb905807e9d97f27c5c9b289e0f8c01e9149a44`.

Il a été téléchargé depuis GitHub, authentifié, déchiffré et restauré :
**5 506 fichiers vérifiés**, soit 268 281 068 octets. Les **1 141 fichiers**
du tar source ont été extraits et vérifiés séparément. L'APK restauré a repassé
le contrôle de ses 86 ELF, 2 447 données Python, 86 alias et 90 sources.

Le test réel `3cd6ad7f` sur le Fold exécute un fichier Python, réussit trois
unittest, construit une archive zipapp puis l'exécute avec la sortie `42`.
Les six opérations humaines passent aussi. Le nettoyage Java indépendant et
l'absence du propriétaire natif ont été vérifiés ; les propriétés du téléphone,
son boot et les quatre APK officiels ChatGPT restent identiques.
L'échec précédent r15 et la validation Linux corrigée sont également conservés.
**Ce résultat ne qualifie pas encore la conversation ni l'éditeur officiel.
Le binaire du moteur ARM R4 n'est pas inclus dans ce complément.**

Conserver l'archive principale et tous les compléments jusqu'à v11. Les douze
manifestes de dépendances et les métadonnées SHA des parties distantes ont été
revérifiés ; leurs anciennes archives n'ont pas toutes été téléchargées à nouveau.

| Fichier | Octets | SHA-256 |
| --- | ---: | --- |
| `native-checkpoint-v12.tar.gz.age.part001` | 115 675 892 | `de93cdc1962b7f927487f35873f632bfe6275611d17f2c13e8ea7de64143a318` |
| APK r16 | 78 809 881 | `a46512293c30eb644a7abef502917c4eb68bae1c40fc6bace2e539ee671e18cd` |

Rapports : [publication](verification/github-supplement-v12-publication.json),
[restauration](verification/github-supplement-v12-restoration.json),
[APK](verification/github-supplement-v12-r16-apk.json) et
[manifeste](verification/supplement-v12-manifest.json).

La clé existante reste dans NexusSecure. Seuls la partie chiffrée et son manifeste
ont été téléversés. Pour une reprise, utiliser le script canonique
`tools/recovery/restore-archive.py` avec le manifeste
`native-checkpoint-v12-manifest.json` et une destination neuve sous le projet,
puis les opérations de fusion documentées dans [README.md](README.md).
