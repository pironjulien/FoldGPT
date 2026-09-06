# Pristine Debian 13 ARM64 base

`tools/install/build_rootfs.py` constructs a new Debian base from authenticated
Debian repositories. It never reads the phone, an existing Linux installation,
an OpenAI profile or a keyring. The result contains the free runtime dependencies;
it does **not** include OpenAI's client, the namespace compatibility shim,
FoldGPT's GPU candidate or a configured user account.

This is a build input for the Android installer, not an installable APK or an
activated phone runtime. See [the integration bundle](README.md).

## Host requirements and command

Use Ubuntu 24.04 WSL with a Linux filesystem and host root privileges. The script
rejects an Android host. Root is needed only for the disposable host chroot,
package configuration and mount namespace; it is not an Android requirement.

Install host tools through the host's authenticated package repositories:

```sh
apt-get update
apt-get install --no-install-recommends mmdebstrap debootstrap \
  debian-archive-keyring qemu-user-static binfmt-support arch-test \
  gnupg ca-certificates xz-utils python3 util-linux
arch-test arm64
```

On an x86-64 build host, the last command must report working ARM64 execution
through QEMU user-mode and the host's `binfmt_misc` support. No QEMU executable
is copied into the rootfs. Its ARM64 packages execute directly on an ARM64
phone once Android activation is implemented. Build-host emulation is separate
from the phone's runtime architecture.

From Windows:

```powershell
wsl -d Ubuntu-24.04 --user root --exec python3 -B /mnt/c/Dev/ChatgptFold/tools/install/build_rootfs.py build
```

The script creates a new `/var/tmp/foldgpt-rootfs-*` work directory on ext4 and
prints its path. Build logs and evidence remain there on failure for inspection;
the script does not erase a failed rootfs or overwrite a previous artifact.
Completed artifacts are copied with digest checks to the ignored
`downloads/install/debian-13-arm64-<digest-prefix>/` directory.

If package installation succeeded but a later verification or export failed,
resume the inactive build without repeating `mmdebstrap`:

```powershell
wsl -d Ubuntu-24.04 --user root --exec python3 -B /mnt/c/Dev/ChatgptFold/tools/install/build_rootfs.py finalize /var/tmp/foldgpt-rootfs-BUILD_ID
```

Finalization requires real root-owned build, rootfs, evidence and `/dev`
directories, with no group/other write permission, symlink aliases or mounts
inside the rootfs. These checks precede cleanup. The export uses Linux
`RENAME_NOREPLACE` on ext4 and native Windows `os.rename` on WSL's NTFS-backed
`/mnt/c` paths; both refuse an existing destination. A failed transfer remains
available for inspection.

## Authentication chain

Ubuntu 24.04's signed `debian-archive-keyring` package supplies Debian Bookworm
trust anchors but predates Trixie's archive keys. The builder does not download
a replacement key from an unauthenticated website:

1. An isolated APT configuration verifies Debian's Bookworm repository using
   those installed Debian keys.
2. APT acquires the current Bookworm `debian-archive-keyring` package. The script
   independently checks its bytes against the SHA-256 from the authenticated
   package index and extracts the updated keyring into the build directory.
3. `mmdebstrap` uses that keyring to authenticate Trixie, Trixie updates and
   Trixie security over HTTPS, then validates each downloaded Debian package.
4. `gpgv` rechecks the four retained `InRelease` files and records the successful
   signature fingerprints and keyring digests.

There is no `trusted=yes`, unauthenticated install, disabled expiry check or
checksum inferred from a package filename. An authentication failure stops the
build. Versions follow the live authenticated repositories; a future snapshot
contract is needed for reproducing the exact package set after those versions
leave the mirrors.

## Contents and evidence

The package selection is versioned in `PACKAGES` inside the builder. It includes
APT/dpkg and Debian archive keys, CA certificates, glibc, Bash/coreutils, Python
with WebSockets/SecretStorage, D-Bus/GNOME Keyring, xfwm4/wmctrl, XKB data, fonts,
Git, Vulkan loader and Debian's standard Mesa libraries. The additional free
GTK/NSS/ALSA/X11 dependencies cover the metadata observed in the official
ChatGPT ARM64 26.901.41600 package. Future client versions may change that set.
The proprietary package is neither an input copied into the base nor an output.

No locale, manual page or copyright pruning is applied. Debian's package
database, repository configuration and installed documentation are retained.
Downloaded package archives are preserved in the separate provenance artifact,
then removed from the rootfs's download cache to avoid duplicating their size on
the phone. Signed APT indexes remain available in both the rootfs and provenance.

The output directory contains:

