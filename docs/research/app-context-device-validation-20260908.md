# Lancement Android sans Shizuku : deux cas réels réussis

Le 8 septembre 2026, l'APK diagnostic distincte `app.foldgpt.contextprobe` a
exécuté les vrais composants Bionic r25 depuis un Service Android créé par
Zygote. **Les deux cas, sans terminal et avec PTY, réussissent sans serveur
Shizuku actif.** Cela établit la faisabilité de ces composants dans le contexte
d'une application ordinaire. Le raccordement à FoldGPT reste à réaliser.

## Ce qui a été exécuté

| Contrôle | Observation réelle |
| --- | --- |
| APK diagnostic | SHA256 `325b0bcfc6ef951d5a4ad71f067b1369c0ae44eaa15d89b1b8149e2806cae41b`, installé comme paquet distinct, jamais comme remplacement de FoldGPT |
| Origine du lancement | `am start-foreground-service` demande à Android de démarrer le Service ; Java lance Python par ProcessBuilder. Le parent Java lu indépendamment est `zygote64` |
| Identité | Java, Python de contrôle et workers sous UID/GID10415 ; filtre hérité actif, aucun traceur ni capacité ; ELF exécuté dans le répertoire natif de l'APK |
| Absence de Shizuku | `pidof shizuku_server` : code1, aucune sortie ni erreur, avant et après. Aucune API Shizuku invoquée ; l'ELF inutilisé du transport reste dans l'inventaire r25 copié |
| Cas pipe | Fichier réellement créé et relu, second Python exécuté et attendu, entrée `INPUT`, sortie `PIPE_INPUT_OK`, code23 |
| Cas PTY | Même fichier et sous-processus ; fd0/1/2 terminaux, taille80x24 ; signal `interrupt`, `KeyboardInterrupt` observé, sortie `INTERRUPTED`, sortie normale130 avec `signal=0` |
| Fermeture | Deux propriétaires réellement attendus avec code0, `cleanupComplete=true`, EOF, libération des verrous, aucune quarantaine ni propriété retenue ; Java attend aussi le Python de contrôle |
| Contrôle indépendant | Relecture des fichiers et identités physiques, inventaire comparé à l'APK, sorties et comptabilité des octets exactes ; énumération shell des processus corroborant la fermeture |
| Service terminé | `dumpsys activity services app.foldgpt.contextprobe` retourne `(nothing)` ; le processus Java peut rester en cache Android |
| Téléphone | Même identifiant de boot ; verrouillage et indicateurs d'intégrité inchangés. Aucun réglage système, reboot ou modification des protections |
| Applications | APK r25 et les quatre APK de ChatGPT officiel identiques avant/après par SHA256 |

Le Service n'accepte aucune commande, chemin ou extra fourni par un appelant.
ADB sert à installer le diagnostic et demander son ouverture ; il n'exécute
aucun de ses workers à la place d'Android. `run-as` n'a servi qu'à lire les
preuves. Il n'a pas lancé Python, le runner ou les commandes testées.

Les 89 ELF et 95 sources r25 restent identiques à l'APK source ; les données
Python ont été relocalisées dans le stockage du diagnostic par `PYTHONHOME`.
Ce n'est pas un nouveau port de Python ni une suppression d'un garde r25.

## Fermeture et limites d'observation

Les PID datés sont Java17919, Python18066, propriétaires18073/18084 et
workers18075/18086. Ils servent uniquement à lire les preuves de ce test.
Une énumération indépendante `ps -A -o PID,UID` recense1170 processus,
voit encore Java17919 sous UID10415 comme témoin positif et ne liste aucun
des cinq processus terminés.

Les lectures individuelles de `/proc/PID/stat` renvoient également ENOENT.
**ENOENT seul ne prouve pas l'absence**, car la lecture du propriétaire était
déjà masquée pendant son exécution. La preuve principale est constituée des
attentes réelles, reçus natifs de nettoyage et EOF, corroborés par l'énumération
indépendante. Le test du sous-processus Python attend normalement cet enfant ;
ce lot ne reteste pas tous les cas de descendants détachés du lot PTY antérieur.

## État de FoldGPT constaté avant le test

Le statut de production était déjà `unavailable`, Shizuku n'était pas actif
et l'ancien PID25371 n'était plus observable avant toute installation du
diagnostic. La dernière information persistée `ready=true` n'était donc pas
une preuve de disponibilité actuelle. Cet état reste inchangé après l'essai.
**Ce lot ne prouve pas la coexistence avec un exécuteur de production actif
et n'a pas remis FoldGPT en service.** Aucun arrêt de production n'a été lancé.

RAM visible : `MemTotal=11351456 kB` (environ10,83Gio utilisables par le noyau).
Mémoire disponible mesurée entre environ2,3 et2,8Gio selon l'instant.
`am memory-limiter status` répondait `disabled` avant et après ; aucune limite
ni allocation n'a été modifiée. Ces chiffres ne constituent pas une mesure
du maximum de mémoire exploitable par un travail FoldGPT.

## Portée de la décision

La dépendance intrinsèque de ces composants pipe/PTY à Shizuku est réfutée
sur le Fold testé. L'étape suivante est un propriétaire de production lancé
directement par Android, avec admission propre à cette origine et conservation
des inventaires, canaux privés, annulation et fermeture réelle.
[Analyse du raccordement](app-launch-integration-20260908.md).

Restent non qualifiés par ce lot : bootstrap de production complet, canaux
fichiers/configuration, profils managed/host, interface, anciennes conversations,
usage après reboot sans préparation PC et mises à jour. Le PTY de ce diagnostic
reçoit un signal `interrupt` ; la saisie de l'octet Ctrl+C reste attribuée au
test r25 antérieur. L'interface et le contrôleur GNU utilisent encore PRoot.

## Preuves conservées et vérification

Les [preuves sélectionnées](../../recovery/verification/app-context-20260908/manifest.json)
sont versionnées dans le dépôt privé, sans APK ni clé de signature. Le
[verdict indépendant](../../recovery/verification/app-context-20260908/independent-verification.json)
renvoie `passed=true` et distingue la preuve des reçus de la corroboration
externe. Les fichiers bruts restent aussi sous
`work/feasibility-survey-20260908/app-context/device-run-2/`.

Le [vérificateur PC](../../tools/runtime/app-context-probe/verify-receipts.py)
ne réexécute pas le harnais et n'importe pas son implémentation. Il confronte
les reçus au candidat gelé et aux fichiers relus. Les empreintes de la
livraison sont préservées par `.gitattributes`.

La première préparation `device-run-1` s'était arrêtée avant installation :
`pm path` renvoie1 pour un paquet absent et le script le traitait comme une
erreur inattendue. La vérification a été corrigée pour exiger explicitement
code1 sans sortie ni erreur. Le harnais Android et les ELF n'ont pas changé ;
`device-run-2` est le premier essai Android de ce candidat.
