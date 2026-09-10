"""Protocol-semantic regressions for environment routing, never an executor proof."""
from copy import deepcopy
import unittest

from tools.executor.app_server_routing import EnvironmentRouter
from tools.executor.exec_server import RpcError


def request(identifier, method, **params):
    return {"id": identifier, "method": method, "params": params}


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.router = EnvironmentRouter("foldgpt", "/launcher")

    def learn(self, method="thread/resume", directory="/project", workspace_roots=None):
        message = request(1, method, threadId="t")
        sent = self.router.outgoing(message)
        response = {"id": 1, "result": {"thread": {"id": "t"}, "cwd": directory,
            "runtimeWorkspaceRoots": workspace_roots if workspace_roots is not None else [directory]}}
        self.assertIs(self.router.incoming(response), response)
        return message, sent

    def test_start_preserves_full_permission_and_input_fields(self):
        original = request(1, "thread/start", cwd="/p", runtimeWorkspaceRoots=["/p", "/extra"],
            sandbox="workspace-write", permissions=None, approvalPolicy="on-request",
            config={"permissions": {"deny": ["/private"]}}, developerInstructions="opaque")
        saved = deepcopy(original)
        routed = self.router.outgoing(original)
        selection = routed["params"].pop("environments")
        self.assertEqual(routed, original)
        self.assertEqual(original, saved)
        self.assertEqual(selection, [{"environmentId": "foldgpt", "cwd": "/p", "runtimeWorkspaceRoots": ["/p", "/extra"]}])

    def test_resume_uses_actual_cwd_only_after_official_success(self):
        original, sent = self.learn()
        self.assertEqual(sent, original)
        routed = self.router.outgoing(request(2, "turn/start", threadId="t", input=[]))
        self.assertEqual(routed["params"]["environments"][0]["cwd"], "/project")

    def test_pipelined_resume_does_not_guess_launcher_cwd(self):
        self.router.outgoing(request(1, "thread/resume", threadId="t"))
        with self.assertRaises(RpcError):
            self.router.outgoing(request(2, "turn/start", threadId="t", input=[]))

    def test_failed_resume_never_changes_location(self):
        self.router.outgoing(request(1, "thread/resume", threadId="t"))
        response = {"id": 1, "error": {"code": -1, "message": "opaque"}}
        self.assertIs(self.router.incoming(response), response)
        with self.assertRaises(RpcError):
            self.router.outgoing(request(2, "turn/start", threadId="t", input=[]))

    def test_cwd_override_retargets_root_preserving_extras_and_deduplication(self):
        self.learn(workspace_roots=["/project", "/extra", "/new"])
        result = self.router.outgoing(request(2, "turn/start", threadId="t", cwd="/new", input=[]))
        self.assertEqual(result["params"]["environments"][0]["runtimeWorkspaceRoots"], ["/new", "/extra"])
        self.router.incoming({"id": 2, "result": {"turn": {"id": "turn"}}})
        result = self.router.outgoing(request(3, "turn/start", threadId="t", input=[]))
        self.assertEqual(result["params"]["environments"][0]["runtimeWorkspaceRoots"], ["/new", "/extra"])

    def test_failed_turn_does_not_retarget_next_turn(self):
        self.learn()
        self.router.outgoing(request(2, "turn/start", threadId="t", cwd="/failed", input=[]))
        self.router.incoming({"id": 2, "error": {"code": -1, "message": "failed"}})
        result = self.router.outgoing(request(3, "turn/start", threadId="t", input=[]))
        self.assertEqual(result["params"]["environments"][0]["cwd"], "/project")

    def test_explicit_environment_owns_roots_over_legacy_fields(self):
        result = self.router.outgoing(request(1, "thread/start", cwd="/legacy", runtimeWorkspaceRoots=["/legacy"],
            environments=[{"environmentId": "local", "cwd": "/explicit", "runtimeWorkspaceRoots": []}]))
        self.assertEqual(result["params"]["environments"], [{"environmentId": "foldgpt", "cwd": "/explicit", "runtimeWorkspaceRoots": []}])
        self.assertEqual(result["params"]["runtimeWorkspaceRoots"], ["/legacy"])

    def test_empty_environment_access_remains_empty(self):
        result = self.router.outgoing(request(1, "turn/start", threadId="t", input=[], environments=[]))
        self.assertEqual(result["params"]["environments"], [])

    def test_successful_disabled_selection_stays_disabled_until_explicit_enable(self):
        self.learn()
        self.router.outgoing(request(2, "turn/start", threadId="t", input=[], environments=[]))
        self.router.incoming({"id": 2, "result": {"turn": {"id": "turn"}}})
        routed = self.router.outgoing(request(3, "turn/start", threadId="t", input=[]))
        self.assertEqual(routed["params"]["environments"], [])
        self.router.incoming({"id": 3, "result": {"turn": {"id": "next"}}})
        routed = self.router.outgoing(request(4, "turn/start", threadId="t", input=[],
            environments=[{"environmentId": "foldgpt", "cwd": "/project"}]))
        self.assertEqual(routed["params"]["environments"], [{"environmentId": "foldgpt", "cwd": "/project"}])
        self.router.incoming({"id": 4, "result": {"turn": {"id": "enabled"}}})
        self.assertTrue(self.router.locations["t"].enabled)

    def test_failed_disabled_selection_does_not_disable_prior_environment(self):
        self.learn()
        self.router.outgoing(request(2, "turn/start", threadId="t", input=[], environments=[]))
        self.router.incoming({"id": 2, "error": {"code": -1, "message": "failed"}})
        routed = self.router.outgoing(request(3, "turn/start", threadId="t", input=[]))
        self.assertEqual(routed["params"]["environments"][0]["cwd"], "/project")

    def test_disabled_start_uses_authoritative_response_paths(self):
        self.router.outgoing(request(1, "thread/start", environments=[]))
        self.router.incoming({"id": 1, "result": {"thread": {"id": "t"}, "cwd": "/actual", "runtimeWorkspaceRoots": ["/actual"]}})
        self.assertEqual(self.router.locations["t"].cwd, "/actual")
        self.assertFalse(self.router.locations["t"].enabled)
        self.learn()
        self.assertFalse(self.router.locations["t"].enabled)

    def test_environment_ids_match_exact_official_toml_grammar(self):
        for identifier in ("none", "NONE", "local", "has.dot", "a" * 65, "", "two words"):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                EnvironmentRouter(identifier, "/p")
        for identifier in ("_native", "-native", "a" * 64):
            self.assertEqual(EnvironmentRouter(identifier, "/p").environment_id, identifier)

    def test_other_environment_or_extension_is_not_silently_remapped(self):
        for selection in ([{"environmentId": "remote", "cwd": "/p"}],
                          [{"environmentId": "local", "cwd": "/p", "permissions": "unknown"}],
                          [{"environmentId": "local", "cwd": "/p"}, {"environmentId": "foldgpt", "cwd": "/p"}]):
            with self.assertRaises(RpcError):
                self.router.outgoing(request(1, "thread/start", environments=selection))

    def test_approval_response_and_host_operations_are_identical_objects(self):
        messages = [request(1, "command/exec", command=["bash"], sandboxPolicy={"type": "readOnly"}),
                    request(2, "process/spawn", argv=["bash"]), request(3, "fs/readFile", path="/p"),
                    {"id": "approval", "result": {"decision": "decline"}}]
        for message in messages:
            self.assertIs(self.router.outgoing(message), message)
            self.assertIs(self.router.incoming(message), message)

    def test_initialize_preserves_client_capabilities(self):
        value = request(1, "initialize", clientInfo={"name": "official"},
            capabilities={"experimentalApi": False, "optOutNotificationMethods": ["thread/status/changed"]})
        result = self.router.outgoing(value)
        self.assertTrue(result["params"]["capabilities"].pop("experimentalApi"))
        expected = deepcopy(value)
        del expected["params"]["capabilities"]["experimentalApi"]
        self.assertEqual(result, expected)

    def test_settings_notification_retains_extra_roots(self):
        self.learn(workspace_roots=["/project", "/extra"])
        self.router.incoming({"method": "thread/settings/updated", "params": {
            "threadId": "t", "threadSettings": {"cwd": "/new"}}})
        result = self.router.outgoing(request(2, "turn/start", threadId="t", input=[]))
        self.assertEqual(result["params"]["environments"][0]["runtimeWorkspaceRoots"], ["/new", "/extra"])


if __name__ == "__main__":
    unittest.main()
