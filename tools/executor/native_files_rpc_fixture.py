"""Real stdio/policy/native-file round trips in a new private fixture.

Runs with native Linux Python or official Android/Bionic CPython packaged in
the APK. No PRoot, shell command, account or model is involved.
The Android service owns the fixture and provides all paths, never an Intent
payload. A failure remains a failure, including unavailable kernel operations.
"""
import argparse
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import time
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.executor.exec_server import decode_message
from tools.executor.native_files import NativeFilesBackend


def require(value, message):
    if not value:
        raise RuntimeError(message)


def file_hash(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def observation(pid="self", android_uid=None):
    proc = Path("/proc") / str(pid)
    status = {}
    for line in (proc / "status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in {"Uid", "Gid", "TracerPid", "Seccomp", "CapEff", "CapPrm", "NoNewPrivs"}:
            status[key] = value.strip()
    uids = [int(value) for value in status["Uid"].split()]
    gids = [int(value) for value in status["Gid"].split()]
    require(all(value != 0 for value in uids), "Fixture must execute without root")
    require(int(status["TracerPid"]) == 0, "Native endpoint must run outside a ptracer")
    require(int(status["CapEff"], 16) == 0 and int(status["CapPrm"], 16) == 0,
            "Fixture must execute without capabilities")
    maps = (proc / "maps").read_text()
    require("fake_userns" not in maps and "libproot" not in maps,
            "Native interpreter loaded a guest isolation shim")
    try:
        context = (proc / "attr/current").read_text().strip().rstrip("\x00")
    except OSError:
        context = None
    if android_uid is not None:
        require(uids == [android_uid] * 4 and int(status["Seccomp"]) == 2
                and context and context.startswith("u:r:untrusted_app"),
                "Fixture is not in the expected Android Zygote UID/filter/SELinux context")
    return {"uid": uids[0], "gid": gids[0], "status": status,
            "securityContext": context, "machine": os.uname().machine,
            "executable": os.readlink(proc / "exe"),
            "mappedFiles": sorted({line.split(maxsplit=5)[5] for line in maps.splitlines()
                                   if len(line.split(maxsplit=5)) == 6 and line.split(maxsplit=5)[5].startswith("/")})}


def context():
    return {"permissions": {"type": "managed",
        "file_system": {"type": "restricted", "entries": [
            {"path": {"type": "special", "value": {"kind": "root"}}, "access": "read"},
            {"path": {"type": "path", "path": "file:///workspace"}, "access": "write"},
            {"path": {"type": "path", "path": "file:///workspace/private"}, "access": "deny"},
            {"path": {"type": "path", "path": "file:///workspace/.git/allowed"}, "access": "write"}]},
        "network": "restricted"}, "cwd": "file:///workspace", "workspaceRoots": ["file:///workspace"],
        "userHomeDir": "file:///fixture-home", "temporaryDirectories": ["file:///fixture-tmp"],
        "windowsSandboxLevel": "disabled"}


class Peer:
    def __init__(self, command, workspace, evidence):
        self.trace = []
        self.identifier = 0
        self.pending = bytearray()
        self.error = None
        self.process = None
        self.selector = None
        try:
            self.error = (evidence / "server-stderr.txt").open("xb")
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=self.error, cwd=workspace, start_new_session=True,
                env={"PATH": os.environ["PATH"], "HOME": str(evidence / "home"),
                     "TMPDIR": str(evidence / "tmp"), "LANG": "C.UTF-8"})
            self.selector = selectors.DefaultSelector()
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
        except BaseException:
            self.close(False)
            raise

    def send(self, value):
        self.process.stdin.write(json.dumps(value, ensure_ascii=False).encode() + b"\n")
        self.process.stdin.flush()

    def call(self, method, params):
        self.identifier += 1
        self.send({"id": self.identifier, "method": method, "params": params})
        deadline = time.monotonic() + 10
        while b"\n" not in self.pending:
            remaining = deadline - time.monotonic()
            require(remaining > 0 and self.selector.select(remaining), "RPC response deadline expired")
            data = os.read(self.process.stdout.fileno(), 65536)
            require(data, "RPC server closed before its response")
            self.pending.extend(data)
            require(len(self.pending) <= 1048576, "RPC fixture response exceeds bound")
        line, _, tail = self.pending.partition(b"\n")
        self.pending = bytearray(tail)
        result = decode_message(line)
        require(result.get("id") == self.identifier and ("result" in result) != ("error" in result),
                "RPC response envelope differs")
        self.trace.append({"method": method, "params": params, "response": result})
        return result

    def close(self, expected):
        failure = None
        clean = False
        try:
            if self.process is None:
                return
            try:
                self.process.stdin.close()
            except OSError as error:
                failure = error
            try:
                code = self.process.wait(10)
            except subprocess.TimeoutExpired:
                # The server owns a fresh session, and its only children are
                # bounded native file helpers. Kill that entire fixture group.
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    self.process.wait(5)
                except subprocess.TimeoutExpired:
                    pass
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(5)
                raise RuntimeError("RPC server failed bounded EOF cleanup")
            if failure is not None:
                raise failure
            if expected:
                require(code == 0, "RPC server did not exit normally after EOF")
                require(not self.pending, "Unexpected buffered RPC output")
                # An inherited writer in an orphan helper must not block a
                # supposedly successful shutdown forever.
                require(self.selector.select(10), "RPC output remained open after server exit")
                require(not os.read(self.process.stdout.fileno(), 1), "Unexpected trailing RPC output")
            try:
                os.killpg(self.process.pid, 0)
            except ProcessLookupError:
                clean = True
            require(clean, "RPC server left a live process in its fixture group")
        finally:
            if self.process is not None and not clean:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(5)
            if self.selector is not None:
                self.selector.close()
            if self.process is not None:
                self.process.stdout.close()
            if self.error is not None:
                self.error.close()


def execute(args):
    evidence = args.evidence.resolve(strict=True)
    workspace = evidence / "workspace"
    for path in (workspace, evidence / "tmp", evidence / "home"):
        path.mkdir(mode=0o700)
    (workspace / ".git").mkdir(mode=0o700)
    (workspace / "private").mkdir(mode=0o700)
    for path, data in (("value", b"initial"), (".git/config", b"protected"), ("private/secret", b"private")):
        (workspace / path).write_bytes(data)
    native = args.helper.resolve(strict=True)
    observed = observation(android_uid=args.android_uid)
    observed["python"] = sys.version
    if args.android_home:
        require(args.android_uid is not None and observed["machine"] == "aarch64"
                and sys.platform == "android", "Bionic fixture requires native Android Python")
        launcher = Path(sys.executable).resolve(strict=True)
        prefix = [str(launcher), "--home", str(args.android_home.resolve(strict=True)), "--"]
        flags = []
        observed["androidLauncherSha256"] = file_hash(launcher)
    elif args.runtime:
        runtime = args.runtime.resolve(strict=True)
        library = runtime / "usr/lib/aarch64-linux-gnu"
        interpreter = runtime / "usr/bin/python3.13"
        original_loader = library / "ld-linux-aarch64.so.1"
        loader = args.loader.resolve(strict=True) if args.loader else original_loader
        require(file_hash(loader) == file_hash(original_loader), "Packaged loader differs from the current GNU runtime")
        prefix = [str(loader), "--library-path", str(library), str(interpreter)]
        require(observed["machine"] == "aarch64", "Android fixture requires actual ARM64")
        observed["runtimeHashes"] = {str(path.relative_to(runtime)): file_hash(path)
                                     for path in (original_loader, interpreter, library / "libc.so.6")}
        observed["packagedLoader"] = str(loader)
        flags = ["-I", "-S", "-B", "-X", "utf8"]
    else:
        prefix = [sys.executable]
        flags = ["-I", "-S", "-B", "-X", "utf8"]
    command = prefix + flags + [str(Path(__file__).with_name("native_files_server.py")),
                       "--helper", str(native), "--workspace", str(workspace), "--guest-workspace", "/workspace"]
    checks = []
    passed = False
    initial = (workspace / "value").stat()
    peer = Peer(command, workspace, evidence)

    def invoke(method, name, policy=None, **fields):
        return peer.call(method, {"path": "file:///workspace/" + quote(name, safe="/"),
                                 "sandbox": context() if policy is None else policy, **fields})

    def success(value):
        require("result" in value, "Expected a real native RPC success: " + json.dumps(value))
        return value["result"]

    def refused(value, code=-32000):
        require("error" in value, "Forbidden operation unexpectedly succeeded")
        if code is not None:
            require(value["error"]["code"] == code, "Unexpected native refusal semantics")

    try:
        handshake = success(peer.call("initialize", {"clientName": "foldgpt-native-files-device-fixture"}))
        require(handshake["sessionId"] and not any(handshake["environmentInfo"]["capabilities"].values()),
                "File backend advertised an unsupported optional capability")
        peer.send({"method": "initialized"})
        require(success(peer.call("environment/status", {}))["status"] == "ready", "Transport not ready")
        observed_server = observation(peer.process.pid, args.android_uid)
        checks.append("actual-stdio-initialize")
        expected = b"initial"
        for index, access in enumerate(("write", "read", "deny", "write")):
            policy = context()
            policy["permissions"]["file_system"]["entries"].append({
                "path": {"type": "path", "path": "file:///workspace/value"}, "access": access})
            read = invoke("fs/readFile", "value", policy)
            meta = invoke("fs/getMetadata", "value", policy)
            canonical = invoke("fs/canonicalize", "value", policy)
            if access == "deny":
                for value in (read, meta, canonical):
                    refused(value)
                    require(value["error"]["code"] != -32004, "Denial was disguised as absence")
            else:
                require(base64.b64decode(success(read)["dataBase64"]) == expected, "Native read bytes differ")
                current = (workspace / "value").stat()
                metadata = success(meta)
                require(metadata["isFile"] and not metadata["isDirectory"] and not metadata["isSymlink"]
                        and metadata["size"] == current.st_size
                        and metadata["modifiedAtMs"] == current.st_mtime_ns // 1000000,
                        "RPC metadata differs from independent native stat")
                require(success(canonical) == {"path": "file:///workspace/value"}, "Canonical guest URI differs")
            data = ("native-write-" + str(index)).encode()
            write = invoke("fs/writeFile", "value", policy, dataBase64=base64.b64encode(data).decode())
            if access == "write":
                require(success(write) == {}, "Invalid write response")
                expected = data
            else:
                refused(write)
            current = (workspace / "value").stat()
            require((current.st_dev, current.st_ino, stat.S_IMODE(current.st_mode), current.st_nlink) ==
                    (initial.st_dev, initial.st_ino, stat.S_IMODE(initial.st_mode), initial.st_nlink)
                    and (workspace / "value").read_bytes() == expected, "A/B/C/A physical invariant differs")
            checks.append("same-inode-" + str(index) + "-" + access)

        for name in (".git/config", "private/secret"):
            refused(invoke("fs/writeFile", name, dataBase64=base64.b64encode(b"forbidden").decode()))
        refused(invoke("fs/readFile", "private/secret"))
        require((workspace / ".git/config").read_bytes() == b"protected"
                and (workspace / "private/secret").read_bytes() == b"private", "Protected bytes changed")
        success(invoke("fs/createDirectory", ".git/allowed/child"))
        refused(invoke("fs/createDirectory", ".git/forbidden/child"))
        require(not (workspace / ".git/forbidden").exists(), "Denied metadata ancestor created")
        checks.append("metadata-protection-and-explicit-exception")
        name = "dossier é/子"
        success(invoke("fs/createDirectory", name))
        success(invoke("fs/writeFile", name + "/data", dataBase64=base64.b64encode(b"actual\x00bytes").decode()))
        require((workspace / name / "data").read_bytes() == b"actual\x00bytes", "UTF-8 path write differs")
        require(stat.S_IMODE((workspace / name).stat().st_mode) == 0o700, "Native directory mode differs")
        success(invoke("fs/canonicalize", name + "/data"))
        checks.append("unicode-directories-and-binary-data")
        policy = context()
        policy["permissions"]["file_system"]["entries"].extend([
            {"path": {"type": "path", "path": "file:///workspace/missing/middle"}, "access": "deny"},
            {"path": {"type": "path", "path": "file:///workspace/missing/middle/leaf"}, "access": "write"}])
        refused(invoke("fs/createDirectory", "missing/middle/leaf", policy))
        require(not (workspace / "missing").exists(), "Denied ancestor plan mutated the workspace")
        checks.append("denied-ancestor-before-mutation")
        for method in ("fs/readFile", "fs/getMetadata", "fs/canonicalize"):
            refused(invoke(method, "absent"), -32004)
        refused(invoke("fs/writeFile", "absent", None, dataBase64="!"), -32602)
        malformed = copy.deepcopy(context())
        malformed["permissions"]["file_system"]["unsupported"] = True
        refused(invoke("fs/createDirectory", "absent", malformed))
        require(not (workspace / "absent").exists(), "Malformed request mutated the workspace")
        checks.append("missing-vs-denied-and-malformed")
        (workspace / "alias").symlink_to("value")
        refused(invoke("fs/writeFile", "alias", dataBase64=base64.b64encode(b"forbidden").decode()))
        (workspace / "alias").unlink()
        require((workspace / "value").read_bytes() == expected, "Alias changed protected target")
        checks.append("backend-alias-refusal")
        refused(peer.call("process/start", {"processId": "unsupported", "argv": ["/system/bin/true"],
            "cwd": "file:///workspace", "env": {}, "tty": False, "sandbox": context()}), -32601)
        checks.append("no-process-capability-substitution")
        passed = True
    finally:
        try:
            peer.close(passed)
        finally:
            (evidence / "rpc-transcript.json").write_text(json.dumps(peer.trace, indent=2) + "\n")
    # A new real backend must acquire the exact workspace lease after pipe EOF.
    import asyncio
    backend = NativeFilesBackend(native, workspace)
    asyncio.run(backend.close(None))
    checks.append("eof-releases-native-workspace-lease")
    return {"schema": "foldgpt.native-files-rpc-fixture.v1", "status": "PASS", "checks": checks,
            "rpcResponses": len(peer.trace), "nativeHelperSha256": file_hash(native), "observation": observed,
            "serverObservation": observed_server,
            "workspace": {"path": str(workspace), "device": initial.st_dev, "valueInode": initial.st_ino},
            "limit": "Supported file RPCs in an exclusive fixture; not arbitrary managed processes or a production environment"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--helper", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--loader", type=Path)
    parser.add_argument("--android-uid", type=int)
    parser.add_argument("--android-home", type=Path)
    args = parser.parse_args()
    result = execute(args)
    (args.evidence / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
