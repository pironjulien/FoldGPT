# Native executor integration: verified seam and policy handoff

This directory contains the audited stdio execution-server transport, immutable
policy handoff, a bounded native process backend and the first real file RPC
backend. These components are not yet a complete protected Android executor.
The default server refuses process/file operations until a backend is supplied.
See [native filesystem integration](native-files.md) for the actual tests,
official-client handshake and remaining admission limits.

Separate native experiments now verify [exact-file A/B/C/A rights](native-abc-proof.md)
and [exec startup plus three concurrent peer-access checks](native-exec-peer-proof.md)
on WSL. Their Android binaries compile but have not run on the Fold. These
diagnostics remain separate from the policy handoff and any execution server.

## Source boundary

Rechecked locally against official Codex **0.153.4**, tag `rust-v0.153.4`, commit
`042fb41b7c813ac7999105e886b2b7aa715b5081`, using `git show` at that tag. The local
checkout HEAD differs. These are source-level findings about this exact version,
not a promise that future Desktop versions expose the same experimental APIs.

The earlier detailed audit is `logs/executor-integration-review.md`. The public
native policy requirements are `tools/policy/managed-policy-contract.md`.

## Options supported by the inspected code

| Route | What the code actually provides | Consequence for FoldGPT |
| --- | --- | --- |
| `CODEX_HOME/environments.toml` | A named environment with either `program`/stdio or `url`/WebSocket; args/env/cwd and initialization timeout are supported. | The configuration can select an independently implemented executor while leaving the official app and executable intact. It does not make the stock executor's native sandbox replaceable. |
| Normal agent tools on that environment | Commands use exec-server `process/start`; normal `apply_patch` uses the selected executor filesystem. Both carry the portable sandbox context. | This is the concrete integration seam for full native process and file protection. |
| Official legacy Landlock mode | `useLegacyLandlock` reaches an actual non-bwrap branch, with network seccomp and broad read plus writable-root Landlock rules. | It explicitly rejects policies requiring direct runtime enforcement and restricted read-only access. It cannot preserve all requested policies. Do not flatten such policies to make this branch accept them. |
| An outer native engine around stock exec-server | Stock `process_sandbox.rs` still transforms managed requests into its own platform sandbox; its filesystem helper does likewise. | Merely enclosing the official server does not replace bwrap initialization. An environment must implement the executor backend itself. |
| Desktop launch adapter using observed `CODEX_CLI_PATH` | The earlier distributed-client inspection found this executable override. It can preserve the packaged binary and mediate app-server transport. | It may select environments and implement separate host RPC integration; it cannot intercept internal model tool calls by forwarding stdin/stdout alone. |

The preferred route remains an environment executor with a real native
supervisor outside PRoot. PRoot supplies path/ABI compatibility inside each
worker. It is not the enforcement layer. A read-only global Landlock grant plus
a write broker cannot implement deny-read exceptions or the complete policy.

## Agent operations and Desktop host operations are different APIs

| Surface in 0.153.4 | Policy and routing |
| --- | --- |
| Executor `process/start` | `argv`, URI `cwd`, environment policy, stdin/tty, optional shell snapshot, full `sandbox`, managed network requirement and proxy context. |
| Executor `fs/readFile`, `writeFile`, `open`, directory/metadata/canonicalize/walk/remove/copy | Policy-bearing filesystem operations. Streaming handles must remain attached to the policy and session that created them. |
| App-server `command/exec` | Requires local environment; resolves its own permission profile; no environment ID in the request. |
| App-server `process/spawn` | Requires local environment and has no per-turn sandbox policy field. It starts the Desktop host process manager. |
| App-server `fs/*` | Uses `try_local_environment()` and passes `sandbox=None`. These are host/UI file operations, not normal model edits. |
| App-server `thread/shellCommand` | Explicit local-host shell path. |

`include_local=false` removes these host facilities from the stock app-server;
that is an integration gap, not a completed full-feature solution. Keeping local
enabled also requires explicit environment selection: the environment manager's
default list includes **all** configured environments, not just the first one.
The ID `local` is reserved. Existing/resumed tasks and turn overrides need the
same routing review, including connections established through Remote.

Host operations with no per-turn policy need an explicit trusted UI/host
contract. Never manufacture a managed policy from an absent field or silently
reroute a failed managed operation into a local/unsandboxed path.

## Implemented policy intent interface

