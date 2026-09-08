# Copie vérifiée d’un ancien projet

`relocate.py` inventorie puis copie un seul répertoire de projet. Il conserve
l’original, refuse une destination existante et ne modifie ni les conversations,
ni SQLite, ni les réglages de l’application. Aucun accès réseau n’est utilisé.
La reprise des conversations constitue une étape distincte, décrite plus bas.

## Utilisation

Python 3.9 ou ultérieur sous Linux/Android, en utilisateur ordinaire. Les
opérations relatives aux descripteurs de répertoire, `O_NOFOLLOW` et le véritable
`renameat2(RENAME_NOREPLACE)` de la libc et du système de fichiers sont requis.
L’outil refuse l’exécution en root. Il n’émule pas une primitive indisponible.

Depuis le compte propriétaire de FoldGPT, inventorier un chemin **préalablement
observé** dans les fichiers de l’ancien environnement. Les valeurs ci-dessous
illustrent la syntaxe ; elles ne prouvent pas l’existence du projet `exemple`.

```sh
python3 relocate.py inventory \
  --source /data/data/app.foldgpt/files/debian/home/julien/Documents/Codex/exemple \
  --source-boundary /data/data/app.foldgpt/files/debian/home/julien/Documents/Codex
```

Vérifier l’inventaire réel, notamment ses chemins, fichiers et tailles. Retenir
son champ `inventorySha256`. Avec la source au repos et la racine native
préalablement vérifiée, lancer :

```sh
python3 relocate.py copy \
  --source /data/data/app.foldgpt/files/debian/home/julien/Documents/Codex/exemple \
  --source-boundary /data/data/app.foldgpt/files/debian/home/julien/Documents/Codex \
  --destination-root /data/data/app.foldgpt/files/projects \
  --name exemple-importe \
  --expected-inventory-sha256 EMPREINTE_REELLE_DE_L_INVENTAIRE
```

Le dernier argument doit être une empreinte SHA-256 hexadécimale minuscule de
64 caractères issue de l’inventaire vérifié. Les chemins absolus canoniques sont
obligatoires ; les composants `..`, `.`, les doubles séparateurs et les liens
symboliques dans les ancêtres sont refusés. Le nom de destination est un seul
composant. Les arbres source et destination doivent être distincts et disjoints.

La collecte Java du 8 septembre a canonicalisé `/data/user/0/app.foldgpt` en
`/data/data/app.foldgpt`. Ces exemples utilisent cette seconde forme ; vérifier
la racine actuellement fournie par l’application avant toute opération. Un alias
symbolique n’est pas suivi automatiquement par le copieur.

L’inventaire inclut chaque répertoire, les tailles, les empreintes SHA-256 des
fichiers et les métadonnées observées. Deux passages complets doivent concorder.
La copie utilise un nouveau dossier `.foldgpt-import-…`, vérifie à nouveau source
et destination, puis publie sans remplacement. Le contenu et l’identité du
dossier publié sont encore vérifiés avant le reçu de réussite.

Chaque résultat est du JSON sur stdout. Le code de sortie vaut `0` uniquement
pour une réussite ; une opération refusée retourne `1`. L’outil n’écrit pas de
journal automatique : conserver l’inventaire et le reçu dans les preuves du
projet, sans les confondre avec les fichiers importés.

## Préservation et limites

- Les fichiers ordinaires et répertoires vides sont copiés. Les liens symboliques,
  liens physiques de fichiers, fichiers spéciaux et entrées d’un autre propriétaire
  ou système de fichiers sont refusés, sans omission silencieuse.
- Les octets et la présence de bits exécutables sont conservés. Les modes demandés
  sont privés (`0600` ou `0700` pour les fichiers, `0700` pour les dossiers), soumis
  à l’umask. Propriétaire, groupe, horodatages, attributs étendus et ACL ne sont pas
  reproduits. Un projet qui en dépend nécessite une analyse avant import.
