"""APK-owned factory for the fixed authenticated Shizuku bootstrap."""
from tools.executor.native_executor_backend import NativeExecutorBackend
from .processes import Limits, Processes


def factory(options):
    required = {"helper", "handleHelper", "processRunner", "workspace", "executables", "runtime"}
    optional = {"limits", "parentEnvironment", "cwdShim", "ordinaryUid"}
    if type(options) is not dict or not required <= set(options) or set(options) - required - optional:
        raise ValueError("Bionic factory requires its exact supervisor-owned options")
    runtime = options["runtime"]
    if type(runtime) is not list or any(type(item) is not dict or set(item) != {"path", "execute"} for item in runtime):
        raise ValueError("Invalid explicit runtime grant set")
    paths = tuple((item["path"], item["execute"]) for item in runtime)
    limits = Limits(**options.get("limits", {}))
    direct = options.get("ordinaryUid")
    if "ordinaryUid" in options and (type(direct) is not dict or not {"processRunner", "limits"} <= set(direct)
            or set(direct) - {"processRunner", "limits", "ptyProcessRunner"}
            or type(direct["processRunner"]) is not str or type(direct["limits"]) is not dict
            or "ptyProcessRunner" in direct and type(direct["ptyProcessRunner"]) is not str):
        raise ValueError("Direct model execution requires explicit bootstrap runner and limits")

    def processes(runner, workspace, **kwargs):
        return Processes(runner, workspace, runtime=paths, executables=options["executables"],
                         cwd_shim=options.get("cwdShim"), **kwargs)

    backend = NativeExecutorBackend(options["helper"], options["workspace"],
        handle_helper=options["handleHelper"], process_runner=options["processRunner"],
        guest_workspace=options["workspace"], limits=limits,
        parent_environment=options.get("parentEnvironment"), process_factory=processes)
    if direct is not None:
        try:
            from .direct_processes import DirectProcesses, DirectLimits
            from tools.executor.ordinary_uid_files import OrdinaryUidFilesBackend
            direct_processes = DirectProcesses(direct["processRunner"], options["workspace"],
                executables=options["executables"], files_backend=backend.files,
                parent_environment=options.get("parentEnvironment"),
                limits=DirectLimits(**direct["limits"]), quarantine_owner=backend.processes)
            direct_files = OrdinaryUidFilesBackend(lock=backend.files.lock)
            pty_processes = None
            if "ptyProcessRunner" in direct:
                from .tty_processes import TtyProcesses
                pty_processes = TtyProcesses(direct["ptyProcessRunner"], options["workspace"],
                    executables=options["executables"], files_backend=backend.files,
                    parent_environment=options.get("parentEnvironment"),
                    limits=DirectLimits(**direct["limits"]), quarantine_owner=backend.processes)
            backend.install_ordinary_uid_profile(direct_processes, direct_files, pty_processes=pty_processes)
        except BaseException:
            # Selection precedes session binding and no child/stream exists.
            import os
            os.close(backend.files.root)
            backend.files.closed = True
            raise
    return backend
