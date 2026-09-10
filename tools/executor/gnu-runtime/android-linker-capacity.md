# Android native linker descriptor capacity

## Observed cause

The installed Fold reports Android 17, SDK 37 and One UI `90000`. The separate
read-only native diagnostic reproduced `libpdfium.so not found` from
`libandroid_runtime.so` when launching the installed strict PRoot with only
`--version` and `RLIMIT_NOFILE=128`. The referenced system file exists.

The native dependency chain includes the APK `libandroid-shmem.so`, the system
`libandroid.so` and the Android framework libraries. The actual ELF traversal
resolved **294** distinct native files with no unresolved DT_NEEDED name.

The retained diagnostic results are under
`downloads/gnu-runtime/managed-android-9df27472898d4d0fa1acc0f6dfb28b6d/`:

| Descriptor ceiling | Real installed PRoot `--version` |
| --- | --- |
| 128 | Failed with `libpdfium.so not found` |
| 294 | Failed later with `libcodec2_hidl_client@1.1.so not found` |
| 300 | Exit 0, version text, empty stderr |
| 305 | Exit 0, version text, empty stderr |
| 310 | Exit 0, version text, empty stderr |
| 422 | Exit 0, version text, empty stderr |

These are native loader diagnostics outside the executor confinement; they do
not claim that a GNU managed process or normal phone command passed.

## Primary implementation evidence

The inspected AOSP Bionic `linker.cpp` blob is
`4cf93b9badb616b892a2b063234abd72fb7c71e8`, present in both inspected `main` and
`android16-release`. This documents the mechanism; the measurements above
establish its practical effect on this particular Android 17 build.

- [LoadTask owns and closes its library descriptor](https://github.com/aosp-mirror/platform_bionic/blob/android16-release/linker/linker.cpp#L573)
  (`set_fd`, lines 573–581; destructor, lines 662–665).
- [A failed library open becomes the generic not-found diagnostic](https://github.com/aosp-mirror/platform_bionic/blob/android16-release/linker/linker.cpp#L1347)
  (lines 1347–1368). The displayed text alone does not establish absent bytes.
- [find_libraries expands the complete DT_NEEDED list before loading](https://github.com/aosp-mirror/platform_bionic/blob/android16-release/linker/linker.cpp#L1545)
  (scope cleanup, lines 1581–1585; dependency expansion, lines 1590–1646;
  loading begins at line 1648). The per-library descriptors coexist during this
  traversal and close when the task scope ends.

## Derived bounded capacity

`gnu_runtime_capacity.py` reads the actual installed APK/system ELF dependency
closure at trusted backend initialization. It validates file-backed ELF tables,
the exact talloc preload SONAME, canonical native paths and file identity while
reading. Unknown dependency locations or an insufficient inherited FD ceiling
fail admission before creating a process.

The GNU descriptor capacity is the existing **128 process descriptors plus the
observed native dependency count**. It is therefore 422 on the measured Fold,
but neither 294 nor 422 is embedded in the implementation. A changed native
runtime or One UI image gets a new traversal. This is a conservative runtime
capacity, not a claim about the exact minimum descriptor peak.

The trusted constructor passes the derived capacity to the separate GNU native
runner. The native side validates it against the inherited soft and hard
ceilings, then applies that actual RLIMIT_NOFILE. Guests cannot set this input.
The static managed runner remains at its original capacity. Filesystem/network
permissions and per-operation policy decisions are unchanged.

`loader-fd-admission.json` records a real execution of the new parser under the
app UID: 128 base, 294 native dependencies, capacity 422, inherited soft 32768 and
hard 524288. `inspect-fd-capacity.py` records the executed diagnostic source.

## Login shell verification

The GNU profile admits the actual runtime `/etc` configuration directory for
reading, including `/etc/profile`, `/etc/bash.bashrc` and `profile.d` scripts,
under its existing root-read/no-DENY admission. The project integration case now
starts a real `/bin/bash -lc`, reads a real workspace `.bash_profile`, verifies
HOME/cwd and the inherited descriptor limit, performs an actual `/dev/null`
redirection, then edits/tests/builds/runs the Python project. No startup script
is disabled. Normal null redirection flags (`O_CREAT|O_TRUNC`) are handled
against the actual verified character device, never an ordinary file.
