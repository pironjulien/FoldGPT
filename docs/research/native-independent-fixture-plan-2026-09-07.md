# Fixture V11 indépendante : préparation PC et contrat d'essai

Cette préparation n'a exécuté aucun build APK, aucune commande ADB et aucun
code sur le téléphone. Les sources de l'identité V11 et les contrôles des
paramètres sont préparés ; les compilations, la signature, la permission
Shizuku et le résultat Android restent à vérifier par la tâche principale.

## Identité fixe et dépendances conservées

| Élément | V10 retenu, inchangé | V11 indépendante |
|---|---|---|
| Application Android | `app.foldgpt.shizukuprobe` | `app.foldgpt.kernelqualification.v11` |
| Version APK | 10 | 11 |
| Tag UserService | `foldgpt-kernel-qualification-v6` | `foldgpt-kernel-qualification-v11` |
| Version UserService | 6 | 11 |
| Suffixe processus | `kernelqualification` | `kernelqualificationv11` |
| Base native | `/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2` | `/data/local/tmp/foldgpt-bionic-supervisor-qualification-v3` |
| Rapports privés app | `files/kernel-v6` | `files/kernel-v11` |
| Action d'exécution | `.KERNEL_RUN_FIXED_V10` | `.KERNEL_RUN_FIXED_V11` |

V11 a son propre `workspace`, `broker`, `python`, ses archives de staging et
`evidence.json`, tous sous V3. Ses 81 alias Python doivent désigner les ELF de
son propre `nativeLibraryDir`, obtenu après installation par PackageManager.
Les bibliothèques système Android restent des dépendances communes en lecture.
Il ne faut mettre à jour aucun paquet/runtime dont V10 dépend pendant sa
rétention. Son APK de référence est
`46049fd8d2f381c2680023c12005a4d57cf4c9a51c829a447eb88642e6b3a6a4`.

## Fichiers concernés

Les chemins ci-dessous sont relatifs à `C:/Dev/ChatgptFold`.

- `tools/executor/shizuku-service/qualification/build.gradle` : applicationId
  V11, version11, sourceSets `build/qualification-stage-v11`, contrôle exact
  package/Python home/workspace/broker avant build.
- `qualification/src/main/AndroidManifest.xml` dans ce projet : libellé V11,
  Activity au nom complet `app.foldgpt.kernelqualification.QualificationActivity`.
  Le seul provider vient du transport, autorité `${applicationId}.shizuku`.
- `qualification/src/main/java/app/foldgpt/kernelqualification/QualificationProfile.java` :
  profils fixes V10/V11 sélectionnés uniquement par le vrai nom de l'application.
- `QualificationActivity.java` voisin : actions/version/tag/rapports issus du
  profil ; V11 ajoute `KERNEL_AUTHORIZE` sans réservation ni bind du UserService.
  Le RUN V11 exige l'autorisation existante, puis réserve l'essai avant bind.
  La garde de propriétaire et la fermeture avec preuves restent obligatoires.
- `tools/executor/shizuku-service/stage-qualification.py` et
  `qualification-inputs-v11.json` : sélection du nouveau build figé, ses hashes,
  la base V3 et le paquet V11. Leur préparation est pilotée par la tâche principale.
- `tools/executor/bionic-supervisor/qualification_factory.py` : contrat fixe V3
  sélectionné dans l'APK ; la correction du runtime est revue séparément.
- `tools/runtime/qualification_identity.py` : table des tuples package/base/version
  admis, chemins de rapport et identité des preuves autorisant une inspection.
- `tools/runtime/stage-kernel-python.py` : identité explicite, corrélation avec
  l'info de l'APK et le déploiement, nouveau répertoire exclusivement créé.
- `tools/runtime/collect-native-qualification.py` : identité explicite et
  absence d'inspection du workspace si les preuves propres visent un autre profil.
- `tools/runtime/test_qualification_identity.py` : cinq tests PC, dont refus
  de collision avant tout subprocess/ADB et avant création du dossier de sortie.

