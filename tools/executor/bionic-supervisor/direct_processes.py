"""Process RPC over an explicitly installed ordinary-UID native owner.

Construction is bootstrap authority; RPC correlation fields confer no rights.
Only the upstream absent/null outer-sandbox contract enters this profile. An
explicit sandbox is refused, never retried here after another profile fails.
The native owner is an ordinary UID process, not a managed or human authority.
"""
import asyncio
import base64
from dataclasses import dataclass
import json
import os
import socket

from tools.executor.exec_server import RpcError
from tools.executor.native_environment import process_environment
from tools.executor.native_processes import (
    COMPLETED_SECONDS, RETAINED_BYTES, RETAINED_CHUNKS, NativeProcessesBackend,
    _Process, _finish, _packet, _receive, _wait_owned,
)
from tools.executor.ordinary_uid_files import native_path
from .direct_wire import envelope, seal


PROFILE = "bionic-direct-v1"


@dataclass(frozen=True)
class DirectLimits:
    """None adds no resource limit; the native owner preserves inherited limits."""
    wall_ms: object = None
    data_bytes: object = None
    file_bytes: object = None
    output_bytes: object = None
    uid_task_budget: object = None
    cpu_seconds: object = None
    descriptors: object = None
    cleanup_grace_ms: int = 5000

    def __post_init__(self):
        values = (self.wall_ms, self.data_bytes, self.file_bytes, self.output_bytes,
                  self.uid_task_budget, self.cpu_seconds, self.descriptors)
        if any(value is not None and (type(value) is not int or not 1 <= value < 2**53)
               for value in values):
            raise ValueError("Direct resource limits must be explicit positive integers or None")
        if (type(self.cleanup_grace_ms) is not int or not 1 <= self.cleanup_grace_ms < 2**53
                or self.descriptors is not None and self.descriptors < 8):
            raise ValueError("Invalid direct cleanup grace or descriptor allowance")


