# Shizuku : droits ADB, exécution native et limites du noyau

Analyse du 7 septembre 2026, actualisée après la qualification autorisée de
Shizuku officiel 13.6.0 et d'un APK de sonde distinct. La tâche principale a
installé/démarré Shizuku en mode ADB, obtenu l'autorisation officielle de la
sonde et collecté son vrai UserService. **Cette révision documentaire lit les
preuves conservées sur le PC et n'envoie aucune commande au téléphone.**
L'ancien diagnostic GNU/PRoot demeure suspendu. Le périmètre exclut
root/Sui/Magisk, déverrouillage, modification de SELinux/Knox et du client
officiel.

## Ce que Shizuku apporte réellement

Shizuku peut aider à construire **une autre base d'exécution native**. Il ne peut
pas faire apparaître les fonctions `USER_NS` et `PID_NS` absentes du noyau
démarré. Ces deux constats sont compatibles : un contexte d'exécution différent
peut résoudre une restriction d'application, sans ajouter du code au noyau.

En mode sans root, Shizuku lance un serveur par le débogage Android autorisé
(ADB). Ce serveur tourne sous l'identité Linux **shell, UID 2000**. L'application
cliente reste sous son propre UID : elle lui envoie des demandes par Binder. Pour certains
appels aux services Android, le serveur effectue la demande avec son identité
shell après vérification de l'autorisation du client. Les services Android
appliquent alors les droits que le système a déjà attribués à shell. [S1–S4]

Le fichier `Service.java` montre les deux étapes : `enforceCallingPermission`
puis, dans `transactRemote`, `Binder.clearCallingIdentity()` avant
`targetBinder.transact(...)`. Ce n'est ni une modification des droits de toutes
les applications ni un remplacement de SELinux. Les permissions Android, les
UID/GID, les capabilities Linux et SELinux restent des couches distinctes.
Une permission Android telle que `WRITE_SECURE_SETTINGS` ne donne pas
`CAP_SYS_ADMIN`. [S3, A2]

Il existe deux interfaces différentes :

| Interface | Contrat réel | Intérêt pour FoldGPT |
| --- | --- | --- |
| Appel Binder relayé | Le serveur relaie une transaction autorisée vers un service Android | Accès ciblé à une API système que shell peut appeler ; pas une API générale de création de namespaces |
| `UserService` | Notre classe Java, avec du code natif JNI possible, s'exécute dans un processus distinct UID 2000 | Héberger un petit superviseur natif et son protocole, avec une surface explicitement limitée |
| `rish` | Terminal/shell interactif exécuté par le backend Shizuku | Prouve qu'un shell distant local au téléphone est un usage prévu ; ne fournit pas, seul, une sandbox pour les commandes du modèle |

`newProcess` est déprécié par l'API ; l'amont recommande `UserService` pour les
nouveaux développements. `rish` possède le support interactif absent de
`newProcess`. Il ne faut donc pas construire un nouvel exécuteur sur cette
ancienne API ni confondre transport PTY et confinement. [S2, S8]

## Pourquoi le contexte peut changer des blocages applicatifs

Le lanceur natif Shizuku vérifie que son UID initial vaut 0 ou 2000, puis fait
`fork()` et `execvp("/system/bin/app_process", ...)`. Le chemin shell ne réalise
pas d'élévation vers root. La tentative de rejoindre le mount namespace d'init
dans ce source est expressément dans `if (uid == 0)` : elle ne fait pas partie
du fonctionnement ADB retenu. [S4]

Le lancement d'un `UserService` passe également par `/system/bin/app_process`,
avec une classe Java et **sans `--zygote`**. Le source AOSP d'`app_process`
différencie ce lancement `RuntimeInit` de celui de `ZygoteInit`. Ce processus
n'est donc pas un enfant de l'application FoldGPT créé par Zygote. Il n'hérite
pas automatiquement du filtre seccomp de *cette application*. [S5–S6, A1]

Le seul chemin de lancement ne prouverait ni `Seccomp: 0` ni l'autorisation d'un
appel particulier sur ce Samsung. Le processus réel a désormais été mesuré
ci-dessous. `app_process` reste un lanceur de runtime Android, pas un mécanisme
d'évasion de sandbox. Un filtre hérité d'un autre ancêtre resterait applicable.

