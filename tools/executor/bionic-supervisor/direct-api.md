# Direct runner API for backend integration

Source is `direct-runner.c`; envelope is `direct_wire.envelope`, then
`direct_wire.seal(payload)`. Runner argv: `runner CONFIG_FD INPUT_FD CONTROL_FD
COMMAND_FD`. CONTROL/COMMAND are `AF_UNIX/SOCK_SEQPACKET`. Input is the child
stdin pipe. Owner stdout/stderr are real forwarded output; consume both.

`envelope(cwd, executable, argv, environment, wall_ms=None, data_bytes=None,
file_bytes=None, output_bytes=None, uid_tasks=None, cpu_seconds=None,
descriptors=None, cleanup_grace_ms=5000)` uses keyword-only arguments. Environment
is a list of complete `NAME=value` strings; no inheritance. Limits None remain
absent. No workspace/runtime grants or policy parameter exist in this profile.

`ready = {type:ready, profile:bionic-direct-v1}` -> parent sends byte `P` on
CONTROL. COMMAND byte `T` or EOF requests termination; byte `I` interrupts the
initial process through its still-owned pidfd. No group/PID-reuse signal fallback.

Other control JSON records:

- `started`: `type`, `profile`, `setupCompleted:true`, `sandboxType:none`.
- `exited`: `type`, `exitCode`, `signal` (Unix code=-1 when signaled).
- `ownership-retained`: `type`, `cleanupComplete:false`. The real native owner
  continues cleanup; this is not a final result and must not release the lease.
- `result`: exactly `type`, `profile`, `outcome`, `started`, `cleanupComplete`,
  `exitCode`, `signal`, `reaped`, `signalsSent`, `stdoutReadBytes`,
  `stderrReadBytes`, `stdoutBytes`, `stderrBytes`, `stage`, `errno`.

Outcome values currently: exited, cancelled, timeout, output_limit, output_error,
setup_error, broker_error, cleanup_error. ReadBytes counts bytes actually drained
from the child, Bytes counts bytes actually forwarded to the parent. During
abnormal cancellation undeliverable pending output is drained with both counts
reported; successful exited requires equality. No output is synthesized.

`cleanupComplete:true` requires a real all-child `waitid` ECHILD witness plus
actual output/setup EOF. Caller must ALSO await the actual owner returncode and
pipe EOF; a reported result alone does not release ownership. Owner returns 0
after a started command has completely cleaned up, including cancelled/timeout
outcomes; returns 70 when setup never completed. Missing final result, absent
owner wait or count mismatch is unknown cleanup and must retain/quarantine.

Startup schema is intentionally unchanged by identity telemetry. UID/GID/caps
are checked by native owner; tests read the actual child identity. No fake
identity fields are added. The compile/test helper outputs real evidence.

Known remaining qualification need: Linux host tests and Android device test
are not implied by Windows NDK compilation. See direct-design.md for the
ordinary-UID trust boundary and unbounded-kernel-cleanup limitations.
