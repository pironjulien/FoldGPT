# Actual official host companion

`host_rpc_mux.py` is a working, opt-in transport increment. One persistent
official app-server owns accounts and tasks; a second persistent official
app-server owns host file operations and connection-scoped processes/watches.
Both execute the unchanged official binary. There is no host thread mirroring,
no synthesized command result and no conversion of a sandbox policy.

## Concrete routing

| RPC family | Destination | Preserved semantics |
| --- | --- | --- |
| `fs/readFile`, `writeFile`, `createDirectory`, `getMetadata`, `readDirectory`, `copy`, `remove` | Host | Official absolute paths, defaults, symlinks, actual filesystem errors/results |
| `fs/watch`, `fs/unwatch` | Host | Same persistent connection owns watch IDs and `fs/changed` notifications |
| `process/spawn`, `writeStdin`, `kill`, `resizePty` | Host | Same persistent connection owns process handles, PTY, env set/unset, output caps, timeouts and exit notifications |
| `command/exec`, `write`, `resize`, `terminate` | Host | Entire request including `sandboxPolicy`/`permissionProfile`; actual deferred response and streaming notifications |
| `environment/info`, `environment/status` for `local` | Host | Actual host shell, cwd and readiness |
| Accounts, tasks, turns, queues, settings, approvals, other environments and other methods | Main | Original messages and request IDs; no task state copied to host |
| `thread/shellCommand` | Main | Still blocked when its actual main session lacks a local environment; never converted into a different host operation |

The pinned protocol is `rust-v0.153.4`, commit
`042fb41b7c813ac7999105e886b2b7aa715b5081`. The host schemas are in
`app-server-protocol/src/protocol/v2/{fs,process,command_exec}.rs`.
In particular, **the official `process/spawn` API is already unsandboxed**. It
inherits its actual app-server environment, then applies caller sets/unsets and
the official non-inheritable-variable filter. The relay does not turn a
sandboxed request into this API. `command/exec` remains sandboxed according to
the received policy or its official configuration.

Initialization goes to both actual servers. Only the real main response is
published, after both have succeeded. Every routed request, response and host
notification is forwarded with its original bytes. There is no JSON-RPC ID
remapping. Only main owns server-initiated UI requests and approval responses;
the audited host families emit no such requests. An unexpected host request
fails the relay instead of mixing decision namespaces. Main remains
authoritative for global/account/task notifications; the companion forwards its
host notifications and actual configuration warnings.

Client EOF closes both official inputs and drains their final output while their
connection owners clean up processes and watches. Failure of either side closes
the combined transport. Abrupt supervisor death/unknown descendant cleanup
still requires the external native supervisor's ownership/quarantine contract;
the diagnostic CLI does not claim crash-proof descendant ownership.

## Launch integration

The `Launch`/`relay` library interface accepts two exact supervisor-owned
commands, cwd values and explicit environment dictionaries. A production native
supervisor can provide its attested stdio bridges here for independently launched
GNU app-server instances. The CLI intentionally accepts only direct official
`app-server --listen stdio://` launches and checks the supervisor-supplied binary
digest. No normal application launch is edited.

The host must see its intended GNU paths and configuration. A practical Android
recipe is an independent native PRoot launch with the same runtime, cwd, HOME,
CODEX_HOME and effective user/project/managed config as main, while a **single
supervisor-owned `environments.toml` file is bound in that process's path view**
with `default = "local"` and `include_local = true`. Main's provider can then
contain only the GNU executor with `include_local = false`. This needs no root
or VM and does not overwrite the official package or the main provider file.
The root supervisor must qualify that concrete launch and its cleanup; the mux
does not silently invent Android paths or bindings.

A copied, separate CODEX_HOME is sufficient for an isolated transport test, but
is **not production configuration parity**: named permissions, rules and the
environment inherited by terminal commands could differ. Replacing a missing
permission profile with an approximate policy would be wrong. Configuration
refresh behavior across both instances also needs validation with the real
launcher. Task-related requests must never be duplicated merely to populate the
companion's memory.

## Verified increment

`verify_host_rpc_mux.py` ran under UID 65534 with two actual official Linux
0.153.4 processes. The archive came from the official GitHub release; its release
asset digest is
`f479424eca092484dc40d87ae28c44f4cc40234a60045d6131e493800d814a30`.
The extracted executable digest is
`56ef98ab4032d317ab26e9b5e5a175650717351edb16ed9cde0cb6d1734d62da`.

The actual test passed file read/write/copy/remove, default recursive behavior,
symlink handling, an inotify-backed watch, binary stdin/stdout with exit 23,
environment unset handling, a real PTY starting at 61x19 and resizing to 97x31,
process kill, connection EOF cleanup, an exact official conflicting-policy
error, an explicitly unconfined command with exit 17, and a streamed command
with deferred exit 7. No account, thread, turn or model request was made and
neither profile contains auth or session artifacts.

Frozen sources, both launch specifications, complete wire evidence, real output
and release provenance are retained in
`downloads/app-server-routing/foldgpt-host-mux-proof-hvq654zl/`.

The read-only command test retained its original policy and could not write its
guard file. Its **actual result was exit 101 with the official missing-bwrap
panic**, which was forwarded intact. That is proof of honest error propagation,
not successful confined host execution. No default sandbox was weakened to
obtain the other test results.

## Remaining session-bound operation

`thread/shellCommand` needs substantially more than a matching thread ID.
`core/src/session/handlers.rs:98` selects the active turn and its cancellation
token, or creates a standalone shell turn. `core/src/tasks/user_shell.rs:141`
then requires **a local environment inside that actual turn snapshot**, not just
the manager's local instance. It derives the shell/login/snapshot/environment
policy, injects the real thread/session identities, emits command item events
and records output into that session (`user_shell.rs:457`).

Resuming the same ID in a second app-server would create a second live session;
it would not share the main session's active turn/cancellation/rollout state.
Executing a host command and fabricating those acknowledgments/events would not
preserve the official operation. The mux deliberately leaves this request with
its sole authoritative owner. Consequently this increment preserves real host
files and terminals, but **cannot yet enable the entire native interface** until
confined host commands and this main-session shell path are implemented.
