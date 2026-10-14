# Verified copy of a legacy project

> Development evidence referenced by private paths below is not part of the public source release. Use the documented test recipes to verify your own build.

`relocate.py` inventories, then copies, a single project directory. It keeps
the original, refuses an existing destination and changes neither the
conversations, nor SQLite, nor the app settings. No network access is used.
Resuming the conversations is a separate step, described below.

## Usage

Python 3.9 or later on Linux/Android, as an ordinary user. Directory-descriptor
relative operations, `O_NOFOLLOW` and a genuine `renameat2(RENAME_NOREPLACE)`
from both libc and the filesystem are required. The tool refuses to run as
root. It does not emulate an unavailable primitive.

From the FoldGPT owner account, inventory a path **previously observed** in the
files of the old environment. The values below illustrate the syntax; they do
not prove that the `exemple` project exists.

```sh
python3 relocate.py inventory \
  --source /data/data/app.foldgpt/files/debian/home/foldgpt/Documents/Codex/exemple \
  --source-boundary /data/data/app.foldgpt/files/debian/home/foldgpt/Documents/Codex
```

Check the actual inventory, especially its paths, files and sizes. Note its
`inventorySha256` field. With the source at rest and the native root verified
beforehand, run:

```sh
python3 relocate.py copy \
  --source /data/data/app.foldgpt/files/debian/home/foldgpt/Documents/Codex/exemple \
  --source-boundary /data/data/app.foldgpt/files/debian/home/foldgpt/Documents/Codex \
  --destination-root /data/data/app.foldgpt/files/projects \
  --name exemple-importe \
  --expected-inventory-sha256 EMPREINTE_REELLE_DE_L_INVENTAIRE
```

The last argument must be a 64-character lowercase hexadecimal SHA-256
fingerprint taken from the verified inventory. Canonical absolute paths are
mandatory; `..` and `.` components, double separators and symbolic links in
ancestors are rejected. The destination name is a single component. The source
and destination trees must be distinct and disjoint.

The Java collection of 8 September canonicalized `/data/user/0/app.foldgpt` to
`/data/data/app.foldgpt`. These examples use the latter form; check the root
currently provided by the app before any operation. A symbolic alias is not
followed automatically by the copier.

The inventory includes every directory, sizes, SHA-256 fingerprints of files
and the observed metadata. Two full passes must agree. The copy uses a new
`.foldgpt-import-…` folder, re-verifies source and destination, then publishes
without replacement. The content and identity of the published folder are
verified once more before the success receipt.

Every result is JSON on stdout. The exit code is `0` only on success; a refused
operation returns `1`. The tool writes no automatic log: keep the inventory and
the receipt in the project's evidence, without mixing them up with the imported
files.

## Preservation and limits

- Regular files and empty directories are copied. Symbolic links, file hard
  links, special files and entries belonging to another owner or filesystem are
  rejected, with no silent omission.
- Bytes and the presence of executable bits are preserved. The requested modes
  are private (`0600` or `0700` for files, `0700` for folders), subject to the
  umask. Owner, group, timestamps, extended attributes and ACLs are not
  reproduced. A project that depends on them needs analysis before import.
- A `.jsonl` among the files is copied byte for byte like any other data. The
  tool rewrites no path in messages or configuration. The project's operational
  absolute paths may need a separate fix after inspection; historical paths stay
  historical.
- The repeated checks detect the changes they observe. They do not freeze
  another process of the same user and do not guarantee that the source will
  stay unchanged after the check. Stop concurrent writes during the migration.
  This tool is not an isolation boundary against a hostile process of the same
  user.
- The source is never deleted. An error after the intermediate folder is created
  keeps it. `retainedStage` gives the last known path; `published: true` states
  that the rename has already succeeded, even if a later verification or
  `fsync` fails. In that case the path is that of the published destination.
  `errno` keeps the native code when there is one. Another process substituting
  the path can make this last path stale: check identities before any
  intervention. No cleanup or destructive rollback is automatic.
- A new attempt refuses an existing destination, even an identical one.
  Resuming an interrupted migration requires examining the receipt and the
  actual files; do not create a second copy and modify the conversations
  blindly.

## Reconnecting to the existing conversation

There are two distinct cases. A legacy project `/home/foldgpt/Documents/Codex/…`
needs the actual inventory and copy of its folder under `files/debian`. An
**already native** project registered under `/data/user/0/app.foldgpt/files/projects/…`
may refer to the same directory as `/data/data/app.foldgpt/files/projects/…`.
Check their canonicalization and `(device, inode)` identity in the current
authority, then inventory the canonical path. If the identity matches, copy or
move nothing: only reconcile the project and thread references through the APIs
below. Similar-looking strings do not prove this identity. A missing, distinct
or refused directory requires stopping this reconciliation, without widening
the admitted root.

