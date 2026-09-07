"""Freeze APK inputs for one fixed Android diagnostic. Never operates a phone."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PACKAGE = "app.foldgpt.kernelqualification"
ISOLATED_PACKAGE = "app.foldgpt.kernelqualification.v11"
BASES = {PACKAGE: "/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2",
         "app.foldgpt.shizukuprobe": "/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2",
         ISOLATED_PACKAGE: "/data/local/tmp/foldgpt-bionic-supervisor-qualification-v3"}
MODULES = ("exec_server", "native_executor_backend", "native_file_streams", "native_files", "native_processes",
           "native_process_policy", "native_environment", "native_environment_unicode", "policy_intent", "private_exec_broker")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--python-cli", type=Path, required=True)
    parser.add_argument("--package", choices=tuple(BASES), required=True)
    parser.add_argument("--output", type=Path, default=HERE / "build/qualification-stage")
    args = parser.parse_args()
    base = BASES[args.package]
    frozen = args.frozen.resolve(strict=True)
    isolated = args.package == ISOLATED_PACKAGE
    if isolated:
        pin = json.loads((HERE / "qualification-inputs-v11.json").read_text())
        if pin["package"] != args.package or pin["base"] != base or frozen.name != pin["frozenName"]:
            raise ValueError("Isolated qualification inputs differ from their reviewed identity")
        for name, expected in pin["frozenFiles"].items():
            if Path(name).name != name or digest((frozen / name).read_bytes()) != expected:
                raise ValueError("Reviewed frozen qualification file differs: " + name)
        expected_supervisor = pin["frozenFiles"]["libfoldgpt_bionic_supervisor.so"]
    else:
        if frozen.name != "foldgpt-bionic-supervisor-8Kd8xQRE":
            raise ValueError("The historical diagnostic requires its reviewed 8Kd8xQRE supervisor")
        expected_supervisor = "4652966bb36c388ee9c26a9b6e6432a09f4bbbb339c230e320511c512b7e5028"
    # The pinned inventory authenticates every source used below, including
    # the resolver shared by Python admission and per-request runtime policy.
    source_hashes = {}
    for line in (frozen / "SOURCES.sha256").read_text().splitlines():
        expected, relative = line.split("  ", 1)
        path = Path(relative)
        if (path.is_absolute() or ".." in path.parts or relative in source_hashes or
                digest((frozen / path).read_bytes()) != expected):
            raise ValueError("Frozen source inventory differs: " + relative)
        source_hashes[relative] = expected
    if isolated:
        for line in (frozen / "BINARIES.sha256").read_text().splitlines():
            expected, relative = line.split("  ", 1)
            if Path(relative).name != relative or digest((frozen / relative).read_bytes()) != expected:
                raise ValueError("Frozen binary inventory differs: " + relative)
    proof = json.loads((frozen / "qualification.json").read_text())
    if proof.get("success") is not True or proof.get("androidExecution") is not False:
        raise ValueError("Frozen host evidence is absent or mislabeled")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    assets = root / "assets"
    jni = root / "jniLibs/arm64-v8a"
    assets.mkdir(); jni.mkdir(parents=True)
    previous = REPO / "downloads/shizuku-lab/runtime-stage-20260907"
    runtime = json.loads((previous / "manifest.json").read_text())
    native = {}
    for entry in runtime["nativeFiles"]:
        if entry["name"] in {"libfoldgpt_bash.so", "libfoldgpt_python_cli.so"}:
            continue
        data = (previous / "jniLibs/arm64-v8a" / entry["name"]).read_bytes()
        if digest(data) != entry["sha256"]:
            raise ValueError("Authenticated Python staging differs")
        native[entry["name"]] = digest(data)
        (jni / entry["name"]).write_bytes(data)
    cli = args.python_cli.read_bytes()
    if (base + "/python").encode() not in cli:
        raise ValueError("CLI does not contain the fixed deployment prefix")
    if isolated and digest(cli) != pin["pythonCliSha256"]:
        raise ValueError("Python CLI differs from the reviewed independent prefix build")
    native["libfoldgpt_python_cli.so"] = digest(cli)
    (jni / "libfoldgpt_python_cli.so").write_bytes(cli)
    for name in ("libfoldgpt_bionic_supervisor.so", "libfoldgpt_native_files.so", "libfoldgpt_native_file_handle.so", "libfoldgpt_qualification_worker.so"):
        data = (frozen / name).read_bytes()
        native[name] = digest(data)
        (jni / name).write_bytes(data)
    if native["libfoldgpt_bionic_supervisor.so"] != expected_supervisor:
        raise ValueError("Wrong frozen supervisor")
    runtime_manifest = {key: runtime[key] for key in ("python", "dataFiles", "runtimeAliases")}
    runtime_bytes = (json.dumps(runtime_manifest, indent=2) + "\n").encode()
    (assets / "foldgpt-python-runtime.json").write_bytes(runtime_bytes)
    shutil.copytree(previous / "assets/bionic-python", root / "staged-python-data")
    for entry in runtime_manifest["dataFiles"]:
        data = (root / "staged-python-data" / entry["path"]).read_bytes()
        if digest(data) != entry["sha256"] or len(data) != entry["bytes"]:
            raise ValueError("Python data differ from authenticated inventory")
    workspace = base + "/workspace"
    marker = "@nativeLibraryDir/"
    worker = marker + "libfoldgpt_qualification_worker.so"
    options = {"helper": marker + "libfoldgpt_native_files.so", "handleHelper": marker + "libfoldgpt_native_file_handle.so",
        "processRunner": marker + "libfoldgpt_bionic_supervisor.so", "workspace": workspace,
        "executables": {"kernel-qualification": worker}, "runtime": [
            {"path": path, "execute": execute} for path, execute in (
                (worker, True), ("/system/lib64", True), ("/system/bin/linker64", True), ("/apex/com.android.runtime", True),
                ("/linkerconfig/ld.config.txt", False), ("/dev/__properties__", False), ("/apex/com.android.tzdata/etc/tz/tzdata", False))],
        "limits": {"wall_ms": 3000, "cpu_seconds": 1, "uid_task_budget": 2, "data_bytes": 16777216,
                   "file_bytes": 1048576, "output_bytes": 8192, "descriptors": 32}}
    deployment = {"schema": "foldgpt.shizuku.deployment.v1", "packageName": args.package,
        "pythonLibrary": "libfoldgpt_python_cli.so", "pythonSha256": native["libfoldgpt_python_cli.so"],
        "nativeLibraries": native, "pythonRuntime": {"path": base + "/python",
            "manifestAsset": "foldgpt-python-runtime.json", "manifestSha256": digest(runtime_bytes)},
        "workspace": workspace, "brokerDirectory": base + "/broker",
        "backendFactory": "tools.executor.bionic-supervisor." +
            ("qualification_factory_v11" if isolated else "qualification_factory") + ":factory", "backendOptions": options,
        "environmentInfo": {"cwd": "file://" + workspace, "userHomeDir": "file://" + workspace,
            "platformOs": "android", "shell": {"name": "kernel-qualification", "path": "kernel-qualification"}}}
    (assets / "foldgpt-executor-deployment.json").write_text(json.dumps(deployment, indent=2) + "\n")
    target = assets / "foldgpt-executor"
    target.mkdir()
    for package in ("tools", "tools/executor", "tools/policy", "tools/executor/bionic-supervisor"):
        directory = target / package
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_bytes(b"")
    # V11 takes its complete native backend from one reviewed frozen build.
    # Historical V10 used the current stdio session owner over the old build.
    sources = [((REPO / "tools/executor" if not isolated and name == "private_exec_broker" else
                 frozen / "package/tools/executor") / (name + ".py"),
                "tools/executor/" + name + ".py") for name in MODULES]
    sources += [(frozen / "package/tools/policy/managed_policy.py", "tools/policy/managed_policy.py")]
    sources += [(frozen / "package/tools/executor/bionic-supervisor" / (name + ".py"), "tools/executor/bionic-supervisor/" + name + ".py")
                for name in ("factory", "policy", "processes", "wire", "qualification") +
                            (("runtime_paths",) if isolated else ())]
    sources += [(REPO / "tools/executor/bionic-supervisor/qualification_factory.py", "tools/executor/bionic-supervisor/qualification_factory.py")]
    if isolated:
        sources += [(REPO / "tools/executor/bionic-supervisor/qualification_factory_v11.py",
                     "tools/executor/bionic-supervisor/qualification_factory_v11.py")]
    # Bootstrap is provided by the transport AAR; record it without duplicating its asset.
    bootstrap = HERE / "transport/src/main/assets/foldgpt-executor/foldgpt_shizuku_bootstrap.py"
    manifest = [{"path": "foldgpt_shizuku_bootstrap.py", "sha256": digest(bootstrap.read_bytes())}]
    for source, relative in sources:
        data = source.read_bytes()
        if source.is_relative_to(frozen) and source_hashes.get(source.relative_to(frozen).as_posix()) != digest(data):
            raise ValueError("Staged source is absent from the authenticated frozen inventory")
        compile(data, relative, "exec"); (target / relative).write_bytes(data)
    for path in sorted(target.rglob("*.py")):
        manifest.append({"path": path.relative_to(target).as_posix(), "sha256": digest(path.read_bytes())})
    (assets / "foldgpt-executor-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # Build the reviewed wire shape directly; no native module imports on Windows.
    uri = "file://" + workspace
    sandbox = {"permissions": {"type": "managed", "file_system": {"type": "restricted", "entries": [
        {"path": {"type": "path", "path": uri}, "access": "write"},
        {"path": {"type": "path", "path": uri + "/private"}, "access": "deny"}]}, "network": "restricted"},
        "cwd": uri, "workspaceRoots": [uri], "windowsSandboxLevel": "disabled"}
    request = {"id": 2, "method": "process/start", "params": {"processId": "kernel-qualification", "argv": ["kernel-qualification"],
        "cwd": uri, "env": {}, "pipeStdin": False, "tty": False, "sandbox": sandbox}}
    (assets / "foldgpt-kernel-request.json").write_text(json.dumps(request, indent=2) + "\n")
    (assets / "foldgpt-host-kernel-evidence.json").write_bytes((frozen / "qualification.json").read_bytes())
    inventory = {"schema": "foldgpt.fixed-qualification-build.v1", "package": args.package, "base": base,
        "frozen": str(frozen), "androidExecution": False,
        "files": [{"path": path.relative_to(root).as_posix(), "sha256": digest(path.read_bytes())}
            for path in sorted(root.rglob("*")) if path.is_file()]}
    (root / "build-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(root)


if __name__ == "__main__":
    main()
