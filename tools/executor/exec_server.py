"""Codex 0.153.4 exec-server stdio transport; native enforcement is injectable.

Wire contract: official commit 042fb41b7c813ac7999105e886b2b7aa715b5081,
exec-server-protocol/src/{rpc,protocol}.rs and exec-server/src/server/registry.rs.
This module NEVER executes a command or accesses a requested file itself. Its
default backend explicitly refuses every operation. A native backend must bind
processes/streams to this session and retain their admitted immutable policy.
It must enforce the whole request, including absent policy and network fields,
before returning a real success. Transport validation is not sandbox admission.

Run from the installed package root: python -B -m tools.executor.exec_server
No profile/configuration is read, written, or modified by this entry point.
"""

import asyncio
import base64
import binascii
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import threading
from urllib.parse import urlsplit
import uuid


OFFICIAL_COMMIT = "042fb41b7c813ac7999105e886b2b7aa715b5081"
MAX_MESSAGE_BYTES = 64 * 1024 * 1024  # Official stdio transport ceiling.
MAX_VALUE_NODES = 256 * 1024  # Official RPC complexity ceiling.
CAPABILITIES = frozenset({
    "networkProxyLaunch", "capabilityDiscoverySandbox", "environmentConfigRead",
    "httpHeaderEnvVars", "sandboxedFileStreaming", "shellSnapshotV2",
})
PROCESS_METHODS = frozenset({
    "process/start", "process/read", "process/write", "process/signal", "process/terminate",
})
FILE_METHODS = frozenset({
    "fs/readFile", "fs/open", "fs/readBlock", "fs/close", "fs/writeFile",
    "fs/createDirectory", "fs/getMetadata", "fs/canonicalize", "fs/readDirectory",
    "fs/walk", "fs/remove", "fs/copy",
})
BACKEND_METHODS = PROCESS_METHODS | FILE_METHODS | frozenset({
    "capabilityRoots/discoverV1", "environmentConfig/read", "http/request",
})
CONTROL_METHODS = frozenset({
    "environment/info", "environment/status", "process/signal", "process/terminate", "fs/close",
})
NOTIFICATIONS = frozenset({
    "process/output", "process/exited", "process/closed", "http/request/bodyDelta",
})


class RpcError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data

    def response(self, request_id):
        error = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return {"id": request_id, "error": error}