Déjà paramétrés sans modification nécessaire :
`tools/executor/bionic-runtime/build-python-cli.sh` reçoit le Python home réel ;
`tools/runtime/stage-native-qualification.py` reçoit `--base` et refuse une base
existante ; `snapshot-native-qualification.py` reçoit ses paquets et workspace.
`Deployment.java` prend le package depuis le vrai Context et les chemins depuis
l'asset signé, pas depuis une requête ; ses contrôles de hashes restent actifs.
Le Gradle du laboratoire, les snapshots V10 et FoldgptEngine ne sont pas modifiés.

## Commandes PC prévues, non exécutées par cette préparation

La CLI doit être recompilée pour V3, même si la bibliothèque CPython ne change
pas. Cette commande WSL utilise les entrées officielles déjà présentes et leur
vérification de hashes ; noter le répertoire `/var/tmp/foldgpt-bionic-python-*`
effectivement produit, sans le remplacer par un ancien chemin :

```bash
bash /mnt/c/Dev/ChatgptFold/tools/executor/bionic-runtime/build-python-cli.sh \
  /mnt/c/Dev/ChatgptFold/downloads/native-python/build-aRED9UkC/prefix \
  /data/local/tmp/foldgpt-bionic-supervisor-qualification-v3/python \
  /mnt/c/Dev/ChatgptFold/downloads/native-python/inputs/python-3.14.7-aarch64-linux-android.tar.gz
```

Après revue et gel du superviseur corrigé, exécuter `stage-qualification.py`
avec `--frozen` pointant exactement vers le build nommé dans
`qualification-inputs-v11.json`, `--python-cli` vers la nouvelle CLI,
`--package app.foldgpt.kernelqualification.v11` et
`--output C:/Dev/ChatgptFold/tools/executor/shizuku-service/build/qualification-stage-v11`.
Cette sortie doit être absente. Le nom et les hashes du nouveau build restent
des résultats à produire ; ils ne sont pas remplacés ici par ceux du 8Kd8xQRE.

Depuis `C:/Dev/ChatgptFold/tools/executor/shizuku-service`, après staging :

```powershell
$env:JAVA_HOME = 'C:\Program Files\Microsoft\jdk-21.0.12.8-hotspot'
$env:ANDROID_HOME = "$env:LOCALAPPDATA\Android\Sdk"
& 'C:\Users\julie\.gradle\wrapper\dists\gradle-9.7.1-bin\1w1c7tv4s851m17nbqdsro2tv\gradle-9.7.1\bin\gradle.bat' --no-daemon :qualification:assembleDebug :transport:testDebugUnitTest -PfoldgptFrozenTransportJni=C:/Dev/ChatgptFold/tools/executor/shizuku-lab/build/frozen-transport-jni --console=plain
```

Le script canonique de signature préserve le certificat déjà vérifié ; sa clé
reste dans NexusSecure. Figer le résultat sous un nouveau dossier V11 avant
vérification : manifest binaire avec le paquet V11, une seule Activity protégée
par DUMP, un seul provider `ExecutorProvider` protégé, permission API_V23,
absence de sharedUserId, signature attendue, ELF et sources conformes aux
inventaires, liens runtime sans référence aux APK V10. Utiliser
`build-tools/36.0.0/apksigner.bat verify --verbose --print-certs` et
`aapt.exe dump xmltree <APK_V11> AndroidManifest.xml`. Le vérificateur figé V10
est une référence de structure ; ne pas l'exécuter comme validateur V11 car ses
comparaisons imposent les octets et l'identité V10.

## Séquence future de validation Android

1. Photographier les preuves de V10 sans modifier son propriétaire, son marker,
   son workspace ou son runtime ; relever APK, contexte, boot et limites réels.
2. Installer uniquement le paquet neuf V11, sans `-r` ni remplacement d'un
   paquet existant. Si ce paquet existe déjà, examiner sa propre histoire.
