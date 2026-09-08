# Reprise technique du 8 septembre 2026

**Téléphone emporté par Julien à09:40 environ. Travail PC uniquement jusqu'à
son retour.** La commande normale STOP_NATIVE_EXECUTOR a été reçue par notre
Activity avant débranchement (Status:ok). Le câble a été retiré avant la lecture
du statut final : aucun nettoyage/reaping de la session8507 n'est donc encore
revendiqué. Le snapshot `phone-departure-device` est incomplet et reste une
preuve de déconnexion, pas une fermeture validée. Ne pas lancer d'autres essais
Android en son absence. Julien autorise la poursuite locale et la préparation
de plusieurs options concrètes à tester à son retour.

Le dépôt de travail est **privé** : `pironjulien/FoldGPT-workspace`, branche
`codex/foldgpt-beta`. Commencer par [README.md](README.md) pour restaurer sources,
sous-modules, moteur séparé et données locales. Le dépôt public `FoldGPT` est un
ancien checkpoint ; il ne reçoit pas cette sauvegarde privée.

## État courant vérifié le 8 septembre à 09:25, heure de Paris

**Le projet ne permet pas encore de travailler depuis une conversation.**
Ne pas confondre la réussite des commandes natives isolées avec celle de
l'expérience complète. Le téléphone est actuellement en **r20/versionCode10,
paquet natif v8 et moteur GNU R5**. La première conversation réelle du projet
« Validation Python FoldGPT » s'est terminée en échec à 09:20.

| Étape | Résultat vérifié |
| --- | --- |
| Exécution native Python sur le Fold | PASS : script, trois unittest, construction et exécution du zipapp, résultat42, Android/aarch64/UID10412 |
| Démarrage ordinaire interface → moteur R5 | PASS : handshake215ms à09:13, wrapper normal conservant tous les arguments |
| Création d'un projet par le sélecteur de l'interface | PASS : « Validation Python FoldGPT », dossier source réellement enregistré |
| Commandes demandées dans la conversation | FAIL : `Bionic launch requires its complete portable sandbox context` |
| Écriture par apply_patch dans cette conversation | FAIL : `Failed to write file .../addition.py` |
| Fichiers effectivement créés par cette conversation | Zéro, inventaire Android indépendant à09:25 |
| Éditeur puis fermeture/reprise du projet créé | Pas encore validés, dépendants de la création réelle |

Le réglage existant de l'interface est **Accès complet**. Notre backend modèle
exige actuellement un contexte de politique managed ; le mode Full access lui
arrive sans ce contexte et il refuse avant lancement. La revue indépendante
retrouve le même refus dans le chemin apply_patch : le backend fichiers exige
aussi un contexte managed et l'erreur affichée masque celle du parseur. La
réponse RPC exacte n'a pas été capturée ; la chaîne source et le refus du parseur
sont vérifiés. Ne pas changer silencieusement
le mode ni fabriquer une politique restreinte pour présenter un succès.

La prise en charge générale reste aussi incomplète : le profil natif actuel
refuse notamment le réseau, le TTY et plusieurs opérations de fichiers
(rename/unlink/liens). Le refus Full access ne doit donc pas être présenté comme
le dernier défaut certain du produit. L'objectif de validation immédiat reste
le petit projet Python réel, puis éditeur et reprise.

Architecture exacte : les commandes Bash/Python sont natives Android/Bionic ;
l'interface et le contrôleur GNU restent dans PRoot. Aucune VM sur le téléphone.
Les fichiers officiels contrôlés avant/après installation R5 sont identiques.
La session native8507 est encore ouverte ; aucune fermeture de cette session
UI n'est revendiquée. Boot `348d453e-f4e5-40e0-8ef0-030f4d5e38af` inchangé.

Preuves locales figées sous
`work/root-artifacts-20260907/native-ui-validation-20260908/` :

- `r5-r20-conversation/completed-failure-report.json`, `completed-ui.json`,
  `runtime-at-failure.log`, `native-status-at-failure.json` ;
- `project-after-create/report.json` : zéro fichier ;
- `r5-r20-first-ui/report.json` : démarrage normal réussi ;
- `r20-native-results.json` : qualification native réussie ; la variante Bash
  garde un avertissement HOME/.bash_profile et sa fixture reste FAIL ;
- `r20-v8-independent-package-review.json` : paquet/signature/sources contrôlés.

APK r20 SHA256 :
`dd1a6beff3ea42f3a66f88f4fc254a169b1a12bcdc737834ca95b6e0372d112a`.
Moteur R5 : run ARM34192631216, commit
`8963acc8e961c0d34b068910b973cc6f9b9df3bc`, archive SHA256
`cb9c5774ecd365340531344b1e060d97fd3872715e1b8c4273dc818221e8549b`.
Bash production : run34196988639, double compilation identique, préfixe réel,
intégré dans r20. Les sources de préparation Bash sont poussées au commit
`1f327835efbe9f5a72331472d4390a242936d912`.

La suite Linux R5 `34192652057` est encore en cours, étape compilation/tests
ciblés au dernier contrôle live. L'ancienne suite complète `34190100825` a échoué
(237échecs et2timeouts) malgré ses tests ciblés réussis ; ses échecs ne sont pas
tous attribuables à l'environnement. Ne pas déclarer les vérifications globales
réussies. Le [complément v13](supplement-v13.md) est désormais publié,
retéléchargé et intégralement restauré : **13 157 fichiers et 1 169 fichiers
source revérifiés**, dont r20, R5 et Bash production. Il fixe le commit
`7a1d6cdfeb15a3e4defceca519f02f0d17060851`. Les prototypes Full access en cours
ne font pas partie de ce checkpoint de la version installée.

Prochaine action : implémenter le contrat upstream d'exécution directe sous
l'UID Android ordinaire, séparément du mode managed. L'absence de contexte est
légitime dans le protocole officiel ; la remplir artificiellement ne corrige
pas le problème. Les prototypes processus/nettoyage et fichiers/streams sont
en développement sur PC, sans sélection ni installation sur le Fold.
Qualifier les commandes et l'écriture via les mêmes appels que
l'interface, puis reprendre cette même conversation. Les finitions restent
hors priorité. Tous les fichiers de travail restent sous `C:\Dev\ChatgptFold`.

## Historique : r19/R4 et préparation R5 (remplacé par l'état ci-dessus)

