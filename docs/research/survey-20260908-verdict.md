# FoldGPT : recherche comparative et verdict de faisabilité

Revue du 8 septembre 2026. Trois sous-agents ont travaillé en parallèle sur
les ports du moteur, les hôtes Linux Android et un test du lancement applicatif.
Les documentations Android/Samsung/ARM et OpenAI ont été lues dans le navigateur
intégré ; les dépôts, fichiers de code et issues ont aussi été lus par le
connecteur GitHub. Il s'agit d'un inventaire large et ciblé, pas d'une prétention
à avoir lu tout Internet. Les résultats Android précédents sont séparés des
constructions et contrôles PC de cette revue.

## Verdict actuel

**Le développement Python depuis la vraie conversation sur le Fold est prouvé.
Une application entièrement native Android, autonome après redémarrage et
compatible avec les mises à jour officielles ne l'est pas encore.**

Les trois points doivent rester distincts :

1. **Exécution locale utile : oui, mesurée.** Le parcours r24/r25 utilise les vrais Bash/Python/rg
   Bionic, crée des fichiers, installe une dépendance, passe cinq tests et
   réexécute l'archive après fermeture/réouverture. Le terminal du modèle échange
   des entrées et reçoit l'interruption. Les commandes tournent sur le Fold.
2. **Lancement des composants sans Shizuku : deux cas réussis sur le Fold.**
   L'application diagnostic a lancé les vrais composants pipe/PTY depuis Zygote,
   sans Shizuku actif. Le lancement de production reste à raccorder, puis la
   reprise après reboot sans PC à qualifier.
3. **Tout Android natif avec l'interface officielle : pas démontré.** L'interface
   Electron Linux et le contrôleur GNU utilisent encore PRoot. PRoot n'est pas
   une VM ni une émulation du CPU ARM64, mais reste une couche de compatibilité.
   Aucun port Electron Android maintenu et prêt pour cette interface n'a été
   établi. Ce travail substantiel ne peut pas être présenté comme une finition.

**Il n'est donc pas justifié de fermer le projet comme impossible, ni de
promettre sa réussite complète.** Le point bwrap n'est plus l'unique obstacle :
le lancement autonome, les anciennes conversations, l'hôte de l'interface et
les mises à jour réelles restent des critères de fonctionnement.

Le Fold ne figurait pas dans ADB lors de la recherche initiale, confirmé par plusieurs
lectures, et aucune interface USB Android n'était recensée sur le PC. La cause
de cette absence n'est pas déduite. Le collecteur enregistre `unavailable` et
`newExecutionTestPassed=false` dans
`work/feasibility-survey-20260908/initial-connection/observation.json`.
Après reconnexion, l'APK diagnostic distincte a été installée et les deux cas
ont réussi : [preuves et limites](app-context-device-validation-20260908.md).
Le boot et les APK officiels sont inchangés ; aucun réglage n'a été modifié.
L'exécuteur de production était déjà indisponible avant cette intervention.

## Pourquoi Rust n'est pas la fonction manquante

Le moteur Codex est déjà écrit en Rust. Le port Android officiel du langage
et les adaptations des forks permettent de produire du code ARM64/Bionic.
Notre hôte Android utilise aussi Java et des composants natifs C/C++ ; chacun
répond à son interface existante. Réécrire tout cet hôte en Rust ne lui donne
pas des appels système ou des permissions supplémentaires.

