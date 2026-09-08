"""Startup-only delivery of direct native model/configuration/UI channels.

The installed owner supplies the workspace, backend and private endpoint path.
No executable, policy, workspace or authority is selected by the client packet.
The existing native owner remains responsible for final reaping/quarantine.
"""
import array
import asyncio
import json
import os
from pathlib import Path
import socket
import stat
import struct

from tools.executor.exec_server import ExecServer, _object, serve_stdio
from tools.executor.native_bootstrap_channel import BootstrapReadChannel
from tools.executor.native_bootstrap_files import create_bootstrap_read_authority
from tools.executor.native_host_files import create_host_file_authority
from tools.executor.native_host_files_channel import HostFileChannel
from tools.executor.native_processes import _fd_ready, _finish

SCHEMA = "foldgpt.native-runtime.v1"
MAX_PACKET = 4096
STARTUP_SECONDS = 30


class SessionExecServer(ExecServer):
    """Expose completion of the real protocol handshake to its trusted owner."""
    def __init__(self, backend, *, environment_info):
        super().__init__(backend, environment_info=environment_info)
        self.session_ready = asyncio.Event()

    async def accept(self, message, emit):
        await super().accept(message, emit)
        if self.initialized and self.session_id is not None:
            self.session_ready.set()


async def _receive(endpoint, peer):
    while True:
        try:
            data, controls, flags, _ = endpoint.recvmsg(MAX_PACKET,
                socket.CMSG_SPACE(12) + socket.CMSG_SPACE(256 * 4), socket.MSG_CMSG_CLOEXEC)
            break
        except BlockingIOError:
            await _fd_ready(endpoint.fileno())
        except InterruptedError:
            continue
    actual, invalid = None, False
    for level, kind, value in controls:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            invalid = True
            rights = array.array("i")
            rights.frombytes(value[:len(value) - len(value) % rights.itemsize])
            for descriptor in rights:
                os.close(descriptor)
        elif level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS and len(value) == 12 and actual is None:
            actual = struct.unpack("iII", value)
        else:
            invalid = True
    if not data:
        raise EOFError("Native runtime controller disconnected")
    if invalid or actual != peer or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
        raise ValueError("Native runtime acquisition credentials or ancillary data differ")
    return data


async def _send(endpoint, value, descriptors=()):
    payload = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")
    if len(payload) > MAX_PACKET:
        raise ValueError("Native runtime startup packet exceeds its bound")
    controls = [(socket.SOL_SOCKET, socket.SCM_CREDENTIALS,
                 struct.pack("iII", os.getpid(), os.getuid(), os.getgid()))]
    if descriptors:
        controls.append((socket.SOL_SOCKET, socket.SCM_RIGHTS,
                         array.array("i", [descriptor.fileno() for descriptor in descriptors])))
    while True:
        try:
            count = endpoint.sendmsg([payload], controls, socket.MSG_NOSIGNAL)
            break
        except BlockingIOError:
            await _fd_ready(endpoint.fileno(), writing=True)
        except InterruptedError:
            continue
    if count != len(payload):
        raise ValueError("Native runtime startup packet is incomplete")


