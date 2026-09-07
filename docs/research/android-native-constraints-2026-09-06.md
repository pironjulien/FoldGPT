# Contraintes Android natives — recherche du 6 septembre 2026

Recherche ciblée dans les documentations primaires, ouvertes dans le navigateur
intégré Codex le 6 septembre 2026, complétée par des lectures ADB bornées. Ce
relevé ne prétend pas couvrir toute la documentation existante. Aucun réglage,
processus, APK, fichier du client ou état du téléphone n'a été modifié pour cette
recherche.

## Décision pratique

Le binaire Bubblewrap ne peut pas créer les namespaces user/pid sur ce noyau :
ils sont absents de sa configuration de compilation. Réparer `bwrap --help`
pourrait corriger sa détection, mais ne fournirait pas ses mécanismes d'isolation.
La voie praticable dans le périmètre est un exécuteur natif ARM64 séparé, avec
restrictions effectivement appliquées par Android, Landlock et seccomp, raccordé
par un contrat d'environnement que le client officiel accepte. Le raccordement
et les commandes GNU générales restent à vérifier ; les probes existantes ne
prouvent pas ce résultat final.

Ni root, ni déverrouillage/flash de bootloader, ni changement de noyau/SELinux,
ni VM ne sont requis ou retenus. Un MCP/skill ne donne aucune primitive noyau
supplémentaire ; ce n'est pas la réponse à l'absence de namespaces.

## Téléphone réellement connecté

Lectures `getprop`, `uname`, `getenforce`, sysfs et `/proc/config.gz`, hors PRoot :

| Élément | Valeur observée |
| --- | --- |
| Modèle / appareil | `SM-F971B` / `h8q` |
| SoC / plateforme | `QTI SM8850` / `canoe`, matériel `qcom` |
| ABI | `arm64-v8a`, noyau `aarch64` |
| Android / SDK / One UI | `17` / `37` / `90000` |
| Correctif sécurité | `2026-08-05` |
| Noyau | `6.12.58-android16-6-p6370076-abogkiF971BXXS2AZH7-4k` |
| GPU sysfs | `Adreno840v2` |
| CPU possibles / pages | `0-7` / `4096` octets |
| Intégrité observée | `warranty_bit=0`, `verifiedbootstate=green`, `flash.locked=1`, SELinux `Enforcing` |

Configuration actuelle lue directement :

```text
CONFIG_NAMESPACES=y
CONFIG_UTS_NS=y
# CONFIG_USER_NS is not set
# CONFIG_PID_NS is not set
CONFIG_NET_NS=y
CONFIG_ARM64_4K_PAGES=y
CONFIG_KVM=y
CONFIG_SECCOMP=y
CONFIG_SECCOMP_FILTER=y
CONFIG_ANDROID_BINDER_IPC=y
CONFIG_SECURITY_LANDLOCK=y
CONFIG_LSM="landlock,lockdown,yama,loadpin,safesetid,selinux,smack,tomoyo,apparmor,ipe,bpf"
```

`CONFIG_KVM=y` ne prouve aucun droit d'accès d'une application à KVM ; aucune
expérimentation de virtualisation n'appartient à cette recherche. Le suffixe
`android16` du noyau ne remplace pas la version Android 17 réellement annoncée
par le système. De même, 4096 est la taille de page de cet appareil ; conserver
les ELF compatibles 16 KiB reste pertinent pour la distribution Android.

La fiche Samsung SM-F971B confirme Galaxy Z Fold8, Snapdragon 8 Elite Gen 5 for
Galaxy, One UI 9 et son manuel Android 17. Qualcomm documente un CPU Oryon
64 bits et un GPU Adreno avec Vulkan 1.3/OpenGL ES 3.2. Les chiffres de débit
marketing ne constituent pas des mesures de FoldGPT ; le GPU exact ci-dessus
vient du téléphone.

## Mécanismes utilisables et limites à traiter

