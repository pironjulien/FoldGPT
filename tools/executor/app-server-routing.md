# Official app-server environment selection

`app_server_routing.py` preserves every policy, approval and model field while
selecting the separately configured FoldGPT executor for `thread/start` and
`turn/start`. It follows the audited `rust-v0.153.4` protocol, commit
`042fb41b7c813ac7999105e886b2b7aa715b5081`. Sixteen semantic regressions cover
resume, failed requests, explicit and empty selections, workspace root changes,
approval transparency and initialization capabilities.

`app_server_adapter.py` provides an opt-in, bounded stdio relay around the
unchanged official executable. It checks its reported version before starting,
forwards responses and server requests byte-for-byte, uses pipe backpressure and
closes its child on disconnect. It never logs protocol payloads or rewrites a
managed policy. Its version check is compatibility checking, not package
authentication; the installer must independently authenticate the binary.

The adapter is **not enabled in the phone session**. A private diagnostic now
verifies its real transport with the untouched official Android-hosted GNU ARM64
Codex 0.153.4. Native GNU admission and production integration remain required.
Desktop host RPCs still pass through to the official local implementation.
This module therefore does not resolve host command/terminal Bubblewrap use.

`thread/resume` does not accept an environment field. The router learns the
directory and roots from its successful official response, then selects the
FoldGPT environment explicitly on the next turn. A turn pipelined before that
response is refused rather than pointed at the launch directory. `thread/fork`
uses the same response learning. Queued submissions after resume but before the
first routed turn, remote connections, internal task creation, and host commands
still require actual runtime inspection before production enablement.

An explicit empty environment list keeps its official meaning on subsequent
turns in the same adapter connection; only a successful explicit selection
reenables access. Failed empty selections leave the previous state intact.
Unknown remote
environments and selection extensions are rejected before forwarding. Explicit
selection paths keep official precedence over legacy top-level paths. A legacy
cwd-only update retargets the former cwd root, preserves additional roots and
deduplicates, matching the tag's `TurnProcessor::build_environment_override`
logic in `app-server/src/request_processors/turn_processor.rs`.

The tag does not return `thread.environments` in start/resume/fork responses.
A fresh adapter cannot reconstruct an older task's explicit disabled selection
from cwd/roots alone. A known disabled selection is preserved within the current
connection across resume/fork. This ambiguity must be resolved before production
resume support; routing an unknown resumed task is not a proof of preserved prior
environment policy. `thread/settings/update` can also rebuild default environment
selections inside the official server, and queued/steered turns may activate
without a new routed `turn/start`. These entry paths remain unqualified.

The current bounds cover individual wire frames and pipe backpressure. They do
not establish bounded total per-connection thread bookkeeping or arbitrary
concurrent request ordering. Those production transport concerns remain open.

## Real private Android handshake

`verify_app_server_adapter.py` runs from frozen sources staged under the app's
`cache/x11`, creates a new private HOME/CODEX_HOME/XDG profile, and verifies the
official executable SHA-256
`4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6`.
It calls only `initialize`, `environment/info`, and `environment/status`. Its
client sends `experimentalApi=false`, so the successful experimental environment
queries also exercise the actual initialize rewrite. The configured environment
is the existing fail-closed transport with no execution backend.

The Android run in `downloads/app-server-routing/20260906-225301/` passes:
the actual official environment answers with the private workspace URI and
`status=ready`, stdin EOF shuts down the adapter with exit 0, stderr is empty,
and independent collection verifies all five staged source hashes. No diagnostic
process remains in the post-EOF process listing, and the private profile has no
authentication or session artifacts. Raw sources, report, configuration and
collection checks are retained. No APK, normal runtime configuration, account,
task or model request was changed. This proves transport compatibility, not
normal protected command execution or complete Desktop routing.

The stdio adapter is a FoldGPT component outside the official package. The
observed Desktop `CODEX_CLI_PATH` hook can launch it, but no current configuration
is edited by these files. Future client updates must revalidate that hook and
the experimental environment contract. No MCP/plugin is involved.
