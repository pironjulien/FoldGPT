# Repository layout

| Directory | Contents |
| --- | --- |
| `android/` | Android host, service, installation code and Android tests |
| `runtime/guest/` | Maintained desktop session, keyring and input bridge sources |
| `compat/desktop-sandbox/` | Desktop compatibility shim and its focused diagnostics |
| `config/` | Versioned runtime configuration and package contracts |
| `plugins/` | FoldGPT’s Android integration plugin |
| `tools/` | Build, packaging, deployment, inspection and module regression tools |
| `tests/` | Cross-module regression tests and the test guide |
| `vendor/` | Open-source dependencies and their upstream notices |
| `recovery/engine/` | Versioned source patch and provenance for the Codex integration |
| `site/` | Source of the public showcase hosted on julienpiron.fr |
| `docs/history/` | Dated engineering observations, separate from current support statements |
| `docs/releases/` | Release scope records |

## Tests are part of the product source

Keep tests that protect behavior, permissions, file integrity, installation, input ordering and session recovery. Module-specific tests stay beside the code they exercise; cross-module tests live under `tests/`. Native and Android checks have explicit prerequisites and runners. See the [test guide](../tests/README.md).

One-off CDP experiments, superseded launchers and old publication drafts have been removed from the current tree. Git history preserves them without exposing them as supported entry points.

## Local outputs

`work/`, `downloads/`, logs, Python caches and Android build outputs are ignored. Keep private captures, signing material, downloaded client packages and recovery archives out of the public source. Cache directories are disposable; verified runtime packages, source archives and original captures are not interchangeable with caches.

Do not use `git clean -fdx` on a development checkout: it would also erase ignored inputs and recovery material. Clean only known generated paths after checking for active builds.
