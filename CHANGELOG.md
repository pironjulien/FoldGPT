# Changelog

## Unreleased - 2026-09-08

- Deliver encrypted recovery supplement v17 privately, redownload and authenticate
  it, and verify 20,008 restored files plus 1,433 Git source files. Reverify
  r26b/r27/r28 APKs from restored source and authenticated v16 inputs; reconstruct
  all 24,346 omitted desktop corpus files from retained original archives.
  Preserve the initial Windows destination-prefix rejection and its correction.
  Remove the verified redundant 1,760,858,355-byte combined encrypted local copy.

- Allow authenticated recovery snapshots strictly below the project's
  `work/FoldGPT-recovery` directory during initial hydration and additive merges.
  Reject self-copying, source/destination links and Windows junction traversal,
  preserve tracked paths even when missing, and protect hydration reports.
  Keep cross-PC recovery commands and snapshots within the project directory.

- Document the actual bundled MCP startup/cache rules: cache keys include cwd,
  selected plugins differ from globally installed plugins, and status-list
  diagnostics can themselves start temporary services. Preserve this boundary
  before implementing any process-count optimization; no tools are disabled.

- Inventory the actual desktop client (26.901.41600) and compare it with the
  26.901.51231 reference: 9,737 installed JavaScript files parsed, 370/370 ASAR
  external members collected, 57 native ELF inspected per version. Record
  commands, handlers, services, routes, settings, ABI requirements, dynamic
  unknowns and source hashes. Document the desktop conversation retention
  lifecycle and its Android process-count implications.
- Install r28/versionCode18 with direct application-origin native startup and
  verified Android boot-count provenance. The original failing legacy conversation
  now creates a Python CLI, passes six tests, builds and runs its zipapp under
  Android UID10412. Preserve all 327 preceding project entries and history prefixes.
  Normal stop reaps the native owner with exit0 and removes its resources;
  reopening succeeds with all 334 resulting project entries preserved.
- Retain the Android foreground service until both the desktop worker and native
  cleanup actually finish. Add generation/restart guards and 14 lifecycle cases
  (24 JVM tests total). A missing cleanup confirmation never becomes success.
- Preserve the r26b real pipe/PTY evidence and subsequent failure chronology:
  Android phantom-process trimming precedes Linux137 and REMOVE_TASK. The new
  shutdown ordering does not resolve process accumulation. Same-boot crash recovery
  and desktop feature parity remain unqualified. A real reboot from Android
  BOOT_COUNT8 to9 now passes automatic marker archival, application-origin
  restart and the existing conversation's six tests/zipapp (all exit0), without
  backend preparation by the PC. Physical cable-disconnected use remains distinct.
- Repair native and four active legacy conversation paths through the existing
  desktop APIs, without rewriting their history. Copy 39 empty legacy directories
  with no symlink traversal; preserve two archived conversations unchanged.
  Extend the one-time v1 maintenance contract for observed stale stopping sessions,
  retaining whole-UID quiescence, exclusive lock and original marker archival.

- Run the separate app-context diagnostic on the Fold with Shizuku absent:
  real pipe/PTY commands, files, subprocesses, input, interrupt and cleanup pass
  under Java/Zygote. Independently verify receipts, files, process enumeration,
  unchanged boot and APK hashes. Preserve selected evidence in private Git.
  Production was already unavailable before the test; its direct-app integration
  and reboot recovery remain pending. Add the integration and migration analysis.

- Complete a parallel, source-backed feasibility survey of Rust/Android engines,
  Linux hosts, Samsung lifecycle limits and official Remote support. Preserve
  the proven r25 workflow separately from unqualified autonomous startup and
  full Android-native UI. Build a separate fixed app-context pipe/PTY diagnostic
  from unchanged r25 payloads; add read-only device evidence collection. The
  Fold was unavailable in ADB, so no new Android execution is claimed.

- Diagnose legacy conversation resume failures on the connected Fold: valid TOML,
  but saved Linux project paths lie outside the current native workspace root.
  Record the outstanding migration defect and verify Local Desktop/UserLAnd
  upstream architectures. No device configuration, history or runtime changed.

- Reassess the Shizuku launch dependency using the historical Bionic app-context
  RPC receipt and verified artifact hashes. Document the unqualified direct-app
  runner alternative, Store/signature limits, AVF tradeoffs and local/cloud
  distinction. No runtime, admission policy or device state changes in this review.

- Prioritize opening FoldGPT and working without a PC, as clarified by Julien.
  Defer the manual terminal panel without removing its implementation. Distinguish
  Android-local command execution from Shizuku startup, which the last device
  validation initiated through PC ADB; autonomous startup remains unqualified.

- Publish encrypted recovery supplement v16 to the private release, redownload
  and authenticate all 39,584 files, restore 1,252 committed source files and
  reverify both r24/r25 APKs. Preserve required Rust vendor sources and exact
  artifact bytes across Git line-ending normalization. Keep main and supplements
  1-15 as dependencies; update the handoff and community comparison for r25.

- Install r25/versionCode15 with explicit ordinary-UID model PTY routing.
  Real conversation calls launch Android Python with three terminal descriptors,
  exchange input through write_stdin and finish with codes23/130, including
  keyboard Ctrl+C. Subsequent pipe commands pass five Python tests, existing
  JSON/Markdown archive runs and rg search. All104 project files are unchanged;
  normal owner cleanup and reopening pass. Human terminal UI remains separate.
- Preserve exact qualified source line endings across Git checkouts, including
  the PTY import closure; no executable or source behavior changes for this fix.

- Qualify the separate PTY backend candidate with nine real Android tests,
  including binary input, resizing, foreground/initial-group interruption,
  detached descendant cleanup and saturated notifications. Eight native owners
  have wait0 receipts and independent absence checks; the existing UI session,
  boot and installed Python remain unchanged. Preserve the first 8/9 run:
  its harness used Python pidfd bindings omitted by the official API24 build.
  The revised test harness calls real Bionic symbols with exact errno and
  retained assertions. This is not yet APK or terminal-UI integration.
- Install and verify r24/versionCode14 with native rg 15.2.0 and static
  PCRE2 10.47/JIT. Fifteen real Fold search cases and six Python production
  commands pass, with fresh admission and clean shutdown. Explain the upstream
  PCRE2 10.45 display constants separately from the linked library and real
  10.47 JIT probe; preserve the initial Shizuku timeout and locked-screen launch.
- Exercise a real dependency project in the normal conversation: download and
  install Packaging 26.3, correct the CLI entrypoint and zipapp build, pass five
  tests, and build byte-identical archives across two source timestamp sets.
  Close/reopen the application and rerun the existing tests and archive with
  captured subprocess results; independently retain all project sources and
  artifacts. This qualifies the ordinary UID Python route, not integrated PTY,
  autonomous reboot recovery or a wholly Bionic controller/interface.
- Update the current README, publication scope and recovery handoff to distinguish
  the working model route from earlier diagnostic fixtures. Keep v15 as the last
  independently restored private backup until a newer delivery is verified.

- Pause before APK r24: preserve r23 installed and its clean session shutdown.
  Build native ripgrep15.2.0 with external static PCRE2 10.47/JIT twice, admit
  its exact sources/binaries, and stage explicit rg commands/aliases/notices.
  No rg Android execution or r24 installation is claimed. Native pip version
  preflight and a controlled one-child PTY probe pass on the Fold; PTY backend,
  dependency project and rg production/UI qualification remain pending.
  Record actual failures, restart point and the local-only artifact boundary
  in recovery/PAUSE-20260908-r24.md.

