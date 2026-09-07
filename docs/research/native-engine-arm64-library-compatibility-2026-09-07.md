# Moteur GNU ARM64 : compatibilité statique des bibliothèques collectées

Contrôle du 2026-09-07, effectué exclusivement sur PC. Aucun binaire ARM64, chargeur ou bibliothèque n’a été exécuté, aucune compilation et aucune commande téléphone n’ont été lancées pour ce contrôle.

## Constat

Pour les deux artefacts examinés, **aucune bibliothèque `DT_NEEDED`, version de symbole requise ni import fort manquant n’a été trouvé** dans les fichiers collectés du Fold. Les dépendances transitives des cinq bibliothèques collectées satisfont également ce contrôle statique.

Cela lève l’incertitude précise concernant la présence des bibliothèques et symboles GNU requis **dans ces copies**. Cela ne démontre ni leur chargement depuis le téléphone, ni l’exécution du moteur sur Android, ni le raccordement à l’exécuteur Bionic/Shizuku.

## Entrées et preuves

Artefacts issus de `C:\Dev\ChatgptFold\downloads\engine-gnu-arm64-20260907\build-evidence\20260907T045021Z\artifacts` :

| Fichier | Taille | SHA256 recalculé |
| --- | ---: | --- |
| `codex` | 231 221 384 octets | `b7828201923a646727873bca275006148c742b1291ac8da17fd12fd222694af3` |
| `codex-code-mode-host` | 68 035 904 octets | `93bd56ad444f2e9d92a12718eb4bd928b8f7752b9ed8f9ba29323d18996e7f6b` |

Ces empreintes correspondent à celles consignées dans [la preuve de compilation](native-engine-arm64-build-2026-09-07.md).

Les cinq fichiers de `C:\Dev\ChatgptFold\downloads\engine-arm64-device-libs-20260907` ont tous une taille et une empreinte SHA256 identiques à leur entrée de [collection.json](../../downloads/engine-arm64-device-libs-20260907/collection.json). Ce sont les bibliothèques GNU collectées sous `files/debian/usr/lib/aarch64-linux-gnu/`, pas les bibliothèques système Bionic d’Android. Ce contrôle n’a pas rafraîchi leur état sur le Fold.

Le [rapport détaillé JSON](../../recovery/verification/engine-arm64-static-compatibility-20260907.json) conserve les sept chemins et empreintes, `DT_NEEDED`, versions définies/requises, chaque import résolu avec son fournisseur, ainsi que les imports faibles non résolus. Les sept sorties `*.elf.txt` de LLVM sont conservées dans le même dossier.

## Bibliothèques et versions

Les sept fichiers sont des ELF64 AArch64 little-endian. Les deux exécutables demandent exactement les mêmes quatre bibliothèques :

| Bibliothèque | Versions requises par les exécutables | Résultat sur le fichier collecté |
| --- | --- | --- |
| `libc.so.6` | `GLIBC_2.17`, `2.18`, `2.25`, `2.27`, `2.28`, `2.29`, `2.30`, `2.32`, `2.33`, `2.34`, `2.38`, `2.39` | Chaque version et chaque import correspondant trouvé ; la table des définitions contient des versions jusqu’à `GLIBC_2.41`. |
| `libm.so.6` | `GLIBC_2.17`, `2.27`, `2.29` | Chaque version et chaque import correspondant trouvé. |
| `libgcc_s.so.1` | `GCC_3.0`, `3.3`, `4.2.0` | Chaque version et chaque import correspondant trouvé. |
| `ld-linux-aarch64.so.1` | `GLIBC_2.17` | Version et import correspondants trouvés dans le chargeur collecté. |

Le contrôle ne se limite pas à comparer le numéro maximal de glibc. Par exemple, `pidfd_spawnp@GLIBC_2.39` et `pidfd_getpid@GLIBC_2.39`, requis par les deux exécutables, sont effectivement exportés par le `libc.so.6` collecté. Les imports C23 de version `GLIBC_2.38` sont également présents. Leur présence dans la bibliothèque ne prouve pas que leurs appels système réussiront sous les politiques Android.

