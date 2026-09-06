"""App-private Unix socket transport for the native filesystem exec-server.

The supervisor supplies fixed paths and the allowed Android UID. Peer credentials
authenticate that UID, not a particular executable within it. This is a transport
and session owner, not a process sandbox or an installed production executor.
"""
import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import stat
import struct
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.executor.exec_server import ExecServer, ProtocolClosed, local_environment_info, serve_stdio
from tools.executor.native_files import NativeFilesBackend

SOCKET_NAME = "exec.sock"


def peer_identity(connection):
    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    pid, uid, gid = struct.unpack("3i", raw)
    if pid <= 0 or uid <= 0 or gid < 0:
        raise PermissionError("Invalid non-root peer credentials")
    return {"pid": pid, "uid": uid, "gid": gid}


def emit_event(event, **fields):
    # No RPC payload, policy, requested path, environment, or file content.
    # Diagnostics must never retain a session when the supervisor stops reading
    # them. Each record fits PIPE_BUF; a saturated diagnostic pipe drops records.
    data = (json.dumps({"event": event, **fields}, separators=(",", ":")) + "\n").encode()
    try:
        fd = sys.stdout.fileno()
        os.set_blocking(fd, False)
        os.write(fd, data)
    except (OSError, ValueError):
        pass


class PrivateListener:
    """Pin a private directory and never remove somebody else's socket/file."""
    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        self.fd = self.lock = self.listener = self.identity = None
        self.path = self.directory / SOCKET_NAME
        try:
            if os.getuid() == 0 or os.getuid() != os.geteuid():
                raise PermissionError("Broker requires an ordinary non-root application UID")
            if self.directory != self.directory.resolve(strict=True):
                raise ValueError("Socket directory aliases are unsupported")
            if len(os.fsencode(self.path)) >= 108:
                raise ValueError("Unix socket path exceeds sockaddr_un capacity")
            self.fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            info = os.fstat(self.fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise PermissionError("Socket directory must be owned and private")
            self.lock = os.open("broker.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                                0o600, dir_fd=self.fd)
            lock_info = os.fstat(self.lock)
            if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid()
                    or lock_info.st_nlink != 1 or stat.S_IMODE(lock_info.st_mode) & 0o077):
                raise PermissionError("Invalid broker ownership lock")
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # A stale socket is an explicit supervisor recovery condition. Never
            # delete an existing path based only on its name or reported owner.
            try:
                os.stat(SOCKET_NAME, dir_fd=self.fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError("Broker socket path already exists")
            self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.listener.set_inheritable(False)
            self.listener.bind(str(self.path))
            info = os.stat(SOCKET_NAME, dir_fd=self.fd, follow_symlinks=False)
            self.identity = (info.st_dev, info.st_ino)
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise PermissionError("Bound socket ownership differs")
            os.chmod(SOCKET_NAME, 0o600, dir_fd=self.fd, follow_symlinks=False)
            self.listener.listen(1)
            self.listener.setblocking(False)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.listener is not None:
            self.listener.close()
            self.listener = None
        if self.fd is not None and self.identity is not None:
            try:
                info = os.stat(SOCKET_NAME, dir_fd=self.fd, follow_symlinks=False)
                if (info.st_dev, info.st_ino) == self.identity and stat.S_ISSOCK(info.st_mode):
                    os.unlink(SOCKET_NAME, dir_fd=self.fd)
            except FileNotFoundError:
                pass
            self.identity = None
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


async def serve_connection(connection, identity, helper, workspace, guest_workspace, handle_helper=None):
    backend = server = reader = writer = None
    try:
        # This task exclusively owns its workspace lease and protocol session.
        if handle_helper is None:
            backend = NativeFilesBackend(helper, workspace, guest_workspace=guest_workspace)
        else:
            from tools.executor.native_file_streams import NativeFileStreamsBackend
            backend = NativeFileStreamsBackend(helper, workspace, handle_helper=handle_helper,
                                               guest_workspace=guest_workspace)
        info = local_environment_info()
        info["cwd"] = backend.mount.uri
        server = ExecServer(backend, environment_info=info)
        connection.setblocking(True)
        reader = connection.makefile("rb")
        writer = connection.makefile("wb", buffering=0)
        emit_event("session-open", peer=identity)
        await serve_stdio(server, reader, writer)
    except (ProtocolClosed, OSError, ValueError):
        emit_event("session-failed", peer=identity)
    finally:
        try:
            if server is not None:
                await server.close()
            elif backend is not None:
                await backend.close(None)
        finally:
            # Release blocked pipe workers before closing their buffered files.
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            for stream in (reader, writer):
                if stream is not None:
                    stream.close()
            connection.close()
            emit_event("session-closed", peer=identity,
                       sessionId=server.session_id if server is not None else None)


async def run(directory, helper, workspace, guest_workspace, expected_uid, handle_helper=None):
    if expected_uid <= 0 or expected_uid >= 2**31:
        raise ValueError("Expected peer UID must be a positive signed 32-bit integer")
    listener = PrivateListener(directory)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    active = accepting = stopping = None
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    emit_event("ready", socket=str(listener.path), pid=os.getpid(), uid=os.getuid(),
               peerUid=expected_uid, transport="AF_UNIX/SOCK_STREAM/SO_PEERCRED")
    try:
        stopping = asyncio.create_task(stop.wait())
        while not stop.is_set():
            accepting = asyncio.create_task(loop.sock_accept(listener.listener))
            done, _ = await asyncio.wait({accepting, stopping}, return_when=asyncio.FIRST_COMPLETED)
            if stopping in done:
                if accepting in done:
                    accepting.result()[0].close()
                break
            connection, _ = accepting.result()
            accepting = None
            connection.set_inheritable(False)
            try:
                identity = peer_identity(connection)
                if identity["uid"] != expected_uid:
                    raise PermissionError("Peer UID is not the supervisor-selected application UID")
            except (OSError, ValueError, struct.error):
                connection.close()
                emit_event("peer-rejected")
                continue
            if active is not None:
                if not active.done():
                    connection.close()
                    emit_event("busy-rejected", peer=identity)
                    continue
                await active
                active = None
            active = asyncio.create_task(serve_connection(connection, identity, helper, workspace, guest_workspace, handle_helper))
    finally:
        for pending in (accepting, stopping):
            if pending is not None:
                pending.cancel()
        await asyncio.gather(*(task for task in (accepting, stopping) if task is not None), return_exceptions=True)
        if active is not None:
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
        listener.close()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)
        emit_event("stopped")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket-dir", type=Path, required=True)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--handle-helper", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--guest-workspace", required=True)
    parser.add_argument("--peer-uid", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.socket_dir, args.helper, args.workspace, args.guest_workspace, args.peer_uid, args.handle_helper))


if __name__ == "__main__":
    main()