- Publish encrypted recovery supplement v15 to the existing private release,
  redownload and authenticate all 8,707 files, restore 1,219 committed sources,
  and reverify the restored r23 APK. Preserve main + supplements 1-14 as required
  dependencies, including the unchanged pending GPU/PTY sources.
- Qualify r23/versionCode13 on the actual Fold with ordinary Python bytecode
  enabled: six production commands, caches read outside the signed runtime,
  clean shutdown, and fresh runtime admission pass. The same UI conversation
  then passes three tests and runs the existing zipapp twice across two launches;
  the editor reopens its saved comment and all project bytes remain identical.
  Both UI owners close with real wait0 receipts and absent resources. Preserve
  the 81 previous cache files in an incident archive; verify all 2,447 runtime
  sources and 86 aliases before and after. Phone boot indicators and the four
  official ChatGPT APKs remain unchanged. This qualifies the Python workflow,
  not every Codex feature or the still-GNU/PRoot controller.
- Place native Python's default bytecode cache in the deployment's sibling
  `python-cache` directory, outside the admitted runtime. Preserve CPython's
  explicit cache options and environment semantics, including isolated and
  empty-environment launches. Two NDK r29 builds match; actual CPython 3.14.7
  Windows checks generate bytecode while preserving all 2,477 copied runtime
  files. Record the separate Android restart results in the r23 device report.
- Qualify r22b on the Fold: unused-session shutdown, ordinary UID production
  workload, actual conversation-created Python sources/tests/zipapp, editor
  save/reopen, and clean shutdown pass. Preserve the subsequent restart failure:
  CPython bytecode caches entered the signed runtime tree. Record actual model
  tool outputs and independently collected Android files; full reprise remains
  pending the cache placement correction.
- Preserve remote upload completion and binary bytes in six ADB staging tools
  using shell v2 and base64; retain post-transfer SHA256 admission.
- Build and verify r22b/versionCode12 with bounded cleanup diagnostics shared
  by the native bootstrap and Java owner; preserve quarantine on any cleanup
  error. Native Linux CI 34215637059 passes 193 unittests and 25 commands.
  Record the source-level selection of Android community adaptations, including
  the Rust 1.95 Android flock gap and the matching V8 150.4.0 build recipe.
- Fix ordinary UID backend shutdown before the first controller connection.
  The returned Fold exposed r21 quarantining an unused owner on `close(None)`;
  allow only an unbound backend with no handles to close without a session.
  Preserve rejection after acquisition and add actual acquisition, descriptor
  and workspace-lock regression coverage. Device requalification is pending.
- Record the completed R5 full-suite failure and classify all 240 failing or
  timed-out test cases without counting retries twice. Audit missing Android
  RPC/cleanup evidence and research comparable native Android Codex ports.
  Preserve the distinction between working targeted tests, the untested r21
  Android candidate and unresolved full-suite failures; no device action.
- Publish encrypted supplement v14 to the private recovery release, redownload
  and authenticate it, and verify all 10,695 restored files and 1,198 source
  files. Revalidate r21 using the restored source verifier. Preserve the earlier
  archives and verify that all 15 pending GPU/PTY files match restored v13.
  Document the exact Android return procedure; no phone action is performed.
- Prepare an explicitly selected ordinary Android UID execution profile for
  the engine's Full access process and filesystem contracts. Keep managed
  requests on their existing backend, retain handle/session ownership and
  shared quarantine, and add actual lifecycle/filesystem/composition tests.
  Cross-compile the direct runner and attest its sources and repeated ELF
  output in production staging. Private Linux CI 34203936964 passes all 190
  unittests with no skips, including the real production acquisition and Python
  project workload. Build and verify APK r21/versionCode11; Android/UI
  qualification remains pending until the phone returns.
- Publish, redownload and authenticate encrypted supplement v13 for the installed
  r20/R5 state and its first real conversation failure. Restore and verify all
  13,157 files and 1,169 source files, all three APK/package inventories, the
  ARM engine and complete production Bash provenance. This is a recovery
  checkpoint; normal conversation execution remains unsupported in Full access.
- Install APK r20 with the independently reproduced production-prefix Bash,
  explicit source/ELF admission and versionCode10. Native Python qualification
  passes on the Fold. The Bash workdir fixture still reports a HOME profile
  warning and remains failed; its previous lab-prefix warning is resolved.
- Install the separate R5 engine and verify successful normal client startup.
  Preserve the first real conversation failure: full-access commands lack the
  currently required managed context, apply_patch fails, and an independent
  Android inventory confirms no project files. End-to-end use remains unqualified.
- Prepare a separately dispatched Bionic Bash build at the actual production
  runtime prefix, preserving Bash features and checking two compiled binaries,
  source inventory and Android imports. Fix relative source preparation paths.
  Build and r20 device integration completed as recorded above.
- Preserve already-enabled kernel credentials on inherited native sockets instead
  of repeating a socket option change that Android rejects. Add real restricted
  Linux-thread coverage that still refuses endpoints without enabled credentials.
- Align native path URI serialization with the engine's pinned Rust url crate,
  including the literal `==` in real Android APK installation directories.
  Preserve canonicality and actual device/inode checks. APK r18/versionCode8
  refreshes the existing Shizuku service version after our APK update.
- Reproduce the remaining engine startup refusal: Android rejects resetting
  SO_PASSCRED on transferred channels where the native owner already enabled
  it. Native Python qualification passes from the real application context;
  the ordinary conversation/editor/resume workflow remains unqualified.
- Separate native process workdir from the original project policy base, so
  commands may enter an admitted project subdirectory without rebasing their
  permissions. Preserve policy identity and add real Linux execution/refusal
  regressions; device validation of this correction remains pending.
- Add real Rust startup and Python-to-Rust integration coverage for Android APK
  paths containing `==`, retaining the production URI validation. Reduce Linux
  validation artifacts with stripped dev/test symbols and separately versioned
  compatible build caches; retain every Rust test and the ARM release profile.
- Fix direct Python script execution in the native model runner by admitting only
  FIOCLEX/FIONCLEX descriptor inheritance operations. APK r16 passes real script,
  unittest, zipapp build and execution on the Fold, plus all six human operations;
  independent native cleanup and unchanged official Android packages are verified.
- Correct the private directories in the two real app-server startup fixtures;
  retain the production permissions check and reuse the Linux compilation cache.
- Publish and independently restore encrypted supplement v12 with APK r16,
  its frozen inputs, exact source commit and real native Python evidence.
  Verify all 5,506 artifact files and 1,141 source files after restoration.
- Publish and restore encrypted supplement v11 with APK r15, its frozen inputs,
  exact source checkpoint and new Fold/Linux proof. Reverify all 5,487 restored
  artifact files, all 1,105 source files and the restored APK inventory.
- Prepare explicit native human v2 production selection through an attested
  APK asset and startup manifest, including real editor cat/Bash execution and
  the native parent's environment. Preserve model authority and v1 admission.
  Freeze the ARM64 native package and standalone GNU-controller qualification;
  add a real production-channel Linux test. Device/editor qualification remains
  pending and PTY is explicitly unsupported.

