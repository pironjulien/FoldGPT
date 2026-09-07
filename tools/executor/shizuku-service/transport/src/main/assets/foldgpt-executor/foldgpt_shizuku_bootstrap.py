"""Fixed APK-owned ExecServer host. FD 3 is service lifetime, never worker stdin.

This module hosts an installed, qualified backend factory. It does not implement
or loosen that backend's sandbox. No execution configuration comes from RPC.
"""
import asyncio
import hashlib
import importlib
import json
import os
import re
import signal
import stat
import sys
import zipfile

SCHEMA = "foldgpt.shizuku.session.v1"
ASSET = "assets/foldgpt-executor-deployment.json"
CWD_NAME = "libfoldgpt_bionic_cwd.so"
CWD_PATH = "@nativeLibraryDir/" + CWD_NAME


def report(event, **fields):
    encoded = json.dumps(dict(schema=SCHEMA, event=event, **fields), separators=(",", ":")).encode("ascii") + b"\n"
    # Small atomic private pipe record. Never multiplex worker output here.
    if os.write(2, encoded) != len(encoded):
        raise OSError("Incomplete private lifecycle report")


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate deployment field")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite deployment value")))


def read_deployment(apk):
    with zipfile.ZipFile(apk) as archive:
        info = archive.getinfo(ASSET)
        if info.file_size > 65536 or sum(name == ASSET for name in archive.namelist()) != 1:
            raise ValueError("Invalid installed deployment asset")
        config = strict_json(archive.read(info))
    required = {"schema", "packageName", "pythonLibrary", "pythonSha256", "brokerDirectory",
                "workspace", "backendFactory", "backendOptions", "environmentInfo"}
    if type(config) is not dict or set(config) != required or config["schema"] != "foldgpt.shizuku.deployment.v1":
        raise ValueError("Invalid deployment schema")
    for name in ("brokerDirectory", "workspace"):
        value = config[name]
        if type(value) is not str or not value.startswith("/") or os.path.realpath(value) != value:
            raise ValueError("Deployment paths must be canonical and absolute")
    if (type(config["backendFactory"]) is not str or
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*:[A-Za-z_][A-Za-z0-9_]*", config["backendFactory"]) is None or
            type(config["backendOptions"]) is not dict or type(config["environmentInfo"]) is not dict):
        raise ValueError("Invalid installed backend contract")
    return config


