# Noyau Samsung : extensions possibles dans le périmètre autorisé

Recherche du 7 septembre 2026. Statut : analyse documentaire, aucune commande,
installation, modification ni reproduction sur le téléphone. La recherche
n'autorise ni root, ni exploit, ni déverrouillage/flash, ni changement de SELinux,
ni VM. Elle ne modifie pas le client ChatGPT officiel.

## Conclusion circonscrite

On ne peut pas fournir les vrais `CONFIG_USER_NS` et `CONFIG_PID_NS` manquants au
noyau actuellement démarré par un APK ordinaire, un réglage, un programme eBPF ou
un module de pilote GKI/DLKM. Dans Linux 6.12.58, ces deux options sont des
`bool`, et non des `tristate` permettant la valeur module `m`. Leur absence
sélectionne des implémentations intégrées qui refusent les opérations
correspondantes. Cela ferme la voie « installer Bubblewrap et lui apporter les
namespaces à côté », sans fermer toute exécution native isolée.

Android fournit une autre base : un service applicatif isolé, des identités UID,
SELinux, des échanges Binder et de descripteurs déjà ouverts, complétés par les
restrictions Landlock/seccomp effectivement disponibles. Cette base peut
réaliser des objectifs précis d'isolation. Elle n'est pas équivalente à tous les
contrats Linux d'un user namespace ou d'un PID namespace, et sa composition
avec GNU/PRoot reste non validée sur ce téléphone. Les redémarrages interdisent
de présenter cette piste comme déjà stable.

## Appareil et niveau de preuve

Les observations conservées dans
`docs/research/android-native-constraints-2026-09-06.md` identifient le
`SM-F971B`, build `F971BXXS2AZH7`, noyau
`6.12.58-android16-6-p6370076-abogkiF971BXXS2AZH7-4k`, Android 17 / SDK 37 /
One UI 9. Elles donnent `CONFIG_NAMESPACES=y`, `CONFIG_USER_NS` et `CONFIG_PID_NS`
non définis, ainsi que Landlock et seccomp présents. Il s'agit des lectures du
6 septembre, pas d'une nouvelle interrogation du téléphone.

La version publique Linux 6.12.58 sert de référence de code. Elle ne constitue
pas le code fournisseur exact. Le checkout local `downloads/isolation-kernel`
est une version AOSP plus récente ; il ne doit pas être présenté comme une
reconstruction du noyau Samsung. De même, la politique SELinux AOSP consultée
ci-dessous décrit une interface et ses limites amont, pas un dump de la
politique Samsung active.

## Matrice des voies

