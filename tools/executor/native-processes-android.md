# Native process lifecycle on Android

On 6 September 2026 the actual Android/Bionic backend passed 20 lifecycle tests
and 104 recorded backend/native observations. This is the static executable
profile documented in [native-process-lifecycle.md](native-process-lifecycle.md),
not a normal Desktop/model task or transport conformance result.

The first device run failed before native exec because official Android CPython
does not expose `os.memfd_create`. The corrected binding uses Bionic libc
`memfd_create` and `fcntl` directly through ctypes. Its ABI is checked against
the retained NDK r29 headers. The actual Android test reads sealed bytes, checks
close-on-exec, and verifies kernel EPERM for writing, shrinking, growing and
changing seals. It uses no ordinary temporary file as a memfd substitute.

Independent successful evidence is retained in
`downloads/native-process/android-1a54dd8c/collected-pass-reviewed-20260906-r2`.

| Evidence | SHA-256 |
| --- | --- |
| Tested debug APK | `1a54dd8cbfdeb329d575ab130b65dbef550fb65067c1a3912244b749c856db5b` |
| Installed native runner | `dd4e45270d0a017f9fadc0b07067c725a7d38767184818f210bd91fd06b9ba88` |
| Installed worker fixture | `0b7d1ed79120abe4f47d673714bc2d25162c43bc7e55f216cbe261c28d0d2ba2` |
| Android wrapper report | `2c1b4c9a1277be65df045c9e19fb1797a44804532b2fe09c0beb0d9e0b7b36d1` |
| Independent verification | `8efd66bf36732ed3eb1dc4984659166474a533bd5c920dfcc28a631352283798` |
| Executed collector | `7a5d0c97276181d78b3bed2e760172882b2fcdb1c06635376410060897ddebf3` |

The compiled snapshot is
`downloads/native-process/foldgpt-native-process-build-0so6WxCj`. APK packaging
strips symbols; installed hashes above therefore refer to actual packaged
programs rather than the unstripped cross-build outputs.

The collector rechecks nine executed Python sources against the APK, all 32
installed native libraries and the APK before/after collection. Actual process
contexts show app UID 10412, Bionic CPython, inherited seccomp, zero effective
capabilities and no PRoot/fake-userns mappings in the supervisor. The case
directory is empty and genuine report/completion artifacts are bound to the
test matrix. It validates 20 native closures, 91 unique notifications and
2130030 unique native output bytes, with two grants and 22 native refusals.
Denial counts do not identify denied paths or independently attribute a command
failure to sandbox enforcement.

The retained earlier failure is
`downloads/native-process/android-f3079b8e/collected-failure-20260906`:
19 tests, 18 errors and one pass, with the actual memfd error and no invented
completion report. Partial collection directories from collector revisions are
also retained. The final collector has been checked against real host and
Android transcripts and rejects nine mutations plus malformed/duplicate JSON.

Collection cannot reconstruct removed case bytes, historical process liveness,
timing or lock ownership. Those remain executed suite observations. Concurrent
fixture error IDs are checked only as valid envelopes because the fixture uses
its completion-time sequence; they do not prove transport request correlation.
The composed file/process executor, real stdio/Unix bridge, general shell,
dynamic programs, TTY, network and normal model routing require their own tests.

The debug and unsigned release-check APKs build, and their diagnostic separation
passes (32 and seven libraries respectively). The unsigned release-check APK was
not installed and is not a signed distribution artifact.