def installed_backend_options(config):
    """Resolve the one fixed cwd library alongside the actual installed ELF.

    Java already checked PackageManager.nativeLibraryDir before spawning this
    interpreter. Never trust a deployment-provided /data/app path, environment
    variable or an RPC argument for this relocatable package location.
    """
    options = dict(config["backendOptions"])
    if "cwdShim" not in options:
        return options
    shim = options["cwdShim"]
    if (type(shim) is not dict or set(shim) != {"path", "sha256"} or shim["path"] != CWD_PATH or
            type(shim["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", shim["sha256"]) is None):
        raise ValueError("cwdShim must identify the fixed installed library and its digest")
    executable = os.readlink("/proc/self/exe")
    if (not executable.startswith("/") or os.path.realpath(executable) != executable or
            sys.executable != executable or os.path.basename(executable) != config["pythonLibrary"]):
        raise ValueError("Actual bootstrap executable differs from its installed interpreter")
    path = os.path.join(os.path.dirname(executable), CWD_NAME)
    if os.path.realpath(path) != path:
        raise ValueError("Installed cwd library has an alias")
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_size > 16777216:
            raise ValueError("Installed cwd library must be a bounded ordinary package file")
        digest = hashlib.sha256()
        while data := os.read(fd, 65536):
            digest.update(data)
        if digest.hexdigest() != shim["sha256"]:
            raise ValueError("Installed cwd library digest mismatch")
    finally:
        os.close(fd)
    options["cwdShim"] = {"path": path, "sha256": shim["sha256"]}
    return options


async def run_session(apk, control_fd=3):
    from tools.executor.exec_server import ExecServer, serve_stdio
    from tools.executor.private_exec_broker import PrivateListener

    backend = server = owner = None
    factory_entered = False
    exit_code = 0
    cancelled = asyncio.Event()
    loop = asyncio.get_running_loop()
    os.set_inheritable(control_fd, False)
    os.set_blocking(control_fd, False)

    def control_ready():
        # The only accepted service operation is cancellation. Data and EOF
        # both request it, independently of blocked client RPC stdin/stdout.
        try:
            os.read(control_fd, 1)
        except BlockingIOError:
            return
        loop.remove_reader(control_fd)
        cancelled.set()

    loop.add_reader(control_fd, control_ready)
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, cancelled.set)
    serving = stopping = None
    try:
        config = read_deployment(apk)
        options = installed_backend_options(config)
        owner = PrivateListener(config["brokerDirectory"])
        owner.begin_process_session(config["workspace"])
        module_name, function_name = config["backendFactory"].split(":")
        factory_entered = True
        module = importlib.import_module(module_name)
        prefix = apk + "/assets/foldgpt-executor/"
        if not getattr(module, "__file__", "").startswith(prefix):
            raise ValueError("Backend factory must come from this installed APK")
        factory = getattr(module, function_name)
        if not callable(factory):
            raise ValueError("Installed backend factory is not callable")
        # Constructor failures after entering trusted backend code cannot prove
        # that no child/resource exists. Keep the persistent marker on failure.
        backend = factory(options)
        declared = os.stat(config["workspace"], follow_symlinks=False)
        pinned = os.fstat(backend.files.root)
        if not stat.S_ISDIR(pinned.st_mode) or (declared.st_dev, declared.st_ino) != (pinned.st_dev, pinned.st_ino):
            raise ValueError("Backend root differs from the persisted workspace identity")
        if config["environmentInfo"].get("cwd") != backend.mount.uri:
            raise ValueError("Deployment cwd differs from pinned backend workspace")
        server = ExecServer(backend, environment_info=config["environmentInfo"])
        report("ready")
        serving = asyncio.create_task(serve_stdio(server))
        stopping = asyncio.create_task(cancelled.wait())
        await asyncio.wait((serving, stopping), return_when=asyncio.FIRST_COMPLETED)
        if stopping.done() and not serving.done():
            serving.cancel()
        results = await asyncio.gather(serving, return_exceptions=True)
        if isinstance(results[0], Exception):
            exit_code = 70
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        exit_code = 70
    finally:
        loop.remove_reader(control_fd)
        for task in (stopping, serving):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (stopping, serving) if task is not None), return_exceptions=True)
        clean = False
        try:
            if backend is not None:
                await backend.close(server.session_id if server is not None else None)
                if getattr(backend.processes, "quarantined", False):
                    raise RuntimeError("Backend retains unresolved process cleanup")
                clean = True
            else:
                clean = not factory_entered
            if clean and owner is not None:
                if owner.process_identity is not None:
                    owner.finish_process_session()
                owner.close()
        except BaseException:
            clean = False
        if not clean:
            if owner is not None:
                owner.quarantined = True
                owner.retained_backend = backend
            report("quarantined", cleanupComplete=False)
            # Keep the ACTUAL backend, pinned roots and process objects alive.
            # Never destroy the native owner, delete a marker, or auto-retry.
            await asyncio.Event().wait()
        report("closed", cleanupComplete=True, exitCode=exit_code)
    return exit_code


def main(apk):
    if os.getuid() != 2000 or os.geteuid() != 2000:
        raise RuntimeError("This installed backend requires non-root shell UID 2000")
    result = asyncio.run(run_session(apk))
    # RPC uses unbuffered stdio and its own termination grace. Avoid interpreter
    # shutdown joining an abandoned pipe-I/O worker after native cleanup.
    os._exit(result)
