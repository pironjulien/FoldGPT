"""Real nonroot Linux composition checks of managed and ordinary model profiles.

Pass the frozen native helper build and an evidence directory beneath the project.
No mock process/file backend, policy fallback, device, or upstream engine is used.
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
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
factory = importlib.import_module("tools.executor.bionic-supervisor.factory").factory
kernel = importlib.import_module("tools.executor.bionic-supervisor.test_kernel")
from tools.executor.exec_server import BackendCall, RpcError, encode_message

BUILD = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
EVIDENCE = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
OBSERVATIONS = []


class ModelProfileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertEqual(sys.platform, "linux", "Actual Linux kernel required")
        self.assertNotEqual(os.getuid(), 0)
        self.assertIsNotNone(BUILD)
        self.assertIsNotNone(EVIDENCE)
        self.base = Path(tempfile.mkdtemp(prefix="model-profiles-", dir=EVIDENCE))
        self.workspace = self.base / "workspace"
        self.workspace.mkdir(mode=0o700)
        (self.workspace / "private").mkdir(mode=0o700)
        (self.workspace / "private/secret").write_bytes(b"original-private")
        (self.workspace / "value").write_bytes(b"actual-model-file")
        self.options = {"helper": str(BUILD / "native-files"), "handleHelper": str(BUILD / "native-file-handle"),
            "processRunner": str(BUILD / "runner"), "workspace": str(self.workspace),
            "executables": {"bash": str(Path("/usr/bin/bash").resolve()), "python": str(Path(sys.executable).resolve())},
            "runtime": [{"path": p, "execute": executable} for p, executable in
                (("/usr", True), ("/lib", True), ("/lib64", True), ("/etc/ld.so.cache", False))],
            "limits": {"wall_ms": 3000},
            "parentEnvironment": {"PATH": "/usr/bin:/bin", "HOME": str(self.workspace)},
            "ordinaryUid": {"processRunner": str(BUILD / "direct-runner"), "limits": {"wall_ms": 15000}}}
        self.owner = factory(self.options)
        self.profiles = self.owner._model_profiles
        self.direct = self.profiles.direct_processes
        self.direct_files = self.profiles.direct_files
        self.events, self.sequence = [], 0
        self.expected_quarantine = False

    async def asyncTearDown(self):
        self.assertEqual(self.owner.processes.quarantined, self.expected_quarantine)
        if self.expected_quarantine:
            with self.assertRaises(RpcError):
                await self.owner.close("test")
        else:
            await asyncio.wait_for(self.owner.close("test"), 20)
            self.assertTrue(self.owner.files.closed and self.direct_files.closed)
        OBSERVATIONS.append({"test": self.id(), "workspace": str(self.workspace),
            "events": len(self.events), "quarantined": self.owner.processes.quarantined})

    async def notify(self, method, params):
        self.events.append({"method": method, "params": params})

    async def call(self, method, params, *, session="test"):
        self.sequence += 1
        return await self.owner.handle(BackendCall(session, self.sequence, method, encode_message(params)), self.notify)

    def params(self, key, command, *, managed=False, **extra):
        params = {"processId": key, "argv": ["bash", "--noprofile", "--norc", "-c", command],
            "cwd": self.workspace.as_uri(), "env": {}, "tty": False, **extra}
        if managed:
            params["sandbox"] = kernel.context(self.workspace)
        return params

    async def start(self, key, command, *, managed=False, **extra):
        result = await self.call("process/start", self.params(key, command, managed=managed, **extra))
        backend = self.owner.processes if managed else self.direct
        self.assertIn(("test", key), backend.processes)
        other = self.direct if managed else self.owner.processes
        self.assertNotIn(("test", key), other.processes)
        if not managed:
            self.assertEqual(result["sandboxType"], "none")
        return backend.processes[("test", key)]

    @staticmethod
    def output(response):
        return b"".join(base64.b64decode(chunk["chunk"]) for chunk in response["chunks"] if chunk["stream"] == "stdout")

    async def complete(self, record):
        await asyncio.wait_for(asyncio.shield(record.finished), 20)
        await asyncio.wait_for(asyncio.shield(record.notifier), 5)
        response = await self.call("process/read", {"processId": record.key})
        self.assertTrue(response["closed"] and response["exited"], response)
        self.assertTrue(record.native_result["cleanupComplete"], record.native_result)
        return response

    async def until(self, record, marker):
        async def observe():
            while True:
                response = await self.call("process/read", {"processId": record.key, "waitMs": 100})
                if marker in self.output(response):
                    return response
                if response["closed"]:
                    self.fail("Process ended without readiness: " + repr(response))
        return await asyncio.wait_for(observe(), 5)

    async def wait_predicate(self, predicate):
        async def observe():
            while not predicate():
                await asyncio.sleep(0)
        await asyncio.wait_for(observe(), 5)

    def file_params(self, identifier, *, managed=False, path=None):
        params = {"handleId": identifier, "path": (path or self.workspace / "value").as_uri()}
        if managed:
            params["sandbox"] = kernel.context(self.workspace)
        return params

    async def test_01_factory_installs_exact_shared_owner_without_human_authority(self):
        self.assertIs(self.direct.files_backend, self.owner.files)
        self.assertIs(self.direct.lease, self.owner.files.lock)
        self.assertIs(self.direct_files.lock, self.owner.files.lock)
        self.assertIs(self.direct.quarantine_owner, self.owner.processes)
        self.assertFalse(self.owner._host_process_owners)
        with self.assertRaises(ValueError):
            self.owner.install_ordinary_uid_profile(self.direct, self.direct_files)
        before = len(os.listdir("/proc/self/fd"))
        for value in (None, {}, {"processRunner": str(BUILD / "direct-runner"), "limits": {}, "extra": True}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                factory({**self.options, "ordinaryUid": value})
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    async def test_02_direct_and_managed_processes_use_distinct_native_paths(self):
        direct = await self.start("direct", "printf direct; printf full > private/secret")
        response = await self.complete(direct)
        self.assertEqual(self.output(response), b"direct")
        self.assertEqual((self.workspace / "private/secret").read_bytes(), b"full")
        managed = await self.start("managed", "printf managed; printf forbidden > private/secret; exit 0", managed=True)
        response = await self.complete(managed)
        self.assertEqual(self.output(response), b"managed")
        self.assertEqual((self.workspace / "private/secret").read_bytes(), b"full")
        self.assertGreaterEqual(managed.native_result["denials"], 1)
        self.assertFalse(self.owner.files.lock.locked())

    async def test_03_file_read_handles_are_immutable_across_profiles(self):
        await self.call("fs/open", self.file_params("direct"))
        await self.call("fs/open", self.file_params("managed", managed=True))
        self.assertIn("direct", self.direct_files.handles)
        self.assertIn("managed", self.owner.files.handles)
        descriptors = [self.direct_files.handles["direct"].fd, self.owner.files.handles["managed"].fd]
        for identifier in ("direct", "managed"):
            response = await self.call("fs/readBlock", {"handleId": identifier, "offset": 0, "len": 128})
            self.assertEqual(base64.b64decode(response["chunk"]), b"actual-model-file")
            with self.assertRaises(RpcError):
                await self.call("fs/readBlock", {"handleId": identifier, "offset": 0, "len": 1,
                    "sandbox": {"permissions": {"type": "disabled"}, "windowsSandboxLevel": "disabled"}})
            with self.assertRaises(RpcError):
                await self.call("fs/readBlock", {"handleId": identifier, "offset": 0, "len": 1}, session="other")
        for identifier in ("direct", "managed"):
            await self.call("fs/close", {"handleId": identifier})
        for descriptor in descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        self.assertEqual(await self.call("fs/close", {"handleId": "unknown"}), {})
        with self.assertRaises(RpcError):
            await self.call("fs/close", {"handleId": "é" * 17})

    async def test_04_cross_profile_file_collisions_and_shared_limit(self):
        await self.call("fs/open", self.file_params("collision"))
        with self.assertRaises(RpcError):
            await self.call("fs/open", self.file_params("collision", managed=True))
        await self.call("fs/close", {"handleId": "collision"})
        await self.call("fs/open", self.file_params("collision", managed=True))
        with self.assertRaises(RpcError):
            await self.call("fs/open", self.file_params("collision"))
        for index in range(127):
            await self.call("fs/open", self.file_params("direct-" + str(index)))
        with self.assertRaises(RpcError):
            await self.call("fs/open", self.file_params("over-capacity", managed=True))
        self.assertEqual(len(self.direct_files.handles) + len(self.owner.files.handles), 128)

    async def test_05_pending_file_reservation_cancellation_releases_only_new_acquisition(self):
        await self.owner.files.lock.acquire()
        pending = asyncio.create_task(self.call("fs/open", self.file_params("pending")))
        try:
            await self.wait_predicate(lambda: "pending" in self.profiles.pending_files)
            with self.assertRaises(RpcError):
                await self.call("fs/open", self.file_params("pending", managed=True))
            with self.assertRaises(RpcError):
                await self.call("fs/close", {"handleId": "pending"})
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertFalse(self.profiles.pending_files)
            self.assertFalse(self.direct_files.handles or self.owner.files.handles)
            self.assertTrue(self.owner.files.lock.locked())
        finally:
            self.owner.files.lock.release()
        await self.call("fs/open", self.file_params("pending", managed=True))
        self.assertIn("pending", self.owner.files.handles)

    async def test_06_process_id_collision_and_lifecycle_cannot_change_mode_or_session(self):
        record = await self.start("same", "printf READY; /usr/bin/sleep 100")
        await self.until(record, b"READY")
        with self.assertRaises(RpcError):
            await self.call("process/start", self.params("same", "printf must-not-run", managed=True))
        with self.assertRaises(RpcError):
            await self.call("process/terminate", {"processId": "same"}, session="other")
        with self.assertRaises(RpcError):
            await self.call("process/terminate", {"processId": "same", "sandbox": kernel.context(self.workspace)})
        self.assertFalse(record.finished.done())
        await self.call("process/terminate", {"processId": "same"})
        await self.complete(record)
        self.assertNotIn(("test", "same"), self.owner.processes.processes)

    async def test_07_pending_process_reservation_and_cancel_before_actual_spawn(self):
        await self.owner.files.lock.acquire()
        pending = asyncio.create_task(self.call("process/start", self.params("pending", "printf bad > marker")))
        try:
            await self.wait_predicate(lambda: ("test", "pending") in self.direct.processes)
            with self.assertRaises(RpcError):
                await self.call("process/start", self.params("pending", "printf bad > marker", managed=True))
            record = self.direct.processes[("test", "pending")]
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertIsNone(record.process)
            self.assertTrue(record.closed)
            self.assertFalse(self.profiles.pending_processes)
            self.assertFalse((self.workspace / "marker").exists())
        finally:
            self.owner.files.lock.release()

    async def test_08_malformed_and_denied_requests_never_retry_direct(self):
        secret = self.workspace / "private/secret"
        contexts = [kernel.context(self.workspace), {},
            {"permissions": {"type": "disabled", "extra": True}, "windowsSandboxLevel": "disabled"}]
        for context in contexts:
            with self.subTest(context=context), self.assertRaises(RpcError):
                await self.call("fs/writeFile", {"path": secret.as_uri(), "sandbox": context, "dataBase64": "YmFk"})
            self.assertEqual(secret.read_bytes(), b"original-private")
        disabled_process = {"permissions": {"type": "disabled"}, "windowsSandboxLevel": "disabled"}
        with self.assertRaises(RpcError):
            await self.call("process/start", self.params("disabled-process", "printf bad > marker", sandbox=disabled_process))
        self.assertNotIn(("test", "disabled-process"), self.direct.processes)
        self.assertFalse((self.workspace / "marker").exists())

    async def test_09_unknown_lifecycle_preserves_upstream_idempotent_replies(self):
        self.assertEqual(await self.call("process/signal", {"processId": "unknown", "signal": "interrupt"}), {})
        self.assertEqual(await self.call("process/terminate", {"processId": "unknown"}), {"running": False})
        with self.assertRaises(RpcError):
            await self.call("process/read", {"processId": "unknown"})

    async def test_10_close_drains_actual_process_and_both_file_handle_owners(self):
        await self.call("fs/open", self.file_params("direct"))
        await self.call("fs/open", self.file_params("managed", managed=True))
        descriptors = [self.direct_files.handles["direct"].fd, self.owner.files.handles["managed"].fd]
        record = await self.start("running", "printf READY; /usr/bin/sleep 100")
        await self.until(record, b"READY")
        await asyncio.wait_for(self.owner.close("test"), 20)
        self.assertTrue(record.closed and record.native_result["cleanupComplete"])
        for descriptor in descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        with self.assertRaises(RpcError):
            await self.call("fs/readFile", {"path": (self.workspace / "value").as_uri()})

    async def test_11_owner_loss_quarantines_pending_files_and_retains_real_lease(self):
        # This initial child has no descendants. PDEATHSIG ends it on owner loss;
        # missing cleanup attestation still cannot release either filesystem.
        python = self.options["executables"]["python"]
        import shlex
        record = await self.start("lost", "exec " + shlex.quote(python) + " -I -B -c " + shlex.quote(
            "import os,time;print(str(os.getpid())+' READY',flush=True);time.sleep(100)"))
        response = await self.until(record, b"READY")
        child_fd = os.pidfd_open(int(self.output(response).split()[0]), 0)
        owner_fd = os.pidfd_open(record.process.pid, 0)
        pending = asyncio.create_task(self.call("fs/writeFile", {
            "path": (self.workspace / "must-not-write").as_uri(), "dataBase64": "YmFk"}))
        self.expected_quarantine = True
        try:
            await asyncio.sleep(0)
            signal.pidfd_send_signal(owner_fd, signal.SIGKILL)
            await asyncio.wait_for(asyncio.shield(record.finished), 15)
            with self.assertRaises(RpcError):
                await asyncio.wait_for(pending, 5)
            self.assertTrue(self.owner.processes.quarantine_event.is_set())
            self.assertTrue(self.direct.quarantined)
            self.assertTrue(self.owner.files.lock.locked())
            self.assertFalse(self.owner.files.closed or self.direct_files.closed)
            self.assertFalse((self.workspace / "must-not-write").exists())
            for context in (None, kernel.context(self.workspace)):
                with self.assertRaises(RpcError):
                    await self.call("fs/readFile", {"path": (self.workspace / "value").as_uri(), "sandbox": context})
            self.assertTrue(select.select([child_fd], [], [], 5)[0], "Exact initial child still alive")
        finally:
            os.close(child_fd)
            os.close(owner_fd)
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


if __name__ == "__main__":
    if BUILD is None or EVIDENCE is None or not EVIDENCE.is_dir():
        raise SystemExit("Pass frozen native helper build and existing project evidence directory")
    required = ("native-files", "native-file-handle", "runner", "direct-runner")
    if any(not (BUILD / name).is_file() for name in required):
        raise SystemExit("The native helper build is incomplete")
    result = unittest.main(verbosity=2, exit=False).result
    success = result.wasSuccessful() and not result.skipped
    sources = {}
    for path in (Path(__file__), Path(__file__).with_name("factory.py"),
            Path(__file__).parents[1] / "native_model_profiles.py",
            Path(__file__).parents[1] / "native_executor_backend.py",
            Path(__file__).parents[1] / "ordinary_uid_files.py"):
        sources[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    output = EVIDENCE / "model-profiles.json"
    output.write_text(json.dumps({"success": success, "testsRun": result.testsRun,
        "uid": os.getuid(), "androidExecution": False, "observations": OBSERVATIONS,
        "sourceSha256": sources,
        "failures": [[test.id(), detail] for test, detail in result.failures],
        "errors": [[test.id(), detail] for test, detail in result.errors],
        "skipped": [[test.id(), reason] for test, reason in result.skipped]}, indent=2) + "\n")
    print(json.dumps({"evidence": str(output), "success": success}), flush=True)
    raise SystemExit(0 if success else 1)
