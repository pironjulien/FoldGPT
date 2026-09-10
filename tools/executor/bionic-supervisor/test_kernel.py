"""Real nonroot kernel tests; no Android device or model request is involved."""
import importlib
import json
import os
from pathlib import Path
import selectors
import shlex
import socket
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
wire = importlib.import_module("tools.executor.bionic-supervisor.wire")
Policy = importlib.import_module("tools.executor.bionic-supervisor.policy").Policy
from tools.executor.native_files import NativeFilesBackend


def context(workspace):
    uri = workspace.as_uri()
    return {"permissions": {"type": "managed", "file_system": {"type": "restricted", "entries": [
        {"path": {"type": "path", "path": uri}, "access": "write"},
        {"path": {"type": "path", "path": uri + "/private"}, "access": "deny"}]}, "network": "restricted"},
        "cwd": uri, "workspaceRoots": [uri], "windowsSandboxLevel": "disabled"}


def run(runner, command, *, input=b"", wall=3000, cancel=False, directory=None, env_extra=None,
        fixture_files=None):
    base = Path(tempfile.mkdtemp(prefix="foldgpt-bionic-case-", dir="/var/tmp"))
    root = base / "workspace"
    root.mkdir(mode=0o700)
    (root / "private").mkdir(mode=0o700)
    (root / "private/secret").write_text("private bytes")
    (root / "private/secret").chmod(0o600)
    (root / ".git").mkdir(mode=0o700)
    for relative, content in (fixture_files or {}).items():
        target = (root / relative).resolve()
        target.relative_to(root)
        target.write_bytes(content)
    if directory:
        (root / directory).mkdir(mode=0o700)
    files = NativeFilesBackend(runner, root, guest_workspace=str(root))
    requested = context(root)
    if directory:
        requested["cwd"] = (root / directory).as_uri()
    policy = Policy(files, requested, requested["cwd"], session="test", request="1")
    control, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    commands, command_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
    environment = {"PATH": "/usr/bin:/bin", "HOME": str(root), "TMPDIR": str(root), **(env_extra or {})}
    encoded = wire.envelope(workspace=str(root), cwd_relative=directory or ".", executable="/usr/bin/bash",
        argv=["/usr/bin/bash", "--noprofile", "--norc", "-c", command],
        environment=[name + "=" + value for name, value in environment.items()],
        runtime=[("/usr", True), ("/lib", True), ("/lib64", True), ("/etc/ld.so.cache", False)],
        wall_ms=wall, data_bytes=256*1024*1024, file_bytes=8*1024*1024,
        output_bytes=65536, uid_tasks=8, cpu_seconds=3, descriptors=128)
    envelope = wire.seal(encoded)
    fds = (files.root, read_fd, peer.fileno(), command_peer.fileno(), envelope)
    process = subprocess.Popen([str(runner), *map(str, fds)], pass_fds=fds, env={},
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    peer.close(); command_peer.close(); os.close(read_fd); os.close(envelope)
    if input:
        os.write(write_fd, input)
    os.close(write_fd)
    selector = selectors.DefaultSelector()
    selector.register(control, selectors.EVENT_READ, "control")
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    output = {"stdout": bytearray(), "stderr": bytearray()}
    events, decisions = [], []
    end = time.monotonic() + wall / 1000 + 8
    while selector.get_map():
        if time.monotonic() >= end:
            commands.send(b"T")
            raise TimeoutError((events, output, base))
        for key, _ in selector.select(0.05):
            if key.data == "control":
                packet = control.recv(16384)
                if not packet:
                    selector.unregister(control)
                    continue
                event = json.loads(packet)
                if event["type"] == "acquire":
                    decision = policy.decide(event)
                    decisions.append({"request": event, "decision": decision})
                    relative = decision["relative"].encode("utf-8")
                    control.send(struct.pack("<QiI4Q", decision["id"], decision["error"], len(relative),
                        decision["device"], decision["inode"], decision["parentDevice"], decision["parentInode"]) + relative)
                else:
                    events.append(event)
                    if event["type"] == "ready":
                        control.send(b"P")
                    if event["type"] == "started" and cancel:
                        commands.send(b"T")
            else:
                chunk = os.read(key.fileobj.fileno(), 8192)
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    output[key.data].extend(chunk)
    code = process.wait(timeout=2)
    result = {"events": events, "decisions": decisions, "returncode": code,
              **{name: value.decode("utf-8", "backslashreplace") for name, value in output.items()}}
    (base / "report.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({"directory": str(base), "returncode": code,
                      "final": events[-1] if events else None,
                      "stdout": result["stdout"], "stderr": result["stderr"]}), flush=True)
    control.close(); commands.close(); selector.close(); os.close(files.root)
    return result, base


if __name__ == "__main__":
    result, base = run(Path(sys.argv[1]), "printf 'value=%s\\n' \"$VALUE\"; read item; printf 'stdin=%s\\n' \"$item\"; printf 42 > value.txt; printf bad > private/secret; printf bad > .git/config; exit 23",
                       input=b"native input\n", env_extra={"VALUE": "golden"})
    assert result["returncode"] == 0, result
    assert result["stdout"] == "value=golden\nstdin=native input\n", result
    assert (base / "workspace/value.txt").read_bytes() == b"42"
    assert (base / "workspace/private/secret").read_bytes() == b"private bytes"
    assert not (base / "workspace/.git/config").exists()
    assert result["events"][-1]["exitCode"] == 23 and result["events"][-1]["cleanupComplete"]
    program = """import errno,os,socket,sys
os.mkdir('project')
open('project/value.py','w').write('answer=42\\n')
for action in (lambda: open('private/secret'),lambda: os.stat('private/secret'),lambda: socket.socket()):
    try: action()
    except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM),e
    else: raise AssertionError('missing real denial')
print('python-native-policy-pass')
"""
    result, base = run(Path(sys.argv[1]), "/usr/bin/python3 -I -B -c " + shlex.quote(program))
    assert result["stdout"] == "python-native-policy-pass\n", result
    assert result["stderr"] == "", result
    assert result["events"][-1]["exitCode"] == 0, result

    # CPython's real CLI opens this file with fopen/FIOCLEX before executing
    # any Python code. A -c/runpy substitute misses that entrypoint failure.
    result, base = run(Path(sys.argv[1]), "/usr/bin/python3 -I -S -B model-entry.py",
        fixture_files={"model-entry.py": b"print(42)\n"})
    assert result["stdout"] == "42\n" and result["stderr"] == "", result
    assert result["events"][-1]["exitCode"] == 0, result
    assert result["events"][-1]["cleanupComplete"], result
