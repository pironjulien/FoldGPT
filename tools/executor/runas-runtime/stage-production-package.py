"""Package the explicit native candidate without claiming end-to-end qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]
TRANSPORT = ROOT / "tools/executor/shizuku-service/transport/src/main/assets/foldgpt-executor"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-stage", type=Path, required=True)
    parser.add_argument("--admission-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-v2", action="store_true")
    args = parser.parse_args()
    stage, admission, output = (getattr(args, name).resolve() for name in ("native_stage", "admission_build", "output"))
    for path in (stage, admission, output):
        path.relative_to(ROOT)
    inventory = json.loads((stage / "manifest.json").read_text())
    for item in inventory["files"]:
        data = (stage / item["path"]).read_bytes()
        if len(data) != item["bytes"] or digest(data) != item["sha256"]:
            raise ValueError("Frozen native stage differs: " + item["path"])
    build = json.loads((admission / "build.json").read_text())
    if digest((stage / "runtime-inventory.h").read_bytes()) != build["inventorySha256"]:
        raise ValueError("Admission inventory differs from the selected native stage")
    bootstrap = (admission / "libfoldgpt_native_bootstrap.so").read_bytes()
    if digest(bootstrap) != build["executableSha256"]:
        raise ValueError("Admission build digest differs")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(stage / "assets", output / "assets")
    shutil.copytree(stage / "jniLibs", output / "jniLibs")
    assets, jni = output / "assets", output / "jniLibs/arm64-v8a"
    (jni / "libfoldgpt_native_bootstrap.so").write_bytes(bootstrap)
    native = {p.name: digest(p.read_bytes()) for p in sorted(jni.iterdir())}
    # The frozen transport module is the unique packager of these same bytes.
    for name in ("libfoldgpt_shizuku_transport.so", "libfoldgpt_bionic_cwd.so"):
        (jni / name).unlink()
    runtime_path = "/data/user/0/app.foldgpt/files/native-runtime-v1/python"
    marker = "@nativeLibraryDir/"
    config = {
        "schema": "foldgpt.native.deployment.v1", "packageName": "app.foldgpt",
        "pythonLibrary": "libfoldgpt_python_cli.so", "pythonSha256": native["libfoldgpt_python_cli.so"],
        "nativeLibraries": native,
        "pythonRuntime": {"path": runtime_path, "manifestAsset": "foldgpt-python-runtime.json",
                          "manifestSha256": digest((assets / "foldgpt-python-runtime.json").read_bytes())},
        "backendFactory": "tools.executor.bionic-supervisor.factory:factory",
        "backendOptions": {
            "helper": marker + "libfoldgpt_native_files.so", "handleHelper": marker + "libfoldgpt_native_file_handle.so",
            "processRunner": marker + "libfoldgpt_bionic_supervisor.so",
            "executables": {"bash": marker + "libfoldgpt_bash.so", "python": marker + "libfoldgpt_python_cli.so",
                            "python3": marker + "libfoldgpt_python_cli.so"},
            "runtime": [{"path": path, "execute": execute} for path, execute in (
                ("/system/lib64", True), ("/system/bin", True), ("/apex/com.android.runtime", True),
                ("/linkerconfig/ld.config.txt", False), ("/dev/__properties__", False),
                ("/apex/com.android.tzdata/etc/tz/tzdata", False), (runtime_path, False))],
            "limits": {},
            "cwdShim": {"path": marker + "libfoldgpt_bionic_cwd.so", "sha256": native["libfoldgpt_bionic_cwd.so"]}}}
    (assets / "foldgpt-executor-deployment.json").write_text(json.dumps(config, indent=2) + "\n")
    if args.host_v2:
        runner = "libfoldgpt_host_supervisor.so"
        if runner not in native:
            raise ValueError("Explicit human v2 selection requires its attested native-stage ELF")
        (assets / "foldgpt-host-deployment.json").write_text(json.dumps({
            "schema": "foldgpt.host.v2", "runner": runner, "runnerSha256": native[runner]}, indent=2) + "\n")
    snapshot = json.loads((ROOT / "downloads/native-app-server-host-v3-20260908/manifest.json").read_text())
    source_paths = {entry["path"][len("package/"):] for entry in snapshot["files"]
                    if entry["path"].startswith("package/") and entry["path"].endswith(".py")}
    source_paths.update("tools/executor/" + name + ".py" for name in (
        "native_runtime_startup", "native_runtime_acquisition", "native_path_uri", "native_host_files", "native_host_files_channel",
        "native_host_bootstrap_v2"))
    source_paths.add("tools/executor/native_host_channel_v2.py")
    source_paths.update("tools/executor/bionic-supervisor/" + name + ".py" for name in (
        "host_policy", "host_wire", "host_processes"))
    source_manifest = []
    for relative in sorted(source_paths):
        source = ROOT / relative
        if not source.exists() and relative.endswith("/__init__.py"):
            data = b""
        else:
            data = source.read_bytes()
        compile(data, relative, "exec")
        target = assets / "foldgpt-executor" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        source_manifest.append({"path": relative, "sha256": digest(data)})
    for source in sorted(TRANSPORT.glob("*.py")):
        data = source.read_bytes()
        compile(data, source.name, "exec")
        (assets / "foldgpt-executor" / source.name).write_bytes(data)
        source_manifest.append({"path": source.name, "sha256": digest(data)})
    (assets / "foldgpt-executor-manifest.json").write_text(json.dumps(source_manifest, indent=2) + "\n")
    # Preserve the qualification's original bytes/scope. It proves the broker,
    # not this newly assembled application or the controller's PRoot bindings.
    evidence = (ROOT / "downloads/runas-broker-v2/device-reports/run_broker_v2.json").read_bytes()
    (assets / "foldgpt-executor-evidence.json").write_bytes(evidence)
    qualification = {"schema": "foldgpt.native.package.v1", "scope": "native-production-candidate",
        "androidProductionExecuted": False,
        "deploymentSha256": digest((assets / "foldgpt-executor-deployment.json").read_bytes()),
        "sourceManifestSha256": digest((assets / "foldgpt-executor-manifest.json").read_bytes()),
        "evidenceSha256": digest(evidence)}
    if args.host_v2:
        qualification["hostDeploymentSha256"] = digest((assets / "foldgpt-host-deployment.json").read_bytes())
    (assets / "foldgpt-executor-qualification.json").write_text(json.dumps(qualification, indent=2) + "\n")
    print(json.dumps({"output": str(output), "sources": len(source_manifest), "nativeLibraries": len(native),
                      "androidProductionExecuted": False}))


if __name__ == "__main__":
    main()
