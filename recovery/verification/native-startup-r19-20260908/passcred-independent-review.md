# Independent review: inherited credentialed native sockets

Read-only review by runas_launch. No device access or Rust production edits.

## Observed cause

The actual engine interposer log controller-errno-fbd61e0d reports setsockopt
EACCES. The separate ordinary application probe controller-link-81296450 reads
SO_PASSCRED=1 on both received seqpacket channels, records setsockopt(same1)
EACCES (13), and then reads SO_PASSCRED=1 again. Their AF_UNIX/SOCK_SEQPACKET
and peer PID/UID/GID are observed; F_SETFL and FIONBIO succeed on all channels.
This identifies a redundant configuration failure. It does not establish that
all later ordinary application initialization steps have passed.

## Callers and ownership

- BootstrapFileSystem::connect calls CredentialedSocket::new for config reads.
- HostFileSystem::connect v1 and HostConnectionV2::connect use ::host, which
  verifies SO_PEERCRED, domain/type and unnamed/abstract connected addresses
  before delegating to ::new.
- NativeRuntimeChannels::acquire independently verifies each transferred FD's
  exact owner/type and anonymous addresses before these adapters receive it.
- NativeRuntimeAcquisition.run creates both seqpacket pairs and enables
  SO_PASSCRED on both ends before passing client ends through SCM_RIGHTS.
- AcquisitionSocket::connect owns its newly created rendezvous socket. Its
  setsockopt is necessary and should remain; it is not this inherited-FD case.

## Required delta invariants

Use the existing sized getsockopt helper. Exactly1 requires no write; exactly0
may use the existing setsockopt1 initialization and must verify the resulting1.
An option read/write failure must propagate, and unrecognized state must fail.
No retry may turn disabled credentials into a successful socket. This preserves
support for ordinary local callers/tests whose fresh pair starts disabled.

All packet validation must stay intact: exactly one SCM_CREDENTIALS record
matching expected PID/UID/GID; reject unknown ancillary records; close every
unexpected SCM_RIGHTS FD; reject truncated payload/control and empty packets.
SO_PEERCRED admission, descriptor ownership, nonblocking/CLOEXEC flags and
AsyncFd registration must also remain unchanged.

Tests should exercise both initially enabled and disabled real socketpairs,
including a child where setsockopt is actually denied: already-enabled succeeds
and authenticates packets, disabled fails. Existing wrong peer, transferred
rights, truncated data, stream type and inherited sender identity tests provide
separate regression coverage. A local Linux syscall-denial test does not claim
to reproduce Android's complete security context.

## Final source review

PASS for the reviewed candidate. Compared with recovery/engine/engine.patch,
bootstrap_files_socket.rs changes only the SO_PASSCRED initialization block.
The complete send/receive/ancillary/descriptor cleanup implementation and host
peer/address checks are byte-identical after newline normalization. Both
runtime_acquisition_socket.rs and runtime_acquisition.rs are unchanged.

The two new Rust tests use actual socketpairs and actual credentials. One
confirms disabled credentials become enabled. The other creates a disposable
thread, enables credentials before applying a real seccomp filter denying
setsockopt, proves that syscall returns EACCES, then exercises both ::new and
::host with bidirectional authenticated messages; a disabled endpoint remains
rejected with real EACCES. No TSYNC flag is used, and only the disposable thread
sets no_new_privs/filter. Test design is appropriate for this regression without
claiming to emulate Android. All preexisting credentialed socket tests were compared with the recovery
patch and are exactly preserved, including wrong-peer, ancillary-FD, truncation
and sender-identity coverage.

I found no concrete weakening or additional caller requiring this change.
Linux compilation/tests have not been run by this reviewer; arm_engine owns
that validation. Source hashes and exact comparison are recorded alongside this
note in passcred-source-independent-check.json.
