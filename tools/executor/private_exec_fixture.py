"""Offline native broker + GNU guest bridge proof, entirely supervisor-owned.

The command file is a fixed argv array prepared by the debug supervisor, never
an Intent payload. It may invoke PRoot for the guest bridge; the native broker
and this collector remain outside it. No account or model request is involved.
"""
import argparse
import asyncio
import base64
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.executor.native_files import NativeFilesBackend
from tools.executor.native_files_rpc_fixture import context, file_hash, observation, require

STREAM_BYTES = 37 * 1024 * 1024 + 13


def stream_bytes(offset, length):
    return bytes(range(256)) * ((offset % 256 + length + 255) // 256)


def pinned_descriptors(pid, identity):
    found = []
    for descriptor in (Path('/proc') / str(pid) / 'fd').iterdir():
        try:
            current = descriptor.stat()
        except FileNotFoundError:
            continue
        if (current.st_dev, current.st_ino) == identity:
            found.append(descriptor.name)
    return found


def exercise_streams(peer, workspace, broker_pid, index):
    target = workspace / 'stream-large.bin'
    metadata = target.stat()
    identity = (metadata.st_dev, metadata.st_ino)
    handle = 'stream-blocks'
    if index:
        old = peer.call('fs/readBlock', {'handleId': 'stream-eof-owned', 'offset': 0, 'len': 1})
        require(old.get('error', {}).get('code') == -32004, 'A new session retained an old stream handle')
    require(peer.call('fs/open', {'path': 'file:///workspace/stream-large.bin', 'handleId': handle,
        'sandbox': context()}).get('result') == {'handleId': handle}, 'Native stream open failed')
    require(len(pinned_descriptors(broker_pid, identity)) == 1, 'Broker did not pin exactly one large-file descriptor')
    for offset, length in ((0, 1048576), (16 * 1024 * 1024 + 17, 1048576),
                           (STREAM_BYTES - 13, 32), (STREAM_BYTES, 1)):
        result = peer.call('fs/readBlock', {'handleId': handle, 'offset': offset, 'len': length})['result']
        expected_length = min(length, max(0, STREAM_BYTES - offset))
        pattern = stream_bytes(offset, expected_length)
        expected = pattern[offset % 256:offset % 256 + expected_length]
        require(base64.b64decode(result['chunk'], validate=True) == expected
                and result['eof'] is (expected_length < length), 'Native pread bytes, offset or EOF differ')
    require(peer.call('fs/close', {'handleId': handle}).get('result') == {}, 'Native stream close failed')
    require(not pinned_descriptors(broker_pid, identity), 'Closed stream retained its physical descriptor')
    closed = peer.call('fs/readBlock', {'handleId': handle, 'offset': 0, 'len': 1})
    require(closed.get('error', {}).get('code') == -32004, 'Closed stream remained readable')
    denied = peer.call('fs/open', {'path': 'file:///workspace/private/secret', 'handleId': 'denied', 'sandbox': context()})
    require(denied.get('error', {}).get('code') == -32000, 'Private stream bypassed its read policy')
    absent = peer.call('fs/open', {'path': 'file:///workspace/absent-stream', 'handleId': 'absent', 'sandbox': context()})
    require(absent.get('error', {}).get('code') == -32004, 'Missing stream did not report missing file')
    require(peer.call('fs/open', {'path': 'file:///workspace/stream-large.bin', 'handleId': 'stream-eof-owned',
        'sandbox': context()}).get('result') == {'handleId': 'stream-eof-owned'}, 'EOF cleanup stream did not open')
    require(len(pinned_descriptors(broker_pid, identity)) == 1, 'EOF fixture did not retain exactly one live descriptor')


class BridgePeer:
    def __init__(self, command, environment, workspace, error_path):
        self.trace = []
        self.identifier = 0
        self.buffer = bytearray()
        self.error = error_path.open("xb")
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.error, cwd=workspace, env=environment, start_new_session=True)
        except BaseException:
            self.error.close()
            raise
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def send(self, message):
        self.process.stdin.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")
        self.process.stdin.flush()

    def call(self, method, params):
        self.identifier += 1
        self.send({"id": self.identifier, "method": method, "params": params})
        deadline = time.monotonic() + 15
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            require(remaining > 0 and self.selector.select(remaining), "Private bridge response deadline expired")
            data = os.read(self.process.stdout.fileno(), 65536)
            require(data, "Private bridge closed before a response")
            self.buffer.extend(data)
            require(len(self.buffer) <= 2 * 1024 * 1024, "Private bridge fixture response exceeds bound")
        line, _, tail = self.buffer.partition(b"\n")
        self.buffer = bytearray(tail)
        value = json.loads(line)
        require(value.get("id") == self.identifier and ("result" in value) != ("error" in value),
                "Private bridge changed RPC correlation/envelope")
        self.trace.append({"method": method, "params": params, "response": value})
        return value

    def close(self, expected):
        failure = None
        def signal_group(number):
            try:
                os.killpg(self.process.pid, number)
            except ProcessLookupError:
                pass
        try:
            if not expected:
                # Let PRoot execute --kill-on-exit and reap its tracees before
                # considering any forced termination of the complete group.
                signal_group(signal.SIGTERM)
            try:
                self.process.stdin.close()
            except OSError as error:
                failure = error
            try:
                self.process.wait(10 if expected else 5)
            except subprocess.TimeoutExpired:
                failure = RuntimeError("Guest bridge exceeded cooperative cleanup deadline")
                signal_group(signal.SIGTERM)
                try:
                    self.process.wait(5)
                except subprocess.TimeoutExpired:
                    signal_group(signal.SIGKILL)
                    self.process.wait(2)
            if expected:
                require(self.process.returncode == 0, "Guest bridge failed normal EOF cleanup")
                require(not self.buffer and self.selector.select(10)
                        and not os.read(self.process.stdout.fileno(), 1), "Guest bridge left its output open")
            try:
                os.killpg(self.process.pid, 0)
            except ProcessLookupError:
                pass
            else:
                failure = RuntimeError("Guest bridge left processes in its fixture session")
                signal_group(signal.SIGTERM)
                signal_group(signal.SIGKILL)
            if failure is not None:
                raise failure
        finally:
            if self.process.poll() is None:
                signal_group(signal.SIGTERM)
                try:
                    self.process.wait(5)
                except subprocess.TimeoutExpired:
                    signal_group(signal.SIGKILL)
                    self.process.wait(2)
            self.selector.close()
            self.process.stdout.close()
            self.error.close()