Le parcours **conversation réelle → projet Python → éditeur → fermeture/reprise**
reste à qualifier. Ne pas le décrire comme terminé à partir des tests des canaux.

- **Installé : r19/versionCode9 et moteur GNU R4**, paquet natif v7.
  R4 est installé à côté du client officiel depuis le run ARM `34183702604`.
  Son archive SHA256 est
  `4c0e6df5d9a5bd425cdf34e0a92c18c9efa58dae616eb65eb2990f38306e501e`.
- La divergence URI `%3D`/`=` des chemins APK est corrigée, avec 97 comparaisons
  contre la vraie crate Rust. L'incrément versionCode renouvelle le service
  Shizuku par son mécanisme existant et évite son ancien nativeLibraryDir.
- **Cause du refus restant errno13 reproduite** : Rust reconfigure SO_PASSCRED
  sur les canaux config/host déjà activés par leur propriétaire. Android refuse
  cette écriture ; la lecture confirme1 avant et après. Rust vérifie désormais
  l'état déjà actif. L'activation reste obligatoire lorsqu'il vaut0, et les
  contrôles de chaque message restent intacts. Revue indépendante passée ;
  compilation ARM et tests du nouveau moteur en cours.
- Les qualifications Python complètes passent depuis le vrai contexte de
  l'application Android. Essai r19 `controller-link-8055df9e`, propriétaire
  22200 arrêté/reapé, wait0 et PID absent. Les fichiers officiels Linux et Android,
  le boot et les propriétés du téléphone sont inchangés après les diagnostics.
- **r19/versionCode9 installé et commandes natives qualifiées** : paquet v7,
  SHA256 APK `13db3dda291362c4c4658bb325714d1576bde07b7f1fac1a9c860565d5a32162`.
  Il ajoute la séparation du sous-dossier d'exécution et de la base de politique,
  sans modifier les permissions. Sources/ELF/signature et 22 tests FactoryTests
  Linux passent dans `34192631216`, dont les deux régressions workdir ; 126 tests
  Python au total, aucun skip. `controller-link-643c6a89` valide réellement sur
  le Fold W/app avec politique W, identité Android/ARM64/UID10412, résultat42 et
  trois refus d'accès attendus. La variante Bash `controller-link-062ed250`
  exécute aussi ce travail avec exit0, mais son test signale deux avertissements
  de profil sur stderr : conserver cette limite et son rapport distinct.
- Nouveau moteur : run ARM `34192631216`, commit
  `8963acc8e961c0d34b068910b973cc6f9b9df3bc`, patch
  `806558ded307f46b76a278c5c81131f1d90bf6a4f7f72b9f66b29416fa9357ea`.
  Ne l'installer qu'après le reçu du collecteur. La validation Linux précédente
  `34190100825` a passé ses tests ciblés et poursuit sa suite complète ; la
  validation du nouveau Rust est `34192652057`, actuellement en attente.
- Le wrapper de production est restauré après chaque diagnostic et vérifié.
  Aucun interposer de diagnostic ne constitue une correction installée.
- **GitHub v12 demeure la dernière récupération intégralement restaurée**.
  Elle contient r16, pas R4/r18/r19. Le complément v13 est en préparation.

Preuves de cette passe :
`work/root-artifacts-20260907/native-ui-validation-20260908/errno13-cause.md`,
`passcred-independent-review.md` et `after-errno-diagnosis-device`.
Les fichiers de travail restent sous `C:\Dev\ChatgptFold`.

## Historique : r16 et récupération v12

**Dernier contrôle, 8 septembre 06:17 : r16/versionCode7 installé et les quatre
commandes Python modèle passent sur le Fold**, essai `3cd6ad7f` : script `.py`
sortie42, trois unittest, construction zipapp, exécution du zipapp sortie42.
Les six cas humains passent aussi. Le test emploie les vrais canaux de production,
sans app-server ni conversation. Java confirme wait0/cleanup/reaping, PID25698
absent indépendamment ; boot, propriétés et quatre APK ChatGPT officiels identiques.
Preuves : `verification/native-model-python-cli-20260908/r16-pass`.
APK : `downloads/native-production-20260908/foldgpt-native-candidate-r16.apk`,
SHA256 `a46512293c30eb644a7abef502917c4eb68bae1c40fc6bace2e539ee671e18cd`.
Paquet figé `downloads/native-host-runner-20260908/production-package-v4`.
**Ne pas réinstaller r15. L'interface habituelle reste à qualifier.**
Le complément GitHub v12 conserve ce résultat et le commit `ceb9058` :
5 506 fichiers et 1 141 fichiers source téléchargés, restaurés et revérifiés.
Consulter [supplement-v12.md](supplement-v12.md) ; le binaire ARM R4 à venir
n'est pas inclus dans cette sauvegarde.

Python Linux corrigé PASS dans `34186068559`. R4 Linux valide353tests exec-server,
33tests injectés et le projet Python via app-server. Seules les deux fixtures
native_startup étaient refusées avant leur assertion, faute de parent0700.
Correction de ces fixtures uniquement, export
`322733dd1f62f1ebcf8781da13d24f7f98db63d76861aaf06eb03bb079408fc9`,
run Linux seul `34186637209`, commit `49f0ef697190216cef5d7f836a2096b17b77dc3d`.
La comparaison complète des deux arbres prouve que seule
`codex-rs/app-server/tests/native_startup.rs` diffère du moteur ARM R4 :
`verification/engine-r4-test-only-equivalence-20260908.json`.
Le moteur ARM R4 continue à compiler ; son collecteur écrit
`work/ci-results/34183702604/arm_engine-download/ready.json` à la fin.

**Historique du contrôle du 8 septembre 06:05 : r15 ne passait pas le lancement
direct d'un fichier Python côté modèle.** Essai `e3c8b2fe` : `python3 fichier.py`
retourne exit2/EPERM. Les trois autres commandes modèle passent : trois unittest,
construction zipapp et exécution42. Les six opérations humaines passent encore.
Les nouveaux appels utilisent le vrai canal exec, sans `-c` ni `runpy`.
Les deux reçus Java confirment wait0/cleanup/reaping ; PID23189 absent et
snapshots boot/propriétés/APK identiques avant/après. Preuve exacte conservée
dans `verification/native-model-python-cli-20260908/r15-failure`.
La correction ciblée FIOCLEX/FIONCLEX du profil modèle est désormais qualifiée
par r16 ci-dessus. Le moteur Rust R4 n'est pas modifié par cette correction native.

