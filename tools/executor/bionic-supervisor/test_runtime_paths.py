"""Real nonroot Linux FD/alias tests. The parent-stat guard is fault injection,
not a reproduction or attestation of Samsung's SELinux policy.
"""
import asyncio
import errno
import importlib
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
paths = importlib.import_module("tools.executor.bionic-supervisor.runtime_paths")
Policy = importlib.import_module("tools.executor.bionic-supervisor.policy").Policy
Processes = importlib.import_module("tools.executor.bionic-supervisor.processes").Processes
kernel = importlib.import_module("tools.executor.bionic-supervisor.test_kernel")
from tools.executor.native_files import NativeFilesBackend

BUILD = Path(sys.argv.pop(1)).resolve(strict=True)


class RuntimePathTests(unittest.TestCase):
    def setUp(self):
        self.assertNotEqual(os.getuid(), 0)
        self.temporary = tempfile.TemporaryDirectory(prefix="foldgpt-runtime-paths-", dir="/var/tmp")
        self.base = Path(self.temporary.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir(mode=0o700)
        (self.workspace / "private").mkdir(mode=0o700)
        (self.workspace / "private/secret").write_bytes(b"workspace only")
        self.external = self.base / "runtime"
        self.external.mkdir()
        self.file = self.external / "ld.config.txt"
        self.file.write_bytes(b"real fixture")
        self.alias = self.base / "runtime-alias"
        self.alias.symlink_to(self.external, target_is_directory=True)
        self.files = NativeFilesBackend(BUILD / "native-files", self.workspace,
                                        guest_workspace=str(self.workspace))
        self.before = set(os.listdir("/proc/self/fd"))

    def tearDown(self):
        self.assertEqual(set(os.listdir("/proc/self/fd")), self.before)
        asyncio.run(self.files.close("resolver"))
        self.temporary.cleanup()

    def processes(self, runtime):
        return Processes(BUILD / "runner", self.workspace, runtime=[(str(runtime), False)],
                         executables={"true": "/usr/bin/true"}, files_backend=self.files,
                         guest_workspace=str(self.workspace))

    def policy(self, denial=None):
        context = kernel.context(self.workspace)
        if denial is not None:
            context["permissions"]["file_system"]["entries"].append(
                {"path": {"type": "path", "path": denial.as_uri()}, "access": "deny"})
        return Policy(self.files, context, context["cwd"], session="resolver", request="1")

    def test_01_ordinary_file_directory_and_borrowed_cloexec_fd(self):
        for path in (self.file, self.external):
            self.assertEqual(paths.runtime_spellings(path), (str(path), str(path)))
            fd = paths._pin(str(path))
            try:
                self.assertFalse(os.get_inheritable(fd))
                self.assertEqual(paths.descriptor_path(fd), str(path))
                os.fstat(fd)  # descriptor_path never closes its caller's FD.
            finally:
                os.close(fd)

    def test_02_allowed_external_alias_and_real_factory_admission(self):
        link = self.alias / self.file.name
        self.assertEqual(paths.runtime_spellings(link), (str(link), str(self.file)))
        self.assertEqual(self.processes(self.alias).runtime, ((str(self.alias), False),))
        self.policy().require_runtime([(str(self.alias), False)])

    def test_03_workspace_direct_descendant_and_ancestor_aliases_refused(self):
        for index, target in enumerate((self.workspace, self.workspace / "private/secret", self.base)):
            alias = self.base / f"forbidden-{index}"
            alias.symlink_to(target)
            for path in (target, alias):
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, "physically overlap"):
                    self.processes(path)

    def test_04_lexical_workspace_alias_to_external_still_refused(self):
        link = self.workspace / "escape"
        link.symlink_to(self.external)
        with self.assertRaisesRegex(ValueError, "physically overlap"):
            self.processes(link)

    def test_05_policy_denies_both_lexical_and_physical_alias_spellings(self):
        for denial in (self.alias, self.alias / self.file.name, self.external, self.file):
            with self.subTest(denial=denial), self.assertRaisesRegex(PermissionError, "Explicit policy denial"):
                self.policy(denial).require_runtime([(str(self.alias), False)])

    def test_06_parent_lstat_fault_does_not_move_to_runtime_policy(self):
        # All FDs/files are real. Only this Python metadata call is denied;
        # Linux DAC cannot recreate Samsung's distinct parent getattr denial.
        original = os.lstat
        def denied_parent(path, *args, **kwargs):
            if os.fspath(path) == str(self.external):
                raise PermissionError(errno.EACCES, "injected parent getattr denial", str(path))
            return original(path, *args, **kwargs)
        policy = self.policy()
        with patch.object(os, "lstat", denied_parent):
            with self.assertRaises(PermissionError):
                self.file.resolve(strict=True)
            self.processes(self.file)
            policy.require_runtime([(str(self.file), False)])

    def test_07_missing_dangling_and_symlink_loop_fail_closed(self):
        missing = self.external / "missing"
        dangling = self.external / "dangling"
        dangling.symlink_to(missing)
        loop = self.external / "loop"
        loop.symlink_to(loop)
        for path, error in ((missing, errno.ENOENT), (dangling, errno.ENOENT), (loop, errno.ELOOP)):
            with self.subTest(path=path), self.assertRaises(OSError) as raised:
                paths.runtime_spellings(path)
            self.assertEqual(raised.exception.errno, error)

    def test_08_closed_descriptor_reports_ebadf(self):
        fd = paths._pin(str(self.file))
        os.close(fd)
        with self.assertRaises(OSError) as raised:
            paths.descriptor_path(fd)
        self.assertEqual(raised.exception.errno, errno.EBADF)

    def test_09_deleted_fd_and_real_deleted_suffix_name_refused(self):
        fd = paths._pin(str(self.file))
        self.file.unlink()
        self.file.write_bytes(b"different inode")
        try:
            with self.assertRaises(ValueError):
                paths.descriptor_path(fd)
        finally:
            os.close(fd)
        ambiguous = self.external / "value (deleted)"
        ambiguous.write_bytes(b"actual legal but ambiguous name")
        with self.assertRaises(ValueError):
            paths.runtime_spellings(ambiguous)

    def test_10_rename_resolves_actual_descriptor_not_replacement(self):
        fd = paths._pin(str(self.file))
        moved = self.external / "moved"
        self.file.rename(moved)
        self.file.write_bytes(b"replacement")
        try:
            self.assertEqual(paths.descriptor_path(fd), str(moved))
            self.assertNotEqual(os.fstat(fd).st_ino, self.file.stat().st_ino)
        finally:
            os.close(fd)

    def test_11_ambiguous_input_is_rejected_without_normalization(self):
        for path in ("relative", "//usr", str(self.file) + "/", str(self.external) + "/./ld.config.txt",
                     str(self.external) + "/../runtime/ld.config.txt", str(self.file) + "\n", "/a\0b", "/\udcff"):
            with self.subTest(path=repr(path)), self.assertRaises((ValueError, UnicodeError)):
                paths.runtime_spellings(path)

    def test_12_magic_links_direct_and_hidden_behind_ordinary_link_refused(self):
        fd = paths._pin(str(self.file))
        magic = f"/proc/self/fd/{fd}"
        hidden = self.external / "hidden-magic"
        hidden.symlink_to(magic)
        try:
            for path in (magic, hidden):
                with self.subTest(path=path), self.assertRaises(OSError) as raised:
                    paths.runtime_spellings(path)
                self.assertEqual(raised.exception.errno, errno.ELOOP)
        finally:
            os.close(fd)

    def test_13_fifo_and_socket_are_not_runtime_objects(self):
        fifo = self.external / "fifo"
        os.mkfifo(fifo)
        with socket.socket(socket.AF_UNIX) as endpoint:
            sock = self.external / "socket"
            endpoint.bind(str(sock))
            for path in (fifo, sock):
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, "ordinary"):
                    paths.runtime_spellings(path)

    def test_14_actual_search_permission_denial_is_not_ignored(self):
        self.external.chmod(0)
        try:
            with self.assertRaises(PermissionError):
                paths.runtime_spellings(self.file)
        finally:
            self.external.chmod(0o700)

    def test_15_actual_alias_retarget_during_admission_is_estale(self):
        original = paths.descriptor_path
        def retarget(fd):
            physical = original(fd)
            self.alias.unlink()
            self.alias.symlink_to(self.workspace, target_is_directory=True)
            return physical
        # Schedule an actual namespace change between the two real openat2
        # operations. No syscall result or object identity is fabricated.
        with patch.object(paths, "descriptor_path", retarget):
            with self.assertRaises(OSError) as raised:
                paths.runtime_spellings(self.alias)
        self.assertEqual(raised.exception.errno, errno.ESTALE)

    def test_16_returned_physical_name_cannot_be_replaced_by_a_symlink(self):
        fd = paths._pin(str(self.file))
        original = paths._pin
        moved = self.external / "moved-while-resolving"
        def replace_name(path, *, canonical=False):
            if canonical:
                self.file.rename(moved)
                self.file.symlink_to(moved)
            return original(path, canonical=canonical)
        try:
            with patch.object(paths, "_pin", replace_name):
                with self.assertRaises(OSError) as raised:
                    paths.descriptor_path(fd)
            self.assertEqual(raised.exception.errno, errno.ELOOP)
            os.fstat(fd)
        finally:
            os.close(fd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
