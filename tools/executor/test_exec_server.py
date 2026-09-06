"""Protocol tests only: never evidence of native sandbox enforcement."""

import asyncio
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from tools.executor.exec_server import (
    BACKEND_METHODS, CAPABILITIES, BackendCall, ExecServer, ProtocolClosed,
    RpcError, UnavailableBackend, decode_message, encode_message, serve_stdio,
    _read_frame,
)


INFO = {"shell": {"name": "sh", "path": "/bin/sh"}, "cwd": "file:///workspace",
        "userHomeDir": "file:///home/test", "platformOs": "linux"}


def request(method, params=None, request_id=1):
    return {"id": request_id, "method": method, "params": params}


def process_params(**extra):
    return {"processId": "p1", "argv": ["/bin/true"], "cwd": "file:///workspace",
            "env": {}, "tty": False, **extra}


class RecordingRefusalBackend(UnavailableBackend):
    """Records transport input and REFUSES it; never simulates native success."""
    supported_methods = BACKEND_METHODS

    def __init__(self):
        self.calls = []
        self.closed_sessions = []

    async def handle(self, call, notify):
        self.calls.append(call)
        raise RpcError(-32004, "Test admission refusal")

    async def close(self, session_id):
        self.closed_sessions.append(session_id)


class ExecServerTests(unittest.IsolatedAsyncioTestCase):
    async def init(self, server):
        result = await server.request(request("initialize", {"clientName": "conformance"}))
        self.assertIn("result", result)
        await server.accept({"method": "initialized"}, self.emit)
        return result["result"]

    async def asyncSetUp(self):
        self.messages = []

    async def emit(self, message):
        self.messages.append(message)

    async def test_exact_handshake_and_capabilities(self):
        server = ExecServer(environment_info=INFO)
        result = await self.init(server)
        uuid.UUID(result["sessionId"])
        self.assertEqual(set(result), {"sessionId", "environmentInfo"})
        info = result["environmentInfo"]
        self.assertEqual(info["capabilities"], {name: False for name in CAPABILITIES})
        self.assertEqual(await server.request(request("environment/info")), {"id": 1, "result": info})
        self.assertEqual(await server.request(request("environment/status", {})),
                         {"id": 1, "result": {"status": "ready"}})
        self.assertNotIn("jsonrpc", encode_message(result).decode())
        await server.close()

    async def test_handshake_order_resume_repeated_initialize(self):
        server = ExecServer(environment_info=INFO)
        self.assertEqual((await server.request(request("environment/info")))["error"]["code"], -32600)
        with self.assertRaises(ProtocolClosed):
            await server.accept({"method": "initialized"}, self.emit)
        failed = await server.request(request("initialize", {"clientName": "test", "resumeSessionId": "other"}))
        self.assertEqual(failed["error"]["code"], -32600)
        first = await server.request(request("initialize", {"clientName": "test"}))
        self.assertIn("result", first)
        self.assertEqual((await server.request(request("environment/info")))["error"]["code"], -32600)
        second = await server.request(request("initialize", {"clientName": "test"}))
        self.assertEqual(second["error"]["code"], -32600)
        await server.close()

    async def test_default_backend_never_executes_or_mutates(self):
        server = ExecServer(environment_info=INFO)
        await self.init(server)
        with tempfile.TemporaryDirectory() as task_dir:
            target = Path(task_dir) / "must-not-exist"
            for method, params in [
                ("process/start", process_params(argv=[sys.executable, "-c", "raise SystemExit(99)"])),
                ("fs/writeFile", {"path": target.as_uri(), "dataBase64": "c2VjcmV0"}),
                ("fs/readFile", {"path": target.as_uri()}),
                ("fs/createDirectory", {"path": target.as_uri()}),
                ("fs/remove", {"path": target.as_uri(), "force": True}),
            ]:
                response = await server.request(request(method, params))
                self.assertEqual(response["error"]["code"], -32601)
                self.assertNotIn("result", response)
            self.assertFalse(target.exists())
        await server.close()

    async def test_backend_gets_complete_immutable_policy_and_trace(self):
        backend = RecordingRefusalBackend()
        server = ExecServer(backend, environment_info=INFO)
        await self.init(server)
        policy = {"permissions": {"type": "managed", "file_system": {
            "type": "restricted", "entries": [{"path": {"type": "path", "path": "file:///workspace/private"}, "access": "none"}]}},
            "cwd": "file:///workspace", "metadata": {"retain": ["everything"]}}
        params = process_params(sandbox=policy, envPolicy={"inherit": "none"})
        message = request("process/start", params, request_id="007")
        message["trace"] = {"traceparent": "test-telemetry"}
        response = await server.request(message)
        self.assertEqual(response["error"]["code"], -32004)
        call = backend.calls[0]
        self.assertIsInstance(call, BackendCall)
        self.assertEqual(call.session_id, server.session_id)
        self.assertEqual(call.request_id, "007")
        self.assertEqual(call.params, params)
        self.assertEqual(json.loads(call.trace_json), message["trace"])
        params["sandbox"]["metadata"]["retain"].clear()
        self.assertEqual(call.params["sandbox"]["metadata"]["retain"], ["everything"])
        returned = call.params
        returned["sandbox"].clear()
        self.assertIn("permissions", call.params["sandbox"])
        await server.close()
        self.assertEqual(backend.closed_sessions, [server.session_id])

    async def test_lifecycle_cannot_replace_bound_policy(self):
        backend = RecordingRefusalBackend()
        server = ExecServer(backend, environment_info=INFO)
        await self.init(server)
        for method, params in [("process/terminate", {"processId": "p1"}),
                               ("fs/close", {"handleId": "h1"}),
                               ("fs/readBlock", {"handleId": "h1", "offset": 0, "len": 3})]:
            params["sandbox"] = {"permissions": {"type": "unrestricted"}}
            result = await server.request(request(method, params))
            self.assertEqual(result["error"]["code"], -32602)
        self.assertEqual(backend.calls, [])
        await server.close()

    async def test_unknown_method_has_official_error(self):
        server = ExecServer(environment_info=INFO)
        await self.init(server)
        self.assertEqual((await server.request(request("exec", {})))["error"]["code"], -32601)
        await server.close()

    async def test_optional_capabilities_reject_before_backend(self):
        backend = RecordingRefusalBackend()
        server = ExecServer(backend, environment_info=INFO)
        await self.init(server)
        for method, params in [
            ("process/start", process_params(shellSnapshot={"scopeId": "x"})),
            ("process/start", process_params(networkProxy={})),
            ("process/start", process_params(enforceManagedNetwork=True)),
            ("fs/open", {"path": "file:///workspace/file", "handleId": "h", "sandbox": {}}),
        ]:
            result = await server.request(request(method, params))
            self.assertEqual(result["error"]["code"], -32602)
        self.assertEqual(backend.calls, [])
        await server.close()

    async def test_malformed_operations_cannot_reach_backend(self):
        backend = RecordingRefusalBackend()
        server = ExecServer(backend, environment_info=INFO)
        await self.init(server)
        cases = [
            ("process/start", process_params(cwd="/native/not/a/uri")),
            ("process/start", process_params(tty="false")),
            ("process/start", process_params(env={"INJECT": ["value"]})),
            ("process/start", process_params(unsafeUnknown=True)),
            ("process/write", {"processId": "p", "writeId": "w", "chunk": "!"}),
            ("process/write", {"processId": "p", "writeId": "w", "chunk": "Zh=="}),
            ("process/signal", {"processId": "p", "signal": "kill"}),
            ("fs/readBlock", {"handleId": "h", "offset": -1, "len": 2}),
            ("fs/readBlock", {"handleId": "h", "offset": False, "len": 2}),
            ("fs/writeFile", {"path": "file:///tmp/file", "dataBase64": "a"}),
            ("fs/copy", {"sourcePath": "file:///a", "destinationPath": "file:///b"}),
            ("environment/status", {"other": True}),
        ]
        for method, params in cases:
            with self.subTest(method=method, params=params):
                response = await server.request(request(method, params))
                self.assertEqual(response["error"]["code"], -32602)
        self.assertEqual(backend.calls, [])
        await server.close()

    async def test_dispatch_every_process_and_filesystem_method_to_refusing_backend(self):
        backend = RecordingRefusalBackend()
        backend.capabilities = frozenset({"sandboxedFileStreaming"})
        server = ExecServer(backend, environment_info=INFO)
        await self.init(server)
        cases = {
            "process/start": process_params(),
            "process/read": {"processId": "p", "afterSeq": None, "waitMs": 0},
            "process/write": {"processId": "p", "writeId": "w", "chunk": "AAEC/w=="},
            "process/signal": {"processId": "p", "signal": "interrupt"},
            "process/terminate": {"processId": "p"},
            "fs/readFile": {"path": "file:///x", "followSymlinks": False},
            "fs/open": {"path": "file:///x", "handleId": "h", "sandbox": {}},
            "fs/readBlock": {"handleId": "h", "offset": 1, "len": 2},
            "fs/close": {"handleId": "h"},
            "fs/writeFile": {"path": "file:///x", "dataBase64": "AAEC/w=="},
            "fs/createDirectory": {"path": "file:///x", "recursive": True},
            "fs/getMetadata": {"path": "file:///x"},
            "fs/canonicalize": {"path": "file:///x"},
            "fs/readDirectory": {"path": "file:///x"},
            "fs/walk": {"path": "file:///x", "options": {}},
            "fs/remove": {"path": "file:///x", "force": False},
            "fs/copy": {"sourcePath": "file:///a", "destinationPath": "file:///b", "recursive": True},
            "capabilityRoots/discoverV1": {"roots": [{"id": "x", "path": "file:///x", "sandbox": {}}]},
            "environmentConfig/read": {}, "http/request": {},
        }
        for method, params in cases.items():
            response = await server.request(request(method, params))
            self.assertEqual(response["error"]["code"], -32004, method)
        self.assertEqual({call.method for call in backend.calls}, BACKEND_METHODS)
        await server.close()

    async def test_control_can_run_while_regular_lane_is_full_and_disconnect_cancels(self):
        class WaitingRefusalBackend(RecordingRefusalBackend):
            def __init__(self):
                super().__init__()
                self.entered = asyncio.Event()
                self.cancelled = False

            async def handle(self, call, notify):
                if call.method == "process/read":
                    self.entered.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        self.cancelled = True
                        raise
                return await super().handle(call, notify)

        backend = WaitingRefusalBackend()
        server = ExecServer(backend, environment_info=INFO, max_in_flight=1)
        await self.init(server)
        await server.accept(request("process/read", {"processId": "p"}, 10), self.emit)
        await asyncio.wait_for(backend.entered.wait(), 1)
        await server.accept(request("fs/readFile", {"path": "file:///x"}, 11), self.emit)
        self.assertEqual(self.messages[-1]["error"]["code"], -32000)
        await server.accept(request("process/terminate", {"processId": "p"}, 12), self.emit)
        await asyncio.sleep(0)
        self.assertEqual(backend.calls[-1].method, "process/terminate")
        await server.close()
        self.assertTrue(backend.cancelled)
        self.assertEqual(backend.closed_sessions, [server.session_id])
        self.assertNotIn(10, [item["id"] for item in self.messages])

    async def test_same_numeric_and_string_ids_are_distinct_but_duplicate_inflight_closes(self):
        server = ExecServer(environment_info=INFO)
        await self.init(server)
        await server.accept(request("environment/status", request_id=1), self.emit)
        await server.accept(request("environment/status", request_id="1"), self.emit)
        with self.assertRaises(ProtocolClosed):
            await server.accept(request("environment/status", request_id=1), self.emit)
        await asyncio.sleep(0)
        self.assertEqual({type(item["id"]) for item in self.messages}, {int, str})
        await server.close()

    async def test_unknown_notification_and_unsolicited_client_response_close(self):
        server = ExecServer(environment_info=INFO)
        await self.init(server)
        for message in [{"method": "shutdown"}, {"id": 1, "result": {}}]:
            with self.assertRaises(ProtocolClosed):
                await server.accept(message, self.emit)
        await server.close()

    async def test_backend_internal_error_is_not_sensitive_or_success(self):
        class BrokenBackend(RecordingRefusalBackend):
            async def handle(self, call, notify):
                raise RuntimeError("sensitive=do-not-print")
        server = ExecServer(BrokenBackend(), environment_info=INFO)
        await self.init(server)
        result = await server.request(request("fs/readFile", {"path": "file:///x"}))
        self.assertEqual(result["error"]["code"], -32603)
        self.assertNotIn("sensitive", str(result))
        await server.close()

    async def test_stdio_blank_crlf_utf8_malformed_recovery_and_eof_cleanup(self):
        backend = RecordingRefusalBackend()
        server = ExecServer(backend, environment_info=INFO)
        incoming = b'\n{bad}\r\n' + encode_message(request("initialize", {"clientName": "épreuve"})) + b'\r\n'
        incoming += b'{"method":"initialized"}\n'
        output = io.BytesIO()
        await serve_stdio(server, io.BytesIO(incoming), output)
        results = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(results[0]["id"], -1)
        self.assertEqual(results[0]["error"]["code"], -32600)
        self.assertIn("sessionId", results[1]["result"])
        self.assertTrue(server.closed)
        self.assertEqual(backend.closed_sessions, [server.session_id])

    async def test_stdio_message_limit_exact_and_oversized_unterminated(self):
        line = encode_message(request("initialize", {"clientName": "x"}))
        for ending in [b"\n", b"\r\n", b""]:
            self.assertEqual(await _read_frame(io.BytesIO(line + ending), len(line)), line)
            server = ExecServer(environment_info=INFO)
            output = io.BytesIO()
            await serve_stdio(server, io.BytesIO(line + ending), output, max_message_bytes=4096)
            self.assertIn("result", json.loads(output.getvalue()))
        server = ExecServer(environment_info=INFO)
        with self.assertRaises(ProtocolClosed):
            await serve_stdio(server, io.BytesIO(b"x" * 4097), io.BytesIO(), max_message_bytes=4096)
        self.assertTrue(server.closed)

    async def test_output_failure_closes_while_input_pipe_stays_open(self):
        release_reader = threading.Event()

        class HeldReader:
            def __init__(self):
                self.frames = iter([
                    encode_message(request("initialize", {"clientName": "test"})) + b"\n",
                    b'{"method":"initialized"}\n',
                    encode_message(request("environment/status", request_id=2)) + b"\n",
                ])

            def readline(self, _limit):
                frame = next(self.frames, None)
                if frame is not None:
                    return frame
                release_reader.wait()
                return b""

        class FailedWriter(io.BytesIO):
            def write(self, data):
                if self.tell():
                    raise BrokenPipeError("peer closed stdout")
                return super().write(data)

        backend = RecordingRefusalBackend()
        server = ExecServer(backend, environment_info=INFO)
        try:
            with self.assertRaises(ProtocolClosed):
                await asyncio.wait_for(serve_stdio(server, HeldReader(), FailedWriter()), 2)
            self.assertTrue(server.closed)
            self.assertEqual(backend.closed_sessions, [server.session_id])
        finally:
            release_reader.set()

    async def test_eof_cancels_blocked_output_and_still_closes_backend(self):
        blocked_write = threading.Event()
        release_writer = threading.Event()

        class EofAfterBlockedWriter:
            def __init__(self):
                self.frames = iter([
                    encode_message(request("initialize", {"clientName": "test"})) + b"\n",
                    b'{"method":"initialized"}\n',
                    encode_message(request("environment/status", request_id=2)) + b"\n",
                ])

            def readline(self, _limit):
                frame = next(self.frames, None)
                if frame is not None:
                    return frame
                blocked_write.wait()
                return b""

        class HeldWriter(io.BytesIO):
            def write(self, data):
                if self.tell():
                    blocked_write.set()
                    release_writer.wait()
                    return len(data)
                return super().write(data)

        backend = RecordingRefusalBackend()
        server = ExecServer(backend, environment_info=INFO)
        cleaned = asyncio.Event()
        original_close = backend.close

        async def close(session_id):
            await original_close(session_id)
            cleaned.set()

        backend.close = close
        running = asyncio.create_task(serve_stdio(server, EofAfterBlockedWriter(), HeldWriter()))
        try:
            await asyncio.wait_for(cleaned.wait(), 2)
            self.assertTrue(blocked_write.is_set())
            self.assertTrue(server.closed)
            self.assertEqual(server.pending, {})
            self.assertEqual(backend.closed_sessions, [server.session_id])
            release_writer.set()
            await asyncio.wait_for(running, 2)
        finally:
            blocked_write.set()
            release_writer.set()
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)

    async def test_inline_error_cannot_hide_eof_while_stdout_is_blocked(self):
        # These routes emit directly from the receive loop. Previously each
        # trapped EOF and native cleanup behind a blocked response write.
        for error_frame in [
            encode_message(request("process/read", {"processId": "p"}, 3)) + b"\n",
            b"{malformed}\n",
            encode_message(request("initialize", {"clientName": "again"}, 3)) + b"\n",
        ]:
            with self.subTest(error_frame=error_frame):
                worker_entered = threading.Event()
                writer_blocked = threading.Event()
                release_writer = threading.Event()
                cleaned = asyncio.Event()

                class WaitingBackend(RecordingRefusalBackend):
                    def __init__(self):
                        super().__init__()
                        self.cancelled = False

                    async def handle(self, call, notify):
                        worker_entered.set()
                        try:
                            await asyncio.Event().wait()
                        except asyncio.CancelledError:
                            self.cancelled = True
                            raise

                    async def close(self, session_id):
                        await super().close(session_id)
                        cleaned.set()

                class EofReader:
                    def __init__(self):
                        self.frames = iter([
                            encode_message(request("initialize", {"clientName": "test"})) + b"\n",
                            b'{"method":"initialized"}\n',
                            encode_message(request("process/read", {"processId": "p"}, 2)) + b"\n",
                            error_frame,
                        ])

                    def readline(self, _limit):
                        frame = next(self.frames, None)
                        if frame == error_frame:
                            worker_entered.wait()
                        if frame is not None:
                            return frame
                        writer_blocked.wait()
                        return b""

                class HeldWriter(io.BytesIO):
                    def write(self, data):
                        if self.tell():
                            writer_blocked.set()
                            release_writer.wait()
                        return super().write(data)

                backend = WaitingBackend()
                server = ExecServer(backend, environment_info=INFO, max_in_flight=1)
                running = asyncio.create_task(serve_stdio(server, EofReader(), HeldWriter()))
                try:
                    await asyncio.wait_for(cleaned.wait(), 2)
                    self.assertTrue(writer_blocked.is_set())
                    self.assertTrue(backend.cancelled)
                    self.assertEqual(backend.closed_sessions, [server.session_id])
                    release_writer.set()
                    await asyncio.wait_for(running, 2)
                finally:
                    worker_entered.set()
                    writer_blocked.set()
                    release_writer.set()
                    running.cancel()
                    await asyncio.gather(running, return_exceptions=True)

    async def test_outbound_queue_saturation_disconnects_without_waiting_for_stdout(self):
        release_writer = threading.Event()

        class EndlessReader:
            def __init__(self):
                self.first = True

            def readline(self, _limit):
                if self.first:
                    self.first = False
                    return encode_message(request("initialize", {"clientName": "test"})) + b"\n"
                return b"{malformed}\n"

        class HeldWriter(io.BytesIO):
            def write(self, data):
                release_writer.wait()
                return super().write(data)

        backend = RecordingRefusalBackend()
        server = ExecServer(backend, environment_info=INFO)
        try:
            with self.assertRaises(ProtocolClosed):
                await asyncio.wait_for(serve_stdio(server, EndlessReader(), HeldWriter(), max_message_bytes=1024), 2)
            self.assertTrue(server.closed)
            self.assertEqual(backend.closed_sessions, [server.session_id])
        finally:
            release_writer.set()


