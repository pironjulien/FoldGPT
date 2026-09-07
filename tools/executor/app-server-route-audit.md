# Routing closure audit, official 0.153.4

This audit reads the actual `rust-v0.153.4` tag, dereferenced commit
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a` (annotated tag object
`042fb41b7c813ac7999105e886b2b7aa715b5081`), through `git show`/`git grep` in
`downloads/isolation-codex`. The working HEAD is a different protocol version.
It does not claim that normal app routing is ready or change a running profile.

## Concrete protocol boundaries

`thread/start` and `turn/start` accept explicit environments. The current router
selects the GNU environment on those requests without changing policy fields.
`ThreadResumeParams`, `ThreadForkParams`, `ThreadSettingsUpdateParams`,
`ThreadQueueStartParams` and `TurnSteerParams` have no corresponding field.
Adding one to their JSON would not implement a supported environment update.

For a cold resume, `thread_processor.rs:3831` calls
`ThreadManager::resume_thread_with_history`. The subsequent spawn defaults to
`default_thread_environment_selections` when no selection or inherited snapshot
was supplied (`thread_manager.rs:1786` and `:1885`). The thread response does not
return the selected environment list in this tag. Keeping a disabled selection
in the relay's memory does not itself reconfigure this independently resumed
core session; routing its next turn remains necessary. A previous relay cannot
claim to have restored a persistent selection that the official API did not
expose. A live rejoin is a different path and can retain an existing session.

`thread/settings/update` with cwd calls `build_environment_override` with no
explicit selection (`turn_processor.rs:903`). That routine rebuilds the full
default environment selection, retargeting the previous cwd root and preserving
other roots. The protocol has no field for asking that update to keep only the
GNU environment. Omitting the requested cwd, synthesizing an empty turn, or
fabricating an acknowledgment would alter the requested operation.

`thread/queue/start` dispatches to the queue service and core directly
(`thread_queue_processor.rs:184`). It does not become another external
`turn/start` request that the relay could rewrite. Queued automatic starts and
steering similarly require the core session's environment to be right already.
Reconstructing a queue start as a different turn would also change queue state,
message identity, atomicity and failure semantics.

## Supported default selection, and its effect on host APIs

The official `environments.toml` supports `include_local = false` and one named
GNU environment (`exec-server/src/environment_toml.rs:29`, `:72`). With that
configuration, `EnvironmentManager::default_environment_ids` has only that
environment (`exec-server/src/environment.rs:360`), so ordinary startup, cold
resume and cwd-only settings updates can all default to GNU without a per-turn
rewrite. This is an actual upstream capability; it is not enough on its own to
preserve the complete app.

The same manager omits its local environment instance when `include_local` is
false (`environment.rs:280`). The following official host-facing routes require
that local instance and consequently fail rather than using the named GNU one:

- File panel RPCs: `request_processors/fs_processor.rs:53`.
- One-off host commands: `command_exec_processor.rs:83`.
- Host process/terminal RPCs: `process_exec_processor.rs:186`.
- `thread/shellCommand`: `thread_processor.rs:2454` explicitly describes this as
  the local-host shell escape hatch, distinct from a turn-selected shell tool.

Keeping `include_local = true` preserves those routes but reintroduces local into
every default selection: `default_environment_ids` returns the default first,
then every other configured environment. It is not a "preferred environment only"
setting. Setting `default = "none"` would disable task environment access and is
not a correction. The environment ID `local` is reserved even when local is
omitted (`environment.rs:306`); naming a stdio provider `local` is not a supported
replacement for the local instance.

## Integration consequence

Two pieces must land together before a complete app acceptance test: a native
provider chosen by all task start/resume/settings/queue paths, and a complete
implementation of the host RPC contracts that currently insist on the local
instance. The existing GNU broker is the execution/transport building block;
host wire requests still need their actual schema, policy, process identity,
streaming, cancellation, TTY and filesystem semantics preserved. Unsupported
semantics cannot be hidden by changing the approval or sandbox policy, dropping
an RPC, or returning a simulated success.

The current stdio router can continue to support isolated explicit diagnostics.
It cannot by itself close these missing core entry paths, and it must not be
advertised as full resume/settings/queue support merely because a routed
`turn/start` command succeeds. No new router mutation was made during this audit.
