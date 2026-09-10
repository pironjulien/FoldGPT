# Inspection statique du client de bureau

Ces outils lisent des copies identifiées par empreinte. Ils n’importent pas les
modules du client et n’exécutent aucun de ses scripts, builds ou installateurs.
Les sources propriétaires et les résultats détaillés restent sous `work` ; le
rapport de compatibilité et les catalogues dérivés sont dans `docs/research`.

## Extraction

`extract-client.py` extrait un paquet Debian décrit par un manifeste attendu.
`extract-asar.py` extrait une copie exacte de l’ASAR installé, dont l’empreinte doit
être fournie. Les sorties doivent être de nouveaux dossiers sous `work` :

```powershell
python tools/desktop-audit/extract-asar.py `
  --asar work/desktop-audit-20260908/installed-r2/app.asar `
  --sha256 1306be560e77fbfb68dd8b0bccac58d52396a3d445f12810a50438fb05f2e61d `
  --output work/desktop-audit-20260908/installed-extracted
```

Les entrées externes `unpacked` et les liens sont inventoriés, jamais remplacés
par un fichier fictif. Leur absence de la copie ASAR ne prouve pas leur absence
du téléphone. Les fichiers JavaScript, JSON, HTML, CSS, source maps éventuelles,
modules `.node` et WebAssembly intégrés sont extraits pour analyse ; les autres
octets restent conservés dans l’archive d’entrée. Les empreintes internes SHA-256
présentes sont vérifiées et l’archive est recontrôlée après extraction.

## Analyse syntaxique

Installer le parseur **dans le projet** sans scripts de dépendance :

```powershell
npm install --prefix work/desktop-audit-parser `
  --cache work/desktop-audit-npm-cache --ignore-scripts --no-audit --no-fund `
  --no-save --update-notifier=false acorn@8.18.0
node --test tools/desktop-audit/test-inventory.mjs
```

L’inventaire accepte plusieurs corpus indépendants. Il vérifie les octets des
sources avant et après leur analyse. Aucune erreur de parsing n’est masquée.

```powershell
node --max-old-space-size=3072 tools/desktop-audit/inventory-surfaces.mjs `
  --corpus installed=work/desktop-audit-20260908/installed-extracted/asar `
  --corpus installedExternal=work/desktop-audit-20260908/installed-files/files `
  --corpus baseline=work/desktop-audit-20260908/extracted-r2/asar `
  --corpus baselineExternal=work/desktop-audit-20260908/extracted-r2/package `
  --corpus liveInitial=work/app-transport-20260908/desktop-app-initial-36a3a1b7313c.js `
  --corpus livePrimary=work/app-transport-20260908/desktop-app-primary-804f738d362c.js `
  --output work/desktop-audit-20260908/surfaces-r4
```

Les exports/imports, handlers, services app-host, méthodes RpcTarget, messages,
réglages, routes, appels de protocole, processus, dépendances et gardes de
plateforme sont catalogués avec fichier, empreinte et position UTF-16. Les
catégories `Candidate` conservent explicitement les ambiguïtés : un nom trouvé
dans une table ou un appel n’établit pas à lui seul qu’il s’agit d’une commande.
Une branche `not supported` n’établit pas qu’elle est atteinte sur le Fold.

Le parseur enregistre aussi les occurrences dynamiques non résolues et les routes
dont le chemin est une expression. Il n’effectue ni analyse complète de flux, ni
résolution de toutes les valeurs calculées, ni désassemblage natif.

## Rapport pour le dépôt

`summarize-surfaces.py` dérive le catalogue installé à partir des preuves brutes et
d’une comparaison d’archives. Les emplacements et nombres du main et du registre
de commandes revus sont vérifiés explicitement. Un changement de version demande
une nouvelle inspection ; ces contrôles ne doivent pas être ajustés à l’aveugle.

```powershell
python tools/desktop-audit/summarize-surfaces.py `
  --analysis work/desktop-audit-20260908/surfaces-r4 `
  --installed work/desktop-audit-20260908/installed-extracted `
  --external work/desktop-audit-20260908/installed-files `
  --comparison work/desktop-audit-20260908/archive-comparison.json `
  --output work/desktop-audit-20260908/summary-r5
```

Conserver les sorties existantes lors des reprises et choisir un nouveau dossier
de sortie. L’analyse de syntaxe est distincte d’une qualification des opérations
sur Android ou d’une preuve de fonctionnement complet de FoldGPT.

Le corpus externe installé provient de la collecte séparée du programme complet.
Le résumé rapproche chaque membre ASAR `unpacked` du manifeste de cette collecte,
conserve son empreinte réelle et refuse une taille différente. Les corpus restent
distincts dans la couverture et sont réunis uniquement pour le catalogue de leur
version respective.

## Inventaire ELF

`inventory-native.py` lit les ELF avec LLVM readelf, sans les charger. Il
contrôle les 57 fichiers de chaque inventaire avant et après lecture, conserve
les chemins Windows étendus et relève architecture, interpréteur, dépendances,
versions de symboles, ABI des addons et fonctions système structurantes. Le mode
`--layout installed` accepte la collecte du téléphone et son ASAR séparé.
`native-metadata.json` exclut les dumps et extraits de chaînes propriétaires et
peut être conservé avec le rapport ; les preuves complètes restent sous `work`.

`compare-native.py` rapproche les chemins des deux versions et distingue les
hashes identiques des exigences natives identiques. Les commandes des passes
vérifiées et leurs limites figurent dans
[le rapport natif](../../docs/research/desktop-native-requirements-20260908.md).

```powershell
python -B -m unittest discover -s tools/desktop-audit -p test_inventory_native.py -v
```
