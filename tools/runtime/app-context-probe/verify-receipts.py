"""Independently verify collected app-context probe receipts on PC, no ADB.

This reads the physical JSON/files, verifies against the frozen candidate APK,
and never executes the device harness or imports the process implementation.
External PID/boot/production observations are reviewed separately by the caller.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(path.read_bytes())


def status(text):
    return {k: v.strip() for k, v in (line.split(":", 1) for line in text.splitlines() if ":" in line)}


def native_identity(value, uid):
    require(type(value["pid"]) is int and value["pid"] > 1, "Invalid native PID")
    require(type(value["ppid"]) is int and value["ppid"] > 1, "Invalid native PPID")
    require(value["uid"] == uid and value["gid"] == uid, "Native UID/GID differs from app")
    require(value["resuid"] == [uid] * 3 and value["resgid"] == [uid] * 3, "Native real/effective/saved identities differ")
    require(value["compatibilityMaps"] == [], "Compatibility maps present")
    fields = value["status"]
    require(fields["Seccomp"] == "2" and fields["TracerPid"] == "0", "Native context is not untraced seccomp 2")
    require(int(fields["CapEff"], 16) == int(fields["CapPrm"], 16) == 0, "Native capabilities present")
    require(set(map(int, fields["Uid"].split())) == {uid}, "Native status UID differs")
    require(set(map(int, fields["Gid"].split())) == {uid}, "Native status GID differs")
    require(bool(fields["Cpus_allowed_list"]) and bool(value["cgroup"]), "Missing native scheduler observations")
    require(value["exe"].startswith("/data/app/") and value["exe"].endswith("/lib/arm64/libfoldgpt_python_cli.so"), "Native executable outside installed APK")


def inspect(evidence, apk, expected_hash):
    actual_hash = hashlib.sha256(apk.read_bytes()).hexdigest()
    require(actual_hash == expected_hash, "Frozen probe APK hash differs")
    with zipfile.ZipFile(apk) as package:
        expected = json.loads(package.read("assets/inventory.json"))
        harness = package.read("assets/payload/probe.py")
    inventory = read_json(evidence / "inventory.json")
    require(inventory == expected, "Collected source/runtime inventory differs from APK")
    require(expected["payload"]["probe.py"] == hashlib.sha256(harness).hexdigest(), "Harness hash mismatch")
    require(b"DirectLimits(wall_ms=12000, cleanup_grace_ms=5000)" in harness and b"signal.alarm(8)" in harness,
            "Frozen diagnostic duration limits differ")
    report = read_json(evidence / "report.json")
    completion = read_json(evidence / "android-completion.json")
    java = read_json(evidence / "java-identity.json")
    require(report["schema"] == "foldgpt.app-context-feasibility.v1", "Unknown report schema")
    require(report["passed"] is True and report["ownershipRetained"] is False and report["errors"] == [], "Diagnostic did not pass cleanly")
    require("fatal" not in report and "traceback" not in report, "Fatal diagnostic exception")
    require(completion["passed"] is True and completion["processExit"] == 0 and completion["pythonReaped"] is True,
            "Java completion lacks actual successful Python wait")
    for name in ("android-failure.txt", "android-timeout.txt"):
        require(not (evidence / name).exists(), "Conflicting Android failure or timeout")
    require(java == report["java"] and java["packageName"] == "app.foldgpt.contextprobe", "Java identity differs")
    uid = java["uid"]
    require(type(uid) is int and uid > 10000, "Normal Android application UID required")
    js = status(java["status"])
    require(js["Seccomp"] == "2" and js["TracerPid"] == "0", "Java was not ordinary untraced filtered app")
    require(int(js["CapEff"], 16) == int(js["CapPrm"], 16) == 0, "Java capabilities present")
    require(set(map(int, js["Uid"].split())) == {uid}, "Java status UID differs")
    require(int(js["Pid"]) == java["pid"] and int(js["PPid"]) > 1, "Java kernel PID differs")
    supervisor = report["supervisor"]
    native_identity(supervisor, uid)
    require(supervisor["ppid"] == java["pid"], "Python was not launched by observed Java")
    require(bool(java["cgroup"]) and bool(java["meminfo"]), "Missing Java scheduler/memory observations")
    require(set(supervisor["memory"]) == {"MemTotal", "MemAvailable"}, "Missing Python memory observation")
    cases = report["cases"]
    require(len(cases) == 2 and [c["name"] for c in cases] == ["pipe", "pty"], "Both ordered cases required")
    result = {"schema": "foldgpt.app-context-independent-receipts.v1", "receiptsVerified": False,
              "probeApkSha256": actual_hash, "uid": uid, "javaPid": java["pid"],
              "javaParentPid": int(js["PPid"]), "supervisorPid": supervisor["pid"], "ownerPids": [], "workerPids": [],
              "measuredScope": "separate Android app pipe/PTY and subprocess primitive checks; no production bootstrap or UI",
              "sourceLimits": {"workerAlarmSeconds": 8, "nativeWallMs": 12000, "cleanupGraceMs": 5000},
              "externalLivenessStillRequired": True, "externalBootAndProductionStillRequired": True}
    for case in cases:
        name = case["name"]
        code = 23 if name == "pipe" else 130
        profile = "bionic-direct-v1" if name == "pipe" else "bionic-direct-pty-v1"
        library = "libfoldgpt_direct_runner.so" if name == "pipe" else "libfoldgpt_direct_pty_supervisor.so"
        require(case["passed"] is True and case["closedWithoutQuarantine"] is True, "Case did not close cleanly")
        require("error" not in case and "failureRecord" not in case, "Case has failure details")
        require(case["runnerSha256"] == expected["libraries"][library], "Case runner differs from r25")
        worker = case["worker"]
        native_identity(worker, uid)
        require(worker == read_json(evidence / name / "identity.json"), "Worker physical identity differs")
        require(worker["ppid"] == case["ownerPid"], "Worker parent differs from native owner")
        require((evidence / name / "created.txt").read_bytes() == b"foldgpt-native-app-context\n", "Native physical file differs")
        result["ownerPids"].append(case["ownerPid"])
        result["workerPids"].append(worker["pid"])
        if "ownerStatus" in case:
            owner = status(case["ownerStatus"])
            require(int(owner["Pid"]) == case["ownerPid"] and int(owner["PPid"]) == supervisor["pid"], "Native owner parent differs from supervisor")
            require(owner["Seccomp"] == "2" and owner["TracerPid"] == "0", "Native owner context differs")
            require(set(map(int, owner["Uid"].split())) == {uid}, "Native owner UID differs")
        response, native = case["response"], case["nativeResult"]
        require(case["ownerWait"] == 0 and type(case["ownerWait"]) is int, "Native owner was not actually reaped with code 0")
        require(bool(case["pipeEof"]) and all(x is True for x in case["pipeEof"].values()), "Missing actual output EOF")
        require(native["profile"] == profile and native["outcome"] == "exited" and native["started"] is True, "Unexpected native terminal result")
        require(native["cleanupComplete"] is True and native["reaped"] >= 1 and native["exitCode"] == code and native["signal"] == 0, "Native wait/cleanup differs")
        require(native["errno"] == 0, "Native errno indicates failure")
        require(response["closed"] is True and response["exited"] is True and response["exitCode"] == code and response["failure"] is None,
                "RPC final lifecycle differs")
        chunks = response["chunks"]
        output = b"".join(base64.b64decode(c["chunk"], validate=True) for c in chunks)
        expected_output = b"READY\nPIPE_INPUT_OK\n" if name == "pipe" else b"READY\r\nINTERRUPTED\r\n"
        require(output == expected_output, "Actual native output differs")
        if name == "pty":
            require(all(c["stream"] == "pty" for c in chunks), "PTY stream identity differs")
        require(native["stdoutReadBytes"] == native["stdoutBytes"] == len(output) and native["stderrReadBytes"] == native["stderrBytes"] == 0,
                "Native output accounting differs")
        exits = [e for e in case["events"] if e["method"] == "process/exited"]
        closes = [e for e in case["events"] if e["method"] == "process/closed"]
        require(len(exits) == len(closes) == 1 and exits[0]["params"]["exitCode"] == code, "Exactly one real exit/close notification required")
    pids = [result["supervisorPid"], *result["ownerPids"], *result["workerPids"]]
    require(len(pids) == len(set(pids)), "Diagnostic PID identity collision")
    result["receiptsVerified"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--apk-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.evidence, args.apk, args.apk_sha256), indent=2))


if __name__ == "__main__":
    main()
