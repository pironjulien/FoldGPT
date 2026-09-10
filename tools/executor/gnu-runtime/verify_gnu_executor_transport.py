"""Actual GNU stdio/Unix composite diagnostic in one fresh private workspace.

This sends protocol requests to a real C bridge and broker, observes physical
files and process cleanup, and retains evidence. No model/profile is activated.
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.executor.test_native_executor_transport import Peer
from tools.policy.managed_policy import GuestPath

BROKER = Path(__file__).with_name("gnu_executor_broker.py")
MOUNT = GuestPath.from_absolute("/workspace")


def context(*, tmp_write=False):
    entries = [{"path": {"type": "path", "path": path}, "access": access}
               for path, access in (("file:///", "read"), (MOUNT.uri, "write"),
                                    (MOUNT.append(("readonly",)).uri, "read"))]
    if tmp_write:
        entries.append({"path": {"type": "path", "path": "file:///tmp"}, "access": "write"})
    return {"permissions": {"type": "managed", "file_system": {"type": "restricted", "entries": entries},
                            "network": "restricted"},
            "cwd": MOUNT.uri, "workspaceRoots": [MOUNT.uri], "useLegacyLandlock": False,
            "windowsSandboxLevel": "disabled", "windowsSandboxPrivateDesktop": False}


def main(options):
    global MOUNT
    MOUNT = GuestPath.from_absolute(options.guest_workspace)
    assert os.getuid() != 0, "This diagnostic must run as an ordinary UID"
    case = Path(tempfile.mkdtemp(prefix="gwire-", dir=options.parent))
    for name in ("workspace", "scratch", "tmp", "ipc"):
        (case / name).mkdir(mode=0o700)
    workspace = case / "workspace"
    for name in (".home", "readonly", ".git"):
        (workspace / name).mkdir(mode=0o700)
    for name in ("readonly/value", ".git/config"):
        (workspace / name).write_bytes(b"protected\n")
        (workspace / name).chmod(0o600)
    events, peers = [], []
    broker = None
    report = {"scope": "actual GNU composite diagnostic; no model request or production routing",
              "passed": False, "uid": os.getuid(), "workspace": str(workspace), "events": events}
    artifacts = ("runner", "files_helper", "handle_helper", "bridge", "proot", "loader", "loader32")
    report["artifacts"] = {name: {"path": str(getattr(options, name)),
        "sha256": hashlib.sha256(getattr(options, name).read_bytes()).hexdigest()} for name in artifacts}
    source_paths = [BROKER, Path(__file__), BROKER.with_name("gnu_process_adapter.py"),
                    BROKER.parent.parent / "private_exec_broker.py", BROKER.parent.parent / "native_executor_backend.py"]
    report["sources"] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    interpreter = [sys.executable, "-I", "-S", "-B"]
    if options.android_home is not None:
        assert sys.platform == "android", "Android launcher inputs require Bionic Python"
        interpreter = [sys.executable, "--home", str(options.android_home), "--"]
    command = [*interpreter, str(BROKER)]
    arguments = {"socket-dir": case / "ipc", "workspace": workspace, "scratch": case / "scratch",
                 "guest-tmp": case / "tmp", "helper": options.files_helper, "handle-helper": options.handle_helper,
                 "process-runner": options.runner, "rootfs": options.rootfs, "proot": options.proot,
                 "loader": options.loader, "loader32": options.loader32, "peer-uid": os.getuid(),
                 "guest-workspace": MOUNT.path,
                 "process-wall-ms": 15000, "process-address-space-bytes": options.address_space_bytes}
    command += [str(token) for name, value in arguments.items() for token in ("--" + name, value)]
    environment = {"PATH": "/system/bin" if options.android_home is not None else "/usr/bin:/bin",
                   "HOME": str(case), "TMPDIR": str(case / "scratch"), "SHELL": "/system/bin/sh",
                   "FOLDGPT_AMBIENT_PROBE": "must-not-inherit", "LANG": "C.UTF-8"}
    broker_log = (case / "broker.stderr").open("w+b")

    def broker_event():
        with selectors.DefaultSelector() as selector:
            selector.register(broker.stdout, selectors.EVENT_READ)
            if not selector.select(10):
                raise TimeoutError("GNU broker event deadline expired")
            value = json.loads(broker.stdout.readline())
            events.append({"broker": value})
            return value

    def peer():
        process = subprocess.Popen([str(options.bridge), "--socket", str(case / "ipc/exec.sock"),
                                    "--peer-uid", str(os.getuid())],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=workspace, env=environment, bufsize=0)
        value = Peer(process, events)
        peers.append(value)
        return value

    def success(client, method, params):
        response = client.call(method, params)
        assert "result" in response, response
        return response["result"]

    def start(client, key, argv, *, policy=None):
        return success(client, "process/start", {"processId": key, "argv": argv,
            "cwd": MOUNT.uri, "env": {}, "tty": False, "sandbox": context() if policy is None else policy,
            "envPolicy": {"inherit": "all", "ignoreDefaultExcludes": False,
                          "exclude": [], "set": {}, "includeOnly": []}})

    def output(result):
        return b"".join(base64.b64decode(chunk["chunk"], validate=True)
                        for chunk in result["chunks"] if chunk["stream"] == "stdout")

    def completed(client, key):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = success(client, "process/read", {"processId": key, "waitMs": 500})
            if result["closed"]:
                assert result["exited"] and result["failure"] is None, result
                return result
        raise TimeoutError("GNU command did not close")

    def ready(client, key):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = success(client, "process/read", {"processId": key, "waitMs": 500})
            if b"READY " in output(result):
                return output(result)
            assert not result["closed"], result
        raise TimeoutError("GNU command did not become ready")

    def leases_released():
        assert not (case / "ipc/process-session.json").exists(), "Session marker survived a claimed clean close"
        for path in (workspace, case / "tmp"):
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)

    try:
        broker = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=broker_log,
                                  cwd=workspace, env=environment, bufsize=0)
        assert broker_event()["event"] == "ready"
        client = peer()
        initial = client.initialize()
        event = broker_event()
        assert event["event"] == "session-open" and event["peer"]["uid"] == os.getuid(), event
        assert event["peer"]["pid"] == client.process.pid, event
        info = initial["environmentInfo"]
        assert info["shell"] == {"name": "bash", "path": "/bin/bash"}, info
        assert info["cwd"] == MOUNT.uri and info["userHomeDir"] == MOUNT.append((".home",)).uri, info
        assert info["temporaryDirectories"] == ["file:///tmp"] and info["tempDir"] == "file:///tmp", info
        assert info["platformOs"] == "linux", info
        assert {name for name, enabled in info["capabilities"].items() if enabled} == {"sandboxedFileStreaming"}, info
        assert success(client, "environment/info", {}) == info
        assert (case / "ipc/process-session.json").exists()
        success(client, "fs/writeFile", {"path": MOUNT.append(("input",)).uri, "sandbox": context(),
                "dataBase64": base64.b64encode(b"file RPC to actual GNU\n").decode()})
        script = '''import os
from pathlib import Path
assert os.environ['HOME']==os.getcwd()+'/.home'
assert os.environ['TMPDIR']=='/tmp' and os.environ['SHELL']=='/bin/bash'
assert 'FOLDGPT_AMBIENT_PROBE' not in os.environ
assert not any(name.startswith('PROOT_') for name in os.environ)
assert Path('input').read_bytes()==b'file RPC to actual GNU\\n'
Path('project').mkdir()
Path('project/artifact').write_bytes(b'actual GNU to file RPC\\n')
Path('project/artifact').rename('project/result')
print('GNU_COMPOSITE_PASS')
'''
        start(client, "project", ["/bin/bash", "-c", "/usr/bin/python3 -c \"$1\"", "bash", script])
        result = completed(client, "project")
        assert result["exitCode"] == 0 and b"GNU_COMPOSITE_PASS" in output(result), result
        expected = b"actual GNU to file RPC\n"
        assert (workspace / "project/result").read_bytes() == expected
        success(client, "fs/open", {"handleId": "artifact", "path": MOUNT.append(("project", "result")).uri, "sandbox": context()})
        block = success(client, "fs/readBlock", {"handleId": "artifact", "offset": 0, "len": 1024})
        assert base64.b64decode(block["chunk"], validate=True) == expected and block["eof"], block
        checks = '''import errno
from pathlib import Path
for path in ('.git/config','readonly/value','/tmp/no-implicit-grant'):
 try: Path(path).write_text('forbidden')
 except OSError as error: assert error.errno in (errno.EACCES,errno.EPERM), error
 else: raise AssertionError('policy bypassed: '+path)
print('POLICY_DENIALS_PASS')
'''
        start(client, "denials", ["/usr/bin/python3", "-c", checks])
        result = completed(client, "denials")
        assert result["exitCode"] == 0 and b"POLICY_DENIALS_PASS" in output(result), result
        for name in ("readonly/value", ".git/config"):
            assert (workspace / name).read_bytes() == b"protected\n"
        assert not (case / "tmp/no-implicit-grant").exists()
        start(client, "temporary", ["/usr/bin/python3", "-c",
              "from pathlib import Path; p=Path('/tmp/explicit'); p.write_text('allowed'); assert p.read_text()=='allowed'; p.unlink()"],
              policy=context(tmp_write=True))
        assert completed(client, "temporary")["exitCode"] == 0
        assert not (case / "tmp/explicit").exists()
        sleeper = "import os,time; print('READY',os.getpid(),flush=True); time.sleep(100)"
        start(client, "lease", ["/usr/bin/python3", "-c", sleeper])
        ready(client, "lease")
        pending = client.request("fs/writeFile", {"path": MOUNT.append(("after",)).uri, "sandbox": context(), "dataBase64": "YWZ0ZXI="})
        success(client, "environment/status", {})
        assert pending not in client.responses and not (workspace / "after").exists()
        success(client, "process/terminate", {"processId": "lease"})
        assert "result" in client.response(pending)
        completed(client, "lease")
        assert (workspace / "after").read_bytes() == b"after"
        start(client, "disconnect", ["/usr/bin/python3", "-c", sleeper])
        pid = int(ready(client, "disconnect").decode().split("READY ", 1)[1].split()[0])
        client.close()
        leases_released()
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("A GNU process survived its transport EOF")
        following = peer()
        new = following.initialize()
        assert new["sessionId"] != initial["sessionId"]
        assert "error" in following.call("fs/readBlock", {"handleId": "artifact", "offset": 0, "len": 1})
        assert "error" in following.call("process/read", {"processId": "project"})
        following.close()
        leases_released()
        broker.terminate()
        assert broker.wait(10) == 0
        broker_log.seek(0)
        assert broker_log.read() == b"", "GNU broker emitted an unhandled error"
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
                   for path, digest in report["sources"].items()), "Diagnostic source changed during execution"
        report["passed"] = True
        report["observations"] = {"gnuShellMetadata": True, "safeParentEnvironment": True,
            "fileProcessRoundTrip": True, "streaming": True, "completePolicyDenials": True,
            "temporaryGrantExplicit": True, "fileLeaseWithResponsiveControl": True,
            "eofReapedProcess": pid, "workspaceAndTemporaryLeasesReleased": True, "sessionIsolation": True}
        print(json.dumps({"passed": True, "workspace": str(workspace), "evidence": str(options.evidence)}))
    finally:
        # The broker remains the cleanup owner, including after diagnostic
        # failure. Never erase its process-session marker to force a restart.
        for client in peers:
            if client.process.poll() is None:
                if not client.process.stdin.closed:
                    client.process.stdin.close()
        if broker is not None:
            if broker.poll() is None:
                broker.terminate()
            try:
                broker.wait(30)
            except subprocess.TimeoutExpired:
                report["cleanupUnknown"] = True
            if broker.poll() is not None:
                for line in broker.stdout.read().splitlines():
                    events.append({"broker": json.loads(line)})
        for client in peers:
            try:
                client.process.wait(10)
            except subprocess.TimeoutExpired:
                report["cleanupUnknown"] = True
            client.selector.close()
            if client.process.poll() is not None:
                for stream in (client.process.stdin, client.process.stdout, client.process.stderr):
                    if not stream.closed:
                        stream.close()
        broker_log.close()
        options.evidence.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("runner", "files-helper", "handle-helper", "bridge", "proot", "loader", "loader32", "rootfs", "parent", "evidence"):
        cli.add_argument("--" + name, type=Path, required=True)
    cli.add_argument("--address-space-bytes", type=int, default=256 * 1024 * 1024)
    cli.add_argument("--guest-workspace", default="/workspace")
    cli.add_argument("--android-home", type=Path)
    values = cli.parse_args()
    for name in ("runner", "files_helper", "handle_helper", "bridge", "proot", "loader", "loader32", "rootfs", "parent"):
        setattr(values, name, getattr(values, name).resolve(strict=True))
    main(values)