Historique du 8 septembre : **r15/versionCode6 était installé et le canal
humain v2 est qualifié sur le Fold**, essais `016fe324` puis `70cf3a99` après
35 secondes d'attente volontaire avant la connexion du contrôleur. Les six cas
réels passent : lecture, sauvegarde stdin de 2097408 octets et relecture exacte,
exécution Python, refus hors du projet et annulation des descendants. Java donne
waitStatus0 et cleanupComplete ; les propriétaires natifs18082 puis19050 sont
absents indépendamment. Boot, propriétés et quatre APK ChatGPT officiels inchangés.
Preuves exactes : `verification/native-host-production-20260908`.
APK : `downloads/native-production-20260908/foldgpt-native-candidate-r15.apk`,
SHA256 `d8f4ff35d0d06120d1ab004ce13e5f8a31e7a25b73258e8ef0cceea2a178fe7b`.
Payload : `downloads/native-host-runner-20260908/production-package-v3`.
Les anciennes tentatives sont conservées ; ne pas réinstaller r12/r13/r14.

Corrections établies : FIOCLEX/FIONCLEX pour Python dans le seul profil humain,
cwd '/' fixé par O_PATH (la sonde réelle prouve O_RDONLY=EACCES et fchdir=PASS),
délai de handshake commencé à la connexion réelle. Le mode natif attend le
contrôleur sous la durée de vie du service Android, qui conserve son arrêt.

**Moteur et interface encore à qualifier : projet non livré.** Le client officiel
commence par `-c features.code_mode_host=true app-server ...` ; l'ancien wrapper
omettait alors le bootstrap. La source corrigée lit FOLDGPT_NATIVE_BOOTSTRAP
dans le démarrage app-server après le vrai parseur CLI ; le wrapper conserve
tous les arguments. Ne pas installer ce wrapper avec un ancien moteur.
La garde Rust de socket accepte désormais l'adresse abstraite que Linux
attribue à SO_PASSCRED ; les credentials noyau restent vérifiés.

CI courante : `34183702604`, branche privée `codex/native-engine-ci-r4-20260908`,
commit `100844688340a16597b556641d93e42427760082`, patch moteur
`8b055f730e651c2bebac801373b92bf57bcc0e1d2701a4ce232f07e1d9f82a9e`.
La qualification native Python Linux est PASS ; tests Rust et ARM en cours.
R2 Linux avait 18 refus de socket erronés puis un disque plein ; R4 libère les
SDK inutilisés sur le seul runner jetable et conserve les cibles compilées.
Les anciens binaires R2/R3 ne contiennent pas ces corrections.

Le script `tools/runtime/install-native-engine-device.py` vérifie le nouveau
paquet, les deux reçus de fermeture, les bibliothèques GNU du Fold et les
fichiers officiels Linux. Il n'a pas encore installé le moteur R4. Le vrai projet
UI vide est `/data/user/0/app.foldgpt/files/projects/ui-python-caae3a83d156` ;
prompt sous `work/root-artifacts-20260907/native-ui-validation-20260908`.
Ne pas prendre une ancienne conversation hors de ce chemin pour le test natif.
PTY reste non sélectionné et non qualifié. Le complément GitHub v11 est publié,
retéléchargé et restauré : 5487 fichiers et 1105 fichiers source revérifiés.
Il conserve r15 et le commit `1eee8df66f43fb5af7caf965cd5b905db3660da4`, avec
les nouvelles preuves natives. Le futur moteur livré nécessitera son propre
complément. `just bazel-lock-update` Windows/Bazel9.0.0 est passé ; aucun
changement de MODULE.bazel.lock. `just fmt` est passé avant l'export R4.

**Qualification production Python réelle PASS, 04:28** : APK r12
`57b474f3f468e3c62470eef5e41da0385eaf2b45c944c06e2e0180b1ffaa4234`,
versionCode3, installé lors de ce test historique. Essai4748f4f6 via vraie Activity/Service Java → Shizuku
→ run-as → Bionic, contrôleur GNU avec vrais binds,3canaux authentifiés.
Création native des fichiers,3tests Python réussis, zipapp construit et exécuté
sortie42, octets recoupés sous GNU, UID10412/platform android/aarch64.
Java waitStatus0/cleanupComplete, bootstrap10018 absent indépendamment.
Boot/propriétés/APK officiel ChatGPT identiques au snapshot avant installation.
Preuves figées `verification/native-production-python-20260908`.
Le client laisse `nativeOwnerReaped:false` car seule la collecte Java indépendante
prouve le wait ; le rapport global associe correctement les deux observations.
**Cette qualification ne fait toujours pas intervenir l'app-server ni la
conversation/éditeur officiel : projet non livré.** Le sous-ensemble ci-dessous
est l'historique des corrections ; ne pas le prendre pour le blocage courant.

Nouveau run moteur CI34180154848, branche privée
`codex/native-engine-ci-r2-20260908`, commit0af61a1927eeee902a338817865619797743f1ca.
Erreur anyhow corrigée en passant la dépendance workspace existante de dev à
production, contrat OwnedProcessController inchangé. Export canonique
`f7e73d475ab9bcaaaedbbbf895213d270126ab946f97db15d76993ffd8a95869`.

Complément courant vers04:25 : le démarrage Java natif r10 a réussi dans l'essai
`b4bace27`, bootstrap4224, manifeste réel, acquisition des3canaux et handshake
ExecServer. Sa fermeture donne waitStatus0/cleanupComplete et PID4224 absent.
Le client a refusé son propre champ `workspaceRoot` attendu à tort dans le
canal config (`discoveryRoot` réel). Le client est corrigé, pas encore projet
Python réussi. Historique figé `verification/native-java-startup-20260908`.

Corrections Android réellement passées : dossier E0700 ; identité des préfixes
système Java `/data/data` et run-as `/data/user/0` via même device/inode et suffixe
privé exact ; autorisation officielle SDK Shizuku reçue ; attendre le callback
bindApplication avant getUid/permissions. Pas de modification C/Python pour cela.
Après mise à jour APK, le service Shizuku conservait sa bibliothèque périmée :
r12 augmente versionCode à3 et maintient le tag IPC stable pour faire retirer
l'ancien service par son destroy qui attend le nettoyage. En compilation.
Le pilote utilise désormais NativePreparationActivity debug/DUMP au premier
plan : le broadcast seul échouait au redémarrage à cause du refus Android FGS.
Le vrai service et backend de production restent les mêmes.

