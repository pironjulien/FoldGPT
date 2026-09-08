# Reprise du projet FoldGPT

**Sauvegarde du 8 septembre :** le [complément v10](supplement-v10.md) conserve
l'APK r12, son runtime gelé et les preuves natives. Ses 25 232 fichiers ont été
retéléchargés depuis GitHub et restaurés/vérifiés sur Windows ; les 1 057
fichiers du tar source exact ont aussi été contrôlés. Ce point de récupération
reste distinct de la qualification de l'interface habituelle.

Le dépôt privé de travail est `pironjulien/FoldGPT-workspace`, branche
`codex/foldgpt-beta`. Il contient les sources et les recherches en cours ; ce
checkpoint ne signifie pas que les commandes ordinaires fonctionnent déjà sur
le téléphone.

**Session reprise le 7 septembre après la clôture de nuit :** lire d'abord
[HANDOFF.md](HANDOFF.md). Le projet Python natif V2 a réussi sur le Fold ;
le canal de lecture et le chargeur de configuration ont ensuite réussi sur PC
entre deux UID distincts. L'intégration à une tâche complète reste en cours.

```powershell
gh repo clone pironjulien/FoldGPT-workspace C:\Dev\ChatgptFold -- -c core.autocrlf=false
Set-Location C:\Dev\ChatgptFold
python tools/recovery/restore-submodules.py
```

Le script récupère les deux sous-modules et applique les modifications exactes
de Termux:X11, après contrôle du commit et du SHA-256. Il conserve un état déjà
restauré et refuse un conflit. Les originaux officiels sont récupérés à leurs
commits figés. Le clone principal utilise LF afin que Git Windows et Git dans
WSL lisent le même état de travail, indépendamment de leurs réglages globaux.

Les dépendances, résultats d'essais et données locales ignorées par Git sont
conservés séparément dans une archive chiffrée de la release privée de reprise.
La clé de déchiffrement reste dans le coffre OneDrive
`Documents/NexusSecure/projects/FoldGPT/recovery.agekey`, jamais dans GitHub.
La release est `recovery-2026-09-07` dans ce même dépôt privé. Son archive
principale représente 127 425 entrées, 13 639 569 361 octets de fichiers,
et 9 872 503 793 octets chiffrés répartis en dix morceaux. SHA-256 de
l'ensemble chiffré :
`002f1e0bc3a6a9d2d95091b419413475212a1e51696f0bb37e33028bfc7271b0`.

