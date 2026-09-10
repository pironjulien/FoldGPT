# Separate native Codex engine: integration review

Date: 2026-09-07. Status: source review and proposed port boundary only.
No phone access, no engine build, no code change, no runtime activation.

## Result and provenance

A separate engine can be designed around actual upstream interfaces, but
replacing `Environment::local()` alone cannot route the full application.
The tag has several independent process launch paths, filesystem operations
with different trust contracts, and shell/session startup paths. A real port
must cover these boundaries together and retain their policy and lifecycle
semantics. A wrapper that pretends to be a supported local executor does not
meet that requirement.

The reviewed source is the **tag** `rust-v0.153.4` in
`C:\Dev\FoldGPT\downloads\isolation-codex`, read through `git show` and
`git grep` without switching the checkout:

- Tag object: `042fb41b7c813ac7999105e886b2b7aa715b5081`.
- Dereferenced commit: `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`.
- Working HEAD at review: `008bbd5884122dc95aaece19ecfe0fc6a59dcf36`; it is
  different and was not used as the reviewed implementation.
- Source links below use the dereferenced commit, not moving HEAD.

Existing project evidence in `app-server-routing.md` records the Desktop
`CODEX_CLI_PATH` launch hook. That hook was not found in this Rust tag by a
whole-tree search: it is a client integration observation, not a Rust API
guarantee. The application and its packaged official engine can remain intact
while this hook launches a separately installed engine. Whether Julien accepts
maintaining that separate engine is a **product decision still pending**.
Technical review does not activate the hook or grant that decision.

## Actual process and file paths

All paths in this table are beneath `codex-rs/` in the pinned source.

