# Réparation des chemins des anciennes conversations

Date : 2026-09-08. Étude PC uniquement : lecture des métadonnées collectées, du protocole Rust existant et du patch de récupération du moteur. Aucun appel téléphone, build, changement de production, migration de fichiers ou réécriture d’historique effectué. Les tests ci-dessous sont proposés, non exécutés pendant cette étude.

## Proposition minimale

**Importer les fichiers du projet ancien dans la racine native admise, puis reprendre la même conversation avec le paramètre cwd existant et enregistrer ce nouveau réglage avec thread/settings/update.** Cela utilise des mécanismes déjà présents ; le premier essai n’exige pas de réécrire le moteur ou de reconstruire un APK.

La reprise avec cwd explicite permet de franchir correctement le contrôle : elle ne le désactive pas. La persistance doit passer par l’événement ThreadSettingsApplied produit par le moteur. Il ne faut pas remplacer des chaînes dans tout le JSONL, modifier directement SQLite, créer une nouvelle conversation ni étendre discoveryRoot vers /.

Ce plan dépend encore de deux collectes ciblées : l’inventaire réel des fichiers de l’ancien projet et l’identification des champs persistants de l’interface qui conservent ses anciens chemins. Les quatre fichiers sous work/config-inspection-20260908 ne contiennent pas cet inventaire ni le schéma complet de ces préférences.

## Cause et périmètre établis

Le [diagnostic collecté](legacy-config-localdesktop-20260908.md) et [failed-session-metadata.json](../../work/config-inspection-20260908/failed-session-metadata.json) identifient :

- Conversation : 01a07831-abaa-7a11-811f-1a6706c3da40.
- Cwd enregistré : /home/julien/Documents/Codex/2026-09-06/dans-le-dossier-de-cette-nouvelle.
- Rollout conservé : files/debian/home/julien/.codex/sessions/2026/09/06/rollout-2026-09-06T19-28-36-01a07831-abaa-7a11-811f-1a6706c3da40.jsonl.
- Racine native de [native-status.json](../../work/config-inspection-20260908/native-status.json) : /data/user/0/app.foldgpt/files/projects.
- Erreur : failed to load configuration: project cwd is outside configuration discovery root.
- config.toml a été analysé correctement pendant la collecte précédente ; ce n’est pas une preuve d’erreur TOML.
- Le propriétaire était ready dans cette collecte datée. Cette étude n’en fait pas une observation actuelle du téléphone.

La garde a été relue dans [config/src/loader/mod.rs](../../work/worktrees/FoldgptEngine/codex-rs/config/src/loader/mod.rs:185), fonction load_config_layers_state_with_project_filesystem, ainsi que dans [recovery/engine/engine.patch](../../recovery/engine/engine.patch) : si le cwd ne commence pas, par composants de chemin, par la racine de découverte de l’autorité, le chargement retourne InvalidInput. Le contrat de [native-bootstrap-files.md](../../tools/executor/native-bootstrap-files.md) impose également une racine inclusive, des lectures natives réelles et le refus hors racine.

Le défaut est l’utilisation d’une ancienne adresse de projet par le nouveau backend. Rien dans les données lues ne prouve encore que le répertoire source existe toujours, qu’il est vide ou que tous ses fichiers ont déjà été migrés. Il faut l’établir avant de modifier le cwd ; créer un répertoire vide puis y pointer la conversation masquerait une perte d’accès aux fichiers.

## Mécanismes Rust déjà disponibles

Sources finales inspectées : arbre canonique work/worktrees/FoldgptEngine/codex-rs, confirmé par le coordinateur et relu directement, avec les adaptations de découverte native. git rev-parse HEAD y retourne 3d2ee51ca2d5db578f328aa75e20aa22c0197c9a ; l’arbre comprend les modifications FoldGPT exportées séparément. La première exploration d’un ancien snapshot a été remplacée par cette vérification canonique pour les mécanismes cités. Le [manifest de récupération](../../recovery/engine/manifest.json) fixe la base 3d2ee51ca2d5db578f328aa75e20aa22c0197c9a, tag rust-v0.153.4, avec le patch déclaré SHA-256 806558ded307f46b76a278c5c81131f1d90bf6a4f7f72b9f66b29416fa9357ea. Ce sont les références de source lues, pas une nouvelle attestation du binaire exécuté sur le Fold.

### Reprendre le même identifiant avec un cwd explicite

[ThreadResumeParams](../../work/worktrees/FoldgptEngine/codex-rs/app-server-protocol/src/protocol/v2/thread.rs:335) contient cwd: Option<String>, distinct de thread_id. Les options path et history ne sont pas nécessaires ici et ont des sémantiques différentes ; ne pas les fournir.

