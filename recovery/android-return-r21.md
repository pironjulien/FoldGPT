# Reprise Android — revue du 8 septembre 2026

Préparé sur PC seulement, sources finales `9e1feeaff2e2501299f272c95ab5b2641d2044df`. Aucun contact avec le téléphone ni changement de source. Les commandes ci-dessous sont à exécuter **au retour du Fold**, depuis `C:\Dev\ChatgptFold` ; conserver les sorties sous ce dossier.

## 1. Résoudre l’ancienne session avant installation

Le dernier propriétaire est le **PID 8507**, UID10412, boot `348d453e-f4e5-40e0-8ef0-030f4d5e38af`, endpoint `/data/user/0/app.foldgpt/app_foldgpt_exec/feafbdfc91344383abb26dde1dfad3c2/owner.sock`. La précédente réponse `Status: ok` à STOP prouve uniquement la réception de l’action. Le fichier `phone-departure-device/snapshot.json` est incomplet.

```powershell
$foldAdbPath = "$env:LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe"
& $foldAdbPath devices -l
& $foldAdbPath -s R3GL808JN4A shell cat /proc/sys/kernel/random/boot_id
& $foldAdbPath -s R3GL808JN4A shell run-as app.foldgpt cat files/native-executor-status.json
& $foldAdbPath -s R3GL808JN4A shell ls -d /proc/8507
```

Sauvegarder ces réponses avant toute autre action. Si l’ancien propriétaire est encore actif, utiliser uniquement l’arrêt normal déjà implémenté, puis relire le statut pendant au plus30s pour la collecte :

```powershell
& $foldAdbPath -s R3GL808JN4A shell am start -W -n app.foldgpt/.NativePreparationActivity -a app.foldgpt.action.STOP_NATIVE_EXECUTOR
```

Sur le même boot, la fermeture propre exige **les deux** objets `lastNativeSessionStatus` et `lastRemoteStatus` associés à `bootstrapPid=8507`, avec `bootstrapReaped=true`, `cleanupComplete=true`, `ownerRetained=false`, `waitStatus=0`, `setupError=null`, `transportFailed=false`, `quarantined=false`, `refusedBeforeFork=false` ; état supérieur `closed`. Ajouter l’absence réelle du PID et de l’ancien socket/manifest, avec une erreur de fichier absent, pas une erreur ADB ou un refus de lecture. Un délai dépassé ne certifie rien. Ne pas tuer numériquement8507, désinstaller, effacer un marqueur ou forcer l’arrêt Android pour fabriquer la preuve.

Si le boot a changé, aucun processus du boot précédent ne peut survivre, mais **le nettoyage gracieux historique reste non prouvé**. Le PID8507 peut désigner autre chose : ne pas le signaler. Conserver le changement de boot et examiner le statut actuel avant la reprise. Si le statut historique est perdu, réattribué à une autre session, ou reste `ready` après reboot, ne pas le présenter comme un reçu pour8507.

## 2. Prérequis réels et candidat

- ADB autorisé sur `R3GL808JN4A` ; Shizuku opérationnel en backend shell **UID2000**, autorisation FoldGPT accordée. Le SDK intégré demande le Binder et l’autorisation ; il **ne démarre pas le serveur Shizuku**. Après reboot, son rétablissement reste un préalable via le mécanisme officiel déjà utilisé.
- Installation FoldGPT existante conservée, compte GNU défini par `files/debian/etc/foldgpt-user`/`passwd`, runtime Python installé et dossiers `cache/x11`, `cache/shm` existants. Le pilote exige ces éléments ; il ne provisionne pas un téléphone vierge.
- Capturer un état avant/après avec `tools/runtime/capture-runas-device.py --output <dossier-neuf-dans-work>` : boot, propriétés et SHA256 des APK, dont ChatGPT officiel. Comparer l’intervalle réel de l’essai ; une éventuelle mise à jour officielle antérieure n’est pas une modification de notre essai.

Après résolution de l’ancienne propriété, contrôler puis installer le candidat déjà revu, sans désinstallation :

```powershell
Get-FileHash downloads/native-production-20260908/foldgpt-native-candidate-r21.apk -Algorithm SHA256
& $foldAdbPath -s R3GL808JN4A install -r downloads/native-production-20260908/foldgpt-native-candidate-r21.apk
```

