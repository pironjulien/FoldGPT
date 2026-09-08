"""Real Linux production channels plus actual ripgrep; requires native helpers."""
import asyncio
import hashlib
import importlib
import json
import os
from pathlib import Path
import unittest

from tools.executor.native_host_bootstrap_v2 import HostChannelFactoryV2
from tools.executor.native_runtime_acquisition import NativeRuntimeAcquisition, SessionExecServer
from tools.executor.native_runtime_startup import StartupManifest
from tools.executor.ordinary_uid_files import OrdinaryUidFilesBackend
from tools.executor.qualify_production_ripgrep import SOURCES, cases, qualify
from tools.executor import test_production_host_v2 as host_tests


class ProductionRipgrepTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = host_tests.ProductionHostV2Tests.asyncTearDown

    async def asyncSetUp(self):
        await host_tests.ProductionHostV2Tests.asyncSetUp(self)
        self.owner.close_endpoint()
        candidate = os.environ.get("FOLDGPT_TEST_RIPGREP")
        self.assertTrue(candidate, "FOLDGPT_TEST_RIPGREP must identify actual host ripgrep 15.2.0 with PCRE2/JIT")
        self.rg = Path(candidate).resolve(strict=True)
        self.assertTrue(self.rg.is_file())
        helpers = Path(os.environ["FOLDGPT_NATIVE_RUNNER"]).parent
        self.direct_runner = helpers / "direct-runner"
        self.assertTrue(self.direct_runner.is_file(), "Actual native direct owner required")
        direct = importlib.import_module("tools.executor.bionic-supervisor.direct_processes")
        self.direct = direct.DirectProcesses(str(self.direct_runner), self.workspace,
            executables={"bash": "/usr/bin/bash", "/usr/bin/bash": "/usr/bin/bash",
                "python3": str(self.python), "rg": str(self.rg)}, files_backend=self.backend.files,
            parent_environment={"PATH": str(self.rg.parent) + ":/usr/bin:/bin", "HOME": str(self.workspace)},
            quarantine_owner=self.backend.processes)
        self.ordinary_files = OrdinaryUidFilesBackend(lock=self.backend.files.lock)
        self.backend.install_ordinary_uid_profile(self.direct, self.ordinary_files)
        info = {key: value for key, value in self.server.info.items() if key != "capabilities"}
        info["platformOs"] = "linux"
        self.server = SessionExecServer(self.backend, environment_info=info)
        self.factory = HostChannelFactoryV2(str(helpers / "host-runner"), runtime=self.runtime,
            executables={"cat": "/usr/bin/cat", "sh": "/usr/bin/bash", "python": str(self.python)}, cwd_shim=None)
        self.owner = NativeRuntimeAcquisition(self.path, self.server, controller_uid=os.getuid(),
            host_channel_factory=self.factory)

    async def test_actual_rg_model_processes_files_streams_and_cleanup(self):
        manifest_path = self.endpoint_dir / "startup.json"
        manifest = StartupManifest(manifest_path, socket_path=self.path, workspace=self.workspace,
            shared_paths=[self.workspace], controller_roots=[Path("/usr").as_uri()],
            parent_environment={"PATH": str(self.rg.parent) + ":/usr/bin:/bin", "HOME": str(self.workspace)},
            directory_fd=self.owner.directory_fd, host_schema=self.factory.schema)
        self.running = asyncio.create_task(self.owner.run())
        try:
            result = await asyncio.wait_for(asyncio.to_thread(qualify, manifest_path,
                expected_platform="linux"), 120)
            artifact_root = os.environ.get("FOLDGPT_NATIVE_TEST_ARTIFACTS")
            if artifact_root:
                output = Path(artifact_root)
                output.mkdir(mode=0o700, parents=True, exist_ok=True)
                (output / "production-ripgrep.json").write_text(json.dumps({
                    "schema": "foldgpt.production-ripgrep-linux-evidence.v1", "androidExecution": False,
                    "rgSha256": hashlib.sha256(self.rg.read_bytes()).hexdigest(),
                    "directRunnerSha256": hashlib.sha256(self.direct_runner.read_bytes()).hexdigest(),
                    "qualification": result}, indent=2) + "\n", encoding="utf-8")
            self.assertTrue(result["passed"], result)
            self.assertEqual(len(result["modelCases"]), len(cases()) + 3)
            self.assertEqual(len(result["independentReads"]), len(SOURCES))
            self.assertEqual({case["sandboxField"] for case in result["modelCases"]}, {"absent", "null"})
            self.assertTrue(all(case["closed"] and case["passed"] for case in result["modelCases"]))
            self.assertEqual({case["result"]["exitCode"] for case in result["modelCases"]}, {0, 1, 2})
            for name, content in SOURCES.items():
                self.assertEqual((Path(result["directory"]) / name).read_bytes(), content)
            self.assertFalse(result["officialEditorQualified"])
            self.assertFalse(result["modelExplicitStdinEofQualified"])
            ended, = await asyncio.wait_for(asyncio.gather(self.running, return_exceptions=True), 15)
            self.assertTrue(ended is None or isinstance(ended, (EOFError, ConnectionError)), ended)
            self.assertFalse(self.path.exists())
            self.assertFalse(self.direct.quarantined)
            self.assertFalse(self.backend.processes.quarantined)
            self.assertTrue(self.ordinary_files.closed)
            self.assertFalse(self.direct.processes)
            self.assertFalse(self.direct.failed)
        finally:
            manifest.remove()
            manifest.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