Dans [thread_resume_inner](../../work/worktrees/FoldgptEngine/codex-rs/app-server/src/request_processors/thread_processor.rs:3755), le moteur récupère d’abord le dernier cwd d’un ThreadSettingsApplied appartenant explicitement au même thread ; sinon il reprend session_cwd(). Ce chemin historique est passé comme fallback à ConfigManager::load_for_cwd. L’override cwd de la requête est séparé.

[ConfigBuilder](../../work/worktrees/FoldgptEngine/codex-rs/core/src/config/mod.rs:1450) résout :

~~~rust
let cwd_override = harness_overrides.cwd.as_deref().or(fallback_cwd.as_deref());
~~~

L’arbre canonique conserve cette priorité et fait ensuite charger les couches avec l’autorité native. Dans [ConfigManager](../../work/worktrees/FoldgptEngine/codex-rs/app-server/src/config_manager.rs:349), la racine de découverte ne sert de fallback que si aucun fallback n’existe : elle ne remplace donc pas l’ancien cwd du rollout qui a déclenché l’erreur. Un cwd explicite valide traite cette cause.

La réponse thread/resume contient le cwd effectif. **Il faut le comparer au chemin migré : une réponse sans erreur ne suffit pas.**

### Persister le nouveau cwd sans réécrire l’histoire

[ThreadSettingsUpdateParams](../../work/worktrees/FoldgptEngine/codex-rs/app-server-protocol/src/protocol/v2/thread.rs:226) possède lui aussi cwd. [thread_settings_update_inner](../../work/worktrees/FoldgptEngine/codex-rs/app-server/src/request_processors/turn_processor.rs:903) charge le thread existant, construit les sélections d’environnement et soumet Op::ThreadSettings.

[build_environment_override](../../work/worktrees/FoldgptEngine/codex-rs/app-server/src/request_processors/turn_processor.rs:689) retargete la racine égale à l’ancien cwd et conserve les autres racines. Il ne faut donc pas supposer que changer cwd corrige automatiquement toutes les racines additionnelles anciennes.

[thread_settings::apply_update](../../work/worktrees/FoldgptEngine/codex-rs/core/src/session/thread_settings.rs:88) sérialise l’application du changement et émet ThreadSettingsApplied avec thread_id. [state/extract.rs](../../work/worktrees/FoldgptEngine/codex-rs/state/src/extract.rs:126) utilise ce réglage pour la projection metadata.cwd. La reprise froide lit ce réglage avant session_cwd, ce qui permet de garder le SessionMeta d’origine intact.

Le simple resume avec override n’est pas une preuve de migration durable : le code de reconstruction d’une conversation reprise diffère du cas fork et diffère de l’émission explicite de réglages. Il faut attendre thread/settings/updated, vérifier le nouvel événement durable, puis arrêter proprement et reprendre **sans fournir cwd**.

Le traitement de thread/settings/update est asynchrone : son accusé RPC ne remplace pas l’événement de réussite ou d’erreur correspondant. Il faut conserver l’ID de requête/soumission et attendre la confirmation avant de déclarer la migration terminée.

### Limite importante : thread déjà chargé

[resume_running_thread](../../work/worktrees/FoldgptEngine/codex-rs/app-server/src/request_processors/thread_processor.rs:4178) peut ignorer les overrides pour un thread déjà chargé et observé. Il peut recréer une entrée idle non abonnée après un arrêt confirmé, mais il ne faut pas dépendre de cette condition implicite.

Pour l’essai, prendre une conversation non active et obtenir une reprise froide contrôlée. Ne pas tuer un processus partagé pour forcer ce comportement ; utiliser le cycle d’arrêt normal et confirmer sa fermeture. Si le thread est déjà chargé et son réglage modifiable, thread/settings/update est le mécanisme prévu, mais une éventuelle erreur de recharge de configuration doit rester visible. Aucun deuxième essai permissif n’est proposé.

Les sous-agents V2 appartenant à un parent ont en outre un chemin de reprise par leur propriétaire : la migration ne doit pas les traiter comme des conversations indépendantes.

### Routage existant : utile comme référence, insuffisant seul

[app_server_routing.py](../../tools/executor/app_server_routing.py) connaît thread/resume, thread/settings/update et thread/settings/updated ; il retient les emplacements seulement après réponses réussies. Il ne fabrique aucun environment pour resume et ne convertit pas l’ancien chemin avant le chargement de configuration. Son en-tête précise que l’intégration aux connexions/host RPC doit être complète avant activation.

