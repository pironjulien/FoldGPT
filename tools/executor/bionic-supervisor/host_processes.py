"""Separate native human process owner. No model policy or permissive retry.

Lifecycle control below is forked from the qualified Bionic process owner;
its managed production source and runner remain unchanged. Filesystem ownership
is the existing HostFileAuthority/rootFD/lease, never another opened backend.
"""
import asyncio
import base64
from dataclasses import dataclass
import json
import os
import socket
import struct

from tools.executor.exec_server import RpcError
from tools.executor.native_environment import process_environment
from tools.executor.native_host_files import HostFileAuthority
from tools.executor.native_processes import COMPLETED_SECONDS, _Process, _finish, _packet, _receive, _wait_owned, _fd_ready
from .host_policy import HostProcessPolicy
from .host_wire import envelope, seal
from .processes import Processes


@dataclass(frozen=True)
class HostLimits:
    wall_ms: object = None
    output_bytes: object = None
    cpu_seconds: object = None
    data_bytes: int = 268435456
    file_bytes: int = 16777216
    uid_task_budget: int = 8
    descriptors: int = 128

    def __post_init__(self):
        optional = (self.wall_ms, self.output_bytes, self.cpu_seconds)
        if any(value is not None and (type(value) is not int or not 1 <= value < 2**53) for value in optional):
            raise ValueError("Invalid explicit host timeout/output/CPU allowance")
        bounded = (self.data_bytes, self.file_bytes, self.uid_task_budget, self.descriptors)
        bounds = ((16777216, 2147483648), (1, 1073741824), (1, 128), (16, 1024))
        if any(type(value) is not int or not low <= value <= high for value, (low, high) in zip(bounded, bounds)):
            raise ValueError("Invalid native host resource allowance")