La fermeture des dépendances reste dans les fichiers collectés : `libc` requiert le chargeur ; `libm` requiert `libc` et le chargeur ; `libgcc_s` requiert `libc`. Les besoins transitifs `GLIBC_PRIVATE`, `GLIBC_ABI_DT_RELR` et les autres versions déclarées sont présents dans les fournisseurs correspondants.

`libstdc++.so.6` a été contrôlée parce qu’elle fait partie de la collecte. Elle n’est **ni une dépendance directe ni une dépendance transitive** des deux exécutables examinés. Ses propres besoins vers `libm`, `libc` et `libgcc_s` sont satisfaits statiquement ; ses définitions incluent `GLIBCXX_3.4.33` et `CXXABI_1.3.15`.

## Imports faibles conservés comme tels

| Objet | Imports dynamiques indéfinis examinés | Imports trouvés | Imports faibles non résolus | Imports forts manquants |
| --- | ---: | ---: | ---: | ---: |
| `codex` | 344 | 331 | 13 | 0 |
| `codex-code-mode-host` | 397 | 392 | 5 | 0 |
| `libc.so.6` | 22 | 22 | 0 | 0 |
| `libm.so.6` | 15 | 12 | 3 | 0 |
| `libgcc_s.so.1` | 28 | 25 | 3 | 0 |
| `libstdc++.so.6` | 195 | 184 | 11 | 0 |
| `ld-linux-aarch64.so.1` | 0 | 0 | 0 | 0 |

Les imports non résolus portent tous le binding ELF `WEAK` et aucune version imposée. Ils comprennent notamment `posix_spawn_file_actions_addchdir`, les hooks `_ITM_*` et `__gmon_start__` ; `codex` comporte aussi des hooks optionnels OpenSSL/Zstd et `sdallocx`, et le host V8 un symbole TLS faible. Ils ne constituent pas des imports forts obligatoires manquants au chargement ELF. Leur éventuel usage à l’exécution n’a pas été testé ; le rapport ne les transforme pas en fonctionnalités démontrées.

## Limites et prochaine vérification distincte

Les deux exécutables conservent **`PT_INTERP=/lib/ld-linux-aarch64.so.1`**. La copie collectée du chargeur se trouve sous `files/debian/usr/lib/aarch64-linux-gnu/`. Le fait de posséder ce fichier ne démontre pas que le chemin absolu `/lib/ld-linux-aarch64.so.1` désigne le bon chargeur depuis le contexte de lancement prévu sur le Fold. La résolution des chemins, liens, permissions, `RPATH`/`RUNPATH` et configuration effective du chargeur doit être vérifiée dans ce contexte, séparément.

Cette preuve ne démontre pas non plus la compatibilité de tous les appels système, les permissions SELinux/seccomp, les relocations et initialisations à l’exécution, les charges par `dlopen`, les composants NSS/DNS/locales, le comportement des descendants ou l’intégration app-server → backend natif. Aucun test de ces points n’est implicitement inclus.

Les fichiers restent des exécutables GNU/glibc, avec un chargeur GNU. Ce constat ne les requalifie pas en exécutables Bionic directement pris en charge par `/system/bin/linker64`, et ne justifie aucun changement au root, au noyau, à Knox ou à l’application officielle.

## Méthode

Lecture statique avec `llvm-readelf.exe` de l’Android NDK r29, LLVM 21.0.0, depuis Windows : `--file-header --program-headers --dynamic --version-info --dyn-syms --wide`. Les fichiers ARM64 sont uniquement des entrées de cet analyseur PC.

Les sections ELF `.dynamic`, `.dynsym`, `.gnu.version`, `.gnu.version_r` et `.gnu.version_d` ont été lues pour associer chaque import versionné à son fournisseur exact et à sa version. Les imports non versionnés ont été cherchés dans l’objet et sa fermeture `DT_NEEDED`, parmi les exports externes non locaux, de version par défaut ou sans version. Les imports faibles restent distincts. Le nombre de symboles et les `DT_NEEDED` ont été recoupés avec les sorties LLVM conservées.
