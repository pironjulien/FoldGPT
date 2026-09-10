# Static native process lifecycle

`NativeProcessesBackend` implements the five official process methods and the
three process notifications from the pinned `rust-v0.153.4` executor protocol
(`042fb41b7c813ac7999105e886b2b7aa715b5081`). This is an opt-in backend for the
existing static native managed-acquisition profile. It does not select a Desktop
environment or provide arbitrary shell, dynamic runtime, PRoot, TTY, managed
networking, shell snapshots, directory metadata or namespace mutation support.

## Actual launch and native protocol

The original acquisition CLI remains supported. Lifecycle uses:

```
native-managed-runner ROOT_FD POLICY_FD STATIC_ELF WALL_MS ADDRESS_BYTES OUTPUT_BYTES UID_TASK_BUDGET --process-v2 STDIN_FD COMMAND_FD ENV_FD -- ARGV...
```

`STDIN_FD` is a distinct owned read-only pipe; it becomes target descriptor 0.
Only its trusted Python writer can enqueue bytes. When `pipeStdin` is false the
writer is closed before spawn, so the target observes actual EOF. An empty
`process/write` chunk is an empty write, not an undocumented EOF operation.

`COMMAND_FD` is a separate authenticated same-parent/same-UID Unix seqpacket
socket. Its one-byte `I` and `T` commands request real SIGINT to the owned command
group and native termination respectively. It is polled during syscall policy
waits, launch waits and stdout/stderr backpressure. The supervisor does not
signal a leader PID after reaping can release that PID for reuse.

Before forking a worker, v2 opens a pidfd for **itself**, transfers that actual
descriptor over the authenticated policy socket with `SCM_RIGHTS`, and waits for
the parent's `P` acknowledgement. The Python owner validates one CLOEXEC pidfd,
its actual `/proc/self/fdinfo` PID and signal-zero identity before acknowledging.
No parent-side lookup of a potentially recycled numeric PID selects the target.
The ordinary control socket remains the primary cancellation route. Fallback
SIGTERM and final SIGKILL use only `libc.pidfd_send_signal` on the retained pidfd.
It stays owned until asyncio has observed supervisor exit; no `Popen.kill`,
`Popen.terminate`, `Popen.poll` or additional parent `waitpid` competes with
asyncio's child watcher. The native supervisor separately owns all worker and
descendant waits. NDK r29 declares both pidfd libc symbols from Android API 31;
the authenticated Bionic runtime must expose these real symbols and kernel APIs.
The earlier v1 native mode is retained for its frozen historical callers.

`ENV_FD` is a bounded sealed memfd holding NUL-terminated `NAME=value` entries.
The Python parent calls the actual `libc.memfd_create` and integer `libc.fcntl`
interfaces on both host and Android. It does not depend on CPython exposing
`os.memfd_create`, `MFD_*` or the sealing constants. These Linux UAPI constants
are checked by native-process-fd-abi.c compiled against host and NDK r29 headers;
the frozen build retains the headers, their hashes, and compiled ABI observations.
NDK r29 declares the Bionic memfd_create symbol from Android API 30.
The native supervisor requires all write/grow/shrink/seal seals, reads the bytes
into private memory and rejects malformed or duplicate entries. Supervisor
environment remains empty. Target environment is exactly the explicit RPC map
after the pinned official final scrub: remove the executor EOF-control variable
and case-insensitive non-inheritable launch secrets. `envPolicy` is refused at
admission until its exact pattern and ordering semantics are implemented.
`arg0` changes target argv0 independently of runtime executable selection.

All private descriptors close before actual exec. The native started profile is
`managed-process-v2`, still emitted only following real `PTRACE_EVENT_EXEC`.
A separate native `exited` frame records the leader's actual wait status before
reaping; final `result` follows descendant reaping and pipe drain. Native claims
are checked against actual received output counts and the observed leader status.
The existing complete policy resolver, copied pathname/open_how acquisition,
Landlock, seccomp, FD injection and explicit UID budget remain unchanged.

