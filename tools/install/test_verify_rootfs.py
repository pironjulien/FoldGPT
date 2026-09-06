"""Path, architecture and pristine-state regression tests; no guest execution."""
import importlib.util
from pathlib import Path
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("verify_rootfs", Path(__file__).with_name("verify_rootfs.py"))
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def elf_header(machine=183):
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHI", header, 16, 3, machine, 1)
    struct.pack_into("<H", header, 52, 64)
    return bytes(header)


class RootfsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="foldgpt-rootfs-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    @unittest.skipUnless(sys.platform == "linux", "Requires actual guest symlinks")
    def test_absolute_guest_links_stay_inside_guest_not_host(self):
        target = self.write("usr/lib/target", b"guest fixture")
        (self.root / "bin").symlink_to("/usr/lib", target_is_directory=True)
        self.assertEqual(VERIFY.guest_path(self.root, "/bin/target"), target)
        self.assertEqual(VERIFY.read_guest(self.root, "bin/target"), b"guest fixture")

    @unittest.skipUnless(sys.platform == "linux", "Requires actual guest symlinks")
    def test_rejects_above_root_links_and_link_cycles(self):
        (self.root / "escape").symlink_to("../outside")
        with self.assertRaises(VERIFY.VerificationError):
            VERIFY.guest_path(self.root, "escape")
        (self.root / "cycle1").symlink_to("cycle2")
        (self.root / "cycle2").symlink_to("cycle1")
        with self.assertRaises(VERIFY.VerificationError):
            VERIFY.guest_path(self.root, "cycle1")

    def test_binary_machine_is_verified_from_elf_header(self):
        path = self.write("usr/bin/dash", elf_header())
        path.chmod(0o755)
        self.assertEqual(VERIFY.verify_elf(self.root, "usr/bin/dash")["machine"], "AArch64")
        path.write_bytes(elf_header(machine=62))
        with self.assertRaises(VERIFY.VerificationError):
            VERIFY.verify_elf(self.root, "usr/bin/dash")

    def pristine_accounts(self):
        self.write("etc/passwd", b"root:x:0:0:root:/root:/bin/bash\nnobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n")
        self.write("etc/shadow", b"root:*:1:0:99999:7:::\nnobody:!:1:0:99999:7:::\n")
        (self.root / "home").mkdir()
        (self.root / "root").mkdir()

    def test_system_accounts_must_be_locked_and_human_home_empty(self):
        self.pristine_accounts()
        self.assertEqual(VERIFY.verify_accounts(self.root)["humanAccounts"], 0)
        self.write("home/personal-marker", b"fixture")
        with self.assertRaises(VERIFY.VerificationError):
            VERIFY.verify_accounts(self.root)

    def test_unlocked_password_is_rejected_without_printing_it(self):
        self.pristine_accounts()
        self.write("etc/shadow", b"root:fixture-secret-hash:1:0:99999:7:::\nnobody:!:1:0:99999:7:::\n")
        with self.assertRaises(VERIFY.VerificationError) as failure:
            VERIFY.verify_accounts(self.root)
        self.assertNotIn("fixture-secret", str(failure.exception))

    def test_minimal_debian_passwd_only_format_requires_direct_locked_markers(self):
        self.pristine_accounts()
        (self.root / "etc/shadow").unlink()
        with self.assertRaises(VERIFY.VerificationError):
            VERIFY.verify_accounts(self.root)
        path = self.root / "etc/passwd"
        path.write_bytes(path.read_bytes().replace(b":x:", b":*:"))
        report = VERIFY.verify_accounts(self.root)
        self.assertTrue(report["passwordsLocked"])
        self.assertEqual(report["passwordDatabase"], "locked-passwd")

    def test_machine_identity_must_be_uninitialized_and_dns_neutral(self):
        self.write("etc/hostname", b"foldgpt\n")
        self.write("etc/resolv.conf", VERIFY.DNS_TEMPLATE)
        self.write("etc/hosts", b"127.0.0.1 localhost\n::1 localhost ip6-localhost ip6-loopback\n")
        self.write("etc/machine-id", b"")
        VERIFY.verify_identity(self.root)
        self.write("etc/machine-id", b"0123456789abcdef0123456789abcdef\n")
        with self.assertRaises(VERIFY.VerificationError):
            VERIFY.verify_identity(self.root)

    def test_archive_keyrings_allowed_but_renamed_foreign_emulator_rejected(self):
        for name in ("tmp", "run", "proc", "sys", "dev"):
            (self.root / name).mkdir()
        self.write("usr/share/keyrings/debian-archive-keyring.gpg", b"fixture trust store")
        self.assertEqual(VERIFY.verify_pristine_tree(self.root)["regularFiles"], 1)
        (self.root / "run/lock").mkdir()
        VERIFY.verify_pristine_tree(self.root)
        marker = self.write("run/lock/live-state", b"fixture")
        with self.assertRaises(VERIFY.VerificationError):
            VERIFY.verify_pristine_tree(self.root)
        marker.unlink()
        self.write("usr/bin/innocent-name", elf_header(machine=62))
        with self.assertRaises(VERIFY.VerificationError):
            VERIFY.verify_pristine_tree(self.root)

    def test_incomplete_foreign_or_duplicate_package_status_rejected(self):
        rows = [f"{name}\t1.0\tarm64\tinstall ok installed" for name in sorted(VERIFY.REQUIRED_PACKAGES | {"mawk"})]
        valid = "\n".join(rows)
        self.assertGreater(len(VERIFY.package_inventory(valid)), 0)
        for invalid in (valid.replace("arm64", "amd64", 1), valid.replace("install ok installed", "install ok unpacked", 1),
                        valid + "\n" + rows[0]):
            with self.subTest(invalid=invalid[:40]), self.assertRaises(VERIFY.VerificationError):
                VERIFY.package_inventory(invalid)

    @unittest.skipUnless(sys.platform == "linux" and hasattr(os, "geteuid") and os.geteuid() == 0
                         and shutil.which("cc"), "Requires host Linux root and static C compiler")
    def test_real_probe_root_is_readonly_and_null_device_is_ephemeral(self):
        (self.root / "dev").mkdir()
        marker = self.write("marker", b"must stay unchanged")
        source = b'''#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
int main(void) {
    int fd = open("/marker", O_WRONLY | O_TRUNC);
    if (fd >= 0) { close(fd); return 1; }
    if (errno != EROFS) return 2;
    fd = open("/dev/null", O_RDWR);
    if (fd < 0) return 3;
    close(fd);
    return 0;
}
'''
        subprocess.run(["cc", "-x", "c", "-static", "-O2", "-", "-o", str(self.root / "probe")],
                       input=source, check=True, capture_output=True)
        self.assertEqual(VERIFY.probe(self.root, ["/probe"]), "")
        self.assertEqual(marker.read_bytes(), b"must stay unchanged")
        self.assertEqual(list((self.root / "dev").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
