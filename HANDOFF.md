# FoldGPT — point d'entrée de reprise

**Dernier état : r28/versionCode18 installé.** Démarrage direct depuis FoldGPT
sans Shizuku, ancienne conversation reprise sans correction temporaire du cwd,
projet Python créé, six tests réussis, zipapp construit et exécuté. Arrêt propre
et réouverture démontrés. Après reboot complet Android, la même conversation
repasse six tests et exécute son zipapp, sans préparation du moteur par le PC.
Voir le [rapport r28](docs/research/r28-device-validation-20260908.md).

L'[inventaire demandé du client desktop](docs/research/desktop-client-inventory-20260908/README.md)
couvre 9 737 JavaScript et 57 ELF. Il a permis d'identifier les délais de
conservation des conversations : jusqu'à une heure côté interface avant
désabonnement, puis 30 minutes côté moteur. r26b a atteint 45 processus UID
et subi un arrêt Android par dépassement de la limite des sous-processus.
Ce défaut de fiabilité reste ouvert ; aucun réglage Android n'a été désactivé.

**Priorité confirmée par Julien : ouvrir FoldGPT et travailler avec le PC
éteint.** Le panneau de terminal manuel est reporté ; il n'est pas nécessaire
pour qualifier le travail depuis la conversation. La [revue des alternatives](docs/research/phone-only-options-20260908.md)
retrouve un résultat Python Bionic sous application ordinaire : Shizuku est
une dépendance de r25, supprimée du lancement courant dans r26b/r28. La reprise
après arrêt propre et après reboot complet est démontrée. La stabilité durable
avec plusieurs conversations reste à corriger.

Le statut technique actuel et les prochaines étapes sont dans
[recovery/HANDOFF.md](recovery/HANDOFF.md). Les commandes ordinaires depuis
l'interface sont maintenant validées pour le parcours Python natif Android :
création, tests, construction, puis reprise d'un projet avec Packaging 26.3
sous r24. R28 ajoute la reprise après reboot sans préparation du moteur par le PC.
Le panneau de terminal utilisateur reste à qualifier ; interface et contrôleur
utilisent encore PRoot.

La récupération des sources, dépendances et preuves est décrite dans
[recovery/README.md](recovery/README.md). Le dépôt de travail est **privé** :
`pironjulien/FoldGPT-workspace`, branche `codex/foldgpt-beta`.
Le [complément v16](recovery/supplement-v16.md) est publié, retéléchargé et
restauré : 39 584 fichiers et 1 252 sources Git vérifiés, APK r24/r25 revérifiés.
Le [complément v17](recovery/supplement-v17.md) est publié, retéléchargé et
restauré : 20 008 fichiers, 1 433 sources Git, trois APK revérifiés et
24 346 copies d'audit reconstruites. Il complète l'archive principale et les
compléments 1 à 16. Une copie chiffrée redondante de 1,76 Go a été retirée.
Tous les téléchargements, snapshots et rapports de reprise vont sous
`C:\Dev\ChatgptFold\work\FoldGPT-recovery`. Les outils de fusion acceptent
ce confinement précis et protègent les sources Git ainsi que leurs snapshots.

Les preuves et limites de chaque essai sont consignées dans les documents liés.
Les consulter avant toute action sur le téléphone ; aucune publication publique
ne fait partie de cette reprise.