- Un `.jsonl` présent parmi les fichiers est copié octet pour octet comme toute
  autre donnée. L’outil ne réécrit aucun chemin dans les messages ou configurations.
  Les chemins absolus opérationnels du projet peuvent nécessiter une correction
  distincte après inspection ; les chemins historiques restent historiques.
- Les contrôles répétés détectent les changements qu’ils observent. Ils ne figent
  pas un autre processus du même utilisateur et ne garantissent pas que la source
  restera inchangée après le contrôle. Arrêter les écritures concurrentes pendant
  la migration. Cet outil n’est pas une frontière d’isolation contre un processus
  hostile du même utilisateur.
- La source n’est jamais supprimée. Une erreur après création du dossier
  intermédiaire le conserve. `retainedStage` donne le dernier chemin connu ;
  `published: true` précise que le renommage a déjà réussi, même si une vérification
  ou un `fsync` ultérieur échoue. Dans ce cas le chemin est celui de la destination
  publiée. `errno` conserve le code natif lorsqu’il existe. Une substitution de
  chemin par un autre processus peut rendre ce dernier chemin obsolète : vérifier
  les identités avant toute intervention. Aucun nettoyage ou retour arrière
  destructif n’est automatique.
- Une nouvelle tentative refuse une destination existante, même identique.
  La reprise d’une migration interrompue exige d’examiner le reçu et les fichiers
  réels ; ne pas créer une seconde copie et modifier les conversations à l’aveugle.

## Raccordement à la conversation existante

Il existe deux cas distincts. Un ancien projet `/home/julien/Documents/Codex/…`
nécessite l’inventaire et la copie réels de son dossier sous `files/debian`. Un
projet **déjà natif** enregistré sous `/data/user/0/app.foldgpt/files/projects/…`
peut désigner le même répertoire que `/data/data/app.foldgpt/files/projects/…`.
Vérifier dans l’autorité actuelle leur canonicalisation et leur identité
`(device, inode)`, puis inventorier le chemin canonique. Si l’identité concorde,
ne rien copier ou déplacer : réconcilier uniquement les références du projet et
du thread via les API ci-dessous. Des chaînes ressemblantes ne prouvent pas cette
identité. Un répertoire absent, distinct ou refusé impose un arrêt de cette
réconciliation, sans élargir la racine admise.

