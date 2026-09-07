# Mécanismes effectifs et blocages de l'exécuteur

Inventaire du 7 septembre 2026. La question n'est pas uniquement « le fichier
bwrap est-il installé ? », mais « pouvons-nous exécuter les commandes avec la
politique demandée, leur runtime et le contrat du client ? ».

## Trois niveaux de disponibilité

| Niveau | Exemple réel | Conséquence |
| --- | --- | --- |
| Composant utilisateur à fournir | Bash, CPython, bibliothèques Bionic ; exécutable bwrap si son binaire manque | Nous pouvons compiler et distribuer notre composant. Cela ne change pas le noyau |
| Fonction présente, accès à déterminer | Namespaces réseau/montage, ptrace, services Binder | UID, capabilities, SELinux et filtres hérités décident des opérations permises |
| Fonction absente du noyau démarré | `CONFIG_USER_NS=n`, `CONFIG_PID_NS=n` | Une compilation d'APK ou d'exécutable n'ajoute pas cette implémentation |

## Ce que signifie exactement le message Bubblewrap

Les [preuves de la tâche Python](../../publication-readiness-fr.md) du
6 septembre indiquent un **binaire déjà présent** : `bwrap --version` répond,
mais `bwrap --help` échoue à lire `/proc/sys/kernel/overflowuid`. Cette preuve
est historique ; l'inventaire v2 ne relance pas Bubblewrap.

