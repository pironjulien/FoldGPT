"""Offline managed-policy probe for the official Codex exec-server, not a sandbox.

Protocol pinned to rust-v0.153.4 (042fb41b7c813ac7999105e886b2b7aa715b5081):
exec-server/src/connection.rs:279-370,658-671: UTF-8 JSON per line, no jsonrpc key;
exec-server-protocol/src/protocol.rs:19-42,76-140,256-290,333-363,418-588;
file-system/src/lib.rs:174-210,237-291,330-348: FileSystemSandboxContext.

Run ONLY as the fixed Python worker of a reviewed native launcher that applies
its Landlock/seccomp boundary BEFORE PRoot/Python. That launcher must create the
same fresh /foldgpt-fixture and /outside marker tree as probe-landlock-codex.c,
bind private scratch at /tmp, replace the preload for this diagnostic, and set:
  FOLDGPT_NATIVE_EXEC_SERVER_PROBE=1
  FOLDGPT_NATIVE_EXEC_SERVER_LAUNCHER=<its absolute, readable native ELF path>
The existing command/exec launcher does not set this separate contract: direct
execution therefore fails. These guards are not cryptographic attestation;
actual non-destructive write refusals and socket denial are also required.

Only fixed process/start, process/read and fs/* requests are sent. No app-server,
thread/turn, account, model, HTTP, or remote-registration requests are possible.
Every tested operation carries a managed policy, never external/disabled. The
official executor may still fail on Android namespaces; that is a FAILED stage,
not a successful denial. This script does not install an alternate executor.

Positive cases precede negative ones. A per-request read-only/deny override on a
previously writable/readable file distinguishes policy handling from the outer
fixture's static protections. Even a full PASS is only this fixed protocol
exercise, not arbitrary-command isolation or Desktop/model integration.
"""

import base64
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import socket
import stat
import subprocess
import sys
import time


CODEX = Path("/usr/lib/chatgpt/resources/codex")
EXPECTED_VERSION = "codex-cli 0.153.4"
EXPECTED_SHA256 = "4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6"
WORKSPACE = Path("/foldgpt-fixture")
OUTSIDE = Path("/outside/victim.txt")
SCRATCH = Path("/tmp/exec-server-policy-probe")
PROTECTED = b"Protected metadata remains intact\n"
OUTSIDE_MARKER = b"Outside file remains intact\n"
FS_MARKER = b"FoldGPT exec-server filesystem proof\n"
SHELL_MARKER = b"FoldGPT exec-server shell proof\n"
FS_FILE = WORKSPACE / "exec-server-policy.txt"
SHELL_FILE = WORKSPACE / "exec-server-shell.txt"
MAX_LINE_BYTES = 1024 * 1024
MAX_WIRE_BYTES = 4 * MAX_LINE_BYTES
MAX_OUTPUT_BYTES = 65536
RUN_SECONDS = 90
REQUEST_METHODS = frozenset({
    "initialize", "environment/info", "process/start", "process/read",
    "fs/readFile", "fs/writeFile", "fs/getMetadata",
})
NOTIFICATION_METHODS = frozenset({"process/output", "process/exited", "process/closed"})


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def b64(data):
    return base64.b64encode(data).decode("ascii")


def unb64(value):
    require(isinstance(value, str), "missing base64 protocol data")
    return base64.b64decode(value, validate=True)


def entry(path, access):
    return {"path": {"type": "path", "path": Path(path).as_uri()}, "access": access}


def policy(*extra_entries):
    # ExecFileSystemSandboxEntry uses snake_case field names, while its enclosing
    # FileSystemSandboxContext uses camelCase. No profile projection is involved.
    entries = [entry("/", "read"), entry(WORKSPACE, "write"), entry(SCRATCH, "write")]
    for name in (".git", "src/.git", ".codex", ".agents"):
        entries.append(entry(WORKSPACE / name, "read"))
    entries.extend(copy.deepcopy(extra_entries))
    return {
        "permissions": {
            "type": "managed",
            "file_system": {"type": "restricted", "entries": entries},
            "network": "restricted",
        },
        "cwd": WORKSPACE.as_uri(),
        "workspaceRoots": [WORKSPACE.as_uri()],
        "userHomeDir": (SCRATCH / "home").as_uri(),
        "temporaryDirectories": [SCRATCH.as_uri()],
        "windowsSandboxLevel": "disabled",
        "windowsSandboxPrivateDesktop": False,
        "useLegacyLandlock": False,
    }


