# Inventaire réel du Fold, de son noyau et de One UI

Référence : [inventaire v2 en lecture seule](../../../downloads/runtime/capabilities-20260907-v2/inventory.json),
7 septembre 2026 à 00:52 Paris. Aucune installation, activation Shizuku,
modification de réglage ou reprise du diagnostic GNU pendant cette collecte.

## Matériel et logiciel observés

| Élément | Valeur lue | Interprétation |
| --- | --- | --- |
| Modèle / appareil | Samsung `SM-F971B` / `h8q` | Identifiants lus sur le téléphone ; aucune déduction depuis un émulateur générique |
| SoC / plateforme | QTI `SM8850` / `canoe` | La référence commerciale ne prouve pas les droits du système |
| ABI applicative | `arm64-v8a` | Exécutables AArch64 et ABI Android/Bionic à fournir |
| CPU | 8 entrées processeur ; implementer `0x51`, part `0x002` | [CPU brut](../../../downloads/runtime/capabilities-20260907-v2/cpuinfo.txt) et [analyse ARM64](04-arm64.md) |
| GPU | `Adreno840v2` | Valeur sysfs lue ; ne confère pas de fonctions de noyau |
| Android / API | `17` / `37` | Interfaces présentes soumises aux permissions et règles fournisseur |
| One UI | propriété `90000` : 9 | Version de ce relevé |
| Correctif déclaré | `2026-08-05` | Ne fournit pas la liste exacte des rétroportages Linux |
| Noyau | `6.12.58-android16-6-p6370076-abogkiF971BXXS2AZH7-4k` | Configuration extraite du noyau en cours, pas d'un noyau Pixel |
| Page mémoire | 4 096 octets | Mesurée via getconf et AT_PAGESZ |
| RAM visible du noyau | `MemTotal=11 351 456 KiB`, soit 10,83 GiB | RAM utilisable, pas totalité commerciale des puces |
| Mémoire disponible à cet instant | `MemAvailable=5 174 960 KiB`, soit 4,94 GiB | Estimation dynamique après mémoire récupérable ; pas une allocation FoldGPT |
| Swap | `12 582 908 KiB` | Ne s'ajoute pas à la RAM physique |
| Intégrité déclarée | warranty bit `0`, boot `green`, flash locked `1`, SELinux `Enforcing` | Indicateurs lus ; pas une garantie générale de sécurité ou de garantie constructeur |
| Uptime | `3544.27` secondes | Compatible avec le deuxième redémarrage déjà enregistré ; pas de nouveau reboot avant ce relevé |

L'[audit mémoire](../foldgpt-memory-2026-09-06.md) n'avait pas trouvé de plafond
global FoldGPT de 2 GiB. Les limites d'espace d'adressage natif ne sont pas une
réservation de RAM, et One UI/Android continuent à consommer de la mémoire.

## Catalogue du noyau

Le [fichier complet de configuration](../../../downloads/runtime/capabilities-20260907-v2/kernel.config)
provient de `/proc/config.gz` : **6 501 paramètres décodés**, y compris options
désactivées. Il est aussi indexé dans `inventory.json`. Cela recense la
configuration exposée par le noyau, pas chaque fonction C ni chaque correctif
Samsung.

| Option | Valeur | Ce que l'on peut conclure |
| --- | --- | --- |
| `CONFIG_USER_NS`, `CONFIG_PID_NS` | `n`, `n` | Ces implémentations sont absentes |
| `CONFIG_NAMESPACES`, `CONFIG_UTS_NS`, `CONFIG_NET_NS`, `CONFIG_TIME_NS` | `y` | Support compilé ; aucune permission générale de création accordée |
| `CONFIG_SYSVIPC` | `n` | IPC System V absent ; ne pas confondre avec Binder, pipes ou sockets |
| `CONFIG_SECCOMP`, `CONFIG_SECCOMP_FILTER` | `y` | Filtrage compilé ; état réel par processus ci-dessous |
| `CONFIG_SECURITY_LANDLOCK`, `CONFIG_SECURITY_SELINUX` | `y` | Support compilé ; Landlock ABI 6 testé antérieurement, SELinux Enforcing relu |
| `CONFIG_CGROUPS` / `CONFIG_CGROUP_PIDS` | `y` / `n` | Pas de contrôleur pids à supposer disponible |
| `CONFIG_MEMFD_CREATE` | `y` | Support memfd ; droits et exécution restent distincts |
| `CONFIG_BPF`, `CONFIG_BPF_SYSCALL`, `CONFIG_BPF_JIT` | `y` | Pas une autorisation de charger des programmes arbitraires |
| `CONFIG_MODULES`, `CONFIG_MODULE_SIG` | `y` | Pas de droit applicatif de charger un module ; namespaces non modulaires |
| `CONFIG_KVM` | `y` | Ne prouve ni l'accès `/dev/kvm` ni AVF/pKVM utilisable par FoldGPT ; VM exclue |
| `CONFIG_ARM64_SVE`, `CONFIG_ARM64_SME`, `CONFIG_ARM64_MTE` | `y` | Configuration noyau ; voir HWCAP pour les extensions annoncées à l'application |