class ProtocolClosed(Exception):
    """A protocol violation closes the connection, as in the official server."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _nonfinite(_):
    raise ValueError("non-finite JSON number")


def encode_message(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def decode_message(line):
    """Reject ambiguity/unsupported envelopes, preserving signed i64/string IDs."""
    try:
        value = json.loads(line, object_pairs_hook=_object, parse_constant=_nonfinite)
        pending = [value]
        count = 0
        while pending:
            item = pending.pop()
            count += 1
            if count > MAX_VALUE_NODES:
                raise ValueError("JSON-RPC message exceeds value limit")
            if type(item) is dict:
                for key in item:
                    key.encode("utf-8", errors="strict")
                pending.extend(item.values())
            elif type(item) is list:
                pending.extend(item)
            elif type(item) is str:
                item.encode("utf-8", errors="strict")
            elif type(item) is float and not math.isfinite(item):
                raise ValueError("non-finite JSON number")
        if type(value) is not dict:
            raise ValueError("expected a JSON-RPC object")
        if "id" in value:
            request_id = value["id"]
            if not (type(request_id) is str or
                    type(request_id) is int and -(2**63) <= request_id < 2**63):
                raise ValueError("id must be a string or signed 64-bit integer")
        if "method" in value:
            if type(value["method"]) is not str:
                raise ValueError("method must be a string")
        elif "id" not in value or not ("result" in value or "error" in value):
            raise ValueError("expected request, notification, response, or error")
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        # The official server reports malformed messages with id=-1, not null.
        raise RpcError(-32600, "Malformed exec-server message") from error


def _fields(params, required, optional=()):
    if type(params) is not dict:
        raise RpcError(-32602, "params must be an object")
    if set(required) - params.keys():
        raise RpcError(-32602, "Missing required parameters: " + ", ".join(sorted(set(required) - params.keys())))
    # Fail closed on protocol extensions instead of dropping policy intent.
    unknown = params.keys() - set(required) - set(optional)
    if unknown:
        raise RpcError(-32602, "Unsupported parameters: " + ", ".join(sorted(unknown)))


def _type(value, kind, name):
    if type(value) is not kind:
        raise RpcError(-32602, name + " has an invalid type")


def _uri(value, name):
    _type(value, str, name)
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise RpcError(-32602, name + " must be an absolute file URI") from error
    if (parsed.scheme != "file" or not parsed.path.startswith("/") or
            parsed.query or parsed.fragment or "\x00" in value):
        raise RpcError(-32602, name + " must be an absolute file URI")


def _base64(value, name):
    _type(value, str, name)
    try:
        decoded = base64.b64decode(value, validate=True)
        if base64.b64encode(decoded).decode("ascii") != value:
            raise ValueError("noncanonical base64")
    except (ValueError, binascii.Error) as error:
        raise RpcError(-32602, name + " must contain canonical base64") from error


def validate_operation(method, params):
    """Validate known outer wire fields; keep full nested intent for admission."""
    schemas = {
        "process/start": ({"processId", "argv", "cwd", "env", "tty"}, {
            "envPolicy", "shellSnapshot", "pipeStdin", "arg0", "sandbox",
            "enforceManagedNetwork", "managedNetwork", "networkProxy"}),
        "process/read": ({"processId"}, {"afterSeq", "maxBytes", "waitMs"}),
        "process/write": ({"processId", "chunk", "writeId"}, set()),
        "process/signal": ({"processId", "signal"}, set()),
        "process/terminate": ({"processId"}, set()),
        "fs/readFile": ({"path"}, {"sandbox", "followSymlinks"}),
        "fs/open": ({"path", "handleId"}, {"sandbox"}),
        "fs/readBlock": ({"handleId", "offset", "len"}, set()),
        "fs/close": ({"handleId"}, set()),
        "fs/writeFile": ({"path", "dataBase64"}, {"sandbox", "followSymlinks"}),
        "fs/createDirectory": ({"path"}, {"sandbox", "recursive", "followSymlinks"}),
        "fs/getMetadata": ({"path"}, {"sandbox", "followSymlinks"}),
        "fs/canonicalize": ({"path"}, {"sandbox"}),
        "fs/readDirectory": ({"path"}, {"sandbox"}),
        "fs/walk": ({"path", "options"}, {"sandbox"}),
        "fs/remove": ({"path"}, {"sandbox", "recursive", "force", "followSymlinks"}),
        "fs/copy": ({"sourcePath", "destinationPath", "recursive"}, {"sandbox"}),
        "capabilityRoots/discoverV1": ({"roots"}, set()),
    }
    if method not in schemas:
        _type(params, dict, "params")
        return  # Optional HTTP/config schemas are the implementing backend's responsibility.
    _fields(params, *schemas[method])
    for key, value in params.items():
        if value is None and key in schemas[method][1]:
            if key in {"pipeStdin", "enforceManagedNetwork"}:
                raise RpcError(-32602, key + " cannot be null")
            continue
        if key in {"processId", "handleId", "writeId", "arg0", "signal"}:
            _type(value, str, key)
        elif key in {"path", "cwd", "sourcePath", "destinationPath"}:
            _uri(value, key)
        elif key in {"tty", "pipeStdin", "recursive", "force", "followSymlinks", "enforceManagedNetwork"}:
            _type(value, bool, key)
        elif key in {"offset", "len", "afterSeq", "maxBytes", "waitMs"}:
            if type(value) is not int or not 0 <= value < 2**64:
                raise RpcError(-32602, key + " must be an unsigned 64-bit integer")
        elif key in {"sandbox", "managedNetwork", "networkProxy", "envPolicy", "shellSnapshot", "options"}:
            _type(value, dict, key)
        elif key in {"chunk", "dataBase64"}:
            _base64(value, key)
        elif key == "argv":
            _type(value, list, key)
            for argument in value:
                _type(argument, str, "argv item")
        elif key == "env":
            _type(value, dict, key)
            for entry in value.values():
                _type(entry, str, "env value")
        elif key == "roots":
            _type(value, list, key)
            for root in value:
                _fields(root, {"id", "path"}, {"sandbox"})
                _type(root["id"], str, "root id")
                _uri(root["path"], "root path")
                if root.get("sandbox") is not None:
                    _type(root["sandbox"], dict, "root sandbox")
    if method == "process/signal" and params["signal"] != "interrupt":
        raise RpcError(-32602, "Unsupported process signal")


@dataclass(frozen=True)
class BackendCall:
    """Server-owned correlation plus a lossless, immutable request snapshot.

    The backend receives all fields unchanged, including full sandbox context.
    IDs are correlation, never authority. Backend handle lookup MUST be scoped
    by session_id and keep the policy acquired at creation; lifecycle calls
    cannot introduce a replacement policy. trace is telemetry, never policy.
    """
    session_id: str
    request_id: str | int
    method: str
    params_json: bytes
    trace_json: bytes | None = None

    @property
    def params(self):
        return json.loads(self.params_json)


class UnavailableBackend:
    supported_methods = frozenset()
    capabilities = frozenset()

    async def handle(self, call, notify):
        raise RpcError(-32601, "Native enforcement backend is not connected")

    async def close(self, session_id):
        """No processes or file handles were created by this backend."""


def local_environment_info():
    """Actual transport host metadata; native adapters supply their guest view."""
    shell_path = shutil.which("pwsh" if os.name == "nt" else "sh")
    if shell_path is None:
        shell_path = shutil.which("powershell" if os.name == "nt" else "bash")
    if shell_path is None:
        raise RuntimeError("No local shell can be described truthfully")
    return {
        "shell": {"name": Path(shell_path).stem, "path": shell_path},
        "cwd": Path.cwd().as_uri(),
        "userHomeDir": Path.home().as_uri(),
        "platformOs": "windows" if os.name == "nt" else platform.system().lower(),
        "temporaryDirectories": [Path(tempfile.gettempdir()).resolve().as_uri()],
        "tempDir": Path(tempfile.gettempdir()).resolve().as_uri(),
    }


class ExecServer:
    """One stdio connection/session with an explicitly supplied trusted backend.

    Backend interface: supported_methods/capabilities are immutable sets;
    async handle(BackendCall, notify(method, params)) returns the *real* wire
    result or raises RpcError; async close(session_id) must cancel/reap all
    descendants, close streams, and await native cleanup even on disconnect.
    Concurrency is bounded, with cleanup/health requests admitted separately.
    """
    def __init__(self, backend=None, *, environment_info=None, max_in_flight=128):
        self.backend = backend if backend is not None else UnavailableBackend()
        self.methods = frozenset(self.backend.supported_methods)
        self.features = frozenset(self.backend.capabilities)
        if self.methods - BACKEND_METHODS or self.features - CAPABILITIES:
            raise ValueError("Backend declares an unaudited method or capability")
        requirements = {
            "networkProxyLaunch": {"process/start"},
            "capabilityDiscoverySandbox": {"capabilityRoots/discoverV1"},
            "environmentConfigRead": {"environmentConfig/read"},
            "httpHeaderEnvVars": {"http/request"},
            "sandboxedFileStreaming": {"fs/open", "fs/readBlock", "fs/close"},
            "shellSnapshotV2": {"process/start"},
        }
        for feature in self.features:
            if not requirements[feature] <= self.methods:
                raise ValueError("Capability lacks its backend methods: " + feature)
        if type(max_in_flight) is not int or max_in_flight < 1:
            raise ValueError("max_in_flight must be positive")
        self.max_in_flight = max_in_flight
        self.info = json.loads(encode_message(environment_info if environment_info is not None else local_environment_info()))
        # Caller-provided metadata can never silently advertise capabilities.
        if "capabilities" in self.info:
            raise ValueError("Capabilities must come from the trusted backend declaration")
        _fields(self.info["shell"], {"name", "path"})
        _type(self.info["shell"]["name"], str, "shell name")
        _type(self.info["shell"]["path"], str, "shell path")
        self.info["capabilities"] = {name: name in self.features for name in sorted(CAPABILITIES)}
        self.session_id = None
        self.initialized = False
        self.closed = False
        self.pending = {}
        self.ordinary = 0
        self.control = 0
        self._emit = None

    async def notify(self, method, params):
        if self.closed or not self.initialized or self._emit is None:
            raise ProtocolClosed("No initialized notification channel")
        if method not in NOTIFICATIONS:
            raise ValueError("Unsupported backend notification")
        await self._emit({"method": method, "params": params})

    async def request(self, message):
        request_id, method = message["id"], message["method"]
        params = message.get("params")
        try:
            if method == "initialize":
                _fields(params, {"clientName"}, {"resumeSessionId"})
                _type(params["clientName"], str, "clientName")
                if params.get("resumeSessionId") is not None:
                    _type(params["resumeSessionId"], str, "resumeSessionId")
                if self.session_id is not None:
                    raise RpcError(-32600, "initialize may only be sent once per connection")
                if params.get("resumeSessionId") is not None:
                    raise RpcError(-32600, "Unknown session; stdio sessions cannot be resumed")
                self.session_id = str(uuid.uuid4())
                return {"id": request_id, "result": {"sessionId": self.session_id, "environmentInfo": self.info}}
            if method not in BACKEND_METHODS | {"environment/info", "environment/status"}:
                raise RpcError(-32601, "Unsupported exec-server method: " + method)
            if self.session_id is None or not self.initialized:
                raise RpcError(-32600, "Client must call initialize then send initialized")
            if method in {"environment/info", "environment/status"}:
                if params is not None and params != {}:
                    raise RpcError(-32602, "Method takes no parameters")
                result = self.info if method == "environment/info" else {"status": "ready"}
                return {"id": request_id, "result": result}
            validate_operation(method, params)
            if method not in self.methods:
                raise RpcError(-32601, "Native backend does not support " + method)
            if method == "process/start":
                for field, capability in (("networkProxy", "networkProxyLaunch"), ("shellSnapshot", "shellSnapshotV2")):
                    if params.get(field) is not None and capability not in self.features:
                        raise RpcError(-32602, "Unsupported capability: " + capability)
                if params.get("enforceManagedNetwork") and params.get("managedNetwork") is None:
                    raise RpcError(-32602, "Managed networking requires its enforcement context")
            if method == "fs/open" and params.get("sandbox") is not None and "sandboxedFileStreaming" not in self.features:
                raise RpcError(-32602, "Sandboxed file streaming is unsupported")
            call = BackendCall(self.session_id, request_id, method, encode_message(params),
                               encode_message(message["trace"]) if message.get("trace") is not None else None)
            result = await self.backend.handle(call, self.notify)
            if type(result) is not dict:
                raise RuntimeError("Backend returned no wire response object")
            encode_message(result)  # Serialization failures must never turn into a success.
            return {"id": request_id, "result": result}
        except RpcError as error:
            return error.response(request_id)
        except Exception:
            # No paths, command text, environment values, or backend secrets in errors.
            return RpcError(-32603, "Native backend or executor metadata failed").response(request_id)

    async def accept(self, message, emit):
        """Dispatch a decoded envelope. Handshake remains ordered; operations run concurrently."""
        if self.closed:
            raise ProtocolClosed("Connection is closed")
        self._emit = emit
        if "method" not in message:
            raise ProtocolClosed("Unexpected client response; no server request is pending")
        if "id" not in message:
            if message["method"] != "initialized" or self.session_id is None:
                raise ProtocolClosed("Unexpected notification or initialized before initialize")
            self.initialized = True
            return
        key = (type(message["id"]), message["id"])
        if key in self.pending:
            # Two simultaneous responses with one id would corrupt correlation.
            raise ProtocolClosed("Duplicate in-flight request id")
        if message["method"] == "initialize" or not self.initialized:
            await emit(await self.request(message))
            return
        control = message["method"] in CONTROL_METHODS
        if (self.control if control else self.ordinary) >= self.max_in_flight:
            await emit(RpcError(-32000, "Executor request capacity exhausted").response(message["id"]))
            return
        if control:
            self.control += 1
        else:
            self.ordinary += 1

        async def finish():
            try:
                await emit(await self.request(message))
            finally:
                self.pending.pop(key, None)
                if control:
                    self.control -= 1
                else:
                    self.ordinary -= 1

        task = asyncio.create_task(finish())
        self.pending[key] = task
        # Consume delivery exceptions; the transport also checks its write state.
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())

    async def close(self):
        if self.closed:
            return
        self.closed = True
        tasks = list(self.pending.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.backend.close(self.session_id)


async def _pipe_io(operation, *args):
    """Cancellable pipe I/O without blocking native cleanup or Python shutdown.

    Windows standard handles cannot generally use asyncio pipe transports. A
    daemon performs only one read or write/flush; it never owns native worker
    state. At most one reader and one serialized writer are active per stdio
    connection. If a peer leaves its pipe open forever, cancellation drops the
    awaited future and interpreter shutdown need not join that blocked pipe.
    Unlike asyncio.to_thread, this does not strand the default executor on EOF
    or a write failure while the peer still keeps stdin open.
    """
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def complete(value, error):
        if future.done():
            return
        if error is None:
            future.set_result(value)
        else:
            future.set_exception(error)

    def run():
        try:
            value, error = operation(*args), None
        except Exception as failure:
            value, error = None, failure
        try:
            loop.call_soon_threadsafe(complete, value, error)
        except RuntimeError:
            pass  # Event loop already closed after transport cancellation.

    threading.Thread(target=run, name="foldgpt-stdio-pipe", daemon=True).start()
    return await future


async def _read_frame(reader, limit):
    line = await _pipe_io(reader.readline, limit + 1)
    if not line:
        return None
    if line.endswith(b"\n"):
        line = line[:-1]
        if line.endswith(b"\r"):
            line = line[:-1]
    elif len(line) > limit and line.endswith(b"\r"):
        if await _pipe_io(reader.read, 1) == b"\n":
            line = line[:-1]
    if len(line) > limit:
        raise ProtocolClosed("Input exceeds stdio size limit")
    return line


async def serve_stdio(server, reader=None, writer=None, *, max_message_bytes=MAX_MESSAGE_BYTES):
    """NDJSON framing; stdout carries only protocol, never diagnostics or output."""
    reader = reader if reader is not None else sys.stdin.buffer
    writer = writer if writer is not None else sys.stdout.buffer
    write_lock = asyncio.Lock()
    failure = asyncio.Event()

    async def emit(message):
        try:
            data = encode_message(message)
            if len(data) > max_message_bytes:
                raise ProtocolClosed("Outbound message exceeds stdio size limit")

            def write():
                writer.write(data + b"\n")
                writer.flush()

            async with write_lock:
                if failure.is_set():
                    raise ProtocolClosed("Output channel is closed")
                await _pipe_io(write)
        except Exception as error:
            failure.set()
            raise ProtocolClosed("Output channel failed") from error

    try:
        while not failure.is_set():
            # One byte beyond the payload catches oversized unterminated input.
            next_frame = asyncio.create_task(_read_frame(reader, max_message_bytes))
            disconnected = asyncio.create_task(failure.wait())
            try:
                done, _ = await asyncio.wait({next_frame, disconnected}, return_when=asyncio.FIRST_COMPLETED)
                if disconnected in done:
                    raise ProtocolClosed("Output channel failed")
                line = next_frame.result()
            finally:
                for pending in (next_frame, disconnected):
                    if not pending.done():
                        pending.cancel()
                await asyncio.gather(next_frame, disconnected, return_exceptions=True)
            if line is None:
                break
            if not line.strip():
                continue
            try:
                message = decode_message(line)
            except RpcError as error:
                await emit(error.response(-1))
                continue
            await server.accept(message, emit)
    finally:
        # EOF is a disconnect, not a request to leave background native work alive.
        await server.close()


def main():
    try:
        asyncio.run(serve_stdio(ExecServer()))
    except (ProtocolClosed, BrokenPipeError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
