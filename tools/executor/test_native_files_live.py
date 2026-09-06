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

from tools.executor.exec_server import ExecServer, RpcError
from tools.executor.native_files import NativeFilesBackend, _native_failure, _native_metadata
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

    async def inspect(self, path, *, canonicalize=False, policy=None, **options):
        params = {"path": "file:///workspace/" + path, "sandbox": policy or context(), **options}
        return await self.server.request({"id": 4,
            "method": "fs/canonicalize" if canonicalize else "fs/getMetadata", "params": params})

    @staticmethod
    def grant(policy, path, access):
        policy["permissions"]["file_system"]["entries"].append({
            "path": {"type": "path", "path": "file:///workspace/" + path}, "access": access})

    async def tree_rpc(self, method, path="", policy=None, **options):
        params = {"path": "file:///workspace/" + path, "sandbox": policy or context(), **options}
        return await self.server.request({"id": 41, "method": "fs/" + method, "params": params})

    async def copy_rpc(self, source, destination, policy=None, recursive=False):
        return await self.server.request({"id": 42, "method": "fs/copy", "params": {
            "sourcePath": "file:///workspace/" + source, "destinationPath": "file:///workspace/" + destination,
            "recursive": recursive, "sandbox": policy or context()}})

    @staticmethod
    def walk_options(**changes):
        return {"maxDepth": 4, "maxDirectories": 10, "maxEntries": 100,
                "followDirectorySymlinks": False, **changes}

    async def test_directory_listing_and_bfs_walk_match_real_names_types_and_bounds(self):
        root = self.root / "tree"
        (root / "nested").mkdir(parents=True)
        (root / ".hidden").mkdir()
        (root / "file é #?%").write_bytes(b"root")
        (root / "nested/child").write_bytes(b"nested")
        (root / ".hidden/secret").write_bytes(b"hidden")
        before = {path: (path.stat().st_ino, path.stat().st_mtime_ns) for path in root.rglob("*")}
        listing = (await self.tree_rpc("readDirectory", "tree"))["result"]
        self.assertEqual(listing, {"entries": [
            {"fileName": item.name, "isDirectory": item.is_dir(), "isFile": item.is_file()}
            for item in sorted(root.iterdir(), key=lambda item: item.name)]})
        walk = (await self.tree_rpc("walk", "tree", options=self.walk_options()))["result"]
        expected = ["tree/.hidden", "tree/file%20%C3%A9%20%23%3F%25", "tree/nested", "tree/.hidden/secret", "tree/nested/child"]
        self.assertEqual([entry["path"] for entry in walk["entries"]], ["file:///workspace/" + path for path in expected])
        self.assertEqual([entry["kind"] for entry in walk["entries"]], ["directory", "file", "directory", "file", "file"])
        self.assertEqual(walk["errors"], [])
        self.assertFalse(walk["truncated"])
        for options, count, truncated in ((self.walk_options(maxDepth=0), 3, False),
                (self.walk_options(maxDirectories=1), 3, True), (self.walk_options(maxEntries=1), 1, True),
                (self.walk_options(pruneHiddenDirectories=True), 4, False)):
            result = (await self.tree_rpc("walk", "tree", options=options))["result"]
            self.assertEqual(len(result["entries"]), count)
            self.assertEqual(result["truncated"], truncated)
        self.assertEqual(before, {path: (path.stat().st_ino, path.stat().st_mtime_ns) for path in root.rglob("*")})
        self.assertEqual((await self.tree_rpc("walk", "value", options=self.walk_options()))["result"],
                         {"entries": [], "errors": [], "truncated": False})
        for method, opts in (("readDirectory", {}), ("walk", {"options": self.walk_options()})):
            missing = await self.tree_rpc(method, "absent", **opts)
            self.assertEqual(missing["error"]["code"], -32004)
        self.assertIn("error", await self.tree_rpc("readDirectory", "value"))

    async def test_walk_exact_upstream_options_and_policy_never_leak_denied_descendants(self):
        for method, opts in (("readDirectory", {}), ("walk", {"options": self.walk_options()})):
            denied = await self.tree_rpc(method, "", **opts)
            self.assertIn("error", denied)
            self.assertNotEqual(denied["error"]["code"], -32004)
            self.assertNotIn("secret", json.dumps(denied))
        policy = context()
        policy["permissions"]["file_system"]["entries"][2]["access"] = "read"
        self.assertIn("result", await self.tree_rpc("readDirectory", "", policy))
        self.assertIn("result", await self.tree_rpc("walk", "", policy, options=self.walk_options(followDirectorySymlinks=True)))
        self.grant(policy, "private/secret", "deny")
        self.assertIn("error", await self.tree_rpc("walk", "", policy, options=self.walk_options()))
        # A policy is checked only for returned/traversed descendants. A shallow
        # request never reads the denied grandchild and can still succeed.
        self.assertIn("result", await self.tree_rpc("walk", "", policy, options=self.walk_options(maxDepth=0)))
        for change in ({"maxDepth": 65}, {"maxDirectories": 10001}, {"maxEntries": 50001},
                       {"maxDirectories": 0}, {"maxEntries": 0}, {"maxDepth": -1}, {"maxEntries": True},
                       {"pruneHiddenDirectories": None}, {"followDirectorySymlinks": "false"}, {"unknown": 1}):
            self.assertIn("error", await self.tree_rpc("walk", "value", options=self.walk_options(**change)))
        for missing in self.walk_options():
            opts = self.walk_options()
            del opts[missing]
            self.assertIn("error", await self.tree_rpc("walk", "value", options=opts))

    async def test_remove_has_real_upstream_default_recursive_force_and_explicit_nonrecursive_semantics(self):
        for index, options in enumerate(({}, {"recursive": None, "force": None}, {"followSymlinks": False})):
            path = self.root / f"remove-{index}"
            (path / "nested").mkdir(parents=True)
            (path / "nested/file").write_bytes(b"actual")
            self.assertEqual((await self.tree_rpc("remove", path.name, **options))["result"], {})
            self.assertFalse(path.exists())
            self.assertEqual((await self.tree_rpc("remove", path.name, **options))["result"], {})
        (self.root / "empty").mkdir()
        self.assertEqual((await self.tree_rpc("remove", "empty", recursive=False, force=False))["result"], {})
        self.assertEqual((await self.tree_rpc("remove", "absent", force=False))["error"]["code"], -32004)
        self.assertEqual((await self.tree_rpc("remove", "missing/child"))["result"], {})
        before = (self.root / "value").stat()
        self.assertEqual((await self.tree_rpc("remove", "value", recursive=False, force=False))["result"], {})
        self.assertFalse((self.root / "value").exists())
        self.assertGreater(before.st_ino, 0)
        self.assertIn("error", await self.tree_rpc("remove", "", force=True))

    async def test_remove_preflights_all_protected_descendants_before_first_unlink(self):
        tree = self.root / "remove-tree"
        (tree / "z/.git").mkdir(parents=True)
        (tree / "a").write_bytes(b"must stay")
        (tree / "z/.git/config").write_bytes(b"protected")
        before = {path: path.lstat().st_ino for path in tree.rglob("*")}
        for policy in (context(), context()):
            self.grant(policy, "remove-tree", "write")
            self.assertIn("error", await self.tree_rpc("remove", "remove-tree", policy))
            self.assertEqual(before, {path: path.lstat().st_ino for path in tree.rglob("*")})
            self.assertEqual((tree / "a").read_bytes(), b"must stay")
        policy = context()
        self.grant(policy, "remove-tree/z/.git", "write")
        self.grant(policy, "remove-tree/a", "read")
        self.assertIn("error", await self.tree_rpc("remove", "remove-tree", policy))
        self.assertTrue(tree.exists())
        self.assertIn("error", await self.tree_rpc("remove", "remove-tree", policy, recursive=False))
        self.grant(policy, "remove-tree/a", "write")
        self.assertEqual((await self.tree_rpc("remove", "remove-tree", policy))["result"], {})
        self.assertFalse(tree.exists())
        self.assertEqual((self.root / ".git/config").read_bytes(), b"protected")

    async def test_copy_files_and_recursive_merge_preserve_real_bytes_permissions_and_unrelated_inodes(self):
        source = self.root / "source"
        (source / "nested").mkdir(parents=True)
        (source / "executable").write_bytes(b"#!/bin/sh\nprintf actual\n")
        (source / "executable").chmod(0o751)
        (source / "nested/empty").write_bytes(b"")
        (source / "nested/binary").write_bytes(bytes(range(256)) * 71)
        destination = self.root / "destination"
        (destination / "nested").mkdir(parents=True)
        (destination / "nested/binary").write_bytes(b"old destination")
        (destination / "unrelated").write_bytes(b"retained")
        unrelated = (destination / "unrelated").stat().st_ino
        overwritten = (destination / "nested/binary").stat().st_ino
        originals = {path: (path.stat().st_ino, path.read_bytes()) for path in source.rglob("*") if path.is_file()}
        self.assertEqual((await self.copy_rpc("source", "destination", recursive=True))["result"], {})
        for path, (inode, content) in originals.items():
            copied = destination / path.relative_to(source)
            self.assertEqual(copied.read_bytes(), content)
            self.assertEqual(stat.S_IMODE(copied.stat().st_mode), stat.S_IMODE(path.stat().st_mode))
            self.assertNotEqual(copied.stat().st_ino, inode)
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual((destination / "nested/binary").stat().st_ino, overwritten)
        self.assertEqual((destination / "unrelated").stat().st_ino, unrelated)
        self.assertEqual((destination / "unrelated").read_bytes(), b"retained")
        self.assertEqual((await self.copy_rpc("source", "new/parents/copied", recursive=True))["result"], {})
        self.assertEqual((self.root / "new/parents/copied/executable").read_bytes(), (source / "executable").read_bytes())
        self.assertEqual((await self.copy_rpc("source/executable", "file-copy"))["result"], {})
        self.assertEqual((self.root / "file-copy").read_bytes(), (source / "executable").read_bytes())
        self.assertEqual((await self.copy_rpc("source/executable", "absent-parent/file"))["error"]["code"], -32004)
        self.assertFalse((self.root / "absent-parent").exists())

    async def test_copy_preflights_protected_paths_source_reads_type_conflicts_and_missing_ancestor_grants(self):
        source = self.root / "source"
        (source / "nested").mkdir(parents=True)
        (source / "a").write_bytes(b"first")
        (source / "nested/z").write_bytes(b"last")
        for relative, access in (("destination/nested/z", "deny"), ("destination/nested", "read"), ("source/nested/z", "deny")):
            policy = context()
            self.grant(policy, relative, access)
            self.assertIn("error", await self.copy_rpc("source", "destination", policy, True))
            self.assertFalse((self.root / "destination").exists())
        self.assertIn("error", await self.copy_rpc("source", "destination", recursive=False))
        self.assertFalse((self.root / "destination").exists())
        (self.root / "destination").mkdir()
        (self.root / "destination/nested").write_bytes(b"file blocks directory")
        self.assertIn("error", await self.copy_rpc("source", "destination", recursive=True))
        self.assertFalse((self.root / "destination/a").exists())
        self.assertEqual((self.root / "destination/nested").read_bytes(), b"file blocks directory")
        for first, second in (("source", "source"), ("source", "source/child"), ("source/nested", "source"), ("value", "value")):
            self.assertIn("error", await self.copy_rpc(first, second, recursive=True))
        self.assertEqual((self.root / "value").read_bytes(), b"original")
        policy = context()
        self.grant(policy, "private/copied", "write")
        self.assertIn("result", await self.copy_rpc("source", "private/copied", policy, True))
        self.assertEqual((self.root / "private/copied/nested/z").read_bytes(), b"last")
        self.assertIn("error", await self.copy_rpc("source", "private/missing/copied", policy, True))
        self.assertFalse((self.root / "private/missing").exists())

    async def test_copy_refuses_new_metadata_subtrees_and_gitdir_file_even_with_parent_write(self):
        (self.root / "source/.agents").mkdir(parents=True)
        (self.root / "source/.agents/instructions").write_bytes(b"metadata")
        (self.root / "source/a").write_bytes(b"ordinary")
        self.assertIn("error", await self.copy_rpc("source", "target", recursive=True))
        self.assertFalse((self.root / "target").exists())
        policy = context()
        self.grant(policy, "target/.agents", "write")
        self.assertIn("result", await self.copy_rpc("source", "target", policy, True))
        self.assertEqual((self.root / "target/.agents/instructions").read_bytes(), b"metadata")
        self.grant(policy, "target/.git", "write")
        self.assertIn("error", await self.copy_rpc("value", "target/.git", policy))
        self.assertFalse((self.root / "target/.git").exists())

    async def test_native_bulk_snapshot_refuses_stale_replaced_or_extra_files_before_mutation(self):
        _, _, _, nodes = self.backend._inspect(None)
        body = self.backend._snapshot(nodes)
        def native(operation, path, *rest, data=body):
            return subprocess.run([HELPER, operation, str(self.backend.root), path, str(len(data)), *rest],
                                  input=data, pass_fds=(self.backend.root,), capture_output=True, timeout=5)
        self.assertEqual(native("tree", "value").returncode, 0)
        (self.root / "value").write_bytes(b"changed after authorization")
        for args in (("remove", "value", "1", "1"), ("copy", "value", "destination", "0"), ("tree", ".")):
            result = native(*args)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(json.loads(result.stderr)["stage"], "tree-state")
            self.assertEqual((self.root / "value").read_bytes(), b"changed after authorization")
            self.assertFalse((self.root / "destination").exists())
        for bad in (body[:-1], body + b"extra\0", body + body, b"malformed"):
            self.assertNotEqual(native("remove", "value", "1", "1", data=bad).returncode, 0)
        for mutation in ("replace-inode", "new-protected-descendant", "new-hardlink"):
            _, _, _, current = self.backend._inspect(None)
            snapshot = self.backend._snapshot(current)
            if mutation == "replace-inode":
                original = self.root / "value"
                original.rename(self.root / "retained")
                original.write_bytes(b"replacement")
            elif mutation == "new-protected-descendant":
                (self.root / "introduced/.agents").mkdir(parents=True)
                (self.root / "introduced/.agents/secret").write_bytes(b"new protected metadata")
            else:
                os.link(self.root / "value", self.root / "hardlink")
            result = native("remove", "value", "1", "1", data=snapshot)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertTrue((self.root / "value").exists())
            if mutation == "new-hardlink":
                (self.root / "hardlink").unlink()
        self.assertEqual((self.root / ".git/config").read_bytes(), b"protected")

    async def test_bulk_rpcs_preserve_alias_refusals_and_reject_oversized_copy_before_creation(self):
        alias = self.root / "alias"
        for kind in ("symlink", "hardlink", "fifo", "gitdir"):
            if kind == "symlink":
                alias.symlink_to("value")
            elif kind == "hardlink":
                os.link(self.root / "value", alias)
            elif kind == "fifo":
                os.mkfifo(alias)
            else:
                (self.root / "nested").mkdir()
                (self.root / "nested/.git").write_bytes(b"gitdir: /unadmitted\n")
            try:
                self.assertIn("error", await self.tree_rpc("readDirectory", ""))
                self.assertIn("error", await self.tree_rpc("walk", "", options=self.walk_options()))
                self.assertIn("error", await self.tree_rpc("remove", "value"))
                self.assertIn("error", await self.copy_rpc("value", "destination"))
                self.assertFalse((self.root / "destination").exists())
                self.assertEqual((self.root / "value").read_bytes(), b"original")
            finally:
                if kind == "gitdir":
                    (self.root / "nested/.git").unlink()
                    (self.root / "nested").rmdir()
                else:
                    alias.unlink()
        with (self.root / "large").open("wb") as stream:
            stream.truncate(16 * 1024 * 1024 + 1)
        self.assertIn("error", await self.copy_rpc("large", "destination"))
        self.assertFalse((self.root / "destination").exists())
        self.assertEqual((self.root / "large").stat().st_size, 16 * 1024 * 1024 + 1)

    async def test_native_metadata_matches_physical_objects_and_is_fresh_after_write(self):
        for relative in ("value", ".git", ""):
            physical = self.root / relative
            expected = physical.stat()
            birth_seconds = int(subprocess.check_output(["stat", "--printf=%W", str(physical)]))
            for follow in (None, False, True):
                with self.subTest(relative=relative, follow=follow):
                    result = (await self.inspect(relative, followSymlinks=follow))["result"]
                    self.assertEqual(result["isFile"], stat.S_ISREG(expected.st_mode))
                    self.assertEqual(result["isDirectory"], stat.S_ISDIR(expected.st_mode))
                    self.assertFalse(result["isSymlink"])
                    self.assertEqual(result["size"], expected.st_size)
                    self.assertEqual(result["modifiedAtMs"], expected.st_mtime_ns // 1000000)
                    if birth_seconds:
                        self.assertGreaterEqual(result["createdAtMs"], birth_seconds * 1000)
                        self.assertLess(result["createdAtMs"], (birth_seconds + 1) * 1000)
                    else:
                        self.assertEqual(result["createdAtMs"], 0)
            self.assertEqual(physical.stat().st_ino, expected.st_ino)
        before = (self.root / "value").stat()
        self.assertIn("result", await self.rpc("value", b"a different native file length"))
        current = (await self.inspect("value"))["result"]
        self.assertEqual(current["size"], (self.root / "value").stat().st_size)
        self.assertEqual(current["modifiedAtMs"], (self.root / "value").stat().st_mtime_ns // 1000000)
        self.assertEqual((self.root / "value").stat().st_ino, before.st_ino)

    async def test_metadata_preserves_upstream_pre_epoch_option_semantics(self):
        path = self.root / "value"
        os.utime(path, ns=(-1234567890, -1234567890))
        actual = path.stat().st_mtime_ns
        self.assertLess(actual, 0, "The fixture filesystem must support pre-epoch mtimes")
        for follow in (True, None):
            self.assertEqual((await self.inspect("value", followSymlinks=follow))["result"]["modifiedAtMs"], 0)
        self.assertEqual((await self.inspect("value", followSymlinks=False))["result"]["modifiedAtMs"],
            actual // 1000000)
        self.assertEqual(path.read_bytes(), b"original")

    async def test_metadata_and_canonicalization_follow_each_actual_policy_without_leaks(self):
        before = (self.root / "value").stat()
        for access in ("write", "read", "deny", "write"):
            policy = context()
            self.grant(policy, "value", access)
            for canonicalize in (False, True):
                result = await self.inspect("value", canonicalize=canonicalize, policy=policy)
                self.assertEqual("result" in result, access != "deny")
                if access == "deny":
                    self.assertNotEqual(result["error"]["code"], -32004)
            self.assertEqual((self.root / "value").stat().st_ino, before.st_ino)
            self.assertEqual((self.root / "value").read_bytes(), b"original")
        policy = context()
        self.grant(policy, "private/secret", "read")
        for canonicalize in (False, True):
            # The explicit child grant is effective despite its denied parent.
            self.assertIn("result", await self.inspect("private/secret", canonicalize=canonicalize, policy=policy))
            for relative in ("private", "private/secret", "private/absent"):
                denied = await self.inspect(relative, canonicalize=canonicalize)
                self.assertIn("error", denied)
                self.assertNotEqual(denied["error"]["code"], -32004)

    async def test_canonicalization_requires_real_object_and_returns_only_guest_uri(self):
        directory = self.root / "données #?%"
        directory.mkdir()
        (directory / "value").write_bytes(b"real")
        for relative, canonical in (
                ("", "file:///workspace"),
                ("//value", "file:///workspace/value"),
                ("donn%c3%a9es%20%23%3f%25//value", "file:///workspace/donn%C3%A9es%20%23%3F%25/value"),
                (".git", "file:///workspace/.git")):
            result = await self.inspect(relative, canonicalize=True)
            self.assertEqual(result["result"], {"path": canonical})
            self.assertNotIn(str(self.root), json.dumps(result))
        for canonicalize in (False, True):
            for relative in ("absent", "absent-parent/child"):
                response = await self.inspect(relative, canonicalize=canonicalize)
                self.assertEqual(response["error"]["code"], -32004)
            self.assertIn("result", await self.inspect("value", canonicalize=canonicalize))
        self.assertFalse((self.root / "absent").exists())
        self.assertFalse((self.root / "absent-parent").exists())

    async def test_inspection_refuses_aliases_special_files_and_unsupported_requests(self):
        alias = self.root / "alias"
        for kind in ("symlink", "directory-symlink", "hardlink", "fifo"):
            if kind == "symlink":
                alias.symlink_to("value")
            elif kind == "directory-symlink":
                alias.symlink_to(".git", target_is_directory=True)
            elif kind == "hardlink":
                os.link(self.root / "value", alias)
            else:
                os.mkfifo(alias)
            try:
                for follow in (False, True, None):
                    self.assertIn("error", await self.inspect("alias", followSymlinks=follow))
                self.assertIn("error", await self.inspect("alias", canonicalize=True))
            finally:
                alias.unlink()
        for canonicalize in (False, True):
            for path in ("../outside", "%2e%2e/outside", "private%2Fsecret"):
                self.assertIn("error", await self.inspect(path, canonicalize=canonicalize))
            for options in ({"unknown": True}, {"followSymlinks": "false"}):
                self.assertIn("error", await self.inspect("value", canonicalize=canonicalize, **options))
            policy = context()
            policy["permissions"]["file_system"]["unknown"] = True
            self.assertIn("error", await self.inspect("value", canonicalize=canonicalize, policy=policy))
        self.assertIn("error", await self.inspect("value", canonicalize=True, followSymlinks=True))
        self.assertEqual((self.root / "value").read_bytes(), b"original")
        self.assertEqual((self.root / ".git/config").read_bytes(), b"protected")

    async def test_native_inspection_rechecks_type_aliases_and_empty_input_independently(self):
        def native(operation, path, length="0", data=b""):
            return subprocess.run([HELPER, operation, str(self.backend.root), path, length],
                pass_fds=(self.backend.root,), input=data, capture_output=True, timeout=5)
        for operation in ("metadata", "metadata-nofollow", "canonicalize"):
            for path, length, body in (("../outside", "0", b""), ("absent", "0", b""),
                    ("value", "1", b""), ("value", "-0", b""), ("value", "0", b"unexpected")):
                result = native(operation, path, length, body)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
            for kind in ("symlink", "hardlink", "fifo"):
                alias = self.root / "native-alias"
                if kind == "symlink":
                    alias.symlink_to("value")
                elif kind == "hardlink":
                    os.link(self.root / "value", alias)
                else:
                    os.mkfifo(alias)
                try:
                    result = native(operation, "native-alias")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b"")
                finally:
                    alias.unlink()
            for path in ("value", ".git", "."):
                result = native(operation, path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, b"")
                if operation == "canonicalize":
                    self.assertEqual(result.stdout, b"")
                else:
                    actual = (self.root / path).stat()
                    parsed = _native_metadata(result.stdout)
                    self.assertEqual(parsed["size"], actual.st_size)
                    self.assertEqual(parsed["isFile"], stat.S_ISREG(actual.st_mode))
        self.assertEqual((self.root / "value").read_bytes(), b"original")

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
            metadata = await exchange(6, "fs/getMetadata", {
                "path": "file:///workspace/new/child/value", "sandbox": context(), "followSymlinks": False})
            self.assertTrue(metadata["result"]["isFile"])
            self.assertEqual(metadata["result"]["size"], (root / "new/child/value").stat().st_size)
            self.assertEqual(metadata["result"]["modifiedAtMs"],
                (root / "new/child/value").stat().st_mtime_ns // 1000000)
            canonical = await exchange(7, "fs/canonicalize", {
                "path": "file:///workspace/new//child/value", "sandbox": context()})
            self.assertEqual(canonical["result"], {"path": "file:///workspace/new/child/value"})
            self.grant(policy, "new/child/value", "deny")
            for identifier, method in ((8, "fs/getMetadata"), (9, "fs/canonicalize")):
                denied = await exchange(identifier, method, {
                    "path": "file:///workspace/new/child/value", "sandbox": policy})
                self.assertIn("error", denied)
                self.assertNotEqual(denied["error"]["code"], -32004)
            missing = await exchange(10, "fs/canonicalize", {
                "path": "file:///workspace/new/absent", "sandbox": context()})
            self.assertEqual(missing["error"]["code"], -32004)
            self.assertEqual((root / "new/child/value").read_bytes(), b"stdio-native-bytes")
            # The actual stdio protocol now covers the operations used around
            # patch application: inspect a tree, copy, edit, and remove a file.
            listed = await exchange(11, "fs/readDirectory", {"path": "file:///workspace/new/child", "sandbox": context()})
            self.assertEqual(listed["result"], {"entries": [{"fileName": "value", "isDirectory": False, "isFile": True}]})
            walked = await exchange(12, "fs/walk", {"path": "file:///workspace/new", "options": self.walk_options(), "sandbox": context()})
            self.assertEqual(walked["result"]["entries"], [
                {"path": "file:///workspace/new/child", "kind": "directory"},
                {"path": "file:///workspace/new/child/value", "kind": "file"}])
            copied = await exchange(13, "fs/copy", {"sourcePath": "file:///workspace/new/child/value",
                "destinationPath": "file:///workspace/new/copied", "recursive": False, "sandbox": context()})
            self.assertEqual(copied["result"], {})
            self.assertEqual((root / "new/copied").read_bytes(), b"stdio-native-bytes")
            self.assertNotEqual((root / "new/copied").stat().st_ino, (root / "new/child/value").stat().st_ino)
            written = await exchange(14, "fs/writeFile", {"path": "file:///workspace/new/copied", "sandbox": context(),
                "dataBase64": base64.b64encode(b"patched through actual RPC").decode()})
            self.assertEqual(written["result"], {})
            self.assertEqual((root / "new/copied").read_bytes(), b"patched through actual RPC")
            removed = await exchange(15, "fs/remove", {"path": "file:///workspace/new/child/value", "sandbox": context(), "force": False})
            self.assertEqual(removed["result"], {})
            self.assertFalse((root / "new/child/value").exists())
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
    def test_native_metadata_requires_exact_types_fields_and_bounds(self):
        valid = {"isDirectory": False, "isFile": True, "isSymlink": False,
                 "size": 8, "createdAtMs": 0, "modifiedAtMs": -1235}
        self.assertEqual(_native_metadata(json.dumps(valid).encode()), valid)
        invalid = [b'[]', b'\xff', b'x' * 1025, b'{}',
            json.dumps(valid).encode() + b' trailing',
            json.dumps(valid).replace('"size": 8', '"size": 8, "size": 9').encode()]
        for key, value in (("size", -1), ("size", 2**64), ("size", True), ("size", 8.0),
                ("createdAtMs", None), ("createdAtMs", -(2**63) - 1), ("modifiedAtMs", 2**63),
                ("isDirectory", 0), ("isDirectory", True), ("isFile", False),
                ("isSymlink", True), ("unknown", False)):
            invalid.append(json.dumps({**valid, key: value}).encode())
        for output in invalid:
            with self.subTest(output=output):
                with self.assertRaises(RpcError) as raised:
                    _native_metadata(output)
                self.assertEqual(raised.exception.code, -32603)

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
