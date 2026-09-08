# Chemins des projets : appels existants de l’interface

Analyse statique du 8 septembre 2026. Les appels ci-dessous sont ceux du client
officiel observé ; ce document ne prouve pas leur exécution ni leur persistance
sur le téléphone. Aucun asset officiel n’a été modifié pour cette analyse.

## Accéder aux services déjà initialisés

La liste CDP `work/app-transport-20260908/desktop-scripts.json` observe le module
`app://-/assets/app-initial-36a3a1b7313c.js`. Son fichier extrait exporte :

| Export | Symbole interne | Sens établi |
| --- | --- | --- |
| `SR` | `iX` | Services du canal app-host déjà initialisé. |
| `b6` | `DU` | Accesseur de `iX.projects`, utilisé par le dialogue Edit project. |
| `HWt` | `wD` | Appel du transport fetch existant vers `vscode://codex/<nom>`. |

Depuis le renderer correspondant, l’import de **cette URL observée** récupère le
module chargé. Ne pas substituer une URL d’une autre version ou exporter soi-même
un objet de l’application. `SR` doit déjà être disponible ; ne pas rappeler
l’initialisation du canal pour forcer sa présence.

```js
const client = await import('app://-/assets/app-initial-36a3a1b7313c.js');
```

Ces noms d’exports minifiés sont propres à l’asset observé. Toute mise à jour
nécessite de retrouver le nouvel asset, ses empreintes et ses exports. Les méthodes
de service sont existantes, mais ces noms d’exports ne constituent pas une API
publique garantie par OpenAI.

## Modifier les dossiers du même projet

Lecture existante :

```js
const before = await client.HWt('get-global-state', {
  params: {key: 'local-projects'}
});
```

Après vérification du vrai identifiant, du nom et de la liste complète des racines :

```js
await client.SR.projects.editLocal({
  projectId: ID_EXISTANT,
  name: NOM_OBSERVE,
  sources: RACINES_COMPLETES_VERIFIEES
});
```

`sources` est un tableau de chaînes ; il ne s’appelle pas `rootPaths` à cette
entrée. Le dialogue officiel utilise exactement `DU().editLocal({name,projectId,
sources})`. Le backend `OOe.editLocal` valide ces trois champs, déduplique les
sources, puis appelle `projectBackend.updateProject` avec `name` et `rootPaths`.
Il diffuse `global-state-updated` pour `local-projects` et
`workspace-root-options-updated`. Il ne recrée pas l’identifiant.

Avant de modifier les racines, ce backend essaie d’associer les conversations
encore non attribuées à leurs projets : `assignUnassignedThreadsBeforeProjectRootsChange`
peut lire plusieurs conversations. Une erreur à cet endroit doit rester visible.
Ce chemin n’est pas équivalent à une écriture directe de `local-projects`.

Ne pas utiliser `electron-update-workspace-root-options` pour réparer un projet
existant : ce message appelle `createOrSelectLocalProjects`, qui peut créer de
nouveaux projets. `upsertLocal` peut également créer un projet absent.

Le service retourne sans modification si l’ID n’existe plus. La résolution de
la promesse seule ne prouve donc pas la réparation : relire `local-projects`,
`workspace-root-options`, le projet moteur correspondant et la navigation réelle.
Ces opérations n’offrent pas de compare-and-swap ; coordonner les écritures.

## Répertoire des nouvelles conversations sans projet

```js
const before = await client.SR.settings.read('projectlessWorkspaceRoot');
await client.SR.settings.write('projectlessWorkspaceRoot', RACINE_CANONIQUE_VERIFIEE);
const after = await client.SR.settings.read('projectlessWorkspaceRoot');
```

Le handler fetch `set-setting` avec `{key,value}` existe aussi. La définition
accepte une chaîne absolue ou `null`. Le réglage porte `agentAccess: hidden` :
l’outil générique `settings-write` refuse les réglages qui ne sont pas
`read-write`; l’interface utilise le service `settings.write`/`set-setting`.

Le choix de dossier par l’UI passe par `projectlessWorkspace.chooseDirectory`,
qui ouvre un sélecteur et vérifie dossier réel et accès. Il n’existe pas dans ce
service un setter de chemin observé. Lorsque le coordinateur utilise directement
le setter existant de réglage, il doit avoir déjà vérifié le dossier et son
admission native. Une chaîne absolue seule ne prouve pas que le moteur y accède.