- Correct Python file opening in the human native executor by admitting only
  the descriptor inheritance operations FIOCLEX/FIONCLEX. Preserve the model
  runner and all other ioctl refusals. Reproduce the ARM64 build byte for byte;
  real Linux production-channel qualification passes. APK r15 now also passes
  all six production human-channel cases on the Fold: file reads, exact 2 MiB
  stdin save/readback, Python script, outside-workspace refusal and descendant
  cancellation, with independent Java reaping and unchanged official APKs.
- Pin the human cwd with O_PATH so Android can enter a directory without
  demanding its read permission. Start the handshake deadline at the actual
  controller connection, preserving service-owned idle cancellation. Repeat the
  complete real Fold qualification after a deliberate 35-second controller delay.
- Correct native selection for the official client's global CLI options by
  resolving its existing startup environment inside app-server startup. Preserve
  the complete argument vector and utility commands; add an integration check
  for the exact official launch arguments. Engine/UI validation remains pending.

- Publish encrypted recovery supplement v10 to the private repository, download
  and authenticate it again, and verify every restored file and the restored r12
  APK. Preserve the exact 49c610d source checkpoint separately from ongoing v2 work.

- Publish encrypted recovery supplement v10 for commit 49c610d and APK r12.
  Redownload it from the private GitHub release and restore/verify all 25,232
  files on Windows, plus 1,057 frozen source files and the complete APK inventory.
  Preserve explicit dependencies on the prior archives and keep keys in the vault.

- Complete the real production Python qualification on the Fold with APK r12:
  create source files through the native channels, pass three tests, build a
  zipapp and execute it with output 42. Independently verify Java wait status 0,
  complete native cleanup and unchanged boot, protection properties and official
  Android ChatGPT package bytes. Conversation and editor qualification is pending.
- Preserve the exact evidence bytes in Git and add a separate-engine installer
  that checks the package, source identity, live GNU libraries and stopped owner,
  then verifies the official Linux client is unchanged after installation.

- Correct Linux qualification portability without changing native runner policy:
  accept the kernel-echoed atomic CLOEXEC flag while rejecting truncation, and
  explicitly fit the secondary test thread stack inside its existing memory
  allowance instead of inheriting GitHub's equally large default stack.

- Add a manual private Ubuntu CI workflow for the exact recovery-exported
  engine: real Linux native Python qualification, targeted engine integration
  tests, and a separate GNU ARM64 controller/companion build. Pin Rust, test
  tools, Actions, verified V8 inputs and the existing OpenSSL source hash;
  retain failed logs and candidate artifacts without claiming phone qualification.

## Unreleased â€” 2026-09-06

- Qualify real Android Java startup through Shizuku/run-as, direct native
  channels and actual waitpid cleanup on the Fold. Correct framework endpoint
  permissions, verified application-prefix identity and Shizuku initialization
  order. Add the official SDK authorization request, a foreground diagnostic
  entry and stable service version identity across our APK updates. The first
  official UI path remains unqualified; the production Python result is recorded
  in the 8 September entry above.

- Preserve twelve real Bionic startup tests including the native environment
  snapshot. Install the independently verified production candidate r4 and
  retain its first Android refusal before native launch: the framework-created
  endpoint directory has mode0771 while the native contract requires0700.
  Qualification retains actual Java session/wait records; UI completion remains
  pending.

- Prepare a separate human process owner and sealed native supervisor for real
  editor commands, including cwd `/`, uncapped output, stdin EOF and owned
  descendant cleanup. Preserve the qualified model runner and its mandatory
  policy. Add real kernel/lifecycle test sources and a separate app-server host
  process injection. Compile the human ARM64 supervisor twice with Windows NDK29
  to identical bytes, retaining frozen headers and ELF checks. Prepare a frozen
  real Fold/Bionic Python and shell workload; actual human execution, transport
  qualification and official-editor open/save remain open.

- Verify eleven real startup file/socket tests with Bionic Python on the Fold
  and measure actual shared file identities, bidirectional bytes, rename and
  advisory locking across Bionic and GNU PRoot. Preserve the Android hardlink
  creation refusal separately from application admission coverage. These ADB
  measurements do not qualify the production launcher or the ordinary UI.

- Connect an explicitly packaged native candidate to the Android runtime through
  the fixed run-as admission, preserving the four lifecycle descriptors and real
  child wait. Prepare private runtime data and startup manifests, bind declared
  native roots into the controller, and select a separate engine through the
  official CLI override. This wiring still requires full device qualification.

- Verify Shizuku to run-as to Bionic under FoldGPT's actual UID on the Fold,
  including all four launch channels and independent cleanup evidence. Add
  a reproducible Windows NDK build of the official Python CLI and an exclusive
  private runtime installer with full byte/alias readback. Preserve the first
  broker trial's old-UID test failure. Its separate corrected V2 passes all
  twelve real kernel probes on the Fold under UID10412, with independently
  verified process cleanup and unchanged boot and official APK hashes.

- Wire a startup-only native bootstrap into the separate engine CLI and
  app-server. It acquires three direct credentialed channels, binds the real
  exec session, checks shared path identities and native-written bytes, and
  retains owner-loss shutdown separately from native cleanup. Descriptor
  adversary tests are added; compilation and runtime qualification are pending.

- Add a reproducible GNU ARM64 engine build/package procedure from the exact
  recovery export, with frozen source and dependency hashes, official sandbox
  V8 artifacts, separate symbols, and static ELF import checks against the
  libraries collected from the Fold. The checker passes on the historical
  binaries; the current build and production native launcher remain pending.

- Add a separate native file authority and credentialed private transport for
  human UI operations. Complete write framing and commit precede mutation;
  operations share the actual worker lease and quarantine. Thirty nonroot PC
  tests pass, including real 16 MiB transfers, credential rejection, cancellation
  and helper cleanup. Engine wiring and Android qualification remain pending.

- Qualify the actual native backend through public app-server thread/start,
  turn/start and command/exec on PC: create Python code, observe failing tests,
  edit, pass three tests, build and execute a zipapp, and enforce private-file
  denials. Six real workers clean up completely. Model responses are fixtures;
  phone UI and live inference remain unqualified. Export all matching engine
  sources, including configuration provenance, AGENTS and permission authority.

- Correct native directory enumeration to return the real immediate names and
  kinds of an admitted directory, even when a child is denied. The previous
  overrestriction prevented Python imports from the workspace. Child reads,
  writes, metadata and traversal remain separately checked. Real file RPCs and
  native process regressions pass; complete app-server qualification follows.

- Preserve the upstream reconcile/preserve Windows proxy preferences in native
  POSIX handoffs too. Real app-server process requests include reconcile even
  on Linux; known inactive preferences must survive without blocking execution.
  Unknown values and enabled Windows enforcement remain rejected.

- Keep Windows recovery reports, downloads and temporary Git indexes inside
  the project. Permit new ignored recovery reports under work/ with collision
  checks; seven real Git/filesystem recovery tests pass. Save and verify the
  existing Codex project root as C:\Dev\ChatgptFold.

- Preserve the upstream Windows private-desktop preference in native policy
  handoffs when Windows enforcement is disabled. Core's default true value is
  inert on POSIX and must not prevent real native app-server execution. Enabled
  Windows enforcement, invalid types and unsupported protections remain refused.

