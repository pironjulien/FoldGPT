"""Host-only scheduling regressions over real native workers and SEQPACKETs.

No syscall result, native lifecycle record or cleanup proof is fabricated.
Gates delay actual policy decisions/ACKs; pidfds stop only our host supervisor
to place a real response in its receive queue before cancellation.
"""
import asyncio
import errno
import importlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
support = importlib.import_module("tools.executor.bionic-supervisor.test_factory")
processes = importlib.import_module("tools.executor.bionic-supervisor.processes")
from tools.executor.exec_server import RpcError

OBSERVATIONS = []


class ControlTerminationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = support.FactoryTests.asyncSetUp
    asyncTearDown = support.FactoryTests.asyncTearDown
    notify = support.FactoryTests.notify
    call = support.FactoryTests.call
    start = support.FactoryTests.start

    def record(self):
        records = list(self.backend.processes.processes.values())
        self.assertEqual(len(records), 1)
        return records[0]

    async def reset_wall(self, wall_ms):
        await self.backend.close("test")
        self.options["limits"]["wall_ms"] = wall_ms
        self.backend = support.factory(self.options)

    async def terminal(self, record, starting, outcome):
        start_results = await asyncio.gather(starting, return_exceptions=True)
        await asyncio.wait_for(asyncio.shield(record.finished), 8)
        self.assertIsNotNone(record.native_result, record.failure)
        self.assertEqual(record.native_result["outcome"], outcome, record.native_result)
        self.assertTrue(record.native_result["cleanupComplete"])
        self.assertIsNotNone(record.process.returncode)
        self.assertTrue(record.closed)
        self.assertFalse(self.backend.processes.quarantined)
        self.assertFalse(self.backend.files.lock.locked())
        self.assertEqual((self.workspace / "private/secret").read_text(), "unchanged private data")
        self.assertFalse((self.workspace / "target").exists())
        OBSERVATIONS.append({"test": self.id(), "nativeResult": record.native_result,
            "supervisorPid": record.process.pid, "supervisorReturncode": record.process.returncode,
            "closed": record.closed, "quarantined": self.backend.processes.quarantined,
            "terminationRequested": record.termination_requested,
            "startErrors": [str(value) for value in start_results if isinstance(value, BaseException)]})

    async def held_first_decision(self, action):
        if action == "timeout":
            await self.reset_wall(1000)
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original = processes.Policy.decide
        first = True
        sent_errors = []
        actual_packet = processes._packet

        def decide(policy, message):
            nonlocal first
            if first:
                first = False
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(8):
                    raise TimeoutError("Host decision gate was not released")
            return original(policy, message)

        async def packet(endpoint, payload):
            try:
                return await actual_packet(endpoint, payload)
            except OSError as error:
                sent_errors.append(error.errno)
                raise

        with patch.object(processes.Policy, "decide", decide), patch.object(processes, "_packet", packet):
            starting = asyncio.create_task(self.start("printf forbidden > target"))
            try:
                await asyncio.wait_for(entered.wait(), 3)
                record = self.record()
                if action == "cancel":
                    await self.call("process/terminate", {"processId": record.key})
                elif action == "command-eof":
                    record.command.close()
                    record.command = None
                    self.assertFalse(record.termination_requested)
                await asyncio.wait_for(record.process.wait(), 5)
            finally:
                release.set()
            await self.terminal(record, starting, "timeout" if action == "timeout" else "cancelled")
        self.assertEqual(sent_errors, [] if action == "cancel" else [errno.EPIPE])
        OBSERVATIONS[-1]["responseSendErrors"] = sent_errors

    async def test_01_rpc_cancel_while_first_real_decision_is_pending(self):
        await self.held_first_decision("cancel")

    async def test_02_native_timeout_while_first_real_decision_is_pending(self):
        await self.held_first_decision("timeout")

    async def test_03_command_eof_while_first_real_decision_is_pending(self):
        await self.held_first_decision("command-eof")

    async def test_04_response_already_queued_when_cancellation_arrives(self):
        actual_packet = processes._packet
        injected = False

        async def packet(endpoint, payload):
            nonlocal injected
            if payload == b"P" or injected:
                return await actual_packet(endpoint, payload)
            injected = True
            record = self.record()
            identity = os.pidfd_open(record.process.pid)
            try:
                signal.pidfd_send_signal(identity, signal.SIGSTOP)
                for _ in range(100):
                    status = Path(f"/proc/{record.process.pid}/status").read_text()
                    if "State:\tT" in status:
                        break
                    await asyncio.sleep(0.01)
                else:
                    self.fail("Pinned host supervisor did not stop")
                # The real decision has passed the Python cancellation check.
                # C is stopped: the reply is definitely queued and unread.
                await actual_packet(endpoint, payload)
                await self.call("process/terminate", {"processId": record.key})
            finally:
                signal.pidfd_send_signal(identity, signal.SIGCONT)
                os.close(identity)

        with patch.object(processes, "_packet", packet):
            starting = asyncio.create_task(self.start("printf forbidden > target"))
            while not injected:
                if starting.done() and starting.exception() is not None:
                    starting.result()
                await asyncio.sleep(0.01)
            record = self.record()
            await self.terminal(record, starting, "cancelled")
        self.assertTrue(injected)
        OBSERVATIONS[-1]["responseQueuedBeforeCancellation"] = True

    async def delayed_ack(self, lose_owner):
        await self.reset_wall(1000)
        actual_packet = processes._packet
        record = None
        sent_errors = []

        async def packet(endpoint, payload):
            nonlocal record
            self.assertEqual(payload, b"P")
            record = self.record()
            if lose_owner:
                identity = os.pidfd_open(record.process.pid)
                try:
                    signal.pidfd_send_signal(identity, signal.SIGKILL)
                finally:
                    os.close(identity)
            await asyncio.wait_for(record.process.wait(), 5)
            try:
                return await actual_packet(endpoint, payload)
            except OSError as error:
                sent_errors.append(error.errno)
                raise

        with patch.object(processes, "_packet", packet):
            starting = asyncio.create_task(self.start("printf forbidden > target"))
            with self.assertRaises(RpcError):
                await starting
            self.assertIsNotNone(record)
            if not lose_owner:
                await self.terminal(record, starting, "timeout")
                self.assertFalse(record.native_result["started"])
            else:
                await asyncio.wait_for(asyncio.shield(record.finished), 8)
                self.assertIsNone(record.native_result)
                self.assertIsNotNone(record.process.returncode)
                self.assertTrue(self.backend.processes.quarantined)
                self.assertFalse(record.closed)
                self.assertTrue(self.backend.files.lock.locked())
                with self.assertRaises(RpcError):
                    await self.start("printf forbidden", key="retry")
                OBSERVATIONS.append({"test": self.id(), "nativeResult": None,
                    "supervisorPid": record.process.pid, "supervisorReturncode": record.process.returncode,
                    "closed": record.closed, "quarantined": self.backend.processes.quarantined,
                    "leaseRetained": self.backend.files.lock.locked(), "failure": record.failure})
        self.assertEqual(sent_errors, [errno.EPIPE])
        OBSERVATIONS[-1]["ackSendErrors"] = sent_errors

    async def test_05_ack_finishes_after_native_startup_timeout(self):
        await self.delayed_ack(False)

    async def test_06_epipe_without_final_result_keeps_quarantine(self):
        await self.delayed_ack(True)


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False).result
    destination = Path(tempfile.mkdtemp(prefix="foldgpt-control-termination-", dir="/var/tmp")) / "observations.json"
    report = {"schema": "foldgpt.control-termination.host-tests.v1", "success": result.wasSuccessful(),
              "androidExecution": False, "observations": OBSERVATIONS}
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"success": result.wasSuccessful(), "observations": str(destination)}), flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 1)
