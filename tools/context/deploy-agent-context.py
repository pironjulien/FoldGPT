"""Deploy and read back FoldGPT context on the authorized development APK.

Only named integration files are installed. The known launch script is replaced
after the guest synchronizer actually succeeds. No app restart, model request,
Android permission change, config rewrite or personal-history export occurs.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[2]
PREFIX = "files/debian/"
# Actual launcher used by the qualified foldgpt5 development installation.
PREVIOUS_LAUNCHER = "4648f7dc896c6612ea498810540518be7904b9cde4ae6507c1c592822127558c"
PAYLOAD = (
    ("tools/context/foldgpt_agent_context.py", "usr/local/lib/foldgpt/foldgpt_agent_context.py", "644"),
    ("config/agent-context/foldgpt.v1.json", "usr/local/share/foldgpt/agent-environment.v1.json", "644"),
    ("foldgpt-session.sh", "usr/local/bin/foldgpt-session", "700"),
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--previous-deployment", type=Path,
                        help="Successful prior deployment report whose exact source identities may be upgraded")
    args = parser.parse_args()
    adb = ["adb", "-s", args.serial]

    def shell(script, data=None):
        return subprocess.check_output(adb + ["shell", "-T", "run-as app.foldgpt /system/bin/sh -c " + shlex.quote(script)],
                                       input=data, timeout=60)

    def read(target):
        return subprocess.check_output(adb + ["exec-out", "run-as", "app.foldgpt", "cat", target], timeout=30)

    snapshots = [(source, target, mode, (REPO / source).read_bytes().replace(b"\r\n", b"\n"))
                 for source, target, mode in PAYLOAD]
    previous_files = {}
    if args.previous_deployment:
        previous_report = json.loads(args.previous_deployment.read_text(encoding="utf-8"))
        if previous_report.get("status") != "DEPLOYED_AND_READ_BACK":
            raise RuntimeError("Previous deployment was not completed")
        previous_files = {item["path"]: item["sha256"] for item in previous_report["files"]}
        if set(previous_files) != {PREFIX + item[1] for item in PAYLOAD}:
            raise RuntimeError("Previous deployment has a different file contract")
        if any(len(value) != 64 or any(c not in "0123456789abcdef" for c in value) for value in previous_files.values()):
            raise RuntimeError("Invalid previous deployment identities")
    launcher = read(PREFIX + PAYLOAD[-1][1])
    if sha(launcher) not in {PREVIOUS_LAUNCHER, sha(snapshots[-1][3])}:
        raise RuntimeError("Unreviewed launch script; no integration file was changed")
    evidence = REPO / "downloads/context" / ("android-" + uuid.uuid4().hex)
    evidence.mkdir(parents=True)
    (evidence / "previous-launcher.sh").write_bytes(launcher)
    report = {"schema": "foldgpt.context-deployment.v1", "status": "IN_PROGRESS", "files": [],
              "modelDeliveryVerified": False, "previousLauncherSha256": sha(launcher)}

    def install(source, target, mode, data):
        path = PREFIX + target
        previous = sha(launcher) if target == PAYLOAD[-1][1] else previous_files.get(path, sha(data))
        # Fixed, explicit paths under app-private files/debian; no link traversal.
        directories = list(reversed(PurePosixPath(path).parents))
        checks = ["set -eu", "umask 077"]
        for parent in directories:
            if str(parent) == ".":
                continue
            name = shlex.quote(str(parent))
            checks += [f"test ! -L {name}", f"if test -e {name}; then test -d {name}; else mkdir {name}; fi"]
        pathq = shlex.quote(path)
        checks += [f"test ! -L {pathq}",
                   f"if test -e {pathq}; then test -f {pathq}; test \"$(stat -c %h {pathq})\" = 1; "
                   f"test \"$(sha256sum {pathq} | cut -d ' ' -f 1)\" = {previous}; fi"]
        if target == PAYLOAD[-1][1]:
            checks += [f"test -f {pathq}"]
        scratch = path + ".foldgpt-" + uuid.uuid4().hex
        scratchq = shlex.quote(scratch)
        checks += ["set -C", f"cat > {scratchq}",
                   f"test \"$(sha256sum {scratchq} | cut -d ' ' -f 1)\" = {sha(data)}",
                   f"chmod {mode} {scratchq}", f"sync -f {scratchq}",
                   f"mv -f {scratchq} {pathq}", f"sync -f {shlex.quote(str(PurePosixPath(path).parent))}"]
        shell("\n".join(checks) + "\n", data)
        if read(path) != data:
            raise RuntimeError("Installed context source differs")
        (evidence / Path(source).name).write_bytes(data)
        report["files"].append({"path": path, "sha256": sha(data), "mode": mode})
        (evidence / "deployment.json").write_text(json.dumps(report, indent=2) + "\n")

    for item in snapshots[:-1]:
        install(*item)
    command = [sys.executable, str(REPO / "tools/device-shell.py"), "--serial", args.serial,
               "/usr/bin/python3", "-B", "/usr/local/lib/foldgpt/foldgpt_agent_context.py",
               "--guest-root", "/", "--manifest", "/usr/local/share/foldgpt/agent-environment.v1.json"]
    sync = subprocess.run(command, capture_output=True, timeout=60, check=True)
    report["synchronization"] = json.loads(sync.stdout)
    verify = subprocess.run(command + ["--check"], capture_output=True, timeout=60, check=True)
    if json.loads(verify.stdout) != report["synchronization"]:
        raise RuntimeError("Guest context readback differs")
    install(*snapshots[-1])
    report["status"] = "DEPLOYED_AND_READ_BACK"
    report["scope"] = "Actual integration files and global AGENTS synchronization; no client restart or model delivery proof"
    (evidence / "deployment.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "evidence": str(evidence),
                      "synchronization": report["synchronization"]}, indent=2))


if __name__ == "__main__":
    main()
