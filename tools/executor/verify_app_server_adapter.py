"""Bounded real official 0.153.4 stdio adapter handshake in a private profile.

Run only from a frozen diagnostic source tree in the guest cache. This sends no
account, thread, turn, command or model request and does not install the adapter.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.executor.verify_official_environment import Peer, SHA256

SOURCES = ("app_server_adapter.py", "app_server_routing.py", "exec_server.py",
    "verify_official_environment.py", "verify_app_server_adapter.py")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    codex = Path("/usr/lib/chatgpt/resources/codex")
    digest = hashlib.sha256(codex.read_bytes()).hexdigest()
    if digest != SHA256:
        raise RuntimeError("Official executable differs from the authenticated 0.153.4 package")
    work = Path(tempfile.mkdtemp(prefix="adapter-profile-", dir=args.parent.resolve(strict=True)))
    for name in ("home", "codex", "workspace", "tmp", "config", "cache", "state"):
        (work / name).mkdir(mode=0o700)
    environment = {"PATH": "/usr/bin:/bin", "HOME": str(work / "home"), "CODEX_HOME": str(work / "codex"),
        "TMPDIR": str(work / "tmp"), "XDG_CONFIG_HOME": str(work / "config"),
        "XDG_CACHE_HOME": str(work / "cache"), "XDG_STATE_HOME": str(work / "state"), "LANG": "C.UTF-8"}
    config = ('default = "foldgpt-adapter-proof"\ninclude_local = false\n[[environments]]\n'
        'id = "foldgpt-adapter-proof"\nprogram = "/usr/bin/python3"\nargs = ["-B", '
        + json.dumps(str(source / "exec_server.py")) + ']\ncwd = '
        + json.dumps(str(work / "workspace")) + '\ninitialize_timeout_sec = 30\n')
    (work / "codex/environments.toml").write_text(config)
    arguments = ["/usr/bin/python3", "-B", str(source / "app_server_adapter.py"),
        "--official", str(codex), "--environment", "foldgpt-adapter-proof", "--cwd", str(work / "workspace"),
        "--", "app-server", "--listen", "stdio://"]
    report = {"schema": "foldgpt.app-server-adapter-handshake.v1", "work": str(work),
        "scope": "Real official app-server through the separate stdio adapter; no execution/routing production claim",
        "modelRequests": 0, "threadRequests": 0, "accountRequests": 0, "officialSha256": digest,
        "sourcesSha256": {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in SOURCES},
        "argv": arguments}
    with (work / "stderr.log").open("wb") as log:
        process = subprocess.Popen(arguments, cwd=work / "workspace", env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, close_fds=True)
        peer = Peer(process)
        try:
            # The adapter, rather than this client, enables experimentalApi.
            peer.send({"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "foldgpt_adapter_proof", "version": "1"},
                "capabilities": {"experimentalApi": False}}})
            initialized = peer.receive(1)
            if initialized.get("codexHome") != str(work / "codex"):
                raise RuntimeError("Official app-server selected another configuration directory")
            peer.send({"method": "initialized", "params": {}})
            peer.send({"id": 2, "method": "environment/info", "params": {"environmentId": "foldgpt-adapter-proof"}})
            info = peer.receive(2)
            if info.get("cwd") != (work / "workspace").as_uri() or info.get("shell", {}).get("path") != "/usr/bin/sh":
                raise RuntimeError("Official environment metadata differs")
            peer.send({"id": 3, "method": "environment/status", "params": {"environmentId": "foldgpt-adapter-proof"}})
            status = peer.receive(3)
            if status != {"status": "ready"}:
                raise RuntimeError("Official executor connection is not ready")
            process.stdin.close()
            process.wait(timeout=25)
            if process.returncode != 0:
                raise RuntimeError("Adapter or official app-server did not shut down cleanly")
            report.update(status="PASS", adapterReturncode=process.returncode, cleanInputEof=True,
                initialize=initialized, environmentInfo=info, environmentStatus=status, requests=peer.requests)
        finally:
            peer.selector.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    report["stderrSha256"] = hashlib.sha256((work / "stderr.log").read_bytes()).hexdigest()
    if (work / "codex/auth.json").exists():
        raise RuntimeError("Diagnostic unexpectedly created authentication data")
    (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
