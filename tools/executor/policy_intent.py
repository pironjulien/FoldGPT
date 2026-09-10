"""Immutable policy handoff data, not an executor or an enforcement decision.

Keep the official portable context as the native boundary's semantic input.
Do not lower it into additive Landlock roots or omit metadata exceptions. This
adapter accepts only the existing strict resolver's documented subset. It has
no device, filesystem, subprocess, transport, environment, or model access.
"""

from dataclasses import dataclass
import hashlib
import json

from tools.policy.managed_policy import OFFICIAL_COMMIT, OFFICIAL_TAG, PolicyError, parse_context


SCHEMA = "foldgpt.policy-intent.v1"
# These methods introduce a complete policy-bearing operation. Handle/process
# lifecycle methods must use the policy bound at creation, never a replacement
# supplied by another request. This list advertises no implemented capability.
POLICY_BEARING_METHODS = frozenset({
    "process/start", "fs/readFile", "fs/open", "fs/writeFile",
    "fs/createDirectory", "fs/getMetadata", "fs/canonicalize",
    "fs/readDirectory", "fs/walk", "fs/remove", "fs/copy",
})


def _identifier(value, field):
    if type(value) is not str or not value:
        raise PolicyError(field, "expected a nonempty connection-local identifier")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise PolicyError(field, "identifier must be UTF-8") from error
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PolicyError(field, "control characters are unsupported")
    return value


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class PolicyIntent:
    """Immutable bytes from prepare_policy_intent; no native access is granted.

    The digest correlates normalized policy input, not caller identity, a
    kernel domain, a native descriptor, or permission to execute an operation.
    Native code must validate an authenticated control channel and independently
    establish the complete enforcement boundary before acknowledging a request.
    """

    session_id: str
    request_id: str
    method: str
    context_json: bytes

    def __post_init__(self):
        _identifier(self.session_id, "$.sessionId")
        _identifier(self.request_id, "$.requestId")
        if type(self.method) is not str or self.method not in POLICY_BEARING_METHODS:
            raise PolicyError("$.method", "expected a supported policy-bearing exec-server method")
        if type(self.context_json) is not bytes:
            raise PolicyError("$.context", "expected UTF-8 context bytes")
        normalized = _json_bytes(parse_context(self.context_json).to_context_dict())
        object.__setattr__(self, "context_json", normalized)

    @property
    def context_sha256(self):
        return hashlib.sha256(self.context_json).hexdigest()

    def to_document(self):
        return {
            "schema": SCHEMA,
            "resolver": {"tag": OFFICIAL_TAG, "commit": OFFICIAL_COMMIT},
            "sessionId": self.session_id,
            "requestId": self.request_id,
            "method": self.method,
            "contextSha256": self.context_sha256,
            "context": json.loads(self.context_json),
        }

    def to_bytes(self):
        return _json_bytes(self.to_document())


def prepare_policy_intent(context, *, session_id, request_id, method):
    """Validate all policy input and snapshot its native handoff representation.

    The caller owns session/request identity. The native supervisor must bind
    this record to that exact operation's payload and its executor-owned mount
    view; IDs and digests are not accepted as bearer capabilities. No process,
    file descriptor, native path, access decision, or protocol success is made.
    """
    policy = parse_context(context)
    return PolicyIntent(session_id, request_id, method, _json_bytes(policy.to_context_dict()))