Le nouveau relevé du Fold établit une différence réelle entre **la commande
ADB mesurée** et les processus applicatifs. [R1]

| Contexte observé à `00:52:19 +02:00` | UID et SELinux | Seccomp | Capabilities effectives |
| --- | --- | --- | --- |
| `cat /proc/self/status` lancé par ADB shell | UID 2000, `u:r:shell:s0` | `Seccomp: 0`, `Seccomp_filters: 0` | `CapEff: 0` |
| `app.foldgpt`, PID 16917 | UID 10412, `untrusted_app` avec catégories MLS | `Seccomp: 2`, `Seccomp_filters: 1` | `CapEff: 0` |
| `app.foldgpt:runtime`, PID 17419 | UID 10412, même contexte applicatif | `Seccomp: 2`, `Seccomp_filters: 1` | `CapEff: 0` |

Les deux processus applicatifs ont pour parent PID 1903, identifié comme
`zygote64` dans le même snapshot. Il s'agit de leurs vrais statuts `/proc`, pas
d'une commande `run-as` présentée comme un enfant de Zygote. Le processus shell
a `CapBnd: 0x8000c0` mais `CapInh/Prm/Eff/Amb: 0` : un plafond de capabilities
non nul ne constitue pas une capability effective. **Le relevé ne donne aucun
`CAP_SYS_ADMIN` effectif à shell.** L'absence de filtre seccomp pour cette
commande ne supprime ni les contrôles UID/SELinux ni les fonctions absentes du
noyau.

