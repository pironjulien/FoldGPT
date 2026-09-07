"""Host-only policy handoff tests; no native enforcement or protocol server."""
from dataclasses import FrozenInstanceError
import copy
import hashlib
import json
import unittest

from tools.executor.policy_intent import PolicyIntent, prepare_policy_intent
from tools.policy.managed_policy import PolicyError, parse_context


def context():
    return {
        "permissions": {
            "type": "managed",
            "file_system": {"type": "restricted", "entries": [
                {"path": {"type": "special", "value": {"kind": "root"}}, "access": "read"},
                {"path": {"type": "path", "path": "file:///workspace"}, "access": "write"},
                {"path": {"type": "path", "path": "file:///workspace/private"}, "access": "deny"},
                {"path": {"type": "path", "path": "file:///workspace/.git/allowed"}, "access": "write"},
            ]},
            "network": "restricted",
        },
        "cwd": "file:///workspace", "workspaceRoots": ["file:///workspace"],
        "userHomeDir": "file:///home/julien", "temporaryDirectories": ["file:///tmp/private"],
        "windowsSandboxLevel": "disabled",
    }


def prepare(value, **overrides):
    identifiers = {"session_id": "session-a", "request_id": "request-a", "method": "process/start"}
    identifiers.update(overrides)
    return prepare_policy_intent(value, **identifiers)


class PolicyIntentTests(unittest.TestCase):
    def test_retains_complete_policy_and_order_without_lowering_to_roots(self):
        original = context()
        intent = prepare(original)
        actual = intent.to_document()["context"]
        self.assertEqual(actual, parse_context(original).to_context_dict())
        self.assertEqual(actual["permissions"]["file_system"]["entries"],
                         original["permissions"]["file_system"]["entries"])
        reparsed = parse_context(actual)
        self.assertFalse(reparsed.decide("/workspace/private/secret").can_read)
        self.assertFalse(reparsed.decide("/workspace/.git/config").can_write)
        self.assertTrue(reparsed.decide("/workspace/.git/allowed").can_write)

    def test_input_and_returned_documents_cannot_mutate_intent(self):
        original = context()
        intent = prepare(original)
        before = intent.to_bytes()
        original["permissions"]["file_system"]["entries"].clear()
        returned = intent.to_document()
        returned["context"]["permissions"]["file_system"]["entries"].clear()
        self.assertEqual(before, intent.to_bytes())
        with self.assertRaises(FrozenInstanceError):
            intent.method = "process/spawn"

    def test_inactive_windows_desktop_preference_survives_native_handoff(self):
        baseline = parse_context(context())
        for value in (False, True):
            with self.subTest(private_desktop=value):
                original = context()
                original["windowsSandboxPrivateDesktop"] = value
                intent = prepare(original)
                self.assertEqual(json.loads(intent.context_json)["windowsSandboxPrivateDesktop"], value)
                restored = parse_context(intent.context_json)
                self.assertEqual(restored.to_context_dict(), parse_context(original).to_context_dict())
                for path in ("/workspace/value", "/workspace/private/secret", "/workspace/.git/config"):
                    self.assertEqual(restored.decide(path), baseline.decide(path))
                original["windowsSandboxLevel"] = "restrictedToken"
                with self.assertRaises(PolicyError) as error:
                    prepare(original)
                self.assertEqual(error.exception.field, "$.windowsSandboxLevel")

    def test_inactive_windows_proxy_preferences_keep_native_policy_intact(self):
        baseline = parse_context(context())
        for mode in (None, "reconcile", "preserve"):
            with self.subTest(mode=mode):
                original = context()
                original["windowsSandboxPrivateDesktop"] = True
                original["windowsSandboxProxySettingsMode"] = mode
                intent = prepare(original)
                actual = json.loads(intent.context_json)
                self.assertEqual(actual.get("windowsSandboxProxySettingsMode"), mode)
                restored = parse_context(intent.context_json)
                for path in ("/workspace/value", "/workspace/private/secret", "/workspace/.git/config"):
                    self.assertEqual(restored.decide(path), baseline.decide(path))
                original["windowsSandboxLevel"] = "elevated"
                with self.assertRaises(PolicyError):
                    prepare(original)
        for invalid in (0, True, [], {}, "proxyOnly", "future-mode"):
            with self.subTest(invalid=invalid):
                original = context()
                original["windowsSandboxProxySettingsMode"] = invalid
                with self.assertRaises(PolicyError) as error:
                    prepare(original)
                self.assertEqual(error.exception.field, "$.windowsSandboxProxySettingsMode")

    def test_digest_and_utf8_round_trip(self):
        original = context()
        original["cwd"] = "file:///workspace/caf%C3%A9"
        intent = prepare(original)
        document = json.loads(intent.to_bytes())
        self.assertEqual(document["contextSha256"], hashlib.sha256(intent.context_json).hexdigest())
        self.assertEqual(parse_context(document["context"]).cwd.path, "/workspace/café")

    def test_changes_to_restrictions_or_root_order_change_digest(self):
        original = context()
        original_digest = prepare(original).context_sha256
        changed = copy.deepcopy(original)
        changed["permissions"]["file_system"]["entries"][2]["access"] = "read"
        self.assertNotEqual(original_digest, prepare(changed).context_sha256)
        changed = copy.deepcopy(original)
        changed["permissions"]["file_system"]["entries"].reverse()
        self.assertNotEqual(original_digest, prepare(changed).context_sha256)

    def test_unsupported_policy_fails_before_handoff(self):
        for key, value in (("network", "enabled"), ("type", "external"), ("unknown", True)):
            original = context()
            original["permissions"][key] = value
            with self.subTest(key=key), self.assertRaises(PolicyError):
                prepare(original)

    def test_duplicate_json_and_missing_sandbox_fail(self):
        with self.assertRaises(PolicyError):
            prepare('{"permissions":{},"permissions":{}}')
        with self.assertRaises(PolicyError):
            prepare(None)
        with self.assertRaises(PolicyError):
            PolicyIntent("session-a", "request-a", "process/start", b'{"permissions":{"type":"disabled"}}')

    def test_local_host_and_handle_lifecycle_are_not_policy_creation_methods(self):
        for method in ("command/exec", "process/spawn", "process/read", "fs/readBlock", "fs/close"):
            with self.subTest(method=method), self.assertRaises(PolicyError):
                prepare(context(), method=method)

    def test_session_and_request_identity_are_explicit(self):
        for field in ("session_id", "request_id"):
            for value in (None, "", "line\nbreak"):
                with self.subTest(field=field, value=value), self.assertRaises(PolicyError):
                    prepare(context(), **{field: value})
        intent = prepare(context(), session_id="session-b", request_id="request-b", method="fs/open")
        self.assertEqual(intent.to_document()["sessionId"], "session-b")
        self.assertEqual(intent.to_document()["requestId"], "request-b")
        self.assertEqual(intent.to_document()["method"], "fs/open")


if __name__ == "__main__":
    unittest.main()
