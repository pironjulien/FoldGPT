"""Explicit APK-selected human v2 authority, separate from model deployment.

No request can choose this factory, native runner, runtime or executable map.
An absent asset keeps the existing v1 startup. A malformed or mismatched asset
fails admission; it never silently retries v1 or controller execution.
"""
import importlib
from pathlib import Path
import zipfile

ASSET = "assets/foldgpt-host-deployment.json"
SCHEMA = "foldgpt.host.v2"
RUNNER = "libfoldgpt_host_supervisor.so"


class HostChannelFactoryV2:
    schema = SCHEMA

    def __init__(self, runner, *, runtime, executables, cwd_shim):
        self.runner = runner
        self.runtime = tuple(runtime)
        self.executables = dict(executables)
        self.cwd_shim = dict(cwd_shim) if cwd_shim is not None else None

    def __call__(self, descriptor, authority, *, peer):
        from tools.executor.native_host_channel_v2 import HostChannelV2
        process_type = importlib.import_module("tools.executor.bionic-supervisor.host_processes").HostProcesses
        processes = process_type(authority, self.runner, runtime=self.runtime,
            executables=self.executables, cwd_shim=self.cwd_shim)
        return HostChannelV2(descriptor, authority, processes=processes, peer=peer)


def installed_host_factory(apk, config, options, native):
    from foldgpt_shizuku_bootstrap import strict_json, verify_library
    with zipfile.ZipFile(apk) as archive:
        count = archive.namelist().count(ASSET)
        if count == 0:
            return None
        if count != 1 or archive.getinfo(ASSET).file_size > 4096:
            raise ValueError("Human deployment asset must be unique and bounded")
        value = strict_json(archive.read(ASSET))
    if (type(value) is not dict or set(value) != {"schema", "runner", "runnerSha256"}
            or value["schema"] != SCHEMA or value["runner"] != RUNNER
            or config["nativeLibraries"].get(RUNNER) != value["runnerSha256"]):
        raise ValueError("Human deployment differs from the installed native inventory")
    runner = verify_library(str(native), RUNNER, value["runnerSha256"])
    native = Path(native)
    executables = dict(options["executables"])
    # These are actual immutable Android executables. Preserve the requested
    # argv: toybox dispatches `cat` by argv[0], and Bash accepts sh invocation.
    executables.update({"cat": "/system/bin/toybox", "toybox": "/system/bin/toybox",
                        "sh": str(native / "libfoldgpt_bash.so")})
    return HostChannelFactoryV2(runner,
        runtime=[(item["path"], item["execute"]) for item in options["runtime"]],
        executables=executables, cwd_shim=options["cwdShim"])
