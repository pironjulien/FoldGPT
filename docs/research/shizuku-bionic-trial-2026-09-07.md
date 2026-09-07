# Essai Shizuku et Bionic sur le Fold — 7 septembre 2026

Ce rapport concerne le dernier essai de faisabilité demandé par Julien :
lancer un petit projet Python nativement via Shizuku, sans root, VM,
déverrouillage ou modification du client officiel. L'application de test est
séparée de FoldGPT. Le résultat doit distinguer cette qualification fixe de
l'exécution ordinaire des commandes du modèle dans l'interface.

## Résultat : qualification fixe réussie sur le Fold

La [collecte indépendante finale](../../downloads/shizuku-lab/collected-final-verified/independent-verification.json)
est **PASS**. Le [rapport Android complet](../../downloads/shizuku-lab/collected-final-verified/report.txt)
prouve une exécution réelle sous le UserService Shizuku, avec Bash/Bionic et
Python 3.14.7 (`sys.platform=android`).

| Contrôle | Résultat réel |
| --- | --- |
| Projet Python | Fichier créé puis modifié de 41 à 42 |
| Tests | Trois tests unittest passent dans un sous-processus |
| Paquet | Zipapp compressé de 606 octets construit et exécuté : `42` |
| Flux et enfants | stdin, stdout, stderr, sortie 23 et environnement vide vérifiés |
| Protections | Landlock ABI 6 et seccomp actifs ; six refus dans Python, refus Binder vérifié avant l'interpréteur |
| Fin | Code 0, stderr vide, nettoyage complet ; superviseur et enfant absents après le test |
| Preuve matérielle | Sources, paquet et sentinelle récupérés ; paquet vérifié puis exécuté indépendamment sur le PC |
| Stabilité de cet essai | Même boot ID avant/après : aucun nouveau redémarrage observé |
| Indicateurs Android | Warranty bit 0, boot vérifié green, flash verrouillé 1, SELinux Enforcing |

L'opération native finale dure 457 ms ; ce chiffre concerne uniquement cette
petite charge fixe, sans installation ni démarrage du service. Les
[2 607 fichiers/alias du runtime](../../downloads/shizuku-lab/attempt-20260907/runtime-independent-after.json)
sont encore conformes après le test. L'APK principal FoldGPT conserve son
[empreinte précédente](../../downloads/shizuku-lab/attempt-20260907/main-apk-unchanged.txt).
Aucun fichier du client officiel n'a été modifié par cet essai.

Identités finales :

- APK de sonde v5 : `5270ee6efa889012ee2a3bfd4891d62c1b7b0c3f75034d0d46037002d26443cc`.
- Garde natif : `7fa4f638c431866e69dcda8618a3e8872b19861941d5d7bd1dbc8ec92352893b`.
- Source C : `c80adb7fbec20105c23ffe9160381d3aab6dc6f9e1e5d265a44cb2abb2cac0c0`.

**La voie technique Shizuku + Bionic est donc démontrée pour cette charge.**
Le modèle n'a pas encore piloté ce travail depuis l'interface ordinaire :
l'application de qualification lance une opération fixe et connue. Le message
Bubblewrap de la route de production n'est pas corrigé par cette installation.

## Contexte réellement obtenu

