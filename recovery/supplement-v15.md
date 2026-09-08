# Sauvegarde v15 : r23 et parcours Python repris sur le Fold

Le [complément privé v15](https://github.com/pironjulien/FoldGPT-workspace/releases/tag/recovery-2026-09-07)
conserve les sources au commit `6337c98e93e70d302ed7098549735dc9bfd4b783`,
les APK r22b/r23, les packages et compilations correspondantes, les recherches
communautaires et les preuves Android. Les incidents et rollouts complets
restent dans la charge chiffrée ; aucun journal privé ni clé n'est publié en clair.

La sauvegarde a été retéléchargée, authentifiée et restaurée sous
`C:\Dev\ChatgptFold` : **8 707 fichiers vérifiés**, 465 453 989 octets.
Les **1 219 fichiers du source Git** ont ensuite été extraits et vérifiés.
Le vérificateur issu de ce source a revérifié l'APK r23 restauré : 87 ELF,
2447 données Python, 86 alias et 95 sources.

| Fichier | Octets | SHA256 |
| --- | ---: | --- |
| `native-checkpoint-v15.tar.gz.age.part001` | 215 774 163 | `a927344626f8a0b98c5e3fec9efb32885e6790cc3fe0c49f19be827b1c868830` |
| APK r23/versionCode13 | 78 848 077 | `3a1bb00e73a828fa298884941514ad421a5f888c7fe483303b0ad514f2122c74` |

La sélection comporte 8 682 fichiers d'artefacts, auxquels s'ajoutent l'archive
Git, les manifestes précédents et la recette de récupération. Les copies
reproductibles du runtime de test Windows et les fixtures temporaires sont
exclues explicitement. L'inventaire et les commandes permettant de les
reproduire sont conservés. Aucun chemin du delta v14 n'est réinclus ; les
packages complets versionnés gardent volontairement certains octets communs.

Le [rapport Android r23](../docs/research/r23-device-validation-20260908.md)
démontre le petit projet Python, l'éditeur et deux reprises avec arrêt propre.
L'interface et le contrôleur GNU restent sous PRoot. Le résultat ciblé ne
qualifie pas tous les outils, PTY ou futures mises à jour. La suite Rust
générale R5 reste en échec documenté. Les erreurs r21/r22 et le build r22
échoué sont conservés comme tels ; aucun APK r22 inexistant n'est revendiqué.

Conserver **l'archive principale et les compléments 1 à 14 avant v15**.
Leurs quinze manifestes et métadonnées distantes ont été vérifiés. Cette passe
retélécharge et restaure v15 ; elle ne restaure pas à nouveau toutes les
archives historiques. Les 15 fichiers GPU/PTY encore en attente sont toujours
identiques à ceux restaurés depuis v13 : [contrôle](verification/pending-sources-v15-audit.json).

Rapports : [publication](verification/github-supplement-v15-publication.json),
[restauration](verification/github-supplement-v15-restoration.json),
[APK restauré](verification/github-supplement-v15-r23-apk.json),
[manifeste](verification/supplement-v15-manifest.json).

Restaurer avec `tools/recovery/restore-archive.py`, le manifeste
`native-checkpoint-v15-manifest.json`, l'identité existante
`%OneDrive%\Documents\NexusSecure\projects\FoldGPT\recovery.agekey` et un
dossier neuf sous `C:\Dev\ChatgptFold\work\FoldGPT-recovery`. La clé reste
dans le coffre. La branche Git contient les mises à jour documentaires
postérieures au checkpoint, notamment le présent reçu de livraison.