| Voie | Statut dans le périmètre | Ce qu'elle apporte ou ce qui la ferme |
| --- | --- | --- |
| Réglage Android/One UI, `sysctl`, option du terminal | Impossible pour ajouter ces deux namespaces | Les options `bool` sélectionnent du code à la compilation. Le code sans `USER_NS` retourne `-EINVAL` pour créer un user namespace ; sans `PID_NS`, `CLONE_NEWPID` retourne `-EINVAL`. Un réglage ne restaure pas ces implémentations. [L1–L4] |
| Module GKI/DLKM installé par notre APK | Impossible comme solution aux namespaces dans le périmètre | `USER_NS`/`PID_NS` ne sont pas des modules chargeables. Le chargement de modules Linux exige `CAP_SYS_MODULE`; la politique AOSP refuse les capabilities aux applications ordinaires et restreint l'origine des modules aux partitions système/fournisseur prévues. Une KMI compatible ne confère pas ces droits. Les modules GKI sont signés ; AOSP permet certains modules fournisseur non signés avec symboles autorisés depuis des partitions validées. Ne pas prétendre que tous les modules exigent une signature individuelle. [L1–L5, A1–A2, D2] |
| Module officiellement fourni et chargé par Samsung | Possible comme mécanisme fournisseur ; non établi pour notre besoin | Un constructeur peut distribuer des composants acceptés par sa chaîne de démarrage. Cela ne rend pas un module de namespace disponible, et aucun module Samsung officiellement exposé à une application pour ce besoin n'a été identifié. Aucun chargement ni demande externe n'a été effectué. |
| Noyau reconstruit avec ces options, correctif binaire, module qui modifie les fonctions du noyau | Hors périmètre | Il faudrait modifier le système privilégié et sa chaîne d'approbation. Ce n'est pas une extension applicative ordinaire ; aucune recherche d'exploit ni procédure de contournement n'est retenue. |
| Mise à jour officielle Samsung | Possible en principe ; contenu et disponibilité non établis | Samsung pourrait modifier configuration et rétroportages par sa mise à jour officielle. Nous ne contrôlons ni son contenu ni son calendrier. Aucun firmware n'est proposé ou installé et aucune mise à jour ne doit être présumée corriger ces points. |
| eBPF chargé par l'application | Impossible comme apport des namespaces absents | Linux limite les types de programmes et leurs droits ; le code AOSP réserve `prog_load` au chargeur système. Les helpers et points d'attache BPF existants ne recompilent pas les branches `CONFIG_USER_NS/PID_NS` absentes. Des programmes réseau autorisés, lorsqu'ils existent, ne sont pas une implémentation des namespaces. [L6–L7, A3] |
| Jeton BPF délégué | Pas de voie ordinaire établie ; ne répond pas au besoin | Dans Linux 6.12.58, la création du jeton suppose un montage bpffs configuré par une autorité et les capacités dans son user namespace ; elle est refusée dans le user namespace initial. L'absence de `USER_NS` ne devient donc pas contournable grâce à ce mécanisme. Même un jeton ne fournit pas une implémentation des namespaces. [L7] |
| API Android de service isolé (`isolatedProcess=true`) | Possible officiellement ; GNU complet à qualifier | Android crée une identité et un processus isolés. AOSP permet l'accès aux FDs de données déjà ouverts transmis par IPC et `self:process ptrace`, tout en interdisant l'ouverture directe des données applicatives et les sockets réseau ordinaires. C'est une piste concrète pour un exécuteur natif avec broker, pas une preuve du fonctionnement de PRoot dans le contexte Samsung exact. [A4–A5] |
| Service Android privilégié préinstallé, Device Owner, Knox SDK | Non établi pour ce besoin ; pas de délégation générale de noyau | Une API du système peut exécuter l'opération documentée qu'elle expose. Ni son existence ni un rôle d'administration ne donnent implicitement `CAP_SYS_MODULE` ou une API d'ajout de namespaces. Aucun service officiel accordant cette opération à FoldGPT n'a été identifié. L'API précise et son autorisation seraient nécessaires avant de retenir cette voie. [A1–A2] |
| pKVM / Android Virtualization Framework | Écarté par la contrainte sans VM | Cela exécute un noyau invité et ne transforme pas la configuration du noyau hôte. Même si un invité offrait les namespaces requis, il modifierait l'objectif. Aucun essai de virtualisation n'est retenu. |
| Landlock + seccomp + UID/SELinux + broker | Primitives disponibles ; composition et stabilité non établies | Ces mécanismes peuvent retirer des droits, médiatiser fichiers/réseau et séparer les processus. Ils ne créent pas une vue PID indépendante ou une nouvelle autorité utilisateur Linux. Le contrat doit exprimer chaque garantie réellement apportée, avec validations natives hors téléphone avant toute reprise. [A4–A5, D1] |

`Impossible` décrit le mécanisme indiqué avec les contraintes actuelles. Il ne
conclut pas que le produit entier est impossible. `Non établi` ne signifie ni
fonctionnel ni absent : la preuve correspondante manque.

## Sources Samsung exactes et rétroportages

