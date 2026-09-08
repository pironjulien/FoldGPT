# Sauvegarde v13 : moteur R5, APK r20 et échec réel de conversation

Le [complément privé v13](https://github.com/pironjulien/FoldGPT-workspace/releases/tag/recovery-2026-09-07)
conserve les sources au commit `7a1d6cdfeb15a3e4defceca519f02f0d17060851`,
les APK r18/r19/r20 et leurs paquets figés, le moteur ARM R5 et le Bash
reconstruit au préfixe réel de production, chacun lié à son commit de compilation.

Il a été retéléchargé, authentifié, déchiffré et restauré sous le projet :
**13 157 fichiers vérifiés**, soit 778 475 744 octets. Les **1 169 fichiers**
du tar source exact ont aussi été extraits et contrôlés. Les trois APK restaurés,
les deux binaires ARM et les sources/recettes/deux ELF de Bash ont repassé leurs
contrôles d'intégrité et d'inventaire.

Le checkpoint conserve les réussites natives Python et le démarrage normal
de l'interface avec R5, puis l'échec réel de la première conversation du petit
projet Python : commandes refusées, écriture refusée, zéro fichier constaté.
**Ce checkpoint ne constitue pas une livraison fonctionnelle.** Le réseau des
commandes, plusieurs opérations de fichiers et le TTY restent aussi à traiter.
Les sources GPU/PTY non qualifiées sont conservées séparément pour la reprise.

| Fichier | Octets | SHA-256 |
| --- | ---: | --- |
| `native-checkpoint-v13.tar.gz.age.part001` | 450 529 801 | `bcbb1f93c3d2e774179a15700b5b1c6e78abcfc3869b56954690411d24e1a54c` |
| APK r20 | 78 813 128 | `dd1a6beff3ea42f3a66f88f4fc254a169b1a12bcdc737834ca95b6e0372d112a` |

Conserver l'archive principale et les compléments1à12. Les treize manifestes
et les métadonnées des anciennes parties ont été revérifiés ; les archives
antérieures n'ont pas toutes été retéléchargées une nouvelle fois.

Rapports : [publication](verification/github-supplement-v13-publication.json),
[restauration](verification/github-supplement-v13-restoration.json),
[APK r20](verification/github-supplement-v13-r20-apk.json) et
[manifeste](verification/supplement-v13-manifest.json).

Pour restaurer, utiliser `tools/recovery/restore-archive.py` avec
`native-checkpoint-v13-manifest.json`, l'identité existante dans NexusSecure
et une destination neuve sous `C:\Dev\ChatgptFold`. Les clés ne sont pas incluses
dans l'archive. Seuls la partie chiffrée et son manifeste ont été téléversés.
La branche Git conserve les évolutions postérieures au checkpoint.
