"""Fixed diagnostic of r25 pipe and PTY adapters from an Android app process.

Executed only by ContextProbeService. No command/policy/production path input.
The separate APK has a separate UID and relocated Python data; ELF/source bytes
are unchanged from r25. This is a primitive feasibility test, not UI qualification.
"""
import asyncio
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "project"))
from tools.executor.exec_server import BackendCall, encode_message

direct = importlib.import_module("tools.executor.bionic-supervisor.direct_processes")
tty = importlib.import_module("tools.executor.bionic-supervisor.tty_processes")
NATIVE = Path(sys.executable).resolve().parent
RESULT = {"schema": "foldgpt.app-context-feasibility.v1", "passed": False,
          "scope": "separate APK UID, byte-identical r25 pipe/PTY ELF and adapters; no production bootstrap or UI", "cases": []}
RETAINED_OWNERS = []


def identity():
    fields = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    maps = Path("/proc/self/maps").read_text()
    return {"pid": os.getpid(), "ppid": os.getppid(), "uid": os.getuid(), "gid": os.getgid(),
            "resuid": os.getresuid(), "resgid": os.getresgid(),
            "exe": str(Path("/proc/self/exe").resolve()),
            "status": {k: fields[k].strip() for k in ("Uid", "Gid", "TracerPid", "Seccomp", "NoNewPrivs", "CapEff", "CapPrm", "Cpus_allowed_list")},
            "cgroup": Path("/proc/self/cgroup").read_text(),
            "memory": {k: v.strip() for k, v in (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()) if k in ("MemTotal", "MemAvailable")},
            "compatibilityMaps": [line for line in maps.splitlines() if any(s in line.lower() for s in ("proot", "libshim", "ld-linux"))]}


def verify_identity(value):
    assert value["uid"] == os.getuid() > 10000, value
    assert len(set(value["resuid"])) == len(set(value["resgid"])) == 1, value
    assert value["status"]["Seccomp"] == "2", value
    assert value["status"]["TracerPid"] == "0", value
    assert int(value["status"]["CapEff"], 16) == int(value["status"]["CapPrm"], 16) == 0, value
    assert not value["compatibilityMaps"], value


IDENTITY_SOURCE = '''def identity():
 fields=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
 return {'pid':os.getpid(),'ppid':os.getppid(),'uid':os.getuid(),'gid':os.getgid(),
  'resuid':os.getresuid(),'resgid':os.getresgid(),'exe':str(Path('/proc/self/exe').resolve()),
  'status':{k:fields[k].strip() for k in ('Uid','Gid','TracerPid','Seccomp','NoNewPrivs','CapEff','CapPrm','Cpus_allowed_list')},
  'cgroup':Path('/proc/self/cgroup').read_text(),
  'compatibilityMaps':[line for line in Path('/proc/self/maps').read_text().splitlines() if any(s in line.lower() for s in ('proot','libshim','ld-linux'))]}
'''


