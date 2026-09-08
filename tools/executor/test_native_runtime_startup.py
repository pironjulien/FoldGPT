"""Actual nonroot filesystem/socket tests for trusted native startup inputs."""
import json
import errno
import os
from pathlib import Path
import socket
import tempfile
import unittest

from tools.executor.native_runtime_startup import (
    LAUNCH_SCHEMA, STARTUP_SCHEMA, StartupManifest, canonical_uri,
    private_directory, read_launch, read_private_json,
)


class NativeRuntimeStartupTests(unittest.TestCase):
    def setUp(self):
        self.assertNotEqual(os.getuid(), 0, "Run startup ownership tests as a real nonroot user")
        self.temp = tempfile.TemporaryDirectory(prefix="foldgpt-startup-",
            dir=os.environ.get("FOLDGPT_TEST_TMPDIR", "/var/tmp"))
        self.root = Path(self.temp.name)
        self.projects = self.root / "projects"
        self.broker = self.root / "broker"
        self.runtime = self.root / "runtime"
        for directory in (self.projects, self.broker, self.runtime):
            directory.mkdir(mode=0o700)
        self.workspace = self.projects / "actual-project"
        self.workspace.mkdir(mode=0o700)
        self.launch = self.broker / "launch.json"
        self.endpoint = self.broker / "owner.sock"
        self.path = self.broker / "startup.json"
        self.value = {"schema": LAUNCH_SCHEMA, "workspace": str(self.workspace),
            "socketPath": str(self.endpoint), "manifestPath": str(self.path),
            "controllerRoots": ["file:///home/foldgpt", "file:///tmp"]}
        self.write_launch(self.value)
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.listener.bind(str(self.endpoint))
        self.endpoint.chmod(0o600)
        self.directory = private_directory(self.broker, os.getuid())
        self.manifest = None

    def tearDown(self):
        if self.manifest is not None:
            self.manifest.close()
        os.close(self.directory)
        self.listener.close()
        self.temp.cleanup()

    def write_launch(self, value):
        self.launch.write_text(json.dumps(value), encoding="utf-8")
        self.launch.chmod(0o600)

    def admit(self):
        return read_launch(self.launch, uid=os.getuid(), broker_directory=self.broker,
                           projects_directory=self.projects)

    def publish(self, **overrides):
        values = {"socket_path": self.endpoint, "workspace": self.workspace,
            "shared_paths": [self.workspace, self.runtime],
            "controller_roots": self.value["controllerRoots"],
            "parent_environment": {"PATH": str(self.runtime), "HOME": str(self.workspace)},
            "directory_fd": self.directory}
        return StartupManifest(self.path, **dict(values, **overrides))

    def test_actual_identity_and_inode_manifest_is_exclusive_and_removable(self):
        self.assertEqual(self.admit(), self.value)
        self.manifest = self.publish()
        actual = read_private_json(self.path, os.getuid())
        self.assertEqual(actual, {"schema": STARTUP_SCHEMA, "socketPath": str(self.endpoint),
            "peer": {"pid": os.getpid(), "uid": os.getuid(), "gid": os.getgid()},
            "workspaceRoot": self.workspace.as_uri(), "controllerRoots": self.value["controllerRoots"],
            "parentEnvironment": {"PATH": str(self.runtime), "HOME": str(self.workspace)},
            "sharedPaths": [{"path": path.as_uri(), "device": path.stat().st_dev,
                              "inode": path.stat().st_ino} for path in (self.workspace, self.runtime)]})
        before = self.path.stat()
        with self.assertRaises(FileExistsError):
            self.publish()
        self.assertEqual((self.path.stat().st_dev, self.path.stat().st_ino), (before.st_dev, before.st_ino))
        self.manifest.remove()
        self.assertFalse(self.path.exists())

    def test_replaced_manifest_is_never_removed(self):
        self.manifest = self.publish()
        previous = self.broker / "previous-startup.json"
        self.path.rename(previous)
        self.path.write_bytes(b"different-owner")
        with self.assertRaises(ValueError):
            self.manifest.remove()
        self.assertEqual(self.path.read_bytes(), b"different-owner")
        self.assertTrue(previous.is_file())

    def test_launch_rejects_duplicate_and_unknown_fields(self):
        self.launch.write_bytes(b'{"schema":"foldgpt.native-launch.v1","schema":"foldgpt.native-launch.v1"}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.admit()
        self.write_launch(dict(self.value, backendFactory="foreign:factory"))
        with self.assertRaises(ValueError):
            self.admit()

    def test_private_input_identity_and_bounds_are_required(self):
        self.launch.chmod(0o644)
        with self.assertRaises(PermissionError):
            self.admit()
        self.launch.chmod(0o600)
        self.launch.write_bytes(b" " * 65537)
        with self.assertRaises(PermissionError):
            self.admit()
        self.write_launch(self.value)
        with self.assertRaises(PermissionError):
            read_private_json(self.launch, os.getuid() + 1)

    def test_alias_and_hardlinked_inputs_are_refused(self):
        alias = self.broker / "alias.json"
        alias.symlink_to(self.launch)
        with self.assertRaises(ValueError):
            read_private_json(alias, os.getuid())
        hard = self.broker / "hard.json"
        try:
            os.link(self.launch, hard)
        except PermissionError as error:
            # Android may forbid creating a hard link before an input exists
            # to admit. Keep this actual kernel result separate from proving
            # our nlink check on Unix hosts that permit hard-link creation.
            self.assertIn(error.errno, (errno.EACCES, errno.EPERM))
            self.assertFalse(hard.exists())
            self.assertEqual(self.launch.stat().st_nlink, 1)
            self.assertEqual(self.admit(), self.value)
            print(json.dumps({"observation": "hardlink_creation_denied_by_kernel",
                "errno": error.errno, "linkedInputAdmissionTested": False}), flush=True)
        else:
            self.assertEqual(self.launch.stat().st_nlink, 2)
            with self.assertRaises(PermissionError):
                self.admit()
            print(json.dumps({"observation": "hardlinked_input_refused",
                "linkedInputAdmissionTested": True}), flush=True)

    def test_workspace_escape_and_controller_overlap_are_refused(self):
        self.write_launch(dict(self.value, workspace=str(self.root)))
        with self.assertRaises(ValueError):
            self.admit()
        for root in (self.projects.as_uri(), self.workspace.as_uri(), (self.workspace / "child").as_uri()):
            self.write_launch(dict(self.value, controllerRoots=[root]))
            with self.assertRaises(ValueError):
                self.admit()
        self.write_launch(dict(self.value, controllerRoots=["file:///tmp", "file:///tmp"]))
        with self.assertRaises(ValueError):
            self.admit()

    def test_endpoint_and_manifest_are_fixed_outside_workspace(self):
        for field in ("socketPath", "manifestPath"):
            self.write_launch(dict(self.value, **{field: str(self.workspace / "input")}))
            with self.assertRaises(ValueError):
                self.admit()

    def test_actual_workspace_permissions_are_required(self):
        self.workspace.chmod(0o755)
        with self.assertRaises(PermissionError):
            self.admit()

    def test_shared_identity_must_cover_actual_workspace_without_aliases(self):
        with self.assertRaises(ValueError):
            self.publish(shared_paths=[self.runtime])
        with self.assertRaises(ValueError):
            self.publish(shared_paths=[self.workspace, self.workspace])
        alias = self.root / "runtime-alias"
        alias.symlink_to(self.runtime, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.publish(shared_paths=[self.workspace, alias])
        self.assertFalse(self.path.exists())

    def test_bound_endpoint_requires_private_socket_in_actual_pinned_directory(self):
        other = self.root / "other"
        other.mkdir(mode=0o700)
        foreign = private_directory(other, os.getuid())
        try:
            with self.assertRaises(ValueError):
                self.publish(directory_fd=foreign)
        finally:
            os.close(foreign)
        self.endpoint.chmod(0o666)
        with self.assertRaises(ValueError):
            self.publish()
        self.assertFalse(self.path.exists())

    def test_parent_environment_rejects_invalid_variables_without_publication(self):
        for invalid in ({"bad=key": "x"}, {"HOME": "bad\0value"}, {"PATH": None},
                        {str(index): "x" for index in range(129)}):
            with self.assertRaises(ValueError):
                self.publish(parent_environment=invalid)
        self.assertFalse(self.path.exists())

    def test_controller_uri_requires_exact_unambiguous_local_spelling(self):
        self.assertEqual(str(canonical_uri("file:///home/foldgpt")), "/home/foldgpt")
        for value in ("file://localhost/tmp", "file:///tmp/../private", "file:///tmp/", "file:///tmp?x",
                      "file:///%74mp", "file:///", "file:///tmp%2fchild", "file:///tmp%00"):
            with self.assertRaises(ValueError):
                canonical_uri(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
