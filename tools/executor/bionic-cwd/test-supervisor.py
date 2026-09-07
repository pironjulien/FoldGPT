"""Compose the real frozen native supervisor factory with the attested shim.

Usage: python3 -B test-supervisor.py FROZEN_SUPERVISOR_DIR HOST_CWD_LIBRARY
Run under an ordinary Linux UID. No Android device is accessed.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import shlex
import sys
import unittest

if len(sys.argv) != 3:
    raise SystemExit(__doc__)
BUILD, SHIM = map(lambda item: Path(item).resolve(strict=True), sys.argv[1:])
sys.argv[:] = sys.argv[:1]
sys.path.insert(0, str(BUILD / "package"))
base = importlib.import_module("tools.executor.bionic-supervisor.test_factory")
base.BUILD = BUILD
SHIM_OPTIONS = {"path": str(SHIM), "sha256": hashlib.sha256(SHIM.read_bytes()).hexdigest()}


class CwdTests(base.FactoryTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.backend.close("configure-shim")
        self.options["cwdShim"] = SHIM_OPTIONS
        self.backend = base.factory(self.options)

    async def test_cwd_real_bash_and_python_policy(self):
        (self.workspace / "project").mkdir(mode=0o700)
        program = """import errno,os
assert os.getcwd().endswith('/workspace/project')
os.mkdir('nested')
os.chdir('nested')
assert os.getcwd().endswith('/workspace/project/nested')
open('answer','w').write('42')
os.chdir('..')
assert open('nested/answer').read()=='42'
try: os.chdir('../private')
except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM),e
else: raise AssertionError('chdir entered policy-denied directory')
assert os.getcwd().endswith('/workspace/project')
try: open('../private/secret')
except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM),e
else: raise AssertionError('relative read escaped cwd policy')
os.chdir('..')
assert os.getcwd().endswith('/workspace')
print('Bash and Python actual cwd with policy passed')
"""
        command = "cd project && exec /usr/bin/python3 -I -B -c " + shlex.quote(program)
        result = await self.complete(await self.start(command))
        self.assertEqual(result["exitCode"], 0, result)
        self.assertEqual(self.output(result), b"Bash and Python actual cwd with policy passed\n")
        self.assertEqual((self.workspace / "project/nested/answer").read_text(), "42")
        self.assertEqual((self.workspace / "private/secret").read_text(), "unchanged private data")

    async def test_reserved_preload_cannot_be_requested(self):
        for value in (str(SHIM), "", "/usr/lib/pretend.so"):
            with self.assertRaises(base.RpcError):
                await self.start("printf forbidden", key="reserved-" + str(len(value)), env={"LD_PRELOAD": value})
            failed = self.backend.processes.failed[-1]
            self.assertIsNone(failed.process)
            self.assertTrue(failed.closed)
            self.assertFalse(self.backend.files.lock.locked())
            self.assertFalse(self.backend.processes.quarantined)

    async def test_removed_preload_still_cannot_call_raw_chdir(self):
        program = """import errno,os
try: os.chdir('.')
except OSError as e: assert e.errno==errno.EPERM,e
else: raise AssertionError('unloaded shim bypassed syscall denial')
print('missing shim fails closed')
"""
        command = "unset LD_PRELOAD; exec /usr/bin/python3 -I -B -c " + shlex.quote(program)
        result = await self.complete(await self.start(command))
        self.assertEqual(result["exitCode"], 0, result)
        self.assertEqual(self.output(result), b"missing shim fails closed\n")

    async def test_wrong_attestation_rejected_before_worker(self):
        # Release this backend's real workspace flock first, so failure cannot
        # come from concurrent ownership instead of the digest under test.
        await self.backend.close("test")
        options = dict(self.options)
        options["cwdShim"] = {**SHIM_OPTIONS, "sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "differs from its bootstrap attestation"):
            base.factory(options)
        self.assertFalse(self.backend.processes.processes)


if __name__ == "__main__":
    if os.getuid() == 0:
        raise SystemExit("Use an ordinary host UID")
    names = [name for name in CwdTests.__dict__ if name.startswith("test_")]
    suite = unittest.TestSuite(CwdTests(name) for name in names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    evidence = {"schema": "foldgpt.bionic-cwd.host.v1", "success": result.wasSuccessful(),
                "scope": "host-native-executor", "uid": os.getuid(), "testsRun": result.testsRun,
                "shim": SHIM_OPTIONS, "supervisorBuild": str(BUILD),
                "androidExecution": False, "observations": base.OBSERVATIONS}
    (BUILD / "cwd-shim-observations.json").write_text(json.dumps(evidence, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