## Registry and official wire

Process keys are `(session_id, caller processId)`, never OS PIDs. Reservation
is synchronous before any launch await. A retained record owns immutable request
bytes, complete policy, immutable runtime mapping, actual native lifecycle,
streams and write IDs. Lifecycle requests cannot replace sandbox intent.
The registry has an explicit private capacity of 128 records.

The five responses and notification shapes match the official protocol:

- `process/start`: processId and `sandboxType: linuxSeccomp` only after verified
  native exec and enforcement. Unsupported context and actual exec failure return
  RPC failure after cleanup; neither emits a false started response.
- `process/read`: Base64 stdout/stderr chunks, nextSeq, exited, exitCode, closed,
  failure and sandboxDenied. Sequence numbers start at 1 across output/exited/
  closed. afterSeq is strict; maxBytes is a whole-chunk budget which always permits
  the first available chunk, including for zero. Without maxBytes, nextSeq is
  the current next event sequence. waitMs waits without blocking other methods.
- `process/write`: accepted/unknownProcess/starting/stdinClosed. A bounded writer
  queue enqueues bytes and remembers writeId atomically before another await.
  Duplicate accepted IDs cannot enqueue twice, including concurrent retries.
- `process/signal`: real interrupt; unknown, starting and exited targets return
  the official empty response. A signal is not reported as successful cleanup.
- `process/terminate`: running reflects a known starting/live record; native
  cancellation and cleanup continue asynchronously. A starting reservation is
  retained until cleanup, avoiding replacement of an owned launch in progress.

Output/exited/closed notifications retain their official shape. The native Unix
signal convention is `128 + signal`. Real nonzero command exits are preserved.
Timeout/output exhaustion remain failures. `sandboxDenied` is false unless a
future classifier has evidence linking a failure to confinement; an ordinary
nonzero exit is never guessed to be a sandbox denial.

Output history retains the upstream 1 MiB/50,000 chunks and accepted write IDs
retain the upstream 4,096 entries. Completed records expire after 30 seconds.
These are bounded histories, not permanent deduplication or lossless archives.
An already accepted write ID remains accepted after its stdin closes; a new
write to a closed pipe reports the upstream internal write failure. The
stdinClosed status denotes a process launched without pipeStdin.
The private stdin queue admits at most 1 MiB and 128 pending chunks. Notification
queue exhaustion or transport failure triggers termination and a truthful
failure; it cannot block read/signal/terminate or native reaping.

## Filesystem composition and failures

Process launches serialize on a mutation lease for their full lifetime.
`files_backend=` may lend an already pinned `NativeFilesBackend` (or its streaming
subclass) and shares its actual mutation lock and root descriptor. The policy
adapter does not close a borrowed descriptor. A composed owner must close process
sessions before disposing of the shared filesystem backend. Process output,
stdin, reads, signal and terminate never acquire this mutation lock.

The workspace remains exclusively owned; arbitrary concurrent unconfined writers
are outside the admitted profile. Runtime mappings are trusted constructor input
and must name immutable executor-managed assets. No worker chooses native roots,
control descriptors or policy decisions.

Supervisor loss or missing native cleanup proof does not create an invented exit
or closed notification. The process read response retains failure with unknown
cleanup; the backend quarantines later launches and retains both the root lease
and the actual shared mutation lock. A composed filesystem cannot resume writes
until recovery has independently established that the descendants are gone.
The process backend sets `quarantine_event` before retaining that lock. Its
composed owner can cancel blocked filesystem RPCs and return an explicit failure
without unlocking the workspace or admitting another mutation.
There is no crash-recovery claim, atomic filesystem rollback, metadata-secrecy
claim, or guarantee of wall-bounded reaping of kernel-blocked tasks.

