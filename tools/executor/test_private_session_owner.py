"""Real nonroot ownership tests; no Android device or sandbox result is claimed."""
import errno
import json
import os
from pathlib import Path
import select
import socket
import stat
import subprocess
import sys
import tempfile
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.executor.private_exec_broker import (
    PROCESS_SESSION, SOCKET_NAME, PrivateListener, PrivateSessionOwner, peer_identity,
)

REPO = Path(__file__).resolve().parents[2]
CHILD_IMPORTS = (
    "import os,sys,json;sys.path.insert(0,sys.argv[1]);"
    "from tools.executor.private_exec_broker import PrivateListener,PrivateSessionOwner;"
    "directory,workspace=sys.argv[2:4]\n"
)


class PrivateSessionOwnerTests(unittest.TestCase):
    def setUp(self):
        self.assertNotEqual(os.getuid(), 0, "Run real ownership tests with an ordinary Linux UID")
        self.temp = tempfile.TemporaryDirectory(prefix="fowner-", dir="/var/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "broker"
        self.workspace = self.root / "workspace"
        self.directory.mkdir(mode=0o700)
        self.workspace.mkdir(mode=0o700)

    def child_argv(self, source, directory=None):
        return [sys.executable, "-I", "-S", "-B", "-u", "-c", CHILD_IMPORTS + source,
                str(REPO), str(directory or self.directory), str(self.workspace)]

    def child(self, source, directory=None):
        result = subprocess.run(self.child_argv(source, directory), env={}, capture_output=True,
                                text=True, timeout=5, check=True)
        self.assertEqual(result.stderr, "")
        return result.stdout

    def assert_blocked_child(self, kind, directory=None):
        observed = json.loads(self.child(
            f"try:\n    owner={kind.__name__}(directory)\n"
            "except OSError as error:\n    print(json.dumps({'type':type(error).__name__,'errno':error.errno}))\n"
            "else:\n    owner.close();raise RuntimeError('Concurrent ownership was admitted')\n", directory))
        self.assertEqual(observed["type"], "BlockingIOError")
        self.assertIn(observed["errno"], (errno.EAGAIN, errno.EWOULDBLOCK))

    def test_stdio_owner_pins_private_cloexec_fds_without_creating_socket(self):
        owner = PrivateSessionOwner(self.directory)
        try:
            self.assertEqual({p.name for p in self.directory.iterdir()}, {"broker.lock"})
            self.assertFalse(os.get_inheritable(owner.fd))
            self.assertFalse(os.get_inheritable(owner.lock))
            self.assertEqual(stat.S_IMODE(os.fstat(owner.lock).st_mode), 0o600)
            pinned = os.fstat(owner.fd)
            declared = self.directory.stat()
            self.assertEqual((pinned.st_dev, pinned.st_ino), (declared.st_dev, declared.st_ino))
            owner.begin_process_session(self.workspace)
            marker = json.loads((self.directory / PROCESS_SESSION).read_bytes())
            self.assertEqual(marker["brokerPid"], os.getpid())
            self.assertEqual(marker["uid"], os.getuid())
            self.assertEqual((marker["workspaceDevice"], marker["workspaceInode"]),
                             (self.workspace.stat().st_dev, self.workspace.stat().st_ino))
            owner.finish_process_session()
            self.assertFalse((self.directory / PROCESS_SESSION).exists())
            self.assertFalse((self.directory / SOCKET_NAME).exists())
        finally:
            owner.close()
        self.assertIsNone(owner.fd)
        self.assertIsNone(owner.lock)
        owner.close()

    def test_owner_and_listener_share_real_process_exclusion_in_both_directions(self):
        for holder in (PrivateSessionOwner, PrivateListener):
            with self.subTest(holder=holder.__name__):
                owner = holder(self.directory)
                try:
                    for contender in (PrivateSessionOwner, PrivateListener):
                        self.assert_blocked_child(contender)
                    owner.begin_process_session(self.workspace)
                    for contender in (PrivateSessionOwner, PrivateListener):
                        self.assert_blocked_child(contender)
                    owner.finish_process_session()
                finally:
                    owner.close()
                other = (PrivateListener if holder is PrivateSessionOwner else PrivateSessionOwner)(self.directory)
                other.close()

    def test_listener_still_binds_private_socket_and_observes_real_peer_credentials(self):
        owner = PrivateListener(self.directory)
        try:
            self.assertTrue(stat.S_ISSOCK(owner.path.stat().st_mode))
            self.assertEqual(stat.S_IMODE(owner.path.stat().st_mode), 0o600)
            self.assertFalse(owner.listener.get_inheritable())
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(owner.path))
                accepted, _ = owner.listener.accept()
                with accepted:
                    self.assertEqual(peer_identity(accepted),
                                     {"pid": os.getpid(), "uid": os.getuid(), "gid": os.getgid()})
        finally:
            owner.close()
        self.assertFalse((self.directory / SOCKET_NAME).exists())

    def test_actual_owner_exit_leaves_marker_and_both_transports_refuse_restart(self):
        self.child("owner=PrivateSessionOwner(directory);owner.begin_process_session(workspace);os._exit(0)\n")
        marker = self.directory / PROCESS_SESSION
        before = marker.read_bytes()
        for kind in (PrivateSessionOwner, PrivateListener):
            with self.assertRaisesRegex(FileExistsError, "lacks verified cleanup"):
                kind(self.directory)
            self.assertEqual(marker.read_bytes(), before)

    def test_quarantined_owner_keeps_actual_lock_and_marker(self):
        source = (
            "owner=PrivateSessionOwner(directory);owner.begin_process_session(workspace);owner.quarantined=True\n"
            "try:\n    owner.finish_process_session()\n"
            "except RuntimeError:\n    print('retained',flush=True)\n"
            "else:\n    raise RuntimeError('Quarantine was released')\n"
            "sys.stdin.read(1);os._exit(0)\n"
        )
        process = subprocess.Popen(self.child_argv(source), env={}, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertTrue(select.select([process.stdout], [], [], 5)[0])
            self.assertEqual(process.stdout.readline(), b"retained\n")
            marker = self.directory / PROCESS_SESSION
            before = marker.read_bytes()
            for kind in (PrivateSessionOwner, PrivateListener):
                self.assert_blocked_child(kind)
            self.assertIsNone(process.poll())
            self.assertEqual(marker.read_bytes(), before)
            # This test child owns only a lock/marker, no worker. Its real exit
            # must still leave quarantine evidence; absence never grants reuse.
            process.stdin.close()
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertEqual(process.stderr.read(), b"")
            with self.assertRaises(FileExistsError):
                PrivateSessionOwner(self.directory)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_existing_real_socket_is_not_deleted_by_either_owner(self):
        path = self.directory / SOCKET_NAME
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as previous:
            previous.bind(str(path))
        before = path.lstat()
        for kind in (PrivateSessionOwner, PrivateListener):
            with self.assertRaisesRegex(FileExistsError, "socket path already exists"):
                kind(self.directory)
            after = path.lstat()
            self.assertEqual((after.st_dev, after.st_ino), (before.st_dev, before.st_ino))

    def test_foreign_marker_replacement_is_retained(self):
        owner = PrivateSessionOwner(self.directory)
        try:
            owner.begin_process_session(self.workspace)
            marker = self.directory / PROCESS_SESSION
            marker.rename(self.directory / "original-marker")
            marker.write_bytes(b"foreign-marker\n")
            with self.assertRaisesRegex(RuntimeError, "ownership changed"):
                owner.finish_process_session()
            self.assertEqual(marker.read_bytes(), b"foreign-marker\n")
            self.assertIsNotNone(owner.process_identity)
        finally:
            owner.close()

    def test_pinned_directory_survives_rename_without_touching_replacement(self):
        owner = PrivateSessionOwner(self.directory)
        moved = self.root / "moved-broker"
        try:
            owner.begin_process_session(self.workspace)
            self.directory.rename(moved)
            self.directory.mkdir(mode=0o700)
            replacement = self.directory / PROCESS_SESSION
            replacement.write_bytes(b"replacement-directory\n")
            self.assert_blocked_child(PrivateSessionOwner, moved)
            self.assert_blocked_child(PrivateListener, moved)
            owner.finish_process_session()
            self.assertFalse((moved / PROCESS_SESSION).exists())
            self.assertEqual(replacement.read_bytes(), b"replacement-directory\n")
        finally:
            owner.close()

    def test_listener_removes_only_its_own_socket_inode(self):
        owner = PrivateListener(self.directory)
        moved = self.directory / "original.sock"
        owner.path.rename(moved)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as replacement:
            replacement.bind(str(owner.path))
            before = owner.path.lstat()
            owner.close()
            after = owner.path.lstat()
            self.assertEqual((after.st_dev, after.st_ino), (before.st_dev, before.st_ino))

    def test_socket_path_limit_applies_only_to_listener_and_failed_listener_releases_lock(self):
        long_directory = self.directory / ("a" * 96)
        long_directory.mkdir(mode=0o700)
        with self.assertRaisesRegex(ValueError, "sockaddr_un"):
            PrivateListener(long_directory)
        owner = PrivateSessionOwner(long_directory)
        try:
            owner.begin_process_session(self.workspace)
            self.assertFalse((long_directory / SOCKET_NAME).exists())
            owner.finish_process_session()
        finally:
            owner.close()

    def test_directory_alias_and_nonprivate_modes_remain_refused(self):
        alias = self.root / "broker-alias"
        alias.symlink_to(self.directory, target_is_directory=True)
        for kind in (PrivateSessionOwner, PrivateListener):
            with self.assertRaisesRegex(ValueError, "aliases"):
                kind(alias)
        self.directory.chmod(0o755)
        for kind in (PrivateSessionOwner, PrivateListener):
            with self.assertRaisesRegex(PermissionError, "owned and private"):
                kind(self.directory)

    def test_symlink_and_hardlinked_locks_remain_refused(self):
        target = self.root / "foreign-lock"
        target.write_bytes(b"lock-owner\n")
        target.chmod(0o600)
        lock = self.directory / "broker.lock"
        lock.symlink_to(target)
        for kind in (PrivateSessionOwner, PrivateListener):
            with self.assertRaises(OSError):
                kind(self.directory)
            self.assertTrue(lock.is_symlink())
        lock.unlink()
        os.link(target, lock)
        for kind in (PrivateSessionOwner, PrivateListener):
            with self.assertRaisesRegex(PermissionError, "ownership lock"):
                kind(self.directory)
        self.assertEqual(target.read_bytes(), b"lock-owner\n")
        self.assertEqual(target.stat().st_nlink, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
