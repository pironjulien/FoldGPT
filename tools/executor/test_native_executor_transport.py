"""Real nonroot stdio -> C bridge -> AF_UNIX -> composite kernel tests.

No model, Desktop configuration, Android device or live workspace is accessed.
Every request/notification and independent physical observation is retained.
"""
import argparse
import base64
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.executor.test_native_processes_live import context, process_children_snapshot

OPTIONS = None
OBSERVATIONS = []
BROKER = Path(__file__).with_name("private_exec_broker.py")


class Peer:
    def __init__(self, process, events, initialized=None):
        self.process, self.events = process, events
        self.initialized = initialized
        self.native_pidfd = -1
        self.buffer = bytearray()
        self.identifier = 0
        self.responses = {}
        self.notifications = []
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ)

    def send(self, value):
        self.events.append({"direction": "request", "message": value})
        self.process.stdin.write(json.dumps(value, ensure_ascii=False).encode() + b"\n")
        self.process.stdin.flush()

    def request(self, method, params):
        self.identifier += 1
        self.send({"id": self.identifier, "method": method, "params": params})
        return self.identifier

    def receive(self, timeout=10):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError("Composite response deadline expired")
            data = os.read(self.process.stdout.fileno(), 65536)
            if not data:
                if self.buffer:
                    raise RuntimeError("Truncated actual RPC frame")
                return None
            self.buffer.extend(data)
        line, _, tail = self.buffer.partition(b"\n")
        self.buffer = bytearray(tail)
        value = json.loads(line)
        self.events.append({"direction": "response", "message": value})
        if "id" in value:
            if value["id"] in self.responses:
                raise RuntimeError("Duplicate actual RPC response")
            self.responses[value["id"]] = value
        else:
            self.notifications.append(value)
        return value

    def response(self, identifier, timeout=10):
        deadline = time.monotonic() + timeout
        while identifier not in self.responses:
            if self.receive(max(0, deadline - time.monotonic())) is None:
                raise RuntimeError("Actual bridge closed before its response")
        return self.responses.pop(identifier)

    def call(self, method, params):
        return self.response(self.request(method, params))

    def initialize(self):
        result = self.call("initialize", {"clientName": "foldgpt-composite-proof"})["result"]
        self.send({"method": "initialized", "params": {}})
        if self.initialized is not None:
            self.initialized(self)
        return result

    def close(self):
        self.process.stdin.close()
        while self.receive() is not None:
            pass
        self.process.wait(10)
        self.selector.close()
        if self.native_pidfd >= 0:
            os.close(self.native_pidfd); self.native_pidfd = -1
        error = self.process.stderr.read()
        if self.process.returncode != 0 or error:
            raise RuntimeError(f"Bridge EOF failed: {self.process.returncode}, {error!r}")