`native-process-build.sh` freezes the Python closure and native sources, builds
host/ARM64 artifacts, rechecks Android Scudo geometry, runs the 17 unchanged
acquisition tests and the lifecycle suite as actual nonroot processes, and records
raw native observations and hashes. Host results and Android compilation do not
establish Android execution; that requires an independently collected device run.

The lifecycle suite has 23 tests, including actual exec permission failure,
binary streams, genuine pipe input and EOF, concurrent duplicate writes and
cancelled writes under backpressure, real interrupt versus terminate, cursor
budgets, environment/argv0, same-inode policy transitions, cross-session IDs,
startup cancellation, actual forked-child reaping, output retention and limits,
shared filesystem mutation ownership, and actual supervisor SIGKILL. That last
test uses a separate process-local subreaper in the fixture to independently reap
the orphan while checking that the backend itself reports unknown cleanup.
The shared-filesystem variant first proves a real native fs/writeFile, kills
the real supervisor, then proves another fs/writeFile remains blocked with the
original bytes intact while process/read and process/terminate remain responsive.
This test requires `--files-helper`, a real native-files helper binary; the build
exports it as `android/libfoldgpt-native-process-files-helper.so`. It may instead
use the identical existing native-files helper already packaged by the owner.
The libc memfd test reads back real bytes/seals and proves that kernel write,
shrink, grow and reseal attempts fail with EPERM. Its report records which Python
APIs/constants are exposed on the actual interpreter, alongside the libc route.

Two pidfd tests establish actual supervisor SIGTERM with the correct asyncio
return code and no child-watcher warning, and a raw protocol run that observes
zero children while acknowledgement is withheld. After acknowledgement the
actual worker appears, native cleanup passes, and the still-open original pidfd
returns ESRCH after reaping instead of selecting a recycled PID.
Another real SCM_RIGHTS test refuses wrong-PID, pipe, duplicate, truncated and
missing descriptor transfers while independently checking that no FD leaked.

The 6 September v2 host snapshot `foldgpt-native-process-build-tyYOXDCt` passes
all 23 lifecycle tests (109 observations) and 17 acquisition regressions as UID
65534. ARM64 static compilation and the Scudo geometry check pass. Its runner
SHA-256 is `bfe9cdfea084d7a5a8a664826b5a68359fadfc1051fba5be5ab540124ef8177a`.
This snapshot does not replace the earlier Android execution evidence at commit
`ca152ac`/APK `1a54dd8c`; the v2 Android rerun and independent collection remain
separate requirements. The [composite transport](native-executor-transport.md)
also retains the actual pre-fix child-watcher failure and the corrected run.

Android v2 initially completed 22 of 23 tests: its kernel does not expose
`/proc/PID/task/PID/children`. The raw gate observer now inventories actual
`/proc/PID/status` PPid/UID identities instead. It records two pre-ACK empty
inventories and the post-ACK native worker, verifies parent starttime before and
after each inventory, and refuses unreadable same-UID candidates. Foreign-UID
denials and actually vanished PIDs are explicitly classified. Composite cleanup
and runner/worker tests share this observer; missing proc files never imply an
empty family. The portable host snapshot `foldgpt-native-process-build-XyjPqBoX`
passes 23 lifecycle and 17 acquisition tests with the unchanged native runner.
The collector selects this observation shape from the packaged suite source,
retaining compatibility with historical v1 and pre-portability v2 evidence.
Seventeen offline integrity checks pass, including the genuine 22/23 Android
failure and altered-copy refusals for missing or contradictory proc inventories.

The independently retained Android `android-23c8555b/collected-pass-v2` and
`android-6c802375/collected-pass-v2` both record 23/23 PASS and 109 observations.
The latter includes `_wait_owned`: already-owned asyncio futures are observed
with `asyncio.wait` followed by `result()`. This retains cancellation and cleanup
ownership without Python 3.14 `shield` installing an additional exception logger
when another waiter is cancelled. It does not disable logging or conceal an
unretrieved future. The motivating composite 8/9 failure remains preserved.
