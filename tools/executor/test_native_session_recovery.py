"""Real nonroot crash/recovery fixtures; no Android result is inferred.

Run this file directly under a dedicated ordinary UID. It re-execs its test
controller with the production Java argv[0], so the actual PID/start-time/name
verification is exercised without replacing the production admission function.
"""
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PYTHON = os.readlink("/proc/self/exe")

from tools.executor.native_session_recovery import (
    APPLICATION_PROCESSES_SCHEMA, APPLICATION_PROCESSES_SOURCE,
    application_processes, observe_uid_quiescence, process_identity,
)
from tools.executor.private_exec_broker import PrivateSessionOwner, PROCESS_SESSION

EPOCH = {"schema": "foldgpt.android-boot-epoch.v1",
         "source": "android.provider.Settings.Global.BOOT_COUNT", "bootCount": 8}


class NativeSessionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertNotEqual(os.getuid(), 0)
        self.assertEqual(Path("/proc/self/cmdline").read_bytes().split(b"\0", 1)[0], b"app.foldgpt:runtime")
        self.temp = tempfile.TemporaryDirectory(prefix="foldgpt-recovery-", dir="/var/tmp")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "broker"
        self.workspace = Path(self.temp.name) / "workspace"
        self.directory.mkdir(mode=0o700)
        self.workspace.mkdir(mode=0o700)
        self.marker = self.directory / PROCESS_SESSION
        identity = process_identity(os.getpid())
        self.population = {"schema": APPLICATION_PROCESSES_SCHEMA,
                           "source": APPLICATION_PROCESSES_SOURCE,
                           "processes": [{"pid": os.getpid(), "startTimeTicks": identity["startTimeTicks"],
                                          "processName": "app.foldgpt:runtime"}]}

    def child_argv(self, source, population=None):
        prelude = ("import os,sys,json,signal;sys.path.insert(0,sys.argv[1]);"
                   "from tools.executor.private_exec_broker import PrivateSessionOwner;"
                   "directory,workspace=sys.argv[2:4];population=json.loads(sys.argv[4]);"
                   "epoch=json.loads(sys.argv[5])\n")
        return [PYTHON, "-I", "-S", "-B", "-u", "-c", prelude + source, str(ROOT),
                str(self.directory), str(self.workspace), json.dumps(population or self.population), json.dumps(EPOCH)]

    def child(self, source, population=None, expected=0):
        result = subprocess.run(self.child_argv(source, population), capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, expected, result.stderr)
        if expected == 0:
            self.assertEqual(result.stderr, "")
        return result

    def crash(self):
        self.child("owner=PrivateSessionOwner(directory,boot_epoch=epoch);"
                   "owner.begin_process_session(workspace);os.kill(os.getpid(),signal.SIGKILL)\n",
                   expected=-signal.SIGKILL)
        self.assertTrue(self.marker.is_file())
        return self.marker.read_bytes(), self.marker.stat()

    @staticmethod
    def recover_source():
        return ("owner=PrivateSessionOwner(directory,boot_epoch=epoch,application_processes=population,"
                "parent_pid=os.getppid(),workspace=workspace)\n")

    def test_real_sigkill_recovery_archives_original_inode_and_bytes(self):
        before, identity = self.crash()
        result = self.child(self.recover_source() +
                            "print(json.dumps(owner.recovered_session));owner.begin_process_session(workspace);"
                            "owner.finish_process_session();owner.close()\n")
        receipt = json.loads(result.stdout)
        self.assertFalse(receipt["previousBootEnded"])
        self.assertFalse(receipt["previousCleanupClaimed"])
        self.assertEqual(receipt["quiescenceObservation"]["nonzeroSignalsSent"], 0)
        saved = self.directory / receipt["archiveName"] / PROCESS_SESSION
        self.assertEqual(saved.read_bytes(), before)
        self.assertEqual((saved.stat().st_dev, saved.stat().st_ino), (identity.st_dev, identity.st_ino))
        self.assertFalse(self.marker.exists())

    def test_live_owner_lock_refuses_recovery_without_changing_marker(self):
        owner = PrivateSessionOwner(self.directory, boot_epoch=EPOCH)
        try:
            owner.begin_process_session(self.workspace)
            before = self.marker.read_bytes()
            source = "try:\n    " + self.recover_source().strip() + "\nexcept BlockingIOError:\n    print('blocked')\nelse:\n    raise RuntimeError('Live owner admitted')\n"
            self.assertEqual(self.child(source).stdout, "blocked\n")
            self.assertEqual(self.marker.read_bytes(), before)
            owner.finish_process_session()
        finally:
            owner.close()

    def test_real_surviving_process_refuses_archival_and_remains_alive(self):
        before, _ = self.crash()
        survivor = subprocess.Popen([PYTHON, "-I", "-S", "-B", "-c", "import time;time.sleep(60)"], stdout=subprocess.DEVNULL)
        try:
            source = "try:\n    " + self.recover_source().strip() + "\nexcept FileExistsError:\n    print('blocked')\nelse:\n    raise RuntimeError('Survivor admitted')\n"
            self.assertEqual(self.child(source).stdout, "blocked\n")
            self.assertEqual(self.marker.read_bytes(), before)
            self.assertIsNone(survivor.poll())
        finally:
            survivor.terminate()
            survivor.wait(timeout=5)

    def test_reused_java_pid_start_time_is_refused_before_archival(self):
        before, _ = self.crash()
        declared = json.loads(json.dumps(self.population))
        declared["processes"][0]["startTimeTicks"] += 1
        source = "try:\n    " + self.recover_source().strip() + "\nexcept PermissionError:\n    print('blocked')\nelse:\n    raise RuntimeError('Reused PID admitted')\n"
        self.assertEqual(self.child(source, declared).stdout, "blocked\n")
        self.assertEqual(self.marker.read_bytes(), before)

    def test_workspace_identity_change_refuses_archival(self):
        before, _ = self.crash()
        self.workspace.rename(self.workspace.with_name("preserved-workspace"))
        self.workspace.mkdir(mode=0o700)
        source = "try:\n    " + self.recover_source().strip() + "\nexcept PermissionError:\n    print('blocked')\nelse:\n    raise RuntimeError('Replaced workspace admitted')\n"
        self.assertEqual(self.child(source).stdout, "blocked\n")
        self.assertEqual(self.marker.read_bytes(), before)

    def test_real_allowed_nonleader_threads_do_not_prevent_recovery(self):
        before, _ = self.crash()
        stopped = threading.Event()
        threads = [threading.Thread(target=stopped.wait) for _ in range(3)]
        for thread in threads:
            thread.start()
        try:
            result = self.child(self.recover_source() + "print(json.dumps(owner.recovered_session));owner.close()\n")
            receipt = json.loads(result.stdout)
            self.assertEqual((self.directory / receipt["archiveName"] / PROCESS_SESSION).read_bytes(), before)
            self.assertTrue(all(thread.is_alive() for thread in threads))
        finally:
            stopped.set()
            for thread in threads:
                thread.join(timeout=5)

    def test_nondumpable_survivor_missing_from_directory_is_still_refused(self):
        source = ("import ctypes,os,time;lib=ctypes.CDLL(None);"
                  "assert lib.prctl(4,0,0,0,0)==0;print('ready',flush=True);time.sleep(60)")
        survivor = subprocess.Popen([PYTHON, "-I", "-S", "-B", "-u", "-c", source], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(survivor.stdout.readline(), "ready\n")
            os.kill(survivor.pid, 0)
            original = os.listdir
            def incomplete_listing(path):
                values = original(path)
                return [entry for entry in values if entry != str(survivor.pid)] if path == "/proc" else values
            # Fault injection models the actual observed Android hidepid view;
            # the child, its nondumpable setting and signal-0 detection are real.
            with patch("tools.executor.native_session_recovery.os.listdir", side_effect=incomplete_listing):
                with self.assertRaises(FileExistsError):
                    observe_uid_quiescence([process_identity(os.getpid())])
            self.assertIsNone(survivor.poll())
        finally:
            survivor.terminate()
            survivor.wait(timeout=5)
            survivor.stdout.close()


if __name__ == "__main__":
    if Path("/proc/self/cmdline").read_bytes().split(b"\0", 1)[0] != b"app.foldgpt:runtime":
        os.execve(PYTHON, ["app.foldgpt:runtime", "-I", "-S", "-B", str(Path(__file__).resolve())], os.environ)
    unittest.main(verbosity=2)
