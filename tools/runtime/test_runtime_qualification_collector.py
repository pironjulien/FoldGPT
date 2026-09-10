"""PC-only, explicitly synthetic protocol fixtures; never Android evidence.

These tests exercise collector validation without ADB, a subprocess, a device,
or material collection. Binary bytes below are deliberate test vectors, not a
worker report and not evidence that the Android workload has run successfully.
"""
import base64
import copy
import importlib.util
from pathlib import Path
import unittest


def load_collector():
    path = Path(__file__).with_name("collect-runtime-qualification.py")
    spec = importlib.util.spec_from_file_location("runtime_collector_synthetic_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = load_collector()
contract = collector.load_contract()


def b64(value):
    return base64.b64encode(value).decode("ascii")


def response(app, response_id):
    return next(frame for frame in app["frames"] if frame.get("id") == response_id)


def synthetic_fixture(profile=collector.V1):
    """Return internally coherent, invented RPC/ownership data for unit tests."""
    native_directory = "/data/app/synthetic-test-package/lib/arm64"
    plan = collector.requests(contract, profile)
    plan["start"]["params"]["env"]["FOLDGPT_PYTHON_REAL"] = (
        native_directory + "/libfoldgpt_python_cli.so")
    stdout_parts = (b"\x00\xffAB", b"C\n")
    stderr = b"\xfe\x00synthetic binary stderr\n"
    chunks = [
        {"seq": 1, "stream": "stdout", "chunk": b64(stdout_parts[0])},
        {"seq": 2, "stream": "stderr", "chunk": b64(stderr)},
        {"seq": 3, "stream": "stdout", "chunk": b64(stdout_parts[1])},
    ]
    read = {"exited": True, "closed": True, "exitCode": 0,
            "failure": None, "sandboxDenied": False, "nextSeq": 6,
            "chunks": copy.deepcopy(chunks)}
    streams = {"stdout": b"".join(stdout_parts), "stderr": stderr}
    written = {"status": "accepted"}
    material = {"dataBase64": b64(streams["stdout"])}
    frames = [
        {"id": 1, "result": {"sessionId": "synthetic-session-only", "environmentInfo": {}}},
        {"id": 2, "result": {"processId": contract.PROCESS_ID, "sandboxType": "linuxSeccomp"}},
        {"id": 3, "result": copy.deepcopy(written)},
        *({"method": "process/output", "params": {"processId": contract.PROCESS_ID, **chunk}}
          for chunk in chunks),
        {"method": "process/exited", "params": {"processId": contract.PROCESS_ID,
            "seq": 4, "exitCode": 0, "sandboxDenied": False}},
        {"method": "process/closed", "params": {"processId": contract.PROCESS_ID, "seq": 5}},
        {"id": 4, "result": copy.deepcopy(read)},
        {"id": 5, "result": copy.deepcopy(material)},
    ]
    app = {"syntheticFixture": True, "schema": "foldgpt.android-runtime-rpc.v1",
        "packageName": profile.package, "nativeBase": profile.base,
        "diagnosticVersion": profile.version,
        "requestedAction": profile.package + profile.identity.run_action,
        "nativeLibraryDir": native_directory,
        "requests": [
            {"id": 1, "method": "initialize", "params": {"clientName": "foldgpt-fixed-runtime-qualification"}},
            {"method": "initialized"},
            *(plan[name] for name in ("start", "write", "read", "file"))],
        "read": read, "stdinWrite": written, "materialRead": material,
        "frames": frames, "transportCleanupComplete": True,
        "transport": {"schema": "foldgpt.shizuku.transport.v1", "bootstrapReaped": True,
            "cleanupComplete": True, "ownerRetained": False, "quarantined": False,
            "transportFailed": False, "refusedBeforeFork": False, "waitStatus": 0}}
    native = {"syntheticFixture": True,
        "schema": "foldgpt.bionic-runtime-qualification.private.v1",
        "workspace": profile.base + "/workspace",
        "nativeResult": {"cleanupComplete": True}, "quarantined": False,
        "supervisorWaited": True, "processClosed": True,
        "supervisorReturncode": 0, "bootstrapPid": 901, "supervisorPid": 902}
    return app, native, streams


def synchronize_read_after_event_reorder(app):
    """Keep sequence/read bytes coherent so only chronology is under test."""
    events = [frame for frame in app["frames"] if "id" not in frame]
    for sequence, event in enumerate(events, 1):
        event["params"]["seq"] = sequence
    app["read"]["chunks"] = [
        {key: value for key, value in event["params"].items() if key != "processId"}
        for event in events if event["method"] == "process/output"]
    app["read"]["nextSeq"] = len(events) + 1
    response(app, 4)["result"] = copy.deepcopy(app["read"])


class RuntimeRpcCollectorTests(unittest.TestCase):
    def setUp(self):
        self.app, self.native, self.streams = synthetic_fixture()

    def assert_rejected(self):
        with self.assertRaises(ValueError):
            collector.verify_rpc(self.app, self.streams, contract)

    def test_v2_requires_its_own_actual_request_sequence(self):
        second = collector.get_profile(2)
        app, native, streams = synthetic_fixture(second)
        self.assertIsNone(collector.verify_rpc(app, streams, contract, second))
        self.assertTrue(collector.identities(app, native, second))
        self.assertFalse(collector.identities(app, native))
        with self.assertRaises(ValueError): collector.verify_rpc(app, streams, contract)
        with self.assertRaises(ValueError): collector.verify_rpc(self.app, self.streams, contract, second)

    def test_synthetic_binary_sequence_is_internally_coherent(self):
        self.assertTrue(self.app["syntheticFixture"])
        self.assertEqual([request["method"] for request in self.app["requests"]],
            ["initialize", "initialized", "process/start", "process/write", "process/read", "fs/readFile"])
        self.assertEqual(base64.b64decode(self.app["requests"][3]["params"]["chunk"]), b"native input\n")
        self.assertIn(b"\x00\xff", self.streams["stdout"])
        self.assertIn(b"\xfe\x00", self.streams["stderr"])
        self.assertIsNone(collector.verify_rpc(self.app, self.streams, contract))

    def test_modified_stdin_bytes_are_rejected(self):
        self.app["requests"][3]["params"]["chunk"] = b64(b"native input!")
        self.assert_rejected()

    def test_duplicate_reply_is_rejected(self):
        self.app["frames"].insert(3, copy.deepcopy(response(self.app, 3)))
        self.assert_rejected()

    def test_final_pipe_drain_after_exit_is_accepted_before_closed(self):
        frames = self.app["frames"]
        frames[5], frames[6] = frames[6], frames[5]
        synchronize_read_after_event_reorder(self.app)
        self.assertIsNone(collector.verify_rpc(self.app, self.streams, contract))

    def test_output_after_closed_is_rejected_even_when_read_and_sequences_agree(self):
        frames = self.app["frames"]
        final_output = frames.pop(5)
        frames.insert(7, final_output)
        synchronize_read_after_event_reorder(self.app)
        self.assert_rejected()

    def test_closed_before_exit_is_rejected_even_when_sequences_agree(self):
        frames = self.app["frames"]
        frames[6], frames[7] = frames[7], frames[6]
        synchronize_read_after_event_reorder(self.app)
        self.assert_rejected()

    def test_read_reply_before_closed_is_rejected(self):
        frames = self.app["frames"]
        frames[7], frames[8] = frames[8], frames[7]
        self.assert_rejected()

    def test_replies_in_wrong_request_order_are_rejected(self):
        frames = self.app["frames"]
        frames[1], frames[2] = frames[2], frames[1]
        self.assert_rejected()

    def test_material_bytes_must_match_stdout_even_if_both_material_records_agree(self):
        self.app["materialRead"]["dataBase64"] = b64(b"other synthetic result\n")
        response(self.app, 5)["result"] = copy.deepcopy(self.app["materialRead"])
        self.assert_rejected()

    def test_material_reply_must_match_material_record(self):
        response(self.app, 5)["result"]["dataBase64"] = b64(b"other bytes")
        self.assert_rejected()

    def test_reported_streams_must_match_notifications(self):
        self.streams["stderr"] += b"changed"
        self.assert_rejected()

    def test_invalid_base64_is_rejected(self):
        self.app["frames"][3]["params"]["chunk"] = "@@@"
        synchronize_read_after_event_reorder(self.app)
        self.assert_rejected()

    def test_boolean_and_integer_coercions_are_rejected(self):
        mutations = {
            "request_boolean_as_integer": lambda app: app["requests"][2]["params"].update(pipeStdin=1),
            "reply_id_as_boolean": lambda app: app["frames"][0].update(id=True),
            "session_id_as_boolean": lambda app: app["frames"][0]["result"].update(sessionId=True),
            "sequence_as_boolean": lambda app: app["frames"][3]["params"].update(seq=True),
            "exit_status_as_boolean": lambda app: app["frames"][6]["params"].update(exitCode=False),
            "read_exit_as_boolean": lambda app: app["read"].update(exitCode=False),
            "read_closed_as_integer": lambda app: app["read"].update(closed=1),
            "read_sequence_as_float": lambda app: app["read"].update(nextSeq=6.0),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.app, self.native, self.streams = synthetic_fixture()
                mutate(self.app)
                self.assert_rejected()


class RuntimeOwnershipCollectorTests(unittest.TestCase):
    def test_v2_clean_ownership_cannot_be_relabelled_as_v1(self):
        second = collector.get_profile(2)
        app, native, _ = synthetic_fixture(second)
        self.assertTrue(collector.transport_clean(app, native, second))
        self.assertFalse(collector.transport_clean(app, native))
        app['nativeBase'] = collector.BASE
        self.assertFalse(collector.transport_clean(app, native, second))

    def test_synthetic_clean_ownership_is_internally_coherent(self):
        app, native, _ = synthetic_fixture()
        self.assertTrue(collector.transport_clean(app, native))

    def test_same_bootstrap_and_supervisor_pid_cannot_authorize_material_collection(self):
        app, native, _ = synthetic_fixture()
        native["supervisorPid"] = native["bootstrapPid"]
        self.assertFalse(collector.transport_clean(app, native))

    def test_boolean_integer_coercions_cannot_authorize_material_collection(self):
        mutations = {
            "diagnostic_version": lambda app, native: app.update(diagnosticVersion=True),
            "transport_wait_status": lambda app, native: app["transport"].update(waitStatus=False),
            "supervisor_returncode": lambda app, native: native.update(supervisorReturncode=False),
            "bootstrap_pid": lambda app, native: native.update(bootstrapPid=True),
            "supervisor_pid": lambda app, native: native.update(supervisorPid=True),
            "supervisor_wait": lambda app, native: native.update(supervisorWaited=1),
            "transport_cleanup": lambda app, native: app.update(transportCleanupComplete=1),
            "native_cleanup": lambda app, native: native["nativeResult"].update(cleanupComplete=1),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                app, native, _ = synthetic_fixture()
                mutate(app, native)
                self.assertFalse(collector.transport_clean(app, native))

    def test_missing_or_incomplete_ownership_never_authorizes_material_collection(self):
        for name in ("supervisorWaited", "processClosed", "supervisorReturncode", "bootstrapPid", "supervisorPid"):
            with self.subTest(missing=name):
                app, native, _ = synthetic_fixture()
                del native[name]
                self.assertFalse(collector.transport_clean(app, native))
        app, native, _ = synthetic_fixture()
        app["transport"]["ownerRetained"] = True
        self.assertFalse(collector.transport_clean(app, native))


if __name__ == "__main__":
    unittest.main(verbosity=2)
