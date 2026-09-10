"""Run the real metadata regression against an explicitly selected old runner.

The ordinary build already runs the same test against the new runner. This
negative control succeeds only when the old worker fails at stat(self/exe),
and both its native process and its supervisor still terminate cleanly.
"""
import asyncio
import base64
import importlib
import io
import json
from pathlib import Path
import sys
import unittest

build, baseline = map(lambda value: Path(value).resolve(strict=True), sys.argv[1:3])
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.argv = [sys.argv[0], str(build)]
tests = importlib.import_module("tools.executor.bionic-supervisor.test_factory")
observation = {}


class Baseline(tests.FactoryTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.options["processRunner"] = str(baseline)

    async def asyncTearDown(self):
        record = self.backend.processes.processes.get(("test", "metadata"))
        if record is not None:
            await asyncio.wait_for(asyncio.shield(record.finished), 12)
            observation.update(nativeResult=record.native_result,
                supervisorReturncode=record.process.returncode, closed=record.closed,
                stdout=b"".join(base64.b64decode(row["chunk"]) for row, _ in record.output
                                 if row["stream"] == "stdout").decode(),
                stderr=b"".join(base64.b64decode(row["chunk"]) for row, _ in record.output
                                 if row["stream"] == "stderr").decode())
        await super().asyncTearDown()


output = io.StringIO()
result = unittest.TextTestRunner(stream=output, verbosity=2).run(unittest.TestSuite([
    Baseline("test_20_current_executable_metadata_is_real_and_proc_stays_denied")]))
source = (build / "package/tools/executor/bionic-supervisor/test_executable_metadata_worker.c").read_text()
line = next(index for index, text in enumerate(source.splitlines(), 1)
            if "NEED(stat(alias,&follow)==0" in text)
caller = next(index for index, text in enumerate(source.splitlines(), 1)
              if "NEED(checks(1)==0)" in text)
expected = f"metadata regression line {line} errno 13\nmetadata regression line {caller} errno 13\n"
native = observation.get("nativeResult") or {}
passed = (result.testsRun == 1 and len(result.failures) == 1 and not result.errors
    and observation.get("stdout") == "" and observation.get("stderr") == expected
    and observation.get("supervisorReturncode") == 0 and observation.get("closed") is True
    and native.get("cleanupComplete") is True and native.get("exitCode") == 1
    and native.get("outcome") == "exited")
report = {"schema": "foldgpt.executable-metadata-negative-control.v1", "success": passed,
    "baselineRunner": str(baseline), "workerBuild": str(build), "observation": observation,
    "unittestOutput": output.getvalue(),
    "failure": result.failures[0][1] if len(result.failures) == 1 else None}
(build / "executable-metadata-baseline.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
if not passed:
    raise SystemExit(1)
