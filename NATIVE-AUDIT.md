# Audit du démarrage natif — 5 septembre 2026

## Résultat

Le client ChatGPT s'affiche réellement sous PRoot sur le Fold, avec la bibliothèque `libfake_userns.so` chargée dans le processus principal et un renderer inspectés. Aucun processus QEMU n'était présent lors de cet audit. Ce résultat confirme un démarrage ARM64 sans émulation CPU ; il ne mesure pas les performances et ne valide pas les tâches, le navigateur ou Remote.

Le contrôle `dpkg -V chatgpt` s'est terminé sans différence signalée. Cela vérifie les fichiers couverts par les sommes du paquet installé, pas l'absence de modifications de comportement : `/etc/ld.so.preload` charge la bibliothèque dans les programmes dynamiques du conteneur.

## Isolation

Le fichier `fake_userns.c`, ajouté par l'autre outil et conservé sans modification, retire les flags de namespaces de `clone` et `unshare`, retourne un succès pour `chroot` et `setns`, fournit des identifiants de namespaces constants et redirige les fichiers de mapping vers `/dev/null`.

Le diagnostic `audit-shim.c` crée uniquement un répertoire vide et son propre fichier témoin. Exécuté sous l'utilisateur julien dans le conteneur :

```text
libc_unshare=0 errno=0; raw_unshare=0
chroot_empty=0 errno=0; outside_marker_accessible=YES
```

La réussite d'un appel à `unshare`, même par instruction SVC, n'est pas probante sous PRoot, qui intercepte lui-même les appels système. Depuis Termux hors PRoot, les namespaces user et pid n'apparaissent pas dans `/proc/self/ns`.

Le test du fichier démontre que le succès de chroot fourni par cette couche ne crée pas le confinement annoncé. Il ne constitue pas un test d'évasion d'un renderer Chromium : les restrictions supplémentaires propres à Chromium n'ont pas été évaluées. Les statuts inspectés montrent encore UID Android 10409, CapEff nul, NoNewPrivs 1 et Seccomp 2 ; Seccomp 2 seul n'identifie pas les filtres ni leur efficacité.

## État du téléphone

Vérifications ADB actuelles : warranty_bit 0, verifiedbootstate green, flash.locked 1, SELinux Enforcing. Ces indicateurs ne constituent pas une garantie contractuelle sur Samsung Care+.

## Suite retenue

Conserver ce résultat comme preuve de compatibilité native. Une solution répondant aux contraintes doit fournir un confinement réellement appliqué, puis passer une tâche personnalisée avec vérification du fichier, un test Remote et des mesures de latence. Le shim actuel n'est pas validé comme moteur de production. Aucun nouveau compte ni secret n'a été introduit dans cette instance pendant cet audit. Les fichiers de l'autre outil et son processus ont été préservés.

## Mesures complémentaires — 6 septembre 2026

`tools/probe-android-isolation.c` a été compilé avec le NDK puis exécuté hors PRoot, depuis ADB shell et `run-as app.foldgpt`. Chaque appel modifiant un état reste dans un processus enfant jetable. Dans les deux contextes :

```text
/proc/self/ns/user: ENOENT
/proc/self/ns/pid: ENOENT
unshare(CLONE_NEWUSER): EINVAL
unshare(CLONE_NEWNS): EPERM
unshare(CLONE_NEWPID): EPERM
landlock_create_ruleset(VERSION): 6
seccomp(GET_ACTION_AVAIL, USER_NOTIF): 0
```

Les processus lancés par `run-as` n'héritent pas nécessairement des filtres seccomp d'un processus créé par Zygote. Ce relevé prouve la présence de ces interfaces dans le noyau, pas leur utilisabilité complète depuis un futur service isolé Android.

Le PRoot épinglé supprime lui-même les flags de namespaces dans `src/syscall/enter.c`, indépendamment du preload. Retirer uniquement le shim ne suffit donc pas pour tester leur disponibilité.

Bubblewrap 0.12 lit les identifiants overflow avant d'analyser `--help`. Corriger cet ordre rendrait la détection du binaire possible, mais ne fournirait pas les namespaces nécessaires à l'exécution.

Le binaire officiel Codex 0.153.4 contient encore `features.use_legacy_landlock`, une option dépréciée. Les diagnostics hors compte, avec un répertoire de configuration séparé et sans requête modèle, ont refusé `:workspace` et une politique explicite lecture globale/écriture projet : `permission profiles requiring direct runtime enforcement are incompatible with --use-legacy-landlock`. Les protections de métadonnées du projet ne doivent pas être supprimées pour forcer cette voie. Aucune configuration du compte n'a été modifiée et aucun fichier témoin créé par Codex n'a été obtenu.

Le service de virtualisation Android annonce uniquement les VM protégées avec Gunyah, sans `/dev/kvm`, et seulement l'OS Microdroid. Le noyau Microdroid présent sur le téléphone désactive namespaces et seccomp. Cette image ne remplace donc pas un noyau Linux offrant les primitives requises. L'installation presque en un clic d'un noyau personnalisé accepté par l'hyperviseur n'est pas démontrée.

