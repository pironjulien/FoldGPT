# Internal bootstrap read authority

`create_bootstrap_read_authority(native_executor, session_id=actual_session)`
issues an in-process `BootstrapReadAuthority` to trusted bootstrap/configuration
code. The constructor takes no paths, extra roots, model options or sandbox
context. Its root is the existing `NativeExecutorBackend.files` mount, backed
by the already open private workspace FD and kernel flock. The authority pins
that FD's device/inode and is bound to the existing executor session. It is
immutable and explicitly refuses serialization. It is not registered with
ExecServer and has no `handle` method.

Four operations are available:

| Internal operation | Result | Actual native route |
| --- | --- | --- |
| `read_file(canonical_uri)` | Exact bounded bytes | Existing `native-files` read and pinned ordinary-file FD |
| `get_metadata(canonical_uri, follow_symlinks=bool)` | Existing strict metadata dictionary | Existing `statx` metadata helper |
| `canonicalize(canonical_uri)` | Canonical file URI after successful lookup | Existing `openat2` descriptor resolver |
| `read_directory(canonical_uri)` | Actual direct children | Existing native tree helper validates the complete descriptor snapshot before returning entries |

The same structural admission checks owners, private root, ordinary files and
directories, link counts, aliases and tree bounds. Symlinks, hard links, special
files and `.git` indirection files remain actual explicit refusals. This work
adds no worktree resolver and no second root. No successful lexical-only path
guess is returned, and a missing in-root file is mapped from actual native
`ENOENT`. An out-of-root path is always denied, including a nonexistent one.

The authority uses the same asyncio lock as process lifetime ownership and the
same composite quarantine/cancellation gate. A read waits while the process
lease is held; quarantine refuses it while retaining that lease. Close and
foreign sessions revoke access. Shared helper invocation owns the real child
through spawn, I/O and reaping, including repeated cancellation. The authority
does not open an alternative workspace backend or acquire a competing flock.

Managed model RPCs still require their complete supplied managed context.
`sandbox: null`, omitted sandbox and forged authority fields never select this
API. The authority builds no managed policy and calls no model policy parser.
The structural inspector's optional argument is retained for existing callers;
it has no authorization meaning and was already unused by the inspector.

## Contract with project configuration discovery

`discovery_root_uri` is the inclusive discovery ceiling. Rust project/Git
discovery must receive this bootstrap-owned root explicitly and stop after
examining it. It must propagate a refusal outside that boundary rather than
turning it into `NotFound` or silently probing `/`. User/home/managed controller
configuration remains on the controller's own filesystem. A linked worktree
whose common directory lies elsewhere requires a separately designed explicit
authority; this API does not infer or grant it from file contents.

The current config/read and role discovery phases use these four methods.
Walk and mutations are not granted by this read authority. The separate private
[bootstrap channel](native-bootstrap-channel.md) carries these reads to Rust;
the model ExecServer interface and its mandatory policy remain unchanged.

## PC evidence

`native-bootstrap-files-test.sh ACTUAL_HOST_BIONIC_SUPERVISOR` snapshots Python
sources into a fresh `/var/tmp` directory, compiles the actual file helpers,
and runs all tests as nonroot. It also builds a deliberately paused native
helper fixture for cancellation, which emits no file result or success data.

The suite covers exact config/binary reads, native metadata, real in-root
NotFound, out-of-root denial, preserved managed restrictions, forged authority
rejection, alias/owner/permission checks, real flock and shared-lock ownership,
injected quarantine state, actual child reaping and session closure. Existing
file-RPC, native streaming and ExecServer tests run alongside it. The actual
nonroot run `foldgpt-bootstrap-files-F2hzb4gY` passed all 90 tests; its source
and binary inventories were preserved and rechecked under
`downloads/bootstrap-files/foldgpt-bootstrap-files-F2hzb4gY`. These PC checks are not an
Android execution or model-driven configuration integration claim.

The subsequent channel/listing increment passes 108 actual nonroot tests in
`foldgpt-bootstrap-files-ybowoamr`, including all previous regressions, real
directory absence/alias/kind checks, credential/FD rejection, and helper
reaping after EOF or an illegal overlapping request. The suite includes 11
inherited authority cases in its channel fixture; 108 is the total execution
count, not 108 newly added tests.
