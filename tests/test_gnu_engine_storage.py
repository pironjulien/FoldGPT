"""Exercise the GNU builder against real native and Windows mounts in WSL."""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "gnu_engine_builder", PROJECT / "tools/executor/build-gnu-engine.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@unittest.skipUnless(sys.platform == "linux" and shutil.which("findmnt"),
                     "Requires Linux mount inspection")
class NativeBuildStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="gnu-storage-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def windows_path(self):
        path = Path("/mnt/c/Dev/ChatgptFold")
        if not path.is_dir():
            self.skipTest("Requires the project on WSL's Windows mount")
        return path

    def test_accepts_future_directory_on_native_mount(self):
        path = self.root / "future source" / "snapshot"
        record = builder.native_storage(path, "source", writable=True)
        self.assertEqual(record["path"], str(path.resolve()))
        self.assertFalse(path.exists(), "Storage inspection must not create files")

    def test_rejects_future_directory_on_windows_mount(self):
        with self.assertRaisesRegex(RuntimeError, "Windows/shared storage"):
            builder.native_storage(self.windows_path() / "work/future-build", "source")

    def test_rejects_linux_symlink_to_windows_mount(self):
        link = self.root / "apparently-native"
        link.symlink_to(self.windows_path(), target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "Windows/shared storage"):
            builder.native_storage(link / "future-build", "source")

    def test_prepare_rejects_windows_target_before_creating_snapshot(self):
        args = argparse.Namespace(build_root=self.root / "build",
                                  target_dir=self.windows_path() / "work/future-target")
        with self.assertRaisesRegex(RuntimeError, "--target-dir.*Windows/shared"):
            builder.prepare(args)
        self.assertFalse(args.build_root.exists())

    def test_prepare_rejects_windows_source_before_reading_export(self):
        args = argparse.Namespace(build_root=self.windows_path() / "work/future-build",
                                  target_dir=self.root / "target")
        with self.assertRaisesRegex(RuntimeError, "--build-root.*Windows/shared"):
            builder.prepare(args)
        self.assertFalse(args.target_dir.exists())

    def test_build_rechecks_target_before_validation_or_cargo(self):
        state = {"source": str(self.root), "build": str(self.root),
                 "targetDirectory": str(self.windows_path() / "work/future-target")}
        with self.assertRaisesRegex(RuntimeError, "Cargo target.*Windows/shared"):
            builder.build(argparse.Namespace(), state)

    def test_reports_unwritable_native_parent(self):
        if os.getuid() == 0:
            self.skipTest("Root bypasses ordinary directory permissions")
        directory = self.root / "root-owned-equivalent"
        directory.mkdir(mode=0o555)
        try:
            with self.assertRaisesRegex(RuntimeError, "not writable by the build user"):
                builder.native_storage(directory / "new-build", "source", writable=True)
        finally:
            directory.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