Il ne constitue donc pas une migration déjà déployée. Ajouter une réécriture générique de chemin à ce routeur ne serait pas la correction minimale tant que la copie des fichiers et la persistance des références ne sont pas qualifiées.

## Migration de données proposée, transaction par projet

La migration doit être fondée sur le **projet**, pas sur une copie des fichiers par conversation : plusieurs conversations peuvent viser le même cwd et doivent continuer à travailler sur les mêmes fichiers.

1. **Préparer un inventaire daté en lecture seule.** Lire les métadonnées des conversations concernées, identifier le vrai répertoire correspondant dans le stockage Debian de FoldGPT, puis relever chemins relatifs, type, taille et empreinte des fichiers. Pour ce projet, la traduction attendue de la racine PRoot est files/debian/home/julien/Documents/Codex/... ; cette correspondance doit être vérifiée sur le répertoire réel, pas seulement déduite du nom.
2. **Fixer une correspondance unique ancien cwd → nouveau cwd.** Exemple proposé, encore non créé : /data/user/0/app.foldgpt/files/projects/imported-codex/2026-09-06/dans-le-dossier-de-cette-nouvelle. Valider les composants et la provenance. /home/julien/Documents/Codex-other ne doit pas être accepté comme enfant de /home/julien/Documents/Codex. Aucune normalisation ambiguë, symlink ou URI étrangère n’est convertie implicitement.
3. **Copier dans un emplacement neuf sous la racine admise.** Garder la source intégralement. Vérifier le manifeste copié avant publication du répertoire final. Refuser un conflit de destination ; une reprise idempotente ne réutilise une destination que si provenance et inventaire concordent. Vérifier que source et destination n’ont pas changé pendant la copie.
4. **Vérifier l’admission native.** Lire/canonicaliser le nouveau cwd avec l’autorité bootstrap existante. Les types et structures refusés aujourd’hui, notamment liens ou indirections Git hors racine, doivent être signalés, conservés à la source et traités explicitement ; ne pas les supprimer ou les ignorer dans un inventaire présenté comme complet.
5. **Reprendre le même threadId et persister le réglage.** Utiliser les deux appels ci-dessous via le transport app-server existant, avec des IDs RPC neufs. Ne pas changer le modèle, les politiques, la confiance ou les permissions pour faire passer la reprise.
6. **Mettre à jour les références de navigation démontrées.** L’ancienne UI a aussi des indices de racine/sortie vers /home/julien/Documents/Codex. Identifier leurs fichiers et clés exacts avant intervention ; modifier uniquement les associations de ce projet, avec sauvegarde et contrôle de concurrence. Vérifier les nouvelles requêtes config/read, la liste des tâches et l’éditeur. Les métadonnées collectées ne permettent pas ici de donner des noms de clés fiables.
7. **Fermer et reprendre sans override.** Valider le même threadId, les mêmes messages historiques, les fichiers copiés et le cwd natif. La source d’origine et le journal de migration restent conservés ; aucune suppression n’est nécessaire pour cette réparation.

Exemple de requêtes pour le futur essai, non envoyées :

~~~json
{
  "jsonrpc": "2.0",
  "id": "legacy-cwd-resume-1",
  "method": "thread/resume",
  "params": {
    "threadId": "01a07831-abaa-7a11-811f-1a6706c3da40",
    "cwd": "/data/user/0/app.foldgpt/files/projects/imported-codex/2026-09-06/dans-le-dossier-de-cette-nouvelle"
  }
}
~~~

~~~json
{
  "jsonrpc": "2.0",
  "id": "legacy-cwd-persist-1",
  "method": "thread/settings/update",
  "params": {
    "threadId": "01a07831-abaa-7a11-811f-1a6706c3da40",
    "cwd": "/data/user/0/app.foldgpt/files/projects/imported-codex/2026-09-06/dans-le-dossier-de-cette-nouvelle"
  }
}
~~~

Les racines runtime additionnelles doivent être inventoriées avant ces appels. thread/resume propose runtimeWorkspaceRoots, mais cette option ne doit être fournie que pour une liste explicite de racines toutes migrées et admises. **Changer runtimeWorkspaceRoots ne change pas discoveryRoot et n’accorde aucune autorité hors de celle-ci.** Un simple cwd-only est le cas minimal si le thread n’a que sa racine de projet.

## Préserver le sens de l’historique et de la configuration

