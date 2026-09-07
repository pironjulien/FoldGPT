# Small Python project through the native executor

Current Android result: **V2 passes all 20 independent checks on the real Fold**.
See [the device report](../../../docs/research/native-runtime-v2-device-result-2026-09-07.md).
Frozen qKM94iHA and the Python CLI with deployment-prefix RUNPATH are qualified
for this fixed project. Failed V1 remains preserved. Ordinary UI execution is
still an integration requirement. The preparation history below does not
supersede this result.

The independent Android package is `app.foldgpt.runtimequalification.v1` and
its sole deployment base is
`/data/local/tmp/foldgpt-bionic-runtime-qualification-v1`. The selected backend
is `tools.executor.bionic-supervisor.runtime_qualification_factory:factory`.
This is a fixed diagnostic facade over the real dynamic `NativeExecutorBackend`,
not the earlier Shizuku C probe without notification mediation.

## Installed inputs and request contract

Before admission, the operator creates a fresh private base containing the
authenticated Python runtime, an empty broker directory, and `workspace`.
The workspace contains empty `directory` and `.git` directories, plus
`private/secret` with exactly `probe-private-unchanged\n`. All belong to the
nonroot Shizuku shell identity; the base is mode 0700. Existing workspaces and
attempt evidence must not be reused.

The bootstrap's inventory admits the actual installed Bash, Python CLI,
supervisor, file helpers, Python libraries and the existing cwd library.
`backendOptions` use the ordinary helper/executable filename markers.
Runtime grants are exactly the Bash and CLI files (execute), the base's Python
directory (read), and `SYSTEM_RUNTIME` from `runtime_qualification_factory.py`.
`cwdShim` identifies the attested `libfoldgpt_bionic_cwd.so`. The facade adds
the actual installed native directory derived from `sys.executable`, after
the existing bootstrap inventory checks; RPC never chooses that directory.
No arbitrary directory marker is added to the common transport.

`LIMITS` in `runtime_qualification.py` are the exact deployment limits. They
bound this small operation and are not an aggregate phone memory allocation.
`parentEnvironment` is absent or empty. No permissions, namespaces, kernel,
SELinux or official-client setting is changed by this qualification.

The Activity performs the ordinary authenticated ExecServer handshake, then:

1. Sends the exact `process/start` produced by
   `process_request(workspace, installed_python_cli)`. Only the packaged
   `FOLDGPT_PYTHON_REAL` environment filename marker is resolved to the actual
   installed path. No arbitrary substitution is performed inside Bash code.
2. Sends `process/write` with `input_request()`. The process ID is
   `runtime-qualification`, write ID is `qualification-input-v1`, and the
   stdin bytes are exactly `native input\n`. Exact write retries retain the
   real backend's idempotence.
3. Waits for `process/closed`, preserving all actual notification frames, then
   sends `process/read` with only the fixed process ID.
4. Sends `fs/readFile` with `file_request(workspace)` and compares its decoded
   material bytes with the actual stdout bytes. The facade rejects this read
   before clean native ownership and rejects other file requests.
5. Closes the session and independently checks the existing bootstrap/JNI
   lifetime result. The Python evidence does not attest its own reaping.

Only one exact start is accepted. Changed code, environment, policy, cwd,
stdin payload and unrelated controls are refused by the facade before the
underlying backend. Actual file access, read/write streams, process admission,
policy decisions and native lifecycle still use the production implementation.

## What the real workload checks

Bash changes its real cwd into `directory`; Python creates `project`, changes
its real cwd there, writes a calculator returning 41, edits it to return 42,
and creates three unittest cases. A real interpreter child runs discovery.
Python builds a compressed zipapp and executes it in another child, obtaining
exactly `42\n`. A further child receives binary stdin, returns identical
binary stdout, produces separate stderr and exits with 23. Child environments
are explicitly empty; their execution does not depend on the cwd preload.

