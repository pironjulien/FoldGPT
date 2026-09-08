"""Real Linux production acquisition + human v2 driver, no transport fixtures."""
import asyncio
import os
from pathlib import Path
import sys
import unittest

from tools.executor.native_host_bootstrap_v2 import HostChannelFactoryV2
from tools.executor.native_runtime_acquisition import NativeRuntimeAcquisition
from tools.executor.native_runtime_startup import StartupManifest
from tools.executor.qualify_production_host_v2 import qualify
from tools.executor import test_native_runtime_acquisition as acquisition_tests


class ProductionHostV2Tests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = acquisition_tests.RuntimeAcquisitionTests.asyncSetUp
    asyncTearDown = acquisition_tests.RuntimeAcquisitionTests.asyncTearDown

    async def test_real_production_channels_cat_shell_save_python_and_owned_cancel(self):
        self.owner.close_endpoint()
        runner = Path(os.environ["FOLDGPT_NATIVE_RUNNER"]).parent / "host-runner"
        python = Path(sys.executable).resolve(strict=True)
        runtime = [("/usr", True), ("/lib", True), ("/lib64", True), ("/etc/ld.so.cache", False)]
        if not python.is_relative_to("/usr"):
            runtime.append((str(Path(sys.prefix).resolve(strict=True)), True))
        factory = HostChannelFactoryV2(str(runner), runtime=runtime,
            executables={"cat": "/usr/bin/cat", "sh": "/usr/bin/bash", "python": str(python)}, cwd_shim=None)
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
