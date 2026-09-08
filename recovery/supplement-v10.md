# Sauvegarde v10 : exécution native r12 et sources du 8 septembre

Le complément `native-checkpoint-v10*` est publié sur la
[release privée de récupération](https://github.com/pironjulien/FoldGPT-workspace/releases/tag/recovery-2026-09-07).
Il a été retéléchargé depuis GitHub, authentifié par age, déchiffré et restauré
sur Windows dans le dossier du projet. Les **25 232 fichiers** ont ensuite été
relus et vérifiés, soit **2 265 207 387 octets** ; aucun lien symbolique.

Cette sauvegarde conserve l'APK **r12**, le runtime gelé `package-r3`,
`stage-r2`, `admission-r2`, le JNI figé, les essais de production et de nettoyage
sur le Fold, les essais refusés, les preuves run-as/chemins partagés et les
tests PC. Le tar source correspond exactement au commit
`49c610d2345d639eda6339629b25169e48266729` ; ses **1 057 fichiers** ont aussi été
extraits dans un second dossier neuf et vérifiés. Le patch moteur vient de ce
commit, sans reprendre les modifications v2 qui continuaient en parallèle.

Cette vérification établit une sauvegarde récupérable. Elle ne qualifie pas
l'interface habituelle ni les développements v2 encore ouverts à cet instant.

## Contenu chiffré et preuves

Le manifeste public est `native-checkpoint-v10-manifest.json`. Les deux parties
totalisent **1 168 147 505 octets**. SHA-256 combiné :

`15e10f26b1323ce24274b01217645d5ee2ece62afa454f958ce1535f1f88f40f`

| Partie | Octets | SHA-256 |
| --- | ---: | --- |
| `native-checkpoint-v10.tar.gz.age.part001` | 1 073 741 824 | `022cff3d36c5f781eecc6265ca20964ced6bdd45dba3cc1a47c26b2405a828ca` |
| `native-checkpoint-v10.tar.gz.age.part002` | 94 405 681 | `94c726dcc9cb161cd0b0799723f8ecc73a5ec36bd10c761e598f8669c279f9d7` |

Les tailles et SHA-256 des assets GitHub et des fichiers retéléchargés concordent.
Après restauration, le vérificateur issu du tar source a contrôlé à nouveau les
85 ELF, 2 447 fichiers Python, 86 alias et 85 sources de l'APK r12.
SHA-256 de cet APK :
`57b474f3f468e3c62470eef5e41da0385eaf2b45c944c06e2e0180b1ffaa4234`.

Rapports :

- [Publication et source restaurée](verification/github-supplement-v10-publication.json)
- [Restauration complète](verification/github-supplement-v10-restoration.json)
- [APK r12 restauré](verification/github-supplement-v10-r12-apk.json)
- [Manifeste des parties](verification/supplement-v10-manifest.json)

## Dépendances et restauration

Conserver l'archive principale et les compléments précédents jusqu'à v9 pour la
reprise complète des fichiers du poste. Leur ordre, les noms de manifestes et
leurs SHA-256 sont inscrits dans `CHECKPOINT.json` à l'intérieur de v10 ; les
dix manifestes sont aussi inclus dans `prior-recovery-manifests`. Ils ont été
retéléchargés et comparés aux métadonnées GitHub pour ce point de sauvegarde.
Les archives antérieures complètes n'ont pas été retéléchargées une nouvelle
fois dans cette vérification v10.

Utiliser des destinations neuves sous `C:\Dev\ChatgptFold\work`. Sur Windows,
le préfixe `\\?\` prend en charge les chemins Python profonds sans modifier
un réglage système. Exemple, depuis le projet :

```powershell
gh release download recovery-2026-09-07 --repo pironjulien/FoldGPT-workspace --pattern 'native-checkpoint-v10*' --dir C:\Dev\ChatgptFold\work\v10-download
$foldV10Key = Join-Path $env:OneDrive 'Documents\NexusSecure\projects\FoldGPT\recovery.agekey'
python -B tools/recovery/restore-archive.py --assets C:\Dev\ChatgptFold\work\v10-download --manifest native-checkpoint-v10-manifest.json --identity $foldV10Key --destination '\\?\C:\Dev\ChatgptFold\work\v10-restored' --report C:\Dev\ChatgptFold\work\v10-restoration.json
```

Le script canonique authentifie l'archive avant extraction et vérifie tous les
fichiers restaurés. Le dossier extrait contient `repository-source-49c610d.tar`.
Pour extraire ce tar source avec Python sous Windows, utiliser `TarFile.extract`
avec `filter="data"` pour chaque entrée : `extractall` peut mélanger les
séparateurs lors de l'application différée des métadonnées des répertoires.
Ce défaut de l'étape supplémentaire a été conservé dans le journal ; une
nouvelle extraction par entrée a ensuite vérifié tous les fichiers et dossiers.
La restauration canonique du complément avait déjà réussi intégralement.

Le tar source n'inclut pas les fichiers internes des sous-modules Git : ceux-ci
restent fournis par la reprise Git et les archives antérieures documentées dans
le [README de récupération](README.md). Ne pas écraser automatiquement des
fichiers existants : certains anciens compléments conservent d'autres versions
aux mêmes emplacements.

La clé age et la clé de signature restent dans NexusSecure. Aucun de ces secrets,
ni aucun fichier déchiffré, n'a été téléversé. Cette opération de sauvegarde n'a
effectué aucune commande sur le téléphone et n'a modifié ni l'index ni HEAD Git.
