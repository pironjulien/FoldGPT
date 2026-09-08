# r28 : reprise d'une ancienne conversation et lancement Android direct

Le paquet **r28/versionCode18** est installé. Le démarrage du propriétaire natif
vient directement de l'application Android, sans Shizuku. L'ancienne conversation
« Créer CLI Python de statistiques », auparavant bloquée sur bwrap/config.toml,
reprend depuis l'interface après mise à jour, crée le projet, corrige ses erreurs,
passe six tests et construit puis exécute un zipapp. L'arrêt normal, la
réouverture et l'exécution après reboot complet sont vérifiés. **La fiabilité durable et la parité desktop ne sont
pas encore démontrées.**

## Paquet et admission

- APK SHA-256 : `d1b218f25cff6b260570c767e68f838ea412dd99e1a69b30ba857c5ed8f32db4`.
- Origine `android-app`, UID10412, marqueur de session v2 avec la valeur Android
  `Settings.Global.BOOT_COUNT=8`, vérifiée par Java avant le lancement.
- Vérification statique du paquet : 91 bibliothèques natives, 2 447 fichiers
  Python, 87 alias et 98 sources. Cela ne constitue pas une exécution Android.
- Le premier contrôle Python direct effectué immédiatement après l'installation
  échoue : ses alias pointaient encore vers l'ancien emplacement APK. L'ouverture
  normale de FoldGPT redéploie ces alias ; la collecte Python suivante réussit.
  Aucun alias n'a été réparé manuellement pour faire passer le lancement.
- Les 327 éléments de projets antérieurs restent présents, avec les mêmes
  permissions et mêmes octets pour les fichiers. Le test ajoute sept éléments.

## Parcours observé dans l'interface

Conversation `01a07831-abaa-7a11-811f-1a6706c3da40`, tour
`01a082a0-72bc-7fc1-b208-95f5dd0606bc`. Ouverture par son bouton normal ; aucun
RPC `thread/resume` avec remplacement de cwd n'est envoyé dans ce test r28.
Le cwd précédemment réparé est donc relu après redémarrage de l'application.

La première commande renvoie réellement :

```text
/data/data/app.foldgpt/files/projects/imported-codex/2026-09-06/dans-le-dossier-de-cette-nouvelle
android
10412
```

Le modèle crée `stats-cli/stats_cli.py`, `__main__.py`, un README et les tests.
Les erreurs intermédiaires sont conservées : entrée invalide, assertion devenue
incomplète après l'ajout de `count`, entrée zipapp redondante et archive cible
placée dans ses propres sources. Des patches invalides sont aussi refusés ;
leurs refus ne sont pas présentés comme des corrections réussies.

Après correction, les **six tests passent** (`Ran 6 tests in 0.002s`, `OK`).
Le modèle construit le zipapp final dans le répertoire parent, puis le lance :

```text
count: 3
min: 2
max: 6
sum: 12
average: 4
```

Cette dernière commande termine avec code0. Le premier zipapp intermédiaire est
conservé dans `stats-cli/`, conformément à la consigne de préserver les fichiers.
La qualité de ce petit projet est distincte de la qualification de l'exécuteur.

La collecte indépendante relit les fichiers et les vraies sorties d'outils dans
le JSONL. Les préfixes des six anciennes conversations restent identiques ; seule
la conversation testée reçoit de nouveaux événements. Les deux conversations
archivées restent totalement inchangées, y compris leurs anciens chemins.

## Arrêt et réouverture

Le propriétaire PID26245 est récolté avec `waitStatus=0`, `bootstrapReaped=true`,
`cleanupComplete=true`, `ownerRetained=false`, `quarantined=false` et
`transportFailed=false`. Le socket, le manifeste de démarrage et le marqueur de
session ont disparu. Le recensement suivant ne conserve que l'activité Android
principale dans l'UID, avant le nouveau lancement.

L'ouverture suivante démarre un nouveau propriétaire PID7432. Le boot est inchangé
et les 334 éléments de projets sont conservés. Ces PID identifient ces captures,
pas un état courant à réutiliser sans vérification.

