"""App-private Unix socket transport for the native exec-server.

The supervisor supplies fixed paths and the allowed Android UID. Peer credentials
authenticate that UID, not a particular executable within it. This is a transport
and session owner, not a process sandbox or an installed production executor.
"""
import argparse
import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import stat
import struct
import sys
from types import MappingProxyType

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.executor.exec_server import ExecServer, ProtocolClosed, RpcError, local_environment_info, serve_stdio
from tools.executor.native_files import NativeFilesBackend
from tools.executor.native_runtime_startup import android_boot_epoch, strict_json

SOCKET_NAME = "exec.sock"
PROCESS_SESSION = "process-session.json"


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


class PrivateSessionOwner:
    """Own a fixed endpoint independently of the authenticated RPC transport.

    The stdio host and Unix listener share the same pinned directory, flock and
    persistent process marker. Stdio does not need a filesystem socket, but must
    still refuse one left by a previous listener with unverified cleanup.
    """
    def __init__(self, directory, *, boot_epoch=None):
        self.directory = Path(directory).absolute()
        self.fd = self.lock = None
        self.process_identity = None
        self.quarantined = False
        self.retained_backend = None
        self.boot_epoch = None if boot_epoch is None else MappingProxyType(android_boot_epoch(boot_epoch))
        self.recovered_session = None
        try:
            if os.getuid() == 0 or os.getuid() != os.geteuid():
                raise PermissionError("Broker requires an ordinary non-root application UID")
            if self.directory != self.directory.resolve(strict=True):
                raise ValueError("Broker directory aliases are unsupported")
            self.fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            info = os.fstat(self.fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise PermissionError("Broker directory must be owned and private")
            self.lock = os.open("broker.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                                0o600, dir_fd=self.fd)
            lock_info = os.fstat(self.lock)
            if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid()
                    or lock_info.st_nlink != 1 or stat.S_IMODE(lock_info.st_mode) & 0o077):
                raise PermissionError("Invalid broker ownership lock")
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                os.stat(PROCESS_SESSION, dir_fd=self.fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if self.boot_epoch is None:
                    raise FileExistsError("A previous native process session lacks verified cleanup")
                self._recover_previous_boot()
            # A stale socket is an explicit supervisor recovery condition. Never
            # delete an existing path based only on its name or reported owner.
            try:
                os.stat(SOCKET_NAME, dir_fd=self.fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise FileExistsError("Broker socket path already exists")
        except BaseException:
            PrivateSessionOwner.close(self)
            raise

    @staticmethod
    def _stamp(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _recover_previous_boot(self):
        """Archive a valid older-boot marker while holding the real broker lock.

        A strictly advanced Android counter proves the previous boot ended.
        Same-boot crashes, counter regression and legacy markers stay blocked.
        No PID probe authorizes this operation and no cleanup success is claimed.
        """
        # The new application owner uses per-session sockets. An unqualified
        # legacy fixed socket remains an independent condition, never removed.
        try:
            os.stat(SOCKET_NAME, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError("Broker socket path already exists")
        marker = os.open(PROCESS_SESSION, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=self.fd)
        archive = None
        try:
            before = os.fstat(marker)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) & 0o077
                    or not 0 < before.st_size <= 4096):
                raise PermissionError("Previous boot marker must be bounded private ordinary data")
            chunks, consumed = [], 0
            while chunk := os.read(marker, 4097 - consumed):
                chunks.append(chunk)
                consumed += len(chunk)
                if consumed > 4096:
                    raise ValueError("Previous boot marker grew beyond its bound")
            data = b"".join(chunks)
            named = os.stat(PROCESS_SESSION, dir_fd=self.fd, follow_symlinks=False)
            if (len(data) != before.st_size or self._stamp(before) != self._stamp(os.fstat(marker))
                    or self._stamp(before) != self._stamp(named)):
                raise RuntimeError("Previous boot marker changed during admission")
            value = strict_json(data)
            fields = {"version", "brokerPid", "uid", "workspaceDevice", "workspaceInode", "bootEpoch"}
            if (type(value) is not dict or set(value) != fields or type(value["version"]) is not int
                    or value["version"] != 2 or type(value["uid"]) is not int or value["uid"] != os.getuid()
                    or type(value["brokerPid"]) is not int or value["brokerPid"] <= 0
                    or type(value["workspaceDevice"]) is not int or value["workspaceDevice"] < 0
                    or type(value["workspaceInode"]) is not int or value["workspaceInode"] <= 0):
                raise FileExistsError("A previous native process session lacks verified boot evidence")
            previous = android_boot_epoch(value["bootEpoch"])
            if self.boot_epoch["bootCount"] <= previous["bootCount"]:
                raise FileExistsError("A previous native process session is not from an earlier boot")
            archive_name = "recovered-boot-" + os.urandom(16).hex()
            os.mkdir(archive_name, mode=0o700, dir_fd=self.fd)
            archive = os.open(archive_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=self.fd)
            archive_info = os.fstat(archive)
            named_archive = os.stat(archive_name, dir_fd=self.fd, follow_symlinks=False)
            if (not stat.S_ISDIR(archive_info.st_mode) or archive_info.st_uid != os.getuid()
                    or stat.S_IMODE(archive_info.st_mode) & 0o077
                    or (archive_info.st_dev, archive_info.st_ino) != (named_archive.st_dev, named_archive.st_ino)):
                raise PermissionError("Previous boot archive directory identity differs")
            receipt = {"schema": "foldgpt.native-boot-recovery.v1", "previousBootEpoch": previous,
                "currentBootEpoch": dict(self.boot_epoch), "uid": os.getuid(),
                "markerSha256": hashlib.sha256(data).hexdigest(),
                "markerDevice": before.st_dev, "markerInode": before.st_ino,
                "previousBootEnded": True, "previousCleanupClaimed": False}
            record = os.open("recovery.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=archive)
            try:
                encoded = json.dumps(receipt, separators=(",", ":")).encode("ascii") + b"\n"
                view = memoryview(encoded)
                while view:
                    written = os.write(record, view)
                    if written <= 0:
                        raise OSError("Previous boot recovery receipt write failed")
                    view = view[written:]
                os.fsync(record)
            finally:
                os.close(record)
            # Retain the original inode and bytes, including the old workspace
            # identity. Only the marker moves; no workspace or session tree does.
            if self._stamp(os.stat(PROCESS_SESSION, dir_fd=self.fd, follow_symlinks=False)) != self._stamp(before):
                raise RuntimeError("Previous boot marker changed before archival")
            os.rename(PROCESS_SESSION, PROCESS_SESSION, src_dir_fd=self.fd, dst_dir_fd=archive)
            moved = os.stat(PROCESS_SESSION, dir_fd=archive, follow_symlinks=False)
            if (moved.st_dev, moved.st_ino) != (before.st_dev, before.st_ino):
                raise RuntimeError("Archived boot marker identity differs")
            os.fsync(archive)
            os.fsync(self.fd)
            self.recovered_session = {**receipt, "archiveName": archive_name}
        finally:
            if archive is not None:
                os.close(archive)
            os.close(marker)

    def begin_process_session(self, workspace):
        """Persist ownership before any process RPC can arrive.

        A broker crash or unverified close leaves this marker. Restart never
        erases it based on PID absence. An explicit Android app owner also
        records its boot epoch, allowing only a proven later boot to recover it.
        """
        if self.process_identity is not None or self.quarantined:
            raise RuntimeError("Native process session already owns this endpoint")
        root = os.stat(workspace, follow_symlinks=False)
        fd = os.open(PROCESS_SESSION, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self.fd)
        try:
            info = os.fstat(fd)
            self.process_identity = (info.st_dev, info.st_ino)
            value = {"version": 1, "brokerPid": os.getpid(), "uid": os.getuid(),
                "workspaceDevice": root.st_dev, "workspaceInode": root.st_ino}
            if self.boot_epoch is not None:
                value.update(version=2, bootEpoch=dict(self.boot_epoch))
            data = json.dumps(value, separators=(",", ":")).encode() + b"\n"
            view = memoryview(data)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    raise OSError("Native session ownership write failed")
                view = view[count:]
            os.fsync(fd)
            os.fsync(self.fd)
        finally:
            os.close(fd)

    def finish_process_session(self):
        if self.process_identity is None or self.quarantined:
            raise RuntimeError("Cannot release an unverified native process session")
        info = os.stat(PROCESS_SESSION, dir_fd=self.fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != self.process_identity:
            raise RuntimeError("Native process session ownership changed")
        os.unlink(PROCESS_SESSION, dir_fd=self.fd)
        os.fsync(self.fd)
        self.process_identity = None

    def close(self):
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class PrivateListener(PrivateSessionOwner):
    """Add an actual Unix listener to the shared persistent endpoint owner."""
    def __init__(self, directory):
        self.listener = self.identity = None
        super().__init__(directory)
        try:
            self.path = self.directory / SOCKET_NAME
            if len(os.fsencode(self.path)) >= 108:
                raise ValueError("Unix socket path exceeds sockaddr_un capacity")
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
        super().close()


async def serve_connection(connection, identity, helper, workspace, guest_workspace, handle_helper=None,
                           process_config=None, owner=None, environment_info=None):
    backend = server = reader = writer = None
    try:
        # This task exclusively owns its workspace lease and protocol session.
        if process_config is not None:
            from tools.executor.native_executor_backend import NativeExecutorBackend
            backend = NativeExecutorBackend(helper, workspace, handle_helper=handle_helper,
                guest_workspace=guest_workspace, **process_config)
            owner.begin_process_session(workspace)
        elif handle_helper is None:
            backend = NativeFilesBackend(helper, workspace, guest_workspace=guest_workspace)
        else:
            from tools.executor.native_file_streams import NativeFileStreamsBackend
            backend = NativeFileStreamsBackend(helper, workspace, handle_helper=handle_helper,
                                               guest_workspace=guest_workspace)
        if environment_info is None:
            info = local_environment_info()
            info["cwd"] = backend.mount.uri
        else:
            # Runtime adapters describe their own guest namespace. Resolving
            # the broker host's shell/home/temp would misidentify a GNU guest
            # when this broker itself runs under Android's Bionic Python.
            info = environment_info
            if info.get("cwd") != backend.mount.uri:
                raise ValueError("Runtime metadata cwd differs from the pinned workspace")
        server = ExecServer(backend, environment_info=info)
        connection.setblocking(True)
        reader = connection.makefile("rb")
        writer = connection.makefile("wb", buffering=0)
        emit_event("session-open", peer=identity)
        await serve_stdio(server, reader, writer)
    except (ProtocolClosed, RpcError, OSError, ValueError):
        emit_event("session-failed", peer=identity)
    finally:
        try:
            try:
                if server is not None:
                    await server.close()
                elif backend is not None:
                    await backend.close(None)
                # serve_stdio may already have attempted ExecServer.close;
                # its idempotent wrapper does not replay backend failures.
                if process_config is not None and backend is not None:
                    await backend.close(server.session_id if server is not None else None)
                    if owner.process_identity is not None:
                        owner.finish_process_session()
            except Exception:
                if process_config is not None and backend is not None:
                    owner.quarantined = True
                    owner.retained_backend = backend
                    emit_event("session-quarantined", peer=identity)
                else:
                    raise
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
                       sessionId=server.session_id if server is not None else None,
                       workspaceQuarantined=owner.quarantined if process_config is not None else False)


async def run(directory, helper, workspace, guest_workspace, expected_uid, handle_helper=None,
              process_config=None, environment_info=None):
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
            if listener.quarantined:
                connection.close()
                emit_event("quarantine-rejected", peer=identity)
                continue
            if active is not None:
                if not active.done():
                    connection.close()
                    emit_event("busy-rejected", peer=identity)
                    continue
                await active
                active = None
            active = asyncio.create_task(serve_connection(connection, identity, helper, workspace, guest_workspace,
                handle_helper, process_config, listener, environment_info))
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
    parser.add_argument("--process-runner", type=Path)
    parser.add_argument("--executable", nargs=2, action="append", metavar=("NAME", "NATIVE_PATH"))
    parser.add_argument("--process-wall-ms", type=int)
    parser.add_argument("--process-address-space-bytes", type=int)
    parser.add_argument("--process-output-bytes", type=int)
    parser.add_argument("--process-uid-task-budget", type=int)
    args = parser.parse_args()
    limits = {name: getattr(args, "process_" + name) for name in
              ("wall_ms", "address_space_bytes", "output_bytes", "uid_task_budget")
              if getattr(args, "process_" + name) is not None}
    process_config = None
    if args.process_runner is None:
        if args.executable or limits:
            parser.error("Process mappings and limits require --process-runner")
    else:
        if not args.handle_helper or not args.executable:
            parser.error("The composite requires --handle-helper and explicit --executable mappings")
        mappings = dict(args.executable)
        if len(mappings) != len(args.executable):
            parser.error("Duplicate native executable mapping")
        from types import MappingProxyType
        from tools.executor.native_processes import NativeProcessLimits
        process_config = MappingProxyType({"process_runner": args.process_runner,
            "executables": MappingProxyType(mappings), "limits": NativeProcessLimits(**limits)})
    asyncio.run(run(args.socket_dir, args.helper, args.workspace, args.guest_workspace, args.peer_uid,
                    args.handle_helper, process_config))


if __name__ == "__main__":
    main()
