# Sauvegarde v16 : recherche native et terminal du modèle r25

Le [complément privé v16](https://github.com/pironjulien/FoldGPT-workspace/releases/tag/recovery-2026-09-07)
conserve les sources au commit `c674ad714d44b98c1baee3a370a75d16f08185f8`,
les APK r24/r25, leurs packages et dépendances de compilation, les recherches
et les preuves du projet Python et du terminal du modèle. Les conversations
et journaux sont dans la charge chiffrée ; la clé reste au coffre.

La sauvegarde a été retéléchargée, authentifiée et restaurée dans un dossier
neuf sous `C:\Dev\ChatgptFold` : **39 584 fichiers vérifiés**, soit
1 310 339 887 octets. Les **1 252 fichiers du source Git** ont ensuite été
extraits et vérifiés. Le vérificateur issu du source sauvegardé a revérifié
les deux APK restaurés avec succès. Aucun nouvel essai téléphone n'est
attribué à cette vérification de récupération.

| Fichier | Octets | SHA256 |
| --- | ---: | --- |
| `native-checkpoint-v16.tar.gz.age.part001` | 461 293 252 | `2db3a46eddb35b6d5e2ef033f5df0cba327e4ba00dc0e5e4552a2839c7e62264` |
| APK r24/versionCode14 | 81 318 297 | `064b8302093361aee3c5b8bb0107dc12781fc4b63b794174a1d17144906421af` |
| APK r25/versionCode15 | 81 340 565 | `2618abba092af33ac387906d75b57ecfd7b76ec7aa02d80b6c20fee4f44a28a3` |

La sélection figée comporte 39 565 fichiers d'artefacts. L'archive ajoute
les seize manifestes antérieurs, le source Git, son checkpoint et la preuve
des vérifications APK. Les sources Rust sous `cc/src/target` sont conservées :
ce sont des sources requises, et non un cache de compilation. Le contrôle
du source distingue les conversions de fins de ligne Git des changements
de contenu avant de restituer les octets attestés dans une copie isolée.
Les quinze sources GPU/PTY encore en attente sont identiques aux octets
déjà récupérés depuis v13 : [contrôle](verification/pending-sources-v16-audit.json).

Le [rapport r25](../docs/research/r25-device-validation-20260908.md) démontre
la saisie et Ctrl+C du modèle depuis la conversation, puis cinq tests Python,
l'archive du projet et rg. Les 104 fichiers du projet sont inchangés. Le panneau
de terminal utilisateur reste à raccorder ; démarrage sans PC et mises à jour
restent à qualifier. L'interface et le contrôleur GNU utilisent encore PRoot.
La suite Rust générale reste en échec documenté. Les essais échoués sont conservés.

Conserver **l'archive principale et les compléments 1 à 15 avant v16**.
Leurs seize manifestes et métadonnées distantes ont été vérifiés. Cette passe
restaure v16 ; elle ne restaure pas à nouveau toutes les archives historiques.

Rapports : [publication](verification/github-supplement-v16-publication.json),
[restauration](verification/github-supplement-v16-restoration.json),
[APK restaurés](verification/github-supplement-v16-r24-r25-apks.json),
[manifeste](verification/supplement-v16-manifest.json).

Restaurer avec `tools/recovery/restore-archive.py`, le manifeste
`native-checkpoint-v16-manifest.json`, l'identité existante
`%OneDrive%\Documents\NexusSecure\projects\FoldGPT\recovery.agekey` et un
dossier neuf sous `C:\Dev\ChatgptFold\work\FoldGPT-recovery`. La clé n'est
jamais copiée dans le projet. La branche Git conserve les mises à jour
documentaires postérieures au checkpoint, dont ce reçu de livraison.
