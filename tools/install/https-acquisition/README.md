# Trusted HTTPS artifact acquisition

`TrustedHttpsArtifact` downloads an independently authenticated release input
into the application's private cache. `AndroidTrustedHttpsArtifact` connects it
to the source URL already declared by `AndroidInactiveClientInstaller.Descriptor`.
No new official download endpoint is guessed or duplicated.

This component acquires bytes only. It does not install a package, validate a
complete runtime, change `PREPARED`, publish `files/debian`, start Android services
or alter a profile. Existing v3 preparation continues to own its verification
and journals. A successful download cannot serve as `ActivationValidator`.

## Trust, cache and recovery

The required descriptor contains an absolute HTTPS URL, exact positive size and
SHA-256 obtained from an independently trusted release source. The downloader
never treats the response's metadata or a checksum from that same download as
authentication. The complete URL, size and digest determine the cache entry key;
different URLs retain different bindings even when their bytes match.

HTTPS uses `HttpsURLConnection` with the platform's normal trust store and
hostname verification. Production code has no custom trust-manager, certificate
acceptance or hostname-verifier hook. Redirects are bounded, cycle checked and
restricted to HTTPS without URL credentials or fragments. Content encoding must
be absent or `identity`, so the pinned digest refers to the actual artifact bytes.
Connection, read and overall deadlines are explicit caller inputs. Cancellation
disconnects the current connection; read timeouts are capped by the remaining
overall deadline. Java thread interruption is also honored.

Each descriptor owns a 0700 directory below `cache/foldgpt-acquisition`. Its
0600 lease file is locked across the entire acquisition and publication using
a real OS file lock. Concurrent threads or processes acquiring the same
descriptor fail explicitly while that lease is held; different descriptor
entries are independent. Existing cache files must be regular, owned, 0600 and
single-link. Directory aliases, hardlinked data and unknown entries are refused.
The private-cache contract excludes hostile concurrent native code with the
same UID; this is not an isolation claim against that authority.

Android's existing managed cache can legitimately have mode 2771 and a cache
GID. `mkdir(0700)` below that setgid directory can create mode 2700; Java's
`getPosixFilePermissions` does not expose the inherited setgid bit. After a
successful new-directory creation only, the Android storage adapter opens the
new path without following links, checks the open directory's UID and expected
device/inode, applies `fchmod(fd, 0700)`, verifies the full resulting mode and
unchanged identity/GID, and synchronizes it. The existing Android cache parent
is not chmod-ed or chown-ed. Existing component cache directories are never
normalized: a full mode other than 0700 is refused unchanged. Full file modes
must similarly be exactly 0600, including the absence of special bits.

The exact descriptor is forced to disk before any partial data is created.
After an interrupted transfer, the next invocation derives its range offset
from the actual private partial file, requests `Range: bytes=N-`, and accepts a
206 response only with the exact requested start, final offset and total size.
A normal 200 response explicitly restarts the partial from zero. An ETag or
range response never replaces final SHA-256 verification; a source changing
between transfers can only succeed if the resulting complete artifact matches
the independently trusted descriptor.

Network interruption preserves the current partial. Detected excess body bytes
or a wrong final digest discard only that owned partial and report failure.
Published artifacts are rehashed when reused; corruption is reported without
silently replacing them. A published artifact coexisting with a competing partial
is an explicit inconsistent cache state.

Publication follows complete size/SHA-256 verification, file fsync, an inode
check and an absent-target check under the same lease. The partial is atomically
renamed, then the containing directory is synchronized. Recovery after a crash
before the rename rehashes and synchronizes the complete partial; recovery after
the rename revalidates the actual final artifact and synchronizes its directory.
A target appearing while the lease is held is refused and preserved.

## Android integration point

The new adapter is:

```java
TrustedHttpsArtifact.Result acquired = AndroidTrustedHttpsArtifact.acquireClient(
    context,
    trustedClientDescriptor,
    acquisitionDeadlines,
    cancellation,
    progress
);
```

It reads `client.json().getString("sourceUrl")` in the existing install package,
and uses `client.bytes` and `client.sha256` unchanged. Its native cache adapter
uses ordinary app-UID `lstat` and directory `fsync`; no Android security setting
changes are involved.

Supply `acquired.file` as `packageSource` when constructing
`AndroidInactivePreparation.ClientInput`, then call the existing v3
`AndroidInactivePreparation.prepare(...)` with the authenticated base, helpers
and integration inputs. Acquisition belongs before that coordinator call; it
does not independently open or mutate a rootfs transaction. The existing
source-free client recovery path remains available when preparation already
has its verified installed package ledger. The coordinator still performs
its normal package verification rather than trusting a cache marker.

Release-descriptor discovery, release signing, input selection and the
first-launch acquisition UI remain separate work. This component requires the
trusted descriptor; it cannot manufacture one from a mutable `latest` URL.

## Actual tests and limits of the evidence

From WSL/Linux:

```bash
cd /mnt/c/Dev/FoldGPT
bash tools/install/https-acquisition/run-jvm-tests.sh
```

