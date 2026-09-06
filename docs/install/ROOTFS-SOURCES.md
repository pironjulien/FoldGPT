# Exact Debian source inputs for the pristine rootfs

`tools/install/rootfs_sources.py` collects the exact Debian source packages
associated with the binaries in [the pristine ARM64 base](ROOTFS.md). It keeps
their authenticated archive metadata, all source components and the copyright
notices installed in that exact rootfs. It does not publish a binary, install
a Debian package, execute guest code or access Android.

The completed collection covers **289 installed binaries, 185 exact source
package versions and all 605 source components** described by their signed
archive indexes. This closes the missing-source-package input from the initial
base build. It does not prove complete source coverage of statically linked
build dependencies; that distinction is recorded in the artifact manifest.

## Collection and trust chain

The input is the completed local rootfs artifact directory, with its original
manifest, package inventory, binary provenance and checksums. Collection:

1. Rehashes every input file and verifies the rootfs identity. For every binary,
   it reads the preserved `.deb`, checks its bytes and reads the actual
   `Package`, `Version`, `Architecture` and `Source` fields using `dpkg-deb`.
   No maintainer scripts or executable package contents run.
2. Derives the source identity using Debian's explicit `Source` metadata.
   Binary-only rebuild suffixes and differing binary/source epochs are handled
   through that metadata, without guessing or choosing a newer candidate.
3. Reuses the archive keyring authenticated by the base build's documented
   Bookworm-to-Trixie bootstrap, checks its recorded digest, and retains the
   seed keyring and trust-chain evidence. The original local build is the trust
   starting point; these development artifacts do not have a release signature.
4. Verifies the current Trixie, updates and security `InRelease` signatures
   with `gpgv`. Repository identity and dates are checked; expired metadata
   stops collection. The stable release has no `Valid-Until`, as published by
   Debian; the updates and security indexes must have one.
5. Downloads `main/source/Sources.xz` and verifies its size and SHA-256 against
   the signed release. It selects exactly the 185 required name/version pairs.
   Missing versions or conflicting authenticated component hashes stop the
   operation. All versions needed by this build were available on the mirrors.
6. Retains and verifies every component from `Checksums-Sha256`, including
   each `.dsc`, original upstream archive, additional `orig-*` archive and
   Debian patch archive. Descriptor identity and the complete descriptor
   component table must match the authenticated index.

Individual uploader signatures in `.dsc` files remain intact, but they are not
the independently verified trust anchor: authentication comes through the
Debian archive signature and the complete SHA-256 chain.

## Running or resuming

Use the same Ubuntu 24.04 WSL host as the base build. Host `python3`, `dpkg-deb`,
`gpgv` and `tar` are required. Collection runs with host root to keep its
disposable ext4 work directory and resumed state under one owner. No Android
root or CPU emulation is used.

```powershell
wsl -d Ubuntu-24.04 --user root --exec python3 -B /mnt/c/Dev/ChatgptFold/tools/install/rootfs_sources.py /mnt/c/Dev/ChatgptFold/downloads/install/debian-13-arm64-dd0aac2065057596
```

The script prints `/var/tmp/foldgpt-rootfs-sources-*`. To reuse already verified
downloads after interruption or to reverify and package the same collection:

```powershell
wsl -d Ubuntu-24.04 --user root --exec python3 -B /mnt/c/Dev/ChatgptFold/tools/install/rootfs_sources.py /mnt/c/Dev/ChatgptFold/downloads/install/debian-13-arm64-dd0aac2065057596 --resume /var/tmp/foldgpt-rootfs-sources-BUILD_ID
```

Resume preserves the original repository metadata and checks its signatures,
dates and every source component again. Expired indexes require a new
collection; the script never disables expiry or silently substitutes source
versions. A checksum mismatch stops the operation rather than replacing the
suspect cached file.

