# Contexte de l'environnement FoldGPT pour Codex

Le manifeste versionné `config/agent-context/foldgpt.v1.json` décrit l'hôte
Android Samsung ARM64, l'invité Debian/PRoot, les chemins de l'intégration, le
rendu CPU/GPU local et l'inférence distante du modèle choisi. Chaque capacité est bornée
par sa preuve et son état : vérifiée sur un périmètre précis, diagnostic
seulement ou indisponible. Les API Android privées, dont SMS, ne deviennent pas
des outils par cette description ; aucune nouvelle permission n'est ajoutée.

La carte distingue l'hôte du client de l'environnement de chaque outil. Un
projet distant peut exécuter ses outils sur un autre hôte ; `uname=Linux` décrit
le noyau/invité et ne suffit pas à déduire un PC. Les chemins du poste Windows
de développement ne sont pas présentés comme des chemins du téléphone.

## Commandes locales du téléphone

L'APK r34 installe `foldgpt status --logs`, `foldgpt logs` et
`foldgpt path /home/julien` dans son stockage privé. Le premier distingue
l'état enregistré du moteur de la présence actuelle de son processus ; les
compteurs portent sur les processus lisibles de l'UID de FoldGPT et sur une
fin de journal bornée. Ils ne prouvent ni une santé complète ni la marge
disponible dans le mécanisme global des phantom processes Android.

Le même raccordement expose Git, Make, Node et npm existants aux commandes
du modèle. Bash/Python restent natifs Android ; les outils GNU/Linux utilisent
PRoot et le même UID Android, avec le dossier physique du projet conservé.
Les lanceurs sont dans `files/foldgpt-tools/bin`, distincts du runtime natif
vérifié. Le service raccorde leur PATH
aux profils `.profile` et `.bashrc` du HOME natif sélectionné : l'environnement
de l'exécuteur est distinct de celui de l'interface. Le bloc géré préserve les
réglages existants et refuse les fichiers ambigus. Aucun démon n'est ajouté.
Le service rafraîchit les liens vers l'APK à chaque démarrage. Un processus
lancé sans charger de profil doit recevoir ce PATH ou le chemin absolu de la
commande ; le contexte décrit explicitement cet emplacement.

Le pont utilise `core.createObject=rename` via l'environnement Git : Android
refuse la création de liens physiques dans ce stockage. PRoot ne reçoit pas
`--link2symlink` pour ces outils, car les alias artificiels ainsi produits dans
les objets Git empêchent la validation native du workspace à la relance. Cette
configuration ne change aucun fichier Git personnel et ne relâche pas le
contrôle des liens du moteur. Les projets comportant volontairement des liens
symboliques restent soumis aux limites de ce contrôle ; cette livraison ne
qualifie pas tous les gestionnaires de paquets ou structures de projets.

La révision `2026-09-09.4` inclut les limites demandées par Julien : travail
autonome dans le périmètre demandé, préservation des projets/historiques/accès,
aucun root Android, déverrouillage, flash, changement de Knox/eFuse ou
affaiblissement des protections Android. Les instructions guident le modèle ;
l'UID ordinaire et les protections Android restent les limites techniques.
Elles ne certifient pas les conditions de garantie du constructeur.

Les dépendances de documents utilisent désormais le fournisseur
[FoldGPT Linux ARM64](workspace-dependencies.md), identifié séparément du
catalogue officiel. `load_workspace_dependencies` publie les chemins Android
des lanceurs `workspace-node`, `workspace-python3` et des bibliothèques. Les
scripts invités reçoivent leurs chemins GNU via `RUNTIME_NODE`,
`RUNTIME_PYTHON`, `RUNTIME_NODE_MODULES` et `RUNTIME_BIN_DIR` ; les valeurs
explicites étrangères à FoldGPT restent conservées. Le Python par défaut
reste Bionic, sans injection de modules GNU dans cet interpréteur.

