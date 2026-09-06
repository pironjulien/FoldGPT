"""Connect official Codex 0.153.4 to FoldGPT's stdio environment in a fresh profile.

No account, conversation, model request, command execution or policy success is
created. This verifies the actual official transport consumer, not enforcement.
Run in the guest using its untouched packaged codex and an explicit test parent.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time

SHA256 = "4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6"


class Peer:
    def __init__(self, process):
        self.process = process
        self.buffer = bytearray()
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ)
        self.requests = []

    def send(self, message):
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        self.process.stdin.flush()
        if "id" in message:
            self.requests.append(message["method"])

    def receive(self, identifier):
        deadline = time.monotonic() + 30
        while True:
            while b"\n" in self.buffer:
                line, _, rest = self.buffer.partition(b"\n")
                self.buffer = bytearray(rest)
                message = json.loads(line)
                if "method" in message:
                    if "id" in message or message["method"].startswith(("thread/", "turn/", "item/")):
                        raise RuntimeError("Unexpected request or conversation activity")
                    continue
                if message.get("id") != identifier or "error" in message:
                    raise RuntimeError("Official response failed: " + str(message))
                return message["result"]
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError("Official environment response timed out")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("Official app-server closed before response")
            self.buffer.extend(chunk)
            if len(self.buffer) > 1048576:
                raise RuntimeError("Response exceeded diagnostic limit")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    args = parser.parse_args()
    codex = Path("/usr/lib/chatgpt/resources/codex")
    if hashlib.sha256(codex.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Official executable differs from the verified package")
    server = args.server.resolve(strict=True)
    work = Path(tempfile.mkdtemp(prefix="official-environment-", dir=args.parent.resolve(strict=True)))
    for name in ("home", "codex", "workspace", "tmp", "config", "cache", "state"):
        (work / name).mkdir(mode=0o700)
    environment = {"PATH": "/usr/bin:/bin", "HOME": str(work / "home"), "CODEX_HOME": str(work / "codex"),
        "TMPDIR": str(work / "tmp"), "XDG_CONFIG_HOME": str(work / "config"),
        "XDG_CACHE_HOME": str(work / "cache"), "XDG_STATE_HOME": str(work / "state"), "LANG": "C.UTF-8"}
    config = ('default = "foldgpt-proof"\ninclude_local = false\n[[environments]]\n'
        'id = "foldgpt-proof"\nprogram = "/usr/bin/python3"\nargs = ["-B", ' + json.dumps(str(server)) + ']\n'
        'cwd = ' + json.dumps(str(work / "workspace")) + '\ninitialize_timeout_sec = 30\n')
    (work / "codex/environments.toml").write_text(config)
    version = subprocess.check_output([str(codex), "--version"], env=environment, text=True, timeout=15).strip()
    if version != "codex-cli 0.153.4":
        raise RuntimeError("Unexpected official executable version")
    report = {"codexVersion": version, "codexSha256": SHA256, "serverSha256": hashlib.sha256(server.read_bytes()).hexdigest(),
        "modelRequests": 0, "scope": "official environment handshake only", "work": str(work)}
    with (work / "stderr.log").open("wb") as log:
        process = subprocess.Popen([str(codex), "app-server", "--listen", "stdio://"], cwd=work / "workspace", env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, close_fds=True)
        peer = Peer(process)
        try:
            peer.send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "foldgpt_environment_proof", "version": "1"},
                "capabilities": {"experimentalApi": True}}})
            initialized = peer.receive(1)
            if initialized.get("codexHome") != str(work / "codex"):
                raise RuntimeError("Official client selected another configuration directory")
            peer.send({"method": "initialized", "params": {}})
            peer.send({"id": 2, "method": "environment/info", "params": {"environmentId": "foldgpt-proof"}})
            info = peer.receive(2)
            if info.get("cwd") != (work / "workspace").as_uri() or info.get("shell", {}).get("path") != "/usr/bin/sh":
                raise RuntimeError("Official environment metadata differs: " + str(info))
            peer.send({"id": 3, "method": "environment/status", "params": {"environmentId": "foldgpt-proof"}})
            status = peer.receive(3)
            if status != {"status": "ready"}:
                raise RuntimeError("Official environment is not connected: " + str(status))
            process.stdin.close()
            process.wait(timeout=10)
            if process.returncode != 0:
                raise RuntimeError("Official app-server did not shut down cleanly")
            report.update(status="PASS", environmentInfo=info, environmentStatus=status, requests=peer.requests)
        finally:
            peer.selector.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    if (work / "codex/auth.json").exists():
        raise RuntimeError("Unexpected authentication data in diagnostic profile")
    (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
