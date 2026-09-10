"""Official process wire over the private static native acquisition profile.

This backend is opt-in and requires the native --process-v2 supervisor mode.
It does not activate Desktop, translate managed policies to additive grants,
provide a shell, or admit TTY/network/dynamic executables. Runtime mappings and
resource allowances are executor-owned constructor inputs, never RPC fields.
"""
import asyncio
import array
import base64
from collections import OrderedDict, deque
import ctypes
from dataclasses import dataclass, field
import errno
import json
import os
from pathlib import Path
import signal
import socket
import stat
from types import MappingProxyType

from tools.executor.exec_server import RpcError, validate_operation
from tools.executor.native_environment import process_environment, snapshot_environment
from tools.executor.native_process_policy import NativeProcessPolicy, strict_json

METHODS = frozenset({"process/start", "process/read", "process/write", "process/signal", "process/terminate"})
RETAINED_BYTES = 1024 * 1024
RETAINED_CHUNKS = 50000
RETAINED_WRITE_IDS = 4096
COMPLETED_SECONDS = 30
# Explicit private-profile capacity limits; output history above matches upstream.
STDIN_BYTES = 1024 * 1024
NOTIFICATION_CAPACITY = 128
# Linux UAPI, verified against NDK r29 linux/memfd.h, linux/fcntl.h and
# asm-generic/fcntl.h by native-process-fd-abi.c in the frozen build. CPython
# Android need not expose os.memfd_create or any Python F_*_SEALS constant.
NATIVE_FD_ABI = MappingProxyType({"MFD_CLOEXEC": 0x0001, "MFD_ALLOW_SEALING": 0x0002,
    "F_ADD_SEALS": 1024 + 9, "F_GET_SEALS": 1024 + 10, "F_SEAL_SEAL": 0x0001,
    "F_SEAL_SHRINK": 0x0002, "F_SEAL_GROW": 0x0004, "F_SEAL_WRITE": 0x0008})
_LIBC = ctypes.CDLL(None, use_errno=True)
_MEMFD_CREATE = _LIBC.memfd_create
_MEMFD_CREATE.argtypes = [ctypes.c_char_p, ctypes.c_uint]
_MEMFD_CREATE.restype = ctypes.c_int
_FCNTL_INT = _LIBC.fcntl
_FCNTL_INT.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
_FCNTL_INT.restype = ctypes.c_int
_PIDFD_SEND_SIGNAL = _LIBC.pidfd_send_signal
_PIDFD_SEND_SIGNAL.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
_PIDFD_SEND_SIGNAL.restype = ctypes.c_int


def _signal_pidfd(fd, signum):
    if _PIDFD_SEND_SIGNAL(fd, signum, None, 0) == 0:
        return True
    number = ctypes.get_errno()
    if number == errno.ESRCH:
        return False
    raise OSError(number, os.strerror(number))


