"""Android/Unix ExecEnvPolicy semantics pinned to Codex rust-v0.153.4.

The supervisor supplies the parent snapshot; this module never reads os.environ.
See native-environment.md for the exact upstream ordering and wire contract.
"""
from collections.abc import Mapping
from types import MappingProxyType

from tools.executor.exec_server import RpcError
from tools.executor.native_environment_unicode import lowercase_scalar

NON_INHERITABLE = frozenset({"CODEX_EXEC_SERVER_NOISE_AUTH_TOKEN", "NODE_REPL_AUTH_TOKEN",
    "OPENAI_FEDERATION_RULE_ID", "OPENAI_IDENTITY_TOKEN_FILE", "OPENAI_WORKLOAD_IDENTITY_CONTEXT"})
EOF_CONTROL = "CODEX_EXEC_SERVER_EXIT_ON_STDIN_CLOSE"
UNIX_CORE = frozenset({"PATH", "SHELL", "TMPDIR", "TEMP", "TMP", "HOME", "LANG",
    "LC_ALL", "LC_CTYPE", "LOGNAME", "USER"})
POLICY_FIELDS = frozenset({"inherit", "ignoreDefaultExcludes", "exclude", "set", "includeOnly"})
_ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _variables(values):
    if not isinstance(values, Mapping):
        raise RpcError(-32602, "Process environment must be a string mapping")
    result = {}
    for name, value in values.items():
        if (type(name) is not str or not name or "=" in name or "\0" in name
                or type(value) is not str or "\0" in value):
            raise RpcError(-32602, "Invalid process environment variable")
        try:
            (name + value).encode("utf-8")
        except UnicodeEncodeError as error:
            raise RpcError(-32602, "Process environment is not valid Unicode") from error
        result[name] = value
    return result


def snapshot_environment(values):
    """Freeze an explicitly supplied supervisor environment, or retain absence.

    An omitted snapshot cannot silently stand in for an empty parent environment
    when an RPC requests inheritance. An explicit empty mapping is meaningful.
    """
    return None if values is None else MappingProxyType(_variables(values))


def matches_pattern(pattern, name):
    """Match wildmatch 2.6.1 '*'/'?' with per-character Unicode lowercase.

    Brackets and backslashes are literal, unlike Python fnmatch. Lowercase each
    scalar independently: whole-string lower/casefold changes matching semantics.
    """
    pattern_index = name_index = 0
    star = -1
    retry = 0
    while name_index < len(name):
        if pattern_index < len(pattern) and pattern[pattern_index] == "*":
            star = pattern_index
            pattern_index += 1
            retry = name_index
        elif (pattern_index < len(pattern) and (pattern[pattern_index] == "?"
                or lowercase_scalar(pattern[pattern_index]) == lowercase_scalar(name[name_index]))):
            pattern_index += 1
            name_index += 1
        elif star >= 0:
            retry += 1
            name_index = retry
            pattern_index = star + 1
        else:
            return False
    while pattern_index < len(pattern) and pattern[pattern_index] == "*":
        pattern_index += 1
    return pattern_index == len(pattern)


def _patterns(values):
    if type(values) is not list or any(type(value) is not str for value in values):
        raise RpcError(-32602, "Environment policy patterns must be a string list")
    try:
        for value in values:
            value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise RpcError(-32602, "Environment policy pattern is not valid Unicode") from error
    return values


def process_environment(params, parent_environment=None):
    """Resolve the portable RPC policy and encode the bounded native execve env.

    All five ExecEnvPolicy fields are required on the wire. Config TOML defaults
    have already been resolved by the official caller and are not guessed here.
    """
    explicit = _variables(params["env"])
    policy = params.get("envPolicy")
    if policy is None:
        result = explicit
    else:
        if type(policy) is not dict or set(policy) != POLICY_FIELDS:
            raise RpcError(-32602, "Environment policy requires the complete supported wire fields")
        inherit = policy["inherit"]
        if type(inherit) is not str or inherit not in {"none", "core", "all"}:
            raise RpcError(-32602, "Invalid environment inheritance policy")
        if type(policy["ignoreDefaultExcludes"]) is not bool:
            raise RpcError(-32602, "ignoreDefaultExcludes must be a boolean")
        exclude, include = _patterns(policy["exclude"]), _patterns(policy["includeOnly"])
        overrides = _variables(policy["set"])
        if inherit == "none":
            result = {}
        else:
            if parent_environment is None:
                raise RpcError(-32602, "Environment inheritance requires a supervisor-owned parent snapshot")
            result = dict(parent_environment)
            if inherit == "core":
                result = {key: value for key, value in result.items() if key.translate(_ASCII_UPPER) in UNIX_CORE}
        if not policy["ignoreDefaultExcludes"]:
            result = {key: value for key, value in result.items()
                if not any(matches_pattern(pattern, key) for pattern in ("*KEY*", "*SECRET*", "*TOKEN*"))}
        result = {key: value for key, value in result.items()
            if not any(matches_pattern(pattern, key) for pattern in exclude)}
        result.update(overrides)
        if include:
            result = {key: value for key, value in result.items()
                if any(matches_pattern(pattern, key) for pattern in include)}
        # Executor RPC overrides are applied after the shell policy filters.
        result.update(explicit)
    result = {key: value for key, value in result.items()
        if key != EOF_CONTROL and key.translate(_ASCII_UPPER) not in NON_INHERITABLE}
    encoded = b"".join((name + "=" + value).encode("utf-8") + b"\0" for name, value in result.items())
    if len(result) > 128 or len(encoded) > 65536:
        raise RpcError(-32602, "Resolved environment exceeds the admitted native bounds")
    return encoded
