"""Rebuild the Android Java adapter against a frozen production payload."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "downloads/native-production-20260908"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    args = parser.parse_args()
    if not args.candidate.isalnum():
        raise ValueError("Candidate must be an ordinary alphanumeric name")
    apk = OUT / f"foldgpt-native-candidate-{args.candidate}.apk"
    log_path = OUT / f"gradle-package-root-{args.candidate}.log"
    if apk.exists() or log_path.exists():
        raise FileExistsError("Existing attempts are retained")
    fixed = OUT / "frozen-transport-root"
    env = dict(os.environ)
    env["JAVA_HOME"] = r"C:\Program Files\Microsoft\jdk-21.0.12.8-hotspot"
    gradle = Path(os.environ["USERPROFILE"]) / ".gradle/wrapper/dists/gradle-9.7.1-bin/1w1c7tv4s851m17nbqdsro2tv/gradle-9.7.1/bin/gradle.bat"
    command = [str(gradle), "--no-daemon", "--max-workers=2", "--no-parallel",
        "-Dorg.gradle.jvmargs=-Xmx1g -Dfile.encoding=UTF-8",
        "-PfoldgptExecutorAssets=" + str(OUT / "package-r3/assets"),
        "-PfoldgptExecutorJni=" + str(OUT / "package-r3/jniLibs"),
        "-PfoldgptFrozenTransportJni=" + str(fixed),
        ":app:assembleDebug", ":shizukuTransport:testDebugUnitTest"]
    with log_path.open("xb") as log:
        result = subprocess.run(command, cwd=ROOT / "android", env=env, stdout=log, stderr=subprocess.STDOUT)
    report = {"argv": command, "exitCode": result.returncode, "log": str(log_path)}
    (OUT / f"root-{args.candidate}-build-command.json").write_text(json.dumps(report, indent=2) + "\n")
    result.check_returncode()
    data = (ROOT / "android/app/build/outputs/apk/debug/app-debug.apk").read_bytes()
    apk.write_bytes(data)
    print(json.dumps({"apk": str(apk), "apkSha256": hashlib.sha256(data).hexdigest()}))


if __name__ == "__main__":
    main()
