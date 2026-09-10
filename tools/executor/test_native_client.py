"""Malformed IPC tests for the host client. Stub backends prove no isolation."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from tools.executor.native_client import NativeRun, RunnerError


@unittest.skipUnless(os.name == "posix", "requires real POSIX pipes/processes")
class NativeClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="foldgpt-client-")
        self.backend = Path(self.temp.name) / "backend"
        self.manifest = {"limits": {"wallMs": 2000, "outputBytes": 4096}}
        self.result = {"type": "result", "outcome": "exited", "exitCode": 0,
                       "signal": None, "stdoutBytes": 0, "stderrBytes": 0,
                       "cleanupComplete": True, "errorStage": None, "errno": 0}
        self.started = {"type": "started", "pid": 123, "policy": "landlock-basic-data-v1"}

    def tearDown(self):
        self.temp.cleanup()

    def script(self, code):
        self.backend.write_text("#!/usr/bin/python3\nimport sys,os,json,time\n"
                                "fd=int(sys.argv[2]); sys.stdin.buffer.read()\n" + code)
        self.backend.chmod(0o700)

    def emit(self, value):
        return "os.write(fd," + repr((json.dumps(value) + "\n").encode()) + ")\n"

    def run_failure(self):
        with NativeRun(self.backend, self.manifest) as running:
            with self.assertRaises(RunnerError):
                running.wait()
            self.assertFalse(running.verified)

    def test_zero_exit_without_completion_is_not_success(self):
        self.script("")
        self.run_failure()

    def test_claimed_completion_without_started_is_rejected(self):
        self.script(self.emit(self.result))
        self.run_failure()

    def test_claimed_success_with_nonzero_supervisor_exit_is_rejected(self):
        self.script(self.emit(self.started) + self.emit(self.result) + "sys.exit(1)\n")
        self.run_failure()

    def test_false_cleanup_is_rejected(self):
        self.result["cleanupComplete"] = False
        self.script(self.emit(self.started) + self.emit(self.result))
        self.run_failure()

    def test_output_counts_are_independently_checked(self):
        self.script(self.emit(self.started) + "os.write(1,b'actual bytes')\n" + self.emit(self.result))
        self.run_failure()

    def test_duplicate_control_fields_are_rejected(self):
        self.script("os.write(fd,b'{\"type\":\"started\",\"type\":\"result\"}\\n')\n")
        self.run_failure()

    def test_partial_completion_is_rejected(self):
        self.script("os.write(fd,b'{\"type\":\"result\"}')\n")
        self.run_failure()

    def test_duplicate_completion_is_rejected(self):
        self.script(self.emit(self.started) + self.emit(self.result) + self.emit(self.result))
        self.run_failure()

    def test_output_limit_is_checked_even_if_backend_ignores_it(self):
        self.script(self.emit(self.started) + "os.write(1,b'x'*4097)\n" + self.emit(self.result))
        self.run_failure()

    def test_stalled_manifest_consumer_is_bounded(self):
        # No stdin read. A large manifest cannot block the constructor's write.
        self.backend.write_text("#!/usr/bin/python3\nimport time\ntime.sleep(20)\n")
        self.backend.chmod(0o700)
        self.manifest["padding"] = "x" * 60000
        with NativeRun(self.backend, self.manifest) as running:
            running.deadline = __import__("time").monotonic() + 0.1
            with self.assertRaises(RunnerError):
                running.wait()
            self.assertFalse(running.verified)


if __name__ == "__main__":
    unittest.main()
