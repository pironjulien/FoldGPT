# Private Linux engine validation

`native-engine-validation.yml` is manual-dispatch only and runs only when the
repository is private. The workflow uses Ubuntu 24.04 PC runners. It never
connects to the phone, starts WSL, changes Android protections, replaces the
official application or publishes a release. This is a build/test environment,
not a VM deployed as the FoldGPT execution solution.

Three independent jobs preserve their logs and explicit proof files as private
Actions artifacts for 14 days. A failed build or unavailable kernel capability
fails its job; missing tools and Python test skips are not counted as success.
When an earlier complete Linux suite is still active, publish with `--arm-only`
to build the new ARM64 candidate and run the current native Python tests without
canceling that suite. Queue `linux_tests_only=true,full_rust_checks=true` for the
same published source snapshot separately; it waits for the current Linux job
and can restore its compatible compilation cache. An ARM build does not replace
the required Linux checks, and their conclusions remain separately recorded.

The fixed kernel worker runs under its canonical dedicated nobody UID/GID
(65534), measured before launch. Its two-task quota permits the worker and its
secondary thread. GitHub's active runner UID is shared with unrelated CI
threads, so it cannot represent that dedicated quota fixture. Only this fixed
kernel driver and the explicit readback of its named report use `sudo -u nobody`;
no test runs as root. Its exact C identity guard and all enforcement probes
remain active. Other native suites run under the ordinary runner UID.

The fixed C qualification explicitly allocates its secondary thread's stack
within half of its existing data-memory budget. Real diagnostics showed GitHub
inherits a 16MiB default pthread stack while this fixture has a 16MiB data limit;
the implicit stack alone exhausted its budget. The other half remains available
for the main worker and heap. Both total memory and two-task quotas stay fixed,
and every real secondary-thread probe remains mandatory. No runner policy changes.

- `native-python`: compile the frozen current C helpers and run actual nonroot
  Python/file/process/credential/lifecycle tests, including the Python project.
  This also tests the separately developed host v2 channel and human process
  owner. Production APK r15 explicitly selects v2 and passed the six real Fold
  cases with independent native cleanup; official-editor validation remains open.
- `engine (linux-tests)`: restore the exact exported engine, compile its real
  CLI, app-server and code-mode companion, then use upstream `just test` for
  selected exec-server and app-server integration tests. The explicitly ignored
  native Python project test is selected by its exact name. Its private child
  test is launched by that parent fixture only. Model responses in this software
  test come from deterministic Responses SSE fixtures; process operations are real.
  With `full_rust_checks=true`, a successful targeted step is followed by the
  complete `just test` suite, `just fix` scoped to the changed Rust packages,
  and `just fmt`. The final source patch is retained for review and replay in
  the maintained engine; tests are not repeated after fix/format. Formatters
  uv 0.12.5 and DotSlash 0.5.9 come from checksum-verified official archives.
- `engine (arm64-build)`: cross-compile release `codex` and adjacent
  `codex-code-mode-host` for **GNU ARM64**, retaining the existing controller
  architecture. GNU controller code is distinct from the Bionic workers that
  execute model tools. Produce `foldgpt-gnu-engine-aarch64.tar.gz` with source
  patch and binary hashes. Readelf checks architecture and GNU loader; execution
  and symbol compatibility against the actual Fold libraries remain device
  qualification steps. This job does not claim to validate them.

## Inputs and resources

The sole engine source is `tools/recovery/restore-engine.py` plus the committed
`recovery/engine/manifest.json` and checked patch. Do not dispatch an old export
and claim it includes uncommitted worktree changes. Freeze concurrent engine
edits, then export through the canonical command before committing:

```powershell
python -B tools/recovery/export-engine-state.py --engine work/worktrees/FoldgptEngine
```

Rust is 1.95.0, just is 1.58.0, cargo-nextest is 0.9.143. The latter tools are
installed through pinned, locked Cargo packages. Each target obtains the
official `ptrcomp_sandbox_release` V8 archive **and** bindings via the restored
upstream `scripts/codex_package/v8.py`; the exact upstream checksum pair is
checked on every run. No alternate V8 build mode is set.
The tool/V8 cache is saved immediately after that verification, so a later
engine compilation failure does not discard the installed pinned tools.
Compiled targets are cached separately by architecture, lockfile and snapshot;
Cargo still checks source fingerprints when a prior compatible cache is restored.
Linux dev/test profiles strip static symbols as well as debug information.
The previous full-suite attempt exhausted its 36GB of available storage even
with Rust debug information disabled. `native-target-v2-stripped` separates the
new profile from incompatible larger artifacts, retaining the tool/source cache;
the first build under this profile recompiles those Rust targets. ARM release
settings and its existing target cache are preserved. ELF section reports verify
that the Linux executables really have no static symbol table or debug sections.
Each command records free storage, and full-suite boundaries record allocated
target blocks and the largest artifacts, counting hardlinks only once.
The disposable hosted Linux job removes only its listed unused Android, .NET,
Haskell and CodeQL SDK directories and the redundant image Rust toolchains before
compilation. Removal of the latter requires the explicit project-local
`RUSTUP_HOME`; cargo/rustup shims and the selected pinned toolchain are retained.
Available disk space before and after is recorded in evidence.

The ARM64 OpenSSL input is the complete official 3.6.3 source archive, pinned to
SHA256 `243a86649cf6f23eeb6a2ff2456e09e5d77dd9018a54d3d96b0c6bdd6ba6c7f1`,
the source already verified in the project's 7 September build evidence. It is
compiled statically using the original source configuration. Cross-compilation
does not run the upstream ARM64 OpenSSL tests.

Cargo and make have two build jobs. Rust test threads are limited to two.
Development/test/release debug information and incremental output are disabled
to limit disk/memory use; assertions, test selection and release optimization
remain active. Release LTO remains the upstream setting. The time bounds are
30 minutes for Python and 180 minutes for each engine job. Disk/RAM/kernel and
actual tool versions are recorded. No swap or kernel setting is modified.

All mutable builds, tool caches and evidence are under the checkout's `work/ci`.
Existing native test fixtures use their canonical `/var/tmp` directories. The
dedicated nobody kernel test gets a byte-verified frozen helper copy there,
because GitHub's private `/home/runner` must retain its existing permissions. Only
explicit report paths are copied, without walking possibly quarantined projects.
Artifacts exclude credential files, caches and environment dumps. Actions have
read-only repository permission and checkout credentials are not persisted.
No project secrets are needed. Third-party Actions are pinned to reviewed SHAs.

## Launch and retrieve

The workflow definition must exist on the repository's default branch for
GitHub's first manual dispatch. The tested ref may then be a dedicated private
branch containing the matching workflow, scripts, native sources and recovery
export. For the current private workspace:

```powershell
gh workflow run native-engine-validation.yml --repo pironjulien/FoldGPT-workspace --ref <tested-branch>
gh run list --repo pironjulien/FoldGPT-workspace --workflow native-engine-validation.yml --limit 5
gh run download <run-id> --repo pironjulien/FoldGPT-workspace --dir work/ci-results/<run-id>
```

The CI archive is a candidate engine payload. Before installation, recheck it
with `tools/executor/check-gnu-engine-elf.py` against the current captured Fold
libraries, then qualify the production launcher and ordinary UI on the phone.
A green Linux job alone is not completion of FoldGPT.
