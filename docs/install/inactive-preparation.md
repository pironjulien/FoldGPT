# Inactive base, account and keyring coordinator

`AndroidInactivePreparation.prepare` is a concrete bounded Android entry point.
It authenticates the two supplied Python sources, opens and holds the existing
rootfs transaction lease, prepares the Debian base, provisions or validates its
real account, commits or reopens the Android vault, and starts PRoot to prepare
and verify the actual GNOME collection. It never activates the root or starts
the display, official client or a model request. Its returned `Result` is
evidence of this inactive preparation step, not a complete-installation result.

The parameters are the Android Context, trusted `RootfsExtractor.Spec`, archive
source, and paths plus trusted SHA-256 descriptors for `initialize_keyring.py`
and `supervise_keyring.py`. The coordinator copies exactly these verified Python
bytes into its inactive root. Native components come from the running app's
Android-verified installed APK. Their combined descriptor is bound to the
coordinator journal so that a different APK/runtime revision cannot silently
resume a previous preparation.

`InactivePreparationJournal` lives beside the existing rootfs transaction
journal and does not modify it. It binds the prepared root inode, authenticated
base descriptor, both script hashes, native descriptor, Android UID/GID and
vault-parent inode. Its random installation identity and four ordered steps
are durable through file fsync, atomic rename and directory fsync. It contains
only identifiers and hashes. The completed vault step additionally binds the
exact encrypted credential bytes; the completed collection step binds the
GNOME helper's immutable journal, installation identifier, data-directory inode
and collection path. Every retry validates actual files and reopens the real
private daemon to verify the same credential/collection. No state flag alone is
accepted as collection verification.

The first coordinator invocation refuses any existing ciphertext, pending
credential import or guest collection data without its own intent. A lost vault
after a collection attempt is an explicit recovery error, never regeneration.
After a crash between ciphertext commit and the next journal write, the existing
`KeyringVault.prepareFreshPassword` reopens those exact encrypted bytes. Existing
`files/debian` remains excluded by the fresh transaction and vault APIs.

`SecretPipeProcess` owns a bounded child process and the credential byte array.
Its original anonymous stdin pipe reaches the production Python supervisor.
The supervisor gives `/dev/null` to the bus and GNOME children and lets the
unchanged initializer consume that original pipe in its own process. The Java
writer closes its pipe and erases its array; the initializer performs its
existing byte-array erasure. Credentials never enter arguments, environment,
logs or plaintext files. Failed child output is not copied into exception text.
Output, waiting, cancellation and process/pipe cleanup are bounded.

`supervise_keyring.py` starts a new D-Bus session daemon at a fresh private Unix
socket and directly supervises a foreground GNOME daemon. It takes the expected
PID from the child it started, then retains the initializer's unique-owner,
`GetConnectionUnixProcessID`, `/proc/PID/environ` and data-directory inode checks.
It does not inherit another desktop bus, display, SSH socket or profile. Linux
parent-death signals kill its owned daemons if the supervisor dies abruptly.
The daemon and bus stop before guest persistence is synchronized and a bounded
nonsecret receipt is emitted. Android checks that receipt against the actual
guest intent file and the host-side inode, without any PID/inode-check bypass.

Integration still required by the parent installer:

- Include both canonical Python sources and their authenticated descriptors in
  the installer inputs/assets; the authenticated guest bundle now includes both.
- Invoke this entry point from the installation worker. It intentionally has no
  activity, service trigger, APK installation hook or activation callback.
- Keep runtime starts and future update operations under the global installation
  lease contract. This component cannot make an unrelated service obey that lease.
- For a device probe beside the current runtime, isolate **files, cache and
  noBackup together** with a ContextWrapper. No separate Keystore alias is
  required: AES-GCM can protect an independent ciphertext in the isolated vault
  while keeping the existing key and production ciphertext intact. Probe cleanup
  must never delete the shared Keystore alias. This coordinator does not perform
  any probe cleanup or touch the production vault when passed isolated paths.
- Extend the Android validation below to complete installer lifecycle and
  cancellation. The host tests use Ubuntu's GNOME 46.1; their evidence remains
  separate from the device's GNOME 48.0-1.

Host evidence includes journal recovery across eight real JVM process deaths,
anonymous-pipe transfer/erasure, bounded timeout and output/refusal tests, and the
actual Java pipe -> production supervisor -> private D-Bus/GNOME path across a
complete daemon/bus restart. Separate real-service checks cover wrong-password
refusal/recovery, unsafe paths, occupied runtime sockets and abrupt supervisor
death. The full Android sources compile against API 37. No Android Keystore is
simulated by the host harness.

## Android recovery validation, 2026-09-06

The debug-only `InactivePreparationProbeService`, protected by `DUMP` and
running in its own Zygote process, reused the previously prepared root with
isolated files/cache/noBackup. Its initial failure exposed a real PRoot socket
translation limit: GNOME's physical control pathname was 115 bytes, exceeding
Linux's 107-byte pathname maximum. The coordinator now uses a shorter per-run
cache prefix and checks the full translated control path before launching.
A second attempt reached the real collection but exposed a Java receipt check
expecting six fields when the supervisor emits five. The check now matches the
exact five-field protocol and continues to reject unknown fields.

After those fixes, run `24e83321-9fb3-4d96-834c-3e2c4ee89688` passed two complete
preparations in the same invocation, including two fresh private daemon/bus
sessions. Root, account, installation identity, Android ciphertext, collection
identity and coordinator journal remained identical; the archive was never
reopened and activation was never attempted. The original failed stage and
vault were retained throughout. The installed debug APK hash matched its local
build. After adding fixed process-failure diagnostics, run
`866bfff3-e619-4b4d-a482-1afa7f5529fb` repeated this success with the same vault.
Forty host tests and both APK builds/content-separation checks pass.
This verifies inactive Android/PRoot/Keystore/GNOME preparation and its
recovery, not the complete installer or a binary release.

Persistent user-data bindings, integration/graphics installation, the official
client, protected local execution and complete activation validation remain
separate installation requirements. The inactive root and its private home must
be retained until that complete data/activation contract is implemented.
