"""Exercise the real native runner under an unprivileged Linux UID.

No account, shell startup files, user documents, phone or model are used. The
shell and loader paths are resolved from this machine, not hardcoded as grants.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import threading
import time


def runtime_grants(program):
    grants = {str(Path(program).resolve()): {"read", "execute"}}
    result = subprocess.run(["ldd", str(Path(program).resolve())], capture_output=True, text=True, check=True)
    for word in result.stdout.split():
        if word.startswith("/"):
            path = str(Path(word).resolve())
            grants[path] = {"read", "execute"}
    return [{"kind": "file", "path": path, "access": sorted(access)} for path, access in grants.items()]


def run(binary, manifest, cancel=False, extra_fds=()):
    reader, writer = os.pipe()
    packets = []

    def collect():
        with os.fdopen(reader, "rb") as source:
            for line in source:
                packets.append(json.loads(line))

    thread = threading.Thread(target=collect, daemon=True)
    thread.start()
    process = subprocess.Popen([str(binary), "--result-fd", str(writer)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(writer, *extra_fds))
    os.close(writer)
    wire = manifest if isinstance(manifest, bytes) else json.dumps(manifest, ensure_ascii=False).encode()
    if cancel:
        process.stdin.write(wire)
        process.stdin.close()
        process.stdin = None
        deadline = time.monotonic() + 3
        while not packets and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not packets or packets[0]["type"] != "started":
            raise AssertionError("Cancellation test never started")
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
    else:
        stdout, stderr = process.communicate(wire, timeout=15)
    thread.join(timeout=2)
    if thread.is_alive():
        raise AssertionError("Native result channel did not close")
    return process.returncode, stdout, stderr, packets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--security-test", type=Path)
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("Run this test as a non-root UID without capabilities")
    binary = args.binary.resolve()
    with tempfile.TemporaryDirectory(prefix="foldgpt-native-runner-") as temporary:
        base = Path(temporary)
        workspace = base / "workspace"
        workspace.mkdir(mode=0o700)
        outside = base / "outside.txt"
        outside.write_text("outside private bytes")
        outside.chmod(0o600)
        value = workspace / "value.txt"
        value.write_text("initial")
        value.chmod(0o600)
        runtime = runtime_grants("/bin/sh")
        manifest = {"schema": "foldgpt.native-runner.v1", "policy": "landlock-basic-data-v1",
                    "metadata": "visible", "network": "deny", "ipc": "private-pipes-only",
                    "workspace": str(workspace), "cwd": str(workspace), "executable": str(Path("/bin/sh").resolve()),
                    "argv": ["/bin/sh", "-c", "printf updated > value.txt; printf second >> value.txt; printf out; printf err >&2"],
                    "env": {"PATH": "/usr/bin:/bin", "LANG": "C"},
                    "grants": [{"kind": "directory", "path": str(workspace), "access": ["read", "write"]}, *runtime],
                    "limits": {"wallMs": 2000, "outputBytes": 1048576, "addressSpaceBytes": 268435456,
                               "fileBytes": 1048576, "openFiles": 64, "uidProcesses": 64}}
        code, stdout, stderr, events = run(binary, manifest)
        assert (code, stdout, stderr) == (0, b"out", b"err"), (code, stdout, stderr, events)
        assert value.read_bytes() == b"updatedsecond"
        assert events[0]["type"] == "started" and events[-1]["outcome"] == "exited" and events[-1]["exitCode"] == 0
        print("PASS: actual shell creates/modifies file and returns byte-exact separate output", flush=True)

        def command(text, **changes):
            request = copy.deepcopy(manifest)
            request["argv"][-1] = text
            request.update(changes)
            return request

        # Shell redirections perform real opens. Error must not become success;
        # subsequent builtin work demonstrates the shell is actually running.
        for name, grants, target, expected in (
                ("read-only", [{"kind": "file", "path": str(value), "access": ["read"]}, *runtime], value, b"updatedsecond"),
                ("deny-read", runtime, value, None),
                ("outside", manifest["grants"], outside, None)):
            text = f"if printf breach > '{target}'; then exit 90; fi; "
            text += (f"read line < '{target}'; printf '%s' \"$line\"" if expected is not None
                     else f"if read line < '{target}'; then exit 91; fi; printf alive")
            result = run(binary, command(text, grants=grants))
            assert result[0] == 0 and result[3][-1]["exitCode"] == 0, (name, result)
            assert result[1] == (expected if expected is not None else b"alive"), (name, result)
            assert value.read_bytes() == b"updatedsecond" and outside.read_text() == "outside private bytes"
            print(f"PASS: shell {name} actual open checks and parent byte verification", flush=True)

        inherited = os.open(outside, os.O_RDONLY)
        try:
            result = run(binary, command(f"if read line <&{inherited}; then exit 92; fi; printf '%s' \"${{FOLDGPT_PARENT_PRIVATE-unset}}\""), extra_fds=(inherited,))
            assert result[0] == 0 and result[1] == b"unset" and result[3][-1]["exitCode"] == 0, result
        finally:
            os.close(inherited)
        print("PASS: explicitly inherited parent file FD removed and host environment absent", flush=True)

        for name, request in (("unknown", dict(manifest, deny=[str(value)])),
                              ("wrong-policy", dict(manifest, policy="managed")),
                              ("unknown-access", command("exit 0", grants=[{"kind": "file", "path": str(value), "access": ["deny"]}]))):
            result = run(binary, request)
            assert result[0] == 2 and not result[3], (name, result)
        duplicate = json.dumps(manifest).encode().replace(b'"schema":', b'"schema":"duplicate","schema":', 1)
        result = run(binary, duplicate)
        assert result[0] == 2 and not result[3], result
        print("PASS: strict unknown-field/profile/access and duplicate-key rejection", flush=True)

        scudo_envelope = command("printf virtual-envelope")
        scudo_envelope["limits"]["addressSpaceBytes"] = (33 + 1) * (1 << 28)
        result = run(binary, scudo_envelope)
        assert result[0] == 0 and result[1] == b"virtual-envelope" and result[3][-1]["exitCode"] == 0, result
        excessive_envelope = command("exit 0")
        excessive_envelope["limits"]["addressSpaceBytes"] = (1 << 34) + 1
        result = run(binary, excessive_envelope)
        assert result[0] == 2 and not result[3], result
        print("PASS: explicit 8.5 GiB virtual envelope accepted and values above 16 GiB rejected", flush=True)

        result = run(binary, command("exit 7"))
        assert result[0] == 0 and result[3][-1]["exitCode"] == 7, result
        print("PASS: real nonzero command exit preserved", flush=True)

        result = run(binary, command("i=0; while [ \"$i\" -lt 4096 ]; do printf 0123456789abcdef; i=$((i+1)); done; printf tail >&2"))
        assert result[0] == 0 and result[1] == b"0123456789abcdef" * 4096 and result[2] == b"tail", result
        assert result[3][-1]["stdoutBytes"] == len(result[1]) and result[3][-1]["stderrBytes"] == len(result[2])
        print("PASS: complete output drained after leader exit with exact delivered counts", flush=True)

        denied_exec = command("exit 0", grants=[g for g in manifest["grants"] if g["path"] != manifest["executable"]])
        result = run(binary, denied_exec)
        assert result[0] == 1 and all(e["type"] != "started" for e in result[3]) and result[3][-1]["outcome"] == "setup_error", result
        print("PASS: executable denial is setup failure, never a successful started command", flush=True)

        for name, request, cancel in (
                ("timeout", command("while :; do :; done"), False),
                ("cancelled", command("while :; do :; done"), True),
                ("output_limit", command("while :; do printf 0123456789; done"), False)):
            if name == "output_limit":
                request["limits"]["outputBytes"] = 1024
            result = run(binary, request, cancel=cancel)
            assert result[0] == 1 and result[3][-1]["outcome"] == name and result[3][-1]["cleanupComplete"], (name, result)
            if name == "output_limit":
                assert len(result[1]) <= 1024
            print(f"PASS: {name} terminates and reaps command", flush=True)

        result = run(binary, command("(while :; do :; done) & printf '%s' \"$!\"; exit 0"))
        assert result[0] == 0 and result[3][-1]["cleanupComplete"] and result[3][-1]["exitCode"] == 0, result
        child = int(result[1])
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("Background descendant survived command completion")
        print("PASS: real background descendant killed/reaped when shell exits", flush=True)

        alias = workspace / "hardlink.txt"
        os.link(outside, alias)
        result = run(binary, manifest)
        assert result[0] == 2 and not result[3], result
        alias.unlink()
        print("PASS: pre-existing writable hardlink alias rejected before launch", flush=True)

        fifo = workspace / "fifo"
        os.mkfifo(fifo, 0o600)
        result = run(binary, manifest)
        assert result[0] == 2 and not result[3], result
        fifo.unlink()
        print("PASS: special file in workspace rejected without opening its data interface", flush=True)

        if args.security_test:
            # Independent live peer, outside the runner's domain. SIGUSR1's
            # default disposition makes unintended signal delivery observable.
            peer = subprocess.Popen(["sleep", "30"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                security = args.security_test.resolve()
                request = command("unused", executable=str(security))
                request["argv"] = [str(security), str(peer.pid), str(outside), str(value)]
                request["grants"] += [{"kind": "file", "path": str(security), "access": ["read", "execute"]}]
                result = run(binary, request)
                assert result[0] == 0 and result[3][-1]["exitCode"] == 0 and peer.poll() is None, result
                print(result[1].decode(), end="", flush=True)
                assert outside.read_text() == "outside private bytes" and value.stat().st_mode & 0o077 == 0
            finally:
                peer.terminate()
                peer.wait(timeout=5)


if __name__ == "__main__":
    main()
