"""Session-bound read handles for the native, policy-bearing file backend.

Open pins a read-only inode through the native helper and receives exactly one
CLOEXEC descriptor over a private socketpair. Every block is a bounded native
pread, so cancellation can reap the helper without leaving a blocked I/O thread.
"""
import array
import asyncio
import base64
from dataclasses import dataclass
import errno
import fcntl
import json
import os
from pathlib import Path
import socket
import stat
import struct

from tools.executor.exec_server import RpcError, validate_operation
from tools.executor.native_files import NativeFilesBackend
from tools.executor.policy_intent import PolicyIntent, prepare_policy_intent
from tools.policy.managed_policy import GuestPath, PolicyError, parse_context

STREAM_METHODS = frozenset({"fs/open", "fs/readBlock", "fs/close"})
MAX_OPEN_HANDLES = 128  # Official FileReadHandleManager connection limit.
MAX_HANDLE_BYTES = 32  # Official MAX_FILE_READ_HANDLE_ID_BYTES.
MAX_BLOCK = 1024 * 1024  # Official FILE_READ_CHUNK_SIZE.
_PACKET = struct.Struct("<8sQQQQQ")


@dataclass(frozen=True)
class ReadHandle:
    handle_id: str
    fd: int
    session_id: str
    policy: PolicyIntent
    device: int
    inode: int


def _helper_error(diagnostic):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate diagnostic field")
            value[key] = item
        return value

    try:
        if type(diagnostic) is not bytes or len(diagnostic) > 512:
            raise ValueError("Invalid native diagnostic length")
        value = json.loads(diagnostic.decode("ascii"), object_pairs_hook=unique)
        allowed = {"invocation", "root-fd", "root-ownership", "channel", "open", "file-kind", "identity",
                   "reopen", "send", "read-fd", "allocation", "offset", "read", "output", "close"}
        if (type(value) is not dict or set(value) != {"stage", "errno"}
                or type(value["stage"]) is not str or value["stage"] not in allowed
                or type(value["errno"]) is not int or not 1 <= value["errno"] <= 4095):
            raise ValueError("Invalid native descriptor diagnostic")
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return RpcError(-32603, "Native descriptor helper violated its contract")
    number = value["errno"]
    code = -32004 if value["stage"] == "open" and number == errno.ENOENT else (
        -32600 if number in {errno.EINVAL, errno.EPERM, errno.EACCES} else -32603)
    return RpcError(code, "Native file-handle operation failed", value)


async def _finish_despite_cancellation(task):
    # Cleanup owns this bounded native child even if the transport cancels again.
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


async def _bounded_communicate(process, output_limit):
    async def receive(stream, limit):
        output = bytearray()
        while True:
            chunk = await stream.read(min(65536, limit + 1 - len(output)))
            if not chunk:
                return bytes(output)
            output.extend(chunk)
            if len(output) > limit:
                raise RpcError(-32603, "Native file helper output exceeds its contract")

    readers = [asyncio.create_task(receive(process.stdout, output_limit)),
               asyncio.create_task(receive(process.stderr, 512))]
    try:
        result = await asyncio.gather(*readers)
        await process.wait()
        return result
    finally:
        for reader in readers:
            if not reader.done():
                reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)


