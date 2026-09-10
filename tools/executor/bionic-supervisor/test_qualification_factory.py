"""Real nonroot kernel tests for the fixed diagnostic facade; no Android run."""
import asyncio
import importlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
module = importlib.import_module("tools.executor.bionic-supervisor.qualification_factory")
from tools.executor.exec_server import BackendCall, RpcError, encode_message

BUILD = Path(sys.argv.pop(1)).resolve(strict=True)


class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertEqual(os.getuid(), 65534)
        self.base = Path(tempfile.mkdtemp(prefix="foldgpt-qualification-facade-", dir="/var/tmp"))
        self.workspace = self.base / "workspace"
        self.workspace.mkdir(mode=0o700)
        for name in ("private", ".git", "directory"):
            (self.workspace / name).mkdir(mode=0o700)
        for name, data in {"input": b"pin-memory-ok\n", "private/secret": b"probe-private-unchanged\n",
                           "directory/marker": b"marker\n"}.items():
            (self.workspace / name).write_bytes(data)
            (self.workspace / name).chmod(0o600)
        self.path = self.base / "evidence.json"
        self.options = {"helper": str(BUILD / "native-files"), "handleHelper": str(BUILD / "native-file-handle"),
            "processRunner": str(BUILD / "runner"), "workspace": str(self.workspace),
            "executables": {"kernel-qualification": str(BUILD / "qualification-worker")},
            "runtime": [{"path": path, "execute": execute} for path, execute in (
                (str(BUILD / "qualification-worker"), True), ("/usr", True), ("/lib", True),
                ("/lib64", True), ("/etc/ld.so.cache", False))], "limits": dict(module.LIMITS)}
        self.backend = module.QualificationBackend(module.native_factory(self.options), module.open_evidence(self.path))
        self.events = []
        self.sequence = 0

    async def asyncTearDown(self):
        if self.backend.processes.quarantined:
            with self.assertRaises(RpcError):
                await self.backend.close("diagnostic")
        else:
            await self.backend.close("diagnostic")
        print(json.dumps({"test": self.id(), "evidence": str(self.path)}), flush=True)

    async def notify(self, method, params):
        self.events.append({"method": method, "params": params})

    async def call(self, method, params):
        self.sequence += 1
        return await self.backend.handle(BackendCall("diagnostic", self.sequence, method, encode_message(params)), self.notify)

    async def start(self):
        await self.call("process/start", module.process_request(self.workspace))
        return self.backend._record

    async def collected(self):
        await asyncio.wait_for(asyncio.shield(self.backend._collector), 22)
        return json.loads(self.path.read_text())

    async def test_01_actual_probe_report_precedes_backend_close(self):
        record = await self.start()
        report = await self.collected()
        self.assertTrue(report["success"], report)
        self.assertEqual(report["supervisorPid"], record.process.pid)
        self.assertEqual(report["bootstrapPid"], os.getpid())
        self.assertTrue(report["bootstrapAliveDuringReport"])
        self.assertTrue(report["supervisorWaited"])
        self.assertTrue(report["processClosed"])
        self.assertEqual(report["supervisorReturncode"], 0)
        self.assertEqual(report["lifetimeScope"], "native-process-only")
        self.assertEqual(report["stderr"], "")
        self.assertFalse(self.backend.files.closed)
        self.assertFalse(report["quarantined"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        read = await self.call("process/read", {"processId": "kernel-qualification"})
        self.assertTrue(read["closed"])

    async def test_02_changed_requests_and_other_methods_never_start(self):
        original = module.process_request(self.workspace)
        for key, value in (("argv", ["kernel-qualification", "extra"]), ("env", {"HOME": "/"}),
                           ("pipeStdin", 0), ("tty", True), ("cwd", "file:///")):
            changed = dict(original, **{key: value})
            with self.assertRaises(RpcError):
                await self.call("process/start", changed)
        for method in ("fs/readFile", "fs/writeFile", "process/write", "process/signal"):
            with self.assertRaises(RpcError):
                await self.call(method, {"processId": "kernel-qualification"})
        self.assertFalse(self.backend.processes.processes)
        await self.start()
        self.assertTrue((await self.collected())["success"])

    async def test_03_duplicate_concurrent_start_is_not_replayed(self):
        params = module.process_request(self.workspace)
        replies = await asyncio.gather(*(self.call("process/start", params) for _ in range(2)), return_exceptions=True)
        self.assertEqual(sum(isinstance(reply, RpcError) for reply in replies), 1)
        self.assertEqual(sum(type(reply) is dict for reply in replies), 1)
        self.assertTrue((await self.collected())["success"])
        self.assertEqual(len(self.backend.processes.processes), 1)
        with self.assertRaises(RpcError):
            await self.call("process/read", {"processId": "kernel-qualification", "waitMs": 1})

    async def test_04_real_missing_fixture_is_failure_with_clean_owner(self):
        (self.workspace / "input").unlink()
        await self.start()
        report = await self.collected()
        self.assertFalse(report["success"])
        self.assertTrue(report["processClosed"])
        self.assertTrue(report["supervisorWaited"])
        self.assertFalse(report["quarantined"])
        self.assertEqual(report["nativeResult"]["exitCode"], 70)
        self.assertIn('"success":false', report["stdout"])

    async def test_05_final_record_with_live_owner_never_becomes_success(self):
        await self.backend.close("diagnostic")
        self.path = self.base / "fault-evidence.json"
        self.options["processRunner"] = str(BUILD / "runner-after-final-stop")
        self.options["limits"]["wall_ms"] = 1000
        self.backend = module.QualificationBackend(module.native_factory(self.options), module.open_evidence(self.path))
        record = await self.start()
        identity = os.pidfd_open(record.process.pid)
        try:
            report = await self.collected()
            self.assertFalse(report["success"])
            self.assertTrue(report["nativeResult"]["cleanupComplete"])
            self.assertFalse(report["supervisorWaited"])
            self.assertIsNone(report["supervisorReturncode"])
            self.assertTrue(report["quarantined"])
            self.assertFalse(report["processClosed"])
            self.assertTrue(self.backend.files.lock.locked())
        finally:
            # Host-only fault recovery: our pinned stopped supervisor, never Android.
            signal.pidfd_send_signal(identity, signal.SIGCONT)
            os.close(identity)
            await asyncio.wait_for(record.process.wait(), 5)
            for endpoint in record.retained_owner[3]:
                endpoint.close()
            record.command = None

    async def test_06_evidence_existing_or_aliased_target_is_refused(self):
        with self.assertRaises(FileExistsError):
            module.open_evidence(self.path)
        victim = self.base / "unchanged"
        victim.write_bytes(b"retained")
        alias = self.base / "alias.json"
        alias.symlink_to(victim)
        with self.assertRaises(FileExistsError):
            module.open_evidence(alias)
        self.assertEqual(victim.read_bytes(), b"retained")


if __name__ == "__main__":
    unittest.main(verbosity=2)
