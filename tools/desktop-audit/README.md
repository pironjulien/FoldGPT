# Static inspection of the desktop client

> Development evidence referenced by private paths below is not part of the public source release. Use the documented test recipes to verify your own build.

These tools read fingerprinted copies. They do not import the client's modules
and run none of its scripts, builds or installers. Proprietary sources and
detailed results stay under `work`; the compatibility report and derived
catalogs are in `docs/research`.

## Extraction

`extract-client.py` extracts a Debian package described by an expected manifest.
`extract-asar.py` extracts an exact copy of the installed ASAR, whose fingerprint
must be supplied. Outputs must be new folders under `work`:

```powershell
python tools/desktop-audit/extract-asar.py `
  --asar work/desktop-audit-20260908/installed-r2/app.asar `
  --sha256 1306be560e77fbfb68dd8b0bccac58d52396a3d445f12810a50438fb05f2e61d `
  --output work/desktop-audit-20260908/installed-extracted
```

External `unpacked` entries and links are inventoried, never replaced with a
placeholder file. Their absence from the ASAR copy does not prove their absence
from the phone. JavaScript, JSON, HTML, CSS, any source maps, `.node` modules
and embedded WebAssembly are extracted for analysis; all other bytes stay in
the input archive. Any embedded SHA-256 fingerprints are verified and the
archive is rechecked after extraction.

## Syntax analysis

Install the parser **inside the project** without dependency scripts:

```powershell
npm install --prefix work/desktop-audit-parser `
  --cache work/desktop-audit-npm-cache --ignore-scripts --no-audit --no-fund `
  --no-save --update-notifier=false acorn@8.18.0
node --test tools/desktop-audit/test-inventory.mjs
```

The inventory accepts several independent corpora. It verifies the source bytes
before and after analysis. No parsing error is hidden.

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

Exports/imports, handlers, app-host services, RpcTarget methods, messages,
settings, routes, protocol calls, processes, dependencies and platform guards
are cataloged with file, fingerprint and UTF-16 position. `Candidate`
categories keep ambiguities explicit: a name found in a table or a call does
not by itself establish that it is a command. A `not supported` branch does not
establish that it is reached on the Fold.

The parser also records unresolved dynamic occurrences and routes whose path is
an expression. It performs no full data-flow analysis, no resolution of all
computed values and no native disassembly.

## Report for the repository

`summarize-surfaces.py` derives the installed catalog from the raw evidence and
an archive comparison. The locations and counts of the reviewed main and command
registry are checked explicitly. A version change requires a new inspection;
these checks must not be adjusted blindly.

```powershell
python tools/desktop-audit/summarize-surfaces.py `
  --analysis work/desktop-audit-20260908/surfaces-r4 `
  --installed work/desktop-audit-20260908/installed-extracted `
  --external work/desktop-audit-20260908/installed-files `
  --comparison work/desktop-audit-20260908/archive-comparison.json `
  --output work/desktop-audit-20260908/summary-r5
```

Keep existing outputs when resuming and choose a new output folder. Syntax
analysis is separate from qualifying operations on Android and from proving that
FoldGPT works end to end.

The installed external corpus comes from the separate collection of the full
program. The summary matches each `unpacked` ASAR member against that
collection's manifest, keeps its actual fingerprint and rejects a size mismatch.
The corpora stay separate in coverage and are combined only for the catalog of
their respective version.

## ELF inventory

`inventory-native.py` reads ELF files with LLVM readelf, without loading them. It
checks the 57 files of each inventory before and after reading, preserves
extended Windows paths and records architecture, interpreter, dependencies,
symbol versions, addon ABI and key system functions. The
`--layout installed` mode accepts the phone collection and its separate ASAR.
`native-metadata.json` excludes dumps and proprietary string extracts and can be
kept with the report; the full evidence stays under `work`.

`compare-native.py` matches paths across the two versions and distinguishes
identical hashes from identical native requirements. The commands for the
verified passes and their limits are listed in
the native report (`../../docs/research/desktop-native-requirements-20260908.md`).

```powershell
python -B -m unittest discover -s tools/desktop-audit -p test_inventory_native.py -v
```