async def _receive_supervisor(endpoint, expected_pid):
    """Accept only the native supervisor's pinned pidfd, before acknowledging it."""
    descriptors = []
    try:
        while True:
            try:
                payload, ancillary, flags, _ = endpoint.recvmsg(512, socket.CMSG_SPACE(4 * array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC)
                break
            except BlockingIOError:
                await _fd_ready(endpoint.fileno())
        valid = len(ancillary) == 1
        for level, kind, data in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                values = array.array("i")
                values.frombytes(data[:len(data) - len(data) % values.itemsize])
                descriptors.extend(values)
                valid = valid and len(data) == values.itemsize
            else:
                valid = False
        if not valid or len(descriptors) != 1 or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
            raise RpcError(-32603, "Native supervisor did not transfer exactly one pinned process identity")
        message = strict_json(payload)
        if (type(message) is not dict or type(message.get("pid")) is not int
                or message != {"type": "supervisor", "pid": expected_pid, "profile": "managed-process-v2"}):
            raise RpcError(-32603, "Native supervisor identity message differs")
        fd = descriptors[0]
        if os.get_inheritable(fd):
            raise RpcError(-32603, "Native supervisor identity is inheritable")
        with open(f"/proc/self/fdinfo/{fd}", "rb") as source:
            info = source.read(4097)
        observed = [line.split(b":", 1)[1].strip() for line in info.splitlines() if line.startswith(b"Pid:")]
        if len(info) > 4096 or observed != [str(expected_pid).encode()] or not _signal_pidfd(fd, 0):
            raise RpcError(-32603, "Native pidfd does not identify the expected live supervisor")
        descriptors.clear()
        return fd, {**message, "closeOnExec": True, "identityRoute": "native-self-pidfd/SCM_RIGHTS", "waitOwner": "asyncio"}
    finally:
        for fd in descriptors:
            os.close(fd)


def _native_fcntl(fd, command, value=0):
    result = _FCNTL_INT(fd, command, value)
    if result < 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    return result


async def _wait_owned(future):
    """Observe an already-owned future without transferring its cancellation.

    The lifecycle owner retains the future and retrieves its terminal result.
    Unlike shield(), wait() does not attach a second exception-reporting owner
    when a caller stops waiting (notably Python 3.14's shield callback).
    """
    await asyncio.wait((future,))
    return future.result()


async def _finish(task):
    """Do not abandon process ownership on repeated transport cancellation."""
    while True:
        try:
            return await _wait_owned(task)
        except asyncio.CancelledError:
            if task.done():
                return task.result()


async def _fd_ready(fd, writing=False):
    loop = asyncio.get_running_loop()
    ready = loop.create_future()
    def complete():
        if not ready.done():
            ready.set_result(None)
    add, remove = (loop.add_writer, loop.remove_writer) if writing else (loop.add_reader, loop.remove_reader)
    add(fd, complete)
    try:
        await ready
    finally:
        remove(fd)


async def _packet(endpoint, payload):
    while True:
        try:
            if endpoint.send(payload) != len(payload):
                raise RpcError(-32603, "Native control packet was not sent atomically")
            return
        except BlockingIOError:
            await _fd_ready(endpoint.fileno(), True)


async def _receive(endpoint):
    while True:
        try:
            payload, ancillary, flags, _ = endpoint.recvmsg(16384)
            if ancillary or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                raise RpcError(-32603, "Native control frame violated its boundary")
            return strict_json(payload) if payload else None
        except BlockingIOError:
            await _fd_ready(endpoint.fileno())


def _sealed_environment(encoded):
    # Use the actual libc symbol on Linux and Android so the Bionic route is
    # exercised by every host conformance launch, not an untested fallback.
    fd = _MEMFD_CREATE(b"native-process-environment",
        NATIVE_FD_ABI["MFD_CLOEXEC"] | NATIVE_FD_ABI["MFD_ALLOW_SEALING"])
    if fd < 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))
    try:
        view = memoryview(encoded)
        while view:
            count = os.write(fd, view)
            view = view[count:]
        os.lseek(fd, 0, os.SEEK_SET)
        seals = (NATIVE_FD_ABI["F_SEAL_WRITE"] | NATIVE_FD_ABI["F_SEAL_GROW"] |
            NATIVE_FD_ABI["F_SEAL_SHRINK"] | NATIVE_FD_ABI["F_SEAL_SEAL"])
        _native_fcntl(fd, NATIVE_FD_ABI["F_ADD_SEALS"], seals)
        if _native_fcntl(fd, NATIVE_FD_ABI["F_GET_SEALS"]) & seals != seals:
            raise OSError("Native environment seals were not retained")
        return fd
    except BaseException:
        os.close(fd)
        raise


@dataclass(frozen=True)
class NativeProcessLimits:
    wall_ms: int = 3600000
    address_space_bytes: int = 256 * 1024 * 1024
    output_bytes: int = 64 * 1024 * 1024
    uid_task_budget: int = 128

    def __post_init__(self):
        bounds = ((self.wall_ms, 1, 3600000), (self.address_space_bytes, 16777216, 17179869184),
                  (self.output_bytes, 1, 67108864), (self.uid_task_budget, 1, 2**32 - 1))
        if any(type(value) is not int or not lower <= value <= upper for value, lower, upper in bounds):
            raise ValueError("Invalid declared native process resource allowance")


