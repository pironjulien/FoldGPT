# Installation coordinator and update boundaries

This is the implementation contract for joining the existing installation
components. It is a design note, not a declaration that the fresh installer
already works. The running development runtime with foldgpt5 and the inactive
Android v2 and v3 preparations are distinct states. No step below authorizes
replacing the existing private `files/debian`.

## Product behavior and component ownership

The intended user flow is: install FoldGPT through Android's normal package
installer, open it on the inner display, let its private runtime prepare, then
sign into the unmodified official client through its own UI. Any Android
installation consent and OpenAI account authentication remain normal product
steps. A generated guest-keyring credential is an internal installation secret,
so a GNOME password dialog must not appear during successful preparation or
routine launches.

FoldGPT owns the Android UI, lifecycle service, private workspace, bootstrap,
display engine and integration scripts. Debian owns its base packages and
package metadata. The official client owns its application files, authentication
and supported update behavior. The installer must not rewrite those client
files, bundle an authenticated profile, or substitute an unofficial update
source. A runtime compatibility layer that simulates Chromium isolation is not
a production security boundary even if packaged client files remain unchanged.

The existing fresh-install transaction is the appropriate base for the
coordinator because it already provides authenticated extraction, exclusive
publication and recovery. A second shell installer with separate readiness
markers would create competing authorities over the same root. Keep all actual
readiness decisions in one Android coordinator and use the guest tools only
for their bounded provisioning work.

The current client-enabled `AndroidInactivePreparation.prepare(..., ClientInput)`
joins the actual package installer after guest-account provisioning and before
vault/collection preparation under that same lease. Its v2 journal binds the
client descriptor and helper hashes, records the verified package report, and
requires real package revalidation on every retry. The separately named
`prepareKeyringOnly` diagnostic preserves the earlier v1 scope; the coordinator
refuses implicit conversion between scopes. The v2 combined path now passes on
the actual Fold twice, including source-free recovery with the same account,
client, vault and collection. See [the device evidence](combined-preparation-probe.md).
The newer v3 overload adds authenticated GPU and guest-integration preparation
between account and client setup. Its Android combined probe now passes two
complete calls after recovering a real shared-state permission conflict, with
the same root, integration report, client and vault. Independent native
collection also matches all 345 manifest entries, their recorded identities and
the absence of activation. See
[the v3 scope and evidence](inactive-native-integration.md).
Input acquisition, complete runtime validation, activation and the first-launch
flow remain unfinished. Neither inactive preparation result establishes those
later steps.

## One durable installation identity

The coordinator acquires the global installation lease before reading or
changing installation state and keeps it until provisioning completes or fails.
Fresh preparation refuses the current migration/existing runtime. It must also
serialize against service starts and update operations; a Java transaction
object alone cannot stop an unrelated service from bypassing this contract.

Persist a schema version, random installation identifier, authenticated
component descriptors, staged-root inode identity and completed provisioning
steps in an app-private durable journal. Journal/checksum data contains no
credential. Each completed step must have its own observable evidence; a state
flag alone is not enough to adopt a directory, ciphertext or GNOME collection.
Keep the existing extraction journal as the rootfs transaction's authority.
Any higher-level journal must bind to that transaction and must never invent
`ACTIVE` by editing its records.

The Android encrypted credential and guest collection are stored separately,
so no ordinary filesystem rename can atomically commit both with Keystore.
Use recoverable, identity-bound steps: durable encrypted credential first,
creation of the matching journal-bound guest collection second, verification
of both third, runtime publication last. After an interruption, reuse the
exact existing ciphertext and collection. Do not regenerate a password to
make a mismatching or inaccessible collection appear to work.

## Preparation sequence

