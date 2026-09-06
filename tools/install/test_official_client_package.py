"""Real filesystem/archive tests; no network, installed client or device calls."""
import hashlib
import gzip
import importlib.util
import io
import json
import lzma
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("official_client_package", Path(__file__).with_name("official_client_package.py"))
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)


def tar(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for name, kind, body, mode in entries:
            item = tarfile.TarInfo(name)
            item.type, item.mode = kind, mode
            if kind == tarfile.REGTYPE:
                item.size = len(body)
                archive.addfile(item, io.BytesIO(body))
            else:
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    item.linkname = body
                archive.addfile(item)
    return output.getvalue()


def ar(entries):
    data = bytearray(b"!<arch>\n")
    for name, content in entries:
        header = (f"{name:<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(content):<10}`\n").encode("ascii")
        assert len(header) == 60
        data.extend(header)
        data.extend(content)
        if len(content) % 2:
            data.extend(b"\n")
    return bytes(data)


def package(payload, control=None, suffix=()):
    if control is None:
        control = [("./control", tarfile.REGTYPE,
                    b"Package: chatgpt\nVersion: 1.2.3\nArchitecture: arm64\nDepends: libc6 (>= 2.35), libgtk-3-0\n", 0o644),
                   ("./postinst", tarfile.REGTYPE, b"#!/bin/sh\nexit 0\n", 0o755)]
    return ar([("debian-binary", b"2.0\n"), ("control.tar.xz", lzma.compress(tar(control))),
               ("data.tar.xz", lzma.compress(tar(payload))), *suffix])


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="foldgpt-client-input-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / "stage"
        self.stage.mkdir(mode=0o700)
        self.source = self.root / "input.deb"
        self.payload = [("./", tarfile.DIRTYPE, b"", 0o755),
                        ("./usr/", tarfile.DIRTYPE, b"", 0o755),
                        ("./usr/lib/", tarfile.DIRTYPE, b"", 0o755),
                        ("./usr/lib/chatgpt/", tarfile.DIRTYPE, b"", 0o755),
                        ("./usr/lib/chatgpt/client", tarfile.REGTYPE, b"intact official fixture\n", 0o755),
                        ("./usr/bin/", tarfile.DIRTYPE, b"", 0o755),
                        ("./usr/bin/chatgpt", tarfile.SYMTYPE, "../lib/chatgpt/client", 0o777)]
        elf = bytearray(64)
        elf[:7] = b"\x7fELF\x02\x01\x01"
        elf[18:20] = (183).to_bytes(2, "little")
        for core in sorted(CLIENT.CORE_EXECUTABLES):
            self.payload.append(("./" + core, tarfile.REGTYPE, bytes(elf), 0o755))
        self.expected = self.write(package(self.payload))

    def write(self, data):
        self.source.write_bytes(data)
        return {"format": CLIENT.FORMAT, "sourceUrl": CLIENT.SOURCE_URL,
                "sourceDocument": CLIENT.SOURCE_DOCUMENT, "package": "chatgpt",
                "architecture": "arm64", "version": "1.2.3",
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "maxTarBytes": 4 * 1024 * 1024, "maxMembers": 100}

    def inspect(self, expected=None):
        with self.source.open("rb") as stream:
            return CLIENT.inspect(stream, expected or self.expected)

    def reject_package(self, data):
        with self.assertRaises((ValueError, tarfile.TarError, lzma.LZMAError, EOFError)):
            self.inspect(self.write(data))

    def materialize(self, inventory):
        root = self.root / "inactive"
        root.mkdir()
        bodies = {name.removeprefix("./"): body for name, kind, body, mode in self.payload if kind == tarfile.REGTYPE}
        for item in inventory["files"]:
            path = root / item["path"]
            if item["kind"] == "directory":
                path.mkdir(exist_ok=True, parents=True)
            elif item["kind"] == "file":
                path.parent.mkdir(exist_ok=True, parents=True)
                path.write_bytes(bodies[item["path"]])
                path.chmod(item["mode"])
            else:
                path.parent.mkdir(exist_ok=True, parents=True)
                path.symlink_to(item["target"])
        return root

    def test_real_archives_and_metadata_inventory(self):
        result = self.inspect()
        self.assertEqual(result["controlFields"]["depends"], "libc6 (>= 2.35), libgtk-3-0")
        self.assertEqual(len(result["files"]), len(self.payload))
        self.assertFalse(result["embeddedSignatureVerified"])
        self.assertFalse(result["embeddedSignaturePresent"])
        result = self.inspect(self.write(package(self.payload, suffix=[("_gpgorigin", b"opaque signature fixture")])))
        self.assertTrue(result["embeddedSignaturePresent"])
        self.assertFalse(result["embeddedSignatureVerified"])

    def test_gzip_control_and_payload_are_fully_validated(self):
        control = tar([("./control", tarfile.REGTYPE, b"Package: chatgpt\nVersion: 1.2.3\nArchitecture: arm64\n", 0o644)])
        content = ar([("debian-binary", b"2.0\n"), ("control.tar.gz", gzip.compress(control)),
                      ("data.tar.gz", gzip.compress(tar(self.payload)))])
        result = self.inspect(self.write(content))
        self.assertEqual(len(result["files"]), len(self.payload))

    def test_digest_size_and_pinned_metadata_checked(self):
        for field, value in (("sha256", "0" * 64), ("bytes", self.expected["bytes"] - 1),
                             ("version", "9.9")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.inspect({**self.expected, field: value})

    def test_core_executables_require_actual_aarch64_elf_and_execute_mode(self):
        core = self.payload[-1]
        for replacement in ((core[0], core[1], b"#!/bin/sh\n", core[3]),
                            (core[0], core[1], core[2][:18] + b"\x3e\0" + core[2][20:], core[3]),
                            (core[0], core[1], core[2], 0o644)):
            self.reject_package(package(self.payload[:-1] + [replacement]))
        self.reject_package(package(self.payload[:-1]))

    def test_descriptor_is_narrow_and_requires_real_positive_limits(self):
        for field, value in (("sourceUrl", "https://mirror.invalid/chatgpt.deb"),
                             ("architecture", "amd64"), ("bytes", True), ("maxMembers", -1),
                             ("version", "1.0\nInjected: yes"), ("sha256", "A" * 64)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                CLIENT.descriptor({**self.expected, field: value})
        with self.assertRaises(ValueError):
            CLIENT.descriptor({**self.expected, "originVerified": True})

    def test_tar_resource_limits(self):
        for field, value in (("maxTarBytes", 512), ("maxMembers", 2)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.inspect({**self.expected, field: value})

    def test_rejects_ar_truncation_duplicates_and_trailing_content(self):
        data = self.source.read_bytes()
        for broken in (data[:-1], data + b"hidden", data.replace(b"2.0\n", b"1.0\n", 1),
                       package(self.payload, suffix=[("data.tar.xz", lzma.compress(tar(self.payload)))])):
            self.reject_package(broken)

    def test_rejects_traversal_names_special_files_and_duplicate_paths(self):
        for name in ("../escape", "/etc/preload", "./usr/../escape", "usr//bad", "usr\\bad", "usr/./bad"):
            self.reject_package(package(self.payload + [(name, tarfile.REGTYPE, b"unsafe", 0o644)]))
        for kind in (tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE):
            self.reject_package(package(self.payload + [("./unexpected", kind, "usr/lib/chatgpt/client", 0o644)]))
        self.reject_package(package(self.payload + self.payload[-1:]))

    def test_rejects_ancestor_symlinks_in_both_orders(self):
        link = ("./alias", tarfile.SYMTYPE, "usr", 0o777)
        child = ("./alias/child", tarfile.REGTYPE, b"outside ancestor", 0o644)
        for additions in ([link, child], [child, link]):
            self.reject_package(package(self.payload + additions))
        self.reject_package(package(self.payload + [("./escape", tarfile.SYMTYPE, "../../host", 0o777)]))

    def test_long_gnu_names_and_guest_absolute_symlink_are_preserved(self):
        path = "./usr/lib/chatgpt/" + "a" * 120
        result = self.inspect(self.write(package(self.payload + [(path, tarfile.REGTYPE, b"long path", 0o644),
                 ("./usr/bin/absolute", tarfile.SYMTYPE, "/usr/lib/chatgpt/client", 0o777)])))
        self.assertIn(path[2:], {item["path"] for item in result["files"]})

    def test_rejects_control_duplicate_fields_and_symlinks(self):
        for content in (b"Package: chatgpt\npackage: second\n", b" orphan\n", b"Package: chatgpt\n\nVersion: 1\n"):
            self.reject_package(package(self.payload, [("./control", tarfile.REGTYPE, content, 0o644)]))
        self.reject_package(package(self.payload, [("./control", tarfile.SYMTYPE, "../elsewhere", 0o777)]))

    def test_rejects_hidden_concatenated_tar(self):
        control = tar([("./control", tarfile.REGTYPE, b"Package: chatgpt\nVersion: 1.2.3\nArchitecture: arm64\n", 0o644)])
        for data in (tar(self.payload) + tar(self.payload), tar(self.payload) + b"hidden"):
            self.reject_package(ar([("debian-binary", b"2.0\n"), ("control.tar.xz", lzma.compress(control)),
                                    ("data.tar.xz", lzma.compress(data))]))

    def test_rejects_missing_second_tar_terminator_and_pax_metadata(self):
        control = tar([("./control", tarfile.REGTYPE, b"Package: chatgpt\nVersion: 1.2.3\nArchitecture: arm64\n", 0o644)])
        data = tar(self.payload)
        end = max(index for index, value in enumerate(data) if value) + 1
        payload_end = (end + 511) // 512 * 512
        for suffix in (0, 512, 513):
            self.reject_package(ar([("debian-binary", b"2.0\n"), ("control.tar.xz", lzma.compress(control)),
                                   ("data.tar.xz", lzma.compress(data[:payload_end + suffix]))]))
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
            item = tarfile.TarInfo("./extra")
            item.pax_headers = {"SCHILY.xattr.security.capability": "unreviewed"}
            archive.addfile(item)
        self.reject_package(ar([("debian-binary", b"2.0\n"), ("control.tar.xz", lzma.compress(control)),
                               ("data.tar.xz", lzma.compress(output.getvalue()))]))

    def test_prepare_and_resume_without_source_recheck_the_actual_bytes(self):
        result = CLIENT.prepare(self.source, self.expected, self.stage)
        package_path = self.stage / "package.deb"
        inode = package_path.stat().st_ino
        self.source.unlink()
        self.assertEqual(CLIENT.prepare(None, self.expected, self.stage), result)
        self.assertEqual(package_path.stat().st_ino, inode)
        self.assertEqual(json.loads((self.stage / "inventory.json").read_text()), result)
        package_path.write_bytes(b"corruption")
        with self.assertRaises(ValueError):
            CLIENT.prepare(None, self.expected, self.stage)

    def test_stage_binding_inventory_and_unrelated_files_cannot_be_adopted(self):
        CLIENT.prepare(self.source, self.expected, self.stage)
        with self.assertRaises(ValueError):
            CLIENT.prepare(None, {**self.expected, "version": "2.0"}, self.stage)
        (self.stage / "inventory.json").write_text("{}")
        with self.assertRaises(ValueError):
            CLIENT.prepare(None, self.expected, self.stage)
        (self.stage / "unrelated").write_text("keep")
        with self.assertRaises(ValueError):
            CLIENT.prepare(None, self.expected, self.stage)
        self.assertEqual((self.stage / "unrelated").read_text(), "keep")

    def test_copy_failure_keeps_bound_stage_and_retry_preserves_source(self):
        original = CLIENT.copy_hash
        def interrupted(stream, output=None, limit=None):
            if output is not None:
                output.write(b"partial")
                raise OSError("injected full filesystem")
            return original(stream, output, limit)
        with patch.object(CLIENT, "copy_hash", side_effect=interrupted), self.assertRaises(OSError):
            CLIENT.prepare(self.source, self.expected, self.stage)
        self.assertFalse((self.stage / "package.deb").exists())
        result = CLIENT.prepare(self.source, self.expected, self.stage)
        self.assertEqual(result["descriptor"], self.expected)

    def test_process_kill_after_package_publication_recovers_same_package(self):
        expected_file = self.root / "descriptor.json"
        expected_file.write_bytes(CLIENT.canonical(self.expected))
        code = """
import importlib.util, json, os, signal, sys
spec = importlib.util.spec_from_file_location('client', sys.argv[1])
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
original = client.publish_json
def crash(parent, name, value):
    if name == 'inventory.json':
        os.kill(os.getpid(), signal.SIGKILL)
    return original(parent, name, value)
client.publish_json = crash
client.prepare(sys.argv[2], json.load(open(sys.argv[3])), sys.argv[4])
"""
        child = subprocess.run([sys.executable, "-c", code, str(Path(CLIENT.__file__)),
                                str(self.source), str(expected_file), str(self.stage)], capture_output=True)
        self.assertEqual(child.returncode, -signal.SIGKILL, child.stderr.decode())
        inode = (self.stage / "package.deb").stat().st_ino
        self.assertFalse((self.stage / "inventory.json").exists())
        self.source.unlink()
        CLIENT.prepare(None, self.expected, self.stage)
        self.assertEqual((self.stage / "package.deb").stat().st_ino, inode)

    def test_symlinks_and_shared_permissions_rejected_without_following(self):
        alias = self.root / "alias"
        alias.symlink_to(self.stage, target_is_directory=True)
        with self.assertRaises(ValueError):
            CLIENT.prepare(self.source, self.expected, alias)
        self.stage.chmod(0o755)
        with self.assertRaises(ValueError):
            CLIENT.prepare(self.source, self.expected, self.stage)
        self.stage.chmod(0o700)
        target = self.root / "precious"
        target.write_text("untouched")
        (self.stage / "client-input.lock").symlink_to(target)
        with self.assertRaises(OSError):
            CLIENT.prepare(self.source, self.expected, self.stage)
        self.assertEqual(target.read_text(), "untouched")

    def test_verify_real_tree_bytes_permissions_and_links(self):
        inventory = self.inspect()
        root = self.materialize(inventory)
        report = CLIENT.verify_files(root, inventory)
        self.assertEqual(report["checked"], len(self.payload) - 1)
        self.assertEqual(report["rootInode"], root.stat().st_ino)
        original = root / "usr/lib/chatgpt/client"
        original.write_bytes(b"modified")
        with self.assertRaises(ValueError):
            CLIENT.verify_files(root, inventory)
        original.write_bytes(b"intact official fixture\n")
        original.chmod(0o644)
        with self.assertRaises(ValueError):
            CLIENT.verify_files(root, inventory)
        original.chmod(0o755)
        link = root / "usr/bin/chatgpt"
        link.unlink()
        link.symlink_to("/outside")
        with self.assertRaises(ValueError):
            CLIENT.verify_files(root, inventory)

    def test_verify_never_follows_parent_or_leaf_symlinks(self):
        inventory = self.inspect()
        root = self.materialize(inventory)
        outside = self.root / "outside"
        (root / "usr/lib").rename(outside)
        (root / "usr/lib").symlink_to(outside, target_is_directory=True)
        with self.assertRaises((OSError, ValueError)):
            CLIENT.verify_files(root, inventory)
        (root / "usr/lib").unlink()
        outside.rename(root / "usr/lib")
        leaf = root / "usr/lib/chatgpt/client"
        leaf.rename(self.root / "outside-file")
        leaf.symlink_to(self.root / "outside-file")
        with self.assertRaises(OSError):
            CLIENT.verify_files(root, inventory)


if __name__ == "__main__":
    unittest.main(verbosity=2)
