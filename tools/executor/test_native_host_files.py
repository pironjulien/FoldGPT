"""Real nonroot helper/lifecycle tests of the separate host file capability."""
import asyncio
import base64
import importlib
import json
import os
from pathlib import Path
import pickle
import stat
import tempfile
import unittest

from tools.executor.exec_server import ExecServer, RpcError
from tools.executor.native_bootstrap_files import create_bootstrap_read_authority
from tools.executor.native_executor_backend import NativeExecutorBackend
from tools.executor.native_files import MAX_DATA, NativeFilesBackend
from tools.executor.native_host_files import HostFileAuthority, create_host_file_authority
from tools.executor.test_policy_intent import context

HELPER = os.environ.get("FOLDGPT_NATIVE_FILES")
HANDLES = os.environ.get("FOLDGPT_NATIVE_HANDLES")
RUNNER = os.environ.get("FOLDGPT_NATIVE_RUNNER")
PAUSED = os.environ.get("FOLDGPT_PAUSED_HELPER")
BIONIC = importlib.import_module("tools.executor.bionic-supervisor.processes")
OBSERVATIONS = []


class HostFileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertTrue(HELPER and HANDLES and RUNNER and PAUSED, "Actual helper inputs required, no simulated fallback")
        self.assertNotEqual(os.geteuid(), 0, "Run actual permission tests as nonroot")
        self.temp = tempfile.TemporaryDirectory(prefix="foldgpt-host-files-", dir="/var/tmp")
        self.parent = Path(self.temp.name)
        self.workspace = self.parent / "workspace"
        self.workspace.mkdir(mode=0o700)
        for name in ("private", ".git", ".agents"):
            (self.workspace / name).mkdir(mode=0o700)
        (self.workspace / "private/secret").write_bytes(b"private")
        (self.workspace / "existing").write_bytes(b"old value")
        (self.parent / "outside").write_bytes(b"outside unchanged")
        def processes(runner, workspace, **options):
            return BIONIC.Processes(runner, workspace, executables={"bash": "/usr/bin/bash"},
                runtime=(("/usr", True), ("/lib", True), ("/lib64", True), ("/etc/ld.so.cache", False)), **options)
        self.owner = NativeExecutorBackend(HELPER, self.workspace, handle_helper=HANDLES,
            process_runner=RUNNER, process_factory=processes, guest_workspace=str(self.workspace),
            limits=BIONIC.Limits(wall_ms=10000, output_bytes=32768), parent_environment={})
        self.server = ExecServer(self.owner)
        await self.server.request({"id": 1, "method": "initialize", "params": {"clientName": "host-file-authority-PC-test"}})
        await self.server.accept({"method": "initialized"}, self.emit)
        self.authority = create_host_file_authority(self.owner, session_id=self.server.session_id)

    async def emit(self, _):
        pass

    def uri(self, name=""):
        return (self.workspace / name).as_uri()

    def policy(self):
        return json.loads(json.dumps(context()).replace("file:///workspace", self.workspace.as_uri()))

    async def model(self, method, path, **extra):
        return await self.server.request({"id": 2, "method": method,
            "params": {"path": self.uri(path), **extra}})

    async def asyncTearDown(self):
        self.owner.processes.quarantined = False
        self.owner.processes.quarantine_event.clear()
        await self.server.close()
        OBSERVATIONS.append({"test": self.id(), "filesClosed": self.owner.files.closed,
            "fileHelperReaped": self.owner.files.process is None, "quarantined": self.owner.processes.quarantined})
        self.temp.cleanup()

    async def refused(self, operation, *, missing=False):
        with self.assertRaises(RpcError) as caught:
            await operation
        self.assertEqual(caught.exception.code == -32004, missing)

    async def test_exact_binary_create_overwrite_metadata_and_empty_write(self):
        data = bytes(range(256)) * 513 + "écriture\n".encode()
        self.assertIsNone(await self.authority.write_file(self.uri("created"), data))
        self.assertEqual((self.workspace / "created").read_bytes(), data)
        self.assertEqual(await self.authority.read_file(self.uri("created")), data)
        self.assertEqual(stat.S_IMODE((self.workspace / "created").stat().st_mode), 0o600)
        await self.authority.write_file(self.uri("existing"), b"\x00\xff")
        self.assertEqual((self.workspace / "existing").read_bytes(), b"\x00\xff")
        metadata = await self.authority.get_metadata(self.uri("existing"), follow_symlinks=False)
        actual = (self.workspace / "existing").stat()
        self.assertEqual({key: metadata[key] for key in ("isDirectory", "isFile", "isSymlink", "size", "modifiedAtMs")},
            {"isDirectory": False, "isFile": True, "isSymlink": False, "size": 2,
             "modifiedAtMs": actual.st_mtime_ns // 1000000})
        await self.authority.write_file(self.uri("existing"), b"")
        self.assertEqual(await self.authority.read_file(self.uri("existing")), b"")

    async def test_directory_creation_and_exact_native_listing(self):
        self.assertIsNone(await self.authority.create_directory(self.uri("project/nested")))
        await self.authority.create_directory(self.uri("project/nested"))
        await self.authority.create_directory(self.uri("project/single"), recursive=False)
        names = ["é.py", "space file", "hash#percent%.py", "plain.py"]
        for name in names:
            await self.authority.write_file(self.uri("project/" + name), name.encode())
        self.assertEqual(await self.authority.read_directory(self.uri("project")), {"entries": [
            {"fileName": name, "isDirectory": name in {"nested", "single"}, "isFile": name not in {"nested", "single"}}
            for name in sorted([*names, "nested", "single"], key=lambda name: name.encode())]})
        self.assertEqual(await self.authority.read_directory(self.uri("project/nested")), {"entries": []})
        self.assertTrue((await self.authority.get_metadata(self.uri()))["isDirectory"])
        self.assertIsNone(await self.authority.create_directory(self.uri()))
        await self.refused(self.authority.create_directory(self.uri(), recursive=False))
        self.assertEqual(stat.S_IMODE((self.workspace / "project/nested").stat().st_mode), 0o700)
        await self.refused(self.authority.create_directory(self.uri("project/single"), recursive=False))
        await self.refused(self.authority.create_directory(self.uri("missing/child"), recursive=False), missing=True)
        self.assertFalse((self.workspace / "missing").exists())
        await self.refused(self.authority.create_directory(self.uri("existing/child")))
        self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")

    async def test_real_missing_lookups_are_distinct_from_outside_denials(self):
        for method in (self.authority.read_file, self.authority.get_metadata, self.authority.read_directory,
                       self.authority.canonicalize):
            await self.refused(method(self.uri("absent")), missing=True)
        await self.refused(self.authority.write_file(self.uri("absent/child"), b"value"), missing=True)
        for uri in (self.parent.as_uri(), "file:///", self.uri() + "-other/absent",
                    self.uri() + "/../outside", self.uri() + "/%2e%2e/outside"):
            for method in (self.authority.read_file, self.authority.get_metadata,
                           self.authority.read_directory, self.authority.create_directory):
                await self.refused(method(uri))
            await self.refused(self.authority.write_file(uri, b"bad"))
        await self.refused(self.authority.write_file(self.uri(), b"bad"))
        self.assertEqual((self.parent / "outside").read_bytes(), b"outside unchanged")

    async def test_human_rights_do_not_change_model_or_bootstrap_authority(self):
        bootstrap = create_bootstrap_read_authority(self.owner, session_id=self.server.session_id)
        for path in ("private/secret", ".git/config", ".agents/rules"):
            self.assertIn("error", await self.model("fs/writeFile", path,
                dataBase64="YmFk", sandbox=self.policy()))
            await self.authority.write_file(self.uri(path), b"human edit")
            self.assertEqual(await self.authority.read_file(self.uri(path)), b"human edit")
            self.assertIn("error", await self.model("fs/writeFile", path,
                dataBase64="YmFk", sandbox=self.policy()))
            self.assertEqual((self.workspace / path).read_bytes(), b"human edit")
        for extra in ({}, {"sandbox": None}, {"authority": "host"}, {"hostAuthority": True}):
            for method, payload in (("fs/readFile", {}), ("fs/writeFile", {"dataBase64": "YmFk"})):
                self.assertIn("error", await self.model(method, "private/secret", **payload, **extra))
        self.assertIn("error", await self.model("fs/readFile", "private/secret", sandbox=self.policy()))
        self.assertEqual(await bootstrap.read_file(self.uri("private/secret")), b"human edit")
        self.assertFalse(hasattr(bootstrap, "write_file"))
        self.assertEqual(self.authority.workspace_root_uri, self.uri())

    async def test_capability_is_immutable_private_and_not_serializable(self):
        with self.assertRaises(TypeError): HostFileAuthority(None, self.owner, self.server.session_id)
        with self.assertRaises(TypeError): pickle.dumps(self.authority)
        with self.assertRaises((AttributeError, TypeError)): self.authority.workspace_root_uri = "file:///"
        for name in ("handle", "remove", "copy"):
            self.assertFalse(hasattr(self.authority, name))
        with self.assertRaises(ValueError): await self.authority._operate("remove", self.uri("existing"))
        with self.assertRaises(ValueError): await self.authority.get_metadata(self.uri(), follow_symlinks=1)
        with self.assertRaises(ValueError): await self.authority.create_directory(self.uri(), recursive=None)

    async def test_invalid_and_oversized_data_refuses_before_opening_destination(self):
        for data in (bytearray(b"mutable"), "not bytes", None, b"x" * (MAX_DATA + 1)):
            await self.refused(self.authority.write_file(self.uri("existing"), data))
            self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")
        await self.refused(self.authority.write_file(self.uri("nested/.git"), b"gitdir: ../other"))
        await self.refused(self.authority.create_directory(self.uri("/".join(["nested"] * 65))))
        self.assertFalse((self.workspace / "nested").exists())

    async def test_control_character_uris_refuse_before_any_mutation(self):
        before = sorted(path.name for path in self.workspace.iterdir())
        for name in ("newline\nfile", "tab\tfile", "null\0file"):
            uri = self.uri(name)
            for method in (self.authority.read_file, self.authority.get_metadata,
                           self.authority.read_directory, self.authority.create_directory):
                await self.refused(method(uri))
            await self.refused(self.authority.write_file(uri, b"bad"))
        self.assertEqual(sorted(path.name for path in self.workspace.iterdir()), before)
        self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")

    async def test_alias_hardlink_and_special_file_refusals_preserve_targets(self):
        alias = self.workspace / "alias"
        mutations = (lambda: alias.symlink_to(self.parent / "outside"),
                     lambda: os.link(self.workspace / "existing", alias),
                     lambda: os.mkfifo(alias))
        for create in mutations:
            create()
            try:
                await self.refused(self.authority.write_file(self.uri("existing"), b"bad"))
                await self.refused(self.authority.read_directory(self.uri()))
            finally: alias.unlink()
        self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")
        self.assertEqual((self.parent / "outside").read_bytes(), b"outside unchanged")

    async def test_actual_file_permissions_and_existing_flock_remain_enforced(self):
        target = self.workspace / "existing"
        target.chmod(0o400)
        try:
            await self.refused(self.authority.write_file(self.uri("existing"), b"bad"))
            self.assertEqual(await self.authority.read_file(self.uri("existing")), b"old value")
        finally: target.chmod(0o600)
        with self.assertRaises(BlockingIOError): NativeFilesBackend(HELPER, self.workspace)
        self.assertEqual(os.fstat(self.owner.files.root).st_ino, self.workspace.stat().st_ino)

    async def test_unknown_process_cleanup_revokes_waiting_host_mutation(self):
        await self.owner.processes.lease.acquire()
        try:
            pending = asyncio.create_task(self.authority.write_file(self.uri("existing"), b"bad"))
            await asyncio.sleep(0.02)
            self.owner.processes.quarantined = True
            self.owner.processes.quarantine_event.set()
            await self.refused(asyncio.wait_for(pending, 2))
            self.assertTrue(self.owner.files.lock.locked())
            self.assertIsNone(self.owner.files.process)
            await self.refused(self.authority.write_file(self.uri("existing"), b"bad"))
            with self.assertRaises(RpcError): create_host_file_authority(self.owner, session_id=self.server.session_id)
        finally: self.owner.processes.lease.release()
        self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")

    async def test_repeated_cancellation_reaps_real_helper_before_unlocking(self):
        original = self.owner.files.helper
        self.owner.files.helper = PAUSED
        pending = asyncio.create_task(self.authority.write_file(self.uri("existing"), b"cancelled"))
        try:
            for _ in range(200):
                if self.owner.files.process is not None: break
                await asyncio.sleep(0.005)
            process = self.owner.files.process
            self.assertIsNotNone(process)
            self.assertTrue(self.owner.files.lock.locked())
            pending.cancel(); pending.cancel()
            with self.assertRaises(asyncio.CancelledError): await pending
            self.assertIsNotNone(process.returncode)
            self.assertFalse(Path(f"/proc/{process.pid}").exists())
            self.assertIsNone(self.owner.files.process)
            self.assertFalse(self.owner.files.lock.locked())
        finally:
            if not pending.done():
                pending.cancel(); await asyncio.gather(pending, return_exceptions=True)
            self.owner.files.helper = original
        self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")

    async def test_real_worker_lease_delays_host_write_until_native_cleanup(self):
        params = {"processId": "worker", "argv": ["bash", "--noprofile", "--norc", "-c", "printf READY; read value"],
            "cwd": self.uri(), "env": {"PATH": "/usr/bin:/bin", "HOME": str(self.workspace)},
            "tty": False, "pipeStdin": True, "sandbox": self.policy()}
        reply = await self.server.request({"id": 3, "method": "process/start", "params": params})
        self.assertIn("result", reply, reply)
        record = self.owner.processes.processes[(self.server.session_id, "worker")]
        try:
            for _ in range(100):
                output = b"".join(base64.b64decode(chunk["chunk"]) for chunk, _ in record.output if chunk["stream"] == "stdout")
                if b"READY" in output: break
                await asyncio.sleep(0.01)
            self.assertIn(b"READY", output)
            pending = asyncio.create_task(self.authority.write_file(self.uri("existing"), b"after cleanup"))
            await asyncio.sleep(0.03)
            self.assertFalse(pending.done())
            self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")
            result = await self.server.request({"id": 4, "method": "process/terminate", "params": {"processId": "worker"}})
            self.assertIn("result", result)
            self.assertIsNone(await asyncio.wait_for(pending, 5))
            await asyncio.wait_for(asyncio.shield(record.finished), 5)
            self.assertTrue(record.native_result["cleanupComplete"], record.native_result)
            self.assertEqual(record.native_result["outcome"], "cancelled")
            self.assertIsNotNone(record.process.returncode)
            self.assertFalse(Path(f"/proc/{record.process.pid}").exists())
            self.assertEqual((self.workspace / "existing").read_bytes(), b"after cleanup")
            OBSERVATIONS.append({"test": self.id(), "nativeResult": record.native_result,
                "supervisorReturncode": record.process.returncode})
        finally:
            if not record.finished.done():
                await self.server.request({"id": 5, "method": "process/terminate", "params": {"processId": "worker"}})

    async def test_closed_and_foreign_sessions_revoke_host_capability(self):
        with self.assertRaises(RpcError): create_host_file_authority(self.owner, session_id="foreign")
        await self.owner.close(self.server.session_id)
        await self.refused(self.authority.write_file(self.uri("existing"), b"bad"))
        with self.assertRaises(RpcError): create_host_file_authority(self.owner, session_id=self.server.session_id)
        self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")

    async def test_root_descriptor_number_and_inode_cannot_be_replaced(self):
        original = self.owner.files.root
        retained = os.dup(original)
        outside = os.open(self.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            self.owner.files.root = retained
            await self.refused(self.authority.write_file(self.uri("existing"), b"bad"))
            self.owner.files.root = original
            os.dup2(outside, original)
            await self.refused(self.authority.write_file(self.uri("outside"), b"bad"))
            self.assertIsNone(self.owner.files.process)
            self.assertEqual((self.parent / "outside").read_bytes(), b"outside unchanged")
        finally:
            os.dup2(retained, original)
            self.owner.files.root = original
            os.close(retained)
            os.close(outside)
        self.assertEqual(await self.authority.read_file(self.uri("existing")), b"old value")

    async def test_close_waits_for_actual_helper_reaping(self):
        original = self.owner.files.helper
        self.owner.files.helper = PAUSED
        pending = asyncio.create_task(self.authority.write_file(self.uri("existing"), b"cancelled"))
        closing = None
        try:
            for _ in range(200):
                if self.owner.files.process is not None: break
                await asyncio.sleep(0.005)
            process = self.owner.files.process
            self.assertIsNotNone(process)
            closing = asyncio.create_task(self.owner.close(self.server.session_id))
            await asyncio.sleep(0.02)
            self.assertFalse(closing.done())
            self.assertFalse(self.owner.files.closed)
            self.assertTrue(self.owner.files.lock.locked())
            self.assertIsNone(process.returncode)
            pending.cancel(); pending.cancel()
            with self.assertRaises(asyncio.CancelledError): await pending
            await asyncio.wait_for(closing, 2)
            self.assertTrue(self.owner.files.closed)
            self.assertIsNone(self.owner.files.process)
            self.assertIsNotNone(process.returncode)
            self.assertFalse(Path(f"/proc/{process.pid}").exists())
            with self.assertRaises(OSError): os.fstat(self.owner.files.root)
        finally:
            if not pending.done():
                pending.cancel(); await asyncio.gather(pending, return_exceptions=True)
            if closing is not None: await closing
            self.owner.files.helper = original
        self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        output = os.environ.get("FOLDGPT_HOST_FILE_OBSERVATIONS")
        if output:
            Path(output).write_text(json.dumps({"uid": os.getuid(), "observations": OBSERVATIONS}, indent=2) + "\n")