- Connect the separate Rust engine to the native bootstrap read authority over
  an anonymous, credential-checked channel. Seventeen Rust protocol/socket
  tests and 108 Python/native regression executions pass. A real PC test with
  distinct nonroot users proves direct controller access is denied while the
  channel reads exact bytes and loads the trusted project configuration through
  the bounded loader. Both owners exit with complete cleanup. Preserve source,
  binary and failure evidence; full app-server/UI integration remains pending.

- Publish and independently restore encrypted native checkpoint v9 from the
  private GitHub release: 8,958 files verified, including Python V2 success,
  earlier failure evidence, matching APKs, stages and supervisor builds.

- Add an internal bootstrap-owned read authority for the existing pinned
  native workspace: actual file bytes, metadata and canonicalization share
  its FD helper, process lease and quarantine gate. Expose an explicit
  discovery ceiling while preserving real outside-root denial and managed
  model-context refusal. Ninety nonroot PC tests pass, including actual child
  cancellation/reaping and existing file/stream/RPC regressions. No new RPC,
  fabricated managed context or Android deployment is introduced.

- Qualify the real native Bash/Python project on the Fold in isolated runtime
  V2: source creation/edit, three tests, zipapp build/execution, binary streams,
  empty child environments and actual denials pass. All 20 independent checks
  pass with actual cleanup and unchanged boot/APKs/protected fixture. Correct
  the Python CLI RUNPATH with its attested deployment prefix. Preserve failed
  V1 and consumed markers; ordinary UI execution remains an integration task.

- Preserve the real Android runtime V1 failure: Bash starts but Python cannot
  resolve libpython3.14.so. Retain complete native/JNI cleanup and unchanged
  boot/package/fixture evidence; no Python success is claimed. Prepare a
  separately versioned runtime prefix RUNPATH correction for review and testing.
- Export the app-server native-runtime bootstrap with six real JSON-RPC tests
  and 29 API regressions passing on PC. Preserve official startup and explicit
  runtime refusal behavior; executor-only project routing remains incomplete.

- Qualify the fixed Shizuku/Bionic V12 worker on the real Fold: all 24
  independent checks pass, including real main/pthread operations, byte streams,
  owner waits and complete cleanup. Preserve exact evidence and unchanged
  boot, original APKs and fixture. Ordinary interface execution remains pending.
  Keep V10/V11 history and the consumed V12 marker intact.
- Prepare the full native Bash/Python project qualification on PC: create and
  edit source, run three tests, build and execute a zipapp, exercise binary
  streams and policy refusals. Correct terminal SEQPACKET handling with receive
  shutdown/draining and continued final-record reads after EPIPE. Six real
  scheduling regressions and five full-project tests pass on frozen N0kMFS8z;
  missing cleanup evidence still retains quarantine. Preserve negative controls.
- Export the separate engine's verified native metadata/shell increment:
  41 targeted tests and one model execution/apply-patch integration pass on PC,
  using actual provider paths and Android POSIX command classification. Preserve
  the ExecutorOnly registration refusal until controller routes are implemented.

- Provide actual executable metadata for the exact `/proc/self/exe` alias,
  pinning the notifying task and preserving the TGID symlink identity for
  nofollow requests from secondary threads. The real regression fails against
  the old runner and passes against the corrected one; 18 factory tests pass
  with 2 optional shim cases skipped, plus resolver and kernel checks.
  Compile and inspect the Android artifact without deploying it. Bionic
  `realpath` and complete Android loading remain unqualified.

- Resume the authorized native qualification with stock SELinux enforced.
  V11 authorization and admission pass; its actual Bionic worker exits 127
  during executable identification, before kernel proofs. Native and JNI
  cleanup, unchanged boot, fixture and APKs are independently verified.
  Preserve the failed attempt and nine exact evidence files. Enable USB
  stay-awake for the active work session and verify 35 seconds without input.
- Compare the GNU ARM64 engine and companion against the collected Fold
  libraries on PC: required libraries, symbol versions and strong imports
  resolve statically. Device loading and ordinary execution remain unproven.

- Publish recovery supplement v8 and verify its actual GitHub download,
  authenticated restoration and all 7,169 files (3,241,402,905 file bytes).
  All 27 published release assets match their recorded sizes and digests.

- Close the overnight session at Julien's request for work-PC recovery. The
  separate GNU ARM64 CLI and code-mode companion compile in release (exit 0);
  PC CPU-emulation help/version checks and real V8 evaluation pass. Preserve
  symbols, exact build inputs and recorded limitations; no Android engine
  execution or ordinary interface command success is claimed. Restore display
  idle protection and record the pending V11 permission and next steps.

- Correct read-only memory accounting to retain remote ADB failures and reject
  missing, partial or raced PSS as complete totals. Seven regression tests pass;
  the live 23-process FoldGPT observation is retained with actual rlimits.
  Audit remaining ExecutorOnly controller paths and their required authorities;
  clarify the current V11 handoff versus retained V10 and older build history.

- Published private recovery supplement v7: 2,819 files downloaded,
  authenticated and restored, then 2,818 project files independently verified
  after additive merge into the Windows clone. All 25 release assets match
  their recorded size and digest; current source and handoff are on GitHub.

- Resolve immutable runtime objects through verified descriptors without
  inspecting every parent; retain workspace exclusions and policy denials.
  The reviewed native build passes 16 resolver tests, C/kernel checks and
  qualification on nonroot Linux. Prepare and install independent V11 with
  verified Python files/aliases; its official Shizuku authorization is pending
  behind the phone lock, with no native attempt started. Keep V10 quarantined.
- Separate the shared transport module's Gradle outputs by root/project to
  prevent colliding merger state. The V11 APK builds, its signature and complete
  source/native inventories verify, and all 24 transport JVM tests pass.

- Close the unused RPC input/output after a quarantined startup failure so
  initialize callers receive EOF/EPIPE while the real owner, lock and marker
  remain retained. Real nonroot startup/lifecycle tests and an independent
  late-writer test pass; the installed V10 quarantine is not changed.

- Published the v5/v6 recovery supplements and independently verified their
  GitHub download, authenticated restoration and additive Windows merge.
  All23 remote assets match their size/digest. The v10 diagnostic passes socket
  initialization but retains quarantine after the actual linkerconfig path
  refusal; its current owner, marker and negative results remain preserved.

- Published and restored the private v4 supplement from GitHub: 2,928 exact
  files, including v8/v9 artifacts and real phone reports. Its 2,927 project
  files also merge exactly into the hydrated Windows clone. Track the root
  handoff so restoration cannot revive the obsolete completion claims.
- Separated persistent session ownership from the authenticated stdio host
  after v9 identified the real bind refusal. Twelve nonroot owner tests and
  actual bootstrap lifecycle checks pass; lab v10 builds with unchanged native
  code and deployment. This PC verification does not qualify Android execution.

- Published the private v3 recovery supplement and verified its actual GitHub download, authenticated decryption and all 8,462 restored files plus one link. Merged its 8,461 project files and link into the already hydrated Windows clone, independently rechecked every byte/link and confirmed no tracked source change. The remaining file is archive identity metadata kept outside Git.

