"""Pure, bounded Codex 0.153.4 filesystem policy resolver; never a sandbox.

Source: rust-v0.153.4 / 042fb41b7c813ac7999105e886b2b7aa715b5081:
  file-system/src/lib.rs:174-210,237-291,330-348 (portable context)
  protocol/src/permissions.rs:926-1001,1782-1823 (access and metadata)
  utils/path-uri/src/lib.rs:324-385,773-807 (POSIX containment)

This module neither reads the host filesystem nor opens files on the Fold.
Decisions are lexical and are NOT authorization to perform a native operation.
Kernel-pinned paths, links, gitdir pointers, runtime grants, syscall mediation,
and process/network isolation belong to the as-yet separate native boundary.

Accepted inputs have exact semantics for this subset of the upstream resolver:
managed/restricted/restricted-network; UTF-8 POSIX file URIs; literal paths and
root/project_roots/tmpdir/slash_tmp special paths. Project subpaths must be
relative and contain no '..'. Ordinary URI/native paths must contain no dot
segments. Globs, missing-path behavior, platform defaults, full-disk special
root-write mode, foreign/opaque paths, other enforcement modes, and unknown
fields fail explicitly. See README.md for the distinction from runtime policy.
"""

from dataclasses import dataclass
from enum import Enum
import json
import re
from urllib.parse import quote, unquote_to_bytes, urlsplit


OFFICIAL_TAG = "rust-v0.153.4"
OFFICIAL_COMMIT = "042fb41b7c813ac7999105e886b2b7aa715b5081"
METADATA_NAMES = (".git", ".agents", ".codex")


class PolicyError(ValueError):
    """The entire input is invalid or outside this resolver's accepted subset."""

    def __init__(self, field, reason):
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


class Access(str, Enum):
    READ = "read"
    WRITE = "write"
    DENY = "deny"


_PRECEDENCE = {Access.READ: 0, Access.WRITE: 1, Access.DENY: 2}


def _object(value, field, allowed, required=()):
    if type(value) is not dict:
        raise PolicyError(field, "expected a JSON object")
    for key in value:
        if key not in allowed:
            raise PolicyError(f"{field}.{key}", "unsupported field")
    for key in required:
        if key not in value:
            raise PolicyError(f"{field}.{key}", "required field is missing")
    return value


def _text(value, field):
    if not isinstance(value, str):
        raise PolicyError(field, "expected a string")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise PolicyError(field, "non-UTF-8 text is unsupported") from error
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise PolicyError(field, "control characters are unsupported")
    return value


def _array(value, field):
    if type(value) is not list:
        raise PolicyError(field, "expected a JSON array")
    return value


def _false_option(value, field):
    if type(value) is not bool:
        raise PolicyError(field, "expected a boolean")
    if value:
        raise PolicyError(field, "enabled option is unsupported")


def _only_null(value, field):
    if value is not None:
        raise PolicyError(field, "non-null option is unsupported")


@dataclass(frozen=True)
class GuestPath:
    """Decoded POSIX components; no filesystem lookup or symlink resolution."""

    parts: tuple[str, ...]

    @classmethod
    def from_uri(cls, value, field="path"):
        value = _text(value, field)
        # Restrict spelling before urlsplit, which otherwise normalizes certain
        # controls. Raw backslashes have special WHATWG file-URL semantics.
        if not value.startswith("file://"):
            raise PolicyError(field, "expected an absolute file:// URI")
        if "\\" in value or "?" in value or "#" in value:
            raise PolicyError(field, "raw backslash, query or fragment is unsupported")
        if re.search(r"%(?![0-9A-Fa-f]{2})", value):
            raise PolicyError(field, "malformed percent encoding")
        try:
            parsed = urlsplit(value)
        except ValueError as error:
            raise PolicyError(field, "invalid file URI") from error
        if parsed.netloc.lower() not in ("", "localhost"):
            raise PolicyError(field, "foreign authority, credentials or port is unsupported")
        if not parsed.path.startswith("/"):
            raise PolicyError(field, "expected an absolute POSIX URI path")
        parts = []
        for encoded in parsed.path.split("/"):
            if not encoded:
                continue
            try:
                component = unquote_to_bytes(encoded).decode("utf-8", errors="strict")
            except UnicodeError as error:
                raise PolicyError(field, "non-UTF-8 path bytes are unsupported") from error
            _text(component, field)
            if "/" in component:
                raise PolicyError(field, "percent-encoded separator has no safe lexical boundary")
            if component in (".", ".."):
                raise PolicyError(field, "dot segments require upstream URL normalization and are unsupported")
            parts.append(component)
        return cls._validated(parts, field)

    @classmethod
    def from_absolute(cls, value, field="path"):
        value = _text(value, field)
        if not value.startswith("/"):
            raise PolicyError(field, "expected an absolute POSIX guest path")
        parts = [part for part in value.split("/") if part]
        if any(part in (".", "..") for part in parts):
            raise PolicyError(field, "dot segments in native paths are unsupported")
        return cls._validated(parts, field)

    @classmethod
    def _validated(cls, parts, field):
        if parts and re.fullmatch(r"[A-Za-z][:|]", parts[0]):
            raise PolicyError(field, "drive-shaped first component is unsupported")
        return cls(tuple(parts))

    @property
    def path(self):
        return "/" + "/".join(self.parts)

    @property
    def uri(self):
        return "file:///" + "/".join(quote(part, safe="") for part in self.parts)

    def contains(self, other):
        return other.parts[:len(self.parts)] == self.parts

    def append(self, parts):
        return GuestPath(self.parts + tuple(parts))


