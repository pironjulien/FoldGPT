"""Real native human-owner lifecycle, stream backpressure and shared lease tests."""
import asyncio
import base64
import importlib
import json
from pathlib import Path
import sys
import unittest

# The fixture consumes the explicit build and evidence arguments once.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
kernel = importlib.import_module("tools.executor.bionic-supervisor.test_host_kernel")
host = importlib.import_module("tools.executor.bionic-supervisor.host_processes")


class HostOwnerTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = kernel.HostKernelTests.asyncSetUp
    asyncTearDown = kernel.HostKernelTests.asyncTearDown

    def backend(self):
        return host.HostProcesses(self.authority, str(kernel.BUILD / "host-runner"),
            runtime=self.runtime, executables={"cat": "/usr/bin/cat", "sh": "/usr/bin/bash"})

    async def complete(self, record):
        await asyncio.wait_for(asyncio.shield(record.finished), 20)
        await asyncio.wait_for(asyncio.shield(record.notifier), 3)
        self.assertTrue(record.closed, record.failure)
        self.assertTrue(record.native_result["cleanupComplete"], record.native_result)
        self.assertIsNotNone(record.process.returncode)
        self.results.append({"nativeResult": record.native_result, "failure": record.failure,
                             "supervisorReturncode": record.process.returncode})

    async def test_real_output_backpressure_holds_shared_workspace_until_cleanup(self):
        backend = self.backend()
        path = self.workspace / "large.bin"
        data = bytes(range(256)) * 40961
        path.write_bytes(data)
        admitted, release = asyncio.Event(), asyncio.Event()
        events, stdout = [], bytearray()
        async def notify(method, params):
            if method == "process/output":
                admitted.set()
                await release.wait()
                if params["stream"] == "stdout":
                    stdout.extend(base64.b64decode(params["chunk"], validate=True))
            events.append((method, params["seq"]))
        record = await backend.spawn("read", ["cat", str(path)], "/", {}, pipe_stdin=False, notify=notify)
        await asyncio.wait_for(admitted.wait(), 5)
        write = asyncio.create_task(self.authority.write_file((self.workspace / "after").as_uri(), b"after cleanup"))
        await asyncio.sleep(0)
        self.assertTrue(self.owner.files.lock.locked())
        self.assertFalse(write.done())
        release.set()
        await self.complete(record)
        await asyncio.wait_for(write, 5)
        self.assertEqual(bytes(stdout), data)
        self.assertEqual([seq for _, seq in events], list(range(1, len(events) + 1)))
        self.assertEqual(events[-1][0], "process/closed")
        self.assertEqual((self.workspace / "after").read_bytes(), b"after cleanup")

    async def test_shell_receives_large_real_stdin_and_explicit_eof(self):
        backend = self.backend()
        path = self.workspace / "saved.bin"
        data = bytes(range(256)) * 8193
        async def notify(*_):
            pass
        record = await backend.spawn("write", ["sh", "-c", 'cat > "$1"', "sh", str(path)],
                                     "/", {"PATH": "/usr/bin:/bin"}, pipe_stdin=True, notify=notify)
        for offset in range(0, len(data), 32768):
            await backend.write(record, data[offset:offset + 32768], close_stdin=False)
        await backend.write(record, b"", close_stdin=True)
        await self.complete(record)
        self.assertEqual(record.exit_code, 0)
        self.assertEqual(path.read_bytes(), data)

    async def test_native_owner_close_owns_and_reaps_human_descendants(self):
        backend = self.backend()
        started = asyncio.Event()
        async def notify(method, params):
            if method == "process/output" and b"ready" in base64.b64decode(params["chunk"]):
                started.set()
        record = await backend.spawn("cancel", ["sh", "-c", "sleep 20 & printf ready; wait"],
            "/", {"PATH": "/usr/bin:/bin"}, pipe_stdin=False, notify=notify)
        await asyncio.wait_for(started.wait(), 5)
        await asyncio.wait_for(self.owner.close("host-real-test"), 15)
        self.assertTrue(record.closed)
        self.assertTrue(record.native_result["cleanupComplete"])
        self.assertEqual(record.native_result["outcome"], "cancelled")
        self.assertIsNotNone(record.process.returncode)
        self.results.append({"nativeResult": record.native_result,
                             "supervisorReturncode": record.process.returncode})

    async def test_broken_human_output_consumer_cancels_and_drains_real_process(self):
        backend = self.backend()
        async def notify(*_):
            raise BrokenPipeError("Actual test consumer disconnected")
        record = await backend.spawn("broken", ["sh", "-c", "printf ready; sleep 20"],
            "/", {"PATH": "/usr/bin:/bin"}, pipe_stdin=False, notify=notify)
        await self.complete(record)
        self.assertTrue(backend.disconnected.is_set())
        self.assertFalse(self.owner.processes.quarantined)


if __name__ == "__main__":
    unittest.main()
