"""Canonical UTF-8 POSIX file URIs for the engine's url 2.5.8 PathUri.

Url::from_file_path on Unix percent-encodes each segment with url's
SPECIAL_PATH_SEGMENT set (url/src/parser.rs:20-42, lib.rs:2948-2980).
Unlike pathlib.as_uri and GuestPath.uri, this keeps '=', '+' and the other
permitted path characters literal. This module grants no filesystem authority.
"""
import os
import re
from urllib.parse import quote, unquote, urlsplit

_PATH_SAFE = "!$&'()*+,:;=@[]^|"


def path_uri(path):
    """Serialize one unambiguous absolute POSIX path, without filesystem I/O."""
    value = os.fspath(path)
    if (type(value) is not str or not value.startswith("/")
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or len(value.encode("utf-8", errors="strict")) >= 4096):
        raise ValueError("Native URI requires an absolute UTF-8 POSIX path")
    parts = value[1:].split("/") if value != "/" else []
    if (any(part in ("", ".", "..") for part in parts)
            or parts and re.fullmatch(r"[A-Za-z][:|]", parts[0])):
        raise ValueError("Native URI path has ambiguous components")
    return "file:///" + "/".join(quote(part, safe=_PATH_SAFE, errors="strict") for part in parts)


def uri_path(value):
    """Decode only the exact spelling emitted by the engine's POSIX serializer."""
    if type(value) is not str:
        raise ValueError("Native path must be a canonical file URI")
    uri = urlsplit(value)
    if uri.scheme != "file" or uri.netloc or uri.query or uri.fragment:
        raise ValueError("Native path must be a local absolute file URI")
    path = unquote(uri.path, errors="strict")
    if path_uri(path) != value:
        raise ValueError("Native file URI is not canonical")
    return path
