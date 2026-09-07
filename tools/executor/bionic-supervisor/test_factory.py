"""Actual composed factory and lifecycle tests, with Linux kernel enforcement."""
import asyncio
import base64
import importlib
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
factory = importlib.import_module("tools.executor.bionic-supervisor.factory").factory
kernel = importlib.import_module("tools.executor.bionic-supervisor.test_kernel")
from tools.executor.exec_server import BackendCall, RpcError, encode_message

BUILD = Path(sys.argv.pop(1)) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
OBSERVATIONS = []
SHIM = os.environ.get("FOLDGPT_BIONIC_CWD_SHIM")


class FactoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertNotEqual(os.getuid(), 0)
        self.base = Path(tempfile.mkdtemp(prefix="foldgpt-bionic-factory-", dir="/var/tmp"))
        self.workspace = self.base / "workspace"
        self.workspace.mkdir(mode=0o700)
        (self.workspace / "private").mkdir(mode=0o700)
        (self.workspace / "private/secret").write_text("unchanged private data")
        (self.workspace / ".git").mkdir(mode=0o700)
        self.options = {"helper": str(BUILD / "native-files"), "handleHelper": str(BUILD / "native-file-handle"),
            "processRunner": str(BUILD / "runner"), "workspace": str(self.workspace),
            "executables": {"bash": "/usr/bin/bash"},
            "runtime": [{"path": path, "execute": execute} for path, execute in
                (("/usr", True), ("/lib", True), ("/lib64", True), ("/etc/ld.so.cache", False))],
            "limits": {"wall_ms": 3000, "output_bytes": 32768},
            "parentEnvironment": {"PATH": "/usr/bin:/bin", "HOME": str(self.workspace)}}
        self.backend = factory(self.options)
        self.events, self.sequence = [], 0

    async def asyncTearDown(self):
        if self.backend.processes.quarantined:
            with self.assertRaises(RpcError):
                await self.backend.close("test")
        else:
            await self.backend.close("test")
        OBSERVATIONS.append({"test": self.id(), "workspace": str(self.workspace), "events": self.events})

    async def notify(self, method, params):
        self.events.append({"method": method, "params": params})

    async def call(self, method, params):
        self.sequence += 1
        return await self.backend.handle(BackendCall("test", self.sequence, method, encode_message(params)), self.notify)

    async def start(self, command, key="process", **extra):
        context = kernel.context(self.workspace)
        params = {"processId": key, "argv": ["bash", "--noprofile", "--norc", "-c", command],
            "cwd": context["cwd"], "env": {"PATH": "/usr/bin:/bin", "HOME": str(self.workspace)},
            "tty": False, "sandbox": context, **extra}
        await self.call("process/start", params)
        return self.backend.processes.processes[("test", key)]

    async def complete(self, record):
        await asyncio.wait_for(asyncio.shield(record.finished), 12)
        await asyncio.wait_for(asyncio.shield(record.notifier), 2)
        result = await self.call("process/read", {"processId": record.key})
        self.assertTrue(result["closed"], result)
        self.assertTrue(result["exited"], result)
        self.assertTrue(record.native_result["cleanupComplete"], record.native_result)
        OBSERVATIONS.append({"test": self.id(), "nativeResult": record.native_result,
                             "read": result, "supervisorReturncode": record.process.returncode})
        return result

    @staticmethod
    def output(result, stream="stdout"):
        return b"".join(base64.b64decode(item["chunk"]) for item in result["chunks"] if item["stream"] == stream)

    async def until(self, record, marker):
        for _ in range(30):
            result = await self.call("process/read", {"processId": record.key, "waitMs": 100})
            if marker in self.output(result):
                return result
            if result["closed"]:
                break
        self.fail("Native process never produced readiness: " + repr(result))

    async def test_01_factory_dynamic_python_and_policy(self):
        program = "import os;os.mkdir('new');open('new/answer','w').write('42');print('native Python')"
        record = await self.start("/usr/bin/python3 -I -B -c " + shlex.quote(program) + "; exit 23")
        result = await self.complete(record)
        self.assertEqual(result["exitCode"], 23)
        self.assertIsNone(result["failure"])
        self.assertEqual(self.output(result), b"native Python\n")
        self.assertEqual((self.workspace / "new/answer").read_text(), "42")
        value = await self.call("fs/readFile", {"path": (self.workspace / "new/answer").as_uri(),
                                                "sandbox": kernel.context(self.workspace)})
        self.assertEqual(base64.b64decode(value["dataBase64"]), b"42")

    async def test_02_real_stdin_eof_and_binary_write(self):
        record = await self.start("if read value; then exit 9; else printf EOF; fi")
        self.assertEqual(self.output(await self.complete(record)), b"EOF")
        program = "import os;value=os.read(0,5);os.write(1,value)"
        record = await self.start("/usr/bin/python3 -I -B -c " + shlex.quote(program), key="stdin", pipeStdin=True)
        data = {"processId": "stdin", "writeId": "once", "chunk": base64.b64encode(b"\x00\xffABC").decode()}
        replies = await asyncio.gather(*(self.call("process/write", data) for _ in range(4)))
        self.assertEqual(replies, [{"status": "accepted"}] * 4)
        self.assertEqual(self.output(await self.complete(record)), b"\x00\xffABC")

    async def test_03_interrupt_and_termination(self):
        program = "import signal,time;signal.signal(signal.SIGINT,lambda *a:exit(42));print('READY',flush=True);time.sleep(100)"
        record = await self.start("exec /usr/bin/python3 -I -B -c " + shlex.quote(program))
        await self.until(record, b"READY")
        self.assertEqual(await self.call("process/signal", {"processId": record.key, "signal": "interrupt"}), {})
        self.assertEqual((await self.complete(record))["exitCode"], 42)
        record = await self.start("printf READY; /usr/bin/sleep 100", key="cancel")
        await self.until(record, b"READY")
        self.assertEqual(await self.call("process/terminate", {"processId": record.key}), {"running": True})
        self.assertEqual((await self.complete(record))["exitCode"], 137)
        self.assertEqual(record.native_result["outcome"], "cancelled")

    async def test_04_timeout_and_descendant_cleanup(self):
        record = await self.start("/usr/bin/sleep 100 & printf '%s' $!; wait")
        result = await self.complete(record)
        pid = int(self.output(result))
        self.assertFalse(Path(f"/proc/{pid}").exists())
        self.assertEqual(record.native_result["outcome"], "timeout")
        self.assertEqual(result["exitCode"], 137)

    async def test_05_cwd_env_and_protected_paths(self):
        (self.workspace / "subdir").mkdir(mode=0o700)
        context = kernel.context(self.workspace)
        context["cwd"] = (self.workspace / "subdir").as_uri()
        record = await self.start("printf '%s\n%s\n' \"$PWD\" \"$VALUE\"; printf 7 > value; printf bad > ../private/secret; printf bad > ../.git/config; exit 0",
            cwd=context["cwd"], sandbox=context, env={"VALUE": "native environment"})
        result = await self.complete(record)
        self.assertEqual(self.output(result), (str(self.workspace / "subdir") + "\nnative environment\n").encode())
        self.assertEqual((self.workspace / "private/secret").read_text(), "unchanged private data")
        self.assertFalse((self.workspace / ".git/config").exists())
        self.assertEqual((self.workspace / "subdir/value").read_text(), "7")

    async def test_06_output_cap(self):
        record = await self.start("exec /usr/bin/python3 -I -B -c 'import os;os.write(1,b\"x\"*100000)' ")
        result = await self.complete(record)
        self.assertEqual(record.native_result["outcome"], "output_limit")
        self.assertEqual(len(self.output(result)), 32768)

    async def test_07_lstat_nofollow_and_bad_metadata_flags(self):
        program = """import ctypes,errno,os,stat
assert stat.S_ISLNK(os.lstat('/usr/bin/python3').st_mode)
assert not stat.S_ISLNK(os.stat('/usr/bin/python3').st_mode)
assert os.readlink('/usr/bin/python3').startswith('python3.')
try: os.open('/usr/bin/python3',os.O_RDONLY|os.O_NOFOLLOW)
except OSError as e: assert e.errno==errno.ELOOP,e
else: raise AssertionError('nofollow followed a symlink')
libc=ctypes.CDLL(None,use_errno=True);buffer=ctypes.create_string_buffer(256)
assert libc.fstatat(-100,b'/usr/bin/python3',buffer,0x40000000)==-1
assert ctypes.get_errno()==errno.EINVAL
print('metadata preserved')
"""
        record = await self.start("exec /usr/bin/python3 -I -B -c " + shlex.quote(program))
        result = await self.complete(record)
        self.assertEqual(result["exitCode"], 0, result)
        self.assertEqual(self.output(result), b"metadata preserved\n")

    async def test_08_real_unittest_discovery_directory_streams(self):
        program = """import errno,os,unittest
os.mkdir('project')
open('project/test_value.py','w').write('import unittest\\nclass Value(unittest.TestCase):\\n def test_value(self): self.assertEqual(6*7,42)\\n')
assert os.listdir('project')==['test_value.py']
assert sorted(os.listdir('.'))==['.git','private','project']
for operation in (lambda: os.listdir('private'), lambda: os.stat('private'),
                  lambda: open('private/secret','rb'), lambda: open('private/secret','wb')):
    try: operation()
    except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM),e
    else: raise AssertionError('denied child became accessible')
suite=unittest.defaultTestLoader.discover('project')
result=unittest.TextTestRunner().run(suite)
assert result.wasSuccessful() and result.testsRun==1
print('discovery passed')
"""
        record = await self.start("exec /usr/bin/python3 -I -B -c " + shlex.quote(program))
        result = await self.complete(record)
        self.assertEqual(result["exitCode"], 0, result)
        self.assertEqual(self.output(result), b"discovery passed\n")

    async def test_09_cancellation_channel_eof(self):
        record = await self.start("printf READY; exec /usr/bin/sleep 100")
        await self.until(record, b"READY")
        record.command.close()
        record.command = None
        result = await self.complete(record)
        self.assertEqual(result["exitCode"], 137)
        self.assertEqual(record.native_result["outcome"], "cancelled")

    async def test_10_cancel_start_while_real_workspace_lease_owned(self):
        record = await self.start("printf READY; exec /usr/bin/sleep 100")
        await self.until(record, b"READY")
        starting = asyncio.create_task(self.start("printf never", key="pending"))
        for _ in range(20):
            if ("test", "pending") in self.backend.processes.processes:
                break
            await asyncio.sleep(0.01)
        pending = self.backend.processes.processes[("test", "pending")]
        starting.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await starting
        self.assertIsNone(pending.process)
        self.assertTrue(pending.closed)
        self.assertTrue(self.backend.files.lock.locked())
        await self.call("process/terminate", {"processId": record.key})
        await self.complete(record)

    async def test_11_supervisor_loss_quarantines_real_owner(self):
        record = await self.start("printf '%s\n' $$; exec /usr/bin/sleep 100")
        for _ in range(20):
            result = await self.call("process/read", {"processId": record.key, "waitMs": 100})
            if self.output(result):
                break
        worker = int(self.output(result))
        # Fault injection only on this test's awaited, unreaped host child.
        os.kill(record.process.pid, signal.SIGKILL)
        await asyncio.wait_for(asyncio.shield(record.finished), 12)
        self.assertTrue(self.backend.processes.quarantined)
        self.assertFalse(record.closed)
        self.assertIsNone(record.native_result)
        self.assertTrue(self.backend.files.lock.locked())
        with self.assertRaises(RpcError):
            await self.start("printf forbidden", key="after-loss")
        # The direct child has PDEATHSIG. Do not claim descendant cleanup from
        # its disappearance: the protocol record is deliberately still absent.
        status = Path(f"/proc/{worker}/status")
        if status.exists():
            self.assertIn("State:\tZ", status.read_text())

    async def test_12_explicit_runtime_denial_is_not_overwritten(self):
        context = kernel.context(self.workspace)
        context["permissions"]["file_system"]["entries"].append(
            {"path": {"type": "path", "path": "file:///usr/share"}, "access": "deny"})
        with self.assertRaises(RpcError):
            await self.start("printf must-not-execute", sandbox=context)
        record = self.backend.processes.failed[-1]
        self.assertIsNone(record.process)
        self.assertTrue(record.closed)
        self.assertFalse(self.backend.files.lock.locked())
        self.assertFalse(self.backend.processes.quarantined)

    async def test_13_fchdir_and_actual_relative_cwd(self):
        program = """import errno,os
os.mkdir('project')
fd=os.open('project',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
os.fchdir(fd);os.close(fd)
assert os.getcwd().endswith('/workspace/project')
open('value','w').write('inside project')
try: open('../private/secret')
except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM),e
else: raise AssertionError('actual cwd denial was bypassed')
fd=os.open('..',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
os.fchdir(fd);os.close(fd)
assert open('project/value').read()=='inside project'
fd=os.open('/usr',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
os.fchdir(fd);os.close(fd)
assert os.stat('bin/python3').st_size>0
print('actual cwd preserved')
"""
        record = await self.start("exec /usr/bin/python3 -I -B -c " + shlex.quote(program))
        result = await self.complete(record)
        self.assertEqual(result["exitCode"], 0, result)
        self.assertEqual(self.output(result), b"actual cwd preserved\n")

    @unittest.skipUnless(SHIM, "The separately built attested cwd shim was not supplied")
    async def test_14_attested_shim_real_bash_and_python_chdir(self):
        await self.backend.close("test")
        shim = Path(SHIM).resolve(strict=True)
        self.options["cwdShim"] = {"path": str(shim), "sha256": hashlib.sha256(shim.read_bytes()).hexdigest()}
        self.backend = factory(self.options)
        (self.workspace / "project").mkdir(mode=0o700)
        program = """import errno,os
assert os.getcwd().endswith('/workspace/project')
os.mkdir('inner');os.chdir('inner')
open('answer','w').write('42')
assert os.getcwd().endswith('/workspace/project/inner')
try: os.chdir('../../private')
except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM),e
else: raise AssertionError('private cwd was admitted')
print('shim native cwd passed')
"""
        record = await self.start("cd project && exec /usr/bin/python3 -I -B -c " + shlex.quote(program))
        result = await self.complete(record)
        self.assertEqual(result["exitCode"], 0, result)
        self.assertEqual(self.output(result), b"shim native cwd passed\n")
        self.assertEqual((self.workspace / "project/inner/answer").read_text(), "42")
        with self.assertRaises(RpcError):
            await self.start("printf forbidden", key="preload", env={"LD_PRELOAD": ""})
        self.assertIsNone(self.backend.processes.failed[-1].process)

    @unittest.skipUnless(SHIM, "The separately built attested cwd shim was not supplied")
    async def test_15_shim_attestation_mismatch_refused(self):
        await self.backend.close("test")
        self.options["cwdShim"] = {"path": str(Path(SHIM).resolve(strict=True)), "sha256": "0" * 64}
        before = set(os.listdir("/proc/self/fd"))
        for _ in range(3):
            with self.assertRaisesRegex(ValueError, "attestation"):
                factory(self.options)
        self.assertEqual(set(os.listdir("/proc/self/fd")), before)
        self.options["cwdShim"]["sha256"] = hashlib.sha256(Path(SHIM).read_bytes()).hexdigest()
        # Successful reconstruction proves the failed constructor released its
        # actual kernel flock, as well as retaining no file descriptor.
        self.backend = factory(self.options)

    async def test_16_runtime_alias_cannot_grant_workspace_execute(self):
        await self.backend.close("test")
        alias = self.base / "runtime-alias"
        alias.symlink_to(self.workspace, target_is_directory=True)
        self.options["runtime"].append({"path": str(alias), "execute": True})
        before = set(os.listdir("/proc/self/fd"))
        with self.assertRaisesRegex(ValueError, "physically overlap"):
            factory(self.options)
        self.assertEqual(set(os.listdir("/proc/self/fd")), before)

    async def test_17_thread_directory_listing_preserves_real_entries(self):
        program = """import os,threading
os.mkdir('project');open('project/value','w').write('actual')
main=os.listdir('project');results=[];errors=[]
def worker():
 try:
  results.append(os.listdir('project'))
  assert open('project/value').read()=='actual'
  assert os.stat('project/value').st_size==6
 except BaseException as error: errors.append(repr(error))
t=threading.Thread(target=worker);t.start();t.join()
assert main==['value'] and results==[['value']] and not errors,(main,results,errors)
print('exact thread directory entries')
"""
        result = await self.complete(await self.start("exec /usr/bin/python3 -I -B -c " + shlex.quote(program)))
        self.assertEqual(result["exitCode"], 0, result)
        self.assertEqual(self.output(result), b"exact thread directory entries\n")

    @unittest.skipUnless(BUILD and (BUILD / "runner-after-final-stop").is_file(), "Host fault-injection supervisor absent")
    async def test_18_final_record_without_owner_wait_keeps_quarantine(self):
        await self.backend.close("test")
        self.options["processRunner"] = str(BUILD / "runner-after-final-stop")
        self.options["limits"]["wall_ms"] = 1000
        self.backend = factory(self.options)
        record = await self.start("printf real-worker-completed")
        identity = os.pidfd_open(record.process.pid)
        try:
            await asyncio.wait_for(asyncio.shield(record.finished), 20)
            self.assertTrue(record.native_result["cleanupComplete"])
            self.assertIsNone(record.process.returncode)
            self.assertTrue(self.backend.processes.quarantined)
            self.assertFalse(record.closed)
            self.assertTrue(self.backend.files.lock.locked())
            self.assertIsNotNone(record.retained_owner)
        finally:
            # Recover only this intentionally stopped, still-owned host process
            # through its pinned pidfd. No fault binary is built for Android.
            signal.pidfd_send_signal(identity, signal.SIGCONT)
            os.close(identity)
            await asyncio.wait_for(record.process.wait(), 5)
            for endpoint in record.retained_owner[3]:
                endpoint.close()
            record.command = None
        self.assertEqual(record.process.returncode, 0)

    @unittest.skipUnless(BUILD and (BUILD / "runner-getdents-memory-missing").is_file(), "Host fault-injection supervisor absent")
    async def test_19_getdents_memory_denial_never_becomes_empty_listing(self):
        await self.backend.close("test")
        self.options["processRunner"] = str(BUILD / "runner-getdents-memory-missing")
        self.backend = factory(self.options)
        program = """import errno,os
os.mkdir('project');open('project/value','w').write('actual')
try: os.listdir('project')
except OSError as error: assert error.errno==errno.EOPNOTSUPP,error
else: raise AssertionError('broker memory denial became a successful listing')
print('actual broker denial preserved')
"""
        result = await self.complete(await self.start("exec /usr/bin/python3 -I -B -c " + shlex.quote(program)))
        self.assertEqual(result["exitCode"], 0, result)
        self.assertEqual(self.output(result), b"actual broker denial preserved\n")

    async def test_20_current_executable_metadata_is_real_and_proc_stays_denied(self):
        await self.backend.close("test")
        executable = (BUILD / "executable-metadata-test").resolve(strict=True)
        self.options["executables"] = {"logical-executable": str(executable)}
        self.options["runtime"].append({"path": str(executable), "execute": True})
        self.backend = factory(self.options)
        context = kernel.context(self.workspace)
        await self.call("process/start", {"processId": "metadata", "argv": ["logical-executable", str(executable)],
            "cwd": context["cwd"], "env": {}, "tty": False, "pipeStdin": True, "sandbox": context})
        record = self.backend.processes.processes[("test", "metadata")]
        result = await self.until(record, b'"mainAndThread":true}')
        observed = json.loads(self.output(result))
        self.assertTrue(observed["mainAndThread"])
        self.assertEqual(record.argv[0], "logical-executable")
        self.assertFalse((self.workspace / record.argv[0]).exists())
        # Independent kernel metadata while our still-owned worker is blocked
        # on its input pipe. Do not compare two broker-emulated stat results.
        proc = Path(f"/proc/{observed['pid']}/exe")
        actual_link, actual_target = proc.lstat(), proc.stat()
        self.assertEqual(proc.readlink(), executable)
        for name, actual in (("linkDevice", actual_link.st_dev), ("linkInode", actual_link.st_ino),
                ("linkMode", actual_link.st_mode), ("linkSize", actual_link.st_size),
                ("targetDevice", actual_target.st_dev), ("targetInode", actual_target.st_ino)):
            self.assertEqual(observed[name], actual, name)
        self.assertEqual((actual_target.st_dev, actual_target.st_ino),
                         (executable.stat().st_dev, executable.stat().st_ino))
        OBSERVATIONS.append({"test": self.id(), "independentProcMetadata": observed,
                             "argv0": record.argv[0], "executable": str(executable)})
        await self.call("process/write", {"processId": record.key, "writeId": "release",
            "chunk": base64.b64encode(b"R").decode()})
        result = await self.complete(record)
        self.assertEqual(result["exitCode"], 0, result)
        self.assertEqual(self.output(result, "stderr"), b"")


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        (BUILD / "factory-observations.json").write_text(json.dumps(OBSERVATIONS, indent=2))
