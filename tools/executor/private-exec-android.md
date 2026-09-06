# Private GNU guest bridge to Android — 6 September 2026

The fixed Android debug fixture v2 passed **53 RPC responses across two distinct
sessions** through a real GNU ARM64 guest bridge and an Android/Bionic broker.
It includes native directory/copy/remove operations and session-bound streaming
from a **38,797,325-byte** binary file, with physical data checks and policy
refusals. No model request or production Desktop route was connected by this test.

## Actual transport and ownership

[`NativePrivateExecProbeService`](../../android/app/src/debug/java/app/foldgpt/NativePrivateExecProbeService.java)
is a DUMP-protected, debug-only Android service. It generates private fixture
directories and a fixed argument array, snapshots the explicit diagnostic
sources, and starts the APK-owned Android/Bionic Python supervisor. It accepts
no Intent-supplied command, path or policy. The existing installed Debian tree
supplies the GNU runtime; this is not a first launch from the inactive v3 stage.

The path exercised is:

```text
offline fixture request / response
    -> GNU ARM64 stdio bridge under app-owned PRoot
    -> private AF_UNIX stream socket
    -> Android/Bionic broker outside PRoot
    -> exec-server session and portable policy resolver
    -> native file helper and actual workspace files
```

[`private-exec-bridge.c`](private-exec-bridge.c) relays bytes between stdio and
the Unix socket. It does not parse commands or rewrite policies. Both ends use
kernel `SO_PEERCRED` to check the supervisor-selected application UID. The
[`broker`](private_exec_broker.py) pins a private socket directory, publishes a
0600 socket, owns one active session and its exclusive workspace lease, and
closes that session on EOF. Shutdown removes only the socket inode it created.
There is no TCP listener.

The actual fixture and broker observations show ARM64, UID/GID 10412, the
Zygote `untrusted_app` SELinux domain, inherited seccomp 2, zero effective and
permitted capabilities, and no tracer. Their mapped files contain no PRoot or
isolation shim. The GNU guest bridge itself uses PRoot; those native-supervisor
observations do not claim that the whole transport runs outside it.

UID checks authenticate an Android app identity, not a particular executable
within that UID. The fixture owns its workspace and admits no unconfined
concurrent writers. This transport is not a production process-isolation or
request-authorization boundary.

## Operations actually exercised

[`private_exec_fixture.py`](private_exec_fixture.py) executes the following
sequence twice, retaining the real request/response envelopes:

| Operation | Responses across both sessions | Observed behavior |
| --- | --- | --- |
| `initialize`, `environment/status` | 4 | Two different session IDs; actual ready responses and workspace lease ownership. |
| `fs/writeFile`, `fs/readFile` | 10 | Binary/Unicode data round-trip; denied private-path and protected `.git/config` writes preserve the filesystem. |
| `fs/createDirectory`, `fs/readDirectory`, `fs/walk` | 6 | Real tree creation, exact directory entry and bounded walk with no errors or truncation. |
| `fs/copy` | 4 | Recursive copy preserves source bytes/inode and creates an independent destination inode; denied source copy creates no destination. |
| `fs/remove` | 6 | Protected `.git` removal is refused; removing the source preserves the independent copy, then the copy is removed. |
| `fs/open` | 8 | Two admitted opens per session; private and absent paths are refused. |
| `fs/readBlock` | 11 | Eight actual data/EOF blocks, two refused reads after close and one refused handle from the previous session. |
| `fs/close` | 2 | Closes the actual pinned file descriptor. |
| `process/start` | 2 | Explicit unsupported-method refusal, code `-32601`; no arbitrary process execution. |

There are 26 responses in the first session and 27 in the second. File-policy refusals use
`-32000` and are checked alongside unchanged bytes or absent targets. Each
bridge exits normally after EOF; a new backend reacquires the real workspace
lease. Broker events record both authenticated peers, both session closures
and shutdown. The socket is absent afterwards.

Each session reads 1 MiB at offset zero and at offset 16 MiB + 17, then requests
32 bytes where only the final 13 remain, and one byte at the exact file end.
The returned bytes and EOF flags match the deterministic physical file. The
fixture observes exactly one pinned broker FD after open, none after close,
and none after disconnect even when the client leaves a handle open. The second
session cannot use that abandoned handle. The private fixture secret remains
unchanged. This device sequence does not exercise duplicate-handle or oversized
block rejection; those belong to the separate [host streaming tests](native-file-streams.md).

