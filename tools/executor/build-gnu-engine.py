"""Freeze and build the separate GNU ARM64 controller; never access a phone.

Run in WSL as foldgpt-build. `prepare` does not compile Rust. The source comes
from the recovery export, not mutable working-tree files or a test harness.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


PROJECT = Path(__file__).resolve().parents[2]
BASE = "3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
TARGET = "aarch64-unknown-linux-gnu"
BINARIES = ("codex", "codex-code-mode-host")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def run(argv, **kwargs) -> str:
    return subprocess.check_output(list(map(str, argv)), text=True, **kwargs).strip()


def native_storage(path: Path, label: str, *, writable: bool = False) -> dict:
    """Check the actual mount, including symlinks and not-yet-created paths."""
    path = path.expanduser().resolve()
    existing = path
    while not existing.exists():
        existing = existing.parent
    if not existing.is_dir():
        raise RuntimeError(f"{label} is not a directory: {existing}")
    mounts = json.loads(run(["findmnt", "--json", "--target", existing,
                            "--output", "FSTYPE,SOURCE,TARGET"]))["filesystems"]
    mount = mounts[0]
    if mount["fstype"].lower() in {"9p", "drvfs", "virtiofs", "ntfs", "ntfs3",
                                   "fuseblk", "fuse.ntfs-3g", "cifs", "smb3"}:
        raise RuntimeError(
            f"{label} uses Windows/shared storage ({mount['fstype']}): {path}. "
            "Use the native Linux build directory /opt/foldgpt/engine-gnu-arm64/builds "
            "and keep the Cargo target on Linux.")
    if writable and not os.access(existing, os.W_OK | os.X_OK):
        raise RuntimeError(f"{label} is not writable by the build user: {existing}")
    return {"path": str(path), "filesystem": mount["fstype"],
            "device": mount["source"], "mountpoint": mount["target"]}


def files(root: Path) -> list[dict]:
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            entries.append({"path": path.relative_to(root).as_posix(), "link": os.readlink(path)})
        elif path.is_file():
            entries.append({"path": path.relative_to(root).as_posix(), "sha256": sha(path),
                            "mode": path.stat().st_mode & 0o777, "bytes": path.stat().st_size})
    return entries


def environment(state: dict) -> dict:
    deps = Path(state["dependencies"])
    env = dict(os.environ)
    env.update({
        "CARGO_HOME": "/opt/foldgpt/cargo", "RUSTUP_HOME": "/opt/foldgpt/rustup",
        "PATH": "/opt/foldgpt/cargo/bin:/opt/foldgpt/tools/bin:" + os.environ["PATH"],
        "CARGO_TARGET_DIR": state["targetDirectory"],
        "CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER": "aarch64-linux-gnu-gcc",
        "CC_aarch64_unknown_linux_gnu": "aarch64-linux-gnu-gcc",
        "CXX_aarch64_unknown_linux_gnu": "aarch64-linux-gnu-g++",
        "AR_aarch64_unknown_linux_gnu": "aarch64-linux-gnu-ar",
        "AARCH64_UNKNOWN_LINUX_GNU_OPENSSL_DIR": str(deps / "openssl"),
        "AARCH64_UNKNOWN_LINUX_GNU_OPENSSL_STATIC": "1",
        "RUSTY_V8_ARCHIVE": state["v8Archive"],
        "RUSTY_V8_SRC_BINDING_PATH": state["v8Binding"],
        "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
    })
    # Do not inherit a different build's V8 mode or cross-target flags.
    for key in ("V8_FROM_SOURCE", "DOCS_RS", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS"):
        if env.get(key):
            raise RuntimeError(f"Ambiguous inherited build override: {key}")
    return env


def prepare(args) -> None:
    sys.dont_write_bytecode = True
    storage = {
        "buildRoot": native_storage(args.build_root, "--build-root", writable=True),
        "targetDirectory": native_storage(args.target_dir, "--target-dir", writable=True),
    }
    args.build_root = Path(storage["buildRoot"]["path"])
    args.target_dir = Path(storage["targetDirectory"]["path"])
    export = PROJECT / "recovery/engine"
    manifest = json.loads((export / "manifest.json").read_text())
    patch = export / manifest["patch"]
    if manifest["base"] != BASE or sha(patch) != manifest["sha256"]:
        raise RuntimeError("Recovery source identity mismatch")
    if run(["git", "-C", args.engine, "rev-parse", "HEAD"]) != BASE:
        raise RuntimeError("Engine repository does not have the pinned base")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    build = args.build_root / f"{stamp}-{manifest['sha256'][:12]}"
    build.mkdir(parents=True, exist_ok=False)
    evidence = PROJECT / "downloads/engine-gnu-arm64" / build.name
    evidence.mkdir(parents=True, exist_ok=False)
    source = build / "source"
    source.mkdir()
    archive = build / "upstream.tar"
    with archive.open("wb") as stream:
        subprocess.run(["git", "-C", str(args.engine), "-c", "core.autocrlf=false",
                        "-c", "core.eol=lf", "archive", BASE], stdout=stream, check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(source, filter="data")
    # A source snapshot deliberately has no Git index and never modifies the
    # live worktree's index. Apply exactly the full-index binary recovery patch.
    shutil.copyfile(patch, evidence / "engine.patch")
    # A snapshot under this project's work/ directory has no Git repository of
    # its own. Stop parent discovery so git apply uses the snapshot, rather
    # than interpreting paths relative to ChatgptFold's enclosing checkout.
    patch_environment = dict(os.environ, GIT_CEILING_DIRECTORIES=str(source.parent))
    for options in (["--check"], []):
        subprocess.run(["git", "apply", *options, str(evidence / "engine.patch")],
                       cwd=source, env=patch_environment, check=True)
    save(evidence / "recovery-manifest.json", manifest)
    save(evidence / "SOURCES.json", files(source))

    # Reuse the official source-package verifier, retaining archive and binding
    # together. Cached downloads are rechecked against upstream's SHA manifest.
    os.environ["CODEX_REPO_ROOT"] = str(source)
    sys.path.insert(0, str(source / "scripts"))
    from codex_package.targets import TARGET_SPECS
    from codex_package.v8 import fetch_codex_v8_artifacts
    v8 = fetch_codex_v8_artifacts(TARGET_SPECS[TARGET], cache_root=PROJECT / "downloads/engine-v8")
    inputs = PROJECT / "downloads/engine-gnu-arm64-20260907/build-evidence/dependency-inputs"
    expected = dict(reversed(line.split()) for line in (inputs / "SHA256SUMS").read_text().splitlines())
    for name in ("libssl.a", "libcrypto.a"):
        path = args.dependencies / "openssl/lib" / name
        if sha(path) != expected[name]:
            raise RuntimeError(f"Previously qualified OpenSSL archive changed: {path}")
    save(evidence / "DEPENDENCIES.json", files(args.dependencies / "openssl"))
    state = {
        "schema": "foldgpt.gnu-engine-build.v1", "sourceBase": BASE,
        "patchSha256": manifest["sha256"], "target": TARGET, "profile": "release",
        "source": str(source), "evidence": str(evidence), "build": str(build),
        "dependencies": str(args.dependencies), "targetDirectory": str(args.target_dir),
        "v8Archive": str(v8.archive), "v8ArchiveSha256": sha(v8.archive),
        "v8Binding": str(v8.binding), "v8BindingSha256": sha(v8.binding),
        "sourceManifestSha256": sha(evidence / "SOURCES.json"),
        "dependencyManifestSha256": sha(evidence / "DEPENDENCIES.json"),
        "upstreamArchiveSha256": sha(archive),
        "builderSha256": sha(Path(__file__)), "androidExecution": False,
        "buildCompleted": False, "packageCompleted": False,
        "storage": storage,
    }
    env = environment(state)
    cwd = source / "codex-rs"
    probes = {}
    for name, command in {
        "rustc": ["rustc", "-vV"], "cargo": ["cargo", "-vV"],
        "targets": ["rustup", "target", "list", "--installed"],
        "gcc": ["aarch64-linux-gnu-gcc", "--version"],
        "gxx": ["aarch64-linux-gnu-g++", "--version"],
        "readelf": ["aarch64-linux-gnu-readelf", "--version"],
    }.items():
        probes[name] = run(command, cwd=cwd, env=env)
    if TARGET not in probes["targets"].splitlines():
        raise RuntimeError(f"Install the pinned Rust toolchain target {TARGET} before building")
    save(evidence / "toolchain.json", probes)
    shutil.copyfile(__file__, evidence / "build-gnu-engine.py")
    save(evidence / "build-state.json", state)
    print(evidence / "build-state.json")


def validate(state: dict) -> Path:
    evidence = Path(state["evidence"])
    if state["schema"] != "foldgpt.gnu-engine-build.v1" or state["sourceBase"] != BASE:
        raise RuntimeError("Unsupported build identity")
    if sha(Path(__file__)) != state["builderSha256"]:
        raise RuntimeError("Builder changed since preparation; use the preserved builder or prepare again")
    for name, key in (("SOURCES.json", "sourceManifestSha256"),
                      ("DEPENDENCIES.json", "dependencyManifestSha256")):
        if sha(evidence / name) != state[key]:
            raise RuntimeError(f"Manifest changed: {name}")
    if files(Path(state["source"])) != json.loads((evidence / "SOURCES.json").read_text()):
        raise RuntimeError("Frozen source changed")
    if files(Path(state["dependencies"]) / "openssl") != json.loads((evidence / "DEPENDENCIES.json").read_text()):
        raise RuntimeError("OpenSSL inputs changed")
    for key in ("v8Archive", "v8Binding"):
        if sha(Path(state[key])) != state[key + "Sha256"]:
            raise RuntimeError(f"V8 input changed: {key}")
    return evidence


def build(args, state: dict) -> None:
    # Check again: a mount or symlink can change after source preparation.
    native_storage(Path(state["source"]), "Build source")
    native_storage(Path(state["build"]), "Build directory", writable=True)
    native_storage(Path(state["targetDirectory"]), "Cargo target", writable=True)
    evidence = validate(state)
    # A unique log retains each attempt, including interrupted or failed builds.
    with tempfile.NamedTemporaryFile(prefix="build-", suffix=".log", dir=evidence, delete=False) as log:
        command = ["cargo", "build", "--locked", "--target", TARGET, "--release", "--timings",
                   "-p", "codex-cli", "--bin", "codex", "-p", "codex-code-mode-host", "--bin", "codex-code-mode-host"]
        if args.jobs is not None:
            command += ["--jobs", str(args.jobs)]
        print(f"Building; log: {log.name}", flush=True)
        result = subprocess.run(command, cwd=Path(state["source"]) / "codex-rs",
                                env=environment(state), stdout=log, stderr=subprocess.STDOUT)
    state.update(buildCompleted=result.returncode == 0, buildExitCode=result.returncode,
                 buildLog=log.name, buildCommand=command)
    if result.returncode == 0:
        validate(state)
        # Snapshot outputs while this build still owns their provenance. A
        # later build can reuse the shared Cargo target without changing them.
        artifacts = Path(state["build"]) / "unstripped"
        artifacts.mkdir(exist_ok=False)
        for name in BINARIES:
            shutil.copy2(Path(state["targetDirectory"]) / TARGET / "release" / name, artifacts / name)
        state["builtBinaries"] = files(artifacts)
    save(args.state, state)
    if result.returncode:
        raise SystemExit(result.returncode)


def archive_directory(root: Path, destination: Path) -> None:
    """Archive fixed inputs in stable order with normalized metadata."""
    with destination.open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w") as output:
            for path in sorted(root.rglob("*")):
                entry = output.gettarinfo(str(path), arcname=path.relative_to(root).as_posix())
                entry.uid = entry.gid = entry.mtime = 0
                entry.uname = entry.gname = ""
                if path.is_file():
                    with path.open("rb") as stream:
                        output.addfile(entry, stream)
                else:
                    output.addfile(entry)


def package(args, state: dict) -> None:
    evidence = validate(state)
    built = Path(state["build"]) / "unstripped"
    if not state["buildCompleted"] or files(built) != state["builtBinaries"]:
        raise RuntimeError("No matching successful build to package")
    stage = Path(state["build"]) / "package"
    stage.mkdir(exist_ok=False)
    symbols = Path(state["build"]) / "symbols"
    symbols.mkdir()
    for name in BINARIES:
        output, debug = stage / name, symbols / f"{name}.debug"
        shutil.copy2(built / name, output)
        subprocess.run(["aarch64-linux-gnu-objcopy", "--only-keep-debug", str(output), str(debug)], check=True)
        subprocess.run(["aarch64-linux-gnu-strip", "--strip-unneeded", str(output)], check=True)
        subprocess.run(["aarch64-linux-gnu-objcopy", f"--add-gnu-debuglink={debug}", str(output)], check=True)
    subprocess.run([sys.executable, str(PROJECT / "tools/executor/check-gnu-engine-elf.py"),
                    "--binaries", str(stage), "--libraries", str(args.libraries),
                    "--output", str(evidence / "static-compatibility.json")], check=True)
    for name in ("SOURCES.json", "recovery-manifest.json", "engine.patch", "static-compatibility.json"):
        shutil.copyfile(evidence / name, stage / name)
    package_files = files(stage)
    save(stage / "manifest.json", {"kind": "separate-gnu-engine-payload", "target": TARGET,
        "sourceBase": BASE, "patchSha256": state["patchSha256"], "files": package_files,
        "androidExecution": False, "liveUiQualified": False,
        "cliContract": "codex app-server [arguments]; native runtime requires production launcher injection"})
    # Symbols are preserved separately, outside the phone payload.
    save(evidence / "SYMBOLS.json", {"directory": str(symbols), "files": files(symbols)})
    archive = evidence / "foldgpt-gnu-engine-aarch64.tar.gz"
    symbol_archive = evidence / "foldgpt-gnu-engine-aarch64-symbols.tar.gz"
    archive_directory(stage, archive)
    archive_directory(symbols, symbol_archive)
    (evidence / "SHA256SUMS").write_text(
        f"{sha(archive)}  {archive.name}\n{sha(symbol_archive)}  {symbol_archive.name}\n")
    state.update(packageCompleted=True, package=str(archive), packageSha256=sha(archive))
    save(args.state, state)
    print(archive)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "build", "package"))
    parser.add_argument("--engine", type=Path, default=PROJECT / "work/worktrees/FoldgptEngine")
    parser.add_argument("--build-root", type=Path, default=Path("/opt/foldgpt/engine-gnu-arm64/builds"))
    parser.add_argument("--dependencies", type=Path, default=Path("/opt/foldgpt/engine-gnu-arm64/deps"))
    parser.add_argument("--target-dir", type=Path, default=Path("/opt/foldgpt/engine-gnu-arm64/target"))
    parser.add_argument("--libraries", type=Path, default=PROJECT / "downloads/engine-arm64-device-libs-20260907")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--jobs", type=int)
    args = parser.parse_args()
    if sys.platform != "linux" or os.getuid() == 0:
        parser.error("Run on the Linux build host as an unprivileged user")
    if args.jobs is not None and args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.action == "prepare":
        prepare(args)
    else:
        if args.state is None:
            parser.error("--state is required for build/package")
        globals()[args.action](args, json.loads(args.state.read_text()))


if __name__ == "__main__":
    main()