CI privée désormais réelle :116tests unittest +12probes noyau passent sans skip
sur Linux, run34179808002, commit e0eeb8a. Les builds moteur Linux/ARM ont relevé
`anyhow` absent des dépendances de production de host_v2_processes ; correction
en cours. Le moteur courant n'est toujours pas installé/validé depuis l'UI.

Point de reprise en cours, 8 septembre vers 03:50 : le candidat production r4
est installé (`4230175209e34cd3defebd12d61aadefa76cc3b17b01fb78fde64ac423252f34`).
Son premier PREPARE réel échoue avant création du propriétaire natif : Android
`Context.getDir(MODE_PRIVATE)` crée `app_foldgpt_exec` en0771, incompatible avec
notre contrat0700. Essai conservé `downloads/native-production-device-20260908/b3d1d1a7`.
Ne pas corriger le téléphone à la main : la correction du créateur Java est en
cours. Aucun lancement natif ni redémarrage dans cet essai. Le pilote est
`tools/runtime/qualify-production-device.py` ; il exige l'empreinte APK installée
et garde les réponses brutes Java pour vérifier les vrais wait/cleanup.

Les tests du démarrage après ajout de `parentEnvironment` passent désormais
12/12 sans skip sur le Fold. Preuves supplémentaires figées sous
`verification/native-startup-parent-environment-20260908`. L'ancien résultat
11/11 ci-dessous demeure une étape historique. Compilation actuelle du moteur
et tâche réelle depuis l'interface toujours non validées ; CI privée en
préparation pendant que WSL reste indisponible.

Le 8 septembre, la chaîne **UserService Shizuku → run-as app.foldgpt → Bionic**
a réussi sur le Fold avec UID/GID10412, quatre canaux exacts, vrai waitpid0,
aucun des deux processus restant, boot et APK officiels inchangés. Preuves
versionnées : `verification/runas-identity-20260908`. Cette phase ne prouve pas
les primitives du superviseur ni l'interface.

Le premier essai du broker sous cette identité a ensuite démarré le vrai
superviseur et son worker, mais le worker figé vérifiait encore UID2000 avant
ses douze probes. Il a donc refusé à `required-enforcement`, code70, sans
exécuter ces probes. Nettoyage natif et Java complet ; bootstrap17661,
superviseur17667 et UserService17538 indépendamment absents. Aucun redémarrage
et APK FoldGPT/ChatGPT inchangés. Conserver l'échec dans
`downloads/runas-broker-v1` ; ne jamais rejouer `.RUN_BROKER_V1`.

La qualification V2 séparée a réussi ses **douze primitives réelles sur le
Fold**, sous UID/GID10412. Son worker conserve tous les contrôles, avec identité
attendue compilée depuis le vrai PackageManager et recoupée avant lancement.
Le superviseur et le worker terminent avec code0, nettoyage complet ; les PID
20535, 20540 et 20454 sont indépendamment absents. Boot, APK FoldGPT/ChatGPT et
propriétés de sécurité inchangés. Preuves scellées :
`verification/runas-broker-20260908` (11 fichiers, manifeste SHA256).
Nouvelle base `runas-native-v2`, APK `app.foldgpt.runasbrokerqualification.v2`,
SHA256 `61ae60536ee44142d917a941d643642ff1cf4f9d4ac03a9ffb6349d502cf736e`.
**Ne jamais rejouer RUN_BROKER_V2 ni effacer son marker.** V1 reste conservé.
Le partage des chemins et le parcours complet depuis l'interface restent à
qualifier ; le succès du broker ne les remplace pas.

Mesures supplémentaires du 8 septembre : les **11 tests des fichiers et sockets
de démarrage passent sur le vrai Python Bionic du Fold** (UID10412), par
ADB/run-as sans superviseur. Android refuse de créer le hardlink du test ; ce
refus système est consigné séparément et ne prouve pas notre admission d'un
hardlink existant. Le partage Bionic/GNU sous les vrais flags PRoot passe aussi :
mêmes device/inode, octets dans les deux sens, rename et flock bidirectionnel.
Le contrôleur conserve son UID libc10410 et son vrai UID noyau10412. Le test
confirme aussi qu'un écrivain sans lease peut muter ; la coordination des
écritures humaines reste à raccorder. Aucun superviseur n'est lancé dans PRoot.
Preuves : `verification/native-startup-and-shared-paths-20260908`.
Ces mesures ADB ne sont pas encore le lancement Java complet ni l'interface.

Le CLI Python et le lanceur C de production sont maintenant compilés avec le
NDK Windows, sous `downloads/native-production-20260908`. Préfixe natif :
`files/native-runtime-v1/python`, avec86aliases dont python/python3/bash/sh.
Le C admission-r2 émet les vrais enregistrements Java setup_failed/closed70
avant tout enfant s'il refuse. Le packaging Java est en vérification ; ne pas
installer les candidats r1/r2 incomplets. La compilation moteur WSL28509 est
toujours non terminale et les nouvelles commandes WSL ne répondent pas ; une
demande d'interruption/reprise limitée est en attente auprès de Julien.

Les sources du point d'entrée **de production**, du client UI fichiers et de
leur acquisition native sont désormais écrites dans le moteur séparé ; elles
ne sont pas encore compilées/qualifiées. Les tests Rust complets sont encore
en compilation, avec une erreur déjà corrigée dans le sample Config et des
linkers WSL toujours vivants. Ne pas annoncer le raccordement livré à partir
de la seule présence de ces sources.

Le test public `thread/start` puis `turn/start` utilise le vrai moteur Rust,
la fabrique Python/native, le canal de configuration authentifié et six vrais
processus supervisés. Il crée le projet, observe deux tests en échec sur trois,
corrige 41 en 42, réussit les trois tests, construit le zipapp et l'exécute avec
`42`. Le refus de lecture privée est relié à la vraie acquisition native avec
errno13 ; le patch privé est refusé avant mutation. Les six superviseurs et
le propriétaire terminent avec nettoyage complet. Seules les réponses du
modèle sont une fixture SSE déterministe : aucune inférence cloud ni interface
Android n'est qualifiée par cet essai.

