"""Actual Linux filesystem operations, including injected concurrent changes."""
import hashlib
import errno
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).with_name("relocate.py")
spec = importlib.util.spec_from_file_location("legacy_relocate", MODULE)
relocate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relocate)


class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.assertNotEqual(os.geteuid(), 0)
        test_root = Path(os.environ["FOLDGPT_LEGACY_TEST_ROOT"]).resolve(strict=True)
        project = MODULE.resolve().parents[3]
        self.assertTrue(test_root.is_relative_to(project))
        self.temp = tempfile.TemporaryDirectory(prefix="case-", dir=test_root)
        self.base = Path(self.temp.name)
        self.source = self.base / "legacy"
        self.target = self.base / "projects"
        self.source.mkdir()
        self.target.mkdir()
        (self.source / "folder").mkdir()
        (self.source / "empty").mkdir()
        (self.source / "folder/data.bin").write_bytes(bytes(range(256)) * 8)
        (self.source / "note.txt").write_text("héritage\n", encoding="utf-8")
        self.fds = set(os.listdir("/proc/self/fd"))

    def tearDown(self):
        self.assertEqual(set(os.listdir("/proc/self/fd")), self.fds)
        # Only this test-created directory is deleted; source fixtures and stages
        # are never production directories and unlinking links never follows them.
        self.assertTrue(self.base.resolve().is_relative_to(Path(os.environ["FOLDGPT_LEGACY_TEST_ROOT"]).resolve()))
        self.temp.cleanup()

    def inventory(self):
        return relocate.inventory(str(self.source), str(self.base))

    def copy(self, expected=None):
        return relocate.copy_project(str(self.source), str(self.base), str(self.target), "imported",
                                     expected or self.inventory()["inventorySha256"])

    def test_inventory_is_stable_and_hashes_real_binary_content(self):
        first = self.inventory()
        self.assertEqual(first, self.inventory())
        data = next(e for e in first["entries"] if e["path"] == "folder/data.bin")
        self.assertEqual(data["sha256"], hashlib.sha256((self.source / data["path"]).read_bytes()).hexdigest())
        self.assertEqual(first["fileCount"], 2)

    def test_copy_preserves_bytes_source_and_empty_directories(self):
        before = self.inventory()
        receipt = self.copy(before["inventorySha256"])
        self.assertEqual(before, self.inventory())
        self.assertEqual(receipt["contentSha256"], before["contentSha256"])
        copied = relocate.inventory(receipt["destination"], str(self.target))
        self.assertEqual(copied["contentSha256"], before["contentSha256"])
        self.assertTrue((self.target / "imported/empty").is_dir())
        self.assertFalse(receipt["sourceDeleted"])
        self.assertFalse(receipt["threadMetadataChanged"])

    def test_search_only_ancestor_preserves_real_copy_and_link_rejection(self):
        alias = self.base / 'alias'
        alias.symlink_to(self.source, target_is_directory=True)
        self.base.chmod(0o100)
        try:
            with self.assertRaises(PermissionError):
                os.listdir(self.base)
            before = self.inventory()
            receipt = self.copy(before['inventorySha256'])
            self.assertEqual(receipt['contentSha256'], before['contentSha256'])
            with self.assertRaises(OSError):
                relocate.inventory(str(alias), str(self.base))
        finally:
            self.base.chmod(0o700)

    def test_existing_directory_is_never_replaced(self):
        (self.target / "imported").mkdir()
        with self.assertRaisesRegex(relocate.Refused, "already exists"):
            self.copy()
        self.assertEqual(list(self.target.iterdir()), [self.target / "imported"])

    def test_existing_file_is_never_replaced(self):
        (self.target / "imported").write_bytes(b"existing")
        with self.assertRaises(relocate.Refused):
            self.copy()
        self.assertEqual((self.target / "imported").read_bytes(), b"existing")

    def test_stale_reviewed_inventory_refuses_before_staging(self):
        before = self.inventory()
        (self.source / "note.txt").write_bytes(b"changed")
        with self.assertRaisesRegex(relocate.Refused, "reviewed inventory"):
            self.copy(before["inventorySha256"])
        self.assertEqual(list(self.target.iterdir()), [])

    def test_added_file_invalidates_reviewed_inventory(self):
        before = self.inventory()
        (self.source / "new").write_bytes(b"new")
        with self.assertRaises(relocate.Refused):
            self.copy(before["inventorySha256"])
        self.assertEqual(list(self.target.iterdir()), [])

    def test_symlink_file_is_refused(self):
        outside = self.base / "outside"
        outside.write_bytes(b"outside")
        (self.source / "link").symlink_to(outside)
        with self.assertRaisesRegex(relocate.Refused, "Symlink"):
            self.inventory()
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_symlink_in_root_path_is_refused(self):
        alias = self.base / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(OSError):
            relocate.inventory(str(alias), str(self.base))

    def test_hardlink_is_refused(self):
        os.link(self.source / "note.txt", self.source / "linked")
        with self.assertRaisesRegex(relocate.Refused, "hardlink"):
            self.inventory()

    def test_fifo_is_refused_without_opening(self):
        os.mkfifo(self.source / "fifo")
        with self.assertRaisesRegex(relocate.Refused, "special file"):
            self.inventory()

    def test_overlapping_roots_are_refused(self):
        with self.assertRaisesRegex(relocate.Refused, "disjoint"):
            relocate.copy_project(str(self.source), str(self.base), str(self.source), "copy", "0" * 64)

    def test_textual_prefix_is_not_a_boundary(self):
        with self.assertRaisesRegex(relocate.Refused, "outside"):
            relocate.inventory(str(self.source), str(self.base / "leg"))

    def test_destination_name_traversal_is_refused(self):
        for name in ("../escape", "folder/name", ".", "", ".."):
            with self.subTest(name=name), self.assertRaises(relocate.Refused):
                relocate.copy_project(str(self.source), str(self.base), str(self.target), name, "0" * 64)

    def test_collision_created_at_publish_keeps_both_trees(self):
        publish = relocate.publish_noreplace
        def collide(parent, stage, target):
            os.mkdir(target, dir_fd=parent)
            (self.target / target / "sentinel").write_bytes(b"concurrent")
            return publish(parent, stage, target)
        with patch.object(relocate, "publish_noreplace", collide), self.assertRaises(relocate.Refused) as caught:
            self.copy()
        self.assertEqual((self.target / "imported/sentinel").read_bytes(), b"concurrent")
        self.assertTrue(Path(caught.exception.retained_stage).is_dir())
        self.assertTrue((self.source / "note.txt").exists())

    def test_source_changed_after_copy_is_not_published(self):
        original = relocate.inspect_tree
        def mutate(descriptor, *, copy_fd=None):
            result = original(descriptor, copy_fd=copy_fd)
            if copy_fd is not None:
                (self.source / "note.txt").write_bytes(b"concurrent source write")
            return result
        with patch.object(relocate, "inspect_tree", mutate), self.assertRaisesRegex(relocate.Refused, "Source changed") as caught:
            self.copy()
        self.assertFalse((self.target / "imported").exists())
        self.assertTrue(Path(caught.exception.retained_stage).is_dir())

    def test_unavailable_noreplace_never_falls_back_to_rename(self):
        with patch.object(relocate.ctypes, "CDLL", return_value=object()), self.assertRaisesRegex(relocate.Refused, "renameat2") as caught:
            self.copy()
        self.assertFalse((self.target / "imported").exists())
        self.assertTrue(Path(caught.exception.retained_stage).is_dir())

    def test_metadata_like_files_are_only_copied(self):
        original = b'{"cwd":"/old/project","message":"historical path"}\n'
        (self.source / "rollout.jsonl").write_bytes(original)
        self.copy()
        self.assertEqual((self.source / "rollout.jsonl").read_bytes(), original)
        self.assertEqual((self.target / "imported/rollout.jsonl").read_bytes(), original)

    def test_publication_os_error_preserves_errno_and_stage(self):
        with patch.object(relocate, "publish_noreplace", side_effect=OSError(errno.ENOSYS, "not available")), self.assertRaises(relocate.Refused) as caught:
            self.copy()
        self.assertEqual(caught.exception.errno, errno.ENOSYS)
        self.assertFalse(caught.exception.published)
        self.assertTrue(Path(caught.exception.retained_stage).is_dir())
        self.assertFalse((self.target / "imported").exists())

    def test_change_after_publication_reports_failure_without_deletion(self):
        publish = relocate.publish_noreplace
        def mutate(parent, stage, target):
            publish(parent, stage, target)
            (self.target / target / "note.txt").write_bytes(b"concurrent published write")
        with patch.object(relocate, "publish_noreplace", mutate), self.assertRaisesRegex(relocate.Refused, "Published content") as caught:
            self.copy()
        self.assertTrue(caught.exception.published)
        self.assertEqual(Path(caught.exception.retained_stage), self.target / "imported")
        self.assertEqual((self.target / "imported/note.txt").read_bytes(), b"concurrent published write")
        self.assertEqual((self.source / "note.txt").read_text(encoding="utf-8"), "héritage\n")

    def test_failed_parent_fsync_reports_that_publication_already_happened(self):
        publish = relocate.publish_noreplace
        sync = relocate.os.fsync
        published_parent = []
        def record_publish(parent, stage, target):
            publish(parent, stage, target)
            published_parent.append(parent)
        def fail_parent_sync(descriptor):
            if published_parent and descriptor == published_parent[0]:
                raise OSError(errno.EIO, "injected directory sync failure")
            return sync(descriptor)
        with patch.object(relocate, "publish_noreplace", record_publish), patch.object(relocate.os, "fsync", fail_parent_sync), self.assertRaises(relocate.Refused) as caught:
            self.copy()
        self.assertTrue(caught.exception.published)
        self.assertEqual(caught.exception.errno, errno.EIO)
        self.assertTrue((self.target / "imported/note.txt").is_file())
        self.assertTrue((self.source / "note.txt").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
