# Diagnostic des dépendances de l’espace de travail

Ce document conserve le constat initial r31. La
[réparation FoldGPT ARM64](../workspace-dependencies.md) décrit le fournisseur
ajouté ensuite, les outils exécutés sur le téléphone et le passage prévu à
une source officielle compatible. L'archive officielle manquante n'est pas
présentée comme publiée par la création de ce paquet FoldGPT.

**L’application officielle existe bien pour Linux ARM64.** La
[documentation Linux](https://learn.chatgpt.com/docs/linux/linux-app), relue
après la capture fournie par Julien, le confirme. Le défaut étudié ici concerne
son bundle d’outils distinct, téléchargé depuis Configuration.

Le 9 septembre 2026, le diagnostic et la réparation ont été reproduits dans
Paramètres → Configuration sur le Fold avec r31/versionCode21. Le bundle
officiel est absent. Le catalogue effectivement reçu par le client ne fournit
aucune entrée Linux ARM64 ; la tentative de secours retourne HTTP 404 depuis
l’application. À ce stade du diagnostic r31, aucune correction n'était livrée.

## Résultats observés

| Contrôle | Résultat |
| --- | --- |
| Version affichée dans Configuration | Non installé |
| Bouton Diagnostiquer | Avertissement indiquant que les dépendances doivent peut-être être réparées |
| API officielle `diagnoseDependencies`, hôte `local` | `installed: false`, `bundleVersion: null`, un problème : `Codex dependencies are not installed` |
| Bouton Réinstaller | Échec `resolve_manifest`, HTTP 404, cible `linux-arm64`, avant téléchargement du bundle |
| Catalogue stable reçu | `26.904.11930` : Windows x64/ARM64, macOS x64/ARM64 et Linux x64 |
| Catalogue alpha reçu | `26.903.20932` : mêmes cinq cibles |
| Historique du catalogue reçu | 50 versions, aucune entrée `linux-aarch64` |
| État natif à 08:50:47 UTC | `ready` |

Le contrôle utilise le service officiel du client et la seule clé partagée
`codex_runtimes_config`, obtenue par abonnement puis désabonnement. Il ne lit
pas les autres configurations de compte et ne modifie pas ce catalogue.

## Cause et portée

Dans la version installée, la sélection transforme Linux/ARM64 en clé de
catalogue `linux-aarch64`. En l’absence d’entrée, elle tente :

`https://persistent.oaistatic.com/codex-primary-runtime/latest/linux-arm64/LATEST.json`

La configuration reçue ne définit aucune autre adresse de base. Le journal
de la réparation réelle identifie l’opération
`3e707cc7-8196-476e-b83a-3d046adad92f`, la cible `linux-arm64`,
`failureStage=resolve_manifest`, `retryable=false` et
`Failed to download primary runtime manifest (404 ).`.

La navigation directe depuis le navigateur intégré du PC a été refusée par
`ERR_BLOCKED_BY_CLIENT`. Une vérification HTTP distincte depuis Python sur le
PC a reçu un refus Cloudflare 403/1010. Ces deux résultats ne servent pas de
preuve supplémentaire d’un 404 ; celui-ci provient du client sur le téléphone.
L’absence de cible est établie indépendamment par son catalogue courant.
Un contrôle ultérieur avec curl et le User-Agent exact de l’installateur,
`codex-primary-runtime-installer`, reçoit également HTTP 404 depuis le PC.
Les en-têtes et le corps de cette réponse sont conservés.

Le client ARM64 et son bundle de dépendances sont deux distributions
distinctes. La présence du client, de Python Bionic ou des outils Debian ne
constitue pas une installation de ce bundle. Un paquet Windows/macOS ARM64
n’est pas compatible avec Linux/Android ; le paquet Linux x64 cible un autre
processeur. Réutiliser leur numéro de version ou fabriquer `runtime.json`
donnerait un diagnostic trompeur.

Le diagnostic officiel vérifie surtout les métadonnées et les chemins.
Une future intégration doit aussi démontrer l’exécution des outils depuis
la conversation, avec les bons chemins et l’ABI Android appropriée.

La résolution nécessite un vrai bundle compatible, ou une intégration ARM64
complète et explicitement identifiée comme telle. Aucun réglage permettant
d’acquérir ce bundle ARM64 n’a été identifié dans la configuration reçue ou
les pages officielles consultées. Cela ne prouve pas l’absence de toute
distribution future, privée ou différente de ce catalogue.
Les capacités Python déjà vérifiées et les corrections r31 du démarrage et
des notifications conservent leur portée ; ce diagnostic ne les requalifie pas.

## Vérification de la version actuelle et des liens fournis

La [documentation développeurs](https://learn.chatgpt.com/docs/developers),
les [réglages de l’application](https://learn.chatgpt.com/docs/developer-settings?surface=app)
et les [environnements locaux](https://learn.chatgpt.com/docs/environments/local-environment)
ont été ouverts dans le navigateur intégré. Ces pages décrivent les réglages,
MCP et scripts de préparation de projets ; elles ne donnent pas de manifeste
ARM64 de remplacement pour le bundle concerné. La page Linux distingue aussi
le support de l’application des exigences propres à certaines fonctionnalités.

Le dépôt APT officiel signé a été relu à 08:54:57 UTC. Son `InRelease` du
8 septembre à 23:43:45 UTC annonce **26.903.61454**, plus récent que le client
installé **26.901.41600**. La vérification utilise la clé déjà qualifiée
`3BFA0E4AE8B8CC16A2D9BA684A3B4A566C4660E4`, puis le SHA-256 et la taille de
`main/binary-arm64/Packages`. Le paquet de 376 255 202 octets téléchargé
correspond au SHA-256 signé
`e545cd78672e1313ff3f0d377772dd4ee7444400357ca85313d732da8d7e6693`.

Son extraction statique vérifie 6 796 entrées de paquet et 9 023 entrées ASAR.
L’ASAR est
`365b431dbbd7a6fcd84205066e8ff3d282fefacd88759ea69168b0ae641c5d06`.
Le fichier `src-J2PvP4xj.js` conserve la sélection `linux-aarch64`, la même
adresse de secours `latest/linux-arm64/LATEST.json` et le même mécanisme
d’échec HTTP. L’interface conserve la même couche Statsig `2096615506` pour
le catalogue. Le paquet ne contient pas de bundle primary-runtime intégré.

Cette lecture ne montre pas de correction de l’acquisition Linux ARM64 dans
la version actuelle. Le nouveau client n’a pas été installé ni exécuté :
une mise à jour seule n’est pas présentée comme une réparation testée, et
une éventuelle différence de configuration servie à cette version n’a pas
été mesurée. Les reçus sont `official-current-package.json`,
`inrelease-verify-msys.log`, `current-client/report.json` et
`installer-comparison.json`. Le premier essai GPG a refusé un chemin Windows ;
le second, avec le chemin MSYS adapté, vérifie bien la signature attendue.

## Preuves et conservation

Les reçus ciblés sont sous
`C:\Dev\ChatgptFold\work\dependencies-diagnostic-20260909` :

- `diagnose-visible-result.json`, `reinstall-result.json`, `api-diagnosis.json` ;
- `subscribed-runtime-config.json` et `manifest-summary.json` ;
- `primary-runtime.log` et `device-evidence.json` ;
- les expressions CDP et le script d’interaction avec les boutons réellement
  affichés, pour reproduire l’inspection.

L’ASAR installé conserve le SHA-256
`1306be560e77fbfb68dd8b0bccac58d52396a3d445f12810a50438fb05f2e61d`,
identique au corpus extrait utilisé pour suivre la sélection du manifeste.
Les empreintes des quatre scripts examinés sont dans `device-evidence.json`.

Aucun APK, fichier du client officiel, paramètre du runtime ou outil natif
n’a été remplacé pendant ce diagnostic. La réparation échoue avant toute
installation. Les modifications antérieures du projet sont conservées.