| Entry path | Actual code path in this tag | Native integration consequence |
| --- | --- | --- |
| Environment registration | `exec-server/src/environment.rs:268` constructs the map; `:286` constructs local; `:306` reserves the ID `local`; `:750` installs `LocalProcess` and `LocalFileSystem`. `:799` derives `is_remote()` only from `remote_client`; `:898` returns `EnvironmentInfo::local()` when it is absent. | Injecting backend objects must include truthful metadata and capabilities. Neither a fake `remote_client` nor claiming a named provider is the reserved `local` instance is a valid way to force dispatch. [S1] |
| Agent `exec_command` / unified execution, local direct mode | Runtime policy/approval stays in `core/src/tools/orchestrator.rs:161,265` and `tools/runtimes/unified_exec.rs`. `unified_exec/process_manager.rs:1192` chooses `attempt.env_for()`, which runs `SandboxManager::transform`; `:1324` calls `codex_sandboxing::spawn_process`, which uses the PTY/pipe utilities. | This path does **not** use `Environment.get_exec_backend()` merely because an environment exists. A native platform sandbox and a real owned launch boundary must handle it, or dispatch must explicitly select a native executor capability. [S2–S4] |
| Agent unified execution, remote or shell snapshot V2 | `process_manager.rs:1192,1242` selects executor management when `is_remote()` or a shell snapshot is present. It calls `env_for_exec_server()`, transports sandbox intent, then `get_exec_backend().start()`. `LocalProcess::start_process()` calls `prepare_exec_request()`, optionally captures/restores a snapshot, and invokes `codex_sandboxing::spawn_process`. | `ExecBackend` is useful here but does not cover all other routes. Dispatch must describe where sandbox enforcement actually lives; it must not misuse the remote flag. The current executor branch rejects nonempty inherited FDs. [S3,S5–S7] |
| App `command/exec` | `command_exec_processor.rs:38,83` only checks local exists. It resolves the effective permission profile/network proxy, calls `core::exec::build_exec_request()` at `:312`, then `CommandExecManager::start()`. The non-Windows branch in `app-server/src/command_exec.rs:231,270` directly calls PTY/pipe spawn using the already transformed argv. | Replacing local's `ExecBackend` does not intercept this. Keep config constraints, effective permission profile, sandbox cwd, proxy lifetime, per-connection process ID, streams, timeout, resize, stdin EOF and terminate. [S8–S9] |
| App `process/spawn` and terminal control | `process_exec_processor.rs:186` requires local. `:98` starts from host env with non-inheritable variables removed. `ProcessExecManager::start()` at `:267,309` invokes PTY/pipe directly. Its request has no permission-profile field. Sessions are keyed by connection and process handle; disconnect sends kill at `:427`. | This is a separate host API, not an agent-tool approval request. Implement its actual authorized host contract within Android's mandatory application boundary; do not fabricate an agent policy that the caller never sent. Native stdout/stderr, TTY resize, close-stdin, kill, timeout and disconnect must all work. [S10] |
| `thread/shellCommand` / user shell | App thread processor requires local. `core/src/tasks/user_shell.rs:136` selects `.environments.local()`, resolves a host-native cwd, prepares login shell/snapshot/env, then creates `PermissionProfile::Disabled` and `SandboxType::None` at `:210` onward. It deliberately removes the session's managed proxy and calls `execute_exec_request()` directly. | Upstream describes this as the explicit user full-access shell, distinct from model tools. Preserve that distinction and the Android UID/SELinux boundary. A native backend must not silently report ordinary agent sandboxing here or infer that user full access grants root/system privileges. Preserve standalone versus auxiliary turn events and cancellation. [S11] |
| Legacy/core one-shot execution | `core/src/exec.rs:367` transforms a sandbox request; `:403` executes it; `:920` invokes `core/src/spawn.rs:52`, a direct Tokio child launch. `core/src/sandboxing/mod.rs:210` delegates to it. | A backend that only returns a `SpawnedProcess` cannot automatically replace call sites that require `tokio::process::Child`. Add a capture adapter or a typed common process abstraction at this boundary. [S12] |
| Agent `apply_patch` | `tools/runtimes/apply_patch.rs:175` obtains the environment filesystem and a context derived from the sandbox attempt, then passes both to `apply_patch_with_options`. It retains partial committed delta and distinguishes sandbox denial. | The existing `ExecutorFileSystem` interface is the right file adapter. Preserve policy context, symlink semantics, denial reporting and partial-write truth; never return fabricated success or drop a refused path. [S13] |
| Local sandboxed file operations | `LocalFileSystem::file_system_for()` at `:95` selects sandboxed only when the context requires it. `SandboxedFileSystem` uses `FileSystemSandboxRunner`; `fs_sandbox.rs:85` materializes roots, adds narrow runtime read access and forces restricted networking. At `:131` it uses `SandboxManager::for_file_system_helpers()`, rejects `None`, and launches the engine's own filesystem helper. `:444` directly starts a Tokio child. | A process sandbox backend must also support helper execution, or a native filesystem adapter must enforce this exact policy itself. Plain canonicalization followed by an unrestricted write is not a substitute for race-resistant enforcement. [S14–S15] |
| App file-panel `fs/*` | `FsRequestProcessor::file_system()` at `:53` obtains **local's** filesystem. Read/write/create/stat/list/remove/copy pass `sandbox=None`; file watches have their own manager and per-connection cleanup. | This is a host UI filesystem contract. Its paths and authorization must be explicit. Replacing only a turn-selected remote filesystem does not cover it. Keep the distinction from agent patch policy and preserve Android's mandatory limits. [S16] |
| Shell snapshots and initialization | `session/session.rs:1160` chooses the actual shell/zsh mode and snapshots, constructs `ThreadEnvironments` at `:1211`, then warms capability files. Old snapshot capture directly invokes `Command::new` at `core/src/shell_snapshot.rs:287`. V2 uses the prepared sandbox argv, then directly invokes `Command::new` at `exec-server/src/shell_snapshot.rs:252`. | An arbitrary opaque launcher token cannot be inserted into argv while retaining snapshot code that edits the shell argument tail. Snapshot creation, native executable provenance, env restoration, timeout and cleanup must be adapted, not disabled to make the main command pass. [S17–S18] |

The dispatch fork is visible in upstream code, not just inferred from API names:

