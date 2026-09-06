# Preparatory managed filesystem resolver

`managed_policy.py` parses a bounded subset of the official Codex 0.153.4
`FileSystemSandboxContext` and returns immutable, lexical path decisions. It
has no dependencies beyond Python 3.10+ and no host-filesystem, device, network,
account, or environment-variable access.

**This is not a sandbox, native policy compiler, or executor.** A positive
decision does not authorize opening a native path. The kernel-facing resolver
must still pin paths and enforce links, runtime metadata, descriptor and
process boundaries. This module does not replace that work.

Python was chosen because reusing the current `codex-protocol` crate imports a
large workspace graph including networking, asynchronous runtime, images and
other unrelated components. This small resolver makes the accepted subset and
its tests reviewable while the native execution boundary is developed.

## API

```python
from tools.policy.managed_policy import parse_context

policy = parse_context({
    "permissions": {
        "type": "managed",
        "file_system": {
            "type": "restricted",
            "entries": [
                {"path": {"type": "special", "value": {"kind": "root"}}, "access": "read"},
                {"path": {"type": "path", "path": "file:///workspace"}, "access": "write"},
            ],
        },
        "network": "restricted",
    },
    "cwd": "file:///workspace",
    "workspaceRoots": ["file:///workspace"],
    "windowsSandboxLevel": "disabled",
})

ordinary = policy.decide("/workspace/value.txt")
assert ordinary.can_read and ordinary.can_write

metadata = policy.decide("/workspace/.git")
assert metadata.resolved_access.value == "write"  # upstream ordinary resolver
assert metadata.access.value == "read"           # symbolic metadata protection
assert metadata.metadata_write_denial == ".git"

assert policy.decide_uri("file:///outside/file").access.value == "read"
normalized_context = policy.to_context_dict()
```

`parse_context` accepts a JSON string, UTF-8 JSON bytes, or a decoded ordinary
dict. Duplicate members, non-finite JSON numbers, unknown fields, wrong types,
and unsupported features raise `PolicyError` with a field path. It validates
the entire context before returning a policy; it never returns a partial
policy after discarding a restriction.

`decide` accepts an absolute POSIX guest path. `decide_uri` accepts the supported
file-URI form. Neither interprets paths relative to the host working directory.
The immutable policy copies the input into tuples and frozen records; changing
the input dict or a returned normalized dict cannot change its decisions.

## Accepted subset

| Input | Behavior |
| --- | --- |
| Enforcement | Managed profile, restricted filesystem, restricted network intent. The network field is preserved as a restriction; networking is not implemented here. |
| Literal paths | UTF-8 `file:///...` or `file://localhost/...`, decoded POSIX components, case sensitive. Percent encodings are decoded once; encoded slashes and NUL are rejected. Repeated/trailing separators are normalized for component matching. |
| Access | `read`, `write`, `deny`; upstream legacy `none` becomes `deny`. Most specific component path wins, then `deny > write > read` for equal specificity. |
| Special paths | `root` with read/deny, `project_roots`, `tmpdir`, `slash_tmp`. The upstream alias `current_working_directory` means **all supplied project roots**, not only cwd. Empty/missing project or temporary roots add no grants. |
| Project subpath | Relative native text, with empty and `.` components ignored. Parent traversal and absolute subpaths are rejected. Percent signs here are literal filename characters, not URI escapes. |
| Symbolic metadata | The exact `metadata_write_denial` rule for `.git`, `.agents`, `.codex`, preserving entry order, descendant checks and explicit writable exceptions. This protects `.git` itself as well as descendants; `.gitignore` is a different path. |
| Context | Explicit POSIX cwd is required for this API. Workspace roots, optional home, and executor temporary roots are retained. Windows settings must be disabled/default, and `useLegacyLandlock` must be false/default. |

The following are explicitly unsupported: globs and scan depth, `minimal` and
unknown special tokens, non-null missing-path behavior, the **special** full-disk
root-write mode, other enforcement/network profiles, Windows/UNC/opaque and
non-UTF-8 paths, control characters, dot segments in ordinary URI/native paths,
and absolute or parent-traversing project subpaths. Some are valid upstream
inputs; this initial module rejects them rather than inventing their semantics.

The special root-write refusal is deliberate. Upstream has an additional
full-disk/narrowing analysis that suppresses metadata protection in some cases;
it is distinct from a literal `file:///` writable entry. That full-disk analysis
is not implemented here. The literal entry retains upstream lexical semantics.

The metadata result has a subtle upstream property: it searches the **first**
matching protected root in the original rule order, then looks for an explicit
write grant within that root. Sorting/coalescing rules can change this result
when writable metadata roots overlap. A dedicated test preserves the observed
behavior rather than substituting a different interpretation.

## Source and validation

All references are to official tag `rust-v0.153.4`, commit
`042fb41b7c813ac7999105e886b2b7aa715b5081`:

- `file-system/src/lib.rs:174-210,237-291,330-348`: portable JSON types.
- `protocol/src/permissions.rs:83-119,926-1001,1782-1823`: precedence, symbolic
  metadata and context-root expansion.
- `protocol/src/permissions.rs:656-665,739-775,884-890`: distinct full-disk
  root-write analysis, rejected by this module.
- `utils/path-uri/src/lib.rs:324-385,632-644,773-807`: POSIX component matching,
  localhost normalization and separator rejection.
- `protocol/src/permissions.rs:2594-2717`: upstream executor-path, narrow deny,
  encoded-component and repeated-separator tests.
- `utils/path-uri/src/tests.rs:1155-1216`: upstream path-boundary and equivalent
  percent-spelling cases; Windows cases remain outside this module's scope.

Run from the repository root:

```powershell
python -m unittest discover -s tests -p test_managed_policy.py -v
```

The suite includes 14 documented resolver vectors, every ordering requested by
those vectors, A/B/C decisions for the same file, protected metadata files and
descendants, prefix lookalikes, explicit exceptions, percent/Unicode handling,
immutability and rejection cases. Its expected outcomes are derived from the
pinned official source. This change has **not** compiled or run the official
Rust resolver as a differential oracle, and it executes no native enforcement.

## Remaining native boundary

The symbolic metadata check does not inspect whether `.git` is a file or
directory, read `gitdir:` pointers, discover repositories, expand platform
runtime roots, canonicalize symlinks, or detect hardlinks. The upstream runtime
policy performs additional expansion, including worktree metadata targets.
Those operations need an executor-owned filesystem view and cannot be inferred
from these lexical results.

Landlock cannot subtract a denied child from a previously granted parent
directory. The native implementation must enforce the complete request with
appropriate descriptor/syscall mediation; copying these decisions into a list
of broad Landlock grants would lose restrictions. The adjacent
`managed-policy-contract.md` and `native_cases` in `managed-policy-vectors.json`
describe the next independent kernel tests. Their expected outcomes remain
requirements, not completed results.