`policy_intent.py` calls the strict existing resolver and creates an immutable,
normalized context snapshot. It retains the **complete portable context**,
including ordered entries, deny rules, explicit metadata exceptions, workspace,
home and temporary roots. It does not compile them into a writable-root list.
Unsupported features and unknown fields remain errors for the whole input.

```python
from tools.executor.policy_intent import prepare_policy_intent

intent = prepare_policy_intent(
    received_sandbox_context,
    session_id=supervisor_session_id,
    request_id=supervisor_request_id,
    method="process/start",
)
context_bytes = intent.context_json
audit_digest = intent.context_sha256
handoff_bytes = intent.to_bytes()
```

The UTF-8 handoff object has these exact fields:

| Field | Meaning |
| --- | --- |
| `schema` | `foldgpt.policy-intent.v1`; this is FoldGPT control data, not a new official exec-server response. |
| `resolver` | Exact audited upstream tag and commit. |
| `sessionId`, `requestId`, `method` | Supervisor-owned correlation with a single policy-bearing operation. |
| `contextSha256` | SHA-256 of deterministic normalized `context` JSON bytes. An identifier for audit correlation, not authentication or a bearer capability. |
| `context` | The normalized official portable policy context accepted by the strict resolver. Original rule order is preserved. |

Canonical context encoding is UTF-8 JSON with sorted object keys, compact
separators, literal Unicode, and no non-finite numbers. Array order is unchanged.
The complete command enforcement engine is not implemented here. A native consumer
must validate this control message and schema itself; a digest matching an
untrusted message establishes no authority.

Process lifecycle calls and `fs/readBlock`/`fs/close` intentionally cannot create
a new intent. The supervisor must retrieve the immutable policy already bound
to their session-scoped process or handle. A new, weaker context must never
replace that binding.

The native supervisor must pair this intent with the exact operation payload
and its own guest/native mapping and pinned roots. Worker input cannot choose
the policy, native FD numbers, mount map, or a wider policy identifier. No
runtime permissions are inferred from the caller's environment variables.

## Native admission still required

Before any success response or `sandboxType: linuxSeccomp` declaration, the
native implementation must establish the requested policy across actual path
resolution, runtime loader/executable access, metadata and worktree `gitdir`
targets, hardlink aliases, descriptor acquisition/reopen, mutation syscalls,
process and network boundaries. Deny exceptions need a real mechanism; additive
Landlock grants cannot subtract a child path from a granted parent.

Use a separately confined worker for each policy. Preserve cancellation,
stdin/tty, output ordering, handle lifetime and descendant cleanup. Supporting
one fixed probe does not establish arbitrary-command enforcement. The pinned
protocol requires managed networking to fail closed when its enforcement
context is missing or unsupported. Unsupported operations must return explicit
errors before mutation rather than a successful placeholder.

Next credible integration evidence is an unauthenticated isolated environment
handshake plus native process/file conformance tests, followed by one normal
Desktop command and one normal `apply_patch` through that environment. None of
those integration or device tests is claimed by this directory.

## Checked source references

All paths are relative to `codex-rs` at the commit above:

- `exec-server/src/environment_toml.rs:22-47,63-91,140-165` — configuration and transports.
- `exec-server/src/environment.rs:359-376` — default plus remaining environments.
- `exec-server-protocol/src/protocol.rs:19-42,76-140,256-290,418-588` — actual wire methods, capabilities and policies.
- `file-system/src/lib.rs:174-210,237-291,330-348` — complete portable filesystem context.
- `exec-server/src/process_sandbox.rs:155-244` and `fs_sandbox.rs:90-165` — stock backend retains its sandbox transformation.
- `linux-sandbox/src/linux_run_main.rs:290-332,377-390` — bwrap/default, legacy branch and direct-runtime-policy rejection.
- `linux-sandbox/src/landlock.rs:70-85,128-161` — restricted-read rejection and broad legacy read grant.
- `app-server/src/request_processors/command_exec_processor.rs:83-89`, `process_exec_processor.rs:69-142`, `fs_processor.rs:53-93` — local-host routing and missing per-turn policy.

Run the new pure handoff checks from the repository root:

```powershell
python -B -m unittest tools.executor.test_policy_intent -v
```

These checks verify serialization, immutable snapshots and rejection behavior.
They do not run an executor, connect to a phone/model, or prove kernel isolation.
