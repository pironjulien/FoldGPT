"""Nonroot PC execution of the APK's exact interpreted project and facade."""
import asyncio
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
contract = importlib.import_module("tools.executor.bionic-supervisor.runtime_qualification")
module = importlib.import_module("tools.executor.bionic-supervisor.runtime_qualification_factory")
from tools.executor.exec_server import BackendCall, RpcError, encode_message

BUILD = Path(sys.argv.pop(1)).resolve(strict=True)
SHIM = Path(sys.argv.pop(1)).resolve(strict=True)
PYTHON = str(Path(sys.executable).resolve(strict=True))
OBSERVATIONS = []


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertNotEqual(os.getuid(), 0)
        self.base = Path(tempfile.mkdtemp(prefix="foldgpt-runtime-qualification-", dir="/var/tmp"))
        self.workspace = self.base / "workspace"
        self.workspace.mkdir(mode=0o700)
        for name in ("private", ".git", "directory"):
            (self.workspace / name).mkdir(mode=0o700)
        (self.workspace / "private/secret").write_bytes(contract.SENTINEL)
        (self.workspace / "private/secret").chmod(0o600)
        self.path = self.base / "evidence.json"
        self.options = {"helper": str(BUILD / "native-files"),
            "handleHelper": str(BUILD / "native-file-handle"), "processRunner": str(BUILD / "runner"),
            "workspace": str(self.workspace), "executables": {"bash": "/usr/bin/bash"},
            "runtime": [{"path": path, "execute": execute} for path, execute in
                        (("/usr", True), ("/lib", True), ("/lib64", True), ("/etc/ld.so.cache", False))],
            "limits": dict(contract.LIMITS), "parentEnvironment": {},
            "cwdShim": {"path": str(SHIM), "sha256": hashlib.sha256(SHIM.read_bytes()).hexdigest()}}
        self.backend = self.make_backend(self.options)
        self.events, self.requests = [], []

    def make_backend(self, options):
        return module.RuntimeQualificationBackend(module.native_factory(options),
            module.open_evidence(self.path), PYTHON, sys.platform)

    async def asyncTearDown(self):
        try:
            await self.backend.close("runtime-test")
        finally:
            OBSERVATIONS.append({"test": self.id(), "evidence": str(self.path),
                                 "requests": self.requests, "events": self.events})
            print(json.dumps({"test": self.id(), "evidence": str(self.path)}), flush=True)

    async def notify(self, method, params):
        self.events.append({"method": method, "params": params})

    async def call(self, method, params):
        identity = len(self.requests) + 1
        self.requests.append({"id": identity, "method": method, "params": params})
        return await self.backend.handle(BackendCall("runtime-test", identity, method, encode_message(params)), self.notify)

    async def start(self, *, input=True):
        await self.call("process/start", contract.process_request(self.workspace, PYTHON, sys.platform))
        if input:
            self.assertEqual(await self.call("process/write", contract.input_request()), {"status": "accepted"})
        return self.backend._record

    async def collected(self):
        await asyncio.wait_for(asyncio.shield(self.backend._collector), 30)
        return json.loads(self.path.read_text())

    async def test_01_real_project_build_streams_refusals_cwd_and_file_rpc(self):
        record = await self.start()
        report = await self.collected()
        self.assertTrue(report["success"], report)
        self.assertFalse(report["androidExecution"])
        self.assertFalse(report["quarantined"])
        self.assertTrue(report["processClosed"])
        self.assertTrue(report["supervisorWaited"])
        self.assertEqual(report["supervisorPid"], record.process.pid)
        self.assertEqual(report["supervisorReturncode"], 0)
        self.assertEqual(report["worker"]["unittestCount"], 3)
        self.assertTrue(report["artifacts"]["archiveVerified"])
        await asyncio.wait_for(asyncio.shield(record.notifier), 3)
        response = await self.call("process/read", {"processId": contract.PROCESS_ID})
        self.assertTrue(response["closed"])
        self.assertEqual(response["exitCode"], 0)
        material = await self.call("fs/readFile", contract.file_request(self.workspace))
        actual = base64.b64decode(material["dataBase64"], validate=True)
        self.assertEqual(actual, base64.b64decode(report["stdoutBase64"], validate=True))
        notified = b"".join(base64.b64decode(event["params"]["chunk"], validate=True)
            for event in self.events if event["method"] == "process/output" and event["params"]["stream"] == "stdout")
        self.assertEqual(actual, notified)
        self.assertEqual(sum(item["method"] == "process/closed" for item in self.events), 1)
        # Independent material validation cannot accept a replaced build artifact.
        archive = self.workspace / "directory/dist/calculator.pyz"
        original = archive.read_bytes()
        archive.write_bytes(original + b"tampered")
        with self.assertRaisesRegex(ValueError, "identity"):
            contract.validate_artifacts(self.workspace, report["worker"])
        archive.write_bytes(original)

    async def test_02_changed_calls_refused_and_duplicate_start_not_replayed(self):
        original = contract.process_request(self.workspace, PYTHON, sys.platform)
        for key, value in (("argv", original["argv"] + ["extra"]), ("env", {}),
                           ("pipeStdin", 1), ("tty", True), ("cwd", "file:///")):
            with self.assertRaises(RpcError):
                await self.call("process/start", dict(original, **{key: value}))
        with self.assertRaises(RpcError):
            await self.call("process/write", contract.input_request())
        results = await asyncio.gather(*(self.call("process/start", original) for _ in range(2)), return_exceptions=True)
        self.assertEqual(sum(isinstance(value, RpcError) for value in results), 1)
        with self.assertRaises(RpcError):
            await self.call("fs/readFile", contract.file_request(self.workspace))
        with self.assertRaises(RpcError):
            await self.call("process/write", dict(contract.input_request(), chunk="d3Jvbmc="))
        results = await asyncio.gather(*(self.call("process/write", contract.input_request()) for _ in range(2)))
        self.assertEqual(results, [{"status": "accepted"}] * 2)
        self.assertTrue((await self.collected())["success"])
        self.assertEqual(len(self.backend.processes.processes), 1)
        with self.assertRaises(RpcError):
            await self.call("process/read", {"processId": contract.PROCESS_ID, "waitMs": 1})
        with self.assertRaises(RpcError):
            await self.call("fs/readFile", {"path": (self.workspace / "private/secret").as_uri()})

    async def test_03_missing_fixture_cannot_be_reported_as_success(self):
        (self.workspace / "directory").rmdir()
        await self.start(input=False)
        report = await self.collected()
        self.assertFalse(report["success"])
        self.assertTrue(report["supervisorWaited"])
        self.assertTrue(report["processClosed"])
        self.assertFalse(report["quarantined"])
        self.assertNotEqual(report["nativeResult"]["exitCode"], 0)
        self.assertTrue(report["stderr"])
        self.assertFalse((self.workspace / "qualification-result.json").exists())

    async def test_04_without_compatibility_library_real_chdir_remains_denied(self):
        await self.backend.close("runtime-test")
        self.path = self.base / "no-shim-evidence.json"
        self.options.pop("cwdShim")
        self.backend = self.make_backend(self.options)
        await self.start(input=False)
        report = await self.collected()
        self.assertFalse(report["success"])
        self.assertTrue(report["supervisorWaited"])
        self.assertTrue(report["processClosed"])
        self.assertFalse(report["quarantined"])
        self.assertRegex(report["stderr"], "Operation not permitted|Permission denied")
        self.assertFalse((self.workspace / "directory/project").exists())

    async def test_05_cancel_during_startup_before_rpc_stdin(self):
        await self.start(input=False)
        response = await self.call("process/terminate", {"processId": contract.PROCESS_ID})
        self.assertTrue(response["running"])
        report = await self.collected()
        self.assertFalse(report["success"])
        self.assertIsNotNone(report["nativeResult"], report)
        self.assertEqual(report["nativeResult"]["outcome"], "cancelled")
        self.assertTrue(report["supervisorWaited"])
        self.assertTrue(report["processClosed"])
        self.assertFalse(report["quarantined"])


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False).result
    report = {"schema": "foldgpt.runtime-qualification.host-tests.v1", "success": result.wasSuccessful(),
              "androidExecution": False, "observations": OBSERVATIONS}
    destination = Path(tempfile.mkdtemp(prefix="foldgpt-runtime-test-report-", dir="/var/tmp")) / "observations.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"success": result.wasSuccessful(), "observations": str(destination)}), flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 1)
