"""Real Linux production acquisition + human v2 driver, no transport fixtures."""
import asyncio
import importlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

from tools.executor.native_executor_backend import NativeExecutorBackend
from tools.executor.native_host_bootstrap_v2 import HostChannelFactoryV2
from tools.executor.native_runtime_acquisition import NativeRuntimeAcquisition, SessionExecServer
from tools.executor.native_runtime_startup import StartupManifest
from tools.executor.qualify_production_host_v2 import qualify
from tools.executor import test_native_runtime_acquisition as acquisition_tests


class ProductionHostV2Tests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = acquisition_tests.RuntimeAcquisitionTests.asyncTearDown

    async def asyncSetUp(self):
        self.assertNotEqual(os.getuid(), 0)
        inputs = [os.environ.get(name) for name in (
            "FOLDGPT_NATIVE_FILES", "FOLDGPT_NATIVE_HANDLES", "FOLDGPT_NATIVE_RUNNER")]
        self.assertTrue(all(inputs), "Actual native helpers required")
        self.temp = tempfile.TemporaryDirectory(prefix="foldgpt-production-", dir="/var/tmp")
        self.parent = Path(self.temp.name)
        self.workspace = self.parent / "workspace"
        self.workspace.mkdir(mode=0o700)
        self.endpoint_dir = self.parent / "endpoint"
        self.endpoint_dir.mkdir(mode=0o700)
        self.python = Path(sys.executable).resolve(strict=True)
        self.runtime = [("/usr", True), ("/lib", True), ("/lib64", True), ("/etc/ld.so.cache", False)]
        if not self.python.is_relative_to("/usr"):
            self.runtime.append((str(Path(sys.prefix).resolve(strict=True)), True))
        bionic = importlib.import_module("tools.executor.bionic-supervisor.processes")
        def processes(runner, workspace, **options):
            return bionic.Processes(runner, workspace, runtime=self.runtime,
                executables={"bash": "/usr/bin/bash", "python3": str(self.python)}, **options)
        self.backend = NativeExecutorBackend(inputs[0], self.workspace, handle_helper=inputs[1],
            process_runner=inputs[2], process_factory=processes, guest_workspace=str(self.workspace),
            parent_environment={"PATH": "/usr/bin:/bin", "HOME": str(self.workspace)})
        info = {"os": "linux", "arch": "x86_64", "cwd": self.workspace.as_uri(),
                "userHomeDir": self.workspace.as_uri(), "shell": {"name": "bash", "path": "/usr/bin/bash"}}
        self.server = SessionExecServer(self.backend, environment_info=info)
        self.path = self.endpoint_dir / "runtime.sock"
        self.owner = NativeRuntimeAcquisition(self.path, self.server, controller_uid=os.getuid())
        self.running = None

    async def test_real_production_channels_cat_shell_save_python_and_owned_cancel(self):
        self.owner.close_endpoint()
        runner = Path(os.environ["FOLDGPT_NATIVE_RUNNER"]).parent / "host-runner"
        factory = HostChannelFactoryV2(str(runner), runtime=self.runtime,
            executables={"cat": "/usr/bin/cat", "sh": "/usr/bin/bash", "python": str(self.python)}, cwd_shim=None)
        self.owner = NativeRuntimeAcquisition(self.path, self.server, controller_uid=os.getuid(),
            host_channel_factory=factory)
        manifest_path = self.endpoint_dir / "startup.json"
        manifest = StartupManifest(manifest_path, socket_path=self.path, workspace=self.workspace,
            shared_paths=[self.workspace], controller_roots=[Path("/usr").as_uri()],
            parent_environment={"PATH": "/usr/bin:/bin", "HOME": str(self.workspace)},
            directory_fd=self.owner.directory_fd, host_schema=factory.schema)
        self.running = asyncio.create_task(self.owner.run())
        try:
            result = await asyncio.wait_for(asyncio.to_thread(qualify, manifest_path), 120)
            self.assertTrue(result["passed"], result)
            self.assertEqual(len(result["cases"]), 6)
            self.assertEqual(len(result["modelCases"]), 4)
            self.assertFalse(result["officialEditorQualified"])
            self.assertEqual((Path(result["directory"]) / "streamed.bin").read_bytes(), bytes(range(256)) * 8193)
            ended, = await asyncio.wait_for(asyncio.gather(self.running, return_exceptions=True), 15)
            self.assertTrue(ended is None or isinstance(ended, (EOFError, ConnectionError)), ended)
            self.assertFalse(self.backend.processes.quarantined)
        finally:
            manifest.remove()
            manifest.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
