# Fresh keyring preparation

The migrated FoldGPT runtime already loads an existing Android-encrypted
credential and unlocks the guest's default GNOME collection. The new components
here prepare the missing **fresh-install** path; they are not yet wired into an
Android installer or invoked by the running service.

`KeyringVault.prepareFreshPassword` refuses an existing `files/debian` rootfs or
pending migration import. Before rootfs activation, it generates 256 random bits,
encodes them without NUL, stores them with the existing Android Keystore AES-GCM
protection, and decrypts the committed result for verification. An interprocess
file lock serializes Keystore/file state, explicit file and directory syncs must
succeed before handoff, and cleanup failures erase any untransferred password.
Retrying an
interrupted preparation reuses the committed encrypted credential. A missing
Keystore key for an existing ciphertext remains an error, never a regeneration.
The caller owns and must erase the returned byte array after its private pipe
transfer. This API compiled with SDK 37 but its fresh-device behavior is untested.

`tools/install/initialize_keyring.py` consumes that password on stdin within the
new guest's private D-Bus session. It requires `--expected-daemon-pid` containing
the actual PID returned when the installer started its supervised GNOME daemon.
The caller must not simply discover whichever daemon currently owns the bus
name and pass that PID as its expectation. It must close the password pipe after
writing, hold the wider installation lease, and keep all clients out until the
transaction has completed.

Before sending any Secret Service request, the helper resolves its unique D-Bus
owner and checks `GetConnectionUnixProcessID` against that expected PID. It reads
`/proc/PID/environ`, requires the daemon's explicit `XDG_DATA_HOME`, and verifies
that this resolves to the same owned private directory inode as the helper's
directory. A wrong PID, other bus, different data directory, unreadable `/proc`
environment or changing bus owner is an error. Every subsequent SecretStorage
request, including encrypted-session creation and cleanup, is addressed to the
verified **unique owner**, so replacement of `org.freedesktop.secrets` cannot
redirect the transaction to another daemon. Secret Service RPCs share a monotonic
10-second deadline after binding; D-Bus identity queries have 5-second timeouts.

The helper holds an exclusive initialization lock and creates an immutable
`.foldgpt-keyring-intent.json` before creating a collection. The mode-0600 journal
contains a schema, a random 256-bit installation identifier, and the private
directory's device/inode identity; it contains **no password**. Its contents are
synced, then published using `renameat2(RENAME_NOREPLACE)`, and the directory is
synced before any collection creation. No hardlink or overwrite of an existing
journal is needed. Retries also sync the directory before proceeding, including
after an earlier publication whose directory sync failed. Unsupported operations
fail rather than falling back to a non-durable write. A helper killed before
publication can leave an unused private `.new` file; it is never adopted as a
journal and contains no credential.

Without a journal, **every existing persistent collection is refused**, even one
called `FoldGPT`. With a valid journal, only an empty collection list or the
single collection labelled `FoldGPT <installation identifier>` can continue.
An invalid, displaced or missing journal alongside an existing collection is a
recovery error, never an invitation to adopt or reset that collection. The label
stays associated with the journal across restarts; this preparatory API does not
support renaming it. The identifier is a transaction association under the
private installation boundary, not authentication against arbitrary same-UID
code with write access to that boundary.

GNOME's `CreateWithMasterPassword` uses encrypted Secret Service transport. The
helper then locks and unlocks only its journal's collection to verify the exact
credential before setting the default alias. An interruption after creation but
before alias setting resumes that same collection with the same password and
journal. An unrelated collection, multiple collections, wrong password or
unexpected alias aborts preparation. It never changes a master password or
deletes a collection.

The lock/unlock verification is intentionally restricted to installation before
any client runs: GNOME skips password checking on an already-unlocked collection.
Do not call this preparation tool on an active workspace. Routine launches keep
using `foldgpt_keyring.py`, which only unlocks the existing default collection.

The GNOME internal interface was audited at GNOME Keyring tag `46.1`, commit
`4e173494bf15795a1ebab6e2bbd9377fac456240`, in
`daemon/dbus/org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface.xml`,
`gkd-secret-service.c` and `gkd-secret-unlock.c`. It is explicitly unsupported
upstream; its presence and behavior must be revalidated on distribution updates.

## Real Linux checks

On WSL Ubuntu 24.04 with GNOME Keyring `46.1-2ubuntu0.2` and SecretStorage
`3.3.3-3`, run:

```sh
python3 tools/install/test_keyring_live.py
```

All twelve real-service checks passed on 6 September 2026:

- Creation with a stored fixture item; wrong-password refusal and recovery;
  recovery after removal of the default alias; refusal of an unrelated label.
- Refusal when the helper's data directory differs from the actual daemon's;
  refusal under a conflicting initialization lock.
- Restart of the daemon on the same bus: the original transaction's actual RPC
  remains addressed to the old unique owner and fails without changing the new
  daemon; a new correctly bound helper subsequently succeeds.
- Two simultaneous private buses/daemons: the nested wrong-bus check refuses a
  PID belonging to the other bus, and the outer check verifies its original
  collection was unchanged.
- A foreign collection called exactly `FoldGPT`, with no journal, is refused;
  its label, unlocked state, alias, item and encrypted files remain unchanged.
- Abrupt exit of the actual helper immediately after the real creation RPC,
  before its alias call; subsequent recovery after a complete daemon/bus restart
  preserves the same journal, collection path, password and fixture item.

The crash injection exists only in the test subprocess and does not fabricate a
daemon response or add a production pause/crash option. The harness uses temporary
private homes and separate daemon/bus sessions, with no host desktop bus, account,
phone or model call. These checks exercise real GNOME persistence across process
restarts; they do not simulate power loss or prove storage durability on Android.

Remaining gates are the global install transaction that coordinates the Android
vault and unactivated rootfs, the exact Debian guest version, and Android
Keystore generation/restart/update tests on the Fold. The guest lock only
serializes cooperating helper processes using this private directory; it does
not replace that wider lease or constrain arbitrary same-UID processes. PID and
`/proc` visibility, directory inode stability, `renameat2`, directory `fsync` and
the GNOME interface still need validation in the exact PRoot/Android environment.
No fresh install is declared ready from the Linux-only checks.
