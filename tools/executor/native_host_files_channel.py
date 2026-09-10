"""Credentialed private host/UI file channel, separate from model and bootstrap.

The trusted owner supplies a connected anonymous socketpair and existing host
authority. Complete write payloads and an explicit commit are admitted before
any native mutation. There is no listener or request-selectable authority.
"""
import array
import asyncio
import base64
import binascii
import json
import os
import socket
import struct

from tools.executor.exec_server import RpcError, _object
from tools.executor.native_host_files import HostFileAuthority
from tools.executor.native_processes import _fd_ready, _finish

SCHEMA = "foldgpt.host-files.v1"
CHUNK_BYTES = 32768
MAX_DATA_BYTES = 16 * 1024 * 1024
MAX_PACKET_BYTES = 65536
OPERATIONS = ("readFile", "writeFile", "getMetadata", "canonicalize", "readDirectory", "createDirectory")


class ChannelViolation(Exception):
    """Fatal private protocol violation; the channel cannot be reused."""


class HostFileChannel:
    def __init__(self, descriptor, authority, *, peer):
        if type(authority) is not HostFileAuthority:
            raise TypeError("Existing host file authority required")
        if (type(peer) is not tuple or len(peer) != 3
                or any(type(value) is not int for value in peer)
                or not 0 < peer[0] < 2**31 or any(not 0 <= value < 2**32 for value in peer[1:])):
            raise ValueError("Actual kernel peer PID/UID/GID required")
        if (type(descriptor) is not socket.socket
                or descriptor.family != socket.AF_UNIX
                or descriptor.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_SEQPACKET
                or descriptor.getsockname() not in ("", b"")
                or descriptor.getpeername() not in ("", b"")):
            raise ValueError("Private connected anonymous AF_UNIX SOCK_SEQPACKET required")
        descriptor.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        descriptor.set_inheritable(False)
        descriptor.setblocking(False)
        self.socket, self.authority, self.peer = descriptor, authority, peer
        self.started = False

    async def _receive(self):
        while True:
            try:
                data, controls, flags, _ = self.socket.recvmsg(MAX_PACKET_BYTES,
                    socket.CMSG_SPACE(12) + socket.CMSG_SPACE(256 * 4), socket.MSG_CMSG_CLOEXEC)
                break
            except BlockingIOError:
                await _fd_ready(self.socket.fileno())
            except InterruptedError:
                continue
        actual, invalid = None, False
        for level, kind, payload in controls:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                invalid = True
                rights = array.array("i")
                rights.frombytes(payload[:len(payload) - len(payload) % rights.itemsize])
                for descriptor in rights:
                    os.close(descriptor)
            elif level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS and len(payload) == 12 and actual is None:
                actual = struct.unpack("iII", payload)
            else:
                invalid = True
        if not data:
            raise EOFError("Host peer disconnected")
        if invalid or actual != self.peer or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
            raise ChannelViolation("Host message credentials/ancillary data rejected")
        return data

    async def _send(self, value):
        data = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")
        if len(data) > MAX_PACKET_BYTES:
            raise ChannelViolation("Host response exceeds packet bound")
        credentials = [(socket.SOL_SOCKET, socket.SCM_CREDENTIALS,
            struct.pack("iII", os.getpid(), os.getuid(), os.getgid()))]
        while True:
            try:
                sent = self.socket.sendmsg([data], credentials, socket.MSG_NOSIGNAL)
                break
            except BlockingIOError:
                await _fd_ready(self.socket.fileno(), writing=True)
            except InterruptedError:
                continue
        if sent != len(data):
            raise ChannelViolation("Incomplete host response packet")

    @staticmethod
    def _json(data):
        def invalid_constant(_):
            raise ValueError("Non-finite JSON constant")
        try:
            value = json.loads(data.decode("utf-8"), object_pairs_hook=_object, parse_constant=invalid_constant)
            if type(value) is not dict:
                raise ValueError("Expected one JSON object")
            return value
        except (ValueError, UnicodeError, RecursionError, TypeError) as error:
            raise ChannelViolation(str(error)) from error

    @classmethod
    def _request(cls, data, expected_id):
        value = cls._json(data)
        if type(value.get("id")) is not int or value["id"] != expected_id or not 1 <= expected_id < 2**53:
            raise ChannelViolation("Request ID is not the next exact integer")
        op = value.get("op")
        keys = {"id", "op", "path"}
        if op == "getMetadata":
            keys.add("followSymlinks")
            if type(value.get("followSymlinks")) is not bool:
                raise ChannelViolation("Explicit metadata followSymlinks required")
        elif op == "createDirectory":
            keys.add("recursive")
            if type(value.get("recursive")) is not bool:
                raise ChannelViolation("Explicit directory recursive flag required")
        elif op == "writeFile":
            keys.update(("bytes", "chunks"))
            size, chunks = value.get("bytes"), value.get("chunks")
            if (type(size) is not int or type(chunks) is not int or not 0 <= size <= MAX_DATA_BYTES
                    or chunks != (size + CHUNK_BYTES - 1) // CHUNK_BYTES):
                raise ChannelViolation("Write requires exact bounded byte and chunk counts")
        if set(value) != keys or op not in OPERATIONS or type(value.get("path")) is not str:
            raise ChannelViolation("Unexpected host request shape")
        return value

    async def _collect_write(self, request):
        data = bytearray()
        for index in range(request["chunks"]):
            chunk = self._json(await self._receive())
            if (set(chunk) != {"type", "id", "index", "dataBase64"} or chunk.get("type") != "chunk"
                    or type(chunk.get("id")) is not int or chunk["id"] != request["id"]
                    or type(chunk.get("index")) is not int or chunk["index"] != index
                    or type(chunk.get("dataBase64")) is not str):
                raise ChannelViolation("Unexpected host write chunk shape or sequence")
            encoded = chunk["dataBase64"]
            expected = min(CHUNK_BYTES, request["bytes"] - len(data))
            if len(encoded) != ((expected + 2) // 3) * 4:
                raise ChannelViolation("Write chunk length does not match announced bytes")
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as error:
                raise ChannelViolation("Write chunk is not valid base64") from error
            if len(decoded) != expected or base64.b64encode(decoded).decode("ascii") != encoded:
                raise ChannelViolation("Write chunk is not the exact canonical payload")
            data.extend(decoded)
        commit = self._json(await self._receive())
        if (set(commit) != {"type", "id"} or commit.get("type") != "commit"
                or type(commit.get("id")) is not int or commit["id"] != request["id"]
                or len(data) != request["bytes"]):
            raise ChannelViolation("Write requires a complete payload and exact commit frame")
        return bytes(data)

    async def _respond(self, request, phase, write_data):
        number, op, path = request["id"], request["op"], request["path"]
        try:
            if op == "readFile":
                data = await self.authority.read_file(path)
            elif op == "readDirectory":
                result = await self.authority.read_directory(path)
                data = json.dumps(result, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            elif op == "getMetadata":
                result = await self.authority.get_metadata(path, follow_symlinks=request["followSymlinks"])
            elif op == "canonicalize":
                result = {"path": await self.authority.canonicalize(path)}
            elif op == "writeFile":
                await self.authority.write_file(path, write_data)
                result = {}
            else:
                await self.authority.create_directory(path, recursive=request["recursive"])
                result = {}
            if op in ("readFile", "readDirectory"):
                if len(data) > MAX_DATA_BYTES:
                    raise RpcError(-32000, "Host result exceeds admitted data bound")
                chunks = (len(data) + CHUNK_BYTES - 1) // CHUNK_BYTES
                for index, offset in enumerate(range(0, len(data), CHUNK_BYTES)):
                    await self._send({"type": "chunk", "id": number, "index": index,
                        "dataBase64": base64.b64encode(data[offset:offset + CHUNK_BYTES]).decode("ascii")})
                result = {"bytes": len(data), "chunks": chunks}
        except RpcError as error:
            await self._send({"type": "error", "id": number,
                "error": {"code": error.code, "message": error.message}})
        else:
            await self._send({"type": "result", "id": number, "result": result})
        phase["sent"] = True

    async def run(self):
        if self.started:
            raise ChannelViolation("Host channel cannot be restarted")
        self.started = True
        outgoing = incoming = None
        try:
            await self._send({"type": "ready", "schema": SCHEMA,
                "sessionId": self.authority._session_id, "workspaceRoot": self.authority.workspace_root_uri,
                "chunkBytes": CHUNK_BYTES, "maxDataBytes": MAX_DATA_BYTES,
                "maxPacketBytes": MAX_PACKET_BYTES, "operations": list(OPERATIONS)})
            pending, number = None, 1
            while True:
                request = self._request(await self._receive() if pending is None else pending, number)
                write_data = await self._collect_write(request) if request["op"] == "writeFile" else None
                phase = {"sent": False}
                async def monitor():
                    packet = await self._receive()
                    return packet, phase["sent"]
                outgoing = asyncio.create_task(self._respond(request, phase, write_data))
                incoming = asyncio.create_task(monitor())
                await asyncio.wait((outgoing, incoming), return_when=asyncio.FIRST_COMPLETED)
                pending = None
                if incoming.done():
                    pending, after_response = incoming.result()
                    if not after_response:
                        raise ChannelViolation("A second request arrived before the terminal response")
                else:
                    incoming.cancel()
                    await asyncio.gather(incoming, return_exceptions=True)
                await outgoing
                outgoing = incoming = None
                number += 1
        except EOFError:
            return
        finally:
            tasks = [task for task in (outgoing, incoming) if task is not None]
            for task in tasks:
                if not task.done(): task.cancel()
            if tasks:
                await _finish(asyncio.gather(*tasks, return_exceptions=True))
            self.socket.close()
