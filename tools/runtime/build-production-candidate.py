"""Rebuild the Android Java adapter against a frozen production payload."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "downloads/native-production-20260908"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from executor_package import validate_package, verify_apk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--package", type=Path, required=True,
                        help="Reviewed executor package containing assets/ and jniLibs/")
    args = parser.parse_args()
    if not args.candidate.isalnum():
        raise ValueError("Candidate must be an ordinary alphanumeric name")
    apk = OUT / f"foldgpt-native-candidate-{args.candidate}.apk"
    log_path = OUT / f"gradle-package-root-{args.candidate}.log"
    if apk.exists() or log_path.exists():
        raise FileExistsError("Existing attempts are retained")
    package = args.package.resolve(strict=True)
    package.relative_to(ROOT)
    package_report = validate_package(package)
    fixed = OUT / "frozen-transport-root"
    env = dict(os.environ)
    env["JAVA_HOME"] = r"C:\Program Files\Microsoft\jdk-21.0.12.8-hotspot"
    # Builds and transient output belong to the project, including Gradle state.
    for name, relative in (("GRADLE_USER_HOME", "work/build-cache/gradle"),
                           ("TEMP", "work/build-cache/tmp"),
                           ("TMP", "work/build-cache/tmp")):
        local = ROOT / relative
        local.mkdir(parents=True, exist_ok=True)
        env[name] = str(local)
    gradle = Path(os.environ["USERPROFILE"]) / ".gradle/wrapper/dists/gradle-9.7.1-bin/1w1c7tv4s851m17nbqdsro2tv/gradle-9.7.1/bin/gradle.bat"
    command = [str(gradle), "--no-daemon", "--max-workers=2", "--no-parallel",
        "-Dorg.gradle.jvmargs=-Xmx1g -Dfile.encoding=UTF-8",
        "-PfoldgptExecutorAssets=" + str(package / "assets"),
        "-PfoldgptExecutorJni=" + str(package / "jniLibs"),
        "-PfoldgptRequireExecutor=true",
        "-PfoldgptFrozenTransportJni=" + str(fixed),
        ":app:assembleDebug", ":shizukuTransport:testDebugUnitTest"]
    with log_path.open("xb") as log:
        result = subprocess.run(command, cwd=ROOT / "android", env=env, stdout=log, stderr=subprocess.STDOUT)
    report = {"argv": command, "exitCode": result.returncode, "log": str(log_path)}
    (OUT / f"root-{args.candidate}-build-command.json").write_text(json.dumps(report, indent=2) + "\n")
    result.check_returncode()
    built = ROOT / "android/app/build/outputs/apk/debug/app-debug.apk"
    # Keep the explicit package check above as the pre-build admission, then
    # verify the actual ZIP before exposing it as a candidate.  The native
    # verifier also checks the signed inventories, Python data and source
    # closure that a simple JNI filename check cannot see.
    apk_verification = OUT / f"apk-verification-{args.candidate}.json"
    subprocess.run([sys.executable,
                    str(ROOT / "tools/executor/runas-runtime/verify-production-apk.py"),
                    str(built), "--output", str(apk_verification)],
                   cwd=ROOT, check=True)
    subprocess.run([sys.executable,
                    str(ROOT / "tools/install/verify-apk-contents.py"),
                    str(built), "--debug"], cwd=ROOT, check=True)
    apk_report = verify_apk(built, package)
    data = built.read_bytes()
    apk.write_bytes(data)
    print(json.dumps({"apk": str(apk), "apkSha256": hashlib.sha256(data).hexdigest(),
                      "package": package_report, "embedding": apk_report,
                      "apkVerification": str(apk_verification)}))


if __name__ == "__main__":
    main()
