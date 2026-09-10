"""Isolated model PTY backend candidate. No human terminal authority routing."""
import asyncio
import base64
import importlib
import json
import os
import socket
import struct

from tools.executor.exec_server import RpcError, validate_operation
from tools.executor.native_processes import COMPLETED_SECONDS, STDIN_BYTES, RETAINED_WRITE_IDS, _finish, _packet, _receive
from tools.executor.ordinary_uid_files import native_path
if __package__:
    from .tty_wire import envelope, seal
else:
    from tty_wire import envelope, seal

_direct = importlib.import_module("tools.executor.bionic-supervisor.direct_processes")
PROFILE = "bionic-direct-pty-v1"


class TtyProcesses(_direct.DirectProcesses):
    def __init__(self, *args, rows=24, cols=80, **kwargs):
        if any(type(value) is not int or not 1 <= value <= 65535 for value in (rows, cols)):
            raise ValueError("Explicit initial terminal dimensions required")
        self.rows, self.cols = rows, cols
        super().__init__(*args, **kwargs)

    def _validate_launch_context(self, params):
        if params.get("sandbox") is not None:
            raise RpcError(-32602, "PTY requires absent outer sandbox; explicit contexts are refused")
        if (params["tty"] is not True or params.get("enforceManagedNetwork")
                or any(params.get(key) is not None for key in ("shellSnapshot", "managedNetwork", "networkProxy"))):
            raise RpcError(-32602, "Native PTY candidate requires tty=true without unsupported launch contexts")
        native_path(params["cwd"])

    async def handle(self, call, notify):
        if call.method != "process/signal":
            return await super().handle(call, notify)
        validate_operation(call.method, call.params)
        if call.session_id in self.closing_sessions:
            raise RpcError(-32600, "Native process session is closing")
        record = self._get(call.session_id, call.params["processId"])
        if record is None or record.state != "running" or record.exit_code is not None:
            return {}
        data = await self._command_exchange(record, b"I", b"", 13)
        error = struct.unpack("<i", data[9:])[0]
        if error < 0:
            self._terminate(record)
            raise RpcError(-32603, "Invalid terminal signal errno")
        if error:
            raise RpcError(-32603, f"Native initial-group interrupt failed with errno={error}")
        return {}

    async def _event_async(self, record, method, payload):
        if method == "process/output":
            payload = {**payload, "stream": "pty"}
        await super()._event_async(record, method, payload)

    async def resize_owned(self, session_id, process_id, *, rows, cols):
        """Owner-only operation; current official model RPC has no resize method.

        This method is not added to supported_methods and confers no human
        terminal authority. A future existing owner may bind a genuine resize
        API only after its provenance and connection ownership are established.
        """
        if any(type(value) is not int or not 1 <= value <= 65535 for value in (rows, cols)):
            raise RpcError(-32602, "Invalid terminal dimensions")
        record = self._get(session_id, process_id)
        if record is None or record.state != "running" or record.exit_code is not None:
            raise RpcError(-32603, "Terminal is not running in this owner session")
        data = await self._command_exchange(record, b"R", struct.pack("<HH", rows, cols), 17)
        actual_rows, actual_cols, error = struct.unpack("<HHi", data[9:])
        if error < 0:
            self._terminate(record)
            raise RpcError(-32603, "Invalid terminal resize errno")
        if error:
            raise RpcError(-32603, f"Native terminal resize failed with errno={error}")
        if (actual_rows, actual_cols) != (rows, cols):
            self._terminate(record)
            raise RpcError(-32603, "Terminal resize readback differs from intent")
        return {"rows": actual_rows, "cols": actual_cols}

    async def _command_exchange(self, record, operation, payload, reply_size):
        async with record.command_lock:
            if record.command is None or record.exit_code is not None or record.termination_requested:
                raise RpcError(-32603, "Terminal is closing")
            if record.command_id == 2**64 - 1:
                raise RpcError(-32603, "Terminal control request space exhausted")
            record.command_id += 1
            request = record.command_id
            async def exchange():
                await _packet(record.command, struct.pack("<cQ", operation, request) + payload)
                data = await asyncio.get_running_loop().sock_recv(record.command, reply_size + 1)
                if len(data) != reply_size:
                    raise RpcError(-32603, "Terminal acknowledgement is truncated or oversized")
                marker, identity = struct.unpack("<cQ", data[:9])
                if marker != operation.lower() or identity != request:
                    raise RpcError(-32603, "Terminal acknowledgement is invalid")
                return data
            exchanging = asyncio.create_task(exchange())
            try:
                done, _ = await asyncio.wait((exchanging, record.finished),
                    timeout=self.limits.cleanup_grace_ms / 1000, return_when=asyncio.FIRST_COMPLETED)
                if exchanging not in done:
                    raise RpcError(-32603, "Terminal control acknowledgement was not observed")
                return exchanging.result()
            except BaseException:
                # A cancelled reader could leave a stale acknowledgement. Close
                # this terminal owner, never reuse an ambiguous response queue.
                self._terminate(record)
                raise
            finally:
                if not exchanging.done():
                    exchanging.cancel()
                await asyncio.gather(exchanging, return_exceptions=True)

    async def _write(self, record, params):
        identifier = params["writeId"]
        if not identifier:
            raise RpcError(-32602, "writeId must not be empty")
        if record is None:
            return {"status": "unknownProcess"}
        if record.state == "starting":
            return {"status": "starting"}
        if identifier in record.accepted_ids:
            return {"status": "accepted"}
        data = base64.b64decode(params["chunk"], validate=True)
        if len(data) > STDIN_BYTES:
            raise RpcError(-32602, "Process stdin chunk exceeds the declared private bound")
        while True:
            record.write_changed.clear()
            if identifier in record.accepted_ids:
                return {"status": "accepted"}
            if record.stdin_closed or record.termination_requested:
                raise RpcError(-32603, "Failed to write to process stdin")
            if record.queued_bytes + len(data) <= STDIN_BYTES and len(record.writes) < 128:
                record.writes.append(data)
                record.queued_bytes += len(data)
                record.accepted_ids[identifier] = None
                if len(record.accepted_ids) > RETAINED_WRITE_IDS:
                    record.accepted_ids.popitem(last=False)
                # Accepted bytes and id are committed together before any await.
                record.write_changed.set()
                return {"status": "accepted"}
            await record.write_changed.wait()

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

    async def _run(self, record):
        record.command_lock = asyncio.Lock()
        record.command_id = 0
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
            limits = self.limits
            sealed = seal(envelope(cwd=str(native_path(params["cwd"])), executable=record.executable.path,
                argv=record.argv, environment=[entry.decode("utf-8") for entry in record.environment.split(b"\0") if entry],
                rows=self.rows, cols=self.cols,
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
