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