## Application réelle des restrictions — 6 septembre 2026

Les nouveaux programmes sont des expériences autonomes, absentes de la variante
release. Le receiver debug requiert la permission signature `android.permission.DUMP`
et ne lance que des programmes et arguments fixes. Chaque essai utilise son propre
répertoire temporaire ; aucun profil ChatGPT ni fichier personnel ne sert de cible.

Contrairement à `run-as`, les essais suivants sont partis du contexte de l'APK
créé par Zygote : UID 10412, filtre seccomp hérité actif, Landlock ABI 6.

| Programme | Résultat vérifié |
| --- | --- |
| `probe-landlock-enforcement.c` | Écriture autorisée réussie ; écriture hors périmètre, lien symbolique et écriture par enfant refusés ; création de socket refusée ; exécution native d'un shell réussie. Le parent vérifie les fichiers. |
| `probe-landlock-broker.c` | Quatre ouvertures accordées et neuf refus attendus. Les fichiers `.git/config` existants, y compris dans un sous-dossier, restent intacts ; `.codex` et `.agents` interdits ne sont pas créés ; les cibles extérieures restent intactes. |
| `probe-landlock-shell.c` | Un vrai `/system/bin/sh` exécute le script fixe après installation des restrictions. Création et ajout de texte autorisés réussissent. Les huit redirections interdites échouent ; la tentative supplémentaire de mksh d'ouvrir `/dev/tty` est également refusée. Contenus vérifiés indépendamment. |
| `probe-landlock-proot.c` | Un vrai `/bin/sh` Debian s'exécute sous PRoot avec une restriction de fichiers installée avant PRoot. Son écriture dans le workspace de test est refusée. Seul le répertoire temporaire privé de PRoot est inscriptible. Le preload hérité est remplacé par un fichier vide pour ce seul diagnostic. |

Le premier programme démontre aussi une limite de Landlock : une règle de lecture
sur `.git` ne retire pas une autorisation d'écriture héritée de son parent. Le
marqueur `metadata_protected=NO` est donc un résultat attendu, pas une protection
validée. Le broker évite cette autorisation récursive : son enfant reste en
lecture seule et reçoit uniquement les descripteurs validés par le parent.

Les brokers copient le chemin une seule fois, valident les composants, ouvrent
depuis un descripteur fixe avec `openat2` et les contraintes `RESOLVE_BENEATH`,
`RESOLVE_NO_SYMLINKS`, `RESOLVE_NO_XDEV`, puis transfèrent le descripteur avec
`SECCOMP_ADDFD_FLAG_SEND`. Ils n'utilisent pas `CONTINUE`. Le transfert initial du
listener emploie directement l'appel système `sendmsg` : le wrapper réseau Android
peut initialiser des bibliothèques en ouvrant des fichiers avant que le parent ait
reçu le listener.

Ces essais ne forment pas un moteur général. Ils ne couvrent pas les commandes
arbitraires, toutes les opérations POSIX, les changements de politique, la
confidentialité des lectures ou l'ensemble du processus Chromium. Une annulation
tardive peut encore laisser une création ou troncature autorisée dans le dossier
de test : la validation d'identifiant et le transfert atomique ne rendent pas
l'opération de fichier transactionnelle. Le parent utilise les droits ordinaires
de l'application. Aucun `externalSandbox` ni succès de sandbox n'est déclaré à
Codex sur la base de ces seuls résultats.

## Point de raccordement à Codex

Inspection du tag officiel `rust-v0.153.4`, commit
`042fb41b7c813ac7999105e886b2b7aa715b5081` : l'app-server lit
`CODEX_HOME/environments.toml`, qui peut déclarer un transport d'exécution stdio
ou WebSocket. Le contrat `ExecParams.sandbox` transporte la politique de fichiers.
Ce mécanisme permet d'étudier un moteur FoldGPT distinct sans modifier les
binaires officiels.

La sélection doit encore être vérifiée avec l'interface Desktop. La liste des
environnements par défaut comprend tous les environnements configurés, et pas
seulement celui nommé `default`. En outre, `command/exec`, `process/spawn`,
`thread/shellCommand` et les RPC `fs/*` restent locaux. Supprimer l'environnement
local rendrait ces fonctions indisponibles ; le conserver ne prouve pas que tous
les outils passent par notre futur moteur. Aucun fichier `environments.toml` du
compte n'a été changé. La preuve de commande protégée exécutée par Codex reste à
obtenir.

## Rendu graphique mesuré

`tools/inspect-gpu.py` interroge uniquement `SystemInfo.getInfo` sur le endpoint
local du client, sans lire de page ni de conversation. Le relevé actuel indique
ANGLE sur `llvmpipe (LLVM 19.1.7)` avec Mesa 25.0.7, composition et rasterisation
logicielles. L'initialisation EGL d'Xlorie côté Android ne contredit pas ce relevé :
elle concerne la présentation de la surface. L'accès à `/dev/kgsl-3d0` existe,
mais ni une faible charge CPU au repos ni le mode d'écran à 119,98 Hz ne prouvent
que le client utilise le GPU ou produit 120 images par seconde.
