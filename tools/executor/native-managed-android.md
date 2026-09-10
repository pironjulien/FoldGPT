# Native managed acquisition on Android

On 6 September 2026 the fixed native acquisition suite passed **17 tests and
46 actual process observations** on the Fold with the graphical client running.
The [native contract](native-managed-contract.md) describes its mechanisms and
bounded scope. This is not a normal model task or the official process RPC
lifecycle. No production Desktop route was changed by this fixture.

## Actual failure and correction

The earlier Android suite passed 11 of 12 tests. Its real fork test returned
`EAGAIN`: the inherited test profile applied `RLIMIT_NPROC=128`, but that limit
counts all threads of the real app UID, including the graphical client. A
contemporaneous shell observation found 251 same-UID tasks. Stopping the GUI
would have hidden that cause.

The corrected runner measures the visible same-UID tasks and sets the child
limit to the minimum of that snapshot plus the explicit additional task budget,
the inherited soft ceiling and the inherited hard ceiling. In the passing run,
all 46 startup events record `396 + 128 = 524`, below the inherited `38443`
ceilings. The fixture independently reads the child's actual limit. Shell
observations immediately before/after the suite found 379/393 tasks; these are
separate samples, not simultaneous equality checks. This is a non-atomic UID
snapshot and does not reserve capacity or implement a per-descendant quota.

## Evidence identities

| Artifact | SHA-256 |
| --- | --- |
| Tested APK | `7429c1e02ce9d5ac77f5c331a7c41cfd6014234c1a737da3b753eb77cb2575a0` |
| Installed stripped runner | `cc2f28de9072a6022f0925eb97146017e6ec3d3b69d938d0c43ed3b09cf88d95` |
| Installed stripped fixture | `c7ce9c8d10e7ec13695f8eecdd6866d6f35062232be374edfddbcb72d97dda4f` |
| Executed suite | `ce73e0d2b60aa6b40533932eb410cc256bccb506c39547e3139366b10b1f04b7` |
| Independent report | `812e99106f67d3c0e60a89ddbb3bdbaaba451e96b0f59f1d037482cbe1ed6dee` |
| Frozen collector | `fbee4aeef4e0454761e42b97beccc4dae71711027f3fdc6c2c8985d1755d37aa` |

Private evidence is retained under
`downloads/native-managed/android-7429c1e0/collected-pass-20260906` for fixture
`cache/mg-2002948493396965784`. The exact tested APK is retained alongside it.
`collector-source.py` preserves the executed collector bytes independently of
later checkout edits. The original failure remains under
`downloads/native-managed/android-c129b8a5/collected-failure-20260906` as
`OBSERVED_FAILURE`; it was not rewritten into a success.

The independent collector checks the APK before and after collection, all 30
installed native libraries, eight exact APK-owned executed sources, full case
coverage, native events and wrapper completion. Ten corruptions of the actual
passing Android result were rejected. Final case directories are empty; the
suite checked actual child/descendant reaping at execution time. Collection
cannot reconstruct already removed case bytes or historical process liveness.

The wrapper ran official Android/Bionic CPython under app UID 10412, tracer 0,
inherited seccomp mode 2, zero capabilities and the untrusted-app SELinux
context. No PRoot or compatibility shim was mapped into that supervisor.
The UID is a test-device observation, not a production configuration value.
The tested worker used real Landlock and seccomp notification with FD injection.

The debug and unsigned release-check APKs passed content separation with 30
and seven native libraries respectively. The release-check APK was not installed
or released. Its hash is
`61be18ab5138bc921a4ef7e82bd9bb37cf40dfa1233f612ced63cf1f96beeaa3`.

## Remaining integration

The passing cases cover actual exec, allowed reads/writes/creation, nested
denials and exceptions, protected metadata, stale identities, malformed broker
responses, exact FD flags, copied pathname/open_how mutation, timeout,
cancellation and forked descendant cleanup. They use a fixed static executable,
one private ordinary workspace and no command stdin or TTY.

The next increment must connect real start/read/write/signal/terminate behavior
to the official execution-server protocol, then admit the required runtime and
shell operations with their complete policy. A general process backend,
networking, normal model work and full Desktop routing remain unfinished. The
existing development GUI compatibility shim is not production isolation.