```text
Agent approval + effective permissions
  -> UnifiedExecRuntime
     -> local direct: SandboxManager -> sandboxing::spawn_process
     -> executor-managed: ExecBackend -> LocalProcess/RemoteProcess

App command/exec -> core::exec::build_exec_request -> CommandExecManager -> PTY/pipe
App process/spawn -> ProcessExecManager -> PTY/pipe
User /shell -> ExecRequest(Disabled/None) -> core::spawn -> Tokio child
Agent apply_patch -> ExecutorFileSystem(context) -> native broker or sandboxed helper
App fs/* -> local ExecutorFileSystem(no agent context)
```

This is a bounded map of the requested execution/file/session paths. Other
subsystems can launch installed helpers, including exec-server stdio transports,
arg0 helpers and optional diagnostic commands. Dependency crates for hooks,
MCP servers, Git and shell wrappers also need an inventory before claiming a
complete Android engine port. Replacing every `Command::new` mechanically is
not proposed: those call sites have different trust and lifecycle contracts.

## Android target issues that must not be hidden

`SandboxManager::get_platform_sandbox()` recognizes macOS, Linux and Windows;
`target_os = "android"` falls through to `None` (`manager.rs:62`). Its
`select_initial()` can also return `None` when no platform implementation is
available. Executor-managed process and filesystem code explicitly reject
missing enforcement, but a port must not rely on every future caller having
the same guard. Add an explicit Android backend and fail when requested
enforcement is unavailable. Defining Android as Linux just to reach Bubblewrap
does not provide missing namespaces.

The parent-death mechanism is also Linux-only in this tag:

- `utils/pty/src/process_group.rs:22` implements `PR_SET_PDEATHSIG` with the
  parent-PID race check; `:41` is a no-op on other targets, including Android.
- `core/src/spawn.rs:97,105` and `utils/pty/src/pipe.rs:155,163` call it only
  under `cfg(target_os = "linux")`.

Consequently, successful Bionic compilation alone would not preserve Linux
process cleanup. The Android runtime must supply equivalent owned-process and
parent-death behavior, reap descendants, and demonstrate it. This is separate
from fixing any compiler or libc incompatibility. [S4,S12,S19]

## Smallest real port boundary

The smallest coherent port is a **shared native execution/policy boundary with
two upstream adapters**, plus the direct host entry points. It is not a single
environment constructor patch. Names below describe proposed responsibilities,
not code that already exists.

1. **Native runtime and enforcement provider.** Put Android launch, broker
   authentication, policy translation, native program admission and owned
   process handles in a small dedicated component outside the large core.
   Extend platform selection and `SandboxManager` to produce an explicit native
   launch plan with the full effective policy. Distinguish agent-restricted,
   user-authorized host, and filesystem-helper requests. Keep canonical roots,
   deny rules, read versus write scope, additional permissions and managed
   network enforcement. Unsupported policy must fail before process launch;
   no automatic `None`, remote-to-local fallback or unmediated restart.
2. **Process adapters.** Provide `ExecBackend`/`ExecProcess` for the existing
   executor-managed branch, and a `SpawnedProcess` adapter for the host managers
   and direct unified-exec branch. Route `command/exec` and `process/spawn`
   through this explicit dispatcher instead of assuming replacing local catches
   them. Adapt one-shot capture and user-shell at the `Child` boundary. Leave
   request validation, approvals, session ownership and event formatting in the
   upstream managers wherever possible.
3. **Filesystem adapter.** Provide `ExecutorFileSystem` backed by the native
   broker, preserving optional agent context and actual host privileges as
   distinct inputs. This avoids requiring every file operation to reexecute
   the full engine as a sandboxed helper. If retaining the helper approach,
   qualify its immutable installed executable and all helper runtime rights.
   Include stream reads, no-follow semantics, recursive operations, metadata,
   watches, errors, cancellation and committed deltas.
4. **Truthful environment and routing semantics.** Express native execution
   capabilities and sandbox ownership independently of transport locality.
   Replace relevant `is_remote() || snapshot` decisions with a typed ownership
   decision when the new backend needs executor-managed enforcement. Preserve
   real host `PathUri` conventions and roots. A truly local engine on the phone
   can have a real local host environment, but a separate provider must not be
   relabeled `local` to satisfy guards. If an explicit named native provider
   owns the host facilities, refactor the host guards and selectors to that
   real facility and report it honestly.
