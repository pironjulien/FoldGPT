"""Lexical policy conformance, not kernel/broker/isolation tests.

Expectations come from the pinned source cited in tools/policy/README.md and
the reviewed JSON vectors. No official Rust binary is executed by these tests.
"""

import copy
from dataclasses import FrozenInstanceError
import itertools
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.policy.managed_policy import Access, GuestPath, PolicyError, parse_context


VECTORS = json.loads((Path(__file__).resolve().parents[1] / "tools/policy/managed-policy-vectors.json").read_text(encoding="utf-8"))


def literal(path, access):
    return {"path": {"type": "path", "path": path}, "access": access}


def special(kind, access, **extra):
    return {"path": {"type": "special", "value": {"kind": kind, **extra}}, "access": access}


def context(entries=None):
    value = copy.deepcopy(VECTORS["context"])
    value["permissions"] = copy.deepcopy(VECTORS["profile_envelope"])
    value["permissions"]["file_system"]["entries"] = entries or []
    return value


class ResolverVectorsTests(unittest.TestCase):
    def test_documented_resolution_vectors_and_entry_permutations(self):
        for vector in VECTORS["resolution_cases"]:
            orders = itertools.permutations(vector["entries"]) if vector.get("check_all_entry_permutations") else [vector["entries"]]
            for order in orders:
                policy = parse_context(context(list(order)))
                for query in vector["queries"]:
                    with self.subTest(case=vector["id"], query=query["path"], order=order):
                        result = policy.decide(query["path"])
                        self.assertEqual(result.resolved_access.value, query["access"])
                        self.assertEqual(result.can_write, query["can_write"])
                        self.assertEqual(result.can_read, query["access"] != "deny")

    def test_A_B_C_are_independent_policy_snapshots_on_the_same_path(self):
        base = [literal("file:///", "read"), literal("file:///workspace", "write")]
        a = parse_context(context(base))
        b = parse_context(context(base + [literal("file:///workspace/value.txt", "read")]))
        c = parse_context(context(base + [literal("file:///workspace/value.txt", "deny")]))
        path = "/workspace/value.txt"
        self.assertEqual([p.decide(path).access for p in (a, b, c, a)], [Access.WRITE, Access.READ, Access.DENY, Access.WRITE])
        self.assertEqual([p.decide(path).can_read for p in (a, b, c)], [True, True, False])
        self.assertTrue(c.decide("/workspace/other.txt").can_write)

    def test_git_file_itself_and_descendants_are_distinct_from_gitignore(self):
        policy = parse_context(context([literal("file:///workspace", "write")]))
        for name in (".git", ".git/config", ".agents", ".agents/config", ".codex", ".codex/config"):
            with self.subTest(name=name):
                result = policy.decide("/workspace/" + name)
                self.assertEqual(result.resolved_access, Access.WRITE)
                self.assertEqual(result.access, Access.READ)
                self.assertEqual(result.metadata_write_denial, name.split("/")[0])
        for name in (".gitignore", ".git-other/config", ".codexignore", ".agents.txt"):
            self.assertTrue(policy.decide("/workspace/" + name).can_write)

    def test_nested_metadata_is_not_automatically_a_top_level_protection(self):
        basic = parse_context(context([literal("file:///workspace", "write")]))
        extended = parse_context(context([literal("file:///workspace", "write"), literal("file:///workspace/src", "write")]))
        self.assertTrue(basic.decide("/workspace/src/.git").can_write)
        self.assertFalse(extended.decide("/workspace/src/.git").can_write)

    def test_metadata_preserves_upstream_first_matching_root_semantics(self):
        # permissions.rs:986-1001 uses find_map, then searches an explicit grant
        # inside THAT protected root. Do not silently sort/coalesce entries.
        outer = literal("file:///workspace", "write")
        inner = literal("file:///workspace/.git", "write")
        query = "/workspace/.git/.codex/config"
        self.assertTrue(parse_context(context([outer, inner])).decide(query).can_write)
        reverse = parse_context(context([inner, outer])).decide(query)
        self.assertFalse(reverse.can_write)
        self.assertEqual(reverse.metadata_write_denial, ".codex")

    def test_explicit_metadata_exception_does_not_override_equal_deny(self):
        policy = parse_context(context([
            literal("file:///workspace", "write"),
            literal("file:///workspace/.git/config", "write"),
            literal("file:///workspace/.git/config", "deny"),
        ]))
        self.assertEqual(policy.decide("/workspace/.git/config").access, Access.DENY)

    def test_literal_root_write_is_not_upstream_special_full_disk_mode(self):
        policy = parse_context(context([literal("file:///", "write")]))
        self.assertFalse(policy.decide("/.git/config").can_write)
        self.assertTrue(policy.decide("/workspace/.git/config").can_write)

    def test_empty_executor_roots_and_temporary_directories_grant_nothing(self):
        value = context([special("project_roots", "write"), special("tmpdir", "write")])
        value.pop("workspaceRoots")
        value.pop("temporaryDirectories")
        policy = parse_context(value)
        self.assertEqual(policy.decide("/workspace/src").access, Access.DENY)
        self.assertEqual(policy.decide("/tmp/cache").access, Access.DENY)

    def test_upstream_legacy_aliases_preserve_semantics(self):
        value = context([special("current_working_directory", "write"), literal("file:///workspace/private", "none")])
        policy = parse_context(value)
        self.assertTrue(policy.decide("/second/file").can_write)
        self.assertEqual(policy.decide("/workspace/private/file").access, Access.DENY)
        normalized = policy.to_context_dict()["permissions"]["file_system"]["entries"]
        self.assertEqual(normalized[0]["path"]["value"]["kind"], "project_roots")
        self.assertEqual(normalized[1]["access"], "deny")


