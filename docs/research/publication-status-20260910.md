# État de publication — 10 septembre 2026

## Décision proposée

Publier prochainement les sources sélectionnées du prototype et une démonstration
fidèle aux essais. Une publication de sources expérimentales n'exige pas la
qualification d'un APK destiné au grand public. Ne pas annoncer installation
en un clic, fiabilité multi-conversations, parité desktop ou inférence locale.

Les API GitHub confirment ce jour que `pironjulien/FoldGPT` et
`pironjulien/FoldGPT-workspace` sont tous deux privés. Le premier n'est donc pas
encore accessible aux lecteurs du futur post. La branche de travail contient
de nombreuses modifications non consolidées, dont celles du sous-module X11.

## État du téléphone constaté aujourd'hui

- L'APK installé a le SHA-256
  `9f1ae782d9910d5edb6003a63eb7724dc24d35d84d0f2d9ef5277f774bbba0d7`.
  Son inventaire contient le manifeste qualifié du paquet natif r45 et la
  méthode Java de nettoyage `reapOwnedProcesses`.
- Les états persistés du service et du propriétaire natif sont `ready`,
  `directNative=true`, sans erreur de préparation/nettoyage enregistrée.
  Le processus propriétaire correspondant est présent. Ce relevé ne constitue
  pas un test supplémentaire d'exécution ou de stabilité.
- La correction EACCES a rétabli la sélection du paquet natif et le raccordement
  du dossier de projets. Une nouvelle discussion a obtenu `OK` dans le tour
  précédent. Aucune exécution Python réussie n'a été confirmée sur cet APK dans
  ce tour précédent ; ce résultat ne remplace pas la revalidation des outils.
- `dumpsys activity settings` donne toujours `max_phantom_processes=32`.
  Aucun override n'est observé dans `device_config` ou le réglage global de
  surveillance interrogé.
- Au relevé de cet audit, `dumpsys activity processes` liste 22 processus enfants
  surveillés actifs au total, dont 21 pour FoldGPT. `ps` liste séparément
  24 processus sous l'UID de FoldGPT. Ces compteurs ne sont pas interchangeables.
  Le plafond est partagé ; dix places apparentes dans ce relevé ne sont pas
  une réservation pour l'application.

## Processus : ce qui reste ouvert

Les arrêts historiques `Trimming phantom processes` sont établis dans les
rapports précédents. Le chargement MCP différé et le déchargement de sessions
sont raccordés ; le nettoyage Java intervient lors de l'arrêt ou de la reprise.
Cela ne démontre pas la maîtrise du pic de processus de plusieurs conversations
qui utilisent effectivement leurs outils en même temps.

Le nettoyage Java sélectionne actuellement les processus par UID et ligne de
commande, puis envoie TERM/KILL. Son message `Reclaimed` compte les candidats ;
il n'atteste pas leur disparition. Sa qualification doit couvrir l'identité des
PID, les processus invisibles dans `/proc`, les vrais descendants de la session
et la préservation des conversations actives. Un PPID égal à 1 peut appartenir
à un auxiliaire légitime de la session courante ; ce seul fait ne prouve pas
une fuite.

La reprise r45 en 18,286 secondes documentée dans
[session-recovery.md](../session-recovery.md) reste une preuve de récupération
après le crash testé, pas la disparition de la contrainte Android.

## Minimum pour les sources et le post

1. Consolider les sources et patches actuels dans un instantané public
   reproductible, avec références X11 accessibles. Exclure profils, secrets,
   historiques privés, archives de récupération et composants propriétaires.
   Vérifier licences et notices du contenu effectivement publié.
2. Actualiser README, PUBLICATION et la procédure de construction. Le paquet
   natif sélectionné doit être explicite et vérifié dans l'APK : une commande
   Gradle incomplète ne doit plus produire silencieusement la régression EACCES.
   Les textes des 6–8 septembre contiennent des limites depuis levées : ils ne
   doivent pas être présentés comme le bilan actuel.
3. Revalider sur l'APK retenu une discussion avec création de fichier, commande
   locale, résultat relu et réouverture. Capturer une démonstration sans données
   personnelles. Indiquer précisément les limites de cette version.
4. Publier l'instantané sélectionné, vérifier son accès sans authentification,
   puis publier le fil X préparé dans `PRODUCT_POST_X.txt`.

## Exigences supplémentaires pour distribuer une bêta installable

- Mesurer les pics et la libération des processus avec plusieurs conversations
  actives et outils, puis arrêt, reprise, arrière-plan et pliage réels.
- Valider installation depuis un stockage neuf, connexion, reprise après reboot,
  mise à jour de l'hôte/runtime/client et conservation des données ; les essais
  sur une installation de développement existante ne les remplacent pas.
- Préparer APK signé, inventaire distribuable, sources/notices correspondantes
  et canal de mise à jour. Le client propriétaire reste obtenu séparément.

Les essais historiques Python, documents et contrôle Android sont décrits dans
[workspace-dependencies.md](../workspace-dependencies.md),
[android-tools.md](../android-tools.md) et les rapports r28/r45. Ils ne constituent
pas une requalification complète de l'APK corrigé aujourd'hui.