Ce premier résultat renforce l'intérêt d'un lanceur issu d'ADB, mais **ne mesure
pas un UserService Shizuku**. Dans cet inventaire antérieur à l'installation, `pm path
moe.shizuku.privileged.api` renvoie le code 1 sans chemin, `pm list packages -u
shizuku` renvoie une liste vide, et aucun processus Shizuku n'est retrouvé dans
le snapshot. C'est une absence observée du paquet standard et du serveur à cet
instant, pas la preuve universelle qu'aucune variante ni installation dans un
autre contexte ne puisse exister. Ce constat à `00:52:19` est historique :
l'installation officielle et la phase 1 qui suivent apportent une nouvelle
preuve, sans réécrire cet ancien relevé. [R1–R2]

### Phase 1 : vrai UserService mesuré

Le rapport de l'APK distinct `app.foldgpt.shizukuprobe` du
`2026-09-07T01:21:49.508+02:00` constate les éléments suivants. Son Binder
provient de Shizuku officiel en mode ADB ; l'API/provider Maven est épinglée à
13.1.5. Il ne s'agit pas d'une commande ADB présentée comme ce service. [R2]

| Élément | Observation du UserService réel |
| --- | --- |
| Identité | PID 32106, UID/GID 2000, parent PID 1 |
| Client autorisé | UID 10350, identique à `callingUid` ; distinct de l'UID du service |
| SELinux | `u:r:shell:s0` |
| Processus et thread Binder | `Seccomp: 0`, `Seccomp_filters: 0` dans `/proc/self/status` **et** `/proc/thread-self/status` |
| Capabilities | `CapInh/Prm/Eff/Amb: 0`, `CapBnd: 0x8000c0` |
| Commandes exécutées par la phase 1 | 0 : collecte fixe du contexte uniquement |
| Fin de vie | La tâche principale a confirmé la disparition du service après `unbindUserService` |

Cette phase valide l'accès à un **contexte shell différent de celui de
l'application**, avec le filtre réellement constaté et sans capability
effective. Elle ne valide pas encore Bash/Python, le confinement d'un travail,
le raccordement au client officiel ou l'autonomie après redémarrage.

Une deuxième différence concerne les fichiers exécutables. La politique AOSP
épinglée permet à `shell` de créer, lire et exécuter des fichiers de type
`shell_data_file`, dont `/data/local/tmp`. La macro `rx_file_perms` comprend
`execute`, `execute_no_trans` et `map`. Cette règle n'est pas enfermée dans une
condition `userdebug_or_eng`. [A3–A5]

Un programme Bionic construit localement dans un espace shell approprié
pourrait donc avoir une voie d'`execve` ordinaire, avec son véritable fichier
exécutable et les sémantiques usuelles `argv`/`/proc/self/exe`, au lieu de
rencontrer exactement le refus qui vise les fichiers `app_data_file` d'une
application moderne. **C'est une hypothèse étayée par une autorisation AOSP,
pas un test réussi sur One UI 9.** Il faut aussi vérifier le montage, le label
réel, le chargeur, les dépendances et les règles Samsung. Cela ne rend pas une
bibliothèque glibc compatible avec Bionic par elle-même.

## Matrice des possibilités et des limites

| Besoin | Apport possible de Shizuku ADB | Ce qui demeure à satisfaire |
| --- | --- | --- |
| Ajouter `CONFIG_USER_NS` / `CONFIG_PID_NS` | Aucun : le serveur utilise le même noyau | Ces options intégrées ne sont pas des bibliothèques applicatives ; voir le dossier noyau |
| Faire fonctionner Bubblewrap standard | Aucun rétablissement des mécanismes manquants | Même un contexte shell ne crée pas un PID namespace absent ; aucune capacité de montage générale ne doit être présumée |
| Exécuter notre code Java/JNI sous une autre identité | Fonction documentée ; vraie classe UserService de la sonde exécutée sous UID 2000 [R2] | L'exécuteur Bionic complet et son intégration restent à valider |
| Ne pas hériter du filtre de l'application FoldGPT | Vrai UserService et son thread Binder mesurés sans seccomp [R2] | Cela ne crée pas les fonctions noyau absentes et ne démontre pas chaque syscall nécessaire |
| Exécuter un ELF Bionic produit dans l'espace shell | Autorisation AOSP de création/exécution de `shell_data_file` | À vérifier sur le Fold ; chaîne Bionic et permissions exactes requises |
| Accéder aux fichiers privés existants de FoldGPT/ChatGPT | Pas d'accès général accordé par Shizuku | La documentation cite explicitement l'impossibilité de lire `/data/user/0/<package>` d'autres apps en mode ADB |
| Contrôler les sous-processus et un terminal | `UserService`, JNI et `rish` montrent des mécanismes réels | Notre supervision, annulation, timeout, PTY, signaux et récupération des enfants doivent être implémentés et vérifiés |
| Protéger les fichiers/réseau/processus pendant les commandes | Shizuku peut héberger un superviseur ; il n'est pas ce confinement | Composition Landlock/seccomp/broker/FD et contrôle de tous les accès sensibles avant le code du modèle |
| Disposer d'un UID unique par tâche | Shizuku ADB seul ne le documente pas | UID 2000 est partagé avec d'autres tâches shell ; ne pas supposer `setuid` libre ou un domaine SELinux privé |
| Corriger les deux redémarrages | Aucune preuve | Le noyau reste le même ; déplacer le même mélange PRoot/ptrace/seccomp ne suffit pas à établir une correction |
| Garder les mises à jour officielles | Possible sans modifier le client officiel | Notre APK et notre contrat d'interfaçage doivent suivre les versions ; cette compatibilité n'est pas automatique |
| Redémarrer le téléphone puis fonctionner sans ordinateur | Démarrage local depuis Android 11 ; auto-démarrage ADB conditionnel ajouté dans le code officiel 13.6.0 pour Android 13+ [S10–S12] | Ce chemin exige notamment WSS et modifie les réglages ADB/leur expiration ; il n'est pas activé comme solution de cette qualification |

Sources des limites de fichiers et de droits : [S2, S8]. Les permissions shell
AOSP peuvent différer selon Android et le constructeur. Cette matrice ne
transforme pas une règle amont en observation du Fold.

## Architecture candidate, sans donner un shell libre au modèle

La piste utile serait un **UserService Shizuku limité à la supervision**, puis
un exécutable Bionic de travail confiné avant toute commande issue du modèle.
Le service garderait un canal de contrôle authentifié ; le travail recevrait
uniquement ses flux et ses accès à l'espace de projet. Le modèle n'aurait pas
accès au Binder Shizuku ni à une méthode générale `transactRemote` ou `rish`.

Cette distinction est indispensable à cause du besoin réel de protection du
téléphone : shell possède des API Android puissantes que le simple filtre de
fichiers ne neutralise pas. Les FDs Binder et de contrôle ne doivent pas être
hérités par le travail, et ses accès à Binder, sockets, autres processus et
opérations sensibles doivent être refusés ou médiatisés. La politique doit
porter sur les mécanismes, pas sur une liste de noms de commandes interdits.
La permission Shizuku accordée à FoldGPT autorise l'application ; elle ne
valide pas automatiquement chaque commande proposée par le modèle.

Le workspace est un choix d'architecture à résoudre, pas un détail de chemin.
Le runtime GNU actuel se trouve dans les données privées de FoldGPT auxquelles
shell n'a pas un accès général. Deux possibilités demandent une analyse :

- un espace de projet réellement accessible au service shell, avec un contrat
  explicite conservant les chemins, propriétaires et opérations attendus ;
- un broker côté application propriétaire pour les accès à ses fichiers, avec
  des opérations ou FDs précisément admis par les contrôles Android.

Passer un FD ne modifie pas son type SELinux et ne garantit pas que shell pourra
effectuer les opérations voulues sur ce FD. Déplacer un projet ou réécrire
silencieusement le répertoire courant ne valide pas le contrat de Codex. Il
reste aussi à traiter la confidentialité vis-à-vis des autres processus UID
2000 : un répertoire `0700` sépare les UID, pas deux programmes sous le même UID.
Un filtre Landlock/seccomp posé sur notre travail limite ce travail et ses
descendants ; il ne confine pas rétroactivement les autres processus shell.
La protection mutuelle contre un processus extérieur UID 2000 demande donc une
frontière supplémentaire ou une limite de confiance explicite. La simple
existence d'un UserService, d'un chemin privé ou d'un contrôle Binder ne prouve
pas cette isolation.

Le service Java/Binder est multithreadé. Notre lancement natif doit utiliser une
transition contrôlée vers un exécutable, avec fermeture des FDs superflus ; il
ne faut pas poursuivre arbitrairement une copie du runtime Java après `fork`.
Un processus Bionic indépendant permettrait de réutiliser la supervision
existante sans mettre la boucle Binder dans la partie confinée.

## Cycle de vie et mises à jour

Le guide officiel consulté, daté de juin 2023, indique un démarrage local sans
PC depuis Android 11 et une relance après reboot. **Il est insuffisant pour
décrire Shizuku 13.6.0.** Le source officiel de cette version contient un
auto-démarrage ADB conditionnel dans `BootCompleteReceiver` : utilisateur
Android principal, Android 13+, dernier mode de lancement ADB et permission
`WRITE_SECURE_SETTINGS` accordée au manager. [S7, S10]

Ce code écrit `adb_wifi_enabled=1`, `adb_enabled=1` et
`adb_allowed_connection_time=0`, puis recherche le service mDNS `TLS_CONNECT`
et se connecte à ADB sur `127.0.0.1` avec la clé conservée par Shizuku. Il dépend
donc également des conditions réelles de débogage sans fil, du réseau et de
l'authentification ADB. Ce n'est ni une survie du processus au reboot ni une
fonction de bootstrap automatique fournie par le SDK client à FoldGPT. [S10]

La permission WSS peut être accordée automatiquement au **manager Shizuku**
lors de son attachement au serveur : `ShizukuService.attachApplication` la
demande dans sa branche `isManager`. `HomeActivity` mémorise le mode ADB
lorsqu'elle voit un serveur UID non nul. De plus, ouvrir le dialogue ADB du
manager alors qu'il possède WSS peut effectuer les mêmes trois écritures de
réglages, indépendamment d'un reboot. Ce comportement ne doit pas être présenté
comme une option manuelle distincte nécessairement désactivée. [S11–S12]

Pendant la qualification, l'accord WSS au manager a été identifié puis **révoqué
par la tâche principale après la phase 1** pour préserver la politique
d'expiration ADB. Les lectures conservées donnent
`adb_allowed_connection_time: null`, et non `0`. `null` signifie ici qu'aucune
valeur explicite n'est lue pour ce réglage ; cela ne prouve pas à lui seul une
durée fournisseur précise. Le manager n'est pas rouvert inutilement, car un
nouvel attachement pourrait accorder WSS de nouveau. Notre APK de sonde
n'accorde ni WSS ni une autorisation ADB à lui-même et ne change aucun de ces
réglages. [R3]

`UserServiceArgs.daemon(false)` prévoit l'arrêt lié à la mort de l'application
cliente ; le mode daemon par défaut dure jusqu'au retrait explicite du service.
Ce dernier n'est pas une garantie de survie au reboot, au système ou à la mort
de Shizuku. L'API exige également une méthode de destruction avec nettoyage
et sortie du processus. Un changement de `version` permet de recréer un
service après modification du code. [S2, S9]

Le contrôle Shizuku serait ajouté à **FoldGPT**, pas injecté dans ChatGPT. Cela
préserve le paquet officiel et sa mise à jour normale. Le raccordement du
client officiel à un environnement d'exécution demeure un travail séparé ;
Shizuku ne fournit pas ce protocole à sa place.

## État réel de preuve : échec initial puis qualification réussie

La phase 1 est acquise pour la collecte du UserService [R2]. La phase 2 du
premier APK à garde natif épinglé **a échoué** : code de sortie 139, stdout et
stderr vides, aucun enregistrement `probe-result`. L'APK ne l'a pas converti en
réussite : `success=false`, `nativeFinalValid=false`,
`cleanup_complete=false`. Son UserService a été conservé pour maintenir la
propriété du processus, sans nouvelle tentative automatique. La tâche
principale l'a ensuite arrêté après avoir vérifié l'absence de descendants.
Le fait que le fichier JSON indique `state=complete` signifie que le rapport a
été produit, pas que le test natif a réussi. [R4]

La tâche principale a constaté un boot inchangé et l'absence du workspace et du
sentinel qui auraient été créés par le garde avant la fixture. Deux analyses
PC ont ensuite reproduit le crash avant `main` : le montage NDK `-static-pie`
retenait un démarrage sans les relocations nécessaires. La correction en PIE
dynamique Android est suivie dans le [rapport de l'essai](../shizuku-bionic-trial-2026-09-07.md).
Ce diagnostic de liaison ne démontre pas une fonction manquante du noyau.
Aucun succès Bash/Python, aucun refus
de confinement de cette phase et aucune réussite du client ordinaire ne sont
déduits de la phase 1 ou des tests hôte. L'ancien diagnostic GNU/PRoot
concomitant aux deux redémarrages demeure suspendu. [R4]

Les reprises contrôlées ont corrigé le format ELF, ciblé le fichier accessible
`/linkerconfig/ld.config.txt` et ajouté la lecture de la base officielle de
fuseaux horaires Bionic. Chaque garde avait son nouveau hash compilé dans
l'APK. La [collecte indépendante finale](../../../downloads/shizuku-lab/collected-final-verified/independent-verification.json)
est maintenant **PASS** : Bash et Python Bionic réels, source créée/modifiée,
trois tests, zipapp construit/exécuté, six refus dans Python et nettoyage
complet. Le boot est inchangé et les indicateurs Knox/boot/SELinux conservés.

**Shizuku + Bionic est donc une voie native démontrée pour cette charge fixe.**
Le test depuis l'interface ordinaire, toutes les politiques et le cycle de vie
de production restent à réaliser. Le résultat ne crée pas les namespaces
absents et ne signifie pas que le message Bubblewrap du client est corrigé.

## Sources et reproductibilité

Les dépôts Shizuku et API ont été lus au 7 septembre 2026. Le HEAD obtenu est
daté de 2025 ; il ne constitue pas un inventaire de la version installée sur le
Fold. Le sous-module API de ce HEAD correspond exactement à la révision API
ci-dessous. Les nouveaux fichiers de cycle de vie sont lus séparément au tag
officiel 13.6.0 `2650830c5b099ae0dd34fedf614d4f592ca05d65`. La qualification
utilise le SDK publié épinglé 13.1.5 ; le serveur officiel n'est pas reconstruit.

- **S1** — [Shizuku README](https://github.com/RikkaApps/Shizuku/blob/b844bc491f1790c72328e1a8e5b2349f8978f0ea/README.md) : serveur ADB/root, Binder intermédiaire, limites ADB.
- **S2** — [Shizuku-API README](https://github.com/RikkaApps/Shizuku-API/blob/a27f6e4151ba7b39965ca47edb2bf0aeed7102e5/README.md) : UID 2000/0, permissions et données privées, UserService/JNI, reboot, dépréciation `newProcess`.
- **S3** — [Service.java, lignes 105–195](https://github.com/RikkaApps/Shizuku-API/blob/a27f6e4151ba7b39965ca47edb2bf0aeed7102e5/server-shared/src/main/java/rikka/shizuku/server/Service.java#L105) : autorisation, identité Binder, UID, permission et contexte SELinux.
- **S4** — [starter.cpp, lignes 94–223](https://github.com/RikkaApps/Shizuku/blob/b844bc491f1790c72328e1a8e5b2349f8978f0ea/manager/src/main/jni/starter.cpp#L94) : lancement `app_process`, `fork`, validation UID et opérations réservées à UID 0.
- **S5** — [ShizukuUserServiceManager.java, lignes 26–39](https://github.com/RikkaApps/Shizuku/blob/b844bc491f1790c72328e1a8e5b2349f8978f0ea/server/src/main/java/rikka/shizuku/server/ShizukuUserServiceManager.java#L26), [ServiceStarter.java, lignes 44–58](https://github.com/RikkaApps/Shizuku/blob/b844bc491f1790c72328e1a8e5b2349f8978f0ea/starter/src/main/java/moe/shizuku/starter/ServiceStarter.java#L44) : commande exacte du UserService sans `--zygote`.
- **S6** — [UserServiceManager.java](https://github.com/RikkaApps/Shizuku-API/blob/a27f6e4151ba7b39965ca47edb2bf0aeed7102e5/server-shared/src/main/java/rikka/shizuku/server/UserServiceManager.java#L49) : vérification du propriétaire du paquet, lancement et token du service.
- **S7** — [Guide officiel Shizuku](https://shizuku.rikka.app/guide/setup/) : lu dans le navigateur intégré le 7 septembre 2026, mise à jour affichée 21 juin 2023 ; lancement sans fil, redémarrage et limites OEM.
- **S8** — [RISH README](https://github.com/RikkaApps/Shizuku-API/blob/a27f6e4151ba7b39965ca47edb2bf0aeed7102e5/rish/README.md) : vrai shell backend et incapacité ADB à utiliser les chemins privés Termux de `PATH`/`LD_PRELOAD`.
- **S9** — [Shizuku.java, lignes 593–627](https://github.com/RikkaApps/Shizuku-API/blob/a27f6e4151ba7b39965ca47edb2bf0aeed7102e5/api/src/main/java/rikka/shizuku/Shizuku.java#L593) : daemon, tag et version du service.
- **S10** — [Shizuku 13.6.0 BootCompleteReceiver.kt](https://github.com/RikkaApps/Shizuku/blob/2650830c5b099ae0dd34fedf614d4f592ca05d65/manager/src/main/java/moe/shizuku/manager/receiver/BootCompleteReceiver.kt) : conditions Android 13+/utilisateur 0/mode ADB/WSS, trois réglages ADB, mDNS et clé ADB conservée. Blob `225ae3d92f7594296924c85247952e1d97b464ee`.
- **S11** — [Shizuku 13.6.0 ShizukuService.java, lignes 240–246](https://github.com/RikkaApps/Shizuku/blob/2650830c5b099ae0dd34fedf614d4f592ca05d65/server/src/main/java/rikka/shizuku/server/ShizukuService.java#L240) : tentative d'accord WSS au manager à son attachement ; [HomeActivity.kt, lignes 50–56](https://github.com/RikkaApps/Shizuku/blob/2650830c5b099ae0dd34fedf614d4f592ca05d65/manager/src/main/java/moe/shizuku/manager/home/HomeActivity.kt#L50) : mémorisation du mode de lancement.
- **S12** — [Shizuku 13.6.0 AdbDialogFragment.kt, lignes 61–69](https://github.com/RikkaApps/Shizuku/blob/2650830c5b099ae0dd34fedf614d4f592ca05d65/manager/src/main/java/moe/shizuku/manager/home/AdbDialogFragment.kt#L61) : mêmes écritures de réglages lorsque le dialogue s'ouvre avec WSS. Blob `8dfa344daf1c8e629e305e6b424fa3ac3ae43df9`.
- **A1** — [AOSP app_main.cpp](https://github.com/aosp-mirror/platform_frameworks_base/blob/main/cmds/app_process/app_main.cpp) : lecture du bloc lignes 210–365, blob `4e41f2c1ac35aeb7fca364daf496d4f675011a2d` ; distinction `RuntimeInit`/`ZygoteInit`. Référence amont, pas le binaire Samsung.
- **A2** — [AOSP Shell AndroidManifest.xml](https://github.com/aosp-mirror/platform_frameworks_base/blob/main/packages/Shell/AndroidManifest.xml) : extrait lignes 1–150, blob `65f487765c1ec1360b7b4bdbc4d9663eed78238e` ; identité shell et permissions Android. Ce fichier ne prouve pas les droits Linux du Fold.
- **A3** — [AOSP shell.te](https://android.googlesource.com/platform/system/sepolicy/+/4571ddd9440721fec583c906a337de949a77749e/private/shell.te) : lignes 308–318, 338–349, 439–440 et 504–548 ; exécution de `shell_data_file`, PTY, ptrace et limites explicites. Révision du 27 mars 2025, pas dump One UI 9.
- **A4** — [AOSP global_macros](https://android.googlesource.com/platform/system/sepolicy/+/4571ddd9440721fec583c906a337de949a77749e/public/global_macros) : lignes 24–27, contenu exact de `x_file_perms`/`rx_file_perms`.
- **A5** — [AOSP file_contexts](https://android.googlesource.com/platform/system/sepolicy/+/4571ddd9440721fec583c906a337de949a77749e/private/file_contexts) : `/data/local/tmp(/.*)?` associé à `shell_data_file`, avec exceptions spécifiques.
- **R1** — Inventaire réel du Fold du `2026-09-07T00:52:19.003675+02:00` : [brief.json](../../../downloads/runtime/capabilities-20260907-v2/brief.json), [inventory.json](../../../downloads/runtime/capabilities-20260907-v2/inventory.json). Entrées `shell-identity`, `shell-context`, `shell-status`, `process-16917-status`, `process-17419-status`, `processes`, `shizuku-package` et `shizuku-package-list`. Version `v2` conservant les codes de sortie distants ; elle remplace la première collecte dont le transport texte ne conservait pas fiablement les erreurs. Lecture seule, sans probe namespace/seccomp/ptrace ni activation Shizuku.
- **R2** — Phase 1 sur le Fold : [context-report.json](../../../downloads/shizuku-lab/attempt-20260907/context-report.json), [context-brief.json](../../../downloads/shizuku-lab/attempt-20260907/context-brief.json), [APK et contrat de sonde](../../../tools/executor/shizuku-lab/README.md). UserService réel à `01:21:49.508 +02:00`, zéro commande, contexte UID 2000 et seccomp mesuré. La disparition après unbind et le boot inchangé ont été vérifiés par la tâche principale.
- **R3** — Qualification ADB/manager : `downloads/shizuku-lab/attempt-20260907/limit-manager-settings-access.stdout` et `.stderr` vides pour la révocation exécutée par la tâche principale ; [verify-adb-expiration.stdout](../../../downloads/shizuku-lab/attempt-20260907/verify-adb-expiration.stdout) affiche `null`. Le fichier [post-failure-state.txt](../../../downloads/shizuku-lab/collected-first/post-failure-state.txt) conserve une lecture ultérieure `null` et les états d'intégrité.
- **R4** — Premier lancement natif : [report.txt](../../../downloads/shizuku-lab/collected-first/report.txt), [état après échec](../../../downloads/shizuku-lab/collected-first/post-failure-state.txt). APK SHA256 `4c3bf3ea917f6a232526779ed61edb4676c1e5ac5a58ea8543e3e2e015cce155`, garde SHA256 `b4579de9630180fe876027f0371bd8b05add0a739716f89becf0710c07951854` ; sortie 139 sans résultat natif. Le [rapport de l'essai](../shizuku-bionic-trial-2026-09-07.md) suit la reproduction PC de la faute de liaison, l'arrêt contrôlé du UserService après vérification des descendants et les éventuels essais suivants.

Sources locales : `downloads/research/shizuku-source-20260907`,
`downloads/research/shizuku-api-source-20260907`, `downloads/isolation-sepolicy`.
Voir également [l'analyse des extensions noyau](../kernel-extension-options-2026-09-07.md)
et [l'incident GNU](../gnu-managed-reboot-2026-09-06.md).
