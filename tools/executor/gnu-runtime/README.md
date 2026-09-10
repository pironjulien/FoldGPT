# Native GNU project increment

This fixed diagnostic runs real GNU Bash and Python on the Linux/Android kernel
through strict PRoot, behind a native Landlock and seccomp supervisor. It requires
an ordinary nonroot application identity; it creates no VM or namespaces and
changes no official client. It is an experimental integration increment, not the
production Desktop command route or a full managed-policy executor.

The embedded project creates and edits Python source, compiles actual bytecode,
runs three unit tests through Bash, builds a ZIP application, and executes that
package. It also verifies the real nonzero Bash exit code 23. The native parent
rereads the result from its physical scratch directory and verifies that outside
and protected files remain unchanged. `verify-host.py` separately rereads every
reported project artifact and hash without executing the report.

The launcher is a reviewed derivative of the existing native offline probe. Run
`python3 prepare-launcher.py` after changing `project.py` or its explicit source
transformation. The generator refuses an unreviewed base hash. The resulting C
file and embedded header are complete standalone compile inputs, including for
the NDK. `derivation.json` binds the base, resulting source and project hashes.

## Host command

```powershell
wsl -d Ubuntu-24.04 -u nobody --exec /bin/bash /mnt/c/Dev/FoldGPT/tools/executor/gnu-runtime/run-linux-tests.sh /var/tmp/foldgpt-proot-strict-Eu22Ab0a/patched/src/proot
```

The recipe compiles under UID 65534 and retains frozen sources, program hashes,
compiler/kernel identity, raw stdout/stderr, actual project bytes, exit status
and verification in a fresh `/var/tmp/foldgpt-gnu-project-*` directory. It uses the
previously reviewed strict PRoot artifact, without modifying it or the phone.

## Actual protection and bounds

Landlock handles all ABI 6 filesystem access rights and scopes signals and
abstract Unix socket names. Only explicit guest program/runtime trees (`usr`,
`lib`, `lib64`, `bin`), the native runtime programs, and private experiment paths
are granted read/execute access. Android additionally grants public native
loader/system program trees. There is **no grant to `/`, `/proc`, `/home`, `/data`
or the whole guest root**. `/dev/null` and `/dev/urandom` get explicit read grants.
`/dev/null` writes require the existing broker's actual device verification.

The existing native listener brokers copied absolute host paths for scratch
writes and permission changes; it never continues a syscall against mutable
tracee memory. Workspace writes retain the old probe's restricted broker policy.
The project itself occupies private scratch, where complete read/write access
is intentional. No secret file is placed within a broadly granted project tree.
This additive profile cannot express arbitrary confidential exclusions inside
one granted directory. Landlock also leaves path metadata (`stat`, `readlink`)
visible; this is not a claim of metadata confidentiality.

The native filter refuses unshare/mount/network interfaces. Legacy `clone`
accepts ordinary fork/thread flags only; namespaces, `CLONE_PARENT`,
`CLONE_PTRACE` and `CLONE_UNTRACED` are refused. `clone3` returns ENOSYS so libc can
use the inspectable legacy clone layout. This is an explicit syscall profile,
not a claim that clone3 is absent from the actual kernel. Unknown syscalls remain
visible in diagnostic output and are refused. `PROOT_NO_SECCOMP=1` chooses full
ptrace syscall-entry translation so USER_NOTIF sees translated paths; inherited
Android and launcher filters remain active. Strict PRoot reports unsupported
`PR_SET_DUMPABLE(0)` as EOPNOTSUPP and preserves actual namespace denials.

The GNU script requires actual denied reads of an outside file, its symlink
alias and `/proc/self/environ`, plus denied outside writes, outside chmod,
network socket creation and namespace unshare. It checks actual NNP/seccomp
queries. PRoot's inherited Landlock domain prevents memory access to the native
parent; a native pre-exec check verifies the denial and reports whether the
underlying OS already denied the baseline.

The supervisor retains the existing bounded deadline, child/subreaper ownership
and descendant cleanup. This diagnostic does not qualify hostile arbitrary
workloads, resource quotas, hostile concurrent scratch writers, same-UID
unconfined supervisors, interactive terminals, networking or cancellation while
a model task is active. No result here permits quietly removing those controls.

## Android handoff

Compile `gnu-project.c` with `gnu-project.generated.h` beside it, using NDK r29
for native AArch64. Invoke the resulting program as:

```
libfoldgpt-gnu-project.so APP_DATA_DIR APK_NATIVE_DIR
```

The fixed Android path expects `APP_DATA_DIR/files/debian` and these APK inputs:
`libfoldgpt-strict-proot.so`, `libproot-loader.so`, `libproot-loader32.so`,
`libtalloc.so`. The strict candidate is separate from the client's regular PRoot.
The program creates only a fresh `cache/foldgpt-gnu-project-*` evidence tree.
An independent debug service should own invocation and accept no arbitrary
command, policy or path extras. Host PASS is not Android acceptance. Android
requires the actual Bionic/ARM64/One UI run, recorded SELinux/seccomp identity,
artifact hashes, unchanged outside bytes and verified descendant cleanup.

The next production step still needs a supervisor-owned GNU runtime manifest,
the full file policy required by each official process request, robust process
RPC/cancellation/TTY handling, and supported Desktop selection/routing. Passing
this project establishes that native GNU execution and a default-deny file read
policy compose; it does not make the current `bwrap` UI error resolved.