SHA256 attendu : `cdfbe23c7ce9e89d499bf4fcbfdf97a9380ab4b7d1faa95db78b52aa8149e4a0`. Le pilote suivant recontrôle les octets de l’APK réellement installée. La signature v2 identique à r20 et `versionCode11` ont été vérifiés sur PC. Ne pas ouvrir simultanément l’interface : l’acquisition de production réserve une seule connexion.

## 3. Qualification native ordinaire puis fermeture

```powershell
python -B tools/runtime/qualify-production-device.py --qualification ordinary-uid --apk-sha256 cdfbe23c7ce9e89d499bf4fcbfdf97a9380ab4b7d1faa95db78b52aa8149e4a0
```

Exiger code0 **et** `downloads/native-ordinary-production-device-20260908/<essai>/report.json: passed=true`. Le rapport doit contenir les cinq commandes modèle réellement fermées avec sortie0 et `sandboxType=none`, Bash `-lc` **et** `-c` sans erreur de démarrage, identité Android/aarch64/UID de l’application, trois unittest, archive produite et sortie exacte42, puis les cinq lectures config/humain identiques. Les transferts du client et de ses deux dépendances sont vérifiés par SHA256.

Exiger aussi `bootUnchanged`, `nativeOwnerAbsent`, `cleanupVerified`, les deux reçus Java associés au **PID de cet essai**, état `closed`, wait0 et aucun défaut. `client.passed=true` seul ne suffit pas. Le pilote effectue STOP en `finally`, conserve `commands.json`, `statuses.json`, stdout/stderr et le rapport. Son délai de collecte n’est pas une garantie de délai de nettoyage.

**Limite du préalable du pilote :** il accepte seulement un état initial `closed`/`unavailable` (ou absent), sans authentifier lui-même la fermeture historique de8507. Le contrôle de l’étape1 est donc indispensable. Inversement, un ancien `ready` persistant après reboot peut empêcher son lancement : constater ce cas réellement avant toute correction ; ne pas effacer le statut pour passer le test.

## 4. Conversation, éditeur, reprise : trois preuves supplémentaires

1. Après la fermeture de l’essai, lancer normalement `app.foldgpt/.FoldActivity`. Reprendre **« Créer et tester une addition Python »**, projet **« Validation Python FoldGPT »**, dossier observé `/data/user/0/app.foldgpt/files/projects/ui-python-caae3a83d156`. Lire le mode actuel ; conserver **Accès complet**. Demander à nouveau le travail réel : fonction addition, cas20+22/-2+2/1+2, zipapp42 et identité Python. Observer les véritables appels/outils et fichiers, sans injecter les fichiers de la qualification précédente ni un résultat synthétique.
2. Dans l’éditeur habituel, ouvrir le fichier réellement créé, ajouter un commentaire reconnaissable et sauvegarder. Vérifier indépendamment les octets Android puis fermer/réouvrir l’onglet. Le client ordinary-uid vérifie des lectures humaines, **pas une sauvegarde UI** : son PASS ne remplace pas cette étape.
3. Arrêter normalement l’espace de travail, conserver les deux reçus de fermeture du propriétaire UI réel, relancer FoldActivity et retrouver la même conversation et les fichiers sauvegardés. Demander dans cette conversation un nouveau lancement des tests et du zipapp, avec identité Android et cwd. Le simple retour de l’écran ou de l’historique ne prouve pas la reprise de l’exécution native.

Pour l’inspection de l’interface, réutiliser l’outillage existant `tools/context/phone_context_ui.py` seulement avec le port loopback transféré et l’identifiant de page **observés à cette reprise** ; la page attendue est `app://-/index.html`. Le journal précédent annonçait9223, mais l’ancien ID de page ne doit pas être réutilisé. Préserver les sorties d’outils, la portion exacte de conversation et les empreintes des fichiers du projet ; éviter toute collecte générale de comptes ou historiques.

## Ce qui n’est pas promis

Ce candidat ne fournit pas de PTY : `tty=true` reste refusé. Le petit projet ne valide pas les programmes interactifs, tous les outils absents du runtime, tous les modes managed, les proxys/snapshots, les mises à jour futures ou toutes les situations de reprise. L’interface et le contrôleur GNU utilisent toujours PRoot ; les commandes Python/Bash sont natives Android/Bionic, aucune VM. Les commandes passent sous l’UID ordinaire de FoldGPT ; aucune modification des protections du téléphone n’est requise par ce protocole. La réussite du projet complet doit être annoncée seulement après les preuves distinctes conversation + sauvegarde + fermeture/reprise.
