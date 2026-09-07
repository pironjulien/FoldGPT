# Android engine integration at Codex 0.153.4

This is a source-backed port plan and an independent PC prototype, not a deployed
engine. It uses `rust-v0.153.4`, commit
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`, without changing the inspected checkout.
The successful fixed Shizuku/Bionic trial does not establish this integration.

## Decision: implement the real local host runtime

Keep the official Desktop client and its bundled executable intact. Its observed
`CODEX_CLI_PATH` launch hook selects the separately installed FoldGPT engine. The
engine owns one actual Android local runtime, with a broker process boundary.
The ID `local` is created by `EnvironmentManager`, not by a named remote provider.
Keep `include_local=true`; with no separately configured environments, the default
list contains exactly the Android local host. Do not rewrite application RPCs.

This closes default selection for start, cold resume, fork, cwd-only settings,
queue and steering through the existing shared environment manager. Explicit
empty environment selection still disables model environment access. The host
file panel and terminal remain the host facilities, as upstream specifies.

The broker transport being IPC does not make this a remote host. Keep
`is_remote()` false. Add independent execution and filesystem ownership metadata:

```rust
pub enum SandboxOwner { Controller, Executor }
pub struct LocalRuntimeBackends {
    pub exec: Arc<dyn ExecBackend>,
    pub filesystem: Arc<dyn ExecutorFileSystem>,
    pub host_processes: Arc<dyn HostProcessBackend>,
    pub process_sandbox_owner: SandboxOwner,
    pub filesystem_sandbox_owner: SandboxOwner,
    pub info: EnvironmentInfo,
}
```

These are proposed engine types, not fields supported by the official JSON API.
Resolve and authenticate this object once at engine startup, before constructing
the `EnvironmentManager`. Do not take the backend endpoint or policy from a
model command's environment variables. Fail startup if the configured runtime
cannot be authenticated; do not fall back to the GNU/Linux local launcher.

`Environment::local()` must use these real backends. `Environment::info()` must
return their measured Android shell, home, cwd, temp paths and capabilities,
instead of the engine controller's `EnvironmentInfo::local()` when they differ.
If the engine remains in the existing GNU userspace, its controller paths are
not automatically valid Android worker paths. All project paths and shell paths
must be resolved consistently by the native runtime; a substring replacement
of `/home` or an opaque launcher token is not a path implementation.

## Adaptation order and exact upstream boundaries

All paths below are beneath `codex-rs/` in the pinned commit.

| Priority | Source boundary | Required change |
| --- | --- | --- |
| P0 | `exec-server/src/environment_bootstrap.rs::PreparedEnvironmentManager::build`; `environment.rs::EnvironmentManager::from_snapshot`, `Environment::local`, `Environment::info` | Inject authenticated local runtime once; preserve reserved local ID, default selection, immutable object identity and true metadata. |
| P0 | `core/src/tools/runtimes/unified_exec.rs::uses_executor_managed_process_sandbox`; `core/src/unified_exec/process_manager.rs:1192,1242` | Select executor ownership independently of `is_remote()`. Preserve `env_for_exec_server`, effective permissions, additional permissions and requested-sandbox context. Snapshot presence remains another reason to use executor management. |
| P0 | `core/src/tools/runtimes/apply_patch.rs::uses_executor_managed_process_sandbox`, `file_system_sandbox_context_for_attempt` | Use filesystem ownership. Preserve partial committed writes, denial reporting and exact policy context. |
| P0 | `app-server/src/request_processors/command_exec_processor.rs:312`; `core/src/exec.rs::build_exec_request` | Select the native launch plan before Linux wrapper transformation. Carry effective permission profile, roots, sandbox cwd, network proxy lifetime and timeout into a typed host launch request. |
| P0 | `app-server/src/command_exec.rs::CommandExecManager::start`; `request_processors/process_exec_processor.rs::ProcessExecManager::start` | Keep existing per-connection maps and event orchestration; replace only the spawn branch with the local host process backend returning `SpawnedProcess`. Preserve true stdin EOF, terminal resize, signals, exit and output closure. |
| P0 | `core/src/tasks/user_shell.rs:136,210`; `core/src/exec.rs::execute_exec_request`, `core/src/spawn.rs` | Route the explicit user host shell through the same real host runtime. Its upstream `Disabled/None` policy does not authorize root, Binder use by workers or modification of the official app. Adapt the Tokio `Child` capture path to the common process handle instead of manufacturing a `Child`. |
| P0 | `exec-server/src/local_file_system.rs`; `app-server/src/request_processors/fs_processor.rs::file_system` | Install `AndroidFileSystem` in the actual local environment; file panel requests retain their `sandbox=None` host semantics and mandatory Android boundaries. Agent context remains distinct and fully enforced. |
| P1 | `exec-server/src/shell_snapshot.rs`; `core/src/shell_snapshot.rs`; `core/src/session/session.rs` | Run native snapshot capture/restoration through the provider. Preserve attachment scope, shell argv, native state files, rc behavior, timeout and cancellation. Do not disable snapshots to make dispatch pass. |
| P1 | `app-server` file watch manager; `ExecutorFileSystem` streaming and walk operations | Provide the native watch/stream lifecycle, no-follow semantics, symlink/error behavior and connection cleanup. A host filesystem trait replacement alone does not redirect the separate watch manager. |
| P1 | helper launches in `core/src/session/mcp_runtime.rs`, hooks, Git, shell escalation and capability discovery | Classify controller infrastructure versus workspace execution; route the latter and apply the actual intended policy. Never mechanically replace every `Command::new`. |

`SandboxType::AndroidLandlock` should be an explicit internal backend result, with
the matching `ProcessSandboxType` mapping for our engine/broker. Extending that
internal enum requires updating exhaustive matches, denial classification and
metrics; it must not rename an unenforced operation as Linux sandbox success.

Three separate capability axes matter. Execution policy ownership, filesystem
ownership and controller-native path usability must not all be replaced with
one new `is_remote()` synonym. For example, plugin attribution currently chooses
native filesystem access in `core/src/session/turn_context.rs:369` when local;
the corresponding adapter is needed when project paths live behind the broker.
Network proxy placement is a fourth independent decision: retain proxy routing
and policy decisions even when the execution transport is local IPC.

## Preserve these exact protocol contracts

The upstream executor request is `exec-server-protocol/src/protocol.rs::ExecParams`:

```text
processId: ProcessId                     # connection/session key, not OS PID
argv: string[]
cwd: PathUri
envPolicy?: ExecEnvPolicy
shellSnapshot?: { scopeId: string, shell: { name: string, path: string } }
env: map<string,string>
tty: bool
pipeStdin: bool                          # default false
arg0: string|null
sandbox?: FileSystemSandboxContext
enforceManagedNetwork: bool              # default false
managedNetwork?: ManagedNetworkSandboxContext
networkProxy?: RemoteNetworkProxyLaunchConfig
```

`FileSystemSandboxContext` carries `permissions`, optional `cwd`, `workspaceRoots`,
`userHomeDir`, `temporaryDirectories`, `windowsSandboxLevel`,
`windowsSandboxPrivateDesktop`, optional `windowsSandboxProxySettingsMode`, and
`useLegacyLandlock`. The native policy parser must consume the typed permission
tree; it must not replace it with a hardcoded workspace read/write policy.
Unrepresentable semantics must be rejected before any mutation or process start.

The application host process contract is different:

```text
process/spawn:
  command, processHandle, cwd, tty, streamStdin, streamStdoutStderr,
  outputBytesCap, timeoutMs, env, size
