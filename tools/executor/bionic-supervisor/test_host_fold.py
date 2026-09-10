"""Fixed real Fold human-primitives qualification; never an ADB launcher.

Run only as an authenticated UserService -> run-as -> installed Bionic Python
descendant. The existing production bootstrap checks the launch identity and
resolves the current PackageManager-attested native directory. This module is
not selected by production, and its results do not qualify the official editor.
"""
import argparse
import asyncio
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import signal
import stat
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def require(value, message):
    if not value:
        raise AssertionError(message)


def save_new(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(data)
        while view:
            count = os.write(fd, view)
            require(count > 0, "Incomplete qualification evidence write")
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)


async def qualify(args):
    # These are the actual currently packaged production admission functions.
    # An external shell UID or copied PC Python result cannot pass this check.
    from foldgpt_native_bootstrap import (
        BROKER, DATA, PROJECTS, RUNTIME, deployment, identity, production_options,
    )
    from foldgpt_shizuku_bootstrap import verify_library
    from tools.executor.exec_server import BackendCall, RpcError, encode_message
    from tools.executor.native_host_files import create_host_file_authority
    factory = importlib.import_module("tools.executor.bionic-supervisor.factory").factory
    human = importlib.import_module("tools.executor.bionic-supervisor.host_processes")

    identity(args.expected_uid, args.expected_parent, args.nonce, args.launch_path)
    evidence = BROKER / args.nonce / "human-qualification"
    workspace = PROJECTS / ("human-qualification-" + args.nonce)
    for parent in (evidence.parent, PROJECTS):
        info = parent.stat()
        require(parent.resolve(strict=True) == parent and stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o077,
                "Qualification requires an existing private app-owned parent")
    evidence.mkdir(mode=0o700, exist_ok=False)
    workspace.mkdir(mode=0o700, exist_ok=False)
    config = deployment(args.apk)
    options, _, native = production_options(config, str(workspace))
    runner = verify_library(str(native), "libfoldgpt_host_supervisor.so", args.host_sha256)
    report = {"schema": "foldgpt.native.human-primitives.v1", "passed": False,
              "officialEditorQualified": False, "launchReceiptRequired": True,
              "workspace": str(workspace), "evidence": str(evidence),
              "pid": os.getpid(), "parentPid": os.getppid(),
              "uid": list(os.getresuid()), "gid": list(os.getresgid()),
              "nativeLibraryDir": str(native), "pythonRuntime": str(RUNTIME),
              "hostRunnerSha256": args.host_sha256, "cases": [], "workers": []}
    backend = processes = task = None
    cancelled = asyncio.Event()
    loop = asyncio.get_running_loop()
    os.set_inheritable(3, False)
    os.set_blocking(3, False)

    def control_ready():
        try:
            os.read(3, 1)
        except BlockingIOError:
            return
        loop.remove_reader(3)
        cancelled.set()

    loop.add_reader(3, control_ready)
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, cancelled.set)
    cancellation = asyncio.create_task(cancelled.wait())
    try:
        backend = factory(options)
        authority = create_host_file_authority(backend, session_id=args.nonce)
        executables = dict(options["executables"])
        executables.update({"sh": str(native / "libfoldgpt_bash.so"), "toybox": "/system/bin/toybox"})
        processes = human.HostProcesses(authority, runner,
            runtime=[(item["path"], item["execute"]) for item in options["runtime"]],
            executables=executables, cwd_shim=options["cwdShim"])
        (workspace / ".foldgpt-tmp").mkdir(mode=0o700)
        (workspace / "private").mkdir(mode=0o700)
        private = workspace / "private/secret"
        save_new(private, b"real private native bytes\0")
        outside = evidence / "outside-sentinel"
        save_new(outside, b"outside workspace unchanged")
        environment = {"HOME": str(workspace), "TMPDIR": str(workspace / ".foldgpt-tmp"),
                       "PATH": str(RUNTIME / "bin") + ":/system/bin", "LANG": "C.UTF-8"}

        async def command(name, argv, *, stdin=None, cancel_marker=None):
            streams = {"stdout": bytearray(), "stderr": bytearray()}
            sequences = []
            marked = asyncio.Event()

            async def notify(method, params):
                sequences.append((method, params["seq"]))
                if method == "process/output":
                    streams[params["stream"]].extend(base64.b64decode(params["chunk"], validate=True))
                    if cancel_marker and cancel_marker in streams["stdout"]:
                        marked.set()

            record = await processes.spawn(name, argv, "/", environment,
                pipe_stdin=stdin is not None, notify=notify)
            if stdin is not None:
                for offset in range(0, len(stdin), 32768):
                    await processes.write(record, stdin[offset:offset + 32768], close_stdin=False)
                await processes.write(record, b"", close_stdin=True)
            if cancel_marker:
                await asyncio.wait_for(marked.wait(), 10)
                processes._terminate(record)
            await asyncio.wait_for(asyncio.shield(record.finished), 30)
            await asyncio.wait_for(asyncio.shield(record.notifier), 10)
            item = {"name": name, "argv": argv, "cwd": "/", "nativeResult": record.native_result,
                    "failure": record.failure, "supervisorReturncode": record.process.returncode,
                    "streams": {key: {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
                                for key, value in streams.items()}}
            report["workers"].append(item)
            require(record.closed and record.native_result["cleanupComplete"]
                    and record.process.returncode == 0 and record.failure is None,
                    "Real native human cleanup or supervisor outcome differs")
            require([seq for _, seq in sequences] == list(range(1, len(sequences) + 1))
                    and sequences[-1][0] == "process/closed", "Native output sequence is incomplete")
            return bytes(streams["stdout"]), bytes(streams["stderr"]), record

        async def cases():
            out, err, record = await command("python-root-read", ["python", "-I", "-S", "-B", "-c",
                "import os,sys; sys.stdout.buffer.write(os.getcwd().encode()+b'\\n'+open(sys.argv[1],'rb').read())",
                str(private)])
            require((out, err, record.exit_code) == (b"/\nreal private native bytes\0", b"", 0),
                    "Bionic Python cwd or actual private bytes differ")
            context = {"permissions": {"type": "managed", "file_system": {"type": "restricted", "entries": [
                {"path": {"type": "path", "path": workspace.as_uri()}, "access": "write"},
                {"path": {"type": "path", "path": (workspace / "private").as_uri()}, "access": "deny"}]},
                "network": "restricted"}, "cwd": workspace.as_uri(), "workspaceRoots": [workspace.as_uri()],
                "windowsSandboxLevel": "disabled"}
            async def denied_notify(*_):
                raise AssertionError("Model file denial emitted process output")
            try:
                await backend.handle(BackendCall(args.nonce, 1, "fs/readFile", encode_message({
                    "path": private.as_uri(), "sandbox": context})), denied_notify)
            except RpcError:
                pass
            else:
                raise AssertionError("Model-private file became accessible to the model")
            report["cases"].append("Bionic Python reads private W file at actual cwd /; model denial remains")

            data = bytes(range(256)) * 8193
            saved = workspace / "python-save.bin"
            out, err, record = await command("python-stdin-eof", ["python", "-I", "-S", "-B", "-c",
                "import sys; data=sys.stdin.buffer.read(); open(sys.argv[1],'wb').write(data)", str(saved)], stdin=data)
            require((out, err, record.exit_code) == (b"", b"", 0) and saved.read_bytes() == data,
                    "Real Python stdin and EOF save differs")
            require(await authority.read_file(saved.as_uri()) == data, "Human native file authority sees other bytes")
            report["cases"].append("Bionic Python saves 2097408 stdin bytes through EOF; native file authority matches")

            large = bytes(range(256)) * 40961
            large_file = workspace / "large.bin"
            save_new(large_file, large)
            out, err, record = await command("python-large-read", ["python", "-I", "-S", "-B", "-c",
                "import sys; sys.stdout.buffer.write(open(sys.argv[1],'rb').read())", str(large_file)])
            require((out, err, record.exit_code) == (large, b"", 0), "Uncapped real native output lost bytes")
            report["cases"].append("Bionic Python returns 10486016 exact stdout bytes without the model output cap")

            out, _, record = await command("python-outside-refusal", ["python", "-I", "-S", "-B", "-c",
                "import sys; sys.stdout.buffer.write(open(sys.argv[1],'rb').read())", str(outside)])
            require(not out and record.exit_code != 0 and outside.read_bytes() == b"outside workspace unchanged",
                    "Actual cwd / incorrectly grants an outside file")
            report["cases"].append("Bionic Python cannot read outside W while cwd is /")

            shell_file = workspace / "shell-save.bin"
            out, err, record = await command("real-bash-toybox-save", ["sh", "--noprofile", "--norc", "-c",
                '/system/bin/toybox cat > "$1"', "sh", str(shell_file)], stdin=data)
            require((out, err, record.exit_code) == (b"", b"", 0) and shell_file.read_bytes() == data,
                    "Actual APK Bash plus Android toybox stdin save failed")
            report["cases"].append("Actual APK Bash and Android toybox cat save stdin through EOF")

            out, _, record = await command("real-descendant-cancel", ["sh", "--noprofile", "--norc", "-c",
                "/system/bin/toybox sleep 20 & printf ready; wait"], cancel_marker=b"ready")
            require(out == b"ready" and record.native_result["outcome"] == "cancelled",
                    "Real shell descendant cancellation was not completed")
            report["cases"].append("Actual shell and toybox descendant are cancelled and reaped by native owner")

        task = asyncio.create_task(cases())
        await asyncio.wait((task, cancellation), return_when=asyncio.FIRST_COMPLETED)
        if cancelled.is_set():
            raise RuntimeError("Service lifetime ended during qualification")
        task.result()
        report["passed"] = True
    except BaseException as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        cancellation.cancel()
        await asyncio.gather(cancellation, return_exceptions=True)
        loop.remove_reader(3)
        if backend is not None:
            try:
                await backend.close(args.nonce)
                report["ownerClosed"] = True
            except BaseException as error:
                report["passed"] = False
                report["ownerClosed"] = False
                report["cleanupError"] = {"type": type(error).__name__, "message": str(error)}
        save_new(evidence / "result.json", (json.dumps(report, indent=2) + "\n").encode())
    print(json.dumps({"passed": report["passed"], "report": str(evidence / "result.json"),
                      "officialEditorQualified": False}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True)
    parser.add_argument("--expected-uid", type=int, required=True)
    parser.add_argument("--expected-parent", type=int, required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--launch-path", required=True)
    parser.add_argument("--host-sha256", required=True)
    sys.exit(asyncio.run(qualify(parser.parse_args())))
