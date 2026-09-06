"""Host checks for plan refusal and real subprocess behavior, never host dpkg writes."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_official_client as installer


class InstallTests(unittest.TestCase):
    def test_exact_client_plan_required_and_dependency_changes_rejected(self):
        installer.check_plan("Inst chatgpt (1.0 local [arm64])\nConf chatgpt (1.0 local [arm64])\n")
        for text in ("", "Inst libc6 (2.40)\nInst chatgpt (1.0)\n", "Remv git\nInst chatgpt (1.0)\n",
                     "Purg chatgpt\n", "Inst chatgpt (1.0)\nInst chatgpt (1.0)\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                installer.check_plan(text)

    def test_package_state_rejects_missing_duplicate_and_malformed_identity(self):
        record = "libc6:arm64\t2.41-12\tarm64\tinstall ok installed\n"
        self.assertEqual(installer.parse_status(record)["libc6:arm64"]["version"], "2.41-12")
        for text in ("", record + record, "libc6\t2.41\n", "bad/name\t2.41\tarm64\tinstall ok installed\n"):
            with self.assertRaises(ValueError):
                installer.parse_status(text)

    def test_resume_accepts_only_pending_triggers_and_unchanged_base_versions(self):
        baseline = installer.parse_status("libc6:arm64\t2.41-12\tarm64\tinstall ok installed\n")
        installer.check_baseline(baseline, baseline, final=True)
        pending = {"libc6:arm64": {**baseline["libc6:arm64"], "status": "install ok triggers-pending"}}
        installer.check_baseline(pending, baseline)
        with self.assertRaises(ValueError):
            installer.check_baseline(pending, baseline, final=True)
        for changed in ({}, {"libc6:arm64": {**baseline["libc6:arm64"], "version": "2.42"}},
                        {"libc6:arm64": {**baseline["libc6:arm64"], "status": "install reinstreq half-installed"}}):
            with self.assertRaises(ValueError):
                installer.check_baseline(changed, baseline)

    def test_client_selection_rejects_multiple_architectures(self):
        records = installer.parse_status("chatgpt\t1.2\tarm64\tinstall ok installed\n")
        self.assertEqual(installer.client_record(records)["architecture"], "arm64")
        with self.assertRaises(ValueError):
            installer.client_record({**records, "chatgpt:amd64": records["chatgpt"]})

    def test_wrong_root_is_rejected_before_package_commands(self):
        with self.assertRaises(ValueError):
            installer.provision({"format": installer.package.FORMAT, "sourceUrl": installer.package.SOURCE_URL,
                "sourceDocument": installer.package.SOURCE_DOCUMENT, "package": "chatgpt", "version": "1.2",
                "architecture": "arm64", "sha256": "0" * 64, "bytes": 1, "maxTarBytes": 1,
                "maxMembers": 1}, "0" * 64, "0:0")

    def test_real_command_eof_failure_and_private_log(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "success.log"
            result = installer.run([sys.executable, "-c", "import sys; assert sys.stdin.read() == ''; print('actual output')"], 5, log)
            self.assertEqual(result, "actual output\n")
            self.assertEqual(log.stat().st_mode & 0o777, 0o600)
            failure = Path(temporary) / "failure.log"
            with self.assertRaisesRegex(RuntimeError, "exit=17"):
                installer.run([sys.executable, "-c", "import sys; print('failure evidence'); sys.exit(17)"], 5, failure)
            self.assertEqual(failure.read_text(), "failure evidence\n")

    def test_deadline_and_excess_output_stop_real_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                installer.run([sys.executable, "-c", "import time; time.sleep(30)"], 0.1, Path(temporary) / "timeout.log")
            self.assertLess(time.monotonic() - started, 5)
            with self.assertRaisesRegex(ValueError, "output exceeds"):
                installer.run([sys.executable, "-c", "import sys; sys.stdout.write('x' * (8 * 1024 * 1024 + 1))"], 5,
                              Path(temporary) / "overflow.log")


if __name__ == "__main__":
    unittest.main(verbosity=2)
