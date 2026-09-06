# Fresh-install preparation

`tools/install/guest_bundle.py` now assembles and verifies the guest integration
files used by the current service. It can prepare them transactionally in a new
Linux directory. This is a reusable input to the future bootstrap, **not a
Debian installer, an APK installation or a first-launch success**. It does not
touch a device, execute a guest script or change the official client.

## Build and verify

Python 3.11 or newer is required. Build and verification run on Windows or Linux.
Preparation additionally requires Linux `renameat2`, fd-relative filesystem
operations and a filesystem enforcing POSIX permissions. Under WSL, use an ext4
destination for preparation, not ordinary NTFS.
The immediate output/preparation parent on Linux must belong to the caller and
forbid group/other writes. This prevents replacement of a private staging name
by another user of a shared parent. Keep its ancestor path under trusted control
as well. On Windows, use a private directory protected by the user's normal ACL;
the Python tool does not audit Windows ACLs.

From the repository root, choose a new output filename in an existing directory:

```powershell
New-Item -ItemType Directory -Force downloads/install | Out-Null
python tools/install/guest_bundle.py build --output downloads/install/guest-integration-v1.tar
```

The command prints the archive's SHA-256 and size. It refuses to replace an
existing file, even if the contents match. The archive is first written and
flushed to a temporary file, then exposed through an exclusive hard link. The
filesystem must support hard links; there is no overwrite fallback.

For local verification, use that exact digest. A distribution consumer must
instead obtain the expected digest from a trusted release descriptor or the
signed APK. **A checksum downloaded alongside an untrusted archive does not
authenticate it.** This tool does not yet implement signed release metadata.

```powershell
python tools/install/guest_bundle.py verify --archive downloads/install/guest-integration-v1.tar --sha256 TRUSTED_SHA256
```

To prepare a new revision directory under a new private Linux parent:

```sh
install_parent=$(mktemp -d /var/tmp/foldgpt-install-XXXXXXXX)
python3 tools/install/guest_bundle.py prepare \
  --archive downloads/install/guest-integration-v1.tar \
  --sha256 TRUSTED_SHA256 \
  --destination "$install_parent/integration-v1"
```

The output has `manifest.json`, `LICENSE` and `payload/usr/local/...`. No file is
copied into `/usr/local`, `files/debian` or another existing installation. The
eventual bootstrap must apply this payload only to its own unactivated, verified
rootfs. Updating a live rootfs requires a separate activation/rollback contract.

## Bundle contract

The format identifier is `foldgpt.guest-integration.v1`. Its positive source list
is deliberately small:

| Repository input | Archive path | Mode |
| --- | --- | --- |
| `LICENSE` | `LICENSE` | 0644 |
| `foldgpt-session.sh` | `payload/usr/local/bin/foldgpt-session` | 0700 |
| `foldgpt_keyring.py` | `payload/usr/local/lib/foldgpt/foldgpt_keyring.py` | 0644 |
| `foldgpt_ime.py` | `payload/usr/local/lib/foldgpt/foldgpt_ime.py` | 0644 |
| `keyboard-focus.js` | `payload/usr/local/lib/foldgpt/keyboard-focus.js` | 0644 |

The builder reads only those five regular UTF-8 text files, rejects NUL bytes,
normalizes CRLF to LF and never enumerates a user profile, rootfs or dependency
directory. Source contents still need normal review before release; an allowlist
is not a secret scanner. The package includes no binary provenance claim.

`manifest.json` contains exactly `format`, `kind` (`guest-integration-only`) and
`files`. Each file record contains its archive `path`, integer `size`, integer
`mode` and lowercase `sha256`; records are ordered by path. JSON uses sorted keys,
two-space indentation, ASCII escapes and one final LF. The manifest does not
contain its own hash; the externally trusted archive hash covers it.

The uncompressed USTAR archive uses sorted regular-file entries, zero uid/gid and
timestamps, empty owner names, fixed modes and Python's canonical 10 KiB record
padding. Rebuilding the same normalized inputs produces identical bytes. Inputs
are capped at 1 MiB per file and 8 MiB per archive; this format is for integration
scripts, not a root filesystem.

Verification checks the expected SHA-256 before parsing. It rejects missing or
duplicate entries, other paths, links, directories, devices, unexpected modes,
altered manifest metadata and file hashes. Reconstructing and comparing the
canonical archive also rejects alternate headers, PAX extensions, truncated
padding, concatenated archives and hidden trailing data. Verification and
preparation use the same in-memory byte snapshot even if the input path is later
replaced.