| Sujet | Contrat documenté et conséquence pour FoldGPT |
| --- | --- |
| Android | UID, SELinux et filtre seccomp hérité protègent également le code natif. Un sous-processus d'application ne gagne pas des droits parce qu'il est ARM64 ou C. |
| Bubblewrap | L'amont utilise les user namespaces pour l'utilisateur non privilégié et crée toujours un mount namespace. Le mode setuid historique a été retiré. Il ne remplace pas les namespaces absents. |
| Landlock ABI 6 déjà testé par le projet | Peut retirer des droits sans privilège ; restrictions héritées par les enfants, impossibles à desserrer ensuite. Les règles s'ajoutent aux contrôles Android existants. |
| Thread de lancement | ABI 6 n'a pas TSYNC, ajouté en ABI 8. Installer les restrictions dans le processus/thread de lancement avant les descendants ; une règle posée sur un thread Java ne confine pas automatiquement ses threads frères. |
| Métadonnées | Une règle Landlock autorisant l'écriture sur le parent permet aussi l'écriture dans les descendants. Une règle `.git` en lecture seule ne retire pas cet accès. Conserver le résolveur complet et le broker d'acquisition. |
| Opérations POSIX | Landlock ne couvre toujours pas toutes les familles `chmod`, `chown`, `setxattr`, `utime`, `flock`, `fcntl`, `stat`. Les refus/médiations doivent conserver la politique sans supprimer les opérations nécessaires aux vrais outils. |
| FDs | Les FDs acquis avant confinement ou transmis conservent leurs droits. Fermer le surplus hérité ; distinguer sortie de commande, contrôle et FDs de données. |
| Réseau | ABI 6 filtre TCP par port, pas UDP (ABI 10) ni les UNIX pathname (ABI 9). Les scopes signal/UNIX abstrait existent dès ABI 6 mais n'offrent pas d'exceptions vers le parent. Préparer les canaux privés avant confinement et contrôler les autres sockets par seccomp/broker. |
| USER_NOTIF | Copier les pointeurs une fois avant décision ; réaliser l'opération sur la copie et des FDs ancrés, puis `ADDFD_FLAG_SEND`. Ne pas utiliser `CONTINUE` pour valider un chemin mutable. L'injection atomique de FD ne rend pas création/troncature transactionnelle lors d'une annulation. |
| PRoot strict | Compatibilité GNU par traduction ptrace sur le même noyau, pas VM et pas émulation CPU pour ARM64 compatible. Confiner le traceur et les enfants par le noyau avant PRoot. Le mode strict local doit garder les vrais refus de sécurité ; ni le PRoot historique ni le shim ne prouvent une sandbox. |
| Bionic / GNU | Le NDK fournit les API Android natives. Le runner actuel admet des ELF statiques bornés ; cela ne prouve pas le support du chargeur glibc, bibliothèques, shell, Git, Python, Node ou compilateurs. Prévoir un ensemble de runtime autorisé, avec les vrais exécutables et dépendances, et le tester sur appareil. |
| Exécution depuis les données | Depuis target API 29, `execve()` direct d'un fichier dans le home inscriptible est refusé. Android recommande du code binaire embarqué dans l'APK. Les exécutables du superviseur doivent provenir du paquet installé ; une production compilée localement réclame une voie de chargement explicitement qualifiée. Abaisser la cible API ne résout pas le contrat produit. |
| TTY | Accorder globalement `ioctl` serait excessif. Créer un PTY privé, conserver uniquement les opérations termios/winsize nécessaires et refuser injection `TIOCSTI`/`TIOCLINUX` ; vérifier le comportement réel du shell et des descendants. Le transport actuellement documenté refuse les TTY. |
| Processus / ressources | Réutiliser pidfd, subreaper, événements exec et preuves de reap déjà développés. Le quota NPROC est par UID, partagé avec l'interface. Une limite d'espace virtuel adaptée à Scudo n'est pas une limite de mémoire résidente. |

Un service `isolatedProcess=true` fournit officiellement un processus isolé sans
permissions propres, avec communication par API Service. C'est une option de
séparation future, pas une preuve d'exécution GNU : il faut qualifier les droits
SELinux sur les FDs reçus, le chargement ELF, ptrace et la médiation depuis son
contexte réel. Une simple propriété de manifeste ne termine pas le broker.
Le chemin déjà testé dans l'application doit rester la base de l'incrément
nécessaire à la commande réelle.

## Android 17, One UI et préservation de Knox

Android 17 introduit des limites mémoire dépendant de la RAM de l'appareil.
`ApplicationExitInfo` indique `REASON_OTHER` avec `MemoryLimiter:AnonSwap` lors
d'une fermeture imputable à cette limite. Il faut observer cette cause et borner
la consommation des builds ; désactiver le limiteur ne serait pas une résolution.
Le loopback entre profils Android est désormais bloqué par défaut, alors que le
loopback au sein du même profil reste inchangé. Un work profile ajouterait donc
un problème de transport sans fournir les namespaces manquants.

