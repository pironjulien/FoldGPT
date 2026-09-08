"""Real PC human supervisor qualification. No Android or fake process results.

Pass a build directory containing host-runner, native-files, native-file-handle
and the unchanged managed runner. Run as a nonroot user; evidence stays in the
explicit existing private test directory. This file has no WSL/ADB launcher.
"""
import asyncio
import importlib
import json
import os
from pathlib import Path
import selectors
import shlex
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
factory = importlib.import_module("tools.executor.bionic-supervisor.factory").factory
wire = importlib.import_module("tools.executor.bionic-supervisor.host_wire")
HostProcessPolicy = importlib.import_module("tools.executor.bionic-supervisor.host_policy").HostProcessPolicy
context = importlib.import_module("tools.executor.bionic-supervisor.test_kernel").context
from tools.executor.exec_server import BackendCall, RpcError, encode_message
from tools.executor.native_host_files import create_host_file_authority

BUILD = Path(sys.argv.pop(1)).resolve(strict=True)
EVIDENCE = Path(sys.argv.pop(1)).resolve(strict=True)


class HostKernelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertNotEqual(os.getuid(), 0)
        self.base = Path(tempfile.mkdtemp(prefix="case-", dir=EVIDENCE))
        self.workspace = self.base / "workspace"
        self.workspace.mkdir(mode=0o700)
        (self.workspace / "private").mkdir(mode=0o700)
        (self.workspace / "private/secret").write_bytes(b"actual host private file\0")
        self.runtime = [("/usr", True), ("/lib", True), ("/lib64", True), ("/etc/ld.so.cache", False)]
        self.owner = factory({"helper": str(BUILD / "native-files"),
            "handleHelper": str(BUILD / "native-file-handle"), "processRunner": str(BUILD / "runner"),
            "workspace": str(self.workspace), "executables": {"bash": "/usr/bin/bash"},
            "runtime": [{"path": path, "execute": execute} for path, execute in self.runtime]})
        self.authority = create_host_file_authority(self.owner, session_id="host-real-test")
        self.results = []

    async def asyncTearDown(self):
        (self.base / "results.json").write_text(json.dumps(self.results, indent=2) + "\n")
        if self.owner.processes.quarantined:
            with self.assertRaises(RpcError):
                await self.owner.close("host-real-test")
        else:
            await self.owner.close("host-real-test")

    def run_native(self, command, *, cwd="/", input_data=b"", cancel_marker=None):
        policy = HostProcessPolicy(self.authority, cwd)
        control, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        commands, command_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
        environment = ["PATH=/usr/bin:/bin", "HOME=" + str(self.workspace)]
        encoded = wire.envelope(workspace=str(self.workspace), cwd=cwd, executable="/usr/bin/bash",
            argv=["bash", "--noprofile", "--norc", "-c", command], environment=environment,
            runtime=self.runtime, timeout_ms=None, output_bytes=None, cpu_seconds=None,
            data_bytes=268435456, file_bytes=16777216, uid_tasks=8, descriptors=128)
        envelope = wire.seal(encoded)
        inherited = (self.owner.files.root, read_fd, peer.fileno(), command_peer.fileno(), envelope)
        child = subprocess.Popen([str(BUILD / "host-runner"), *map(str, inherited)],
            env={}, pass_fds=inherited, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        peer.close(); command_peer.close(); os.close(read_fd); os.close(envelope)
        os.set_blocking(write_fd, False)
        selectors_owned = selectors.DefaultSelector()
        selectors_owned.register(control, selectors.EVENT_READ, "control")
        selectors_owned.register(child.stdout, selectors.EVENT_READ, "stdout")
        selectors_owned.register(child.stderr, selectors.EVENT_READ, "stderr")
        if input_data:
            selectors_owned.register(write_fd, selectors.EVENT_WRITE, "stdin")
        else:
            os.close(write_fd); write_fd = -1
        output = {"stdout": bytearray(), "stderr": bytearray()}
        events, decisions, sent = [], [], 0
        end, cancel_sent, cleanup_proven = time.monotonic() + 30, False, False
        try:
            while selectors_owned.get_map():
                if time.monotonic() >= end:
                    commands.send(b"T")
                    raise TimeoutError("Actual host process test deadline exceeded")
                for key, _ in selectors_owned.select(0.025):
                    if key.data == "stdin":
                        try:
                            sent += os.write(write_fd, input_data[sent:sent + 32768])
                        except BlockingIOError:
                            continue
                        if sent == len(input_data):
                            selectors_owned.unregister(write_fd)
                            os.close(write_fd); write_fd = -1
                    elif key.data == "control":
                        packet = control.recv(16384)
                        if not packet:
                            selectors_owned.unregister(control)
                            continue
                        event = json.loads(packet)
                        if event["type"] == "acquire":
                            decision = policy.decide(event)
                            decisions.append({"request": event, "decision": decision})
                            relative = decision["relative"].encode("utf-8")
                            control.send(struct.pack("<QiI4Q", decision["id"], decision["error"], len(relative),
                                decision["device"], decision["inode"], decision["parentDevice"], decision["parentInode"]) + relative)
                        else:
                            events.append(event)
                            if event["type"] == "ready":
                                self.assertEqual(event, {"type": "ready", "profile": "bionic-host-v1"})
                                control.send(b"P")
                    else:
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selectors_owned.unregister(key.fileobj)
                        else:
                            output[key.data].extend(data)
                            if cancel_marker and not cancel_sent and cancel_marker in output["stdout"]:
                                commands.send(b"T"); cancel_sent = True
            returncode = child.wait(timeout=6)
            final = [event for event in events if event["type"] == "result"]
            self.assertEqual(len(final), 1, events)
            self.assertTrue(final[0]["cleanupComplete"], final)
            cleanup_proven = True
            self.assertTrue(final[0]["started"], final)
            self.assertEqual(final[0]["stdoutBytes"], len(output["stdout"]))
            self.assertEqual(final[0]["stderrBytes"], len(output["stderr"]))
            self.assertEqual(returncode, 0, final)
            self.results.append({"events": events, "decisions": decisions, "returncode": returncode,
                                 "stdoutBytes": len(output["stdout"]), "stderrBytes": len(output["stderr"]),
                                 "cancelSent": cancel_sent, "actualCwdRequested": cwd})
            return bytes(output["stdout"]), bytes(output["stderr"]), final[0]
        finally:
            # Cancellation always asks the still-owned native supervisor. A
            # timeout does not pretend cleanup completed or release its lease.
            if child.poll() is None:
                commands.send(b"T")
                try:
                    child.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    self.owner.processes.quarantined = True
                    self.owner.processes.quarantine_event.set()
            if not cleanup_proven:
                self.owner.processes.quarantined = True
                self.owner.processes.quarantine_event.set()
            if write_fd >= 0:
                os.close(write_fd)
            selectors_owned.close(); control.close(); commands.close()
            child.stdout.close(); child.stderr.close()
            policy.close()

    async def run_owned(self, command, **options):
        await self.owner.files.lock.acquire()
        try:
            return await asyncio.to_thread(self.run_native, command, **options)
        finally:
            if not self.owner.processes.quarantined:
                self.owner.files.lock.release()

    async def test_real_root_cwd_and_human_private_read_preserve_model_refusal(self):
        path = self.workspace / "private/secret"
        stdout, stderr, final = await self.run_owned("pwd; cat " + shlex.quote(str(path)))
        self.assertEqual(stdout, b"/\nactual host private file\0")
        self.assertEqual(stderr, b"")
        self.assertEqual(final["exitCode"], 0)
        async def notify(*_):
            raise AssertionError("A file refusal cannot emit a process event")
        with self.assertRaises(RpcError):
            await self.owner.handle(BackendCall("host-real-test", 1, "fs/readFile", encode_message({
                "path": path.as_uri(), "sandbox": context(self.workspace)})), notify)
        self.assertEqual(path.read_bytes(), b"actual host private file\0")

    async def test_real_shell_streams_large_binary_stdin_then_eof(self):
        payload = bytes(range(256)) * 8193
        path = self.workspace / "written.bin"
        stdout, stderr, final = await self.run_owned("cat > " + shlex.quote(str(path)), input_data=payload)
        self.assertEqual((stdout, stderr, final["exitCode"]), (b"", b"", 0))
        self.assertEqual(path.read_bytes(), payload)

    async def test_no_hidden_eight_megabyte_output_cap(self):
        path = self.workspace / "large.bin"
        payload = bytes(range(256)) * 40961
        path.write_bytes(payload)
        stdout, stderr, final = await self.run_owned("cat " + shlex.quote(str(path)))
        self.assertEqual(stdout, payload)
        self.assertEqual((stderr, final["exitCode"]), (b"", 0))

    async def test_root_cwd_does_not_grant_outside_file_access(self):
        outside = self.base / "outside"
        outside.write_bytes(b"outside sentinel")
        stdout, stderr, final = await self.run_owned("cat " + shlex.quote(str(outside)))
        self.assertEqual(stdout, b"")
        self.assertNotEqual(final["exitCode"], 0)
        self.assertTrue(stderr)
        self.assertEqual(outside.read_bytes(), b"outside sentinel")

    async def test_real_cancellation_reaps_background_descendant(self):
        stdout, _, final = await self.run_owned("sleep 20 & printf ready; wait", cancel_marker=b"ready")
        self.assertEqual(stdout, b"ready")
        self.assertEqual(final["outcome"], "cancelled")
        self.assertTrue(final["cleanupComplete"])


if __name__ == "__main__":
    unittest.main()