L'entrée officielle vérifiée par la tâche principale dans le navigateur intégré
le 7 septembre 2026 est le
[Samsung Open Source Release Center](https://opensource.samsung.com/), pour
`SM-F971B` et `F971BXXS2AZH7`. Le site affiche une page de maintenance :
« Sorry! We're doing some work on site », avec actualisation/retour à l'accueil.
Aucun paquet source correspondant à ce build n'a été acquis ou identifié de
manière vérifiable. **Il ne faut pas écrire que Samsung ne publie pas ces
sources.** Aucune route alternative officielle vérifiée n'a été trouvée dans
les sources déjà disponibles.

Les fichiers Linux ont été lus via le connecteur de code GitHub ; les sources
AOSP locales ont été relues à leur révision indiquée. Les pages GKI et Knox ont
été relues par la tâche principale dans le navigateur intégré le 7 septembre,
puis leurs observations ont été transmises à cette recherche. Aucun navigateur
externe n'a été utilisé pour naviguer et aucun formulaire de demande de sources
n'a été envoyé. La maintenance du portail bloque actuellement la recherche du
paquet Samsung exact.

La chaîne de version Samsung n'établit pas quels correctifs amont ont été
rétroportés. Le niveau de patch Android `2026-08-05` ne le prouve pas davantage.
Les deux points suivants restent **non établis sur le noyau fournisseur** :

| Point à comparer | Source amont et signature sémantique à rechercher | Portée |
| --- | --- | --- |
| Synchronisation ARM64 `orig_x0` après ptrace | [88b839ce497c](https://github.com/torvalds/linux/commit/88b839ce497ccb1ff92f7ae742c78dd2937ba572), `arch/arm64/kernel/ptrace.c` : synchroniser l'argument sauvegardé lors des mises à jour des registres et du numéro de syscall, en distinguant l'entrée et la sortie. La présence du premier correctif incomplet `e057b9477232` seule ne suffit pas. | Important pour la cohérence entre les arguments modifiés par PRoot et ceux vus par seccomp/audit. Ce n'est pas une cause de redémarrage démontrée. |
| Landlock `LANDLOCK_SCOPE_SIGNAL` et SIGIO | [4b80320ca7ed](https://github.com/torvalds/linux/commit/4b80320ca7ed03d6e683f95b6066565dc97b9f92), `security/landlock/fs.c`, `fs.h`, `task.c` : conserver le domaine pour les propriétaires de groupe et vérifier chaque destinataire en préservant l'exception intra-processus. | Important pour l'évaluation de l'isolation des signaux si le correctif manque. Aucun lien causal avec les redémarrages n'est établi. |

La comparaison doit porter sur la logique, pas seulement sur un nom de fonction
ou un hash de commit : un rétroportage fournisseur peut avoir un hash différent.
Un paquet « même modèle » ou « même majeure 6.12 » ne suffit pas à conclure.

## Ce que permet précisément un service isolé natif

La règle `allow isolated_app_all self:process ptrace` n'utilise pas `self` au
sens « uniquement ce PID ». En langage de politique SELinux, elle autorise
des accès entre tâches du même type source/cible après expansion. Les autres
contrôles restent applicables : identité Linux/dumpable et politique ptrace,
catégories MLS, seccomp hérité, puis Landlock éventuellement ajouté. Le fichier
AOSP `private/mls` exige notamment l'égalité des niveaux pour `ptrace`. Un
enfant issu de `fork` conserve normalement UID et contexte de son parent ;
cela rend le traçage parent/enfant concevable dans un même service isolé. Cela
n'autorise pas le traçage de toutes les applications isolées, ni d'un broker
portant une autre identité. [A4, A6]

Les sources AOSP donnent trois éléments concrets supplémentaires :

- `private/domain.te` autorise `self:process fork`. `app.te` autorise lecture,
  mapping et exécution des fichiers de type `apk_data_file`, donc des binaires
  réellement installés avec l'APK, tandis que son interdiction d'exécuter des
  fichiers de données s'applique explicitement à `isolated_app_all`. Passer un
  FD ne change pas son type SELinux : un FD de code dans `app_data_file` ne
  devient pas un exécutable autorisé. Le chargeur et toutes les bibliothèques
  natives requises doivent avoir une provenance et un étiquetage admis. [A1–A2]
- Les listes seccomp Bionic `android16-release` admettent `clone`, `execveat`,
  `seccomp` et les appels Landlock ; `SYSCALLS.TXT` inclut `execve` et `ptrace`.
  `clone` assure les créations ARM64 utilisées par Bionic ; une mention de
  `vfork` réservée aux autres architectures n'interdit pas les sous-processus
  ARM64. Cela documente l'amont ; la politique exacte héritée sur Samsung reste
  à qualifier. [A7]
- `binder_call(appdomain, appdomain)` inclut les permissions de transfert et
  `fd use`. Le service peut recevoir des FDs par son API Binder, avec
  `ParcelFileDescriptor`, puis transmettre uniquement les FDs nécessaires à son
  exécuteur natif. Le broker ouvre/valide les fichiers dans son propre contexte ;
  le service isolé dispose de droits explicites de lecture/écriture/mapping sur
  les fichiers de données reçus, sans droit d'ouverture directe. Les sockets
  UNIX déjà connectées et transmises disposent aussi d'une voie documentée.
  L'identité Binder et chaque requête doivent rester vérifiées. [A1, A4, A8]

Une architecture candidate garde le service Java/Binder comme contrôleur,
lance un petit exécutable Bionic installé dans l'APK, et confie à ce processus
la création et la surveillance de ses descendants. Il faut éviter de poursuivre
un runtime Java/Binder multithreadé arbitrairement après `fork` : une voie
`ProcessBuilder`/lanceur natif avec transition immédiate vers l'exécutable,
fermeture des FDs superflus et protocole dédié est à spécifier. Cette proposition
ne nécessite ni noyau invité ni modification de ChatGPT.

Limites restant réelles : le glibc/runtime GNU stocké dans des données privées
ne gagne pas des droits d'exécution par transfert de FD ; un exécutable nouvellement
compilé demande une stratégie conforme au modèle d'exécution Android ; une
commande GNU arbitraire ne parle pas Binder et requiert donc une adaptation
explicite pour utiliser le broker. Réintroduire PRoot/seccomp/Landlock dans le
service isolé ne prouve pas que la cause des deux redémarrages disparaît. Aucune
de ces opérations n'a été exécutée sur le téléphone pendant cette recherche.

## Plan sûr et critères de reprise

1. Conserver l'arrêt de la fixture suspecte et les preuves de l'incident. Les
   fichiers projet entièrement NUL ne permettent pas de localiser le
   redémarrage au premier sous-processus. Aucun correctif causal n'est encore
   identifié ; voir `docs/research/gnu-managed-reboot-2026-09-06.md`.
2. Depuis le navigateur intégré, rechercher le modèle/build exact au portail
   Samsung. En cas de paquet exact disponible, relever nom, build, taille et
   empreinte, puis inspecter les sources sur le PC sans compiler pour le
   téléphone ni installer quoi que ce soit. Si le portail impose une demande,
   préparer la demande exacte ; son envoi à Samsung est une action distincte.
3. Comparer hors téléphone la configuration, les branches ARM64 ptrace/seccomp
   et Landlock concernées. Conserver `inconnu` tant que la correspondance source
   et build ou un équivalent sémantique ne sont pas prouvés.
4. Définir le contrat de l'exécuteur natif par garantie : identité du processus,
   fichiers, signaux, réseau, création de descendants, annulation et limites
   mémoire. Évaluer le service isolé Android avec un broker explicite de FDs.
   Ne pas étiqueter cette composition comme Bubblewrap ou comme un namespace
   qu'elle ne fournit pas.
5. Étudier et valider la composition sur une machine ARM64 de développement
   dédiée hors du téléphone, avec instrumentation et budgets réellement bornés.
   Une validation Linux/PC ne devient pas une validation Samsung/Android. Toute
   future reprise sur téléphone nécessite une explication étayée de l'incident
   ou un chemin différent justifié, ainsi que l'accord de la tâche principale.

Le critère de réussite reste un vrai travail natif de bout en bout, préservant
les protections de l'appareil et les mises à jour du client officiel. Une
détection `bwrap` rendue positive sans ses garanties, une simulation, une VM ou
une protection supprimée ne satisfait pas ce critère.

## Sources effectivement relues

Références Linux 6.12.58 consultées via le connecteur de code le 7 septembre :

- **L1** [init/Kconfig](https://github.com/gregkh/linux/blob/v6.12.58/init/Kconfig) : `USER_NS` et `PID_NS` sont `bool`.
- **L2** [kernel/Makefile](https://github.com/gregkh/linux/blob/v6.12.58/kernel/Makefile) : compilation conditionnelle des deux implémentations.
- **L3** [include/linux/user_namespace.h](https://github.com/gregkh/linux/blob/v6.12.58/include/linux/user_namespace.h) : stubs sans `CONFIG_USER_NS`.
- **L4** [include/linux/pid_namespace.h](https://github.com/gregkh/linux/blob/v6.12.58/include/linux/pid_namespace.h) : refus `CLONE_NEWPID` sans `CONFIG_PID_NS`.
- **L5** [kernel/module/main.c](https://github.com/gregkh/linux/blob/v6.12.58/kernel/module/main.c) : `may_init_module`, `CAP_SYS_MODULE`, `modules_disabled`.
- **L6** [kernel/bpf/syscall.c](https://github.com/gregkh/linux/blob/v6.12.58/kernel/bpf/syscall.c) : limites et capacités selon type de programme.
- **L7** [kernel/bpf/token.c](https://github.com/gregkh/linux/blob/v6.12.58/kernel/bpf/token.c) : délégation bornée, capacités et user namespace.

Sources AOSP de politique SELinux relues dans le checkout officiel local,
révision `4571ddd9440721fec583c906a337de949a77749e`. Ces liens pointent la
révision relue ; ils n'affirment pas la correspondance avec le binaire Samsung :

- **A1** [private/app.te](https://android.googlesource.com/platform/system/sepolicy/+/4571ddd9440721fec583c906a337de949a77749e/private/app.te), ligne 524 : refus des capabilities pour les domaines applicatifs ordinaires.
- **A2** [private/domain.te](https://android.googlesource.com/platform/system/sepolicy/+/4571ddd9440721fec583c906a337de949a77749e/private/domain.te), lignes 1479–1483 : origine admise des modules.
- **A3** [private/bpfloader.te](https://android.googlesource.com/platform/system/sepolicy/+/4571ddd9440721fec583c906a337de949a77749e/private/bpfloader.te), lignes 50–51 : séparation du chargeur BPF.
- **A4** [private/isolated_app_all.te](https://android.googlesource.com/platform/system/sepolicy/+/4571ddd9440721fec583c906a337de949a77749e/private/isolated_app_all.te) : accès aux FDs transmis, ptrace interne, refus d'ouverture directe et des sockets réseau.
- **A5** [attrs_manifest.xml, android16-release](https://github.com/aosp-mirror/platform_frameworks_base/blob/android16-release/core/res/res/values/attrs_manifest.xml) : contrat `isolatedProcess` et `externalService`, relu via le connecteur de code.
- **A6** [private/mls](https://android.googlesource.com/platform/system/sepolicy/+/4571ddd9440721fec583c906a337de949a77749e/private/mls), lignes 14–19 : contraintes MLS sur `ptrace`.
- **A7** Bionic `android16-release`, relu via le connecteur de code : [SECCOMP_ALLOWLIST_COMMON.TXT](https://github.com/aosp-mirror/platform_bionic/blob/android16-release/libc/SECCOMP_ALLOWLIST_COMMON.TXT), [SYSCALLS.TXT](https://github.com/aosp-mirror/platform_bionic/blob/android16-release/libc/SYSCALLS.TXT), [SECCOMP_BLOCKLIST_APP.TXT](https://github.com/aosp-mirror/platform_bionic/blob/android16-release/libc/SECCOMP_BLOCKLIST_APP.TXT), [SECCOMP_BLOCKLIST_COMMON.TXT](https://github.com/aosp-mirror/platform_bionic/blob/android16-release/libc/SECCOMP_BLOCKLIST_COMMON.TXT).
- **A8** [public/te_macros](https://android.googlesource.com/platform/system/sepolicy/+/4571ddd9440721fec583c906a337de949a77749e/public/te_macros), macro `binder_call` lignes 464–473 ; invocation entre applications dans `app.te` ligne 403.

**D1** `docs/research/android-native-constraints-2026-09-06.md` : observations du
téléphone et références Landlock, seccomp, Android Sandbox, Samsung/Knox ouvertes
lors de la recherche du 6 septembre. En particulier, la référence Knox conservée
est [Hardware-Backed Security](https://docs.samsungknox.com/admin/fundamentals/whitepaper/samsung-knox-mobile-security/system-security/hw-backed-security/).
La page Knox a aussi été relue dans le navigateur intégré par la tâche
principale le 7 septembre (mise à jour affichée : 7 mars 2025) : clé privée
Samsung pour Secure Boot et Warranty Bit persistant en cas notamment de noyau
non signé ou SELinux désactivé. Elle ne constitue ni une garantie contractuelle
ni une nouvelle vérification de l'intégrité de l'appareil dans cette sous-tâche.

**D2** [AOSP : modules de noyau chargeables](https://source.android.com/docs/core/architecture/kernel/loadable-kernel-modules?hl=fr), page intégralement relue dans le navigateur intégré par la tâche principale le 7 septembre, mise à jour affichée : 18 juin 2026. Partitions de modules vérifiées et en lecture seule, séparation GKI/fournisseur et restrictions des symboles ; tous les modules ne sont pas nécessairement signés individuellement.
