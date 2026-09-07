# Native file/process composite transport

This increment connects the real file, streaming and static process backends
behind the existing C stdio bridge and private Unix socket. It is a diagnostic
transport composition. No Desktop environment is selected, no model request is
made and no normal project build or general shell/runtime support is claimed.

## Ownership and supervisor inputs

`NativeExecutorBackend` owns one pinned filesystem backend and lends its actual
root descriptor and mutation lock to `NativeProcessesBackend`. It exposes the
same `mount` expected by `private_exec_broker` and the union of implemented
methods. `sandboxedFileStreaming` is the only advertised optional capability.
One bound session owns both sets of handles; other session IDs are refused.

The old file-only broker arguments remain valid. The supervisor explicitly
opts into composition with:

```
--handle-helper NATIVE_FILE_HANDLE
--process-runner NATIVE_MANAGED_RUNNER
--executable ADMITTED_NAME IMMUTABLE_NATIVE_EXECUTABLE
--process-wall-ms MILLISECONDS
--process-address-space-bytes BYTES
--process-output-bytes BYTES
--process-uid-task-budget TASKS
```

The executable mapping may be repeated with distinct names. Duplicate names,
invalid resource allowances and process options without a runner are refused.
Requests can select only a mapped name and cannot change supervisor paths or
limits. The admitted process profile still requires a private ordinary workspace,
complete per-process filesystem policy and an explicit environment. Files must
meet its real native admission checks; the broker does not silently chmod user
files. TTY, arbitrary shells/dynamic runtimes and managed networking remain
unsupported and are refused explicitly.

All filesystem operations and later starts wait behind a live process's shared
mutation lease. Process read, stdin and termination remain responsive. A process
cleanup failure wakes and refuses pending file operations and pending starts,
while retaining the actual lock. Composite close owns one shielded task and
replays the same failure on repeated calls; it cannot hang retrying a removed
process record or accidentally release the quarantined filesystem.

Before accepting any composite RPC, the fixed broker endpoint durably creates
`process-session.json` in its private socket directory. The record binds the
actual workspace device/inode and broker UID/PID; it is removed only after
verified clean session closure. Unknown cleanup retains both backend ownership
and the marker, rejects reconnects, and survives a later ordinary broker stop.
A broker crash also leaves the marker. Even file-only startup at that same
endpoint refuses it. There is no automatic deletion based on PID absence and
no recovery claim: independent supervisor recovery must establish descendant
cleanup first. UID authentication does not distinguish hostile programs sharing
that UID, and this cooperating fixed-endpoint contract is not a new isolation
boundary against a different unconfined supervisor.

## Recorded host proof and causal correction

Run `bash tools/executor/native-executor-transport-build.sh` under Linux. The
script freezes the Python/native sources, compiles actual static workers and the
C bridge, and executes all tests as an ordinary nonroot UID. It retains failed
runs as well as successful runs under `downloads/native-executor/`.

The first fixture used mode 0644 files, correctly rejected by native workspace
admission; this failure is retained in `foldgpt-native-executor-foGoJcTB`.
The fixture now creates its own private files with explicit 0600 mode.

Capturing and asserting real broker stderr subsequently exposed an intermittent
cleanup error: CPython's `Popen.send_signal` polled/reaped the supervisor before
the asyncio pidfd watcher, which then reported `returncode 255`. The retained
`foldgpt-native-executor-eAtYZqbo` run has 2 failing tests. Its logs were not
suppressed. [Lifecycle v2](native-process-lifecycle.md) corrects this by transferring
a self-pinned pidfd and acknowledging ownership before the native worker fork;
fallback signals never invoke the Popen polling path or use a bare PID.

`foldgpt-native-executor-ICYhC7DI` passes all nine composite transport tests and
all seven existing file-transport regressions as UID 65534. Its composite report
contains 83 real response/notification frames, 35 broker lifecycle events and
independent file/inode, process, lock and marker observations. Normal broker
stderr is empty, including EOF with a live descendant and SIGTERM with a live
native process. It tests:

- One session writes a file, reads/writes it through an actual native process,
  reads its streaming descriptor, and verifies same-inode bytes and policy denials.
- Real binary stdin/stdout/stderr, duplicate write IDs, SIGINT versus terminate,
  and ordered official process notifications.
- A real file mutation waits for process cleanup while termination stays live.
- EOF, killed C bridge and broker SIGTERM reap actual workers/descendants and
  release descriptors, root lease and the session marker.
- Actual runner SIGKILL refuses queued writes/starts, reports unknown exit and
  cleanup, retains quarantine after disconnect, rejects reconnects and refuses
  restart without altering the marker. A separate test observer reaps the real
  orphan; that observation does not manufacture a broker cleanup result.
- Broker SIGKILL retains ownership evidence; process and file-only restarts
  refuse it. Invalid supervisor configuration never opens an endpoint.

## Android integration and retained execution evidence

The runtime modules required by the composite are `exec_server.py`,
`native_files.py`, `native_file_streams.py`, `native_process_policy.py`,
`native_processes.py`, `native_executor_backend.py`, `policy_intent.py`,
`private_exec_broker.py`, `native_environment.py`, `native_environment_unicode.py`
and `tools/policy/managed_policy.py`.
The diagnostic also needs `test_native_executor_transport.py`,
`test_native_processes_live.py` (its shared fixed policy fixture),
`native_files_rpc_fixture.py` (native context inspection) and
`native_executor_android_fixture.py`. These 15 files are declared identically
in the new debug service, Gradle debug asset set and APK separation check.