| Step | Actual work | Completion evidence |
| --- | --- | --- |
| Accept components | Authenticate versioned Debian, native libraries, display/graphics and integration inputs against a trusted descriptor. | Exact hashes, sizes, architectures and required API/library versions. |
| Prepare Debian | Run `RootfsTransaction.prepare` in its private stage. | `PREPARED`, durable receipt, exact root inode; no activation pointer. |
| Provision identity and bindings | Establish the guest account/home, DNS bridge and runtime path contract. | `/etc/passwd`/groups/home agree with the launch arguments; required files and runtime bindings resolve in the real guest. |
| Install integration | Apply verified scripts and selected tested driver/runtime revision only to the inactive root. | Per-file hashes, permissions and dependency checks; required XKB data exists before display startup. |
| Obtain the official client | Fetch the official package using its documented acquisition channel and terms, then install it intact with its declared dependencies. | Package origin/provenance, architecture, package metadata, exact installed version and unmodified packaged files. |
| Prepare vault | Invoke `KeyringVault.prepareFreshPassword` under the same installation lease. | Newly generated or resumed Android-encrypted credential decrypts exactly; files and directory syncs succeed. |
| Prepare guest collection | Start a supervised private guest bus and GNOME daemon, transfer the credential through a private pipe, and invoke the existing helper. | Expected daemon PID/unique bus owner/data-directory inode match; the exact journal-bound collection passes lock/unlock verification. |
| Validate complete runtime | Evaluate the actual staged runtime and all required integrations. | Required executables, dependencies, permissions, keyring association and kernel/runtime checks pass with no simulated isolation success. |
| Publish | Call `RootfsTransaction.activate` with the real validator. | Atomic no-clobber pointer publication and durable `ACTIVE` journal. |
| Start and sign in | Start the normal runtime/display service and official client. | Actual desktop connection; user signs into OpenAI using the official flow. |

The existing keyring preparation verifies the guest collection before any
client starts. OpenAI sign-in happens afterwards and is not an offline
installation prerequisite. Distinguish guest account provisioning from an
OpenAI account session when implementing the validator.

The official acquisition/update mechanism must be verified for the package
version shipped to the user. Existing local package inspection documents a
dependency set; it does not by itself prove that a signed OpenAI APT repository,
an automatic updater or redistribution rights exist. Do not hardcode a guessed
download endpoint, treat a checksum from an untrusted mirror as authentication,
or ship the proprietary package inside the FoldGPT source distribution.

## Android and guest filesystem semantics

Derive Android UID/GID, private paths and device display state at runtime.
Do not distribute the development device's UID `10412`, guest UID `10410`,
personal home name or cache paths as a universal installation configuration.
Any guest identity chosen must agree with PRoot's mapping and the actual
Android ownership contract; PRoot's presentation of ownership does not grant
kernel privileges.

Archive ownership is not applied with `chown`: extracted objects belong to
the app UID. Preserve actual modes, contents and guest symlinks. Absolute
guest symlink targets are guest paths; host-side tools must use no-follow
inspection instead of resolving them against Android's root. Recovery may
modify permissions only on its own abandoned inactive stage so it can reclaim
that stage. It must never walk or clean a live root, user-data tree or symlink
target outside its owned staging boundary.

The first Android probe exposed a platform difference at symlink mtime:
Java's `BasicFileAttributeView.setTimes(..., NOFOLLOW_LINKS)` failed at `root/bin`.
The native no-follow timestamp operation now passes actual Android extraction;
the independent inventory checked every logical member and physical entry.
The combined client/vault run also prepares and recovers that authenticated base.
These extraction results do not establish the complete runtime's readiness.

The production activation flush expects the root to be readable/traversable
by the app UID. If future provisioning introduces inaccessible content, fail
with the actual path/operation and extend the durability contract deliberately;
do not silently weaken permissions, skip its synchronization or replace a
failed result with an activation marker.

## Credential handling and unattended startup

Use the nonexportable Android Keystore key to protect the generated GNOME
credential. Transfer plaintext only through the owned byte array and private
pipe required by the helper, close that pipe, and erase the caller's byte array
after handoff. Do not place the secret in argv, environment, logs, persistent
plaintext files, a default empty-password collection or the public rootfs.

The helper already verifies the expected daemon PID, unique D-Bus owner,
explicit `XDG_DATA_HOME` and its own collection journal. Preserve these checks
when wiring it into PRoot. If Android `/proc` visibility or PID translation
prevents them, solve and test the real identity handoff rather than disabling
the check. GNOME's internal collection-creation interface needs compatibility
validation against the exact installed Debian package, not only the Ubuntu
version used by the host harness.

Routine launches unlock the existing verified collection. They never run
first-install creation against an active workspace. A lost Keystore key or
inaccessible ciphertext must be an explicit recovery state; silently starting
an empty collection would discard access to the user's saved authentication.
Android-unlocked launch requirements and background task continuity must remain
consistent with the chosen Keystore protection policy.

## Updates and user-data preservation

Track three update identities independently: the signed Android APK, the
FoldGPT/Debian runtime components, and the official client. Updating one does
not prove the others remain compatible. APK updates require the same signing
identity and preserve app-private data and Keystore aliases. Uninstall/reinstall
is not the normal update path because Android may delete both.

