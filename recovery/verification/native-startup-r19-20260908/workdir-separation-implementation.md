# Execution workdir and unchanged policy base

The candidate changes only three production Python files and the existing Linux
factory test. No C, Rust, phone or application packaging changes were made.

- NativeProcessesBackend retains its original equality guard in an overridable
  launch-context validation method. Its static profile is unchanged.
- Bionic Processes requires a supplied sandbox context; under the existing
  workspace lease, Policy still parses the entire context via PolicyIntent and
  parse_context before any native spawn. Unsupported context remains rejected.
- Policy keeps policy_cwd and execution_cwd separately. Both must be within the
  pinned mount and present as ordinary directories in its actual inspection.
  Execution cwd must have read access under the original full policy. Existing
  narrower grants remain valid; no new ancestor read rule was invented.
- The native envelope and relative copied-path resolution use execution_cwd.
  PolicyIntent bytes, rule ordering, roots, denials and metadata protection are
  never rebased. Runtime intersection checks and lifecycle ownership are intact.

New existing-suite tests:

1. FactoryTests.test_05b_execution_workdir_preserves_original_project_policy
   creates W within P, runs real Bash/Python with cwd W/app and policy cwd W,
   requires getcwd W/app and result42 written under app, observes three actual
   denied operations against W/private and W/.git, verifies preserved original
   bytes, policy snapshot identity, process wait and native cleanup.
2. FactoryTests.test_05c_invalid_execution_and_policy_workdirs_never_spawn
   rejects outside/missing/file/denied execution cwd, outside/missing/file policy
   cwd, missing/unsupported context and a real symlink cwd. It requires no native
   process, released workspace lease, no process registry entry and no marker.

Windows syntax compilation, git diff --check and all 10 existing PolicyIntent
unit tests pass (the latter validate unchanged policy normalization only). The local Linux kernel
suite has NOT run. WSL was already listed as running, but its read-only `id`
probe produced no output and was cancelled; no WSL configuration was changed.
The real test_factory suite must run in native-python CI before this candidate
is described as execution-qualified or packaged for the phone.

No protocol change is required: official process/start already carries distinct
cwd and sandbox.cwd, and the existing C envelope carries a separate cwd_relative.

Independent read-only source review by shared_paths found no concrete defect: unchanged
policy snapshot, execution cwd admitted as ordinary/readable under the lease before
spawn, and native envelope uses that execution cwd. No Linux execution claim.

## Source-linked Linux result

Run 34192631216 / commit 8963acc8e961c0d34b068910b973cc6f9b9df3bc
passed all 22 real FactoryTests under UID1001, without skips. Both added
workdir tests are explicitly marked ok. All four changed source hashes match
byte-for-byte between the CI native-helper manifest, the committed Git blobs,
production package v7 and APK r19. The separate r19-v7-independent-package-review.json
records this comparison, all 117 unchanged APK ELF hashes versus r18, and the
unchanged deployment/runtime/host selection. Android workdir execution is still
a separate test; no old v6 preflight report was altered or reused as v7 proof.
