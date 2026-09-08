"""Install our verified GNU controller beside the intact official client.

The phone workspace must be stopped. This does not activate the workspace,
replace an official file, or claim that a static ELF check proves execution.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
DATA = "/data/user/0/app.foldgpt"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--compatibility", type=Path, required=True)
    parser.add_argument("--patch-sha256", required=True)
    parser.add_argument("--apk-sha256", required=True)
    args = parser.parse_args()
    for path in (args.package, args.compatibility):
        path.resolve(strict=True).relative_to(ROOT)
    with tarfile.open(args.package) as archive:
        members = archive.getmembers()
        expected = {"codex", "codex-code-mode-host", "manifest.json"}
        if len(members) != len(expected) or {m.name for m in members} != expected:
            raise ValueError("Unexpected engine package inventory")
        if any(not m.isfile() or m.size > 512 * 1024 * 1024 for m in members):
            raise ValueError("Engine package requires bounded regular files")
        payload = {m.name: archive.extractfile(m).read() for m in members}
    manifest = json.loads(payload["manifest.json"])
    if manifest.get("target") != "aarch64-unknown-linux-gnu" or manifest.get("patchSha256") != args.patch_sha256:
        raise ValueError("Engine source or target differs")
    inventory = manifest["files"]
    if len(inventory) != 2 or {item["path"] for item in inventory} != expected - {"manifest.json"}:
        raise ValueError("Engine manifest inventory differs")
    for item in inventory:
        data = payload[item["path"]]
        if digest(data) != item["sha256"] or len(data) != item["bytes"]:
            raise ValueError("Engine payload hash differs")
    compatibility = json.loads(args.compatibility.read_text())
    checked = compatibility.get("binaries", [])
    if (compatibility.get("passed") is not True or len(checked) != 2
            or {item["binary"] for item in checked} != expected - {"manifest.json"}):
        raise ValueError("Missing static compatibility result")
    for item in checked:
        if item.get("passed") is not True or digest(payload[item["binary"]]) != item["sha256"]:
            raise ValueError("Compatibility report describes another binary")
    trial = uuid.uuid4().hex[:8]
    output = ROOT / "downloads/native-engine-device-20260908" / trial
    output.mkdir(parents=True, exist_ok=False)
    adb = [str(Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/platform-tools/adb.exe"), "-s", "R3GL808JN4A"]
    commands = []
    report = {"installed": False, "runtimeQualified": False, "trial": trial,
              "packageSha256": digest(args.package.read_bytes()), "engineManifest": manifest}

    def run(argv, data=None, check=True, timeout=30):
        proc = subprocess.run(adb + ["exec-in" if data is not None else "shell", shlex.join(argv)],
                              input=data, capture_output=True, timeout=timeout)
        commands.append({"argv": argv, "code": proc.returncode,
            "stdout": proc.stdout.decode("utf-8", "replace"), "stderr": proc.stderr.decode("utf-8", "replace")})
        if check:
            proc.check_returncode()
        return proc.stdout.decode("utf-8").strip()

    def app(*argv, **kwargs):
        return run(["run-as", "app.foldgpt", *argv], **kwargs)

    def private_path(path):
        # run-as observes the declared /data/user/0 system prefix.
        if app("readlink", "-f", path) != path:
            raise ValueError("Unexpected alias in installation path: " + path)

    try:
        report["bootBefore"] = run(["cat", "/proc/sys/kernel/random/boot_id"])
        package_paths = run(["pm", "path", "app.foldgpt"]).splitlines()
        if len(package_paths) != 1 or not package_paths[0].startswith("package:/data/app/"):
            raise ValueError("Unexpected FoldGPT APK path")
        apk = package_paths[0].removeprefix("package:")
        if run(["sha256sum", apk]).split()[0] != args.apk_sha256:
            raise ValueError("Installed FoldGPT APK differs")
        status = json.loads(app("cat", "files/native-executor-status.json"))
        session, remote = (status.get(key) or {} for key in ("lastNativeSessionStatus", "lastRemoteStatus"))
        pid = session.get("bootstrapPid")
        if (status.get("state") != "closed" or not isinstance(pid, int) or pid <= 0
                or remote.get("bootstrapPid") != pid
                or any(item.get("cleanupComplete") is not True or item.get("bootstrapReaped") is not True
                       or item.get("ownerRetained") is not False or item.get("waitStatus") != 0
                       or item.get("setupError") is not None
                       or any(item.get(key) is not False for key in ("transportFailed", "quarantined", "refusedBeforeFork"))
                       for item in (session, remote))):
            raise ValueError("Native owner must be closed with completed cleanup")
        if run(["sh", "-c", 'if [ -d "$1" ]; then printf present; fi', "foldgpt-install", "/proc/" + str(pid)]):
            raise ValueError("Previous native owner is still present")
        uid = app("id", "-u")
        rows = run(["ps", "-A", "-o", "UID,PID,NAME"]).splitlines()[1:]
        if any(len(r.split()) == 3 and r.split()[0] == uid and
               ("proot" in r.split()[2].lower() or "codex" in r.split()[2].lower()
                or "chatgpt" in r.split()[2].lower() or r.split()[2] == "app.foldgpt:runtime") for r in rows):
            raise ValueError("FoldGPT workspace must be stopped before installation")
        root = DATA + "/files/debian"
        for relative in ("", "/usr", "/usr/local", "/usr/local/bin"):
            private_path(root + relative)
        report["deviceLibraries"] = {}
        for name, item in compatibility["libraries"].items():
            if Path(name).name != name:
                raise ValueError("Unexpected library name in compatibility report")
            actual = app("sha256sum", root + "/usr/lib/aarch64-linux-gnu/" + name).split()[0]
            if actual != item["sha256"]:
                raise ValueError("Phone library differs from static compatibility input: " + name)
            report["deviceLibraries"][name] = actual
        official = ("usr/lib/chatgpt/ChatGPT", "usr/lib/chatgpt/resources/app.asar", "usr/lib/chatgpt/resources/codex")
        report["officialBefore"] = {name: app("sha256sum", root + "/" + name, timeout=90).split()[0] for name in official}
        library = root + "/usr/local/libexec"
        app("mkdir", "-p", library)
        private_path(library)
        staging = library + "/foldgpt-install-" + trial
        app("mkdir", "-m", "700", staging)
        files = {"codex-native": payload["codex"], "codex-code-mode-host": payload["codex-code-mode-host"],
                 "engine-manifest.json": payload["manifest.json"]}
        bundle = io.BytesIO()
        with tarfile.open(fileobj=bundle, mode="w") as archive:
            for name, data in files.items():
                entry = tarfile.TarInfo(name)
                entry.size, entry.mode, entry.uid, entry.gid = len(data), 0o755 if name != "engine-manifest.json" else 0o644, int(uid), int(uid)
                archive.addfile(entry, io.BytesIO(data))
        app("tar", "-xf", "-", "-C", staging, data=bundle.getvalue(), timeout=120)
        for name, data in files.items():
            if app("sha256sum", staging + "/" + name).split()[0] != digest(data):
                raise ValueError("Transferred controller bytes differ")
        destination = library + "/foldgpt"
        old = app("sh", "-c", 'if [ -e "$1" ] || [ -L "$1" ]; then printf present; fi', "foldgpt-install", destination)
        if old:
            private_path(destination)
            backup = library + "/foldgpt-before-" + trial
            app("mv", destination, backup)
            report["previousEngine"] = backup
        app("mv", staging, destination)
        wrapper = (ROOT / "tools/executor/foldgpt-codex-native.sh").read_bytes().replace(b"\r\n", b"\n")
        wrapper_path = root + "/usr/local/bin/foldgpt-codex-native"
        temp_wrapper = wrapper_path + "." + trial
        if app("sh", "-c", 'if [ -e "$1" ] || [ -L "$1" ]; then printf present; fi', "foldgpt-install", wrapper_path):
            private_path(wrapper_path)
            app("cp", "-p", wrapper_path, wrapper_path + ".before-" + trial)
        app("sh", "-c", 'umask 077; set -C; cat > "$1"', "foldgpt-install", temp_wrapper, data=wrapper)
        if app("sha256sum", temp_wrapper).split()[0] != digest(wrapper):
            raise ValueError("Transferred wrapper bytes differ")
        app("chmod", "755", temp_wrapper)
        app("mv", "-f", temp_wrapper, wrapper_path)
        for name, data in files.items():
            if app("sha256sum", destination + "/" + name).split()[0] != digest(data):
                raise ValueError("Installed controller bytes differ")
        report["wrapperSha256"] = digest(wrapper)
        report["destination"] = destination
        report["bootAfter"] = run(["cat", "/proc/sys/kernel/random/boot_id"])
        if report["bootBefore"] != report["bootAfter"]:
            raise ValueError("Phone boot changed during installation")
        report["officialAfter"] = {name: app("sha256sum", root + "/" + name, timeout=90).split()[0] for name in official}
        if report["officialBefore"] != report["officialAfter"]:
            raise ValueError("Official Linux client changed during installation")
        report["installed"] = True
    except BaseException as error:
        report["error"] = type(error).__name__ + ": " + str(error)
    finally:
        (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(output), **report}))
    return 0 if report["installed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