5. **Shell/session integration.** Select the native backend at engine session
   construction so resume, fork, cwd changes, queued work and steering use the
   same actual selection. Integrate the chosen shell, both relevant snapshot
   paths and zsh-fork escalation channels if that mode is exposed. Keep state
   restoration, PATH ordering, RC behavior, startup failure and cleanup real.
   Do not disable snapshots/TTY/queue support and call the overall port done.

There is a useful existing adapter in
`utils/pty/src/process.rs:364`: `ProcessDriver`, consumed by
`spawn_from_driver()` at `:378`. It provides stdin, split output, exit,
termination and resize, and is already used by Windows sandbox backends. It can
reduce changes to the app-server managers. It is **not sufficient unchanged**:

- `ClosureTerminator::signal()` at `:287` returns unsupported on Unix; an
  Android adapter needs actual interrupt/signal semantics and reliable errors,
  not a kill callback presented as a successful interrupt.
- The output adapter ignores `broadcast::RecvError::Lagged` at `:427`. A native
  transport must prove lossless backpressure within its declared output cap or
  extend this interface to report/recover gaps. Silent loss cannot count as
  complete stdout/stderr.
- Exit can arrive before the tail of output. The driver contract waits until
  senders close; the backend must close them only after all bytes are forwarded.
- Closing stdin must close the underlying child input after queued writes.
  Killing the controller channel must not leave the native process tree alive.

`ExecProcess` is a different contract (`exec-server/src/process.rs:198`): retained
reads by sequence plus pushed `Output`, `Exited`, `Closed`, `Failed` events,
write, signal and terminate. It has no host PTY resize or explicit stdin-close
method in this tag. Implementing only this trait cannot satisfy every app
terminal operation. Reuse the native owned-process implementation beneath both
adapters rather than translating one incomplete API into fake acknowledgments.
[S7,S19]

## Policy and session invariants to retain

The authoritative policy is still the engine's effective permission profile,
approval decision and environment restrictions. In particular:

- `SandboxAttempt` separately tracks `sandbox_requested` and the host wrapper.
  Executor-managed execution intentionally sends unwrapped argv but carries a
  `FileSystemSandboxContext` when enforcement was requested. Dropping that
  context would remove the requested protection. [S2]
- Keep explicit denied reads when additional permissions or escalated attempts
  are resolved; preserve policy refusal and managed-network denial semantics.
- A genuine user `/shell`, host file-panel request, and model `apply_patch` do
  not have identical policy inputs. Their mandatory Android envelope remains
  present in every case. No operation may gain root, modify SELinux or the
  official client through a misleading interpretation of `Disabled`.
- Native IDs must identify the owned process/session, not merely a reusable
  Linux PID. Preserve duplicate-start rejection, connection ownership,
  confirmed termination, stream closure, timeout versus cancellation and
  failure reporting. A transport disconnect must not replay a mutation.
- Keep the proxy alive through process completion and final network decisions;
  do not convert approved proxy routing into unrestricted direct networking.
- Preserve partial filesystem mutations in error reports rather than asserting
  an all-or-nothing operation that was not transactional.

The existing routing audit remains relevant: start/turn environment fields do
not cover every resume/settings/queue route. Source searches in this review
confirm default selection in `core/src/thread_manager.rs:748,1886`, cwd override
construction in `turn_processor.rs:689,904`, and local user-shell selection in
`thread_processor.rs:2459`. A separate native engine must fix this at its
session/default/host facility layer; a JSON relay cannot invent fields absent
from the official protocol. See `app-server-route-audit.md` for the prior
protocol-by-protocol evidence.

## Qualification and update cost

No tests listed here were run; these are required acceptance scopes for a
future implementation, first outside the phone. Tests must execute real
processes and filesystem operations, not mocked success.