def verify_outer_fixture():
    for target in (WORKSPACE / ".git/config", WORKSPACE / "src/.git/config", OUTSIDE):
        info = target.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                "native fixture must be an ordinary, non-hardlinked file")
        expected = OUTSIDE_MARKER if target == OUTSIDE else PROTECTED
        require(target.read_bytes() == expected, "native fixture marker mismatch")
        require(stat.S_IMODE(info.st_mode) == 0o600, "native fixture mode mismatch")


def preflight():
    require(sys.platform == "linux", "this worker requires its native Linux/Android launcher")
    require(os.environ.get("FOLDGPT_NATIVE_EXEC_SERVER_PROBE") == "1",
            "native exec-server probe launcher is absent; refusing direct execution")
    launcher_name = os.environ.get("FOLDGPT_NATIVE_EXEC_SERVER_LAUNCHER", "")
    require(launcher_name.startswith("/"), "native launcher executable path is absent")
    launcher = Path(launcher_name)
    require(launcher.is_file() and os.access(launcher, os.X_OK), "native launcher is not present")
    with launcher.open("rb") as native_file:
        header = native_file.read(20)
    require(len(header) == 20 and header[:6] == b"\x7fELF\x02\x01",
            "launcher is not a native 64-bit little-endian ELF")
    require(int.from_bytes(header[18:20], "little") == 183,
            "this official-binary diagnostic is pinned to ARM64")
    verify_outer_fixture()
    for target in (WORKSPACE / ".git/config", OUTSIDE):
        # Open only: do not truncate a fixture even if confinement is missing.
        try:
            fd = os.open(target, os.O_WRONLY | os.O_NOFOLLOW)
        except OSError as error:
            require(error.errno in (errno.EACCES, errno.EPERM), "unrelated outer write refusal")
        else:
            os.close(fd)
            raise RuntimeError("native outer file protection is absent")
    try:
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError as error:
        require(error.errno in (errno.EACCES, errno.EPERM), "unrelated socket failure")
    else:
        connection.close()
        raise RuntimeError("native outer network protection is absent")
    require(all(not path.exists() and not path.is_symlink() for path in
                (SCRATCH, FS_FILE, SHELL_FILE)),
            "diagnostic requires fresh native fixtures, not existing data")
    with CODEX.open("rb") as official_file:
        digest = hashlib.file_digest(official_file, "sha256").hexdigest()
    require(digest == EXPECTED_SHA256, "official Codex binary differs from the audited ARM64 package")
    SCRATCH.mkdir(mode=0o700)
    for name in ("home", "codexhome", "config", "cache", "state"):
        (SCRATCH / name).mkdir(mode=0o700)
    return digest


class RpcError(RuntimeError):
    def __init__(self, method, error):
        self.method = method
        self.error = error
        super().__init__(f"{method} returned {json.dumps(error, ensure_ascii=True)[:1200]}")


