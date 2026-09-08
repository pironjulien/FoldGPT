# FoldGPT — point d'entrée de reprise

**Dernier état : r25/versionCode15 installé, terminal interactif du modèle
validé depuis la conversation, cinq tests Python et rg toujours réussis.**
Voir le [rapport r25](docs/research/r25-device-validation-20260908.md) pour les
preuves, la dernière ouverture et les fonctions encore à terminer.

**Priorité confirmée par Julien : ouvrir FoldGPT et travailler avec le PC
éteint.** Le panneau de terminal manuel est reporté ; il n'est pas nécessaire
pour qualifier le travail depuis la conversation. Le prochain essai doit
isoler le démarrage de Shizuku depuis le téléphone, puis la reprise du projet
sans commande de préparation envoyée par le PC.

Le statut technique actuel et les prochaines étapes sont dans
[recovery/HANDOFF.md](recovery/HANDOFF.md). Les commandes ordinaires depuis
l'interface sont maintenant validées pour le parcours Python natif Android :
création, tests, construction, puis reprise d'un projet avec Packaging 26.3
sous r24. Le panneau de terminal utilisateur et le fonctionnement sans PC après reboot restent
à qualifier ; interface et contrôleur utilisent encore PRoot.

La récupération des sources, dépendances et preuves est décrite dans
[recovery/README.md](recovery/README.md). Le dépôt de travail est **privé** :
`pironjulien/FoldGPT-workspace`, branche `codex/foldgpt-beta`.
Le [complément v16](recovery/supplement-v16.md) est publié, retéléchargé et
restauré : 39 584 fichiers et 1 252 sources Git vérifiés, APK r24/r25 revérifiés.
Conserver l'archive principale et les compléments 1 à 15 avant v16.

Les preuves et limites de chaque essai sont consignées dans les documents liés.
Les consulter avant toute action sur le téléphone ; aucune publication publique
ne fait partie de cette reprise.