- Corrected the v7/v8 diagnostic chronology: their retained admission reports were generated automatically by restored Activity Intents during APK updates, before Python aliases were restaged, and do not prove later explicit executions. The v8 preflight identifies the stale alias and passes after restaging. V9 rejects the inherited unversioned run action without reserving an attempt and requires `KERNEL_RUN_FIXED_V9`, with separate kernel-v5 reports and service version5. Its later explicit trial passes admission but confirms `PermissionError` errno13 at the broker's AF_UNIX bind, before any native worker. The bootstrap is reaped with exit70 and complete transport cleanup; independent inspection confirms the service PID absent, only the empty broker lock, and unchanged fixture, boot, integrity indicators and package hashes. Native evidence remains absent and the collector retains `success:false`; Android `/proc/TID/mem` and `pidfd_getfd` are still unmeasured. Documented the limited Activity lifecycle review: a reporting deadline can precede worker completion, so the Activity must not be reused after timeout. Replaced the obsolete root handoff with current private recovery pointers.
- Added diagnostic APKs reusing the existing Shizuku laboratory authorization. The real v6 bootstrap was reaped with exit70 before native worker execution; later versions preserve that evidence and add bounded setup/admission diagnostics. These observations do not qualify the kernel. Added additive Git recovery with real conflict, tracked-path and exclusive-report checks; all five regressions pass.

- Added exclusive staging and independent device snapshots for the fixed native kernel qualification. The actual v2 Fold fixture is verified for exact bytes, ownership and permissions; the collector preserves remote exit status and transfers file bytes as base64 to avoid this Windows ADB build's stdout newline conversion. Earlier invalid collection attempts are preserved and explicitly superseded. This prepares the trial without claiming native execution.

- Completed private GitHub recovery validation: downloaded/authenticated/restored the full encrypted archive, checked all 113,900 files and 441 symlinks, then hydrated a real Windows clone and verified its 100,332 ignored data files byte-for-byte without changing tracked sources. Published corrected native artifacts and exact engine/vendor source recovery; OneDrive reports the recovery/signing identities in sync. Global tool installations and regenerable caches remain documented separately.

- Verified the auxiliary Rust engine against the actual Python ExecServer and corrected C supervisor on the PC. Real process/file operations, full policy, binary streams, exit, disconnection without replay and separate native cleanup pass; 27 targeted regressions and final Clippy pass. The exact engine patch restores from a fresh upstream clone and its test logs are preserved in private recovery. Android registration remains inactive.

- Independently reviewed the Bionic supervisor and corrected secondary-thread directory reads that could falsely report an empty directory, plus premature lease release before native supervisor reaping. The frozen corrected build passes 19 real process tests, two direct kernel tests and the fixed main/pthread qualification. Its Android ARM64 binaries compile with ELF checks; Android execution remains unmeasured. The exact next fixed device qualification is documented without activating the production route.

- Added the actual Bionic libc cwd shim and immutable APK path/digest admission. Four real native-supervisor composition tests pass for Bash/Python cwd, relative policy, reserved preload and attestation; raw chdir stays denied. The updated signed debug APK contains the shim, preserves the installed certificate and passes package/ELF checks. Sixteen transport unit tests pass; no native deployment is activated and no phone is accessed by this work.

- Preserved the separate engine's exact upstream base and complete source patch in private recovery. A fresh upstream clone restores an identical patch checksum. Added complete source/archive/hydration commands for another Windows PC; the archive's live GitHub restoration is verified separately before publishing its release.

- Added the authenticated Shizuku transport and app-private AF_UNIX adapter, then wired an explicitly selected native-executor owner into FoldGPT's real `:runtime` service. Qualified deployment/source/evidence hashes are mandatory; the default launcher remains unchanged. Runtime destruction now waits for verified native cleanup across service generations. The main signed debug APK builds and passes content/certificate checks; 12 library tests, four JVM ownership tests and real host JNI/ExecServer stream/EOF/cancellation checks pass. The existing HTTPS Gradle test compilation issue is recorded separately. No phone installation or launch was performed for this integration.

- Added private GitHub recovery tooling, exact preservation/restoration of the modified Termux:X11 submodule, and authenticated encrypted workspace archives with per-file checksums. A fresh private clone restores the exact vendor patch. Preserved the installed FoldGPT debug signing identity in NexusSecure and made the main build select and verify that certificate on another PC. Native engine integration remains in progress.

- Demonstrated the fixed Shizuku/Bionic Python qualification on the Fold on 7 September: actual source creation/edit, three tests, zipapp build/run, subprocess streams/exit, six interpreter denials and complete cleanup. Independent collection verifies APK/probe identities, physical project bytes, the 2,607-entry runtime before/after, and unchanged boot/integrity indicators. Corrected the guard's unsupported static PIE startup, narrowed the linker configuration rule and added the official read-only timezone database. The separate diagnostic SDK does not alter FoldGPT or the official client; ordinary model routing, production policy and secure automatic startup remain unfinished. See `docs/research/shizuku-bionic-trial-2026-09-07.md`.
- Added five linked capability inventories covering effective executor mechanisms, the actual Fold/One UI build, Android native APIs, ARM64 and Shizuku. A read-only v2 collector retains 6,501 kernel settings, 228 declared features, 521 Binder services and real process/CPU observations. It distinguishes the unfiltered ADB shell with zero effective capabilities from Zygote-created FoldGPT processes with inherited seccomp. Shizuku is a documented candidate launch context, not an observed working executor; no service was activated and the suspended GNU diagnostic was not rerun. See `docs/research/capabilities/README.md`.
- Rechecked the official Bubblewrap branch at the dereferenced Codex 0.153.4 tag: the retained binary was present, but its help-based detection failed; both argument builders still explicitly require the unavailable user/PID namespaces. Recorded this distinction from a missing file and corrected the routing audit's tag-object/commit provenance.

- Rechecked the missing namespace mechanisms against Linux, AOSP module rules and Knox documentation. Added a native Bash 5.3.15 / official CPython 3.14.7 Android runtime candidate outside the official client: 79 ELF files and the complete Python library are staged on the PC. Independent host CLI validation caught and corrected PYTHONHOME precedence; 16 portable checks now pass, and the corrected Android launcher cross-compiles. This does not implement the managed Bionic backend or validate ordinary phone commands. No phone test or client replacement was performed. See `docs/research/kernel-extension-options-2026-09-07.md` and `docs/research/bionic-native-route-2026-09-07.md`.

- Investigated Android GNU loader FD and virtual-address capacity from actual ELF dependencies and native syscall observations. The new managed fixture then coincided with two confirmed, unintended device reboots; its execution is suspended pending diagnosis. No full Android GNU project or ordinary phone command success is claimed. Added read-only whole-UID memory and incident collection; current measurements show no global 2 GiB FoldGPT rlimit. See `docs/research/gnu-managed-reboot-2026-09-06.md` and `docs/research/foldgpt-memory-2026-09-06.md`.

- Added the strict PRoot child Landlock domain before guest execution, with real parent/child tracing controls independent of Yama: 286 syscall observations, eight lifecycle cases and 11 tracer controls pass on the host. The ARM64 candidate passes compilation/ELF checks. Its first managed Android launch stopped at a native linker dependency error, retained separately; phone execution is not yet qualified.
- Added the separate GNU managed process adapter and private broker, including exact temporary-root permissions, protected metadata and owned runtime scratch. Eight real host cases pass, including Python edit/test/package, binary stdin, cancellation and timeout. The debug Android integration service and independent collector are prepared; neither establishes normal phone/model execution yet.

