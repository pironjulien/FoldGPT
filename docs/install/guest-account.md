# Fresh guest account provisioning

`AndroidGuestAccountProvisioner.prepare(transaction)` implements the identity
step for an inactive Debian root already returned by `RootfsTransaction.prepare`.
The transaction lease must remain open through the whole installation. The
adapter derives UID and GID from the running Android process; its host-independent
engine takes those IDs explicitly for filesystem tests.

The component refuses NEW, PREPARING, ACTIVATING, ACTIVE and closed transactions.
It verifies the rootfs transaction receipt and root inode before touching the
guest. It never activates the root, starts PRoot or accesses the current runtime.
The caller should use the returned `GuestIdentity` when constructing launch
arguments, including `prootIds()`, user name and home.

The resulting guest account is `foldgpt`, with home `/home/foldgpt`, shell
`/bin/bash`, and the caller's non-root Android UID/GID. The home consists of real
owned directories and has mode 0700. `/etc/foldgpt-user` selects the account for
the shared `GuestIdentity.load` reader.

Account creation preserves Debian's existing password database scheme. When
`shadow` is present, the new passwd row uses `x` and the shadow row uses the
locked password marker `!`. When it is absent, the new passwd row uses `!`
directly. The same distinction applies to group/gshadow. This matches useradd's
choice of database without requiring an unconfined provisioning process. No
existing account is converted, and no password, skeleton, key or profile is
created or copied. The authenticated Debian archive currently has neither
shadow nor gshadow; that path has been tested with the actual archive.

Before the first account mutation, `/etc/foldgpt-account.v1` durably records the
root inode, requested identity and original/result hashes for all databases.
Absent shadow databases are recorded explicitly. Every replacement uses a new
file, file fsync, atomic rename and directory fsync. After a crash, the component
accepts only the exact original or resulting database versions. It refuses
conflicting names, IDs, memberships, homes, selectors, unexpected database
changes, symlinks and hardlinked metadata. The journal contains hashes rather
than copies of account database contents.

The coordinator must record completion of this identity step before running
later provisioning steps that can legitimately change system account databases.
After that point, use `GuestIdentity.load(root)` and validate the expected IDs;
do not replay this step's older whole-database hashes following apt changes.
The component does not prove the shell executable works, mount persistent user
data, configure DNS, install packages, provision the vault or validate the
complete runtime. Those remain separate coordinator steps. Guest IDs and a
locked Unix password are not an execution sandbox; Android remains the actual
kernel owner and protected execution requires its own verified enforcement.

Host evidence on 2026-09-06 includes eight JUnit tests under an unprivileged Linux
user, with 24 separate JVM process deaths across database schemes, followed by
successful recovery. An opt-in `GuestAccountRealArchiveCheck` also extracted the
authenticated Debian archive, provisioned its actual account files and home,
closed/reopened the rootfs transaction and verified unchanged identity with no
activation pointer. The Android adapter compiled against API 37. These results
were followed by real Android provisioning and ARM guest execution below.

The first Zygote run exposed Android's restrictive process umask: creation
attributes alone published group as 0600 instead of the required 0644. The
writer now sets and checks the exact staged-file mode before fsync/rename,
without changing the process umask. Recovery republishes only content already
bound to its journal when that earlier mode-filtered result is encountered.
The expanded host suite has 29 transaction/identity/account tests, including
24 actual JVM deaths and recovery of those mode-filtered results.

The same failed Android transaction then resumed successfully using its
existing extracted root and account journal. In the actual untrusted_app
Zygote context, getuid/getgid and getent in Debian agreed with the dynamically
derived Android identity. The guest ran bash with /home/foldgpt and its locked
account. The root remained PREPARED and no activation pointer was created.
The existing client root and account were not used by this test.