Le 7 septembre 2026, les dix morceaux ont été retéléchargés depuis GitHub,
déchiffrés et réellement extraits dans un dossier neuf : **113 900 fichiers
vérifiés octet par octet et 441 liens symboliques contrôlés**. Le
[rapport conservé](verification/github-archive-restoration.json) et le
[manifeste de l'archive](verification/archive-manifest.json) fixent ce résultat.
La récupération du moteur à partir d'un clone neuf a également reproduit
[exactement le patch exporté](verification/engine-source-restoration.json).

## Récupérer les données locales

Depuis PowerShell, avec GitHub CLI connecté au compte ayant accès au dépôt :

```powershell
gh release download recovery-2026-09-07 --repo pironjulien/FoldGPT-workspace --dir C:\Dev\ChatgptFold\work\FoldGPT-recovery\downloaded
$ErrorActionPreference = 'Stop'
$foldRecoveryKey = (Join-Path $env:OneDrive 'Documents\NexusSecure\projects\FoldGPT\recovery.agekey').Replace('\','/')
$foldRecoveryKeyLinux = (& wsl --distribution Ubuntu-24.04 --exec wslpath -u $foldRecoveryKey).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Impossible de résoudre le chemin du coffre' }
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/restore-archive.py --assets /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/downloaded --identity $foldRecoveryKeyLinux --destination /var/tmp/foldgpt-recovered --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/archive-verification.json
```

Le PC doit disposer de WSL Ubuntu, Python 3.12 ou plus récent et `age` dans
Ubuntu ; voir [l'environnement de build](build-environment.md). WSL est utilisé
sur le PC pour conserver les liens Linux de l'archive. Les destinations doivent
être nouvelles. Le script vérifie les dix morceaux, authentifie entièrement le
déchiffrement avant extraction, compare l'inventaire et contrôle les octets de
chaque fichier effectivement restauré. La clé n'est jamais affichée.

Le même téléchargement récupère aussi le complément `native-checkpoint-v2*`.
Il conserve l'APK et les builds natifs figés après l'archive principale. Sa
restauration, également vérifiée après retéléchargement GitHub, s'effectue dans
un dossier distinct :

```powershell
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/restore-archive.py --assets /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/downloaded --manifest native-checkpoint-v2-manifest.json --identity $foldRecoveryKeyLinux --destination /var/tmp/foldgpt-native-recovered --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-verification.json
```

Ce complément contient 123 fichiers vérifiés et l'APK debug de FoldGPT
`c9a83886ebdfeba7f28ecbc37a383252cc91ad6e5c3ad3dc7189cc81e35694a1`,
compilé et signé, **pas installé sur le téléphone**. Il reste séparé de
l'ancienne sortie APK de l'archive principale. Voir le
[rapport de restauration](verification/github-supplement-v2-restoration.json).
Le superviseur figé de ce complément v2 est `foldgpt-bionic-supervisor-8Kd8xQRE` ; il inclut
les corrections de revue sur les threads et l'attente réelle du superviseur.
Les anciens fichiers `native-checkpoint*` sans `v2` restent une preuve
historique de l'étape précédente et ne sont pas le complément à utiliser.

L'archive est un instantané réalisé pendant le développement. **Les sources
les plus récentes sont celles de la branche Git**, pas celles de l'archive.
Hydrater ensuite le clone neuf avec seulement ses données ignorées par Git :

```powershell
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/hydrate-project.py --snapshot /var/tmp/foldgpt-recovered/ChatgptFold --project /mnt/c/Dev/ChatgptFold --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/hydration.json
```

La procédure conserve les fichiers suivis par Git et les sous-modules déjà
restaurés. Elle refuse les collisions avec des données locales préexistantes.
Cette étape a été exécutée sur un clone Windows réel : **100 332 fichiers de
données (13 460 048 339 octets) et 441 liens ont été comparés à l'inventaire
après copie**, avec contrôle de l'absence de modification des sources Git.
Voir le [rapport complet](verification/github-hydrated-files-verification.json).
Les liens absolus sont conservés avec leur cible originale ; les sorties de
build dépendant d'un ancien chemin doivent être reconstruites, pas exécutées
aveuglément. `android/local.properties` conserve le chemin SDK du premier PC :
le régénérer si l'emplacement du SDK diffère sur le second.

## Complément v3 : qualification Android v6/v7

Le complément **`native-checkpoint-v3*`** ajoute les stages Python/APK,
le superviseur figé, les petits builds Python provenant de WSL, les tests PC
et toutes les preuves des derniers essais Android. Il complète l'archive
principale et v2. SHA-256 chiffré :
`7f4b00b2963d7f5e39e28b5ca077697f7c4e0a9519ce1082644aa97d9aeb8c5b`.
Les 224 870 091 octets ont été retéléchargés depuis GitHub, déchiffrés puis
extraits : **8 462 fichiers et un lien vérifiés**, soit 385 929 107 octets de
fichiers. Voir le [rapport de restauration](verification/github-supplement-v3-restoration.json).

Après l'hydratation principale, restaurer ce complément dans un autre dossier,
puis ajouter ses fichiers ignorés au clone. Le rapport doit être un fichier neuf
hors des fichiers suivis du clone et du snapshot ; aucune donnée différente n'est écrasée.

```powershell
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/restore-archive.py --assets /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/downloaded --manifest native-checkpoint-v3-manifest.json --identity $foldRecoveryKeyLinux --destination /var/tmp/foldgpt-native-v3 --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v3-verification.json
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/merge-supplement.py --snapshot /var/tmp/foldgpt-native-v3/foldgpt-native-artifacts-v3-20260907 --project /mnt/c/Dev/ChatgptFold --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v3-merge.json
```

Le runtime Python recompilé et ses preuves sont alors sous
`downloads/kernel-python-builds/foldgpt-bionic-python-rsemaYBI`.
L'APK v7 de ce complément est `tools/executor/shizuku-lab/build/kernel-v7-setup/app-debug.apk`.
Les anciens APK restent associés à leurs propres preuves. Le v7 installé a
rencontré un refus Java d'admission ; il ne valide pas le worker natif. Lire
[HANDOFF.md](HANDOFF.md) et le rapport Android avant toute opération sur le Fold.

Cette fusion a été exécutée sur le clone Windows déjà hydraté puis vérifiée
indépendamment : **8 461 fichiers du projet et un lien, tous exacts**, sans
modification des sources Git ni remplacement de données. Le fichier d'identité
de l'archive `CHECKPOINT.json` reste dans le snapshot. Voir la
[preuve de fusion](verification/github-supplement-v3-merge.json).

## Complément v4 : diagnostics Android v8/v9

Le complément **`native-checkpoint-v4*`** ajoute les APK v8/v9, le stage v8
et les preuves réelles : ancien Intent rejeté sans réservation v9, préflight
admis après préparation, puis refus de `bind` au démarrage du bootstrap.
Il complète les archives principale, v2 et v3. Aucun worker noyau n'a été lancé.

Les **86 998 467 octets chiffrés** ont été retéléchargés depuis GitHub,
authentifiés puis extraits : **2 928 fichiers vérifiés**, soit 141 071 743 octets.
SHA-256 chiffré :
`e35e7e59659929b55e9b432cab1e496f40640ab993501d04f8f509e8ed0648a1`.
Voir la [preuve de restauration](verification/github-supplement-v4-restoration.json).

Après la fusion du v3, suivre la même procédure additive dans des dossiers neufs :

```powershell
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/restore-archive.py --assets /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/downloaded --manifest native-checkpoint-v4-manifest.json --identity $foldRecoveryKeyLinux --destination /var/tmp/foldgpt-native-v4 --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v4-verification.json
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/merge-supplement.py --snapshot /var/tmp/foldgpt-native-v4/foldgpt-native-artifacts-v4-20260907 --project /mnt/c/Dev/ChatgptFold --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v4-merge.json
```

Cette fusion a été exécutée sur le clone Windows déjà hydraté : **2 927 fichiers
du projet vérifiés indépendamment**, sans modification des sources ni écrasement
de données. `CHECKPOINT.json` reste dans le snapshot. Voir la
[preuve de fusion](verification/github-supplement-v4-merge.json).

L'APK v9 figé est `tools/executor/shizuku-lab/build/kernel-v9-launch/app-debug.apk`.
Les sources courantes peuvent avoir progressé depuis cet APK ; lire le
[point de reprise](HANDOFF.md) avant tout nouveau build ou essai.

## Complément v5 : APK v10 et session conservée

Le complément **`native-checkpoint-v5*`** ajoute le stage et l'APK v10, les
12 tests nonroot de propriété de session, ainsi que les rapports réels de cet
essai. Le socket de démarrage est dépassé, puis `/linkerconfig` est refusé.
Le propriétaire reste en quarantaine : lire le
[rapport v10](../docs/research/native-v10-retained-session-2026-09-07.md)
avant toute action sur le téléphone.

Les **54 234 188 octets chiffrés** ont été retéléchargés depuis GitHub,
authentifiés puis extraits : **2 798 fichiers vérifiés**, soit 105 688 281 octets.
SHA-256 chiffré :
`2455b1fba1fe1f39c73cd19c6e1b459f618502b2ee4392f5a2da6da54a7f3559`.
Voir la [preuve de restauration](verification/github-supplement-v5-restoration.json).

Après la fusion du v4, utiliser de nouveaux dossiers :

```powershell
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/restore-archive.py --assets /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/downloaded --manifest native-checkpoint-v5-manifest.json --identity $foldRecoveryKeyLinux --destination /var/tmp/foldgpt-native-v5 --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v5-verification.json
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/merge-supplement.py --snapshot /var/tmp/foldgpt-native-v5/foldgpt-native-artifacts-v5-20260907 --project /mnt/c/Dev/ChatgptFold --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v5-merge.json
```

L'APK est `tools/executor/shizuku-lab/build/kernel-v10-stdio/app-debug.apk`.
La sauvegarde conserve les échecs et les sessions retenues ; elle ne signifie
pas que les commandes ordinaires fonctionnent déjà depuis l'interface.

La fusion v5 a aussi été exécutée et contrôlée indépendamment sur le clone
Windows : **2 797 fichiers du projet exacts**, sans écrasement. Voir la
[preuve de fusion](verification/github-supplement-v5-merge.json).

## Complément v6 : historique ajouté depuis la première sauvegarde

Le contrôle final de couverture a retrouvé quelques anciens builds et rapports
dans `downloads` absents de l'archive principale et des compléments v3 à v5.
Le complément **`native-checkpoint-v6*`** les conserve. Les métadonnées `.git`
et caches régénérables restent exclus selon la règle générale d'archivage.

Ses **1 323 849 octets chiffrés** ont été retéléchargés, authentifiés et
restaurés : **468 fichiers**, soit 4 532 494 octets, métadonnées de checkpoint
comprises. SHA-256 :
`609c235e281a35a543f62800d9fa3f829f28c77b2d606dbf15460fb4dc56a81d`.
Voir la [preuve de restauration](verification/github-supplement-v6-restoration.json).

Après la fusion du v5 :

```powershell
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/restore-archive.py --assets /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/downloaded --manifest native-checkpoint-v6-manifest.json --identity $foldRecoveryKeyLinux --destination /var/tmp/foldgpt-native-v6 --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v6-verification.json
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/merge-supplement.py --snapshot /var/tmp/foldgpt-native-v6/foldgpt-native-artifacts-v6-20260907 --project /mnt/c/Dev/ChatgptFold --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v6-merge.json
```

La fusion v6 a également été exécutée sur le clone Windows : **467 fichiers
du projet exacts**, sans écrasement ; le fichier de checkpoint reste à part.
Voir la [preuve de fusion](verification/github-supplement-v6-merge.json).

## Dernier complément v7 : préparation native V11

Le complément **`native-checkpoint-v7*`** conserve le superviseur corrigé
`KvSGBnzP`, le stage et l'APK V11, ses tests PC et les preuves d'installation
du runtime séparé sur le Fold. L'autorisation Shizuku attend derrière le
verrouillage du téléphone ; aucune tentative native V11 n'est lancée.
Lire le [rapport V11](../docs/research/native-v11-isolated-preparation-2026-09-07.md).

Ses **54 505 580 octets chiffrés** ont été retéléchargés depuis GitHub,
authentifiés et restaurés : **2 819 fichiers vérifiés**, soit 106 367 838
octets. SHA256 :
`28c5064af2f2b7e9b249086bc6a8c3ede07a55163355840bc7e97c8bc133e736`.
Voir la [preuve de restauration](verification/github-supplement-v7-restoration.json).

Après la fusion du v6, utiliser des dossiers neufs :

```powershell
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/restore-archive.py --assets /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/downloaded --manifest native-checkpoint-v7-manifest.json --identity $foldRecoveryKeyLinux --destination /var/tmp/foldgpt-native-v7 --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v7-verification.json
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/merge-supplement.py --snapshot /var/tmp/foldgpt-native-v7/foldgpt-native-artifacts-v7-20260907 --project /mnt/c/Dev/ChatgptFold --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v7-merge.json
```

Les sources actuelles restent celles de Git. Les APK et stages historiques
ne sont ni remplacés ni rejoués par cette restauration.

La fusion v7 a également été réalisée sur le clone Windows : **2 818 fichiers
du projet vérifiés indépendamment**, sans modification des sources ni
remplacement de données. Le fichier de checkpoint reste dans le snapshot.
Voir la [preuve de fusion](verification/github-supplement-v7-merge.json).

## Complément v8 : clôture de nuit et build GNU ARM64

Le complément `native-checkpoint-v8*` conserve les deux exécutables GNU ARM64,
leurs symboles et versions non dépouillées, les preuves PC, les scripts de
compilation, l'instantané exact des 6 956 sources et les dépendances OpenSSL/V8.
Il ajoute aussi les dernières observations mémoire et les cinq bibliothèques
GNU copiées en lecture seule du Fold pour une comparaison future.

Archive chiffrée : **956 432 196 octets**, SHA256
`0578a1b5b816bbe29081642c03c9052f88624cf8c0a331908898dc17e1163355`.
Elle contient 3 241 402 905 octets de fichiers avant compression. L'archive
principale et les compléments précédents restent nécessaires.

Ce complément a été retéléchargé depuis GitHub, authentifié, déchiffré et
réellement extrait : **7 169 fichiers vérifiés**, sans lien symbolique.
Voir la [preuve de restauration v8](verification/github-supplement-v8-restoration.json).
Les fusions Windows précédemment vérifiées couvrent le socle et v3 à v7 ; le
v8 est ici vérifié par sa restauration Linux complète, sans nouvelle fusion
Windows lors de la clôture.

Après les fusions précédentes, restaurer puis fusionner ce complément dans des
dossiers neufs, avec les mêmes outils :

```powershell
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/restore-archive.py --assets /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/downloaded --manifest native-checkpoint-v8-manifest.json --identity $foldRecoveryKeyLinux --destination /var/tmp/foldgpt-native-v8 --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v8-verification.json
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/merge-supplement.py --snapshot /var/tmp/foldgpt-native-v8/foldgpt-native-artifacts-v8-20260907 --project /mnt/c/Dev/ChatgptFold --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v8-merge.json
```

Les artefacts se retrouvent sous `downloads/engine-gnu-arm64-20260907` :
`build-evidence/20260907T045021Z/artifacts`, `source-snapshot` et `dependencies`.
L'instantané exact du build reste une preuve ; les sources de développement
actuelles se récupèrent avec le patch Git décrit ci-dessous. Les chemins de
build `/opt/foldgpt` sont ceux du PC d'origine. Lire les scripts avant reprise
et reconstituer leur environnement selon [build-environment.md](build-environment.md).
Ce complément n'installe rien sur le téléphone et n'active aucun exécuteur.

## Complément v9 : Python natif V2 réussi sur le Fold

Le complément `native-checkpoint-v9*` conserve les stages et APK V12/V1/V2,
les gels du superviseur correspondants, le runtime Python corrigé et les
preuves du projet réellement créé, testé et construit sur le téléphone.
L'échec de chargement V1 reste conservé avec la réussite V2.

Archive chiffrée : **152 783 597 octets**, SHA256
`f0d7cfdfabc367c46fd6b9af0de3b1baa36a778e7264b8ec1a71e8a5fd2a0efe`.
Elle a été retéléchargée depuis la release privée, authentifiée, déchiffrée et
extraite : **8 958 fichiers vérifiés**, soit 314 414 434 octets, sans lien
symbolique. Voir la [preuve de restauration v9](verification/github-supplement-v9-restoration.json).
La fusion additive dans le clone Windows n'a pas été répétée ; cette preuve
porte sur la restauration Linux complète.

Après les compléments précédents, utiliser des dossiers neufs :

```powershell
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/restore-archive.py --assets /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/downloaded --manifest native-checkpoint-v9-manifest.json --identity $foldRecoveryKeyLinux --destination /var/tmp/foldgpt-native-v9 --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v9-verification.json
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/merge-supplement.py --snapshot /var/tmp/foldgpt-native-v9/foldgpt-native-artifacts-v9-20260907 --project /mnt/c/Dev/ChatgptFold --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/native-v9-merge.json
```

Lire le [rapport V2](../docs/research/native-runtime-v2-device-result-2026-09-07.md)
avant toute reprise. Les actions de qualification V12/V1/V2 sont consommées ;
restaurer leurs preuves ne les autorise pas à nouveau. Le raccordement aux
commandes ordinaires de l'interface reste en développement.

## Récupérer le moteur séparé

Le code du moteur séparé est développé sous
`C:\Dev\ChatgptFold\work\worktrees\FoldgptEngine`, à partir du
commit Codex `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a` (`rust-v0.153.4`).
Son état de travail est exporté dans `recovery/engine/engine.patch` avec le
commit officiel exact et le SHA-256 du patch dans `manifest.json` :

```powershell
python tools/recovery/restore-engine.py --destination C:\Dev\ChatgptFold\work\worktrees\FoldgptEngine
wsl --distribution Ubuntu-24.04 --exec python3 /mnt/c/Dev/ChatgptFold/tools/recovery/hydrate-project.py --snapshot /var/tmp/foldgpt-recovered/FoldgptEngine --project /mnt/c/Dev/ChatgptFold/work/worktrees/FoldgptEngine --report /mnt/c/Dev/ChatgptFold/work/FoldGPT-recovery/engine-hydration.json
```

Le script récupère la release officielle, vérifie son commit, applique le patch
contrôlé dans les fichiers et l'index Git, puis interdit les pushes vers le dépôt
public amont. Les nouveaux fichiers du patch sont donc protégés eux aussi lors
de l'hydratation. Le clone du moteur utilise les fins de ligne LF pour les outils
Linux du PC. Les caches Rust
`target`, Gradle `.gradle`/`.cxx`, Python `__pycache__` et métadonnées `.git`
ne sont pas archivés ; ils sont régénérables. Les dépendances globales du PC
restent à installer selon le document d'environnement.

## Signature et état du travail

La clé de signature Android de FoldGPT est également conservée dans le coffre,
fichier `android-debug.keystore` à côté de `recovery.agekey`. Le build principal
la sélectionne depuis OneDrive, ou depuis `FOLDGPT_SIGNING_KEYSTORE`, puis
contrôle son certificat. Cela permet de mettre à jour l'application déjà
installée sans changer d'identité de signature sur l'autre PC. Un coffre absent
ou une autre clé produit une erreur explicite ; aucune nouvelle identité n'est
créée silencieusement. Cette clé concerne FoldGPT, pas l'application officielle
ChatGPT.

Le fournisseur OneDrive déclare ces deux fichiers **synchronisés** via l'API
Windows Cloud Files (`InSyncState=1`, contrôle du 7 septembre à 03:28). Le
[rapport](verification/vault-sync.json) ne contient aucune clé. Ce contrôle
reflète l'état local déclaré par OneDrive ; un téléchargement indépendant du
coffre depuis le second PC n'a pas été effectué ici.

État technique vérifié au début de cette sauvegarde : le test fixe
Shizuku/Bionic crée, teste et construit réellement un projet Python sur le
Fold. L'intégration aux commandes, fichiers et sessions ordinaires est en cours.
Voir `docs/research/shizuku-bionic-trial-2026-09-07.md`. Ne pas relancer l'ancien
diagnostic GNU/PRoot/seccomp associé aux redémarrages du téléphone.
