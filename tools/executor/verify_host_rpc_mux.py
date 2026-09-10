"""Actual official host file/watch/process/PTY traffic through the split relay.

All profiles and data are fresh and private. No account, thread, turn or model
request is made. Confined command execution is deliberately not claimed here.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.executor.test_native_executor_transport import Peer


def main(options):
    assert os.getuid() != 0
    official = options.official.resolve(strict=True)
    assert hashlib.sha256(official.read_bytes()).hexdigest() == options.official_sha256
    source = Path(__file__).resolve().parent
    case = Path(tempfile.mkdtemp(prefix="host-mux-", dir=options.parent))
    workspace = case / "workspace"
    for name in ("main", "host", "home", "workspace", "tmp", "config", "cache", "state"):
        (case / name).mkdir(mode=0o700)
    common = {"PATH": "/usr/bin:/bin", "HOME": str(case / "home"), "TMPDIR": str(case / "tmp"),
              "XDG_CONFIG_HOME": str(case / "config"), "XDG_CACHE_HOME": str(case / "cache"),
              "XDG_STATE_HOME": str(case / "state"), "LANG": "C.UTF-8", "RUST_LOG": "error",
              "FOLDGPT_PARENT": "synthetic-parent", "FOLDGPT_UNSET": "synthetic-remove"}
    for role in ("main", "host"):
        (case / role / "config.toml").write_text('check_for_update_on_startup = false\n')
        launch = {"argv": [str(official), "app-server", "--listen", "stdio://"],
                  "cwd": str(workspace), "environment": {**common, "CODEX_HOME": str(case / role)}}
        (case / (role + ".json")).write_text(json.dumps(launch))
    # Only a separate configured environment exists in main. This transport
    # test does not claim that the diagnostic environment executes commands.
    (case / "main/environments.toml").write_text('default = "host-mux-proof"\ninclude_local = false\n'
        '[[environments]]\nid = "host-mux-proof"\nprogram = "/usr/bin/python3"\n'
        'args = ["-B", ' + json.dumps(str(source / "exec_server.py")) + ']\ncwd = '
        + json.dumps(str(workspace)) + '\n')
    (case / "host/environments.toml").write_text('default = "local"\ninclude_local = true\n')
    events, observed_pids = [], []
    report = {"passed": False, "scope": "two actual official servers; host RPC mapping only",
              "accountRequests": 0, "threadRequests": 0, "modelRequests": 0,
              "uid": os.getuid(), "case": str(case), "officialSha256": options.official_sha256,
              "events": events, "sources": {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                  for name in ("host_rpc_mux.py", "verify_host_rpc_mux.py", "exec_server.py")}}
    stderr = (case / "stderr.log").open("w+b")
    process = subprocess.Popen([sys.executable, "-I", "-S", "-B", str(source / "host_rpc_mux.py"),
        "--official", str(official), "--official-sha256", options.official_sha256,
        "--main-launch", str(case / "main.json"), "--host-launch", str(case / "host.json")],
        env=common, cwd=workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, bufsize=0)
    peer = Peer(process, events)

    def result(method, params):
        value = peer.call(method, params)
        assert "result" in value, value
        return value["result"]

    def notification(method, handle=None, *, predicate=None):
        deadline = time.monotonic() + 15
        while True:
            for item in peer.notifications:
                if item["method"] == method and (handle is None or item["params"].get("processHandle") == handle):
                    if predicate is None or predicate(item["params"]):
                        return item["params"]
            if time.monotonic() > deadline:
                raise TimeoutError("Expected official host notification was not received")
            assert peer.receive(max(0, deadline - time.monotonic())) is not None

    def streamed(handle):
        return b"".join(base64.b64decode(item["params"]["deltaBase64"], validate=True)
                        for item in peer.notifications
                        if item["method"] == "process/outputDelta" and item["params"]["processHandle"] == handle)

    try:
        initial = result("initialize", {"clientInfo": {"name": "foldgpt_host_mux_proof", "version": "1"},
                                       "capabilities": {"experimentalApi": True}})
        assert initial["codexHome"] == str(case / "main"), initial
        peer.send({"method": "initialized", "params": {}})
        assert result("environment/status", {"environmentId": "local"})["status"] == "ready"
        assert result("environment/info", {"environmentId": "host-mux-proof"})["cwd"] == workspace.as_uri()
        payload = b"actual official file RPC\x00\xff"
        target = workspace / "a/b/value"
        result("fs/createDirectory", {"path": str(target.parent)})
        result("fs/writeFile", {"path": str(target), "dataBase64": base64.b64encode(payload).decode()})
        assert target.read_bytes() == payload
        alias = workspace / "alias"
        alias.symlink_to(target)
        assert base64.b64decode(result("fs/readFile", {"path": str(alias)})["dataBase64"], validate=True) == payload
        assert result("fs/getMetadata", {"path": str(alias)})["isSymlink"]
        result("fs/copy", {"sourcePath": str(workspace / "a"), "destinationPath": str(workspace / "copy"), "recursive": True})
        assert (workspace / "copy/b/value").read_bytes() == payload
        listing = result("fs/readDirectory", {"path": str(workspace)})
        assert {entry["fileName"] for entry in listing["entries"]} >= {"a", "copy", "alias"}
        result("fs/watch", {"watchId": "watch", "path": str(target.parent)})
        result("fs/writeFile", {"path": str(target), "dataBase64": "Y2hhbmdlZA=="})
        change = notification("fs/changed", predicate=lambda p: p["watchId"] == "watch")
        assert str(target) in change["changedPaths"], change
        result("fs/unwatch", {"watchId": "watch"})
        result("fs/remove", {"path": str(workspace / "copy")})
        result("fs/remove", {"path": str(workspace / "already-absent")})
        assert not (workspace / "copy").exists()
        script = "import os,sys; assert os.environ['FOLDGPT_PARENT']=='synthetic-parent'; assert 'FOLDGPT_UNSET' not in os.environ; assert os.environ['EXACT']=='one two'; sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.exit(23)"
        result("process/spawn", {"command": ["/usr/bin/python3", "-c", script], "processHandle": "binary",
            "cwd": str(workspace), "streamStdin": True, "streamStdoutStderr": True,
            "env": {"FOLDGPT_UNSET": None, "EXACT": "one two"}})
        result("process/writeStdin", {"processHandle": "binary", "deltaBase64": "AP9BQkM=", "closeStdin": True})
        exited = notification("process/exited", "binary")
        assert exited["exitCode"] == 23 and exited["stdout"] == "", exited
        assert streamed("binary") == b"\0\xffABC", streamed("binary")
        # The real official PTY path owns terminal allocation, resize, echo,
        # input/output and exit. No PTY response is synthesized by the mux.
        tty_script = "import os,sys; print('TTY',*os.get_terminal_size(),flush=True); input(); print('RESIZED',*os.get_terminal_size(),flush=True)"
        result("process/spawn", {"command": ["/usr/bin/python3", "-u", "-c", tty_script], "processHandle": "tty",
            "cwd": str(workspace), "tty": True, "size": {"rows": 19, "cols": 61}})
        notification("process/outputDelta", "tty", predicate=lambda p: b"TTY 61 19" in base64.b64decode(p["deltaBase64"]))
        result("process/resizePty", {"processHandle": "tty", "size": {"rows": 31, "cols": 97}})
        result("process/writeStdin", {"processHandle": "tty", "deltaBase64": "Cg=="})
        assert notification("process/exited", "tty")["exitCode"] == 0
        assert b"RESIZED 97 31" in streamed("tty"), streamed("tty")
        for name in ("kill", "eof"):
            result("process/spawn", {"command": ["/usr/bin/python3", "-u", "-c",
                "import os,time; print('PID',os.getpid(),flush=True); time.sleep(100)"],
                "processHandle": name, "cwd": str(workspace), "streamStdoutStderr": True})
            notification("process/outputDelta", name, predicate=lambda p: b"PID " in base64.b64decode(p["deltaBase64"]))
            pid = int(streamed(name).decode().split("PID ", 1)[1].split()[0])
            observed_pids.append(pid)
            if name == "kill":
                result("process/kill", {"processHandle": name})
                assert notification("process/exited", name)["exitCode"] != 0
        malformed = peer.call("command/exec", {"command": ["/usr/bin/true"],
                              "sandboxPolicy": {"type": "readOnly"}, "permissionProfile": "synthetic-missing"})
        assert "error" in malformed and "cannot be combined" in malformed["error"]["message"], malformed
        # This is an explicit test request for the official API's unconfined
        # mode. It does not replace or relax any caller's confined policy.
        executed = result("command/exec", {"command": ["/bin/sh", "-c", "printf actual-command; exit 17"],
                           "cwd": str(workspace), "sandboxPolicy": {"type": "dangerFullAccess"}})
        assert executed["exitCode"] == 17 and executed["stdout"] == "actual-command", executed
        streamed_command = peer.request("command/exec", {"command": ["/usr/bin/python3", "-u", "-c",
            "import sys; print('COMMAND_READY',flush=True); sys.stdout.buffer.write(sys.stdin.buffer.read()); sys.exit(7)"],
            "cwd": str(workspace), "processId": "command-stream", "streamStdin": True,
            "streamStdoutStderr": True, "sandboxPolicy": {"type": "dangerFullAccess"}})
        notification("command/exec/outputDelta", predicate=lambda p: p["processId"] == "command-stream"
                     and b"COMMAND_READY" in base64.b64decode(p["deltaBase64"]))
        assert streamed_command not in peer.responses
        result("command/exec/write", {"processId": "command-stream", "deltaBase64": "AP9YWVo=", "closeStdin": True})
        command_response = peer.response(streamed_command)
        assert command_response["result"]["exitCode"] == 7 and command_response["result"]["stdout"] == "", command_response
        command_bytes = b"".join(base64.b64decode(item["params"]["deltaBase64"], validate=True)
            for item in peer.notifications if item["method"] == "command/exec/outputDelta"
            and item["params"]["processId"] == "command-stream")
        assert command_bytes == b"COMMAND_READY\n\0\xffXYZ", command_bytes
        guarded = workspace / "read-only-must-survive"
        guarded.write_bytes(b"unchanged")
        confined = peer.call("command/exec", {"command": ["/usr/bin/python3", "-c",
            "from pathlib import Path; Path('read-only-must-survive').write_bytes(b'POLICY_BYPASS')"],
            "cwd": str(workspace), "sandboxPolicy": {"type": "readOnly"}})
        assert guarded.read_bytes() == b"unchanged", confined
        assert "error" in confined or confined["result"]["exitCode"] != 0, confined
        report["confinedCommandObservation"] = confined
        process.stdin.close()
        while peer.receive() is not None:
            pass
        assert process.wait(30) == 0
        for pid in observed_pids:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("An official host process survived kill or connection EOF")
        assert not (case / "host/sessions").exists() and not (case / "main/sessions").exists()
        assert not (case / "host/auth.json").exists() and not (case / "main/auth.json").exists()
        assert all(hashlib.sha256((source / name).read_bytes()).hexdigest() == digest
                   for name, digest in report["sources"].items())
        report["passed"] = True
        report["observations"] = {"mainInitializationAuthoritative": True, "hostLocalEnvironmentAvailable": True,
            "mainNamedEnvironmentAvailable": True, "fileReadWriteCopyRemoveAndSymlink": True,
            "actualFilesystemWatch": True, "binaryInputOutputAndExit23": True, "environmentUnsetPreserved": True,
            "ptyInitialSizeAndResize": True, "processKillAndEofCleanup": observed_pids,
            "commandInvalidPolicyErrorPreserved": True, "explicitUnconfinedCommandExit17": True,
            "commandStreamAndDeferredExit7": True, "readOnlyRequestNeverWroteProtectedFile": True,
            "confinedCommandExecutionValidated": False, "threadShellCommandImplemented": False}
        print(json.dumps({"passed": True, "evidence": str(options.evidence), "case": str(case)}))
    finally:
        if process.poll() is None:
            if not process.stdin.closed:
                process.stdin.close()
            try:
                process.wait(30)
            except subprocess.TimeoutExpired:
                report["cleanupUnknown"] = True
        peer.selector.close()
        for stream in (process.stdin, process.stdout):
            if not stream.closed:
                stream.close()
        stderr.close()
        options.evidence.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--official", type=Path, required=True)
    cli.add_argument("--official-sha256", required=True)
    cli.add_argument("--parent", type=Path, required=True)
    cli.add_argument("--evidence", type=Path, required=True)
    main(cli.parse_args())