- Verified a real Bash/GNU Python project on the Fold under native Landlock/seccomp before strict ARM64 PRoot: source creation/editing, three tests, ZIP application and eight denial assertions pass. Independent collection binds ten artifacts, APK/native builds and all 6,200 official client files against the historical package; current Knox/boot/SELinux indicators remain intact. This is a fixed diagnostic, not yet the normal model command route.
- Added the actual five-field Codex environment policy resolver with pinned Unicode matching, frozen parent snapshots and APK source-closure integration. Portable and real native environment tests pass; historical collector proofs remain accepted only with their matching source contract.
- Verified the updated environment-module packaging on the Fold: nine composite transport tests and 23 native lifecycle tests pass in APK `3ba18fd6`, with independent source/library/APK and retained-data collection. The separate unmodified official Codex 0.153.4 also completes initialize/environment-info/status through the opt-in stdio adapter and exits cleanly; this handshake uses no account or model request.
- Added opt-in app-server environment routing outside the official package, preserving permission and approval fields. Resume and workspace changes are covered by semantic tests; general GNU managed execution, Desktop host operations and production routing remain unfinished.

- Added opt-in PRoot `--strict-sandbox` without changing the default compatibility mode. Real namespace/mount errors, clone namespace flags, proc user mappings and kernel NNP are preserved; unsupported security requests fail explicitly. Under nonroot WSL, 286 native observations and eight lifecycle cases pass, including GNU compilation and actual seccomp traps. The five-file NDK ARM64/ARM32 candidate passes static ELF checks; Android execution and protected GNU integration remain unqualified.
- Deployed the Android host/capability map through the official global AGENTS mechanism and verified its exact loading and answers in two real Fold Desktop tasks with 5.6 Luna. The current map is independent of model choice, preserves user instructions and accurately limits Android APIs. The earlier rejected Astra CLI request remains a separate failure.
- Added the versioned inactive integration v2 contract for context sources while preserving v1 archives and retry identities. Fifteen JVM tests, eight Python archive tests and two real Linux stage preparations/reopens passed; Android v2 preparation and activation remain unqualified.
- Verified the native static process lifecycle on Android/Bionic: 20 tests, 104 observations and independent collection of exact APK/source/native identities. The real libc memfd binding fixes the unavailable CPython Android API while preserving kernel seals. This is backend conformance, not normal model task routing.
- Verified native HTTPS acquisition of the independently authenticated official client 26.901.51231, private cache reuse and unchanged Android cache parent. The new client has not been installed or qualified as an update. Added an explicit French publication readiness plan and recorded remaining live runtime-log errors.

- Verified native managed file acquisition and process cleanup on the Fold with the GUI active: 17 tests and 46 real process observations pass. The runner now accounts for existing same-UID Android/GUI threads before applying its declared additional task budget, while retaining the inherited kernel ceilings. Independent collection binds eight executed sources and 30 installed libraries to the exact APK, and preserves the earlier 11/12 failure separately. This static-command increment does not yet implement the official process lifecycle, general shell/TTY/network support or Desktop routing. See `tools/executor/native-managed-android.md`.
- Verified native session-bound streaming through the actual GNU ARM64 guest bridge and Android/Bionic broker: 53 RPC responses across two sessions read a 38,797,325-byte binary file with exact offsets/EOF, private-path and stale-handle refusals, and real descriptor/lease cleanup. Independent collection verifies the full transcript, physical data and unchanged metadata/private fixture bytes, zero stderr, eight packaged source snapshots, all 28 installed native libraries and the tested APK identity before/after collection. Normal protected model tasks and arbitrary processes remain unfinished. See `tools/executor/private-exec-android.md` and `tools/executor/native-file-streams.md`.
- Verified the private GNU ARM64 guest bridge to the Android/Bionic file broker on the Fold: 32 real RPC responses across two distinct sessions include directory listing/walking, recursive copy/remove, policy refusals, independent copy inodes and EOF lease release. Independent collection checks the final files, authenticated app-UID peers, transcript and tested APK artifacts. The guest bridge uses PRoot; the native broker does not. Production Desktop routing and normal protected model execution remain unfinished. See `tools/executor/private-exec-android.md`.
- Added and ran the independent v3 collector against all 345 physical manifest entries: bytes, modes, inodes, native symlink targets and exact GPU/XKB trees agree. The original collection under APK `f6f5...` and later reinspection under `b47b...` retain the same 225,050 ms run, root/package/integration-report identities and hashes; the later APK did not generate or rerun the earlier preparation. Two integration opens and zero base archive opens are verified, with no activation or secret/ciphertext transfer. See `docs/install/inactive-native-integration.md` for full identities and evidence.
- Completed the actual inactive Android v3 preparation and retry with GPU/scripts, the intact client and the same private vault/collection. The first run exposed a shared-state parent permission conflict; integration now creates that parent privately and recovers the previously bound 0755 directory without replacing its inode/report. Ten native JVM tests pass, followed by two complete calls on the same failed Android stage. The runtime remains PREPARED; activation and complete protected model execution remain unfinished.
- Verified the real native filesystem RPC transport under Android's application context with official, authenticated CPython 3.14.7 Android/Bionic. All 34 responses and 12 grouped checks pass, including policy changes on one inode, actual asyncio/subprocess/FD transport, protected-file refusals and EOF lock release. Independent ADB collection verifies bytes, inode and APK executable hashes. This resolves the supervisor's observed GNU set_robust_list incompatibility without modifying Android security; the full process executor and Desktop routing remain unfinished.
- Integrated the official package step into the inactive Android coordinator before vault creation. The actual Fold prepares Debian, its account, the intact client and a private GNOME collection, then repeats the complete call without reopening the base archive or supplying the package download. Both calls preserve the same root/package inodes, report, ciphertext and collection; independent ADB verification passes. Forty-three journal tests and 34 strict fixture-parser checks pass. This v2 root remains inactive; the later v3 increment above adds integration preparation, while protected commands, lifecycle and activation remain unfinished.
- Corrected two Mesa renderpass lifetime bugs behind the settings-menu corruption: the first draw now sees its own threaded-context metadata, and each new Zink rendering instance resets its render area before applying current damage/resolve bounds. The selected foldgpt5 driver keeps native Adreno acceleration. All 24 independent GLES pixel regressions pass on the Fold, along with Vulkan/GLX probes, the 20 settings sections and repeated real Plugins/Browser taps after a normal restart. See `docs/verification-gpu-renderpasses-2026-09-06.md` for the comparison evidence and diagnostic limits.
- Implemented native metadata and canonicalization for the managed filesystem RPC backend. All 48 host checks pass; the expanded Android Zygote fixture verifies real metadata, directory creation, existing-path canonicalization and denied-plan preservation under UID 10412 and inherited seccomp. The later direct RPC and private bridge fixtures above add Android transport evidence; model-request integration remains unfinished.
- Added conditional PRoot SIGTERM cancellation with protected initial-fork setup and cleanup of pending child attachments. Twenty-two real nonroot host cases pass. Android's public Process.destroy now terminates the actual guest tree; the Zygote fixture independently verifies three reaped descendants and repeats the existing storage, Debian execution and shared-memory checks.
- Added authenticated official-client package input and an inactive package-install entry point. Real Debian ARM64 package installation, original maintainer scripts, package inventory and interrupted same-root recovery pass under nonroot host PRoot/QEMU. Android integration and device execution were completed in the later increment recorded above.
- Verified the official integrated browser with two real Codex turns on the Fold: open/read Example Domain, click its link to IANA and navigate back. Recorded actual CUA calls/results and independently checked the final page. This qualifies those browser operations only; PiP and remaining browser features are not certified.
- Added native `fs/createDirectory` handling, including recursive creation with policy checks for every missing ancestor before mutation, parent inode checks and 0700 directory creation through file descriptors. Forty-one transport/native file tests pass under unprivileged WSL, including a separate stdio server creating a directory then writing and reading a file. Linux and Android helpers compiled in this increment; subsequent Android fixtures above exercise the operation. The production executor remains unfinished.
- Replaced the obsolete Termux URL adapter with a validated, acknowledged Android link bridge. The real guest opens Example Domain in Android's selected browser; background launches and invalid numeric hosts are refused. The official client's internal browser remains independent. Nine Linux socket tests and four URI tests pass; no browser-task automation claim is made.
- Joined inactive Debian/account preparation to the Android vault and a supervised private GNOME collection. Actual Android failures exposed an overlong PRoot-translated socket path and a receipt field-count mismatch; both are corrected. Two complete device preparations now preserve the original failed stage, ciphertext, collection and journal without reopening the archive or activating the root. Forty unprivileged host tests also pass, including safe process-failure diagnostics. The complete installer remains unfinished.
- Corrected three executor review failures: bounded independent stdout delivery now allows EOF cleanup under saturation or malformed input, strict native ENOENT diagnostics retain Codex's NotFound code, and unsupported `.git` file creation is refused before mutation. Thirty-one transport/native tests pass under unprivileged WSL; twenty-three transport tests also pass on Windows. The Android production executor remains unfinished.
- Connected the audited execution-server transport to real native read/write RPCs in a private host workspace, retaining per-request policy and explicit metadata exceptions. Twenty-six transport/native checks pass. The unchanged official Codex 0.153.4 also completes the environment handshake on the Fold with a fresh profile. Android Zygote tests verify the file helper's real reads/writes and refused aliases/incomplete inputs. Arbitrary-command policy enforcement and the production Android bridge remain unfinished.
- Integrated fresh guest account provisioning with the leased Debian transaction. Real Android testing revealed umask-filtered file modes; exact staged modes and journal-bound recovery correct the cause. The original failed stage then resumes and executes its new guest identity under Zygote, without activation. Twenty-nine host tests pass, including 24 actual JVM deaths. No binary release is claimed.

