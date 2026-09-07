# Reprise privée FoldGPT — 7 septembre 2026

Les sources actuelles sont sur la branche `codex/foldgpt-beta` de ce dépôt privé.
Les archives « Source code » générées pour le tag correspondent seulement au
premier point de sauvegarde. Commencer par `recovery/README.md` sur la branche
actuelle pour restaurer les sources, sous-modules, moteur et dépendances.

Les archives chiffrées ont réellement été retéléchargées depuis GitHub,
authentifiées, extraites et vérifiées fichier par fichier :

| Archive | Fichiers restaurés | Liens | Octets chiffrés |
| --- | ---: | ---: | ---: |
| `workspace*` — archive principale, dix morceaux | 113 900 | 441 | 9 872 503 793 |
| `native-checkpoint-v2*` | 123 | 0 | Voir le manifeste |
| `native-checkpoint-v3*` | 8 462 | 1 | 224 870 091 |
| `native-checkpoint-v4*` | 2 928 | 0 | 86 998 467 |
| `native-checkpoint-v5*` | 2 798 | 0 | 54 234 188 |
| `native-checkpoint-v6*` | 468 | 0 | 1 323 849 |

Le complément sans suffixe v2/v3/v4/v5/v6 reste historique. Utiliser les manifestes
et la procédure de restauration additive du README. Les sources Git récentes
doivent être conservées ; les scripts refusent les collisions. La restauration
principale et les fusions v3/v4 ont aussi été vérifiées sur un vrai clone Windows.

La clé de déchiffrement et la clé de signature Android restent dans le coffre
OneDrive `Documents/NexusSecure/projects/FoldGPT`, jamais dans GitHub.
Leur synchronisation locale est documentée ; leur téléchargement depuis le
second PC n'a pas été testé ici. Les installations globales et caches
régénérables du PC sont décrits dans `recovery/build-environment.md`.

Le test fixe Shizuku/Bionic crée, teste et construit un petit projet Python sur
le Fold. Les commandes ordinaires depuis l'interface restent en développement.
V9 identifie un refus de création du socket au démarrage, avec bootstrap attendu
et nettoyé ; le worker noyau n'a pas démarré. Les refus v7/v8 provenaient du rejeu
d'un ancien Intent pendant les mises à jour, avant préparation des nouveaux
alias. Lire `recovery/HANDOFF.md` et les rapports corrigés avant toute reprise.

V10 dépasse le refus de socket, puis confirme un refus `/linkerconfig` pendant
la construction du backend. Sa session reste en quarantaine, sans preuve de
nettoyage ni lancement de worker de qualification. Le complément v5 conserve
l'APK exact, ses sources figées, les tests PC et les rapports Android. Lire le
rapport v10 avant toute opération sur le téléphone ; ne pas rejouer sa fixture.

V6 complète la couverture des anciens builds et rapports ajoutés dans
`downloads` depuis la première sauvegarde. Il ne contient pas un nouvel essai
Android. Les métadonnées `.git` et caches régénérables restent exclus.
