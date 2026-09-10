"""Parser and bounded literal-scanning checks; no audited binary is executed."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location("native_inventory", HERE / "inventory-native.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class InventoryChecks(unittest.TestCase):
    def test_archive_names_cannot_escape_or_change_platform_spelling(self):
        for name in ("", "/lib/libc.so", "../lib.so", "a/../lib.so", "a//lib.so", "a/./lib.so", "C:/lib.so", "a\\lib.so"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                AUDIT.safe_relative(name)
        self.assertEqual(str(AUDIT.safe_relative("usr/lib/chatgpt/ChatGPT")), "usr/lib/chatgpt/ChatGPT")

    def test_literal_scan_crosses_blocks_and_retains_each_token_category(self):
        target = ROOT / "work/desktop-audit-20260908/analyzer-tests"
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=target) as temporary:
            path = Path(temporary) / "data"
            # Long printable regions must not trigger quadratic end-of-string
            # matching. The token crossing 1 MiB must remain discoverable.
            prefix = b"x" * (1024 * 1024 - 3)
            path.write_bytes(prefix + b"/proc/self/status\0" + b"A" * (1024 * 1024) + b"\0bwrap\0WAYLAND_DISPLAY\0")
            result = AUDIT.scan_strings(path, limit=1)
            self.assertTrue(result["truncated"])
            self.assertIn("/proc/", result["tokenMatches"])
            self.assertIn("bwrap", result["tokenMatches"])
            self.assertIn("WAYLAND_DISPLAY", result["tokenMatches"])

    def test_version_order_is_numeric_and_does_not_erase_non_numeric_requirements(self):
        versions = ["GLIBC_2.9", "GLIBC_2.28", "GLIBC_PRIVATE", "GLIBCXX_3.4.9", "GLIBCXX_3.4.22"]
        self.assertEqual(AUDIT.numeric_max(versions, "GLIBC_"), "GLIBC_2.28")
        self.assertEqual(AUDIT.numeric_max(versions, "GLIBCXX_"), "GLIBCXX_3.4.22")
        self.assertIsNone(AUDIT.numeric_max(["GLIBC_PRIVATE"], "GLIBC_"))
        self.assertEqual(AUDIT.abi_summary([], [], None), "static-elf-libc-unidentified")


if __name__ == "__main__":
    unittest.main()
