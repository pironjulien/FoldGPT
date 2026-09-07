"""Export the pinned upstream PTY crate and generate a reviewable additive patch."""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2] / "downloads" / "isolation-codex"
COMMIT = "3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
PREFIX = "codex-rs/utils/pty/"
DESTINATION = HERE / "pty-prototype"


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPOSITORY), *args],
                          check=True, capture_output=True).stdout


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f"Pinned source anchor changed: {old[:80]!r}")
    return source.replace(old, new, 1)


def main() -> None:
    actual = git("rev-parse", "rust-v0.153.4^{commit}").decode().strip()
    if actual != COMMIT:
        raise RuntimeError("The requested upstream tag no longer matches its pinned commit")
    paths = git("ls-tree", "-r", "--name-only", COMMIT, "--", PREFIX).decode().splitlines()
    originals = {}
    for path in paths:
        content = git("show", f"{COMMIT}:{path}")
        originals[path] = content
        target = DESTINATION / path.removeprefix(PREFIX)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    path = PREFIX + "src/process.rs"
    source = originals[path].decode()
    source = replace_once(source,
        "    resizer: StdMutex<Option<ResizeFn>>,\n}",
        "    resizer: StdMutex<Option<ResizeFn>>,\n"
        "    // Native signal delivery does not consume later termination control.\n"
        "    #[cfg_attr(not(windows), allow(dead_code))]\n"
        "    interrupt_preserves_control: bool,\n}")
    source = replace_once(source,
        "            resizer: StdMutex::new(resizer),\n",
        "            resizer: StdMutex::new(resizer),\n"
        "            interrupt_preserves_control: false,\n")
    source = replace_once(source,
        "        if result.is_ok() {\n            killer_opt.take();\n        }",
        "        if result.is_ok() && !self.interrupt_preserves_control {\n"
        "            killer_opt.take();\n        }")
    source = replace_once(source,
        "    pub fn request_terminate(&self) {\n"
        "        if let Ok(mut killer_opt) = self.killer.lock()\n"
        "            && let Some(mut killer) = killer_opt.take()\n"
        "        {\n            let _ = killer.kill();\n        }\n    }",
        "    pub fn request_terminate(&self) {\n"
        "        let _ = self.try_request_terminate();\n    }\n\n"
        "    /// Request termination and report the actual controller result.\n"
        "    /// Retain the controller after failure so ownership and retry remain possible.\n"
        "    pub fn try_request_terminate(&self) -> io::Result<()> {\n"
        "        let mut killer_opt = self.killer.lock()\n"
        "            .map_err(|_| io::Error::other(\"process control lock poisoned\"))?;\n"
        "        if let Some(killer) = killer_opt.as_mut() {\n"
        "            killer.kill()?;\n            killer_opt.take();\n        }\n"
        "        Ok(())\n    }")
    source += "\n" + (HERE / "owned_process_driver.rs").read_text(encoding="utf-8")
    (DESTINATION / "src/process.rs").write_text(source, encoding="utf-8", newline="\n")
    lib_path = PREFIX + "src/lib.rs"
    lib = originals[lib_path].decode() + (
        "\n/// Native owned-process adapter with lossless output and fallible controls.\n"
        "pub use process::{OwnedProcessController, OwnedProcessDriver, spawn_from_owned_driver};\n")
    (DESTINATION / "src/lib.rs").write_text(lib, encoding="utf-8", newline="\n")
    cargo = originals[PREFIX + "Cargo.toml"].decode()
    cargo = cargo.replace("edition.workspace = true", 'edition = "2024"')
    cargo = cargo.replace("license.workspace = true", 'license = "Apache-2.0"')
    cargo = cargo.replace("version.workspace = true", 'version = "0.153.4"')
    cargo = cargo.replace("[lints]\nworkspace = true\n", "[workspace]\n")
    versions = {"anyhow": "1", "portable-pty": "0.9.0", "tokio": "1",
                "pretty_assertions": "1.4.1", "lazy_static": "1", "log": "0.4", "libc": "0.2.182"}
    for name, version in versions.items():
        cargo = cargo.replace(name + " = { workspace = true", name + f' = {{ version = "{version}"')
    # Standalone export has no larger workspace to unify winapi's std feature.
    # Its c_void must match std::ffi::c_void used by the unmodified upstream code.
    cargo = cargo.replace('winapi = { version = "0.3.9", features = [',
                          'winapi = { version = "0.3.9", features = [\n    "std",')
    cargo += '\n[[bin]]\nname = "owned_driver_fixture"\npath = "pc_fixture.rs"\n'
    (DESTINATION / "Cargo.toml").write_text(cargo, encoding="utf-8", newline="\n")
    saved_lock = HERE / "prototype-Cargo.lock"
    if saved_lock.exists():
        (DESTINATION / "Cargo.lock").write_bytes(saved_lock.read_bytes())
    for name, target in [("pc_fixture.rs", "pc_fixture.rs"), ("owned_driver_tests.rs", "tests/owned_driver.rs")]:
        (DESTINATION / target).write_bytes((HERE / name).read_bytes())
    patch = []
    for path, updated in [(path, source), (lib_path, lib)]:
        patch.extend(difflib.unified_diff(originals[path].decode().splitlines(keepends=True),
                     updated.splitlines(keepends=True), fromfile="a/" + path, tofile="b/" + path))
    (HERE / "owned-process-driver.patch").write_text("".join(patch), encoding="utf-8", newline="\n")
    provenance = {"upstream_commit": COMMIT, "upstream_tag": "rust-v0.153.4",
                  "working_checkout_modified": False,
                  "source_sha256": {p: hashlib.sha256(c).hexdigest() for p, c in originals.items()},
                  "purpose": "Compilable native process adapter; not an Android execution backend"}
    (HERE / "prototype-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(DESTINATION)


if __name__ == "__main__":
    main()