Le service garde désormais son statut foreground jusqu'à la fin effective du
worker et du nettoyage natif. **24 tests JVM passent**, dont 14 nouveaux cas de
fin, échec, générations et redémarrages concurrents. Le service compile contre
Android37 et son comportement d'arrêt ci-dessus a été observé sur le Fold.

## Limites actuelles

Le [rapport r26b](r26b-device-validation-20260908.md) établit un arrêt Android par
`Trimming phantom processes` avant Linux137 et REMOVE_TASK. Le comptage UID est
passé de 25 à 45 après plusieurs reprises de maintenance. Dans la validation r28
avec une seule conversation chargée, 30 processus UID sont relevés. Ce n'est pas
le compteur global exact des processus fantômes ni une garantie de stabilité.

Le [cycle desktop](desktop-thread-lifecycle-20260908.md) conserve longtemps les
conversations et leurs services. Les [corrections proposées](native-process-pressure-options-20260908.md)
visent le démarrage différé des outils inutilisés et la fermeture transactionnelle
des sessions réellement libérables. Elles ne sont pas encore implémentées.
Le [signal analogue chez Termux](https://github.com/termux/termux-app/issues/2366)
a été consulté dans le navigateur intégré ; aucun changement du plafond Android
ou de ses protections n'a été effectué.

Le reboot complet autorisé est également vérifié : le boot passe de
`348d453e-f4e5-40e0-8ef0-030f4d5e38af` à
`8dc407f6-5287-4873-93a4-d2dd7284828b`, et BOOT_COUNT de 8 à 9. L'ouverture normale
de FoldGPT, après déverrouillage Android, archive elle-même le marqueur v2 du
boot précédent, avec ses octets originaux inchangés. Le reçu atteste la fin du
boot précédent sans inventer un nettoyage réussi avant reboot. Un nouveau
propriétaire PID21725 démarre directement depuis l'application. Aucun serveur,
marqueur ou alias n'est préparé par le PC après reboot : ADB sert à ouvrir
l'activité et à relever les preuves, CDP à piloter le composer.

La conversation reprend le même dossier enregistré et exécute trois commandes
réelles : identité Android, six tests (`OK`, 0.001s) et zipapp existant donnant
sum12/average4. Tous les codes sont 0 ; tour
`01a082aa-28d5-7d42-a349-845b434ebf95`, durée observée 18.840s. Cela démontre la
reprise sans serveur PC ; un essai physiquement câble débranché reste distinct.
La collecte suivante préserve tous les 334 éléments sans ajout et tous les
préfixes d'historiques ; elle relève 31 processus UID à cet instant.

La première collecte après lancement avait relu trop tôt le statut `ready`
persisté de l'ancien boot, puis refusé son manifeste disparu. La collecte
suivante vérifie explicitement le BOOT_COUNT et le PID du marqueur courant ;
elle réussit sans nouvelle mutation du runtime.

La reprise automatique après mort du propriétaire pendant un même boot reste
non qualifiée. Le marqueur v1 de r26b a été archivé une fois par l'outil de
maintenance, après arrêt Android de l'UID complet, deux recensements vides et
recensement indépendant sous verrou ; aucun nettoyage antérieur n'est inventé.

Bash, Python et rg sont Bionic. L'interface desktop et son contrôleur GNU
utilisent toujours PRoot. Le panneau de terminal humain, les mises à jour du
client et l'ensemble des outils desktop ne sont pas qualifiés par ce projet
Python. L'[inventaire complet du corpus collecté](desktop-client-inventory-20260908/README.md)
fournit les commandes/routes/dépendances et conserve les inconnues dynamiques.

## Preuves reproductibles

Captures originales sous `work/app-transport-20260908/` :
`install-r28`, `app-start-r28`, `r28-functional`, `stop-r28`, `app-reopen-r28`,
`legacy-recovery-r26b-r1`, `lifecycle-foreground-r2` et
`lifecycle-foreground-service-r2`. Les événements UI sont dans
`r28-legacy-progress3.json`, les sorties complètes dans
`r28-functional/tool-outputs.json`.

La sélection versionnée et ses empreintes sont dans
[`recovery/verification/r28-20260908`](../../recovery/verification/r28-20260908).
