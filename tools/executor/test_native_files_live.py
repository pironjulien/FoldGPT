"""Real native file RPC tests. Requires compiled native-files and nonroot Linux."""
import asyncio
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.executor.exec_server import ExecServer
from tools.executor.native_files import NativeFilesBackend, _native_failure
from tools.executor.test_policy_intent import context

HELPER = os.environ.get("FOLDGPT_NATIVE_FILES")


@unittest.skipUnless(HELPER and os.name == "posix", "Requires the native Linux file helper")
class NativeFilesLiveTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if os.geteuid() == 0:
            self.fail("Run actual file permission checks as a nonroot user")
        self.temporary = tempfile.TemporaryDirectory(prefix="foldgpt-files-rpc-")
        self.root = Path(self.temporary.name)
        (self.root / ".git").mkdir()
        (self.root / ".git/config").write_bytes(b"protected")
        (self.root / "private").mkdir()
        (self.root / "private/secret").write_bytes(b"private")
        (self.root / "value").write_bytes(b"original")
        self.backend = NativeFilesBackend(HELPER, self.root)
        self.server = ExecServer(self.backend)
        result = await self.server.request({"id": 1, "method": "initialize", "params": {"clientName": "native-file-test"}})
        self.assertIn("result", result)
        await self.server.accept({"method": "initialized"}, self.emit)

    async def emit(self, _):
        pass

    async def asyncTearDown(self):
        await self.server.close()
        self.temporary.cleanup()

    async def rpc(self, path, data=None, policy=None):
        params = {"path": "file:///workspace/" + path, "sandbox": policy or context()}
        if data is not None:
            params["dataBase64"] = base64.b64encode(data).decode()
        return await self.server.request({"id": 2, "method": "fs/readFile" if data is None else "fs/writeFile", "params": params})

    async def test_actual_write_read_and_metadata_exceptions(self):
        self.assertEqual((await self.rpc("value", b"real\x00bytes"))["result"], {})
        self.assertEqual((self.root / "value").read_bytes(), b"real\x00bytes")
        read = await self.rpc("value")
        self.assertEqual(base64.b64decode(read["result"]["dataBase64"]), b"real\x00bytes")
        self.assertIn("error", await self.rpc(".git/config", b"forbidden"))
        self.assertEqual((self.root / ".git/config").read_bytes(), b"protected")
        self.assertIn("result", await self.rpc(".git/allowed", b"explicit"))
        self.assertEqual((self.root / ".git/allowed").read_bytes(), b"explicit")

    async def test_same_inode_write_read_deny_write(self):
        before = (self.root / "value").stat().st_ino
        for access in ("write", "read", "deny", "write"):
            policy = context()
            policy["permissions"]["file_system"]["entries"].append({"path": {"type": "path", "path": "file:///workspace/value"}, "access": access})
            read = await self.rpc("value", policy=policy)
            write = await self.rpc("value", access.encode(), policy=policy)
            self.assertEqual("result" in read, access != "deny")
            self.assertEqual("result" in write, access == "write")
            self.assertEqual((self.root / "value").stat().st_ino, before)
            self.assertEqual((self.root / "value").read_bytes(), b"write")

    async def test_denied_reads_and_unsupported_context_never_mutate(self):
        self.assertIn("error", await self.rpc("private/secret"))
        self.assertIn("error", await self.rpc("private/secret", b"forbidden"))
        policy = context()
        policy["permissions"]["file_system"]["extra"] = "unimplemented"
        self.assertIn("error", await self.rpc("new", b"forbidden", policy))
        self.assertFalse((self.root / "new").exists())
        self.assertEqual((self.root / "private/secret").read_bytes(), b"private")

    async def test_missing_files_preserve_official_not_found_semantics(self):
        for path in ("absent", "absent-parent/file"):
            with self.subTest(path=path):
                response = await self.rpc(path)
                self.assertEqual(response["error"]["code"], -32004)
        write = await self.rpc("absent-parent/file", b"must-not-appear")
        self.assertEqual(write["error"]["code"], -32004)
        self.assertFalse((self.root / "absent-parent").exists())
        for path in ("private/secret", "private/absent"):
            denied = await self.rpc(path)
            self.assertIn("error", denied)
            self.assertNotEqual(denied["error"]["code"], -32004)
        self.assertIn("result", await self.rpc("value"))

    async def test_new_gitdir_files_refuse_before_mutation_even_with_explicit_grant(self):
        (self.root / "nested").mkdir()
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                policy = context()
                if explicit:
                    policy["permissions"]["file_system"]["entries"].append({
                        "path": {"type": "path", "path": "file:///workspace/nested/.git"},
                        "access": "write",})
                result = await self.rpc("nested/.git", b"gitdir: /tmp/unsupported\n", policy)
                self.assertIn("error", result)
                self.assertFalse((self.root / "nested/.git").exists())
                self.assertIn("result", await self.rpc("value"))
                self.assertIn("result", await self.rpc("value", b"still-usable"))
                self.assertEqual((self.root / "value").read_bytes(), b"still-usable")

    async def test_aliases_and_nested_metadata_are_not_writable(self):
        (self.root / "nested/.git").mkdir(parents=True)
        (self.root / "nested/.git/config").write_bytes(b"nested")
        self.assertIn("error", await self.rpc("nested/.git/config", b"forbidden"))
        self.assertEqual((self.root / "nested/.git/config").read_bytes(), b"nested")
        (self.root / "link").symlink_to(".git/config")
        self.assertIn("error", await self.rpc("link", b"forbidden"))
        (self.root / "link").unlink()
        os.link(self.root / ".git/config", self.root / "link")
        self.assertIn("error", await self.rpc("link", b"forbidden"))
        self.assertEqual((self.root / ".git/config").read_bytes(), b"protected")

    async def test_native_rejects_aliases_and_truncated_transport_independently(self):
        (self.root / "link").symlink_to("value")
        for relative, expected, data in (("link", 4, b"bad!"), ("../outside", 4, b"bad!"), ("value", 9, b"short")):
            result = subprocess.run([HELPER, "write", str(self.backend.root), relative, str(expected)],
                pass_fds=(self.backend.root,), input=data, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.root / "value").read_bytes(), b"original")


class NativeDiagnosticTests(unittest.TestCase):
    def test_not_found_requires_a_strict_open_failure_record(self):
        self.assertEqual(_native_failure(b'{"stage":"open","errno":2}\n').code, -32004)
        for diagnostic in (
            b'{"stage":"open","errno":2,"errno":13}',
            b'{"stage":"open","errno":2,"extra":true}',
            b'{"stage":"open","errno":2.0}',
            b'{"stage":"open","errno":true}',
            b'{"stage":"unknown","errno":2}',
            b'{"stage":"open","errno":2} trailing',
            b'{"stage":"open","errno":0}',
            b'{"stage":"open","errno":99999}',
            b'\xff', b'[]', b'x' * 1025,
        ):
            with self.subTest(diagnostic=diagnostic):
                self.assertEqual(_native_failure(diagnostic).code, -32603)
        for diagnostic in (b'{"stage":"directory-sync","errno":2}',
                           b'{"stage":"open","errno":13}',
                           b'{"stage":"open","errno":1}'):
            self.assertNotEqual(_native_failure(diagnostic).code, -32004)


if __name__ == "__main__":
    unittest.main()