- Garder byte pour byte le préfixe existant du rollout et les messages ; un nouveau réglage fait partie de l’historique ajouté, pas d’une falsification du passé.
- Ne pas remplacer les chemins anciens dans les messages utilisateur, résultats d’outils, artefacts, logs ou prompts enregistrés. Leur valeur historique reste correcte.
- Ne pas éditer directement la projection SQLite : le moteur doit produire le réglage et ses projections. Une modification isolée de metadata.cwd serait contredite au prochain chargement du rollout.
- Ne pas déplacer .codex, ses jetons ou la totalité du home sous projects. Les configurations du contrôleur et les fichiers du projet conservent leurs autorités distinctes.
- Réexaminer les chemins opérationnels des fichiers de projet (.codex/config.toml, scripts, instructions, dépendances locales) sans remplacement global. Les références absolues exécutables ont besoin d’une modification de projet vérifiée si elles ciblent réellement l’ancienne racine.
- Conserver le niveau de confiance et les politiques. Une clé projects.<ancien chemin> dans config.toml peut perdre sa correspondance après import ; ne pas fabriquer trusted par défaut. Le mécanisme de confiance existant résout la clé via l’autorité native.
- Laisser intact le code installé de l’application officielle. Les réglages utilisateurs et associations de projet sont des données ; ils nécessitent néanmoins un schéma connu et une sauvegarde avant écriture.

## Test PC minimal non destructif proposé

Utiliser un espace neuf sous work/legacy-path-repair-test avec une copie de données de test, un CODEX_HOME isolé, aucun identifiant utilisateur réel et un moteur déjà disponible. Aucune reconstruction ni accès OpenAI n’est nécessaire pour les opérations de métadonnées ci-dessous. Si le moteur PC disponible n’a pas exactement le patch de production, ce test doit être étiqueté protocole seulement, sans revendiquer l’admission native du Fold.

Préparer deux arbres de fixture : une racine legacy hors de la découverte et une racine projects admise. La fixture doit contenir de vrais fichiers de contenu connu, des messages historiques et un vieux cwd ; les résultats ne sont jamais présentés comme les fichiers réels de Julien.

| Étape | Résultat attendu et preuve |
| --- | --- |
| Reprise initiale sans override | Reproduit le refus hors racine avec la même garde ; aucune modification du rollout source. |
| Copie vérifiée et resume avec cwd interne | Même threadId, histoire inchangée, réponse cwd égale à la destination ; config/read interne réussit. |
| thread/settings/update puis arrêt propre | Notification de réglage effectivement appliqué, événement durable du même thread, aucun remplacement du préfixe historique. |
| Nouveau processus, resume sans cwd | Utilise la destination depuis le réglage persistant, pas session_cwd legacy ; mêmes fichiers/empreintes. |
| Nouvelle lecture config/read avec ancien cwd | Reste refusée. Le correctif n’ouvre pas l’ancienne racine. |
| Destination conflictuelle, source manquante, chemin voisin avec même préfixe textuel, lien sortant ou racine additionnelle non migrée | Refus explicite, source et métadonnées inchangées ; aucune copie partielle déclarée complète. |
| Arrêt entre copie et persistance, puis reprise du plan | Journal idempotent ; aucune seconde copie divergente, aucune perte de fichiers ni nouvel ID de conversation. |

Le test Rust existant thread_settings_update_cwd_retargets_default_environment, dans [thread_settings_update.rs](../../work/worktrees/FoldgptEngine/codex-rs/app-server/tests/suite/v2/thread_settings_update.rs:170), contrôle le cwd et les racines transmis à l’environnement après mise à jour. Son source est une référence utile, **pas un test exécuté dans cette étude** ; il n’inclut pas à lui seul toute la migration, la copie des fichiers et la reprise froide avec notre racine bootstrap.

## Preuve finale nécessaire sur le vrai défaut

Une fois le plan et la copie qualifiés par le coordinateur :

- Ouvrir la même ancienne conversation depuis l’interface habituelle, vérifier les messages et lire un fichier existant du projet importé.
- Constater des requêtes de configuration avec le nouveau cwd, sans le message hors racine.
- Effectuer une petite modification de projet dans le répertoire natif, confirmer son contenu réel, fermer normalement et rouvrir cette conversation sans paramètre de réparation.
- Vérifier que le projet Python r25 continue à fonctionner et qu’un chemin hors racine reste refusé.
- Vérifier intégrité du rollout ancien et des fichiers source conservés ; limiter les nouveaux événements au réglage et aux actions réellement effectuées.

Le succès de ces contrôles fermerait le défaut d’ancienne adresse pour ce projet. Il ne qualifierait ni automatiquement toutes les autres conversations, ni les archives à racines multiples, ni le démarrage sans Shizuku, ni le port complet de l’interface.
