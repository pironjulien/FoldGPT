# Verified official client input

`tools/install/official_client_package.py` implements the bounded package-input
part of the [installation coordinator contract](end-to-end-architecture.md).
It prepares the exact official `.deb` for a later guest package-manager step and
can compare all packaged files against an inactive root. It does not install
packages, execute maintainer scripts, extract an archive, publish a runtime or
declare the client ready.

## Trust and caller contract

The caller supplies an independently authenticated descriptor containing the
official acquisition/documentation URLs, package name, exact version, ARM64
architecture, SHA-256, compressed size and expanded-tar/member bounds. The helper
compares the package bytes before interpreting its metadata. Creating a
descriptor from the hash of an untrusted local file is not authentication.

The accepted acquisition channel is the official Linux page's ARM64 `.deb`
link. The helper does not fetch `latest`, substitute a mirror or manufacture a
signature result. A newer package requires a newly authenticated descriptor;
the existing version/hash binding must not silently change when that URL moves.
The descriptor itself must be delivered through the trusted component mechanism
chosen by the Android coordinator. No general-purpose descriptor downloader or
APK-integrated client installer is provided here yet.

`prepare` receives an existing private directory created by the installation
coordinator under its global lease. It adds a per-input `flock`, records the
exact descriptor and copies the package to an exclusive temporary file, hashes
the completed copy, parses it, synchronizes it and publishes `package.deb`.
Only then is a complete `inventory.json` written and synchronized. Existing
descriptors, packages or inventories must match; unrelated content is refused.
Named partial files can be retried inside this same bound directory. They are
never readiness evidence. After a crash following package publication, a retry
with no source revalidates and reuses the same package inode.

The caller must keep the global installation lease throughout provisioning and
validation. The helper's local lock does not stop another guest process from
modifying a staged root or replace the Android transaction's root-identity
check. Input files remain owned by the caller; "pinned" refers to the required
digest, not a kernel immutable attribute.

## What is checked

The parser accepts Debian ar format 2.0, one bounded gzip/xz control archive,
one bounded gzip/xz data archive and an optional `_gpgorigin` signature member.
It rejects duplicate/unknown ar members, malformed bounds/alignment, unsafe
paths, duplicate tar paths, symlink ancestors, links escaping the guest root,
hardlinks, special files, PAX/sparse records and hidden/truncated tar tails.
GNU long names remain supported within Linux path/component bounds. This is a
deliberately explicit supported format; a future official packaging change
fails for review instead of silently losing metadata.

The inventory includes the original control fields and control-file hashes,
every logical payload path, each regular file's SHA-256/size/mode, symlink text
and directory presence. Both `usr/lib/chatgpt/ChatGPT` and
`usr/lib/chatgpt/resources/codex` must contain executable little-endian ELF64
for AArch64, independently of the Debian `Architecture` field. Expanded bytes,
member count, control data and the serialized inventory have explicit bounds.
File-descriptor identity and mutation timestamps are checked during inspection.

`verify-files` recomputes the inventory from the authenticated `.deb`; it does
not trust a separately supplied inventory. It walks the inactive root with
directory descriptors and no-follow operations, then compares regular-file
contents and modes, directory kinds and literal symlink targets. Guest absolute
symlinks never resolve against Android or the host. Shared Debian directory
modes and the stage root mode are not owned by this client package and are not
claimed to match. This step returns the observed root device/inode and the
explicit scope `packaged-files-only`.

This evidence does not replace a real `dpkg` installed/configured-state check,
dependency resolution, maintainer-script success, repository setup, loader or
GPU tests, GNOME collection association or enforcement of command policy.
Those remain coordinator obligations before `RootfsTransaction.activate`.

## Invocation

These operations require Linux/guest Python with POSIX descriptor operations,
`flock`, gzip and xz support. A caller-owned private stage is a required input.
The descriptor path in these examples must already be authenticated.

```sh
python3 tools/install/official_client_package.py inspect \
  --descriptor /private/client-descriptor.json --package /private/chatgpt_arm64.deb

python3 tools/install/official_client_package.py prepare \
  --descriptor /private/client-descriptor.json --package /private/chatgpt_arm64.deb \
  --stage /private/coordinator/client-input

# Recovery after the complete package was published; no archive source required.
python3 tools/install/official_client_package.py prepare \
  --descriptor /private/client-descriptor.json --stage /private/coordinator/client-input

python3 tools/install/official_client_package.py verify-files \
  --descriptor /private/client-descriptor.json \
  --package /private/coordinator/client-input/package.deb --root /private/inactive-root
```

## Evidence from 6 September 2026

The existing official package `chatgpt` **26.901.41600**, ARM64, was inspected
successfully: 388,651,910 compressed bytes, SHA-256
`8d5141b299ca593255fa25760895e84375937cc305197528c822dfa71ac2a3bf`, 7,360
logical data members and 1,365,770,240 expanded tar bytes. Both core executable
headers passed AArch64 validation. The package was not changed or installed
on the phone by these checks.

A separate provenance probe fetched the official repository's `InRelease`
directly over HTTPS on this date. Its signature verified with fingerprint
`3BFA0E4AE8B8CC16A2D9BA684A3B4A566C4660E4`, whose public key is carried by
the official package's `postinst`. The same key successfully verified the
cached package's detached `_gpgorigin` signature over the exact concatenation
of its `debian-binary`, control and data ar members. The independently fetched
HTTPS release provides the external origin binding here; a key merely found
inside a local package would not. This separate proof is not represented as
`embeddedSignatureVerified: true` by the generic helper, which uses the caller's
trusted descriptor and does not run GPG itself.

The current official APT index advertises **26.901.51231**, with SHA-256
`02a2f5c6cb69509c62abcbdd13c76b139cdb2ca9edde7537239ddde024077ea0`.
That version has not been adopted or qualified by this work. The inspected
official `postinst` configures the signed `stable/main` repository under
`https://persistent.oaistatic.com/codex-app-prod/linux/deb`, installs
`/usr/share/keyrings/chatgpt-archive-keyring.gpg` and maintains the official
`.sources` file. FoldGPT must execute that intact package-manager flow when
wiring the later installation step; copying application files alone does not
provide those installed-state/update guarantees.

The 20-test filesystem/archive suite passed as Linux user `nobody`. It covers
real compressed archives, missing and wrong-architecture executable headers,
traversal/symlink/special-member attacks, descriptor and inventory tampering,
partial-copy failure, content/mode drift, and an actual subprocess `SIGKILL`
after package publication followed by source-free recovery of the same inode.

A separate full-size run also passed as `nobody`: prepare the authenticated
388 MB package, extract it with real `dpkg-deb --extract` into a new inactive
ext4 directory, verify all 7,359 paths below the archive root, then resume
preparation without the source while retaining the same package inode. No
maintainer script ran; this is extraction/integrity evidence, not a configured
Debian package installation. The retained report is `real-package-report.json`
in the evidence directory below, and the Linux stage is
`/var/tmp/foldgpt-client-real-xbhzbg_m`.

Private evidence and the separate GPG probe are retained under
`downloads/install/client-input-59de43132ff8467498627ae89f08d494/`.
No proprietary client package, account profile or credential is added to the
source distribution.
