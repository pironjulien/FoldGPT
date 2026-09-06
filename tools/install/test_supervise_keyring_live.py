"""Exercise the production supervisor against real private Linux DBus/GNOME daemons."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

SUPERVISOR = Path(__file__).with_name("supervise_keyring.py").resolve()
PASSWORD = b"test-only private-pipe credential with spaces and newline\n"


class SupervisedKeyringTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fg-keyring-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir(mode=0o700)
        self.ordinal = 0

    def tearDown(self):
        self.temporary.cleanup()

    def environment(self):
        self.ordinal += 1
        runtime = self.root / ("run" + str(self.ordinal))
        runtime.mkdir(mode=0o700)
        return {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "XDG_RUNTIME_DIR": str(runtime),
                "USER": "foldgpt-test", "PYTHONDONTWRITEBYTECODE": "1",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent-host-bus",
                "DISPLAY": ":937", "SSH_AUTH_SOCK": "/nonexistent-host-ssh"}

    def invoke(self, password=PASSWORD, success=True, env=None):
        result = subprocess.run([sys.executable, str(SUPERVISOR)], env=env or self.environment(),
                                input=password, capture_output=True, timeout=45)
        self.assertNotIn(password, result.stdout + result.stderr)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        if success:
            self.assertTrue(result.stdout.startswith(b"FOLDGPT_KEYRING_RECEIPT="))
            receipt = json.loads(result.stdout.partition(b"=")[2])
            self.assertEqual(receipt["schema"], "foldgpt.inactive-keyring.v1")
            self.assertRegex(receipt["installationId"], r"^[0-9a-f]{64}$")
            self.assertRegex(receipt["intentSha256"], r"^[0-9a-f]{64}$")
            return receipt
        self.assertNotIn(b"FOLDGPT_KEYRING_RECEIPT=", result.stdout)

    def test_creation_restart_wrong_password_and_same_collection_recovery(self):
        initial = self.invoke()
        journal = self.home / ".local/share/.foldgpt-keyring-intent.json"
        original = journal.read_bytes()
        self.assertEqual(initial, self.invoke())
        self.invoke(password=b"test-only wrong password", success=False)
        self.assertEqual(initial, self.invoke())
        self.assertEqual(original, journal.read_bytes())
        encrypted = list((self.home / ".local/share/keyrings").glob("*.keyring"))
        self.assertEqual(len(encrypted), 1)
        for path in self.home.rglob("*"):
            if path.is_file():
                self.assertNotIn(PASSWORD, path.read_bytes(), str(path))

    def test_linked_data_and_occupied_runtime_are_refused(self):
        outside = self.root / "outside"
        outside.mkdir(mode=0o700)
        local = self.home / ".local"
        local.mkdir(mode=0o700)
        (local / "share").symlink_to(outside)
        self.invoke(success=False)
        self.assertEqual(list(outside.iterdir()), [])
        (local / "share").unlink()
        env = self.environment()
        (Path(env["XDG_RUNTIME_DIR"]) / "bus").write_text("preserve")
        self.invoke(success=False, env=env)
        self.assertEqual((Path(env["XDG_RUNTIME_DIR"]) / "bus").read_text(), "preserve")

    def test_abrupt_supervisor_death_kills_owned_daemons_and_preserves_retry(self):
        child = subprocess.Popen([sys.executable, str(SUPERVISOR)], env=self.environment(),
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        children = []
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                children = [int(value) for value in Path(f"/proc/{child.pid}/task/{child.pid}/children").read_text().split()]
                if len(children) == 2 and all(Path(f"/proc/{pid}/exe").exists() for pid in children):
                    break
                self.assertIsNone(child.poll())
                time.sleep(0.025)
            self.assertEqual(len(children), 2)
            for pid in children:
                self.assertNotIn(PASSWORD, Path(f"/proc/{pid}/cmdline").read_bytes())
                environment = Path(f"/proc/{pid}/environ").read_bytes()
                self.assertNotIn(PASSWORD, environment)
                self.assertNotIn(b"DISPLAY=", environment)
                self.assertNotIn(b"SSH_AUTH_SOCK=", environment)
            child.kill()
            child.communicate(timeout=10)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                alive = []
                for pid in children:
                    try:
                        if Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].strip().split()[0] != "Z":
                            alive.append(pid)
                    except FileNotFoundError:
                        pass
                if not alive:
                    break
                time.sleep(0.025)
            self.assertEqual(alive, [], "Owned daemon survived parent death")
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
        self.invoke()


if __name__ == "__main__":
    unittest.main()