Resumed directories must be canonical and owned by the collector, without
group/other write permission. Symlinks, hardlinks and special files are refused.
The package recipe defines the complete set of exported files; unexpected
files, orphaned transfer temporaries and extra directories stop packaging.
The internal checksum table excludes itself, including on a second generation.
Every regular tar member is verified both before and after export. The existing
rootfs publication helper provides atomic no-replacement export on ext4 and
native Windows NTFS.

## Artifact contents

The source archive is an uncompressed outer tar because its 605 source
components are already compressed or signed. It contains:

- `sources/<name>/<version>/`: every authenticated source component, byte for
  byte; version epochs use `%3A` in directory names for Windows compatibility.
- `source-packages.json` and `binary-source-map.json`: the selected full index
  stanzas, source URLs, component sizes/hashes and exact binary-to-source map.
- `repositories/` and `repositories.json`: three `InRelease` files, three
  authenticated `Sources.xz` indexes and signature results.
- `notices/`, `notices.json`: all 289 installed package copyright notices and
  Debian's common license texts. Rootfs symlinks are resolved inside the archive,
  without extracting or following host paths. The notices retain their own
  authors, licenses and terms; no single license is assigned to the rootfs.
- `base-evidence/`: original base identity, package metadata, keyrings,
  trust-chain evidence and build/verification scripts. The original binary
  provenance archive is identified by SHA-256 and remains a separate artifact.
- `rootfs_sources.py`, `manifest.json`, `SHA256SUMS.json`: the collector source
  captured for the run, scope, explicit limits and hashes of every payload file.

No OpenAI client, account, secret, Android component or compatibility shim is
included. Source archives are retained without execution or general extraction.

## Verified local result (2026-09-06)

The final artifact was produced by a successful **real resume** after the
initial collection, using the existing downloads and revalidating all of them.

Output directory:
`downloads/install/debian-sources-dd0aac2065057596-b06d96d663ca4df7/`

| Item | Verified value |
| --- | --- |
| Rootfs SHA-256 | `dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f` |
| Source archive | `debian-13-arm64-corresponding-sources.tar` |
| Archive bytes | 2008238080 |
| Archive SHA-256 | `b06d96d663ca4df7e5ff7e0b66d92970edb6ef1c9fa53d2086aaa89409cd5727` |
| Exact source components | 605 files, 1989463132 bytes |
| Binary/source mapping | 289 binaries, 185 source versions |
| Retained package notices | 289 |
| Verified regular archive members | 937, including the checksum index |
| Preserved ext4 work directory | `/var/tmp/foldgpt-rootfs-sources-ibh7lrfs` |

Native Windows Python independently verified all six exported file hashes and
all 937 archive members. It confirmed that the internal checksum table has no
self-entry and the captured collector matches the source used for this final
run. Its report is retained locally as
`downloads/install/debian-sources-b06d96d663ca4df7-validation.json`.

The 37 regression tests passed under WSL. They cover exact source versions,
binNMU/epoch handling, malformed or conflicting metadata, full descriptor
coverage, safe archive link resolution, rejected transfers, two successive
checksum generations, unexpected files/directories/links and complete exported
archive verification with corrupted, missing or duplicated members.

```powershell
wsl -d Ubuntu-24.04 --user root --exec python3 -B -m unittest discover -s /mnt/c/Dev/ChatgptFold/tools/install -p rootfs_sources_test.py -v
```

## Remaining distribution limits

This artifact contains the complete Debian source-package inputs selected by
the 289 binaries' `Source` metadata, together with their installed notices.
It is not a complete reconstruction of each binary's build environment or an
individual license-compliance determination.

In particular, `sqv` comes from `rust-sequoia-sqv 1.3.0-3`; its authenticated
source descriptor lists external Rust crate build dependencies. The 185-source
collection does not establish the exact versions of all statically embedded
dependencies. Build records such as the relevant `.buildinfo`, component
analysis and any additional matching sources/notices are needed before claiming
that this closure is complete. A current dependency candidate cannot substitute
for the version actually used to build the binary.

The base also has no signed FoldGPT release/update channel and has not been
rebuilt reproducibly or activated on Android. No binary has been published by
this collection step.