class PathSemanticsTests(unittest.TestCase):
    def test_equivalent_percent_spelling_and_component_boundaries(self):
        policy = parse_context(context([
            literal("file:///", "read"), literal("file:///workspace////", "write"),
            literal("file:///workspace/%70rivate", "deny"),
        ]))
        self.assertEqual(policy.decide_uri("file:///workspace/pri%76ate/key").access, Access.DENY)
        self.assertEqual(policy.decide("/workspace/private/key").access, Access.DENY)
        self.assertEqual(policy.decide("/workspace/private-other/key").access, Access.WRITE)
        self.assertEqual(policy.decide("/workspace-other/key").access, Access.READ)
        self.assertEqual(policy.decide("/WORKSPACE/private/key").access, Access.READ)

    def test_utf8_names_and_uri_native_literals_do_not_double_decode(self):
        policy = parse_context(context([literal("file:///workspace/caf%C3%A9", "write")]))
        self.assertTrue(policy.decide("/workspace/café/file").can_write)
        self.assertTrue(policy.decide_uri("file://localhost/workspace/café/file").can_write)
        self.assertFalse(policy.decide("/workspace/caf%C3%A9/file").can_read)
        percent = parse_context(context([literal("file:///workspace/%252F", "read")]))
        self.assertTrue(percent.decide("/workspace/%2F").can_read)
        self.assertFalse(percent.decide("/workspace/other").can_read)

    def test_project_subpath_is_native_text_not_a_uri(self):
        policy = parse_context(context([special("project_roots", "write", subpath="./assets//%2F?#")]))
        self.assertTrue(policy.decide("/workspace/assets/%2F?#/file").can_write)
        self.assertTrue(policy.decide("/second/assets/%2F?#/file").can_write)
        self.assertFalse(policy.decide("/workspace/assets/other/file").can_read)

    def test_posix_encoded_backslash_is_a_literal_character(self):
        policy = parse_context(context([literal("file:///workspace/a%5Cb", "read")]))
        self.assertTrue(policy.decide("/workspace/a\\b/file").can_read)
        self.assertFalse(policy.decide("/workspace/a/b/file").can_read)

    def test_case_and_unicode_normalization_are_not_folded(self):
        policy = parse_context(context([literal("file:///workspace/é", "write")]))
        self.assertTrue(policy.decide("/workspace/é/file").can_write)
        self.assertFalse(policy.decide("/workspace/É/file").can_read)
        self.assertFalse(policy.decide("/workspace/e\u0301/file").can_read)

    def test_reject_ambiguous_or_unsupported_uri_whole_policy(self):
        paths = [
            "file:///workspace/private%2Fkey", "file:///workspace/%00/key",
            "file:///%00/bad/path/YQ", "file:///workspace/%ff", "file:///workspace/%xy",
            "file:///workspace/../outside", "file:///workspace/%2e%2e/outside",
            "file:///workspace/./file", "file:///C:/workspace", "file:///%43%3a/workspace",
            "file:///C|/workspace", "file:///C%7C/workspace",
            "file://server/share", "file://user:password@localhost/workspace",
            "file://localhost:80/workspace", "file:///workspace?query", "file:///workspace#fragment",
            "file:///workspace\\private", "file:///workspace/\nprivate", "file:relative",
            "file:/workspace", "https://example.com/workspace", "file:///workspace/%01",
        ]
        for uri in paths:
            with self.subTest(uri=uri):
                with self.assertRaises(PolicyError):
                    parse_context(context([literal("file:///", "read"), literal(uri, "deny")]))

    def test_bad_query_is_an_error_not_a_broader_decision(self):
        policy = parse_context(context([literal("file:///", "write")]))
        for path in ("relative", "/workspace/../outside", "/workspace/./file", "/C:/file", "/a\0b"):
            with self.subTest(path=path), self.assertRaises(PolicyError):
                policy.decide(path)
        with self.assertRaises(PolicyError):
            policy.decide_uri("file:///workspace/private%2fkey")

    def test_normalization_is_stable_and_preserves_decisions(self):
        policy = parse_context(context([
            literal("file://localhost/workspace///", "write"),
            literal("file:///workspace/%70rivate/", "deny"),
            special("project_roots", "read", subpath="./assets//"),
        ]))
        normalized = policy.to_context_dict()
        reparsed = parse_context(json.dumps(normalized))
        self.assertEqual(reparsed.to_context_dict(), normalized)
        for path in ("/workspace/value", "/workspace/private/key", "/second/assets/file", "/outside"):
            self.assertEqual(policy.decide(path), reparsed.decide(path))
        self.assertEqual(GuestPath.from_uri("file:///workspace/a%20b/").uri, "file:///workspace/a%20b")