class CompositeTransportTests(unittest.TestCase):
    def children(self, pid):
        snapshot = process_children_snapshot(pid)
        self.events.append({'childSnapshot': snapshot})
        return set(snapshot['children'])

    def setUp(self):
        self.assertNotEqual(os.getuid(), 0, "Kernel/IPC tests must execute without root")
        self.temporary = tempfile.TemporaryDirectory(prefix="fcomp-", dir=OPTIONS.parent, delete=not OPTIONS.retain_cases)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "work"
        self.socket_dir = self.root / "ipc"
        for path in (self.workspace, self.socket_dir, self.root / "home", self.root / "tmp"):
            path.mkdir(mode=0o700)
        (self.workspace / "private").mkdir(mode=0o700)
        (self.workspace / "private/secret").write_bytes(b"private-intact")
        (self.workspace / "value").write_bytes(b"original")
        (self.workspace / "private/secret").chmod(0o600)
        (self.workspace / "value").chmod(0o600)
        self.environment = {"PATH": "/usr/bin:/bin", "HOME": str(self.root / "home"),
                            "TMPDIR": str(self.root / "tmp"), "LANG": "C.UTF-8"}
        self.processes, self.streams, self.peers = [], [], []
        self.brokers = {}
        self.events = []
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.pidfd_open.argtypes = [ctypes.c_int, ctypes.c_uint]
        self.libc.pidfd_open.restype = ctypes.c_int
        self.previous_subreaper = ctypes.c_int()
        self.assertEqual(self.libc.prctl(37, ctypes.byref(self.previous_subreaper), 0, 0, 0), 0)
        self.assertEqual(self.libc.prctl(36, 1, 0, 0, 0), 0)
        self.interpreter = [sys.executable, "-I", "-S", "-B"]
        if OPTIONS.android_home is not None:
            self.assertEqual(sys.platform, "android")
            self.assertEqual(os.getuid(), OPTIONS.android_uid)
            self.environment["PATH"] = "/system/bin"
            self.interpreter = [sys.executable, "--home", str(OPTIONS.android_home), "--"]
            (self.root / "shm").mkdir(mode=0o700)

    def tearDown(self):
        diagnostics = []
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(10)
            if process.pid in self.brokers:
                log, expected_success = self.brokers[process.pid]
                for line in process.stdout.read().splitlines():
                    self.events.append({"broker": json.loads(line)})
                log.seek(0)
                diagnostic = log.read()
                self.events.append({"brokerExit": process.returncode,
                    "brokerStderrBase64": base64.b64encode(diagnostic).decode()})
                if expected_success:
                    diagnostics.append(diagnostic)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        for peer in self.peers:
            peer.selector.close()
            if peer.native_pidfd >= 0:
                os.close(peer.native_pidfd); peer.native_pidfd = -1
        for stream in self.streams:
            stream.close()
        # Only this test's subreaper-adopted descendants, never other processes.
        for pid in self.children(os.getpid()):
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except ProcessLookupError:
                pass
        self.assertEqual(self.libc.prctl(36, self.previous_subreaper.value, 0, 0, 0), 0)
        OBSERVATIONS.append({"test": self.id(), "uid": os.getuid(), "events": self.events,
            "caseDirectory": str(self.root), "caseRetained": OPTIONS.retain_cases,
            "valueDevice": (self.workspace / "value").stat().st_dev,
            "valueInode": (self.workspace / "value").stat().st_ino,
            "finalValueBase64": base64.b64encode((self.workspace / "value").read_bytes()).decode(),
            "privateSha256": hashlib.sha256((self.workspace / "private/secret").read_bytes()).hexdigest()})
        if not OPTIONS.retain_cases:
            self.temporary.cleanup()
        self.assertTrue(all(not value for value in diagnostics),
            f"Actual broker emitted an unhandled error: {diagnostics!r}")

    def broker(self, extra=(), process_profile=True, ready=True):
        log = (self.root / f"broker-{len(self.processes)}.stderr").open("w+b")
        self.streams.append(log)
        command = [*self.interpreter, str(BROKER), "--socket-dir", str(self.socket_dir),
            "--helper", str(OPTIONS.files_helper), "--handle-helper", str(OPTIONS.handle_helper),
            "--workspace", str(self.workspace), "--guest-workspace", "/workspace", "--peer-uid", str(os.getuid())]
        if process_profile:
            command += ["--process-runner", str(OPTIONS.runner), "--executable", "native-fixture", str(OPTIONS.fixture),
                "--process-wall-ms", "3000", "--process-address-space-bytes", str(OPTIONS.address_space_bytes)]
        child = subprocess.Popen([*command, *extra], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log,
            env=self.environment, cwd=self.workspace, bufsize=0)
        self.processes.append(child)
        self.brokers[child.pid] = (log, ready)
        self.active_broker = child
        if ready:
            selector = selectors.DefaultSelector()
            try:
                selector.register(child.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(10), "Broker readiness timeout")
                value = json.loads(child.stdout.readline())
                self.events.append({"broker": value})
                self.assertEqual(value["event"], "ready")
                if OPTIONS.android_home is not None:
                    from tools.executor.native_files_rpc_fixture import observation
                    self.events.append({"nativeBrokerContext": observation(child.pid, android_uid=OPTIONS.android_uid)})
            finally:
                selector.close()
        return child

    def peer(self):
        command = [str(OPTIONS.bridge)]
        endpoint = str(self.socket_dir / "exec.sock")
        environment = self.environment
        if OPTIONS.android_home is not None:
            native = OPTIONS.native_directory
            environment = {**self.environment, "LD_LIBRARY_PATH": str(OPTIONS.proot_compat) + ":" + str(native),
                "PROOT_LOADER": str(native / "libproot-loader.so"),
                "PROOT_LOADER_32": str(native / "libproot-loader32.so"), "PROOT_TMP_DIR": str(self.root / "tmp")}
            command = [str(native / "libproot.so"), "--kill-on-exit", "--link2symlink", "--sysvipc",
                "-r", str(OPTIONS.guest_runtime), "-i", f"{os.getuid()}:{os.getgid()}", "-w", "/workspace"]
            for target in ("/dev", "/proc", "/sys", "/system", "/apex"):
                command.extend(["-b", target])
            for source, target in ((self.root / "tmp", "/tmp"), (self.root / "shm", "/dev/shm"),
                    (self.socket_dir, "/tmp/foldgpt-private-ipc"), (self.workspace, "/workspace"),
                    (self.root / "home", "/tmp/foldgpt-private-home"), (OPTIONS.bridge, "/tmp/foldgpt-exec-bridge")):
                command.extend(["-b", str(source) + ":" + target])
            command.extend(["/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "HOME=/tmp/foldgpt-private-home",
                "LANG=C.UTF-8", "/tmp/foldgpt-exec-bridge"])
            endpoint = "/tmp/foldgpt-private-ipc/exec.sock"
        child = subprocess.Popen([*command, "--socket", endpoint, "--peer-uid", str(os.getuid())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=environment, cwd=self.workspace, bufsize=0)
        self.processes.append(child)
        peer = Peer(child, self.events, self.identify_bridge)
        self.peers.append(peer)
        return peer

    def identify_bridge(self, peer):
        selector = selectors.DefaultSelector()
        selector.register(self.active_broker.stdout, selectors.EVENT_READ)
        try:
            while True:
                self.assertTrue(selector.select(10), "Authenticated bridge identity was not observed")
                event = json.loads(self.active_broker.stdout.readline())
                self.events.append({"broker": event})
                if event["event"] == "session-open":
                    identity = event["peer"]
                    break
        finally:
            selector.close()
        self.assertEqual(identity["uid"], os.getuid())
        peer.native_pidfd = self.libc.pidfd_open(identity["pid"], 0)
        self.assertGreaterEqual(peer.native_pidfd, 0)
        if OPTIONS.android_home is None:
            self.assertEqual(identity["pid"], peer.process.pid)
        else:
            proc = Path("/proc") / str(identity["pid"])
            status = dict(line.split(":", 1) for line in (proc / "status").read_text().splitlines() if ":" in line)
            self.assertEqual(int(status["TracerPid"]), peer.process.pid)
            self.assertEqual(status["Uid"].split(), [str(os.getuid())] * 4)
            maps = (proc / "maps").read_text()
            self.assertIn("libc.so.6", maps)
            self.events.append({"guestBridgeContext": {"pid": identity["pid"], "prootPid": peer.process.pid,
                "uid": os.getuid(), "tracerPid": int(status["TracerPid"]),
                "executable": os.readlink(proc / "exe"), "gnuLibcMapped": True}})

    def success(self, peer, method, params):
        response = peer.call(method, params)
        self.assertIn("result", response, response)
        return response["result"]

    def start(self, peer, name="process", args=("stdio",), **extra):
        return self.success(peer, "process/start", {"processId": name, "argv": ["native-fixture", *args],
            "cwd": "file:///workspace", "env": {}, "tty": False, "sandbox": context(), **extra})

    @staticmethod
    def output(value, stream="stdout"):
        return b"".join(base64.b64decode(chunk["chunk"], validate=True)
            for chunk in value["chunks"] if chunk["stream"] == stream)

    def completed(self, peer, name="process", closed=True):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            value = self.success(peer, "process/read", {"processId": name, "waitMs": 100})
            if value["closed"] or (not closed and value["failure"] is not None):
                return value
            time.sleep(0.01)
        self.fail("Actual process completion not observed")

    def until_output(self, peer, expected, name="process"):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            value = self.success(peer, "process/read", {"processId": name, "waitMs": 100})
            if expected in self.output(value):
                return value
        self.fail("Actual fixture output not observed")

    def lease(self, held):
        fd = os.open(self.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            if held:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    def absent(self, pid):
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_01_one_session_files_processes_streaming_and_actual_policy(self):
        broker = self.broker(); peer = self.peer(); initial = peer.initialize()
        self.assertEqual(initial["environmentInfo"]["cwd"], "file:///workspace")
        caps = initial["environmentInfo"]["capabilities"]
        self.assertEqual({name for name, value in caps.items() if value}, {"sandboxedFileStreaming"})
        self.lease(True)
        payload = b"actual-file-before-process"
        self.success(peer, "fs/writeFile", {"path": "file:///workspace/value", "sandbox": context(),
            "dataBase64": base64.b64encode(payload).decode()})
        inode = (self.workspace / "value").stat().st_ino
        self.start(peer, "read", ("open", "0", "value", str(os.O_RDONLY), "0", "unused"))
        self.assertEqual(self.output(self.completed(peer, "read")), payload)
        self.start(peer, "write", ("open", "0", "value", str(os.O_WRONLY | os.O_TRUNC), "0", "native-change"))
        self.assertEqual(self.completed(peer, "write")["exitCode"], 0)
        self.assertEqual((self.workspace / "value").read_bytes(), b"native-change")
        self.assertEqual((self.workspace / "value").stat().st_ino, inode)
        self.success(peer, "fs/open", {"handleId": "actual", "path": "file:///workspace/value", "sandbox": context()})
        block = self.success(peer, "fs/readBlock", {"handleId": "actual", "offset": 2, "len": 64})
        self.assertEqual(base64.b64decode(block["chunk"]), b"tive-change"); self.assertTrue(block["eof"])
        self.start(peer, "denied", ("open", "0", "value", str(os.O_RDWR | os.O_TRUNC), str(errno.EACCES), "forbidden"), sandbox=context("read"))
        self.assertEqual(self.output(self.completed(peer, "denied")), b"DENIED:13\n")
        self.assertIn("error", peer.call("fs/readFile", {"path": "file:///workspace/private/secret", "sandbox": context()}))
        for extra in ({"argv": ["/bin/sh", "-c", "true"]}, {"tty": True}, {"sandbox": None}):
            self.assertIn("error", peer.call("process/start", {"processId": "invalid", "argv": ["native-fixture", "eof"],
                "cwd": "file:///workspace", "env": {}, "tty": False, "sandbox": context(), **extra}))
        self.assertEqual((self.workspace / "value").read_bytes(), b"native-change")
        peer.close(); self.lease(False)
        self.assertFalse((self.socket_dir / "process-session.json").exists())
        other = self.peer(); following = other.initialize()
        self.assertNotEqual(initial["sessionId"], following["sessionId"])
        self.assertIn("error", other.call("fs/readBlock", {"handleId": "actual", "offset": 0, "len": 1}))
        self.assertIn("error", other.call("process/read", {"processId": "read"}))
        other.close(); broker.terminate(); self.assertEqual(broker.wait(10), 0)

    def test_02_stdin_binary_output_interrupt_and_terminate(self):
        self.broker(); peer = self.peer(); peer.initialize()
        self.start(peer, args=("echo", "5"), pipeStdin=True)
        message = {"processId": "process", "writeId": "one", "chunk": base64.b64encode(b"\x00\xffABC").decode()}
        self.assertEqual(self.success(peer, "process/write", message), {"status": "accepted"})
        self.assertEqual(self.success(peer, "process/write", message), {"status": "accepted"})
        self.assertEqual(self.output(self.completed(peer)), b"\x00\xffABC")
        self.start(peer, "binary", ("stdio",)); result = self.completed(peer, "binary")
        self.assertEqual(result["exitCode"], 17)
        self.assertEqual(self.output(result), b"\x00\xff\x80OUT")
        self.assertEqual(self.output(result, "stderr"), b"\xfe\x00ERR")
        self.start(peer, "int", ("interrupt",)); self.until_output(peer, b"READY", "int")
        self.success(peer, "process/signal", {"processId": "int", "signal": "interrupt"})
        self.assertEqual(self.completed(peer, "int")["exitCode"], 42)
        self.start(peer, "term", ("sleep",))
        self.assertEqual(self.success(peer, "process/terminate", {"processId": "term"}), {"running": True})
        self.assertEqual(self.completed(peer, "term")["exitCode"], 137)
        peer.close()
        for name in ("process", "binary", "int", "term"):
            notes = [item for item in peer.notifications if item["params"]["processId"] == name]
            self.assertEqual([item["params"]["seq"] for item in notes], list(range(1, len(notes) + 1)))
            self.assertEqual(notes[-1]["method"], "process/closed")

    def test_03_file_mutation_waits_for_process_and_control_remains_live(self):
        self.broker(); peer = self.peer(); peer.initialize(); self.start(peer, args=("sleep",))
        identifier = peer.request("fs/writeFile", {"path": "file:///workspace/value", "sandbox": context(), "dataBase64": "YWZ0ZXI="})
        self.success(peer, "environment/status", {})
        time.sleep(0.05)
        self.assertNotIn(identifier, peer.responses)
        self.assertEqual((self.workspace / "value").read_bytes(), b"original")
        self.success(peer, "process/terminate", {"processId": "process"})
        self.assertIn("result", peer.response(identifier))
        self.assertEqual((self.workspace / "value").read_bytes(), b"after")
        self.assertEqual(self.completed(peer)["exitCode"], 137)
        peer.close()

    def test_04_eof_reaps_descendants_releases_handles_and_workspace(self):
        self.broker(); peer = self.peer(); peer.initialize()
        self.success(peer, "fs/open", {"handleId": "held", "path": "file:///workspace/value", "sandbox": context()})
        self.start(peer, args=("fork",))
        output = self.output(self.until_output(peer, b"CHILD:"))
        child = int(output.split(b"CHILD:")[1].splitlines()[0])
        peer.close(); self.absent(child); self.lease(False)
        self.assertFalse((self.socket_dir / "process-session.json").exists())
        self.events.append({"independentDescendantReaped": child, "actualLeaseReleased": True})

    def test_05_killed_bridge_disconnect_reaps_actual_process(self):
        broker = self.broker(); peer = self.peer(); peer.initialize(); self.start(peer, args=("sleep",))
        runners = self.children(broker.pid); self.assertEqual(len(runners), 1)
        runner = runners.pop(); workers = self.children(runner); self.assertEqual(len(workers), 1); worker = workers.pop()
        from tools.executor.native_processes import _signal_pidfd
        self.assertTrue(_signal_pidfd(peer.native_pidfd, signal.SIGKILL))
        peer.process.wait(10)
        deadline = time.monotonic() + 10
        while (self.socket_dir / "process-session.json").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse((self.socket_dir / "process-session.json").exists())
        self.absent(worker); self.absent(runner); self.lease(False)
        self.events.append({"independentPidsReaped": [runner, worker], "actualLeaseReleased": True})

    def test_06_broker_sigterm_cleans_active_native_session(self):
        broker = self.broker(); peer = self.peer(); peer.initialize(); self.start(peer, args=("sleep",))
        runner, = self.children(broker.pid); worker, = self.children(runner)
        broker.terminate(); self.assertEqual(broker.wait(10), 0)
        peer.process.wait(10)
        self.absent(worker); self.absent(runner); self.lease(False)
        self.assertFalse((self.socket_dir / "exec.sock").exists())
        self.assertFalse((self.socket_dir / "process-session.json").exists())

    def test_07_runner_sigkill_quarantines_pending_files_starts_and_reconnect(self):
        broker = self.broker(); peer = self.peer(); peer.initialize(); self.start(peer, args=("sleep",))
        runner, = self.children(broker.pid); worker, = self.children(runner)
        self.assertEqual(Path(f"/proc/{runner}/exe").resolve(), OPTIONS.runner)
        write = peer.request("fs/writeFile", {"path": "file:///workspace/value", "sandbox": context(), "dataBase64": "Zm9yYmlkZGVu"})
        start = peer.request("process/start", {"processId": "waiting", "argv": ["native-fixture", "eof"],
            "cwd": "file:///workspace", "env": {}, "tty": False, "sandbox": context()})
        self.success(peer, "environment/status", {}); time.sleep(0.05)
        os.kill(runner, signal.SIGKILL)
        self.assertIn("error", peer.response(write, 5))
        self.assertIn("error", peer.response(start, 5))
        state = self.completed(peer, closed=False)
        self.assertFalse(state["closed"]); self.assertFalse(state["exited"])
        self.assertIsNone(state["exitCode"]); self.assertIn("unknown", state["failure"])
        self.assertFalse(any(item["method"] in {"process/closed", "process/exited"} for item in peer.notifications))
        self.assertIn("error", peer.call("fs/readFile", {"path": "file:///workspace/value", "sandbox": context()}))
        self.assertEqual((self.workspace / "value").read_bytes(), b"original")
        # Independent subreaper observes the real orphan; broker deliberately
        # does not treat this test-only observation as its missing native result.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pid, status = os.waitpid(worker, os.WNOHANG)
            if pid == worker:
                self.assertTrue(os.WIFSIGNALED(status)); self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
                break
            time.sleep(0.01)
        else:
            self.fail("Independent observer could not reap actual orphan")
        peer.close(); self.lease(True)
        marker = self.socket_dir / "process-session.json"
        before = marker.read_bytes(); inode = marker.stat().st_ino
        refused = self.peer(); output, _ = refused.process.communicate(b'{"id":1,"method":"initialize","params":{"clientName":"refused"}}\n', timeout=5)
        self.assertEqual(output, b""); self.assertNotEqual(refused.process.returncode, 0)
        self.assertIsNone(broker.poll())
        broker.terminate(); self.assertEqual(broker.wait(10), 0)
        self.assertFalse((self.socket_dir / "exec.sock").exists())
        retry = self.broker(ready=False); self.assertNotEqual(retry.wait(5), 0)
        self.assertEqual(marker.read_bytes(), before); self.assertEqual(marker.stat().st_ino, inode)
        self.events.append({"nativeSupervisorKilled": runner, "independentOrphanReaped": worker,
            "brokerStillQuarantined": True, "restartRefusedWithRetainedMarker": json.loads(before)})

    def test_08_broker_crash_retains_marker_and_file_only_restart_refuses(self):
        broker = self.broker(); peer = self.peer(); peer.initialize()
        marker = self.socket_dir / "process-session.json"; before = marker.read_bytes()
        broker.kill(); broker.wait(5); peer.process.wait(5)
        # Fixture owns this dead broker's exact socket; removing it isolates the
        # persistent process-ownership refusal from the older stale-socket gate.
        (self.socket_dir / "exec.sock").unlink()
        retry = self.broker(process_profile=False, ready=False)
        self.assertNotEqual(retry.wait(5), 0)
        self.assertEqual(marker.read_bytes(), before)
        self.assertFalse((self.socket_dir / "exec.sock").exists())

    def test_09_invalid_supervisor_configuration_never_creates_endpoint(self):
        for extra, profile in ((["--process-wall-ms", "0"], True),
                (["--executable", "native-fixture", str(OPTIONS.fixture)], True),
                (["--process-wall-ms", "100"], False),
                (["--executable", "rogue", str(OPTIONS.fixture)], False)):
            process = self.broker(extra, process_profile=profile, ready=False)
            self.assertNotEqual(process.wait(5), 0)
            self.assertFalse((self.socket_dir / "exec.sock").exists())
            self.assertFalse((self.socket_dir / "process-session.json").exists())
        self.lease(False)


def main():
    global OPTIONS
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runner", "fixture", "files-helper", "handle-helper", "bridge", "evidence"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--address-space-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--android-home", type=Path)
    parser.add_argument("--android-uid", type=int)
    parser.add_argument("--native-directory", type=Path)
    parser.add_argument("--guest-runtime", type=Path)
    parser.add_argument("--proot-compat", type=Path)
    parser.add_argument("--retain-cases", action="store_true")
    OPTIONS = parser.parse_args()
    for name in ("runner", "fixture", "files_helper", "handle_helper", "bridge"):
        setattr(OPTIONS, name, getattr(OPTIONS, name).resolve(strict=True))
    android_paths = ("native_directory", "guest_runtime", "proot_compat")
    if OPTIONS.android_home is not None:
        if sys.platform != "android" or OPTIONS.android_uid != os.getuid() or not all(getattr(OPTIONS, name) for name in android_paths):
            parser.error("The Android route requires its actual UID, Bionic home and fixed guest/runtime paths")
        for name in ("android_home", *android_paths):
            setattr(OPTIONS, name, getattr(OPTIONS, name).resolve(strict=True))
    elif OPTIONS.android_uid is not None or any(getattr(OPTIONS, name) is not None for name in android_paths):
        parser.error("Guest runtime inputs require the native Android route")
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CompositeTransportTests))
    report = {"scope": "nonroot C bridge/socket/composite diagnostic; no Desktop routing or model request",
        "passed": result.wasSuccessful(), "tests": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "uid": os.getuid(), "observations": OBSERVATIONS,
        "artifacts": {name: {"path": str(getattr(OPTIONS, name)),
            "sha256": hashlib.sha256(getattr(OPTIONS, name).read_bytes()).hexdigest()}
            for name in ("runner", "fixture", "files_helper", "handle_helper", "bridge")}}
    OPTIONS.evidence.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
