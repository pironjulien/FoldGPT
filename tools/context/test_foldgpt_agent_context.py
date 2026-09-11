import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).with_name("foldgpt_agent_context.py")
SPEC = importlib.util.spec_from_file_location("context", SOURCE)
context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context)
MANIFEST = Path(__file__).resolve().parents[2] / "config/agent-context/foldgpt.v1.json"


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="foldgpt-context-", dir=os.environ.get("FOLDGPT_TEST_TMPDIR", "/var/tmp"))
        self.root = Path(self.temporary.name)
        (self.root / "etc").mkdir()
        (self.root / "etc/foldgpt-user").write_text("foldgpt\n")
        (self.root / "etc/passwd").write_text("root:x:0:0::/root:/bin/bash\nfoldgpt:x:10410:10410::/home/foldgpt:/bin/bash\n")
        (self.root / "etc/group").write_text("root:x:0:\nfoldgpt:x:10410:\n")
        self.home = self.root / "home/foldgpt"
        self.home.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def sync(self, **options):
        return context.synchronize(self.root, MANIFEST, **options)

    def test_selected_home_and_manifest_are_really_written_and_read_back(self):
        result = self.sync()
        self.assertEqual(result["selectedGuestFile"], "/home/foldgpt/.codex/AGENTS.md")
        manifest = self.root / result["manifestGuestFile"].lstrip("/")
        actual = json.loads(manifest.read_bytes())
        self.assertEqual(actual["guestBinding"]["uid"], 10410)
        self.assertEqual(actual["manifest"]["clientHost"]["platform"], "Android")
        self.assertFalse(result["modelDeliveryVerified"])
        self.assertEqual(self.sync(check=True), result)

    def test_preferences_and_suffix_survive_updates_and_repeat_does_not_replace_inode(self):
        codex = self.home / ".codex"
        codex.mkdir()
        agents = codex / "AGENTS.md"
        prefix = "Mes instructions : café.\r\n".encode()
        agents.write_bytes(prefix)
        self.sync()
        agents.write_bytes(agents.read_bytes() + b"\nMy later instruction.\n")
        original = agents.read_bytes()
        inode = agents.stat().st_ino
        self.sync()
        self.assertEqual(agents.read_bytes(), original)
        self.assertEqual(agents.stat().st_ino, inode)
        revised = json.loads(MANIFEST.read_bytes())
        revised["revision"] = "test-new-revision"
        source = self.root / "updated.json"
        source.write_bytes(context.canonical(revised))
        context.synchronize(self.root, source)
        self.assertTrue(agents.read_bytes().startswith(prefix))
        self.assertTrue(agents.read_bytes().endswith(b"\nMy later instruction.\n"))
        self.assertEqual(agents.read_bytes().count(context.BEGIN), 1)

    def test_nonempty_override_wins_and_empty_override_falls_back(self):
        codex = self.home / ".codex"
        codex.mkdir()
        (codex / "AGENTS.md").write_text("Base preference.\n")
        override = codex / "AGENTS.override.md"
        override.write_text("Override preference.\n")
        self.assertTrue(self.sync()["selectedGuestFile"].endswith("AGENTS.override.md"))
        self.assertEqual((codex / "AGENTS.md").read_text(), "Base preference.\n")
        override.write_text("  \n")
        self.assertTrue(self.sync()["selectedGuestFile"].endswith("/AGENTS.md"))
        self.assertEqual(override.read_text(), "  \n")

    def test_explicit_codex_home_is_used_without_config_change(self):
        selected = self.home / "custom"
        selected.mkdir()
        config = selected / "config.toml"
        config.write_text('model = "unchanged"\n')
        result = self.sync(codex_home="/home/foldgpt/custom")
        self.assertEqual(result["selectedGuestFile"], "/home/foldgpt/custom/AGENTS.md")
        self.assertEqual(config.read_text(), 'model = "unchanged"\n')
        self.assertFalse((self.home / ".codex").exists())

    def test_symlink_and_hardlink_targets_fail_without_outside_changes(self):
        codex = self.home / ".codex"
        codex.mkdir()
        external = self.root / "outside"
        external.write_bytes(b"private outside instruction")
        target = codex / "AGENTS.md"
        target.symlink_to(external)
        with self.assertRaises((ValueError, OSError)):
            self.sync()
        target.unlink()
        os.link(external, target)
        with self.assertRaises(ValueError):
            self.sync()
        self.assertEqual(external.read_bytes(), b"private outside instruction")

    def test_bad_account_or_oversized_existing_instructions_are_not_repaired(self):
        (self.root / "etc/foldgpt-user").write_text("root\n")
        with self.assertRaises(ValueError):
            self.sync()
        (self.root / "etc/foldgpt-user").write_text("foldgpt\n")
        codex = self.home / ".codex"
        codex.mkdir()
        agents = codex / "AGENTS.md"
        original = b"x" * context.LIMIT
        agents.write_bytes(original)
        with self.assertRaises(ValueError):
            self.sync()
        self.assertEqual(agents.read_bytes(), original)

    def test_changed_content_or_duplicate_markers_fail_check(self):
        result = self.sync()
        path = Path(result["selectedPhysicalFile"])
        original = path.read_bytes()
        changed = original.replace(b"Debian GNU/Linux", b"Wrong guest OS")
        self.assertNotEqual(changed, original)
        path.write_bytes(changed)
        with self.assertRaises(ValueError):
            self.sync(check=True)
        path.write_bytes(original + context.BEGIN + b"\n")
        with self.assertRaises(ValueError):
            self.sync()

    def test_manifest_json_duplicates_and_capability_promotion_are_rejected(self):
        source = self.root / "bad.json"
        source.write_text('{"schema":1,"schema":2}')
        with self.assertRaises(ValueError):
            context.manifest(source)
        data = json.loads(MANIFEST.read_bytes())
        data["capabilities"][0]["status"] = "all-android-access"
        source.write_bytes(context.canonical(data))
        with self.assertRaises(ValueError):
            context.manifest(source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
