"""PC-only runtime APK staging from reviewed immutable input hashes."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil

from runtime_qualification_profile import JNI, REPO, HERE, V1, get_profile, load_contract, requests

MODULES = ("exec_server", "native_executor_backend", "native_file_streams", "native_files", "native_processes",
    "native_process_policy", "native_environment", "native_environment_unicode", "policy_intent", "private_exec_broker")
BIONIC = ("factory", "policy", "processes", "wire", "qualification", "qualification_factory", "runtime_paths",
          "runtime_qualification", "runtime_qualification_factory")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_inventory(root, filename):
    rows = {}
    for line in (root / filename).read_text().splitlines():
        digest, relative = line.split("  ", 1)
        path = PurePosixPath(relative)
        if (path.is_absolute() or str(path) != relative or ".." in path.parts or "\\" in relative
                or relative in rows or sha((root / relative).read_bytes()) != digest):
            raise ValueError("Frozen inventory differs: " + relative)
        rows[relative] = digest
    return rows


def stage(frozen, python_cli, *, pin, output=None, profile=V1):
    BASE, PACKAGE = profile.base, profile.package
    if output is None:
        output = profile.stage
    frozen, python_cli = Path(frozen).resolve(strict=True), Path(python_cli).resolve(strict=True)
    if (pin.get("schema") != "foldgpt.runtime-qualification.inputs.v1" or pin.get("package") != PACKAGE
            or pin.get("base") != BASE or pin.get("frozenName") != frozen.name):
        raise ValueError("Inputs do not identify the reviewed runtime qualification")
    required = {"SOURCES.sha256", "BINARIES.sha256", "libfoldgpt_bionic_supervisor.so",
                "libfoldgpt_native_files.so", "libfoldgpt_native_file_handle.so"}
    if not required <= set(pin["frozenFiles"]):
        raise ValueError("Frozen runtime input pins are incomplete")
    for name, expected in pin["frozenFiles"].items():
        if Path(name).name != name or sha((frozen / name).read_bytes()) != expected:
            raise ValueError("Reviewed frozen runtime input differs: " + name)
    sources = read_inventory(frozen, "SOURCES.sha256")
    read_inventory(frozen, "BINARIES.sha256")
    contract = load_contract(frozen / "package")
    # The frozen build can contain kernel gate evidence, but it is never
    # transformed into a runtime execution claim or embedded as runtime proof.
    previous = REPO / "downloads/shizuku-lab/runtime-stage-20260907"
    manifest_bytes = (previous / "manifest.json").read_bytes()
    if sha(manifest_bytes) != pin["runtimeManifestSha256"]:
        raise ValueError("Authenticated Python/Bash runtime inventory differs")
    runtime = json.loads(manifest_bytes)
    cli = python_cli.read_bytes()
    if sha(cli) != pin["pythonCliSha256"] or (BASE + "/python").encode() not in cli:
        raise ValueError("Python CLI differs from its reviewed runtime prefix build")
    if profile.version == 2 and (BASE + "/python/lib:$ORIGIN").encode() not in cli:
        raise ValueError("Runtime V2 CLI lacks its fixed native dependency search path")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    assets, jni = output / "assets", output / "jniLibs/arm64-v8a"
    assets.mkdir(); jni.mkdir(parents=True)
    native = {}
    for entry in runtime["nativeFiles"]:
        name = entry["name"]
        if name == "libfoldgpt_python_cli.so":
            continue
        data = (previous / "jniLibs/arm64-v8a" / name).read_bytes()
        if sha(data) != entry["sha256"]:
            raise ValueError("Authenticated Python/Bash ELF differs: " + name)
        if name == "libfoldgpt_bash.so" and sha(data) != pin["bashSha256"]:
            raise ValueError("Bash differs from its reviewed input")
        (jni / name).write_bytes(data); native[name] = sha(data)
    (jni / "libfoldgpt_python_cli.so").write_bytes(cli)
    native["libfoldgpt_python_cli.so"] = sha(cli)
    for name in ("libfoldgpt_bionic_supervisor.so", "libfoldgpt_native_files.so", "libfoldgpt_native_file_handle.so"):
        data = (frozen / name).read_bytes(); (jni / name).write_bytes(data); native[name] = sha(data)
    if set(pin["transportNativeHashes"]) != {"libfoldgpt_bionic_cwd.so", "libfoldgpt_shizuku_transport.so"}:
        raise ValueError("Runtime JNI inventory is not exact")
    for name, digest in pin["transportNativeHashes"].items():
        if sha((JNI / name).read_bytes()) != digest:
            raise ValueError("Frozen transport input differs: " + name)
        # These two ELFs are supplied only by the transport module's frozen
        # jniLibs, preventing duplicate APK entries. They are still attested.
        native[name] = digest
    runtime_manifest = {name: runtime[name] for name in ("python", "dataFiles", "runtimeAliases")}
    runtime_bytes = (json.dumps(runtime_manifest, indent=2) + "\n").encode()
    (assets / "foldgpt-python-runtime.json").write_bytes(runtime_bytes)
    shutil.copytree(previous / "assets/bionic-python", output / "staged-python-data")
    for entry in runtime_manifest["dataFiles"]:
        data = (output / "staged-python-data" / entry["path"]).read_bytes()
        if sha(data) != entry["sha256"] or len(data) != entry["bytes"]:
            raise ValueError("Python runtime data differ from authenticated inventory")
    marker = "@nativeLibraryDir/"
    options = {"helper": marker + "libfoldgpt_native_files.so", "handleHelper": marker + "libfoldgpt_native_file_handle.so",
        "processRunner": marker + "libfoldgpt_bionic_supervisor.so", "workspace": BASE + "/workspace",
        "executables": {"bash": marker + "libfoldgpt_bash.so"}, "limits": contract.LIMITS,
        "cwdShim": {"path": marker + "libfoldgpt_bionic_cwd.so", "sha256": native["libfoldgpt_bionic_cwd.so"]},
        "parentEnvironment": {}, "runtime": [{"path": path, "execute": execute} for path, execute in (
            (marker + "libfoldgpt_bash.so", True), (marker + "libfoldgpt_python_cli.so", True), (BASE + "/python", False),
            ("/system/lib64", True), ("/system/bin/linker64", True), ("/apex/com.android.runtime", True),
            ("/linkerconfig/ld.config.txt", False), ("/dev/__properties__", False), ("/apex/com.android.tzdata/etc/tz/tzdata", False))]}
    config = {"schema": "foldgpt.shizuku.deployment.v1", "packageName": PACKAGE,
        "pythonLibrary": "libfoldgpt_python_cli.so", "pythonSha256": native["libfoldgpt_python_cli.so"],
        "nativeLibraries": native, "pythonRuntime": {"path": BASE + "/python",
            "manifestAsset": "foldgpt-python-runtime.json", "manifestSha256": sha(runtime_bytes)},
        "workspace": BASE + "/workspace", "brokerDirectory": BASE + "/broker",
        "backendFactory": profile.backend_factory, "backendOptions": options,
        "environmentInfo": {"cwd": "file://" + BASE + "/workspace", "userHomeDir": "file://" + BASE + "/workspace",
            "platformOs": "android", "shell": {"name": "bash", "path": "bash"}}}
    (assets / "foldgpt-executor-deployment.json").write_text(json.dumps(config, indent=2) + "\n")
    (assets / "foldgpt-runtime-requests.json").write_text(json.dumps(requests(contract, profile), indent=2) + "\n")
    target = assets / "foldgpt-executor"
    for directory in ("tools", "tools/executor", "tools/policy", "tools/executor/bionic-supervisor"):
        path = target / directory; path.mkdir(parents=True, exist_ok=True); (path / "__init__.py").write_bytes(b"")
    relatives = ["tools/executor/" + name + ".py" for name in MODULES]
    relatives += ["tools/policy/managed_policy.py"]
    relatives += ["tools/executor/bionic-supervisor/" + name + ".py" for name in BIONIC]
    if profile.version == 2:
        relatives += ["tools/executor/bionic-supervisor/runtime_qualification_factory_v2.py"]
    for relative in relatives:
        data = (frozen / "package" / relative).read_bytes()
        if sources.get("package/" + relative) != sha(data):
            raise ValueError("Runtime source is absent from the frozen inventory: " + relative)
        compile(data, relative, "exec"); (target / relative).write_bytes(data)
    bootstrap = HERE / "transport/src/main/assets/foldgpt-executor/foldgpt_shizuku_bootstrap.py"
    source_manifest = [{"path": "foldgpt_shizuku_bootstrap.py", "sha256": sha(bootstrap.read_bytes())}]
    source_manifest += [{"path": path.relative_to(target).as_posix(), "sha256": sha(path.read_bytes())}
                        for path in sorted(target.rglob("*.py"))]
    (assets / "foldgpt-executor-manifest.json").write_text(json.dumps(source_manifest, indent=2) + "\n")
    (output / "reviewed-inputs.json").write_text(json.dumps(pin, indent=2) + "\n")
    inventory = {"schema": "foldgpt.runtime-qualification-build.v1", "package": PACKAGE, "base": BASE,
        "frozen": str(frozen), "androidExecution": False, "files": [
            {"path": path.relative_to(output).as_posix(), "sha256": sha(path.read_bytes())}
            for path in sorted(output.rglob("*")) if path.is_file()]}
    (output / "build-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--python-cli", type=Path, required=True)
    parser.add_argument("--version", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    profile = get_profile(args.version)
    inventory = stage(args.frozen, args.python_cli, pin=json.loads(profile.inputs.read_text()), profile=profile)
    print(json.dumps({"stage": str(profile.stage), "files": len(inventory["files"]), "androidExecution": False}))


if __name__ == "__main__":
    main()