@dataclass(frozen=True)
class Entry:
    access: Access
    kind: str
    path: GuestPath | None = None
    special: str | None = None
    subpath: tuple[str, ...] | None = None

    def to_dict(self):
        if self.kind == "path":
            path = {"type": "path", "path": self.path.uri}
        else:
            value = {"kind": self.special}
            if self.subpath is not None:
                value["subpath"] = "/".join(self.subpath)
            path = {"type": "special", "value": value}
        return {"path": path, "access": self.access.value}


@dataclass(frozen=True)
class ResolvedEntry:
    path: GuestPath
    access: Access
    source_index: int


@dataclass(frozen=True)
class Decision:
    """Raw upstream access plus the separate symbolic metadata write check."""

    path: GuestPath
    resolved_access: Access
    metadata_write_denial: str | None

    @property
    def can_read(self):
        return self.resolved_access != Access.DENY

    @property
    def can_write(self):
        return self.resolved_access == Access.WRITE and self.metadata_write_denial is None

    @property
    def access(self):
        """Effective lexical access after metadata protection, not kernel access."""
        if self.resolved_access == Access.WRITE and not self.can_write:
            return Access.READ
        return self.resolved_access


@dataclass(frozen=True)
class ManagedPolicy:
    cwd: GuestPath
    workspace_roots: tuple[GuestPath, ...]
    user_home_dir: GuestPath | None
    temporary_directories: tuple[GuestPath, ...] | None
    entries: tuple[Entry, ...]
    resolved_entries: tuple[ResolvedEntry, ...]

    def decide(self, absolute_guest_path):
        return self._decide(GuestPath.from_absolute(absolute_guest_path))

    def decide_uri(self, guest_uri):
        return self._decide(GuestPath.from_uri(guest_uri))

    def _decide(self, path):
        candidates = [entry for entry in self.resolved_entries if entry.path.contains(path)]
        winner = max(candidates, key=lambda entry: (len(entry.path.parts), _PRECEDENCE[entry.access]), default=None)
        access = winner.access if winner else Access.DENY
        metadata = None
        if access == Access.WRITE:
            # Preserve source ordering here: upstream metadata_write_denial uses
            # the FIRST matching protected root, then looks for an explicit grant
            # below that root. Sorting/coalescing rules can change this behavior.
            protected = None
            for entry in self.resolved_entries:
                if entry.access != Access.WRITE:
                    continue
                for name in METADATA_NAMES:
                    candidate = entry.path.append((name,))
                    if candidate.contains(path):
                        protected, metadata = candidate, name
                        break
                if protected is not None:
                    break
            if protected is not None and any(
                entry.access == Access.WRITE and protected.contains(entry.path) and entry.path.contains(path)
                for entry in self.resolved_entries
            ):
                metadata = None
        return Decision(path, access, metadata)

    def to_context_dict(self):
        """Return a fresh normalized portable context, retaining entry order."""
        result = {
            "permissions": {
                "type": "managed",
                "file_system": {"type": "restricted", "entries": [entry.to_dict() for entry in self.entries]},
                "network": "restricted",
            },
            "cwd": self.cwd.uri,
            "workspaceRoots": [path.uri for path in self.workspace_roots],
            "windowsSandboxLevel": "disabled",
            "windowsSandboxPrivateDesktop": False,
            "useLegacyLandlock": False,
        }
        if self.user_home_dir is not None:
            result["userHomeDir"] = self.user_home_dir.uri
        if self.temporary_directories is not None:
            result["temporaryDirectories"] = [path.uri for path in self.temporary_directories]
        return result


