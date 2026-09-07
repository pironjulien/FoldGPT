# Native process environment policy

`native_environment.py` resolves the complete executor `envPolicy` wire object
before the native backend creates a process record or launches its supervisor.
It does not select a Desktop environment or admit shells, TTY or networking.

The source boundary is official Codex `rust-v0.153.4`, commit
`042fb41b7c813ac7999105e886b2b7aa715b5081`, specifically:

- `exec-server/src/local_process.rs:706-738`: child environment creation, explicit
  RPC overrides and the final launch-context scrub.
- `protocol/src/shell_environment.rs:89-171`: Unix inheritance, filtering and
  override ordering; `:13-26` defines non-inheritable identity variables.
- `protocol/src/config_types.rs:207-269`: inheritance modes and policy defaults.
- `exec-server-protocol/src/protocol.rs:293-301`: all five `ExecEnvPolicy` fields
  are required; there are no wire defaults for missing fields.
- `config/src/shell_environment_policy.rs:133-161`: TOML defaults are resolved
  before serialization: `all`, `ignoreDefaultExcludes=true`, empty filters/set.

The order is inherited parent (`none`, Unix `core`, `all`), optional default
exclusions (`*KEY*`, `*SECRET*`, `*TOKEN*`), custom exclusions, policy `set`,
`includeOnly`, then explicit RPC `env` overrides. The five non-inheritable names
are always removed using ASCII case-insensitive comparison; the executor EOF
control variable is removed by its exact name, matching upstream. Ordinary Unix
names remain case-sensitive. Explicit overrides can restore ordinary variables
filtered earlier, as upstream specifies, but cannot restore identity context.

`NativeProcessesBackend(..., parent_environment=...)` takes a supervisor-owned
string mapping and freezes a copy. No ambient Python/Android environment is read.
The supplied snapshot must describe the intended executor environment, never a
caller-chosen Android process context. An omitted snapshot supports exact `env`
and `inherit=none`; requests for `core` or `all` fail until a snapshot is supplied.
An explicitly empty snapshot is distinct and can be inherited. Existing native
limits of 128 resulting variables and 65536 encoded bytes remain enforced after
policy resolution and before native launch.

Pattern behavior follows `wildmatch` 2.6.1: only `*` and `?` are wildcards, matching
whole names, with lowercase comparison of each Unicode character independently.
Brackets and backslashes are literals, so Python `fnmatch`, regular-expression
case flags, whole-string lowercasing and case folding would change behavior.
The downloaded crate matches the upstream Cargo.lock SHA-256
`29333c3ea1ba8b17211763463ff24ee84e41c78224c16b001cd907e663a38c68`.
The tag pins Rust 1.95.0, whose character lowercase data is Unicode 17.0.
`native_environment_unicode.py` retains its complete non-identity scalar mapping
as compact ranges and exceptions. Python 3.14 uses Unicode 16, which differs for
28 scalars; the matcher therefore uses the pinned mapping instead of host Python
lowercasing. The table was extracted from the actual pinned compiler, with its
oracle-map SHA-256 recorded in the module. Both environment modules must be
packaged wherever `native_processes.py` is installed.

Run portable tests with `python -B -m unittest tools.executor.test_native_environment -v`.
The separate `test_native_environment_live.py` takes `--runner`, `--fixture` and
optional `--evidence`, reuses the real static native `env` fixture and records
the existing official RPC/native lifecycle observations. It must run under a
nonroot UID. No model or Android execution is implied by host test results.

The recorded host run passes 12 portable cases under Windows Python 3.14 and
Linux Python, three dedicated real native cases (four actual child processes),
and the existing 23-case lifecycle suite as UID 65534. The updated incomplete
policy assertion in lifecycle test 11 also passes separately. Native inputs were
the existing `foldgpt-native-process-build-tyYOXDCt/linux/{runner,fixture,files-helper}`
artifacts; this change did not rebuild them or execute Android code.

`downloads/native-environment/` retains the actual Rust oracle source/binary,
the authenticated crate source, Unicode extraction/generator, differential
driver/report, and native JSON observations. The real Rust 1.95.0/wildmatch
comparison passes all 1,112,064 Unicode scalars and 38,932 wildcard/name pairs.
That verification caught the Python Unicode mismatch before delivery.