Ce réglage concerne la création future de dossiers ; il ne déplace pas les fichiers
et ne met pas à jour les conversations existantes. La méthode `settings.write`
observée écrit dans le store sans attendre explicitement un flush disque :
relire puis vérifier après fermeture/réouverture normale.

## Indices de navigation des conversations existantes

```js
await client.HWt('set-global-state', {params: {
  key: 'thread-workspace-root-hints',
  value: {[THREAD_ID_OBSERVE]: RACINE_VERIFIEE}
}});
```

Même mécanisme pour `thread-projectless-output-directories`, **avec le dossier de
sortie existant correspondant**, pas systématiquement le cwd. Le backend valide
une map chaîne → chaîne et la fusionne avec la map actuelle. Fournir uniquement
les entrées réellement vérifiées préserve les autres conversations. Il diffuse
`global-state-updated` après l’écriture. Le handler n’assure ni preuve d’existence,
ni contrôle d’identité de chemin, ni persistance du cwd moteur.

`PROJECT_ORDER` est le seul membre du set de refus direct observé (`$L` dans le main
actuellement installé, `QL` dans le main de référence). Cette constatation
n’autorise pas à modifier d’autres clés sans connaître
leur sémantique. Les IDs projectless et associations de projet restent inchangés
pour une simple réconciliation de chemin.

## Cwd du moteur et état du renderer

Conserver le protocole `thread/resume` avec cwd vérifié, puis
`thread/settings/update`, notification `thread/settings/updated`, et reprise froide
sans override. La notification fait appliquer `O9t` dans le renderer et met à jour
`conversation.cwd` ; il ne faut pas modifier manuellement son objet en mémoire.

Le helper renderer `updateThreadSettingsForNextTurn` transmet normalement
`thread/settings/update`, mais possède un fallback qui met seulement l’état UI à
jour si le moteur ne supporte pas cette méthode. Son retour seul n’est donc pas
une preuve de réglage durable. Vérifier l’événement moteur et la reprise froide.

Pour `/data/user/0/app.foldgpt/files/projects/...` et `/data/data/app.foldgpt/files/projects/...`,
établir l’identité device/inode dans l’autorité actuelle, puis changer seulement
les références. Pour un projet `/home/julien/...`, inventorier et copier les vrais
fichiers avant de reprendre la conversation. Les [règles de migration](legacy-path-repair-design-20260908.md)
restent applicables.

## Provenance locale

| Fichier analysé | SHA-256 |
| --- | --- |
| `work/app-transport-20260908/desktop-app-initial-36a3a1b7313c.js` | `6e7f7700cda7eed3ba38b20d5ec2ab4fa16333c80ed43c56e3f83bd1344d32ae` |
| `work/desktop-audit-20260908/installed-extracted/asar/.vite/build/main-C5K7o1Hr.js` | `1a12a4625ca931b86befd0c40e3ab1b17355bbb8ef87092b1d239e0439ce0d26` |

Les deux bundles renderer extraits via CDP sont égaux aux fichiers de l’archive
installée après normalisation CRLF → LF ; leurs octets Windows ne sont pas égaux
aux octets LF de l’archive. L’empreinte de l’asset initial dans l’archive vaut
`5e4b002d1b6a5cb2edef63e0e8bde74613d78124f487f054d7047744a501bcdc`.
Le main installé diffère du main de référence anciennement lu ; ses handlers
`editLocal`, globals/hints et settings ont été relus dans la copie exacte avant
confirmation de ce document. Archive installée : SHA-256
`1306be560e77fbfb68dd8b0bccac58d52396a3d445f12810a50438fb05f2e61d`.

Repères dans ces sources minifiées, offsets caractères UTF-16 à partir de zéro :
`DU` 5589235 ; dialogue `editLocal` 8765657 ; exports/services `iX` 6968580 ;
fetch `wD` 3344808 ; réglage 2167084 ; notification de réglage 2775603 ;
fallback `updateThreadSettingsForNextTurn` 3032612.
Dans le main actuellement installé : `editLocal` 2290465 ;
handler `get-global-state` 1330366 ; méthode de fusion des globals/hints
`setGlobalStateValue` 1341825 ; setter de réglage 1343574 ;
enregistrement de `projectlessWorkspace` 2595412.
Ces offsets donnent des repères de recherche dans les fichiers précisément
identifiés. L’inventaire AST séparé fournit aussi des positions structurées.
