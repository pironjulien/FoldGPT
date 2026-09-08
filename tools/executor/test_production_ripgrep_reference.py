"""Verify qualification expectations against installed, unmodified host ripgrep.

These tests do not simulate RPC or prove Android execution. They preserve the
actual Windows/Linux tool's streams and exercise the same files and searches.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
import uuid

from tools.executor.qualify_production_ripgrep import SOURCES, cases, validate_case


class RealRipgrepReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        found = os.environ.get("FOLDGPT_REFERENCE_RG") or shutil.which("rg")
        if not found:
            raise RuntimeError("A real ripgrep 15.2.0 with PCRE2/JIT must be installed for the reference test")
        cls.rg = Path(found).resolve(strict=True)
        cls.output = Path(__file__).resolve().parents[2] / "work/native-ripgrep-20260908" / ("pc-reference-" + uuid.uuid4().hex)
        cls.project = cls.output / "project"
        cls.project.mkdir(parents=True, exist_ok=False)
        (cls.project / ".git").mkdir()
        for name, content in SOURCES.items():
            path = cls.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        cls.records = []

    def test_real_searches_unicode_json_pcre_and_exit_statuses(self):
        for case in cases():
            with self.subTest(case=case["case"]):
                command = [str(self.rg), *case["argv"]]
                if "stdin" in case:
                    # Do not send EOF: rg must exit naturally on its first
                    # complete matching line while the write end stays open.
                    process = subprocess.Popen(command, cwd=self.project, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    try:
                        process.stdin.write(case["stdin"])
                        process.stdin.flush()
                        code = process.wait(timeout=20)
                        stdout, stderr = process.stdout.read(), process.stderr.read()
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=10)
                        process.stdin.close()
                        process.stdout.close()
                        process.stderr.close()
                else:
                    run = subprocess.run(command, cwd=self.project, stdin=subprocess.DEVNULL,
                        capture_output=True, timeout=20)
                    code, stdout, stderr = run.returncode, run.stdout, run.stderr
                (self.output / (case["case"] + ".stdout")).write_bytes(stdout)
                (self.output / (case["case"] + ".stderr")).write_bytes(stderr)
                self.records.append({"case": case["case"], "argv": command, "exitCode": code,
                    "stdoutSha256": hashlib.sha256(stdout).hexdigest(),
                    "stderrSha256": hashlib.sha256(stderr).hexdigest()})
                self.assertEqual(code, case["exitCode"], stderr)
                validate_case(case, {"stdout": stdout, "stderr": stderr})
        for name, content in SOURCES.items():
            self.assertEqual((self.project / name).read_bytes(), content)

    @classmethod
    def tearDownClass(cls):
        (cls.output / "report.json").write_text(json.dumps({
            "schema": "foldgpt.ripgrep-host-reference.v1", "platform": os.name,
            "androidExecuted": False, "productionChannelsExecuted": False,
            "executable": str(cls.rg), "executableSha256": hashlib.sha256(cls.rg.read_bytes()).hexdigest(),
            "cases": cls.records}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