Eight actual operations must be refused inside the interpreter: private read,
private write, protected `.git` write, IPv4 socket, Unix socket, ioctl, a
signal-permission query on the outside supervisor, and entering the denied
private directory. These are real exceptions with EACCES or EPERM, not flags
supplied by the RPC client. The cwd library changes the real cwd using a
mediated directory descriptor; the raw chdir syscall remains denied.

The public worker result is one JSON line, with no stderr. Its schema is the
exact structure validated by `validate_report`; the 18 `proofs` values must
all be JSON `true`. The material `qualification-result.json` must equal that
stdout byte for byte. The private evidence schema is
`foldgpt.bionic-runtime-qualification.private.v1`, preserving the real process
record, complete output, supervisor PID/return code/wait, quarantine, source
hashes and built archive identity. `validate_artifacts` independently opens
the archive, checks its CRC and compares its three source files with the
tested final project. Collection never traverses a quarantined workspace.

## PC validation and discovered cancellation race

The first frozen-source PC run used PHREPY0u and the existing cwd library
IpMWhNfc. The complete project, replayed output, fs/readFile material result,
duplicate-start refusal, exact-write idempotence and negative fixtures passed.
Without the cwd library, the unchanged raw chdir denial correctly stops Bash.

An additional real early-cancellation test exposed a pre-existing race:
the supervisor abandons a policy-response receive after cancellation while
the Python broker still sends the outstanding response. Closing the Unix
SEQPACKET socket with unread inbound data resets the peer, losing its final
proof. The existing backend correctly quarantines and reports failure;
it does not invent successful cleanup. Baseline evidence, including this
failure, is retained under
`downloads/runtime-qualification/facade-host-hp_h5z7d`.

A separate candidate initially prevented responses after requested termination,
but independent review showed that this alone missed autonomous timeouts and
responses already in flight. The final correction seals the native receive
half with `SHUT_RD`, drains queued decisions and transmits the actual final
record. Python continues receiving after `EPIPE` while still requiring a final
record and the real owner wait. Startup cancellation/timeout is preserved.

Six tests on real host processes cover cancellation during the first decision,
autonomous expiration, command EOF, a response already queued, a delayed startup
acknowledgment, and a missing final result retaining quarantine. All pass on
`tAfr3AJp`; five deliberately fail against unchanged `PHREPY0u`.
The full project/facade suite passes all five tests on that corrected build.

The final packaging build is **`foldgpt-bionic-supervisor-N0kMFS8z`**. It also
includes host-independent POSIX paths in the contract, so Windows staging and
collection use real Android path syntax. The payload executed by Bash/Python
is unchanged. The six control tests and five project tests pass on this exact
frozen source, as do the canonical factory/resolver/kernel checks. Android
supervisor SHA256 is
`6bccc77b4f2dff0f78fd22e4f6427263ee159d87b35c740e8be0622319fd4dd4`.
The current compiled runtime CLI SHA256 is
`7de6f5ba8d620c3a796810147686c645cf10b2d412b00aea63a8dc7eec5a0f50`.

The [PC evidence inventory](../../../recovery/verification/native-runtime-pc-20260907/manifest.json)
preserves actual results plus two failed host invocations. A rebuild under the
same host UID as concurrent Rust work hit process/thread failures (`EAGAIN`);
its sources/output are retained and it was not frozen for deployment. The
canonical builder's separate unprivileged test identity passed. An invocation
with the ARM64 Android cwd library on x86 Linux also failed to preload, as
expected; selecting the actual host `.host.so` produced the passing project
results. Neither host preparation error was a phone test or a policy change.

`tools/runtime/stage-native-qualification.py` now admits the exact runtime base
with its empty project directory, while preserving kernel fixtures. Python
staging uses the distinct runtime identity, and the read-only snapshot compares
its private sentinel and protected directory. Eleven PC identity/staging tests
pass, including rejection of crossed profiles before any ADB call. The new
phone fixture has been created and independently verified; the runtime worker
has not yet been launched at this checkpoint.
