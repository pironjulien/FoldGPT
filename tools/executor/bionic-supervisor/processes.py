"""Official process wire backed by the separate Bionic notification supervisor."""
import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import struct

from tools.executor.exec_server import RpcError
from tools.executor.native_processes import COMPLETED_SECONDS, NativeProcessesBackend, _finish, _packet, _receive
from .policy import Policy
from .runtime_paths import native_name, require_outside_workspace
from .wire import envelope, seal


@dataclass(frozen=True)
class Limits:
    wall_ms: int = 60000
    data_bytes: int = 268435456
    file_bytes: int = 16777216
    output_bytes: int = 8388608
    uid_task_budget: int = 8
    cpu_seconds: int = 30
    descriptors: int = 128

    def __post_init__(self):
        bounds = ((self.wall_ms, 1, 3600000), (self.data_bytes, 16777216, 2147483648),
                  (self.file_bytes, 1, 1073741824), (self.output_bytes, 1, 67108864),
                  (self.uid_task_budget, 1, 128), (self.cpu_seconds, 1, 3600),
                  (self.descriptors, 16, 1024))
        if any(type(value) is not int or not low <= value <= high for value, low, high in bounds):
            raise ValueError("Invalid declared Bionic process resource allowance")


@dataclass(frozen=True)
class CwdShim:
    path: str
    sha256: str

    def verify(self):
        path = Path(self.path)
        if (not path.is_absolute() or str(path) != self.path or
                path.resolve(strict=True) != path or any(c in self.path for c in " :\t\r\n\0")):
            raise ValueError("cwdShim must be one canonical loader path")
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_size > 16777216:
                raise ValueError("cwdShim must be a bounded regular immutable runtime file")
            digest = hashlib.sha256()
            consumed = 0
            while data := os.read(fd, 65536):
                consumed += len(data)
                if consumed > 16777216:
                    raise ValueError("cwdShim grew beyond its admitted bound")
                digest.update(data)
            if digest.hexdigest() != self.sha256:
                raise ValueError("cwdShim differs from its bootstrap attestation")
        finally:
            os.close(fd)


