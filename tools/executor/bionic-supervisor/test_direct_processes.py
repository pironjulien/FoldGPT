"""Real Linux tests of the direct model process adapter and its native owner.

Run with a frozen native-helper build and evidence directories; never skips missing helpers.
No Android device, upstream engine, fabricated native result or mock process.
"""
import asyncio
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import shlex
import signal
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
module = importlib.import_module("tools.executor.bionic-supervisor.direct_processes")
factory = importlib.import_module("tools.executor.bionic-supervisor.factory").factory
from tools.executor.exec_server import BackendCall, RpcError, encode_message

BUILD = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
EVIDENCE = Path(sys.argv.pop(1)).resolve() if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
OBSERVATIONS = []


class DirectProcessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertEqual(sys.platform, "linux", "This suite requires the real Linux PC kernel")
        self.assertNotEqual(os.getuid(), 0)
        self.assertIsNotNone(BUILD, "Pass the compiled native-helper build directory")
        self.base = Path(tempfile.mkdtemp(prefix="foldgpt-direct-process-", dir="/var/tmp"))
        self.workspace = self.base / "workspace"
        self.workspace.mkdir(mode=0o700)
        self.python = str(Path(sys.executable).resolve())
        self.bash = str(Path("/usr/bin/bash").resolve())
        self.owner = factory({"helper": str(BUILD / "native-files"),
            "handleHelper": str(BUILD / "native-file-handle"), "processRunner": str(BUILD / "runner"),
            "workspace": str(self.workspace), "executables": {"bash": self.bash, "python": self.python},
            "runtime": [{"path": "/usr", "execute": True}], "limits": {"wall_ms": 3000}})
        self.backend = module.DirectProcesses(BUILD / "direct-runner", self.workspace,
            files_backend=self.owner.files, quarantine_owner=self.owner.processes,
            executables={"bash": self.bash, "python": self.python},
            parent_environment={"PATH": "/usr/bin:/bin", "HOME": str(self.workspace),
                "USER": "native-test", "VISIBLE": "inherited", "PRIVATE_TOKEN": "filtered"},
            limits=module.DirectLimits(wall_ms=15000))
        self.events = []
        self.sequence = 0
        self.expected_quarantine = False

    async def asyncTearDown(self):
        self.assertEqual(self.backend.quarantined, self.expected_quarantine,
                         "Unexpected native descendant ownership state")
        if self.expected_quarantine:
            with self.assertRaises(RpcError):
                await self.backend.close("test")
            with self.assertRaises(RpcError):
                await self.owner.close("test")
        else:
            await self.backend.close("test")
            await self.owner.close("test")
        await self.backend.close("other")
        OBSERVATIONS.append({"test": self.id(), "workspace": str(self.workspace),
                             "events": len(self.events)})

    async def notify(self, method, params):
        self.events.append({"method": method, "params": params})

    async def call(self, method, params, *, session="test", notify=None):
        self.sequence += 1
        return await self.backend.handle(BackendCall(session, self.sequence, method,
            encode_message(params)), self.notify if notify is None else notify)

    def params(self, argv, key="process", **extra):
        return {"processId": key, "argv": argv, "cwd": self.workspace.as_uri(), "env": {},
                "tty": False, **extra}

    async def start(self, argv, key="process", *, session="test", notify=None, **extra):
        result = await self.call("process/start", self.params(argv, key, **extra), session=session, notify=notify)
        self.assertEqual(result, {"processId": key, "sandboxType": "none"})
        record = self.backend.processes[(session, key)]
        self.assertEqual(record.mode, "ordinary-uid")
        self.assertIsNone(record.policy)
        return record

    async def complete(self, record):
        await asyncio.wait_for(asyncio.shield(record.finished), 25)
        await asyncio.wait_for(asyncio.shield(record.notifier), 5)
        response = await self.call("process/read", {"processId": record.key}, session=record.session)
        self.assertTrue(response["closed"], response)
        self.assertTrue(response["exited"], response)
        self.assertTrue(record.native_result["cleanupComplete"])
        self.assertEqual(record.process.returncode, 0)
        self.assertTrue(all(record.pipe_eof.values()))
        self.assertFalse(self.backend.lease.locked())
        OBSERVATIONS.append({"test": self.id(), "result": record.native_result,
            "ownerReturncode": record.process.returncode, "pipeEof": record.pipe_eof,
            "readExit": response["exitCode"], "failure": response["failure"]})
        return response

    @staticmethod
    def output(response, name="stdout"):
        return b"".join(base64.b64decode(chunk["chunk"]) for chunk in response["chunks"] if chunk["stream"] == name)

    async def until(self, record, marker):
        async def observe():
            while True:
                response = await self.call("process/read", {"processId": record.key, "waitMs": 100}, session=record.session)
                if marker in self.output(response):
                    return response
                if response["closed"]:
                    self.fail("Command closed before readiness: " + repr(response))
        return await asyncio.wait_for(observe(), 5)

    async def test_01_bash_python_real_project_test_build_run(self):
        program = '''import os, pathlib, subprocess, sys, zipapp
p=pathlib.Path('project'); p.mkdir()
(p/'calculator.py').write_text('def answer():\\n    return 41\\n')
source=p/'calculator.py'; source.write_text(source.read_text().replace('return 41','return 42'))
(p/'test_calculator.py').write_text('import unittest\\nfrom calculator import answer\\nclass T(unittest.TestCase):\\n    def test_answer(self): self.assertEqual(answer(),42)\\n    def test_int(self): self.assertIsInstance(answer(),int)\\n    def test_positive(self): self.assertGreater(answer(),0)\\n')
(p/'__main__.py').write_text('from calculator import answer\\nprint(answer())\\n')
subprocess.run([sys.executable,'-I','-B','-m','unittest','discover','-s',str(p),'-v'],check=True)
zipapp.create_archive(p,'calculator.pyz',compressed=True)
subprocess.run([sys.executable,'-B','calculator.pyz'],check=True)
'''
        command = shlex.quote(self.python) + " -I -B -c " + shlex.quote(program)
        record = await self.start(["bash", "--noprofile", "--norc", "-c", command])
        response = await self.complete(record)
        self.assertEqual(response["exitCode"], 0)
        self.assertIsNone(response["failure"])
        self.assertEqual(self.output(response), b"42\n")
        self.assertIn(b"Ran 3 tests", self.output(response, "stderr"))
        self.assertTrue((self.workspace / "calculator.pyz").is_file())

    async def test_02_binary_stdin_idempotence_and_default_eof(self):
        record = await self.start(["python", "-I", "-B", "-c", "import os;print(repr(os.read(0,1)))"])
        self.assertEqual(self.output(await self.complete(record)), b"b''\n")
        record = await self.start(["python", "-I", "-B", "-c", "import os;os.write(1,os.read(0,5))"], key="binary", pipeStdin=True)
        request = {"processId": record.key, "writeId": "same", "chunk": base64.b64encode(b"\x00\xffABC").decode()}
        self.assertEqual(await asyncio.gather(*(self.call("process/write", request) for _ in range(4))),
                         [{"status": "accepted"}] * 4)
        self.assertEqual(self.output(await self.complete(record)), b"\x00\xffABC")

    async def test_03_real_cwd_alias_and_full_uid_filesystem(self):
        outside = self.base / "ordinary-directory"
        outside.mkdir()
        (self.workspace / "cwd-alias").symlink_to(outside, target_is_directory=True)
        program = "import os;open('before','w').write('42');os.rename('before','after');os.chmod('after',0o600);os.symlink('after','alias');assert open('alias').read()=='42';os.unlink('alias');print(os.getcwd())"
        record = await self.start(["python", "-I", "-B", "-c", program], cwd=(self.workspace / "cwd-alias").as_uri())
        response = await self.complete(record)
        self.assertEqual(self.output(response), (str(outside) + "\n").encode())
        self.assertEqual((outside / "after").read_text(), "42")
        self.assertFalse((outside / "before").exists())

    async def test_04_environment_policy_and_argv0(self):
        policy = {"inherit": "all", "ignoreDefaultExcludes": False, "exclude": ["USER"],
                  "set": {"POLICY": "resolved"}, "includeOnly": []}
        script = 'printf "%s\\n%s\\n%s\\n%s\\n%s\\n" "$0" "$VISIBLE" "$POLICY" "$PRIVATE_TOKEN" "$USER"'
        record = await self.start(["bash", "--noprofile", "--norc", "-c", script],
                                  arg0="direct-argv0", env={"VISIBLE": "override"}, envPolicy=policy)
        response = await self.complete(record)
        self.assertEqual(self.output(response), b"direct-argv0\noverride\nresolved\n\n\n")

    async def test_05_actual_nonroot_identity_capabilities_and_network(self):
        program = '''import json,os,socket
caps={k:v.strip() for k,v in (line.split(':',1) for line in open('/proc/self/status') if line.startswith(('CapEff:','CapPrm:','CapInh:','CapAmb:')))}
assert len(set(os.getresuid()))==1 and os.geteuid()!=0
assert all(int(value,16)==0 for value in caps.values())
tcp=socket.socket();tcp.bind(('127.0.0.1',0));tcp.listen(1)
client=socket.socket();client.connect(tcp.getsockname());peer,_=tcp.accept();client.sendall(b'42');assert peer.recv(2)==b'42'
udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind(('127.0.0.1',0));udp.sendto(b'udp',udp.getsockname());assert udp.recvfrom(3)[0]==b'udp'
assert socket.getaddrinfo('localhost',80)
print(json.dumps({'uid':os.geteuid(),'caps':caps,'tcp':True,'udp':True,'resolver':True}))
'''
        response = await self.complete(await self.start(["python", "-I", "-B", "-c", program]))
        report = json.loads(self.output(response))
        self.assertEqual(report["uid"], os.getuid())
        self.assertTrue(report["tcp"] and report["udp"] and report["resolver"])

    async def test_06_fast_exit_is_observed_once(self):
        for index in range(8):
            record = await self.start(["bash", "--noprofile", "--norc", "-c", "exit 23"], key=f"fast-{index}")
            self.assertEqual((await self.complete(record))["exitCode"], 23)
            events = [event for event in self.events if event["params"]["processId"] == record.key]
            self.assertEqual(sum(event["method"] == "process/exited" for event in events), 1)
            self.assertEqual(events[-1]["method"], "process/closed")

    async def test_07_interrupt_and_cancel_real_wait_status(self):
        program = "import signal,time;signal.signal(signal.SIGINT,lambda *a:exit(42));print('READY',flush=True);time.sleep(100)"
        record = await self.start(["python", "-I", "-B", "-c", program])
        await self.until(record, b"READY")
        await self.call("process/signal", {"processId": record.key, "signal": "interrupt"})
        self.assertEqual((await self.complete(record))["exitCode"], 42)
        record = await self.start(["python", "-I", "-B", "-c", "import time;print('READY',flush=True);time.sleep(100)"], key="cancel")
        await self.until(record, b"READY")
        self.assertEqual(await self.call("process/terminate", {"processId": record.key}), {"running": True})
        self.assertEqual((await self.complete(record))["exitCode"], 137)
        self.assertEqual(record.native_result["outcome"], "cancelled")

    async def test_08_double_fork_setsid_descendants_are_reaped(self):
        program = '''import os,time
child=os.fork()
if child==0:
 os.setsid()
 grandchild=os.fork()
 if grandchild==0:
  open('grandchild','w').write(str(os.getpid()))
  while True: time.sleep(1)
 os._exit(0)
os.waitpid(child,0)
while not os.path.exists('grandchild'): time.sleep(.01)
print('READY',flush=True)
'''
        record = await self.start(["python", "-I", "-B", "-c", program])
        response = await self.complete(record)
        self.assertEqual(response["exitCode"], 0)
        pid = int((self.workspace / "grandchild").read_text())
        self.assertFalse(Path(f"/proc/{pid}").exists())
        self.assertGreaterEqual(record.native_result["reaped"], 2)

    async def test_09_cancellation_before_lease_never_spawns(self):
        await self.backend.lease.acquire()
        starting = asyncio.create_task(self.call("process/start", self.params(["bash", "-c", "touch should-not-exist"])))
        try:
            while ("test", "process") not in self.backend.processes:
                await asyncio.sleep(0)
            record = self.backend.processes[("test", "process")]
            starting.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await starting
            self.assertIsNone(record.process)
            self.assertTrue(record.closed)
            self.assertTrue(self.backend.lease.locked())
            self.assertFalse((self.workspace / "should-not-exist").exists())
        finally:
            self.backend.lease.release()

    async def test_10_context_and_unsupported_features_never_spawn(self):
        cases = [{"sandbox": {}}, {"sandbox": {"permissions": {"type": "disabled"}}},
                 {"sandbox": {"permissions": {"type": "managed"}}}, {"tty": True},
                 {"shellSnapshot": {}}, {"managedNetwork": {}}, {"networkProxy": {}},
                 {"enforceManagedNetwork": True}, {"cwd": "file://foreign.invalid/project"}]
        for extra in cases:
            with self.subTest(extra=extra), self.assertRaises(RpcError):
                await self.call("process/start", self.params(["bash", "-c", "touch should-not-exist"], **extra))
        self.assertEqual(self.backend.processes, {})
        self.assertFalse((self.workspace / "should-not-exist").exists())
        response = await self.complete(await self.start(["bash", "-c", "printf explicit-null"], sandbox=None))
        self.assertEqual(self.output(response), b"explicit-null")

    async def test_11_slow_notifications_apply_real_backpressure(self):
        async def slow(method, params):
            await asyncio.sleep(.002)
            await self.notify(method, params)
        count = 16 * 1024 * 1024
        program = f"import os;remaining={count};block=b'x'*65536\nwhile remaining:\n n=os.write(1,block[:remaining]);remaining-=n"
        record = await self.start(["python", "-I", "-B", "-c", program], notify=slow)
        response = await self.complete(record)
        self.assertEqual(response["exitCode"], 0)
        self.assertIsNone(response["failure"])
        received = hashlib.sha256()
        length = 0
        sequences = []
        for event in self.events:
            sequences.append(event["params"]["seq"])
            if event["method"] == "process/output":
                data = base64.b64decode(event["params"]["chunk"])
                received.update(data)
                length += len(data)
        self.assertEqual(length, count)
        self.assertEqual(received.digest(), hashlib.sha256(b"x" * count).digest())
        self.assertEqual(sequences, list(range(1, len(sequences) + 1)))

    async def test_12_notify_failure_cleans_actual_process(self):
        async def broken(method, params):
            raise ConnectionError("Intentional failed transport")
        record = await self.start(["python", "-I", "-B", "-c", "import time;print('READY',flush=True);time.sleep(100)"], notify=broken)
        response = await self.complete(record)
        self.assertIn("notification transport failed", response["failure"])
        self.assertEqual(record.native_result["outcome"], "cancelled")

    async def test_13_session_handle_cannot_control_another_session(self):
        record = await self.start(["python", "-I", "-B", "-c", "import time;print('READY',flush=True);time.sleep(100)"])
        await self.until(record, b"READY")
        self.assertEqual(await self.call("process/terminate", {"processId": record.key}, session="other"), {"running": False})
        with self.assertRaises(RpcError):
            await self.call("process/read", {"processId": record.key}, session="other")
        await self.call("process/terminate", {"processId": record.key})
        await self.complete(record)

    async def test_14_real_timeout_closes_and_releases_lease(self):
        self.backend.limits = module.DirectLimits(wall_ms=200)
        record = await self.start(["python", "-I", "-B", "-c", "import time;time.sleep(100)"])
        response = await self.complete(record)
        self.assertEqual(record.native_result["outcome"], "timeout")
        self.assertEqual(response["exitCode"], 137)
        self.assertIn("timeout", response["failure"])

    async def test_15_invalid_cwd_reports_actual_setup_failure(self):
        with self.assertRaises(RpcError):
            await self.start(["bash", "-c", "exit 0"], cwd=(self.workspace / "missing").as_uri())
        record = self.backend.failed[-1]
        self.assertIsNotNone(record.native_result)
        self.assertFalse(record.native_result["started"])
        self.assertTrue(record.native_result["cleanupComplete"])
        self.assertEqual(record.native_result["errno"], 2)
        self.assertEqual(record.process.returncode, 70)
        self.assertTrue(record.closed)
        self.assertFalse(self.backend.lease.locked())

    async def test_16_real_owner_loss_retains_lease_and_propagates_quarantine(self):
        # This one initial child creates no descendants. Its kernel PDEATHSIG
        # ends it when its owner is intentionally lost; that still cannot invent
        # the missing native cleanup certificate or release shared authority.
        record = await self.start(["python", "-I", "-B", "-c",
            "import os,time;print(str(os.getpid())+' READY',flush=True);time.sleep(100)"])
        response = await self.until(record, b"READY")
        child_pid = int(self.output(response).split()[0])
        child_fd = os.pidfd_open(child_pid, 0)
        owner_fd = os.pidfd_open(record.process.pid, 0)
        self.expected_quarantine = True
        try:
            signal.pidfd_send_signal(owner_fd, signal.SIGKILL)
            await asyncio.wait_for(asyncio.shield(record.finished), 15)
            self.assertEqual(record.process.returncode, -signal.SIGKILL)
            self.assertIsNone(record.native_result)
            self.assertFalse(record.closed)
            self.assertTrue(self.backend.quarantined)
            self.assertTrue(self.backend.quarantine_event.is_set())
            self.assertTrue(self.owner.processes.quarantined)
            self.assertTrue(self.owner.processes.quarantine_event.is_set())
            self.assertTrue(self.backend.lease.locked())
            # Polling a pinned pidfd proves the exact child exited, without
            # reaping another owner's child or inferring a workspace certificate.
            import select
            self.assertTrue(select.select([child_fd], [], [], 5)[0])
            with self.assertRaises(RpcError):
                await self.call("process/start", self.params(["bash", "-c", "exit 0"], key="refused"))
            with self.assertRaises(RpcError):
                await self.owner.handle(BackendCall("test", "refused-file", "fs/readFile",
                    encode_message({"path": (self.workspace / "anything").as_uri()})), self.notify)
        finally:
            os.close(owner_fd)
            os.close(child_fd)

    async def test_17_session_disconnect_finishes_real_owner(self):
        record = await self.start(["python", "-I", "-B", "-c", "import time;print('READY',flush=True);time.sleep(100)"])
        await self.until(record, b"READY")
        await asyncio.wait_for(self.backend.close("test"), 15)
        self.assertTrue(record.closed)
        self.assertTrue(record.native_result["cleanupComplete"])
        self.assertEqual(record.process.returncode, 0)
        self.assertTrue(all(record.pipe_eof.values()))
        self.assertFalse(self.backend.lease.locked())
        with self.assertRaises(RpcError):
            await self.call("process/start", self.params(["bash", "-c", "exit 0"], key="refused"))

    async def test_18_cancelled_notification_stops_owner_without_wall_limit(self):
        self.backend.limits = module.DirectLimits()
        cancelled = asyncio.Event()

        async def disconnected(method, params):
            if method == "process/output":
                cancelled.set()
                raise asyncio.CancelledError()

        record = await self.start(["python", "-I", "-B", "-c",
            "import time;print('READY',flush=True);time.sleep(100)"], notify=disconnected)
        await asyncio.wait_for(cancelled.wait(), 5)
        await asyncio.wait_for(asyncio.shield(record.finished), 15)
        await asyncio.gather(record.notifier, return_exceptions=True)
        self.assertTrue(record.notifier.cancelled())
        self.assertTrue(record.closed and record.termination_requested)
        self.assertTrue(record.native_result["cleanupComplete"])
        self.assertEqual(record.native_result["outcome"], "cancelled")
        self.assertEqual(record.process.returncode, 0)
        self.assertTrue(all(record.pipe_eof.values()))
        self.assertFalse(self.backend.lease.locked())


if __name__ == "__main__":
    if BUILD is None or not (BUILD / "direct-runner").is_file() or EVIDENCE is None or not EVIDENCE.is_dir():
        raise SystemExit("Pass a frozen direct-runner build and an existing evidence directory")
    result = unittest.main(verbosity=2, exit=False).result
    output = EVIDENCE / "direct-processes.json"
    sources = {}
    for name in ("direct_processes.py", "direct_wire.py", "test_direct_processes.py"):
        path = Path(__file__).with_name(name)
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    with (BUILD / "direct-runner").open("rb") as stream:
        runner_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    success = result.wasSuccessful() and not result.skipped
    output.write_text(json.dumps({"success": success, "testsRun": result.testsRun,
        "uid": os.getuid(), "androidExecution": False, "observations": OBSERVATIONS,
        "sourceSha256": sources, "runnerSha256": runner_sha,
        "failures": [[test.id(), detail] for test, detail in result.failures],
        "errors": [[test.id(), detail] for test, detail in result.errors],
        "skipped": [[test.id(), reason] for test, reason in result.skipped]}, indent=2) + "\n")
    print(json.dumps({"evidence": str(output), "success": success}), flush=True)
    raise SystemExit(0 if success else 1)
