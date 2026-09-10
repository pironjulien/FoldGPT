"""Real envPolicy RPC launches through the existing native env-printing fixture."""
import argparse
import json
import os
from pathlib import Path
import sys
import unittest

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.executor import test_native_processes_live as lifecycle
from tools.executor.exec_server import RpcError
from tools.executor.native_environment import NON_INHERITABLE, EOF_CONTROL
from tools.executor.native_processes import NativeProcessLimits, NativeProcessesBackend
from tools.executor.test_native_environment import policy


class NativeEnvironmentLiveTests(lifecycle.NativeProcessTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.parent_input = {"PATH": "/declared/native/bin", "HOME": "/declared/private/home",
            "EXTRA": "parent", "API_KEY": "synthetic-parent-secret", "FILTERED": "parent",
            **{name: "synthetic-non-inheritable" for name in NON_INHERITABLE}, EOF_CONTROL: "1"}
        self.backend = NativeProcessesBackend(lifecycle.RUNNER, self.root,
            executables={"native-fixture": lifecycle.FIXTURE},
            limits=NativeProcessLimits(wall_ms=3000, address_space_bytes=lifecycle.ADDRESS_SPACE),
            parent_environment=self.parent_input)

    async def environment_result(self, identifier, selected, explicit=None):
        await self.start(identifier, ("env",), envPolicy=selected, env=explicit or {}, arg0="native-env-proof")
        response = await self.completed(identifier)
        self.assertEqual(response["exitCode"], 0)
        self.assertIsNone(response["failure"])
        values = dict(line.split("=", 1) for line in self.output(response).decode("utf-8").splitlines())
        self.assertEqual(values.pop("ARG0"), "native-env-proof")
        return values

    async def test_env_inheritance_and_snapshot_survive_real_execve(self):
        self.parent_input["HOME"] = "mutation-must-not-propagate"
        for strategy, expected in (("none", {}),
                ("core", {"PATH": "/declared/native/bin", "HOME": "/declared/private/home"}),
                ("all", {"PATH": "/declared/native/bin", "HOME": "/declared/private/home",
                    "EXTRA": "parent", "FILTERED": "parent"})):
            self.assertEqual(await self.environment_result(strategy,
                policy(inherit=strategy, ignoreDefaultExcludes=False)), expected)

    async def test_env_filter_order_and_identity_scrub_survive_real_execve(self):
        blocked = {name.lower(): "synthetic-explicit" for name in NON_INHERITABLE}
        blocked[EOF_CONTROL] = "1"
        selected = policy(ignoreDefaultExcludes=False, exclude=["filtered"],
            set={**blocked, "FILTERED": "restored", "API_KEY": "explicitly-restored", "EXTRA": "set"},
            includeOnly=["filter*", "api_key", "extra", "*token*", "openai*", EOF_CONTROL])
        self.assertEqual(await self.environment_result("ordered", selected,
            {**blocked, "EXTRA": "rpc-wins", "UNICODE": "é=😀"}),
            {"FILTERED": "restored", "API_KEY": "explicitly-restored", "EXTRA": "rpc-wins", "UNICODE": "é=😀"})

    async def test_env_malformed_wire_is_refused_before_real_launch(self):
        for selected in ({"inherit": "none"}, policy(ignoreDefaultExcludes=1), policy(exclude="*"),
                policy(inherit="unsupported"), policy(unknown=True)):
            with self.assertRaises(RpcError):
                await self.start(args=("env",), envPolicy=selected)
        self.assertFalse(self.backend.processes)
        self.assertFalse(self.notifications)


def load_tests(loader, tests, pattern):
    # Inherit lifecycle helpers, without re-registering their separate full suite.
    return unittest.TestSuite(NativeEnvironmentLiveTests(name)
        for name in loader.getTestCaseNames(NativeEnvironmentLiveTests) if name.startswith("test_env_"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    lifecycle.RUNNER, lifecycle.FIXTURE, lifecycle.PARENT = args.runner, args.fixture, args.parent
    program = unittest.main(argv=[sys.argv[0]], exit=False, verbosity=2)
    if args.evidence:
        args.evidence.write_text(json.dumps({"schema": "foldgpt.native-environment.v1", "uid": os.getuid(),
            "successful": program.result.wasSuccessful(), "observations": lifecycle.OBSERVATIONS}, indent=2) + "\n")
    sys.exit(0 if program.result.wasSuccessful() else 1)
