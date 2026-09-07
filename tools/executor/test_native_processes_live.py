"""Real nonroot kernel tests for official native process lifecycle semantics."""
import argparse
import asyncio
import base64
import errno
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.executor.exec_server import BackendCall, RpcError, encode_message
from tools.executor.native_processes import NativeProcessLimits, NativeProcessesBackend

RUNNER = FIXTURE = FILES_HELPER = PARENT = EVIDENCE = None
ADDRESS_SPACE = 256 * 1024 * 1024
OBSERVATIONS = []


def process_children_snapshot(pid):
    """Observe real same-UID children using proc status on Linux and Android.

    Android need not expose CONFIG_PROC_CHILDREN. A missing or unreadable
    same-UID status is therefore an observation failure, never an empty family.
    Foreign-UID access denials and processes that actually vanish are recorded.
    The parent is checked before and after the inventory to reject PID reuse.
    """
    uid, observer = os.getuid(), os.getpid()

    def status(target):
        with (Path('/proc') / str(target) / 'status').open('rb') as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise RuntimeError('Unbounded proc status')
        fields = {}
        for line in data.splitlines():
            key, separator, value = line.partition(b':')
            if separator and key in (b'Pid', b'PPid', b'Uid'):
                if key in fields:
                    raise RuntimeError('Duplicate proc identity field')
                fields[key] = [int(part) for part in value.split()]
        if set(fields) != {b'Pid', b'PPid', b'Uid'} or fields[b'Pid'] != [target] \
                or len(fields[b'PPid']) != 1 or len(fields[b'Uid']) != 4:
            raise RuntimeError('Incomplete proc identity')
        return {'pid': target, 'ppid': fields[b'PPid'][0], 'uids': fields[b'Uid']}

    def parent_identity():
        value = status(pid)
        # comm may contain spaces or parentheses; starttime is stat field 22.
        data = (Path('/proc') / str(pid) / 'stat').read_bytes()
        tail = data.rsplit(b')', 1)[1].split()
        value['startTimeTicks'] = int(tail[19])
        if value['uids'] != [uid] * 4:
            raise RuntimeError('Child inventory parent is outside the observer UID')
        return value

    before = parent_identity()
    visible = sorted(int(path.name) for path in Path('/proc').iterdir() if path.name.isdecimal())
    readable, vanished, foreign = [], [], []
    for target in visible:
        try:
            readable.append(status(target))
        except FileNotFoundError:
            if (Path('/proc') / str(target)).exists():
                raise RuntimeError(f'Live process {target} has no readable status')
            vanished.append(target)
        except PermissionError:
            try:
                owner = (Path('/proc') / str(target)).stat().st_uid
            except FileNotFoundError:
                vanished.append(target)
                continue
            if owner == uid or target in (pid, observer):
                raise RuntimeError(f'Cannot inspect same-UID process {target}')
            foreign.append({'pid': target, 'ownerUid': owner})
    after = parent_identity()
    identities = {value['pid']: value for value in readable}
    if before != after or pid not in identities or observer not in identities \
            or identities[pid] != {key: before[key] for key in ('pid', 'ppid', 'uids')} \
            or identities[observer]['uids'] != [uid] * 4:
        raise RuntimeError('Proc inventory lost the actual parent or observer identity')
    children = sorted(value['pid'] for value in readable if value['ppid'] == pid)
    if any(identities[child]['uids'] != [uid] * 4 for child in children):
        raise RuntimeError('Unexpected child outside the observer UID')
    return {'route': 'proc-status-ppid', 'observerPid': observer, 'observerUid': uid,
        'parent': before, 'visiblePids': visible, 'readableProcesses': readable,
        'vanishedPids': vanished, 'inaccessibleForeignProcesses': foreign, 'children': children}


def context(access="write"):
    return {"permissions": {"type": "managed", "file_system": {"type": "restricted", "entries": [
        {"path": {"type": "path", "path": "file:///workspace"}, "access": access},
        {"path": {"type": "path", "path": "file:///workspace/private"}, "access": "deny"}]}, "network": "restricted"},
        "cwd": "file:///workspace", "workspaceRoots": ["file:///workspace"], "useLegacyLandlock": False,
        "windowsSandboxLevel": "disabled", "windowsSandboxPrivateDesktop": False}


class NativeProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertNotEqual(os.getuid(), 0)
        self.temporary = tempfile.TemporaryDirectory(prefix="native-process-live-", dir=PARENT)
        self.work = Path(self.temporary.name)
        self.root = self.work / "workspace"; self.root.mkdir(mode=0o700)
        (self.root / "value").write_bytes(b"native-original")
        (self.root / "value").chmod(0o600)
        (self.root / "private").mkdir(mode=0o700)
        (self.root / "private/secret").write_bytes(b"private-intact")
        (self.root / "private/secret").chmod(0o600)
        self.backend = NativeProcessesBackend(RUNNER, self.root, executables={"native-fixture": FIXTURE},
            limits=NativeProcessLimits(wall_ms=3000, address_space_bytes=ADDRESS_SPACE))
        self.notifications = []
        self.sequence = 0

    async def asyncTearDown(self):
        records = list(self.backend.processes.values())
        for session in {record.session for record in records}:
            await self.backend.close(session)
        for record in records:
            if record.native_started is not None:
                with self.assertRaises(ProcessLookupError):
                    os.kill(record.native_started["pid"], 0)
        self.temporary.cleanup()

    async def notify(self, method, params):
        # Round-trip actual official JSON envelopes; bytes are Base64 only.
        self.notifications.append(json.loads(encode_message({"method": method, "params": params})))

    async def call(self, method, params, session="session-one"):
        self.sequence += 1
        call = BackendCall(session, self.sequence, method, encode_message(params))
        try:
            result = await self.backend.handle(call, self.notify)
            OBSERVATIONS.append({"test": self.id(), "method": method, "session": session,
                                 "params": params, "result": result})
            return result
        except RpcError as error:
            if method == "process/start":
                await asyncio.sleep(0)
                if self.backend.failed and self.backend.failed[-1].setup_diagnostic:
                    print("native setup diagnostic:", repr(self.backend.failed[-1].setup_diagnostic), file=sys.stderr)
            OBSERVATIONS.append({"test": self.id(), "method": method, "session": session,
                                 "params": params, "error": error.response(self.sequence)})
            raise

    async def start(self, name="process", args=("stdio",), session="session-one", **extra):
        return await self.call("process/start", {"processId": name, "argv": ["native-fixture", *args],
            "cwd": "file:///workspace", "env": {}, "tty": False, "sandbox": context(), **extra}, session)

    async def completed(self, name="process", session="session-one"):
        record = self.backend.processes[(session, name)]
        await asyncio.wait_for(asyncio.shield(record.finished), 10)
        if record.notifier is not None:
            await asyncio.wait_for(asyncio.shield(record.notifier), 2)
        result = await self.call("process/read", {"processId": name}, session)
        self.assertTrue(result["closed"], result)
        self.assertTrue(result["exited"], result)
        self.assertTrue(record.native_result["cleanupComplete"], record.native_result)
        OBSERVATIONS.append({"test": self.id(), "nativeStarted": record.native_started,
            "nativeResult": record.native_result, "notifications": list(self.notifications),
            "supervisorIdentity": record.supervisor_identity, "supervisorSignals": record.supervisor_signals,
            "supervisorReturncode": record.process.returncode})
        return result

    @staticmethod
    def output(response, stream="stdout"):
        return b"".join(base64.b64decode(item["chunk"], validate=True) for item in response["chunks"] if item["stream"] == stream)

    async def until_output(self, name, expected):
        for _ in range(30):
            value = await self.call("process/read", {"processId": name, "waitMs": 100})
            if expected in self.output(value):
                return value
            await asyncio.sleep(0)
        self.fail("Actual native output did not arrive")

    async def test_01_real_exec_binary_streams_and_nonzero_exit(self):
        self.assertEqual(await self.start(), {"processId": "process", "sandboxType": "linuxSeccomp"})
        result = await self.completed()
        self.assertEqual(result["exitCode"], 17)
        self.assertIsNone(result["failure"])
        self.assertEqual(self.output(result), b"\0\xff\x80OUT")
        self.assertEqual(self.output(result, "stderr"), b"\xfe\0ERR")
        self.assertEqual([item["params"]["seq"] for item in self.notifications], list(range(1, len(self.notifications) + 1)))
        self.assertEqual(self.notifications[-1]["method"], "process/closed")

    async def test_02_real_stdin_concurrent_duplicate_write_ids(self):
        await self.start(args=("echo", "5"), pipeStdin=True)
        request = {"processId": "process", "writeId": "exactly-once", "chunk": base64.b64encode(b"\0\xffABC").decode()}
        results = await asyncio.gather(*(self.call("process/write", request) for _ in range(8)))
        self.assertEqual(results, [{"status": "accepted"}] * 8)
        response = await self.completed()
        self.assertEqual(response["exitCode"], 0)
        self.assertEqual(self.output(response), b"\0\xffABC")
        self.assertEqual(await self.call("process/write", request), {"status": "accepted"})

    async def test_03_real_eof_and_write_statuses(self):
        self.assertEqual(await self.call("process/write", {"processId": "unknown", "writeId": "a", "chunk": ""}), {"status": "unknownProcess"})
        with self.assertRaises(RpcError):
            await self.call("process/write", {"processId": "unknown", "writeId": "", "chunk": ""})
        await self.start(args=("eof",))
        self.assertEqual(await self.call("process/write", {"processId": "process", "writeId": "b", "chunk": ""}), {"status": "stdinClosed"})
        self.assertEqual(self.output(await self.completed()), b"EOF")

    async def test_04_real_interrupt_differs_from_termination(self):
        await self.start("interrupt", ("interrupt",))
        await self.until_output("interrupt", b"READY")
        self.assertEqual(await self.call("process/signal", {"processId": "interrupt", "signal": "interrupt"}), {})
        result = await self.completed("interrupt")
        self.assertEqual(result["exitCode"], 42)
        self.assertIn(b"INTERRUPTED", self.output(result))
        await self.start("terminate", ("sleep",))
        self.assertEqual(await self.call("process/terminate", {"processId": "terminate"}), {"running": True})
        result = await self.completed("terminate")
        self.assertEqual(result["exitCode"], 137)
        self.assertEqual(await self.call("process/terminate", {"processId": "terminate"}), {"running": False})

    async def test_05_read_cursor_chunk_boundaries_including_zero(self):
        await self.start()
        full = await self.completed()
        limited = await self.call("process/read", {"processId": "process", "maxBytes": 0})
        self.assertEqual(len(limited["chunks"]), 1)
        first = limited["chunks"][0]
        self.assertEqual(limited["nextSeq"], first["seq"] + 1)
        rest = await self.call("process/read", {"processId": "process", "afterSeq": first["seq"]})
        self.assertTrue(all(chunk["seq"] > first["seq"] for chunk in rest["chunks"]))
        self.assertEqual(rest["nextSeq"], full["nextSeq"])

    async def test_06_explicit_environment_scrub_and_independent_arg0(self):
        await self.start(args=("env",), arg0="actual-arg0", env={"EXACT": "é=ok", "node_repl_auth_token": "must-not-inherit",
            "OPENAI_IDENTITY_TOKEN_FILE": "must-not-inherit", "CODEX_EXEC_SERVER_EXIT_ON_STDIN_CLOSE": "1"})
        output = self.output(await self.completed())
        self.assertEqual(output, "ARG0=actual-arg0\nEXACT=é=ok\n".encode())

    async def test_07_same_inode_policy_sequence_and_actual_denial(self):
        inode = (self.root / "value").stat().st_ino
        for index, access in enumerate(("write", "read", "deny", "write")):
            expected = errno.EACCES if access != "write" else 0
            await self.start(str(index), ("open", "0", "value", str(os.O_RDWR | os.O_TRUNC), str(expected), "real-change"), sandbox=context(access))
            result = await self.completed(str(index))
            self.assertEqual(result["exitCode"], 0)
            self.assertEqual((self.root / "value").stat().st_ino, inode)
            self.assertEqual((self.root / "value").read_bytes(), b"real-change")
        self.assertEqual((self.root / "private/secret").read_bytes(), b"private-intact")

    async def test_08_duplicate_and_cross_session_ids(self):
        await self.start("same", ("sleep",))
        with self.assertRaises(RpcError):
            await self.start("same", ("sleep",))
        self.assertEqual(await self.call("process/terminate", {"processId": "same"}, "other"), {"running": False})
        pending = asyncio.create_task(self.start("same", ("eof",), session="other"))
        await asyncio.sleep(0)
        self.assertFalse(pending.done())
        self.assertEqual(await self.call("process/write", {"processId": "same", "writeId": "x", "chunk": ""}, "other"), {"status": "starting"})
        await self.call("process/terminate", {"processId": "same"})
        await self.completed("same")
        await pending
        self.assertEqual(self.output(await self.completed("same", "other")), b"EOF")

    async def test_09_startup_cancellation_while_waiting_for_workspace(self):
        await self.start("holding", ("sleep",))
        starting = asyncio.create_task(self.start("waiting", ("eof",)))
        await asyncio.sleep(0)
        self.assertEqual(await self.call("process/terminate", {"processId": "waiting"}), {"running": True})
        with self.assertRaises(RpcError):
            await asyncio.wait_for(starting, 1)
        self.assertNotIn(("session-one", "waiting"), self.backend.processes)

    async def test_10_real_descendant_reaping_after_leader_exit(self):
        await self.start(args=("fork-exit",))
        response = await self.completed()
        self.assertEqual(response["exitCode"], 19)
        child = int(self.output(response).split(b"CHILD:")[1].splitlines()[0])
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)

    async def test_11_unsupported_profile_fails_before_exec(self):
        for extra in ({"tty": True}, {"envPolicy": {"inherit": "none"}}, {"managedNetwork": {}}, {"sandbox": None}):
            with self.assertRaises(RpcError) as refused:
                await self.start(**extra)
            if "envPolicy" in extra:
                self.assertIn("complete supported wire fields", str(refused.exception))
        self.assertFalse(self.backend.processes)
        self.assertFalse(self.notifications)

    async def test_12_stdin_backpressure_keeps_terminate_responsive(self):
        await self.start(args=("sleep",), pipeStdin=True)
        data = base64.b64encode(b"x" * (1024 * 1024)).decode()
        self.assertEqual(await self.call("process/write", {"processId": "process", "writeId": "filled", "chunk": data}), {"status": "accepted"})
        blocked = asyncio.create_task(self.call("process/write", {"processId": "process", "writeId": "waiting", "chunk": "YQ=="}))
        await asyncio.sleep(0.05)
        self.assertFalse(blocked.done())
        await asyncio.wait_for(self.call("process/terminate", {"processId": "process"}), 0.5)
        with self.assertRaises(RpcError):
            await asyncio.wait_for(blocked, 1)
        self.assertEqual((await self.completed())["exitCode"], 137)

    async def test_13_real_output_retention_and_limit(self):
        await self.start(args=("output",))
        response = await self.completed()
        self.assertEqual(response["exitCode"], 0)
        self.assertLessEqual(len(self.output(response)), 1024 * 1024)
        self.assertTrue(all(value == 0xa5 for value in self.output(response)))
        self.assertGreater(response["chunks"][0]["seq"], 1)

    async def test_14_real_exec_permission_failure_has_no_start_success(self):
        bad = self.work / "non-executable"
        bad.write_bytes(FIXTURE.read_bytes()); bad.chmod(0o600)
        self.backend = NativeProcessesBackend(RUNNER, self.root, executables={"native-fixture": bad},
            limits=NativeProcessLimits(wall_ms=3000, address_space_bytes=ADDRESS_SPACE))
        with self.assertRaises(RpcError):
            await self.start()
        self.assertFalse(self.notifications)
        self.assertFalse(self.backend.processes)
        self.assertFalse(self.backend.quarantined)
        self.assertFalse(self.backend.failed[-1].native_result["started"])
        self.assertTrue(self.backend.failed[-1].native_result["cleanupComplete"])

    async def test_15_real_timeout_and_output_exhaustion_are_failures(self):
        self.backend.limits = NativeProcessLimits(wall_ms=100, address_space_bytes=ADDRESS_SPACE)
        await self.start("timeout", ("sleep",))
        response = await self.completed("timeout")
        self.assertEqual(response["exitCode"], 137)
        self.assertIn("timeout", response["failure"])
        self.backend.limits = NativeProcessLimits(wall_ms=3000, output_bytes=32768, address_space_bytes=ADDRESS_SPACE)
        await self.start("limited", ("output",))
        response = await self.completed("limited")
        self.assertNotEqual(response["exitCode"], 0)
        self.assertIn("output_limit", response["failure"])
        self.assertEqual(len(self.output(response)), 32768)

    async def test_16_cancelled_backpressured_write_retry_does_not_duplicate(self):
        await self.start(args=("sleep",), pipeStdin=True)
        payload = base64.b64encode(b"a" * (1024 * 1024)).decode()
        await self.call("process/write", {"processId": "process", "writeId": "one", "chunk": payload})
        pending = asyncio.create_task(self.call("process/write", {"processId": "process", "writeId": "not-yet", "chunk": "YQ=="}))
        await asyncio.sleep(0.03)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        record = self.backend.processes[("session-one", "process")]
        self.assertNotIn("not-yet", record.accepted_ids)
        self.assertEqual(await self.call("process/write", {"processId": "process", "writeId": "one", "chunk": payload}), {"status": "accepted"})
        await self.call("process/terminate", {"processId": "process"})
        await self.completed()

    async def test_17_composed_file_backend_lease_is_kept_across_process(self):
        from tools.executor.native_files import NativeFilesBackend
        files = NativeFilesBackend(RUNNER, self.root)
        try:
            self.backend = NativeProcessesBackend(RUNNER, self.root, executables={"native-fixture": FIXTURE},
                limits=NativeProcessLimits(wall_ms=3000, address_space_bytes=ADDRESS_SPACE), files_backend=files)
            await self.start(args=("sleep",))
            self.assertTrue(files.lock.locked())
            self.assertFalse(self.backend.quarantine_event.is_set())
            waiting = asyncio.create_task(files.lock.acquire())
            await asyncio.sleep(0)
            self.assertFalse(waiting.done())
            await self.call("process/terminate", {"processId": "process"})
            await self.completed()
            await asyncio.wait_for(waiting, 1)
            files.lock.release()
            self.assertFalse(files.closed)
            self.assertEqual(os.fstat(files.root).st_ino, self.root.stat().st_ino)
        finally:
            await self.backend.close("session-one")
            os.close(files.root); files.closed = True

    async def test_18_supervisor_sigkill_has_no_invented_exit_or_cleanup(self):
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        record = None
        try:
            await self.start(args=("sleep",))
            record = self.backend.processes[("session-one", "process")]
            target = record.native_started["pid"]
            record.process.kill()  # Actual native supervisor SIGKILL.
            await asyncio.wait_for(asyncio.shield(record.finished), 3)
            result = await self.call("process/read", {"processId": "process"})
            self.assertFalse(result["exited"])
            self.assertFalse(result["closed"])
            self.assertIsNone(result["exitCode"])
            self.assertIn("unknown", result["failure"])
            self.assertTrue(self.backend.quarantined)
            self.assertFalse(any(item["method"] in {"process/exited", "process/closed"} for item in self.notifications))
            with self.assertRaises(RpcError):
                await self.start("refused-after-loss", ("eof",))
            with self.assertRaises(RpcError):
                await self.backend.close("session-one")
            # Test-only independent observer adopts/reaps the actual orphan.
            # This does not turn the production backend's unknown result into PASS.
            for _ in range(100):
                pid, status = os.waitpid(target, os.WNOHANG)
                if pid == target:
                    self.assertTrue(os.WIFSIGNALED(status))
                    self.assertEqual(os.WTERMSIG(status), 9)
                    break
                await asyncio.sleep(0.01)
            else:
                self.fail("Independent fixture did not reap the actual orphan after supervisor loss")
            record.policy.close()
            self.backend.lease.release()  # Only after independently verified reaping above.
        finally:
            self.assertEqual(libc.prctl(36, previous.value, 0, 0, 0), 0)

    async def test_20_real_libc_memfd_and_seals_without_python_memfd_api(self):
        import fcntl
        from tools.executor.native_processes import NATIVE_FD_ABI, _native_fcntl, _sealed_environment
        payload = b"EXPLICIT=value\0"
        fd = _sealed_environment(payload)
        try:
            info = os.fstat(fd)
            self.assertEqual(info.st_uid, os.getuid())
            self.assertEqual(info.st_nlink, 0)
            self.assertEqual(info.st_size, len(payload))
            self.assertFalse(os.get_inheritable(fd))
            self.assertEqual(os.read(fd, len(payload) + 1), payload)
            seals = _native_fcntl(fd, NATIVE_FD_ABI["F_GET_SEALS"])
            required_seals = sum(value for key, value in NATIVE_FD_ABI.items() if key.startswith("F_SEAL_"))
            self.assertEqual(seals & required_seals, required_seals)
            for operation in (lambda: os.pwrite(fd, b"X", 0), lambda: os.ftruncate(fd, 0),
                              lambda: os.ftruncate(fd, len(payload) + 1),
                              lambda: _native_fcntl(fd, NATIVE_FD_ABI["F_ADD_SEALS"], 0)):
                with self.assertRaises(OSError) as failure:
                    operation()
                self.assertEqual(failure.exception.errno, errno.EPERM)
            OBSERVATIONS.append({"test": self.id(), "memfdRoute": "libc.memfd_create",
                "sealRoute": "libc.fcntl", "actualSeals": seals, "actualSize": info.st_size,
                "pythonMemfdExposed": hasattr(os, "memfd_create"),
                "pythonConstants": {key: getattr(os if key.startswith("MFD_") else fcntl, key, None)
                                    for key in NATIVE_FD_ABI}, "verifiedNativeAbi": dict(NATIVE_FD_ABI),
                "writeShrinkGrowResealDenied": True})
        finally:
            os.close(fd)

    async def test_21_pinned_supervisor_signal_preserves_asyncio_wait_status(self):
        await self.start(args=("sleep",))
        record = self.backend.processes[("session-one", "process")]
        self.assertEqual(record.supervisor_identity["pid"], record.process.pid)
        self.assertTrue(record.supervisor_identity["acknowledgedBeforeWorker"])
        self.assertFalse(os.get_inheritable(record.supervisor_fd))
        with self.assertNoLogs("asyncio", level="WARNING"):
            self.assertTrue(self.backend._signal_supervisor(record, 15))
            response = await self.completed()
        self.assertEqual(response["exitCode"], 137)
        self.assertEqual(record.process.returncode, 1)
        self.assertEqual(record.supervisor_fd, -1)
        self.assertIn({"signal": 15, "delivered": True, "route": "libc.pidfd_send_signal"}, record.supervisor_signals)

    async def test_22_native_identity_gate_blocks_fork_until_ack_and_pidfd_survives_reap(self):
        import socket
        from tools.executor.native_process_policy import NativeProcessPolicy
        from tools.executor.native_processes import _receive_supervisor, _receive, _packet, _sealed_environment, _signal_pidfd
        policy = NativeProcessPolicy(RUNNER, self.root, context())
        control, native_control = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        command, native_command = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        control.setblocking(False); command.setblocking(False)
        read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
        env_fd = _sealed_environment(b"")
        pidfd = -1
        process = None
        try:
            arguments = [str(RUNNER), str(policy.root), str(native_control.fileno()), str(FIXTURE),
                "3000", str(ADDRESS_SPACE), "67108864", "128", "--process-v2", str(read_fd),
                str(native_command.fileno()), str(env_fd), "--", "native-fixture", "sleep"]
            process = await asyncio.create_subprocess_exec(*arguments, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env={}, close_fds=True,
                pass_fds=(policy.root, native_control.fileno(), native_command.fileno(), read_fd, env_fd))
            native_control.close(); native_command.close()
            pidfd, identity = await asyncio.wait_for(_receive_supervisor(control, process.pid), 2)
            child_snapshots = [process_children_snapshot(process.pid)]
            self.assertEqual(child_snapshots[-1]['children'], [])
            await asyncio.sleep(0.05)
            child_snapshots.append(process_children_snapshot(process.pid))
            self.assertEqual(child_snapshots[-1]['children'], [])
            self.assertIsNone(process.returncode)
            await _packet(control, b"P")
            started = await asyncio.wait_for(_receive(control), 2)
            self.assertEqual(started["type"], "started")
            self.assertEqual(started["profile"], "managed-process-v2")
            child_snapshots.append(process_children_snapshot(process.pid))
            self.assertEqual(child_snapshots[-1]['children'], [started["pid"]])
            with self.assertNoLogs("asyncio", level="WARNING"):
                self.assertTrue(_signal_pidfd(pidfd, 15))
                events = []
                while (event := await asyncio.wait_for(_receive(control), 3)) is not None:
                    events.append(event)
                stdout, stderr = await asyncio.wait_for(process.communicate(), 3)
            self.assertEqual(stdout, b""); self.assertEqual(stderr, b"")
            self.assertEqual(process.returncode, 1)
            self.assertEqual(events[-1]["type"], "result")
            self.assertTrue(events[-1]["cleanupComplete"])
            self.assertEqual(events[-1]["signal"], 9)
            # This still-open pidfd retains the original dead supervisor's
            # identity; it cannot signal another process with a recycled PID.
            self.assertFalse(_signal_pidfd(pidfd, 0))
            self.assertFalse(_signal_pidfd(pidfd, 15))
            OBSERVATIONS.append({"test": self.id(), "supervisorIdentity": identity,
                "noWorkerBeforeAcknowledgement": True, "nativeStarted": started, "nativeEvents": events,
                "supervisorReturncode": process.returncode, "postReapSignalReturnedESRCH": True,
                "waitOwner": "asyncio", "signalRoute": "libc.pidfd_send_signal",
                "childSnapshots": child_snapshots})
        finally:
            if process is not None and process.returncode is None and pidfd >= 0:
                _signal_pidfd(pidfd, 9)
                await asyncio.wait_for(process.communicate(), 3)
            if pidfd >= 0:
                os.close(pidfd)
            for endpoint in (control, native_control, command, native_command):
                endpoint.close()
            for descriptor in (read_fd, write_fd, env_fd):
                os.close(descriptor)
            policy.close()

    async def test_23_real_pidfd_transfer_refuses_wrong_or_extra_descriptors_without_leaks(self):
        import array
        import ctypes
        import socket
        from tools.executor.native_processes import _receive_supervisor
        libc = ctypes.CDLL(None, use_errno=True)
        libc.pidfd_open.argtypes = [ctypes.c_int, ctypes.c_uint]
        libc.pidfd_open.restype = ctypes.c_int
        identity = libc.pidfd_open(os.getpid(), 0)
        self.assertGreaterEqual(identity, 0)
        read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
        try:
            payload = encode_message({"type": "supervisor", "pid": os.getpid(), "profile": "managed-process-v2"})
            cases = [([identity], os.getpid() + 1), ([read_fd], os.getpid()),
                ([identity, identity], os.getpid()), ([identity] * 8, os.getpid()), ([], os.getpid())]
            for descriptors, expected_pid in cases:
                receiver, sender = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                receiver.setblocking(False)
                try:
                    before = len(os.listdir("/proc/self/fd"))
                    ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", descriptors))] if descriptors else []
                    self.assertEqual(sender.sendmsg([payload], ancillary), len(payload))
                    with self.assertRaises(RpcError):
                        await _receive_supervisor(receiver, expected_pid)
                    self.assertEqual(len(os.listdir("/proc/self/fd")), before)
                finally:
                    receiver.close(); sender.close()
            OBSERVATIONS.append({"test": self.id(), "realScmRightsRefusals": len(cases),
                "wrongPidPipeExtraTruncatedMissingRejected": True, "actualDescriptorCountsUnchanged": True})
        finally:
            os.close(identity); os.close(read_fd); os.close(write_fd)

    async def test_19_shared_filesystem_quarantine_blocks_actual_write_after_supervisor_loss(self):
        import ctypes
        from tools.executor.native_files import NativeFilesBackend
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        files = NativeFilesBackend(FILES_HELPER, self.root)
        blocked = None
        try:
            write = BackendCall("session-one", 1001, "fs/writeFile", encode_message({"path": "file:///workspace/value",
                "dataBase64": base64.b64encode(b"before-loss").decode(), "sandbox": context()}))
            await files.handle(write, self.notify)
            self.assertEqual((self.root / "value").read_bytes(), b"before-loss")
            self.backend = NativeProcessesBackend(RUNNER, self.root, executables={"native-fixture": FIXTURE},
                limits=NativeProcessLimits(wall_ms=3000, address_space_bytes=ADDRESS_SPACE), files_backend=files)
            await self.start(args=("sleep",))
            record = self.backend.processes[("session-one", "process")]
            target = record.native_started["pid"]
            record.process.kill()
            await asyncio.wait_for(asyncio.shield(record.finished), 3)
            self.assertTrue(files.lock.locked())
            self.assertTrue(self.backend.quarantine_event.is_set())
            attempted = BackendCall("session-one", 1002, "fs/writeFile", encode_message({"path": "file:///workspace/value",
                "dataBase64": base64.b64encode(b"must-not-run").decode(), "sandbox": context()}))
            blocked = asyncio.create_task(files.handle(attempted, self.notify))
            await asyncio.sleep(0.05)
            self.assertFalse(blocked.done())
            self.assertEqual((self.root / "value").read_bytes(), b"before-loss")
            self.assertIn("unknown", (await self.call("process/read", {"processId": "process"}))["failure"])
            self.assertEqual(await self.call("process/terminate", {"processId": "process"}), {"running": False})
            blocked.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await blocked
            with self.assertRaises(RpcError):
                await self.backend.close("session-one")
            for _ in range(100):
                pid, status = os.waitpid(target, os.WNOHANG)
                if pid == target:
                    self.assertTrue(os.WIFSIGNALED(status)); self.assertEqual(os.WTERMSIG(status), 9)
                    break
                await asyncio.sleep(0.01)
            else:
                self.fail("Independent test observer failed to reap the actual orphan")
            files.lock.release()  # No production recovery claim; actual orphan was just reaped.
            self.assertEqual((self.root / "value").read_bytes(), b"before-loss")
        finally:
            if blocked is not None and not blocked.done():
                blocked.cancel(); await asyncio.gather(blocked, return_exceptions=True)
            os.close(files.root); files.closed = True
            self.assertEqual(libc.prctl(36, previous.value, 0, 0, 0), 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--files-helper", type=Path, required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--address-space-bytes", type=int, default=256 * 1024 * 1024)
    args, remaining = parser.parse_known_args()
    RUNNER, FIXTURE, PARENT, EVIDENCE = args.runner, args.fixture, args.parent, args.evidence
    FILES_HELPER = args.files_helper
    ADDRESS_SPACE = args.address_space_bytes
    program = unittest.main(argv=[sys.argv[0], *remaining], exit=False, verbosity=2)
    if EVIDENCE:
        EVIDENCE.write_text(json.dumps({"schema": "foldgpt.native-process-lifecycle.v1", "uid": os.getuid(),
            "successful": program.result.wasSuccessful(), "observations": OBSERVATIONS}, indent=2) + "\n")
    sys.exit(0 if program.result.wasSuccessful() else 1)