- `debian-13-arm64-rootfs.tar.gz`: the completed filesystem, with numeric
  ownership and package permissions preserved, `/dev` empty and no host mounts.
- `debian-13-arm64-provenance.tar.gz`: authenticated `.deb` inputs, signed
  indexes and keyrings, signature verification reports, tool versions, build
  scripts, logs and rootfs verification results.
- `manifest.json`: component identity, rootfs digest/size, requested packages,
  verification results and explicit missing activation/client/keyring status.
- `installed-packages.tsv` and `downloaded-packages.json`: every installed
  package's version/architecture and its corresponding archived `.deb` digest.
- `repository-signatures.json` and `SHA256SUMS.json`: repository trust evidence
  and hashes of the delivered artifacts.

The builder refuses to proceed if an installed package lacks its matching
downloaded-package provenance. The provenance contains Debian binary packages
and authenticated indexes. A separate [exact source collection](ROOTFS-SOURCES.md)
now preserves all 185 source-package versions named by these 289 binaries,
with 605 authenticated source components and their installed notices.
It remains separate from the original provenance archive. Exact sources for
statically embedded build dependencies and their notices still need review;
the source-package mapping alone does not establish that closure. This
development output is not a published binary release.

## Verification and privacy

`verify_rootfs.py` performs static checks and bounded ARM64 probes in a host
mount namespace where the guest root is read-only. It does not unlock or create
a GNOME keyring. Its report distinguishes host QEMU execution from Android
testing. The build records no Android success.

The probes receive only an ephemeral `/dev/null` on a separate read-only tmpfs
inside their private namespace, because Git requires it. No device node is
created in the on-disk rootfs. A real compiled probe verifies that opening a
rootfs file with `O_TRUNC` fails with `EROFS`, while `/dev/null` remains usable.

The generic hostname is `foldgpt`; `/etc/hosts` contains loopback entries only.
The distributed resolver file contains an instruction comment, not the build
host's DNS servers. Android activation must populate DNS from the active
network before using APT or the client. No fixed third-party DNS provider is
silently selected.

There is no initialized machine ID, non-system login account, account profile,
SSH host key, keyring collection or compatibility preload. Default system
accounts supplied by Debian remain locked. The archive deliberately has no
device nodes: Android will bind its actual `/dev` into the guest rather than
trying to create devices with an ordinary app UID.

Debian's minimal `base-passwd` format can lock system accounts directly with
`*` in `/etc/passwd` without creating `/etc/shadow`. The verifier accepts these
locked accounts and still rejects an `x` reference without a matching locked
shadow entry. It also allows Debian's standard empty `/run/lock` directory,
while refusing live runtime state.

The base is not yet suitable for direct activation: the Android host must
install it transactionally, validate XKB access before Xlorie starts, establish
its guest identity, initialize a new Keystore/GNOME secret pair, acquire the
official client and provide the validated execution/isolation layer. The current
service's hard-coded guest identity and legacy compatibility shim are not
silently reproduced in this pristine base.

## Verified local artifact (2026-09-06)

Output: `downloads/install/debian-13-arm64-dd0aac2065057596/`.
Retained ext4 build: `/var/tmp/foldgpt-rootfs-eqhh0jhx`.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `debian-13-arm64-rootfs.tar.gz` | 327673156 | `dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f` |
| `debian-13-arm64-provenance.tar.gz` | 216191848 | `72f50499cc6856194d6532929c6148a9a4d9406ce6efda57758e6fc95c2ec041` |

The completed image passed the static and read-only guest checks: 289 installed
packages matched to retained authenticated `.deb` inputs, four valid signed
repository indexes, 1,030 AArch64 ELF files, 16,360 regular files, 280 usable
fonts, 18 locked system accounts and no human accounts. `dpkg --audit`, Python
WebSockets/SecretStorage imports, fontconfig and Git 2.47.3 passed. XKB rules
are readable from outside the guest. No OpenAI client, initialized keyring,
personal profile, QEMU executable or compatibility shim is included.

All six exported files matched `SHA256SUMS.json` when independently hashed by
native Windows Python. Ten verifier regressions and five builder regressions
passed under WSL; the latter cover real ext4/NTFS no-replacement publication
and refusal of an external `/dev` symlink, unsafe directory ownership or
writable directories before cleanup. The outside fixture survives unchanged.

There was one full `mmdebstrap` installation (367.5395 seconds), followed by
corrected post-build signature verification and finalization. The provenance
captures the builder used for the successful export. Subsequent error-path and
cleanup-boundary hardening is in the current source and regression tests; it
does not change this already verified rootfs. There was no second full build
and no Android activation test. Binary publication remains pending acquisition
of the corresponding Debian sources and license review.
