"""Three-owner routing unit tests and real nonroot composed PTY lifecycle tests.

Routing/capacity tests use explicit registry doubles. Factory lifecycle tests
execute the previously built real host PTY owner; no Android claim is made.
All evidence and live workspaces stay under the caller's project directory.
"""
import asyncio
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import select
import signal
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.executor.exec_server import BackendCall, RpcError, encode_message
from tools.executor.native_model_profiles import NativeModelProfiles
factory_module = importlib.import_module("tools.executor.bionic-supervisor.factory")
sys.path.insert(0, str(ROOT / "tools/executor/shizuku-service/transport/src/main/assets/foldgpt-executor"))
import foldgpt_shizuku_bootstrap as installed_bootstrap

RUNNER = Path(sys.argv.pop(1)).resolve(strict=True)
OUTPUT = Path(sys.argv.pop(1)).resolve(strict=True)
OUTPUT.relative_to(ROOT)
WORKSPACES = Path(os.environ.get("FOLDGPT_PTY_TEST_WORKSPACES", str(OUTPUT))).resolve(strict=True)
WORKSPACES.relative_to(ROOT)
OBSERVATIONS = []


def request(method="process/start", **values):
    params = {"processId": "p"}
    if method == "process/start":
        params.update(argv=["python", "-c", "pass"], cwd="file:///workspace", env={}, tty=True)
    params.update(values)
    return BackendCall("test", 1, method, encode_message(params))


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        lock = asyncio.Lock()
        files = SimpleNamespace(lock=lock, closed=False, handles={})
        def processes():
            return SimpleNamespace(files_backend=files, lease=lock, processes={}, quarantined=False,
                quarantine_event=asyncio.Event(), closing_sessions=set(), handle=AsyncMock(return_value={}))
        managed, direct, tty = processes(), processes(), processes()
        direct.quarantine_owner = tty.quarantine_owner = managed
        self.owner = SimpleNamespace(session=None, closing=False, files=files, processes=managed,
                                     _host_process_owners=[])
        self.files = SimpleNamespace(lock=lock, closed=False, handles={}, session=None)
        self.managed, self.direct, self.tty = managed, direct, tty
        self.profiles = NativeModelProfiles(self.owner, direct, self.files, tty)
        self.notify = AsyncMock()

    async def test_start_selection_and_refusal_never_retry(self):
        for values, selected in (({}, self.tty), ({"sandbox": None}, self.tty),
                                 ({"tty": False}, self.direct), ({"sandbox": {}}, self.managed)):
            for backend in self.profiles.process_backends: backend.handle.reset_mock(side_effect=True)
            selected.handle.side_effect = RpcError(-32602, "intentional selected-owner refusal")
            with self.assertRaisesRegex(RpcError, "selected-owner refusal"):
                await self.profiles.handle(request(**values), self.notify)
            for backend in self.profiles.process_backends:
                self.assertEqual(backend.handle.await_count, int(backend is selected))
            self.assertFalse(self.profiles.pending_processes)

    async def test_validation_precedes_every_profile(self):
        for fields in ({"tty": "true"}, {"ptyProcessRunner": "/outside"}, {"sandbox": False}):
            with self.assertRaises(RpcError):
                await self.profiles.handle(request(**fields), self.notify)
        self.assertTrue(all(not b.handle.called for b in self.profiles.process_backends))

    async def test_handles_route_by_registry_and_reject_ambiguity(self):
        self.tty.processes[("test", "p")] = object()
        await self.profiles.handle(request("process/read"), self.notify)
        self.tty.handle.assert_awaited_once()
        self.managed.handle.assert_not_called()
        self.direct.handle.assert_not_called()
        with self.assertRaises(RpcError):
            await self.profiles.handle(request("process/read", tty=False), self.notify)
        self.direct.processes[("test", "p")] = object()
        with self.assertRaisesRegex(RpcError, "ambiguous"):
            await self.profiles.handle(request("process/terminate"), self.notify)

    async def test_capacity_and_duplicate_ids_cover_three_registries(self):
        for index in range(128):
            backend = self.profiles.process_backends[index % 3]
            backend.processes[("test", str(index))] = object()
        with self.assertRaisesRegex(RpcError, "capacity"):
            await self.profiles.handle(request(processId="new"), self.notify)
        with self.assertRaisesRegex(RpcError, "already exists"):
            await self.profiles.handle(request(processId="2", tty=False), self.notify)
        self.assertTrue(all(not b.handle.called for b in self.profiles.process_backends))

    async def test_pending_start_reserves_all_profiles_until_cancellation(self):
        entered = asyncio.Event()
        async def waiting(*args):
            entered.set()
            await asyncio.Event().wait()
        self.tty.handle.side_effect = waiting
        task = asyncio.create_task(self.profiles.handle(request(), self.notify))
        await entered.wait()
        try:
            with self.assertRaisesRegex(RpcError, "already exists"):
                await self.profiles.handle(request(tty=False), self.notify)
            self.direct.handle.assert_not_called()
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(self.profiles.pending_processes)

    async def test_constructor_rejects_foreign_lease_live_and_shared_owners(self):
        self.tty.lease = asyncio.Lock()
        with self.assertRaisesRegex(ValueError, "lease"):
            NativeModelProfiles(self.owner, self.direct, self.files, self.tty)
        self.tty.lease = self.owner.files.lock
        self.tty.processes[("test", "old")] = object()
        with self.assertRaisesRegex(ValueError, "live"):
            NativeModelProfiles(self.owner, self.direct, self.files, self.tty)
        self.tty.processes.clear()
        self.tty.processes = self.direct.processes
        with self.assertRaisesRegex(ValueError, "separate"):
            NativeModelProfiles(self.owner, self.direct, self.files, self.tty)

    async def test_without_installed_pty_keeps_existing_direct_refusal(self):
        profiles = NativeModelProfiles(self.owner, self.direct, self.files)
        self.direct.handle.side_effect = RpcError(-32602, "PTY unsupported by pipe owner")
        with self.assertRaisesRegex(RpcError, "unsupported"):
            await profiles.handle(request(), self.notify)
        self.direct.handle.assert_awaited_once()
        self.tty.handle.assert_not_called()


class RealFactoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertNotEqual(os.getuid(), 0)
        self.workspace = WORKSPACES / self._testMethodName
        self.workspace.mkdir(mode=0o700)
        python = str(Path(sys.executable).resolve(strict=True))
        self.options = {"helper": "/usr/bin/true", "handleHelper": "/usr/bin/true",
            "processRunner": "/usr/bin/true", "workspace": str(self.workspace),
            "executables": {"python": python}, "runtime": [{"path": "/usr", "execute": True}],
            "limits": {}, "parentEnvironment": {"PATH": "/usr/bin:/bin", "HOME": str(self.workspace)},
            "ordinaryUid": {"processRunner": "/usr/bin/true", "ptyProcessRunner": str(RUNNER),
                            "limits": {"wall_ms": 15000}}}
        # The inactive managed/pipe file helpers are never invoked by these
        # real PTY tests; their selection is checked independently above.
        self.owner = factory_module.factory(self.options)
        self.tty = self.owner._model_profiles.pty_processes
        self.events, self.sequence = [], 0
        self.quarantine_expected = False

    async def asyncTearDown(self):
        if self.quarantine_expected:
            with self.assertRaises(RpcError): await self.owner.close("test")
            self.assertTrue(self.owner.files.lock.locked())
        else:
            await asyncio.wait_for(self.owner.close("test"), 20)
            self.assertTrue(self.owner.files.closed)
            self.assertTrue(self.owner._model_profiles.direct_files.closed)
            self.assertFalse(self.owner.files.lock.locked())
        OBSERVATIONS.append({"test": self.id(), "quarantined": self.owner.processes.quarantined,
                             "events": len(self.events), "filesClosed": self.owner.files.closed,
                             "workspaceUid": self.workspace.stat().st_uid,
                             "workspaceMode": oct(self.workspace.stat().st_mode & 0o777)})

    async def notify(self, method, params): self.events.append({"method": method, "params": params})

    async def call(self, method, params):
        self.sequence += 1
        return await self.owner.handle(BackendCall("test", self.sequence, method, encode_message(params)), self.notify)

    async def start(self, code, process_id="p"):
        result = await self.call("process/start", {"processId": process_id, "argv": ["python", "-I", "-B", "-c", code],
            "cwd": self.workspace.as_uri(), "env": {}, "tty": True, "pipeStdin": False})
        self.assertEqual(result, {"processId": process_id, "sandboxType": "none"})
        self.assertFalse(self.owner.processes.processes or self.owner._model_profiles.direct_processes.processes)
        return self.tty.processes[("test", process_id)]

    @staticmethod
    def output(response):
        return b"".join(base64.b64decode(c["chunk"]) for c in response["chunks"])

    async def until(self, record, marker):
        async def read():
            while True:
                response = await self.call("process/read", {"processId": record.key, "waitMs": 100})
                if marker in self.output(response): return response
                if response["closed"]: self.fail(repr(response))
        return await asyncio.wait_for(read(), 5)

    async def test_factory_tty_runs_writes_and_closes_all_three_owners(self):
        self.assertEqual(len(self.owner._model_profiles.process_backends), 3)
        self.assertIs(self.tty.lease, self.owner.files.lock)
        self.assertIs(self.tty.files_backend, self.owner.files)
        self.assertIs(self.tty.quarantine_owner, self.owner.processes)
        self.assertFalse(self.owner._host_process_owners)
        record = await self.start("import os; print('READY',flush=True); v=input(); print('GOT:'+v,flush=True)")
        await self.until(record, b"READY")
        self.assertTrue(self.owner.files.lock.locked())
        result = await self.call("process/write", {"processId": "p", "writeId": "actual-input",
            "chunk": base64.b64encode(b"model-input\n").decode()})
        self.assertEqual(result, {"status": "accepted"})
        await asyncio.wait_for(asyncio.shield(record.finished), 20)
        await asyncio.wait_for(asyncio.shield(record.notifier), 5)
        result = await self.call("process/read", {"processId": "p"})
        self.assertIn(b"GOT:model-input", self.output(result))
        self.assertTrue(all(chunk["stream"] == "pty" for chunk in result["chunks"]))
        self.assertEqual(result["exitCode"], 0)
        self.assertTrue(record.native_result["cleanupComplete"])
        self.assertEqual(record.process.returncode, 0)
        await self.owner.close("test")
        self.assertTrue(all("test" in b.closing_sessions and not b.processes
                            for b in self.owner._model_profiles.process_backends))
        OBSERVATIONS.append({"test": self.id(), "nativeResult": record.native_result})

    async def test_close_waits_for_active_tty_and_refuses_later_files(self):
        record = await self.start("import time; print('READY',flush=True); time.sleep(100)")
        await self.until(record, b"READY")
        await asyncio.wait_for(self.owner.close("test"), 20)
        self.assertTrue(record.closed and record.native_result["cleanupComplete"])
        self.assertEqual(record.process.returncode, 0)
        with self.assertRaises(RpcError):
            await self.call("fs/readFile", {"path": (self.workspace / "anything").as_uri()})

    async def test_no_public_human_or_resize_authority(self):
        self.assertNotIn("process/spawn", self.owner.supported_methods)
        self.assertNotIn("process/resizePty", self.owner.supported_methods)
        for method in ("process/spawn", "process/resizePty"):
            with self.assertRaises(RpcError): await self.call(method, {})
        self.assertFalse(self.tty.processes)

    async def test_constructor_bad_pty_does_not_retain_root_or_lease(self):
        await self.owner.close("test")
        before = len(os.listdir("/proc/self/fd"))
        invalid = {**self.options, "ordinaryUid": {**self.options["ordinaryUid"], "ptyProcessRunner": "/missing/runner"}}
        with self.assertRaises(FileNotFoundError): factory_module.factory(invalid)
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)
        self.owner = factory_module.factory(self.options)
        self.tty = self.owner._model_profiles.pty_processes

    async def test_actual_owner_loss_quarantines_shared_filesystem(self):
        record = await self.start("import os,time; print(str(os.getpid())+' READY',flush=True); time.sleep(100)")
        response = await self.until(record, b"READY")
        child = os.pidfd_open(int(self.output(response).split()[0]), 0)
        owner = os.pidfd_open(record.process.pid, 0)
        pending = asyncio.create_task(self.call("fs/writeFile", {
            "path": (self.workspace / "must-not-write").as_uri(), "dataBase64": "YmFk"}))
        self.quarantine_expected = True
        try:
            await asyncio.sleep(0)
            signal.pidfd_send_signal(owner, signal.SIGKILL)
            await asyncio.wait_for(asyncio.shield(record.finished), 15)
            with self.assertRaises(RpcError): await asyncio.wait_for(pending, 5)
            self.assertTrue(self.owner.processes.quarantined and self.tty.quarantined)
            self.assertTrue(self.owner.processes.quarantine_event.is_set())
            self.assertTrue(self.owner.files.lock.locked())
            self.assertFalse((self.workspace / "must-not-write").exists())
            self.assertTrue(select.select([child], [], [], 5)[0])
        finally:
            os.close(child)
            os.close(owner)
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