References read: canonical tree `work/worktrees/FoldgptEngine`, base
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a` (`rust-v0.153.4`) with the FoldGPT
adaptations. The calls below belong to the existing app-server protocol; they
are not `relocate.py` commands. No access to the UI transport is assumed to
have been discovered.

1. Read `thread/read` and `project/read`/`project/list` through the existing
   transport to obtain the actual IDs, associations and roots. Keep the earlier
   evidence, the rollout prefix and the project at rest. Do not infer a
   `projectId` from the displayed title.
2. For a real legacy project, copy the observed files with the tool; for the
   alias of an already native project, keep its folder after proving identity.
   Check that the existing native authority admits the canonical path. Do not
   widen `discoveryRoot` or the permissions.
3. Perform a cold resume of the same `threadId` with `thread/resume` and the
   verified `cwd`. Check the returned cwd; an already loaded thread may ignore
   this override. Do not use the `history`/`path` options or create a fork.
4. Send `thread/settings/update` with the same `threadId` and the new `cwd`.
   Wait for `thread/settings/updated`, then check persistence; the RPC
   acknowledgement alone does not prove that the asynchronous change was
   applied. Inventory any additional runtime roots separately.
5. For a genuine, already identified app-server project, `project/update`
   accepts a new `roots` list under the **same** `projectId`. Omit `name` and
   `metadata` to preserve them. The list replaces all roots: keep the other
   observed roots and retarget only those actually migrated. This call alone
   does not change the conversations' cwd. The server returns the updated
   project and emits `project/changed` if a change occurred.
6. Re-read the project, close the conversation normally, then resume it without
   override. Check the same `threadId`, preserved history, new cwd and real
   access to a file. Also check the editor and the configuration reads of the
   usual interface. Additional UI preferences must be identified explicitly
   before modification.

Example `params` bodies, to be filled with verified values:

```json
{"threadId":"ID_EXISTANT","cwd":"/data/data/app.foldgpt/files/projects/exemple-importe"}
```

This same body works for `thread/resume` and `thread/settings/update`, with
distinct RPC IDs and a separate verification for each operation.

```json
{"projectId":"ID_PROJET_OBSERVE","roots":[{"path":"/data/data/app.foldgpt/files/projects/exemple-importe"}]}
```

This `project/update` example is only correct for a project with that single
root. `ProjectUpdateParams` offers no expected version or compare-and-swap.
A read followed by a write is therefore not atomic against another client:
ensure there is no concurrent modification and re-read immediately before and
after. Project and thread updates are separate operations; an interruption
between them must remain reported as an incomplete migration.

Source: `app-server-protocol/src/protocol/v2/project.rs` (`ProjectUpdateParams`),
`app-server/src/request_processors/projects.rs` (`project_update`), and the
repair study (`../../../docs/research/legacy-path-repair-design-20260908.md`)
for the resume and persistence mechanisms.

## Verification

The tests create fixtures only under an explicit project root and use real
filesystem operations, including no-replace renaming. They check bytes, links,
collisions, injected concurrent writes and descriptor closing.

```sh
PYTHONDONTWRITEBYTECODE=1 \
FOLDGPT_LEGACY_TEST_ROOT=/chemin/absolu/FoldGPT/work/legacy-projects-tests \
python3 /chemin/absolu/FoldGPT/tools/runtime/legacy-projects/test_relocate.py
```

The test folder must already exist, be inside the project and be on a Linux
filesystem that offers the required primitives. WSL `/mnt/c` (DrvFS) rejected
`renameat2(NOREPLACE)` with `EINVAL` and `mkfifo` with `EOPNOTSUPP` in the
first attempt: these errors are not turned into success. Linux PC qualification
is not Android qualification; the latter remains separate from proving that a
real conversation resumes through the interface.

On 8 September 2026, **20 tests passed** under WSL Ubuntu 24.04, uid 1000, on a
64 MiB ext4 image created in `work/legacy-projects-tests`, mounted only inside
that same folder and then unmounted. Result, command and source fingerprints:
Linux proof (`../../../recovery/verification/legacy-projects-20260908/linux-tests.json`)
and full output (`../../../recovery/verification/legacy-projects-20260908/linux-tests.log`).
The originals stay under `work/legacy-projects-tests`. These tests include
native errors, sync failure after publication and a concurrent modification of
the published content. No phone test has been run with this tool at this stage.