class Peer:
    def __init__(self, process, deadline):
        self.process = process
        self.deadline = deadline
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ)
        self.buffer = bytearray()
        self.wire_bytes = 0
        self.next_id = 1
        self.sent = []
        self.process_ids = set()
        self.notification_count = 0

    def send(self, method, params, request_id=None):
        require(method in REQUEST_METHODS or (method == "initialized" and request_id is None),
                "outbound method is outside this offline diagnostic")
        message = {"method": method, "params": params}
        if request_id is not None:
            message["id"] = request_id
        encoded = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
        require(len(encoded) <= MAX_LINE_BYTES, "oversized outbound request")
        self.process.stdin.write(encoded)
        self.process.stdin.flush()
        self.sent.append(method)

    def receive(self, timeout=15):
        deadline = min(self.deadline, time.monotonic() + timeout)
        while True:
            if b"\n" in self.buffer:
                line, _, remainder = self.buffer.partition(b"\n")
                self.buffer = bytearray(remainder)
                require(len(line) <= MAX_LINE_BYTES, "oversized JSON line")
                if not line.strip():
                    continue
                message = json.loads(line)
                require(isinstance(message, dict), "invalid JSON-RPC envelope")
                return message
            remaining = deadline - time.monotonic()
            require(remaining > 0 and self.selector.select(remaining), "exec-server response timed out")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            require(chunk, "exec-server closed stdout before completing the test")
            self.buffer.extend(chunk)
            self.wire_bytes += len(chunk)
            require(len(self.buffer) <= MAX_LINE_BYTES and self.wire_bytes <= MAX_WIRE_BYTES,
                    "exec-server output exceeded this diagnostic's bound")

    def call(self, method, params):
        request_id = self.next_id
        self.next_id += 1
        self.send(method, params, request_id)
        while True:
            message = self.receive()
            if "method" in message:
                require("id" not in message, "unexpected executor-initiated request")
                require(message["method"] in NOTIFICATION_METHODS, "unexpected executor notification")
                data = message.get("params")
                require(isinstance(data, dict) and data.get("processId") in self.process_ids,
                        "notification for an unknown diagnostic process")
                self.notification_count += 1
                require(self.notification_count <= 1024, "excessive executor notifications")
                continue  # process/read is the single source of output in this probe.
            require(type(message.get("id")) is int and message["id"] == request_id,
                    "unexpected JSON-RPC response id")
            require(("result" in message) != ("error" in message), "ambiguous JSON-RPC response")
            if "error" in message:
                require(isinstance(message["error"], dict), "invalid JSON-RPC error")
                raise RpcError(method, message["error"])
            require(isinstance(message["result"], dict), "missing response object")
            return message["result"]

    def close(self):
        self.selector.close()


def fs_write(peer, path, data, sandbox):
    return peer.call("fs/writeFile", {"path": path.as_uri(), "dataBase64": b64(data),
                                      "followSymlinks": False, "sandbox": sandbox})


def fs_read(peer, path, sandbox):
    result = peer.call("fs/readFile", {"path": path.as_uri(), "followSymlinks": False,
                                       "sandbox": sandbox})
    return unb64(result.get("dataBase64"))


def expect_fs_denial(operation):
    try:
        operation()
    except RpcError as error:
        # Both invalid input and permission denial use -32600 in this version.
        # A code alone therefore does not prove enforcement. Require the OS
        # denial diagnostic; reject helper/namespace/bootstrap errors explicitly.
        message = str(error.error.get("message", ""))
        denied = re.search(r"\b(?:permission denied|operation not permitted)\b", message, re.I)
        bootstrap = re.search(r"bwrap|bubblewrap|namespace|failed to (?:spawn|start)|sandbox helper|seccomp installation",
                              message, re.I)
        require(error.error.get("code") == -32600 and denied and not bootstrap,
                "negative case failed for an unproven reason: " + str(error))
        return
    raise RuntimeError("executor unexpectedly allowed a denied filesystem operation")