- Replaced the runtime service's development username/UID with an explicit guest account selection validated against passwd, group and real home directories before X11 starts. XDG_RUNTIME_DIR follows the guest UID. Twenty JVM/POSIX tests pass; the updated debug APK starts the existing official client with Adreno rendering. Fresh account provisioning and the complete installer remain pending.

- Integrated the independently cross-compiled PRoot/loaders/talloc/android-shmem set into the development APK and verified all five installed hashes. A new real SysV shared-memory test exposed lost errno propagation in PRoot's helper; the source patch preserves the actual error and the same Android regression now passes. Five Zygote storage/execution checks pass, the existing desktop restarts, and CDP still confirms Adreno GPU composition/rasterization. Both APK variants compile and their diagnostic separation passes. This does not complete the installer or managed executor.

- Identified and removed the separate legacy `com.openai.chatgpt.launcher`, which was also labelled FoldGPT and only opened Termux:X11. Its installed APK was backed up and hash-verified before user-0 removal with data retained. The installed application list now contains only `app.foldgpt` and the official `com.openai.chatgpt` for this setup.

- Implemented authenticated fresh-rootfs preparation and recovery. The actual Android adapter prepares and resumes Debian under the application UID; an independent verifier matches all 20,240 logical members and 20,244 physical entries. The explicit PRoot hardlink backend passes actual Zygote guest stat/statx, shared data/metadata and unlink checks, and executes pristine Debian Perl. Sixteen unprivileged JVM tests include five real process deaths during storage conversion. This remains inactive base preparation, not the complete one-click installer.
- Added an exact native runtime input gate after a release-content audit found an unused historical probe in the common native directory. The stray artifact is preserved outside packaging; rebuilt debug/release APKs pass independent library and diagnostic-class separation checks. Both variants compile and release vital lint passes; no binary has been published.

- Implemented the native landlock-basic-data-v1 process backend and strict streaming client. Actual Linux shell, security and client tests pass. Eight native executable cases also pass under the Fold's real Zygote context, including denied access, failed exec, allocation/virtual-address limits, cancellation and descendant cleanup. Android Scudo remains enabled with its measured address reservation accounted for. This is not the complete managed Codex executor.

- Verified FoldGPT restart with both old Termux applications disabled, then removed those packages for user 0 while preserving their private data and verified original APK backups. FoldGPT starts without them. Replaced the integrated display notification, disconnected screen and help with application-owned FoldGPT UI; Android confirms a silent low-importance display channel.
- Passed a real offline official Codex 0.153.4 command/exec fixture under Landlock/seccomp on the Fold, with four permitted opens, denied protected-file writes and independent native verification. Added bounded scratch fchmod and the observed private Rust spawn channel. This does not complete the production executor; an intermittent PRoot temporary-directory startup failure remains documented.
- Corrected memfd/ashmem detection before DMA-BUF synchronization without swallowing exporter failures. Rebuilt and installed Xlorie, selected the tested Mesa foldgpt4 revision, and verified GPU composition, GLX/Present/pixmap tests and the visible File menu. No application frame-rate claim is made. See `docs/verification-2026-09-06.md`.

