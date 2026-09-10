"""Fixed probe driver using the real factory; host execution and Android contract.

Usage: python3 -B qualification.py FROZEN_BUILD_DIR
This CLI creates a fresh PC workspace and never invokes adb. Android uses the
same fixed request sequence through its authenticated Shizuku ExecServer.
"""
import asyncio
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
factory = importlib.import_module("tools.executor.bionic-supervisor.factory").factory
from tools.executor.exec_server import BackendCall, encode_message

PROOFS = frozenset({"memoryRead", "memoryWrite", "pidfdGetfd", "sharedOffset", "privateReadDenied",
    "protectedWriteDenied", "rawChdirDenied", "networkDenied", "ioctlDenied", "binderDenied", "threadMemory", "threadPidfdGetfd"})


def context(workspace):
    uri = Path(workspace).as_uri()
    return {"permissions": {"type": "managed", "file_system": {"type": "restricted", "entries": [
        {"path": {"type": "path", "path": uri}, "access": "write"},
        {"path": {"type": "path", "path": uri + "/private"}, "access": "deny"}]}, "network": "restricted"},
        "cwd": uri, "workspaceRoots": [uri], "windowsSandboxLevel": "disabled"}


def process_request(workspace):
    policy = context(workspace)
    return {"processId": "kernel-qualification", "argv": ["kernel-qualification"],
        "cwd": policy["cwd"], "env": {}, "pipeStdin": False, "tty": False, "sandbox": policy}


def evidence(worker_stdout, worker_stderr, record):
    lines = worker_stdout.splitlines()
    if len(lines) != 1:
        raise ValueError("The fixed worker did not produce one complete result")
    worker = json.loads(lines[0])
    if (set(worker) != PROOFS | {"type", "success"} or worker["type"] != "kernel-qualification"
            or any(worker[name] is not True for name in PROOFS | {"success"})):
        raise ValueError("A required real kernel mechanism failed: " + repr(worker))
    if worker_stderr:
        raise ValueError("The fixed worker produced unexpected stderr")
    result = record.native_result
    if (not record.closed or record.exit_code != 0 or result is None or result["cleanupComplete"] is not True
            or result["started"] is not True or result["outcome"] != "exited" or result["exitCode"] != 0
            or result["signal"] != 0 or record.process.returncode != 0):
        raise ValueError("The real supervisor did not prove bounded clean completion")
    return worker


async def qualify(options, directory):
    workspace = Path(options["workspace"])
    # These are fixed non-sensitive probe data. Never use an existing workspace.
    workspace.mkdir(mode=0o700, exist_ok=False)
    (workspace / "private").mkdir(mode=0o700)
    (workspace / ".git").mkdir(mode=0o700)
    (workspace / "directory").mkdir(mode=0o700)
    for relative, data in {"input": b"pin-memory-ok\n", "private/secret": b"probe-private-unchanged\n",
                           "directory/marker": b"marker\n"}.items():
        (workspace / relative).write_bytes(data)
        (workspace / relative).chmod(0o600)
    backend = factory(options)
    events, requests, error = [], [], None
    record = None

    async def notify(method, params):
        events.append({"method": method, "params": params})

    async def call(method, params):
        request = {"id": len(requests) + 1, "method": method, "params": params}
        requests.append(request)
        return await backend.handle(BackendCall("qualification", request["id"], method, encode_message(params)), notify)

    result = {"schema": "foldgpt.bionic-kernel-qualification.v1", "success": False,
        "platform": sys.platform, "uid": os.getuid(), "gid": os.getgid(),
        "androidExecution": sys.platform == "android", "workspace": str(workspace), "options": options}
    try:
        await call("process/start", process_request(workspace))
        record = backend.processes.processes[("qualification", "kernel-qualification")]
        await asyncio.wait_for(asyncio.shield(record.finished), 15)
        await asyncio.wait_for(asyncio.shield(record.notifier), 2)
        read = await call("process/read", {"processId": "kernel-qualification"})
        streams = {name: b"".join(base64.b64decode(row["chunk"], validate=True) for row in read["chunks"]
            if row["stream"] == name) for name in ("stdout", "stderr")}
        result.update({"read": read, "stdout": streams["stdout"].decode(), "stderr": streams["stderr"].decode(),
                       "nativeResult": record.native_result, "supervisorReturncode": record.process.returncode})
        result["proofs"] = evidence(streams["stdout"], streams["stderr"], record)
        if (workspace / "private/secret").read_bytes() != b"probe-private-unchanged\n" or (workspace / ".git/config").exists():
            raise ValueError("A denied probe object was changed")
        result["success"] = True
    except BaseException as failure:
        error = failure
        result["error"] = type(failure).__name__ + ": " + str(failure)
        if record is None and backend.processes.failed:
            record = backend.processes.failed[-1]
            result["nativeResult"] = record.native_result
            result["setupDiagnostic"] = record.setup_diagnostic.decode("utf-8", "replace")
    finally:
        try:
            await backend.close("qualification")
        except BaseException as failure:
            result["success"] = False
            result["cleanupError"] = type(failure).__name__ + ": " + str(failure)
            error = error or failure
        result["quarantined"] = backend.processes.quarantined
        result["requests"], result["notifications"] = requests, events
        # Unknown descendants retain the workspace lease. Evidence collection
        # must not walk that workspace while the actual owner is quarantined.
        result["files"] = None if result["quarantined"] else {
            str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(workspace.rglob("*")) if path.is_file()}
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"success": result["success"], "evidence": str(directory),
                          "quarantined": result["quarantined"], "error": result.get("error")}), flush=True)
    if error:
        raise error
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.platform == "android" or os.getuid() == 0:
        raise SystemExit("This command is the nonroot PC qualification driver; Android uses the reviewed Shizuku transport")
    build = Path(sys.argv[1]).resolve(strict=True)
    case = Path(tempfile.mkdtemp(prefix="foldgpt-kernel-qualification-", dir="/var/tmp"))
    options = {"helper": str(build / "native-files"), "handleHelper": str(build / "native-file-handle"),
        "processRunner": str(build / "runner"), "workspace": str(case / "workspace"),
        "executables": {"kernel-qualification": str(build / "qualification-worker")},
        "runtime": [{"path": path, "execute": execute} for path, execute in
            ((str(build / "qualification-worker"), True), ("/usr", True), ("/lib", True),
             ("/lib64", True), ("/etc/ld.so.cache", False))],
        "limits": {"wall_ms": 3000, "cpu_seconds": 1, "uid_task_budget": 2,
                   "data_bytes": 16777216, "file_bytes": 1048576, "output_bytes": 8192, "descriptors": 32}}
    asyncio.run(qualify(options, case / "evidence"))