Preuve locale : `work/root-artifacts-20260907/native-app-server/native-app-server-1uzqJ1`,
run nextest `9bb38527-42b7-445b-95b5-444f5ed94c52`. Le sixième processus est un
vrai `command/exec` public, qui exécute le zipapp avec sortie42 et code0 en
conservant la politique native. Le résultat v8 antérieur est conservé.
Snapshot Python/helpers v3 :
`downloads/native-app-server-host-v3-20260908`. Les échecs précédents restent
conservés. Le dernier import Python échouait à cause d'une restriction indue
sur le listing du parent d'un dossier refusé ; cette cause est corrigée sans
accorder l'accès au dossier privé. 34 tests filesystem et18 tests natifs passent
sous UID distinct du compilateur ; deux cas de shim optionnel non fournis sont
explicitement ignorés. Les réglages Windows inactifs restent exactement transmis.

Le raccordement `command/exec` à l'exécuteur sélectionné est maintenant écrit
et qualifié sur PC (10 tests gestionnaire,5 tests publics,22 régressions). Sa
preuve additionnelle avec la vraie fabrique native passe également (v9).
Les droits de l'éditeur ont un composant Python et un canal distincts
qualifiés30/30 ; le client Rust et son branchement restent à faire.
L'éditeur officiel Linux lit les fichiers via
`process/spawn` : raccorder seulement `fs/readFile` ne suffit pas.

**Le projet n'est pas livré.** Le test courant partage réellement les chemins
sur PC ; `ExecutorOnly` reste fermé. Les changements de contexte dynamiques,
skills, commandes humaines, EOF/PTY, surveillance et lancement Android exigent
encore leur raccordement. Le prochain résultat attendu demeure l'utilisation
réelle depuis l'interface du Fold, pas un remplacement par une démonstration PC.

## Acquis antérieur : canal natif et configuration entre deux UID prouvés sur PC

Le [canal privé](../tools/executor/native-bootstrap-channel.md) relie maintenant
le Rust du moteur à l'autorité Python/native. Les [preuves exactes](verification/native-bootstrap-channel-20260907/manifest.json)
conservent 17 tests Rust, 108 exécutions de régression Python/native et le
[rapport entre deux UID](verification/native-bootstrap-channel-20260907/isolation/report.json).
Le contrôleur UID1000 reçoit un vrai `PermissionDenied` en accès direct au
projet UID65534, puis lit les 70 000 octets attendus et la configuration projet
via le canal. Le vrai chargeur borné conserve la provenance `Project` et le
modèle attendu. Les refus restent des refus ; les deux processus terminent
avec code0, sans helper survivant ni quarantaine.

Le dernier export du moteur est un checkpoint de développement qui inclut
ConfigBuilder/rôles (55 tests), AGENTS (47), permissions/reprise (10),
command/exec (37) et la preuve app-server native v9. `just fix` ciblé et
`just fmt` global sont terminés. Patch vérifié sur la base exacte, SHA256
`6facc6ae7d2eebc91236b0b1d508ad02ce57c8d74b44716665e92885d33d32ca`.
La suite Rust complète est en cours. Son premier lancement a révélé la
dépendance de compilation PC libcap-dev manquante ; elle est installée dans
WSL Ubuntu-24.04. Aucun test n'a été supprimé pour contourner cet échec.
`ExecutorOnly` reste fermé. Aucune tâche complète depuis l'interface n'est
encore validée, et le canal n'est pas encore déployé sur Android.

La piste UserService Shizuku → `run-as app.foldgpt` est en qualification :
l'identité app existe, mais la chaîne complète, les primitives Bionic et le
partage réel des fichiers avec le contrôleur restent à démontrer. Voir
`work/root-artifacts-20260907/run-as-shared-native-audit.md`. Cette voie vise
uniquement notre application debug ; elle ne modifie pas l'application officielle.

Le moteur courant se trouve sous `C:\Dev\ChatgptFold\work\worktrees\FoldgptEngine`.
Les anciens chemins `C:\Dev\FoldgptEngine` dans les preuves sont historiques.
Le lien Git du worktree est relatif et vérifié sous Windows et WSL. Les logs
locaux sont sous `work/root-artifacts-20260907` ; le snapshot complet du canal
est sous `downloads/native-bootstrap-channel-20260907`.

## Acquis téléphone : projet Python natif V2 réussi, 7 septembre vers 21:07

Le [rapport V2](../docs/research/native-runtime-v2-device-result-2026-09-07.md)
et ses [preuves exactes](verification/native-runtime-v2-20260907/manifest.json)
conservent création/modification du projet, trois tests, zipapp construit et
exécuté, flux binaires, environnement enfant vide et refus réels. Les 20
contrôles indépendants passent. Nettoyage natif/JNI complet, propriétaires 2636
et 2676 absents ; boot/APK/fixture inchangés, aucun redémarrage pendant l'essai.

La correction RUNPATH fonctionne sur le Fold. Package
`app.foldgpt.runtimequalification.v2`, base
`/data/local/tmp/foldgpt-bionic-runtime-qualification-v2`, gel `qKM94iHA`.
APK vérifié : `downloads/runtime-qualification/apk-v2-independent/runtimequalification-debug.apk`,
SHA256 `8572ecc3ed975e6eb8dc98e1df5247931e5354aa6dd737f400c4e7c699674b2c`.
Action `.RUNTIME_RUN_FIXED_V2` consommée : ne pas rejouer ni effacer marker.

Poursuivre le raccordement des chemins/autorités et du lancement du moteur à
l'interface habituelle. Aucun succès ordinaire UI.
Le maintien éveillé USB reste activé durant la session active.

