"""Real native file RPC tests. Requires compiled native-files and nonroot Linux."""
import asyncio
import base64
import copy
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
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

    async def mkdir(self, path, policy=None, **options):
        params = {"path": "file:///workspace/" + path, "sandbox": policy or context(), **options}
        return await self.server.request({"id": 3, "method": "fs/createDirectory", "params": params})

    @staticmethod
    def grant(policy, path, access):
        policy["permissions"]["file_system"]["entries"].append({
            "path": {"type": "path", "path": "file:///workspace/" + path}, "access": access})

    async def test_recursive_directory_creation_and_following_file_rpcs(self):
        for number, options in enumerate(({}, {"recursive": None}, {"recursive": True, "followSymlinks": False})):
            with self.subTest(options=options):
                relative = f"created-{number}/donn%C3%A9es/child"
                self.assertEqual((await self.mkdir(relative, **options))["result"], {})
                actual = self.root / f"created-{number}/données/child"
                for directory in (actual, actual.parent, actual.parent.parent):
                    self.assertTrue(directory.is_dir())
                    self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
                    self.assertEqual(directory.stat().st_uid, os.getuid())
                self.assertIn("result", await self.rpc(relative + "/value", b"real-after-mkdir"))
                self.assertEqual((actual / "value").read_bytes(), b"real-after-mkdir")
                read = await self.rpc(relative + "/value")
                self.assertEqual(base64.b64decode(read["result"]["dataBase64"]), b"real-after-mkdir")

    async def test_nonrecursive_missing_parent_and_existing_directory_semantics(self):
        self.assertEqual((await self.mkdir("single", recursive=False))["result"], {})
        directory = self.root / "single"
        original = directory.stat()
        for path in ("single", ""):
            self.assertIn("error", await self.mkdir(path, recursive=False))
            self.assertEqual((await self.mkdir(path, recursive=True))["result"], {})
        self.assertEqual(directory.stat().st_ino, original.st_ino)
        self.assertIn("result", await self.mkdir("single/child", recursive=False))
        missing = await self.mkdir("missing/child", recursive=False)
        self.assertEqual(missing["error"]["code"], -32004)
        self.assertFalse((self.root / "missing").exists())
        for path in ("value", "value/child"):
            self.assertIn("error", await self.mkdir(path))
        self.assertEqual((self.root / "value").read_bytes(), b"original")

    async def test_missing_ancestor_policy_is_checked_before_any_creation(self):
        for access in ("read", "deny"):
            policy = context()
            self.grant(policy, "new/intermediate", access)
            self.grant(policy, "new/intermediate/leaf", "write")
            response = await self.mkdir("new/intermediate/leaf", policy=policy)
            self.assertIn("error", response)
            # The writable first component must not be created before the
            # denied intermediate component is discovered.
            self.assertFalse((self.root / "new").exists())
        policy = context()
        self.grant(policy, "private/absent/leaf", "write")
        self.assertIn("error", await self.mkdir("private/absent/leaf", policy=policy))
        self.assertFalse((self.root / "private/absent").exists())
        self.assertEqual((self.root / "private/secret").read_bytes(), b"private")

    async def test_explicit_child_write_can_override_an_existing_denied_parent(self):
        policy = context()
        self.grant(policy, "private/allowed", "write")
        self.assertEqual((await self.mkdir("private/allowed/child", policy=policy))["result"], {})
        self.assertTrue((self.root / "private/allowed/child").is_dir())
        self.assertIn("error", await self.rpc("private/secret", policy=policy))
        self.assertEqual((self.root / "private/secret").read_bytes(), b"private")

    async def test_directory_metadata_protection_and_explicit_exceptions(self):
        (self.root / "nested/.agents").mkdir(parents=True)
        for path in (".git/forbidden/child", ".codex/forbidden", "nested/.agents/forbidden"):
            self.assertIn("error", await self.mkdir(path))
            self.assertFalse((self.root / path).exists())
        self.assertFalse((self.root / ".codex").exists())
        self.assertFalse((self.root / ".git/forbidden").exists())
        self.assertIn("result", await self.mkdir(".git/allowed/child"))
        policy = context()
        self.grant(policy, "nested/.agents/allowed", "write")
        self.assertIn("result", await self.mkdir("nested/.agents/allowed/child", policy=policy))
        # Granting only the leaf cannot authorize creation of its protected
        # missing metadata parent.
        self.grant(policy, ".codex/allowed", "write")
        self.assertIn("error", await self.mkdir(".codex/allowed", policy=policy))
        self.assertFalse((self.root / ".codex").exists())
        self.grant(policy, ".codex", "write")
        self.assertIn("result", await self.mkdir(".codex/allowed", policy=policy))
        self.assertEqual((self.root / ".git/config").read_bytes(), b"protected")

    async def test_directory_aliases_unknown_fields_and_policy_refuse(self):
        (self.root / "alias").symlink_to("private", target_is_directory=True)
        for follow in (False, True, None):
            self.assertIn("error", await self.mkdir("alias/created", followSymlinks=follow))
        self.assertFalse((self.root / "private/created").exists())
        (self.root / "alias").unlink()
        for options in ({"recursive": "true"}, {"recursive": 1}, {"unknown": True}):
            self.assertIn("error", await self.mkdir("created", **options))
        policy = context()
        policy["permissions"]["file_system"]["unknown"] = True
        self.assertIn("error", await self.mkdir("created", policy=policy))
        self.assertFalse((self.root / "created").exists())

    async def test_directory_depth_bound_keeps_workspace_usable(self):
        too_deep = "/".join(["d"] * 65)
        self.assertIn("error", await self.mkdir(too_deep))
        self.assertFalse((self.root / "d").exists())
        admitted = "/".join(["d"] * 64)
        self.assertIn("result", await self.mkdir(admitted))
        self.assertTrue((self.root / admitted).is_dir())
        self.assertIn("result", await self.rpc("value", b"still-usable"))
        self.assertEqual((self.root / "value").read_bytes(), b"still-usable")

    async def test_native_directory_plan_and_input_are_rechecked_before_mutation(self):
        parent = os.fstat(self.backend.root)
        def native(path, missing, device=parent.st_dev, inode=parent.st_ino, data=b"", operation="mkdirs"):
            return subprocess.run([HELPER, operation, str(self.backend.root), path,
                str(missing), str(device), str(inode)], pass_fds=(self.backend.root,),
                input=data, capture_output=True, timeout=5)
        cases = (
            ("created/child", 2, parent.st_dev, parent.st_ino + 1, b"", "mkdirs"),
            ("created/child", 2, parent.st_dev + 1, parent.st_ino, b"", "mkdirs"),
            ("created/child", 2, parent.st_dev, parent.st_ino, b"extra", "mkdirs"),
            ("created/child", 1, parent.st_dev, parent.st_ino, b"", "mkdirs"),
            ("created/child", 2, parent.st_dev, parent.st_ino, b"", "mkdir"),
            ("../outside", 2, parent.st_dev, parent.st_ino, b"", "mkdirs"),
            ("created/" + "x" * 256, 2, parent.st_dev, parent.st_ino, b"", "mkdirs"),
            ("created/child", "-1", parent.st_dev, parent.st_ino, b"", "mkdirs"),
        )
        for case in cases:
            with self.subTest(case=case):
                result = native(*case)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertFalse((self.root / "created").exists())
        self.assertNotEqual(native("private/child", 2).returncode, 0)
        self.assertFalse((self.root / "private/child").exists())
        result = native("created/child", 2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b"")
        self.assertTrue((self.root / "created/child").is_dir())

    async def test_native_refuses_replaced_directory_identity(self):
        existing = self.root / "existing"
        existing.mkdir()
        inspected = existing.stat()
        existing.rename(self.root / "retained")
        existing.mkdir()
        result = subprocess.run([HELPER, "mkdirs", str(self.backend.root), "existing/child",
            "1", str(inspected.st_dev), str(inspected.st_ino)],
            pass_fds=(self.backend.root,), input=b"", capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((existing / "child").exists())
        self.assertFalse((self.root / "retained/child").exists())
        self.assertIn("result", await self.mkdir("existing/child"))
        self.assertTrue((existing / "child").is_dir())

    async def test_real_stdio_directory_and_file_round_trip_then_releases_lease(self):
        root = self.root / "stdio"
        root.mkdir(mode=0o700)
        # A separate Python server, real pipes and the actual native executable;
        # no fake backend or in-process RPC convenience path is involved here.
        source = (
            "import asyncio,sys\n"
            "from tools.executor.exec_server import ExecServer,serve_stdio\n"
            "from tools.executor.native_files import NativeFilesBackend\n"
            "asyncio.run(serve_stdio(ExecServer(NativeFilesBackend(sys.argv[1],sys.argv[2]))))\n"
        )
        process = await asyncio.create_subprocess_exec(sys.executable, "-B", "-c", source,
            HELPER, str(root), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env={}, cwd=Path(__file__).resolve().parents[2])

        async def exchange(identifier, method, params):
            process.stdin.write(json.dumps({"id": identifier, "method": method, "params": params}).encode() + b"\n")
            await process.stdin.drain()
            message = json.loads(await asyncio.wait_for(process.stdout.readline(), 5))
            self.assertEqual(message["id"], identifier)
            return message

        try:
            self.assertIn("result", await exchange(1, "initialize", {"clientName": "real-directory-test"}))
            process.stdin.write(b'{"method":"initialized"}\n')
            self.assertEqual((await exchange(2, "fs/createDirectory", {
                "path": "file:///workspace/new/child", "sandbox": context()}))["result"], {})
            self.assertTrue((root / "new/child").is_dir())
            self.assertEqual((await exchange(3, "fs/writeFile", {
                "path": "file:///workspace/new/child/value", "sandbox": context(),
                "dataBase64": base64.b64encode(b"stdio-native-bytes").decode()}))["result"], {})
            self.assertEqual((root / "new/child/value").read_bytes(), b"stdio-native-bytes")
            read = await exchange(4, "fs/readFile", {
                "path": "file:///workspace/new/child/value", "sandbox": context()})
            self.assertEqual(base64.b64decode(read["result"]["dataBase64"]), b"stdio-native-bytes")
            policy = context()
            self.grant(policy, "denied/intermediate", "deny")
            self.grant(policy, "denied/intermediate/leaf", "write")
            self.assertIn("error", await exchange(5, "fs/createDirectory", {
                "path": "file:///workspace/denied/intermediate/leaf", "sandbox": policy}))
            self.assertFalse((root / "denied").exists())
            process.stdin.close()
            await process.stdin.wait_closed()
            self.assertEqual(await asyncio.wait_for(process.wait(), 5), 0)
            self.assertEqual(await process.stdout.read(), b"")
            self.assertEqual(await process.stderr.read(), b"")
            successor = NativeFilesBackend(HELPER, root)
            await successor.close(None)
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()

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