- Collected the 185 exact Debian source-package versions corresponding to the pristine rootfs's 289 binaries: 605 authenticated components, three signed Sources indexes and 289 notices. Real resume, complete archive verification and 37 regressions pass. Sources for statically embedded build dependencies remain a separate distribution requirement; no binary release is claimed.
- Extended the native policy diagnostic through real execve, empty environment, descriptor cleanup and independent memory-sentinel checks. Against the same live authorized worker, an unconfined control can read memory, ptrace and duplicate its FD, while Landlock C is denied all three. Tests pass as an unprivileged WSL user with Yama unchanged; Android is compiled only and no general executor is implied.
- Built and independently hash-checked a pristine Debian 13 ARM64 base with 289 authenticated packages, neutral network/identity templates and retained package provenance. Host ARM64 checks use QEMU only during construction; no emulator, OpenAI client, shim, personal profile or keyring is in the archive. Android activation and corresponding-source distribution work remain separate gates.
- Cross-compiled PRoot, matching ARM64/ARM32 loaders, talloc and android-shmem using the official Linux NDK r29, independent of Termux. Source archives, patches and notices accompany five statically checked ELF candidates. Android execution and APK integration remain pending.
- Verified real A/B/C/A read/write confinement on one inode with Landlock in native WSL workers and independent parent checks, plus a real blocked-open watchdog. The ARM64 Android diagnostic compiles; this is not an integrated Codex executor.
- Prepared first-install keyring generation and recovery: twelve real GNOME checks pass in disposable Linux homes, including wrong-service rejection, preserved foreign collections and recovery after interrupted creation. The Android vault now serializes cross-process commits and checks file/directory synchronization. The generation API compiles but is not yet integrated or tested on the Fold.
- Added verified, transactional preparation of the five-file guest integration bundle. Thirteen host regressions pass; a pristine Debian/bootstrap installer remains unfinished.
- Added immutable policy handoff data for the audited Codex execution interface. Eight new tests pass; native process/file enforcement is not implemented by this adapter.
- Gated display handoff and runtime startup on an interactive, unlocked, focused Activity, and configured the display to honor Android's normal screen timeout independently of the service's CPU wake lock. Automatic reopening on unfold still requires a valid Android launch integration and device tests.
- Added a deterministic local Mesa review bundle containing the pinned candidate archive, complete upstream sources, FoldGPT patches/build inputs, notices and ELF requirements. Twenty-one payload hashes and repeated collection were verified. Regressions reject unreviewed archives and added private data; this does not qualify a binary release or prove repeatable compilation.
- Serialized debug Codex probe completion with Android service starts and bound listener receipt, execution and cleanup to monotonic deadlines. These lifecycle changes still need their Android runtime test.
- Built the complete corrected Xlorie library with official Linux NDK r29, preserving case-sensitive header lookup on ext4. Its 1,986 exports match the baseline and LOAD alignment is 16 KiB. The candidate APK builds and contains the verified library hash; Android runtime validation is pending reconnection.
- Implemented a pure, strict resolver for a documented subset of Codex 0.153.4 managed filesystem policies. All 23 tests pass, including independent A/B/C policies on the same path, metadata exceptions and URI boundaries. This validates lexical decisions only; native enforcement remains a separate implementation step.
- Fixed GPU archive validation/transfer races by transferring the same validated byte snapshot and comparing its precomputed digest. Six host regressions pass, including concurrent replacement, remote tampering and real Linux extraction/retry after truncation. Existing revisions remain intact. The revised Android deployment run is pending.
- Added an offline official-Codex fixture probe in a permission-protected, debug-only Android service. The binary starts under native restrictions; the final initialize/command-exec/file verification remains pending after USB disconnected. No model request or account profile is used.
- Verified actual Adreno 840 rendering in the official client through Mesa 26.2.2 Zink/Turnip: GPU composition/rasterization enabled, Vulkan and GLX pixel tests passed, X11 Present completed. Corrected Mesa's failed-pixmap-import handling; the compositor texture test now passes and the desktop is visible with `xfwm4` retained. Menu transitions still exhibit intermittent corruption; neither reliable GPU presentation nor 120 FPS is claimed.
- Prepared additional Mesa fixes for the real KGSL calibrated-timestamp ioctl and RandR refresh reporting when XF86VidMode is absent. These compiled candidate changes await device validation after USB disconnected; the installed session still selects `foldgpt3`.
- Combined the native broker and PRoot experiments: a real Debian shell created and appended permitted files while eight protected/outside redirections and two mode changes were refused. The parent independently verified contents, absent files and modes. Scratch chmod is mediated explicitly; this fixed-script proof does not implement arbitrary Codex policy or read confidentiality.
- Fixed IME endpoint lifetime across display Activity recreation: one process-owned endpoint, serialized shutdown and rebinding, and the currently resumed Activity receives requests. Repeated transitions no longer produced `Address already in use`; peer UID and inner-display checks remain enforced.
- Added private, read-only log and GPU diagnostics. The initial CDP report identified ANGLE on llvmpipe with GPU composition disabled; Android's EGL presentation alone did not establish client acceleration. Subsequent Adreno results are recorded above.
- Added debug-only native Landlock experiments under the actual application UID and inherited Zygote seccomp filter. Real writes outside the granted directory and symlink escapes are refused. A broker experiment preserves protected project metadata with four granted opens and nine expected denials, independently verified from the parent.
- Verified a fixed Debian shell under a Landlock policy installed before PRoot starts: the shell executes and an attempted workspace write is refused. The experiments are not a production sandbox or an integrated Codex executor.
- Updated the visible-Activity handoff to ChatGPT Android to use the current explicit PendingIntent launch delegation on API 36+. Automatic reopening on unfold is still not implemented.
- Added Android Keystore AES-GCM protection and private stdin delivery for the existing encrypted GNOME keyring. Two cold launches unlocked it without a Linux prompt; the one-time plaintext import was removed. Cold startup requires Android to be unlocked.
- Added inner-display gating using Jetpack WindowManager's display-area folding features. During a real user fold/reopen, the Linux display closed, the official Android client was launched, and the runtime PID remained unchanged. Reopening FoldGPT restored the existing Linux interface. This does not yet validate an active Codex task or Remote.
- Added native Android isolation probes outside PRoot. On the test device, Landlock ABI 6 and seccomp notification are available; user namespace creation returns EINVAL and mount namespace creation EPERM. The official Codex 0.153.4 legacy Landlock route rejects the tested workspace policies; local commands remain blocked.
- Built and installed `app.foldgpt` with embedded Termux:X11, a separate foreground runtime service and private Linux storage. The integrated host now runs the official ChatGPT client and Codex interface independently of the Termux runtime host.
- Compiled PRoot and matching loaders from pinned commit `7266fb3e8516535682f5a9c8f3a7e70f6506eddb`, resolving the Termux-specific loader paths.
- Added shared-memory mapping and an `xfwm4` session. Verified fullscreen at 2448 Ã— 1848; XRandR reports 119.98 Hz, with application FPS still unmeasured.
- Verified Samsung keyboard opening and closing through actual touch. Fixed unwanted reopening: only deliberate pointer input opens the keyboard. On-device tests confirmed automatic refocus stays closed, the next touch reopens, and Samsung key taps enter text.
- Added explicit keyboard visibility requests over a Unix socket with peer UID checks. The CDP bridge follows page targets and reloads without transmitting field contents.
- Added development build, migration, guest-script deployment and diagnostic tools. Migration refuses existing data and cleans private temporary archives on failure; the unvalidated legacy installer now exits explicitly.
- Reproduced a local Codex execution blocker: Debian `bwrap` 0.12.0 fails `--help` when `/proc/sys/kernel/overflowuid` is inaccessible. Local tools remain blocked.
- Prepared reviewed source for publication at `pironjulien/FoldGPT`, excluding historical media, binaries and account data. Recorded verified behavior and remaining gates in `PUBLICATION.md`.

## 2026-09-05

- Installed Debian ARM64 and Termux:X11 on the Fold without unlocking or rooting Android.
- Official ChatGPT failed its namespace checks under ordinary PRoot. A full Debian QEMU experiment reached authentication, but a custom task did not complete during the recorded test.
- Added a native PRoot startup shim, display settings, launcher APK and initial keyboard daemon. The client displayed its interface and later answered a conversation.
- Audited the shim: `chroot` returned success while an outside marker remained accessible. Recorded the isolation limits in `NATIVE-AUDIT.md`.
- The initial keyboard daemon toggled visibility and was not validated for reliable everyday touch use. The original launcher depended on the separate Termux:X11 application.

## 2026-09-07 â€” Organisation locale du poste

- Regroupe les worktrees, outils, archives et journaux FoldGPT dans `work/`, exclu localement de Git, au lieu de la racine de `C:\Dev`.
- RÃ©pare les rattachements Git et adapte les chemins des scripts au nouvel emplacement du SDK Linux et des fichiers de travail.