def run_shell(peer, process_id, script, sandbox):
    peer.process_ids.add(process_id)
    result = peer.call("process/start", {
        "processId": process_id, "argv": ["/bin/sh", "-c", script],
        "cwd": WORKSPACE.as_uri(), "envPolicy": None, "shellSnapshot": None,
        "env": {"PATH": "/usr/bin:/bin", "HOME": str(SCRATCH / "home"),
                "TMPDIR": str(SCRATCH), "LANG": "C.UTF-8"},
        "tty": False, "pipeStdin": False, "arg0": None, "sandbox": sandbox,
        "enforceManagedNetwork": False, "managedNetwork": None, "networkProxy": None,
    })
    require(result.get("processId") == process_id, "executor changed the logical process ID")
    # This official Linux executor reports linuxSeccomp after a managed launch.
    # Merely reporting that label is not the enforcement proof below.
    require(result.get("sandboxType") == "linuxSeccomp", "managed process sandbox was not reported")
    after_seq = 0
    streams = {"stdout": bytearray(), "stderr": bytearray()}
    while time.monotonic() < peer.deadline:
        result = peer.call("process/read", {"processId": process_id, "afterSeq": after_seq,
                                            "maxBytes": MAX_OUTPUT_BYTES, "waitMs": 1000})
        require(result.get("failure") is None, "executor process failure: " + str(result.get("failure")))
        chunks = result.get("chunks")
        require(isinstance(chunks, list), "missing process chunks")
        for chunk in chunks:
            require(isinstance(chunk, dict) and type(chunk.get("seq")) is int
                    and chunk["seq"] > after_seq, "invalid process output sequence")
            stream = chunk.get("stream")
            require(stream in streams, "unexpected output stream")
            streams[stream].extend(unb64(chunk.get("chunk")))
            after_seq = chunk["seq"]
        require(sum(map(len, streams.values())) <= MAX_OUTPUT_BYTES, "process output limit exceeded")
        next_seq = result.get("nextSeq")
        require(type(next_seq) is int and next_seq >= after_seq + 1, "invalid process read cursor")
        after_seq = next_seq - 1
        if result.get("closed") is True:
            require(result.get("exited") is True and result.get("exitCode") == 0,
                    "fixed policy command did not exit successfully")
            return bytes(streams["stdout"]), bytes(streams["stderr"])
    raise RuntimeError("fixed process did not close before diagnostic deadline")


def execute_checks(peer, report):
    report["stage"] = "initialize"
    initialized = peer.call("initialize", {"clientName": "foldgpt_exec_policy_probe", "resumeSessionId": None})
    require(isinstance(initialized.get("sessionId"), str) and initialized["sessionId"], "missing executor session")
    peer.send("initialized", None)
    info = peer.call("environment/info", None)
    require(info.get("platformOs") == "linux" and info.get("cwd") == WORKSPACE.as_uri(),
            "executor environment does not match the fixed fixture")
    require(info.get("userHomeDir") == (SCRATCH / "home").as_uri(), "executor selected another home")
    sandbox = policy()

    report["stage"] = "managed_fs_positive"
    require(fs_read(peer, WORKSPACE / ".git/config", sandbox) == PROTECTED, "managed read mismatch")
    fs_write(peer, FS_FILE, FS_MARKER, sandbox)
    require(FS_FILE.read_bytes() == FS_MARKER and fs_read(peer, FS_FILE, sandbox) == FS_MARKER,
            "managed write/read did not reach the physical fixture")
    metadata = peer.call("fs/getMetadata", {"path": FS_FILE.as_uri(), "followSymlinks": False, "sandbox": sandbox})
    require(metadata.get("isFile") is True and metadata.get("size") == len(FS_MARKER), "metadata mismatch")
    report["fsPositive"] = "PASS"

    report["stage"] = "managed_fs_policy_change"
    expect_fs_denial(lambda: fs_write(peer, FS_FILE, b"FORBIDDEN\n", policy(entry(FS_FILE, "read"))))
    require(FS_FILE.read_bytes() == FS_MARKER, "read-only policy did not preserve an otherwise writable file")
    expect_fs_denial(lambda: fs_read(peer, FS_FILE, policy(entry(FS_FILE, "deny"))))
    require(fs_read(peer, FS_FILE, sandbox) == FS_MARKER, "baseline policy failed after deny override")
    report["fsPerRequestPolicy"] = "PASS"

    report["stage"] = "managed_fs_protected_denials"
    for target in (WORKSPACE / ".git/config", WORKSPACE / "src/.git/config", OUTSIDE):
        expect_fs_denial(lambda path=target: fs_write(peer, path, b"FORBIDDEN\n", sandbox))
    verify_outer_fixture()
    report["fsProtectedFixtures"] = "PASS"

    report["stage"] = "managed_process_positive"
    stdout, _ = run_shell(peer, "foldgpt-positive", "printf 'FoldGPT exec-server shell proof\\n' > exec-server-shell.txt || exit 10\nprintf 'shell_positive=PASS\\n'\n", sandbox)
    require(stdout == b"shell_positive=PASS\n" and SHELL_FILE.read_bytes() == SHELL_MARKER,
            "managed process did not produce its expected real file")
    report["processPositive"] = "PASS"

    report["stage"] = "managed_process_policy_change"
    command = "printf 'shell_denial_started=PASS\\n'\nif printf 'FORBIDDEN\\n' > exec-server-shell.txt; then exit 20; fi\nprintf 'shell_denial=PASS\\n'\n"
    restricted = policy(entry(SHELL_FILE, "read"))
    stdout, stderr = run_shell(peer, "foldgpt-denial", command, restricted)
    require(stdout == b"shell_denial_started=PASS\nshell_denial=PASS\n",
            "denial occurred before the real shell body or did not execute as expected")
    require(b"Permission denied" in stderr or b"Operation not permitted" in stderr,
            "shell failed for a reason other than an access refusal")
    require(SHELL_FILE.read_bytes() == SHELL_MARKER, "per-request shell denial changed the file")
    verify_outer_fixture()
    require(FS_FILE.read_bytes() == FS_MARKER and SHELL_FILE.read_bytes() == SHELL_MARKER,
            "later requests altered the earlier proof files")
    report["processPerRequestPolicy"] = "PASS"


