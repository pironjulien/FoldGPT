# Native GNU managed process adapter

`GnuProcessesBackend` is an opt-in process backend over the existing native
supervisor, complete parsed policy and private lifecycle transport. Its runtime
inputs are supplied by the trusted supervisor. Commands cannot replace them.
No normal environment is selected by this module.

The GNU native descriptor capacity includes the measured immutable Android
dependency closure in addition to the existing process budget; see
`android-linker-capacity.md`. This addresses the real Bionic loader failure
without changing the static runner or filesystem/network policy.

## Admission and authority

The current profile requires logical root read access and no DENY entry. It
admits one private ordinary workspace mapped to `/workspace` and a distinct
private ordinary temporary root mapped to `/tmp`. The full original policy and
environment reach the existing process policy owner without replacement or
an extra grant. Declaring a temporary directory never grants write access.

Workspace and temporary writes use the same `NativeProcessPolicy.decide`
implementation. The latter only projects a relative native path against the
`/tmp` mount. mkdir, unlink, rmdir and rename also consult the original policy,
including protected `.git`/`.agents` metadata and read-only subtree entries.
Each write acquisition verifies the policy's observed parent/target inode and
injects the actual opened descriptor using `SECCOMP_ADDFD_FLAG_SEND`. Namespace
mutations execute through pinned native parents. No seccomp notification is
continued against mutable guest pointers.

The namespace contract requires exclusive ownership and ordinary files:
symlinks, hardlinks, external concurrent native writers, cross-root renames and
directory descriptors for writable opens are outside this first profile. TTY,
custom argv0, managed networking, shell snapshots and DENY policies are rejected
explicitly. A single session owns the adapter; an unknown cleanup retains both
workspace and temporary leases and refuses another session or repeated close.

## Runtime scratch and tracing

PRoot's own scratch is separate from the guest `/tmp`. Its Landlock grant has
read/execute rights only. Only notifications from the owned, unreaped,
single-threaded PRoot leader receive internal scratch open/mutation/mode
authority. Guest processes cannot use that authority. The GNU seccomp filter
embeds the leader PID before exec and denies ptrace and process_vm access to
that PID. It also permits the monotonic Landlock create/restrict syscalls needed
by the strengthened strict PRoot child domain; integration must use the reviewed
strict candidate and retain its independent tracing tests.

PRoot's actual cross-process F2FS case-sensitivity probe executes during trusted
native bootstrap, after supervisor identity acknowledgement and before ptrace
startup/confinement. It uses only a freshly created directory in the pinned
runtime scratch. Its child belongs to the already owned process group. The
measured result sets `PROOT_F2FS_WORKAROUND`; an inconclusive result fails setup.
This avoids granting a runtime child general scratch authority or disabling the
probe. Cancellation and the wall deadline remain owned by the supervisor.

Android loads the immutable APK `libtalloc.so` through a supervisor-owned
`LD_PRELOAD` path so its SONAME can satisfy `libtalloc.so.2`, without accepting
a symlink in a writable tree. This Android-specific loader behavior requires
device validation. Guest environment variables are supplied literally through
`/usr/bin/env -i --`; they cannot change the native PRoot environment.

## Reproduction and evidence

Run `run-managed-linux-tests.sh /absolute/path/to/strict-proot` as an ordinary
Linux UID. It copies all required source inputs into a fresh `/var/tmp`
directory, regenerates and builds the separate GNU derivative with warnings as
errors, runs the integration suite and records source/output hashes.

The eight cases cover a real Bash login shell/profile and Python project (edit, three tests, bytecode,
zipapp, execution), workspace denials, absent temporary write grants, explicitly
granted temporary writes with metadata/subtree denials, binary stdin and exact
environment/exit status, pre-spawn policy rejection, cancellation after both
parent and child report readiness, and a real wall timeout with complete cleanup.
Seven cases launch processes; the rejected policy does not create one.

`test_gnu_process_adapter.py` also accepts `--rootfs`, `--loader`, `--loader32`,
`--address-space-bytes`, `--wall-ms` and `--timeout-wall-ms` for the native Android
diagnostic. Host success alone does not validate Android loader behavior or
normal phone routing. `GNU_DIAGNOSTIC` builds add private raw syscall and PRoot
logs; release builds do not contain that logging.
