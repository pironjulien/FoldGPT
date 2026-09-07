"""PC-only orchestration: real native authority and Rust client with different UIDs.

Root is used only by the PC fixture owner to launch both NONROOT processes.
No ADB, Android package, kernel configuration or production bootstrap is touched.
"""
import argparse
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import pwd
import socket
import subprocess
import sys
import tempfile


async def serve(arguments):
    if os.getuid() == 0:
        raise RuntimeError("Actual authority must run nonroot")
    descriptor, peer_fd = map(int, arguments[:2])
    package, helpers, runner, directory = map(Path, arguments[2:])
    sys.path.insert(0, str(package))
    from tools.executor.exec_server import ExecServer
    from tools.executor.native_bootstrap_files import create_bootstrap_read_authority
    from tools.executor.native_bootstrap_channel import BootstrapReadChannel
    from tools.executor.native_executor_backend import NativeExecutorBackend
    processes_type = importlib.import_module("tools.executor.bionic-supervisor.processes").Processes
    workspace = directory / "workspace"
    workspace.mkdir(mode=0o700)
    (workspace / ".codex").mkdir()
    (workspace / ".codex/config.toml").write_text('model = "native-project-model"\n')
    (workspace / "binary").write_bytes(bytes(range(256)) * 273 + bytes(range(112)))
    def process_factory(runner, workspace, **options):
        return processes_type(runner, workspace, executables={"bash": "/usr/bin/bash"},
            runtime=(("/usr", True), ("/lib", True), ("/lib64", True), ("/etc/ld.so.cache", False)), **options)
    owner = NativeExecutorBackend(str(helpers / "native-files"), workspace,
        handle_helper=str(helpers / "native-file-handle"), process_runner=str(runner),
        process_factory=process_factory, guest_workspace=str(workspace), parent_environment={})
    server = ExecServer(owner)
    await server.request({"id": 1, "method": "initialize", "params": {"clientName": "cross-uid-PC-qualification"}})
    async def notify(_): pass
    await server.accept({"method": "initialized"}, notify)
    print(json.dumps(dict(pid=os.getpid(), uid=os.getuid(), gid=os.getgid(),
        session=server.session_id, workspace=str(workspace))), flush=True)
    with os.fdopen(peer_fd) as peer_input:
        peer = tuple(json.loads(peer_input.readline()))
    authority = create_bootstrap_read_authority(owner, session_id=server.session_id)
    channel = BootstrapReadChannel(socket.socket(fileno=descriptor), authority, peer=peer)
    error = None
    try:
        await channel.run()
    except BaseException as failure:
        error = repr(failure)
        raise
    finally:
        await server.close()
        (directory / "owner-report.json").write_text(json.dumps(dict(
            error=error, filesClosed=owner.files.closed, helperGone=owner.files.process is None,
            quarantined=owner.processes.quarantined, uid=os.getuid(), pid=os.getpid()), indent=2))


def qualify(args):
    if os.getuid() != 0:
        raise RuntimeError("PC fixture owner needs permission to launch two distinct nonroot accounts")
    account = pwd.getpwnam("foldgpt-build")
    native = pwd.getpwnam("nobody")
    if account.pw_uid == native.pw_uid or not account.pw_uid or not native.pw_uid:
        raise RuntimeError("Distinct nonroot test accounts required")
    out = Path(tempfile.mkdtemp(prefix="foldgpt-bootstrap-isolation-", dir="/var/tmp"))
    out.chmod(0o755)
    package = out / "package"
    records = []
    for relative in ("tools/executor", "tools/executor/bionic-supervisor", "tools/policy"):
        destination = package / relative
        destination.mkdir(parents=True, exist_ok=True)
        for source in sorted((args.source / relative).glob("*.py")):
            data = source.read_bytes(); (destination / source.name).write_bytes(data)
            records.append(dict(path=f"{relative}/{source.name}", sha256=hashlib.sha256(data).hexdigest()))
    (out / "sources.json").write_text(json.dumps(records, indent=2))
    server_directory, client_directory = out / "server", out / "client"
    for directory, user in ((server_directory, native), (client_directory, account)):
        directory.mkdir(mode=0o700); os.chown(directory, user.pw_uid, user.pw_gid)
    first, second = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    for endpoint in (first, second): endpoint.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
    peer_read, peer_write = os.pipe()
    environment = {"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    server = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--serve",
        str(first.fileno()), str(peer_read), str(package), str(args.helpers), str(args.runner), str(server_directory)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=(out / "server.stderr").open("wb"),
        pass_fds=(first.fileno(), peer_read), user=native.pw_uid, group=native.pw_gid, extra_groups=[], env=environment)
    first.close(); os.close(peer_read)
    ready_line = server.stdout.readline()
    if not ready_line:
        raise RuntimeError(f"Native owner did not initialize; inspect {out}")
    ready = json.loads(ready_line)
    (out / "ready.json").write_bytes(ready_line)
    if (ready["pid"], ready["uid"], ready["gid"]) != (server.pid, native.pw_uid, native.pw_gid):
        raise RuntimeError("Native process identity differs")
    client = subprocess.Popen([str(args.client), str(second.fileno()), str(server.pid), str(native.pw_uid),
        str(native.pw_gid), ready["session"], ready["workspace"], str(client_directory / "home"),
        str(client_directory / "client-report.json")],
        stdin=subprocess.DEVNULL, stdout=(out / "client.stdout").open("wb"), stderr=(out / "client.stderr").open("wb"),
        pass_fds=(second.fileno(),), user=account.pw_uid, group=account.pw_gid, extra_groups=[], env=environment)
    second.close()
    with os.fdopen(peer_write, "w") as peer_output:
        peer_output.write(json.dumps([client.pid, account.pw_uid, account.pw_gid]) + "\n")
    client_code = client.wait(timeout=60)
    server_code = server.wait(timeout=60)
    report = dict(clientReturncode=client_code, serverReturncode=server_code,
        clientPid=client.pid, serverPid=server.pid, output=str(out),
        clientExecutableSha256=hashlib.sha256(args.client.read_bytes()).hexdigest(),
        helpers={name: hashlib.sha256((args.helpers / name).read_bytes()).hexdigest()
            for name in ("native-files", "native-file-handle")})
    if client_code == server_code == 0:
        report["client"] = json.loads((client_directory / "client-report.json").read_text())
        report["owner"] = json.loads((server_directory / "owner-report.json").read_text())
        data = (Path(ready["workspace"]) / "binary").read_bytes()
        report["independentBinarySha256"] = hashlib.sha256(data).hexdigest()
        report["verified"] = (report["client"]["verified"] and report["owner"]["filesClosed"]
            and report["owner"]["helperGone"] and not report["owner"]["quarantined"]
            and report["owner"]["error"] is None and data == (bytes(range(256)) * 273 + bytes(range(112)))
            and not Path(f"/proc/{server.pid}").exists() and not Path(f"/proc/{client.pid}").exists())
    else:
        report["verified"] = False
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if not report["verified"]: raise SystemExit(1)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--serve"]:
        asyncio.run(serve(sys.argv[2:]))
    else:
        parser = argparse.ArgumentParser()
        for option in ("client", "source", "helpers", "runner"):
            parser.add_argument(f"--{option}", required=True, type=Path)
        qualify(parser.parse_args())
