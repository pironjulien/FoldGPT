"""Private Linux CI stages. These commands never access an Android device."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import urllib.request

from native_helpers import build as build_helpers


PROJECT = Path(__file__).resolve().parents[2]
WORK = PROJECT / "work/ci"
ENGINE = WORK / "engine"
EVIDENCE = WORK / "evidence"
HELPERS = WORK / "native-helpers"
ARM_TARGET = "aarch64-unknown-linux-gnu"
OPENSSL_SHA = "243a86649cf6f23eeb6a2ff2456e09e5d77dd9018a54d3d96b0c6bdd6ba6c7f1"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def command(name, argv, *, cwd=PROJECT, env=None, reject_skips=False):
    """Preserve streamed output, exact argv and the exit code before failing."""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    argv = list(map(str, argv))
    started = time.monotonic()
    disk_before = shutil.disk_usage(PROJECT)._asdict()
    log_path = EVIDENCE / f"{name}.log"
    print(f"Running {name}: {argv}", flush=True)
    with log_path.open("w") as log:
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
        for line in child.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        code = child.wait()
    skipped = bool(re.search(r"OK \(skipped=|\.\.\. skipped ", log_path.read_text()))
    save(EVIDENCE / f"{name}.result.json", {
        "argv": argv, "cwd": str(cwd), "exitCode": code,
        "seconds": round(time.monotonic() - started, 3), "pythonSkippedTests": skipped,
        "diskBefore": disk_before, "diskAfter": shutil.disk_usage(PROJECT)._asdict(),
    })
    if code or (reject_skips and skipped):
        raise RuntimeError(f"{name} failed; exit={code}, skipped={skipped}; see {log_path}")


def github_env(values):
    path = os.environ.get("GITHUB_ENV")
    if not path:
        raise RuntimeError("CI stage requires GitHub's explicit environment file")
    with Path(path).open("a") as stream:
        for key, value in values.items():
            if "\n" in str(value) or "\r" in str(value):
                raise RuntimeError("Multiline build environment value refused")
            stream.write(f"{key}={value}\n")


def restore():
    command("restore-engine", [sys.executable, "-B", PROJECT / "tools/recovery/restore-engine.py",
                               "--destination", ENGINE])
    manifest = json.loads((PROJECT / "recovery/engine/manifest.json").read_text())
    shutil.copyfile(PROJECT / "recovery/engine/manifest.json", EVIDENCE / "engine-recovery.json")
    files = subprocess.check_output(["git", "-C", ENGINE, "ls-files", "-z"])
    inventory = []
    for raw in files.split(b"\0"):
        if not raw:
            continue
        relative = raw.decode()
        path = ENGINE / relative
        if path.is_symlink():
            inventory.append({"path": relative, "link": os.readlink(path)})
        else:
            inventory.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha(path)})
    save(EVIDENCE / "engine-sources.json", {"patchSha256": manifest["sha256"], "files": inventory})


def v8(target):
    for key in ("V8_FROM_SOURCE", "DOCS_RS", "RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH"):
        if os.environ.get(key):
            raise RuntimeError(f"Unexpected inherited V8 override: {key}")
    os.environ["CODEX_REPO_ROOT"] = str(ENGINE)
    sys.path.insert(0, str(ENGINE / "scripts"))
    from codex_package.targets import TARGET_SPECS
    from codex_package.v8 import fetch_codex_v8_artifacts
    pair = fetch_codex_v8_artifacts(TARGET_SPECS[target], cache_root=WORK / "cache/v8")
    github_env({"RUSTY_V8_ARCHIVE": pair.archive, "RUSTY_V8_SRC_BINDING_PATH": pair.binding})
    save(EVIDENCE / "v8.json", {
        "target": target, "verifierSha256": sha(ENGINE / "scripts/codex_package/v8.py"),
        "archive": str(pair.archive), "archiveSha256": sha(pair.archive),
        "binding": str(pair.binding), "bindingSha256": sha(pair.binding),
    })


def helpers():
    build_helpers(PROJECT, HELPERS)
    shutil.copyfile(HELPERS / "manifest.json", EVIDENCE / "native-helpers.json")


def native_environment():
    environment = dict(os.environ)
    environment.update({
        "PYTHONPATH": str(HELPERS / "package"), "FOLDGPT_NATIVE_FILES": str(HELPERS / "native-files"),
        "FOLDGPT_NATIVE_HANDLES": str(HELPERS / "native-file-handle"),
        "FOLDGPT_NATIVE_RUNNER": str(HELPERS / "runner"),
        "FOLDGPT_PAUSED_HELPER": str(HELPERS / "paused-helper"),
        "FOLDGPT_BIONIC_CWD_SHIM": str(HELPERS / "libfoldgpt_bionic_cwd.host.so"),
        "FOLDGPT_NATIVE_TEST_HELPERS": str(HELPERS), "FOLDGPT_NATIVE_TEST_RUNNER": str(HELPERS / "runner"),
        "FOLDGPT_NATIVE_TEST_ARTIFACTS": str(EVIDENCE / "native-app-server"),
        "FOLDGPT_DIRECT_RUNNER": str(HELPERS / "direct-runner"),
        "FOLDGPT_DIRECT_WORKER": str(HELPERS / "direct-worker"),
    })
    return environment


def python_tests():
    environment = native_environment()
    failures = []
    runs = [("fd-abi", [HELPERS / "native-process-fd-abi"]),
            ("runtime-paths-c", [HELPERS / "runtime-paths-test"])]
    for module in ("test_native_runtime_startup", "test_native_runtime_acquisition",
                   "test_native_host_files", "test_native_host_files_channel",
                   "test_production_host_v2", "test_ordinary_uid_files", "test_production_ordinary_uid"):
        runs.append((module, [sys.executable, "-B", "-m", f"tools.executor.{module}"]))
    supervisor = HELPERS / "package/tools/executor/bionic-supervisor"
    host_evidence = EVIDENCE / "native-host-v2"
    host_evidence.mkdir(mode=0o700, exist_ok=False)
    direct_evidence = EVIDENCE / "ordinary-uid"
    direct_evidence.mkdir(mode=0o700, exist_ok=False)
    for script, arguments in (
        ("test_kernel", [HELPERS / "runner"]), ("test_factory", [HELPERS]),
        ("test_runtime_paths", [HELPERS]), ("qualification", [HELPERS]),
        ("test_runtime_qualification", [HELPERS, HELPERS / "libfoldgpt_bionic_cwd.host.so"]),
        ("test_host_kernel", [HELPERS, host_evidence]),
        ("test_host_processes", [HELPERS, host_evidence]),
        ("test_host_channel_v2", [HELPERS, host_evidence]),
        ("test_direct_runner", [HELPERS, direct_evidence]),
        ("test_direct_processes", [HELPERS, direct_evidence]),
        ("test_model_profiles", [HELPERS, direct_evidence]),
    ):
        runs.append((script, [sys.executable, "-B", supervisor / f"{script}.py", *arguments]))
    runs.append(("ordinary-deployment-host", [sys.executable, "-B",
        PROJECT / "tools/executor/shizuku-service/verify-deployment-host.py",
        HELPERS / "libfoldgpt_bionic_cwd.host.so", "--direct-runner", HELPERS / "direct-runner",
        "--output", direct_evidence / "deployment-host"]))
    for name, argv in runs:
        if name == "qualification":
            # Its canonical fixture requires nobody, and reserves exactly two
            # additional UID tasks: the worker and its one secondary thread.
            # GitHub's own runner shares UID1001 and starts unrelated threads;
            # running this quota probe there invalidates that dedicated fixture.
            owner = pwd.getpwnam("nobody")
            if (owner.pw_uid, owner.pw_gid) != (65534, 65534):
                raise RuntimeError("Dedicated kernel fixture identity differs from its canonical source")
            command("kernel-qualification-identity", ["sudo", "-u", "nobody", "--", "id"])
            # GitHub makes /home/runner private. Preserve those permissions;
            # expose only this frozen, credential-free fixture in canonical
            # native test storage, not the runner's checkout or home directory.
            fixture = Path(tempfile.mkdtemp(prefix="foldgpt-ci-kernel-", dir="/var/tmp"))
            fixture.chmod(0o755)
            public_helpers = fixture / "helpers"
            shutil.copytree(HELPERS, public_helpers)
            for entry in json.loads((HELPERS / "manifest.json").read_text())["files"]:
                if sha(public_helpers / entry["path"]) != entry["sha256"]:
                    raise RuntimeError("Dedicated kernel fixture transfer changed bytes")
            save(EVIDENCE / "kernel-fixture-transfer.json", {
                "directory": str(public_helpers), "manifestSha256": sha(public_helpers / "manifest.json"),
                "uid": owner.pw_uid, "gid": owner.pw_gid})
            argv = [sys.executable, "-B", public_helpers / "package/tools/executor/bionic-supervisor/qualification.py",
                    public_helpers]
            argv = ["sudo", "-u", "nobody", "--", *argv]
        environment["FOLDGPT_HOST_FILE_OBSERVATIONS"] = str(EVIDENCE / f"{name}.observations.json")
        try:
            # Run from the frozen package, so repository imports cannot shadow it.
            command(name, argv, cwd=HELPERS / "package", env=environment, reject_skips=True)
        except RuntimeError as error:
            failures.append(str(error))
    collect_native_reports()
    save(EVIDENCE / "native-python-summary.json", {
        "success": not failures, "failures": failures, "androidExecution": False,
        "scope": "Real nonroot Linux C/Python workers, files, permissions, credentials and lifecycle",
    })
    if failures:
        raise RuntimeError("Native Python qualification failed; preserved all stage results")


def collect_native_reports():
    # Only exact JSON evidence paths emitted by the selected trusted test drivers.
    # Do not walk a workspace whose native owner may have been quarantined.
    for log in sorted(EVIDENCE.glob("*.log")):
        for line in log.read_text().splitlines():
            start = line.find("{")
            if start < 0:
                continue
            try:
                # unittest may write its case label before the driver's JSON.
                record = json.loads(line[start:])
            except json.JSONDecodeError:
                continue
            for key in ("evidence", "observations"):
                value = record.get(key)
                if not isinstance(value, str):
                    continue
                path = Path(value)
                if log.stem == "qualification":
                    # The fixed driver uses a private nobody-owned /var/tmp
                    # directory. Read only its named report as the same UID.
                    if not re.fullmatch(r"/var/tmp/foldgpt-kernel-qualification-[A-Za-z0-9_]+/evidence", value):
                        raise RuntimeError("Unexpected dedicated kernel evidence path")
                    report = subprocess.check_output(["sudo", "-u", "nobody", "--", "/usr/bin/cat",
                                                      value + "/qualification.json"])
                    save(EVIDENCE / "kernel-qualification.json", json.loads(report))
                    continue
                if path.is_dir():
                    path = path / "qualification.json"
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to("/var/tmp"):
                    name = f"{log.stem}-{hashlib.sha256(str(path).encode()).hexdigest()[:12]}.json"
                    shutil.copyfile(path, EVIDENCE / name)


def engine_tests():
    environment = native_environment()
    cwd = ENGINE / "codex-rs"
    command("engine-linux-build", ["cargo", "build", "--locked", "--timings",
        "-p", "codex-cli", "--bin", "codex", "-p", "codex-app-server", "--bins",
        "-p", "codex-code-mode-host", "--bin", "codex-code-mode-host"], cwd=cwd, env=environment)
    binaries = Path(os.environ["CARGO_TARGET_DIR"]) / "debug"
    save(EVIDENCE / "engine-linux-binaries.json", {
        name: {"sha256": sha(binaries / name), "bytes": (binaries / name).stat().st_size}
        for name in ("codex", "codex-app-server", "codex-code-mode-host")})
    sections = {}
    for name in ("codex", "codex-app-server", "codex-code-mode-host"):
        output = subprocess.check_output(["readelf", "--wide", "--section-headers", binaries / name], text=True)
        (EVIDENCE / f"{name}-linux-sections.log").write_text(output)
        sections[name] = {"bytes": (binaries / name).stat().st_size,
                          "staticSymbolTable": bool(re.search(r"\s\.symtab\s", output)),
                          "debugSections": sorted(set(re.findall(r"\s(\.debug_[A-Za-z0-9_]+)\s", output)))}
    save(EVIDENCE / "engine-linux-symbols.json", sections)
    if any(record["staticSymbolTable"] or record["debugSections"] for record in sections.values()):
        raise RuntimeError("Linux qualification binaries still contain removable compilation symbols")
    base = ["just", "--justfile", ENGINE / "justfile", "test", "--locked", "--test-threads", "2"]
    runs = [
        ("exec-server-tests", ["-p", "codex-exec-server", "--lib", "--test", "runtime_acquisition",
            "--test", "native_local_runtime", "--test", "owned_process_events",
            "--test", "selected_capability_roots", "--test", "deferred_environment"]),
        ("app-server-injected-tests", ["-p", "codex-app-server", "--test", "all", "-E", "test(injected_)"]),
        ("app-server-startup-tests", ["-p", "codex-app-server", "--test", "native_startup"]),
        ("app-server-native-python", ["-p", "codex-app-server", "--test", "all", "--run-ignored", "all",
             "-E", "test(=suite::v2::native_app_server::real_native_app_server_python_project)"]),
    ]
    failures = []
    for name, arguments in runs:
        try:
            command(name, [*base, *arguments], cwd=ENGINE, env=environment)
        except RuntimeError as error:
            failures.append(str(error))
        report = Path(os.environ["CARGO_TARGET_DIR"]) / "nextest/local/junit.xml"
        if report.is_file():
            shutil.copyfile(report, EVIDENCE / f"{name}.junit.xml")
    save(EVIDENCE / "engine-tests-summary.json", {
        "success": not failures, "failures": failures, "androidExecution": False, "phoneUiTested": False,
        "scope": "Selected engine integration tests; native project uses deterministic Responses SSE fixtures",
    })
    if failures:
        raise RuntimeError("Engine tests failed; all selected independent suites were attempted")


def format_tools():
    """Install exact upstream formatter binaries, verified before extraction."""
    specs = (
        ("uv", "0.12.5", "https://github.com/astral-sh/uv/releases/download/0.12.5/uv-x86_64-unknown-linux-gnu.tar.gz",
         "68a509da24b06b4223a1c0175fb5eb5bc79342b76cbeff0cfe51ac3f5b17b6b2", "uv-x86_64-unknown-linux-gnu/uv"),
        ("dotslash", "0.5.9", "https://github.com/facebook/dotslash/releases/download/v0.5.9/dotslash-linux-musl.x86_64.v0.5.9.tar.gz",
         "4c75c6eb7890ae35993b962073f6d9bbe78b42b81a5691303ad70f63bfbf7196", "dotslash"),
    )
    result = []
    cache = WORK / "cache/format-tools"
    cache.mkdir(parents=True, exist_ok=True)
    bin_dir = WORK / "tools/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, version, url, digest, member in specs:
        archive = cache / f"{name}-{version}.tar.gz"
        if not archive.exists():
            with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as output:
                shutil.copyfileobj(response, output)
        if sha(archive) != digest:
            raise RuntimeError(f"Official formatter archive checksum mismatch: {name}")
        with tarfile.open(archive) as stream:
            info = stream.getmember(member)
            if not info.isfile():
                raise RuntimeError(f"Formatter archive member is not a regular executable: {name}")
            with stream.extractfile(info) as source, (bin_dir / name).open("wb") as output:
                shutil.copyfileobj(source, output)
        (bin_dir / name).chmod(0o755)
        command(f"{name}-version", [bin_dir / name, "--version"])
        result.append({"name": name, "version": version, "url": url,
                       "archiveSha256": digest, "binarySha256": sha(bin_dir / name)})
    save(EVIDENCE / "format-tools.json", result)


def engine_final_checks():
    """Run broad tests only after the selected integration step succeeds."""
    environment = native_environment()
    environment.update({"UV_CACHE_DIR": str(WORK / "cache/uv"),
                        "UV_PYTHON_INSTALL_DIR": str(WORK / "cache/uv-python"),
                        "DOTSLASH_CACHE": str(WORK / "cache/dotslash")})
    base = ["just", "--justfile", ENGINE / "justfile"]
    storage_snapshot("engine-full-before")
    try:
        command("engine-full-tests", [*base, "test", "--locked", "--test-threads", "2"],
                cwd=ENGINE, env=environment)
    finally:
        storage_snapshot("engine-full-after")
        report = Path(os.environ["CARGO_TARGET_DIR"]) / "nextest/local/junit.xml"
        if report.is_file():
            shutil.copyfile(report, EVIDENCE / "engine-full-tests.junit.xml")
    # Scope Clippy to actual changed Rust packages, including newly added sources.
    changed = subprocess.check_output(["git", "diff", "HEAD", "--name-only", "-z"], cwd=ENGINE).split(b"\0")
    packages = set()
    for raw in changed:
        if not raw:
            continue
        path = ENGINE / raw.decode()
        if not path.is_relative_to(ENGINE / "codex-rs") or (path.suffix != ".rs" and path.name != "Cargo.toml"):
            continue
        for parent in path.parents:
            if parent == ENGINE:
                break
            manifest = parent / "Cargo.toml"
            if manifest.is_file():
                package = tomllib.loads(manifest.read_text()).get("package", {}).get("name")
                if package:
                    packages.add(package)
                    break
    if not packages:
        raise RuntimeError("Expected private engine changes for the scoped final Clippy pass")
    save(EVIDENCE / "engine-fix-packages.json", sorted(packages))
    command("engine-fix", [*base, "fix", "--locked", *[arg for package in sorted(packages) for arg in ("-p", package)]],
            cwd=ENGINE, env=environment)
    format_tools()
    command("engine-format", [*base, "fmt"], cwd=ENGINE, env=environment)
    # Preserve only final fixer changes relative to the exact restored source index.
    (EVIDENCE / "engine-final-source-fixes.patch").write_bytes(
        subprocess.check_output(["git", "diff", "--binary", "--full-index"], cwd=ENGINE))
    save(EVIDENCE / "engine-final-checks.json", {"passed": True, "androidExecution": False,
        "fullSuite": True, "fixPackages": sorted(packages), "format": True,
        "fixPatchSha256": sha(EVIDENCE / "engine-final-source-fixes.patch")})


def storage_snapshot(name):
    """Measure actual allocated target blocks, without counting hardlinks twice."""
    target = Path(os.environ["CARGO_TARGET_DIR"])
    seen, largest = set(), []
    allocated = 0
    for path in target.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        info = path.stat()
        identity = info.st_dev, info.st_ino
        if identity in seen:
            continue
        seen.add(identity)
        allocated += info.st_blocks * 512
        largest.append({"path": path.relative_to(target).as_posix(), "bytes": info.st_size})
    record = {"disk": shutil.disk_usage(PROJECT)._asdict(), "targetAllocatedBytes": allocated,
              "targetFiles": len(seen), "largest": sorted(largest, key=lambda item: item["bytes"], reverse=True)[:20]}
    print(json.dumps({name: record}), flush=True)
    save(EVIDENCE / f"{name}-storage.json", record)


def arm_dependencies():
    source_root = WORK / "openssl-source"
    source_root.mkdir(exist_ok=False)
    archive = source_root / "openssl-3.6.3.tar.gz"
    url = "https://github.com/openssl/openssl/releases/download/openssl-3.6.3/" + archive.name
    with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as output:
        shutil.copyfileobj(response, output)
    if sha(archive) != OPENSSL_SHA:
        raise RuntimeError("Official OpenSSL source differs from the previously verified source hash")
    with tarfile.open(archive) as stream:
        stream.extractall(source_root, filter="data")
    source = source_root / "openssl-3.6.3"
    prefix = WORK / "openssl-arm64"
    command("openssl-configure", ["perl", "./Configure", "linux-aarch64",
        "--cross-compile-prefix=aarch64-linux-gnu-", "no-shared", f"--prefix={prefix}",
        "--openssldir=/usr/lib/ssl"], cwd=source)
    command("openssl-build", ["make", "-j2", "build_sw"], cwd=source)
    command("openssl-install", ["make", "install_sw"], cwd=source)
    save(EVIDENCE / "openssl.json", {"url": url, "sourceSha256": sha(archive), "files": [
        {"path": path.relative_to(prefix).as_posix(), "sha256": sha(path)}
        for path in sorted(prefix.rglob("*")) if path.is_file() and not path.is_symlink()]})
    github_env({
        "CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER": "aarch64-linux-gnu-gcc",
        "CC_aarch64_unknown_linux_gnu": "aarch64-linux-gnu-gcc",
        "CXX_aarch64_unknown_linux_gnu": "aarch64-linux-gnu-g++",
        "AR_aarch64_unknown_linux_gnu": "aarch64-linux-gnu-ar",
        "AARCH64_UNKNOWN_LINUX_GNU_OPENSSL_DIR": prefix,
        "AARCH64_UNKNOWN_LINUX_GNU_OPENSSL_STATIC": "1",
    })


def arm_build():
    command("engine-arm64-build", ["cargo", "build", "--locked", "--target", ARM_TARGET,
        "--release", "--timings", "-p", "codex-cli", "--bin", "codex",
        "-p", "codex-code-mode-host", "--bin", "codex-code-mode-host"], cwd=ENGINE / "codex-rs")
    stage = EVIDENCE / "arm64-gnu"
    stage.mkdir(exist_ok=False)
    inventory = []
    for name in ("codex", "codex-code-mode-host"):
        path = stage / name
        shutil.copy2(Path(os.environ["CARGO_TARGET_DIR"]) / ARM_TARGET / "release" / name, path)
        command(f"{name}-arm64-strip", ["aarch64-linux-gnu-strip", "--strip-unneeded", path])
        command(f"{name}-arm64-elf", ["aarch64-linux-gnu-readelf", "-h", "-l", "-d", "--wide", path])
        header = (EVIDENCE / f"{name}-arm64-elf.log").read_text()
        if not re.search(r"Machine:\s+AArch64\b", header) or "/lib/ld-linux-aarch64.so.1" not in header:
            raise RuntimeError(f"Unexpected GNU ARM64 ELF identity: {name}")
        inventory.append({"path": name, "sha256": sha(path), "bytes": path.stat().st_size})
    save(stage / "manifest.json", {"target": ARM_TARGET, "profile": "release", "files": inventory,
        "patchSha256": json.loads((EVIDENCE / "engine-recovery.json").read_text())["sha256"],
        "androidExecution": False, "phoneUiTested": False, "deviceLibrariesValidated": False})
    archive = EVIDENCE / "foldgpt-gnu-engine-aarch64.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for path in sorted(stage.iterdir()):
            stream.add(path, arcname=path.name)
    save(EVIDENCE / "arm64-package.json", {"file": archive.name, "sha256": sha(archive)})


def identity():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    save(EVIDENCE / "host.json", {"platform": platform.platform(), "uid": os.getuid(), "gid": os.getgid(),
        "python": sys.version, "cpuCount": os.cpu_count(), "disk": list(shutil.disk_usage(PROJECT)),
        "memory": Path("/proc/meminfo").read_text(), "androidExecution": False})
    for name, argv in {"gcc": ["gcc", "--version"], "git": ["git", "--version"],
                       "kernel": ["uname", "-a"]}.items():
        command(name, argv)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("identity", "restore", "v8", "helpers", "python-tests",
                                        "engine-tests", "engine-final-checks", "arm-dependencies", "arm-build"))
    parser.add_argument("--target", default="x86_64-unknown-linux-gnu")
    args = parser.parse_args()
    if sys.platform != "linux" or os.getuid() == 0:
        parser.error("Run on the Linux PC runner as its ordinary unprivileged user")
    WORK.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    if args.stage == "v8":
        v8(args.target)
    else:
        globals()[args.stage.replace("-", "_")]()


if __name__ == "__main__":
    main()
