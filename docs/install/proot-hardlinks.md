# Debian hardlinks on Android: explicit PRoot storage backend

The first Android extraction reached Debian's `usr/bin/perl5.40.1` hardlink and
failed with `EACCES`. The coordinating device check also failed to create a
hardlink between two ordinary app-owned writable files using `run-as`. Do not
interpret this as an archive error or copy the alias's bytes into another inode.

The runtime already starts PRoot with `--link2symlink`. That extension has a
real storage representation for shared contents and guest link operations on
filesystems which cannot create hardlinks. **Use a declared installation
backend for that representation**, with independent host and guest validation.
Do not convert every `link()` failure into apparent success. The native POSIX
backend and the PRoot storage backend must remain distinct manifest states.

The extractor now supports this explicitly declared backend. The original
archive and live runtime data remain unchanged. Host and actual Android
validation results are distinguished below.

## Audited source and observed layout

The inspected implementation is the existing pinned Termux PRoot checkout
`7266fb3e8516535682f5a9c8f3a7e70f6506eddb` with its current reviewed source.
`src/extension/link2symlink/link2symlink.c` SHA-256 is
`0e9f77337973b2e94184259edee5ac78fa9d42a13ba0eb4d0ec5dd1320f18f6c`.
That exact file matches the previously built host test binary's source.
Pin the actual built PRoot, loaders and build flags as well: a filename prefix
alone is not a complete compatibility contract.

The normal Termux build, without `USERLAND`, uses `.l2s.`. `USERLAND` uses
`.proot.l2s.` and has different stat handling; it is a different backend.
The current service does not set `PROOT_L2S_DIR`, so backing data is placed next
to the original source. Use the same setting for the first bounded backend.

For two guest names `a` and `b` in the host directory `H`, the extension creates:

```text
H/a                  -> H/.l2s.a0001
H/b                  -> H/.l2s.a0001
H/.l2s.a0001          -> H/.l2s.a0001.0002
H/.l2s.a0001.0002       one ordinary data file, original mode and mtime
```

All three arrows store **absolute host paths**, not guest `/usr/...` paths.
The intermediate name contains a collision suffix; the final four-digit suffix
stores the guest link count. PRoot canonicalizes the paths and adjusts
`stat`, `lstat`, `fstat` and `statx` results to represent the shared data inode.
`rename` and `unlink` update the representation and link count, removing the
backing file when its final guest name disappears. This is filesystem
compatibility, not namespace isolation or a kernel hardlink on Android.

`PROOT_L2S_DIR`, if configured, changes the backing location. The current source
holds an `O_NOFOLLOW` directory descriptor for host mutations there; its tests
include refusal of a replaced-directory symlink escape. Introducing such a
central directory would require a separate storage/policy decision and tests.
It is unnecessary for the two current Debian groups.

## Proposed install contract

The implemented FoldGPT-owned format identifier is
`proot-termux-l2s-7266fb3-v1`, explicitly tied to the source/build above.
It is not an upstream-stable format version. Record at least:

- Backend identifier, exact PRoot/loader hashes and relevant build flags.
- Authenticated archive digest and the final immutable host root path/inode.
- For each group: source archive member, every hardlink member, unique backing
  relative path, intermediate relative path, actual shared count, original
  size/hash/mode/mtime and expected absolute link targets.
- A durable completed-conversion receipt only after all structures and metadata
  have been flushed and verified. Do not accept the POSIX inode-equality receipt
  for this backend.

Group the trusted archive's hardlinks by their declared regular source before
conversion. Require every source and alias to be unique and rooted in declared
directories; verify their archived mode/mtime consistency. This archive has
exactly two groups, each with a count of two:

| Original regular member | Hardlink member |
| --- | --- |
| `usr/bin/perl` | `usr/bin/perl5.40.1` |
| `usr/bin/perlbug` | `usr/bin/perlthanks` |

For a newly extracted, inactive stage under an exclusive lease, relocate each
source's **existing inode** to its final backing filename, then create the
intermediate and all guest-name symlinks using exclusive operations. The data
stays in a single inode; do not duplicate bytes or replace source contents.
Reserve and validate the `.l2s.` generated names before any mutation. Refuse
collisions with archive members, malformed names, unsupported counts/path
lengths, unexpected existing files or a different backend receipt. Keep the
same final directory throughout this step and activation.

The current fresh transaction publishes a symlink to an immutable stage rather
than renaming that stage. That is compatible with absolute host link targets.
A later directory move, copied rootfs, backup restore at a different app path
or package-ID change would break these links. Such operations need an explicit
offline relocation/migration tool that verifies and rewrites the registered
targets. Do not casually change the guest launcher root between its stable
physical path and a new alias without testing PRoot path translation.

Conversion is not a single atomic filesystem operation. If it is part of
extraction, write its completed receipt only at the end. A process killed during
conversion leaves an inactive incomplete stage that can be discarded and
re-extracted under the existing ownership contract. A valid old POSIX receipt
must not accidentally adopt a partly converted stage. Persist the backend in
the transaction identity and make mismatched recovery fail rather than guessing
which layout exists. Exercise process termination after moving backing data,
after the intermediate, after each alias and before/after the final receipt.

Never perform this conversion on the currently active private root.

## Validation that preserves the distinction

Host inspection and guest inspection answer different questions. Require both.

The host validator uses no-follow operations and the group registry to verify:

- Every logical archive name exists once; non-group files and guest symlinks
  retain their original representation and expected metadata.
- Group members and intermediates are physical symlinks with exactly the
  registered targets inside the immutable root; the one backing file is an
  ordinary app-owned inode with the authenticated bytes, original mode/mtime,
  and no unexpected host hardlinks.
