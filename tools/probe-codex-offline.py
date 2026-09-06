"""Fixed offline command/exec experiment; launched ONLY by the native probe.

The native launcher must enforce its actual Landlock/seccomp policy BEFORE
PRoot, Python and the official Codex process start. This script is not an
isolation mechanism, a general executor, or a replacement for Codex's policy.
It never connects to a model, logs in, or uses the installed account profile.
The externalSandbox declaration describes that already-enforced outer test
boundary; it does not establish enforcement by itself.
"""

import errno
import hashlib
import json
import os
from pathlib import Path
import selectors
import socket
import subprocess
import time


CODEX_BINARY = Path("/usr/lib/chatgpt/resources/codex")
# Digest of the untouched binary read from downloads/chatgpt_arm64.deb.
EXPECTED_SHA256 = "4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6"
EXPECTED_VERSION = "0.153.4"
WORKSPACE = Path("/foldgpt-fixture")
CODEX_HOME = Path("/tmp/codexhome")
HOME = Path("/tmp/home")
LOG_PATH = Path("/tmp/codex-offline-stderr.log")
PROTECTED = b"Protected metadata remains intact\n"
OUTSIDE = b"Outside file remains intact\n"
MARKER = b"FoldGPT native shell write\n"
APPENDED = MARKER + b"FoldGPT appended\n"
MAX_MESSAGE_BYTES = 1024 * 1024

FIXED_COMMAND = """echo 'codex_fixture_started=PASS'
echo 'FoldGPT native shell write' > normal.txt || exit 10
echo 'FoldGPT native shell write' > src/normal.txt || exit 11
echo 'FoldGPT native shell write' > .gitignore || exit 12
echo 'FoldGPT appended' >> normal.txt || exit 13
echo 'codex_fixture_writes=PASS'
for denied in .git/config src/.git/config .git/new-file .codex/config.toml .agents/settings ../outside/victim.txt /outside/victim.txt outside-link/victim.txt; do
  if echo 'FORBIDDEN' > "$denied"; then
    echo 'codex_fixture_forbidden_write=FAIL'; exit 20
  fi
done
echo 'codex_fixture_denials=PASS'
exit 0
"""
EXPECTED_STDOUT = (
    "codex_fixture_started=PASS\n"
    "codex_fixture_writes=PASS\n"
    "codex_fixture_denials=PASS\n"
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def preflight():
    require(os.environ.get("FOLDGPT_NATIVE_OFFLINE_PROBE") == "1",
            "launch this script through the native probe, never directly")
    require((WORKSPACE / ".git/config").read_bytes() == PROTECTED,
            "native probe protected fixture missing")
    require(Path("/outside/victim.txt").read_bytes() == OUTSIDE,
            "native probe outside fixture missing")
    # Check an actual refusal before declaring externalSandbox to Codex. If
    # mistakenly launched without confinement, only our named test fixture is
    # affected and Codex is never launched after this failure.
    try:
        fd = os.open(WORKSPACE / ".git/config", os.O_WRONLY | os.O_TRUNC)
    except OSError as error:
        require(error.errno in (errno.EPERM, errno.EACCES),
                "metadata probe failed for an unrelated reason")
    else:
        os.close(fd)
        raise RuntimeError("native metadata write protection is absent")
    require((WORKSPACE / ".git/config").read_bytes() == PROTECTED,
            "preflight damaged protected fixture")
    # No connection is attempted. socket() itself must be refused by the
    # native filter; model/network APIs cannot be used in this experiment.
    try:
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError as error:
        require(error.errno in (errno.EPERM, errno.EACCES),
                "network probe failed for an unrelated reason")
    else:
        connection.close()
        raise RuntimeError("native network isolation is absent")
    require(not (CODEX_HOME / "auth.json").exists(),
            "temporary Codex profile must have no credentials")
    with CODEX_BINARY.open("rb") as official_binary:
        digest = hashlib.file_digest(official_binary, "sha256").hexdigest()
    require(digest == EXPECTED_SHA256,
            "installed Codex binary differs from the audited official package")
    return digest


class Peer:
    def __init__(self, process):
        self.process = process
        self.buffer = bytearray()
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ)
        self.notifications = 0
        self.requests_sent = []

    def send(self, message):
        self.process.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        self.process.stdin.flush()
        if "id" in message:
            self.requests_sent.append(message["method"])

    def response(self, request_id, timeout):
        deadline = time.monotonic() + timeout
        while True:
            while b"\n" in self.buffer:
                line, _, remaining = self.buffer.partition(b"\n")
                self.buffer = bytearray(remaining)
                if not line.strip():
                    continue
                message = json.loads(line)
                require(isinstance(message, dict), "invalid JSON-RPC envelope")
                if "method" in message:
                    require("id" not in message, "unexpected server request")
                    require(not message["method"].startswith(("turn/", "thread/", "item/")),
                            "unexpected model/thread activity")
                    self.notifications += 1
                    continue
                require(message.get("id") == request_id, "unexpected response id")
                require("error" not in message,
                        "official app-server returned: " + str(message.get("error")))
                require(isinstance(message.get("result"), dict), "missing response result")
                return message["result"]
            remaining_time = deadline - time.monotonic()
            require(remaining_time > 0, "official app-server response timed out")
            require(self.selector.select(remaining_time), "official app-server response timed out")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            require(chunk, "official app-server closed stdout before its response")
            self.buffer.extend(chunk)
            require(len(self.buffer) <= MAX_MESSAGE_BYTES, "oversized JSON-RPC response")

    def close(self):
        self.selector.close()


