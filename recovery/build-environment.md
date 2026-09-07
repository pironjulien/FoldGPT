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

Paquets Ubuntu requis par les builds utilisés :

```sh
sudo apt-get install build-essential cmake pkg-config libssl-dev libdbus-1-dev libclang-dev libasound2-dev protobuf-compiler age
```

Le build actuel utilise le NDK officiel sous `/opt/foldgpt/android-ndk-r29`,
`RUSTUP_HOME=/opt/foldgpt/rustup` et `CARGO_HOME=/opt/foldgpt/cargo`.
Les binaires Bazel, uv et DotSlash sont sous `/opt/foldgpt/tools/bin` ; leurs
archives ont été comparées aux SHA-256 des releases officielles GitHub.
Les tests du moteur sont exécutés sous le compte Linux non privilégié
`foldgpt-build`, avec le véritable Bubblewrap 0.9.0 sur le PC.
Les scripts et manifestes sous `tools/install/native`,
`tools/executor/bionic-runtime` et `tools/executor/shizuku-service` décrivent les
entrées figées et les vérifications ELF. Les répertoires de caches `.gradle`,
`.cxx`, `target`, `__pycache__` sont régénérables et exclus de l'archive. Les
répertoires Git internes sont remplacés par la récupération des dépôts et des
patchs de reprise ; l'archive conserve leurs fichiers de travail.

La signature FoldGPT utilise la clé du coffre NexusSecure, contrôlée contre le
certificat de l'APK existant. Voir `README.md` dans ce dossier.
