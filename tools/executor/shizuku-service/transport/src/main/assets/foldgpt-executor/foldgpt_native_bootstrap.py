"""Installed production native owner after an origin-specific C admission.

FD3 is the independent service lifetime. Exec/config/UI traffic uses three
direct Unix sockets acquired through the private startup manifest. Stdio is
never used as a Java relay or as an alternate executor.
"""
import asyncio
from collections import namedtuple
import importlib
import os
from pathlib import Path
import re
import signal
import stat
import sys
import zipfile

from foldgpt_shizuku_bootstrap import (
    installed_backend_options, report, report_cleanup_failure, report_setup_failure, strict_json,
)

DATA = Path("/data/user/0/app.foldgpt")
RUNTIME = DATA / "files/native-runtime-v1/python"
PROJECTS = DATA / "files/projects"
BROKER = DATA / "app_foldgpt_exec"
ASSET = "assets/foldgpt-executor-deployment.json"
FACTORY = "tools.executor.bionic-supervisor.factory:factory"
BootstrapPaths = namedtuple("BootstrapPaths", "data runtime projects broker")


def launch_contract(launch_origin):
    if launch_origin == "run-as":
        return "foldgpt.native.deployment.v1", 0
    if launch_origin == "android-app":
        return "foldgpt.native.deployment.v2", 2
    raise ValueError("Unknown installed native launch origin")


def process_context(status, context, *, launch_origin="run-as"):
    """Validate observed kernel state, never infer it from a deployment flag."""
    _, seccomp = launch_contract(launch_origin)
    for name in ("CapInh", "CapPrm", "CapEff", "CapAmb"):
        if int(status[name].strip(), 16) != 0:
            raise ValueError("Native bootstrap must not possess capabilities")
    if int(status["NoNewPrivs"].strip()) != 0 or int(status["Seccomp"].strip()) != seccomp:
        raise ValueError("Native bootstrap did not preserve its admitted process state")
    filters = int(status["Seccomp_filters"].strip())
    if (seccomp == 0 and filters != 0) or (seccomp == 2 and filters < 1):
        raise ValueError("Native bootstrap inherited filter count differs")
    if launch_origin == "run-as":
        if not context.startswith("u:r:runas_app:"):
            raise ValueError("Native bootstrap has an unexpected Android process context")
    else:
        # The application context is checked against actual collected device
        # evidence. The final domain check is defined by the app entry module.
        from foldgpt_app_bootstrap import application_context
        application_context(status, context)


def identity(uid, parent, nonce, launch_path, *, launch_origin="run-as"):
    launch_contract(launch_origin)
    if (sys.platform != "android" or not sys.flags.isolated or not sys.flags.no_site
            or not sys.dont_write_bytecode or uid < 10000
            or os.getresuid() != (uid,) * 3 or os.getresgid() != (uid,) * 3
            or parent <= 0 or os.getppid() != parent
            or re.fullmatch(r"[0-9a-f]{32}", nonce) is None):
        raise ValueError("Installed native bootstrap identity or launch input differs")
    paths = runtime_paths(uid, launch_origin=launch_origin)
    if Path(launch_path) != paths.broker / nonce / "launch.json" or Path.cwd() != paths.data:
        raise ValueError("Installed native bootstrap private path or working directory differs")
    with open("/proc/self/status", encoding="ascii") as source:
        status = dict(line.split(":", 1) for line in source.read(65536).splitlines() if ":" in line)
    with open("/proc/self/attr/current", encoding="ascii") as source:
        context = source.read(4096).rstrip("\n\0")
    process_context(status, context, launch_origin=launch_origin)
    return paths


def runtime_paths(uid, *, launch_origin="run-as"):
    launch_contract(launch_origin)
    if launch_origin == "android-app":
        from foldgpt_app_bootstrap import application_paths
        return application_paths(uid)
    return BootstrapPaths(DATA, RUNTIME, PROJECTS, BROKER)