Les nouveaux binaires, stages et preuves sont également publiés dans le
complément privé v9 : 8 958 fichiers retéléchargés, authentifiés et vérifiés
après extraction. Voir [la procédure](README.md#complément-v9--python-natif-v2-réussi-sur-le-fold)
et [le rapport exact](verification/github-supplement-v9-restoration.json).

## Historique : Python runtime V1 échoue au chargement, 7 septembre vers 20:49

Le [rapport runtime V1](../docs/research/native-runtime-v1-device-result-2026-09-07.md)
et ses [preuves exactes](verification/native-runtime-v1-20260907/manifest.json)
conservent le test réel : Bash démarre, puis le chargement de `libpython3.14.so`
échoue. Nettoyage natif/JNI complet, propriétaires absents, boot/APK/fixture
inchangés. L'action V1 est consommée : ne pas la rejouer ni effacer son marker.

La correction candidate ajoute au RUNPATH le vrai préfixe des bibliothèques.
Le CLI V2 est compilé sous `downloads/runtime-qualification/python-cli-v2`,
SHA256 `b0709f801f95739b1a6988d51f22d8df1373316595ce19df8ce329d5c84628f2`.
La revue et le packaging V2 séparé sont en cours ; aucun résultat Android V2.
Le bootstrap app-server passe six nouveaux tests réels et29 régressions API sur
PC. Il est exporté dans le patch moteur. Les couches projet/autorités restent à
raccorder, et `ExecutorOnly` reste refusé jusqu'à leur preuve réelle.

Priorité inchangée : un projet Python créé et testé depuis l'interface habituelle.
Le maintien éveillé USB reste activé pendant la session de travail.

## Historique : V12 réussit sur le Fold, 7 septembre vers 19:49

La qualification fixe Shizuku/Bionic V12 réussit, avec les 24 vérifications
indépendantes, nettoyage réel et boot/APK/fixture inchangés. Lire le
[rapport V12](../docs/research/native-v12-device-result-2026-09-07.md) et les
[preuves suivies](verification/native-v12-20260907/manifest.json).
L'action V12 a été consommée : conserver son marker et ne pas la rejouer.

Le projet Python complet passe sur PC avec Bash natif, création/modification,
trois tests et zipapp. La prochaine identité séparée est
`app.foldgpt.runtimequalification.v1`, base
`/data/local/tmp/foldgpt-bionic-runtime-qualification-v1`. Avant son déploiement,
la course annulation/expiration du canal SOCK_SEQPACKET est maintenant corrigée
et vérifiée : six tests de synchronisation et cinq tests du projet passent sur
le nouveau gel `N0kMFS8z`, avec les contrôles canoniques. Conserver le build V12
`PHREPY0u` intact. La fixture runtime-v1 est créée et vérifiée sur le téléphone ;
son worker n'est pas encore lancé. Lire le
[contrat et les preuves PC](../tools/executor/bionic-supervisor/runtime_qualification.md).

L'incrément de métadonnées/shell du moteur passe 41 tests ciblés et une
intégration modèle/commande/apply-patch réelle sur PC. Le patch moteur exporté
inclut ce résultat. L'injection app-server interne est l'étape suivante ; les
accès `ExecutorOnly` restent refusés jusqu'à leur raccordement réel.

Les commandes ordinaires depuis l'interface ne sont pas encore démontrées.
Le moteur auxiliaire et ses accès projet/autorités restent à raccorder selon
l'audit du contrôleur. La priorité reste ce fonctionnement, finitions suspendues.

## Historique : résultat V11, 7 septembre vers 19:03

Priorité confirmée par Julien vers 19:36 : démontrer le fonctionnement réel
du petit projet Python depuis l'interface avant toute finition. L'enquête sur
les points noirs est suspendue : corruption capturée aujourd'hui malgré les
bibliothèques foldgpt5 effectivement mappées. Aucun correctif GPU nouveau ni
changement de pilote n'a été appliqué. Les captures privées et mesures sont
dans `downloads/menu-points-20260907`; les nouvelles sondes sous `tools/gpu`
sont des préparations non validées sur l'appareil, pas une résolution.

Julien a repris le travail et reconnecté le Fold. Le maintien éveillé USB est
activé et vérifié sans entrée injectée ; conserver ce réglage pendant la session
active et rétablir sa valeur initiale0 à la fin, conformément au
[rapport courant](../docs/research/native-v11-device-result-2026-09-07.md).

L'autorisation Shizuku officielle et le préflight V11 passent. L'unique essai
natif a lancé son processus, qui échoue au démarrage Bionic avec le code127 :
`unable to stat either "/proc/self/exe" or "kernel-qualification"`.
**La qualification n'est pas réussie** et aucun nouveau lancement V11 n'est
admis. Le nettoyage natif et JNI est réel et complet, sans quarantaine V11.
Le boot, la fixture, les APK et les indicateurs d'intégrité restent inchangés.
Les preuves V10 restent conservées indépendamment. Lire le rapport et ses
[preuves exactes](verification/native-v11-20260907/manifest.json) avant la suite.

Le correctif des métadonnées de l'exécutable passe désormais sur PC dans le
build `foldgpt-bionic-supervisor-PHREPY0u`, avec comparaison au runner précédent
et au noyau réel, y compris depuis un pthread. Les sources et preuves sont
suivies dans Git. Aucun nouvel APK n'est empaqueté ni installé. La résolution
`realpath` Bionic et l'effet de son repli dans le chargeur restent à établir ;
ne pas considérer l'ajout d'`O_PATH` comme une correction, car l'injection de
ce type de FD est refusée par le noyau. Lire les limites du rapport courant.
Les mécanismes du worker et les commandes ordinaires restent à valider ;
ne pas réactiver l'ancien diagnostic GNU/PRoot.
La [comparaison statique ARM64](../docs/research/native-engine-arm64-library-compatibility-2026-09-07.md)
a également été terminée sur PC ; elle ne prouve pas le chargement Android.

## Historique de clôture à la demande de Julien, 7 septembre vers 07:16

Julien part au travail et a demandé d'arrêter les essais, de tout consigner et
de finaliser la sauvegarde pour reprendre sur l'autre PC. Aucun nouvel essai
sur le Fold ne doit être déduit de cette clôture. La session de nuit est close ;
**le projet et les commandes ordinaires depuis l'interface restent inachevés**.

Le moteur auxiliaire GNU ARM64 et son compagnon ont réellement compilé en
release, sortie 0, en 18 min 08 s. Le compagnon a exécuté `text(6 * 7)` donnant
42 sur PC, puis fermé la session et quitté avec 0. Lire le
[rapport du build ARM64](../docs/research/native-engine-arm64-build-2026-09-07.md)
pour l'état final des autres vérifications ; aucune exécution de ce moteur sur
le Fold n'est établie. Les sources du build et celles restaurées par Git ont
le même contenu, avec des différences de matérialisation Windows documentées.

Le dernier contrôle mémoire en lecture seule, à 07:00, mesure 10,83 Gio utilisables
par Android, 3,49 Gio disponibles à cet instant et 695,74 Mio PSS pour les 23
processus de l'UID FoldGPT. Voir le
[rapport mémoire](verification/android-memory-20260907.json) et ses limites.
Il ne démontre aucun plafond global de 2 Gio pour FoldGPT.

Des copies exactes de cinq bibliothèques GNU du téléphone ont été collectées
en lecture seule dans `downloads/engine-arm64-device-libs-20260907` pour une
future comparaison des exigences ELF. Cette comparaison n'a pas été effectuée
avant l'arrêt ; aucune bibliothèque ni commande GNU n'a été exécutée sur le
téléphone pour cette collecte.

Pour reprendre : restaurer le clone et les compléments avec `recovery/README.md`,
puis lire le point V11 ci-dessous et l'audit des accès du contrôleur. Le premier
verrou téléphone reste son déverrouillage normal et l'autorisation officielle
Shizuku. Préserver V10, les fixtures et toutes les preuves existantes.

La clôture est sauvegardée dans le complément privé v8 : 7 169 fichiers
retéléchargés, authentifiés et vérifiés après extraction. Les 27 éléments de
la release correspondent à leurs tailles et empreintes. Les sources et cette
reprise sont sur la branche `codex/foldgpt-beta`. Le build ARM64 et ses entrées
exactes sont sous `downloads/engine-gnu-arm64-20260907` après restauration.

## Historique avant reprise : V11 attendait l'autorisation Shizuku

Le correctif des chemins runtime passe sur PC ; le superviseur figé courant
est `foldgpt-bionic-supervisor-KvSGBnzP`. L'APK séparé
`app.foldgpt.kernelqualification.v11` est installé, son runtime V3 vérifié et
la demande officielle Shizuku attend derrière le verrouillage du Fold.
**Aucune commande native V11 n'est lancée.** Le V10 reste intact en quarantaine.

Lire le [résultat V11](../docs/research/native-v11-isolated-preparation-2026-09-07.md)
et le [plan de fixture indépendante](../docs/research/native-independent-fixture-plan-2026-09-07.md).
Après déverrouillage et autorisation normale, contrôler `authorization.json`,
puis exécuter le préflight V11 avant l'unique action `KERNEL_RUN_FIXED_V11`.
Utiliser explicitement package V11, base
`/data/local/tmp/foldgpt-bionic-supervisor-qualification-v3` et report-version11.
Ne pas utiliser les commandes historiques V2 ci-dessous pour ce nouvel essai.

APK : `tools/executor/shizuku-service/build/qualification-v11-independent/qualification-debug.apk`.
SHA256 `1f8609c9a837d6923a464dda0a94153c874d6eaa5bda18cc7cf1d93245cdffd9`.
Stage : `tools/executor/shizuku-service/build/qualification-stage-v11`.
Les journaux `pc-v11-*`, `fixture-v11`, `python-v11` et
`v11-awaiting-authorization` sont dans `downloads/native-kernel-trial`.

## Résultats réellement obtenus

- Sur le Fold, l'essai fixe Shizuku/Bionic a créé et modifié un projet Python,
  passé trois tests et construit/exécuté un zipapp donnant 42. Les flux, refus,
  nettoyage et identité du runtime sont vérifiés indépendamment. Voir le
  [rapport téléphone](../docs/research/shizuku-bionic-trial-2026-09-07.md).
- Les commandes ordinaires depuis l'interface ne sont **pas encore reliées** à
  cet exécuteur. L'ancien chemin peut donc encore afficher l'erreur Bubblewrap.
- Le transport Shizuku est inclus dans notre APK, avec un point de préparation
  explicite et inactif, des entrées d'APK contrôlées et une terminaison qui
  conserve les propriétaires tant que le nettoyage n'est pas établi.
- Le shim Bionic `chdir` est compilé, testé sur PC et empaqueté dans l'APK.
  L'APK `c9a83886ebdfeba7f28ecbc37a383252cc91ad6e5c3ad3dc7189cc81e35694a1`
  est signé avec l'identité existante et **n'a pas été installé** sur le Fold.
- Le superviseur natif corrigé `8Kd8xQRE` passe 19 tests de processus réels,
  deux tests noyau directs et une qualification main/pthread sur PC nonroot.
  Sa lecture de dossiers par threads et son attente du superviseur ont été
  corrigées après revue indépendante. Les anciens builds ZBbervqT/UwX0Qj9H
  précèdent ces corrections et ne doivent pas servir au prochain essai.
- Le moteur séparé possède une injection d'environnement véritablement local et
  un flux de processus borné utilisable depuis un backend externe. Les tests
  ciblés passent avec vrais processus et octets. Trois échecs de la suite large
  sont également reproduits sur la base amont intacte : aucune suite complète
  verte n'est revendiquée. Voir `FOLDGPT-INTEGRATION.md` après restauration.
- Le nouveau `ExecServerLocalRuntime` a ensuite relié le client Rust au vrai
  serveur Python et au superviseur C `8Kd8xQRE` sur PC : commandes, cwd/env,
  stdin binaire, stdout/stderr/EOF, exit 23, opérations fichiers et refus avant
  mutation passent. Une coupure ferme l'admission sans rejeu ni faux événement
  de terminaison ; le nettoyage est constaté séparément côté natif. Les 27
  régressions ciblées et Clippy passent. Les [preuves de ce test réel](verification/engine-native-runtime/tests.txt)
  sont conservées dans Git. Cela ne sélectionne aucun exécuteur sur Android.

## Historique V10 et dépendances de l'intégration

**État V10 conservé, distinct du V11 courant décrit en tête.** Le démarrage
stdio dépasse le refus de socket. Le statut authentifié du service PID11821
confirme `factory_construct`, `PermissionError`, errno13, refus de
`/linkerconfig`. Le bootstrap PID11978 reste vivant ; son nettoyage n'est pas
établi. `evidence.json` est vide, `broker/process-session.json` et
`files/kernel-v6/attempt-started` restent en place. Ne pas réinstaller, tuer
l'ancien propriétaire, effacer le marqueur ou rejouer cette fixture.

L'APK figé est `tools/executor/shizuku-lab/build/kernel-v10-stdio/app-debug.apk`,
SHA-256 `46049fd8d2f381c2680023c12005a4d57cf4c9a51c829a447eb88642e6b3a6a4`.
Le stage est `kernel-stage-v10`. Lire le
[rapport v10 et la prochaine correction](../docs/research/native-v10-retained-session-2026-09-07.md).
La vérification des chemins runtime a depuis été corrigée et préparée dans V11,
sans retirer le contrôle du chevauchement avec le workspace. Les mécanismes
noyau du worker restent non mesurés. Les étapes v6 à v9 ci-dessous sont
historiques et ne doivent pas être rejouées après la quarantaine v10.

1. Le laboratoire autorisé `app.foldgpt.shizukuprobe` est passé au v9. V6 a
   réellement lancé le bootstrap UID2000, sorti70 avant `ready` et avant le
   worker, avec attente JNI et nettoyage complets. Les rapports de refus v7/v8
   ont été produits automatiquement lors des mises à jour, par restauration
   de l'ancien Intent **avant le restaging des alias**. Ils ne prouvent pas de
   nouveaux essais explicites après ce restaging. Les dates conservées dans
   `downloads/native-kernel-trial/lab-v8-inspection/report-times.txt` établissent
   cette distinction. Le préflight v8 après restaging passe ; son premier refus
   identifiait un alias Python pointant vers l'ancien APK.
   V9 refuse réellement l'ancien `KERNEL_RUN_FIXED` restauré, sans créer
   `attempt-started` : voir `lab-v9-inspection/inherited-intent-refusal.json`
   et `inherited-intent-directory.txt` sous le même dossier de preuves.
   Son préflight passe également, sans lancement natif. Seule l'action explicite
   `KERNEL_RUN_FIXED_V9` peut réserver l'essai, dans `files/kernel-v5`, avec le
   service tag/version5. Cet essai explicite a ensuite réellement atteint le
   bootstrap : `broker_open` échoue avec `PermissionError`, errno13, sur le
   `bind()` AF_UNIX de `private_exec_broker.py:93`, avant tout worker. Le bootstrap
   a été attendu et nettoyé (`waitStatus=17920`, `bootstrapReaped` et
   `cleanupComplete` vrais, sans owner retenu ni quarantaine). La collecte
   `lab-v9-cleanup-inspection` constate PID9798 absent, broker.lock seul, fixture,
   boot, indicateurs et APK inchangés. Le collecteur reste `success:false` faute
   de preuve native. Résoudre ce refus de bind avant de qualifier le noyau.
   Conserver toutes les réservations et preuves v2/v3/v4/v5. Voir le
   [rapport actuel](../docs/research/native-kernel-qualification-2026-09-07.md)
   et la [procédure v9](../tools/executor/shizuku-lab/ADMISSION-DIAGNOSTIC.md).
   Recalculer les 81 alias contre le vrai `nativeLibraryDir` après chaque
   installation. Le libellé RPC `preflight_v4` est historique ; il ne désigne
   pas la version installée. Ne pas réutiliser l'Activity après un timeout :
   `finished` peut être fixé par le délai avant la fin du worker Java et ne
   constitue pas une preuve de fin des opérations ou du nettoyage natif.
2. Après résolution de ce démarrage, qualifier `/proc/TID/mem`, `pidfd_getfd` et les mêmes accès depuis un thread
   secondaire dans le **véritable UserService Shizuku**. La
   [qualification minimale](../tools/executor/bionic-supervisor/qualification.md)
   décrit la fixture vierge, l'unique requête, les empreintes, les résultats
   attendus et le nettoyage. Les preuves PC ne constituent pas des preuves
   Android et ne doivent pas être rebaptisées.
3. Relier au service Android la liaison moteur/ExecServer maintenant prouvée sur
   PC. Le transport doit conserver politiques, flux, erreurs et ownership. Le runtime reste
   local (`is_remote=false`) ; les chemins invisibles au contrôleur sont
   actuellement refusés avant les routes qui supposent encore un accès direct.
   L'[audit du contrôleur](../docs/research/native-executor-controller-path-audit-2026-09-07.md)
   détaille les routes encore directes, leurs autorités et les preuves nécessaires.
   Retirer le refus `ExecutorOnly` seul serait incorrect.
4. Compléter les opérations de fichiers/processus nécessaires. Le superviseur
   refuse encore notamment suppression/renommage/liens, exécution de fichiers
   compilés dans le projet, TTY et réseau. Les quotas actuels sont des limites
   de processus/UID, pas une limite mémoire agrégée d'un workspace.
5. Prouver depuis l'interface ordinaire une vraie demande de création, tests et
   construction du petit projet Python choisi par Julien. Cette preuve manque.

Le travail Rust peut continuer entre deux exports : vérifier le patch actuel
dans `recovery/engine/manifest.json`. Exporter et vérifier un nouveau point
stable avant de changer de PC ; ne pas remplacer les sources Git par leur
version plus ancienne dans l'archive.

## Contraintes conservées

- Aucun root, déverrouillage, changement de noyau/SELinux ou action Knox.
- Aucun retour à une VM sur le téléphone. WSL sert uniquement au build PC.
- Client officiel et ses fichiers conservés, mises à jour officielles normales.
- Aucun succès simulé, politique désactivée ou fonctionnalité omise présentée
  comme terminée ; MCP/plugin restent le dernier recours demandé par Julien.
- Ne pas relancer l'ancien diagnostic GNU/PRoot/ptrace/seccomp associé aux deux
  redémarrages inexpliqués. Les nouveaux essais utilisent des fixtures propres.
- Ne pas tuer un propriétaire encore nécessaire au nettoyage, effacer une
  quarantaine ou relancer automatiquement après un résultat de nettoyage inconnu.
- Le SDK Shizuku ne recrée pas les droits ADB après un reboot. Le démarrage
  automatique modifiant la durée de confiance ADB n'a pas été activé.

Inspection archivée du téléphone, en lecture seule le 7 septembre vers 03:27 :
boot `348d453e-f4e5-40e0-8ef0-030f4d5e38af` inchangé, warranty bit 0,
verified boot green, flash locked 1, SELinux Enforcing. Mémoire totale visible
11 351 456 kB, disponible à cet instant 4 663 908 kB ; ce dernier chiffre varie.
Il n'existe pas de réservation générale de seulement 2 Gio pour une application
native démontrée par ces mesures. Ne pas assimiler RAM physique, mémoire
disponible, zram et plafonds du lanceur.

La protection des écrans est gérée par `tools/runtime/protect-idle-screens.ps1`.
L'exécuter avec `-ActivateNow` à la fin du travail ou lors d'un arrêt, conformément
à la demande de Julien. Le script remet aussi le Fold en veille d'affichage.
