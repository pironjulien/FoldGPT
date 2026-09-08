# Validation r24 sur le Fold — 8 septembre 2026

## Résultat à 16:08 UTC

**R24 est installé. La recherche native rg et PCRE2/JIT ont réussi leurs
15 cas sur le Fold ; la régression Python de six commandes passe aussi.
Chaque qualification est suivie d'une nouvelle admission et d'arrêts propres.**
Dans la conversation, Dependency Inspector a réellement téléchargé et installé
Packaging 26.3. Après les corrections issues de la revue, cinq tests passent
et deux constructions produisent le même zipapp. Après fermeture et réouverture,
les tests et l'archive existante s'exécutent de nouveau avec les résultats
attendus, sans reconstruire les sources ni réinstaller la dépendance.

Bash, Python et rg sont Android/Bionic. L'interface et le contrôleur GNU
restent sous PRoot ; aucune VM sur le téléphone. Le terminal PTY intégré est
un chantier distinct. Les [preuves r23](r23-device-validation-20260908.md)
de conversation, éditeur et deux reprises restent acquises.

## Paquet installé

| Élément | Preuve |
| --- | --- |
| Version | FoldGPT r24/versionCode14 |
| APK | `downloads/native-production-20260908/foldgpt-native-candidate-r24.apk` |
| SHA256 installé et paquet vérifié | `064b8302093361aee3c5b8bb0107dc12781fc4b63b794174a1d17144906421af` |
| Inventaire APK | 89 bibliothèques natives, 2 447 fichiers Python, 87 alias, 95 sources ; 15 fichiers de notices du toolchain rg |
| Entrées natives | `bash`, `python`, `python3`, `rg` ; 14 tests du paquet réussis, aucun ignoré |
| Signature | Signature APK v2 vérifiée, certificat de développement conservé |
| ELF rg installé | `062cbdb374009c1ded3673ff0f92d6bf0d1119cdada43f9f1a64f18d124580ca`, ARM64 avec chargeur `/system/bin/linker64` |

Sources : [vérification APK](../../work/r24-native-20260908/r24-apk-verification.json),
[tests des entrées](../../work/r24-native-20260908/r24-entrypoint-tests.json),
[signature](../../work/r24-native-20260908/r24-signature.txt) et
[installation avec relecture du hash](../../work/r24-native-20260908/r24-install.json).
Les vérificateurs PC conservent `androidExecuted=false` : les essais appareil
ci-dessous constituent des preuves séparées.

## Qualifications natives sur l'appareil

| Essai | Résultat et portée |
| --- | --- |
| [rg a0ec1f9f](../../downloads/native-ripgrep-production-device-20260908/a0ec1f9f/report.json) | 15 cas réussis : identité Android/aarch64/UID 10412, chemin/hash ELF, JIT exécuté, versions, inventaire, règles Git, Unicode, JSON/offsets, lookbehind, stdin, codes 1/2 attendus, résolution Bash et vrai pipeline |
| JIT dans ce même rapport | La sonde appelle réellement `pcre2_jit_compile` et `pcre2_jit_match` ; version runtime `10.47 2025-10-21`, `jitAvailable=1`, `jitBytes=1252`, `jitMatch=2`, contrôle Unicode/lookbehind/backreference réussi |
| Arrêt et nouvelle admission rg | Propriétaires 8696 puis 9172 fermés, attendus et ressources absentes ; boot inchangé ; `firstCyclePassed=true`, `restart.passed=true` |
| [Python 1546575d](../../downloads/native-ordinary-production-device-20260908/1546575d/report.json) | Six commandes réussies : Bash login/nonlogin, trois unittest, zipapp construit/exécuté et cache Python normal extérieur au runtime |
| Arrêt et nouvelle admission Python | Propriétaires 9361 puis 9651 fermés, attendus et ressources absentes ; boot inchangé ; les deux cycles passent |

Ces qualifications traversent le vrai propriétaire Java/Shizuku/run-as et le
protocole de production depuis un client GNU. Leur portée exclut explicitement
app-server et l'interface. Le second cycle vérifie admission et arrêt sans
connecter un nouveau client ; il ne doit pas être décrit comme une deuxième
exécution de l'ensemble des commandes.

L'entrée standard a reçu une vraie ligne, et rg a quitté sur sa première
correspondance avec le pipe encore ouvert. Le stdin fermé initialement et le
EOF d'un pipeline Bash sont aussi testés. Le protocole modèle ne fournit pas
encore la fermeture explicite après écriture :
`modelExplicitStdinEofQualified=false` reste visible.

## PCRE2 10.45 affiché et bibliothèque 10.47 liée

