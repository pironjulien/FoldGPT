"""Real ExecServer/bootstrap EOF and policy transport tests on PC/Linux.

The installed test factory records and REFUSES process RPC; it never pretends
to enforce a sandbox. A fixed diagnostic child exercises real cleanup only.
"""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FACTORY = '''
import asyncio, json, os, subprocess, sys
from pathlib import Path
from types import SimpleNamespace
from tools.executor.exec_server import RpcError
class RecordingRefusal:
    supported_methods = frozenset({"process/start"})
    capabilities = frozenset()
    mount = SimpleNamespace(uri="file:///workspace")
    processes = SimpleNamespace(quarantined=False)
    def __init__(self, options):
        self.options = options
        self.files = SimpleNamespace(root=os.open(options["workspace"], os.O_RDONLY | os.O_DIRECTORY))
        self.child = subprocess.Popen([sys.executable, "-I", "-c", "import time;time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        Path(options["workspace"], "diagnostic-child.pid").write_text(str(self.child.pid))
    async def handle(self, call, notify):
        Path(self.options["workspace"], "received.json").write_bytes(call.params_json)
        raise RpcError(-32004, "Host transport fixture refuses execution")
    async def close(self, session):
        if self.child.poll() is None:
            self.child.terminate()
        self.child.wait(timeout=5)
        if self.files.root >= 0:
            os.close(self.files.root)
            self.files.root = -1
        Path(self.options["workspace"], "reaped").write_text(str(self.child.returncode))
        if self.options["failClose"]:
            raise RuntimeError("Injected cleanup reporting failure after real diagnostic cleanup")
def create_backend(options): return RecordingRefusal(options)
'''


def read_line(stream, timeout=5):
    if not select.select([stream], [], [], timeout)[0]:
        raise TimeoutError("Expected protocol line was not emitted")
    return json.loads(stream.readline())


def run():
    if os.getuid() == 0:
        raise SystemExit("Run under an ordinary Linux UID")
    with tempfile.TemporaryDirectory(prefix="foldgpt-bootstrap-", dir="/var/tmp") as temporary:
        root = Path(temporary)
        for mode in ("eof", "cancel-open-input", "quarantine"):
            directory = root / mode
            directory.mkdir(mode=0o700)
            workspace = directory / "workspace"
            broker = directory / "broker"
            workspace.mkdir(mode=0o700)
            broker.mkdir(mode=0o700)
            apk = directory / "test.apk"
            config = {"schema": "foldgpt.shizuku.deployment.v1", "packageName": "test.host",
                "pythonLibrary": "libtest.so", "pythonSha256": "0" * 64,
                "brokerDirectory": str(broker), "workspace": str(workspace),
                "backendFactory": "transport_test_factory:create_backend",
                "backendOptions": {"workspace": str(workspace), "failClose": mode == "quarantine"},
                "environmentInfo": {"shell": {"name": "sh", "path": "/bin/sh"}, "cwd": "file:///workspace",
                    "userHomeDir": "file:///home/test", "platformOs": "linux"}}
            with zipfile.ZipFile(apk, "w") as archive:
                archive.writestr("assets/foldgpt-executor-deployment.json", json.dumps(config))
                archive.writestr("assets/foldgpt-executor/transport_test_factory.py", FACTORY)
                archive.write(HERE / "transport/src/main/assets/foldgpt-executor/foldgpt_shizuku_bootstrap.py",
                    "assets/foldgpt-executor/foldgpt_shizuku_bootstrap.py")
            control_read, control_write = os.pipe()
            # Host test calls run_session directly; the production main's shell
            # UID admission remains unchanged. All session code is production.
            entry = ("import asyncio,os,sys;sys.path[:0]=[sys.argv[1]+'/assets/foldgpt-executor',sys.argv[2]];"
                "from foldgpt_shizuku_bootstrap import run_session;"
                "os._exit(asyncio.run(run_session(sys.argv[1],int(sys.argv[3]))))")
            process = subprocess.Popen([sys.executable, "-I", "-S", "-u", "-c", entry,
                str(apk), str(REPO), str(control_read)], pass_fds=(control_read,),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            os.close(control_read)
            try:
                assert read_line(process.stderr)["event"] == "ready"
                assert (broker / "process-session.json").exists()
                process.stdin.write(b'{"id":1,"method":"initialize","params":{"clientName":"transport-host"}}\n')
                assert "result" in read_line(process.stdout)
                process.stdin.write(b'{"method":"initialized"}\n')
                policy = {"cwd": "file:///workspace", "mode": "managed", "entries": [
                    {"path": "file:///workspace/private", "access": "deny", "scope": "subtree"}],
                    "nested": {"unknown": [True, None, {"keep": "unchanged"}]}}
                params = {"processId": "must-refuse", "argv": ["/not-executed", "payload"],
                    "cwd": "file:///workspace", "env": {"LANG": "C"}, "tty": False, "sandbox": policy}
                process.stdin.write(json.dumps({"id": 2, "method": "process/start", "params": params}).encode() + b"\n")
                assert read_line(process.stdout)["error"]["code"] == -32004
                assert json.loads((workspace / "received.json").read_text()) == params
                if mode == "eof":
                    process.stdin.close()
                else:
                    # Leave client stdin open. Independent service EOF wins.
                    os.close(control_write); control_write = -1
                final = read_line(process.stderr)
                if mode == "quarantine":
                    assert final == {"schema": "foldgpt.shizuku.session.v1", "event": "quarantined", "cleanupComplete": False}
                    assert process.poll() is None
                    assert (broker / "process-session.json").is_file()
                    assert (workspace / "reaped").is_file()
                    # Fault was injected after real child reaping. Only this
                    # explicitly owned PC test bootstrap remains to stop.
                    process.kill(); process.wait(timeout=5)
                else:
                    assert final == {"schema": "foldgpt.shizuku.session.v1", "event": "closed", "cleanupComplete": True, "exitCode": 0}
                    assert process.wait(timeout=5) == 0
                    assert (workspace / "reaped").is_file()
                    assert not (broker / "process-session.json").exists()
            finally:
                if control_write >= 0:
                    os.close(control_write)
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()
    print("PASS: actual ExecServer handshake; complete nested policy preserved and refused; real diagnostic child cleanup on stdin EOF and service EOF with stdin open; failed cleanup retains live owner and persistent marker")


if __name__ == "__main__":
    run()