class DirectProcesses(NativeProcessesBackend):
    def __init__(self, runner, workspace, *, executables, files_backend=None,
                 parent_environment=None, limits=None, quarantine_owner=None,
                 mutation_lease=None, guest_workspace=None):
        if not hasattr(os, "getresuid") or len(set(os.getresuid())) != 1 or os.geteuid() == 0:
            raise ValueError("Direct processes require one nonroot native UID")
        super().__init__(runner, workspace, executables=executables,
            guest_workspace=str(workspace) if guest_workspace is None else guest_workspace,
            limits=limits or DirectLimits(), files_backend=files_backend,
            parent_environment=parent_environment, mutation_lease=mutation_lease)
        if self.guest_workspace != self.workspace:
            raise ValueError("Direct processes require actual native workspace paths")
        if quarantine_owner is not None and quarantine_owner.lease is not self.lease:
            raise ValueError("Direct and composed owners must share their actual filesystem lease")
        self.quarantine_owner = quarantine_owner

    def _unavailable(self):
        return (self.quarantined or self.quarantine_event.is_set()
                or self.files_backend is not None and self.files_backend.closed
                or self.quarantine_owner is not None and (self.quarantine_owner.quarantined
                    or self.quarantine_owner.quarantine_event.is_set()))

    def _quarantine(self):
        self.quarantined = True
        self.quarantine_event.set()
        if self.quarantine_owner is not None:
            self.quarantine_owner.quarantined = True
            self.quarantine_owner.quarantine_event.set()

    def _validate_launch_context(self, params):
        if params.get("sandbox") is not None:
            raise RpcError(-32602, "Direct processes require an absent outer sandbox; explicit contexts are refused")
        if (params["tty"] or params.get("enforceManagedNetwork")
                or any(params.get(key) is not None for key in ("shellSnapshot", "managedNetwork", "networkProxy"))):
            raise RpcError(-32602, "Direct pipe execution does not implement PTY, shell snapshots or managed networking")
        native_path(params["cwd"])

    async def _start(self, call, notify):
        params = call.params
        if self._unavailable():
            raise RpcError(-32603, "Direct workspace owner is closed or quarantined")
        self._validate_launch_context(params)
        argv = params["argv"]
        if not argv or len(argv) > 256 or any("\0" in value for value in argv):
            raise RpcError(-32602, "Invalid direct argument vector")
        executable = self.executables.get(argv[0])
        if executable is None:
            raise RpcError(-32602, "Executable is outside the installed native runtime mapping")
        arg0 = params.get("arg0")
        if arg0 is not None and "\0" in arg0:
            raise RpcError(-32602, "Invalid direct argv0")
        environment = process_environment(params, self.parent_environment)
        key = (call.session_id, params["processId"])
        if key in self.processes:
            raise RpcError(-32600, "Process id already exists in this session")
        if len(self.processes) >= 128:
            raise RpcError(-32000, "Native process registry capacity exhausted")
        loop = asyncio.get_running_loop()
        record = _Process(call.session_id, params["processId"], call.params_json,
            call.request_id, notify, executable,
            tuple([arg0 if arg0 is not None else argv[0], *argv[1:]]),
            environment, loop.create_future(), loop.create_future())
        record.mode = "ordinary-uid"
        record.event_lock = asyncio.Lock()
        record.transport_closed = asyncio.Event()
        record.ownership_retained = asyncio.Event()
        record.exit_notified = False
        record.pipe_eof = {"stdout": False, "stderr": False}
        self.processes[key] = record
        record.task = asyncio.create_task(self._run(record))
        try:
            await _wait_owned(record.started)
            return {"processId": record.key, "sandboxType": "none"}
        except BaseException:
            self._terminate(record)
            await _finish(record.finished)
            raise

    def _terminate(self, record):
        record.termination_requested = True
        record.cancellation.set()
        record.write_changed.set()
        if record.command is not None:
            try:
                record.command.send(b"T")
            except (BlockingIOError, OSError):
                # EOF cancels too; only the native owner may signal descendants.
                record.command.close()

    async def _notify(self, record):
        try:
            await super()._notify(record)
        finally:
            record.transport_closed.set()
            if not record.closed:
                # CancelledError is a transport loss too. With no wall limit,
                # the owner must still receive termination and prove cleanup.
                self._terminate(record)

    async def _event_async(self, record, method, payload):
        """Bound transport memory with backpressure; retain read history separately."""
        async with record.event_lock:
            seq = record.next_seq
            record.next_seq += 1
            params = {"processId": record.key, "seq": seq, **payload}
            if method == "process/output":
                size = len(base64.b64decode(payload["chunk"], validate=True))
                record.output.append(({"seq": seq, **payload}, size))
                record.retained_bytes += size
                while record.retained_bytes > RETAINED_BYTES or len(record.output) > RETAINED_CHUNKS:
                    _, removed = record.output.popleft()
                    record.retained_bytes -= removed
            record.changed.set()
            if record.transport_closed.is_set():
                return
            try:
                record.notifications.put_nowait((method, params))
                return
            except asyncio.QueueFull:
                if record.cancellation.is_set():
                    return  # Cancellation must still drain actual pipes and prove cleanup.
            sending = asyncio.create_task(record.notifications.put((method, params)))
            disconnected = asyncio.create_task(record.transport_closed.wait())
            cancelled = asyncio.create_task(record.cancellation.wait())
            try:
                await asyncio.wait((sending, disconnected, cancelled), return_when=asyncio.FIRST_COMPLETED)
                if sending.done():
                    sending.result()
            finally:
                for task in (sending, disconnected, cancelled):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(sending, disconnected, cancelled, return_exceptions=True)

    async def _output(self, record, stream, name):
        while True:
            data = await stream.read(65536)
            if not data:
                record.pipe_eof[name] = True
                return
            record.byte_counts[name] += len(data)
            if name == "stderr" and record.state == "starting":
                record.setup_diagnostic = (record.setup_diagnostic + data)[:4096]
            try:
                await _wait_owned(record.started)
            except RpcError:
                continue
            await self._event_async(record, "process/output",
                {"stream": name, "chunk": base64.b64encode(data).decode("ascii")})

    async def _end_events(self, record):
        if record.notifier.done():
            return
        try:
            record.notifications.put_nowait(None)
            return
        except asyncio.QueueFull:
            pass
        stopping = asyncio.create_task(record.notifications.put(None))
        disconnected = asyncio.create_task(record.transport_closed.wait())
        cancelled = asyncio.create_task(record.cancellation.wait())
        try:
            await asyncio.wait((stopping, disconnected, cancelled), return_when=asyncio.FIRST_COMPLETED)
            if not stopping.done():
                record.notifier.cancel()
        finally:
            for task in (stopping, disconnected, cancelled):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stopping, disconnected, cancelled, return_exceptions=True)

    async def _publish_exit(self, record):
        if (not record.exit_notified and record.exit_code is not None and record.started.done()
                and not record.started.cancelled() and record.started.exception() is None):
            record.exit_notified = True
            await self._event_async(record, "process/exited",
                {"exitCode": record.exit_code, "sandboxDenied": False})

    @staticmethod
    def _wait_status(message, *, absent=False):
        code, signum = message["exitCode"], message["signal"]
        if (type(code) is not int or type(signum) is not int or not -1 <= code <= 255
                or not 0 <= signum <= 64 or signum and code != -1
                or not signum and code < 0 and not absent):
            raise RpcError(-32603, "Direct native wait status is invalid")
        return 128 + signum if signum else code

    async def _control(self, record, endpoint):
        ready = False
        while True:
            message = await _receive(endpoint)
            if message is None:
                if record.native_result is None:
                    raise RpcError(-32603, "Direct native owner closed without a cleanup result")
                return
            if type(message) is not dict:
                raise RpcError(-32603, "Direct lifecycle frame is not an object")
            kind = message.get("type")
            if record.native_result is not None:
                raise RpcError(-32603, "Direct lifecycle frame arrived after the final result")
            if kind == "ready":
                if ready or message != {"type": "ready", "profile": PROFILE}:
                    raise RpcError(-32603, "Invalid direct startup handshake")
                ready = True
                try:
                    await _packet(endpoint, b"P")
                except BrokenPipeError:
                    pass  # Only its subsequent final record can certify cancellation.
            elif kind == "started":
                if (not ready or record.native_started is not None or type(message.get("setupCompleted")) is not bool or message != {
                        "type": "started", "profile": PROFILE, "setupCompleted": True, "sandboxType": "none"}):
                    raise RpcError(-32603, "Invalid direct exec acknowledgement")
                record.native_started = message
                if record.termination_requested:
                    self._terminate(record)
                else:
                    record.state = "running"
                    record.started.set_result(None)
                    await self._publish_exit(record)
            elif kind == "exited":
                if not ready or record.exit_code is not None or set(message) != {"type", "exitCode", "signal"}:
                    raise RpcError(-32603, "Invalid direct native exit observation")
                record.exit_code = self._wait_status(message)
                await self._publish_exit(record)
                record.write_changed.set()
            elif kind == "ownership-retained":
                if (not ready or type(message.get("cleanupComplete")) is not bool
                        or message != {"type": "ownership-retained", "cleanupComplete": False}):
                    raise RpcError(-32603, "Invalid direct retained-ownership observation")
                self._quarantine()
                record.failure = "Native cleanup is pending; ownership and workspace lease are retained"
                record.ownership_retained.set()
                self._terminate(record)
            elif kind == "result":
                fields = {"type", "profile", "outcome", "started", "cleanupComplete", "exitCode", "signal",
                          "reaped", "signalsSent", "stdoutReadBytes", "stderrReadBytes",
                          "stdoutBytes", "stderrBytes", "stage", "errno"}
                numeric = {"reaped", "signalsSent", "stdoutReadBytes", "stderrReadBytes",
                           "stdoutBytes", "stderrBytes", "stage", "errno"}
                if (set(message) != fields or message["profile"] != PROFILE
                        or any(type(message[name]) is not bool for name in ("started", "cleanupComplete"))
                        or any(type(message[name]) is not int or not 0 <= message[name] < 2**64 for name in numeric)
                        or message["outcome"] not in {"exited", "cancelled", "timeout", "output_limit",
                            "output_error", "setup_error", "broker_error", "cleanup_error"}):
                    raise RpcError(-32603, "Direct native final result violates its schema")
                self._wait_status(message, absent=not message["started"])
                if message["started"] != (record.native_started is not None):
                    raise RpcError(-32603, "Direct final result disagrees with the exec acknowledgement")
                if (message["started"] and message["reaped"] < 1
                        or message["outcome"] == "exited" and not message["started"]):
                    raise RpcError(-32603, "Direct final result has no corresponding actual command wait")
                if any(message[name + "ReadBytes"] < message[name + "Bytes"] for name in ("stdout", "stderr")):
                    raise RpcError(-32603, "Direct output counts claim unsourced bytes")
                record.native_result = message
                if not record.started.done():
                    record.started.set_exception(RpcError(-32603,
                        f"Direct command failed before exec: outcome={message['outcome']} "
                        f"stage={message['stage']} errno={message['errno']}"))
            else:
                raise RpcError(-32603, "Unknown direct native lifecycle frame")

    def _clean(self, record):
        result = record.native_result
        if (result is None or result["cleanupComplete"] is not True or record.process is None
                or record.process.returncode != (0 if result["started"] else 70)
                or not all(record.pipe_eof.values())):
            return False
        if any(result[name + "Bytes"] != record.byte_counts[name] for name in ("stdout", "stderr")):
            return False
        if result["outcome"] == "exited" and any(
                result[name + "ReadBytes"] != result[name + "Bytes"] for name in ("stdout", "stderr")):
            return False
        if result["started"] and self._wait_status(result) != record.exit_code:
            return False
        return True

    async def _run(self, record):
        process = None
        endpoints, descriptors, readers = [], [], []
        owned = clean = False
        communication = waiting = None
        record.notifier = asyncio.create_task(self._notify(record))
        try:
            acquiring = asyncio.create_task(self.lease.acquire())
            cancellation = asyncio.create_task(record.cancellation.wait())
            try:
                await asyncio.wait((acquiring, cancellation), return_when=asyncio.FIRST_COMPLETED)
            finally:
                if not acquiring.done():
                    acquiring.cancel()
                cancellation.cancel()
                await asyncio.gather(acquiring, cancellation, return_exceptions=True)
                if not acquiring.cancelled() and acquiring.exception() is None:
                    owned = acquiring.result()
            if self._unavailable() or record.termination_requested or not owned:
                raise RpcError(-32600, "Direct start was cancelled or the workspace is unavailable")
            params = json.loads(record.params_json)
            self._validate_launch_context(params)
            info = os.stat(record.executable.path, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != (record.executable.device, record.executable.inode):
                raise RpcError(-32603, "Direct executable changed after admission")
            control, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            command, command_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            endpoints.extend((control, peer, command, command_peer))
            control.setblocking(False)
            command.setblocking(False)
            record.command = command
            read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
            descriptors.append(read_fd)
            record.stdin = write_fd
            os.set_blocking(write_fd, False)
            if not params.get("pipeStdin", False):
                os.close(write_fd)
                record.stdin = -1
                record.stdin_closed = True
            limits = self.limits
            sealed = seal(envelope(cwd=str(native_path(params["cwd"])), executable=record.executable.path,
                argv=record.argv, environment=[entry.decode("utf-8") for entry in record.environment.split(b"\0") if entry],
                wall_ms=limits.wall_ms, data_bytes=limits.data_bytes, file_bytes=limits.file_bytes,
                output_bytes=limits.output_bytes, uid_tasks=limits.uid_task_budget,
                cpu_seconds=limits.cpu_seconds, descriptors=limits.descriptors, cleanup_grace_ms=limits.cleanup_grace_ms))
            descriptors.append(sealed)
            inherited = (sealed, read_fd, peer.fileno(), command_peer.fileno())
            spawning = asyncio.create_task(asyncio.create_subprocess_exec(self.runner, *map(str, inherited),
                pass_fds=inherited, close_fds=True, env={}, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE))
            process = await _finish(spawning)
            record.process = process
            peer.close()
            command_peer.close()
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
            cancelled = asyncio.create_task(record.cancellation.wait())
            retained = asyncio.create_task(record.ownership_retained.wait())
            try:
                timeout = None if limits.wall_ms is None else (limits.wall_ms + limits.cleanup_grace_ms) / 1000
                done, _ = await asyncio.wait((communication, cancelled, retained),
                    timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
                if communication not in done:
                    self._terminate(record)
                    done, _ = await asyncio.wait((communication,), timeout=limits.cleanup_grace_ms / 1000)
                    if communication not in done:
                        raise RpcError(-32603, "Direct cleanup exceeded its grace; actual ownership is retained")
                communication.result()
                clean = self._clean(record)
                if not clean:
                    raise RpcError(-32603, "Direct result, real owner wait, pipe EOF or output accounting is inconsistent")
                if record.native_result["outcome"] not in {"exited", "cancelled"}:
                    record.failure = "Direct command ended with " + record.native_result["outcome"]
            finally:
                for task in (cancelled, retained):
                    task.cancel()
                await asyncio.gather(cancelled, retained, return_exceptions=True)
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            record.failure = record.failure or str(error) or "Direct start cancelled"
            if not record.started.done():
                record.started.set_exception(RpcError(-32603, record.failure))
        finally:
            # No PID-based supervisor kill, cancelled wait task or fabricated wait.
            if process is not None and not clean:
                self._terminate(record)
                if waiting is None:
                    waiting = asyncio.create_task(process.wait())
                pending = [task for task in (*readers[:3], waiting) if not task.done()]
                if pending:
                    await asyncio.wait(pending, timeout=self.limits.cleanup_grace_ms / 1000)
                clean = self._clean(record)
            if process is not None and not clean:
                self._quarantine()
                record.failure = record.failure or "Direct descendant cleanup is unknown; workspace ownership is retained"
            # The stdin pump owns no descendant. Finish it before closing its
            # descriptor, even when the distinct native owner must be retained.
            for task in readers[3:]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*readers[3:], return_exceptions=True)
            if process is not None and (process.returncode is None or any(not task.done() for task in readers[:3])):
                # Keep strong references to every real resource. The quarantined
                # shared lease is deliberately not released by a later timer.
                record.retained_owner = (communication, waiting, readers, endpoints, process)
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
                os.close(record.stdin)
                record.stdin = -1
            record.stdin_closed = True
            record.write_changed.set()
            for fd in descriptors:
                os.close(fd)
            if owned and (process is None or clean):
                self.lease.release()
            started = record.started.done() and not record.started.cancelled() and record.started.exception() is None
            record.state = "complete"
            record.closed = clean or process is None
            if started and record.closed:
                await self._event_async(record, "process/closed", {})
            record.changed.set()
            if not started:
                self.failed.append(record)
                self.processes.pop((record.session, record.key), None)
            elif record.closed:
                asyncio.get_running_loop().call_later(COMPLETED_SECONDS, self._expire, record)
            else:
                self.failed.append(record)
            await self._end_events(record)
            if not record.finished.done():
                record.finished.set_result(None)

    async def close(self, session_id):
        for (session, _), record in self.processes.items():
            if session == session_id:
                record.transport_closed.set()
                if record.notifier is not None:
                    record.notifier.cancel()
        try:
            await super().close(session_id)
        finally:
            if self.quarantined:
                self._quarantine()
