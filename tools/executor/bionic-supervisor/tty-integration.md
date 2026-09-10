# Model PTY composition

The optional installed deployment key is
`backendOptions.ordinaryUid.ptyProcessRunner`, selecting
`@nativeLibraryDir/libfoldgpt_direct_pty_supervisor.so` in production.
The installed bootstrap verifies that library through the existing native hash
inventory and resolves its path before constructing any model process owner.
The RPC cannot supply or replace this option.

The factory constructs `TtyProcesses` with the managed owner's actual pinned
filesystem, the same mutation lease and quarantine owner, the same ordinary-UID
limits, executable mapping and parent environment. The three process owners
and their registries must be distinct. Existing handles and quarantine/closing
state cannot be imported with a new PTY owner.

After complete outer-operation validation, an explicit process sandbox selects
the existing managed backend. An absent/null sandbox selects the existing pipe
backend for `tty=false` or the installed PTY backend for `tty=true`. Without an
installed PTY owner, the pipe backend preserves its existing unsupported-PTY
refusal. No refusal is retried in another profile.

Reads, writes, signals and termination find their owner from the stored
session/process handle across all three registries. Ambiguous ownership is
rejected. Duplicate IDs, pending starts and the existing 128-process capacity
cover all three registries together. Subsequent requests cannot reclassify an
existing handle through new sandbox or terminal fields.

Session close awaits managed, ordinary pipe and ordinary PTY owners alongside
any separate human terminal owners. File owners close only after all process
owners complete without ambiguity. A PTY cleanup failure propagates quarantine
to the composed managed owner and retains the shared workspace lease.

The human terminal API remains separate. Model capabilities do not acquire
`process/spawn` or `process/resizePty`; the candidate's resize operation remains
owner-only, since the pinned model protocol has no public resize method.

The promoted `tty-runner.c`, `tty_wire.py` and `tty_processes.py` are byte-for-byte
copies of the independently reviewed candidate under
`work/native-pty-20260908/candidate-dossier.json`. The Android ELF is unchanged;
this integration does not require recompiling it. Device execution of the
candidate and execution through the installed model interface are separate
qualification steps, owned by the production qualification flow.

`test_model_pty_profiles.py` distinguishes routing tests with registry doubles,
real nonroot Linux PTY/factory lifecycle tests, and bootstrap identity fixtures
that still verify actual immutable file bytes. The Linux evidence is
`work/native-pty-20260908/model-integration-host-v3/report.json` (16 passing cases).
Its temporary Linux filesystem was mounted only under the project to preserve
the production private-workspace admission that NTFS cannot provide; it was
dismounted after collecting the evidence. No Android execution is claimed by
these PC tests.