def main():
    digest = preflight()
    environment = {
        "PATH": "/usr/bin:/bin", "HOME": str(HOME), "CODEX_HOME": str(CODEX_HOME),
        "XDG_CONFIG_HOME": "/tmp/config", "XDG_CACHE_HOME": "/tmp/cache",
        "XDG_STATE_HOME": "/tmp/state", "TMPDIR": "/tmp/run", "LANG": "C.UTF-8",
        "RUST_BACKTRACE": "1",
    }
    version_result = subprocess.run([str(CODEX_BINARY), "--version"], env=environment,
                                    stdin=subprocess.DEVNULL, capture_output=True, timeout=15,
                                    check=False, text=True)
    require(version_result.returncode == 0,
            "official version command failed: " + version_result.stderr[:4096])
    version = version_result.stdout.strip()
    require(version == "codex-cli " + EXPECTED_VERSION,
            "unexpected official CLI version: " + version)
    print("official_binary_verification=PASS version=" + version + " sha256=" + digest,
          flush=True)
    with LOG_PATH.open("wb") as diagnostic_log:
        process = subprocess.Popen(
            [str(CODEX_BINARY), "app-server", "--listen", "stdio://"],
            cwd=WORKSPACE, env=environment, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=diagnostic_log, close_fds=True,
        )
        peer = Peer(process)
        try:
            peer.send({"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "foldgpt_offline_probe", "version": "1"},
                "capabilities": {"experimentalApi": False},
            }})
            initialized = peer.response(1, 30)
            require(initialized.get("codexHome") == str(CODEX_HOME),
                    "app-server selected another account/configuration directory")
            require(initialized.get("platformOs") == "linux", "app-server is not Linux")
            print("official_app_server_initialize=PASS", flush=True)
            peer.send({"method": "initialized", "params": {}})
            peer.send({"id": 2, "method": "command/exec", "params": {
                "command": ["/bin/sh", "-c", FIXED_COMMAND],
                "cwd": str(WORKSPACE), "timeoutMs": 15000, "outputBytesCap": 65536,
                "sandboxPolicy": {"type": "externalSandbox", "networkAccess": "restricted"},
            }})
            result = peer.response(2, 30)
            require(result.get("exitCode") == 0, "fixed command failed: " + str(result))
            require(result.get("stdout") == EXPECTED_STDOUT,
                    "official command/exec did not return the expected fixture output")
            print("official_command_exec_response=PASS", flush=True)
            require((WORKSPACE / "normal.txt").read_bytes() == APPENDED,
                    "official command/exec did not perform its permitted file writes")
            require((WORKSPACE / "src/normal.txt").read_bytes() == MARKER,
                    "nested permitted write is missing")
            require((WORKSPACE / ".gitignore").read_bytes() == MARKER,
                    "similarly named permitted write is missing")
            require((WORKSPACE / ".git/config").read_bytes() == PROTECTED,
                    "protected metadata changed")
            require(Path("/outside/victim.txt").read_bytes() == OUTSIDE,
                    "outside fixture changed")
            require(peer.requests_sent == ["initialize", "command/exec"],
                    "unexpected outbound protocol request")
            process.stdin.close()
            process.wait(timeout=10)
            require(process.returncode == 0, "app-server did not shut down cleanly")
        finally:
            peer.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    require(not (CODEX_HOME / "auth.json").exists(), "probe unexpectedly created credentials")
    print(json.dumps({
        "officialCodexVersion": version, "officialCodexSha256": digest,
        "initialize": "PASS", "commandExec": "PASS", "fixtureVerification": "PASS",
        "modelRequests": 0, "accountProfile": "temporary", "scope": "fixed offline fixture only",
        "diagnosticLog": str(LOG_PATH), "diagnosticBytes": LOG_PATH.stat().st_size,
    }, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
