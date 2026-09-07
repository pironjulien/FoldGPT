"""Private, credentialed bootstrap reads; never registered as model ExecServer RPC.

Only a trusted owner can supply the already connected anonymous socketpair,
actual peer credentials and an existing in-process BootstrapReadAuthority.
There is no listener, endpoint path, request policy or serialized authority.
"""
import array
import asyncio
import base64
import json
import os
import socket
import struct

from tools.executor.exec_server import RpcError, _object
from tools.executor.native_bootstrap_files import BootstrapReadAuthority
from tools.executor.native_processes import _fd_ready, _finish

SCHEMA = "foldgpt.bootstrap-files.v1"
CHUNK_BYTES = 32768
MAX_DATA_BYTES = 16 * 1024 * 1024
MAX_PACKET_BYTES = 65536
OPERATIONS = ("readFile", "getMetadata", "canonicalize", "readDirectory")


class ChannelViolation(Exception):
    """The private channel must be closed without accepting another request."""


class BootstrapReadChannel:
    def __init__(self, descriptor, authority, *, peer):
        if type(authority) is not BootstrapReadAuthority:
            raise TypeError("Existing bootstrap authority required")
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
                actual = struct.unpack("3i", payload)
            else:
                invalid = True
        if not data:
            raise EOFError("Bootstrap peer disconnected")
        if invalid or actual != self.peer or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
            raise ChannelViolation("Bootstrap message credentials/ancillary data rejected")
        return data

    async def _send(self, value):
        data = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")
        if len(data) > MAX_PACKET_BYTES:
            raise ChannelViolation("Bootstrap response exceeds packet bound")
        credentials = [(socket.SOL_SOCKET, socket.SCM_CREDENTIALS,
            struct.pack("3i", os.getpid(), os.getuid(), os.getgid()))]
        while True:
            try:
                sent = self.socket.sendmsg([data], credentials, socket.MSG_NOSIGNAL)
                break
            except BlockingIOError:
                await _fd_ready(self.socket.fileno(), writing=True)
            except InterruptedError:
                continue
        if sent != len(data):
            raise ChannelViolation("Incomplete bootstrap response packet")

    @staticmethod
    def _request(data, expected_id):
        def invalid_constant(_):
            raise ValueError("Non-finite JSON constant")
        try:
            value = json.loads(data.decode("utf-8"), object_pairs_hook=_object, parse_constant=invalid_constant)
            if type(value) is not dict or type(value.get("id")) is not int or value["id"] != expected_id or expected_id >= 2**53:
                raise ValueError("Request ID is not the next exact integer")
            keys = {"id", "op", "path"}
            if value.get("op") == "getMetadata":
                keys.add("followSymlinks")
                if type(value.get("followSymlinks")) is not bool:
                    raise ValueError("Explicit metadata followSymlinks required")
            if set(value) != keys or value.get("op") not in OPERATIONS or type(value.get("path")) is not str:
                raise ValueError("Unexpected bootstrap request shape")
            return value
        except (ValueError, UnicodeError, RecursionError, TypeError) as error:
            raise ChannelViolation(str(error)) from error

    async def _respond(self, request, phase):
        number, op, path = request["id"], request["op"], request["path"]
        try:
            if op == "readFile":
                data = await self.authority.read_file(path)
            elif op == "readDirectory":
                result = await self.authority.read_directory(path)
                data = json.dumps(result, ensure_ascii=True, separators=(",", ":")).encode("ascii")
            elif op == "getMetadata":
                result = await self.authority.get_metadata(path, follow_symlinks=request["followSymlinks"])
            else:
                result = {"path": await self.authority.canonicalize(path)}
            if op in ("readFile", "readDirectory"):
                if len(data) > MAX_DATA_BYTES:
                    raise RpcError(-32000, "Bootstrap result exceeds admitted data bound")
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
            raise ChannelViolation("Bootstrap channel cannot be restarted")
        self.started = True
        outgoing = incoming = None
        try:
            await self._send({"type": "ready", "schema": SCHEMA,
                "sessionId": self.authority._session_id, "discoveryRoot": self.authority.discovery_root_uri,
                "chunkBytes": CHUNK_BYTES, "maxDataBytes": MAX_DATA_BYTES,
                "maxPacketBytes": MAX_PACKET_BYTES, "operations": list(OPERATIONS)})
            pending, number = None, 1
            while True:
                request = self._request(await self._receive() if pending is None else pending, number)
                phase = {"sent": False}
                async def monitor():
                    packet = await self._receive()
                    return packet, phase["sent"]
                outgoing = asyncio.create_task(self._respond(request, phase))
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
                # Await the authority's real helper reaping before releasing the
                # channel. The native owner retains global cleanup responsibility.
                await _finish(asyncio.gather(*tasks, return_exceptions=True))
            self.socket.close()
