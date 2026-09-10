# Native human PTY: separate candidate

The model runner and frozen host-v2 production package remain unchanged. This
candidate adds a real private Linux PTY, not a pipe advertised as a terminal.
Reviewed inputs: the current supervisor, its syscall profile, NDK29 tty UAPI,
Codex utils/pty's actual process contract, and the existing Android constraints
research (`docs/research/android-native-constraints-2026-09-06.md`, TTY/FD/signal
sections). Linux and Fold execution are separate qualification gates.

The native supervisor opens /dev/ptmx before confinement, obtains its own slave,
pins that slave as O_PATH and owns the master for the entire worker lifetime.
The child creates a fresh session, acquires the slave as controlling terminal,
then duplicates it to stdin/stdout/stderr. Existing identity, limits, Landlock,
pathname notification mediation and native reaping precede exec as before.

Only TCGETS/TCSETS/TCSETSW/TCSETSF, TIOCGWINSZ/TIOCSWINSZ, TIOCGPGRP/TIOCSPGRP,
TIOCGSID, FIONREAD/TIOCOUTQ and flow-control ioctls are admitted by the separate
PTY syscall header. Dangerous tty injection/global console/device operations
remain refused, including TIOCSTI, TIOCLINUX, TIOCCONS and TIOCSCTTY after startup.
The exact pinned slave receives the necessary Landlock device-ioctl right; no
global /dev grant is introduced. The only device acquisition is /dev/tty,
resolved to that held slave descriptor and returned through atomic ADDFD_SEND.
No pointer-bearing pathname request is continued against mutable caller memory.

Job control requires setpgid. It remains constrained by the kernel to the
already-created session; setsid stays denied after startup. Consequently cleanup
cannot rely on killing the initial group. The supervisor repeatedly opens pidfds
for its current direct children, verifies child ownership with waitid(P_PIDFD),
kills the pinned children, then reaps. Subreaper adoption brings all orphaned
descendants through the same operation. ECHILD and real terminal EOF are required
before the cleanup receipt; errors retain ownership. No stale numeric PID/group
is used to kill unrelated processes.

Rows and columns are explicit nonzero u16 values in a separate sealed envelope.
Resize travels over the owned control socket and returns an acknowledgment only
after native TIOCSWINSZ and readback succeed. Interrupt uses TIOCSIG on the owned
master to target the kernel's actual foreground process group. Termination
continues through owned descendant cleanup, independently of blocked streams.

The terminal's single ordered output stream is reported as stdout; stderr from
the child is merged by the real PTY. The master's EIO after slave closure is
terminal EOF, not fabricated success. Pipe EOF on the frontend input transport
only closes further input: PTYs have no independent half-close. Applications
receive real VEOF through terminal input bytes according to their current line
discipline; raw mode is never silently rewritten to simulate pipe EOF.

Tests must cover isatty/session/foreground identity, initial dimensions and
actual resize/SIGWINCH, raw binary input/output, canonical input and VEOF,
interactive Bash foreground job control, dangerous-ioctl/outside-W refusal,
and cleanup of background children that changed their process group.
