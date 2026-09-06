"""Host-only deployment regressions. The ADB stand-in is not device evidence."""
import hashlib
from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "gpu_deploy", Path(__file__).parents[1] / "tools/gpu/deploy-test-prefix.py")
DEPLOY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPLOY)


def archive(name, link=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as content:
        entry = tarfile.TarInfo(name)
        if link is None:
            entry.size = 4
            content.addfile(entry, io.BytesIO(b"test"))
        else:
            entry.type = tarfile.SYMTYPE
            entry.linkname = link
            content.addfile(entry)
    return output.getvalue()


class ArchiveTests(unittest.TestCase):
    def test_rejects_outside_paths(self):
        for name in ("home/test/file", "/" + DEPLOY.PREFIX + "/file",
                     DEPLOY.PREFIX + "/../escape"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                DEPLOY.validate_archive(archive(name))

    def test_rejects_symlink_parent_traversal_even_when_lexically_inside(self):
        # A preceding symlink may shorten the actual traversal depth. Never
        # accept '..' merely because textual normalization stays in the prefix.
        with self.assertRaises(ValueError):
            DEPLOY.validate_archive(archive(DEPLOY.PREFIX + "/lib/a", "nested/../b"))

    def test_accepts_library_alias(self):
        DEPLOY.validate_archive(archive(DEPLOY.PREFIX + "/lib/libGL.so.1", "libGL.so.1.2.0"))

    def run_transfer(self, corrupt_remote=False):
        good = archive(DEPLOY.PREFIX + "/bin/vulkan-clear-probe")
        bad = archive("home/test/outside-prefix.txt")
        received = []
        extractions = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "downloads/gpu/foldgpt-mesa-26.2.2-arm64.tar.gz"
            original.parent.mkdir(parents=True)
            original.write_bytes(good)

            def run(command, **kwargs):
                if command[3:5] == ["shell", "mkdir"]:
                    # Reproduce the race after validation but before push.
                    original.write_bytes(bad)
                elif command[3] == "push":
                    received.append(Path(command[4]).read_bytes())
                elif command[3] == "shell" and "tar -xzf" in command[-1]:
                    extractions.append(command[-1])
                return subprocess.CompletedProcess(command, 0)

            def checksum(*args, **kwargs):
                data = bad if corrupt_remote else received[0]
                return hashlib.sha256(data).hexdigest() + "  mesa.tar.gz\n"

            with patch.object(DEPLOY, "ROOT", root), \
                 patch.object(DEPLOY.subprocess, "run", side_effect=run), \
                 patch.object(DEPLOY.subprocess, "check_output", side_effect=checksum), \
                 patch("sys.argv", ["deploy", "--serial", "host-test-only"]), \
                 redirect_stdout(io.StringIO()):
                if corrupt_remote:
                    with self.assertRaisesRegex(RuntimeError, "changed during ADB transfer"):
                        DEPLOY.main()
                else:
                    DEPLOY.main()
            self.assertEqual(received, [good])
            self.assertEqual(len(extractions), 0 if corrupt_remote else 1)
        return extractions

    def test_original_archive_replacement_cannot_change_validated_payload(self):
        self.run_transfer()

    def test_remote_hash_mismatch_never_reaches_extraction(self):
        self.run_transfer(corrupt_remote=True)

    @unittest.skipUnless(os.name == "posix", "Exercises the real Linux shell, tar and rename")
    def test_interrupted_extraction_can_retry_without_poisoning_revision(self):
        import shlex
        # Recover the exact run-as shell body from the host orchestration seam.
        wrapper = self.run_transfer()[0]
        body = shlex.split(wrapper)[-1]
        payload = io.BytesIO()
        required = ("bin/vulkan-clear-probe", "bin/glx-clear-probe",
                    "bin/vulkan-timestamp-probe", "lib/libGL.so.1", "lib/libEGL.so.1",
                    "lib/libvulkan_freedreno.so", "share/vulkan/icd.d/freedreno_icd.aarch64.json")
        with tarfile.open(fileobj=payload, mode="w:gz") as content:
            for path in required:
                entry = tarfile.TarInfo(DEPLOY.PREFIX + "/" + path)
                entry.size = 4
                entry.mode = 0o755
                content.addfile(entry, io.BytesIO(b"test"))
        data = payload.getvalue()
        DEPLOY.validate_archive(data)
        with tempfile.TemporaryDirectory(prefix="foldgpt-extraction-test-") as temporary:
            root = Path(temporary)
            (root / "files/debian/opt").mkdir(parents=True)
            body = body.replace("/data/user/0/app.foldgpt", str(root))
            destination = root / "files/debian" / DEPLOY.PREFIX
            broken = subprocess.run(["/bin/sh", "-c", body], cwd=root, input=data[:-12],
                                    capture_output=True, timeout=10)
            self.assertNotEqual(broken.returncode, 0)
            self.assertFalse(destination.exists())
            self.assertEqual(list((root / "files/debian/opt/foldgpt-gpu").iterdir()), [])
            retry = subprocess.run(["/bin/sh", "-c", body], cwd=root, input=data,
                                   capture_output=True, timeout=10)
            self.assertEqual(retry.returncode, 0, retry.stderr.decode())
            for path in required:
                self.assertEqual((destination / path).read_bytes(), b"test")
            (destination / "preserve").write_bytes(b"existing revision")
            duplicate = subprocess.run(["/bin/sh", "-c", body], cwd=root, input=data,
                                       capture_output=True, timeout=10)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertEqual((destination / "preserve").read_bytes(), b"existing revision")


if __name__ == "__main__":
    unittest.main()