class WireTests(unittest.TestCase):
    def test_strict_json_and_id_types(self):
        for invalid in [b"[]", b"null", b'{"id":null,"method":"x"}',
                        b'{"id":true,"method":"x"}', b'{"id":1.5,"method":"x"}',
                        b'{"id":9223372036854775808,"method":"x"}',
                        b'{"id":1,"method":"x","params":{"a":1,"a":2}}',
                        b'{"id":1,"method":"x","params":NaN}',
                        b'{"id":1,"method":"x","params":1e999}',
                        b'{"id":1,"method":"x","params":"\\ud800"}',
                        b'{"id":1,"method":"x","params":{"\\ud800":1}}',
                        b'{"id":1,"method":4}', b'{"x":1}', b'\xff']:
            with self.subTest(invalid=invalid), self.assertRaises(RpcError):
                decode_message(invalid)
        for request_id in ["", "1", -2**63, 2**63 - 1]:
            self.assertEqual(decode_message(encode_message(request("x", request_id=request_id)))["id"], request_id)

    def test_complexity_limit_rejects_compact_fanout(self):
        with patch("tools.executor.exec_server.MAX_VALUE_NODES", 8):
            with self.assertRaises(RpcError):
                decode_message(b'{"id":1,"method":"x","params":[0,0,0,0,0,0]}')

    def test_capabilities_must_be_explicit_and_have_implementation_routes(self):
        with self.assertRaises(ValueError):
            ExecServer(environment_info={**INFO, "capabilities": {"sandboxedFileStreaming": True}})
        backend = UnavailableBackend()
        backend.capabilities = frozenset({"sandboxedFileStreaming"})
        with self.assertRaises(ValueError):
            ExecServer(backend, environment_info=INFO)
        backend.capabilities = frozenset({"claimsFullIsolation"})
        with self.assertRaises(ValueError):
            ExecServer(backend, environment_info=INFO)

    def test_real_stdio_entrypoint_handshake_with_no_profile_or_commands(self):
        root = Path(__file__).resolve().parents[2]
        frames = [request("initialize", {"clientName": "entrypoint-test"}), {"method": "initialized"}]
        result = subprocess.run([sys.executable, "-B", "-m", "tools.executor.exec_server"],
                                cwd=root, input=b"".join(encode_message(frame) + b"\n" for frame in frames),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["result"]["environmentInfo"]["capabilities"], {name: False for name in CAPABILITIES})
        self.assertEqual(result.stderr, b"")


if __name__ == "__main__":
    unittest.main()
