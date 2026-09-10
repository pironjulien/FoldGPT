"""Real nonroot Linux runner tests. Build directory and evidence are explicit.

No Android/WSL action. Requires direct-runner and direct-worker compiled from
the adjacent C files. No simulated lifecycle record or syscall result.
"""
import base64
import ctypes
import errno
import importlib
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
wire = importlib.import_module("tools.executor.bionic-supervisor.direct_wire")
BUILD = Path(sys.argv.pop(1)).resolve(strict=True)
EVIDENCE = Path(sys.argv.pop(1)).resolve(strict=True)
OBSERVATIONS = []


class Running:
    def __init__(self, command, cwd, *, acknowledge=True, **limits):
        self.control, control_child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.command, command_child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.input_read, self.input_write = os.pipe2(os.O_CLOEXEC)
        environment = ["PATH=/usr/bin:/bin", "LANG=C.UTF-8", "HOME=" + str(cwd)]
        allowances = {"wall_ms": 10000, "uid_tasks": 128, **limits}
        config = wire.seal(wire.envelope(cwd=str(cwd), executable=command[0], argv=command,
            environment=environment, **allowances))
        inherited = (config, self.input_read, control_child.fileno(), command_child.fileno())
        self.process = subprocess.Popen([str(BUILD / "direct-runner"), *map(str, inherited)],
            pass_fds=inherited, close_fds=True, env={}, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.close(config);os.close(self.input_read)
        control_child.close();command_child.close()
        self.input_read = -1
        self.events = []
        self.out = bytearray();self.err = bytearray()
        self.result = None
        self.selector = selectors.DefaultSelector()
        for stream, label in ((self.control, "control"), (self.process.stdout, "stdout"), (self.process.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            self.selector.register(stream, selectors.EVENT_READ, label)
        self.until(lambda: any(event["type"] == "ready" for event in self.events), 3)
        if acknowledge:
            self.control.send(b"P")

    def close_input(self):
        if self.input_write >= 0:
            os.close(self.input_write);self.input_write = -1

    def step(self, timeout=0.05):
        for key, _ in self.selector.select(timeout):
            try:
                data = key.fileobj.recv(8192) if key.data == "control" else os.read(key.fileobj.fileno(), 65536)
            except BlockingIOError:
                continue
            if not data:
                self.selector.unregister(key.fileobj)
                continue
            if key.data == "control":
                event = json.loads(data)
                self.events.append(event)
                if event["type"] == "result":
                    if self.result is not None:
                        raise AssertionError("Duplicate result")
                    self.result = event
            else:
                (self.out if key.data == "stdout" else self.err).extend(data)

    def until(self, predicate, seconds=12):
        deadline = time.monotonic() + seconds
        while not predicate():
            if time.monotonic() >= deadline:
                raise AssertionError({"timeout": seconds, "events": self.events,
                    "stdout": bytes(self.out[-2048:]).decode(errors="replace"),
                    "stderr": bytes(self.err[-2048:]).decode(errors="replace")})
            self.step()

    def finish(self):
        self.until(lambda: self.result is not None and self.process.poll() is not None
            and not self.selector.get_map())
        actual = self.process.wait(timeout=1)
        assert self.result["cleanupComplete"] is True, self.result
        assert actual == (0 if self.result["started"] else 70), (actual, self.result)
        assert len(self.out) == self.result["stdoutBytes"], self.result
        assert len(self.err) == self.result["stderrBytes"], self.result
        if self.result["outcome"] == "exited":
            assert self.result["stdoutReadBytes"] == len(self.out), self.result
            assert self.result["stderrReadBytes"] == len(self.err), self.result
        OBSERVATIONS.append({"ownerPid": self.process.pid, "ownerReturncode": actual,
            "events": self.events, "stdoutBase64": base64.b64encode(self.out).decode(),
            "stderrBase64": base64.b64encode(self.err).decode()})
        return self.result

    def close(self):
        self.close_input()
        if self.process.poll() is None:
            try:
                self.command.send(b"T")
            except OSError:
                pass
            try:
                self.finish()
            except BaseException:
                # Do not kill an owner that may still own descendants just to
                # manufacture a passing cleanup. The failed CI retains evidence.
                OBSERVATIONS.append({"incompleteOwnerPid": self.process.pid, "events": self.events})
                raise
        self.selector.close()
        self.control.close();self.command.close()
        self.process.stdout.close();self.process.stderr.close()


class DirectRunnerTests(unittest.TestCase):
    def setUp(self):
        if sys.platform != "linux" or os.getuid() == 0:
            self.fail("Real nonroot Linux required")
        self.temp = tempfile.TemporaryDirectory(prefix="direct-", dir=EVIDENCE)
        self.cwd = Path(self.temp.name)
        self.running = []

    def tearDown(self):
        for current in self.running:
            current.close()
        self.temp.cleanup()

    def run_command(self, args, **kwargs):
        current = Running(args, self.cwd, **kwargs)
        self.running.append(current)
        current.close_input()
        return current

    def pidfds(self, current, count):
        def rows():
            return [json.loads(line) for line in bytes(current.out).splitlines() if line.startswith(b'{"worker"')]
        current.until(lambda: len(rows()) >= count)
        records = rows()
        handles = [os.pidfd_open(row["pid"]) for row in records]
        self.addCleanup(lambda: [os.close(fd) for fd in handles])
        return records, handles

    def assert_gone(self, handles):
        for fd in handles:
            with self.assertRaises(ProcessLookupError):
                signal.pidfd_send_signal(fd, 0)

    def test_direct_filesystem_network_and_real_python_build(self):
        code = r'''
import json, os, pathlib, platform, shutil, socket, sys, unittest, zipapp
p=pathlib.Path.cwd()
(p/'addition.py').write_text('def addition(a,b): return a+b\n')
(p/'test_addition.py').write_text('import unittest\nfrom addition import addition\nclass T(unittest.TestCase):\n def test_a(self): self.assertEqual(addition(20,22),42)\n def test_b(self): self.assertEqual(addition(-2,2),0)\n def test_c(self): self.assertEqual(addition(1,2),3)\n')
suite=unittest.defaultTestLoader.discover(str(p))
result=unittest.TextTestRunner().run(suite)
assert result.wasSuccessful() and result.testsRun==3
(p/'app').mkdir(); shutil.copy(p/'addition.py',p/'app/addition.py')
(p/'app/__main__.py').write_text('from addition import addition\nprint(addition(20,22))\n')
zipapp.create_archive(p/'app',p/'addition.pyz',interpreter='/usr/bin/env python3')
(p/'a').write_text('native'); os.rename(p/'a',p/'b'); os.symlink('b',p/'link')
assert (p/'link').read_text()=='native'; os.chmod(p/'b',0o600)
os.unlink(p/'link'); os.unlink(p/'b')
with socket.socket() as server:
 server.bind(('127.0.0.1',0));server.listen(1)
 with socket.create_connection(server.getsockname()) as client:
  peer,_=server.accept()
  with peer:
   client.sendall(b'native');assert peer.recv(6)==b'native'
print(json.dumps({'platform':sys.platform,'machine':platform.machine(),'uid':os.getuid(),'tests':result.testsRun}))
'''
        current = self.run_command([sys.executable, "-c", code])
        result = current.finish()
        self.assertEqual(result["exitCode"], 0, bytes(current.err))
        data = json.loads(current.out)
        self.assertEqual(data["uid"], os.getuid())
        self.assertEqual(data["tests"], 3)
        follow = self.run_command([sys.executable, str(self.cwd / "addition.pyz")])
        self.assertEqual(follow.finish()["exitCode"], 0)
        self.assertEqual(bytes(follow.out), b"42\n")

    def test_actual_exec_failure_has_no_started_event(self):
        current = self.run_command([str(self.cwd / "missing-program")])
        result = current.finish()
        self.assertFalse(result["started"])
        self.assertEqual(result["outcome"], "setup_error")
        self.assertEqual(result["errno"], errno.ENOENT)
        self.assertNotIn("started", [event["type"] for event in current.events])

    def test_cancel_before_ack_creates_no_command(self):
        current = self.run_command([sys.executable, "-c", "raise SystemExit(0)"], acknowledge=False)
        current.command.send(b"T")
        result = current.finish()
        self.assertFalse(result["started"])
        self.assertEqual(result["reaped"], 0)

    def test_setsids_groups_nested_subreapers_are_reaped(self):
        current = self.run_command([str(BUILD / "direct-worker"), "tree"])
        records, handles = self.pidfds(current, 4)
        self.assertGreater(len({row["sid"] for row in records}), 1)
        self.assertGreater(len({row["pgrp"] for row in records}), 1)
        current.command.send(b"T")
        result = current.finish()
        self.assertEqual(result["outcome"], "cancelled")
        self.assertEqual(result["reaped"], 4)
        self.assert_gone(handles)

    def test_double_fork_is_cleaned_after_real_initial_exit(self):
        current = self.run_command([str(BUILD / "direct-worker"), "orphan"])
        result = current.finish()
        self.assertEqual(result["exitCode"], 23)
        self.assertEqual(result["outcome"], "exited")
        self.assertEqual(result["reaped"], 3)
        self.assertIn(b'double-orphan', current.out)

    def test_clone_parent_non_sigchld_and_thread_fork(self):
        current = self.run_command([str(BUILD / "direct-worker"), "clone"])
        records, handles = self.pidfds(current, 4)
        self.assertEqual({row["worker"] for row in records},
            {"clone-parent", "clone-zero-signal", "thread-fork-child", "clone-leader"})
        current.command.close()
        result = current.finish()
        self.assertEqual(result["outcome"], "cancelled")
        self.assertEqual(result["reaped"], 4)
        self.assert_gone(handles)

    def test_bounded_fork_churn_does_not_use_scan_as_completion(self):
        current = self.run_command([str(BUILD / "direct-worker"), "churn"])
        current.until(lambda: b'churn-grandchild' in current.out)
        current.command.send(b"T")
        result = current.finish()
        self.assertEqual(result["outcome"], "cancelled")
        self.assertGreater(result["reaped"], 1)

    def test_pidfd_cancellation_does_not_signal_an_unrelated_process(self):
        unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(20)"])
        try:
            current = self.run_command([str(BUILD / "direct-worker"), "tree"])
            self.pidfds(current, 4)
            current.command.send(b"T");current.finish()
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate();unrelated.wait(timeout=3)

    def test_large_output_backpressure_preserves_exact_bytes(self):
        current = self.run_command([sys.executable, "-c", "import os;os.write(1,bytes(range(256))*40961)"])
        current.finish()
        self.assertEqual(bytes(current.out), bytes(range(256)) * 40961)

    def test_real_binary_stdin_and_eof(self):
        current = Running([sys.executable, "-c", "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())"], self.cwd)
        self.running.append(current)
        data = bytes(range(256)) * 8
        self.assertEqual(os.write(current.input_write, data), len(data))
        current.close_input()
        self.assertEqual(current.finish()["exitCode"], 0)
        self.assertEqual(bytes(current.out), data)

    def test_timeout_reaps_real_descendants(self):
        current = self.run_command([str(BUILD / "direct-worker"), "tree"], wall_ms=750)
        _, handles = self.pidfds(current, 4)
        self.assertEqual(current.finish()["outcome"], "timeout")
        self.assert_gone(handles)

    def test_control_disconnect_cleans_without_fabricating_certificate(self):
        current = self.run_command([str(BUILD / "direct-worker"), "tree"])
        _, handles = self.pidfds(current, 4)
        current.selector.unregister(current.control)
        current.control.close()
        current.until(lambda: current.process.poll() is not None and not current.selector.get_map())
        self.assertEqual(current.process.wait(timeout=1), 0)
        self.assertIsNone(current.result)
        self.assert_gone(handles)
        OBSERVATIONS.append({"controlDisconnected": True, "ownerPid": current.process.pid,
            "ownerReturncode": current.process.returncode, "cleanupCertificateReceived": False,
            "descendantsVerifiedGoneByTestPidfds": True})

    def test_ordinary_uid_can_kill_owner_and_no_cleanup_is_fabricated(self):
        # This is an explicit limitation test. The test process becomes the
        # fallback subreaper and cleans only its own verified adopted children.
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        current = None
        handles = []
        try:
            current = Running([str(BUILD / "direct-worker"), "owner-loss"], self.cwd)
            self.running.append(current)
            _, handles = self.pidfds(current, 2)
            os.write(current.input_write, b"K")
            current.close_input()
            current.until(lambda: current.process.poll() is not None)
            self.assertEqual(current.process.wait(timeout=1), -signal.SIGKILL)
            self.assertIsNone(current.result)
            adopted = 0
            for fd in handles:
                # Verify the current kernel parent relationship before cleanup.
                try:
                    os.waitid(os.P_PIDFD, fd, os.WEXITED | os.WNOHANG | os.WNOWAIT | 0x40000000)
                    signal.pidfd_send_signal(fd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except ChildProcessError:
                    continue
                adopted += 1
                os.waitid(os.P_PIDFD, fd, os.WEXITED | 0x40000000)
            self.assertGreaterEqual(adopted, 1)
            current.until(lambda: not current.selector.get_map())
            self.assertIsNone(current.result)
            OBSERVATIONS.append({"ownerKilledByOrdinaryUidChild": True,
                "ownerReturncode": current.process.returncode, "cleanupCertificateReceived": False,
                "fallbackTestSubreaperReaped": adopted})
        finally:
            # The worker's command is bounded to its actual parent owner. Only
            # test-issued pidfds belonging to this harness may be signaled here.
            for fd in handles:
                try:
                    os.waitid(os.P_PIDFD, fd, os.WEXITED | os.WNOHANG | os.WNOWAIT | 0x40000000)
                    signal.pidfd_send_signal(fd, signal.SIGKILL)
                    os.waitid(os.P_PIDFD, fd, os.WEXITED | 0x40000000)
                except (ProcessLookupError, ChildProcessError):
                    pass
            self.assertEqual(libc.prctl(36, previous.value, 0, 0, 0), 0)

    def test_explicit_output_limit_reports_actual_drain_and_delivery(self):
        current = self.run_command([sys.executable, "-c", "import os;os.write(1,b'x'*1048576)"], output_bytes=8192)
        result = current.finish()
        self.assertEqual(result["outcome"], "output_limit")
        self.assertGreater(result["stdoutReadBytes"], 8192)
        self.assertGreaterEqual(result["stdoutReadBytes"], result["stdoutBytes"])
        self.assertLessEqual(result["stdoutBytes"], 8192)


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        (EVIDENCE / "direct-runner-results.json").write_text(json.dumps({
            "schema": "foldgpt.direct.native.tests.v1", "uid": os.getuid(),
            "platform": sys.platform, "observations": OBSERVATIONS}, indent=2) + "\n")
