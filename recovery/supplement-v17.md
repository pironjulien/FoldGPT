# Sauvegarde v17 : démarrage autonome r28 et inventaire desktop

Le [complément privé v17](https://github.com/pironjulien/FoldGPT-workspace/releases/tag/recovery-2026-09-07)
conserve les APK r26b/r27/r28, leurs packages, les preuves de lancement direct
depuis Android, d'arrêt normal et de reprise après redémarrage du téléphone.
Il contient aussi les archives originales du client desktop, l'inventaire
JavaScript/natif et les recherches sur la conservation des processus.
Les sources correspondent au commit
`34f9e603e3f1b305043661e446a6626f83824f07` ; la branche privée conserve les
mises à jour documentaires et les outils de reprise postérieurs.

La sauvegarde a été publiée, retéléchargée, authentifiée et restaurée dans un
dossier neuf : **20 008 fichiers vérifiés**, soit 3 484 889 274 octets. Les
**1 433 fichiers du source Git** ont été extraits et comparés. Les APK
r26b/r27/r28 ont repassé leur vérification depuis ce source restauré et les
44 fichiers PTY/notices hérités de v16. Les 24 346 copies d'audit omises ont
été réellement reconstruites et relues, soit 3 624 194 578 octets.

Un premier appel de reconstruction a refusé le préfixe Windows `\\?\` de sa
destination. Le chemin canonique a corrigé cet appel ; l'archive et les
fichiers authentifiés n'ont pas été modifiés. Le reçu conserve cet incident.
La copie locale concaténée du fichier chiffré, identique aux fragments
conservés, a ensuite été supprimée : 1 760 858 355 octets libérés.

| Fichier | Octets | SHA256 |
| --- | ---: | --- |
| `native-checkpoint-v17.tar.gz.age.part001` | 1 073 741 824 | `fdb04cc9486a4f9fc1b2e85206df0f2f509c40afcbd0134f9fb0eb8c39eaa460` |
| `native-checkpoint-v17.tar.gz.age.part002` | 687 116 531 | `e8d93001f3e11ab08b1735c4adc988f93b26cad4095d5816a83a3df95436f84f` |
| APK r28/versionCode18 | 81 380 149 | `d1b218f25cff6b260570c767e68f838ea412dd99e1a69b30ba857c5ed8f32db4` |

Empreinte des deux fragments concaténés :
`e5887bf1ea0650933e6a051002d659eee63f91112c1916abb00e7ce7113888fe`.
Seuls le manifeste et les fragments chiffrés sont publiés. La clé existante
reste dans `%OneDrive%\Documents\NexusSecure\projects\FoldGPT\recovery.agekey`.

Reçus : [publication](verification/github-supplement-v17-publication.json),
[restauration](verification/github-supplement-v17-restoration.json),
[APK depuis le source restauré](verification/github-supplement-v17-apks-restored-source.json),
[corpus reconstruit](verification/github-supplement-v17-corpus-reconstruction.json),
[manifeste](verification/supplement-v17-manifest.json) et
[doublon retiré](verification/supplement-v17-duplicate-cleanup.json).

## Périmètre et copies reconstructibles

La sélection figée comprend 19 988 fichiers, soit 3 454 029 672 octets.
Elle conserve les originaux installés de la version 26.901.41600 et le paquet
Debian de référence 26.901.51231 : ces deux versions restent distinctes.
Les copies extraites redondantes sont omises du complément après vérification
de leur reconstruction depuis ces originaux. Aucun historique ni fichier de
projet unique n'est supprimé. Les essais échoués restent conservés.

La reconstruction restitue les octets de 24 346 fichiers réguliers du corpus
d'audit, sans exécuter le client. Elle ne remplace pas un installateur et ne
reconstitue pas les permissions POSIX, liens ou répertoires vides : les archives
originales conservent ces informations.

Conserver **l'archive principale et les compléments 1 à 16 avant v17**.
Leurs manifestes et métadonnées distantes sont contrôlés ; cette passe ne
retélécharge ni ne restaure à nouveau toutes les archives historiques.
Lire la [procédure de reprise](README.md) pour le clone et l'intégration des
données ignorées par Git. Toutes les destinations locales restent sous
`C:\Dev\ChatgptFold\work\FoldGPT-recovery`.

Restaurer v17 avec `tools/recovery/restore-archive.py` et le manifeste
`native-checkpoint-v17-manifest.json`, dans un dossier neuf. Le dossier obtenu
contient `foldgpt-native-artifacts-v17-20260908`. Après application des
compléments, `work/FoldGPT-recovery/restore-reconstructible-v17.py` vérifie ou
reconstruit les copies omises avec `reconstruction-v17.json` ; consulter
`work/FoldGPT-recovery/supplement-v17-usage.md` pour ses arguments.

## Ce que démontre r28

Le [rapport téléphone r28](../docs/research/r28-device-validation-20260908.md)
démontre le démarrage depuis FoldGPT sans Shizuku, la création d'un projet
Python dans l'ancienne conversation, six tests, la construction et l'exécution
du zipapp. Après redémarrage complet Android, la même conversation repasse
ses tests et exécute l'archive existante sans préparation du moteur par le PC.
ADB/CDP ont piloté et observé ces essais ; le test câble physiquement débranché
reste distinct et non réalisé.

La stabilité avec plusieurs conversations et la reprise après un arrêt brutal
sur le même démarrage Android restent à corriger. Les commandes sont natives
Android/Bionic ; l'interface desktop et le contrôleur GNU utilisent encore PRoot.
Cette livraison de récupération ne démontre pas une équivalence complète au
desktop ni une interface entièrement Android.
