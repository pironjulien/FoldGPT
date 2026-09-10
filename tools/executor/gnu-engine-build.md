# Construction du contrôleur GNU ARM64 séparé

Le contrôleur qui héberge le moteur et l'interface officielle reste dans le
userspace GNU/PRoot existant. Sa cible est donc `aarch64-unknown-linux-gnu`.
Ce binaire **n'est pas Bionic**. Les outils du modèle doivent être lancés par
le backend Bionic distinct. Aucun de ces scripts n'utilise ADB ou le téléphone.

## Preuves disponibles le 8 septembre 2026

- Base moteur : `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`, Rust 1.95.0.
- La construction GNU ARM64 du 7 septembre a effectivement terminé en 18 min 08 s.
  Ses binaires correspondent à l'ancien patch `3de9c0db…`, pas au patch courant.
  Elle ne dispense donc pas de construire les corrections exportées aujourd'hui.
- Les outils GCC/G++ ARM64, binutils, CMake et Ninja étaient présents lors de
  l'inventaire PC. La prévalidation ci-dessous les relit avant chaque préparation.
- V8 doit conserver la paire officielle `ptrcomp_sandbox_release`, version
  résolue par le `Cargo.lock`. `scripts/codex_package/v8.py` du moteur vérifie
  l'archive et les bindings ensemble contre le manifeste SHA officiel.
- Le préfixe OpenSSL 3.6.3 construit précédemment est réutilisé avec vérification
  des deux archives statiques contre les empreintes déjà conservées. Les
  headers et autres entrées deviennent ensuite des entrées figées de ce build.
- Le vérificateur ELF ajouté a été exécuté le 8 septembre sur les deux vrais
  binaires historiques et les cinq bibliothèques réellement collectées du Fold.
  Tous les imports forts, noms et versions, sont résolus dans leur fermeture
  de dépendances. Aucun binaire ARM64 n'a été exécuté pour ce contrôle.
- La libc collectée provient du Debian du Fold, pas de Bionic. Les anciens
  binaires demandent au maximum `GLIBC_2.39`; la libc collectée exporte
  `GLIBC_2.41`, relu avec LLVM readelf le 8 septembre. Le nouveau contrôle devra être
  réexécuté sur les nouveaux binaires. Un passage sur les anciens ne les valide
  pas. Les bibliothèques du téléphone devront être recollectées si le rootfs
  a changé depuis cette collecte.

Rapport courant du contrôle statique :
`work/root-artifacts-20260907/arm-engine-script-static-compatibility-20260908.json`.
Les absences d'imports faibles sont listées séparément dans ce rapport.

## Commandes reproductibles

Le stockage de compilation est une exception locale prévue au dossier Windows
du projet : sources figées et sorties Cargo restent sur le disque Linux de WSL.
Le dépôt, les exports de récupération et les preuves livrables restent dans
`C:\Dev\FoldGPT`. À l'installation du poste, créer le sous-dossier dédié
au compte de compilation, sans changer le propriétaire du préfixe `/opt` :

```sh
sudo install -d -o foldgpt-build -g foldgpt-build -m 0755 /opt/foldgpt/engine-gnu-arm64/builds
```

Depuis WSL Ubuntu-24.04, utilisateur `foldgpt-build`, après l'export moteur
canonique et lorsque les sources à livrer sont arrêtées :

```sh
cd /mnt/c/Dev/FoldGPT
python3 -B tools/executor/build-gnu-engine.py prepare
```

`prepare` ne compile pas Rust. Il crée un dossier neuf sous
`/opt/foldgpt/engine-gnu-arm64/builds`, reconstitue `git archive BASE` plus le patch
exporté, vérifie les dépendances et conserve les sources/empreintes/outils sous
`downloads/engine-gnu-arm64/<date>-<patch>/`. Il imprime le chemin exact du
`build-state.json`. Le worktree et son index ne sont jamais modifiés. Aucun
script n'utilise les anciens emplacements Windows hors du dossier projet.

Le builder vérifie le montage réel avec `findmnt`, après résolution des liens,
avant de préparer les sources puis avant de compiler. Il refuse les répertoires
de sources/cache sur les montages Windows ou partagés, même avec une option
`--build-root` ou `--target-dir` explicite. Il vérifie aussi les droits d'écriture
du compte et enregistre le système de fichiers dans `build-state.json`.
Ne pas déplacer les sources d'une compilation en cours : préparer un nouvel
état sur Linux après sa fin ou son interruption, en conservant le cache Cargo.

Régression sur les vrais montages WSL, avec un dossier temporaire Linux :

```sh
TMPDIR=/opt/foldgpt/engine-gnu-arm64/builds python3 -B -m unittest discover -s tests -p 'test_gnu_engine_storage.py' -v
```

Puis, avec le chemin exact imprimé :

```sh
python3 -B tools/executor/build-gnu-engine.py build --state /chemin/imprime/build-state.json
python3 -B tools/executor/build-gnu-engine.py package --state /chemin/imprime/build-state.json
```

Le nombre de jobs reste le défaut Cargo, sauf `--jobs N` choisi selon les
ressources disponibles. Ne pas lancer un build ARM64 concurrent aux tests
globaux Rust ou aux tests de workers utilisant le même budget de processus.

La commande réelle est `cargo build --locked --target aarch64-unknown-linux-gnu
--release --timings -p codex-cli --bin codex -p codex-code-mode-host --bin
codex-code-mode-host`. Elle conserve le point d'entrée `codex app-server` et le
compagnon `codex-code-mode-host` adjacent, conformément à `install-context`.
Chaque tentative possède son propre journal et code de sortie. Après succès,
les binaires sont figés avant une éventuelle réutilisation du cache Cargo.

Le paquet contient les deux exécutables, leurs identités et la provenance des
sources. Les symboles de débogage disposent d'une archive séparée. Les deux
archives ont un manifeste SHA256, un ordre et des métadonnées déterministes.
La compilation elle-même n'est pas déclarée reproductible octet par octet.
Ce paquet est un payload de notre moteur, pas un remplacement du paquet
officiel ou de ses ressources.

## Ce qui manque encore pour le lancement réel

Le code de production `cli/src/main.rs` et `app-server/src/main.rs` n'injecte
pas encore `ExecServerLocalRuntime`. La preuve app-server v9 construit ce
runtime dans sa fixture de test. Pointer simplement `CODEX_CLI_PATH` vers la
CLI construite ne raccorde donc pas le backend natif et ne corrige pas le
problème de lancement à lui seul.

Le lanceur de production doit accepter les argv réels du client, authentifier
le transport une seule fois, construire le vrai runtime avec ses fichiers de
configuration et appeler l'app-server. Il doit préserver stdio, les arguments,
les annulations et les erreurs de lancement. Il ne doit jamais retomber sur
l'exécuteur Linux si l'initialisation native échoue. Les fixtures SSE et les
options qui désactivent des tâches de démarrage pour les tests ne sont pas un
lanceur à déployer.

Le raccordement de chemins est décrit dans
`work/root-artifacts-20260907/shared-paths-final-connection-plan.md`. Il garde
le HOME et le profil GNU du contrôleur et publie les vrais chemins du projet
et de l'IPC. Le backend Bionic doit construire son propre environnement ; les
variables de bibliothèques du contrôleur ne sont pas compatibles avec lui.

Le `CODEX_CLI_PATH` de production, le bootstrap authentifié, le partage mesuré
et le test réel depuis l'interface restent à livrer. Aucun paquet produit par
ces scripts ne doit être déclaré qualifié Android avant ces vérifications.
