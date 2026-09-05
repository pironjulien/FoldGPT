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
