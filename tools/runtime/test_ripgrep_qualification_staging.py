"""Execute the staged client's real import closure without access to repo imports."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
import uuid


_spec = importlib.util.spec_from_file_location("ripgrep_device_driver",
    Path(__file__).with_name("qualify-production-device.py"))
_driver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_driver)


class RipgrepQualificationStaging(unittest.TestCase):
    def run_client_help(self, *, omit=None):
        output = _driver.ROOT / "work/native-ripgrep-20260908" / ("staging-test-" + uuid.uuid4().hex)
        package = output / "client"
        package.mkdir(parents=True, exist_ok=False)
        inputs = _driver.qualification_inputs("ripgrep")
        self.assertEqual(set(inputs), {"client.py", "native_path_uri.py",
            "qualify_production_host_v2.py", "qualify_production_ordinary_uid.py"})
        for name, data in inputs.items():
            if name != omit:
                (package / name).write_bytes(data)
        result = subprocess.run([sys.executable, "-I", "-S", "-B", str(package / "client.py"), "--help"],
            cwd=output, capture_output=True, timeout=20)
        (output / "stdout.txt").write_bytes(result.stdout)
        (output / "stderr.txt").write_bytes(result.stderr)
        return result

    def test_complete_import_closure_runs_in_isolated_directory(self):
        result = self.run_client_help()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"startup", result.stdout)
        self.assertEqual(result.stderr, b"")

    def test_missing_nested_client_dependency_fails_before_any_acquisition(self):
        result = self.run_client_help(omit="qualify_production_ordinary_uid.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"FileNotFoundError", result.stderr)
        self.assertIn(b"qualify_production_ordinary_uid.py", result.stderr)
        self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