class NativeRuntimeAcquisition:
    """Own one private listener and one non-replayable controller acquisition.

    Closing this transport cancels its tasks and awaits the server's existing
    cleanup. Its return alone never certifies the Android owner's waitpid.
    """
    def __init__(self, path, server, *, controller_uid):
        if type(server) is not SessionExecServer or server.session_id is not None:
            raise TypeError("A fresh native session server is required")
        if type(controller_uid) is not int or controller_uid <= 0 or controller_uid != os.getuid():
            raise ValueError("Runtime acquisition requires its real nonroot application UID")
        path = Path(path)
        if not path.is_absolute() or str(path) != os.path.realpath(path) or len(os.fsencode(path)) >= 108:
            raise ValueError("Runtime endpoint must have a canonical bounded Unix path")
        workspace = Path(server.backend.mount.path)
        if path.is_relative_to(workspace) or workspace.is_relative_to(path.parent):
            raise ValueError("Runtime endpoint must be outside the native workspace")
        self.directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self.listener = self.connection = None
        self.identity = None
        self.path, self.server, self.uid = path, server, controller_uid
        self.started = False
        try:
            directory = os.fstat(self.directory_fd)
            if directory.st_uid != self.uid or directory.st_mode & 0o077:
                raise ValueError("Runtime endpoint directory must be private to its application")
            self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            self.listener.set_inheritable(False)
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            self.listener.bind(str(path))
            info = os.stat(path.name, dir_fd=self.directory_fd, follow_symlinks=False)
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != self.uid:
                raise ValueError("New runtime endpoint has unexpected identity")
            self.identity = (info.st_dev, info.st_ino)
            os.chmod(path.name, 0o600, dir_fd=self.directory_fd, follow_symlinks=False)
            self.listener.listen(1)
            self.listener.setblocking(False)
        except BaseException:
            self.close_endpoint()
            raise

    def close_endpoint(self):
        for endpoint in (self.listener, self.connection):
            if endpoint is not None:
                endpoint.close()
        self.listener = self.connection = None
        if self.directory_fd is not None:
            try:
                if self.identity is not None:
                    current = os.stat(self.path.name, dir_fd=self.directory_fd, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) == self.identity and stat.S_ISSOCK(current.st_mode):
                        os.unlink(self.path.name, dir_fd=self.directory_fd)
            except FileNotFoundError:
                pass
            finally:
                os.close(self.directory_fd)
                self.directory_fd = None

    async def _accept(self):
        while True:
            try:
                endpoint, _ = self.listener.accept()
                break
            except BlockingIOError:
                await _fd_ready(self.listener.fileno())
            except InterruptedError:
                continue
        self.connection = endpoint
        self.listener.close()
        self.listener = None
        endpoint.set_inheritable(False)
        endpoint.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        endpoint.setblocking(False)
        peer = struct.unpack("iII", endpoint.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if peer[0] <= 0 or peer[1] != self.uid or peer[2] != os.getgid():
            raise ValueError("Runtime controller has unexpected kernel credentials")
        request = json.loads((await _receive(endpoint, peer)).decode("utf-8"), object_pairs_hook=_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite startup JSON")))
        if request != {"type": "acquire", "schema": SCHEMA}:
            raise ValueError("Unknown native runtime startup request")
        return endpoint, peer

    async def run(self):
        if self.started:
            raise ValueError("Native runtime acquisition cannot be replayed")
        self.started = True
        tasks, sockets, streams = [], [], []
        try:
            endpoint, peer = await asyncio.wait_for(self._accept(), STARTUP_SECONDS)
            pairs = []
            for kind in (socket.SOCK_STREAM, socket.SOCK_SEQPACKET, socket.SOCK_SEQPACKET):
                parent, client = socket.socketpair(socket.AF_UNIX, kind)
                sockets.extend((parent, client))
                for descriptor in (parent, client):
                    descriptor.set_inheritable(False)
                    if kind == socket.SOCK_SEQPACKET:
                        descriptor.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
                pairs.append((parent, client))
            await _send(endpoint, {"type": "channels", "schema": SCHEMA,
                "workspaceRoot": self.server.backend.mount.uri, "fdRoles": ["exec", "config", "host"]},
                tuple(pair[1] for pair in pairs))
            for _, client in pairs:
                client.close()
            reader = pairs[0][0].makefile("rb", buffering=0)
            writer = pairs[0][0].makefile("wb", buffering=0)
            streams.extend((reader, writer))
            serving = asyncio.create_task(serve_stdio(self.server, reader, writer))
            tasks.append(serving)
            lifetime = asyncio.create_task(_receive(endpoint, peer))
            tasks.append(lifetime)
            initialized = asyncio.create_task(asyncio.wait_for(self.server.session_ready.wait(), STARTUP_SECONDS))
            tasks.append(initialized)
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if lifetime in done:
                lifetime.result()
                raise ValueError("Unexpected second native startup request")
            if serving in done:
                serving.result()
                raise EOFError("ExecServer closed before completing native startup")
            initialized.result()
            backend, session = self.server.backend, self.server.session_id
            config = BootstrapReadChannel(pairs[1][0],
                create_bootstrap_read_authority(backend, session_id=session), peer=peer)
            host = HostFileChannel(pairs[2][0],
                create_host_file_authority(backend, session_id=session), peer=peer)
            await _send(endpoint, {"type": "ready", "schema": SCHEMA, "sessionId": session,
                                   "workspaceRoot": backend.mount.uri})
            tasks.extend((asyncio.create_task(config.run()), asyncio.create_task(host.run())))
            tasks.remove(initialized)
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            if lifetime in done:
                raise ValueError("Unexpected runtime lifetime packet")
        finally:
            # Wake any blocking stdio helper before cancelling the coroutine.
            for descriptor in sockets:
                if descriptor.fileno() >= 0:
                    try:
                        descriptor.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
            for task in tasks:
                if not task.done():
                    task.cancel()
            async def cleanup():
                await asyncio.gather(*tasks, return_exceptions=True)
                await self.server.close()
            try:
                await _finish(asyncio.create_task(cleanup()))
            finally:
                for stream in streams:
                    stream.close()
                for descriptor in sockets:
                    descriptor.close()
                self.close_endpoint()
