#!/usr/bin/env python3
"""Fixed two-process filesystem measurement; does not launch either runtime.

Use a fresh, already-created private directory. Record the actual native launcher in the outer evidence. The controller must use the real
desktop PRoot command construction with an exact W:W bind. This script installs
no sandbox, uses no ptrace, and changes only its fresh qualification directory.
The measured filesystem facts do not by themselves qualify the production launch or UI.
"""
import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

SCHEMA = "foldgpt.shared-path-measurement.v1"
LIMIT = 65536


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def kernel_identity():
    selected = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"Pid", "PPid", "TracerPid", "Uid", "Gid", "Seccomp", "NoNewPrivs"}:
            selected[key] = [int(item) for item in value.split()]
    return selected


def signature(info):
    return {"device": info.st_dev, "inode": info.st_ino,
            "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid,
            "gid": info.st_gid, "size": info.st_size}


class Measurement:
    def __init__(self, args):
        self.args = args
        self.deadline = time.monotonic() + args.timeout
        self.path = Path(args.workspace)
        require(self.path.is_absolute() and str(self.path) == args.workspace,
                "Workspace must be normalized and absolute")
        require(str(self.path.resolve(strict=True)) == args.workspace,
                "Workspace must be canonical; aliases are not evidence of sharing")
        self.root = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(self.root)
        require(stat.S_IMODE(info.st_mode) == 0o700, "Workspace must already be 0700")
        self.identity = kernel_identity()
        require(self.identity.get("Uid") == [args.kernel_uid] * 4,
                "Measured kernel UIDs differ from the launcher's expected app UID")
        require(args.kernel_uid != 0, "No root measurement")
        if args.role == "native":
            require(info.st_uid == args.kernel_uid, "Native workspace owner differs")
            require(os.listdir(self.root) == [], "Native measurement requires a fresh empty workspace")
        os.chdir(self.path)
        require(os.getcwd() == args.workspace, "Controller/native cwd differs from the canonical workspace")
        self.report = {"schema": SCHEMA, "role": args.role, "status": "running",
                       "workspace": args.workspace, "root": signature(info),
                       "cwd": os.getcwd(), "procCwd": os.readlink("/proc/self/cwd"),
                       "kernel": self.identity, "libcUid": os.getuid(),
                       "libcGid": os.getgid(), "executable": sys.executable,
                       "platform": sys.platform, "home": os.environ.get("HOME"),
                       "tmpdir": os.environ.get("TMPDIR")}

    def create(self, name, data):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self.root)
        try:
            view = memoryview(data)
            while view:
                count = os.write(fd, view)
                require(count > 0, "Incomplete write")
                view = view[count:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self.root)

    def create_json(self, name, value):
        self.create(name, (json.dumps(value, sort_keys=True) + "\n").encode())

    def read(self, name):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self.root)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= LIMIT,
                    "Invalid measurement file")
            chunks = []
            remaining = LIMIT + 1
            while remaining:
                chunk = os.read(fd, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            require(len(data) <= LIMIT, "Measurement exceeds bound")
            return data, signature(info)
        finally:
            os.close(fd)

    def wait(self, name):
        # Readiness is an explicit exclusive, fully fsynced commit file; data
        # files are always published before that commit by the opposite side.
        while time.monotonic() < self.deadline:
            try:
                data, _ = self.read(name)
                if data == b"ready\n":
                    return
                raise RuntimeError("Malformed readiness marker")
            except FileNotFoundError:
                time.sleep(0.025)
        raise TimeoutError("Shared path handshake deadline: " + name)

    def ready(self, name):
        # Rename from a complete temporary file prevents a concurrent read of
        # an empty marker. Every name is one-use in this new directory.
        temporary = name + ".pending"
        self.create(temporary, b"ready\n")
        os.rename(temporary, name, src_dir_fd=self.root, dst_dir_fd=self.root)
        os.fsync(self.root)

    def contended(self):
        try:
            fcntl.flock(self.root, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            require(error.errno in (errno.EAGAIN, errno.EWOULDBLOCK), "Unexpected flock error")
            return error.errno
        fcntl.flock(self.root, fcntl.LOCK_UN)
        raise RuntimeError("Expected another real open-file-description to hold the same inode lock")

    def native(self):
        fcntl.flock(self.root, fcntl.LOCK_EX | fcntl.LOCK_NB)
        payload = bytes(range(256)) + "natif â†’ contrÃ´leur\n".encode() + os.urandom(32)
        self.create("native.bytes", payload)
        _, identity = self.read("native.bytes")
        self.report["nativeBytes"] = {"sha256": hashlib.sha256(payload).hexdigest(), **identity}
        self.create_json("native.identity.json", self.report)
        self.ready("native.ready")
        self.wait("controller.read.done")
        moved, moved_identity = self.read("native.renamed")
        require(moved == payload and moved_identity["inode"] == identity["inode"]
                and moved_identity["device"] == identity["device"], "Controller rename changed original inode/bytes")
        reply, reply_identity = self.read("controller.bytes")
        require(reply == b"controller-reply\0" + payload[::-1], "Controller bytes differ")
        self.report["controllerBytes"] = {"sha256": hashlib.sha256(reply).hexdigest(), **reply_identity}
        fcntl.flock(self.root, fcntl.LOCK_UN)
        self.ready("native.unlocked")
        self.wait("controller.locked")
        self.report["nativeBlockedByControllerErrno"] = self.contended()
        self.ready("native.contention.done")
        self.wait("controller.unlocked")
        fcntl.flock(self.root, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(self.root, fcntl.LOCK_UN)
        self.report["reacquiredAfterControllerRelease"] = True

    def controller(self):
        self.wait("native.ready")
        native = json.loads(self.read("native.identity.json")[0])
        for key in ("device", "inode"):
            require(native["root"][key] == self.report["root"][key], "Root identity mismatch: " + key)
        require(native["workspace"] == self.args.workspace, "Native canonical path differs")
        payload, identity = self.read("native.bytes")
        require(hashlib.sha256(payload).hexdigest() == native["nativeBytes"]["sha256"], "Native bytes differ")
        for key in ("device", "inode"):
            require(identity[key] == native["nativeBytes"][key], "File identity mismatch: " + key)
        self.report["nativeBytes"] = {"sha256": hashlib.sha256(payload).hexdigest(), **identity}
        self.report["controllerBlockedByNativeErrno"] = self.contended()
        # This intentionally demonstrates that flock is advisory: a legitimate
        # controller writer can ignore it. Passing does NOT prove write ordering.
        self.create("controller.bytes", b"controller-reply\0" + payload[::-1])
        os.rename("native.bytes", "native.renamed", src_dir_fd=self.root, dst_dir_fd=self.root)
        os.fsync(self.root)
        self.report["unleasedWriterCanMutate"] = True
        self.ready("controller.read.done")
        self.wait("native.unlocked")
        fcntl.flock(self.root, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.ready("controller.locked")
        self.wait("native.contention.done")
        fcntl.flock(self.root, fcntl.LOCK_UN)
        self.ready("controller.unlocked")

    def run(self):
        try:
            getattr(self, self.args.role)()
            self.report["status"] = "passed"
            self.create_json(self.args.role + ".result.json", self.report)
            print(json.dumps(self.report, sort_keys=True), flush=True)
        except BaseException as error:
            self.report.update(status="failed", error=str(error), errorType=type(error).__name__)
            print(json.dumps(self.report, sort_keys=True), flush=True)
            raise
        finally:
            os.close(self.root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("native", "controller"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--kernel-uid", required=True, type=int)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    require(0 < args.timeout <= 60, "Qualification timeout must be positive and at most 60 seconds")
    Measurement(args).run()


if __name__ == "__main__":
    main()
