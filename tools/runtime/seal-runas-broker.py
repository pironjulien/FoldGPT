"""Independently check and preserve the completed V2 broker device evidence.

This reads the phone; it never starts or replays a qualification.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / "downloads/runas-broker-v2"
    destination = root / "recovery/verification/runas-broker-20260908"
    if destination.exists():
        raise FileExistsError("Preserved evidence must not be overwritten")
    verifier = root / "tools/executor/shizuku-service/runasbrokerqualificationv2/verify.py"
    spec = importlib.util.spec_from_file_location("broker_verifier", verifier)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = json.loads((source / "device-reports/run_broker_v2.json").read_text())
    result = module.verify(report)
    before = json.loads((source / "before-install/snapshot.json").read_text())
    after = json.loads((source / "after-run/snapshot.json").read_text())
    for field in ("bootId", "properties", "packages", "stayAwake"):
        if before[field] != after[field]:
            raise ValueError("Snapshot changed: " + field)
    if before.get("completed") is not True or after.get("completed") is not True:
        raise ValueError("Incomplete snapshots")
    target = report["installation"]["target"]
    if before["packages"]["app.foldgpt"] != [
        {"path": target["sourceDir"], "sha256": target["apkSha256"]}
    ]:
        raise ValueError("Target differs from independent APK hash")
    adb = Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/platform-tools/adb.exe"
    prefix = [str(adb), "-s", before["serial"], "shell"]
    commands = []

    def read(*args):
        completed = subprocess.run(prefix + list(args), capture_output=True, timeout=30)
        record = {"argv": list(args), "code": completed.returncode,
                  "stdout": completed.stdout.decode("utf-8", "replace"),
                  "stderr": completed.stderr.decode("utf-8", "replace")}
        commands.append(record)
        return record

    boot = read("cat", "/proc/sys/kernel/random/boot_id")
    if boot["code"] != 0 or boot["stdout"].strip() != after["bootId"]:
        raise ValueError("Live boot differs from qualified boot")
    pids = [result["bootstrapPid"], result["supervisorPid"], report["service"]["servicePid"]]
    for pid in pids:
        if type(pid) is not int or pid <= 1:
            raise ValueError("Invalid reported PID")
        check = read("ls", "-d", f"/proc/{pid}")
        if check["code"] == 0 or "No such file or directory" not in check["stderr"]:
            raise ValueError("PID absence not independently proved: " + str(pid))
    result.update({"bootUnchanged": True, "packagesUnchanged": True,
                   "propertiesUnchanged": True, "processesAbsent": pids,
                   "bootId": after["bootId"], "readOnlyCommands": commands,
                   "verifierSha256": hashlib.sha256(verifier.read_bytes()).hexdigest()})
    (source / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    files = [source / "verification.json"]
    for directory in ("before-install", "device-reports", "after-run", "runtime-deployment"):
        files.extend(sorted((source / directory).glob("*.json")))
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for file in files:
        relative = file.relative_to(source)
        data = file.read_bytes()
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        if output.read_bytes() != data:
            raise ValueError("Evidence copy differs")
        records.append({"path": relative.as_posix(), "source": file.relative_to(root).as_posix(),
                        "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    (destination / "manifest.json").write_text(json.dumps({
        "scope": result["scope"], "passed": True, "files": records}, indent=2) + "\n")
    print(json.dumps({"output": str(destination), "kernelProofs": result["kernelProofs"],
                      "files": len(records), "processesAbsent": pids}))


if __name__ == "__main__":
    main()
