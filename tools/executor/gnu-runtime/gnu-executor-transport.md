# GNU composite private executor

`gnu_executor_broker.py` is an opt-in diagnostic supervisor entrypoint. It uses
the existing `NativeExecutorBackend` file/stream owner, the GNU process adapter,
and the unchanged `private_exec_broker` Unix listener. The existing C
`private-exec-bridge` supplies the stdio side. No official package, app profile,
environment selection, system protection or device setting is changed by it.

The supervisor supplies canonical native paths for the file helper, read-handle
helper, GNU managed runner, strict PRoot, GNU rootfs, both PRoot loaders, private
workspace, PRoot scratch, guest temporary root and socket directory. The four
writable/IPC roots must be separately owned private directories with no overlap.
Runtime inputs must remain outside those roots. The prepared workspace must
contain a private `.home` directory. The GNU image must contain working executable
paths `/bin/bash` and `/usr/bin/env`; admission checks their real image targets.

The default diagnostic maps this single workspace to `/workspace`, `.home` to
`/workspace/.home`, and the distinct guest temporary root to `/tmp`.
`--guest-workspace` can select another canonical project path, including under
`/root`; overlap with runtime/control trees and ambiguous PRoot binding syntax
is refused. Cwd and home metadata and the parent HOME follow that exact mapping.
It advertises
Bash `/bin/bash`, platform `linux`, and exactly those GNU URIs. The Bionic broker
host's shell, home and temporary paths are never used as environment metadata.
The process parent snapshot is built explicitly from `PATH=/usr/bin:/bin`,
`HOME=/workspace/.home`, `TMPDIR=/tmp`, `SHELL=/bin/bash` and `LANG=C.UTF-8`.
No ambient environment is read or inherited into that snapshot. The full RPC
environment policy still determines actual process inheritance and overrides.

The optional process factory is a constructor-only seam. RPCs cannot select it
or replace its immutable executable mapping. File streams, process/control RPCs,
shared workspace lease, session identity, shielding of cleanup, and quarantine
remain owned by their existing backends. The GNU adapter also retains the
temporary-root lease until process cleanup is verified. Kernel `SO_PEERCRED`
checks authenticate the supervisor-selected nonroot UID, not one particular
binary within that UID. The persistent process-session marker remains after a
broker crash or unknown cleanup, and the existing listener refuses reconnection.

## Execution and evidence

Run `gnu_executor_broker.py --help` for all required paths. The limits have the
same validated defaults and overrides as `NativeProcessLimits`. An official
environment can connect using the unchanged bridge and its explicit
`--socket NATIVE_SOCKET --peer-uid UID` arguments. Configuring or selecting that
environment is separate work and is not performed by this module.

`test_gnu_executor_broker.py` checks supervisor admission, ambient-environment
independence, accurate metadata, private path requirements and constructor-failure
lease release. Its eight admission tests do not execute a GNU workload.

`verify_gnu_executor_transport.py` uses actual native programs in one fresh
private workspace. Required runtime paths are explicit; `--parent` selects its
private evidence parent and `--evidence` its report path. The C bridge is executed
directly and therefore must match the diagnostic interpreter's native ABI.
`--android-home` supports the existing Bionic Python launcher; a GNU bridge hosted
under an outer PRoot needs a separately verified launch recipe.

The Linux nonroot diagnostic passed with GNU runner
`/var/tmp/foldgpt-gnu-managed-AObUdJhX/runner` and the previously built transport
helpers. Frozen source/evidence bundle:
`downloads/native-executor/foldgpt-gnu-transport-664aknj5/`. Both `/workspace` and
`/root/projets/essai é` actual mounts passed the same complete diagnostic. It records
actual Bash/Python execution, file-RPC-to-process and process-to-stream round
trips, the declared parent environment, protected file denial, denied `/tmp`
writes without a grant, successful `/tmp` mutations with an explicit grant,
file operations waiting on a live process while control remains responsive,
EOF reaping a live GNU process, released workspace and temporary leases, and
unusable old handles/process IDs after reconnect. Source hashes were stable
throughout the run. Nine existing native composite transport regressions also
passed, including quarantine and crash-marker retention; evidence is
`/var/tmp/foldgpt-gnu-broker-regression-iclvhy0l/composite.json`.

## Admission boundaries

The current GNU engine admits full policies only when they allow logical root
read and contain no DENY entries. It never drops or replaces an unsupported
policy. Actual runtime read grants remain narrower than logical root read.
Write and namespace operations retain per-operation policy decisions. Merely
advertising `/tmp` does not grant write permission there. File RPCs remain
limited to the pinned workspace even though GNU programs read runtime files.

TTY, custom argv0, shell snapshots, managed networking, arbitrary filesystem
mounts and application-driven multi-workspace/cwd routing are not established by
this diagnostic. The configurable single-workspace mount still requires Android
validation with the application's real project directories. This host result is
not Android acceptance, an ordinary model/UI command test, or a resolution of
the current production `bwrap` error.
