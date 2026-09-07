# Environnement de compilation du checkpoint

Projets locaux : `C:\Dev\ChatgptFold` et `C:\Dev\FoldgptEngine`.
Les sources sont dans Git ; l'archive privée conserve les dépendances et les
résultats locaux. Les installations globales suivantes se réinstallent sur le
PC de reprise et ne font pas partie de l'archive du projet.

| Outil | Version utilisée |
| --- | --- |
| JDK Windows | Microsoft OpenJDK 21.0.12.8 |
| Android SDK | Platform API 37, build-tools 36.0.0 |
| Android NDK | r29, `29.0.14206865` |
| Gradle | 9.7.1 |
| AGP du service Shizuku | 9.3.1 |
| Python Windows | 3.14 |
| Distribution de build Linux sur PC | WSL Ubuntu 24.04 |
| Python Linux pour les tests du lanceur | CPython 3.12.3, en-têtes `python3.12-dev` |
| JDK Linux pour les tests JNI | OpenJDK 17.0.20 |
| Rust du moteur séparé | 1.95.0, avec rustfmt et clippy |
| just Linux | 1.58.0 |
| cargo-nextest Linux | 0.9.143 |
| Bazel Linux | 9.0.0, imposé par le moteur |
| uv Linux | 0.12.10 |
| DotSlash Linux | 0.5.9 |
| age Windows / Ubuntu | 1.3.1 / 1.1.1 |
| gitleaks | 8.30.1 |

Le Linux de compilation est uniquement sur le PC. Il ne représente pas une
machine virtuelle installée sur le Fold.

Le complément v8 ajoute le build **GNU ARM64** du moteur auxiliaire : GCC/G++
croisés 13.3.0, cible Rust `aarch64-unknown-linux-gnu`, sysroot glibc 2.39,
OpenSSL statique 3.6.3 et la paire V8 150.4.0 avec sandbox. Les scripts exacts,
preuves, binaires/symboles et dépendances sont sous
`downloads/engine-gnu-arm64-20260907` après restauration. Le dossier
`build-evidence` contient `prepare_snapshot.py`, `prepare_dependencies.sh`,
`build_engine.sh` et les vérificateurs. Les chemins de ces scripts sont ceux du
PC de build (`/opt/foldgpt/engine-gnu-arm64`, `C:/Dev/FoldgptEngine`).
`qemu-aarch64-static` sert uniquement aux contrôles CPU sur PC. La qualification
avec le runtime GNU du Fold reste à faire ; voir le
[rapport du build](../docs/research/native-engine-arm64-build-2026-09-07.md).

Paquets Ubuntu requis par les builds utilisés :

```sh
sudo apt-get install build-essential cmake pkg-config libssl-dev libdbus-1-dev libclang-dev libasound2-dev protobuf-compiler age python3.12-dev openjdk-17-jdk-headless bubblewrap git unzip
```

Le build actuel utilise le NDK officiel **Linux** sous `/opt/foldgpt/android-ndk-r29`,
`RUSTUP_HOME=/opt/foldgpt/rustup` et `CARGO_HOME=/opt/foldgpt/cargo`.
Les scripts de cross-compilation Bionic utilisent son compilateur
`linux-x86_64/bin/aarch64-linux-android35-clang`. Le build Gradle lancé sur
Windows utilise le NDK Windows de même révision ; ces deux installations ne
sont pas interchangeables.
Les binaires Bazel, uv et DotSlash sont sous `/opt/foldgpt/tools/bin` ; leurs
archives ont été comparées aux SHA-256 des releases officielles GitHub.
Les tests du moteur sont exécutés sous le compte Linux non privilégié
`foldgpt-build`, avec le véritable Bubblewrap 0.9.0 sur le PC.
Les tests du superviseur, de sa façade et du transport JNI emploient aussi
le compte non privilégié `nobody`, UID/GID 65534. Pour ce compte sans shell
de connexion, utiliser `wsl.exe -d Ubuntu-24.04 -u nobody --exec ...`.
`verify-native-host.py` impose cet UID et compile avec le JDK Linux ;
`verify-python-cli-host.py` utilise les en-têtes et la bibliothèque du Python
Linux qui le lance. Ces contrôles PC ne qualifient pas les politiques Android.
Les scripts et manifestes sous `tools/install/native`,
`tools/executor/bionic-runtime` et `tools/executor/shizuku-service` décrivent les
entrées figées et les vérifications ELF. Les répertoires de caches `.gradle`,
`.cxx`, `target`, `__pycache__` sont régénérables et exclus de l'archive. Les
répertoires Git internes sont remplacés par la récupération des dépôts et des
patchs de reprise ; l'archive conserve leurs fichiers de travail.

Pour reprendre la qualification Android, conserver également les stages et
les APK figés dans le complément de récupération correspondant. Les stages
`tools/executor/shizuku-service/build/qualification-stage` et
`tools/executor/shizuku-lab/build/kernel-stage`, ainsi que
`tools/executor/shizuku-lab/build/frozen-transport-jni`, sont ignorés par Git.
Ils ne seront donc pas recréés par un clone seul. La procédure détaillée se
trouve dans `tools/executor/shizuku-lab/KERNEL-QUALIFICATION.md` ; les versions
de sources et les empreintes doivent correspondre à l'APK choisi.

Le CLI Python de qualification contient son préfixe Android de déploiement à
la compilation. Son petit build WSL et ses preuves doivent être conservés
séparément des sources du projet. Après toute installation ou mise à jour
du paquet diagnostique, relire `nativeLibraryDir` via PackageManager et
reconstruire les alias du runtime avec les outils de staging ; les chemins
`/data/app/...` d'une ancienne archive sont uniquement historiques. La reprise
sur un autre PC n'autorise pas à effacer une réservation d'essai, un marqueur
de broker ou une preuve sur le téléphone.

`hydrate-project.py` exige une destination encore absente pour chaque racine
ignorée qu'il copie, y compris `downloads/` et les dossiers `build/`. Un
complément ne doit pas être réhydraté aveuglément sur ces racines déjà
restaurées. Le restaurer à part, puis ne fusionner que les fichiers absents,
en acceptant les fichiers déjà présents seulement si leurs octets et leur
type sont identiques ; refuser toute collision différente et tout remplacement
de source suivie ou de sous-module.

La signature FoldGPT utilise la clé du coffre NexusSecure, contrôlée contre le
certificat de l'APK existant. Voir `README.md` dans ce dossier.