async def case(is_tty):
    name = "pty" if is_tty else "pipe"
    workspace = ROOT / name
    workspace.mkdir(mode=0o700)
    environment = {"PATH": "/system/bin", "LANG": "C.UTF-8", "HOME": str(workspace),
                   "TMPDIR": str(workspace), "PYTHONHOME": str(ROOT / "python"),
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
    cls = tty.TtyProcesses if is_tty else direct.DirectProcesses
    runner = NATIVE / ("libfoldgpt_direct_pty_supervisor.so" if is_tty else "libfoldgpt_direct_runner.so")
    backend = cls(runner, workspace, executables={"python": str(Path(sys.executable).resolve())},
                  parent_environment=environment, limits=direct.DirectLimits(wall_ms=12000, cleanup_grace_ms=5000))
    sequence = 0
    events = []
    observation = {"name": name, "passed": False, "runnerSha256": hashlib.sha256(runner.read_bytes()).hexdigest()}
    observation["events"] = events
    RESULT["cases"].append(observation)
    async def notify(method, params):
        events.append({"method": method, "params": params})
    async def call(method, params):
        nonlocal sequence
        sequence += 1
        return await backend.handle(BackendCall(name, sequence, method, encode_message(params)), notify)
    def output(response):
        return b"".join(base64.b64decode(c["chunk"]) for c in response["chunks"])
    async def until(record, marker):
        deadline = asyncio.get_running_loop().time() + 6
        while asyncio.get_running_loop().time() < deadline:
            response = await call("process/read", {"processId": "fixed", "waitMs": 50})
            if marker in output(response):
                return response
            if response["closed"]:
                raise AssertionError(response)
            await asyncio.sleep(0.01)
        raise TimeoutError("Expected native output not observed")
    record = None
    child = "import json,os,sys,signal,subprocess\nfrom pathlib import Path\nsignal.alarm(8)\n" + IDENTITY_SOURCE
    child += "Path('identity.json').write_text(json.dumps(identity()))\nPath('created.txt').write_bytes(b'foldgpt-native-app-context\\n')\n"
    child += "result=subprocess.run([sys.executable,'-B','-s','-c',\"import os; print('SUBPROCESS:'+str(os.getuid()))\"],capture_output=True,check=True,timeout=3)\n"
    child += "assert result.stdout==('SUBPROCESS:'+str(os.getuid())+'\\n').encode()\n"
    if is_tty:
        child += "assert all(os.isatty(fd) for fd in (0,1,2))\nassert os.get_terminal_size(0)==(80,24)\nprint('READY',flush=True)\ntry:\n while True: signal.pause()\nexcept KeyboardInterrupt:\n print('INTERRUPTED',flush=True)\n sys.exit(130)\n"
    else:
        child += "print('READY',flush=True)\nassert sys.stdin.buffer.readline()==b'INPUT\\n'\nprint('PIPE_INPUT_OK',flush=True)\nsys.exit(23)\n"
    try:
        result = await call("process/start", {"processId": "fixed", "argv": ["python", "-B", "-s", "-c", child],
                            "cwd": workspace.as_uri(), "env": environment, "tty": is_tty, "pipeStdin": not is_tty})
        assert result == {"processId": "fixed", "sandboxType": "none"}, result
        record = backend.processes[(name, "fixed")]
        observation["ownerPid"] = record.process.pid
        try:
            observation["ownerStatus"] = Path(f"/proc/{record.process.pid}/status").read_text()
            observation["ownerCgroup"] = Path(f"/proc/{record.process.pid}/cgroup").read_text()
        except OSError as error:
            observation["ownerObservationError"] = repr(error)
        await until(record, b"READY")
        worker = json.loads((workspace / "identity.json").read_bytes())
        verify_identity(worker)
        assert worker["ppid"] == record.process.pid, worker
        observation["worker"] = worker
        assert (workspace / "created.txt").read_bytes() == b"foldgpt-native-app-context\n"
        if is_tty:
            assert await call("process/signal", {"processId": "fixed", "signal": "interrupt"}) == {}
        else:
            assert await call("process/write", {"processId": "fixed", "writeId": "one", "chunk": base64.b64encode(b"INPUT\n").decode()}) == {"status": "accepted"}
        await asyncio.wait_for(asyncio.shield(record.finished), 20)
        await asyncio.wait_for(asyncio.shield(record.notifier), 5)
        response = await call("process/read", {"processId": "fixed", "waitMs": 50})
        observation.update(nativeResult=record.native_result, response=response,
                           ownerWait=record.process.returncode, pipeEof=record.pipe_eof)
        assert response["closed"] and response["exited"] and response["failure"] is None, response
        assert response["exitCode"] == (130 if is_tty else 23), response
        assert (b"INTERRUPTED" if is_tty else b"PIPE_INPUT_OK") in output(response), response
        assert record.native_result["cleanupComplete"] and record.process.returncode == 0
        assert all(record.pipe_eof.values()) and not backend.lease.locked()
        assert not Path(f"/proc/{record.process.pid}").exists(), "Reaped owner still present"
        observation["passed"] = True
    except BaseException as error:
        observation["error"] = repr(error)
        observation["traceback"] = traceback.format_exc()
        for candidate in [*backend.processes.values(), *backend.failed]:
            observation["failureRecord"] = {"failure": candidate.failure,
                "nativeResult": candidate.native_result,
                "ownerWait": candidate.process.returncode if candidate.process else None}
        raise
    finally:
        # close asks the actual native owner to cancel and reap; no external PID kill.
        try:
            await asyncio.wait_for(backend.close(name), 20)
            observation["closedWithoutQuarantine"] = not backend.quarantined and not backend.lease.locked()
            assert observation["closedWithoutQuarantine"], "Native ownership remains quarantined or locked"
        finally:
            if not observation.get("closedWithoutQuarantine", False):
                RETAINED_OWNERS.append(backend)
            (ROOT / "report.json").write_text(json.dumps(RESULT, indent=2))


async def main():
    RESULT["supervisor"] = identity()
    verify_identity(RESULT["supervisor"])
    java = json.loads((ROOT / "java-identity.json").read_text())
    assert RESULT["supervisor"]["ppid"] == java["pid"]
    assert java["uid"] == os.getuid() and java["pid"] > 1
    java_status = dict(line.split(":", 1) for line in java["status"].splitlines() if ":" in line)
    assert java_status["Seccomp"].strip() == "2" and java_status["TracerPid"].strip() == "0", java_status
    assert int(java_status["CapEff"], 16) == int(java_status["CapPrm"], 16) == 0, java_status
    assert set(map(int, java_status["Uid"].split())) == {os.getuid()}, java_status
    RESULT["java"] = java
    failures = []
    for mode in (False, True):
        try:
            await case(mode)
        except BaseException as error:
            failures.append(repr(error))
            # Do not admit the next test if an earlier owner retained its lease.
            if not RESULT["cases"][-1].get("closedWithoutQuarantine", False):
                break
    RESULT["errors"] = failures
    RESULT["passed"] = len(RESULT["cases"]) == 2 and not failures and not RETAINED_OWNERS and all(
        c["passed"] and c.get("closedWithoutQuarantine", False) for c in RESULT["cases"])
    RESULT["ownershipRetained"] = bool(RETAINED_OWNERS)
    (ROOT / "report.json").write_text(json.dumps(RESULT, indent=2))
    if RETAINED_OWNERS:
        # Keep the live adapter/event loop/service on an unproven cleanup path.
        # Java reports timeout after 90 seconds and also retains its owner.
        await asyncio.Event().wait()
    return 0 if RESULT["passed"] else 1


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except BaseException as error:
        RESULT["fatal"] = repr(error)
        RESULT["traceback"] = traceback.format_exc()
        (ROOT / "report.json").write_text(json.dumps(RESULT, indent=2))
        code = 1
    sys.exit(code)
