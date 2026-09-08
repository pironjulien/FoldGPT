# Anciennes conversations et comparaison Local Desktop / UserLAnd

## Diagnostic actuel du Fold

Collecte en lecture seule du 8 septembre 2026, sous
`work/config-inspection-20260908/`. Le téléphone est connecté, son identifiant de
boot est inchangé depuis le lot r25. Le propriétaire natif rapporte `ready`.
Aucun redémarrage, changement de configuration ou migration de données effectué.

L'erreur effective est :

```text
failed to load configuration: project cwd is outside configuration discovery root
```

Elle apparaît notamment pendant `thread/resume` de la conversation
`01a07831-abaa-7a11-811f-1a6706c3da40`, puis pendant les lectures de configuration
associées. Julien confirme qu'elle survient en ouvrant une ancienne conversation.

- Son répertoire enregistré est
  `/home/julien/Documents/Codex/2026-09-06/dans-le-dossier-de-cette-nouvelle`.
- Le workspace du propriétaire actuel est
  `/data/user/0/app.foldgpt/files/projects`.
- Les indices de racine et de sortie des anciennes conversations pointent encore
  vers `/home/julien/Documents/Codex`.
- Le projet Python qualifié utilise déjà le nouveau répertoire natif.
- Le `config.toml` actuel a été lu en mémoire et analysé avec `tomllib` avec succès.
  Aucun contenu d'authentification n'a été collecté.

Il s'agit d'un défaut de compatibilité/migration entre les anciens chemins et la
racine de découverte native. Ce constat n'établit pas encore la correction. Il
ne justifie ni d'élargir aveuglément la racine vers `/`, ni de retirer les contrôles
de chemins, ni d'effacer les anciennes conversations.

La correction doit conserver les fichiers et l'historique, traiter explicitement
les anciens chemins et vérifier une reprise réelle. Les lectures de configuration
et les commandes dans le workspace natif doivent continuer à fonctionner.

## Sources amont relues dans le navigateur intégré

Le README de [Local Desktop](https://github.com/localdesktop/localdesktop.github.io#how-it-works)
décrit un système de fichiers Arch Linux ARM64 dans le stockage de l'application,
PRoot, un compositeur Wayland intégré utilisant le NDK Android, et une session
Xfce Wayland. Son [site officiel](https://localdesktop.github.io/) annonce une
implémentation Rust, sans root, fonctionnant dans une seule application.

Son [guide utilisateur](https://localdesktop.github.io/docs/user/getting-started/)
documente aussi des limites Android et recommande, sur Samsung, un réglage des
restrictions des processus enfants dans les options développeur. Le titre
« sans bidouille » de l'article ne signifie donc pas une compatibilité universelle
sans réglage. Aucun de ces réglages n'a été appliqué pendant cette revue.

[UserLAnd](https://github.com/CypherpunkArmory/UserLAnd) annonce des distributions
et applications Linux sans root. Son dépôt
[UserLAnd-Assets-Support](https://github.com/CypherpunkArmory/UserLAnd-Assets-Support)
documente explicitement la construction de son PRoot.

## Conséquence pour FoldGPT

FoldGPT utilise déjà Debian ARM64, PRoot et Termux:X11 pour le client desktop.
Les instructions ARM64 s'exécutent sur le processeur ; PRoot fournit une couche
de compatibilité et conserve le noyau Android. Cela n'est pas une VM, mais ce
n'est pas non plus un port complet de l'interface vers les API Android.

Les deux projets confirment la pertinence de cette base. Wayland et l'emballage
Android de Local Desktop sont des éléments concrets à comparer, sans prétendre
qu'ils résolvent automatiquement la reprise des conversations, l'exécution des
outils, l'isolation attendue par le moteur ou les mises à jour. Le langage Rust
ne confère aucun privilège supplémentaire.

Les preuves r25 de travail Python depuis la conversation restent acquises. La
reprise des anciennes conversations est maintenant un défaut identifié ;
l'autonomie après redémarrage sans PC et le lancement sans Shizuku restent à
qualifier. Cette revue ne conclut ni à une impossibilité totale ni à une
application terminée.