- There is exactly one backing file per group, no orphan group entries and no
  unrelated extra paths. Generated internals are accounted for explicitly.

For this archive, the projected physical tree has 20,244 entries, consisting
of 2,595 directories, 16,358 regular files and 1,291 symlinks. The original
logical archive remains 20,240 members with 1,285 ordinary symlinks and two
hardlink aliases. Physical regular data remains 958,101,116 bytes. Do not alter
the trusted archive totals to disguise the representation change; record and
validate both logical and physical totals.

The guest validator runs through the **same PRoot build and flags** used by
the runtime. For each actual Debian pair, require ordinary-file type (including
`lstat`), identical device/inode, link count two via legacy stat and `statx`,
matching contents and execution/read behavior. Actual writes/chmod/unlink tests
belong in a disposable fixture, not in Debian's installed Perl executables.
The fixture must prove that writes and metadata changes through either name
affect the other, rename preserves the relation, unlink leaves the survivor,
and the last unlink reclaims the data. Also test a third alias, failed creation,
open-FD lifetime and package-update replacement behavior before declaring broad
hardlink compatibility.

Native policy enforcement must evaluate the actual backing access. The kernel
sees the hidden data inode, while the guest names aliases. In particular, two
aliases of one inode cannot be treated as unrelated objects when defining
read/write permissions. A PRoot stat presentation is not protection against
access to a backing name; the executor's real filesystem boundary remains a
separate requirement. PRoot itself does not sandbox arbitrary native code.

## Real host experiments performed

`tools/install/transaction/probe-link2symlink.py` ran as UID 65534 (`nobody`)
against the already-built host PRoot binary:

```text
binary SHA256 55c9e4783ba83543143c76b6920029cadf01e3194e53f3f95b81ac36e885a0d9
source /var/tmp/foldgpt-pinned-proot-build-20260906/source
evidence /var/tmp/foldgpt-l2s-probe-3mqj29op/result.json
```

The first child called real `link()` through PRoot. Independent host inspection
observed the three symlinks and single data file above, with a kernel link count
of one. Guest Python `lstat` and coreutils `stat` reported regular files sharing
one inode with link count two. A separate PRoot process reopened them and passed
shared write, chmod, nanosecond mtime, rename, survivor unlink and final unlink.
The host directory was empty afterwards.

A second fixture was assembled independently by the host using that exact
storage layout without any `link()` call or data duplication. The same guest
operations passed, and its backing data was reclaimed after the last unlink.
An `EEXIST` test preserved both files' data and guest link counts; PRoot did
convert the attempted source to a one-link representation, so failed `link()`
does not guarantee a byte-identical physical layout.

`link2symlink-guest.c` was then compiled as a static x86-64 executable. With
`proot -l -r /var/tmp/foldgpt-l2s-root-rpQQzYRj -w / /probe`, it passed the same
operations inside a real separate guest root, with no host-directory bindings,
first for a guest-created group and then for a host-provisioned group. It
explicitly checks both `lstat` and `statx`. Host inspection found the data
directory empty after both runs. These tests use the host CPU directly; no
emulation or Android execution is involved.

## Actual Android validation on 6 September 2026

The Android extractor prepared the unchanged Debian archive with this backend.
The independent Python verifier compared all 20,244 physical entries against
the 20,240 logical archive entries, explicitly accounting for each intermediate,
backing file, absolute target, mode, timestamp and data digest. All comparisons
pass; the physical regular payload is exactly 958,101,116 bytes. Native shell
SHA checks independently confirm six key files, including both backing files.

`ProotStorageProbeService` runs only in debug builds under permission `DUMP`,
uses no Intent arguments, and holds the inactive transaction lease. Actual
Android evidence: UID 10412, SELinux `untrusted_app`, inherited `Seccomp: 2`.
The installed binaries inspected by the service have these hashes:

| Component | SHA-256 |
| --- | --- |
| PRoot | `789eed1718f2da762db1970d636d926fb6b66c09e5b31eeebcc04a80d60ba4c3` |
| ARM64 loader | `e2c43b1ee24dce17769e3dea22dd7d001c6307fdf825509bf5e76f6ae27af41c` |
| ARM32 loader | `ace22dc72b05deb829e2ed75db36ed66021ca0d111340c4394a0a5710173def2` |
| Stripped ARM64 guest fixture | `f2de4380ccc9aa54ceaec2db3c310fe7bb588e7a8d5c4607c85eaa62a2a8b169` |

Four actual guest cases pass with the runtime's PRoot flags and private test
bindings: read-only legacy stat/statx/content checks for both real Debian
pairs; execution of pristine Debian Perl; a guest-created group; and a group
created by the production Java converter. Both mutable fixtures pass shared
write/chmod/nanosecond mtime, rename, survivor unlink and last unlink. Android
host inspection confirms the data directory is empty after final unlink.
No client files, credentials, network or model calls are involved.

Build the debug fixture using `build-link2symlink-guest.sh OUTPUT_DIRECTORY`,
copy it into `android/native/debug/arm64-v8a/`, and assemble debug. The fixture
and service are excluded from release. Local evidence is retained under
`downloads/install/android-proot-storage-5640582806351511109/` and
`downloads/install/android-proot-extraction-8bd6790e/` (ignored, not public).

Five real process-death recovery cases also pass under an unprivileged host
JVM, one at each conversion checkpoint; they are not Android power-loss tests.
Third-alias/open-FD/package-update cases and physical-root relocation remain
outside this bounded validation. It does not establish full filesystem
equivalence, an update transaction or completed Codex isolation.
