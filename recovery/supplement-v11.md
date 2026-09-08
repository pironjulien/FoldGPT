# Sauvegarde v11 : APK r15 et opérations natives du Fold

Le complément `native-checkpoint-v11*` est publié sur la
[release privée de récupération](https://github.com/pironjulien/FoldGPT-workspace/releases/tag/recovery-2026-09-07).
Il a été retéléchargé, authentifié, déchiffré et restauré dans le projet :
**5 487 fichiers vérifiés**, soit 267 679 822 octets. Les **1 105 fichiers**
du tar source exact `1eee8df66f43fb5af7caf965cd5b905db3660da4` ont aussi été
extraits dans un dossier neuf et contrôlés. L'APK restauré a repassé son
vérificateur : 86 ELF, 2 447 données Python, 86 alias et 90 sources.

Ce complément contient l'APK r15, les entrées natives figées v3, les essais
réussis `016fe324` et `70cf3a99` sur le Fold, le refus précurseur et les preuves
Linux du run `34183702604` (121 tests réussis). Le second essai Fold démarre
son contrôleur après 35 secondes, puis passe les six opérations réelles et
le nettoyage Java indépendant. **La conversation et l'éditeur officiel ne
sont pas encore qualifiés. Le moteur R4 n'est pas inclus comme binaire livré.**

Conserver l'archive principale et les compléments jusqu'à v10. Leurs onze
manifestes et les métadonnées SHA-256 des parties GitHub ont été revérifiés ;
les anciennes archives complètes n'ont pas été retéléchargées une nouvelle fois.
Les dépendances exactes figurent dans `CHECKPOINT.json` à l'intérieur de v11.

| Fichier | Octets | SHA-256 |
| --- | ---: | --- |
| `native-checkpoint-v11.tar.gz.age.part001` | 115 569 908 | `2465b17cb39539b5ee6572432afb815ffc4037b27e525fbc6c798bfebe3a0747` |
| APK r15 restauré | 78 809 241 | `d8f4ff35d0d06120d1ab004ce13e5f8a31e7a25b73258e8ef0cceea2a178fe7b` |

Rapports : [publication](verification/github-supplement-v11-publication.json),
[restauration](verification/github-supplement-v11-restoration.json),
[APK](verification/github-supplement-v11-r15-apk.json) et
[manifeste](verification/supplement-v11-manifest.json).

Depuis le dépôt, restaurer dans une destination neuve sous `C:\Dev\ChatgptFold\work` :

```powershell
gh release download recovery-2026-09-07 --repo pironjulien/FoldGPT-workspace --pattern 'native-checkpoint-v11*' --dir C:\Dev\ChatgptFold\work\v11-download
$foldV11Key = Join-Path $env:OneDrive 'Documents\NexusSecure\projects\FoldGPT\recovery.agekey'
python -B tools/recovery/restore-archive.py --assets C:\Dev\ChatgptFold\work\v11-download --manifest native-checkpoint-v11-manifest.json --identity $foldV11Key --destination '\\?\C:\Dev\ChatgptFold\work\v11-restored' --report C:\Dev\ChatgptFold\work\v11-restoration.json
```

La clé demeure dans NexusSecure et n'est pas incluse dans la sauvegarde.
Seules la partie chiffrée et son manifeste ont été téléversés dans la release.
