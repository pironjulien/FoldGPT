"""APK-owned factory for the fixed authenticated Shizuku bootstrap."""
from tools.executor.native_executor_backend import NativeExecutorBackend
from .processes import Limits, Processes


def factory(options):
    required = {"helper", "handleHelper", "processRunner", "workspace", "executables", "runtime"}
    optional = {"limits", "parentEnvironment", "cwdShim"}
    if type(options) is not dict or not required <= set(options) or set(options) - required - optional:
        raise ValueError("Bionic factory requires its exact supervisor-owned options")
    runtime = options["runtime"]
    if type(runtime) is not list or any(type(item) is not dict or set(item) != {"path", "execute"} for item in runtime):
        raise ValueError("Invalid explicit runtime grant set")
    paths = tuple((item["path"], item["execute"]) for item in runtime)
    limits = Limits(**options.get("limits", {}))

    def processes(runner, workspace, **kwargs):
        return Processes(runner, workspace, runtime=paths, executables=options["executables"],
                         cwd_shim=options.get("cwdShim"), **kwargs)

    return NativeExecutorBackend(options["helper"], options["workspace"],
        handle_helper=options["handleHelper"], process_runner=options["processRunner"],
        guest_workspace=options["workspace"], limits=limits,
        parent_environment=options.get("parentEnvironment"), process_factory=processes)