Preparation writes only beneath a newly created 0700 staging directory, uses
exclusive no-follow opens and checks actual file modes. After files and
directories have been flushed, Linux `renameat2(RENAME_NOREPLACE)` promotes the
whole directory. An existing destination is never replaced or merged, including
an empty directory or symlink. Normal failures clean only that invocation's
private staging directory. A process or power failure may leave a staging
directory; it cannot turn that directory into an activated rootfs. A future
Android installer must implement its own explicit recovery and durable install
state. A failure after the final rename can leave the complete new directory;
retry must inspect it rather than overwrite it.

## Checks

```powershell
python -B -m unittest discover -s tools/install -p test_guest_bundle.py -v
wsl -d Ubuntu-24.04 --exec python3 -B -m unittest discover -s /mnt/c/Dev/ChatgptFold/tools/install -p test_guest_bundle.py -v
```

All 13 tests passed in WSL on 6 September 2026. Windows passed the nine portable
checks and skipped four tests requiring actual Linux filesystem behavior.
They cover integrity, path/link attacks, ambiguous archives, deterministic
assembly, refusal of shared writable parents, existing-output preservation and
recovery after a real write failure.
No Android install or first launch is implied by those results.

## Remaining dependencies for an autonomous APK

1. **Native runtime supply.** The development APK now contains independently built libraries.
   An [independent NDK build](../../tools/install/native/README.md) now compiles
   PRoot, both matching loaders, talloc and android-shmem without Termux and
   verifies five ELF outputs, with corresponding sources, notices and provenance.
   The five-library set is integrated and passes real Android startup, storage
   and shared-memory checks; see the native build notes for exact evidence.
   The independent Xlorie build also exists; the final package still needs a
   signed APK update identity. See
   [the native build notes](../../tools/gpu/X11-BUILD.md) and
   [distribution policy](../../LEGAL.md).
2. **A pristine Debian ARM64 rootfs.** A new [Debian base](ROOTFS.md) has been
   constructed from authenticated repositories, with 289 configured packages,
   retained provenance and no user profile. The current migration still copies
   an existing installation; the new base has not been activated on Android.
   Activation must preserve guest symlinks and provision DNS, guest identity and
   runtime bindings. `xkb-data` must already
   be present and readable at `usr/share/X11/xkb` before starting Xlorie. The
   current service checks these base inputs and the existing vault before X11.
3. **The guest contract.** The service currently specifies `/home/julien`,
   `USER=julien` and guest UID:GID `10410:10410`. Fresh `/etc/passwd`, groups and
   ownership must agree with that contract or the service contract must be
   changed deliberately. The Android IME UID remains a separate dynamic value.
   The scripts directly need `python3`, `python3-websockets`,
   `python3-secretstorage`, `dbus-run-session`, `gnome-keyring` and its D-Bus
   activation files, `xfwm4`, `wmctrl`, `xkb-data`, fonts, coreutils and `awk`.
   The client's remaining library dependencies must come from its official
   package metadata. Git and workspace tools also need installation.
4. **Compatibility and rendering.** Today's rootfs inherits a compiled
   `libfake_userns.so` and `/etc/ld.so.preload`; no clean installer builds that
   state. This compatibility shim simulates isolation calls and is not the
   production isolation model. The tested Adreno driver at
   `/opt/foldgpt-gpu/mesa-26.2.2-foldgpt4` is also inherited. It needs its own
   verified component contract and source/provenance companion; the integration
   bundle does not silently select an untested driver.
5. **A new encrypted keyring.** Routine launches still require an existing vault
   and default GNOME collection. The new [first-install preparation components](keyring.md)
   generate and verify a fresh credential and collection; their integration in
   an Android install transaction remains unfinished. No account or existing
   collection belongs in a distributable rootfs.
6. **Official client and activation.** Obtain the unmodified OpenAI client from
   its official source under its applicable terms. Then install the four guest
   scripts, validate all required components and activate a completed rootfs
   before launching X11. The current migration omits `foldgpt_keyring.py`, while
   `deploy-session.py` and this bundle include it. There is no fresh-install UI
   or release-mode provisioning path yet; `run-as` is development tooling.
7. **Functional acceptance.** A successful first window does not establish local
   Codex execution, Remote, client/APK updates or sustained task continuity.
   Those remain separate device tests.

Do not distribute the existing private Debian image to fill these gaps. The next
bootstrap component should create a fresh guest from authenticated package
inputs and produce a validated install manifest, with OpenAI acquisition and
per-device keyring initialization handled separately.