`rg --version` et `rg --pcre2-version` affichent réellement
`PCRE2 10.45 is available (JIT is available)`. Cet affichage ne constitue pas
une mesure dynamique de la version de la bibliothèque. La chaîne de sources
est vérifiée localement dans les sources épinglées du build, puis relue sur
GitHub aux références exactes :

1. [ripgrep 15.2.0, version.rs](https://github.com/BurntSushi/ripgrep/blob/15.2.0/crates/core/flags/doc/version.rs#L60)
   produit ce texte à partir de `pcre2::version()`.
2. [pcre2 0.2.11, ffi.rs](https://github.com/BurntSushi/rust-pcre2/blob/9f269262a71d88605c67bd3fcc8633970aa6ad81/src/ffi.rs#L31)
   renvoie `(PCRE2_MAJOR, PCRE2_MINOR)`.
3. [Bindings pcre2-sys 0.2.10](https://github.com/BurntSushi/rust-pcre2/blob/fd05026e1bf3ad62b3876cf9bd952dc742368462/pcre2-sys/src/bindings.rs#L3)
   contiennent les constantes prégénérées `10` et `45`. Elles ne sont pas
   recalculées à partir de notre bibliothèque externe.
4. [Le build.rs de ce crate](https://github.com/BurntSushi/rust-pcre2/blob/fd05026e1bf3ad62b3876cf9bd952dc742368462/pcre2-sys/build.rs#L32)
   accepte une bibliothèque externe trouvée par pkg-config. Le journal réel
   `work/native-ripgrep-20260908/build-v4/first/pcre2-sys-link.txt` sélectionne
   `static=pcre2-8` dans le préfixe construit ; son `.pc` annonce 10.47.

Le [manifeste du double build](../../work/native-ripgrep-20260908/build-v4/build.json)
lie les sources 10.47, la bibliothèque statique, rg et la sonde. La sonde native
interroge `PCRE2_CONFIG_VERSION` puis exécute le JIT sur le Fold. La différence
de texte est donc expliquée par les constantes des bindings, pas par une preuve
d'ELF substitué. La sonde reste un exécutable distinct : elle ne constitue pas
une introspection dynamique du processus rg. Les empreintes et la liaison
attestée relient les deux preuves. Aucun rebuild ni changement de version
annoncée n'a été effectué pour masquer cet écart.

## Incidents conservés et lancement de l'interface

La [première tentative 40445f18](../../downloads/native-ripgrep-production-device-20260908/40445f18/report.json)
a échoué avant acquisition : Shizuku n'a pas initialisé son Binder dans les
30 secondes. Le serveur était absent ; la cause de sa disparition n'est pas
établie. Ce rapport conserve `passed=false` et `cleanupVerified=false`, sans
lui attribuer les reçus des essais suivants. Le boot est resté inchangé.

Le lancement officiel de Shizuku a ensuite créé le serveur 8320 sous UID 2000,
observé vivant dans [le suivi du démarrage](../../work/r24-native-20260908/shizuku-start-followup.txt).
Cela rétablit cette séance ; cela ne prouve pas une reprise autonome après
reboot ni ne résout la cause de la précédente disparition.

Le [premier lancement UI](../../work/root-artifacts-20260907/native-ui-validation-20260908/r24-first-ui/report.json)
n'a pas observé de handshake dans la fenêtre de capture, alors que l'écran
était verrouillé. Après l'action Android standard `wm dismiss-keyguard`,
le [lancement suivant](../../work/root-artifacts-20260907/native-ui-validation-20260908/r24-unlocked-ui/report.json)
observe le handshake en 520 ms, avec propriétaire natif 12780. Cette remise au
premier plan n'est pas une désactivation de la sécurité du verrouillage.
Un handshake seul ne qualifie toujours pas un projet.

## Dependency Inspector : premières preuves et corrections

La [conversation collectée jusqu'à 15:43:15 UTC](../../work/r24-native-20260908/ui/conversation-dependency-5/report.json)
et ses [appels/sorties](../../work/r24-native-20260908/ui/conversation-dependency-5/events.json)
montrent les opérations réelles dans `ui-python-caae3a83d156/dependency-inspector` :

- Téléchargement de Packaging 26.3 : code 0, 129956 octets, SHA256
  `d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c`.
- Installation réelle par pip 26.2.1 dans `.deps`, puis import depuis
  `.deps/packaging/__init__.py`, version 26.3.
- Quatre unittest réussis, build zipapp code 0 ; rapports JSON et Markdown
  donnant requests compatible, urllib3 incompatible et colorama absent.
  Leur code métier 1 est conservé et distingué d'une exception.
- Zipapp de 512958 octets, SHA256
  `342db0b0b5d20a491efddd8493ac9400bf6c61898c7aa1ebe51ba217b28f4f08`,
  contenant le vrai package, METADATA et licences.

La [collecte indépendante des fichiers à 15:44:36 UTC](../../work/r24-native-20260908/ui/project-after-create/report.json)
permet de relire ces octets et conserve l'ancien `addition.py` de 89 octets,
SHA256 `f9d6616102991bd0b4debba05ced51b1d37ce447b467f76159cdb26af38da205`.
Son `executionQualified=false` est correct : les preuves d'exécution proviennent
des appels réels, pas de l'archive collectée.

La première passe a exposé puis corrigé trois erreurs : découverte de zéro
test, double déclaration de l'entrée zipapp et dépendance absente dans
l'archive. Les erreurs restent dans les traces. La revue de cette première
collecte trouve aussi des points encore ouverts à cet instant :

- La commande README `python3 -m dependency_inspector.cli` charge un module
  qui définit `main` sans l'appeler. Le zipapp appelle bien `main`, mais la
  commande source documentée doit être corrigée et réellement testée.
- `pyproject.toml` annonce `build-backend="backend"` sans fournir ce backend.
  Le build zipapp réussi ne valide pas ce contrat de packaging inexistant.
- `rg --files` ordinaire a indiqué `polluted` et listé le zipapp. La dernière
  commande a ajouté `--ignore-file .gitignore` ; elle ne démontre donc pas que
  la recherche ordinaire respecte les exclusions. [L'amont](https://github.com/BurntSushi/ripgrep/blob/15.2.0/crates/core/flags/defs.rs#L4852)
  précise que `.gitignore` exige par défaut un dépôt détecté. Il faut une
  configuration d'exclusion adaptée au vrai projet, sans faux dossier Git.
- Le test nommé `test_cli_json_stable` vérifie une sous-chaîne, sans comparer
  deux sorties JSON exactes ; la stabilité annoncée et la version installée
  invalide restent à exercer explicitement.

Ces constats portent sur la première collecte. Les échanges suivants et les
octets relus indépendamment permettent maintenant de distinguer les corrections
réelles et la portée restante :

| Point | Preuve suivante et limite |
| --- | --- |
| Commande CLI source | `cli.py` appelle désormais `main()` dans sa garde `__main__`. `validation.json` capture la commande réelle avec code 1, JSON complet et stderr vide sur l'exemple incompatible. |
| Backend absent | Le backend fictif n'est plus déclaré. Le contrat de construction documenté est le script zipapp réel ; une distribution wheel du projet lui-même n'est pas qualifiée. |
| Tests | Cinq tests passent, dont de vrais sous-processus vérifiant les codes 0/1/2 et un cas de version installée invalide. Le test nommé `stable` parse un statut JSON mais ne compare pas deux sorties complètes ; aucune preuve générale de stabilité JSON n'en est déduite. |
| Exclusions rg | Le README explique correctement l'option `--ignore-file .gitignore` hors dépôt Git. L'exclusion explicite est démontrée ; `rg --files` sans cette option liste toujours le zipapp dans ce dossier sans dépôt. |
| Zipapp reproductible | Deux constructions avec dates sources différentes ont le SHA256 `b9fb352580451e18a5c9166a3c5dc99e1988cc8110101afc9db07423f98966c1`, 133266 octets, 37 entrées triées et horodatées 1980-01-01 ; Packaging et ses trois licences sont embarqués. |

Les [sorties de la correction et des deux builds](../../work/r24-native-20260908/ui/conversation-dependency-review-2/events.json)
conservent aussi l'échec initial de `touch -d`, puis la vraie réussite
`touch -t` : `touch1=0`, `touch2=0`, `build1=0`, `build2=0`, `byte_identical=1`.
Les [résultats subprocess à 15:51:22 UTC](../../work/r24-native-20260908/ui/conversation-dependency-receipt-1/events.json)
capturent tests, CLI module, zipapp JSON et Markdown avec codes **[0, 1, 1, 1]**.
Le code 1 exprime l'incompatibilité urllib3 attendue. `unittest` écrit son
compte rendu normal dans stderr ; les trois CLI ont un stderr vide.

Le premier compte rendu textuel annonçait à tort code 0 pour la CLI source.
Le [dernier échange de correction](../../work/r24-native-20260908/ui/conversation-dependency-report-final-1/report.json)
et la [collecte finale à 16:01:27 UTC](../../work/r24-native-20260908/ui/project-after-editor-flushed/report.json)
confirment que `validation-report.txt` indique désormais code 1, distingue
l'ancienne archive de la finale et décrit correctement stderr. Son SHA256
est `f210da74e8bddc7eed9fa9fb19a10bfc031bd852f271a8cffc349eec90cb17f7`.
Les anciennes sorties erronées restent conservées.

## Fermeture, reprise et conservation des fichiers

L'[arrêt du propriétaire 12780](../../work/r24-native-20260908/ui/stop-resumed/report.json)
passe avec ressources absentes et boot inchangé. Le
[lancement suivant à 15:56 UTC](../../work/root-artifacts-20260907/native-ui-validation-20260908/r24-dependency-resume/report.json)
observe un nouveau handshake en 295 ms ; son `uiWorkflowQualified=false`
reste correct pour cette seule mesure de lancement. Le propriétaire suivant
est **4217**.

La [conversation après reprise](../../work/r24-native-20260908/ui/conversation-dependency-resume-1/events.json)
exécute réellement les cinq tests puis l'archive existante en JSON et Markdown,
sans installation ni reconstruction. `validation-resume.json` conserve les
argv, stdout/stderr et codes **[0, 1, 1]**, les empreintes recalculées du wheel
et de l'archive, et `success=true`. Les sorties métier attendues sont présentes.

La comparaison des collectes [avant fermeture](../../work/r24-native-20260908/ui/project-after-editor/report.json)
et [après reprise](../../work/r24-native-20260908/ui/project-after-resume/report.json)
retrouve les **103 fichiers précédents avec les mêmes empreintes**, plus le seul
`validation-resume.json`, soit 104 fichiers. Cette collecte reste en lecture
seule avec `executionQualified=false` : elle prouve les octets, séparément de
leur exécution dans la conversation. Le nom `project-after-editor` est une
étiquette du collecteur, sans nouvelle preuve d'édition/sauvegarde du projet
avec dépendance. La vraie sauvegarde dans l'éditeur reste démontrée par r22/r23.

La [mesure d'intégrité à 15:58:54 UTC](../../work/r24-native-20260908/integrity-afterdependency.json)
comparée à [celle de reprise du travail](../../work/r24-native-20260908/integrity-resumedwork.json)
retrouve le même boot, les mêmes propriétés contrôlées et les mêmes quatre
APK ChatGPT officiels. Boot vérifié `green`, verrouillage `1`/`locked`, bit de
garantie `0` ; le hash installé de FoldGPT est bien celui de r24. À cet instant,
4217 est `ready`, sans quarantaine : sa session est ouverte et aucun reçu de
fermeture ne lui est attribué par cette photographie. Ces observations ne
constituent pas une promesse de compatibilité avec tout firmware futur.

## PTY et limites restantes

La [sonde PTY v4a](../../work/r24-native-20260908/pty-probe-bc976fd3/report.json)
a réussi sur le Fold, y compris le signal au groupe initial via pidfd. Elle
conserve `arbitraryExecTested=false`, `descendantCleanupTested=false` et
`foldgptIntegrationTested=false`. Le candidat séparé a d'abord passé huit tests
réels Linux nonroot dans `work/native-pty-20260908/candidate-host-v5/`, puis neuf
dans `candidate-host-v6/`. Ils incluent une saturation observée des 128
notifications avant terminaison et attente/EOF. Ces résultats PC gardent leur
portée propre.

Le [backend candidat exécuté séparément sur le Fold à 16:08 UTC](../../work/native-pty-20260908/device-run-84339a6123c94addbb4c411995222350/report.json)
passe ensuite **neuf tests réels**, avec huit propriétaires natifs attendus
code 0 et indépendamment absents après fermeture. Les cas couvrent saisie
binaire et fusion stdout/stderr, taille/SIGWINCH, interruption du groupe
initial, Ctrl-C du groupe de premier plan, descendants détachés, saturation,
refus de profils incompatibles et acquittement d'interruption avant sortie.
Boot, identité/statut de la session UI préexistante et Python installé restent
inchangés. Ce candidat s'exécute dans un répertoire d'essai privé distinct :
il n'est ni installé dans l'APK r24, ni qualifié depuis le terminal UI.

La [première exécution du backend](../../work/native-pty-20260908/device-run-dad05a818083425dab0bbb830637635c/report.json)
reste en échec : huit tests passent, test03 rencontre `AttributeError` avant
d'appeler `os.pidfd_open`. La [revue des sources exactes](../../work/native-pty-20260908/android-pidfd-review.md)
montre que le CPython fourni est compilé pour API24 et omet ces bindings sous
API31. Le harnais v2 appelle les vrais symboles Bionic via ctypes, avec errno
réel et toutes les assertions conservées. Aucun appel noyau n'est simulé ;
cette correction du harnais n'est pas une modification de Python installé.

La priorité reste rg + PTY + vrai projet avec dépendance, puis une décision
explicite sur le contrôleur et l'interface natifs. Les mises à jour futures,
le fonctionnement sans PC après reboot et toutes les fonctions du produit
ne sont pas démontrés par cette passe. Le test réel du projet avec dépendance
et sa reprise ferment ce jalon fonctionnel précis ; ils ne qualifient pas le
terminal intégré ni un produit entièrement Bionic.
