# Native filesystem transport on Android

`native_files_server.py` joins the reviewed exec-server stdio transport to
`NativeFilesBackend`. Its supervisor supplies an exclusively owned workspace,
guest mapping and trusted native helper. The five file operations in the
original fixture retain their complete portable policies. The later private
bridge increment adds four methods, as recorded below. Process and streaming requests are
refused. This endpoint is not the live Desktop environment or a complete executor.

`native_files_rpc_fixture.py` calls that real endpoint in a separate process over
pipes. It independently checks bytes, inodes and metadata; write/read/deny/write
decisions on one file; protected metadata and explicit exceptions; Unicode
directories and binary data; and missing-ancestor, malformed, alias and unsupported
process refusals. Policy denials require the admission error code, distinct from
internal errors and NotFound. Transcripts retain the actual sent fixture contexts
and responses. A fresh backend reacquires the real workspace lease after server
exit and pipe EOF. Timeout kills the fixture group and remains a failure.

Run `bash tools/executor/native-files-rpc-build.sh` on Linux. The 6 September 2026
host run passes 34 actual responses and 12 grouped checks in
`downloads/native-files-rpc/foldgpt-files-rpc-build-eNPRIXQ3`. Native helper SHA-256:
`04b600c5ad5b4e7caacaec9cbf88ec067dfc210d251a68b5fb67a6bdd81e040d`.
Both parent and server observations show UID 65534, zero effective/permitted
capabilities, no tracer and no PRoot/shim maps. This is host evidence.

## APK-owned device fixture

The debug-only `NativeFilesRpcProbeService` is protected by DUMP and accepts no
command/path/policy Intent input. Gradle bundles six explicit source assets. The
service copies them into a new private cache directory and starts the APK-owned
official Android/Bionic interpreter with an explicit minimal environment and
isolated PyConfig. All test
files and profiles are new; no account, model or live client setting is involved.

Android's Zygote context refuses the direct GNU loader in private data with
EACCES, although `run-as` permits it. Packaging the byte-identical loader in the
APK native directory corrects executable placement without changing Android
policy. `stage-gnu-loader.py` reads this one regular file from the independently
authenticated Debian base and checks archive SHA-256, AArch64 ELF identity and
LOAD permissions/alignment. It does not source a binary from a phone or mirror.
The original GNU diagnostic required this match; the current service uses Bionic.

Authenticated base SHA-256:
`dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f`.
GNU loader SHA-256:
`1d8b77f28b7cec0329dca107a28fb0a850193b1dcce59be68fa0b06b514548cc`.
This is Debian glibc, covered by the base's corresponding source inventory.
The proprietary client is not changed or bundled by this diagnostic.

The packaged loader starts under Zygote, but Python exits 159 (SIGSYS).
The native signal observer identified AArch64 syscall **99, set_robust_list**,
with kernel `si_code=SYS_SECCOMP`. It forwards the unchanged signal and confirms
the real child dies with signal 31 and is reaped. The observation lives in
`cache/native-files-rpc-4f4415db-c710-4094-88f6-e29494dda7d9/sigsys-observer.txt`.
This is an actual GNU/Bionic ABI incompatibility under the inherited Android
application filter; PRoot's source handles that syscall as ENOSYS. The intended
supervisor instead uses Python's officially compiled Android/Bionic runtime,
without suppressing a security signal or modifying the Android filter.
The 6 September Android/Bionic run **passes 34 real RPC responses and all
12 grouped checks**. Both fixture and actual server run ARM64 under UID 10412,
Zygote's untrusted_app SELinux domain, inherited seccomp 2, zero capabilities
and no tracer. It exercises real subprocess pipes, asyncio helper execution,
inherited file descriptors and EOF followed by workspace-lock reacquisition.
No GNU loader, PRoot or isolation shim is mapped in those Python processes.

The independently collected evidence is
`downloads/native-files-rpc/android-052f7bd5-1635-47d8-9286-2e9fe8e4f55d`.
The collector checks four physical files, the exercised inode, rejected absent
targets, 34 retained requests/responses and executable hashes against the APK.
Debug APK SHA-256:
`bbea3f3cc90951c502ad23a0f9b730027bd5646b70146b0bd45fb6315bbe0f42`.
Android helper SHA-256:
`378bb697243c8b84bfce3ef07d621f27daae575610c00d50bad5f7cab4442c58`.
Launcher SHA-256:
`33dbb844735052ccf78162d34d8570ee1ea50fbc4f0298fbe59b02197745499f`.

`android-python-build.sh` builds that small launcher with NDK r29/API 35 and
stages the intact, Sigstore-verified official CPython 3.14.7 Android ARM64
runtime. Its inventory records 2,552 files and 86 AArch64 ELF objects, 16 KiB
LOAD alignment, corresponding sources and 18 notices. Those static checks do
not claim every bundled Python module has executed on the phone.

APK validation checks exact debug source assets and the debug-only service,
and rejects them in release. CPython assets/libraries and the retained GNU
diagnostic loader are debug inputs. Both actual APK content checks pass. The
unsigned release-check APK is never installed.

## Later private guest bridge

The separate GNU guest-to-Android socket fixture subsequently passed 32 actual
RPC responses across two sessions in APK
`b47b230214cf2fcd8744ebaa951fb6c2b6c6e445c2097da01528dc3734c7263b`.
It adds actual `fs/readDirectory`, `fs/walk`, `fs/copy` and `fs/remove` checks,
including protected mutation refusals, independent copy inodes and EOF lease
release. The GNU bridge runs under PRoot while its Bionic broker stays outside
it. The original 34-response/12-group result above remains associated with its
earlier `bbea...` APK; these are distinct fixtures, not one cumulative test run.
See [the private bridge evidence and limits](private-exec-android.md).

## Remaining boundary

The interpreter and policy resolver are trusted supervisor components outside
PRoot. The exclusively owned fixtures do not admit unconfined outside writers,
arbitrary guest processes, gitdir aliases or managed networking. The private
transport is now exercised on Android; production broker lifecycle, complete
process policy and actual Desktop routing still need implementation and
validation. No normal protected model task is claimed. This is not a production
security or complete-installation result.
