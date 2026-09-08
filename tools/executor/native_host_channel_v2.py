"""Multiplexed private human filesystem/process channel, explicitly version 2.

Uses the same one anonymous host SEQPACKET FD. Model/configuration FD roles and
version-1 production remain unchanged. Every process read returns one bounded
real event, so output backpressure never prevents an independent terminate RPC.
"""
import asyncio
import base64
import binascii
import importlib
import uuid

from tools.executor.exec_server import RpcError
from tools.executor.native_host_files_channel import (
    CHUNK_BYTES, MAX_DATA_BYTES, MAX_PACKET_BYTES, OPERATIONS,
    ChannelViolation, HostFileChannel,
)
from tools.executor.native_processes import _finish

HostProcesses = importlib.import_module("tools.executor.bionic-supervisor.host_processes").HostProcesses
SCHEMA = "foldgpt.host.v2"
PROCESS_OPERATIONS = ("processStart", "processRead", "processWrite", "processTerminate")
MAX_PENDING = 128


class HostChannelV2(HostFileChannel):
    def __init__(self, descriptor, authority, *, processes, peer):
        super().__init__(descriptor, authority, peer=peer)
        if type(processes) is not HostProcesses or processes.authority is not authority:
            raise TypeError("Version 2 requires its actual separately owned human processes")
        if any(value is not None for value in (processes.limits.wall_ms, processes.limits.output_bytes, processes.limits.cpu_seconds)):
            raise ValueError("Host channel v2 requires uncapped streams and no hidden process timer")
        self.processes = processes
        self.send_lock = asyncio.Lock()
        self.failed = asyncio.Event()
        self.failure = None
        self.tasks = {}
        self.live = {}
        self.file_request = None
        self.upload = None

    async def _send(self, value):
        # _fd_ready has one writable registration per FD. Serialize packet
        # writes only; never hold this lock while waiting for a file/process.
        async with self.send_lock:
            await super()._send(value)

    @staticmethod
    def _bytes(value):
        if type(value) is not str or len(value) > ((CHUNK_BYTES + 2) // 3) * 4:
            raise ChannelViolation("Host process input exceeds its packet bound")
        try:
            data = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ChannelViolation("Invalid host process base64") from error
        if len(data) > CHUNK_BYTES or base64.b64encode(data).decode("ascii") != value:
            raise ChannelViolation("Host process input is not canonical bounded base64")
        return data

    def _process_request(self, request, number):
        if type(request.get("id")) is not int or request["id"] != number or not 1 <= number < 2**53:
            raise ChannelViolation("Host request ID differs from the next exact integer")
        op = request.get("op")
        if op == "processStart":
            if (set(request) != {"id", "op", "command", "cwd", "environment", "pipeStdin"}
                    or type(request["command"]) is not list or not request["command"]
                    or len(request["command"]) > 256
                    or any(type(value) is not str or "\0" in value for value in request["command"])
                    or type(request["cwd"]) is not str
                    or type(request["environment"]) is not dict
                    or type(request["pipeStdin"]) is not bool):
                raise ChannelViolation("Unexpected native host process start shape")
        else:
            keys = {"id", "op", "processId"}
            if op == "processWrite":
                keys.update(("dataBase64", "closeStdin"))
                if type(request.get("closeStdin")) is not bool:
                    raise ChannelViolation("Explicit host stdin close flag required")
                self._bytes(request.get("dataBase64"))
            if (op not in PROCESS_OPERATIONS or set(request) != keys
                    or type(request.get("processId")) is not str
                    or len(request["processId"]) != 32
                    or any(c not in "0123456789abcdef" for c in request["processId"])):
                raise ChannelViolation("Unexpected native host process request shape")
        return request

    def _start_task(self, request, data=None):
        number = request["id"]
        async def execute():
            if request["op"] in OPERATIONS:
                try:
                    await self._respond(request, {"sent": False}, data)
                finally:
                    self.file_request = None
            else:
                try:
                    result = await self._process(request)
                except RpcError as error:
                    await self._send({"type": "error", "id": number,
                        "error": {"code": error.code, "message": error.message}})
                else:
                    await self._send({"type": "result", "id": number, "result": result})
        task = asyncio.create_task(execute())
        self.tasks[number] = task
        def complete(done):
            self.tasks.pop(number, None)
            if not done.cancelled() and done.exception() is not None:
                self.failure = done.exception()
                self.failed.set()
        task.add_done_callback(complete)

    async def _process(self, request):
        op = request["op"]
        if op == "processStart":
            if len(self.live) >= MAX_PENDING:
                raise RpcError(-32000, "Host process registry capacity exhausted")
            key = uuid.uuid4().hex
            events = asyncio.Queue(maxsize=128)
            slot = {"events": events, "record": None, "reading": False, "writing": False}
            self.live[key] = slot
            async def notify(method, params):
                await events.put((method, params))
            try:
                slot["record"] = await self.processes.spawn(key, request["command"], request["cwd"],
                    request["environment"], pipe_stdin=request["pipeStdin"], notify=notify)
            except BaseException:
                self.live.pop(key, None)
                raise
            return {"processId": key}
        slot = self.live.get(request["processId"])
        if slot is None or slot["record"] is None:
            raise RpcError(-32600, "Unknown started host process")
        record = slot["record"]
        if op == "processTerminate":
            # This acknowledges cancellation admission, not descendant cleanup.
            self.processes._terminate(record)
            return {}
        if op == "processWrite":
            if slot["writing"]:
                raise ChannelViolation("Concurrent stdin writes cannot reorder byte ownership")
            slot["writing"] = True
            try:
                await self.processes.write(record, self._bytes(request["dataBase64"]),
                    close_stdin=request["closeStdin"])
            finally:
                slot["writing"] = False
            return {}
        if slot["reading"]:
            raise ChannelViolation("Only one consumer may own a process event stream")
        slot["reading"] = True
        try:
            read = asyncio.create_task(slot["events"].get())
            try:
                await asyncio.wait((read, record.notifier), return_when=asyncio.FIRST_COMPLETED)
                if not read.done():
                    if slot["events"].empty():
                        raise RpcError(-32603, record.failure or "Native process ended without its complete event stream")
                    # The final events are already queued and remain owned.
                    await read
                method, params = read.result()
            finally:
                if not read.done():
                    read.cancel()
                await asyncio.gather(read, return_exceptions=True)
            event = {"seq": params["seq"]}
            if method == "process/output":
                data = self._bytes(params["chunk"])
                event.update(type="output", stream=params["stream"], dataBase64=base64.b64encode(data).decode("ascii"))
            elif method == "process/exited":
                event.update(type="exited", exitCode=params["exitCode"])
            elif method == "process/closed":
                await _finish(record.finished)
                await _finish(record.notifier)
                if not record.closed or record.native_result is None or not record.native_result["cleanupComplete"]:
                    raise RpcError(-32603, "Host close lacks native cleanup proof")
                event.update(type="closed", failure=record.failure)
                self.live.pop(record.key, None)
                self.processes.processes.pop((record.session, record.key), None)
            else:
                raise ChannelViolation("Unexpected native host event")
            return {"event": event}
        finally:
            slot["reading"] = False

    async def run(self):
        if self.started:
            raise ChannelViolation("Host channel cannot be restarted")
        self.started = True
        incoming = None
        failure = asyncio.create_task(self.failed.wait())
        try:
            await self._send({"type": "ready", "schema": SCHEMA,
                "sessionId": self.authority._session_id, "workspaceRoot": self.authority.workspace_root_uri,
                "chunkBytes": CHUNK_BYTES, "maxDataBytes": MAX_DATA_BYTES,
                "maxPacketBytes": MAX_PACKET_BYTES, "maxPendingRequests": MAX_PENDING,
                "operations": [*OPERATIONS, *PROCESS_OPERATIONS]})
            number = 1
            while True:
                incoming = asyncio.create_task(self._receive())
                await asyncio.wait((incoming, failure), return_when=asyncio.FIRST_COMPLETED)
                if failure.done():
                    raise self.failure
                data = incoming.result()
                incoming = None
                packet = self._json(data)
                if packet.get("type") in ("chunk", "commit"):
                    upload = self.upload
                    if upload is None or type(packet.get("id")) is not int or packet["id"] != upload["request"]["id"]:
                        raise ChannelViolation("Upload frame has no owned write request")
                    if packet["type"] == "chunk":
                        if set(packet) != {"type", "id", "index", "dataBase64"} or type(packet["index"]) is not int or packet["index"] != upload["chunks"]:
                            raise ChannelViolation("Invalid multiplexed file chunk sequence")
                        decoded = self._bytes(packet["dataBase64"])
                        expected = min(CHUNK_BYTES, upload["request"]["bytes"] - len(upload["data"]))
                        if not decoded or len(decoded) != expected:
                            raise ChannelViolation("Upload chunk differs from exact announced size")
                        upload["data"].extend(decoded)
                        upload["chunks"] += 1
                    else:
                        if (set(packet) != {"type", "id"} or len(upload["data"]) != upload["request"]["bytes"]
                                or upload["chunks"] != upload["request"]["chunks"]):
                            raise ChannelViolation("Write commit lacks its complete bounded payload")
                        self.upload = None
                        self._start_task(upload["request"], bytes(upload["data"]))
                    continue
                if len(self.tasks) + (self.upload is not None) >= MAX_PENDING:
                    raise ChannelViolation("Host in-flight request allowance exceeded")
                if packet.get("op") in OPERATIONS:
                    request = self._request(data, number)
                    if self.file_request is not None:
                        raise ChannelViolation("Only one filesystem exchange may own staged bytes")
                    self.file_request = number
                    if request["op"] == "writeFile":
                        self.upload = {"request": request, "data": bytearray(), "chunks": 0}
                    else:
                        self._start_task(request)
                else:
                    self._start_task(self._process_request(packet, number))
                number += 1
        except EOFError:
            return
        finally:
            tasks = list(self.tasks.values()) + [task for task in (incoming, failure) if task is not None]
            for task in tasks:
                if not task.done(): task.cancel()
            self.upload = None
            self.socket.close()
            # Close the independent human owner concurrently with cancellation
            # of file requests waiting for its lease. Reaping stays native.
            await _finish(asyncio.gather(*tasks, self.processes.close(self.authority._session_id), return_exceptions=True))
