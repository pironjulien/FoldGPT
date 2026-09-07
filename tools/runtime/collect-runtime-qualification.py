"""Read-only collection of the separate interpreted runtime qualification.

No kernel-probe result is accepted, and no worker is launched or retried.
Material files are read only after real native and transport ownership is clean.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import zipfile

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools/executor/shizuku-service"))
from runtime_qualification_profile import BASE, PACKAGE, RETAINED_PACKAGES, V1, get_profile, load_contract, requests


def strict(data):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("Duplicate JSON field: " + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def exact(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def identities(app, native, profile=V1):
    return (type(app) is dict and type(native) is dict
        and app.get("schema") == "foldgpt.android-runtime-rpc.v1"
        and native.get("schema") == "foldgpt.bionic-runtime-qualification.private.v1"
        and app.get("packageName") == profile.package and app.get("nativeBase") == profile.base
        and exact(app.get("diagnosticVersion"), profile.version)
        and app.get("requestedAction") == profile.package + profile.identity.run_action
        and native.get("workspace") == profile.base + "/workspace")


def transport_clean(app, native, profile=V1):
    if not identities(app, native, profile):
        return False
    transport, result = app.get("transport"), native.get("nativeResult")
    return (type(transport) is dict and type(result) is dict
        and transport.get("schema") == "foldgpt.shizuku.transport.v1"
        and app.get("transportCleanupComplete") is True
        and transport.get("bootstrapReaped") is True and transport.get("cleanupComplete") is True
        and transport.get("ownerRetained") is False and transport.get("quarantined") is False
        and transport.get("transportFailed") is False and transport.get("refusedBeforeFork") is False
        and type(transport.get("waitStatus")) is int and transport["waitStatus"] in (0, 70 << 8)
        and native.get("quarantined") is False and native.get("supervisorWaited") is True
        and native.get("processClosed") is True and result.get("cleanupComplete") is True
        and type(native.get("supervisorReturncode")) is int
        and all(type(native.get(name)) is int and native[name] > 0 for name in ("bootstrapPid", "supervisorPid"))
        and native["bootstrapPid"] != native["supervisorPid"])


def verify_rpc(app, streams, contract, profile=V1):
    native_directory = app["nativeLibraryDir"]
    if (type(native_directory) is not str or not native_directory.startswith("/data/app/")
            or not native_directory.endswith("/lib/arm64") or "\\" in native_directory or "\0" in native_directory
            or str(PurePosixPath(native_directory)) != native_directory
            or ".." in PurePosixPath(native_directory).parts):
        raise ValueError("Runtime report lacks an actual native package location")
    expected = requests(contract, profile)
    expected["start"]["params"]["env"]["FOLDGPT_PYTHON_REAL"] = native_directory + "/libfoldgpt_python_cli.so"
    sent = [{"id": 1, "method": "initialize", "params": {"clientName": "foldgpt-fixed-runtime-qualification"}},
            {"method": "initialized"}] + [expected[name] for name in ("start", "write", "read", "file")]
    if not exact(app.get("requests"), sent):
        raise ValueError("Actual runtime requests differ from the authenticated fixed sequence")
    read, frames = app["read"], app["frames"]
    if (type(read) is not dict or read.get("exited") is not True or read.get("closed") is not True
            or not exact(read.get("exitCode"), 0) or "failure" not in read or read["failure"] is not None
            or read.get("sandboxDenied") is not False or type(read.get("chunks")) is not list
            or type(frames) is not list or not 7 <= len(frames) <= 128):
        raise ValueError("Incomplete or failed runtime RPC lifecycle")
    replies, events, output = {}, [], []
    terminal = "running"
    for frame in frames:
        if type(frame) is not dict or "error" in frame:
            raise ValueError("Runtime RPC frame was invalid or refused")
        if "id" in frame:
            key = frame["id"]
            if type(key) is not int or key not in (1, 2, 3, 4, 5) or key in replies or type(frame.get("result")) is not dict:
                raise ValueError("Unexpected or duplicate runtime RPC response")
            if key != len(replies) + 1 or (key >= 4 and terminal != "closed"):
                raise ValueError("Runtime RPC response arrived outside its actual request lifecycle")
            replies[key] = frame["result"]
            continue
        method, params = frame.get("method"), frame.get("params")
        if (method not in ("process/output", "process/exited", "process/closed") or type(params) is not dict
                or params.get("processId") != contract.PROCESS_ID or type(params.get("seq")) is not int
                or params["seq"] != len(events) + 1):
            raise ValueError("Unrelated, missing or reordered runtime event")
        events.append((method, params))
        if method == "process/output":
            # Exit reports the leader wait. Pipe readers can still drain real
            # bytes until the independent process/closed notification.
            if terminal == "closed":
                raise ValueError("Runtime output arrived after actual process closure")
            output.append({key: value for key, value in params.items() if key != "processId"})
        elif method == "process/exited":
            if terminal != "running" or not exact(params.get("exitCode"), 0) or params.get("sandboxDenied") is not False:
                raise ValueError("Actual runtime exit event failed or arrived out of order")
            terminal = "exited"
        else:
            if terminal != "exited":
                raise ValueError("Runtime closed event arrived before its unique exit event")
            terminal = "closed"
    if (set(replies) != {1, 2, 3, 4, 5} or not exact(replies[4], read)
            or not exact(replies[2], {"processId": contract.PROCESS_ID, "sandboxType": "linuxSeccomp"})
            or not exact(replies[3], {"status": "accepted"}) or not exact(replies[3], app.get("stdinWrite"))
            or not exact(replies[5], app.get("materialRead"))
            or type(replies[1].get("sessionId")) is not str or not replies[1]["sessionId"]
            or type(replies[1].get("environmentInfo")) is not dict
            or not events or events[-1][0] != "process/closed"
            or sum(name == "process/closed" for name, _ in events) != 1
            or sum(name == "process/exited" for name, _ in events) != 1
            or not exact(read.get("nextSeq"), len(events) + 1) or not exact(read["chunks"], output)):
        raise ValueError("Runtime responses and terminal notifications disagree")
    actual = {"stdout": b"", "stderr": b""}
    for chunk in output:
        if chunk.get("stream") not in actual or type(chunk.get("chunk")) is not str:
            raise ValueError("Unexpected runtime output stream")
        actual[chunk["stream"]] += base64.b64decode(chunk["chunk"], validate=True)
    if (actual != streams or sum(map(len, actual.values())) > 8192
            or base64.b64decode(replies[5]["dataBase64"], validate=True) != streams["stdout"]):
        raise ValueError("Actual RPC/material bytes differ from native evidence")


def verify(app, native, before, after, *, serial, apk_sha, material, contract, profile=V1):
    BASE, PACKAGE = profile.base, profile.package
    checks = {"runtimeIdentity": identities(app, native, profile), "actualCleanOwnership": transport_clean(app, native, profile)}
    error = None
    try:
        if not all(checks.values()):
            raise ValueError("Runtime identity or actual ownership is unproven")
        checks["nativeAndroidIdentity"] = (native.get("platform") == "android" and native.get("androidExecution") is True
            and exact(native.get("uid"), 2000) and exact(native.get("gid"), 2000))
        identity = native.get("bootstrapIdentity", {})
        status = identity.get("status", {})
        checks["actualShellContext"] = (identity.get("securityContext") == "u:r:shell:s0"
            and all(exact(identity.get(name), 2000) for name in ("uid", "euid", "gid", "egid"))
            and all(status.get(name, "").split() == ["2000"] * 4 for name in ("Uid", "Gid"))
            and all(status.get(name) and int(status[name], 16) == 0 for name in ("CapInh", "CapPrm", "CapEff", "CapAmb"))
            and not identity.get("readError") and type(identity.get("pid")) is int
            and identity["pid"] == native.get("bootstrapPid")
            and status.get("Pid") == str(identity["pid"]) and status.get("Tgid") == str(identity["pid"]))
        result, transport = native["nativeResult"], app["transport"]
        checks["nativeResult"] = (native.get("success") is True and native.get("phase") == "process-finished"
            and native.get("lifetimeScope") == "native-process-only" and native.get("bootstrapAliveDuringReport") is True
            and native.get("startError") is None and "failure" in native and native["failure"] is None
            and native.get("setupDiagnostic") == "" and "error" not in native
            and result.get("type") == "result" and result.get("started") is True and result.get("outcome") == "exited"
            and all(exact(result.get(name), 0) for name in ("exitCode", "signal", "errno", "stage"))
            and exact(native.get("supervisorReturncode"), 0))
        checks["transportWait"] = (exact(transport.get("waitStatus"), 0) and transport.get("ready") is True
            and transport.get("setupError") is None and exact(app.get("shizukuServerUid"), 2000)
            and type(app.get("clientUid")) is int and app["clientUid"] >= 10000)
        checks["rpcSuccess"] = (app.get("rpcSuccess") is True and app.get("state") == "complete"
            and not any(name in app for name in ("error", "cleanupError")))
        streams = {name: base64.b64decode(native[name + "Base64"], validate=True) for name in ("stdout", "stderr")}
        worker = contract.validate_report(streams["stdout"], streams["stderr"], BASE + "/workspace",
            app["nativeLibraryDir"] + "/libfoldgpt_python_cli.so", "android")
        checks["actualWorkerResult"] = exact(worker, native.get("worker")) and exact(worker, app.get("worker")) and worker["python"] == "3.14.7"
        verify_rpc(app, streams, contract, profile); checks["actualRpcRequestsLifecycleAndBytes"] = True
        checks["byteCounts"] = all(exact(result.get(name + "Bytes"), len(streams[name])) for name in streams)
        checks["allStreamsAgree"] = all(app[name].encode() == streams[name] and native[name].encode() == streams[name]
            and base64.b64decode(app[name + "Base64"], validate=True) == streams[name] for name in streams)
        checks["materialResultMatches"] = (material / "qualification-result.json").read_bytes() == streams["stdout"]
        artifacts = contract.validate_artifacts(material, worker)
        checks["materialSourcesAndArchive"] = exact(artifacts, native.get("artifacts"))
        checks["beforeSnapshot"] = (before.get("schema") == "foldgpt.native-device-snapshot.v1"
            and before.get("collectionComplete") is True and before.get("errors") == []
            and before.get("bootStableDuringCollection") is True and before.get("serial") == serial)
        checks["afterSnapshot"] = (after.get("schema") == "foldgpt.native-device-snapshot.v1"
            and after.get("collectionComplete") is True and after.get("errors") == []
            and after.get("bootStableDuringCollection") is True and after.get("serial") == serial)
        comparison = after.get("comparison", {})
        checks["bootAndStockIndicators"] = (all(comparison.get(name) is True for name in ("sameDevice", "sameBoot", "sameIndicators"))
            and after.get("observedStockIndicators") is True)
        checks["retainedPackagesUnchanged"] = all(comparison.get("packagesUnchanged", {}).get(name) is True for name in profile.retained_packages)
        checks["installedApk"] = list(after.get("packages", {}).get(PACKAGE, {}).values()) == [apk_sha]
        checks["fixtureUnchanged"] = (after.get("fixture", {}).get("sha256") == {"private/secret": hashlib.sha256(contract.SENTINEL).hexdigest()}
            and after.get("fixture", {}).get("gitConfigAbsent") is True and comparison.get("fixtureUnchanged") is True)
        checks["reportedOwnersAbsent"] = (after.get("processTableValid") is True
            and all(after.get("expectedPidAbsence", {}).get(str(native[name])) is True for name in ("bootstrapPid", "supervisorPid")))
    except (OSError, KeyError, ValueError, TypeError, AttributeError, IndexError, zipfile.BadZipFile) as failure:
        error = str(failure)
    return {"schema": "foldgpt.independent-runtime-qualification.v1",
        "success": bool(checks) and all(value is True for value in checks.values()) and error is None,
        "checks": checks, "error": error, "package": PACKAGE, "base": BASE,
        "scope": "Fixed interpreted Python project through dynamic native backend; ordinary model UI remains separate"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("adb", "serial"):
        parser.add_argument("--" + name, required=True)
    for name in ("apk", "before", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--version", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    profile = get_profile(args.version)
    BASE, PACKAGE = profile.base, profile.package
    args.output.mkdir(parents=True, exist_ok=False)
    collected = {}
    def read(name, remote):
        result = subprocess.run([args.adb, "-s", args.serial, "shell", "-T", shlex.join(remote)],
                                capture_output=True, timeout=30)
        (args.output / (name + ".stdout")).write_bytes(result.stdout)
        (args.output / (name + ".stderr")).write_bytes(result.stderr)
        if result.returncode or result.stderr:
            raise ValueError("Read-only collection failed: " + name)
        return result.stdout
    def record(name, remote):
        try:
            value = base64.b64decode(read(name, remote).replace(b"\r", b"").replace(b"\n", b""), validate=True)
            if len(value) > 1048576:
                raise ValueError("Evidence exceeds collection bound")
            (args.output / (name + ".json")).write_bytes(value)
            collected[name] = True; return strict(value)
        except Exception as error:
            collected[name] = str(error); return None
    app = record("app-report", ["run-as", PACKAGE, "base64", profile.identity.report_file("report.json")])
    native = record("native-evidence", ["base64", BASE + "/evidence.json"])
    clean = transport_clean(app, native, profile)
    command = [sys.executable, "-B", str(Path(__file__).with_name("snapshot-native-qualification.py")),
               "--adb", args.adb, "--serial", args.serial, "--output", str(args.output / "after"), "--before", str(args.before)]
    for package in (*profile.retained_packages, PACKAGE):
        command += ["--package", package]
    if clean:
        command += ["--workspace", BASE + "/workspace"]
        for name in ("bootstrapPid", "supervisorPid"):
            command += ["--absent-pid", str(native[name])]
    material = args.output / "workspace"
    error = None
    try:
        try:
            snapshot = subprocess.run(command, capture_output=True, timeout=120)
        except subprocess.TimeoutExpired as timeout:
            (args.output / "snapshot.stdout").write_bytes(timeout.stdout or b"")
            (args.output / "snapshot.stderr").write_bytes(timeout.stderr or b"")
            raise ValueError("Independent after snapshot exceeded its collection deadline") from timeout
        (args.output / "snapshot.stdout").write_bytes(snapshot.stdout)
        (args.output / "snapshot.stderr").write_bytes(snapshot.stderr)
        contract = load_contract()
        if not clean:
            raise ValueError("Actual clean ownership is unproven; no material traversal was attempted")
        if snapshot.returncode:
            raise ValueError("Independent after snapshot failed")
        with zipfile.ZipFile(args.apk) as archive:
            path = "tools/executor/bionic-supervisor/runtime_qualification.py"
            if archive.read("assets/foldgpt-executor/" + path) != (REPO / path).read_bytes():
                raise ValueError("Collector contract differs from the actual signed workload source")
        if native.get("success") is not True or app.get("rpcSuccess") is not True:
            raise ValueError("Actual runtime reported failure; clean ownership does not imply a successful Python workload")
        material.mkdir()
        (material / ".git").mkdir()
        if read("git-list", ["ls", "-A", BASE + "/workspace/.git"]) != b"":
            raise ValueError("Protected git directory was changed")
        for name in ("private/secret", "qualification-result.json", "directory/dist/calculator.pyz",
                     *("directory/project/" + name for name in contract.SOURCES)):
            value = base64.b64decode(read("material-" + name.replace("/", "-"),
                ["base64", BASE + "/workspace/" + name]).replace(b"\r", b"").replace(b"\n", b""), validate=True)
            if len(value) > contract.LIMITS["file_bytes"]:
                raise ValueError("Material file exceeds its process bound")
            path = material / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value)
        report = verify(app, native, strict(args.before.read_bytes()), strict((args.output / "after/snapshot.json").read_bytes()),
            serial=args.serial, apk_sha=hashlib.sha256(args.apk.read_bytes()).hexdigest(), material=material, contract=contract,
            profile=profile)
    except Exception as failure:
        error = str(failure)
        report = {"schema": "foldgpt.independent-runtime-qualification.v1", "success": False, "error": error,
                  "package": PACKAGE, "base": BASE, "checks": {"actualCleanOwnership": clean}}
        if identities(app, native, profile):
            report["observedRuntimeFailure"] = {
                "nativeResult": native.get("nativeResult"), "nativeError": native.get("error"),
                "nativeStderr": native.get("stderr"), "appError": app.get("error"),
                "nativeSuccess": native.get("success"), "rpcSuccess": app.get("rpcSuccess")}
    report["collected"] = collected
    (args.output / "independent-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    raise SystemExit(0 if report["success"] else 1)


if __name__ == "__main__":
    main()
