"""Actual filesystem tests, with every temporary artifact beneath the project.

POSIX descriptor no-follow checks execute only on POSIX; Windows does not claim
to validate Android descriptors. No process, phone, root, or mounted guest is used.
"""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from tools.executor.exec_server import BackendCall, RpcError
from tools.executor.ordinary_uid_files import OrdinaryUidFilesBackend, native_path
from tools.executor import ordinary_uid_files as ordinary


PROJECT = Path(__file__).resolve().parents[2]
ARTIFACTS = PROJECT / "work" / "ordinary-uid-20260908"


def disabled(**fields):
    return {"permissions": {"type": "disabled"}, "windowsSandboxLevel": "disabled", **fields}


class OrdinaryFilesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="files-", dir=ARTIFACTS)
        self.root = Path(self.temporary.name).resolve()
        self.backend = OrdinaryUidFilesBackend()
        self.sequence = 0
        self.loop_errors = []
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: self.loop_errors.append(context))

    async def asyncTearDown(self):
        await self.backend.close(self.backend.session or "session-a")
        self.assertTrue(self.root.is_relative_to(ARTIFACTS.resolve()))
        self.temporary.cleanup()
        self.assertFalse(self.loop_errors, "No unowned worker exception may escape cancellation")

    async def call(self, method, *, session="session-a", **params):
        self.sequence += 1
        call = BackendCall(session, self.sequence, "fs/" + method,
            json.dumps(params, ensure_ascii=False).encode("utf-8"))
        return await self.backend.handle(call, None)

    async def write(self, path, data=b"native", **params):
        return await self.call("writeFile", path=path.as_uri(),
            dataBase64=base64.b64encode(data).decode("ascii"), **params)

    def symlink(self, source, target, *, directory=False):
        try:
            os.symlink(source, target, target_is_directory=directory)
        except OSError as error:
            if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows account cannot create actual symlinks")
            raise

    async def test_absent_null_disabled_write_read_real_native_paths(self):
        for index, params in enumerate(({}, {"sandbox": None}, {"sandbox": disabled()})):
            path = self.root / ("unicode é space-%d.txt" % index)
            await self.write(path, b"long-original", **params)
            await self.write(path, b"42", **params)
            self.assertEqual(path.read_bytes(), b"42")
            result = await self.call("readFile", path=path.as_uri(), **params)
            self.assertEqual(base64.b64decode(result["dataBase64"]), b"42")
            self.assertEqual((await self.call("canonicalize", path=path.as_uri()))["path"], path.as_uri())
        metadata = await self.call("getMetadata", path=path.as_uri())
        self.assertEqual((metadata["isFile"], metadata["isDirectory"], metadata["isSymlink"], metadata["size"]),
            (True, False, False, 2))
        self.assertEqual(metadata["modifiedAtMs"], path.stat().st_mtime_ns // 1000000)

    async def test_disabled_context_optional_fields_validated_without_workspace_rebase(self):
        context = disabled(cwd=None, workspaceRoots=[], userHomeDir=None, temporaryDirectories=None,
            windowsSandboxPrivateDesktop=True, windowsSandboxProxySettingsMode="preserve", useLegacyLandlock=True)
        context["windowsSandboxLevel"] = "restricted-token"
        path = self.root / "outside-declared-roots"
        await self.write(path, sandbox=context)
        self.assertEqual(path.read_bytes(), b"native")

    async def test_managed_unknown_malformed_contexts_never_write_or_fall_through(self):
        contexts = [False, {}, {"permissions": {"type": "disabled"}},
            disabled(unknown=True), disabled(workspaceRoots=None), disabled(cwd="file:///bad%00path"),
            disabled(useLegacyLandlock=None), disabled(windowsSandboxPrivateDesktop=1)]
        for permissions in ({"type": "managed", "file_system": {"type": "unrestricted"}, "network": "enabled"},
                {"type": "external", "network": "enabled"}, {"type": "disabled", "network": "enabled"},
                {"type": "unknown"}):
            contexts.append({**disabled(), "permissions": permissions})
        for context in contexts:
            with self.subTest(context=context):
                with self.assertRaises(RpcError):
                    await self.write(self.root / "forbidden", sandbox=context)
                self.assertFalse((self.root / "forbidden").exists())
        self.assertIsNone(self.backend.session)

    async def test_uri_unknown_option_and_base64_refusals(self):
        for uri in ("relative", "file://remote-server/etc/x", "https://example.com/x", "file:///x?key=x", "file:///x%00"):
            with self.subTest(uri=uri), self.assertRaises(RpcError):
                await self.call("readFile", path=uri)
        with self.assertRaises(RpcError):
            await self.write(self.root / "not-written", unknown=True)
        with self.assertRaises(RpcError):
            await self.call("writeFile", path=(self.root / "not-written").as_uri(), dataBase64="!!!!")
        self.assertFalse((self.root / "not-written").exists())

    async def test_missing_file_and_missing_parent_report_real_not_found(self):
        with self.assertRaises(RpcError) as missing:
            await self.call("readFile", path=(self.root / "missing").as_uri())
        self.assertEqual(missing.exception.code, -32004)
        with self.assertRaises(RpcError) as parent:
            await self.write(self.root / "missing" / "child")
        self.assertEqual(parent.exception.code, -32004)
        self.assertFalse((self.root / "missing").exists())

    async def test_directory_defaults_nonrecursive_and_remove_force(self):
        nested = self.root / "parent" / "child"
        with self.assertRaises(RpcError):
            await self.call("createDirectory", path=nested.as_uri(), recursive=False)
        await self.call("createDirectory", path=nested.as_uri())
        await self.call("createDirectory", path=nested.as_uri())
        await self.write(nested / "file")
        with self.assertRaises(RpcError):
            await self.call("remove", path=nested.as_uri(), recursive=False)
        self.assertTrue((nested / "file").exists())
        await self.call("remove", path=nested.as_uri())
        self.assertFalse(nested.exists())
        await self.call("remove", path=nested.as_uri())
        with self.assertRaises(RpcError) as missing:
            await self.call("remove", path=nested.as_uri(), force=False)
        self.assertEqual(missing.exception.code, -32004)

    async def test_real_aliases_hardlinks_and_final_link_remove(self):
        target = self.root / "target"
        target.write_bytes(b"before")
        hardlink = self.root / "hardlink"
        os.link(target, hardlink)
        await self.write(hardlink, b"after")
        self.assertEqual(target.read_bytes(), b"after")
        link = self.root / "symbolic"
        self.symlink(target.name, link)
        await self.write(link, b"followed")
        self.assertEqual(target.read_bytes(), b"followed")
        metadata = await self.call("getMetadata", path=link.as_uri())
        self.assertTrue(metadata["isSymlink"] and metadata["isFile"])
        self.assertEqual((await self.call("canonicalize", path=link.as_uri()))["path"], target.as_uri())
        await self.call("remove", path=link.as_uri())
        self.assertFalse(link.is_symlink())
        self.assertEqual(target.read_bytes(), b"followed")

    async def test_read_directory_follows_links_and_omits_dangling(self):
        (self.root / "file").write_bytes(b"x")
        (self.root / "directory").mkdir()
        self.symlink("file", self.root / "file-link")
        self.symlink("directory", self.root / "directory-link", directory=True)
        self.symlink("absent", self.root / "broken")
        entries = {e["fileName"]: e for e in (await self.call("readDirectory", path=self.root.as_uri()))["entries"]}
        self.assertNotIn("broken", entries)
        self.assertTrue(entries["file-link"]["isFile"])
        self.assertTrue(entries["directory-link"]["isDirectory"])

    async def test_copy_files_and_directory_merge_preserves_bytes_and_rejects_self(self):
        source = self.root / "source"
        (source / "sub").mkdir(parents=True)
        (source / "sub" / "file").write_bytes(b"source")
        target = self.root / "target"
        target.mkdir()
        (target / "keep").write_bytes(b"keep")
        with self.assertRaises(RpcError):
            await self.call("copy", sourcePath=source.as_uri(), destinationPath=target.as_uri(), recursive=False)
        await self.call("copy", sourcePath=source.as_uri(), destinationPath=target.as_uri(), recursive=True)
        self.assertEqual((target / "sub" / "file").read_bytes(), b"source")
        self.assertEqual((target / "keep").read_bytes(), b"keep")
        for destination in (source, source / "sub" / "deep"):
            with self.assertRaises(RpcError):
                await self.call("copy", sourcePath=source.as_uri(), destinationPath=destination.as_uri(), recursive=True)
        file = target / "keep"
        with self.assertRaises(RpcError):
            await self.call("copy", sourcePath=file.as_uri(), destinationPath=file.as_uri(), recursive=False)
        self.assertEqual(file.read_bytes(), b"keep")

    async def test_copy_preserves_symlink_and_rejects_alias_descendant(self):
        source = self.root / "source"
        source.mkdir()
        (source / "file").write_bytes(b"data")
        self.symlink("file", source / "link")
        self.symlink("source", self.root / "alias", directory=True)
        await self.call("copy", sourcePath=source.as_uri(), destinationPath=(self.root / "copy").as_uri(), recursive=True)
        self.assertEqual(os.readlink(self.root / "copy" / "link"), "file")
        with self.assertRaises(RpcError):
            await self.call("copy", sourcePath=source.as_uri(), destinationPath=(self.root / "alias" / "inside").as_uri(), recursive=True)
        self.assertFalse((source / "inside").exists())

    async def test_walk_limits_depth_hidden_and_real_output(self):
        for name in ("dir", ".hidden"):
            (self.root / name).mkdir()
            (self.root / name / "file").write_bytes(b"content")
        (self.root / "top").write_bytes(b"top")
        options = dict(maxDepth=0, maxDirectories=10, maxEntries=20, followDirectorySymlinks=False)
        result = await self.call("walk", path=self.root.as_uri(), options=options)
        self.assertEqual({native_path(e["path"]).name for e in result["entries"]}, {"dir", ".hidden", "top"})
        options.update(maxDepth=4, pruneHiddenDirectories=True)
        result = await self.call("walk", path=self.root.as_uri(), options=options)
        self.assertIn((self.root / "dir" / "file").as_uri(), {e["path"] for e in result["entries"]})
        self.assertNotIn((self.root / ".hidden" / "file").as_uri(), {e["path"] for e in result["entries"]})
        options["maxEntries"] = 1
        result = await self.call("walk", path=self.root.as_uri(), options=options)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["entries"]), 1)
        for changed in ({"maxDepth": 65}, {"maxEntries": 0}, {"maxDirectories": True}, {"unknown": True}):
            with self.assertRaises(RpcError):
                await self.call("walk", path=self.root.as_uri(), options={**options, **changed})

    async def test_walk_cycle_and_file_link_semantics(self):
        (self.root / "file").write_bytes(b"data")
        self.symlink("file", self.root / "file-link")
        self.symlink(".", self.root / "cycle", directory=True)
        options = dict(maxDepth=64, maxDirectories=100, maxEntries=100, followDirectorySymlinks=True)
        result = await self.call("walk", path=self.root.as_uri(), options=options)
        self.assertFalse(result["truncated"])
        self.assertEqual({native_path(e["path"]).name for e in result["entries"]}, {"file", "cycle"})
        options["followDirectorySymlinks"] = False
        result = await self.call("walk", path=(self.root / "cycle").as_uri(), options=options)
        self.assertEqual(result, {"entries": [], "errors": [], "truncated": False})

    async def test_stream_offsets_eof_and_immutable_session_mode(self):
        path = self.root / "file"
        path.write_bytes(b"0123456789")
        await self.call("open", path=path.as_uri(), handleId="read", sandbox=disabled())
        fd = self.backend.handles["read"].fd
        self.assertFalse(os.get_inheritable(fd))
        block = await self.call("readBlock", handleId="read", offset=4, len=3)
        self.assertEqual((base64.b64decode(block["chunk"]), block["eof"]), (b"456", False))
        block = await self.call("readBlock", handleId="read", offset=9, len=3)
        self.assertEqual((base64.b64decode(block["chunk"]), block["eof"]), (b"9", True))
        with self.assertRaises(RpcError):
            await self.call("readBlock", handleId="read", offset=0, len=1, sandbox=disabled())
        with self.assertRaises(RpcError):
            await self.call("readBlock", session="other", handleId="read", offset=0, len=1)
        with self.assertRaises(RpcError):
            await self.call("close", session="other", handleId="read")
        self.assertEqual(os.fstat(fd).st_size, 10)
        await self.call("close", handleId="read")
        await self.call("close", handleId="read")
        with self.assertRaises(OSError):
            os.fstat(fd)
        with self.assertRaises(RpcError) as missing:
            await self.call("readBlock", handleId="read", offset=0, len=1)
        self.assertEqual(missing.exception.code, -32004)

    async def test_stream_duplicate_limits_invalid_len_and_read_error_closes(self):
        path = self.root / "file"
        path.write_bytes(b"x")
        await self.call("open", path=path.as_uri(), handleId="first")
        with self.assertRaises(RpcError):
            await self.call("open", path=path.as_uri(), handleId="first")
        with self.assertRaises(RpcError):
            await self.call("open", path=path.as_uri(), handleId="é" * 17)
        with self.assertRaises(RpcError):
            await self.call("readBlock", handleId="first", offset=0, len=0)
        self.assertIn("first", self.backend.handles)
        with self.assertRaises(RpcError):
            await self.call("readBlock", handleId="first", offset=2**64 - 1, len=1)
        self.assertNotIn("first", self.backend.handles)
        for index in range(128):
            await self.call("open", path=path.as_uri(), handleId=str(index))
        with self.assertRaises(RpcError):
            await self.call("open", path=path.as_uri(), handleId="overflow")

    async def test_shutdown_closes_actual_handles_and_refuses_reuse(self):
        path = self.root / "file"
        path.write_bytes(b"x")
        await self.call("open", path=path.as_uri(), handleId="read")
        fd = self.backend.handles["read"].fd
        with self.assertRaises(RpcError):
            await self.backend.close("other")
        self.assertFalse(self.backend.closed)
        await self.backend.close("session-a")
        self.assertFalse(self.backend.handles)
        with self.assertRaises(OSError):
            os.fstat(fd)
        with self.assertRaises(RpcError):
            await self.write(self.root / "late")
        self.assertFalse((self.root / "late").exists())

    async def test_cancel_queued_write_joins_worker_and_never_writes_later(self):
        loop = asyncio.get_running_loop()
        pool = ThreadPoolExecutor(max_workers=1)
        entered, release = threading.Event(), threading.Event()
        def occupy():
            entered.set()
            release.wait(10)
        blocker = pool.submit(occupy)
        entered.wait(5)
        previous = loop._default_executor
        loop.set_default_executor(pool)
        task = asyncio.create_task(self.write(self.root / "cancelled"))
        try:
            for _ in range(4):
                await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done(), "Cancellation must retain worker ownership")
            self.assertTrue(self.backend.lock.locked())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(self.backend.lock.locked())
            self.assertFalse((self.root / "cancelled").exists())
        finally:
            release.set()
            blocker.result(10)
            pool.shutdown(wait=True)
            loop._default_executor = previous

    async def test_cancel_queued_duplicate_open_preserves_original_handle(self):
        path = self.root / "file"
        path.write_bytes(b"original")
        await self.call("open", path=path.as_uri(), handleId="original")
        fd = self.backend.handles["original"].fd
        loop = asyncio.get_running_loop()
        pool = ThreadPoolExecutor(max_workers=1)
        release = threading.Event()
        blocker = pool.submit(release.wait, 10)
        previous = loop._default_executor
        loop.set_default_executor(pool)
        task = asyncio.create_task(self.call("open", path=path.as_uri(), handleId="original"))
        try:
            for _ in range(4):
                await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(self.backend.handles["original"].fd, fd)
            self.assertEqual(os.fstat(fd).st_size, 8)
        finally:
            release.set()
            blocker.result(10)
            pool.shutdown(wait=True)
            loop._default_executor = previous

    async def test_cancel_inflight_real_write_waits_for_descriptor_close(self):
        entered, release = threading.Event(), threading.Event()
        original = ordinary._write_all
        def controlled_write(fd, data, cancelled):
            os.write(fd, data[:1])  # A real committed byte before cancellation.
            entered.set()
            release.wait(10)
            original(fd, data[1:], cancelled)
        path = self.root / "partial"
        with patch.object(ordinary, "_write_all", controlled_write):
            task = asyncio.create_task(self.write(path, b"abcdef"))
            while not entered.is_set():
                await asyncio.sleep(0.001)
            task.cancel()
            await asyncio.sleep(0)
            self.assertTrue(self.backend.lock.locked())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(path.read_bytes(), b"a")
        await self.write(path, b"after-cancel")
        self.assertEqual(path.read_bytes(), b"after-cancel")

    @unittest.skipUnless(os.name == "posix", "Actual Android/POSIX no-follow descriptors required")
    async def test_nofollow_rejects_parent_leaf_aliases_and_preserves_target(self):
        actual = self.root / "actual"
        actual.mkdir()
        (actual / "file").write_bytes(b"original")
        self.symlink("actual", self.root / "alias", directory=True)
        self.symlink("file", actual / "link")
        for path in (self.root / "alias" / "file", actual / "link"):
            for method, extra in (("readFile", {}), ("getMetadata", {}),
                    ("writeFile", {"dataBase64": "eA=="}), ("remove", {"recursive": False})):
                with self.subTest(path=path, method=method), self.assertRaises(RpcError):
                    await self.call(method, path=path.as_uri(), followSymlinks=False, **extra)
        self.assertEqual((actual / "file").read_bytes(), b"original")
        nested = actual / "new" / "deep"
        await self.call("createDirectory", path=nested.as_uri(), followSymlinks=False)
        await self.write(nested / "created", b"42", followSymlinks=False)
        await self.call("remove", path=(nested / "created").as_uri(), recursive=False, followSymlinks=False)
        with self.assertRaises(RpcError):
            await self.call("remove", path=nested.as_uri(), recursive=True, followSymlinks=False)

    @unittest.skipUnless(os.name == "posix", "Actual POSIX FIFO required")
    async def test_fifo_read_never_blocks_or_returns_regular_file_success(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        for method, extra in (("readFile", {}), ("open", {"handleId": "fifo"})):
            with self.assertRaises(RpcError):
                await asyncio.wait_for(self.call(method, path=fifo.as_uri(), **extra), timeout=2)
        self.assertFalse(self.backend.handles)


if __name__ == "__main__":
    unittest.main()
