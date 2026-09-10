"""Portable RPC environment semantics, independent of host environment/secrets."""
import unittest

from tools.executor.exec_server import RpcError
from tools.executor.native_environment import (
    EOF_CONTROL, NON_INHERITABLE, matches_pattern, process_environment, snapshot_environment,
)


def policy(**changes):
    return {"inherit": "all", "ignoreDefaultExcludes": True,
        "exclude": [], "set": {}, "includeOnly": [], **changes}


def decoded(params, parent=None):
    encoded = process_environment(params, snapshot_environment(parent))
    return dict(part.decode("utf-8").split("=", 1) for part in encoded.split(b"\0") if part)


class NativeEnvironmentTests(unittest.TestCase):
    def test_absent_or_null_policy_is_exact_explicit_environment(self):
        for extra in ({}, {"envPolicy": None}):
            self.assertEqual(decoded({"env": {"EXACT": "é=ok"}, **extra}, {"PARENT": "absent"}),
                {"EXACT": "é=ok"})

    def test_config_defaults_arrive_as_complete_wire_fields(self):
        self.assertEqual(decoded({"env": {}, "envPolicy": policy()}, {"SECRET": "retained-by-policy"}),
            {"SECRET": "retained-by-policy"})
        with self.assertRaises(RpcError):
            decoded({"env": {}, "envPolicy": {}})

    def test_none_core_all_use_only_the_explicit_snapshot(self):
        parent = {"path": "/native/bin", "home": "/private/home", "TmpDir": "/private/tmp",
            "LANG": "C.UTF-8", "LC_MESSAGES": "outside-core", "EXTRA": "all-only"}
        for inherit, expected in (("none", {}), ("all", parent),
                ("core", {key: parent[key] for key in ("path", "home", "TmpDir", "LANG")})):
            with self.subTest(inherit=inherit):
                self.assertEqual(decoded({"env": {}, "envPolicy": policy(inherit=inherit)}, parent), expected)
        self.assertEqual(decoded({"env": {}, "envPolicy": policy(inherit="none")}), {})
        for inherit in ("core", "all"):
            with self.assertRaises(RpcError):
                decoded({"env": {}, "envPolicy": policy(inherit=inherit)})
        self.assertEqual(decoded({"env": {}, "envPolicy": policy()}, {}), {})

    def test_snapshot_is_immutable_and_detached_from_constructor_input(self):
        parent = {"EXACT": "frozen"}
        snapshot = snapshot_environment(parent)
        parent["EXACT"] = "changed"
        with self.assertRaises(TypeError):
            snapshot["EXACT"] = "changed"
        self.assertEqual(process_environment({"env": {}, "envPolicy": policy()}, snapshot), b"EXACT=frozen\0")

    def test_filter_set_include_and_explicit_override_order(self):
        inherited = {"API_KEY": "inherited", "KEEP": "parent", "DROP": "parent", "OTHER": "parent"}
        effective = policy(ignoreDefaultExcludes=False, exclude=["drop"],
            set={"API_KEY": "set-is-later", "DROP": "restored", "KEEP": "set", "SET_ONLY": "filtered"},
            includeOnly=["api_key", "drop", "keep"])
        self.assertEqual(decoded({"envPolicy": effective, "env": {"KEEP": "explicit", "EXTRA": "explicit"}}, inherited),
            {"API_KEY": "set-is-later", "DROP": "restored", "KEEP": "explicit", "EXTRA": "explicit"})

    def test_default_secret_filters_and_custom_excludes_are_case_insensitive(self):
        parent = {"myKey": "secret", "api_secret": "secret", "AuthToken": "secret",
            "FILTERED": "custom", "OK": "visible"}
        self.assertEqual(decoded({"env": {}, "envPolicy": policy(ignoreDefaultExcludes=False,
            exclude=["fil?er*"])}, parent), {"OK": "visible"})

    def test_unix_names_remain_case_sensitive_when_setting_values(self):
        self.assertEqual(decoded({"env": {"Path": "explicit"}, "envPolicy": policy(set={"path": "set"})},
            {"PATH": "parent"}), {"PATH": "parent", "path": "set", "Path": "explicit"})

    def test_non_inheritable_variables_cannot_return_from_any_input(self):
        blocked = {name.lower(): "test-value" for name in NON_INHERITABLE}
        blocked[EOF_CONTROL] = "1"
        self.assertEqual(decoded({"env": {**blocked, "OK": "explicit"},
            "envPolicy": policy(set=blocked)}, blocked), {"OK": "explicit"})
        # The upstream EOF control scrub is exact; the five identity names use ASCII case folding.
        self.assertEqual(decoded({"env": {EOF_CONTROL.lower(): "ordinary"}}),
            {EOF_CONTROL.lower(): "ordinary"})

    def test_wildmatch_literals_unicode_and_full_name_matching(self):
        cases = [("*", "", True), ("", "", True), ("?", "", False),
            ("a**b?", "A-middle-Bé", True), ("KEY", "API_KEY", False),
            ("[A-Z]", "K", False), ("[A-Z]", "[a-z]", True),
            (r"A\*", "A\\suffix", True), (r"A\*", "Asuffix", False),
            ("É?", "é😀", True), ("ß", "SS", False), ("Σ", "ς", False),
            ("ΟΣ", "οσ", True), ("ΟΣ", "ος", False),
            ("İ", "i\u0307", False), ("İ", "İ", True),
            ("\ua7ce*", "\ua7cf_suffix", True), ("\U00016ea0?", "\U00016ebbZ", True)]
        for pattern, value, expected in cases:
            with self.subTest(pattern=pattern, value=value):
                self.assertEqual(matches_pattern(pattern, value), expected)

    def test_malformed_policy_is_rejected_without_guessing_defaults(self):
        invalid = [False, [], {"inherit": "none"}, policy(unknown=True), policy(inherit="ALL"),
            policy(inherit=1), policy(ignoreDefaultExcludes=1), policy(exclude="*"),
            policy(exclude=[1]), policy(includeOnly=["\ud800"]), policy(set=[]), policy(set={"A": 1})]
        for value in invalid:
            with self.subTest(value=repr(value)), self.assertRaises(RpcError):
                decoded({"env": {}, "envPolicy": value}, {})

    def test_invalid_environment_cannot_reach_native_serialization(self):
        for values in ([], {"": "empty-name"}, {"A=B": "bad"}, {"A\0": "bad"},
                {"A": "bad\0"}, {"A": 1}, {"A": "\ud800"}):
            with self.subTest(values=repr(values)):
                with self.assertRaises(RpcError):
                    decoded({"env": values})
                with self.assertRaises(RpcError):
                    snapshot_environment(values)

    def test_native_limits_apply_after_filters_and_overrides(self):
        large = {"K" + str(index): "value" for index in range(129)}
        with self.assertRaises(RpcError):
            decoded({"env": large})
        self.assertEqual(decoded({"env": {}, "envPolicy": policy(includeOnly=["K0"])}, large), {"K0": "value"})
        with self.assertRaises(RpcError):
            decoded({"env": {"A": "é" * 32767}})
        self.assertEqual(len(process_environment({"env": {"A": "x" * 65533}})), 65536)


if __name__ == "__main__":
    unittest.main(verbosity=2)
