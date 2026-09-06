"""Host archive-format tests using explicit tiny fixtures, never GPU execution."""
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest

import inactive_integration_bundle as bundle


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.USTAR_FORMAT) as tar:
        for path, kind, mode, content in entries:
            item = tarfile.TarInfo(path)
            item.type = kind
            item.mode = mode
            if kind == tarfile.SYMTYPE:
                item.linkname = content
                tar.addfile(item)
            elif kind == tarfile.DIRTYPE:
                tar.addfile(item)
            else:
                item.size = len(content)
                tar.addfile(item, io.BytesIO(content))
    return output.getvalue()


def xkb_entries():
    root = bundle.XKB
    return [(root, tarfile.DIRTYPE, 0o755, b""),
            (root + "/rules", tarfile.DIRTYPE, 0o755, b""),
            (root + "/rules/base", tarfile.REGTYPE, 0o644, b"fixture base\n"),
            (root + "/rules/evdev", tarfile.REGTYPE, 0o644, b"fixture evdev\n"),
            (root + "/rules/xorg", tarfile.SYMTYPE, 0o777, "base")]


def gpu_entries():
    entries = []
    elf = b"\x7fELF\x02\x01" + b"\0" * 12 + b"\xb7\x00" + b"fixture"
    for name in bundle.GPU_FILES:
        data = elf if name.startswith("lib/") else b"fixture configuration\n"
        if name.endswith(".json"):
            data = json.dumps({"ICD": {"library_path": "/" + bundle.GPU_PREFIX + "/lib/libvulkan_freedreno.so"}}).encode()
        entries.append((bundle.GPU_PREFIX + "/" + name, tarfile.REGTYPE, 0o777, data))
    for name, target in bundle.GPU_LINKS.items():
        entries.append((bundle.GPU_PREFIX + "/" + name, tarfile.SYMTYPE, 0o777, target))
    return entries


class InactiveBundleTests(unittest.TestCase):
    def test_xkb_exact_inventory_contains_native_relative_links(self):
        entries = xkb_entries()
        records = bundle.inventory_xkb(archive(entries))
        self.assertEqual(set(records), {item[0] for item in entries})
        self.assertEqual(records[bundle.XKB + "/rules/xorg"]["link"], "base")

    def test_xkb_duplicate_unknown_kind_mode_and_absolute_links_are_rejected(self):
        valid = xkb_entries()
        for entries in (valid + [valid[-1]], valid[:-1] + [(valid[-1][0], tarfile.LNKTYPE, 0o777, b"base")],
                        valid[:-1] + [(valid[-1][0], tarfile.SYMTYPE, 0o777, "/etc/passwd")],
                        valid[:-1] + [(valid[-1][0], tarfile.SYMTYPE, 0o777, "absent")],
                        [(valid[0][0], tarfile.DIRTYPE, 0o777, b"")] + valid[1:], valid[1:]):
            with self.assertRaises(ValueError):
                bundle.inventory_xkb(archive(entries))

    def test_gpu_subset_preserves_bytes_but_normalizes_unsafe_archive_modes(self):
        entries = gpu_entries()
        entries.append((bundle.GPU_PREFIX + "/bin/development-probe", tarfile.REGTYPE, 0o777, b"not runtime"))
        records, payload = bundle.gpu_payload(archive(entries))
        self.assertEqual(len(records), len(bundle.GPU_FILES) + len(bundle.GPU_LINKS))
        self.assertNotIn(entries[-1][0], records)
        for path, kind, _, data in entries[:-1]:
            if kind == tarfile.REGTYPE:
                self.assertEqual(payload[path], data)
                self.assertEqual(records[path]["mode"], 0o755 if "/lib/" in path else 0o644)

    def test_gpu_missing_file_duplicate_wrong_elf_and_link_are_rejected(self):
        valid = gpu_entries()
        for entries in (valid[1:], valid + [valid[0]],
                        [(valid[0][0], tarfile.REGTYPE, 0o777, b"not ARM64")] + valid[1:],
                        valid[:-1] + [(valid[-1][0], tarfile.SYMTYPE, 0o777, "wrong-target")]):
            with self.assertRaises(ValueError):
                bundle.gpu_payload(archive(entries))

    def test_snapshot_authentication_is_mandatory(self):
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "archive"
            path.write_bytes(b"fixture")
            self.assertEqual(bundle.snapshot(path, bundle.digest(b"fixture"), 7), b"fixture")
            with self.assertRaises(ValueError):
                bundle.snapshot(path, "0" * 64, 7)
            with self.assertRaises(ValueError):
                bundle.snapshot(path, bundle.digest(b"fixture"), 6)

    def test_unsafe_paths_are_rejected(self):
        for path in ("/opt/x", "../x", "opt/../x", "opt//x", "opt/./x", "opt/x/", "opt\\x", "opt/x\n"):
            with self.assertRaises(ValueError):
                bundle.safe_path(path)

    def test_binary_framing_is_deterministic_and_manifest_precedes_payload(self):
        records, payload = bundle.gpu_payload(archive(gpu_entries()))
        records.update(bundle.inventory_xkb(archive(xkb_entries())))
        first, manifest = bundle.encode(records, payload, "a" * 64, "b" * 64, bundle.GPU_SHA)
        second, _ = bundle.encode(dict(reversed(list(records.items()))), dict(reversed(list(payload.items()))), "a" * 64, "b" * 64, bundle.GPU_SHA)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith(bundle.MAGIC + struct.pack(">I", len(manifest)) + manifest))
        self.assertEqual(first[len(bundle.MAGIC) + 4 + len(manifest):], b"".join(payload[path] for path in sorted(payload)))


if __name__ == "__main__":
    unittest.main()
