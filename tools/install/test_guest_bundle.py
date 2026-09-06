"""Host regression tests; no Android calls, guest execution or model requests."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("guest_bundle", Path(__file__).with_name("guest_bundle.py"))
BUNDLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUNDLE)


def modified_archive(original, mutate):
    entries = []
    with tarfile.open(fileobj=io.BytesIO(original)) as archive:
        for item in archive:
            entries.append((item, archive.extractfile(item).read()))
    entries = mutate(entries)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for item, data in entries:
            archive.addfile(item, io.BytesIO(data))
    return output.getvalue()


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="foldgpt-bundle-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # Deliberate fixture sources; no host profile or existing rootfs is copied.
        for name in BUNDLE.SOURCES:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_bytes(("fixture for " + name + "\r\n").encode())
        self.data = BUNDLE.build(self.root)
        self.sha = hashlib.sha256(self.data).hexdigest()

    def reject(self, data):
        with self.assertRaises(ValueError):
            BUNDLE.verify(data, hashlib.sha256(data).hexdigest())

    def test_repeated_build_and_line_endings_produce_identical_bytes(self):
        self.assertEqual(self.data, BUNDLE.build(self.root))
        for name in BUNDLE.SOURCES:
            path = self.root / name
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
        self.assertEqual(self.data, BUNDLE.build(self.root))
        files = BUNDLE.verify(self.data, self.sha)
        self.assertEqual(len(files), 9)
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(manifest["format"], "foldgpt.guest-integration.v1")
        self.assertEqual(len(manifest["files"]), 8)

    def test_never_sweeps_private_or_binary_inputs(self):
        (self.root / "auth.json").write_text("private account fixture")
        (self.root / "chatgpt.deb").write_bytes(b"proprietary fixture")
        self.assertEqual(self.data, BUNDLE.build(self.root))

    def test_digest_is_required_and_compared_before_tar_parsing(self):
        for expected in ("", "0" * 64, self.sha.upper(), self.sha + "\n"):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                BUNDLE.verify(self.data, expected)
        changed = bytearray(self.data)
        changed[700] ^= 1
        with self.assertRaises(ValueError):
            BUNDLE.verify(bytes(changed), self.sha)

    def test_rejects_missing_and_duplicate_files(self):
        self.reject(modified_archive(self.data, lambda entries: entries[:-1]))
        self.reject(modified_archive(self.data, lambda entries: entries + entries[:1]))

    def test_rejects_escape_paths_and_link_types(self):
        for name in ("../escape", "/etc/ld.so.preload", "payload/../outside", "payload/home/auth.json"):
            def rename(entries):
                entries[0][0].name = name
                return entries
            with self.subTest(name=name):
                self.reject(modified_archive(self.data, rename))
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.DIRTYPE):
            def change_type(entries):
                entries[0][0].type = kind
                entries[0][0].linkname = "/outside"
                return entries
            with self.subTest(kind=kind):
                self.reject(modified_archive(self.data, change_type))

    def test_rejects_forged_permissions_and_manifest(self):
        def setuid(entries):
            entries[0][0].mode |= 0o4000
            return entries
        self.reject(modified_archive(self.data, setuid))

        def tamper_manifest(entries):
            result = []
            for item, data in entries:
                if item.name == "manifest.json":
                    data = data.replace(b'"guest-integration-only"', b'"complete-linux-installer"')
                    item.size = len(data)
                result.append((item, data))
            return result
        self.reject(modified_archive(self.data, tamper_manifest))

    def test_rejects_truncation_concatenation_and_hidden_trailing_data(self):
        for data in (self.data[:-1], self.data[:-1024], self.data + self.data,
                     self.data + b"private trailing bytes"):
            with self.subTest(size=len(data)):
                self.reject(data)

    def test_rejects_binary_or_unnormalized_content_even_with_matching_manifest(self):
        files = BUNDLE.verify(self.data, self.sha)
        files.pop("manifest.json")
        path = "payload/usr/local/bin/foldgpt-session"
        for invalid in (b"\x7fELF\0binary", b"\xffinvalid utf8", b"windows\r\n"):
            with self.subTest(content=invalid):
                self.reject(BUNDLE._archive({**files, path: invalid}))

    def test_output_publication_never_replaces_an_existing_file(self):
        output = self.root / "new.tar"
        BUNDLE.write_new_archive(output, self.data)
        with self.assertRaises(FileExistsError):
            BUNDLE.write_new_archive(output, b"replacement")
        self.assertEqual(output.read_bytes(), self.data)
        self.assertEqual(list(self.root.glob(".foldgpt-bundle-*")), [])

    @unittest.skipUnless(sys.platform == "linux", "Requires real Linux renameat2 and POSIX modes")
    def test_prepare_creates_verified_files_and_preserves_existing_destination(self):
        destination = self.root / "revision"
        BUNDLE.prepare(self.data, self.sha, destination)
        expected = BUNDLE.verify(self.data, self.sha)
        for name, data in expected.items():
            self.assertEqual((destination / name).read_bytes(), data)
            self.assertEqual(stat.S_IMODE((destination / name).stat().st_mode),
                             BUNDLE.MODES.get(name, 0o644))
        marker = destination / "preserve"
        marker.write_bytes(b"existing revision")
        with self.assertRaises(FileExistsError):
            BUNDLE.prepare(self.data, self.sha, destination)
        self.assertEqual(marker.read_bytes(), b"existing revision")
        self.assertEqual(list(self.root.glob(".foldgpt-stage-*")), [])

    @unittest.skipUnless(sys.platform == "linux", "Requires real Linux parent permissions")
    def test_rejects_shared_writable_parent_before_creating_stage_or_archive(self):
        parent = self.root / "shared"
        parent.mkdir()
        for mode in (0o777, 0o1777, 0o770):
            parent.chmod(mode)
            with self.subTest(mode=mode):
                with self.assertRaisesRegex(ValueError, "forbid group/other writes"):
                    BUNDLE.prepare(self.data, self.sha, parent / "revision")
                with self.assertRaisesRegex(ValueError, "forbid group/other writes"):
                    BUNDLE.write_new_archive(parent / "bundle.tar", self.data)
                self.assertEqual(list(parent.iterdir()), [])

    @unittest.skipUnless(sys.platform == "linux", "Requires real Linux fd-relative writes")
    def test_failed_write_leaves_no_destination_and_retry_succeeds(self):
        destination = self.root / "retry"
        original_write = os.write
        writes = 0

        def disk_failure(fd, data):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("Deliberate write failure")
            return original_write(fd, data)

        with patch.object(BUNDLE.os, "write", side_effect=disk_failure), self.assertRaises(OSError):
            BUNDLE.prepare(self.data, self.sha, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".foldgpt-stage-*")), [])
        BUNDLE.prepare(self.data, self.sha, destination)
        self.assertTrue((destination / "manifest.json").is_file())

    @unittest.skipUnless(sys.platform == "linux", "Requires real Linux symlinks")
    def test_rejects_source_and_destination_symlinks_without_following(self):
        source = self.root / "LICENSE"
        source.unlink()
        source.symlink_to(self.root / "foldgpt-session.sh")
        with self.assertRaises(ValueError):
            BUNDLE.build(self.root)
        outside = self.root / "outside"
        outside.mkdir()
        target = self.root / "target"
        target.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(FileExistsError):
            BUNDLE.prepare(self.data, self.sha, target)
        self.assertEqual(list(outside.iterdir()), [])
        with self.assertRaises(ValueError):
            BUNDLE.prepare(self.data, self.sha, target / "child")


if __name__ == "__main__":
    unittest.main()