def _entry(value, index):
    field = f"$.permissions.file_system.entries[{index}]"
    value = _object(value, field, {"path", "access", "missing_path_behavior"}, ("path", "access"))
    _only_null(value.get("missing_path_behavior"), field + ".missing_path_behavior")
    access_text = value["access"]
    if type(access_text) is not str or access_text not in ("read", "write", "deny", "none"):
        raise PolicyError(field + ".access", "expected read, write, deny or the upstream none alias")
    access = Access.DENY if access_text == "none" else Access(access_text)
    path = _object(value["path"], field + ".path", {"type", "path", "value", "pattern"}, ("type",))
    if path["type"] == "path":
        _object(path, field + ".path", {"type", "path"}, ("path",))
        return Entry(access, "path", path=GuestPath.from_uri(path["path"], field + ".path.path"))
    if path["type"] != "special":
        raise PolicyError(field + ".path.type", "only literal and supported special paths are accepted; globs are unsupported")
    _object(path, field + ".path", {"type", "value"}, ("value",))
    special = _object(path["value"], field + ".path.value", {"kind", "subpath"}, ("kind",))
    kind = special["kind"]
    if kind == "current_working_directory":
        kind = "project_roots"
    if type(kind) is not str or kind not in ("root", "project_roots", "tmpdir", "slash_tmp"):
        raise PolicyError(field + ".path.value.kind", "unsupported special path; no platform defaults or unknown-token fallback")
    if kind == "root" and access == Access.WRITE:
        raise PolicyError(field + ".access", "special root write requires the upstream full-disk narrowing analysis and is unsupported")
    subpath = None
    if kind != "project_roots":
        _object(special, field + ".path.value", {"kind"})
    elif special.get("subpath") is not None:
        raw = _text(special["subpath"], field + ".path.value.subpath")
        if raw.startswith("/") or ".." in raw.split("/"):
            raise PolicyError(field + ".path.value.subpath", "absolute and parent-traversing subpaths are unsupported")
        # Upstream join treats subpath as native text: '%' is a literal byte,
        # not another round of URI decoding; empty and '.' components disappear.
        subpath = tuple(part for part in raw.split("/") if part not in ("", "."))
    return Entry(access, "special", special=kind, subpath=subpath)


def _decode_json(document):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise PolicyError("$", f"duplicate JSON member {key!r}")
            result[key] = value
        return result

    def nonfinite(value):
        raise PolicyError("$", f"non-finite JSON value {value!r}")

    try:
        if isinstance(document, bytes):
            document = document.decode("utf-8", errors="strict")
        return json.loads(document, object_pairs_hook=unique, parse_constant=nonfinite)
    except (json.JSONDecodeError, UnicodeError, RecursionError) as error:
        raise PolicyError("$", "invalid JSON text") from error


def parse_context(document):
    """Validate fully, then return an immutable lexical policy snapshot.

    Accept a JSON string/UTF-8 bytes or an ordinary decoded JSON dict. An error
    names the invalid/unsupported field; no partial policy is returned.
    """
    if isinstance(document, (str, bytes)):
        document = _decode_json(document)
    context = _object(document, "$", {
        "permissions", "cwd", "workspaceRoots", "userHomeDir", "temporaryDirectories",
        "windowsSandboxLevel", "windowsSandboxPrivateDesktop", "windowsSandboxProxySettingsMode",
        "useLegacyLandlock",
    }, ("permissions", "cwd", "windowsSandboxLevel"))
    if context["windowsSandboxLevel"] != "disabled":
        raise PolicyError("$.windowsSandboxLevel", "only disabled Windows settings are accepted for this POSIX resolver")
    _false_option(context.get("windowsSandboxPrivateDesktop", False), "$.windowsSandboxPrivateDesktop")
    _only_null(context.get("windowsSandboxProxySettingsMode"), "$.windowsSandboxProxySettingsMode")
    _false_option(context.get("useLegacyLandlock", False), "$.useLegacyLandlock")
    permissions = _object(context["permissions"], "$.permissions", {"type", "file_system", "network"}, ("type",))
    if permissions["type"] != "managed":
        raise PolicyError("$.permissions.type", "only managed policies are accepted")
    _object(permissions, "$.permissions", {"type", "file_system", "network"}, ("file_system", "network"))
    if permissions["network"] != "restricted":
        raise PolicyError("$.permissions.network", "only restricted network intent is accepted; no networking is enforced here")
    fs = _object(permissions["file_system"], "$.permissions.file_system", {"type", "entries", "glob_scan_max_depth"}, ("type",))
    if fs["type"] != "restricted":
        raise PolicyError("$.permissions.file_system.type", "only restricted filesystem policies are accepted")
    _object(fs, "$.permissions.file_system", {"type", "entries", "glob_scan_max_depth"}, ("entries",))
    _only_null(fs.get("glob_scan_max_depth"), "$.permissions.file_system.glob_scan_max_depth")
    cwd = GuestPath.from_uri(context["cwd"], "$.cwd")

    def paths(key, default):
        values = _array(context.get(key, default), "$." + key)
        return tuple(GuestPath.from_uri(value, f"$.{key}[{index}]") for index, value in enumerate(values))

    roots = paths("workspaceRoots", [])
    home = context.get("userHomeDir")
    home = GuestPath.from_uri(home, "$.userHomeDir") if home is not None else None
    temps = paths("temporaryDirectories", []) if context.get("temporaryDirectories") is not None else None
    entries = tuple(_entry(value, index) for index, value in enumerate(_array(fs["entries"], "$.permissions.file_system.entries")))
    resolved = []
    for index, entry in enumerate(entries):
        if entry.kind == "path":
            targets = (entry.path,)
        elif entry.special == "root":
            targets = (GuestPath(()),)
        elif entry.special == "project_roots":
            targets = tuple(root.append(entry.subpath or ()) for root in roots)
        elif entry.special == "tmpdir":
            targets = temps or ()
        else:  # The parser permits exactly one remaining special: slash_tmp.
            targets = (GuestPath(("tmp",)),)
        resolved.extend(ResolvedEntry(path, entry.access, index) for path in targets)
    return ManagedPolicy(cwd, roots, home, temps, entries, tuple(resolved))