Le paquet `FoldGPT-ARM64-2026.09.09.2` exécute ses contrôles Node/Python,
LibreOffice/Poppler et scripts de rendu Word/PowerPoint sur le Fold. Le
manifeste de contexte conserve un statut prudent `diagnostic-only` pour la
capacité entière : les résultats datés ne qualifient pas tous les usages des
bibliothèques. Le diagnostic des fichiers et l'installation complète des
plugins sont des contrôles distincts ; consulter les preuves de livraison
dans le document lié, et le résultat de la réinstallation réelle.

## Point de raccordement officiel

La [documentation officielle AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
a été effectivement ouverte par l'intégrateur dans le navigateur intégré de
Codex le 2026-09-06. Codex recherche globalement dans `CODEX_HOME`, par défaut
`~/.codex`, le premier fichier non vide entre `AGENTS.override.md` et
`AGENTS.md`. Les instructions des projets s'ajoutent ensuite selon leur
hiérarchie. La documentation indique une limite combinée par défaut de 32 KiB
(`project_doc_max_bytes`) et recommande une nouvelle session pour les
instructions devenues obsolètes.

Le code source officiel conservé dans
`downloads/isolation-codex/codex-rs/core/src/agents_md.rs` confirme la priorité
des fichiers et l'assemblage des instructions. Le fragment
`context/user_instructions.rs` utilise le rôle `user` et la catégorie
`agents_md.instructions`. Ce raccordement ne remplace pas les instructions
système ou développeur du client et ne requiert ni patch de binaire ni option
de modèle expérimentale.

Ce mécanisme concerne les sessions Codex qui chargent ce profil. Il n'établit
pas que les conversations ChatGPT cloud visibles dans la même application
reçoivent le contexte. Aucun prompt, historique ou paramètre protégé d'une
session déjà créée n'est modifié.

## Génération et synchronisation

`tools/context/foldgpt_agent_context.py` prend une racine invitée explicite,
lit uniquement la sélection `/etc/foldgpt-user`, les entrées publiques passwd
et group, et vérifie le compte nonroot et son home réel. Il n'impose ni
`/home/julien` ni `/home/foldgpt` : le chemin vient du contrat d'identité actuel.
Exécuté dans l'invité avec `--guest-root /`, il exige aussi le UID/GID nonroot
et le HOME du compte sélectionné.

Le générateur sélectionne le fichier global réellement prioritaire, préserve
octet pour octet les instructions extérieures à son bloc délimité et refuse
les marqueurs ambigus, liens symboliques, liens physiques ou fichiers trop
grands. Un verrou sérialise ses écritures. Le manifeste résolu est publié sous
`CODEX_HOME/foldgpt/environment-<sha256>.json`, puis le bloc AGENTS référence
ce chemin et ce hash. Les fichiers sont forcés et publiés atomiquement ; un
second passage inchangé ne remplace pas l'inode AGENTS. Les anciens manifestes
adressés par leur contenu sont conservés. Ce contrat ne prétend pas isoler un
processus hostile de même UID ni sérialiser un éditeur qui ignore le verrou.

Le manifeste résolu contient le compte et le CODEX_HOME ciblés, aucun compte
OpenAI, jeton, message ou donnée Android privée. `config.toml`, les instructions
personnelles hors bloc et les binaires officiels restent intacts. Une collision
de manifeste, un fichier étranger ou une erreur d'identité échoue explicitement.

Depuis le compte invité déjà provisionné :

```bash
python3 -B /usr/local/lib/foldgpt/foldgpt_agent_context.py \
  --guest-root / \
  --manifest /usr/local/share/foldgpt/agent-environment.v1.json
```

Si le client utilise un autre CODEX_HOME, passer son chemin invité absolu réel
avec `--codex-home`. `--check` exige des fichiers déjà synchronisés et ne crée
pas de nouveau verrou ou manifeste. Le rapport donne les chemins ciblés et
les SHA-256 effectivement relus ; `modelDeliveryVerified` reste toujours
`false`, car une écriture disque n'est pas une preuve de réception par un modèle.

## Raccordement livré au lancement et au bundle

`foldgpt-session.sh` appelle le générateur avant le coffre et avant `chatgpt`,
en conservant un éventuel CODEX_HOME explicite. Son `set -e` rend une erreur
de synchronisation visible comme un échec de lancement ; il ne poursuit pas
silencieusement avec une description corrompue. L'intégrateur doit déployer le
générateur et le manifeste avant le lanceur qui les appelle.

Le bundle invité inclut désormais les deux sources publiques supplémentaires :

- `/usr/local/lib/foldgpt/foldgpt_agent_context.py` ;
- `/usr/local/share/foldgpt/agent-environment.v1.json`.

Il ne contient aucun home ni fichier AGENTS personnel préfabriqué. Les nouvelles
sources changent naturellement le hash du prochain bundle. Les bundles,
paquets et preuves v3 existants ne sont ni réécrits ni réautorisés.

La liste positive Java sélectionne maintenant le contrat exact v1 ou v2.
La nouvelle révision v2 ajoute ces deux fichiers ; l'ancien contrat et les
anciennes preuves restent conservés. Les deux vrais conteneurs ont été
préparés et rouverts dans des stages Linux distincts ; cela ne qualifie pas
une préparation Android v2. Voir [la révision inactive](install/inactive-agent-context.md).

## Vérification et limites actuelles

Huit tests Linux sans privilèges vérifient le compte réel du fixture, la
sélection override, le manifeste relu, les chemins, la préservation des
instructions et de `config.toml`, l'idempotence, les mises à jour, les refus
de liens, les limites de taille et les incohérences. Quatorze tests du bundle
passent, dont la présence des nouvelles sources réelles et du raccordement
avant lancement. `bash -n foldgpt-session.sh` passe.

```bash
python3 -B tools/context/test_foldgpt_agent_context.py
python3 -B tools/install/test_guest_bundle.py
```

Ces tests ne sont pas une preuve modèle. L'intégrateur a ensuite déployé et
relu le contexte dans le vrai profil `/home/julien/.codex`, puis exécuté une
nouvelle tâche depuis l'interface officielle du Fold avec **5.6 Luna**.
Le message de test ne nommait ni Android, ni Samsung, ni le chemin attendu.
La réponse identifie le Samsung SM-F971B, Android API 37, Debian/PRoot, le GPU
Adreno et l'inférence distante, puis donne le manifeste exact.

La collecte du seul rollout de cette tâche confirme le bloc AGENTS exact au
rôle `user`, le modèle effectif `gpt-5.6-luna`, le message initial, la réponse
finale et la clôture du tour, sans appel d'outil. Le premier essai CLI Astra
refusé par le compte reste un échec conservé ; il n'a pas été requalifié.
La révision `.2` ne fixe aucun modèle et a passé une seconde tâche réelle.

| Identité de la révision `.2` vérifiée | Valeur |
| --- | --- |
| Manifeste résolu | `d4ad1cfb06502aaf509d4e4e419e3c209c13ad84abb0a15c64eb32e5d1cc7055` |
| Fichier global AGENTS | `5dc0dc186a02b03e10a0a71fb511f63659aeb901763afcba8a05fb6aeaff61e7` |
| Rollout de la tâche | `8bda9499a536d26378a10b1c5224cfcbe2ce504df11cf1018753f6db5c01f3fb` |

Le déploiement est conservé sous
`downloads/context/android-a09bc9bcf39b411791c24778dfdf6d05`, la preuve Desktop
sous `downloads/context/desktop-7a56db56d81047da8b48ec99d16e48a3`.
`tools/context/collect-ui-context.py` conserve un rapport borné et son propre
code, sans exporter les autres conversations ni les identifiants du compte.
L'ancien essai de collecteur rejetait le vrai suffixe newline et la phase
`final_answer` du client ; ce rapport FAIL est conservé séparément.

Cette preuve porte sur la transmission du contexte dans une nouvelle tâche
Codex locale. Elle n'accorde aucune API Android et ne valide ni les commandes
protégées, ni les anciennes sessions, ni les conversations ChatGPT cloud.