class BootstrapTests(unittest.TestCase):
    """Actual library bytes/hash checks with an explicit mocked installed identity."""
    def setUp(self):
        self.directory = WORKSPACES / self._testMethodName
        self.directory.mkdir(mode=0o700)
        self.names = ("libfoldgpt_python_cli.so", "libfoldgpt_direct_runner.so", "libfoldgpt_direct_pty_supervisor.so")
        self.libraries = {}
        for name in self.names:
            data = RUNNER.read_bytes()
            path = self.directory / name
            path.write_bytes(data)
            path.chmod(0o644)
            self.libraries[name] = hashlib.sha256(data).hexdigest()
        marker = "@nativeLibraryDir/"
        self.config = {"pythonLibrary": self.names[0], "pythonSha256": self.libraries[self.names[0]],
            "nativeLibraries": self.libraries,
            "backendOptions": {"helper": marker + self.names[0], "handleHelper": marker + self.names[0],
                "processRunner": marker + self.names[0], "executables": {"python": marker + self.names[0]},
                "runtime": [], "ordinaryUid": {"processRunner": marker + self.names[1], "limits": {},
                                              "ptyProcessRunner": marker + self.names[2]}}}

    def resolve(self):
        executable = str(self.directory / self.names[0])
        # Identity is a unit-test fixture; verify_library still reads actual,
        # immutable local ELF bytes through O_NOFOLLOW and checks their hashes.
        with patch.object(installed_bootstrap.os, "readlink", return_value=executable), \
                patch.object(installed_bootstrap.sys, "executable", executable):
            return installed_bootstrap.installed_backend_options(self.config)

    def test_pty_marker_resolves_only_exact_attested_native_bytes(self):
        actual = self.resolve()["ordinaryUid"]
        self.assertEqual(actual["ptyProcessRunner"], str(self.directory / self.names[2]))
        self.assertEqual(actual["processRunner"], str(self.directory / self.names[1]))

    def test_changed_pty_elf_hash_is_rejected(self):
        (self.directory / self.names[2]).write_bytes(b"changed")
        with self.assertRaises(ValueError): self.resolve()

    def test_external_pty_path_and_unknown_option_are_rejected(self):
        self.config["backendOptions"]["ordinaryUid"]["ptyProcessRunner"] = "/usr/bin/true"
        with self.assertRaises(ValueError): self.resolve()
        self.config["backendOptions"]["ordinaryUid"]["ptyProcessRunner"] = "@nativeLibraryDir/" + self.names[2]
        self.config["backendOptions"]["ordinaryUid"]["ttyRunner"] = self.names[2]
        with self.assertRaises(ValueError): self.resolve()

    def test_pipe_only_bootstrap_contract_remains_supported(self):
        del self.config["backendOptions"]["ordinaryUid"]["ptyProcessRunner"]
        self.assertEqual(set(self.resolve()["ordinaryUid"]), {"processRunner", "limits"})


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False).result
    report = {"schema": "foldgpt.model-pty-composition-tests.v1", "passed": result.wasSuccessful() and not result.skipped,
        "tests": result.testsRun, "uid": os.getuid(), "androidExecuted": False,
        "routingTestsUseRegistryDoubles": True, "factoryTestsUseRealPtyOwner": True,
        "bootstrapTestsMockIdentityAndReadRealFiles": True,
        "runnerSha256": hashlib.sha256(RUNNER.read_bytes()).hexdigest(), "observations": OBSERVATIONS,
        "errors": [[test.id(), value] for test, value in result.errors],
        "failures": [[test.id(), value] for test, value in result.failures]}
    (OUTPUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "tests": result.testsRun, "report": str(OUTPUT / "report.json")}))
    raise SystemExit(0 if report["passed"] else 1)