def main():
    report = {"status": "FAIL", "stage": "native_preflight", "modelRequests": 0,
              "scope": "fixed offline exec-server managed-policy diagnostic; not production isolation"}
    process = None
    peer = None
    try:
        report["officialCodexSha256"] = preflight()
        environment = {"PATH": "/usr/bin:/bin", "HOME": str(SCRATCH / "home"),
                       "CODEX_HOME": str(SCRATCH / "codexhome"), "XDG_CONFIG_HOME": str(SCRATCH / "config"),
                       "XDG_CACHE_HOME": str(SCRATCH / "cache"), "XDG_STATE_HOME": str(SCRATCH / "state"),
                       "TMPDIR": str(SCRATCH), "LANG": "C.UTF-8", "RUST_BACKTRACE": "0"}
        report["stage"] = "official_version"
        version = subprocess.run([str(CODEX), "--version"], env=environment, cwd=WORKSPACE,
                                 stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                 timeout=15, check=True).stdout.strip()
        require(version == EXPECTED_VERSION, "official CLI version does not match the reviewed protocol")
        report["officialCodexVersion"] = version
        report["stage"] = "exec_server_start"
        log_path = SCRATCH / "official-exec-server-stderr.log"
        with log_path.open("xb") as diagnostic_log:
            process = subprocess.Popen([str(CODEX), "exec-server", "--strict-config", "--listen", "stdio://"],
                                       cwd=WORKSPACE, env=environment, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=diagnostic_log, close_fds=True)
            peer = Peer(process, time.monotonic() + RUN_SECONDS)
            execute_checks(peer, report)
            report["stage"] = "shutdown"
            process.stdin.close()
            process.wait(timeout=10)
            require(process.returncode == 0, "official executor shutdown failed")
        require(not (SCRATCH / "codexhome/auth.json").exists(), "unexpected credentials in temporary profile")
        report.update(status="PASS", stage="complete", requestMethods=peer.sent,
                      diagnosticLog=str(log_path), diagnosticBytes=log_path.stat().st_size)
        return_code = 0
    except Exception as error:
        report["error"] = str(error)[:1600]
        if peer is not None:
            report["requestMethods"] = peer.sent
        return_code = 1
    finally:
        if peer is not None:
            peer.close()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        # The native supervisor must independently verify its fixture tree and
        # bound/clean up all descendants. This worker makes no hostile-tree claim.
    print(json.dumps(report, ensure_ascii=True, separators=(",", ":")), flush=True)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