def deployment(apk, *, launch_origin="run-as"):
    launch_contract(launch_origin)
    if not apk.startswith("/data/app/") or os.path.realpath(apk) != apk:
        raise ValueError("Native bootstrap must load its installed canonical APK")
    with zipfile.ZipFile(apk) as archive:
        item = archive.getinfo(ASSET)
        if item.file_size > 65536 or archive.namelist().count(ASSET) != 1:
            raise ValueError("Native deployment asset is not uniquely bounded")
        config = strict_json(archive.read(item))
    return deployment_contract(config, launch_origin=launch_origin)


def deployment_contract(config, *, launch_origin="run-as"):
    schema, _ = launch_contract(launch_origin)
    fields = {"schema", "packageName", "pythonLibrary", "pythonSha256", "nativeLibraries",
              "pythonRuntime", "backendFactory", "backendOptions"}
    if launch_origin == "android-app":
        fields.add("launchOrigin")
    if (type(config) is not dict or set(config) != fields
            or config["schema"] != schema
            or launch_origin == "android-app" and config["launchOrigin"] != "android-app"
            or config["packageName"] != "app.foldgpt"
            or config["pythonLibrary"] != "libfoldgpt_python_cli.so"
            or config["backendFactory"] != FACTORY):
        raise ValueError("Native deployment differs from its exact installed contract")
    runtime = config["pythonRuntime"]
    if (type(runtime) is not dict or set(runtime) != {"path", "manifestAsset", "manifestSha256"}
            or runtime["path"] != RUNTIME.as_posix()
            or runtime["manifestAsset"] != "foldgpt-python-runtime.json"
            or type(runtime["manifestSha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", runtime["manifestSha256"]) is None):
        raise ValueError("Native Python runtime differs from the admitted production prefix")
    options = config["backendOptions"]
    required = {"helper", "handleHelper", "processRunner", "executables", "runtime", "limits", "cwdShim"}
    if (type(options) is not dict or not required <= set(options)
            or set(options) - required - {"ordinaryUid"}):
        raise ValueError("Native deployment must not supply a model workspace or inherited environment")
    if "ordinaryUid" in options:
        direct = options["ordinaryUid"]
        if (type(direct) is not dict or not {"processRunner", "limits"} <= set(direct)
                or set(direct) - {"processRunner", "limits", "ptyProcessRunner"}
                or direct["processRunner"] != "@nativeLibraryDir/libfoldgpt_direct_runner.so"
                or "ptyProcessRunner" in direct and direct["ptyProcessRunner"] != "@nativeLibraryDir/libfoldgpt_direct_pty_supervisor.so"
                or type(direct["limits"]) is not dict or direct["limits"]):
            raise ValueError("Ordinary UID production execution requires its installed runner and standard limits")
    return config


def production_entrypoints(executables, native, libraries):
    """Admit only the exact installed commands, with their identical absolute paths."""
    bash, python = str(native / "libfoldgpt_bash.so"), str(native / "libfoldgpt_python_cli.so")
    expected = {"bash": bash, "python": python, "python3": python}
    if "libfoldgpt_rg.so" in libraries:
        expected["rg"] = str(native / "libfoldgpt_rg.so")
    if executables != expected:
        raise ValueError("Production entrypoints must identify the exact installed native commands")
    # environment/info advertises absolute shell paths. They must name these
    # same admitted executables; no RPC-selected or external ELF is admitted.
    return {**expected, **{path: path for path in expected.values()}}


def production_options(config, workspace, *, launch_origin="run-as"):
    from tools.executor.native_path_uri import path_uri
    paths = runtime_paths(os.getuid(), launch_origin=launch_origin)
    options = installed_backend_options(config)
    native = Path(os.readlink("/proc/self/exe")).parent
    if not str(native).startswith("/data/app/") or native.resolve(strict=True) != native:
        raise ValueError("Production native executable directory differs")
    names = {"helper": "libfoldgpt_native_files.so", "handleHelper": "libfoldgpt_native_file_handle.so",
             "processRunner": "libfoldgpt_bionic_supervisor.so"}
    if any(options[name] != str(native / library) for name, library in names.items()):
        raise ValueError("Production helper does not identify its installed executable")
    if "ordinaryUid" in options and options["ordinaryUid"]["processRunner"] != str(native / "libfoldgpt_direct_runner.so"):
        raise ValueError("Ordinary UID runner does not identify its installed executable")
    if ("ordinaryUid" in options and "ptyProcessRunner" in options["ordinaryUid"]
            and options["ordinaryUid"]["ptyProcessRunner"] != str(native / "libfoldgpt_direct_pty_supervisor.so")):
        raise ValueError("Ordinary UID PTY runner does not identify its installed executable")
    bash, python = str(native / "libfoldgpt_bash.so"), str(native / "libfoldgpt_python_cli.so")
    options["executables"] = production_entrypoints(options["executables"], native, config["nativeLibraries"])
    options["workspace"] = workspace
    if launch_origin == "android-app":
        # Only the exact compiled Python prefix may change spelling, after the
        # local same-inode app-root and exact private suffix checks above.
        options["runtime"] = [dict(grant, path=str(paths.runtime))
                              if grant["path"] == str(RUNTIME) else grant
                              for grant in options["runtime"]]
    options["runtime"] = [*options["runtime"], {"path": str(native), "execute": True}]
    temporary = str(Path(workspace) / ".foldgpt-tmp")
    options["parentEnvironment"] = {"HOME": workspace, "TMPDIR": temporary,
        "PATH": str(paths.runtime / "bin") + ":/system/bin", "SHELL": bash, "LANG": "C.UTF-8"}
    info = {"cwd": path_uri(workspace), "userHomeDir": path_uri(workspace),
        "platformOs": "android", "shell": {"name": "bash", "path": bash},
        "temporaryDirectories": [path_uri(temporary)], "tempDir": path_uri(temporary)}
    return options, info, native


def temporary_directory(backend):
    # Acquire the backend's actual workspace lock before preparing its temporary
    # directory. Existing contents are retained; aliases and foreign ownership
    # are refused instead of changing existing permissions or replacing paths.
    try:
        os.mkdir(".foldgpt-tmp", mode=0o700, dir_fd=backend.files.root)
    except FileExistsError:
        pass
    descriptor = os.open(".foldgpt-tmp", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=backend.files.root)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Native temporary directory must remain private and owned")
    finally:
        os.close(descriptor)


async def cleanup_resources(backend, server, acquisition, manifest, owner, factory_entered):
    """Return actual cleanup outcome and its first bounded diagnostic input."""
    clean = not factory_entered
    stage = "backend_close"
    try:
        if backend is not None:
            await backend.close(server.session_id if server is not None else None)
            stage = "process_cleanup"
            if backend.processes.quarantined:
                raise RuntimeError("Production native process cleanup is unresolved")
            clean = True
        if clean:
            if acquisition is not None:
                stage = "acquisition_close"
                acquisition.close_endpoint()
            if manifest is not None:
                stage = "manifest_remove"
                manifest.remove()
                stage = "manifest_close"
                manifest.close()
            if owner is not None:
                if owner.process_identity is not None:
                    stage = "session_finish"
                    owner.finish_process_session()
                stage = "owner_close"
                owner.close()
    except BaseException as error:
        return False, (stage, error)
    return clean, None


async def run(apk, uid, parent, nonce, launch_path, control_fd=3, *, launch_origin="run-as"):
    backend = server = owner = acquisition = manifest = None
    factory_entered = ready = reader_registered = False
    exit_code = 0
    serving = stopping = None
    cancelled = asyncio.Event()
    loop = asyncio.get_running_loop()

    def control_ready():
        try:
            os.read(control_fd, 1)
        except BlockingIOError:
            return
        loop.remove_reader(control_fd)
        cancelled.set()

    stage = "control"
    try:
        paths = identity(uid, parent, nonce, launch_path, launch_origin=launch_origin)
        os.set_inheritable(control_fd, False)
        os.set_blocking(control_fd, False)
        loop.add_reader(control_fd, control_ready)
        reader_registered = True
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, cancelled.set)
        stage = "imports"
        from tools.executor.native_runtime_acquisition import NativeRuntimeAcquisition, SessionExecServer
        from tools.executor.native_runtime_startup import StartupManifest, read_launch
        from tools.executor.native_path_uri import path_uri
        from tools.executor.native_host_bootstrap_v2 import installed_host_factory
        from tools.executor.private_exec_broker import PrivateSessionOwner
        stage = "deployment"
        config = deployment(apk, launch_origin=launch_origin)
        launch = read_launch(launch_path, uid=uid, broker_directory=paths.broker / nonce,
                             projects_directory=paths.projects, launch_origin=launch_origin)
        stage = "native_inventory"
        options, environment, native = production_options(config, launch["workspace"], launch_origin=launch_origin)
        host_factory = installed_host_factory(apk, config, options, native)
        stage = "broker_open"
        owner = PrivateSessionOwner(paths.broker,
            boot_epoch=launch["bootEpoch"] if launch_origin == "android-app" else None)
        stage = "workspace_claim"
        owner.begin_process_session(launch["workspace"])
        stage = "factory_import"
        module = importlib.import_module(FACTORY.split(":", 1)[0])
        if not getattr(module, "__file__", "").startswith(apk + "/assets/foldgpt-executor/"):
            raise ValueError("Native backend factory must come from this installed APK")
        stage = "factory_construct"
        factory_entered = True
        backend = module.factory(options)
        stage = "workspace_verify"
        declared = os.stat(launch["workspace"], follow_symlinks=False)
        pinned = os.fstat(backend.files.root)
        if (not stat.S_ISDIR(pinned.st_mode)
                or (declared.st_dev, declared.st_ino) != (pinned.st_dev, pinned.st_ino)
                or path_uri(backend.mount.path) != environment["cwd"]):
            raise ValueError("Production workspace differs from the actual pinned backend")
        temporary_directory(backend)
        stage = "server_construct"
        server = SessionExecServer(backend, environment_info=environment)
        acquisition = NativeRuntimeAcquisition(launch["socketPath"], server, controller_uid=uid,
            host_channel_factory=host_factory)
        manifest = StartupManifest(launch["manifestPath"], socket_path=acquisition.path,
            workspace=launch["workspace"], shared_paths=[launch["workspace"], str(paths.runtime), str(native)],
            controller_roots=launch["controllerRoots"],
            parent_environment=dict(backend.processes.parent_environment), directory_fd=acquisition.directory_fd,
            host_schema=host_factory.schema if host_factory is not None else None)
        # The C setup alarm stays active throughout imports and publication.
        # The acquisition now owns bounded admission and the persistent native
        # owner owns cleanup/quarantine; no process has been admitted yet.
        signal.alarm(0)
        serving = asyncio.create_task(acquisition.run())
        stopping = asyncio.create_task(cancelled.wait())
        report("ready")
        ready = True
        await asyncio.wait((serving, stopping), return_when=asyncio.FIRST_COMPLETED)
        if stopping.done() and not serving.done():
            serving.cancel()
        results = await asyncio.gather(serving, return_exceptions=True)
        result = results[0]
        if isinstance(result, BaseException) and not (
                isinstance(result, asyncio.CancelledError) and cancelled.is_set()
                or isinstance(result, EOFError) and server.initialized):
            exit_code = 70
    except BaseException as error:
        exit_code = 70
        if not ready:
            report_setup_failure(stage, error)
    finally:
        # Do not let an inherited setup alarm destroy an unresolved owner.
        signal.alarm(0)
        if reader_registered:
            loop.remove_reader(control_fd)
        for task in (stopping, serving):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (stopping, serving) if task is not None), return_exceptions=True)
        clean, cleanup_error = await cleanup_resources(backend, server, acquisition, manifest, owner, factory_entered)
        if not clean:
            if owner is not None:
                owner.quarantined = True
                owner.retained_backend = backend
            try:
                if cleanup_error is not None:
                    report_cleanup_failure(*cleanup_error)
                report("quarantined", cleanupComplete=False)
            finally:
                for descriptor in (0, 1):
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                # A broken diagnostic pipe cannot release an unresolved owner.
                # The same lock, marker, backend and native children stay alive.
                await asyncio.Event().wait()
        report("closed", cleanupComplete=True, exitCode=exit_code)
    return exit_code


def main(arguments):
    if len(arguments) != 5:
        raise ValueError("Installed native launch argument count differs")
    apk, uid, parent, nonce, launch_path = arguments
    os._exit(asyncio.run(run(apk, int(uid), int(parent), nonce, launch_path)))
