# Changelog

## 2026-09-11 — Showcase graphics recovery

- Preserve the static capture and disable unavailable 3D controls after graphics initialization or restoration failures.
- Clean up partial GPU resources, ignore stale texture callbacks and restore controls after successful recovery.
- Add seven scene lifecycle regression tests to public CI.

## 2026-09-11 — Fold8 handset and Remote cover display

- Correct the showcase model to Samsung's standard Galaxy Z Fold8 rear layout, with two cameras behind the right half of the inner display and the cover display behind the other half.
- Fix outward surface orientation and centered folding; add solid sidewalls to the camera island and lens rings.
- Show OpenAI's official Remote preview on the cover display, with readable text and preserved image proportions; document its provenance separately from the authentic Fold captures.

## 2026-09-11 — Repository maintenance

- Remove superseded Termux/QEMU launchers, one-off live-CDP experiments, the old launcher app and outdated publication drafts.
- Group maintained guest sources under `runtime/guest/` with byte-identical generated bundles; retain the compatibility shim and diagnostics under `compat/desktop-sandbox/`.
- Separate historical audits and release records from the root documentation; retain meaningful regression tests and document their prerequisites.
- Repair native PRoot regression runners for source-only checkouts and include additional existing host regression suites in the standard runner.
- Refresh the showcase screenshot in the README, ignore disposable test caches and document the source layout.

Notable changes to FoldGPT are recorded here. Source preview versions describe the published implementation and its documentation; they do not certify a consumer installation or every device workflow.

## [Unreleased]

### Showcase and documentation

- Record the maintainer’s confirmation that Samsung Pay works on the development Fold in the showcase and compatibility documentation.

- Focus showcase copy on Codex, local projects, workspace tools and Android input; remove visible animation narration and capture-production notes while preserving image credits, accessible controls and alpha limitations.

- Restore the authentic Codex composer and session controls in the gallery and 3D screen; anonymize only the account name as `you@gmail.com` and its avatar. Document the two direct pixel edits and unchanged original interface.

- Select the showcase language automatically from the browser's preferred language: French for French preferences, English otherwise, with no visible selector.

- Move the showcase into the Julien Piron portfolio at `https://julienpiron.fr/foldgpt/` and publish its static source under `site/`.
- Use the application's exact vector icon and graphite/gold identity in the website and repository artwork.
- Replace simulated demonstrations with historical device captures and explicit media provenance. The interactive handset remains clearly identified as a WebGL visualization.
- Introduce a particle handset with rotation, fold controls, dispersion and reassembly, plus accessible controls and reduced-motion support.
- Link the README and product documentation to the canonical portfolio page and its authentic capture gallery.
- Align public credits with the julienpiron.fr brand and add the faithful banner export used for Open Graph and X link previews, with localized alternative text.

## [0.2.0-alpha.1] — 2026-09-11

The first named source preview opens FoldGPT to contributors: an Android host for the Linux ARM64 ChatGPT desktop client, with desktop Codex and local project tools on a Galaxy Z Fold.

### Experience and implementation

- Android host, embedded Termux:X11 display, touch and keyboard integration, and a separate runtime service with recovery and explicit-stop handling.
- Debian/PRoot compatibility environment and a native execution layer for local commands, project files, Git, Python, and Node workflows.
- ARM64 workspace integration for document creation and rendering, including demonstrated DOCX, PPTX, XLSX, and PDF workflows.
- Version-specific desktop workspace adaptation and source recovery records for the open-source Codex execution engine.
- Android bridge plugin and supporting source for permission-based device integrations.

### Source distribution

- Restore Android application, installer, shell-loader configuration, native execution helpers, and build inputs omitted from the earlier public snapshot.
- Record vendored Termux:X11 and PRoot source provenance and explain dependency licenses and proprietary-client acquisition.
- Require a complete, explicitly selected native executor package for production-candidate builds; verify its assets and JNI inventory before assembling the final APK.

### Fixes

- Repair the native workspace admission path whose fallback to a guest path produced `EACCES` during local command execution.

### Documentation and collaboration

- Add a product overview, architecture diagram, compatibility matrix, FAQ, roadmap, and a documentation entry point.
- Add contribution and security-reporting guidance, structured issue forms, and a pull-request template.
- Separate product support statements from dated development evidence and publication drafts.

### Release boundaries

- Source only: no consumer APK, preconfigured Linux image, proprietary client package, or account data is included.
- The demonstrated target is the development Galaxy Z Fold 8. Clean-device installation, updates, Remote, and sustained simultaneous/background sessions remain under qualification.
- Android's shared phantom-process budget still applies. Multiple ordinary APKs do not create separate budgets; reducing process pressure must preserve independent conversations.
- Desktop runtime, files, and tools run locally. Model inference uses OpenAI's online services.

[0.2.0-alpha.1]: https://github.com/pironjulien/FoldGPT/releases/tag/v0.2.0-alpha.1