@dataclass(frozen=True)
class NativeExecutable:
    path: str
    device: int
    inode: int

    @classmethod
    def admit(cls, value):
        path = Path(value).absolute()
        if path != path.resolve(strict=True):
            raise ValueError("Native runtime aliases are unsupported")
        info = path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Native runtime must name a real regular executable")
        return cls(str(path), info.st_dev, info.st_ino)


@dataclass
class _Process:
    session: str
    key: str
    params_json: bytes
    request_id: object
    notify: object
    executable: NativeExecutable
    argv: tuple
    environment: bytes
    started: object
    finished: object
    state: str = "starting"
    task: object = None
    policy: object = None
    process: object = None
    command: object = None
    stdin: int = -1
    stdin_closed: bool = False
    termination_requested: bool = False
    cancellation: object = field(default_factory=asyncio.Event)
    output: object = field(default_factory=deque)
    retained_bytes: int = 0
    next_seq: int = 1
    exit_code: object = None
    closed: bool = False
    failure: object = None
    sandbox_denied: bool = False
    changed: object = field(default_factory=asyncio.Event)
    write_changed: object = field(default_factory=asyncio.Event)
    writes: object = field(default_factory=deque)
    queued_bytes: int = 0
    accepted_ids: object = field(default_factory=OrderedDict)
    notifications: object = field(default_factory=lambda: asyncio.Queue(NOTIFICATION_CAPACITY))
    notifier: object = None
    native_started: object = None
    native_result: object = None
    setup_diagnostic: bytes = b""
    supervisor_fd: int = -1
    supervisor_identity: object = None
    supervisor_signals: object = field(default_factory=list)
    byte_counts: object = field(default_factory=lambda: {"stdout": 0, "stderr": 0})