La même documentation décrit la visibilité IME à restaurer explicitement après
un changement de configuration non géré. Cela explique pourquoi le pliage,
la rotation et le retour clavier ont encore besoin d'une validation fonctionnelle.

Samsung documente Auto Blocker (One UI 6 et plus) comme une protection des sources
d'installation et commandes/mises à jour par USB. Cela ne fournit pas de user
namespace et ne doit pas être désactivé pour essayer de corriger Bubblewrap.
L'état précis d'Auto Blocker n'a pas été lu ni changé pendant cette recherche.

Le livre blanc Knox décrit un e-fuse permanent lorsqu'une configuration système
non approuvée est détectée, notamment noyau non signé ou SELinux désactivé. Les
lectures d'intégrité ci-dessus sont conformes à l'état attendu aujourd'hui ; elles
ne constituent pas un engagement contractuel Samsung Care+ ni une preuve d'audit
exhaustif. Les ajouts FoldGPT doivent rester dans son espace applicatif et ses
paquets signés, sans toucher ces composants ni les fichiers du client officiel.

## Sources primaires ouvertes le 6 septembre 2026

1. [Samsung : fiche Galaxy Z Fold8 SM-F971B](https://www.samsung.com/ae/business/smartphones/galaxy-z/galaxy-z-fold8-graphite-256gb-sm-f971bzkimea/) — appareil, SoC, One UI 9, manuel Android 17.
2. [Qualcomm : Snapdragon 8 Elite Gen 5](https://www.qualcomm.com/smartphones/products/8-series/snapdragon-8-elite-gen-5) — Oryon 64 bits, Adreno et API GPU ; les variantes exactes dépendent de l'OEM.
3. [AOSP : Application Sandbox](https://source.android.com/docs/security/app-sandbox) — UID, SELinux et seccomp pour Java comme pour le natif ; page mise à jour le 18 juin 2026.
4. [Android : changement `execve` target 29](https://developer.android.com/about/versions/10/behavior-changes-10#execute-permission) — page mise à jour le 15 juillet 2026.
5. [Android : API natives NDK](https://developer.android.com/ndk/guides/stable_apis) — page mise à jour le 6 mars 2026.
6. [Android 17 : changements pour toutes les applications](https://developer.android.com/about/versions/17/behavior-changes-all) — mémoire, loopback, IME ; page mise à jour le 4 août 2026.
7. [Android : élément service et isolatedProcess](https://developer.android.com/guide/topics/manifest/service-element#isolated) — page mise à jour le 3 juillet 2026.
8. [Linux : Landlock userspace API](https://docs.kernel.org/userspace-api/landlock.html) — document daté août 2026, spécification actuelle distinguant explicitement les versions ABI ; ne pas attribuer ses ABI récentes au téléphone ABI 6.
9. [Linux : seccomp BPF et Userspace Notification](https://docs.kernel.org/userspace-api/seccomp_filter.html) — précédence des filtres, héritage, mémoire de notification, ADDFD.
10. [Bubblewrap : dépôt amont et README](https://github.com/containers/bubblewrap) — namespaces requis, périmètre et limites TTY.
11. [PRoot : documentation amont](https://proot-me.github.io/) — traduction sur noyau hôte, QEMU uniquement pour CPU incompatible ; les déclarations historiques de confinement ne remplacent pas l'audit de sécurité local.
12. [Samsung Knox : Hardware-Backed Security](https://docs.samsungknox.com/admin/fundamentals/whitepaper/samsung-knox-mobile-security/system-security/hw-backed-security/) — Warranty Bit et composants système ; mise à jour le 7 mars 2025.
13. [Samsung Knox : Samsung Auto Blocker](https://docs.samsungknox.com/admin/fundamentals/whitepaper/samsung-knox-mobile-security/system-security/samsung-auto-blocker/) — restrictions One UI d'installation/USB ; mise à jour le 7 mars 2025.

Sources locales relues : `NATIVE-AUDIT.md`,
`tools/install/native/proot-strict-sandbox.md`,
`tools/executor/native-managed-contract.md`,
`tools/executor/native-runner-android-test.md`,
`tools/executor/native-executor-transport.md`.