class HostProcesses(Processes):
    def __init__(self, authority, runner, *, runtime, executables, limits=None, cwd_shim=None):
        if type(authority) is not HostFileAuthority:
            raise TypeError("An existing owner-issued host authority is required")
        owner = authority._owner
        if owner.closing or owner.files.closed or owner.processes.quarantined:
            raise PermissionError("Native host owner is closing or quarantined")
        self.authority = authority
        super().__init__(runner, authority._files.mount.path, runtime=runtime, executables=executables,
            limits=limits or HostLimits(), cwd_shim=cwd_shim, guest_workspace=authority._files.mount.path,
            files_backend=authority._files)
        self.event_lock = asyncio.Lock()
        self.disconnected = asyncio.Event()
        owner._host_process_owners.append(self)

    async def _notify(self, record):
        try:
            await super()._notify(record)
        finally:
            if record.failure == "Process notification transport failed":
                self.disconnected.set()
                for owned in self.processes.values():
                    self._terminate(owned)

    def _quarantine_owner(self):
        self.quarantined = True
        self.quarantine_event.set()
        self.authority._owner.processes.quarantined = True
        self.authority._owner.processes.quarantine_event.set()

    async def spawn(self, key, command, cwd, environment, *, pipe_stdin, notify):
        owner = self.authority._owner
        owner._bind(self.authority._session_id)
        if owner.closing or owner.files.closed or owner.processes.quarantined or self.disconnected.is_set():
            raise RpcError(-32603, "Native host process authority is unavailable")
        if (type(key) is not str or not key or len(key.encode('utf-8')) > 128
                or type(command) is not list or not command or len(command) > 256
                or any(type(value) is not str or '\0' in value for value in command)
                or type(cwd) is not str or type(pipe_stdin) is not bool or not callable(notify)):
            raise RpcError(-32602, "Invalid native host command")
        executable = self.executables.get(command[0])
        if executable is None:
            raise RpcError(-32602, "Host executable is outside its bootstrap runtime mapping")
        environment = process_environment({"env": environment})
        identity = (self.authority._session_id, key)
        if identity in self.processes or len(self.processes) >= 128:
            raise RpcError(-32600, "Host process handle already exists or registry is full")
        loop = asyncio.get_running_loop()
        params = json.dumps({"cwd": cwd, "pipeStdin": pipe_stdin}).encode('utf-8')
        record = _Process(identity[0], key, params, key, notify, executable, tuple(command),
            environment, loop.create_future(), loop.create_future())
        record.host_eof_queued = not pipe_stdin
        self.processes[identity] = record
        record.task = asyncio.create_task(self._run(record))
        try:
            await _wait_owned(record.started)
            return record
        except BaseException:
            self._terminate(record)
            await _finish(record.finished)
            raise

    async def write(self, record, data, *, close_stdin):
        if self.processes.get((record.session, record.key)) is not record:
            raise RpcError(-32600, "Host process is outside this authority")
        if type(data) is not bytes or len(data) > 32768 or type(close_stdin) is not bool:
            raise RpcError(-32602, "Host stdin requires a bounded complete byte chunk")
        while True:
            record.write_changed.clear()
            if record.host_eof_queued or record.stdin_closed or record.termination_requested:
                raise RpcError(-32603, "Host stdin is closed")
            if record.queued_bytes + len(data) <= 65536 and len(record.writes) < 128:
                if data:
                    record.writes.append(data)
                    record.queued_bytes += len(data)
                if close_stdin:
                    record.writes.append(None)
                    record.host_eof_queued = True
                record.write_changed.set()
                return
            await record.write_changed.wait()

    async def _writer(self, record):
        try:
            while not record.termination_requested and not record.stdin_closed:
                record.write_changed.clear()
                if not record.writes:
                    await record.write_changed.wait()
                    continue
                data = record.writes[0]
                if data is None:
                    break
                view = memoryview(data)
                while view:
                    try:
                        count = os.write(record.stdin, view)
                        if count <= 0:
                            raise BrokenPipeError("Native host stdin made no progress")
                        view = view[count:]
                    except BlockingIOError:
                        await _fd_ready(record.stdin, writing=True)
                record.writes.popleft()
                record.queued_bytes -= len(data)
                record.write_changed.set()
        except BrokenPipeError:
            pass
        finally:
            if record.stdin >= 0:
                os.close(record.stdin); record.stdin = -1
            record.stdin_closed = True
            record.writes.clear(); record.queued_bytes = 0
            record.write_changed.set()

    async def _event_async(self, record, method, payload):
        # Serial admission preserves sequence ordering even while actual output
        # waits for bounded transport capacity. Disconnect drains owned pipes.
        async with self.event_lock:
            if self.disconnected.is_set():
                return
            params = {"processId": record.key, "seq": record.next_seq, **payload}
            sending = asyncio.create_task(record.notifications.put((method, params)))
            disconnected = asyncio.create_task(self.disconnected.wait())
            try:
                await asyncio.wait((sending, disconnected), return_when=asyncio.FIRST_COMPLETED)
                if sending.done():
                    sending.result()
                    record.next_seq += 1
            finally:
                for task in (sending, disconnected):
                    if not task.done(): task.cancel()
                await asyncio.gather(sending, disconnected, return_exceptions=True)

    async def _output(self, record, stream, name):
        while data := await stream.read(32768):
            record.byte_counts[name] += len(data)
            if name == "stderr" and record.state == "starting":
                record.setup_diagnostic = (record.setup_diagnostic + data)[:4096]
            if self.limits.output_bytes is not None and sum(record.byte_counts.values()) > self.limits.output_bytes:
                raise RpcError(-32603, "Native host output exceeded its explicit contract")
            try:
                await _wait_owned(record.started)
            except RpcError:
                continue
            await self._event_async(record, "process/output", {"stream": name, "chunk": base64.b64encode(data).decode('ascii')})

    async def _end_events(self, record):
        if self.disconnected.is_set():
            record.notifier.cancel()
            return
        stopping = asyncio.create_task(record.notifications.put(None))
        disconnected = asyncio.create_task(self.disconnected.wait())
        try:
            await asyncio.wait((stopping, disconnected, record.notifier), return_when=asyncio.FIRST_COMPLETED)
            if not stopping.done():
                record.notifier.cancel()
        finally:
            for task in (stopping, disconnected):
                if not task.done(): task.cancel()
            await asyncio.gather(stopping, disconnected, return_exceptions=True)

    async def close(self, session_id):
        if session_id != self.authority._session_id:
            raise RpcError(-32600, "Host process close targets another session")
        self.disconnected.set()
        for record in self.processes.values():
            if record.notifier is not None:
                record.notifier.cancel()
        try:
            await super().close(session_id)
        finally:
            if self.quarantined:
                self._quarantine_owner()

    async def _control(self, record, endpoint):
        ready = False
        input_closed = False

        async def answer(payload):
            nonlocal input_closed
            try:
                await _packet(endpoint, payload)
            except BrokenPipeError:
                # The native owner seals its receive side after terminal
                # cleanup. A decision or startup ACK may finish concurrently.
                # EPIPE proves only that this half-channel closed; continue
                # reading and require the real final result and owner wait.
                input_closed = True

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
                if ready or message != {"type": "ready", "profile": "bionic-host-v1"}:
                    raise RpcError(-32603, "Invalid Bionic startup handshake")
                ready = True
                await answer(b"P")
            elif kind == "acquire":
                if not ready or input_closed or record.native_result is not None:
                    raise RpcError(-32603, "Acquisition outside its bound process lifetime")
                evaluating = asyncio.create_task(asyncio.to_thread(record.policy.decide, message))
                decision = await _finish(evaluating)
                relative = decision["relative"].encode("utf-8")
                response = struct.pack("<QiI4Q", decision["id"], decision["error"], len(relative),
                    decision["device"], decision["inode"], decision["parentDevice"], decision["parentInode"]) + relative
                if not record.termination_requested:
                    await answer(response)
            elif kind == "started":
                if not ready or record.native_started is not None or message != {
                    "type": "started", "profile": "bionic-host-v1", "setupCompleted": True}:
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
                    await self._event_async(record, "process/exited", {"exitCode": record.exit_code, "sandboxDenied": False})
                record.write_changed.set()
            elif kind == "ownership-retained":
                if message != {"type": "ownership-retained", "cleanupComplete": False}:
                    raise RpcError(-32603, "Invalid retained-ownership record")
                self.quarantined = True
                self.quarantine_event.set()
                self._quarantine_owner()
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
                    record.started.set_exception(RpcError(-32603,
                        "Bionic command failed before setup completed: "
                        f"outcome={message['outcome']} stage={message['stage']} errno={message['errno']}"))
            else:
                raise RpcError(-32603, "Unknown Bionic lifecycle record")

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
            preparing = asyncio.create_task(asyncio.to_thread(HostProcessPolicy, self.authority, params["cwd"]))
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
            sealed = seal(envelope(workspace=self.workspace, cwd=params["cwd"],
                executable=record.executable.path, argv=record.argv, environment=environment, runtime=self.runtime,
                timeout_ms=limits.wall_ms, data_bytes=limits.data_bytes, file_bytes=limits.file_bytes,
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
            done, _ = await asyncio.wait((communication,), timeout=None if limits.wall_ms is None else limits.wall_ms / 1000 + 8)
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
                self._quarantine_owner()
            # Unknown cleanup retains live tasks, native owner, policy and the
            # exact filesystem lease. There is no automatic permissive retry.
            if retained:
                self._quarantine_owner()
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
                await self._event_async(record, "process/closed", {})
            record.changed.set()
            if not started:
                self.failed.append(record)
                self.processes.pop((record.session, record.key), None)
            elif record.closed:
                asyncio.get_running_loop().call_later(COMPLETED_SECONDS, self._expire, record)
            await self._end_events(record)
            if not record.finished.done():
                record.finished.set_result(None)
