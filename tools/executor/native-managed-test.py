"""Kernel conformance for the private managed acquisition increment."""
import argparse
from dataclasses import asdict
import errno
import json
import os
from pathlib import Path
import signal
import stat
import sys
import tempfile
import time
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.executor.native_process_policy import NativeProcessPolicy, run_native_managed

RUNNER = FIXTURE = PARENT = EVIDENCE = None
ADDRESS_SPACE_BYTES = 256 * 1024 * 1024
UID_TASK_BUDGET = 128
OBSERVATIONS = []


def context(access="write", entries=()):
    def entry(path, value):
        return {"path": {"type": "path", "path": "file:///workspace" + path}, "access": value}
    return {"permissions": {"type": "managed", "file_system": {"type": "restricted", "entries": [
        entry("", access), entry("/private", "deny"), entry("/private/readable", "read"), *entries]}, "network": "restricted"},
        "cwd": "file:///workspace", "workspaceRoots": ["file:///workspace"], "useLegacyLandlock": False,
        "windowsSandboxLevel": "disabled", "windowsSandboxPrivateDesktop": False}


class ManagedKernelTests(unittest.TestCase):
    def setUp(self):
        self.assertNotEqual(os.getuid(), 0)
        self.temporary = tempfile.TemporaryDirectory(prefix="managed-kernel-", dir=PARENT)
        self.work = Path(self.temporary.name)
        self.root = self.work / "workspace"
        self.root.mkdir(mode=0o700)
        for directory in ("private", ".git", "nested", "nested/.agents"):
            (self.root / directory).mkdir(mode=0o700)
        for path, data in (("value", b"first-native-value"), ("public", b"permitted-other"),
                           ("private/secret", b"private-native-value"), ("private/readable", b"narrower-read"),
                           (".git/config", b"protected-metadata"), ("nested/.agents/config", b"nested-protected")):
            (self.root / path).write_bytes(data)
            (self.root / path).chmod(0o600)
        (self.work / "outside").write_bytes(b"outside-intact")

    def tearDown(self):
        self.temporary.cleanup()

    def run_case(self, args, policy=None, **options):
        options.setdefault("address_space_bytes", ADDRESS_SPACE_BYTES)
        options.setdefault("uid_task_budget", UID_TASK_BUDGET)
        result = run_native_managed(RUNNER, FIXTURE, self.root, context() if policy is None else policy,
                                   [str(FIXTURE), *args], **options)
        OBSERVATIONS.append({"test": self.id(), "args": args, "returncode": result.returncode,
                             "events": result.events, "stdoutHex": result.stdout.hex(), "stderrHex": result.stderr.hex(),
                             "decisions": result.decisions})
        return result

    def complete(self, result, *, outcome="exited", exit_code=0):
        self.assertTrue(result.events, result)
        final = result.events[-1]
        self.assertEqual(final["type"], "result", result)
        self.assertEqual(final["outcome"], outcome, result)
        self.assertTrue(final["cleanupComplete"], result)
        self.assertEqual(final["stdoutBytes"], len(result.stdout), result)
        self.assertEqual(final["stderrBytes"], len(result.stderr), result)
        if outcome == "exited":
            self.assertEqual(result.returncode, 0, result)
            self.assertEqual(final["exitCode"], exit_code, result)
            self.assertTrue(final["started"], result)
            self.assertEqual(sum(item["type"] == "started" for item in result.events), 1)
            with self.assertRaises(ProcessLookupError):
                os.kill(result.events[0]["pid"], 0)
        return final

    def opening(self, path="value", *, kind=0, flags=os.O_RDONLY, error=0, marker="", policy=None, **options):
        return self.run_case(["open", str(kind), path, str(flags), str(error), marker], policy, **options)

    def test_01_real_exec_and_brokered_open_positive_control(self):
        result = self.opening()
        final = self.complete(result)
        self.assertEqual(result.stdout, b"first-native-value")
        self.assertEqual(final["grants"], 1)
        self.assertEqual(result.decisions[0]["path"], "file:///workspace/value")

    def test_02_same_inode_write_read_deny_write(self):
        inode = (self.root / "value").stat().st_ino
        result = self.opening(flags=os.O_RDWR | os.O_TRUNC, marker="first-write")
        self.complete(result)
        self.assertEqual((self.root / "value").read_bytes(), b"first-write")
        self.complete(self.opening(policy=context("read")))
        self.complete(self.opening(flags=os.O_WRONLY, error=errno.EACCES, policy=context("read")))
        self.assertEqual((self.root / "value").read_bytes(), b"first-write")
        self.complete(self.opening(error=errno.EACCES, policy=context("deny")))
        self.complete(self.opening(flags=os.O_WRONLY, error=errno.EACCES, policy=context("deny")))
        self.complete(self.opening("private/readable", policy=context("deny")))
        self.complete(self.opening(flags=os.O_WRONLY | os.O_TRUNC, marker="last-write"))
        self.assertEqual((self.root / "value").read_bytes(), b"last-write")
        self.assertEqual((self.root / "value").stat().st_ino, inode)

    def test_03_nested_deny_and_narrower_read_and_write(self):
        for flags in (os.O_RDONLY, os.O_WRONLY, os.O_RDWR):
            self.complete(self.opening("private/secret", flags=flags, error=errno.EACCES))
        result = self.opening("private/readable")
        self.complete(result)
        self.assertEqual(result.stdout, b"narrower-read")
        self.complete(self.opening("private/readable", flags=os.O_WRONLY, error=errno.EACCES))
        grant = {"path": {"type": "path", "path": "file:///workspace/private/secret"}, "access": "write"}
        self.complete(self.opening("private/secret", flags=os.O_WRONLY | os.O_TRUNC, marker="explicit-write",
                                   policy=context(entries=[grant])))
        self.assertEqual((self.root / "private/secret").read_bytes(), b"explicit-write")

    def test_04_metadata_preserved_and_explicit_exception_works(self):
        for path in (".git/config", "nested/.agents/config"):
            old = (self.root / path).read_bytes()
            self.complete(self.opening(path, flags=os.O_WRONLY | os.O_TRUNC, error=errno.EACCES))
            self.assertEqual((self.root / path).read_bytes(), old)
        grant = {"path": {"type": "path", "path": "file:///workspace/.git/config"}, "access": "write"}
        self.complete(self.opening(".git/config", flags=os.O_WRONLY | os.O_TRUNC, marker="explicit-metadata",
                                   policy=context(entries=[grant])))
        self.assertEqual((self.root / ".git/config").read_bytes(), b"explicit-metadata")

    def test_05_all_native_acquisition_syscalls_and_absolute_paths(self):
        kinds = [0, 1] + ([2] if os.uname().machine == "x86_64" else [])
        for kind in kinds:
            with self.subTest(kind=kind):
                self.complete(self.opening(kind=kind))
                self.complete(self.opening("private/secret", kind=kind, error=errno.EACCES))
                self.complete(self.opening(str(self.root / "value"), kind=kind))
        self.complete(self.opening(str(self.work / "outside"), error=errno.EPERM))
        self.complete(self.opening("../outside", error=errno.EPERM))
        self.assertEqual((self.work / "outside").read_bytes(), b"outside-intact")

    def test_06_real_creation_exclusive_missing_and_creation_denial(self):
        self.complete(self.opening("new", flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL, marker="created"))
        self.assertEqual((self.root / "new").read_bytes(), b"created")
        self.assertEqual(stat.S_IMODE((self.root / "new").stat().st_mode), 0o600)
        self.complete(self.opening("new", flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL, error=errno.EEXIST))
        self.complete(self.opening("absent", error=errno.ENOENT))
        self.complete(self.opening("private/new", flags=os.O_WRONLY | os.O_CREAT, error=errno.EACCES))
        self.assertFalse((self.root / "private/new").exists())
        self.complete(self.opening(".codex", flags=os.O_WRONLY | os.O_CREAT, error=errno.EACCES))
        self.assertFalse((self.root / ".codex").exists())

    def test_07_nonzero_exit_is_a_real_command_result(self):
        self.complete(self.run_case(["exit", "17"]), exit_code=17)

    def test_08_timeout_and_cancellation_reap_native_child(self):
        self.complete(self.run_case(["sleep"], wall_ms=200), outcome="timeout")
        self.complete(self.run_case(["sleep"], cancel_after=0.1), outcome="cancelled")

    def test_09_actual_forked_descendant_is_reaped_on_timeout(self):
        result = self.run_case(["fork"], wall_ms=300)
        self.complete(result, outcome="timeout")
        self.assertTrue(result.stdout.startswith(b"CHILD:"), result)
        pid = int(result.stdout.strip().split(b":")[1])
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_10_corrupt_private_response_cannot_admit_any_write(self):
        original = (self.root / "value").read_bytes()
        for transform in (lambda request, reply: {**reply, "id": reply["id"] ^ 1},
                          lambda request, reply: {**reply, "unknown": 1},
                          lambda request, reply: b'{"allow":1,"allow":1}'):
            result = self.opening(flags=os.O_WRONLY | os.O_TRUNC, marker="must-not-write", reply_transform=transform)
            self.complete(result, outcome="broker_error")
            self.assertEqual((self.root / "value").read_bytes(), original)

    def test_11_native_rejects_stale_identity_before_truncation(self):
        original = (self.root / "value").read_bytes()
        result = self.opening(flags=os.O_WRONLY | os.O_TRUNC, error=errno.ESTALE,
                              reply_transform=lambda request, reply: {**reply, "inode": reply["inode"] + 1})
        self.complete(result)
        self.assertEqual((self.root / "value").read_bytes(), original)

    def test_12_unsupported_policy_rejected_before_spawn_and_lease_released(self):
        bad = context()
        bad["permissions"]["network"] = "enabled"
        with self.assertRaises(ValueError):
            self.run_case(["exit"], bad)
        bad = context()
        bad["unreviewed"] = True
        with self.assertRaises(ValueError):
            self.run_case(["exit"], bad)
        self.complete(self.opening())

    def test_13_real_uid_task_accounting_matches_the_installed_child_limit(self):
        result = self.run_case(["resources"])
        self.complete(result)
        started = result.events[0]
        expected = min(started["uidTasksObserved"] + UID_TASK_BUDGET,
                       started["inheritedNprocSoft"], started["inheritedNprocHard"])
        self.assertEqual(started["uidTaskBudget"], UID_TASK_BUDGET)
        self.assertEqual(started["uidNprocLimit"], expected)
        self.assertEqual(result.stdout, f"{expected}:{expected}\n".encode())
        self.assertGreater(expected, started["uidTasksObserved"])

    def test_14_network_cwd_namespace_metadata_and_inherited_descriptors(self):
        result = self.run_case(["isolation"])
        self.complete(result)
        self.assertEqual(result.stdout, b"ISOLATION\n")
        self.assertFalse((self.root / "unsupported-directory").exists())

    def test_15_requested_file_flags_survive_actual_fd_injection(self):
        for flags in (os.O_RDONLY | os.O_CLOEXEC, os.O_RDONLY | os.O_NONBLOCK, os.O_WRONLY | os.O_APPEND):
            self.complete(self.opening(flags=flags))

    @staticmethod
    def mutate_tracee(message, field, data):
        # The trusted test parent deliberately changes the *original* tracee
        # memory only after the native supervisor has copied and reported it.
        # This is a real deterministic TOCTOU challenge, not a mocked syscall.
        import ctypes
        class IOVector(ctypes.Structure):
            _fields_ = [("base", ctypes.c_void_p), ("length", ctypes.c_size_t)]
        libc = ctypes.CDLL(None, use_errno=True)
        operation = libc.process_vm_writev
        operation.argtypes = [ctypes.c_int, ctypes.POINTER(IOVector), ctypes.c_ulong,
                              ctypes.POINTER(IOVector), ctypes.c_ulong, ctypes.c_ulong]
        operation.restype = ctypes.c_ssize_t
        source = ctypes.create_string_buffer(data)
        local = IOVector(ctypes.addressof(source), len(data))
        remote = IOVector(message[field], len(data))
        count = operation(message["pid"], ctypes.byref(local), 1, ctypes.byref(remote), 1, 0)
        if count != len(data):
            raise RuntimeError(f"Actual tracee mutation positive control failed: bytes={count}, errno={ctypes.get_errno()}")

    def test_16_copied_path_cannot_be_replaced_with_a_denied_target(self):
        def change(request, reply):
            self.assertEqual(request["pathHex"], b"value".hex())
            self.mutate_tracee(request, "pathAddress", b"private/secret\0")
            return reply
        result = self.opening(reply_transform=change)
        self.complete(result)
        self.assertEqual(result.stdout, b"first-native-value")
        self.assertEqual((self.root / "private/secret").read_bytes(), b"private-native-value")

    def test_17_copied_open_how_cannot_gain_truncating_write_flags(self):
        import struct
        def change(request, reply):
            self.assertEqual(request["flags"], os.O_RDONLY)
            self.assertNotEqual(request["howAddress"], 0)
            self.mutate_tracee(request, "howAddress", struct.pack("<QQQ", os.O_RDWR | os.O_TRUNC, 0, 0))
            return reply
        result = self.opening(kind=1, policy=context("read"), reply_transform=change)
        self.complete(result)
        self.assertEqual(result.stdout, b"first-native-value")
        self.assertEqual((self.root / "value").read_bytes(), b"first-native-value")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--address-space-bytes", type=int, default=256 * 1024 * 1024)
    parser.add_argument("--uid-task-budget", type=int, default=128)
    args, remaining = parser.parse_known_args()
    RUNNER, FIXTURE, PARENT, EVIDENCE = args.runner, args.fixture, args.parent, args.evidence
    ADDRESS_SPACE_BYTES = args.address_space_bytes
    UID_TASK_BUDGET = args.uid_task_budget
    program = unittest.main(argv=[sys.argv[0], *remaining], exit=False, verbosity=2)
    if EVIDENCE:
        EVIDENCE.write_text(json.dumps({"schema": "foldgpt.native-managed-acquisition.v1", "uid": os.getuid(),
                                       "platform": list(os.uname()), "successful": program.result.wasSuccessful(),
                                       "observations": OBSERVATIONS}, indent=2) + "\n")
    sys.exit(0 if program.result.wasSuccessful() else 1)
