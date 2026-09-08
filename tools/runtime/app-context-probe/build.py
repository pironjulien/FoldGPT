"""Build a separate diagnostic APK, without Gradle or any device operation."""
import ast
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEFAULT_APK = ROOT / "downloads/native-production-20260908/foldgpt-native-candidate-r25.apk"
DEFAULT_HASH = "2618abba092af33ac387906d75b57ecfd7b76ec7aa02d80b6c20fee4f44a28a3"
BUILD = None
SDK = Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk"
TOOLS = SDK / "build-tools/36.0.0"
PLATFORM = SDK / "platforms/android-37.0/android.jar"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(name, args):
    value = subprocess.run([str(v) for v in args], cwd=HERE, capture_output=True, timeout=120)
    (BUILD / (name + ".log")).write_bytes(value.stdout + value.stderr)
    value.check_returncode()


def main():
    global BUILD
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-apk", type=Path, default=DEFAULT_APK)
    parser.add_argument("--expected-apk-sha256", default=DEFAULT_HASH)
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory beneath the project work directory")
    args = parser.parse_args()
    APK = args.source_apk.resolve(strict=True)
    EXPECTED = args.expected_apk_sha256
    if len(EXPECTED) != 64 or any(c not in "0123456789abcdef" for c in EXPECTED):
        raise ValueError("Explicit lowercase SHA-256 required")
    BUILD = args.output.resolve()
    if not BUILD.is_relative_to((ROOT / "work").resolve()) or BUILD == (ROOT / "work").resolve():
        raise ValueError("Diagnostic artifacts must remain under this project's work directory")
    if BUILD.exists():
        raise FileExistsError("Retain previous build evidence; use a separate revision directory")
    BUILD.mkdir(parents=True)
    frozen = BUILD / "source"
    frozen.mkdir()
    for name in ("build.py", "probe.py", "ContextProbeService.java", "AndroidManifest.xml"):
        shutil.copyfile(HERE / name, frozen / name)
    assert sha(APK.read_bytes()) == EXPECTED, "r25 APK bytes differ"
    ast.parse((HERE / "probe.py").read_text())
    assets = BUILD / "assets"
    assets.mkdir()
    inventory = {"schema": "foldgpt.app-context-payload.v1", "r25ApkSha256": EXPECTED,
                 "libraries": {}, "payload": {}, "aliases": [], "androidExecuted": False}
    with zipfile.ZipFile(APK) as original:
        runtime = json.loads(original.read("assets/foldgpt-python-runtime.json"))
        sources = json.loads(original.read("assets/foldgpt-executor-manifest.json"))
        def payload(relative, content, expected):
            assert sha(content) == expected, relative
            target = assets / "payload" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            inventory["payload"][relative] = expected
        for row in runtime["dataFiles"]:
            data = original.read("assets/bionic-python/" + row["path"])
            assert len(data) == row["bytes"]
            payload("python/" + row["path"], data, row["sha256"])
        for row in sources:
            if row["path"].startswith("tools/"):
                payload("project/" + row["path"], original.read("assets/foldgpt-executor/" + row["path"]), row["sha256"])
        data = (HERE / "probe.py").read_bytes()
        payload("probe.py", data, sha(data))
        inventory["aliases"] = runtime["runtimeAliases"]
        for row in runtime["nativeFiles"]:
            data = original.read("lib/arm64-v8a/" + row["name"])
            assert sha(data) == row["sha256"]
            inventory["libraries"][row["name"]] = row["sha256"]
        (assets / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
        classes = BUILD / "classes"
        classes.mkdir()
        run("javac", [shutil.which("javac"), "-encoding", "UTF-8", "-source", "17", "-target", "17", "-classpath", PLATFORM,
                      "-d", classes, HERE / "ContextProbeService.java"])
        dex = BUILD / "dex"
        dex.mkdir()
        # Invoke the official D8 Java entry point directly, avoiding shell .bat execution.
        run("d8", [shutil.which("java"), "-cp", TOOLS / "lib/d8.jar", "com.android.tools.r8.D8",
                   "--lib", PLATFORM, "--min-api", "30", "--output", dex, *classes.rglob("*.class")])
        base = BUILD / "base.apk"
        run("aapt2", [TOOLS / "aapt2.exe", "link", "-I", PLATFORM, "--manifest", HERE / "AndroidManifest.xml",
                      "-A", assets, "--min-sdk-version", "30", "--target-sdk-version", "37", "-o", base])
        with zipfile.ZipFile(base, "a", compression=zipfile.ZIP_DEFLATED) as package:
            package.write(dex / "classes.dex", "classes.dex")
            for name in inventory["libraries"]:
                package.writestr("lib/arm64-v8a/" + name, original.read("lib/arm64-v8a/" + name))
    aligned = BUILD / "aligned.apk"
    run("zipalign", [TOOLS / "zipalign.exe", "-f", "-P", "16", "4", base, aligned])
    # This fresh diagnostic-only key has no production authority. Kept inside work/.
    key = BUILD / "diagnostic-only.p12"
    run("keytool", [Path(shutil.which("java")).parent / "keytool.exe", "-genkeypair", "-keystore", key,
                    "-storepass", "diagnostic-only", "-keypass", "diagnostic-only", "-alias", "probe", "-keyalg", "RSA",
                    "-keysize", "2048", "-validity", "30", "-dname", "CN=FoldGPT isolated diagnostic"])
    final = BUILD / "foldgpt-app-context-probe.apk"
    signer = [shutil.which("java"), "-jar", TOOLS / "lib/apksigner.jar"]
    run("sign", [*signer, "sign", "--ks", key, "--ks-pass", "pass:diagnostic-only", "--key-pass", "pass:diagnostic-only",
                 "--out", final, aligned])
    run("signature", [*signer, "verify", "--verbose", "--print-certs", final])
    with zipfile.ZipFile(final) as package:
        for name, expected in inventory["libraries"].items():
            assert sha(package.read("lib/arm64-v8a/" + name)) == expected
        for name, expected in inventory["payload"].items():
            assert sha(package.read("assets/payload/" + name)) == expected
    result = {"apk": str(final), "sha256": sha(final.read_bytes()), "bytes": final.stat().st_size,
              "libraries": len(inventory["libraries"]), "payloadFiles": len(inventory["payload"]),
              "r25ApkSha256": EXPECTED, "javaSha256": sha((HERE / "ContextProbeService.java").read_bytes()),
              "probeSha256": sha((HERE / "probe.py").read_bytes()), "compiledAndVerified": True, "androidExecuted": False}
    (BUILD / "build-report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