class NativeProcessesBackend:
    supported_methods = METHODS
    capabilities = frozenset()

    def __init__(self, runner, workspace, *, executables, guest_workspace="/workspace", limits=None,
                 mutation_lease=None, files_backend=None, parent_environment=None):
        self.runner = str(Path(runner).resolve(strict=True))
        self.workspace = str(Path(workspace).absolute())
        self.guest_workspace = guest_workspace
        self.parent_environment = snapshot_environment(parent_environment)
        self.executables = MappingProxyType({name: NativeExecutable.admit(value) for name, value in executables.items()})
        if not self.executables or any(type(name) is not str or not name for name in self.executables):
            raise ValueError("An explicit immutable native runtime mapping is required")
        if any(Path(value.path).is_relative_to(self.workspace) for value in self.executables.values()):
            raise ValueError("Native runtime grants must not overlap the managed workspace")
        self.limits = limits or NativeProcessLimits()
        self.files_backend = files_backend
        if files_backend is not None:
            info = os.stat(self.workspace, follow_symlinks=False)
            pinned = os.fstat(files_backend.root)
            if files_backend.closed or (info.st_dev, info.st_ino) != (pinned.st_dev, pinned.st_ino) or files_backend.mount.path != guest_workspace:
                raise ValueError("Composed filesystem backend must own the same pinned workspace")
            if mutation_lease is not None and mutation_lease is not files_backend.lock:
                raise ValueError("Composed process and file backends must share their mutation lock")
        self.lease = files_backend.lock if files_backend is not None else mutation_lease or asyncio.Lock()
        self.processes = {}
        self.failed = deque(maxlen=128)
        self.closing_sessions = set()
        self.quarantined = False
        self.quarantine_event = asyncio.Event()

    def _get(self, session, key):
        return self.processes.get((session, key))

    async def handle(self, call, notify):
        validate_operation(call.method, call.params)
        if call.method not in METHODS:
            raise RpcError(-32601, "Unsupported native process method")
        if call.session_id in self.closing_sessions:
            raise RpcError(-32600, "Native process session is closing")
        params = call.params
        if call.method == "process/start":
            return await self._start(call, notify)
        record = self._get(call.session_id, params["processId"])
        if call.method == "process/read":
            return await self._read(record, params)
        if call.method == "process/write":
            return await self._write(record, params)
        if call.method == "process/signal":
            if record is not None and record.state == "running" and record.exit_code is None:
                sending = asyncio.create_task(_packet(record.command, b"I"))
                try:
                    done, _ = await asyncio.wait((sending, record.finished), return_when=asyncio.FIRST_COMPLETED)
                    if sending in done:
                        await sending
                    elif record.exit_code is None:
                        raise RpcError(-32603, "Native interrupt transport ended without an observed exit")
                except (OSError, ValueError):
                    if record.exit_code is None:
                        raise RpcError(-32603, "Native interrupt transport failed before an observed exit")
                finally:
                    if not sending.done():
                        sending.cancel()
                    await asyncio.gather(sending, return_exceptions=True)
            return {}
        running = record is not None and record.state in {"starting", "running"} and record.exit_code is None
        if running:
            self._terminate(record)
        return {"running": running}

    def _validate_launch_context(self, params):
        # This original static profile executes at its policy cwd. Backends
        # with a separate native cwd must validate both roles before spawning.
        if params.get("sandbox") is None or params["cwd"] != params["sandbox"].get("cwd"):
            raise RpcError(-32602, "Native launch requires its complete matching portable sandbox context")

    async def _start(self, call, notify):
        params = call.params
        if self.quarantined:
            raise RpcError(-32603, "Native workspace cleanup is unknown; subsequent acquisition is refused")
        if params["tty"] or any(params.get(key) is not None for key in ("shellSnapshot", "managedNetwork", "networkProxy")) or params.get("enforceManagedNetwork"):
            raise RpcError(-32602, "TTY, shell snapshots and managed networking are outside the static native profile")
        argv = params["argv"]
        if not argv or len(argv) > 256 or any("\0" in value for value in argv):
            raise RpcError(-32602, "Invalid native argument vector")
        executable = self.executables.get(argv[0])
        if executable is None:
            raise RpcError(-32602, "Executable is outside the admitted native runtime mapping")
        arg0 = params.get("arg0")
        if arg0 is not None and "\0" in arg0:
            raise RpcError(-32602, "Invalid native argv0")
        environment = process_environment(params, self.parent_environment)
        self._validate_launch_context(params)
        key = (call.session_id, params["processId"])
        if key in self.processes:
            raise RpcError(-32600, "Process id already exists in this session")
        if len(self.processes) >= 128:
            raise RpcError(-32000, "Static native process registry capacity exhausted")
        loop = asyncio.get_running_loop()
        record = _Process(call.session_id, params["processId"], call.params_json, call.request_id,
            notify, executable, tuple([arg0 if arg0 is not None else argv[0], *argv[1:]]),
            environment, loop.create_future(), loop.create_future())
        # Reservation and task creation contain no await and cannot race a duplicate.
        self.processes[key] = record
        record.task = asyncio.create_task(self._run(record))
        try:
            await _wait_owned(record.started)
            return {"processId": record.key, "sandboxType": "linuxSeccomp"}
        except asyncio.CancelledError:
            self._terminate(record)
            await _finish(record.finished)
            raise
        except Exception:
            await _finish(record.finished)
            raise

    def _terminate(self, record):
        record.termination_requested = True
        record.cancellation.set()
        record.write_changed.set()
        if record.command is not None:
            try:
                record.command.send(b"T")
            except (BlockingIOError, BrokenPipeError, OSError):
                # The supervisor remains the owned asyncio child. Its existing
                # SIGTERM path is the same cancellation/descendant cleanup path.
                if record.process is not None and record.process.returncode is None:
                    self._signal_supervisor(record, signal.SIGTERM)

    def _signal_supervisor(self, record, signum):
        # asyncio alone reaps its direct child. Popen.send_signal calls poll(),
        # which can steal waitpid from its watcher and invent returncode 255.
        # The received pidfd cannot refer to a later process reusing that PID.
        if record.supervisor_fd < 0:
            return False
        delivered = _signal_pidfd(record.supervisor_fd, signum)
        record.supervisor_signals.append({"signal": signum, "delivered": delivered, "route": "libc.pidfd_send_signal"})
        return delivered

    async def _notify(self, record):
        try:
            while True:
                item = await record.notifications.get()
                try:
                    if item is None:
                        return
                    await record.notify(*item)
                finally:
                    record.notifications.task_done()
        except asyncio.CancelledError:
            raise
        except Exception:
            record.failure = "Process notification transport failed"
            self._terminate(record)

    def _event(self, record, method, payload):
        seq = record.next_seq
        record.next_seq += 1
        params = {"processId": record.key, "seq": seq, **payload}
        if method == "process/output":
            data = base64.b64decode(payload["chunk"], validate=True)
            record.output.append(({"seq": seq, **payload}, len(data)))
            record.retained_bytes += len(data)
            while record.retained_bytes > RETAINED_BYTES or len(record.output) > RETAINED_CHUNKS:
                _, size = record.output.popleft()
                record.retained_bytes -= size
        record.changed.set()
        try:
            record.notifications.put_nowait((method, params))
        except asyncio.QueueFull:
            record.failure = "Native process notification capacity exhausted"
            self._terminate(record)

    async def _read(self, record, params):
        if record is None:
            raise RpcError(-32600, "Unknown process id in this session")
        if record.state == "starting":
            raise RpcError(-32600, "Process is starting")
        after = params.get("afterSeq") or 0
        maximum = params.get("maxBytes")
        deadline = asyncio.get_running_loop().time() + (params.get("waitMs") or 0) / 1000
        while True:
            record.changed.clear()
            chunks, total, next_seq = [], 0, record.next_seq
            for chunk, size in record.output:
                if chunk["seq"] <= after:
                    continue
                if chunks and maximum is not None and total + size > maximum:
                    break
                chunks.append(dict(chunk)); total += size; next_seq = chunk["seq"] + 1
                if maximum is not None and total >= maximum:
                    break
            if maximum is None:
                next_seq = record.next_seq
            response = {"chunks": chunks, "nextSeq": next_seq, "exited": record.exit_code is not None,
                "exitCode": record.exit_code, "closed": record.closed, "failure": record.failure,
                "sandboxDenied": record.sandbox_denied}
            remaining = deadline - asyncio.get_running_loop().time()
            if chunks or record.closed or (response["exited"] and after < max(0, next_seq - 1)) or remaining <= 0:
                return response
            try:
                await asyncio.wait_for(record.changed.wait(), remaining)
            except asyncio.TimeoutError:
                return response

    async def _write(self, record, params):
        identifier = params["writeId"]
        if not identifier:
            raise RpcError(-32602, "writeId must not be empty")
        if record is None:
            return {"status": "unknownProcess"}
        if record.state == "starting":
            return {"status": "starting"}
        if not json.loads(record.params_json).get("pipeStdin", False):
            return {"status": "stdinClosed"}
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

    async def _writer(self, record):
        try:
            while not record.termination_requested and not record.stdin_closed:
                record.write_changed.clear()
                if not record.writes:
                    await record.write_changed.wait()
                    continue
                data = record.writes[0]
                view = memoryview(data)
                while view:
                    try:
                        count = os.write(record.stdin, view)
                        view = view[count:]
                    except BlockingIOError:
                        await _fd_ready(record.stdin, True)
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

    async def _output(self, record, stream, name):
        while True:
            data = await stream.read(65536)
            if not data:
                return
            record.byte_counts[name] += len(data)
            if name == "stderr" and record.state == "starting":
                record.setup_diagnostic = (record.setup_diagnostic + data)[:4096]
            if sum(record.byte_counts.values()) > self.limits.output_bytes + 4096:
                raise RpcError(-32603, "Native process exceeded its output contract")
            try:
                await _wait_owned(record.started)
            except RpcError:
                continue  # Drain setup diagnostics without a false process notification.
            self._event(record, "process/output", {"stream": name, "chunk": base64.b64encode(data).decode("ascii")})

    async def _control(self, record, endpoint):
        record.supervisor_fd, record.supervisor_identity = await _receive_supervisor(endpoint, record.process.pid)
        await _packet(endpoint, b"P")
        record.supervisor_identity["acknowledgedBeforeWorker"] = True
        while True:
            message = await _receive(endpoint)
            if message is None:
                if record.native_result is None:
                    raise RpcError(-32603, "Native lifecycle socket closed without completion")
                return
            if type(message) is not dict:
                raise RpcError(-32603, "Native lifecycle message is not an object")
            kind = message.get("type")
            if kind == "open":
                work = asyncio.create_task(asyncio.to_thread(record.policy.decide, message))
                try:
                    reply = await _wait_owned(work)
                except asyncio.CancelledError:
                    await _finish(work)
                    raise
                try:
                    await _packet(endpoint, json.dumps(reply, separators=(",", ":")).encode())
                except BrokenPipeError:
                    if not record.termination_requested:
                        raise
            elif kind == "started":
                if record.native_started is not None or record.native_result is not None:
                    raise RpcError(-32603, "Native process emitted duplicate or late startup")
                required = {"type", "pid", "profile", "uidTasksObserved", "uidTaskBudget", "uidNprocLimit", "inheritedNprocSoft", "inheritedNprocHard"}
                if set(message) != required or message["profile"] != "managed-process-v2" or any(type(message[key]) is not int or message[key] < 0 for key in required - {"type", "profile"}):
                    raise RpcError(-32603, "Native process startup contract differs")
                record.native_started = message
                if record.termination_requested:
                    self._terminate(record)
                    continue
                record.state = "running"
                record.started.set_result(None)
            elif kind == "exited":
                if record.native_started is None or record.exit_code is not None or set(message) != {"type", "exitCode", "signal"}:
                    raise RpcError(-32603, "Invalid native leader exit observation")
                code, signum = message["exitCode"], message["signal"]
                if type(code) is not int or type(signum) is not int or not -1 <= code <= 255 or not 0 <= signum <= 64 or (signum and code != -1) or (not signum and code < 0):
                    raise RpcError(-32603, "Native exit status is invalid")
                record.exit_code = 128 + signum if signum else code
                if record.started.done() and record.started.exception() is None:
                    self._event(record, "process/exited", {"exitCode": record.exit_code, "sandboxDenied": False})
                record.write_changed.set()
            elif kind == "result":
                if record.native_result is not None:
                    raise RpcError(-32603, "Native process emitted duplicate completion")
                required = {"type", "outcome", "exitCode", "signal", "cleanupComplete", "started", "grants", "denials", "stdoutBytes", "stderrBytes", "stage", "errno"}
                if (set(message) != required or message["outcome"] not in {"exited", "cancelled", "timeout", "output_limit", "setup_error", "broker_error", "cleanup_error"}
                        or any(type(message[key]) is not bool for key in ("cleanupComplete", "started"))
                        or any(type(message[key]) is not int or message[key] < 0 for key in ("signal", "grants", "denials", "stdoutBytes", "stderrBytes", "stage", "errno"))
                        or type(message["exitCode"]) is not int or not -1 <= message["exitCode"] <= 255):
                    raise RpcError(-32603, "Native completion shape differs")
                record.native_result = message
                if not record.started.done():
                    record.started.set_exception(RpcError(-32603, "Native process failed before verified exec"))
            else:
                raise RpcError(-32603, "Unknown native lifecycle event")

    async def _run(self, record):
        children, endpoints, descriptors = [], [], []
        owned = False
        process = None
        spawning = None
        communication = None
        clean = False
        record.notifier = asyncio.create_task(self._notify(record))
        try:
            lease = asyncio.create_task(self.lease.acquire())
            cancellation = asyncio.create_task(record.cancellation.wait())
            try:
                await asyncio.wait((lease, cancellation), return_when=asyncio.FIRST_COMPLETED)
                if lease.done():
                    owned = lease.result()
                else:
                    lease.cancel()
                    await asyncio.gather(lease, return_exceptions=True)
            finally:
                cancellation.cancel()
                await asyncio.gather(cancellation, return_exceptions=True)
            if self.quarantined or record.termination_requested:
                raise RpcError(-32600, "Native process start was cancelled or its workspace quarantined")
            params = json.loads(record.params_json)
            preparing = asyncio.create_task(asyncio.to_thread(NativeProcessPolicy, self.runner, self.workspace,
                params["sandbox"], session_id=record.session, request_id=type(record.request_id).__name__ + ":" + str(record.request_id),
                guest_workspace=self.guest_workspace, backend=self.files_backend))
            try:
                record.policy = await _wait_owned(preparing)
            except asyncio.CancelledError:
                record.policy = await _finish(preparing)
                raise
            if record.termination_requested:
                raise RpcError(-32600, "Native process start was cancelled before spawn")
            info = os.stat(record.executable.path, follow_symlinks=False)
            if (info.st_dev, info.st_ino) != (record.executable.device, record.executable.inode):
                raise RpcError(-32603, "Admitted native executable identity changed")
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
            env_fd = _sealed_environment(record.environment); descriptors.append(env_fd)
            limits = self.limits
            arguments = [self.runner, str(record.policy.root), str(peer.fileno()), record.executable.path,
                str(limits.wall_ms), str(limits.address_space_bytes), str(limits.output_bytes), str(limits.uid_task_budget),
                "--process-v2", str(read_fd), str(command_peer.fileno()), str(env_fd), "--", *record.argv]
            spawning = asyncio.create_task(asyncio.create_subprocess_exec(*arguments,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                close_fds=True, pass_fds=(record.policy.root, peer.fileno(), command_peer.fileno(), read_fd, env_fd), env={}))
            process = await _wait_owned(spawning); record.process = process
            peer.close(); command_peer.close()
            for fd in descriptors:
                os.close(fd)
            descriptors.clear()
            children = [asyncio.create_task(self._control(record, control)),
                asyncio.create_task(self._output(record, process.stdout, "stdout")),
                asyncio.create_task(self._output(record, process.stderr, "stderr"))]
            writer = asyncio.create_task(self._writer(record)) if record.stdin >= 0 else None
            if writer is not None:
                children.append(writer)
            communication = asyncio.gather(*children[:3], process.wait())
            await asyncio.wait_for(_wait_owned(communication), limits.wall_ms / 1000 + 8)
            result = record.native_result
            required = {"type", "outcome", "exitCode", "signal", "cleanupComplete", "started", "grants", "denials", "stdoutBytes", "stderrBytes", "stage", "errno"}
            if type(result) is not dict or set(result) != required or result["cleanupComplete"] is not True:
                raise RpcError(-32603, "Native process lacks verified descendant cleanup")
            clean = True
            if result["stdoutBytes"] != record.byte_counts["stdout"] or result["stderrBytes"] != record.byte_counts["stderr"]:
                raise RpcError(-32603, "Native output accounting differs from actual pipes")
            if not record.started.done() or record.started.exception() is not None:
                raise RpcError(-32603, "Native process failed before verified exec")
            expected = 128 + result["signal"] if result["signal"] else result["exitCode"]
            if record.exit_code != expected or result["started"] is not True:
                raise RpcError(-32603, "Native final status differs from observed leader exit")
            if result["outcome"] not in {"exited", "cancelled"}:
                record.failure = "Native process ended with " + str(result["outcome"])
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            record.failure = record.failure or ("Native process start cancelled" if isinstance(error, asyncio.CancelledError) else "Native process supervision failed")
            if not record.started.done():
                failure = RpcError(-32603, record.failure)
                failure.__cause__ = error
                record.started.set_exception(failure)
        finally:
            if process is None and spawning is not None:
                try:
                    process = await _finish(spawning); record.process = process
                except Exception:
                    pass
            if process is not None and not children:
                # A cancellation may win exactly while create_subprocess_exec
                # completes. Adopt the real child and its pipes before cleanup.
                peer.close(); command_peer.close()
                for fd in descriptors:
                    os.close(fd)
                descriptors.clear()
                children = [asyncio.create_task(self._control(record, control)),
                    asyncio.create_task(self._output(record, process.stdout, "stdout")),
                    asyncio.create_task(self._output(record, process.stderr, "stderr"))]
            if process is not None and process.returncode is None:
                self._terminate(record)
                try:
                    await asyncio.wait_for(asyncio.shield(process.wait()), 7)
                except asyncio.TimeoutError:
                    self._signal_supervisor(record, signal.SIGKILL)
                    try:
                        await asyncio.wait_for(asyncio.shield(process.wait()), 3)
                    except asyncio.TimeoutError:
                        pass  # Retain ownership/quarantine; no invented reaping.
                    record.failure = "Native supervisor lost; descendant cleanup is unknown"
            if record.native_result is not None and record.native_result.get("cleanupComplete") is True:
                clean = True
            for child in children:
                if not child.done():
                    child.cancel()
            if children:
                await asyncio.gather(*children, return_exceptions=True)
            if communication is not None:
                if not communication.done():
                    communication.cancel()
                await asyncio.gather(communication, return_exceptions=True)
            if record.stdin >= 0:
                os.close(record.stdin); record.stdin = -1
            record.stdin_closed = True; record.write_changed.set()
            for endpoint in endpoints:
                endpoint.close()
            record.command = None
            if record.supervisor_fd >= 0 and process is not None and process.returncode is not None:
                os.close(record.supervisor_fd); record.supervisor_fd = -1
            for fd in descriptors:
                os.close(fd)
            if process is not None and not clean:
                self.quarantined = True
                self.quarantine_event.set()
                record.failure = "Native descendant cleanup is unknown; workspace remains quarantined"
            if record.policy is not None and (process is None or clean):
                record.policy.close()
            # The shared filesystem backend owns this very same lock. Releasing
            # it after supervisor loss could admit writes while descendants are
            # still alive. Only an independently verified recovery may release it.
            if owned and (process is None or clean):
                self.lease.release()
            was_started = record.started.done() and not record.started.cancelled() and record.started.exception() is None
            if not record.started.done():
                record.started.set_exception(RpcError(-32603, record.failure or "Native process failed before exec"))
            record.state = "complete"; record.closed = clean or process is None
            if was_started and record.closed:
                self._event(record, "process/closed", {})
            record.changed.set()
            if not was_started:
                self.failed.append(record)
                self.processes.pop((record.session, record.key), None)
            elif record.closed:
                asyncio.get_running_loop().call_later(COMPLETED_SECONDS, self._expire, record)
            try:
                record.notifications.put_nowait(None)
            except asyncio.QueueFull:
                record.notifier.cancel()
            # Notification delivery cannot prevent real process cleanup/read/terminate.
            if not record.finished.done():
                record.finished.set_result(None)

    def _expire(self, record):
        key = (record.session, record.key)
        if self.processes.get(key) is record and record.closed:
            self.processes.pop(key, None)

    async def close(self, session_id):
        self.closing_sessions.add(session_id)
        records = [record for (session, _), record in self.processes.items() if session == session_id]
        records.extend(record for record in self.failed if record.session == session_id and not record.closed)
        for record in records:
            if not record.finished.done():
                self._terminate(record)
        for record in records:
            await _finish(record.finished)
            if record.notifier is not None and not record.notifier.done():
                record.notifier.cancel()
            if record.notifier is not None:
                await asyncio.gather(record.notifier, return_exceptions=True)
            self.processes.pop((session_id, record.key), None)
        if any(record.process is not None and not record.closed for record in records):
            raise RpcError(-32603, "Session closed with unknown native descendant cleanup")
