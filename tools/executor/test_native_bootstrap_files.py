"""Actual nonroot FD/helper tests of the internal bootstrap read authority.

No Android, new RPC, model call routing, or process-workload success is claimed.
Quarantine tests explicitly inject ownership state while using the real lock.
"""
import asyncio
import base64
import importlib
import json
import os
from pathlib import Path
import pickle
import sys
import tempfile
import unittest

from tools.executor.exec_server import ExecServer, RpcError
from tools.executor.native_bootstrap_files import BootstrapReadAuthority, create_bootstrap_read_authority
from tools.executor.native_executor_backend import NativeExecutorBackend
from tools.executor.native_files import NativeFilesBackend
from tools.executor.test_policy_intent import context

HELPER = os.environ.get("FOLDGPT_NATIVE_FILES")
HANDLES = os.environ.get("FOLDGPT_NATIVE_HANDLES")
RUNNER = os.environ.get("FOLDGPT_NATIVE_RUNNER")
PAUSED = os.environ.get("FOLDGPT_PAUSED_HELPER")
BionicProcesses = importlib.import_module("tools.executor.bionic-supervisor.processes").Processes


@unittest.skipUnless(HELPER and HANDLES and RUNNER and PAUSED, "Requires actual PC native helper inputs")
class BootstrapReadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertNotEqual(os.geteuid(), 0, "Actual permission tests must run as nonroot")
        self.temporary = tempfile.TemporaryDirectory(prefix="foldgpt-bootstrap-reads-")
        self.parent = Path(self.temporary.name)
        self.workspace = self.parent / "workspace"; self.workspace.mkdir(mode=0o700)
        (self.workspace / ".codex").mkdir()
        (self.workspace / ".codex/config.toml").write_bytes(b'[features]\nexample = true\n')
        (self.workspace / "binary").write_bytes(b"\x00\xffnative\r\n")
        (self.workspace / "private").mkdir()
        (self.workspace / "private/secret").write_bytes(b"private")
        (self.parent / "outside").write_bytes(b"outside-workspace")
        def processes(runner, workspace, **options):
            return BionicProcesses(runner, workspace, executables={"bash": "/usr/bin/bash"},
                runtime=(("/usr", True), ("/lib", True), ("/lib64", True), ("/etc/ld.so.cache", False)), **options)
        self.owner = NativeExecutorBackend(HELPER, self.workspace, handle_helper=HANDLES,
            process_runner=RUNNER, process_factory=processes, guest_workspace=str(self.workspace), parent_environment={})
        self.server = ExecServer(self.owner)
        await self.server.request({"id": 1, "method": "initialize", "params": {"clientName": "bootstrap-authority-PC-test"}})
        await self.server.accept({"method": "initialized"}, self.emit)
        self.authority = create_bootstrap_read_authority(self.owner, session_id=self.server.session_id)

    async def emit(self, _): pass

    def policy(self):
        return json.loads(json.dumps(context()).replace("file:///workspace", self.workspace.as_uri()))

    async def asyncTearDown(self):
        # State-injection tests restore only their synthetic quarantine flag.
        self.owner.processes.quarantined = False
        self.owner.processes.quarantine_event.clear()
        await self.server.close()
        self.temporary.cleanup()

    async def refused(self, operation, *, missing=False):
        with self.assertRaises(RpcError) as failure:
            await operation
        self.assertEqual(failure.exception.code == -32004, missing)

    async def test_exact_binary_config_metadata_and_canonicalization(self):
        self.assertEqual(self.authority.discovery_root_uri, self.workspace.as_uri())
        self.assertEqual(await self.authority.read_file(self.workspace.as_uri() + "/binary"), b"\x00\xffnative\r\n")
        self.assertEqual(await self.authority.read_file(self.workspace.as_uri() + "/.codex/config.toml"),
            (self.workspace / ".codex/config.toml").read_bytes())
        metadata = await self.authority.get_metadata(self.workspace.as_uri() + "/binary", follow_symlinks=False)
        self.assertTrue(metadata["isFile"]); self.assertEqual(metadata["size"], 10)
        self.assertTrue((await self.authority.get_metadata(self.workspace.as_uri()))["isDirectory"])
        self.assertEqual(await self.authority.canonicalize(self.workspace.as_uri() + "/.codex"), self.workspace.as_uri() + "/.codex")

    async def test_outside_ancestor_denial_is_never_not_found(self):
        for uri in ("file:///", "file:///outside", self.workspace.as_uri() + "-other/file", self.parent.as_uri(),
                    self.workspace.as_uri() + "/../outside", self.workspace.as_uri() + "/%2e%2e/outside"):
            for method in (self.authority.read_file, self.authority.get_metadata, self.authority.canonicalize):
                await self.refused(method(uri))
        self.assertEqual((self.parent / "outside").read_bytes(), b"outside-workspace")

    async def test_missing_inside_root_retains_real_native_not_found(self):
        for method in (self.authority.read_file, self.authority.get_metadata, self.authority.canonicalize):
            await self.refused(method(self.workspace.as_uri() + "/absent"), missing=True)

    async def test_model_none_or_forged_authority_does_not_gain_bootstrap_access(self):
        for extra in ({}, {"sandbox": None}, {"bootstrapAuthority": True}, {"authority": "bootstrap"}):
            result = await self.server.request({"id": 2, "method": "fs/readFile", "params": {
                "path": self.workspace.as_uri() + "/private/secret", **extra}})
            self.assertIn("error", result)
            self.assertNotEqual(result["error"]["code"], -32004)
        result = await self.server.request({"id": 3, "method": "fs/readFile", "params": {
            "path": self.workspace.as_uri() + "/private/secret", "sandbox": self.policy()}})
        self.assertIn("error", result)
        self.assertEqual(await self.authority.read_file(self.workspace.as_uri() + "/private/secret"), b"private")
        allowed = await self.server.request({"id": 4, "method": "fs/readFile", "params": {
            "path": self.workspace.as_uri() + "/binary", "sandbox": self.policy()}})
        self.assertEqual(base64.b64decode(allowed["result"]["dataBase64"]), b"\x00\xffnative\r\n")

    async def test_no_mutation_or_serializable_authority_surface(self):
        with self.assertRaises(TypeError): BootstrapReadAuthority(None, self.owner, self.server.session_id)
        with self.assertRaises(TypeError): pickle.dumps(self.authority)
        with self.assertRaises((AttributeError, TypeError)): self.authority.discovery_root_uri = "file:///"
        for name in ("write_file", "remove", "create_directory", "copy", "handle"):
            self.assertFalse(hasattr(self.authority, name))
        with self.assertRaises(ValueError): await self.authority._read("write", self.workspace.as_uri() + "/binary")
        with self.assertRaises(ValueError): await self.authority.get_metadata(self.workspace.as_uri(), follow_symlinks=None)

    async def test_alias_hardlink_and_gitdir_remain_explicit_structural_refusals(self):
        target = self.workspace / "alias"
        target.symlink_to(self.parent / "outside")
        await self.refused(self.authority.read_file(self.workspace.as_uri() + "/alias")); target.unlink()
        os.link(self.workspace / "binary", target)
        await self.refused(self.authority.read_file(self.workspace.as_uri() + "/binary")); target.unlink()
        (self.workspace / ".git").write_text("gitdir: ../outside\n")
        await self.refused(self.authority.get_metadata(self.workspace.as_uri() + "/.git"))
        (self.workspace / ".git").unlink()

    async def test_real_file_permissions_and_shared_kernel_flock(self):
        secret = self.workspace / "private/secret"; secret.chmod(0)
        try: await self.refused(self.authority.read_file(self.workspace.as_uri() + "/private/secret"))
        finally: secret.chmod(0o600)
        with self.assertRaises(BlockingIOError): NativeFilesBackend(HELPER, self.workspace)
        self.assertEqual(os.fstat(self.owner.files.root).st_ino, self.workspace.stat().st_ino)

    async def test_reads_wait_for_actual_shared_process_lease(self):
        self.assertIs(self.owner.processes.lease, self.owner.files.lock)
        await self.owner.processes.lease.acquire()
        pending = asyncio.create_task(self.authority.read_file(self.workspace.as_uri() + "/binary"))
        try:
            await asyncio.sleep(0.05); self.assertFalse(pending.done()); self.assertIsNone(self.owner.files.process)
        finally: self.owner.processes.lease.release()
        self.assertEqual(await asyncio.wait_for(pending, 2), b"\x00\xffnative\r\n")

    async def test_injected_quarantine_cancels_pending_read_without_releasing_lease(self):
        await self.owner.processes.lease.acquire()
        try:
            pending = asyncio.create_task(self.authority.read_file(self.workspace.as_uri() + "/binary"))
            await asyncio.sleep(0.02)
            self.owner.processes.quarantined = True; self.owner.processes.quarantine_event.set()
            await self.refused(asyncio.wait_for(pending, 2))
            self.assertTrue(self.owner.files.lock.locked()); self.assertIsNone(self.owner.files.process)
            await self.refused(self.authority.read_file(self.workspace.as_uri() + "/binary"))
            with self.assertRaises(RpcError): create_bootstrap_read_authority(self.owner, session_id=self.server.session_id)
        finally: self.owner.processes.lease.release()

    async def test_repeated_cancellation_reaps_actual_native_child_before_unlock(self):
        original = self.owner.files.helper; self.owner.files.helper = PAUSED
        pending = asyncio.create_task(self.authority.read_file(self.workspace.as_uri() + "/binary"))
        try:
            for _ in range(200):
                if self.owner.files.process is not None: break
                await asyncio.sleep(0.005)
            process = self.owner.files.process; self.assertIsNotNone(process)
            self.assertTrue(self.owner.files.lock.locked())
            pending.cancel(); pending.cancel()
            with self.assertRaises(asyncio.CancelledError): await pending
            self.assertIsNotNone(process.returncode)
            self.assertFalse(Path(f"/proc/{process.pid}").exists())
            self.assertIsNone(self.owner.files.process); self.assertFalse(self.owner.files.lock.locked())
        finally:
            if not pending.done():
                pending.cancel(); await asyncio.gather(pending, return_exceptions=True)
            self.owner.files.helper = original

    async def test_closed_and_foreign_session_revoke_authority(self):
        with self.assertRaises(RpcError): create_bootstrap_read_authority(self.owner, session_id="foreign-session")
        await self.owner.close(self.server.session_id)
        await self.refused(self.authority.read_file(self.workspace.as_uri() + "/binary"))
        with self.assertRaises(RpcError): create_bootstrap_read_authority(self.owner, session_id=self.server.session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
