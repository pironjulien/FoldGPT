# Ce que FoldGPT retient des portages Android — 8 septembre 2026

## Décision

Conserver le moteur R5 actuel pour finir le parcours Python dans l'interface.
Réutiliser les adaptations Android individuellement, après un test de leur cause,
sans installer un fork complet ni supprimer une fonctionnalité pour compiler.
La compilation Bionic du contrôleur reste une piste concrète, distincte du défaut
de contrat r20 et du défaut de fermeture r21 constaté au retour du téléphone.

| Sujet | Preuve comparée | Décision FoldGPT |
|---|---|---|
| V8 natif Android | DioNanos publie V8 150.4.0 `ptrcomp_sandbox_release`, avec binding et archive correspondant à notre dépendance et Rust 1.95.0 | Retenir cette recette pour un build isolé ; vérifier les octets et le fonctionnement réel de V8 avant intégration. Ne pas réduire la version ou retirer la sandbox V8. |
| Base du moteur | La release wallentx `rust-v0.153.4-termux` est deux commits devant notre base officielle, sans modification du protocole app-server/exec-server dans le delta | Référence proche pour les ajustements de compilation. Elle ne contient pas notre raccordement natif FoldGPT. |
| Recette V8 wallentx | Le workflow publié télécharge V8 147.4.0/profil `release`, alors que Cargo demande 150.4.0 avec sandbox | Ne pas reprendre cette recette telle quelle ; le test `--help` ne démontre pas V8 fonctionnel. |
| Verrous Rust | Rust 1.95.0 omet Android du `cfg` des fonctions `File::lock`/`try_lock`/`unlock` utilisant flock ; le chemin Android retourne Unsupported sans syscall | Pour un contrôleur Bionic, appeler réellement `libc::flock`, puis tester contention et libération. L'erreur Rust seule ne démontre pas une absence du noyau. Notre exécuteur Python utilise déjà flock réel. |
| Terminaux PTY | Le NDK r29 exporte `openpty`/`forkpty` depuis API23 ; le Fold a UNIX98_PTYS activé | Tester l'API Bionic existante. Ne pas importer le shim qui ignore des erreurs de configuration. Une probe ARM64 a été compilée, mais pas exécutée sur Android dans cette revue. |
| DNS/TLS | Des utilisateurs de Codex Linux dans Termux résolvent leur DNS en compilant pour Bionic ; le modèle a déjà répondu dans notre scénario r20 | Piste pour un contrôleur Bionic, pas diagnostic établi de l'incident actuel. Pas de proxy ajouté par analogie. |
| Mises à jour | Les forks mettent à jour leurs propres exécutables ; notre moteur porte aussi un patch FoldGPT | Garder les applications officielles intactes et maintenir notre moteur séparé. Ne pas utiliser l'auto-updater d'un fork qui remplacerait notre intégration. |

## Références vérifiées

- [DioNanos, source examinée](https://github.com/DioNanos/codex-termux/tree/235ec42906fbeb1a5c17f0a9e596e1f86fd5a8df)
- [wallentx, release réellement publiée](https://github.com/wallentx/codex-termux/releases/tag/rust-v0.153.4-termux)
- [Delta wallentx depuis notre base](https://github.com/wallentx/codex-termux/compare/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a...f3b937747529a52ff0bc8111e1088e422e3c6cfb)
- [Rust 1.95.0, implémentation Unix des verrous](https://github.com/rust-lang/rust/blob/1.95.0/library/std/src/sys/fs/unix.rs)
- [Ticket Codex Android DNS/verrous](https://github.com/openai/codex/issues/11809)

Les rapports détaillés, extraits et empreintes se trouvent dans
`work/native-port-review-20260908/` : `README.md`, `candidate-recipe.md`,
`inputs-manifest.json`, `pty-lock-review.md`, `pty-lock/capture-verification.json`,
`dns-launch/comparison.md` et `dns-launch/source-evidence.json`. Aucun témoignage
Reddit directement vérifié n'est ajouté à ces conclusions.

## Ce qui a réellement changé lors du retour du Fold

Le téléphone avait le même boot qu'avant son absence. Une nouvelle session r20
a été préparée puis arrêtée, avec les deux reçus propres pour PID28809 et absence
réelle de ses ressources. r21 a ensuite été installé normalement, sans désinstallation.
La reprise d'activité Android a créé PID29981 ; sa fermeture avant toute connexion
du pilote a échoué, et le propriétaire est resté en quarantaine.

Cause source reproduite : `OrdinaryUidFilesBackend.close(None)` refusait une session
encore inutilisée. Le correctif accepte l'absence d'identité uniquement si aucune
session et aucun handle n'ont été acquis. La fermeture avec une identité incorrecte
après acquisition reste refusée. Le CI privé 34215637059 passe 25 commandes et
193 unittest, sans exclusion ; le premier essai CI 34215414532 est conservé comme
échec de construction de la fixture de régression, ensuite corrigée.

Le candidat r22b/versionCode12 ajoute ce correctif et un diagnostic `cleanupError`
borné, distinct de `setupError`. Son SHA256 est
`eedddbd13fa9b64a4be38e8ae2cf0a34ac91aadf48d5271cdea0f7014384b99b`.
Ses 95 sources et 87 ELF ont été vérifiés ; signature v2 identique à r21.
Les tests de diagnostic Python (7), de protocole Java (18) et d'observation Java (6)
passent. Le premier build a aussi révélé que les tests HTTPS JVM existants demandent
leur lanceur dédié `jdk.httpserver` et ne compilent pas sous le lanceur Android
Gradle global ; cet échec reste dans `gradle-package-root-r22.log`. Le build
canonique suivant et les tests JVM ciblés passent.

Ces preuves PC ne valident pas encore le projet Python depuis l'interface Android,
sa sauvegarde dans l'éditeur et sa reprise. La récupération de la quarantaine r21
doit préserver l'incident et reprendre réellement les ressources ; elle ne doit
jamais transformer cet arrêt raté en `closed/0`.

Architecture conservée : commandes Bash/Python natives Android/Bionic ; interface
et contrôleur GNU sous PRoot. Aucune VM sur le téléphone. La revue communautaire
ne constitue pas une démonstration « tout natif » du produit complet.
