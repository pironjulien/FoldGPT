import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provision_keyring", ROOT / "tools/provision-keyring.py")
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)


class ProvisionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "Private shell publication requires POSIX filesystem modes")
    def test_existing_import_is_preserved_and_failed_attempt_cleans_its_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            def run(token, value):
                command = provision.staging_command(token).replace(
                    "/data/user/0/app.foldgpt/no_backup", str(base / "no_backup"))
                return subprocess.run(["sh", "-c", command], cwd=base, input=value,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            first = run("a" * 32, b"first test credential")
            self.assertEqual(first.returncode, 0, first.stderr)
            second = run("b" * 32, b"second test credential")
            self.assertNotEqual(second.returncode, 0)
            directory = base / "no_backup/foldgpt-keyring"
            self.assertEqual((directory / "keyring-password.import").read_bytes(), b"first test credential")
            self.assertEqual(sorted(path.name for path in directory.iterdir()), ["keyring-password.import"])

    def test_rejects_staging_path_injection(self):
        for token in ("../secret", "x" * 32, "a" * 32 + ";cat"):
            with self.subTest(token=token), self.assertRaises(ValueError):
                provision.staging_command(token)

    def test_secret_only_goes_to_stdin_and_device_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "test-only-password.txt"
            source.write_bytes("test secret é\n".encode())
            captured = {}

            def run(command, **kwargs):
                captured["command"] = command
                captured["input"] = bytes(kwargs["input"])
                captured["mutable_input"] = kwargs["input"]
                self.assertIs(kwargs["stdout"], provision.subprocess.DEVNULL)
                self.assertIs(kwargs["stderr"], provision.subprocess.DEVNULL)
                return SimpleNamespace(returncode=0)

            with patch.object(provision.sys, "argv", ["provision", "--serial", "test-phone", "--secret-file", str(source)]), \
                 patch.object(provision.subprocess, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(provision.main(), 0)
            self.assertEqual(captured["command"][:3], ["adb", "-s", "test-phone"])
            self.assertNotIn("test secret", " ".join(captured["command"]))
            self.assertEqual(captured["input"], source.read_bytes())
            self.assertEqual(captured["mutable_input"], bytearray(len(captured["input"])))


if __name__ == "__main__":
    unittest.main()