The streaming subclass implements twelve file methods. The earlier direct native RPC
fixture separately covers metadata and canonicalization; they were not invoked
by this bridge sequence. See [the earlier evidence](native-files-android-rpc.md).
Supported operations still have explicit admission limits: symlinks, gitdir
aliases and unconfined outside writers are not admitted. A denied child refuses
an entire listing/walk rather than disappearing from its result. Copy rejects
overlapping trees and enforces its aggregate byte bound. An OS or transport
failure during a mutation is not an atomic rollback guarantee.

## Independent collection and exact artifacts

The v2 test APK is retained at
`downloads/private-exec/android-pex-7800203653557930252/tested-debug.apk`;
independent evidence is in its `collected-v2-20260906-r2/` sibling directory.
[`collect-private-exec.py`](collect-private-exec.py) pins the installed APK using
Package Manager and native SHA-256 before and after collection. Both pins match
the retained APK. All **28 installed native libraries** match their APK entries
on both reads, and all **eight private diagnostic sources** match the packaged
assets byte for byte.

The collector verifies every request, response ID, result, refusal, streamed
byte block and EOF flag. It rereads the final small payload, protected metadata
and fixed private fixture secret; independently generates the large-file pattern
and compares its hash and size with the actual native file. It checks ordinary
private file types, modes, identities, unchanged evidence and the absence of
removed/refused targets, dangling aliases and the IPC socket. All three actual
stderr files contain zero bytes. Historical FD/lease checks come from the
authenticated fixture source and completed report; the collector does not
reconstruct already closed descriptors. No RPC/report path becomes a collection
target, and no account, vault or user document is collected.

```text
APK             373aa5c8f4e54fb9256d599fde2f7b30f1acd34eebfce1a49db169518f37bcf4
native helper   a7d638dc9cc65fb81d9a264746d94faa3a7033f2e6e1cd049868851875179b02
Python launcher 8adcc2fab3312bdec7ad53c690c067ae80705e211c9b30279bcdf51cfd5a62d7
GNU bridge      8df6da1dd80dd07871a0b7943d34f2151147b728c905ce3174ed73133deed74a
stream helper   a57eff0d42d8996c0a370c18184dc4e9ef4086c7cd7e8abc8ece1712be13a312
large file      3b9956d06f64e0071deaf9207deb0468304f5a381a4799d420ba8e03d0569cad
fixture report  8c6768a595d6b1972ec0a7f5a9c3d2a3eab55e51ba4ea4911264c46e175eca0d
RPC transcript  efed0d3b0eafebd5eee02859d8ce333a24cdb514aa813512d1a2a810f943c5d9
collector report 1b0d24c066e1f19b8e7806e9bce180d56c935e1eb154557edee5861775b0d907
collector source e45917b123684ec11a45db27d9755af99032e3bb972554bd8d5214ae8e99c5f6
```

The exact executed collector is retained as `tested-collector.py` beside that
private collection. The repository copy uses LF for its final line as well;
that newline-only normalization changes its file hash without changing Python
statements or the recorded device evidence.

All evidence-file hashes in `independent-verification.json` were recomputed
against the retained artifacts when documenting this checkpoint. The build
recipe is [`private-exec-build.sh`](private-exec-build.sh); rebuilding a new
candidate does not replace the dated Android result above.

The earlier v1 result remains under
`downloads/private-exec/android-pex-1903360000830250665/`: 32 responses on APK
`b47b230214cf2fcd8744ebaa951fb6c2b6c6e445c2097da01528dc3734c7263b`.
The current transcript validator accepts both retained real versions and rejects
six targeted corruptions of payload, refusal, EOF, offset, response ID and
envelope. Its full device collector intentionally refuses a historical fixture
whose executing APK no longer matches the installed package; v1 was not rerun
under the v2 APK.

## Remaining integration

This is a fixed diagnostic using new files and no account. A production broker
lifecycle, actual Desktop/environment selection for normal and resumed tasks,
trusted task-policy routing, arbitrary protected processes, TTY and networking
still require implementation and real model-task validation. The private bridge
does not repair the official workspace-runtime Linux ARM64 manifest 404, qualify
Remote, activate the prepared installation, or establish a distributable APK.
