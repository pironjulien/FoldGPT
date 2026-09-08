"""Real Linux ordinary model profile through production acquisition and channels.

Uses the installed helper composition, credentialed Unix descriptor handoff,
actual Bash/Python workers, and independent config/human filesystem reads.
Android startup and the official editor are deliberately outside this test.
"""
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
from tools.executor.qualify_production_ordinary_uid import qualify
from tools.executor import test_production_host_v2 as host_tests


class ProductionOrdinaryUidTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = host_tests.ProductionHostV2Tests.asyncTearDown

    async def asyncSetUp(self):
        await host_tests.ProductionHostV2Tests.asyncSetUp(self)
        self.owner.close_endpoint()
        helpers = Path(os.environ["FOLDGPT_NATIVE_RUNNER"]).parent
        self.direct_runner = helpers / "direct-runner"
        self.assertTrue(self.direct_runner.is_file(), "Actual ordinary native owner required")
        direct = importlib.import_module("tools.executor.bionic-supervisor.direct_processes")
        self.direct = direct.DirectProcesses(str(self.direct_runner), self.workspace,
            executables={"bash": "/usr/bin/bash", "/usr/bin/bash": "/usr/bin/bash",
                "python3": str(self.python)}, files_backend=self.backend.files,
            parent_environment={"PATH": "/usr/bin:/bin", "HOME": str(self.workspace)},
            quarantine_owner=self.backend.processes)
        self.ordinary_files = OrdinaryUidFilesBackend(lock=self.backend.files.lock)
        self.backend.install_ordinary_uid_profile(self.direct, self.ordinary_files)
        info = {key: value for key, value in self.server.info.items() if key != "capabilities"}
        info["platformOs"] = "linux"
        self.server = SessionExecServer(self.backend, environment_info=info)
        self.factory = HostChannelFactoryV2(str(helpers / "host-runner"), runtime=self.runtime,
            executables={"cat": "/usr/bin/cat", "sh": "/usr/bin/bash", "python": str(self.python)},
            cwd_shim=None)
        self.owner = NativeRuntimeAcquisition(self.path, self.server, controller_uid=os.getuid(),
            host_channel_factory=self.factory)

    async def test_model_creates_tests_builds_and_independent_channels_read_same_project(self):
        manifest_path = self.endpoint_dir / "startup.json"
        manifest = StartupManifest(manifest_path, socket_path=self.path, workspace=self.workspace,
            shared_paths=[self.workspace], controller_roots=[Path("/usr").as_uri()],
            parent_environment={"PATH": "/usr/bin:/bin", "HOME": str(self.workspace)},
            directory_fd=self.owner.directory_fd, host_schema=self.factory.schema)
        self.running = asyncio.create_task(self.owner.run())
        try:
            result = await asyncio.wait_for(asyncio.to_thread(qualify, manifest_path,
                expected_platform="linux"), 120)
            artifact_root = os.environ.get("FOLDGPT_NATIVE_TEST_ARTIFACTS")
            if artifact_root:
                output = Path(artifact_root)
                output.mkdir(mode=0o700, parents=True, exist_ok=True)
                (output / "production-ordinary-uid.json").write_text(json.dumps({
                    "schema": "foldgpt.production-ordinary-uid-linux-evidence.v1",
                    "androidExecution": False, "officialEditorQualified": False,
                    "directRunnerSha256": hashlib.sha256(self.direct_runner.read_bytes()).hexdigest(),
                    "qualification": result}, indent=2) + "\n", encoding="utf-8")
            self.assertTrue(result["passed"], result)
            self.assertEqual(len(result["modelCases"]), 5)
            self.assertEqual(len(result["independentReads"]), 5)
            self.assertEqual({case["sandboxField"] for case in result["modelCases"]}, {"absent", "null"})
            self.assertTrue(all(case["start"]["sandboxType"] == "none" and case["closed"]
                and case["passed"] for case in result["modelCases"]))
            self.assertEqual({case["context"] for case in result["modelFileCases"]},
                {"absent", "null", "disabled"})
            self.assertTrue(all(case["configMatched"] and case["humanMatched"]
                for case in result["independentReads"]))
            self.assertFalse(result["officialEditorQualified"])
            self.assertTrue(result["javaCleanupReceiptRequired"])
            project = Path(result["directory"])
            self.assertTrue(project.is_relative_to(self.workspace))
            self.assertEqual((project / "app/addition.py").read_bytes(), b"def addition(a, b):\n    return a + b\n")
            self.assertTrue((project / "addition.pyz").read_bytes().startswith(b"PK"))
            ended, = await asyncio.wait_for(asyncio.gather(self.running, return_exceptions=True), 15)
            self.assertTrue(ended is None or isinstance(ended, (EOFError, ConnectionError)), ended)
            self.assertFalse(self.path.exists())
            self.assertFalse(self.direct.quarantined)
            self.assertFalse(self.backend.processes.quarantined)
            self.assertTrue(self.ordinary_files.closed)
            self.assertFalse(self.direct.processes)
            self.assertFalse(self.direct.failed)
            self.assertFalse(self.backend.files.lock.locked())
        finally:
            manifest.remove()
            manifest.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
