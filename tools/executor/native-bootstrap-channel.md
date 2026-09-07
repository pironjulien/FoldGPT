# Private bootstrap file channel

`BootstrapReadChannel` carries four read operations from an existing native
workspace authority to the separate Rust `BootstrapFileSystem`. The trusted
owner transfers an anonymous connected AF_UNIX/SOCK_SEQPACKET socketpair and
the actual peer PID/UID/GID. There is no listening address, model RPC selector,
request-supplied root, session, policy or serialized authority.

Every message is checked against kernel SCM_CREDENTIALS. Unexpected ancillary
data is refused; any received SCM_RIGHTS descriptors are closed. Both endpoints
are nonblocking and close-on-exec. The owner must enable SO_PASSCRED before
handoff. The Python peer also supplies its actual credentials when sending.

The ready message fixes schema `foldgpt.bootstrap-files.v1`, existing session,
discovery root, four operations and exact limits. Requests have a monotonically
increasing integer ID starting at 1, operation and canonical file URI; metadata
also requires `followSymlinks`. Unknown fields and overlapping requests close
the channel. Read/list results use base64 chunks of at most 32 KiB, followed by
exact byte/chunk counters. Total data is bounded at 16 MiB and packets at 64 KiB.
Metadata/canonicalization have typed terminal results. Native absence remains
NotFound; access refusal cannot become absence. The native authority rejects
links under either follow setting.

The Rust request permit remains held through semantic validation, including
directory JSON and names. Cancellation after admission closes the channel;
cancelling a waiter does not cancel another caller's active operation. Python
waits for the real helper to be reaped before releasing its channel. Global
native cleanup remains owned by the existing backend, not by this transport.

## Verified scope

- 17 Rust socket/protocol cases pass, including a real sender with a different
  PID, descriptor rejection, exact limits, errors, cancellation and two reproduced
  pre-correction directory-admission races.
- 108 Python/native regression executions pass as nonroot, including seven new
  channel cases, inherited authority cases and the existing file/stream/RPC suite.
- `qualify_bootstrap_isolation.py` launched the actual Rust client as UID1000
  and actual Python/native backend as UID65534. Direct controller file access
  returned PermissionDenied, while the channel read 70,000 exact binary bytes,
  metadata, directory entries and canonical paths. The real bounded configuration
  loader read the trusted native project layer with correct model provenance.
  Real missing/outside refusals preserved subsequent valid reads. Both processes
  exited with zero; helper gone, files closed, no quarantine. Evidence:
  `/var/tmp/foldgpt-bootstrap-isolation-otdri1q3/report.json`.

This is PC bootstrap/configuration integration. It does not yet prove a complete
app-server task, model execution from the UI, Android channel deployment or the
remaining configuration/instruction/host-tool routes. `ExecutorOnly` stays closed.