class NativeFileStreamsBackend(NativeFilesBackend):
    supported_methods = NativeFilesBackend.supported_methods | STREAM_METHODS
    capabilities = NativeFilesBackend.capabilities | frozenset({"sandboxedFileStreaming"})

    def __init__(self, helper, workspace, *, handle_helper, guest_workspace="/workspace"):
        self.handle_helper = str(Path(handle_helper).resolve(strict=True))
        self.handles = {}
        super().__init__(helper, workspace, guest_workspace=guest_workspace)

    async def _invoke(self, arguments, descriptors):
        spawning = asyncio.create_task(asyncio.create_subprocess_exec(
            self.handle_helper, *arguments, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            close_fds=True, pass_fds=tuple(descriptors), env={}))
        process = communication = None
        try:
            process = await asyncio.shield(spawning)
            self.process = process
            communication = asyncio.create_task(_bounded_communicate(process,
                int(arguments[3]) if arguments[0] == "read" else 0))
            output, diagnostic = await asyncio.wait_for(asyncio.shield(communication), 30)
            if process.returncode != 0:
                raise _helper_error(diagnostic)
            if diagnostic:
                raise RpcError(-32603, "Native descriptor helper emitted unexpected diagnostics")
            return output
        except asyncio.TimeoutError as error:
            raise RpcError(-32603, "Native file helper exceeded its execution deadline") from error
        finally:
            if process is None:
                process = await _finish_despite_cancellation(spawning)
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass

            async def reap():
                if communication is not None:
                    await asyncio.gather(communication, return_exceptions=True)

                async def drain(stream):
                    # Readers can have stopped at their contract bound while
                    # asyncio paused a full pipe. Drain after kill, in bounded
                    # pieces, so process.wait also observes pipe termination.
                    while await stream.read(65536):
                        pass

                await asyncio.gather(drain(process.stdout), drain(process.stderr), process.wait())

            try:
                await _finish_despite_cancellation(asyncio.create_task(reap()))
            finally:
                self.process = None

    async def _acquire(self, relative, expected):
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        received = []
        keep = None
        try:
            parent.set_inheritable(False)
            child.set_inheritable(False)
            output = await self._invoke(["open", str(self.root), relative, str(child.fileno()),
                                        str(expected.st_dev if expected else 0), str(expected.st_ino if expected else 0)],
                                       (self.root, child.fileno()))
            child.close()
            parent.setblocking(False)
            payload, ancillary, flags, _ = parent.recvmsg(_PACKET.size + 1,
                socket.CMSG_SPACE(256 * array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC)
            valid = len(ancillary) == 1
            for level, kind, raw in ancillary:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    numbers = array.array("i")
                    if len(raw) % numbers.itemsize:
                        valid = False
                    numbers.frombytes(raw[:len(raw) - len(raw) % numbers.itemsize])
                    received.extend(numbers)
                else:
                    valid = False
            if (output or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or not valid
                    or len(received) != 1 or len(payload) != _PACKET.size):
                raise RpcError(-32603, "Native descriptor transfer must contain exactly one complete descriptor")
            magic, device, inode, mode, uid, links = _PACKET.unpack(payload)
            fd = received[0]
            info = os.fstat(fd)
            file_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            if (magic != b"FGFDv1\0\0" or expected is None or (device, inode) != (expected.st_dev, expected.st_ino)
                    or (device, inode, mode, uid, links) != (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink)
                    or not stat.S_ISREG(info.st_mode) or uid != os.getuid() or links != 1
                    or file_flags & os.O_ACCMODE != os.O_RDONLY or file_flags & os.O_PATH
                    or not fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC):
                raise RpcError(-32603, "Received native descriptor identity or access differs")
            # Reaped helper + closed child endpoint implies EOF, with no second
            # packet/SCM_RIGHTS transfer. Queued excess rights close with socket.
            extra, excess, extra_flags, _ = parent.recvmsg(1,
                socket.CMSG_SPACE(256 * array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC)
            for level, kind, raw in excess:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    numbers = array.array("i")
                    numbers.frombytes(raw[:len(raw) - len(raw) % numbers.itemsize])
                    received.extend(numbers)
            # Linux echoes MSG_CMSG_CLOEXEC in msg_flags even at EOF.
            if extra or excess or extra_flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                raise RpcError(-32603, "Native descriptor helper sent extra packets")
            keep = fd
            return fd
        finally:
            child.close()
            parent.close()
            for fd in received:
                if fd != keep:
                    os.close(fd)

    def _drop(self, identifier):
        handle = self.handles.pop(identifier, None)
        if handle is not None:
            os.close(handle.fd)

    async def handle(self, call, notify):
        if call.method not in STREAM_METHODS:
            return await super().handle(call, notify)
        async with self.lock:
            if self.closed:
                raise RpcError(-32000, "Filesystem session is closed")
            if self.session is None:
                self.session = call.session_id
            elif self.session != call.session_id:
                raise RpcError(-32000, "Workspace belongs to another executor session")
            params = call.params
            validate_operation(call.method, params)
            identifier = params["handleId"]
            if len(identifier.encode("utf-8")) > MAX_HANDLE_BYTES:
                raise RpcError(-32600, "File read handle ID exceeds the official 32-byte bound")
            if call.method == "fs/open":
                if identifier in self.handles:
                    raise RpcError(-32600, "File read handle already exists")
                if len(self.handles) >= MAX_OPEN_HANDLES:
                    raise RpcError(-32600, "At most 128 file reads may be open per connection")
                try:
                    intent = prepare_policy_intent(params.get("sandbox"), session_id=call.session_id,
                        request_id=str(call.request_id), method=call.method)
                    policy = parse_context(intent.context_json)
                    path = GuestPath.from_uri(params["path"])
                    if not self.mount.contains(path) or path == self.mount or not policy.decide_uri(path.uri).can_read:
                        raise PermissionError("Filesystem policy denies the requested file handle")
                    _, _, _, nodes = self._inspect(policy)
                    parts = path.parts[len(self.mount.parts):]
                    fd = await self._acquire("/".join(parts), nodes.get(parts))
                except (ValueError, KeyError, PolicyError, PermissionError) as error:
                    raise RpcError(-32000, str(error)) from error
                except OSError as error:
                    raise RpcError(-32603, "Native file descriptor acquisition failed") from error
                try:
                    info = os.fstat(fd)
                    self.handles[identifier] = ReadHandle(identifier, fd, call.session_id, intent, info.st_dev, info.st_ino)
                except BaseException:
                    os.close(fd)
                    raise
                return {"handleId": identifier}
            if call.method == "fs/close":
                self._drop(identifier)  # Official close is idempotent for unknown IDs.
                return {}
            length, offset = params["len"], params["offset"]
            if not 1 <= length <= MAX_BLOCK:
                raise RpcError(-32600, "File read block length must be between 1 and 1048576")
            handle = self.handles.get(identifier)
            if handle is None:
                raise RpcError(-32004, "Unknown file read handle")
            if handle.session_id != call.session_id:
                raise RpcError(-32000, "File read handle belongs to another session")
            try:
                data = await self._invoke(["read", str(handle.fd), str(offset), str(length)], (handle.fd,))
                if len(data) > length:
                    raise RpcError(-32603, "Native file block exceeded the requested length")
                return {"chunk": base64.b64encode(data).decode("ascii"), "eof": len(data) < length}
            except BaseException:
                self._drop(identifier)  # Upstream closes a handle on a read I/O error.
                raise

    async def close(self, session_id):
        async with self.lock:
            if not self.closed:
                if self.session is not None and self.session != session_id:
                    raise RpcError(-32000, "Cannot close a different filesystem session")
                for identifier in list(self.handles):
                    self._drop(identifier)
                self.closed = True
                os.close(self.root)
