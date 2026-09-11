# Dépendances de documents sur FoldGPT

FoldGPT fournit une distribution Linux ARM64 identifiée `FoldGPT-ARM64-*`.
Elle réutilise les bibliothèques et plugins portables OpenAI avec des moteurs
Node/Python et des extensions natives Linux ARM64. Ce bundle est une adaptation
FoldGPT ; il ne se présente pas comme un téléchargement officiel Linux ARM64.
Les sections suivantes décrivent l'intégration et les observations réalisées
sur le téléphone de développement. La [matrice de compatibilité](compatibility.md)
définit les limites de la version source publique.

## Livraison vérifiée sur le Fold, 9 septembre 2026

r34/versionCode24 et le moteur corrigé sont installés sur le SM-F971B.
Le bouton **Réinstaller** termine avec `outcome=installed`, sans domaine ni
étape d'échec, en 44,918 secondes. Il installe les cinq plugins documents,
pdf, spreadsheets, presentations et template-creator. La correction du moteur
sélectionne explicitement le système de fichiers du contrôleur pour les
marketplaces locales, tout en conservant les limites des projets natifs.

Un fichier réel, `dependencies/bin/override/soffice`, a ensuite été déplacé
vers une sauvegarde conservée. Le bouton **Diagnostiquer** signale alors
`installed=false`, un problème, et le chemin absent. **Réinstaller** rétablit
le fichier d'origine en 34,515 secondes, avec son SHA-256 inchangé et les cinq
plugins toujours synchronisés. Le diagnostic revient à zéro problème.
Après arrêt propre et réouverture, le bouton **Diagnostiquer** confirme encore
`installed=true`, `problemCount=0` pour ce même paquet.

L'échange 12 dans la conversation existante **Analyser le logiciel** s'exécute
ensuite après ce redémarrage. Le modèle appelle réellement
`load_workspace_dependencies`, reçoit les cinq skills et lit leurs fichiers.
Les scripts fournis produisent une page Word de 1547 × 2002 et une diapositive
de 1200 × 900, toutes deux relues et inspectées visuellement. Les deux XLSX de
l'échange 11 sont relus avec le `openpyxl` fourni : 2, 4, 6, total enregistré
et somme recalculée 12. Tous ces appels se terminent avec le code 0.
L'échange 11 avait aussi créé et relu DOCX/PPTX/PDF/PNG et un XLSX via le vrai
RPC Artifact Tool Python/Node ; ses fichiers d'origine restent inchangés.

Les rendus sont conservés dans le projet du téléphone sous
`outputs/Validation rendus r34 _q6r4i9n`. Les copies relues sur le PC et leurs
hashes sont dans `work/dependencies-fix-20260909/r34-render-readback.json`.
La vérification finale conserve les 251 fichiers préexistants et le préfixe
d'historique de 2 495 298 octets ; le projet contient désormais 355 fichiers
et l'historique atteint 4 281 221 octets. Le propriétaire est `ready`, son PID
est présent et la clôture de la conversation est enregistrée. Le décompte de
30 processus UID au repos ne mesure pas le compteur global des phantom
processes et ne qualifie pas la stabilité prolongée.

| Composant livré | Identité |
| --- | --- |
| APK r34 | `4caf61b818bf6f7ff5b95682b7a911b84f90b6539a51357e499d328be3389114` |
| Bundle FoldGPT-ARM64-2026.09.09.2 | `88f149442eeaca10cd10b0cb7600b255866f51921e3cd3271fcf7fd17b6a878d` |
| Paquet du moteur GNU ARM64 | `494500f447ce983b3bbf6ce8e94275cd7051c2f5daa7eaf623ae39400743f9bc` |
| Patch de sources du moteur | `612a64d2960da128f468742d6bee6d6f3285040a19e65491f1dfcdc00ea49cba` |

Les cinq tests de configuration du moteur, 31 tests JVM du cycle de vie,
la vérification de l'APK et la comparaison des bibliothèques réelles du Fold
passent. Les sources figées et le paquet du moteur sont dans
`downloads/engine-gnu-arm64/20260909T111218Z-612a64d2960d`; les résultats UI,
l'essai de fichier manquant, l'APK et le bundle sont dans
`work/dependencies-fix-20260909`. Le rapport d'installation du moteur est dans
`downloads/native-engine-device-20260908/527caeb3` et conserve sa version
précédente. Le remplacement du contrôleur n'a modifié aucun octet du client
déjà adapté ; son archive ASAR officielle d'origine reste sauvegardée.