| Change source | What must be requalified |
| --- | --- |
| First native engine port | Agent shell + patch; host command + terminal + files; default/start/resume/fork/cwd/queue/steer; shell snapshot creation/restoration; actual stdout/stderr/TTY/stdin EOF/signals; timeout, cancellation, connection loss, engine death, descendants and reaping; policy denials and allowed operations; file races, output limits and proxy enforcement. |
| Official client update | Continued meaning of `CODEX_CLI_PATH`; launched argv/environment/cwd; app-server initialize/capabilities; host process/file/event schemas; thread history and auth ownership; the real unmodified-client workflow. The official bundled executable must remain intact and independently identifiable. |
| Upstream engine update | Rebase against the exact tag/commit; enumerate new direct spawn/file paths; compare permission models/defaults and sandbox transformation; environment selection/session restoration; snapshots and zsh escalation; `ExecProcess`, `ProcessDriver` and app RPC lifecycle contracts; protocol/schema and native helper packaging. |
| Android/One UI/kernel update | Native ABI, executable provenance/labels, inherited seccomp, UID/SELinux/Binder FD behavior, Landlock ABI and vendor backports, memory/FD limits, process cleanup and PTY behavior. Passing upstream Linux tests is not Samsung validation. |
| Runtime/toolchain update | Immutable program/dependency admission, actual command behavior, executable output support, shell environment, descriptors/address space and measured resource budgets. |

Useful upstream test anchors already present in the reviewed tag include
`app-server/tests/suite/v2/command_exec.rs`, `process_exec.rs`,
`core/tests/suite/unified_exec.rs`, `unified_exec_process_events.rs`,
`unified_exec_stdin_approval.rs`, `user_shell_cmd.rs`, and the sandboxing
manager/policy tests. Add Android-boundary acceptance for semantics those host
tests do not exercise. No full engine build or phone reproducer is authorized
by this review.

**Present state:** the source offers real extension points and a bounded design
direction. It does not establish that the complete engine builds for Bionic,
that arbitrary GNU tooling runs in the new boundary, or that the composed
runtime is safe after the two unexplained reboots. Choosing this maintenance
path, implementing it and qualifying it remain separate steps.

## Pinned source anchors

- **S1** [Environment and manager](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/exec-server/src/environment.rs#L268).
- **S2** [SandboxAttempt policy transport](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/tools/sandboxing.rs#L386) and [orchestrator selection](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/tools/orchestrator.rs#L265).
- **S3** [Unified process dispatch](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/unified_exec/process_manager.rs#L1176).
- **S4** [SandboxManager platform selection and transformation](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/sandboxing/src/manager.rs#L62) and [shared spawn](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/sandboxing/src/spawn.rs#L45).
- **S5** [LocalProcess start](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/exec-server/src/local_process.rs#L275).
- **S6** [Executor sandbox preparation](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/exec-server/src/process_sandbox.rs#L78).
- **S7** [ExecBackend / ExecProcess contracts](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/exec-server/src/process.rs#L192).
- **S8** [App command request processing](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/command_exec_processor.rs#L100).
- **S9** [App command direct spawn](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/command_exec.rs#L231).
- **S10** [App host process manager](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/process_exec_processor.rs#L267).
- **S11** [User shell execution](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/tasks/user_shell.rs#L136).
- **S12** [Core execution](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/exec.rs#L367) and [direct child spawn](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/spawn.rs#L52).
- **S13** [Apply-patch filesystem path](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/tools/runtimes/apply_patch.rs#L168).
- **S14** [Local filesystem dispatch](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/exec-server/src/local_file_system.rs#L95).
- **S15** [Sandboxed filesystem helper](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/exec-server/src/fs_sandbox.rs#L85).
- **S16** [Host file-panel requests](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/fs_processor.rs#L53).
- **S17** [Session shell selection](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/session/session.rs#L1160) and [legacy snapshot launch](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/shell_snapshot.rs#L275).
- **S18** [Executor snapshot launch](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/exec-server/src/shell_snapshot.rs#L238).
- **S19** [ProcessDriver](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/utils/pty/src/process.rs#L364), [Unix signal limitation](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/utils/pty/src/process.rs#L286), and [Linux parent-death implementation](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/utils/pty/src/process_group.rs#L22).