Références lues : arbre canonique `work/worktrees/FoldgptEngine`, base
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a` (`rust-v0.153.4`) avec les adaptations
FoldGPT. Les appels ci-dessous sont du protocole app-server existant, pas des
commandes de `relocate.py`. Aucun accès au transport UI n’est supposé découvert.

1. Lire `thread/read` et `project/read`/`project/list` par le transport existant
   afin d’obtenir les véritables identifiants, associations et racines. Garder
   les preuves antérieures, le préfixe du rollout et le projet au repos. Ne pas
   déduire un `projectId` du titre affiché.
2. Pour un projet legacy réel, copier les fichiers observés avec l’outil ; pour
   l’alias d’un projet déjà natif, conserver son dossier après preuve d’identité.
   Vérifier l’admission du chemin canonique par l’autorité native existante. Ne pas
   élargir `discoveryRoot` ou les permissions.
3. Effectuer une reprise froide du même `threadId` avec `thread/resume` et le
   `cwd` vérifié. Vérifier le cwd retourné ; un thread déjà chargé peut ignorer
   cet override. Ne pas utiliser les options `history`/`path` ou créer un fork.
4. Envoyer `thread/settings/update` avec le même `threadId` et le nouveau `cwd`.
   Attendre `thread/settings/updated`, puis vérifier la persistance ; l’accusé RPC
   seul ne prouve pas que le changement asynchrone a été appliqué. Inventorier
   séparément les éventuelles racines runtime additionnelles.
5. Pour un véritable projet app-server déjà identifié, `project/update` accepte
   une nouvelle liste `roots` sous le **même** `projectId`. Omettre `name` et
   `metadata` pour les préserver. La liste remplace toutes les racines : conserver
   les autres racines observées et ne retargeter que celles effectivement migrées.
   Cet appel ne change pas à lui seul le cwd des conversations. Le serveur retourne
   le projet mis à jour et émet `project/changed` si un changement a eu lieu.
6. Relire le projet, fermer normalement la conversation puis la reprendre sans
   override. Vérifier même `threadId`, historique conservé, nouveau cwd et accès
   réel à un fichier. Vérifier également l’éditeur et les lectures de configuration
   de l’interface habituelle. Les préférences UI supplémentaires doivent être
   identifiées explicitement avant modification.

Exemples de corps `params`, à remplir avec les valeurs vérifiées :

```json
{"threadId":"ID_EXISTANT","cwd":"/data/data/app.foldgpt/files/projects/exemple-importe"}
```

Ce même corps convient à `thread/resume` et `thread/settings/update`, avec des
identifiants RPC distincts et une vérification propre à chaque opération.

```json
{"projectId":"ID_PROJET_OBSERVE","roots":[{"path":"/data/data/app.foldgpt/files/projects/exemple-importe"}]}
```

Cet exemple `project/update` n’est correct que pour un projet ayant cette unique
racine. `ProjectUpdateParams` ne propose pas de version attendue ou compare-and-swap.
Une lecture suivie d’une écriture n’est donc pas atomique contre un autre client :
coordonner l’absence de modification concurrente et relire immédiatement avant et
après. Les mises à jour du projet et du thread sont des opérations distinctes ;
une interruption entre elles doit rester signalée comme migration incomplète.

Source : `app-server-protocol/src/protocol/v2/project.rs` (`ProjectUpdateParams`),
`app-server/src/request_processors/projects.rs` (`project_update`), et
[étude de réparation](../../../docs/research/legacy-path-repair-design-20260908.md)
pour les mécanismes de reprise et de persistance.

## Vérification

Les tests créent uniquement des fixtures sous une racine explicite du projet et
utilisent les vraies opérations du système de fichiers, notamment le renommage
sans remplacement. Ils contrôlent les octets, les liens, les collisions, les
écritures concurrentes injectées et la fermeture des descripteurs.

```sh
PYTHONDONTWRITEBYTECODE=1 \
FOLDGPT_LEGACY_TEST_ROOT=/chemin/absolu/ChatgptFold/work/legacy-projects-tests \
python3 /chemin/absolu/ChatgptFold/tools/runtime/legacy-projects/test_relocate.py
```

Le dossier de test doit déjà exister, se trouver sous le projet et être sur un
système de fichiers Linux offrant les primitives requises. WSL `/mnt/c` (DrvFS)
a refusé `renameat2(NOREPLACE)` avec `EINVAL` et `mkfifo` avec `EOPNOTSUPP` dans le
premier essai : ces erreurs ne sont pas converties en succès. La qualification
Linux PC ne vaut pas qualification Android ; celle-ci reste distincte de la
preuve de reprise d’une vraie conversation via l’interface.

Le 8 septembre 2026, **20 tests ont réussi** sous WSL Ubuntu 24.04, uid 1000,
sur une image ext4 de 64 Mio créée dans `work/legacy-projects-tests`, montée
uniquement dans ce même dossier puis démontée. Résultat, commande et empreintes
des sources : [preuve Linux](../../../recovery/verification/legacy-projects-20260908/linux-tests.json)
et [sortie complète](../../../recovery/verification/legacy-projects-20260908/linux-tests.log).
Les originaux restent sous `work/legacy-projects-tests`. Ces tests
incluent les erreurs natives, l’échec de synchronisation après publication et une
modification concurrente du contenu publié. Aucun test téléphone n’a été réalisé
par cet outil à ce stade.