Shizuku officiel `13.6.0.r1086.2650830c` a été installé depuis sa
[publication officielle](https://github.com/RikkaApps/Shizuku/releases/tag/v13.6.0).
Le serveur a démarré sous l'identité ADB shell, sans root. Notre application
`app.foldgpt.shizukuprobe` utilise le SDK officiel `13.1.5` et son autorisation
standard ; elle ne fournit aucune interface de commande arbitraire.

Le [rapport de contexte](../../downloads/shizuku-lab/attempt-20260907/context-report.json)
mesure le vrai UserService et son thread Binder : UID/GID 2000, domaine
SELinux `u:r:shell:s0`, aucun filtre seccomp hérité, aucune capability effective,
permise, héritable ou ambiante. L'appelant est bien l'application autorisée
UID 10350. Cette première étape n'a lancé aucune commande native.

## Chaîne de qualification

Le [garde natif](../../tools/executor/bionic-runtime/shizuku-probe.c) lance
Bash 5.3.15 puis CPython 3.14.7 compilés pour Android/Bionic. La bibliothèque
Python complète et les dépendances sont déployées dans un laboratoire shell
privé : 79 fichiers ELF, 81 alias et 2 447 fichiers de données.
La [vérification indépendante avant exécution](../../downloads/shizuku-lab/attempt-20260907/runtime-independent-before.json)
contrôle les 2 607 fichiers/alias sur le téléphone.

Avant l'interpréteur, le garde ferme les descripteurs hérités, applique
`no_new_privs`, Landlock et un filtre seccomp explicite. Il n'utilise pas
PRoot, ptrace, notifications seccomp, namespaces ou shell modèle privilégié.
Il limite les ressources et supervise les descendants. Le
[contrat détaillé](../../tools/executor/bionic-runtime/shizuku-protocol.md)
décrit les accès autorisés et la portée exacte des limites : celles-ci ne
constituent notamment pas un plafond mémoire total de tous les processus.

La charge fixe doit créer et modifier un calculateur Python, passer trois
tests unittest, construire un paquet zipapp et l'exécuter pour obtenir 42.
Elle vérifie aussi les flux stdin/stdout/stderr, un code de sortie 23,
l'environnement vide des enfants et six refus dans l'interpréteur.

## Premier lancement : erreur de liaison corrigible

Le binaire `b4579de9630180fe876027f0371bd8b05add0a739716f89becf0710c07951854`
avec l'APK `4c3bf3ea917f6a232526779ed61edb4676c1e5ac5a58ea8543e3e2e015cce155`
est sorti avec le code 139, sans sortie de contrôle. Le
[rapport négatif](../../downloads/shizuku-lab/collected-first/report.txt)
est conservé. Aucun workspace ni fichier sentinelle n'a été créé, et le
boot ID du téléphone est resté identique.

Deux analyses PC ont retrouvé une mauvaise construction du programme : le
NDK r29 sélectionnait un démarrage dynamique pour `-static-pie`, mais sans
interpréteur ELF chargé de ses relocations. Le même ELF reproduit le crash
sur PC avant `main`, après `getpid`, à l'adresse du garde interne Bionic
`page_size`. Ce résultat n'indique pas une fonction manquante du noyau Samsung.
La correction est une liaison PIE dynamique Android avec son `linker64`,
conservant ASLR, RELRO/NOW, pile non exécutable et le confinement du travail.

L'application a correctement refusé de déclarer le nettoyage prouvé en
l'absence de rapport natif. Après collecte des preuves et vérification de
l'absence de descendants, l'opérateur a arrêté uniquement ce UserService
de diagnostic (PID 2214). Aucun essai automatique n'a été déclenché.

## Dépendances Android corrigées avant le succès

Le [premier garde dynamique](../../downloads/shizuku-lab/collected-dynamic/report.txt)
est entré dans son code puis a refusé la préparation Landlock, avant Python,
avec nettoyage complet. Samsung refuse le `getattr` du dossier
`/linkerconfig`, mais autorise son fichier `ld.config.txt`. La règle vise
désormais directement ce fichier en lecture, au lieu du dossier. Le code
conserve aussi le vrai errno de `fstat`, précédemment remplacé par EPERM.

L'[essai suivant](../../downloads/shizuku-lab/collected-linker-file/report.txt)
a passé les trois tests et les six refus, construit et exécuté le paquet,
puis échoué sur le contrôle exact de stderr : Bionic y ajoutait des erreurs
de base de fuseaux horaires inaccessible. L'accès en lecture au seul fichier
officiel `/apex/com.android.tzdata/etc/tz/tzdata` corrige cette dépendance.
Le contenu attendu du test n'a pas été assoupli, et aucun message n'est filtré.
Les répertoires des essais échoués sont conservés séparément sur le téléphone
et leurs données ont été copiées sur le PC avant toute nouvelle exécution.

La collecte PC a ensuite été adaptée aux fins de ligne Windows : son exécution
locale du paquet produit `42\r\n`, normalisé en texte pour comparaison avec
`42\n`. Les octets Android, les hashes et stderr restent vérifiés exactement.
Cette correction de collecte n'a pas relancé le test sur le téléphone.

## Démarrage futur et limites du résultat

Le SDK est déjà intégré dans notre application de qualification. Il ne crée
pas à lui seul les droits ADB après un redémarrage Android. Shizuku 13.6
propose un démarrage automatique conditionnel, mais le chemin examiné modifie
aussi les réglages ADB et désactive l'expiration des autorisations. Ce mode
n'a pas été activé ; le réglage d'expiration est resté à sa valeur initiale
`null`. L'autorisation optionnelle `WRITE_SECURE_SETTINGS` automatiquement
accordée au gestionnaire a été retirée. Voir
[l'analyse sourcée](capabilities/05-shizuku.md).

Même si le projet fixe réussit, les commandes générales du modèle, toutes
les politiques demandées par Codex, les routes fichiers/terminal/sessions,
le partage de l'UID shell et le cycle de vie de production restent à traiter.
Le présent essai ne valide pas l'exécution d'ELF compilés dans le workspace,
ni une équivalence générale avec Bubblewrap. Les deux reboots antérieurs
restent inexpliqués ; le diagnostic GNU concerné reste suspendu.
