"""Real Unix descriptor handoff and native owner cleanup; no mocked backend."""
import array
import asyncio
import base64
import fcntl
import importlib
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.executor.native_executor_backend import NativeExecutorBackend
from tools.executor.native_runtime_acquisition import NativeRuntimeAcquisition, SCHEMA, SessionExecServer
from tools.executor import native_runtime_acquisition
from tools.executor.native_path_uri import path_uri


class RuntimeAcquisitionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertNotEqual(os.getuid(), 0)
        inputs = [os.environ.get(name) for name in ("FOLDGPT_NATIVE_FILES", "FOLDGPT_NATIVE_HANDLES", "FOLDGPT_NATIVE_RUNNER")]
        self.assertTrue(all(inputs), "Actual native helpers required")
        self.temp = tempfile.TemporaryDirectory(prefix="foldgpt-acquire-", dir="/var/tmp")
        self.parent = Path(self.temp.name)
        self.workspace = self.parent / "workspace=+[] café"
        self.workspace.mkdir(mode=0o700)
        self.endpoint_dir = self.parent / "endpoint"
        self.endpoint_dir.mkdir(mode=0o700)
        (self.workspace / "existing").write_bytes(b"native\x00bytes")
        bionic = importlib.import_module("tools.executor.bionic-supervisor.processes")
        def processes(runner, workspace, **options):
            return bionic.Processes(runner, workspace, executables={"bash": "/usr/bin/bash"},
                runtime=(("/usr", True), ("/lib", True), ("/lib64", True), ("/etc/ld.so.cache", False)), **options)
        self.backend = NativeExecutorBackend(inputs[0], self.workspace, handle_helper=inputs[1],
            process_runner=inputs[2], process_factory=processes, guest_workspace=str(self.workspace), parent_environment={})
        info = {"os": "linux", "arch": "x86_64", "cwd": path_uri(self.workspace),
                "userHomeDir": path_uri(self.workspace), "shell": {"name": "bash", "path": "/usr/bin/bash"}}
        self.server = SessionExecServer(self.backend, environment_info=info)
        self.path = self.endpoint_dir / "runtime.sock"
        self.owner = NativeRuntimeAcquisition(self.path, self.server, controller_uid=os.getuid())
        self.running = None

    async def asyncTearDown(self):
        if self.running is not None and not self.running.done():
            self.running.cancel()
        if self.running is not None:
            await asyncio.gather(self.running, return_exceptions=True)
        await self.server.close()
        self.owner.close_endpoint()
        self.assertFalse(self.backend.processes.quarantined)
        self.assertTrue(self.backend.files.closed)
        self.assertIsNone(self.backend.files.process)
        self.temp.cleanup()

    def connect(self):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        client.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        client.settimeout(15)
        client.connect(str(self.path))
        return client

    def receive(self, client, expected_rights):
        data, ancillary, flags, _ = client.recvmsg(65536, socket.CMSG_SPACE(12) + socket.CMSG_SPACE(12), socket.MSG_CMSG_CLOEXEC)
        # Linux echoes the requested atomic CLOEXEC flag in recvmsg's result.
        # Reject every other bit, including either form of truncation.
        self.assertEqual(flags & ~socket.MSG_CMSG_CLOEXEC, 0)
        credentials, descriptors = [], []
        for level, kind, value in ancillary:
            self.assertEqual(level, socket.SOL_SOCKET)
            if kind == socket.SCM_CREDENTIALS:
                credentials.append(struct.unpack("iII", value))
            else:
                self.assertEqual(kind, socket.SCM_RIGHTS)
                rights = array.array("i")
                rights.frombytes(value)
                descriptors.extend(rights)
        self.assertEqual(credentials, [(os.getpid(), os.getuid(), os.getgid())])
        self.assertEqual(len(descriptors), expected_rights)
        for descriptor in descriptors:
            self.assertFalse(os.get_inheritable(descriptor))
        return json.loads(data), descriptors

    def exercise(self):
        client = self.connect()
        descriptors, rpc = [], None
        try:
            client.send(json.dumps({"type": "acquire", "schema": SCHEMA}).encode())
            offered, rights = self.receive(client, 3)
            self.assertEqual(offered, {"type": "channels", "schema": SCHEMA,
                "workspaceRoot": path_uri(self.workspace), "fdRoles": ["exec", "config", "host"]})
            descriptors = [socket.socket(fileno=fd) for fd in rights]
            for descriptor in descriptors:
                descriptor.settimeout(15)
            rpc = descriptors[0].makefile("rwb", buffering=0)
            rpc.write(b'{"id":1,"method":"initialize","params":{"clientName":"actual-acquisition-test"}}\n')
            initialized = json.loads(rpc.readline())
            session = initialized["result"]["sessionId"]
            rpc.write(b'{"method":"initialized"}\n')
            ready, _ = self.receive(client, 0)
            self.assertEqual(ready, {"type": "ready", "schema": SCHEMA,
                "workspaceRoot": path_uri(self.workspace), "sessionId": session})
            config, host = descriptors[1:]
            config_ready, _ = self.receive(config, 0)
            host_ready, _ = self.receive(host, 0)
            self.assertEqual(config_ready["sessionId"], session)
            self.assertEqual(host_ready["sessionId"], session)
            self.assertEqual(config_ready["discoveryRoot"], path_uri(self.workspace))
            self.assertEqual(host_ready["workspaceRoot"], path_uri(self.workspace))
            self.assertNotEqual(self.workspace.as_uri(), path_uri(self.workspace))
            uri = path_uri(self.workspace / "existing")
            config.send(json.dumps({"id": 1, "op": "readFile", "path": uri}).encode())
            chunk, _ = self.receive(config, 0)
            result, _ = self.receive(config, 0)
            self.assertEqual(base64.b64decode(chunk["dataBase64"]), b"native\x00bytes")
            self.assertEqual(result, {"type": "result", "id": 1, "result": {"bytes": 12, "chunks": 1}})
            host.send(json.dumps({"id": 1, "op": "writeFile", "path": uri, "bytes": 3, "chunks": 1}).encode())
            host.send(b'{"type":"chunk","id":1,"index":0,"dataBase64":"bmV3"}')
            host.send(b'{"type":"commit","id":1}')
            written, _ = self.receive(host, 0)
            self.assertEqual(written, {"type": "result", "id": 1, "result": {}})
            self.assertEqual((self.workspace / "existing").read_bytes(), b"new")
            rpc.write(json.dumps({"id": 2, "method": "fs/readFile", "params": {"path": uri, "sandbox": None}}).encode() + b"\n")
            self.assertIn("error", json.loads(rpc.readline()))
        finally:
            client.close()
            if rpc is not None:
                rpc.close()
            for descriptor in descriptors:
                descriptor.close()

    async def test_idle_owner_survives_desktop_startup_and_cancels_cleanly(self):
        with patch.object(native_runtime_acquisition, "STARTUP_SECONDS", 0.1):
            self.running = asyncio.create_task(self.owner.run())
            await asyncio.sleep(0.2)
            self.assertFalse(self.running.done(), "No protocol deadline may expire before the controller connects")
            self.assertTrue(self.path.is_socket())
            self.running.cancel()
            await asyncio.gather(self.running, return_exceptions=True)
        self.assertFalse(self.path.exists())
        self.assertTrue(self.backend.files.closed)

    async def test_idle_ordinary_profile_stop_closes_backend_and_releases_kernel_lease(self):
        # Production r21 installs the ordinary profile before any controller
        # can initialize. Exercise that composition over the actual native
        # owner, listener and kernel flock; no synthetic session or backend.
        direct_runner = os.environ.get("FOLDGPT_DIRECT_RUNNER")
        self.assertTrue(direct_runner, "Actual direct runner required")
        direct_module = importlib.import_module("tools.executor.bionic-supervisor.direct_processes")
        from tools.executor.ordinary_uid_files import OrdinaryUidFilesBackend
        direct = direct_module.DirectProcesses(direct_runner, self.workspace,
            executables=self.backend.processes.executables, files_backend=self.backend.files,
            parent_environment={}, quarantine_owner=self.backend.processes)
        direct_files = OrdinaryUidFilesBackend(lock=self.backend.files.lock)
        self.backend.install_ordinary_uid_profile(direct, direct_files)
        contender = os.open(self.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.running = asyncio.create_task(self.owner.run())
            await asyncio.sleep(0)
            self.assertFalse(self.running.done())
            self.assertIsNone(self.server.session_id)
            self.assertTrue(self.path.is_socket())
            self.running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(self.running, 5)
            # The installed bootstrap closes again after acquisition returns.
            # Its second close must observe the same successful owned result.
            await asyncio.wait_for(self.backend.close(None), 5)
            self.assertTrue(self.backend.files.closed)
            self.assertTrue(direct_files.closed)
            self.assertIsNone(direct_files.session)
            self.assertFalse(self.backend.processes.quarantined)
            self.assertFalse(direct.quarantined)
            self.assertFalse(direct.processes)
            self.assertFalse(self.backend.files.lock.locked())
            self.assertFalse(self.path.exists())
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(contender)

    async def test_connected_controller_must_send_its_handshake_on_time(self):
        with patch.object(native_runtime_acquisition, "STARTUP_SECONDS", 0.1):
            self.running = asyncio.create_task(self.owner.run())
            client = self.connect()
            try:
                with self.assertRaises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(self.running), 5)
            finally:
                client.close()
        self.assertTrue(self.running.done())
        self.assertFalse(self.path.exists())
        self.assertTrue(self.backend.files.closed)

    async def test_direct_channels_real_session_file_work_and_eof_cleanup(self):
        self.running = asyncio.create_task(self.owner.run())
        await asyncio.to_thread(self.exercise)
        result, = await asyncio.wait_for(asyncio.gather(self.running, return_exceptions=True), 15)
        self.assertTrue(result is None or isinstance(result, (EOFError, ConnectionError)))
        self.assertFalse(self.path.exists())

    async def test_unknown_fields_never_acquire_channels(self):
        self.running = asyncio.create_task(self.owner.run())
        client = self.connect()
        try:
            client.send(json.dumps({"type": "acquire", "schema": SCHEMA, "workspaceRoot": "/"}).encode())
            with self.assertRaises(ValueError):
                await asyncio.wait_for(self.running, 15)
            self.assertEqual(await asyncio.to_thread(client.recv, 4096), b"")
            self.assertIsNone(self.server.session_id)
        finally:
            client.close()

    async def test_duplicate_fields_never_acquire_channels(self):
        self.running = asyncio.create_task(self.owner.run())
        client = self.connect()
        try:
            client.send(b'{"type":"acquire","type":"acquire","schema":"foldgpt.native-runtime.v1"}')
            with self.assertRaises(ValueError):
                await asyncio.wait_for(self.running, 15)
            self.assertIsNone(self.server.session_id)
        finally:
            client.close()

    async def test_unexpected_descriptor_is_closed(self):
        self.running = asyncio.create_task(self.owner.run())
        read_end, write_end = os.pipe()
        client = self.connect()
        try:
            client.sendmsg([json.dumps({"type": "acquire", "schema": SCHEMA}).encode()],
                [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [read_end]))])
            os.close(read_end)
            read_end = None
            with self.assertRaises(ValueError):
                await asyncio.wait_for(self.running, 15)
            with self.assertRaises(BrokenPipeError):
                os.write(write_end, b"x")
        finally:
            if read_end is not None:
                os.close(read_end)
            os.close(write_end)
            client.close()

    async def test_existing_endpoint_is_preserved(self):
        before = self.path.stat()
        other = SessionExecServer(self.backend,
            environment_info={name: value for name, value in self.server.info.items() if name != "capabilities"})
        # The endpoint collision must fail without removing the first owner.
        with self.assertRaises(OSError):
            NativeRuntimeAcquisition(self.path, other, controller_uid=os.getuid())
        self.assertEqual(self.path.stat().st_ino, before.st_ino)

    async def test_endpoint_inside_workspace_is_refused(self):
        with self.assertRaises(ValueError):
            NativeRuntimeAcquisition(self.workspace / "rpc.sock", self.server, controller_uid=os.getuid())
        self.assertFalse((self.workspace / "rpc.sock").exists())

    async def test_endpoint_directory_must_be_private(self):
        self.endpoint_dir.chmod(0o755)
        try:
            with self.assertRaises(ValueError):
                NativeRuntimeAcquisition(self.endpoint_dir / "other.sock", self.server, controller_uid=os.getuid())
        finally:
            self.endpoint_dir.chmod(0o700)


if __name__ == "__main__":
    unittest.main(verbosity=2)