Before the first distributable install, define a durable user-data location
independent of replaceable runtime revisions, with explicit guest bindings for
the home, workspaces and client profile. Bindings must be reflected in real
filesystem policy enforcement. The current prototype stores data inside its
rootfs; moving that existing data requires a separate verified migration.
Do not infer that the fresh transaction's stage directory can later be deleted
without inspecting where live user data resides.

For runtime updates, prepare a new authenticated revision under the update
lease, verify it against the current data format, and switch only at a safe
runtime boundary. A rollback of executables must not overwrite newer user
files or pretend to reverse a client/profile schema migration. Until a real
versioned update transaction exists, the fresh installer must keep refusing an
existing `files/debian` instead of being reused as an updater.

Official client updates must retain their supported mechanism and packaged
files. Check the new client against the integration points that FoldGPT relies
on, including the display backend, keyboard bridge, local execution interface
and GNOME collection behavior. A client version that starts is not sufficient
proof of protected command execution or background continuity.

## Acceptance and publication evidence

Before calling this an autonomous installation, demonstrate a first run in an
empty dedicated application data area with no access to a preconfigured Termux
image. Preserve the current development installation until that proof is
complete. Record actual recovery after interrupted preparation and after
restart, no GNOME password dialog, official sign-in, a protected command that
creates a real file, denied protected accesses, a real fold/lock with an active
task, and a client/APK update that retains the same account and workspace.

Source publication can describe reviewed components and separately dated
device results. A binary release additionally needs exact component/source
inventories, corresponding sources and notices, a retained APK signing identity,
and an authenticated update channel. Do not label source publication as a
one-click installer, a validated beta, guaranteed warranty compatibility or
120 FPS merely because the renderer uses Adreno.

The dated evidence available on 6 September 2026 establishes these separate
milestones:

- [foldgpt5 on the existing runtime](../verification-gpu-renderpasses-2026-09-06.md):
  24 independent GLES pixel cases, Vulkan/GLX probes and all 20 settings sections
  pass, including real repeated Plugins/Browser taps. This fixes the reproduced
  menu corruption without certifying every GPU operation or application FPS.
- [Integrated browser on the Fold](../../tools/browser/README.md): two real
  Codex turns open/read a page, click to IANA and navigate back. File transfers,
  authentication, local development pages and PiP remain unverified.
- [Native filesystem RPC on Android](../../tools/executor/native-files-android-rpc.md):
  34 actual responses and 12 grouped checks pass under the real Zygote context,
  with independent file/inode/refusal and executable-hash verification. The
  Android/Bionic supervisor has no PRoot or isolation-shim mappings. This debug
  fixture does not establish live Desktop routing, arbitrary managed processes
  or a normal protected model task.
- [Private guest bridge](../../tools/executor/private-exec-android.md): a separate
  GNU bridge under PRoot reaches the native Android/Bionic broker over a private
  Unix socket. Its latest 53 responses across two sessions include directory
  listing/walking, copy/remove, protected mutation refusals, block reads above
  the whole-file limit and real descriptor/lease release. The full transcript,
  physical bytes, packaged sources, native libraries and tested APK match the
  independent collector's checks.
  App-UID authentication does not identify a particular program within that UID.
  Production task/policy routing and the process executor remain unfinished.
- [Inactive Android v2 preparation](combined-preparation-probe.md): two calls
  retain the same authenticated root, guest account, intact client, vault and
  collection. No activation or desktop launch occurs. The [v3 route](inactive-native-integration.md)
  has its own successful inactive Android preparation/recovery plus independent
  checks of 29 integration and 316 XKB entries. The two calls and original
  collection used APK `f6f5...`; inspection under `b47b...` later verified the
  same retained stage/report without rerunning preparation. The v3 report records
  the full APK hashes and each collection's scope.

The official workspace-runtime diagnostic remains unresolved: the recorded
configuration has no Linux ARM64 entry and manifest retrieval returns HTTP 404.
The Bionic interpreter above serves the native supervisor fixture; it does not
repair that upstream dependency supply.

Use these scoped reports when reconciling older build notes and publication
text. Historical host-only results remain historical evidence even when a later
increment passes on Android. In particular, routine unlocking on the migrated
runtime, new collection preparation in the inactive v2/v3 stages and a first launch
from a fully activated fresh installation are three different acceptance claims.