Native inputs are the newly matched v2 ARM64 managed runner, unchanged static
process fixture, native-files helper, native-file-handle helper, and the actual
GNU ARM64 C guest bridge. They must be bound to the same frozen source hashes,
authenticated Bionic CPython assets and tested APK. Native supervision must stay
outside PRoot with the real inherited Android seccomp policy. Only the guest
bridge traverses PRoot. `NativeExecutorProbeService` supplies the actual Bionic
bootstrap's `--home PREFIX -- SCRIPT` contract, fixed APK programs, installed
guest root, private PRoot loader paths and a fresh `cx-*` evidence directory.
It accepts no command, path or policy from an Intent. The service is debug-only,
uses its dedicated `:nativeExecutorProbe` process and requires Android `DUMP`.
No source in the normal client, keyboard or Antigravity integration changed.

The suite now binds the authenticated C bridge PID to a pidfd. Its killed-bridge
test targets that actual GNU bridge, allowing its PRoot supervisor to finish
cleanup normally. Native broker context is observed outside PRoot; the GNU
bridge's actual tracer PID and mapped libc are checked separately. Android
retains all nine case directories, including quarantined markers, for independent
inspection. This is not an automatic marker recovery operation.

The adapted host snapshot `foldgpt-native-executor-6UK3BrV3` passes all nine
composite tests and seven prior file tests as UID 65534. The retained-case
variant also passes all nine; a separate host read verifies each retained
directory, file device/inode and private bytes. Both probe services and their
helper compile with javac 17 against the configured Android 37 SDK. The complete
preparation record is
`downloads/native-executor/android-source-02ef6a9912254b6e8487cb949ddaae4b/`.
No Gradle or ADB command was run for these preparation checks.

The lifecycle wrapper now requires all 23 v2 tests and binds `testsRun` and
`nativeProcessProfile` in its report. The independent lifecycle collector checks
supervisor pidfd identities, acknowledgement, signal route, real wait status and
the two raw identity/transfer cases. Eleven offline tests pass against the real
23-test host snapshot and retained Android v1 PASS20 and failure18/19 evidence;
altered copies lacking pidfd/cleanup proof or containing the returncode255 warning
are rejected. Those checks preserve historical evidence without executing it.

Android acceptance must rerun file/process/stream interleaving, real stdin and
signals, the pidfd acknowledgement gate, clean disconnect/reaping and actual
runner-loss quarantine. Independently collect exact source/library/APK hashes,
UID/peer identities, final files/inodes, observed processes and retained marker
identities. Neither these host results nor ARM64 compilation establish that
Android composite path, production Desktop routing or a normal model task.

The first actual composite execution, APK `dec1eece`, records six passing cases
and three failures: Android lacks `/proc/PID/task/PID/children`. The shared child
observer now retains a real PPid/UID process inventory and rejects unreadable
same-UID processes rather than reporting an invented empty family. Host snapshot
`foldgpt-native-executor-wsswHA53` passes all nine composite and seven prior file
tests with that observer. Android APK `23c8555b` then records eight of nine PASS;
case07 correctly fails on actual Python 3.14 shield exception diagnostics.
Its native descendant quarantine assertions completed, but stderr remains a
real failed acceptance condition. Both complete failures and retained cases are
preserved under `downloads/native-executor/android-*/failure-*`.

The lifecycle owner now observes its already-owned futures through
`asyncio.wait`/`result()`; the packaged Python 3.14 source demonstrates why
cancelled `shield` waiters otherwise add a second exception-reporting callback.
The corrected host snapshot `foldgpt-native-executor-t5do5Qb3` passes nine
composite and seven previous file tests. Host results remain distinct from the
subsequent Android acceptance run.

`collect-native-executor.py` independently collects a fixed completed `cx-*`
probe, binds its exact thirteen sources and installed native programs to the
tested APK, correlates actual transport request/response identities, checks
native/guest context observations, and rereads nine retained files, inodes,
private bytes, stderr logs and quarantine markers. Failed suites remain
`OBSERVED_FAILURE` without PASS artifacts. Twelve offline integrity checks pass
against the corrected host snapshot and both real Android failures, including
altered-copy refusal cases. They read retained case bytes directly from each
failure archive without executing or changing it. Historical proc snapshots,
process liveness, timing and lock observations cannot be reconstructed by later
collection; guest runtime libraries beyond the APK program closure are not
independently hashed. No normal Desktop route or arbitrary-command sandbox is
qualified by this diagnostic.

The corrected Android run in APK `6c8023753649884d448ae7911f304ac6e4e86a5486c8704a00b97a67b7c18153`
passes all nine composite cases. The independently collected result is retained
at `downloads/native-executor/android-6c802375/collected-pass-v2/independent-verification.json`.
That historical APK contains the previous thirteen-source closure. The new
fifteen-source closure adds the actual five-field environment-policy resolver;
collectors derive the expected closure and case11 refusal from the supplied
packaged sources, retaining the older successful and failed archives separately.

The fifteen-source Android build now also passes all nine cases with the normal
FoldGPT interface running. APK `3ba18fd629681f075cf2d827717e5dc1484963518b84366d03f55938040b99c8`
and fixture `cx-744289973968909795` are bound in
`downloads/native-executor/android-environment-20260906/collected/independent-verification.json`.
The collector confirms actual file/process/stream interleaving, binary stdin,
signals, cleanup and retained quarantine evidence. This verifies packaging and
the composite regression; it does not exercise GNU or model task routing.