Un processeur ARM64 exécute les instructions. L'ABI du système définit également
les conventions d'appel, le chargeur, la libc et les dépendances. Un ELF Linux
GNU ARM64 n'est donc pas automatiquement un programme Android/Bionic.
[NDK ABI](https://developer.android.com/ndk/guides/abis),
[ARM AAPCS64](https://github.com/ARM-software/abi-aa/blob/main/aapcs64/aapcs64.rst),
[sandbox Android](https://source.android.com/docs/security/app-sandbox).

La configuration récupérée sur le Fold le 6 septembre ne compile ni
`CONFIG_USER_NS` ni `CONFIG_PID_NS`. Le vrai
[Bubblewrap](https://github.com/containers/bubblewrap/blob/main/README.md)
utilise les namespaces du noyau et crée toujours un mount namespace.
Compiler un autre binaire bwrap, Rust ou C, ne recrée pas ces fonctions noyau.
Les autres mécanismes disponibles doivent avoir une implémentation et des
tests propres ; renvoyer artificiellement « succès » n'est pas une solution.

## Ce que les autres apportent réellement

| Piste étudiée | Ce que les sources établissent | Décision pour FoldGPT |
| --- | --- | --- |
| Local Desktop | Hôte Rust/NDK, Wayland/Smithay et Arch ARM64 sous PRoot ; démarrage sans Shizuku. Son `setup_fake_bwrap` supprime des options d'isolation puis exécute directement la commande. | Référence utile pour lancement, surfaces et reprise. Ne pas adopter le setup intégral ni son faux bwrap. Un changement de bureau ne termine pas notre exécuteur. |
| Termux et Termux:X11 | Processus et PTY depuis l'application ; serveur X11 NDK. Le correctif Samsung d24418e4 change le flavor et l'identité du processus visible. | Termux:X11 est déjà intégré. Tester la filiation Android de nos composants et mesurer les processus avant de modifier le service. Aucun abaissement du SDK ni sharedUserId importé. |
| DioNanos/codex-termux et wallentx | Vrai V8 Android dans les branches lues, adaptations ABI/PTY/chemins, archives avec empreintes. | Réemployer les deltas nécessaires au futur contrôleur Bionic. Le sélecteur DioNanos vérifié, identique à l'amont, aboutit sur Android à `SandboxType::None` ; le sandbox mémoire V8 n'isole pas les fichiers/processus des outils. |
| UserLAnd, Andronix, AnLinux | Environnements Linux principalement PRoot, avec recettes de packaging et distributions. | Confirment la famille d'hébergement déjà employée. Ne fournissent pas les namespaces manquants. |
| Asombi | Chargeur Rust utilisant notamment namespaces/chroot ; chemin Android PRoot. Certaines sondes comptent EPERM comme « disponible ». | Une primitive présente mais interdite n'est pas utilisable. Aucun mécanisme de remplacement établi pour le Fold. |
| Glibc Termux Pacman | Chargeur GNU direct et adaptations de bibliothèque, distincts d'une VM. Certaines adaptations simulent UID/GID ou retirent Landlock/pidfd. | Étudier uniquement des composants ciblés si nécessaires ; le paquet complet ne respecte pas nos contrats tel quel. |
| Winlator/Box64 | Wine et traduction x86 vers ARM. | Aucun bénéfice démontré pour notre client déjà ARM64 ; pas de migration retenue. |
| Node mobile, ponts web Codex | Intégration Node/JNI ou pont HTTP/JSON-RPC concrets. Node mobile lu reste en 18.20.4 ; les processus enfants ont leurs propres contraintes Android. | Source d'architecture. Une nouvelle UI WebView/Vue n'est pas l'interface officielle et ne peut pas la remplacer silencieusement. |
| Electron Android | Hello-world sur émulateur déclaré dans l'issue officielle 48761, fermée `not_planned` faute de moyens de maintenance. | Possibilité d'ingénierie, aucun port complet maintenu établi pour notre client. Ne pas promettre la parité ni appeler le langage seul une solution. |
| AVF/pKVM, terminal Linux virtualisé | Autre noyau dans une VM, sous réserve de disponibilité matérielle, système et API. | Hors contrainte sans VM. Un Pixel ne constitue pas une preuve de réussite du projet. |
| Jumelage OpenAI | Code amont expérimental réel ; le produit documenté connecte ChatGPT mobile à un hôte desktop macOS/Windows, via un relais. | Ce n'est pas une fonction documentée d'hôte Android local. Piste secondaire, aucun jumelage lancé. |

Sources détaillées, révisions, licences et limites de lecture :
[hôtes Linux](survey-20260908-linux-hosts.md),
[moteurs Rust/Android](survey-20260908-rust-engine.md),
[test applicatif](survey-20260908-app-context.md).

La même exigence s'applique à notre propre réalisation :
[NATIVE-AUDIT.md](../../NATIVE-AUDIT.md) documente un ancien shim
`libfake_userns` dans l'hôte GNU. Les essais des outils Bionic ne prouvent ni
son retrait de l'interface ni le confinement de Chromium. Les fichiers officiels
intacts et les protections Android conservées ne suffisent pas à qualifier
toutes les garanties annoncées par une couche de compatibilité.

Le parcours r25 testé utilise explicitement `ordinaryUid`/Full access et annonce
`sandboxType: none`. Il exécute sous l'UID de FoldGPT via la chaîne Shizuku/run-as
qualifiée ; ce n'est pas une preuve du contexte applicatif Zygote ni du profil
distinct `managed`. Les tests statiques
historiques de Landlock/broker ne qualifient pas tous les programmes dynamiques.

## Samsung, One UI, Android et mémoire

Le modèle matériel vérifié dans les traces est **SM-F971B / h8q**, SoC
**QTI SM8850**, Android 17/API 37, One UI 90000, noyau 6.12.58, pages 4K et
GPU Adreno 840 v2. Ce sont des observations datées du 6 septembre ; les lecteurs
ne doivent pas les remplacer par les caractéristiques d'un Fold7 ou d'un Pixel.

La [fiche Samsung SM-F971B](https://www.samsung.com/ae/business/smartphones/galaxy-z/galaxy-z-fold8-graphite-256gb-sm-f971bzkimea/)
relue confirme Fold 8, Snapdragon 8 Elite Gen 5 et One UI 9. Elle annonce 12 Go pour
256/512 Go de stockage et 16 Go pour 1 To. La variante commerciale ne suffit pas à
déduire la RAM exacte de l'appareil connecté ou une allocation utile à FoldGPT.

Les [changements Android 17](https://developer.android.com/about/versions/17/behavior-changes-all)
documentent un limiteur mémoire dépendant de la RAM et le motif de fermeture
`MemoryLimiter:AnonSwap`. Le collecteur préparé lit `/proc/meminfo`, les RSS/swap
des processus et `am memory-limiter status` ; il ne modifie aucune limite.
**Aucune hausse de 2 à 4 Go n'a été appliquée pendant cette étude.** Il faut lire
les valeurs effectives et la cause d'arrêt, pas choisir une allocation sur la
base de la seule mémoire commerciale.

Les issues communautaires
[Termux 5086](https://github.com/termux/termux-app/issues/5086),
[Termux 4824](https://github.com/termux/termux-app/issues/4824) et
[Termux:X11 1022](https://github.com/termux/termux-x11/issues/1022)
décrivent du classement CPU et des gels en arrière-plan sur certains Samsung.
Leurs commentaires ont été lus et sauvegardés sous `work/.../web/`.
Ils motivent des mesures de cgroup/cpuset et de reprise ; ce sont des témoignages
sur des appareils/versions différents, pas un diagnostic déjà prouvé du Fold 8.
Le [service au premier plan Android](https://developer.android.com/develop/background-work/services/fgs/service-types)
signale un travail en cours ; il n'accorde pas le contexte shell.

La documentation [Landlock amont](https://github.com/landlock-lsm/linux/blob/master/Documentation/userspace-api/landlock.rst)
a aussi été relue. L'ABI 6 historiquement mesurée sur le Fold permet des
restrictions héritées ; la synchronisation de tous les threads arrive en ABI 8,
les sockets UNIX par chemin en ABI 9 et UDP en ABI 10. Ne pas attribuer ces
versions récentes au noyau du téléphone ni copier un exemple best-effort qui
retirerait une garantie requise. Le choix des profils reste explicite.

Deux pages de forums Samsung ont retourné HTTP 400 et 431, et le sous-module
UserLAndLibrary n'a pas pu être consulté (404). Ces limites de lecture ne sont
pas interprétées comme une preuve d'absence de solution.

## Tests simples et ordre de décision

| Test | Résultat disponible | Ce qu'il décide |
| --- | --- | --- |
| Depuis la conversation : créer un projet Python, installer Packaging, tester et construire | Réussi sur r24/r25 ; cinq tests, fichier et archive indépendamment relus | Les outils et les fichiers peuvent réellement être locaux au Fold. |
| Entrée interactive et interruption depuis le modèle | Réussi r25, trois FDs tty, codes 23/130 ; neuf tests backend séparés | Le terminal du modèle fonctionne dans les cas qualifiés. Le panneau manuel n'est pas le blocage prioritaire. |
| Ouvrir une ancienne conversation | Échec reproduit : ancien cwd Linux hors racine native ; TOML valide | Défaut de migration de chemins à corriger en conservant historique/fichiers. Ce n'est pas une erreur de syntaxe de `config.toml`. |
| Lancer nos propriétaires pipe/PTY depuis un Service Android normal | **Deux cas réussis sur le Fold**, vrais fichiers/enfants, entrée, interruption et nettoyage vérifiés | La nécessité de Shizuku pour ces composants est réfutée sur ce Fold. Il reste à raccorder le propriétaire de production. |
| Ouvrir FoldGPT après redémarrage normal, sans préparation ADB/Shizuku | Non exécuté | Critère d'autonomie : reprendre le projet, demander un vrai changement, passer les tests et vérifier les fichiers. Aucun câble ne doit fournir le lancement. |
| Mettre à jour client officiel et FoldGPT puis reprendre le même projet | Non qualifié | Les fichiers officiels intacts au contrôle actuel ne garantissent pas le prochain cycle de mise à jour. |
| Même parcours avec contrôleur/interface entièrement Android | Non qualifié | Critère nécessaire à l'affirmation « tout natif Android ». La réussite du seul moteur Rust ne suffit pas. |

Le nouveau test n'est pas une simulation : les 89 ELF, 95 sources r25 et
2447 données Python sont relus dans l'APK diagnostic et vérifiés par empreinte.
Il lance le Python réel et les adaptateurs réels depuis Java/Zygote sous un
UID applicatif distinct. Il vérifie la filiation, les fichiers, sous-processus,
entrées, sorties, signal d'interruption et fermeture réelle. Le signal PTY du
diagnostic est `process/signal`; seul le reçu r25 établit l'essai clavier Ctrl+C.

Sources versionnées : [app-context-probe](../../tools/runtime/app-context-probe/README.md).
Candidat : `work/feasibility-survey-20260908/app-context/versioned-build-v1/foldgpt-app-context-probe.apk`,
SHA256 `325b0bcfc6ef951d5a4ad71f067b1369c0ae44eaa15d89b1b8149e2806cae41b`.
La compilation, signature, les contrôles de contenu et les deux cas Android
sont passés. Aucun garde du lancement r25 n'a été retiré.

La prochaine intervention utile est le raccordement applicatif, analysé dans
[le plan d'intégration](app-launch-integration-20260908.md). Le défaut des
anciens chemins dispose aussi d'une [voie de réparation par le protocole existant](legacy-path-repair-design-20260908.md).
Le succès du diagnostic ne démontre pas ces deux corrections ni un produit terminé.

## Documentation OpenAI confrontée au code

La [page Remote officielle](https://learn.chatgpt.com/docs/remote-connections),
ouverte après redirection de `developers.openai.com/codex/remote-connections`,
indique explicitement les hôtes desktop macOS/Windows et un démarrage du
jumelage dans l'application, pas dans le CLI ou l'extension IDE. Le code CLI
expérimental trouvé ne remplace pas cette limite produit documentée et ne
prouve pas qu'un moteur local Android peut être jumelé au client officiel.

L'objectif conserve les fichiers et outils sur le téléphone et les mises à
jour officielles. Le modèle OpenAI continue à nécessiter son service Internet ;
cela ne signifie pas un besoin de PC personnel. La recherche ne retient aucun
MCP/plugin pour remplacer cet objectif.

## Preuves de référence

- [R25 : résultats Android](r25-device-validation-20260908.md), y compris la
  suite générale Rust R5 encore en échec : 16933 réussites, 238 échecs, 2 timeouts,
  35 ignorés. La revue ciblée ne rend pas cette suite verte.
- [Diagnostic de l'ancienne conversation](legacy-config-localdesktop-20260908.md).
- [Contraintes natives mesurées](android-native-constraints-2026-09-06.md).
- [Alternatives de lancement et mises à jour](phone-only-options-20260908.md).
- [Critères de fin du projet](functional-milestones-20260908.md).

Les builds, clés de diagnostic et preuves privées restent dans le dossier du
projet. Le checkpoint de récupération v16 précédent reste inchangé ; la
présente livraison source ne se prétend pas un nouveau backup intégral.