La lecture de `/sys/kernel/security/lsm` et de
`/proc/sys/kernel/unprivileged_bpf_disabled` a été refusée avec code 1 et
`Permission denied`. Le contenu de ces fichiers reste **inconnu** ; aucun zéro
ou état activé/désactivé n'est inventé.

## Droits réellement observés

| Contexte | UID / SELinux | Seccomp | Capabilities effectives |
| --- | --- | --- | --- |
| Commande ADB shell | `2000`, `u:r:shell:s0` | Mode 0, aucun filtre | `0` |
| FoldGPT principal, PID 16917 | `10412`, `untrusted_app`, catégories applicatives | Mode 2, un filtre | `0` |
| Service runtime FoldGPT, PID 17419 | `10412`, même domaine applicatif | Mode 2, un filtre | `0` |
| `run-as app.foldgpt` | `10412`, domaine **runas_app** | Mode 0 | Ne pas assimiler aux processus Zygote |
| Shizuku UserService | Aucun processus réel identifié dans ce relevé | **Inconnu** | **Inconnu** |

Les deux vrais processus FoldGPT ont le parent Zygote PID 1903. Lire leurs
fichiers `/proc` depuis ADB ne change pas leur contexte. À l'inverse, exécuter
une sonde via `run-as` ne prouverait pas son fonctionnement dans l'application.

Le bounding set du shell vaut `0x8000c0`, tandis que ses capacités permises,
effectives, héritables et ambiantes valent zéro. Ce plafond n'est pas une
attribution de privilèges ; ni `CAP_SYS_ADMIN` ni `CAP_SYS_MODULE` n'y figurent.
L'absence de filtre seccomp n'enlève pas les contrôles UID/SELinux du shell.

`pm path moe.shizuku.privileged.api` retourne un code 1 sans chemin ; la liste
des paquets contenant `shizuku` et le relevé des processus ne retrouvent pas le
paquet standard/serveur. Cela décrit ce snapshot, pas tous les profils ou forks
possibles. Aucun service Shizuku n'a été installé ou lancé pour le vérifier.

### Complément : UserService Shizuku réellement mesuré

Après cet inventaire, l'essai autorisé du 7 septembre a installé Shizuku
officiel `13.6.0.r1086.2650830c` et une application de qualification séparée.
Le [rapport réel](../../../downloads/shizuku-lab/attempt-20260907/context-report.json)
relève le UserService PID 32106 : UID/GID 2000, SELinux `u:r:shell:s0`,
`Seccomp: 0` et aucun filtre, y compris sur le thread Binder. Ses capabilities
effectives, permises, héritables et ambiantes sont nulles ; l'appelant autorisé
est l'application de test UID 10350. Ce service a ensuite quitté après
détachement. Le constat « inconnu » du tableau précédent reste celui du
snapshot initial, et ne décrit plus l'état de cette qualification.

Ce contexte donne une voie de lancement distincte de Zygote ; il n'ajoute
aucun namespace au noyau. Voir le [suivi Shizuku](05-shizuku.md) pour les
résultats d'exécution et les conditions de démarrage.

## Fonctions déclarées par Android et One UI

- [Catalogue Package Manager](../../../downloads/runtime/capabilities-20260907-v2/declared-features.txt) :
  **228 entrées**, matériel, fonctions Android et extensions constructeur.
- [Catalogue Binder](../../../downloads/runtime/capabilities-20260907-v2/binder-services.txt) :
  **521 services**, dont services Samsung et Android ; nom et interface lorsque
  le système les expose.
- [Catalogue CPU brut](../../../downloads/runtime/capabilities-20260907-v2/cpuinfo.txt) et
  [HWCAP dans le JSON](../../../downloads/runtime/capabilities-20260907-v2/inventory.json) :
  `AT_HWCAP=0xffffffff`, `AT_HWCAP2=0x40003cbb73ef`.

Ces catalogues évitent d'oublier une famille d'API, mais ne disent pas que
FoldGPT peut appeler chaque méthode d'un service. Il faut identifier une
méthode précise, son contrat, ses permissions et sa politique fournisseur.
L'existence d'un service Knox ne donne pas une API de namespaces.

Les sources du build Samsung exact restent à acquérir : le portail officiel
OSRC affichait une maintenance lors de la recherche. Les sources AOSP et
Linux amont permettent d'expliquer les contrats, mais pas de certifier la liste
des correctifs Samsung ni une reproduction fidèle dans l'émulateur Android.
Voir [sources et points non établis](../kernel-extension-options-2026-09-07.md).