process/writeStdin: processHandle, deltaBase64?, closeStdin
process/resizePty: processHandle, size:{rows,cols}
process/kill: processHandle
```

Here `outputBytesCap` and `timeoutMs` distinguish omission from JSON null:
omission selects the server default; null disables that host API limit. `env`
maps names to strings or null, with null removing the inherited variable. PTY
implies streaming input/output. These requests carry no agent permission profile.
The Android mandatory envelope is additional host reality, not an invented agent
approval request. A backend resource refusal is an actual error, not success
under an arbitrarily shortened timeout.

`command/exec` instead has `processId`, `sandboxPolicy`/`permissionProfile`,
`disableTimeout`, `disableOutputCap`, and mutually exclusive explicit values.
Keep its final response after all output notifications. Preserve upstream
validation instead of merging these two RPCs into one approximate wire schema.

## Process adapter prototype scope

`ExecProcess` supports sequenced retained reads/events, write, interrupt and
terminate. It lacks the host resize and explicit stdin-close methods. Therefore
it cannot itself be the terminal API. Both it and the host `SpawnedProcess`
adapter should consume one native owned-process implementation.

The existing `utils/pty::ProcessDriver` uses broadcast receivers and ignores
lagged output. Its closure terminator also does not provide Unix interruption.
The independent prototype adds an owned driver with bounded mpsc output and
explicit fallible control operations, retaining the old driver for existing
callers. This makes native transport integration possible without silently
dropping output or acknowledging an unsupported interrupt.
For explicit host kill/terminate RPCs, use the prototype's fallible
`ProcessHandle::try_request_terminate()`: both upstream managers currently call
the void `request_terminate()` followed by `Ok(())`. Keeping that exact sequence
would incorrectly acknowledge a native controller transport failure. Automatic
drop/timeout cleanup can retain best-effort calls while the broker remains the
owner and reports the actual outcome.

The broker must independently retain process ownership until all descendants
are reaped, even if the engine disappears. It sends process exit, stream closure
and cleanup status as distinct facts. Native child stdout is never the trusted
control channel. Duplicate IDs, request retransmission and unknown cleanup must
not launch a second copy of a command.

## Completion gate

A compilation of the auxiliary engine is only a build result. Completion needs
the unchanged official client to create/edit/test/build the agreed Python project
through ordinary model tools, then exercise file panel, host terminal, cold
resume, cwd settings and queued work. Confirm real denial, stdout/stderr, stdin
EOF, resize, cancellation, disconnect and descendant cleanup. The current fixed
offline trial establishes the native protection building block, not these routes.

The new local runtime approach preserves normal official client updates. Each
update still needs compatibility checking of its launch hook and app-server
protocol against the separately maintained engine.