## Installation et réparation

Le client conserve son installation par manifeste : acquisition, SHA-256,
extraction temporaire, vérification, activation et synchronisation des plugins.
Le module `tools/runtime/foldgpt-workspace-provider.cjs` ajoute les vérifications
de l'architecture ELF ARM64, des fichiers critiques et de l'exécution réelle.
Les essais couvrent Node, Canvas/Sharp/Skia, Python, les documents Office, PDF,
Artifact Tool, LibreOffice/Poppler et les scripts de rendu Word/PowerPoint
effectivement fournis avec les plugins. Une erreur reste un échec.

La configuration est dans l'invité :
`/usr/local/share/foldgpt/workspace-runtime/provider.json`.
L'installation active est sous le HOME invité sélectionné :
`~/.cache/codex-runtimes/codex-primary-runtime`.
Le dernier contrôle d'exécution est conservé dans
`~/.local/state/foldgpt-workspace/last-validation.json`.
Les boutons **Diagnostiquer** et **Réinstaller** restent ceux du client.

Un adaptateur ASAR limité à un module raccorde ce fournisseur au client
26.901.41600. L'archive officielle d'origine est conservée avec son SHA-256
dans `workspace-runtime/client-backup`; une version inconnue est refusée.
Mettre à jour le client lui-même nécessite donc de vérifier son nouveau point
de raccordement. Le moteur distinct FoldGPT gère les marketplaces locales
avec le système de fichiers du client ; les demandes de projet continuent
d'utiliser leur autorité native bornée.

## Commandes du modèle

`load_workspace_dependencies` fournit les chemins physiques Android des
lanceurs `workspace-node`, `workspace-python3`, `pnpm` et des bibliothèques.
Le Python par défaut du modèle reste Bionic. Les bibliothèques GNU doivent
être utilisées avec `workspace-python3` depuis le dossier physique de la tâche.
Les lanceurs conservent arguments, cwd et codes de sortie.

Les processus auxiliaires entrent dans le même environnement GNU. Les variables
`RUNTIME_NODE`, `RUNTIME_PYTHON`, `RUNTIME_NODE_MODULES` et `RUNTIME_BIN_DIR`
utilisent les chemins invités correspondants lorsque la valeur est absente ou
désigne le chemin publié par FoldGPT. Les valeurs tierces explicites sont
préservées. Les scripts Linux retrouvent les vrais outils dans
`dependencies/bin/override`; les lanceurs de secours restent disponibles.
Le moteur LibreOffice réel gère son redémarrage normal de code 81 ; les erreurs
et crashs restent propagés.

L'exécution reste sous l'UID Android ordinaire. Aucun root Android,
déverrouillage du bootloader, changement Knox/eFuse ou affaiblissement des
protections Android n'est requis. Le contrôle natif actuel des projets refuse
encore leurs liens symboliques ; ces changements ne qualifient pas tous les
gestionnaires de paquets, tous les plugins ou les longues périodes de veille.

## Passer à une distribution officielle

Deux modes sont prévus dans le même fichier de configuration :

```json
{"schema":"foldgpt.workspace-provider.v1","source":"official-catalog"}
```

Ce mode rend la sélection au catalogue effectivement reçu par le client.
Pour un manifeste officiel explicite, utiliser `source: "official-manifest"`
avec un champ `manifestUrl` pointant vers sa véritable adresse HTTPS OpenAI.
Les origines autorisées sont `persistent.oaistatic.com` et
`oaisidekickupdates.blob.core.windows.net`. Aucune adresse de remplacement
fonctionnelle n'est inventée dans ce document.

Le manifeste doit fournir l'archive ARM64, son SHA-256 et le format de bundle 2
avec la racine `codex-primary-runtime`. Le chemin des outils et les essais
d'exécution doivent rester compatibles. Après sélection, une vraie
réinstallation doit confirmer les outils et les plugins, puis leur usage depuis
la conversation. Cette migration ne peut pas être validée de bout en bout tant
que la distribution officielle correspondante n'est pas disponible.

## Sources de construction

`build-workspace-bundle.py` relève les versions, les sources et les empreintes
des composants. `pack-workspace-bundle.py` produit l'inventaire, les fichiers
critiques, les scripts d'intégration et le manifeste FoldGPT. Les bibliothèques
natives externes proviennent des paquets Debian authentifiés installés dans
l'invité ; l'archive suppose cet environnement, ce n'est pas un rootfs autonome.
Les sources, versions et archives de cette livraison restent sous
`work/dependencies-fix-20260909`.
