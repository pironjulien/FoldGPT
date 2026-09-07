"""Supervisor admission and namespace metadata; no GNU process is simulated."""
import fcntl
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.executor.native_executor_backend import NativeExecutorBackend
from gnu_executor_broker import configuration, parser


class GnuSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.assertNotEqual(os.getuid(), 0, "Run supervisor admission tests as an ordinary UID")
        self.temporary = tempfile.TemporaryDirectory(prefix="gconf-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.paths = {}
        for name in ("socket-dir", "workspace", "scratch", "guest-tmp"):
            value = self.root / name
            value.mkdir(mode=0o700)
            self.paths[name] = value
        (self.paths["workspace"] / ".home").mkdir(mode=0o700)
        # Real system ELF paths suffice for admission-only tests. These paths
        # are never executed as a helper/runner or reported as working ones.
        self.program = Path("/usr/bin/true").resolve(strict=True)
        options = {**self.paths, "rootfs": Path("/"), "peer-uid": os.getuid(),
                   **{name: self.program for name in
                      ("helper", "handle-helper", "process-runner", "proot", "loader", "loader32")}}
        self.args = parser().parse_args([str(token) for name, value in options.items()
                                       for token in ("--" + name, value)])

    def test_guest_metadata_and_snapshot_ignore_all_ambient_values(self):
        with patch.dict(os.environ, {"SHELL": "/system/bin/sh", "HOME": "/android/home",
                                     "TMPDIR": "/android/tmp", "API_KEY": "synthetic"}, clear=True):
            result = configuration(self.args)
        self.assertEqual(result["environment_info"], {
            "shell": {"name": "bash", "path": "/bin/bash"}, "cwd": "file:///workspace",
            "userHomeDir": "file:///workspace/.home", "platformOs": "linux",
            "temporaryDirectories": ["file:///tmp"], "tempDir": "file:///tmp"})
        self.assertEqual(result["process_config"]["parent_environment"], {
            "PATH": "/usr/bin:/bin", "HOME": "/workspace/.home", "TMPDIR": "/tmp",
            "SHELL": "/bin/bash", "LANG": "C.UTF-8"})
        self.assertEqual(result["process_config"]["process_factory"].keywords["guest_tmp"],
                         self.paths["guest-tmp"])

    def test_writable_and_ipc_root_overlap_is_refused_before_endpoint(self):
        for field in ("scratch", "guest_tmp", "socket_dir"):
            original = getattr(self.args, field)
            try:
                setattr(self.args, field, self.paths["workspace"])
                with self.assertRaisesRegex(ValueError, "disjoint"):
                    configuration(self.args)
            finally:
                setattr(self.args, field, original)
        self.assertFalse((self.paths["socket-dir"] / "exec.sock").exists())

    def test_private_home_and_nonmutable_runtime_are_required(self):
        home = self.paths["workspace"] / ".home"
        home.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "owned and private"):
            configuration(self.args)
        home.chmod(0o700)
        candidate = self.paths["workspace"] / "runtime"
        candidate.write_bytes(self.program.read_bytes())
        candidate.chmod(0o700)
        self.args.proot = candidate
        with self.assertRaisesRegex(ValueError, "cannot live"):
            configuration(self.args)

    def test_runtime_alias_and_missing_shell_are_refused(self):
        alias = self.root / "alias"
        alias.symlink_to(self.paths["scratch"], target_is_directory=True)
        self.args.scratch = alias
        with self.assertRaisesRegex(ValueError, "aliases"):
            configuration(self.args)
        self.args.scratch = self.paths["scratch"]
        empty_runtime = self.root / "empty-runtime"
        empty_runtime.mkdir(mode=0o700)
        self.args.rootfs = empty_runtime
        with self.assertRaises(FileNotFoundError):
            configuration(self.args)

    def test_guest_project_mapping_preserves_real_uri_spelling(self):
        self.args.guest_workspace = "/root/projets/essai é"
        result = configuration(self.args)
        self.assertEqual(result["guest_workspace"], self.args.guest_workspace)
        self.assertEqual(result["environment_info"]["cwd"], "file:///root/projets/essai%20%C3%A9")
        self.assertEqual(result["process_config"]["parent_environment"]["HOME"], "/root/projets/essai é/.home")

    def test_guest_mount_cannot_hide_or_reuse_a_runtime_tree(self):
        for path in ("/", "/usr", "/usr/project", "/tmp/p", "/proc/p", "/root//project", "/root/../usr", "/root/a:b", "/root/p!"):
            self.args.guest_workspace = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                configuration(self.args)

    def test_factory_constructor_failure_releases_the_file_lease(self):
        def fail(*args, **kwargs):
            self.assertNotIn("executables", kwargs)
            self.assertIn("parent_environment", kwargs)
            self.assertEqual(kwargs["files_backend"].mount.uri, "file:///workspace")
            raise ValueError("deliberate constructor failure")
        with self.assertRaisesRegex(ValueError, "deliberate"):
            NativeExecutorBackend(self.program, self.paths["workspace"], handle_helper=self.program,
                                  process_runner=self.program, process_factory=fail,
                                  parent_environment={"PATH": "/usr/bin:/bin"})
        fd = os.open(self.paths["workspace"], os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    def test_ambiguous_factory_configuration_is_rejected_before_files_open(self):
        with self.assertRaisesRegex(ValueError, "own its executable mapping"):
            NativeExecutorBackend(self.program, self.root / "absent", handle_helper=self.program,
                                  process_runner=self.program, process_factory=lambda: None,
                                  executables={"incorrect": self.program})


if __name__ == "__main__":
    unittest.main(verbosity=2)
