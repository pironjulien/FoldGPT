# Moteur auxiliaire : compilation GNU ARM64 sur PC

## Périmètre et état

Ce contrôle construit le véritable CLI `codex` et son compagnon
`codex-code-mode-host` à partir du moteur auxiliaire. Il ne modifie ni le client
officiel ni ses fichiers, n'installe rien sur le Fold et n'active pas le runtime
natif dans l'application. L'intégration `LocalRuntime` décrite dans
`FOLDGPT-INTEGRATION.md` reste une frontière injectable sans activation de
production.

La compilation release des deux binaires a **réussi**, sortie 0, en **18 min
08 s**, fin `2026-09-07T05:13:16Z` selon le journal WSL. Le compagnon ARM64 a
réellement exécuté du JavaScript sur PC : négociation du protocole, ouverture de
session, `text(6 * 7)` donnant `42`, fermeture de session et sortie 0.

Julien a ensuite demandé l'arrêt des travaux et la sauvegarde. Le contrôle PC
déjà lancé a été collecté jusqu'à sa fin ; aucune nouvelle compilation ni probe
n'a été lancée après cette consigne. `probe_app_server.py` est préparé mais
**non exécuté** : il reste à vérifier `initialize` et `config/read` sur le serveur
issu de ce build. Aucun protocole application/modèle complet n'est revendiqué.

## Sources et preuve de correspondance

- Dépôt séparé : `C:/Dev/FoldgptEngine`.
- Base vérifiée : `rust-v0.153.4`,
  `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`.
- Patch restaurable : `recovery/engine/engine.patch`, SHA256
  `3de9c0db116c299bf091ad694ff64480d61417af45e3852b2626908ce4111504`.
- Snapshot effectivement compilé :
  `/opt/foldgpt/engine-gnu-arm64/20260907T045021Z/source`.
- Preuves Windows :
  `C:/Dev/foldgpt-engine-gnu-arm64/20260907T045021Z/`.
- Inventaire : 6 956 fichiers dans `SOURCES.json`, SHA256 du manifeste
  `d889fba0d8cdf5f6f0c6e083a05b371d1ddde9e0b95971b9f6611be7503c1d9a`.

`compare_recovery.py` reconstruit la base propre avec `git -c core.autocrlf=false
archive`, vérifie le hash du patch puis exécute `git apply --check` et `git apply`.
La comparaison exhaustive ne trouve aucun fichier ajouté/manquant ni écart de
contenu de code après normalisation des seules fins de ligne. Elle identifie
6 653 fichiers CRLF dans le checkout Windows contre LF dans l'archive Git. Le
lien `codex-rs/vendor/bubblewrap/LICENSE -> COPYING` est aussi matérialisé par
Windows en fichier texte de sept octets. Ce sont des différences de
matérialisation réelles : le snapshot compilé n'est pas identique octet pour
octet à l'archive LF. `recovery-comparison.json` conserve leur liste exhaustive.
Aucune source Rust partagée n'a été modifiée pour cette compilation.

## Chaîne de compilation

Hôte WSL Ubuntu 24.04 x86_64, compte non privilégié `foldgpt-build` ; Rust
**1.95.0**, cible **aarch64-unknown-linux-gnu**, GCC/G++ ARM64 **13.3.0**,
sysroot Ubuntu avec glibc **2.39**. Les sources restent figées ; les objets et
caches sont dans `/opt/foldgpt/engine-gnu-arm64/target`, hors OneDrive.

Le profil release du dépôt est conservé : thin LTO, quatre unités de génération
de code, informations de lignes et symboles non dépouillés. Quatre jobs Cargo
sont utilisés compte tenu des 15 GiB de RAM disponibles pour WSL. Aucun flag de
fonctionnalité n'est supprimé, aucune cible MUSL ou Bionic n'est substituée.

La CI officielle valide GNU ARM64 sur un hôte ARM64 ; les releases Linux
publiées utilisent MUSL. La présente recette constitue donc une compilation
croisée locale, et non la reproduction exacte d'un runner officiel de release.

Les outils cibles sont définis séparément des outils hôtes :

```sh
export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc
export CC_aarch64_unknown_linux_gnu=aarch64-linux-gnu-gcc
export CXX_aarch64_unknown_linux_gnu=aarch64-linux-gnu-g++
export AR_aarch64_unknown_linux_gnu=aarch64-linux-gnu-ar
cargo build --locked --target aarch64-unknown-linux-gnu --release --timings \
  -p codex-cli --bin codex \
  -p codex-code-mode-host --bin codex-code-mode-host
```

`C:/Dev/foldgpt-engine-gnu-arm64/build_engine.sh` contient l'environnement exact
et la commande complète ; `build.log` enregistre versions, hashes des entrées,
diagnostics et horodatages. `prepare_snapshot.py` et `prepare_dependencies.sh`
conservent la préparation reproductible, sans modifier les fichiers du dépôt.

## Dépendances natives

V8 **150.4.0** utilise la paire officielle GNU ARM64
`librusty_v8_ptrcomp_sandbox_release_aarch64-unknown-linux-gnu.a.gz` et
`src_binding_ptrcomp_sandbox_release_aarch64-unknown-linux-gnu.rs`, téléchargée
depuis le tag `rusty-v8-v150.4.0` d'OpenAI Codex. Les deux hashes sont vérifiés
avec le manifeste publié, comme dans `.github/actions/setup-rusty-v8/action.yml`.
Le sandbox V8 est conservé. Le compagnon lie les objets libc++ Chromium fournis
par cette archive.

