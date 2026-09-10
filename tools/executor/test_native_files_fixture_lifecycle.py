"""Real subprocess failure cleanup for the native RPC fixture; POSIX only."""
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest

from tools.executor.native_files_rpc_fixture import Peer


@unittest.skipUnless(os.name == "posix", "Requires actual POSIX descriptors and process groups")
class FixtureLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="foldgpt-rpc-lifecycle-")
        self.root = Path(self.directory.name)
        for name in ("home", "tmp"):
            (self.root / name).mkdir(mode=0o700)

    def tearDown(self):
        self.directory.cleanup()

    def test_failed_exec_closes_the_real_error_descriptor(self):
        before = set(os.listdir("/proc/self/fd"))
        with self.assertRaises(FileNotFoundError):
            Peer([str(self.root / "absent-executable")], self.root, self.root)
        self.assertEqual(set(os.listdir("/proc/self/fd")), before)
        self.assertEqual((self.root / "server-stderr.txt").read_bytes(), b"")

    def test_broken_stdin_close_still_reaps_the_actual_child(self):
        peer = Peer([sys.executable, "-I", "-S", "-c", "pass"], self.root, self.root)
        self.assertEqual(peer.process.wait(5), 0)
        # This write is buffered until close, which must really encounter EPIPE.
        peer.process.stdin.write(b"pending")
        with self.assertRaises(BrokenPipeError):
            peer.close(False)
        self.assertTrue(peer.error.closed)
        self.assertTrue(peer.process.stdout.closed)
        with self.assertRaises(ProcessLookupError):
            os.killpg(peer.process.pid, 0)

    def test_trailing_real_output_is_a_failure_with_closed_resources(self):
        peer = Peer([sys.executable, "-I", "-S", "-c", "print('unexpected')"], self.root, self.root)
        with self.assertRaisesRegex(RuntimeError, "trailing RPC output"):
            peer.close(True)
        self.assertTrue(peer.error.closed)
        self.assertTrue(peer.process.stdout.closed)
        with self.assertRaises(ProcessLookupError):
            os.killpg(peer.process.pid, 0)

    def test_exited_server_with_live_descendant_never_claims_clean_eof(self):
        script = (
            "import os,time\n"
            "child=os.fork()\n"
            "if child == 0:\n"
            " open('descendant-pid','x').write(str(os.getpid()))\n"
            " time.sleep(60)\n"
            "else:\n"
            " while not os.path.exists('descendant-pid'): time.sleep(.001)\n"
        )
        peer = Peer([sys.executable, "-I", "-S", "-c", script], self.root, self.root)
        started = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "output remained open"):
            peer.close(True)
        self.assertLess(time.monotonic() - started, 20)
        descendant = int((self.root / "descendant-pid").read_text())
        status = Path(f"/proc/{descendant}/status")
        deadline = time.monotonic() + 5
        while status.exists() and "State:\tZ" not in status.read_text() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(not status.exists() or "State:\tZ" in status.read_text(),
                        "Descendant remains executable after diagnostic failure cleanup")
        self.assertTrue(peer.error.closed)
        self.assertTrue(peer.process.stdout.closed)


if __name__ == "__main__":
    unittest.main()