class Processes(NativeProcessesBackend):
    def __init__(self, runner, workspace, *, runtime, executables, limits=None, cwd_shim=None, **options):
        super().__init__(runner, workspace, executables=executables, limits=limits or Limits(), **options)
        if self.files_backend is None:
            raise ValueError("The Bionic process backend requires the composed filesystem owner")
        if self.guest_workspace != self.workspace:
            raise ValueError("Bionic currently requires the native workspace path as its advertised mount")
        self.cwd_shim = None
        if cwd_shim is not None:
            if (type(cwd_shim) is not dict or set(cwd_shim) != {"path", "sha256"} or
                    type(cwd_shim["path"]) is not str or type(cwd_shim["sha256"]) is not str or
                    len(cwd_shim["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in cwd_shim["sha256"])):
                raise ValueError("cwdShim requires its exact installed path and SHA256")
            self.cwd_shim = CwdShim(**cwd_shim)
            self.cwd_shim.verify()
        self.runtime = tuple((native_name(path), execute) for path, execute in runtime)
        if self.cwd_shim is not None:
            self.runtime += ((self.cwd_shim.path, True),)
            if self.parent_environment is not None and "LD_PRELOAD" in self.parent_environment:
                raise ValueError("LD_PRELOAD is reserved by the configured native cwd shim")
        if not self.runtime or len(self.runtime) > 64 or any(type(execute) is not bool for _, execute in self.runtime):
            raise ValueError("Explicit bounded Bionic runtime grants are required")
        for path, _ in self.runtime:
            require_outside_workspace(path, self.workspace)

    async def _control(self, record, endpoint):
        ready = False
        while True:
            message = await _receive(endpoint)
            if message is None:
                if record.native_result is None:
                    raise RpcError(-32603, "Bionic supervisor ended without a cleanup result")
                return
            if type(message) is not dict:
                raise RpcError(-32603, "Malformed Bionic control record")
            kind = message.get("type")
            if kind == "ready":
                if ready or message != {"type": "ready", "profile": "bionic-managed-v1"}:
                    raise RpcError(-32603, "Invalid Bionic startup handshake")
                ready = True
                await _packet(endpoint, b"P")
            elif kind == "acquire":
                if not ready or record.native_result is not None:
                    raise RpcError(-32603, "Acquisition outside its bound process lifetime")
                evaluating = asyncio.create_task(asyncio.to_thread(record.policy.decide, message))
                decision = await _finish(evaluating)
                relative = decision["relative"].encode("utf-8")
                response = struct.pack("<QiI4Q", decision["id"], decision["error"], len(relative),
                    decision["device"], decision["inode"], decision["parentDevice"], decision["parentInode"]) + relative
                await _packet(endpoint, response)
            elif kind == "started":
                if not ready or record.native_started is not None or message != {
                    "type": "started", "profile": "bionic-managed-v1", "setupCompleted": True}:
                    raise RpcError(-32603, "Invalid Bionic setup acknowledgement")
                record.native_started = message
                if record.termination_requested:
                    self._terminate(record)
                else:
                    record.state = "running"
                    record.started.set_result(None)
            elif kind == "exited":
                if set(message) != {"type", "exitCode", "signal"} or record.exit_code is not None:
                    raise RpcError(-32603, "Invalid Bionic exit record")
                code, signum = message["exitCode"], message["signal"]
                if (type(code) is not int or type(signum) is not int or not -1 <= code <= 255 or
                    not 0 <= signum <= 64 or (signum and code != -1) or (not signum and code < 0)):
                    raise RpcError(-32603, "Invalid Bionic wait status")
                record.exit_code = 128 + signum if signum else code
                if record.started.done() and not record.started.cancelled() and record.started.exception() is None:
                    self._event(record, "process/exited", {"exitCode": record.exit_code, "sandboxDenied": False})
                record.write_changed.set()
            elif kind == "ownership-retained":
                if message != {"type": "ownership-retained", "cleanupComplete": False}:
                    raise RpcError(-32603, "Invalid retained-ownership record")
                self.quarantined = True
                self.quarantine_event.set()
                record.failure = "Native cleanup is pending; the actual supervisor remains alive"
            elif kind == "result":
                fields = {"type", "outcome", "exitCode", "signal", "cleanupComplete", "started",
                          "grants", "denials", "stdoutBytes", "stderrBytes", "stage", "errno"}
                if set(message) != fields or record.native_result is not None:
                    raise RpcError(-32603, "Invalid Bionic final record")
                if (any(type(message[name]) is not bool for name in ("cleanupComplete", "started")) or
                    any(type(message[name]) is not int or message[name] < 0
                        for name in ("signal", "grants", "denials", "stdoutBytes", "stderrBytes", "stage", "errno")) or
                    type(message["exitCode"]) is not int or not -1 <= message["exitCode"] <= 255 or
                    message["outcome"] not in {"exited", "cancelled", "timeout", "output_limit", "setup_error", "broker_error", "cleanup_error"}):
                    raise RpcError(-32603, "Bionic final record violates its schema")
                record.native_result = message
                if not record.started.done():
                    record.started.set_exception(RpcError(-32603, "Bionic command failed before setup completed"))
            else:
                raise RpcError(-32603, "Unknown Bionic lifecycle record")

    def _terminate(self, record):
        record.termination_requested = True
        record.cancellation.set()
        record.write_changed.set()
        if record.command is not None:
            try:
                record.command.send(b"T")
            except (BlockingIOError, BrokenPipeError, OSError):
                # EOF is a cancellation request too. Never signal a recycled
                # numeric PID or kill the native owner to manufacture a timeout.
                record.command.close()
                record.command = None

    async def _run(self, record):
        process = None
        endpoints, descriptors, readers = [], [], []
        owned = clean = retained = False
        communication = waiting = None
        record.notifier = asyncio.create_task(self._notify(record))
        try:
            acquiring = asyncio.create_task(self.lease.acquire())
            cancellation = asyncio.create_task(record.cancellation.wait())
            try:
                await asyncio.wait((acquiring, cancellation), return_when=asyncio.FIRST_COMPLETED)
                if acquiring.done():
                    owned = acquiring.result()
                else:
                    acquiring.cancel()
                    await asyncio.gather(acquiring, return_exceptions=True)
            finally:
                cancellation.cancel()
                await asyncio.gather(cancellation, return_exceptions=True)
            if self.quarantined or record.termination_requested:
                raise RpcError(-32600, "Bionic start was cancelled or the workspace is quarantined")
            params = json.loads(record.params_json)
            preparing = asyncio.create_task(asyncio.to_thread(Policy, self.files_backend,
                params["sandbox"], params["cwd"], session=record.session,
                request=type(record.request_id).__name__ + ":" + str(record.request_id)))
            record.policy = await _finish(preparing)
            record.policy.require_runtime(self.runtime)
            if record.termination_requested:
                raise RpcError(-32600, "Bionic start cancelled before spawn")
            info = os.stat(record.executable.path, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != (record.executable.device, record.executable.inode):
                raise RpcError(-32603, "Bionic executable changed after admission")
            control, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            command, command_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            endpoints.extend((control, peer, command, command_peer))
            control.setblocking(False); command.setblocking(False)
            record.command = command
            read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
            descriptors.append(read_fd)
            record.stdin = write_fd
            os.set_blocking(write_fd, False)
            if not params.get("pipeStdin", False):
                os.close(write_fd); record.stdin = -1; record.stdin_closed = True
            environment = [entry.decode("utf-8") for entry in record.environment.split(b"\0") if entry]
            if self.cwd_shim is not None:
                if any(entry.startswith("LD_PRELOAD=") for entry in environment):
                    raise RpcError(-32602, "LD_PRELOAD is reserved by the configured native cwd shim")
                self.cwd_shim.verify()
                environment.append("LD_PRELOAD=" + self.cwd_shim.path)
            limits = self.limits
            sealed = seal(envelope(workspace=self.workspace, cwd_relative="/".join(record.policy.cwd_parts) or ".",
                executable=record.executable.path, argv=record.argv, environment=environment, runtime=self.runtime,
                wall_ms=limits.wall_ms, data_bytes=limits.data_bytes, file_bytes=limits.file_bytes,
                output_bytes=limits.output_bytes, uid_tasks=limits.uid_task_budget,
                cpu_seconds=limits.cpu_seconds, descriptors=limits.descriptors))
            descriptors.append(sealed)
            inherited = (record.policy.root, read_fd, peer.fileno(), command_peer.fileno(), sealed)
            spawning = asyncio.create_task(asyncio.create_subprocess_exec(self.runner, *map(str, inherited),
                pass_fds=inherited, close_fds=True, env={}, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE))
            process = await _finish(spawning)
            record.process = process
            peer.close(); command_peer.close()
            for fd in descriptors:
                os.close(fd)
            descriptors.clear()
            readers = [asyncio.create_task(self._control(record, control)),
                       asyncio.create_task(self._output(record, process.stdout, "stdout")),
                       asyncio.create_task(self._output(record, process.stderr, "stderr"))]
            if record.stdin >= 0:
                readers.append(asyncio.create_task(self._writer(record)))
            waiting = asyncio.create_task(process.wait())
            communication = asyncio.gather(*readers[:3], waiting)
            done, _ = await asyncio.wait((communication,), timeout=limits.wall_ms / 1000 + 8)
            if communication not in done:
                retained = True
                record.failure = "Native cleanup exceeded its deadline; ownership is retained"
                raise RpcError(-32603, record.failure)
            communication.result()
            result = record.native_result
            if result is None or result["cleanupComplete"] is not True:
                raise RpcError(-32603, "Missing Bionic descendant cleanup proof")
            clean = True
            if any(result[name + "Bytes"] != record.byte_counts[name] for name in ("stdout", "stderr")):
                raise RpcError(-32603, "Bionic output accounting differs from the actual pipes")
            expected = 128 + result["signal"] if result["signal"] else result["exitCode"]
            if result["started"] and expected != record.exit_code:
                raise RpcError(-32603, "Bionic final status differs from the wait observation")
            if result["outcome"] not in ("exited", "cancelled"):
                record.failure = "Bionic command ended with " + result["outcome"]
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            record.failure = record.failure or str(error) or "Bionic start cancelled"
            if not record.started.done():
                record.started.set_exception(RpcError(-32603, record.failure))
        finally:
            if process is not None and process.returncode is None:
                self._terminate(record)
                if waiting is None:
                    waiting = asyncio.create_task(process.wait())
                done, _ = await asyncio.wait((waiting,), timeout=6)
                if not done:
                    retained = True
            if (record.native_result is not None and record.native_result["cleanupComplete"]
                    and process is not None and process.returncode is not None):
                clean = True
            if process is not None and not clean:
                self.quarantined = True
                self.quarantine_event.set()
            # Unknown cleanup retains live tasks, native owner, policy and the
            # exact filesystem lease. There is no automatic permissive retry.
            if retained:
                record.retained_owner = (communication, waiting, readers, endpoints, process, record.policy)
            else:
                for task in readers:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
                if communication is not None:
                    await asyncio.gather(communication, return_exceptions=True)
                for endpoint in endpoints:
                    endpoint.close()
                record.command = None
            if record.stdin >= 0:
                os.close(record.stdin); record.stdin = -1
            record.stdin_closed = True; record.write_changed.set()
            for fd in descriptors:
                os.close(fd)
            if record.policy is not None and (process is None or clean):
                record.policy.close()
            if owned and (process is None or clean):
                self.lease.release()
            started = record.started.done() and not record.started.cancelled() and record.started.exception() is None
            record.state = "complete"; record.closed = clean or process is None
            if started and record.closed:
                self._event(record, "process/closed", {})
            record.changed.set()
            if not started:
                self.failed.append(record)
                self.processes.pop((record.session, record.key), None)
            elif record.closed:
                asyncio.get_running_loop().call_later(COMPLETED_SECONDS, self._expire, record)
            try:
                record.notifications.put_nowait(None)
            except asyncio.QueueFull:
                record.notifier.cancel()
            if not record.finished.done():
                record.finished.set_result(None)