class StrictInputTests(unittest.TestCase):
    def assert_invalid(self, value, field):
        with self.assertRaises(PolicyError) as raised:
            parse_context(value)
        self.assertEqual(raised.exception.field, field)

    def test_known_unsupported_inputs_fail_explicitly(self):
        modifications = [
            ("permissions.type", "external"), ("permissions.type", "disabled"),
            ("permissions.file_system.type", "unrestricted"), ("permissions.network", "enabled"),
            ("permissions.file_system.glob_scan_max_depth", 4),
            ("windowsSandboxLevel", "restrictedToken"), ("windowsSandboxPrivateDesktop", True),
            ("windowsSandboxProxySettingsMode", "proxyOnly"), ("useLegacyLandlock", True),
        ]
        for dotted, value in modifications:
            doc = context()
            target = doc
            keys = dotted.split(".")
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
            with self.subTest(field=dotted):
                self.assert_invalid(doc, "$." + dotted)
        for kind in ("minimal", "unknown", "future_special"):
            self.assert_invalid(context([special(kind, "deny")]), "$.permissions.file_system.entries[0].path.value.kind")
        self.assert_invalid(context([special("root", "write")]), "$.permissions.file_system.entries[0].access")
        self.assert_invalid(context([{"path": {"type": "glob_pattern", "pattern": "**/*.secret"}, "access": "deny"}]), "$.permissions.file_system.entries[0].path.type")
        entry = literal("file:///workspace", "deny")
        entry["missing_path_behavior"] = "skip"
        self.assert_invalid(context([entry]), "$.permissions.file_system.entries[0].missing_path_behavior")
        for path in ("../outside", "a/../public", "/outside"):
            self.assert_invalid(context([special("project_roots", "read", subpath=path)]), "$.permissions.file_system.entries[0].path.value.subpath")

    def test_unknown_fields_are_not_ignored_at_any_level(self):
        for route in ((), ("permissions",), ("permissions", "file_system")):
            doc = context()
            target = doc
            for key in route:
                target = target[key]
            target["futureRestriction"] = True
            self.assert_invalid(doc, "$" + "".join("." + key for key in route) + ".futureRestriction")
        entry = literal("file:///workspace", "read")
        entry["futureRestriction"] = True
        self.assert_invalid(context([entry]), "$.permissions.file_system.entries[0].futureRestriction")
        for value in (
            {"type": "path", "path": "file:///workspace", "value": {"kind": "root"}},
            {"type": "special", "value": {"kind": "root"}, "pattern": "**"},
        ):
            with self.assertRaises(PolicyError):
                parse_context(context([{"path": value, "access": "read"}]))

    def test_wrong_types_and_required_fields(self):
        for key, value in (("cwd", None), ("workspaceRoots", None), ("workspaceRoots", "file:///workspace"),
                           ("temporaryDirectories", {}), ("userHomeDir", 4),
                           ("useLegacyLandlock", 0), ("windowsSandboxPrivateDesktop", 0)):
            doc = context()
            doc[key] = value
            self.assert_invalid(doc, "$." + key)
        for key in ("cwd", "permissions", "windowsSandboxLevel"):
            doc = context()
            del doc[key]
            self.assert_invalid(doc, "$." + key)
        for value in (None, [], True, 7):
            self.assert_invalid(value, "$")
        for access in (None, 0, [], "WRITE", "allow"):
            self.assert_invalid(context([literal("file:///workspace", access)]), "$.permissions.file_system.entries[0].access")

    def test_duplicate_members_nonfinite_invalid_json_and_non_utf8_fail(self):
        for text in ('{"permissions":{},"permissions":{}}', '{"x":NaN}', '{"x":Infinity}',
                     '{"x":-Infinity}', '{', b'\xff', '{"x":1}'.encode("utf-16")):
            with self.subTest(text=text), self.assertRaises(PolicyError):
                parse_context(text)

    def test_nested_input_and_normalized_output_cannot_mutate_a_policy(self):
        doc = context([literal("file:///workspace", "read")])
        policy = parse_context(doc)
        doc["permissions"]["file_system"]["entries"][0]["access"] = "write"
        doc["workspaceRoots"].append("file:///outside")
        out = policy.to_context_dict()
        out["permissions"]["file_system"]["entries"][0]["access"] = "write"
        self.assertEqual(policy.decide("/workspace/file").access, Access.READ)
        self.assertEqual(len(policy.workspace_roots), 2)
        with self.assertRaises(FrozenInstanceError):
            policy.entries = ()

    def test_no_filesystem_or_environment_access_is_needed(self):
        with patch("builtins.open", side_effect=AssertionError("no file lookup")), \
             patch("os.stat", side_effect=AssertionError("no host metadata")), \
             patch("os.getenv", side_effect=AssertionError("no host environment")):
            policy = parse_context(context([special("tmpdir", "write")]))
            self.assertTrue(policy.decide("/tmp/private-a/file").can_write)
            self.assertFalse(policy.decide("/tmp/file").can_write)


if __name__ == "__main__":
    unittest.main()
