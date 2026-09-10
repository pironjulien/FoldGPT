"""Debian source metadata regression tests; no network, guest or account access."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("rootfs_sources", Path(__file__).with_name("rootfs_sources.py"))
SOURCES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCES)


class SourceIdentityTests(unittest.TestCase):
    def identity(self, package="binary-package", version="1.2.3-4", source=""):
        return SOURCES.source_identity({"package": package, "version": version, "source": source})

    def test_empty_source_uses_binary_name_and_exact_version(self):
        self.assertEqual(self.identity("apt", "3.0.3", ""), ("apt", "3.0.3"))
        self.assertEqual(self.identity("example", "2:1.0~rc1-2", ""),
                         ("example", "2:1.0~rc1-2"))

    def test_name_only_source_preserves_binary_version(self):
        self.assertEqual(self.identity("at-spi2-common", "2.56.2-1+deb13u1", "at-spi2-core"),
                         ("at-spi2-core", "2.56.2-1+deb13u1"))
        self.assertEqual(self.identity("example-bin", "3:1.2-4+b2", "example-source"),
                         ("example-source", "3:1.2-4+b2"))

    def test_explicit_source_version_overrides_binnmu_binary_version(self):
        self.assertEqual(self.identity("bash", "5.2.37-2+b9", "bash (5.2.37-2)"),
                         ("bash", "5.2.37-2"))

    def test_binary_epoch_is_not_invented_in_explicit_source_version(self):
        # This exact relationship occurs in the actual pristine rootfs inventory.
        self.assertEqual(self.identity("bsdutils", "1:2.41.5-0+deb13u1", "util-linux (2.41.5-0+deb13u1)"),
                         ("util-linux", "2.41.5-0+deb13u1"))

    def test_explicit_source_epoch_and_revision_remain_exact(self):
        self.assertEqual(self.identity("example-bin", "9:2.0-3+b1", "example-source (2:1.9~rc2+dfsg-7)"),
                         ("example-source", "2:1.9~rc2+dfsg-7"))

    def test_rejects_malformed_source_field(self):
        invalid = (
            "example-source ()", "example-source (1.0", "example-source 1.0)",
            "example-source (1.0) trailing", "example-source (1.0) (2.0)",
            "example-source (1.0 2.0)", "example-source (1.0/2)",
            "../example-source", "path/example-source", "example@source",
        )
        for source in invalid:
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.identity(source=source)


class Deb822Tests(unittest.TestCase):
    def test_separate_stanzas_and_colons_in_values(self):
        text = ("Package: alpha\nVersion: 1:2.0-3\nVcs-Git: https://example.invalid/repo:tag\n\n"
                "Package: beta\nVersion: 4.0\n\n")
        self.assertEqual(SOURCES.parse_deb822(text), [
            {"Package": "alpha", "Version": "1:2.0-3", "Vcs-Git": "https://example.invalid/repo:tag"},
            {"Package": "beta", "Version": "4.0"},
        ])

    def test_continuations_remove_exactly_one_initial_whitespace(self):
        text = ("Package: alpha\nDescription: first line\n second line\n  indented line\n"
                "\ttab continuation\n .\n last line\n")
        self.assertEqual(SOURCES.parse_deb822(text)[0]["Description"],
                         "first line\nsecond line\n indented line\ntab continuation\n.\nlast line")

    def test_blank_input_and_multiple_blank_lines(self):
        self.assertEqual(SOURCES.parse_deb822("\n\n"), [])
        self.assertEqual(SOURCES.parse_deb822("\nPackage: alpha\n\n\n"), [{"Package": "alpha"}])

    def test_crlf_has_no_carriage_returns_in_values(self):
        text = "Package: alpha\r\nDescription: first\r\n continuation\r\n\r\n"
        self.assertEqual(SOURCES.parse_deb822(text),
                         [{"Package": "alpha", "Description": "first\ncontinuation"}])

    def test_duplicate_field_is_rejected_even_if_values_match(self):
        # Deb822 field names are case-insensitive; a spelling change must not
        # turn a duplicate into an independently interpreted field.
        for text in ("Package: alpha\nPackage: alpha\n", "Package: alpha\nVersion: 1\nVersion: 2\n",
                     "Package: alpha\npackage: beta\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                SOURCES.parse_deb822(text)

    def test_same_field_in_different_stanzas_is_valid(self):
        self.assertEqual(SOURCES.parse_deb822("Package: alpha\n\nPackage: beta\n"),
                         [{"Package": "alpha"}, {"Package": "beta"}])

    def test_orphan_continuation_and_missing_colon_are_rejected(self):
        for text in (" orphan continuation\n", "Package alpha\n", "Package: alpha\n\n orphan\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                SOURCES.parse_deb822(text)


class SourceFilesTests(unittest.TestCase):
    HASH_A = "0123456789abcdef" * 4
    HASH_B = "fedcba9876543210" * 4

    def files(self, *lines):
        return SOURCES.source_files({"Checksums-Sha256": "\n" + "\n".join(lines)})

    def test_all_source_components_are_returned_with_integer_sizes(self):
        records = self.files(
            f"{self.HASH_A} 1024 example_1.2-3.dsc",
            f"{self.HASH_B} 4096 example_1.2.orig.tar.xz",
            f"{self.HASH_A} 512 example_1.2.orig-data.tar.xz",
            f"{self.HASH_B} 256 example_1.2-3.debian.tar.xz",
        )
        self.assertCountEqual(records, [
            {"name": "example_1.2-3.dsc", "bytes": 1024, "sha256": self.HASH_A},
            {"name": "example_1.2.orig.tar.xz", "bytes": 4096, "sha256": self.HASH_B},
            {"name": "example_1.2.orig-data.tar.xz", "bytes": 512, "sha256": self.HASH_A},
            {"name": "example_1.2-3.debian.tar.xz", "bytes": 256, "sha256": self.HASH_B},
        ])
        self.assertTrue(all(type(record["bytes"]) is int for record in records))

    def test_deb822_checksum_continuations_feed_the_file_parser(self):
        text = ("Package: example\nChecksums-Sha256:\n"
                f" {self.HASH_A} 123 example_1.0.dsc\n"
                f" {self.HASH_B} 456 example_1.0.tar.xz\n\n")
        records = SOURCES.source_files(SOURCES.parse_deb822(text)[0])
        self.assertCountEqual(records, [
            {"name": "example_1.0.dsc", "bytes": 123, "sha256": self.HASH_A},
            {"name": "example_1.0.tar.xz", "bytes": 456, "sha256": self.HASH_B},
        ])

    def test_path_traversal_absolute_paths_and_separators_are_rejected(self):
        for name in ("../escape", "/absolute", "path/file.dsc", "./file.dsc", "..", ".",
                     "..\\escape", "path\\file.dsc"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.files(f"{self.HASH_A} 123 {name}")

    def test_duplicate_filenames_are_rejected_with_equal_or_different_metadata(self):
        for second in (f"{self.HASH_A} 123 example.dsc", f"{self.HASH_B} 456 example.dsc"):
            with self.subTest(second=second), self.assertRaises(ValueError):
                self.files(f"{self.HASH_A} 123 example.dsc", second)

    def test_malformed_checksums_are_rejected(self):
        for checksum in ("0" * 63, "0" * 65, "g" * 64, "sha256:" + self.HASH_A):
            with self.subTest(checksum=checksum), self.assertRaises(ValueError):
                self.files(f"{checksum} 123 example.dsc")

    def test_nonpositive_and_nonnumeric_sizes_are_rejected(self):
        for size in ("0", "-1", "-999999", "1.5", "many"):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.files(f"{self.HASH_A} {size} example.dsc")

    def test_missing_or_empty_checksum_field_is_rejected(self):
        for stanza in ({}, {"Checksums-Sha256": ""}, {"Checksums-Sha256": "\n\n"}):
            with self.subTest(stanza=stanza), self.assertRaises(ValueError):
                SOURCES.source_files(stanza)

    def test_missing_or_extra_checksum_columns_are_rejected(self):
        for line in (f"{self.HASH_A} 123", f"{self.HASH_A} 123 example.dsc extra"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                self.files(line)


class SourceSelectionTests(unittest.TestCase):
    def setUp(self):
        self.binary = {"package": "example-bin", "version": "2:1.0-1+b3",
                       "source": "example-source (1.0-1)"}
        self.lines = ["0" * 64 + " 123 example-source_1.0-1.dsc",
                      "1" * 64 + " 456 example-source_1.0.orig.tar.xz"]
        self.stanza = {"Package": "example-source", "Version": "1.0-1",
                       "Directory": "pool/main/e/example-source",
                       "Checksums-Sha256": "\n".join(self.lines)}

    def select(self, *stanzas):
        return SOURCES.select_sources([self.binary],
                                      [("trixie", "https://example.invalid", list(stanzas))])

    def test_selects_exact_source_version_not_newer_binary_candidate(self):
        newer = {**self.stanza, "Version": "2.0-1"}
        selected = self.select(newer, self.stanza)
        self.assertEqual(len(selected), 1)
        self.assertEqual((selected[0]["package"], selected[0]["version"]), ("example-source", "1.0-1"))
        with self.assertRaises(ValueError):
            self.select(newer)

    def test_equivalent_file_sets_from_multiple_indexes_are_order_independent(self):
        reordered = {**self.stanza, "Checksums-Sha256": "\n".join(reversed(self.lines))}
        self.assertEqual(len(self.select(self.stanza, reordered)), 1)

    def test_same_source_version_with_conflicting_hashes_is_rejected(self):
        conflicting = {**self.stanza, "Checksums-Sha256": "\n".join(self.lines).replace("1" * 64, "2" * 64)}
        with self.assertRaises(ValueError):
            self.select(self.stanza, conflicting)

    def test_unsafe_directory_and_missing_or_multiple_descriptors_rejected(self):
        for directory in ("../pool/main/e/example", "/pool/main/e/example", "pool/../escape", "pool\\escape"):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                self.select({**self.stanza, "Directory": directory})
        for checksum_lines in ([self.lines[1]], self.lines + ["3" * 64 + " 17 duplicate.dsc"]):
            with self.subTest(lines=checksum_lines), self.assertRaises(ValueError):
                self.select({**self.stanza, "Checksums-Sha256": "\n".join(checksum_lines)})


class DescriptorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="foldgpt-descriptor-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.record = {"package": "example-source", "version": "2:1.0-1", "files": [
            {"name": "example-source_1.0-1.dsc", "bytes": 99, "sha256": "0" * 64},
            {"name": "example-source_1.0.orig.tar.xz", "bytes": 123, "sha256": "1" * 64},
            {"name": "example-source_1.0-1.debian.tar.xz", "bytes": 456, "sha256": "2" * 64},
        ]}
        self.text = ("Format: 3.0 (quilt)\nSource: example-source\nVersion: 2:1.0-1\n"
                     "Checksums-Sha256:\n " + "1" * 64 + " 123 example-source_1.0.orig.tar.xz\n "
                     + "2" * 64 + " 456 example-source_1.0-1.debian.tar.xz\n")

    def validate(self, text):
        (self.directory / self.record["files"][0]["name"]).write_text(text)
        return SOURCES.validate_descriptor(self.directory, self.record)

    def test_descriptor_identity_and_every_source_component_match_index(self):
        self.validate(self.text)
        armor = ("-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n" + self.text
                 + "-----BEGIN PGP SIGNATURE-----\nfixture retained signature\n-----END PGP SIGNATURE-----\n")
        # This function cross-checks already authenticated bytes. It must not
        # invent separate trust in this deliberately non-cryptographic fixture.
        self.validate(armor)

    def test_mismatched_source_name_or_version_rejected(self):
        for text in (self.text.replace("Source: example-source", "Source: other-source"),
                     self.text.replace("Version: 2:1.0-1", "Version: 1.0-1")):
            with self.subTest(text=text[:40]), self.assertRaises(ValueError):
                self.validate(text)

    def test_missing_extra_or_modified_component_rejected(self):
        variants = (
            self.text.replace(" " + "1" * 64 + " 123 example-source_1.0.orig.tar.xz\n", ""),
            self.text + " " + "3" * 64 + " 17 unlisted.orig-data.tar.xz\n",
            self.text.replace("1" * 64, "f" * 64),
            self.text.replace(" 123 ", " 124 "),
        )
        for text in variants:
            with self.subTest(text=text[-80:]), self.assertRaises(ValueError):
                self.validate(text)


class ArchiveReadTests(unittest.TestCase):
    def archive(self, entries):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as archive:
            for name, kind, payload in entries:
                member = tarfile.TarInfo(name)
                member.type = kind
                if kind == tarfile.REGTYPE:
                    member.size = len(payload)
                    archive.addfile(member, io.BytesIO(payload))
                else:
                    member.linkname = payload
                    archive.addfile(member)
        archive = tarfile.open(fileobj=io.BytesIO(output.getvalue()), mode="r:")
        self.addCleanup(archive.close)
        return archive, SOURCES.archive_members(archive)

    def test_guest_absolute_and_relative_links_resolve_without_host_extraction(self):
        archive, members = self.archive([
            ("usr/share/doc/base/copyright", tarfile.REGTYPE, b"notice fixture"),
            ("usr/share/doc/relative", tarfile.SYMTYPE, "base"),
            ("usr/share/doc/absolute", tarfile.SYMTYPE, "/usr/share/doc/base"),
        ])
        for path in ("usr/share/doc/relative/copyright", "usr/share/doc/absolute/copyright"):
            with self.subTest(path=path):
                self.assertEqual(SOURCES.read_archive_file(archive, members, path),
                                 (b"notice fixture", "usr/share/doc/base/copyright"))

    def test_hardlink_target_is_relative_to_archive_root(self):
        archive, members = self.archive([
            ("usr/share/common-licenses/GPL-3", tarfile.REGTYPE, b"license fixture"),
            ("usr/share/doc/example/copyright", tarfile.LNKTYPE, "usr/share/common-licenses/GPL-3"),
        ])
        self.assertEqual(SOURCES.read_archive_file(archive, members, "usr/share/doc/example/copyright"),
                         (b"license fixture", "usr/share/common-licenses/GPL-3"))

    def test_above_root_link_cycle_and_nonregular_final_target_rejected(self):
        for entries, path in (
            ([("escape", tarfile.SYMTYPE, "../outside")], "escape"),
            ([("one", tarfile.SYMTYPE, "two"), ("two", tarfile.SYMTYPE, "one")], "one"),
            ([("directory", tarfile.DIRTYPE, "")], "directory"),
        ):
            archive, members = self.archive(entries)
            with self.subTest(path=path), self.assertRaises(ValueError):
                SOURCES.read_archive_file(archive, members, path)

    def test_duplicate_and_escaping_member_names_rejected(self):
        for entries in (
            [("same", tarfile.REGTYPE, b"one"), ("same", tarfile.REGTYPE, b"two")],
            [("../escape", tarfile.REGTYPE, b"fixture")],
            [("/absolute", tarfile.REGTYPE, b"fixture")],
        ):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.archive(entries)


class DownloadFailureTests(unittest.TestCase):
    def test_rejected_download_leaves_no_unverified_component_in_bundle(self):
        with tempfile.TemporaryDirectory(prefix="foldgpt-download-test-") as directory:
            target = Path(directory) / "source.tar.xz"
            response = io.BytesIO(b"unauthenticated fixture")
            response.url = "https://example.invalid/source.tar.xz"
            with patch.object(SOURCES.urllib.request, "urlopen", return_value=response), self.assertRaises(ValueError):
                SOURCES.download(response.url, target, {"bytes": 1, "sha256": "0" * 64})
            self.assertEqual(list(Path(directory).iterdir()), [])


class BundlePublicationTests(unittest.TestCase):
    def make_archive(self, path, entries):
        with tarfile.open(path, "w") as archive:
            for name, contents in entries:
                member = tarfile.TarInfo("./" + name)
                member.size = len(contents)
                archive.addfile(member, io.BytesIO(contents))

    def test_two_checksum_generations_and_complete_archive_verification(self):
        with tempfile.TemporaryDirectory(prefix="foldgpt-source-resume-test-") as temporary:
            bundle = Path(temporary) / "bundle"
            bundle.mkdir()
            source = bundle / "fixture.txt"
            source.write_bytes(b"first generation")
            first = SOURCES.write_bundle_checksums(bundle, {"fixture.txt"})
            source.write_bytes(b"second generation")
            second = SOURCES.write_bundle_checksums(bundle, {"fixture.txt"})
            self.assertNotEqual(first, second)
            self.assertNotIn("SHA256SUMS.json", second)
            self.assertEqual(json.loads((bundle / "SHA256SUMS.json").read_text()), second)
            archive = Path(temporary) / "result.tar"
            self.make_archive(archive, [("fixture.txt", source.read_bytes()),
                                       ("SHA256SUMS.json", (bundle / "SHA256SUMS.json").read_bytes())])
            self.assertEqual(SOURCES.verify_source_archive(archive, second), 2)

    def test_unexpected_file_or_empty_directory_is_refused(self):
        for name, is_directory in ((".download-orphan", False), ("unlisted-empty", True)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                bundle = Path(temporary)
                (bundle / "fixture.txt").write_bytes(b"fixture")
                if is_directory:
                    (bundle / name).mkdir()
                else:
                    (bundle / name).write_bytes(b"not authenticated")
                with self.assertRaises(ValueError):
                    SOURCES.write_bundle_checksums(bundle, {"fixture.txt"})
                self.assertFalse((bundle / "SHA256SUMS.json").exists())

    def test_symlink_and_hardlink_are_refused(self):
        for link_kind in ("symlink", "hardlink"):
            with self.subTest(kind=link_kind), tempfile.TemporaryDirectory() as temporary:
                bundle = Path(temporary) / "bundle"
                bundle.mkdir()
                outside = Path(temporary) / "outside.txt"
                outside.write_bytes(b"harmless outside fixture")
                link = bundle / "fixture.txt"
                try:
                    if link_kind == "symlink":
                        link.symlink_to(outside)
                    else:
                        os.link(outside, link)
                except OSError as error:
                    self.skipTest("Link creation unavailable: " + str(error))
                with self.assertRaises(ValueError):
                    SOURCES.write_bundle_checksums(bundle, {"fixture.txt"})
                self.assertEqual(outside.read_bytes(), b"harmless outside fixture")

    def test_exported_corruption_missing_extra_and_duplicate_members_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            bundle.mkdir()
            (bundle / "fixture.txt").write_bytes(b"expected")
            sums = SOURCES.write_bundle_checksums(bundle, {"fixture.txt"})
            index = ("SHA256SUMS.json", (bundle / "SHA256SUMS.json").read_bytes())
            valid = ("fixture.txt", b"expected")
            for entries in ([index, ("fixture.txt", b"damaged")], [index],
                            [index, valid, ("extra", b"unknown")], [index, valid, valid],
                            [("SHA256SUMS.json", b"{}"), valid]):
                with self.subTest(entries=entries):
                    archive = Path(temporary) / "result.tar"
                    self.make_archive(archive, entries)
                    with self.assertRaises(ValueError):
                        SOURCES.verify_source_archive(archive, sums)


if __name__ == "__main__":
    unittest.main()
