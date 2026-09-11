# FoldGPT

ChatGPT Desktop and Codex on Galaxy Z Fold, with local project files and development tools. No root or bootloader unlock required.

**[Website](https://julienpiron.fr/foldgpt/)** · **[Public source and product documentation](https://github.com/pironjulien/FoldGPT/tree/main)** · **[Changelog](CHANGELOG.md)**

## Runtime development

This branch contains the Android runtime development sources and their engineering records. The `main` branch is the curated source release for contributors. The desktop client and model requests remain separate OpenAI services; the source release does not provide a consumer APK or a preconfigured client image.

| Area | Entry point |
| --- | --- |
| Android app and service | `android/app/` |
| Desktop session, keyring and input | [runtime/guest](runtime/guest/README.md) |
| Compatibility shim and diagnostics | [compat/desktop-sandbox](compat/desktop-sandbox/README.md) |
| Local execution and process lifecycle | [tools/executor](tools/executor/README.md) |
| Runtime packaging | `tools/install/`, `tools/runtime/` |
| Regression tests | [tests](tests/README.md) |
| Engineering references | [docs](docs/README.md) |

Run the relevant checks in the test guide before changing runtime code. Native tests require Linux and the stated compiler inputs; Android behavior needs device verification. Keep upstream changes, original capture files, signing material and verified recovery packages intact.

## Workspace hygiene

Use ignored `work/` for private evidence and reproducible build outputs, and `downloads/` for verified build inputs. Neither directory is safe to delete wholesale. The maintained web page is hosted on julienpiron.fr; the source release contains its `site/` mirror. Superseded experiments and launchers remain available through Git history.
