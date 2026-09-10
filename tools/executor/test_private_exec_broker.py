"""Real unprivileged AF_UNIX/C-bridge/native-file IPC and lifecycle tests."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from tools.executor.native_files import NativeFilesBackend

BRIDGE = Path(os.environ["FOLDGPT_PRIVATE_BRIDGE"]).resolve(strict=True)
HELPER = Path(os.environ["FOLDGPT_NATIVE_FILES"]).resolve(strict=True)
BROKER = Path(__file__).with_name("private_exec_broker.py")


class RpcPeer:
    def __init__(self, process):
        self.process = process
        self.pending = bytearray()
        self.identifier = 0
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ)

    def send(self, message):
        self.process.stdin.write(json.dumps(message, ensure_ascii=False).encode() + b"\n")
        self.process.stdin.flush()

    def call(self, method, params):
        self.identifier += 1
        self.send({"id": self.identifier, "method": method, "params": params})
        deadline = time.monotonic() + 10
        while b"\n" not in self.pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError("Private native broker response deadline expired")
            data = os.read(self.process.stdout.fileno(), 65536)
            if not data:
                raise RuntimeError("Private bridge closed before its response")
            self.pending.extend(data)
        line, _, tail = self.pending.partition(b"\n")
        self.pending = bytearray(tail)
        value = json.loads(line)
        if value.get("id") != self.identifier:
            raise RuntimeError("Native broker changed RPC correlation")
        return value

    def initialize(self):
        value = self.call("initialize", {"clientName": "foldgpt-private-ipc-proof"})
        self.send({"method": "initialized", "params": {}})
        return value["result"]

    def close(self):
        self.process.stdin.close()
        self.process.wait(10)
        self.selector.close()
        self.process.stdout.close()
        diagnostic = self.process.stderr.read()
        self.process.stderr.close()
        if self.process.returncode != 0 or diagnostic or self.pending:
            raise RuntimeError(f"Bridge failed normal half-close: {self.process.returncode} {diagnostic!r}")


class PrivateIpcTests(unittest.TestCase):
    def setUp(self):
        self.assertNotEqual(os.getuid(), 0, "Run the real IPC proof without root")
        self.temporary = tempfile.TemporaryDirectory(prefix="fipc-", dir=os.environ.get("FOLDGPT_PRIVATE_TEST_PARENT"))
        self.root = Path(self.temporary.name)
        self.socket_dir = self.root / "ipc"
        self.workspace = self.root / "work"
        for directory in (self.socket_dir, self.workspace, self.root / "home", self.root / "tmp"):
            directory.mkdir(mode=0o700)
        (self.workspace / "private").mkdir(mode=0o700)
        (self.workspace / "value").write_bytes(b"original")
        self.environment = {"PATH": "/usr/bin:/bin", "HOME": str(self.root / "home"),
                            "TMPDIR": str(self.root / "tmp"), "LANG": "C.UTF-8"}
        self.children = []
        self.files = []

    def tearDown(self):
        for child in reversed(self.children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(5)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        for file in self.files:
            file.close()
        self.temporary.cleanup()

    def broker(self, uid=None, directory=None, ready=True):
        diagnostic = (self.root / f"broker-{len(self.children)}.log").open("wb")
        self.files.append(diagnostic)
        process = subprocess.Popen([sys.executable, "-I", "-S", "-B", str(BROKER),
            "--socket-dir", str(directory or self.socket_dir), "--helper", str(HELPER),
            "--workspace", str(self.workspace), "--guest-workspace", "/workspace",
            "--peer-uid", str(os.getuid() if uid is None else uid)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=diagnostic,
            cwd=self.workspace, env=self.environment, start_new_session=True)
        self.children.append(process)
        if ready:
            self.assertEqual(self.event(process)["event"], "ready")
        return process

    def event(self, process):
        # Buffered readline owns a single complete JSON event at a time. Broker
        # events are small, bounded metadata and no RPC payload is logged.
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            self.assertTrue(selector.select(10), "Broker lifecycle event deadline expired")
            line = process.stdout.readline()
            self.assertTrue(line, "Broker exited before lifecycle event")
            return json.loads(line)
        finally:
            selector.close()

    def bridge(self, uid=None, path=None):
        child = subprocess.Popen([str(BRIDGE), "--socket", str(path or self.socket_dir / "exec.sock"),
            "--peer-uid", str(os.getuid() if uid is None else uid)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=self.workspace, env=self.environment)
        self.children.append(child)
        return child

    def policy(self, access="write"):
        return {"permissions": {"type": "managed", "file_system": {"type": "restricted", "entries": [
            {"path": {"type": "special", "value": {"kind": "root"}}, "access": "read"},
            {"path": {"type": "path", "path": "file:///workspace"}, "access": access},
            {"path": {"type": "path", "path": "file:///workspace/private"}, "access": "deny"}]},
            "network": "restricted"}, "cwd": "file:///workspace", "workspaceRoots": ["file:///workspace"],
            "windowsSandboxLevel": "disabled"}

    def unlockable_workspace(self):
        fd = os.open(self.workspace, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    def test_native_rpc_policy_bytes_session_busy_and_reconnect(self):
        broker = self.broker()
        first = RpcPeer(self.bridge())
        initialized = first.initialize()
        self.assertFalse(any(initialized["environmentInfo"]["capabilities"].values()))
        self.assertEqual(initialized["environmentInfo"]["cwd"], "file:///workspace")
        with self.assertRaises(BlockingIOError):
            self.unlockable_workspace()
        payload = bytes(range(256)) * 1024 + "épreuves 🐍".encode()
        encoded = base64.b64encode(payload).decode()
        self.assertIn("result", first.call("fs/writeFile", {"path": "file:///workspace/value",
            "dataBase64": encoded, "sandbox": self.policy()}))
        self.assertEqual((self.workspace / "value").read_bytes(), payload)
        read = first.call("fs/readFile", {"path": "file:///workspace/value", "sandbox": self.policy()})
        self.assertEqual(base64.b64decode(read["result"]["dataBase64"]), payload)
        refusal = first.call("fs/writeFile", {"path": "file:///workspace/value", "dataBase64": "eA==", "sandbox": self.policy("read")})
        self.assertEqual(refusal["error"]["code"], -32000)
        self.assertEqual((self.workspace / "value").read_bytes(), payload)
        unknown = first.call("process/read", {"processId": "not-a-process", "maxBytes": 1})
        self.assertIn("error", unknown)
        second = self.bridge()
        output, _ = second.communicate(b'{"id":1,"method":"initialize","params":{"clientName":"busy"}}\n', timeout=10)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(output, b"")
        self.assertEqual(first.call("environment/status", {})["result"], {"status": "ready"})
        first.close()
        self.unlockable_workspace()
        replacement = RpcPeer(self.bridge())
        other = replacement.initialize()
        self.assertNotEqual(initialized["sessionId"], other["sessionId"])
        replacement.close()
        self.unlockable_workspace()
        broker.terminate()
        self.assertEqual(broker.wait(10), 0)
        self.assertFalse((self.socket_dir / "exec.sock").exists())

    def test_server_rejects_unexpected_uid_before_backend(self):
        broker = self.broker(uid=os.getuid() + 1)
        child = self.bridge()
        output, _ = child.communicate(b'{"id":1,"method":"initialize","params":{"clientName":"denied"}}\n', timeout=10)
        self.assertEqual(output, b"")
        self.assertNotEqual(child.returncode, 0)
        self.unlockable_workspace()
        self.assertIsNone(broker.poll())

    def test_bridge_rejects_unexpected_server_uid_without_sending(self):
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.socket_dir / "exec.sock"))
        listener.listen(1)
        listener.settimeout(5)
        try:
            child = self.bridge(uid=os.getuid() + 1)
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(5)
                output, error = child.communicate(b"MUST-NOT-REACH-PEER", timeout=5)
                self.assertEqual(connection.recv(128), b"")
            self.assertEqual(child.returncode, 77)
            self.assertEqual(output, b"")
            self.assertIn(b"authentication/connect", error)
        finally:
            listener.close()

    def test_raw_bidirectional_backpressure_and_half_close(self):
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.socket_dir / "exec.sock"))
        listener.listen(1)
        listener.settimeout(10)
        result = {}
        def echo():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(10)
                    result["credentials"] = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    h = hashlib.sha256()
                    while data := connection.recv(8191):
                        h.update(data)
                        connection.sendall(data)
                    connection.sendall(b"AFTER-INPUT-EOF")
                    connection.shutdown(socket.SHUT_WR)
                    result["hash"] = h.hexdigest()
            except BaseException as error:
                result["error"] = error
        thread = threading.Thread(target=echo)
        thread.start()
        payload = bytes(range(256)) * 8192 + b"unterminated\x00tail"
        try:
            child = self.bridge()
            output, error = child.communicate(payload, timeout=15)
            thread.join(10)
            self.assertFalse(thread.is_alive(), "Raw Unix peer did not finish")
            if "error" in result:
                raise result["error"]
            self.assertEqual(result["credentials"][1], os.getuid())
            self.assertEqual(result["hash"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(output, payload + b"AFTER-INPUT-EOF")
            self.assertEqual(error, b"")
            self.assertEqual(child.returncode, 0)
        finally:
            listener.close()
            thread.join(10)

    def test_supervisor_stop_cleans_idle_active_connection_and_lease(self):
        broker = self.broker()
        peer = RpcPeer(self.bridge())
        peer.initialize()
        with self.assertRaises(BlockingIOError):
            self.unlockable_workspace()
        broker.terminate()
        self.assertEqual(broker.wait(10), 0)
        peer.process.wait(10)
        self.assertNotEqual(peer.process.returncode, 0)
        peer.selector.close()
        self.unlockable_workspace()
        self.assertFalse((self.socket_dir / "exec.sock").exists())

    def test_private_directory_alias_stale_path_and_competitor_refused(self):
        alias = self.root / "alias"
        alias.symlink_to(self.socket_dir, target_is_directory=True)
        self.assertNotEqual(self.broker(directory=alias, ready=False).wait(10), 0)
        self.socket_dir.chmod(0o750)
        self.assertNotEqual(self.broker(ready=False).wait(10), 0)
        self.socket_dir.chmod(0o700)
        stale = self.socket_dir / "exec.sock"
        stale.write_bytes(b"supervisor-owned-sentinel")
        self.assertNotEqual(self.broker(ready=False).wait(10), 0)
        self.assertEqual(stale.read_bytes(), b"supervisor-owned-sentinel")
        stale.unlink()
        broker = self.broker()
        self.assertNotEqual(self.broker(ready=False).wait(10), 0)
        self.assertIsNone(broker.poll())

    def test_shutdown_preserves_replaced_socket_path(self):
        broker = self.broker()
        path = self.socket_dir / "exec.sock"
        path.unlink()
        path.write_bytes(b"replacement-must-survive")
        broker.terminate()
        self.assertEqual(broker.wait(10), 0)
        self.assertEqual(path.read_bytes(), b"replacement-must-survive")


if __name__ == "__main__":
    unittest.main()
