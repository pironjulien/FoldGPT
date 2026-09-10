"""Collect only named private diagnostic evidence and verify its real files.

Requires an explicit UUID-created fixture. Never reads client profiles, vaults,
credentials or arbitrary paths supplied by an RPC response.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", args.fixture):
        raise ValueError("Expected the exact diagnostic fixture UUID")
    remote = "cache/native-files-rpc-" + args.fixture
    adb = ["adb", "-s", args.serial]
    args.output.mkdir(parents=True, exist_ok=False)

    def run(*command):
        return subprocess.check_output(adb + ["exec-out", shlex.join(["run-as", "app.foldgpt", *command])], timeout=30)

    for name in ("report.json", "rpc-transcript.json", "fixture-output.txt", "server-stderr.txt", "android-completion.txt"):
        (args.output / name).write_bytes(run("cat", remote + "/" + name))
    report = json.loads((args.output / "report.json").read_bytes())
    if report.get("status") != "PASS" or report.get("schema") != "foldgpt.native-files-rpc-fixture.v1":
        raise ValueError("The actual diagnostic has not passed")
    uid = int(run("id", "-u").strip())
    for name in ("observation", "serverObservation"):
        value = report[name]
        if (value["uid"] != uid or value["machine"] != "aarch64"
                or value["status"]["TracerPid"] != "0" or value["status"]["Seccomp"] != "2"
                or int(value["status"]["CapEff"], 16) != 0 or int(value["status"]["CapPrm"], 16) != 0
                or not value["securityContext"].startswith("u:r:untrusted_app")):
            raise ValueError("The real server/fixture Android execution context differs")
    if not (args.output / "android-completion.txt").read_text().startswith("PASS uid=" + str(uid) + " "):
        raise ValueError("Missing successful Android service completion")
    with zipfile.ZipFile(args.apk) as apk:
        helper = hashlib.sha256(apk.read("lib/arm64-v8a/libfoldgpt-native-files.so")).hexdigest()
        launcher = hashlib.sha256(apk.read("lib/arm64-v8a/libfoldgpt_python.so")).hexdigest()
    if helper != report["nativeHelperSha256"] or launcher != report["observation"]["androidLauncherSha256"]:
        raise ValueError("Reported actual native executables differ from the checked APK")
    expected = {"value": b"native-write-3", ".git/config": b"protected", "private/secret": b"private",
                "dossier é/子/data": b"actual\x00bytes"}
    for name, data in expected.items():
        if run("cat", remote + "/workspace/" + name) != data:
            raise ValueError("Independent ADB fixture file verification failed")
    physical = run("stat", "-c", "%d:%i:%a:%h", remote + "/workspace/value").decode().strip().split(":")
    if int(physical[0]) != report["workspace"]["device"] or int(physical[1]) != report["workspace"]["valueInode"] or physical[3] != "1":
        raise ValueError("Real fixture inode differs from the recorded same-inode exercise")
    for name in ("missing", ".git/forbidden", "absent", "alias"):
        result = subprocess.run(adb + ["shell", shlex.join(["run-as", "app.foldgpt", "test", "-e", remote + "/workspace/" + name])], timeout=10)
        if result.returncode != 1:
            raise ValueError("A rejected fixture target exists or inspection failed")
    transcript = json.loads((args.output / "rpc-transcript.json").read_bytes())
    if len(transcript) != report["rpcResponses"] or len(transcript) != 34:
        raise ValueError("Actual RPC transcript is incomplete")
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in args.output.iterdir() if path.is_file()}
    proof = {"status": "PASS", "uid": uid, "fixture": args.fixture, "rpcResponses": len(transcript),
             "independentFiles": len(expected), "valueIdentity": physical,
             "apkSha256": hashlib.sha256(args.apk.read_bytes()).hexdigest(), "evidenceSha256": hashes}
    (args.output / "independent-verification.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