GNU n'active pas OpenSSL vendored dans le manifeste du moteur. OpenSSL ARM64
**3.6.3** a donc été construit séparément depuis l'archive complète officielle,
dont le SHA256 publié est vérifié. La version correspond à celle de
`openssl-src-300.6.1+3.6.3` présente dans le lockfile. La tentative initiale depuis
cette crate a échoué car elle omet des sources de tests et de modules ; les deux
journaux d'échec sont conservés. La source complète a été utilisée pour éviter
de retirer des fonctionnalités afin de réussir le build.

La configuration OpenSSL est `linux-aarch64`, compilateur croisé, `no-shared`,
`--openssldir=/usr/lib/ssl`, puis `make -j4 build_sw` et `make install_sw`.
`AARCH64_UNKNOWN_LINUX_GNU_OPENSSL_DIR` cible cette installation privée et
`AARCH64_UNKNOWN_LINUX_GNU_OPENSSL_STATIC=1` évite une dépendance dynamique
additionnelle à `libssl`/`libcrypto`. Les providers de base/default sont intégrés.
Les chemins de modules/engines optionnels de cette installation restent des
chemins de build PC ; leur chargement dynamique personnalisé n'est pas qualifié
sur Android. Les certificats et le TLS réel du runtime final restent à vérifier.

## Vérifications et limites

Les probes utilisent **qemu-aarch64-static en mode utilisateur sur le PC**,
avec le chargeur et les bibliothèques GNU ARM64 de `/usr/aarch64-linux-gnu`.
Cela exécute les instructions des binaires produits et peut détecter une erreur
de chargement, de liaison ou de protocole. Cela ne reproduit ni One UI, ni
SELinux Samsung, ni les droits de l'UID Android, ni le comportement de PRoot.
Ce n'est pas une proposition de runtime émulé sur le téléphone.

`probe_code_mode.py` vérifie une véritable évaluation V8 et la fermeture propre.
Son premier essai avait un mauvais nom de variante attendu (`text` au lieu de
`input_text`) dans le vérificateur ; le moteur avait déjà retourné correctement
42. Cet échec de vérificateur est conservé séparément. Le second essai utilise
le schéma réel et réussit, sans modification du moteur.

`verify_engine.py` produit les ELF dépouillés, conserve les binaires non
dépouillés et les symboles, relève `PT_INTERP`, `DT_NEEDED` et `GLIBC_*`, puis
contrôle le chargement des commandes de version/aide. Les quatre probes ont
terminé avec la sortie 0 : `codex --version` donne `codex-cli 0.153.4`, puis
`codex --help`, `codex app-server --help` et `codex-code-mode-host --help`.
Les trois probes CLI conservent un avertissement : le moteur refuse de créer ses
alias PATH sous le `CODEX_HOME` temporaire placé dans `/tmp`. Les aides/version
se chargent, mais la création des alias et le lancement de leurs helpers ne sont
donc pas qualifiés par ces probes. Rien n'a été désactivé pour masquer ce refus.

Le premier transfert d'artefact a rencontré un refus de métadonnées `utime` sur
DrvFS sous le compte non privilégié. Le conditionnement est ensuite réalisé sur
le système de fichiers Linux et seuls les octets sont copiés vers Windows ; le
journal d'échec reste conservé.

## Artefacts figés et exigences ELF

Les six fichiers se trouvent dans le sous-dossier `artifacts` des preuves.
`verification.json` conserve les tailles et SHA256 des versions dépouillées,
non dépouillées et des symboles séparés.

| Binaire dépouillé | Taille | SHA256 |
| --- | ---: | --- |
| `codex` | 231 221 384 octets | `b7828201923a646727873bca275006148c742b1291ac8da17fd12fd222694af3` |
| `codex-code-mode-host` | 68 035 904 octets | `93bd56ad444f2e9d92a12718eb4bd928b8f7752b9ed8f9ba29323d18996e7f6b` |

Les deux exécutables sont des **ELF AArch64 PIE**, avec segments LOAD alignés sur
64 KiB, pile non exécutable, GNU_RELRO et liaison immédiate BIND_NOW.
Le chargeur est `/lib/ld-linux-aarch64.so.1`. Leurs `DT_NEEDED` sont exactement :

- `libgcc_s.so.1` ;
- `libm.so.6` ;
- `libc.so.6` ;
- `ld-linux-aarch64.so.1`.

Les deux requièrent des versions de symboles jusqu'à **GLIBC_2.39** ; `libgcc_s`
doit notamment fournir `GCC_3.0`, `GCC_3.3` et `GCC_4.2.0`. Ce sont des binaires
GNU/glibc, pas des ELF Bionic directement chargeables par `/system/bin/linker64`.
La compatibilité de ces exigences avec le runtime GNU effectivement déployé sur
le Fold reste à vérifier avant toute sélection du moteur auxiliaire. Les tests
utilisent glibc 2.39 côté PC et ne démontrent pas le parcours complet
application/modèle/projet Python sur le téléphone.