Le code officiel `rust-v0.153.4`, relu au commit réel
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`, lance précisément `bwrap --help`
pour rechercher ses capacités, dont `--as-pid-1` puis `--perms`. En l'absence
de ces éléments dans sa sortie, ce binaire n'est pas retenu. « Unavailable »
ne prouve donc pas l'absence du fichier. Réparer honnêtement cette détection
enlèverait une première erreur, sans fournir les mécanismes d'exécution.
[Source : détection](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/linux-sandbox/src/launcher.rs#L185).

Dans la branche Bubblewrap auditée, **les deux constructeurs demandent
explicitement `--unshare-user`, `--unshare-pid` et `--unshare-ipc`** ; le lanceur
ajoute `--as-pid-1`. Les namespaces user/PID manquants sont donc bien requis
par cette route. Le réseau séparé et le montage `/proc` sont conditionnels,
mais cela ne retire pas les deux demandes précédentes.
[Constructeur 1](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/linux-sandbox/src/bwrap.rs#L284),
[constructeur 2](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/linux-sandbox/src/bwrap.rs#L334).

Le moteur possède aussi des branches sans Bubblewrap pour certaines politiques
et une option Landlock historique. Elles ne représentent pas toutes les
politiques requises, notamment les lectures restreintes. Les sélectionner sans
traiter ces différences ne serait pas une solution générale conservant les
protections.
[Compatibilité Landlock](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/linux-sandbox/src/linux_run_main.rs#L377),
[limite des lectures](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/linux-sandbox/src/landlock.rs#L71).

## Peut-on construire les fonctions manquantes ?

Les deux options absentes sont des options Linux intégrées (`bool`), pas des
modules chargeables. Nous pouvons reconstruire des sources sur PC, mais leur
installation comme nouveau noyau sur ce téléphone sortirait du périmètre
sans root/déverrouillage/modification du système. Une mise à jour officielle
Samsung pourrait les changer ; aucune mise à jour offrant cela n'a été
identifiée. Voir [l'analyse des extensions noyau](../kernel-extension-options-2026-09-07.md).

## Matrice des mécanismes utiles

| Mécanisme | Preuve ou limite sur le Fold | Utilité réelle et travail restant |
| --- | --- | --- |
| User namespaces | `CONFIG_USER_NS=n`, configuration courante lue | La voie non privilégiée de Bubblewrap ne peut pas y obtenir une autorité de montage confinée |
| PID namespaces | `CONFIG_PID_NS=n` | Pas de vue PID séparée. Facultatif dans certains usages génériques de bwrap, mais explicitement demandé par la branche Codex auditée ci-dessus |
| Autres namespaces | `CONFIG_NAMESPACES=y`, `UTS_NS=y`, `NET_NS=y`, `TIME_NS=y` | Présence distincte d'autorisation. Aucun `CAP_SYS_ADMIN` effectif dans l'app ni dans shell ; pas de pouvoir général de montage obtenu via ADB |
| Landlock | `CONFIG_SECURITY_LANDLOCK=y` actuellement ; ABI 6 et refus de politiques bornées réellement testés auparavant | Restriction héritée des fichiers et de certains accès/scopes. Ni réattribution d'UID ni namespace ; ne suffit pas à tous les contrôles réseau |
| Seccomp | Noyau avec filtres ; vrais processus app à mode 2 / un filtre, shell observé à mode 0 | Restreindre les syscalls et médiatiser des opérations. Impossible de réautoriser un appel refusé par un filtre hérité |
| Notifications seccomp et injection de FD | Essais natifs bornés réussis sur le Fold | Le broker effectue l'opération autorisée ; chemins, pointeurs, inodes, annulation et concurrence restent à couvrir dans le shell dynamique |
| UID et SELinux | App et shell ont des identités/domaines distincts, capabilities effectives nulles | Protègent les autres applications. Ne séparent pas automatiquement des tâches partageant notre UID ou UID 2000 |
| Service Android isolé | API Android et règles AOSP documentées | UID distinct et droits réduits ; admission des exécutables, FD et politique Samsung à qualifier. Aucun droit shell automatique |
| Shizuku UserService | Mesuré après l'inventaire : UID 2000, shell SELinux, seccomp initial 0, capabilities nulles ; qualification Python fixe réussie | Voie Bionic démontrée pour ce test ; ne donne pas les namespaces absents ni une sandbox de production prête |
| Exécutables Bionic | Nouveaux Bash/CPython compilés sur PC et chaîne fixe qualifiée sur le Fold via Shizuku | Base native sans traduction PRoot pour les commandes. Intégration ordinaire du modèle encore requise |
| Exécutables construits dans le projet | Restriction Android de l'exécution directe des données applicatives modernes | Un interpréteur APK peut lire un script Python. Un ELF compilé doit avoir une voie d'exécution réellement autorisée ; piste shell documentée, non testée sur le Fold |
| Processus et ressources | Tests natifs bornés de sous-processus/nettoyage ; `CONFIG_CGROUP_PIDS=n` | PIDFD/subreaper/limites disponibles selon droits. Aucun quota cgroup de descendants à présumer ; `RLIMIT_NPROC` compte le même UID |
| PRoot/ptrace | Compatibilité historique partiellement validée ; nouvelle composition concomitante à deux reboots | N'ajoute pas de garanties noyau. Diagnostic suspendu ; aucun transfert sous Shizuku pour le relancer |
| ARM64, SIMD, crypto | ABI et extensions annoncées dans HWCAP/CPU | Exécuter et accélérer le code local ; aucune instruction n'accorde des droits de noyau à l'application |
| BPF, modules et KVM | Plusieurs options compilées ; droits non délégués | Ni catalogue de « fonctions activables par APK », ni solution aux namespaces manquants. KVM ne prouve pas AVF/pKVM utilisable ; VM hors périmètre |

Preuves : [inventaire v2](../../../downloads/runtime/capabilities-20260907-v2/inventory.json),
[tests natifs limités](../../../tools/executor/native-runner-android-test.md),
[acquisition brokerée](../../../tools/executor/native-managed-android.md),
[capacités Android](03-android-native.md), [Shizuku et sources](05-shizuku.md).

Le [rapport Shizuku + Bionic](../shizuku-bionic-trial-2026-09-07.md) apporte
les preuves de la nouvelle chaîne fixe, y compris les essais échoués puis
corrigés. Ce résultat n'étend pas les anciens tests à des politiques générales.

## Ce que doit remplacer notre exécuteur

Le nouveau composant doit implémenter les protections et opérations requises
avec les mécanismes disponibles. Il ne peut pas se présenter comme fournissant
des namespaces qui n'existent pas. Les contrats à démontrer comprennent :

- lecture/écriture et exceptions par projet, résolution de chemins résistante
  aux courses et protection des métadonnées privées ;
- réseau selon la politique demandée, y compris absence d'accès libre au
  Binder, aux sockets et aux services puissants du téléphone ;
- lancement réel de Bash/Python et descendants, environnement et répertoire
  courant cohérents avec les fichiers affichés ;
- entrées/sorties, codes de sortie, signaux, annulation, terminal lorsque
  demandé, contrôle des ressources et nettoyage des descendants ;
- transmission fidèle des permissions et approbations du moteur, avec refus
  explicite si une garantie demandée n'est pas réalisable.

La protection du processus de commande ne protège pas forcément un workspace
contre un autre processus non confiné de même UID. C'est particulièrement
important avec UID shell partagé : un répertoire `0700` ne crée pas une nouvelle
identité. Le superviseur doit rester une interface étroite ; le modèle ne doit
pas recevoir le contrôle général de Shizuku/rish.

## Variantes natives et autres blocages

| Voie | Atout | Limite déterminante |
| --- | --- | --- |
| Bionic dans le contexte de FoldGPT, avec broker | Réutilise des primitives et transports déjà testés ; Bash/Python compilés | Filtre hérité, isolation de même UID et exécutables produits à traiter |
| Bionic dans un service Android isolé, avec broker | Séparation d'identité offerte par Android | Droits de fichiers/exécution très limités ; assemblage inter-UID non démontré |
| Superviseur Bionic lancé via Shizuku UserService | Autre contexte de lancement ; piste d'`execve` shell documentée | UID partagé, espace de projet, confinement, redémarrage du service et règles Samsung à qualifier |

Ces variantes sont des architectures de notre exécuteur, pas trois solutions
terminées. L'échec de l'une ne clôt pas automatiquement les deux autres.

Le raccordement au client est un **autre travail réel** : la sélection d'un
environnement externe du moteur officiel ne redirige pas toutes les opérations
hôte, panneaux fichiers et commandes de session. Les audits de
[routage](../../../tools/executor/app-server-route-audit.md) et
[portage du moteur](../../../tools/executor/native-engine-integration-review.md)
identifient ces points. Un service Shizuku fonctionnel ne les résout pas seul.
Nos composants peuvent être entretenus séparément du paquet officiel ; cela
préserve ses mises à jour normales sans promettre une compatibilité automatique
de notre interface avec toute future version.

Un MCP/plugin pourrait fournir des outils dans le périmètre autorisé de
l'application, mais n'ajouterait pas davantage de namespaces ni ne garantirait
la même expérience complète. Il reste le dernier recours demandé. Une VM,
une exécution distante ou une modification du noyau changeraient les contraintes
et ne sont pas retenues comme résolution de ce travail.

La [nouvelle chaîne Bionic](../bionic-native-route-2026-09-07.md) et les anciennes
preuves partielles ne sont pas encore un succès de bout en bout. Le critère
reste le petit projet Python réalisé réellement par le modèle depuis le Fold,
avec tests, paquet et refus de politique vérifiés.
