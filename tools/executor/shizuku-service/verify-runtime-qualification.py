"""Preserve and verify the separate runtime APK entirely on the PC."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

from runtime_qualification_profile import CERTIFICATE, HERE, REPO, V1, get_profile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_archive(apk, stage=None, profile=V1):
    BASE, PACKAGE = profile.base, profile.package
    if stage is None:
        stage = profile.stage
    inventory = json.loads((stage / "build-inventory.json").read_text())
    if (inventory.get("schema") != "foldgpt.runtime-qualification-build.v1" or inventory.get("package") != PACKAGE
            or inventory.get("base") != BASE or inventory.get("androidExecution") is not False):
        raise ValueError("Runtime stage identity differs")
    for entry in inventory["files"]:
        path = stage / entry["path"]
        if not path.resolve().is_relative_to(stage.resolve()) or sha(path.read_bytes()) != entry["sha256"]:
            raise ValueError("Runtime staging inventory differs: " + entry["path"])
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate APK entry")
        assets = {"assets/" + path.relative_to(stage / "assets").as_posix(): path.read_bytes()
                  for path in (stage / "assets").rglob("*") if path.is_file()}
        bootstrap = HERE / "transport/src/main/assets/foldgpt-executor/foldgpt_shizuku_bootstrap.py"
        assets["assets/foldgpt-executor/foldgpt_shizuku_bootstrap.py"] = bootstrap.read_bytes()
        if {name for name in names if name.startswith("assets/")} != set(assets):
            raise ValueError("Runtime APK assets are not the exact reviewed set")
        for name, data in assets.items():
            if archive.read(name) != data:
                raise ValueError("Runtime APK asset differs: " + name)
        config = json.loads(assets["assets/foldgpt-executor-deployment.json"])
        if (config["packageName"] != PACKAGE or config["workspace"] != BASE + "/workspace"
                or config["brokerDirectory"] != BASE + "/broker" or config["pythonRuntime"]["path"] != BASE + "/python"
                or config["backendFactory"] != profile.backend_factory):
            raise ValueError("Runtime APK deployment identity differs")
        manifest = json.loads(assets["assets/foldgpt-executor-manifest.json"])
        for entry in manifest:
            if sha(archive.read("assets/foldgpt-executor/" + entry["path"])) != entry["sha256"]:
                raise ValueError("Runtime source manifest differs")
        native = {"lib/arm64-v8a/" + name: digest for name, digest in config["nativeLibraries"].items()}
        if ("lib/arm64-v8a/libfoldgpt_qualification_worker.so" in native
                or {name for name in names if name.startswith("lib/")} != set(native)):
            raise ValueError("Runtime APK native set contains an unrelated or missing ELF")
        for name, digest in native.items():
            data = archive.read(name)
            if not data.startswith(b"\x7fELF") or sha(data) != digest:
                raise ValueError("Runtime APK native hash differs: " + name)
        dex = b"".join(archive.read(name) for name in names if name.endswith(".dex"))
        for literal in ("runtime-v" + str(profile.version), "foldgpt-runtime-qualification-v" + str(profile.version), profile.identity.run_action,
                        ".RUNTIME_AUTHORIZE", "foldgpt.android-runtime-rpc.v1"):
            if literal.encode() + b"\0" not in dex:
                raise ValueError("Runtime DEX identity is missing: " + literal)
        if b"foldgpt.android-kernel-rpc.v1\0" in dex:
            raise ValueError("Runtime DEX unexpectedly includes the kernel result parser")
    return {"nativeHashesVerified": len(native), "sourceHashesVerified": len(manifest),
            "stageInventorySha256": sha((stage / "build-inventory.json").read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    profile = get_profile(args.version)
    APK, BASE, BUILD, INPUTS, PACKAGE = profile.apk, profile.base, profile.build, profile.inputs, profile.package
    target = args.output.resolve(); target.mkdir(parents=True, exist_ok=False)
    apk = target / APK.name; shutil.copyfile(APK, apk)
    checks = verify_archive(apk, profile=profile)
    sdk = Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/build-tools/36.0.0"
    def run(name, command):
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        (target / name).write_text(result.stdout, encoding="utf-8"); return result.stdout
    signature = run("signature.txt", [str(sdk / "apksigner.bat"), "verify", "--verbose", "--print-certs", str(apk)])
    if "Signer #1 certificate SHA-256 digest: " + CERTIFICATE not in signature or "Number of signers: 1" not in signature:
        raise ValueError("Runtime APK signer differs")
    binary = run("binary-manifest.txt", [str(sdk / "aapt.exe"), "dump", "xmltree", str(apk), "AndroidManifest.xml"])
    expected = ('package="' + PACKAGE + '"', '"' + PACKAGE + '.shizuku"',
        '"app.foldgpt.shizukuexec.ExecutorProvider"', '"app.foldgpt.runtimequalification.RuntimeQualificationActivity"',
        '"android.permission.DUMP"', '"android.permission.INTERACT_ACROSS_USERS_FULL"',
        'android:versionCode(0x0101021b)=(type 0x10)0x' + format(profile.version, 'x'))
    if not all(value in binary for value in expected) or binary.count("E: provider ") != 1 or binary.count("E: activity ") != 1:
        raise ValueError("Runtime Android manifest differs")
    tests = []
    for module in ("transport", "runtimequalification"):
        suites = list((BUILD / "modules" / module / "test-results/testDebugUnitTest").glob("TEST-*.xml"))
        if not suites:
            raise ValueError("Actual JVM test results are absent: " + module)
        for path in sorted(suites):
            suite = ET.parse(path).getroot()
            if any(int(suite.get(key, 0)) != 0 for key in ("failures", "errors", "skipped")) or int(suite.get("tests", 0)) <= 0:
                raise ValueError("Runtime/transport JVM tests did not all pass")
            tests.append({"module": module, "name": suite.get("name"), "tests": int(suite.get("tests")), "sha256": sha(path.read_bytes())})
            destination = target / "jvm-tests" / module; destination.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination / path.name)
    sources = {HERE / name for name in ("settings.gradle", "build.gradle", "transport/build.gradle",
        "runtimequalification/build.gradle", "runtime_qualification_profile.py", "stage-runtime-qualification.py",
        "verify-runtime-qualification.py", "test_runtime_qualification_packaging.py")}
    sources.add(INPUTS)
    for name in ("collect-runtime-qualification.py", "test_runtime_qualification_collector.py",
                 "snapshot-native-qualification.py", "runtime_qualification_identity.py"):
        sources.add(REPO / "tools/runtime" / name)
    for directory in (HERE / "transport/src", HERE / "runtimequalification/src"):
        sources.update(path for path in directory.rglob("*") if path.is_file() and
                       path.suffix in {".java", ".aidl", ".xml", ".py", ".c", ".h", ".txt", ".json"})
    rows = []
    for path in sorted(sources):
        relative = path.relative_to(REPO); destination = target / "diagnostic-sources" / relative
        destination.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, destination)
        rows.append({"path": relative.as_posix(), "sha256": sha(destination.read_bytes())})
    report = {"schema": "foldgpt.runtime-qualification-apk.v1", "verified": True, "androidExecution": False,
        "package": PACKAGE, "base": BASE, "versionCode": profile.version, "apkSha256": sha(apk.read_bytes()),
        "certificateSha256": CERTIFICATE, **checks, "jvmTests": tests, "diagnosticSources": rows}
    (target / "provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key not in ("jvmTests", "diagnosticSources")}))


if __name__ == "__main__":
    main()