def read_ready(process):
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        require(selector.select(10), "Native broker readiness deadline expired")
        line = process.stdout.readline()
        require(line, "Native broker closed before readiness")
        message = json.loads(line)
        require(message.get("event") == "ready", "Native broker did not report readiness")
        return message
    finally:
        selector.close()


def assert_unlocked(workspace):
    fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)


def execute(args):
    evidence = args.evidence.resolve(strict=True)
    metadata = evidence.stat()
    require(metadata.st_uid == os.getuid() and not stat.S_IMODE(metadata.st_mode) & 0o077,
            "Fixture evidence must be owned and private")
    workspace, ipc = evidence / "workspace", evidence / "ipc"
    for directory in (workspace, ipc, evidence / "home", evidence / "tmp"):
        directory.mkdir(mode=0o700)
    (workspace / ".git").mkdir(mode=0o700)
    (workspace / "private").mkdir(mode=0o700)
    (workspace / "value").write_bytes(b"initial")
    (workspace / ".git/config").write_bytes(b"metadata")
    if args.handle_helper:
        with (workspace / 'stream-large.bin').open('xb') as large:
            pattern = bytes(range(256)) * 4096
            for _ in range(37):
                large.write(pattern)
            large.write(bytes(range(13)))
        (workspace / 'private/secret').write_bytes(b'fixture-private-stream')
    command_file = args.bridge_command_file.resolve(strict=True)
    command = json.loads(command_file.read_text())
    require(type(command) is list and 1 <= len(command) <= 256
            and all(type(value) is str and value and "\x00" not in value for value in command),
            "Supervisor bridge command must be an argv array")
    uid = os.getuid()
    require(uid > 0 and (args.android_uid is None or uid == args.android_uid), "Unexpected native application UID")
    observed = observation(android_uid=args.android_uid)
    if args.android_home:
        require(args.android_uid is not None and sys.platform == "android", "Native Android Python is required")
        interpreter = [sys.executable, "--home", str(args.android_home.resolve(strict=True)), "--"]
    else:
        interpreter = [sys.executable, "-I", "-S", "-B"]
    environment = {"PATH": os.environ["PATH"], "HOME": str(evidence / "home"),
                   "TMPDIR": str(evidence / "tmp"), "LANG": "C.UTF-8"}
    guest_environment = dict(environment)
    # These are the app supervisor's known native PRoot loader inputs. The GNU
    # command prefix can independently start /usr/bin/env -i inside the guest.
    for name in ("LD_LIBRARY_PATH", "PROOT_LOADER", "PROOT_LOADER_32", "PROOT_TMP_DIR"):
        if name in os.environ:
            guest_environment[name] = os.environ[name]
    guest_environment.setdefault("PROOT_TMP_DIR", str(evidence / "tmp"))
    bridge_socket = args.guest_socket or str(ipc / "exec.sock")
    bridge_command = command + ["--socket", bridge_socket, "--peer-uid", str(uid)]
    broker_command = interpreter + [str(Path(__file__).with_name("private_exec_broker.py")),
        "--socket-dir", str(ipc), "--helper", str(args.helper.resolve(strict=True)),
        "--workspace", str(workspace), "--guest-workspace", "/workspace", "--peer-uid", str(uid)]
    if args.handle_helper:
        broker_command.extend(['--handle-helper', str(args.handle_helper.resolve(strict=True))])
    traces, checks, events = [], [], []
    ready = broker_observation = None
    sessions = []
    passed = False
    with (evidence / "broker-stderr.txt").open("xb") as diagnostic:
        broker = subprocess.Popen(broker_command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=diagnostic, cwd=workspace, env=environment, start_new_session=True)
        try:
            ready = read_ready(broker)
            events.append(ready)
            require(ready["pid"] == broker.pid and ready["uid"] == uid and ready["peerUid"] == uid,
                    "Native broker readiness identity differs")
            broker_observation = observation(broker.pid, android_uid=args.android_uid)
            require((ipc / "exec.sock").stat().st_uid == uid
                    and stat.S_IMODE((ipc / "exec.sock").stat().st_mode) == 0o600,
                    "Native broker socket is not private")
            checks.append("native-broker-uid-context-and-private-socket")
            for index in range(2):
                peer = BridgePeer(bridge_command, guest_environment, workspace, evidence / f"bridge-{index}-stderr.txt")
                good = False
                try:
                    result = peer.call("initialize", {"clientName": "foldgpt-private-guest-bridge"})["result"]
                    sessions.append(result["sessionId"])
                    features = {name for name, value in result['environmentInfo']['capabilities'].items() if value}
                    require(features == ({'sandboxedFileStreaming'} if args.handle_helper else set()),
                            'Broker advertised unsupported capabilities')
                    peer.send({"method": "initialized", "params": {}})
                    require(peer.call("environment/status", {})["result"] == {"status": "ready"}, "Native environment is not ready")
                    try:
                        assert_unlocked(workspace)
                    except BlockingIOError:
                        pass
                    else:
                        raise RuntimeError("Live broker session does not own the workspace lease")
                    payload = bytes(range(256)) * 1024 + f"épreuve-{index}-🐍".encode()
                    encoded = base64.b64encode(payload).decode()
                    require("result" in peer.call("fs/writeFile", {"path": "file:///workspace/value",
                        "dataBase64": encoded, "sandbox": context()}), "Actual native write was refused")
                    require((workspace / "value").read_bytes() == payload, "Physical write bytes differ")
                    read = peer.call("fs/readFile", {"path": "file:///workspace/value", "sandbox": context()})["result"]
                    require(base64.b64decode(read["dataBase64"]) == payload, "Guest bridge read bytes differ")
                    denied = peer.call("fs/writeFile", {"path": "file:///workspace/private/forbidden", "dataBase64": "eA==", "sandbox": context()})
                    require(denied.get("error", {}).get("code") == -32000
                            and not (workspace / "private/forbidden").exists(), "Native deny policy was not preserved")
                    metadata = peer.call("fs/writeFile", {"path": "file:///workspace/.git/config", "dataBase64": "eA==", "sandbox": context()})
                    require(metadata.get("error", {}).get("code") == -32000
                            and (workspace / ".git/config").read_bytes() == b"metadata", "Protected metadata changed")
                    tree_uri = "file:///workspace/tree"
                    require("result" in peer.call("fs/createDirectory", {"path": tree_uri,
                        "recursive": True, "sandbox": context()}), "Native directory creation failed")
                    require("result" in peer.call("fs/writeFile", {"path": tree_uri + "/data",
                        "dataBase64": encoded, "sandbox": context()}), "Native tree data write failed")
                    source_identity = (workspace / "tree/data").stat().st_ino
                    listing = peer.call("fs/readDirectory", {"path": tree_uri, "sandbox": context()})
                    require(listing.get("result") == {"entries": [{"fileName": "data", "isDirectory": False,
                        "isFile": True}]}, "Directory RPC differs from the physical tree")
                    walked = peer.call("fs/walk", {"path": tree_uri, "sandbox": context(), "options": {
                        "maxDepth": 4, "maxDirectories": 10, "maxEntries": 100, "followDirectorySymlinks": False}})
                    require(walked.get("result") == {"entries": [{"path": tree_uri + "/data", "kind": "file"}],
                        "errors": [], "truncated": False}, "Walk RPC differs from the physical tree")
                    require("result" in peer.call("fs/copy", {"sourcePath": tree_uri,
                        "destinationPath": "file:///workspace/copied", "recursive": True, "sandbox": context()}),
                        "Recursive native copy failed")
                    require((workspace / "copied/data").read_bytes() == payload
                            and (workspace / "copied/data").stat().st_ino != source_identity
                            and (workspace / "tree/data").stat().st_ino == source_identity,
                            "Copy did not preserve source identity and create independent data")
                    refused_copy = peer.call("fs/copy", {"sourcePath": "file:///workspace/private",
                        "destinationPath": "file:///workspace/forbidden-copy", "recursive": True, "sandbox": context()})
                    require(refused_copy.get("error", {}).get("code") == -32000
                            and not (workspace / "forbidden-copy").exists(), "Denied copy mutated its destination")
                    refused_remove = peer.call("fs/remove", {"path": "file:///workspace/.git",
                        "recursive": True, "sandbox": context()})
                    require(refused_remove.get("error", {}).get("code") == -32000
                            and (workspace / ".git/config").read_bytes() == b"metadata", "Recursive remove changed metadata")
                    require("result" in peer.call("fs/remove", {"path": tree_uri, "sandbox": context()})
                            and not (workspace / "tree").exists()
                            and (workspace / "copied/data").read_bytes() == payload, "Source removal affected its independent copy")
                    require("result" in peer.call("fs/remove", {"path": "file:///workspace/copied", "sandbox": context()})
                            and not (workspace / "copied").exists(), "Recursive native removal failed")
                    checks.append(f"guest-tree-rpcs-and-protected-mutation-refusals-{index}")
                    if args.handle_helper:
                        exercise_streams(peer, workspace, broker.pid, index)
                    process = peer.call("process/start", {"processId": "unsupported", "argv": ["/system/bin/true"],
                        "cwd": "file:///workspace", "env": {}, "tty": False, "sandbox": context()})
                    require(process.get("error", {}).get("code") == -32601, "Broker substituted a process capability")
                    good = True
                finally:
                    try:
                        peer.close(good)
                    finally:
                        traces.extend(peer.trace)
                backend = NativeFilesBackend(args.helper, workspace)
                asyncio.run(backend.close(None))
                if args.handle_helper:
                    info = (workspace / 'stream-large.bin').stat()
                    require(not pinned_descriptors(broker.pid, (info.st_dev, info.st_ino)),
                            'Session EOF left a native file descriptor open')
                    checks.append(f'guest-streaming-large-binary-offsets-policy-and-fd-cleanup-{index}')
                checks.append(f"guest-bridge-native-rpc-policy-and-eof-cleanup-{index + 1}")
            require(sessions[0] != sessions[1], "New connection reused an old protocol session")
            checks.append("distinct-reconnected-sessions")
            passed = True
        finally:
            broker.terminate()
            try:
                code = broker.wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(broker.pid, signal.SIGKILL)
                broker.wait(2)
                raise RuntimeError("Native broker did not finish supervisor shutdown")
            finally:
                raw_events = broker.stdout.read()
                broker.stdout.close()
                for line in raw_events.splitlines():
                    events.append(json.loads(line))
                (evidence / "broker-events.json").write_text(json.dumps(events, indent=2) + "\n")
                (evidence / "rpc-transcript.json").write_text(json.dumps(traces, indent=2) + "\n")
            if passed:
                require(code == 0 and not (ipc / "exec.sock").exists(), "Broker shutdown left its socket or failed")
                assert_unlocked(workspace)
    authenticated = [event["peer"] for event in events if event["event"] == "session-open"]
    require(len(authenticated) == 2 and all(peer["uid"] == uid and peer["pid"] > 0 for peer in authenticated),
            "Broker did not independently authenticate both guest bridge peers")
    checks.append("broker-peer-credentials-and-supervisor-socket-cleanup")
    return {"schema": "foldgpt.private-exec-fixture.v2" if args.handle_helper else "foldgpt.private-exec-fixture.v1",
        "status": "PASS", "checks": checks,
        "rpcResponses": len(traces), "sessions": sessions, "authenticatedBridgePeers": authenticated,
        "nativeHelperSha256": file_hash(args.helper), "bridgeCommandFileSha256": file_hash(command_file),
        "observation": observed, "brokerObservation": broker_observation,
        "workspace": str(workspace), "valueSha256": file_hash(workspace / "value"),
        "streaming": {'helperSha256': file_hash(args.handle_helper), 'fileBytes': STREAM_BYTES,
                      'fileSha256': file_hash(workspace / 'stream-large.bin')}
                     if args.handle_helper else None,
        "limit": "Private transport and supported file RPCs; UID checks do not distinguish programs sharing one app UID"}


def main():
    def terminate(_number, _frame):
        # A second SIGTERM must not interrupt ownership cleanup in finally.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt("Supervisor requested private fixture cleanup")
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--handle-helper", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--bridge-command-file", type=Path, required=True)
    parser.add_argument("--guest-socket")
    parser.add_argument("--android-home", type=Path)
    parser.add_argument("--android-uid", type=int)
    args = parser.parse_args()
    result = execute(args)
    (args.evidence / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
