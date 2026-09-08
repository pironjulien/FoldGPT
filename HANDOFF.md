# FoldGPT — point d'entrée de reprise

**Dernier état : r25/versionCode15 installé, terminal interactif du modèle
validé depuis la conversation, cinq tests Python et rg toujours réussis.**
Voir le [rapport r25](docs/research/r25-device-validation-20260908.md) pour les
preuves, la dernière ouverture et les fonctions encore à terminer.

Le statut technique actuel et les prochaines étapes sont dans
[recovery/HANDOFF.md](recovery/HANDOFF.md). Les commandes ordinaires depuis
l'interface sont maintenant validées pour le parcours Python natif Android :
création, tests, construction, puis reprise d'un projet avec Packaging 26.3
sous r24. Le panneau de terminal utilisateur et le fonctionnement sans PC après reboot restent
à qualifier ; interface et contrôleur utilisent encore PRoot.

La récupération des sources, dépendances et preuves est décrite dans
[recovery/README.md](recovery/README.md). Le dépôt de travail est **privé** :
`pironjulien/FoldGPT-workspace`, branche `codex/foldgpt-beta`.
Le dernier complément distant restauré et vérifié reste v15 ; les nouveautés
r24/r25 doivent figurer dans une livraison suivante avant d'être annoncées récupérables.

Les preuves et limites de chaque essai sont consignées dans les documents liés.
Les consulter avant toute action sur le téléphone ; aucune publication publique
ne fait partie de cette reprise.
