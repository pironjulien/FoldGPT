# Native controller startup EACCES: measured cause

8 September 2026. Scope: r18/versionCode8, GNU engine R4, real FoldActivity
launch on R3GL808JN4A. The ordinary conversation remains unqualified.

## Evidence

- `controller-link-e74e6cf4` passed the full six human operations and four
  native model Python commands from the actual ordinary Android application
  process. It did not invoke a model conversation or the editor.
- Independent read-only snapshot `after-controller-full-device` confirms boot
  `348d453e-f4e5-40e0-8ef0-030f4d5e38af`; the previous owner PID10602 is absent.
- `controller-link-eb183f00` repeats that full qualification after the same
  process prctl/core-limit/environment calls. PR_GET_DUMPABLE remains1 under
  the existing PRoot compatibility behavior; it is not evidence that process
  dump prevention was established. Canonical Python paths and epoll creation
  also pass. No installed hardening or phone setting was changed.
- `controller-errno-fbd61e0d` launches the actual unchanged R4 engine with a
  temporary GNU libc pass-through diagnostic library. It records only syscall
  function names and EACCES, never payload/environment/file contents. The
  first engine process16565 reaches `setsockopt` and receives EACCES. The log
  retains the actual startup error. Both attempts also see a nonfatal statx
  EACCES, which does not explain the later startup refusal.
- `controller-link-81296450` reproduces the relevant call directly in the
  ordinary application process on BOTH transferred config and host channels:
  `getsockopt(SOL_SOCKET, SO_PASSCRED)` returns1; a repeated
  `setsockopt(SOL_SOCKET, SO_PASSCRED, 1)` fails with errno13; readback remains1.
  Peer identity and descriptor checks still pass. The native owner already
  enables this option on both endpoints before transferring descriptors.

## Cause and intended correction

`CredentialedSocket::new` in exec-server/src/bootstrap_files_socket.rs
unconditionally reconfigures SO_PASSCRED. The Python production qualifier
uses the already configured channels. Android permits using and inspecting
the transferred endpoints, but refuses this redundant configuration call.

Read and preserve the already enabled socket option; retain credential and
peer validation. Any required initialization on an unconfigured local socket
must still succeed and be verified. Never translate an actual failed request
into success, nor remove SCM_CREDENTIALS checks. Implementation and real Rust
and Fold validations are still pending at the time of this note.

## Diagnostic lifecycle

Each driver checks the previous native owner's complete reaping and absence,
verifies the production wrapper hash, and restores the exact original wrapper
in a finally block with a SHA256 readback. Its LF-normalized SHA remains
`c23406a7e597d7b2d4190333c972f8b4c2727949d8effe6f1fb45d094917bc95`.
No official client file or installed engine was replaced by the diagnostics.
The temporary diagnostic scripts and library are project-owned evidence and
are not part of the production package.

The first two interposer attempts did not collect usable libc diagnostics:
the client consumes stderr, and an initial polling implementation could read
the previous runtime log. They remain recorded as inconclusive. The decisive
attempt requires a newly created private per-PID trace file as well as the
actual startup error.
