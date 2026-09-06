"""Real publication and cleanup-boundary tests; never build or install a rootfs."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


if sys.platform == "linux":
    SPEC = importlib.util.spec_from_file_location("build_rootfs", Path(__file__).with_name("build_rootfs.py"))
    BUILD = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(BUILD)


@unittest.skipUnless(sys.platform == "linux", "Builder runs only on host Linux")
class PublicationTests(unittest.TestCase):
    def exercise(self, parent):
        with tempfile.TemporaryDirectory(prefix=".rootfs-publication-test-", dir=parent) as temporary:
            root = Path(temporary)
            source = root / "source"
            target = root / "published"
            source.mkdir()
            (source / "manifest.json").write_bytes(b"verified fixture")
            BUILD.publish_directory(source, target)
            self.assertFalse(source.exists())
            self.assertEqual((target / "manifest.json").read_bytes(), b"verified fixture")
            source.mkdir()
            (source / "manifest.json").write_bytes(b"replacement fixture")
            with self.assertRaises((FileExistsError, subprocess.CalledProcessError)):
                BUILD.publish_directory(source, target)
            self.assertEqual((target / "manifest.json").read_bytes(), b"verified fixture")
            self.assertEqual((source / "manifest.json").read_bytes(), b"replacement fixture")

    def test_linux_atomic_rename_preserves_existing_directory(self):
        self.exercise("/var/tmp")

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("python.exe")
                         and Path("/mnt/c/Dev/ChatgptFold/downloads/install").is_dir(),
                         "Requires WSL and native Windows Python for real NTFS publication")
    def test_native_windows_publish_preserves_existing_ntfs_directory(self):
        self.exercise("/mnt/c/Dev/ChatgptFold/downloads/install")


@unittest.skipUnless(sys.platform == "linux" and os.geteuid() == 0,
                     "Finalization safety checks require host Linux root")
class FinalizationBoundaryTests(unittest.TestCase):
    def fixture(self, work):
        root = work / "rootfs"
        root.mkdir()
        (work / "evidence").mkdir()
        (root / "dev").mkdir()
        return root

    def test_external_dev_symlink_is_refused_before_any_mutation(self):
        with tempfile.TemporaryDirectory(prefix="foldgpt-rootfs-test-", dir="/var/tmp") as temporary, \
                tempfile.TemporaryDirectory(prefix="foldgpt-outside-fixture-", dir="/var/tmp") as external:
            work = Path(temporary)
            root = self.fixture(work)
            sentinel = Path(external) / "keep.txt"
            sentinel.write_bytes(b"harmless outside fixture must survive")
            (root / "dev").rmdir()
            (root / "dev").symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "real directories"):
                BUILD.finish(work)
            self.assertTrue((root / "dev").is_symlink())
            self.assertEqual(sentinel.read_bytes(), b"harmless outside fixture must survive")
            self.assertEqual(list((work / "evidence").iterdir()), [])

    def test_writable_build_directories_are_refused_before_dev_cleanup(self):
        for relative in (".", "rootfs", "evidence", "rootfs/dev"):
            with self.subTest(directory=relative), \
                    tempfile.TemporaryDirectory(prefix="foldgpt-rootfs-test-", dir="/var/tmp") as temporary:
                work = Path(temporary)
                root = self.fixture(work)
                sentinel = root / "dev/keep.txt"
                sentinel.write_bytes(b"not yet cleaned")
                (work / relative).chmod(0o775)
                with self.assertRaisesRegex(ValueError, "not group/other writable"):
                    BUILD.finish(work)
                self.assertEqual(sentinel.read_bytes(), b"not yet cleaned")

    def test_non_root_owned_directories_are_refused_before_dev_cleanup(self):
        for relative in (".", "rootfs", "evidence", "rootfs/dev"):
            with self.subTest(directory=relative), \
                    tempfile.TemporaryDirectory(prefix="foldgpt-rootfs-test-", dir="/var/tmp") as temporary:
                work = Path(temporary)
                root = self.fixture(work)
                sentinel = root / "dev/keep.txt"
                sentinel.write_bytes(b"not yet cleaned")
                os.chown(work / relative, 65534, -1)
                with self.assertRaisesRegex(ValueError, "root-owned"):
                    BUILD.finish(work)
                self.assertEqual(sentinel.read_bytes(), b"not yet cleaned")


if __name__ == "__main__":
    unittest.main()
