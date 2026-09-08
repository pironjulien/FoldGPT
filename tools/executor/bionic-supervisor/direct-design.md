# Ordinary-UID direct runner prototype

This new profile implements the upstream absence of an outer process sandbox.
It does not change the qualified managed or human runners, grant root, alter
Android policy or replace the official application. It is not packaged yet.

## Ownership invariant

One standalone, single-threaded native owner sets `PR_SET_CHILD_SUBREAPER` before
forking its sole initial command. Its SIGCHLD disposition is `SIG_DFL`, with no
`SA_NOCLDWAIT`, and only the owner waits for its children. No process-group-only
cleanup premise is used. It installs no new filesystem or syscall sandbox.

On completion, cancellation, timeout, command EOF or output/control failure it
repeatedly discovers possible direct children from `/proc`, opens their pidfds,
and verifies each is *currently its waitable child* using
`waitid(P_PIDFD, ..., WEXITED|WNOHANG|WNOWAIT|__WALL)` before signaling via that
pidfd. A stale numeric PID alone never authorizes a signal. Killing a parent
reparents its surviving descendants to the nearest living subreaper, eventually
this owner. Nested subreapers, setsid, setpgid and double-fork do not change the
ancestry invariant. Non-SIGCHLD clone children are covered by `__WALL`.

The discovery scan is deliberately **not** the completion witness. Only a real
`waitid(P_ALL, 0, ..., WEXITED|WNOHANG|__WALL)` yielding `ECHILD`, after all observed
exit statuses have been reaped, proves this owner has no remaining child.
With no remaining direct child, no live descendant can subsequently fork or
be reparented into this tree. The owner additionally requires EOF of the actual
child output/setup pipes. Unknown state never produces `cleanupComplete:true`.

The Fold's captured kernel configuration has `CONFIG_PROC_CHILDREN=n`, so this
implementation does not depend on `/proc/PID/task/TID/children`. Kernel source
also documents that that interface may miss concurrent exits. Discovery uses
ordinary `/proc/PID/stat` and the kernel wait relationship, not PPID text alone.

## Honest limits

- Discovery can miss racing tasks. It is retried; an incomplete scan cannot
  cause a successful cleanup result because the separate wait witness remains.
- No finite cleanup deadline is promised for uninterruptible kernel tasks,
  indefinitely spawning descendants, denied proc/pidfd access or broken kernel
  behavior. After the declared grace interval, report retained ownership and
  keep the actual owner alive. The calling backend must retain/quarantine its
  workspace lease if no successful result and real owner wait are available.
- Full ordinary-UID access is not an adversarial isolation boundary from other
  processes sharing that UID. Such a process may send SIGKILL to its owner; a
  machine shutdown can also kill it. Setting owner dumpability to zero prevents
  ordinary ptrace/proc-memory access but cannot prevent same-UID SIGKILL. There
  is then no cleanup certificate; the backend must not manufacture one.
- A separate existing service asked by the command to create work is not a
  descendant of this owner. Neither subreaping nor an unprivileged direct
  executor establishes ownership of that service. No broader guarantee is made.
- Android must permit the required owner operations. Host success and NDK
  compilation are not Android qualification. No namespaces/cgroups/ptrace attach
  are created. Resource limits, when supplied, are actual per-process/UID limits,
  not aggregate workspace reservations.

## Source basis

Reviewed via GitHub source connector after the integrated browser returned
`Browser is not available: iab`:

- Linux v6.12.58 `kernel/exit.c`, blob
  `d465b36bcc869689bdb79f0bc61ff83c47964161`: `find_new_reaper` uses the nearest
  living ancestor subreaper; `wait_consider_task` preserves child presence for
  live children; `__do_wait` scans children under tasklist_lock; waitid accepts
  P_PIDFD and `__WALL`.
- Linux v6.12.58 `fs/proc/array.c`, blob
  `5e4f7b411fbdb9d2d8153db76340be532334fbd7`: PROC_CHILDREN optional, and its source
  explicitly disclaims an accurate concurrently changing children list.
- Captured Fold configuration:
  `downloads/runtime/capabilities-20260907-v2/kernel.config`, SHA256
  `e9f2c634a6e96299d1ab452e30950a2170ed83ebec3ae94051f1d3058fe8b41d`:
  USER_NS=n, PID_NS=n, PROC_FS=y, PROC_CHILDREN=n. These are prior device evidence,
  not a fresh device check in this task.

## Native interface

`direct-runner CONFIG_FD INPUT_FD CONTROL_FD COMMAND_FD`

CONFIG is a sealed memfd encoded by `direct_wire.py`. INPUT is the real child
stdin. CONTROL and COMMAND are private SEQPACKET endpoints. CONTROL receives a
`ready` message, then must send the single-byte `P` acknowledgement. COMMAND
accepts `T` (terminate), `I` (interrupt the current initial process by pidfd);
EOF cancels. Owner stdout/stderr carry the actual forwarded child bytes.

The owner emits started only after an actual exec-success pipe EOF. Exit events
contain the actual initial process wait result. Result success additionally
requires the independent ECHILD witness, real pipe EOF and no remaining owner
child. Outer code must await the native owner itself before releasing authority.

The startup acknowledgement follows the conventional close-on-exec error-pipe
contract: explicit setup/exec failures write their stage and errno; a clean
close after the owner gate permits the started event. Cancellation before this
acknowledgement and an observed signal death do not produce a successful start.
It is not a proof against a same-UID adversary killing the child precisely at
the exec boundary; no instruction-level tracing is performed. The final actual
wait status remains authoritative about exit and cleanup.

This prototype is non-PTY. A request must not silently turn a requested PTY into
pipes. Direct-mode kernel filesystem/network behavior is ordinary UID behavior;
the test suite exercises real operations that the managed profile denies.