The runner verifies the existing JUnit dependencies, snapshots the new sources,
generates two ephemeral test server certificates and a separate test truststore,
then runs a real `HttpsServer` and real downloads as UID/GID 65534. Only the test
JVM receives that truststore. One server certificate is trusted for
`DNS:localhost`; the other is untrusted. Tests require actual TLS handshake
failures for the untrusted chain and incorrect hostname. No public Internet
download is part of the test suite.

The same runner compiles the actual new Android adapter and its referenced
project classes against the SDK selected by `android/local.properties` and
`compileSdk`. `FOLDGPT_ANDROID_JAR` can explicitly identify another configured
SDK jar. This is Android source compilation, not Android execution.

Verified snapshot on 2026-09-06:
`downloads/install/https-acquisition/foldgpt-https-java-dUfNMcSD`.
**19 tests pass** as UID/GID 65534 on real Linux files and HTTPS sockets, including:

- Exact binary download, private publication, cached rehash and corruption refusal.
- Real connection truncation and range recovery, ignored range restart and invalid range refusal.
- Wrong SHA-256, excessive chunked bytes and unsupported content encoding.
- Trusted HTTPS redirects, downgrade refusal and redirect loops.
- Actual untrusted-certificate and hostname failures with normal TLS verification.
- Cancellation, thread interruption and an overall deadline shorter than the configured read timeout.
- Concurrent threads and a separate JVM competing for the same OS lease.
- A child JVM forcibly killed after writing actual HTTPS bytes, followed by range recovery.
- Interrupted descriptor publication, interruption after hashing and after atomic rename.
- Publication collision preservation, directory aliases, hardlinked files and unknown cache entries.
- Actual kernel setgid inheritance from a 2771 parent: ordinary mkdir produces
  2700, while the component's new directories finish at exactly 0700 and its
  files at 0600; the parent UID/GID, device/inode and full mode remain unchanged.
- Existing 2700 cache/descriptor directories and a 2600 published file are
  refused and preserved, without another network request or a permission repair.

`SHA256SUMS`, `test-identity.txt`, `junit-result.txt`, `android-compile.txt` and
`android-sdk-sha256.txt` retain the source, execution and compilation evidence.
These tests perform no phone download, Android activation, official-client
package installation or new runtime qualification. The first separate Android
probe failed before networking because of inherited directory setgid; its
unchanged evidence is in `downloads/install/https-acquisition/android-cb8b011a`.
The following Android runs supersede that compilation-only status for this
acquisition component.

## Actual Android acquisition, 6 September 2026

The corrected adapter first created its private cache with mode 0700, retaining
the Android parent at 2771. The download then correctly refused the old pinned
26.901.41600 descriptor because the official `latest` channel served a different
size. That observed failure is independently preserved in
`downloads/install/https-acquisition/android-1cea3ef5/collected-size-refusal`.

The new 26.901.51231 input was authenticated independently of `latest` using the
previously qualified official key fingerprint
`3BFA0E4AE8B8CC16A2D9BA684A3B4A566C4660E4`, a newly downloaded signed `InRelease`,
its exact ARM64 `Packages` digest/size, and the versioned package. The package's
`_gpgorigin` signature also verifies against that key. Full provenance and the
unchanged package inventory verifier's two passes are retained in
`downloads/install/client-current-d7a90fbfe5bc4316b8101284db9d28db/PROVENANCE.md`.
The authenticated descriptor uses 388605714 package bytes, SHA-256
`02a2f5c6cb69509c62abcbdd13c76b139cdb2ca9edde7537239ddde024077ea0`,
1365708800 exact data tar bytes and 7360 members. It changes only the fixed
acquisition probe, not the installed client or earlier inactive v3 input.

That exact package was downloaded on the Fold under the native app UID, then
rehashed and reused from the same inode. The second acquisition ran under a
worker-only StrictMode network-death guard and passed. Private directories are
0700, files 0600 and the managed parent retains its identity, owner and full
mode. The completed service has no remaining acquisition worker/wake lock.

Independent collection:
`downloads/install/https-acquisition/android-1a54dd8c/collected-pass-20260906`.

| Evidence | SHA-256 |
| --- | --- |
| Tested debug APK | `1a54dd8cbfdeb329d575ab130b65dbef550fb65067c1a3912244b749c856db5b` |
| Android report | `2ae6259b7128b801082328fded614e6c254acab69f3f40c9576cbad31f693a7f` |
| Independent verification | `34a55d6b2003e245c03829e4872233c073bbcb230769938aaf9bbca66a7aa610` |
| Executed collector | `7eb2e0da2e79652584e5617944020e6c4624efb66a4befe45bf7d8089fb890c5` |

The collector rechecks the installed APK, physical package bytes/hash and inode,
full cache modes, descriptor, worker completion and stable evidence before and
after collection. Java build-source snapshots are retained separately; this
does not establish source-to-DEX equivalence. Shared-UID traffic counters do not
count HTTP requests. No installation, activation, account, keyring access or
client-update qualification occurred. The fresh signed index has no Valid-Until;
this provenance check alone does not establish anti-rollback protection.