3. Lancer V11 `KERNEL_COLLECT_INFO`, lire `files/kernel-v11/package-info.json`.
   Cette action ne lie pas le UserService. Créer la fixture V3 neuve avec
   `stage-native-qualification.py --base ...-v3` puis Python avec
   `stage-kernel-python.py --package app.foldgpt.kernelqualification.v11
   --base ...-v3 --report-version 11 --stage <STAGE_V11>` et les paramètres
   ADB/serial/output explicites. Vérifier 2447 fichiers/81 alias si l'inventaire
   officiel reste inchangé ; les hashes et noms de l'inventaire font foi.
4. Action `KERNEL_AUTHORIZE` seule : attendre le vrai résultat de la permission
   officielle. Elle ne réserve pas `attempt-started`, ne crée pas de UserService
   et ne lance pas le bootstrap. Une nouvelle application a un nouvel UID et
   ne récupère pas l'autorisation accordée à `app.foldgpt.shizukuprobe`.
5. `KERNEL_PREFLIGHT`, relever le vrai UID2000, tag/version et chemins V11.
   Préparer le snapshot avant essai incluant V11, app.foldgpt et shizukuprobe,
   avec uniquement le workspace neuf V3.
6. Un seul `KERNEL_RUN_FIXED_V11`, puis collecte avec `--package ...v11
   --base ...-v3 --report-version 11 --apk <APK_V11> --before <SNAPSHOT_V11>`.
   Trois preuves doivent concorder : RPC, superviseur/worker réels et snapshot
   indépendant. Un timeout, une quarantaine ou un résultat partiel restent des
   échecs ; aucune absence de PID ne remplace nettoyage et wait réels.

Les quatre actions utilisent le composant
`app.foldgpt.kernelqualification.v11/app.foldgpt.kernelqualification.QualificationActivity`
et des noms préfixés par `app.foldgpt.kernelqualification.v11.`.
Cette séquence n'est pas lancée par le présent travail.

## Contention du shell UID2000

La séparation Android des applications donne des UID clients distincts, mais
les UserServices Shizuku fonctionnent tous sous UID2000. La clé serveur est
`packageName + ':' + tag` (`UserServiceManager.java:109–123`, sources officielles
conservées), donc le nouveau paquet/tag ne remplace pas le record V10. La
permission est conservée par UID (`ClientManager.java:65–71`) et doit être
obtenue pour V11 avec l'API officielle. Ne pas accorder un sharedUserId ni
transférer directement la configuration Shizuku.

Le `runner.c` figé compte les threads de tout UID2000 avant fork, puis fixe
`RLIMIT_NPROC` du seul worker à `min(baseline + 2, limites héritées)`. V10 reste
compté dans la baseline. Son propre rlimit n'est pas abaissé. Le budget2 couvre
le worker principal et l'unique pthread prévu ; une création shell simultanée
peut faire échouer la création de ce thread. Inversement, une disparition shell
libère de la marge sous le plafond : ce n'est pas un quota exclusif au workspace.

Garder les budgets et refus existants. Faire une seule qualification active,
recueillir une baseline stable incluant V10, puis comparer les comptes et
éventuels refus `EAGAIN/EACCES`. Ne pas lancer un deuxième test natif, une mise
à jour du labo ou une série de commandes ADB pendant la fenêtre du worker.
Le diagnostic fixe reste borné à un worker/pthread ; cette observation ne
validera pas à elle seule un budget fiable pour du code arbitraire multi-tenant.

## Vérifications réalisées ici

Parsing Python des quatre modules modifiés/ajoutés, cinq tests PC de profils et
collisions, et `git diff --check` passent. L'Activity, ses branches d'autorisation
et le Gradle ont été relus ; ils n'ont pas encore été compilés ou exécutés sur
Android par cette préparation. Les résultats de build futurs doivent remplacer
ce statut uniquement après leur obtention.

La mise en œuvre qui a suivi cette revue a compilé et vérifié le superviseur
`KvSGBnzP` et l'APK V11, puis installé son paquet/runtime séparé. L'autorisation
Shizuku attend derrière le verrouillage du Fold ; aucun essai natif V11 n'a
commencé. Le [rapport courant](native-v11-isolated-preparation-2026-09-07.md)
donne les empreintes, contrôles et preuves exactes.
