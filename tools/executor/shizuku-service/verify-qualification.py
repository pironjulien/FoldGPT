"""Verify and preserve one reviewed independent APK on Windows; no device operations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

from qualification_profiles import PROFILES, for_version

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
CERT = "30930ffce7c10b673e95e69f2d78bb9e60aa71132db3c21cdc15cf56df77fa16"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", type=int, choices=tuple(PROFILES), required=True)
    args = parser.parse_args(argv)
    profile = for_version(args.version)
    package, base = profile.package, profile.base
    target = args.output.resolve()
    target.mkdir(parents=True, exist_ok=False)
    stage = profile.stage
    source_apk = profile.apk
    apk = target / source_apk.name
    shutil.copyfile(source_apk, apk)
    inventory = json.loads((stage / "build-inventory.json").read_text())
    assert inventory["package"] == package and inventory["base"] == base
    for entry in inventory["files"]:
        assert sha((stage / entry["path"]).read_bytes()) == entry["sha256"]
    bootstrap = HERE / "transport/src/main/assets/foldgpt-executor/foldgpt_shizuku_bootstrap.py"
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assets = {"assets/" + path.relative_to(stage / "assets").as_posix(): path.read_bytes()
                  for path in (stage / "assets").rglob("*") if path.is_file()}
        assets["assets/foldgpt-executor/foldgpt_shizuku_bootstrap.py"] = bootstrap.read_bytes()
        assert {name for name in names if name.startswith("assets/")} == set(assets)
        assert all(archive.read(name) == data for name, data in assets.items())
        deployment = json.loads(assets["assets/foldgpt-executor-deployment.json"])
        assert deployment["packageName"] == package and deployment["workspace"] == base + "/workspace"
        assert deployment["brokerDirectory"] == base + "/broker"
        assert deployment["pythonRuntime"]["path"] == base + "/python"
        assert deployment["backendFactory"] == "tools.executor.bionic-supervisor." + profile.factory_module + ":factory"
        manifest = json.loads(assets["assets/foldgpt-executor-manifest.json"])
        for entry in manifest:
            assert sha(archive.read("assets/foldgpt-executor/" + entry["path"])) == entry["sha256"]
        native = {"lib/arm64-v8a/" + name: digest for name, digest in deployment["nativeLibraries"].items()}
        transport = REPO / "tools/executor/shizuku-lab/build/frozen-transport-jni/arm64-v8a"
        for name in ("libfoldgpt_shizuku_transport.so", "libfoldgpt_bionic_cwd.so"):
            native["lib/arm64-v8a/" + name] = sha((transport / name).read_bytes())
        assert {name for name in names if name.startswith("lib/")} == set(native)
        assert len(native) == 84
        assert all(archive.read(name).startswith(b"\x7fELF") and sha(archive.read(name)) == digest
                   for name, digest in native.items())
        dex = b"".join(archive.read(name) for name in names if name.endswith(".dex"))
        assert all(value.encode() + b"\0" in dex for value in
                   ("kernel-v" + str(profile.version), "foldgpt-kernel-qualification-v" + str(profile.version),
                    ".KERNEL_RUN_FIXED_V" + str(profile.version), ".KERNEL_AUTHORIZE"))
    sdk = Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/build-tools/36.0.0"
    def run(name, command):
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        (target / name).write_text(result.stdout, encoding="utf-8")
        return result.stdout
    signature = run("signature.txt", [str(sdk / "apksigner.bat"), "verify", "--verbose", "--print-certs", str(apk)])
    assert "Signer #1 certificate SHA-256 digest: " + CERT in signature
    assert "Number of signers: 1" in signature
    binary = run("binary-manifest.txt", [str(sdk / "aapt.exe"), "dump", "xmltree", str(apk), "AndroidManifest.xml"])
    assert 'package="' + package + '"' in binary
    assert '"' + package + '.shizuku"' in binary
    assert "android:versionCode(0x0101021b)=(type 0x10)" + hex(profile.version) in binary
    assert binary.count("E: provider ") == 1 and binary.count("E: activity ") == 1
    assert '"app.foldgpt.shizukuexec.ExecutorProvider"' in binary
    assert '"app.foldgpt.kernelqualification.QualificationActivity"' in binary
    assert '"android.permission.DUMP"' in binary and '"android.permission.INTERACT_ACROSS_USERS_FULL"' in binary
    tests = []
    for path in sorted((profile.build_root / "modules/transport/test-results/testDebugUnitTest").glob("TEST-*.xml")):
        suite = ET.parse(path).getroot()
        assert all(int(suite.get(key, 0)) == 0 for key in ("failures", "errors", "skipped"))
        tests.append({"name": suite.get("name"), "tests": int(suite.get("tests")), "sha256": sha(path.read_bytes())})
        (target / "jvm-tests").mkdir(exist_ok=True)
        shutil.copyfile(path, target / "jvm-tests" / path.name)
    assert sum(suite["tests"] for suite in tests) == 24
    sources = {HERE / name for name in ("build.gradle", "settings.gradle", "stage-qualification.py",
               "verify-qualification.py", "verify-qualification-v11.py", "qualification_profiles.py",
               "test_qualification_packaging.py", "transport/build.gradle", "qualification/build.gradle")}
    sources.add(profile.inputs)
    for directory in (HERE / "transport/src", HERE / "qualification/src"):
        sources.update(path for path in directory.rglob("*") if path.is_file() and
                       path.suffix in {".java", ".aidl", ".xml", ".py", ".c", ".h", ".txt"})
    rows = []
    for path in sorted(sources):
        relative = path.relative_to(REPO)
        copied = target / "diagnostic-sources" / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, copied)
        rows.append({"path": relative.as_posix(), "sha256": sha(copied.read_bytes())})
    report = {"schema": "foldgpt.independent-qualification-apk.v1", "verified": True,
              "androidExecution": False, "package": package, "versionCode": profile.version, "base": base,
              "apkSha256": sha(apk.read_bytes()), "certificateSha256": CERT,
              "nativeHashesVerified": len(native), "sourceHashesVerified": len(manifest),
              "stageInventorySha256": sha((stage / "build-inventory.json").read_bytes()),
              "jvmTests": tests, "diagnosticSources": rows}
    (target / "provenance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"jvmTests", "diagnosticSources"}}))


if __name__ == "__main__":
    main()
