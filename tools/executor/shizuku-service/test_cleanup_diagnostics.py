"""PC tests for real cleanup orchestration and bounded diagnostic encoding.

Faulting resource fixtures exercise reporting and ordering only. They neither
execute commands nor claim that an Android sandbox has been qualified.
"""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest

ASSETS = Path(__file__).resolve().parent / "transport/src/main/assets/foldgpt-executor"
sys.path.insert(0, str(ASSETS))
from foldgpt_native_bootstrap import cleanup_resources
from foldgpt_shizuku_bootstrap import CLEANUP_STAGES, report_cleanup_failure


class CleanupResourceTests(unittest.IsolatedAsyncioTestCase):
    async def outcome(self, fail=None, session=None):
        observed = []
        error = OSError(16, "Fixed resource remains busy")

        def action(stage):
            observed.append(stage)
            if fail == stage:
                raise error

        async def close(actual_session):
            self.assertEqual(session, actual_session)
            action("backend_close")

        backend = SimpleNamespace(close=close, processes=SimpleNamespace(quarantined=fail == "process_cleanup"))
        acquisition = SimpleNamespace(close_endpoint=lambda: action("acquisition_close"))
        manifest = SimpleNamespace(remove=lambda: action("manifest_remove"), close=lambda: action("manifest_close"))
        owner = SimpleNamespace(process_identity=object(), finish_process_session=lambda: action("session_finish"),
                                close=lambda: action("owner_close"))
        result = await cleanup_resources(backend, SimpleNamespace(session_id=session), acquisition, manifest, owner, True)
        return result, observed, error

    async def test_close_before_connection_passes_none_and_preserves_first_error(self):
        (clean, diagnostic), observed, error = await self.outcome("backend_close", session=None)
        self.assertFalse(clean)
        self.assertEqual(["backend_close"], observed)
        self.assertEqual("backend_close", diagnostic[0])
        self.assertIs(error, diagnostic[1])

    async def test_each_partial_cleanup_failure_stops_before_later_releases(self):
        order = ["backend_close", "acquisition_close", "manifest_remove", "manifest_close", "session_finish", "owner_close"]
        for stage in order:
            with self.subTest(stage=stage):
                (clean, diagnostic), observed, error = await self.outcome(stage, session="initialized-session")
                self.assertFalse(clean)
                self.assertEqual(stage, diagnostic[0])
                self.assertIs(error, diagnostic[1])
                self.assertEqual(order[:order.index(stage) + 1], observed)

    async def test_retained_processes_block_endpoint_manifest_and_owner_release(self):
        (clean, diagnostic), observed, _ = await self.outcome("process_cleanup")
        self.assertFalse(clean)
        self.assertEqual("process_cleanup", diagnostic[0])
        self.assertIsInstance(diagnostic[1], RuntimeError)
        self.assertEqual(["backend_close"], observed)

    async def test_success_requires_all_resource_closes_without_diagnostic(self):
        result, observed, _ = await self.outcome(session="initialized-session")
        self.assertEqual((True, None), result)
        self.assertEqual(["backend_close", "acquisition_close", "manifest_remove", "manifest_close", "session_finish", "owner_close"], observed)

    async def test_unreturned_factory_remains_unresolved_without_invented_cause(self):
        self.assertEqual((False, None), await cleanup_resources(None, None, None, None, None, True))
        self.assertEqual((True, None), await cleanup_resources(None, None, None, None, None, False))


class CleanupEncoderTests(unittest.TestCase):
    def test_actual_encoder_emits_one_bounded_private_ascii_frame_for_each_stage(self):
        program = (
            "import sys;sys.path.insert(0,sys.argv[1]);"
            "from foldgpt_shizuku_bootstrap import report_cleanup_failure;"
            "error=type('E'*64,(Exception,),{})(('x\\n\\\"\\\\é'*200));"
            "report_cleanup_failure(sys.argv[2],error)"
        )
        for stage in sorted(CLEANUP_STAGES):
            with self.subTest(stage=stage):
                result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", program, str(ASSETS), stage],
                                        capture_output=True, check=True, timeout=5)
                self.assertEqual(b"", result.stdout)
                self.assertEqual(1, result.stderr.count(b"\n"))
                self.assertLessEqual(len(result.stderr), 512)
                diagnostic = json.loads(result.stderr)
                self.assertEqual({"schema", "event", "stage", "errorType", "errno", "source", "line", "message"}, set(diagnostic))
                self.assertEqual("cleanup_failed", diagnostic["event"])
                self.assertEqual(stage, diagnostic["stage"])
                self.assertEqual(64, len(diagnostic["errorType"]))
                self.assertEqual(160, len(diagnostic["message"]))
                self.assertIsNone(diagnostic["errno"])
                self.assertTrue(all(32 <= ord(char) <= 126 and char not in '\\"' for char in diagnostic["message"]))

    def test_unknown_cleanup_stage_cannot_be_reported(self):
        with self.assertRaisesRegex(ValueError, "Unknown bootstrap cleanup stage"):
            report_cleanup_failure("factory_construct", RuntimeError("fixed"))


if __name__ == "__main__":
    unittest.main()
