"""Real nonroot native descriptors, SCM_RIGHTS, bounded pread and RPC lifetime tests."""
import asyncio
import base64
from dataclasses import FrozenInstanceError
import errno
import fcntl
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.executor.exec_server import BackendCall, ExecServer, RpcError, encode_message
from tools.executor.native_files import NativeFilesBackend
from tools.executor.native_file_streams import NativeFileStreamsBackend, MAX_BLOCK, _helper_error
from tools.executor.test_policy_intent import context

FILE_HELPER = os.environ.get("FOLDGPT_NATIVE_FILES")
HANDLE_HELPER = os.environ.get("FOLDGPT_NATIVE_FILE_HANDLE")


@unittest.skipUnless(FILE_HELPER and HANDLE_HELPER and os.name == "posix",
                     "Requires compiled native helpers and nonroot Linux")
class NativeFileStreamsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if os.getuid() == 0:
            self.fail("Run actual ownership and permission checks as a nonroot user")
        self.temporary = tempfile.TemporaryDirectory(prefix="foldgpt-streams-")
        self.work = Path(self.temporary.name)
        self.root = self.work / "workspace"
        self.root.mkdir(mode=0o700)
        self.original = bytes(range(256)) * 37 + b"native actual bytes\x00\xff"
        (self.root / "value").write_bytes(self.original)
        (self.root / "private").mkdir()
        (self.root / "private/secret").write_bytes(b"denied")
        self.backend = NativeFileStreamsBackend(FILE_HELPER, self.root, handle_helper=HANDLE_HELPER)
        self.server = ExecServer(self.backend)
        self.sequence = 0
        self.initialized = await self.server.request({"id": 0, "method": "initialize", "params": {"clientName": "native-stream-tests"}})
        await self.server.accept({"method": "initialized"}, self.emit)

    async def emit(self, _):
        pass

    async def asyncTearDown(self):
        await self.server.close()
        self.temporary.cleanup()

    async def rpc(self, method, **params):
        self.sequence += 1
        return await self.server.request({"id": self.sequence, "method": method, "params": params})

    async def opening(self, identifier="h", path="value", policy=None):
        return await self.rpc("fs/open", handleId=identifier, path="file:///workspace/" + path,
                              sandbox=context() if policy is None else policy)

    async def read(self, identifier="h", offset=0, length=MAX_BLOCK):
        return await self.rpc("fs/readBlock", handleId=identifier, offset=offset, len=length)

    @staticmethod
    def fd_count():
        return len(os.listdir("/proc/self/fd"))

    def peer(self, mode):
        """Actual independently executed peers exercise kernel descriptor transfer."""
        script = self.work / "peer.py"
        script.write_text('''#!/usr/bin/python3
import array, json, os, socket, struct, sys, time
mode = MODE
if mode == "spawn-marker":
    open(MARKER, "w").write(str(os.getpid()))
    os.execv(HELPER, [HELPER, *sys.argv[1:]])
if sys.argv[1] == "read":
    if mode == "read-overflow":
        os.write(1, b"x" * (int(sys.argv[4]) + 1))
        sys.exit(0)
    if mode == "read-failure":
        os.write(2, b'{"stage":"read","errno":5}\\n')
        sys.exit(1)
    open(MARKER, "w").write(str(os.getpid()))
    time.sleep(60)
    sys.exit(0)
root, relative, channel = int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
sock = socket.socket(fileno=channel)
flags = os.O_RDONLY
if mode == "writable": flags = os.O_RDWR
if mode == "opath": flags = os.O_PATH
if mode == "directory": relative = "."
if mode == "wrong-inode": relative = "private/secret"
fd = os.open(relative, flags, dir_fd=root)
info = os.fstat(fd)
payload = struct.pack("<8sQQQQQ", b"FGFDv1\\0\\0", info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink)
rights = [fd] * (253 if mode == "many" else 2 if mode == "multiple" else 1)
ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", rights))]
if mode == "missing": ancillary = []
if mode == "short": payload = payload[:-1]
if mode == "oversize": payload += b"x" * 4096
if mode == "magic": payload = b"badmagic" + payload[8:]
sock.sendmsg([payload], ancillary)
if mode in ("extra", "empty-rights"):
    sock.sendmsg([b"x" if mode == "extra" else b""], ancillary)
if mode == "sent-block":
    open(MARKER, "w").write(str(os.getpid()))
    time.sleep(60)
if mode == "sent-failure":
    os.write(2, b'{"stage":"send","errno":5}\\n')
    sys.exit(1)
if mode == "stderr": os.write(2, b"unexpected")
if mode == "stdout": os.write(1, b"unexpected")
if mode == "stdout-flood": os.write(1, b"x" * (8 * 1024 * 1024))
if mode == "stderr-flood": os.write(2, b"x" * (8 * 1024 * 1024))
'''.replace("MODE", repr(mode)).replace("MARKER", repr(str(self.work / "marker")))
            .replace("HELPER", repr(str(Path(HANDLE_HELPER).resolve()))))
        script.chmod(0o700)
        return str(script)

    async def wait_marker(self):
        marker = self.work / "marker"
        async with asyncio.timeout(5):
            while not marker.exists() or not marker.read_text():
                await asyncio.sleep(0.005)
        return int(marker.read_text())

    def assert_reaped(self, pid):
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertIsNone(self.backend.process)

    async def test_capability_and_all_inherited_methods_remain_available(self):
        self.assertTrue(NativeFilesBackend.supported_methods <= self.backend.supported_methods)
        self.assertEqual(self.backend.capabilities, frozenset({"sandboxedFileStreaming"}))
        self.assertNotIn("sandboxedFileStreaming", NativeFilesBackend.capabilities)
        self.assertIn("sandboxedFileStreaming", json.dumps(self.initialized))
        result = await self.rpc("fs/readFile", path="file:///workspace/value", sandbox=context())
        self.assertEqual(base64.b64decode(result["result"]["dataBase64"]), self.original)
        result = await self.rpc("fs/getMetadata", path="file:///workspace/value", sandbox=context())
        self.assertEqual(result["result"]["size"], len(self.original))
        self.assertEqual((await self.opening())["result"], {"handleId": "h"})
        self.assertIn("result", await self.read())
        self.assertEqual((await self.rpc("fs/close", handleId="h"))["result"], {})

    async def test_real_binary_offsets_and_exact_upstream_eof_semantics(self):
        self.assertIn("result", await self.opening())
        for offset, length in ((0, 17), (23, 777), (0, len(self.original)),
                               (len(self.original) - 2, 11), (len(self.original), 1), (2**31, 41)):
            with self.subTest(offset=offset, length=length):
                result = (await self.read(offset=offset, length=length))["result"]
                expected = self.original[offset:offset + length]
                self.assertEqual(result, {"chunk": base64.b64encode(expected).decode(), "eof": len(expected) < length})
                self.assertIs(type(result["chunk"]), str)
                self.assertEqual(os.lseek(self.backend.handles["h"].fd, 0, os.SEEK_CUR), 0)

    async def test_files_larger_than_whole_file_limit_use_bounded_pread(self):
        size = 37 * 1024 * 1024 + 17
        path = self.root / "large"
        with path.open("wb") as stream:
            stream.truncate(size)
            stream.seek(19 * 1024 * 1024 + 41)
            stream.write(self.original)
            stream.seek(size - 17)
            stream.write(b"large-file-ending")
        self.assertIn("result", await self.opening(path="large"))
        for offset, length in ((0, MAX_BLOCK), (19 * 1024 * 1024 + 31, MAX_BLOCK), (size - 17, MAX_BLOCK)):
            result = (await self.read(offset=offset, length=length))["result"]
            with path.open("rb") as expected:
                expected.seek(offset)
                data = expected.read(length)
            self.assertEqual(base64.b64decode(result["chunk"]), data)
            self.assertEqual(result["eof"], len(data) < length)
        self.assertEqual(path.stat().st_size, size)

    async def test_fd_is_readonly_cloexec_and_the_retained_inode_survives_namespace_changes(self):
        self.assertIn("result", await self.opening())
        handle = self.backend.handles["h"]
        self.assertEqual(fcntl.fcntl(handle.fd, fcntl.F_GETFL) & os.O_ACCMODE, os.O_RDONLY)
        self.assertTrue(fcntl.fcntl(handle.fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC)
        with self.assertRaises(OSError) as caught:
            os.write(handle.fd, b"forbidden")
        self.assertEqual(caught.exception.errno, errno.EBADF)
        (self.root / "value").rename(self.root / "moved")
        (self.root / "moved").chmod(0)
        (self.root / "value").write_bytes(b"new inode")
        (self.root / "moved").unlink()
        self.assertEqual(os.fstat(handle.fd).st_nlink, 0)
        self.assertEqual(base64.b64decode((await self.read())["result"]["chunk"]), self.original)
        self.assertIn("result", await self.opening("new"))
        self.assertNotEqual(self.backend.handles["new"].inode, handle.inode)
        self.assertEqual(base64.b64decode((await self.read("new"))["result"]["chunk"]), b"new inode")

    async def test_complete_policy_denial_happens_before_native_acquisition(self):
        self.backend.handle_helper = self.peer("spawn-marker")
        policies = [None, {}, context(), context(), context()]
        policies[2]["permissions"]["network"] = "enabled"
        policies[3]["permissions"]["file_system"]["unreviewed"] = True
        policies[4]["unknown"] = True
        for policy in policies:
            params = {"handleId": "bad", "path": "file:///workspace/value"}
            if policy is not None:
                params["sandbox"] = policy
            self.assertIn("error", await self.rpc("fs/open", **params))
            self.assertFalse((self.work / "marker").exists())
        for path in ("private/secret", "../outside", ""):
            self.assertIn("error", await self.opening("denied", path))
            self.assertFalse((self.work / "marker").exists())
        self.assertEqual(self.backend.handles, {})
        self.assertIn("result", await self.opening())
        self.assertTrue((self.work / "marker").exists())

    async def test_handle_policy_is_frozen_and_lifecycle_cannot_replace_it(self):
        policy = context()
        self.assertIn("result", await self.opening(policy=policy))
        handle = self.backend.handles["h"]
        original = handle.policy.to_bytes()
        policy["permissions"]["file_system"]["entries"].clear()
        self.assertEqual(handle.policy.to_bytes(), original)
        self.assertEqual(handle.session_id, self.server.session_id)
        self.assertEqual(handle.handle_id, "h")
        with self.assertRaises(FrozenInstanceError):
            handle.fd = -1
        with self.assertRaises(FrozenInstanceError):
            handle.policy.context_json = b"{}"
        for method, params in (("fs/readBlock", {"handleId": "h", "offset": 0, "len": 1}),
                                ("fs/close", {"handleId": "h"})):
            self.assertEqual((await self.rpc(method, **params, sandbox=context()))["error"]["code"], -32602)
        self.assertEqual(handle.policy.to_bytes(), original)
        self.assertIn("result", await self.read())

    async def test_duplicate_unknown_handle_utf8_bounds_and_idempotent_close(self):
        self.assertIn("result", await self.opening())
        fd = self.backend.handles["h"].fd
        self.assertEqual((await self.opening())["error"]["code"], -32600)
        self.assertEqual(self.backend.handles["h"].fd, fd)
        self.assertEqual((await self.read("unknown"))["error"]["code"], -32004)
        self.assertEqual((await self.rpc("fs/close", handleId="unknown"))["result"], {})
        for identifier in ("", "é" * 16, "z" * 32):
            self.assertIn("result", await self.opening(identifier))
            self.assertIn("result", await self.read(identifier))
            self.assertIn("result", await self.rpc("fs/close", handleId=identifier))
        for identifier in ("é" * 17, "z" * 33):
            self.assertEqual((await self.opening(identifier))["error"]["code"], -32600)
        self.assertIn("result", await self.rpc("fs/close", handleId="h"))
        with self.assertRaises(OSError):
            os.fstat(fd)
        self.assertIn("result", await self.rpc("fs/close", handleId="h"))

    async def test_exact_128_handle_limit_releases_capacity_after_close(self):
        for number in range(128):
            self.assertIn("result", await self.opening(str(number)))
        before = self.fd_count()
        self.assertEqual((await self.opening("overflow"))["error"]["code"], -32600)
        self.assertEqual(self.fd_count(), before)
        await self.rpc("fs/close", handleId="71")
        self.assertIn("result", await self.opening("replacement"))
        self.assertEqual(len(self.backend.handles), 128)

    async def test_session_cannot_read_open_close_or_disconnect_another_session(self):
        self.assertIn("result", await self.opening())
        for method, params in (("fs/readBlock", {"handleId": "h", "offset": 0, "len": 1}),
                                ("fs/close", {"handleId": "h"}),
                                ("fs/open", {"handleId": "other", "path": "file:///workspace/value", "sandbox": context()})):
            with self.assertRaises(RpcError) as caught:
                await self.backend.handle(BackendCall("other-session", 9, method, encode_message(params)), self.emit)
            self.assertEqual(caught.exception.code, -32000)
        with self.assertRaises(RpcError):
            await self.backend.close("other-session")
        self.assertEqual(set(self.backend.handles), {"h"})
        self.assertIn("result", await self.read())

    async def test_strict_fields_types_and_offset_validation_retain_valid_handle(self):
        self.assertIn("result", await self.opening())
        invalid = [dict(offset=offset) for offset in (-1, 2**64, True, 1.0, "0")]
        invalid += [dict(len=value) for value in (-1, 2**64, False, 1.5, "1")]
        invalid += [{"unreviewed": 1}, {"handleId": 1}, {"handleId": None}]
        for change in invalid:
            params = {"handleId": "h", "offset": 0, "len": 1, **change}
            self.assertEqual((await self.rpc("fs/readBlock", **params))["error"]["code"], -32602)
        for length in (0, MAX_BLOCK + 1):
            self.assertEqual((await self.read(length=length))["error"]["code"], -32600)
        for method, params in (("fs/open", {"path": "file:///workspace/value", "sandbox": context()}),
                                ("fs/readBlock", {"handleId": "h", "offset": 0}), ("fs/close", {})):
            self.assertEqual((await self.rpc(method, **params))["error"]["code"], -32602)
        self.assertIn("h", self.backend.handles)
        self.assertIn("result", await self.read())

    async def test_native_off_t_failure_closes_handle_and_reports_actual_errno(self):
        self.assertIn("result", await self.opening())
        fd = self.backend.handles["h"].fd
        for offset in (2**63, 2**64 - 1):
            result = await self.read(offset=offset, length=1)
            self.assertEqual(result["error"]["code"], -32600)
            self.assertEqual(result["error"]["data"], {"stage": "offset", "errno": errno.EINVAL})
            self.assertNotIn("h", self.backend.handles)
            with self.assertRaises(OSError):
                os.fstat(fd)
            self.assertIn("result", await self.opening())
            fd = self.backend.handles["h"].fd

    async def test_absence_permission_alias_and_native_identity_fail_honestly(self):
        self.assertEqual((await self.opening(path="missing"))["error"]["code"], -32004)
        (self.root / "value").chmod(0)
        self.assertEqual((await self.opening())["error"]["code"], -32600)
        (self.root / "value").chmod(0o600)
        before = self.fd_count()
        with self.assertRaises(RpcError) as stale:
            await self.backend._acquire("value", (self.root / "private/secret").stat())
        self.assertEqual(stale.exception.data, {"stage": "identity", "errno": errno.ESTALE})
        (self.root / "alias").symlink_to("value")
        with self.assertRaises(RpcError):
            await self.backend._acquire("alias", (self.root / "alias").lstat())
        (self.root / "alias").unlink()
        os.link(self.root / "value", self.root / "hardlink")
        with self.assertRaises(RpcError):
            await self.backend._acquire("hardlink", (self.root / "hardlink").stat())
        (self.root / "hardlink").unlink()
        with self.assertRaises(RpcError):
            await self.backend._acquire("private", (self.root / "private").stat())
        self.assertEqual(self.fd_count(), before)
        self.assertEqual(self.backend.handles, {})

    async def test_real_malformed_scm_rights_transfers_never_leak_descriptors(self):
        baseline = self.fd_count()
        for mode in ("missing", "multiple", "many", "writable", "opath", "directory", "wrong-inode",
                     "short", "oversize", "magic", "extra", "empty-rights", "sent-failure", "stderr", "stdout",
                     "stdout-flood", "stderr-flood"):
            with self.subTest(mode=mode):
                self.backend.handle_helper = self.peer(mode)
                self.assertIn("error", await asyncio.wait_for(self.opening(), 5))
                self.assertEqual(self.backend.handles, {})
                self.assertIsNone(self.backend.process)
                self.assertEqual(self.fd_count(), baseline)
        self.backend.handle_helper = HANDLE_HELPER
        self.assertIn("result", await self.opening())

    async def test_repeated_real_open_close_and_spawn_failure_leave_no_fd(self):
        baseline = self.fd_count()
        for _ in range(24):
            self.assertIn("result", await self.opening())
            self.assertIn("result", await self.read(length=23))
            self.assertIn("result", await self.rpc("fs/close", handleId="h"))
            self.assertEqual(self.fd_count(), baseline)
        self.backend.handle_helper = str(self.work / "nonexistent-helper")
        self.assertIn("error", await self.opening())
        self.assertEqual(self.fd_count(), baseline)
        self.assertIsNone(self.backend.process)

    async def test_received_fd_closes_if_final_registration_fails(self):
        class RejectRegistration(dict):
            def __setitem__(self, key, value):
                raise RuntimeError("Injected allocation/registration failure")
        self.backend.handles = RejectRegistration()
        baseline = self.fd_count()
        self.assertIn("error", await self.opening())
        self.assertEqual(self.fd_count(), baseline)

    async def test_read_helper_failure_or_oversized_output_drops_handle(self):
        baseline = self.fd_count()
        for mode in ("read-failure", "read-overflow"):
            self.backend.handle_helper = HANDLE_HELPER
            self.assertIn("result", await self.opening())
            self.backend.handle_helper = self.peer(mode)
            self.assertEqual((await self.read(length=17))["error"]["code"], -32603)
            self.assertEqual(self.backend.handles, {})
            self.assertEqual(self.fd_count(), baseline)

    async def test_cancel_after_scm_rights_queued_reaps_child_and_closes_kernel_rights(self):
        baseline = self.fd_count()
        self.backend.handle_helper = self.peer("sent-block")
        task = asyncio.create_task(self.opening())
        pid = await self.wait_marker()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assert_reaped(pid)
        self.assertEqual(self.backend.handles, {})
        self.assertEqual(self.fd_count(), baseline)

    async def test_cancel_read_reaps_child_and_drops_bound_descriptor(self):
        baseline = self.fd_count()
        self.assertIn("result", await self.opening())
        self.backend.handle_helper = self.peer("read-block")
        task = asyncio.create_task(self.read())
        pid = await self.wait_marker()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assert_reaped(pid)
        self.assertEqual(self.backend.handles, {})
        self.assertEqual(self.fd_count(), baseline)

    async def test_cancel_during_actual_spawn_completion_still_reaps_process(self):
        baseline = self.fd_count()
        self.backend.handle_helper = self.peer("sent-block")
        created, release = asyncio.Event(), asyncio.Event()
        original_spawn = asyncio.create_subprocess_exec
        children = []

        async def delayed_spawn(*args, **kwargs):
            process = await original_spawn(*args, **kwargs)
            children.append(process)
            created.set()
            await release.wait()
            return process

        with patch("asyncio.create_subprocess_exec", delayed_spawn):
            task = asyncio.create_task(self.opening())
            await asyncio.wait_for(created.wait(), 5)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()  # Repeated transport cancellation cannot interrupt cleanup.
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(len(children), 1)
        self.assert_reaped(children[0].pid)
        self.assertEqual(self.fd_count(), baseline)
        self.assertEqual(self.backend.handles, {})

    async def test_disconnect_closes_all_handles_and_releases_workspace_lease(self):
        for identifier in ("a", "b", "c"):
            self.assertIn("result", await self.opening(identifier))
        descriptors = [self.backend.root, *(handle.fd for handle in self.backend.handles.values())]
        await self.server.close()
        self.assertTrue(self.backend.closed)
        self.assertEqual(self.backend.handles, {})
        for fd in descriptors:
            with self.assertRaises(OSError):
                os.fstat(fd)
        replacement = NativeFileStreamsBackend(FILE_HELPER, self.root, handle_helper=HANDLE_HELPER)
        await replacement.close("replacement")

    async def test_disconnect_cancels_actual_active_read_before_closing_other_handles(self):
        for identifier in ("active", "idle"):
            self.assertIn("result", await self.opening(identifier))
        descriptors = [self.backend.root, *(handle.fd for handle in self.backend.handles.values())]
        self.backend.handle_helper = self.peer("read-block")
        await self.server.accept({"id": 100, "method": "fs/readBlock",
            "params": {"handleId": "active", "offset": 0, "len": 17}}, self.emit)
        pid = await self.wait_marker()
        self.assertEqual(len(self.server.pending), 1)
        await asyncio.wait_for(self.server.close(), 5)
        self.assert_reaped(pid)
        self.assertEqual(self.server.pending, {})
        self.assertEqual(self.backend.handles, {})
        for fd in descriptors:
            with self.assertRaises(OSError):
                os.fstat(fd)
        replacement = NativeFileStreamsBackend(FILE_HELPER, self.root, handle_helper=HANDLE_HELPER)
        await replacement.close("replacement")


class NativeHandleDiagnosticTests(unittest.TestCase):
    def test_only_exact_native_diagnostics_can_become_remote_errors(self):
        for diagnostic in (b'{"stage":"open","stage":"open","errno":2}',
                           b'{"stage":[],"errno":2}', b'{"stage":"open","errno":true}',
                           b'{"stage":"open","errno":0}', b'{"stage":"invented","errno":2}',
                           b'{"stage":"open","errno":2,"extra":1}', b"\xff", b"x" * 513):
            error = _helper_error(diagnostic)
            self.assertEqual(error.code, -32603)
            self.assertIsNone(error.data)
        self.assertEqual(_helper_error(b'{"stage":"open","errno":2}\n').code, -32004)


if __name__ == "__main__":
    unittest.main()
