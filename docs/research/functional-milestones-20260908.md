# Ce qui est acquis et ce qui permet de terminer — 8 septembre 2026

**Dernier résultat :** les vrais composants pipe/PTY r25 fonctionnent depuis
une application Android ordinaire sans Shizuku. Deux cas réussis avec collecte
indépendante ; [preuves](app-context-device-validation-20260908.md).
Le lancement de production reste à raccorder ; ce résultat ne qualifie pas
encore la reprise complète de FoldGPT sans PC après reboot.

**Priorité précisée par Julien : ouvrir FoldGPT, écrire une demande et travailler
avec le PC éteint.** Le panneau de terminal manuel est reporté ; sa réalisation
n'est pas un préalable à ce parcours. L'exécution locale est déjà démontrée
pour Python ; le démarrage autonome est un contrôle distinct. Le lanceur Android
existe, mais attend Shizuku actif. Les derniers essais ont démarré Shizuku via
ADB depuis le PC. Ne pas confondre cette préparation avec l'endroit où les
commandes du modèle s'exécutent, ni déduire une dépendance permanente au câble.

Le [manuel officiel Shizuku](https://shizuku.rikka.app/guide/setup/#start-via-wireless-debugging),
relu dans le navigateur intégré pendant cette clarification, documente le
démarrage sans ordinateur via le débogage sans fil à partir d'Android 11.
Il précise que les étapes de démarrage doivent être répétées après reboot.
Le SDK et notre UserService existent déjà dans FoldGPT ; ils ne démarrent pas
le serveur Shizuku. Intégrer un lanceur dédié et qualifier la procédure sur
le Fold sont des travaux distincts. Aucun automatisme complet après reboot
ni essai sans PC n'est revendiqué par cette lecture documentaire.

**Mise à jour r25 :** le terminal utilisé par le modèle est maintenant validé
depuis la conversation, avec saisie et Ctrl+C. Les cinq tests Python, le zipapp
existant et rg passent ensuite ; arrêt et réouverture propres. Le jalon du
**panneau de terminal utilisateur** ci-dessous reste à réaliser. La totalité
native exige toujours les jalons contrôleur et interface.
[Preuves r25](r25-device-validation-20260908.md).

**On peut déjà créer, tester et construire un petit projet Python depuis la
conversation sur le Fold, modifier son fichier et reprendre le travail après
fermeture. Ce parcours a réellement réussi. Le projet complet n'est pas fini :
r24 a qualifié la recherche native sur le Fold ; le projet avec dépendance
passe cinq tests et son zipapp existant fonctionne après fermeture/réouverture.
Le panneau de terminal utilisateur reste à qualifier et l’interface/le contrôleur utilisent PRoot.**

Cette photographie intègre le [rapport r24](r24-device-validation-20260908.md),
les sorties du projet avec dépendance jusqu'à sa reprise et les neuf tests
du backend PTY exécuté séparément sur le Fold.
La revue distingue les corrections réelles et les limites des contrôles, sans
transformer le test nommé `stable` en preuve de stabilité JSON générale.
Aucun pourcentage, probabilité de réussite ou
délai n'est déduit du nombre de jalons ; leurs charges sont très différentes.

## Preuves de départ

| Fonction | Ce qui a réellement réussi | Limite de la preuve |
| --- | --- | --- |
| Projet Python | Conversation r22 : vrais fichiers, trois unittest, zipapp affichant 42 ; éditeur et sauvegarde | Petit projet sans dépendance externe |
| Reprise | Deux ouvertures r23, mêmes fichiers et commentaire sauvegardé, tests et archive existante réexécutés, arrêts propres | Ne couvre pas toutes les interruptions ou un reboot Android |
| Exécution native | Bash/Python Android/aarch64 sous l'UID FoldGPT 10412 ; caches actifs hors runtime | Interface et contrôleur GNU encore sous PRoot ; aucune VM sur le téléphone |
| Recherche rg | R24 installé : 15 cas réels Android, PCRE2/JIT exécuté, fermeture puis nouvelle admission/arrêt propres | Qualification de production hors UI ; fermeture explicite du stdin modèle après écriture non qualifiée |
| pip et dépendance | Conversation r24 : vrai téléchargement/hash de Packaging 26.3, installation/import, cinq tests, zipapp identique sur deux builds et réexécution de l'archive après fermeture/réouverture ; 103 fichiers conservés | Le mode d'exclusion rg explicite est documenté hors Git ; la stabilité JSON générale et un nouveau geste éditeur ne sont pas déduits de ces tests |
| Terminal du modèle | R25 installé : deux vraies sessions depuis la conversation, saisie et Ctrl+C, codes 23/130 ; régression sans terminal, arrêt et réouverture réussis. Backend Android : neuf tests dont resize/descendants/saturation | Le panneau de terminal utilisateur et son redimensionnement ne sont pas raccordés ; l'interface utilise encore PRoot |

Les mesures r23 puis r24 à 15:58:54 UTC constatent bootloader verrouillé, boot
vérifié et quatre APK ChatGPT officiels inchangés pendant les essais. Le périmètre conserve cette
contrainte : aucun root, flash, déverrouillage ou changement des protections.
Une mesure passée n'est pas une promesse sur toutes les mises à jour futures.

## Critères de réussite, dans l'ordre utile

| Jalon | Test qui permet de le déclarer réussi | Ce qui interdit de le déclarer réussi |
| --- | --- | --- |
| Recherche et projet avec dépendance | Depuis la conversation habituelle, utiliser le vrai rg, télécharger et vérifier Packaging 26.3, l'installer réellement dans `.deps`, écrire les modules et tests de Dependency Inspector, produire JSON/Markdown et un zipapp qui embarque la dépendance, puis réexécuter après sauvegarde et reprise | Un `--help`, une commande lancée uniquement depuis le PC, une dépendance copiée depuis un autre runtime ou un rapport sans sorties et codes réels |
| Travail sans PC | Téléphone débranché : démarrer l'application, reprendre le projet et exécuter ses tests ; répéter après fermeture complète, pliage/reprise, passage en arrière-plan et redémarrage Android normal, avec un parcours d'autorisation documenté | Une préparation ADB depuis le PC indispensable à chaque séance, une session ancienne restée prête, ou l'affirmation que le SDK Shizuku suffit à relancer ses droits après reboot |
| Installation et mises à jour | Installer/reprendre avec la procédure documentée ; qualifier une mise à jour réelle disponible de FoldGPT et du client officiel en conservant compte, conversation et fichiers ; vérifier les versions et reprendre les tests | Des fichiers officiels modifiés, une perte de données ou une compatibilité future annoncée sans essai ; l'absence de version amont disponible doit rester une limite explicite |
| Contrôleur entièrement Bionic | Construire le moteur séparé avec son raccordement FoldGPT, exécuter réellement V8/code-mode, authentification, fichiers/processus, puis le même projet depuis l'interface avec arrêt/reprise | Un fork CLI générique qui perd notre intégration, une compilation ou un `--help` sans charge réelle, une fonction retirée pour faire passer le test |
| Interface entièrement native Android | Démontrer un hôte Android conservant les services attendus de l'interface officielle, puis le parcours complet et sa mise à jour, sans Electron Linux ni PRoot pour l'interface | Le seul remplacement de la CLI, une page WebView de démonstration ou une nouvelle interface présentée comme l'application officielle inchangée |

Le **panneau de terminal manuel**, distinct du terminal du modèle validé en r25,
reste un travail reporté de parité fonctionnelle. Pour le qualifier ultérieurement :
ouvrir un vrai Bash interactif, saisir, redimensionner, interrompre et fermer
un travail avec descendants ; vérifier les sorties et la disparition réelle
des processus détenus. Aucun composant n'est supprimé et aucun succès n'est
attribué à ce panneau tant que ces contrôles n'ont pas été réalisés.

Le projet Dependency Inspector créé utilise un wheel universel réel de
Packaging 26.3 : SHA256
`d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c`.
Les trois entrées d'exemple doivent produire exactement une dépendance
compatible, une incompatible et une absente. Leurs noms sont des données :
seul Packaging doit être installé. Les prompts et la preuve PC sont dans
[`ui-qualification/`](../../work/native-ripgrep-20260908/ui-qualification/README.md).

Les jalons « contrôleur » et « interface » sont indispensables à une promesse
**tout natif Android**. Ils ne sont pas des finitions. Le parcours Python déjà
acquis demeure utile, mais il ne clôt pas cet objectif plus exigeant. Aucun
port complet de l'interface officielle vers Android n'est aujourd'hui prouvé
dans FoldGPT ou fourni par les recettes CLI comparées.

## Quand dire « utilisable », « terminé » ou « arrêt »

- **Utilisable sur le parcours Python validé** : r22/r23 le démontrent pour
  l'addition, puis r24 pour le projet avec Packaging, les tests, la construction
  et la reprise. Il faut nommer cette portée lorsqu'on le dit à Julien.
- **Utilisable au quotidien pour le développement visé** : le projet avec
  dépendance, la recherche, les commandes du modèle et le parcours sans PC ont leurs
  preuves dans l'interface, sans défaut connu bloquant ces opérations.
- **Terminé pour l'objectif initial intégral** : les critères de fonctionnement,
  d'installation/mise à jour et de totalité native sont satisfaits. Les échecs
  restants de la suite générale doivent être corrigés ou démontrés sans effet
  sur ce périmètre ; ils ne peuvent pas être appelés cosmétiques par défaut.
- **Arrêt immédiat d'un essai téléphone** : redémarrage inattendu, perte de
  fichiers, processus dont l'arrêt n'est pas confirmé ou tentative nécessitant
  une modification exclue. Conserver les traces ; ne pas répéter le même essai
  sans cause identifiée et correction contrôlable sur PC.
- **Arrêt d'une piste technique** : son test minimal reproduit une impossibilité
  dont la correction exige une contrainte interdite. Cela ferme cette piste,
  pas automatiquement toutes les autres. Si les solutions restantes imposent
  une autre interface ou une autre expérience, le dire explicitement : ce
  changement d'objectif ne peut pas être décidé silencieusement.

Le problème Bubblewrap de la voie Linux reste un fait historique. Le parcours
Python r23 démontre une autre exécution réelle sans Bubblewrap. Cela ne prouve
ni que tous les outils sont prêts, ni qu'un dernier binaire manque avant la
victoire. Il ne faut plus présenter le reste du travail sous cette forme.

## Choix communautaire suivant

**La priorité est de fermer le lot rg + PTY + vrai projet avec dépendance,
puis de décider explicitement la suite contrôleur/interface native.** Git
Bionic reste une piste communautaire ultérieure, hors du lot actuel. Si elle
est retenue, la recette Termux examinée doit conserver HTTPS, certificats et
préfixe réel FoldGPT, avec un vrai dépôt, diff, commit local et clone/fetch
qualifiés. Aucun développement Git n’est engagé par ce document.

La recette CLI Bionic/V8 DioNanos reste la piste pour porter le contrôleur,
dans un candidat séparé et sans reprendre les neutralisations identifiées.
L'interface est un chantier distinct : le README Electron actuel annonce
macOS/Windows/Linux, pas Android. Ni Git, ni V8, ni le SDK Shizuku ne fournissent
un port de cette interface. Le [comparatif communautaire](community-selection-20260908.md)
relie ces décisions aux sources vérifiées.

## Sources de cette photographie

- [Rapport r24 et revue du premier projet avec dépendance](r24-device-validation-20260908.md).
- [Rapport r23 et preuves de conversation/éditeur/reprise](r23-device-validation-20260908.md).
- [Build rg PC v4](../../work/native-ripgrep-20260908/build-v4/build.json) : double build, ARM64/Bionic et `androidExecuted=false`.
- [Préflight pip Android](../../work/r24-native-20260908/pip-preflight-63a2aba2/report.json) et [sonde PTY v4a](../../work/r24-native-20260908/pty-probe-bc976fd3/report.json).
- [Recette candidate contrôleur Bionic, non exécutée](../../work/native-port-review-20260908/candidate-recipe.md).
- [Git Termux](https://github.com/termux/termux-packages/blob/master/packages/git/build.sh), blob `f3be7d87939e5b8ea9f6c5273c72495cfae280c6`, relu via GitHub le 8 septembre : Git 2.55.0, shell/préfixe et présence HTTPS contrôlée.
- [Electron](https://github.com/electron/electron/blob/main/README.md), blob `128071b9bc690c361f62a12b180824f195832c7d`, relu via GitHub le 8 septembre : plateformes annoncées.
- [SDK Shizuku](https://github.com/RikkaApps/Shizuku-API/blob/master/README.md), blob `3ebe9fee660873cb4ac31f5b3e54a99d625ffa23`, relu via GitHub le 8 septembre : identité shell et redémarrage ADB requis après boot sans root.

## Où lire le statut courant

Le [README](../../README.md), le [point d'entrée de reprise](../../HANDOFF.md),
le [handoff technique](../../recovery/HANDOFF.md), la
[portée de publication](../releases/source-alpha.md) et le
[changelog](../../CHANGELOG.md) ont été actualisés avec les preuves r24.
Ils distinguent la route UID ordinaire réellement utilisée des anciennes
fixtures protégées. Le [complément v16](../../recovery/supplement-v16.md) est
la dernière sauvegarde distante restaurée : 39 584 fichiers, 1 252 sources Git
et les deux APK r24/r25 vérifiés.

Le point de pause r24, le rapport r23, le bilan des blocages r20 et les notes
Bionic du 7 septembre sont des photographies historiques. Leurs anciennes
prochaines étapes et leurs PID ne remplacent pas le handoff courant. Les
manifestes de compilation gardent aussi `androidExecuted=false` : la preuve
Android est un rapport séparé, sans réécriture des résultats PC antérieurs.
