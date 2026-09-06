#!/usr/bin/python3
"""xdg-open adapter for FoldGPT's foreground Android HTTP(S) URL bridge."""
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import struct
import sys
import time
import unicodedata
from urllib.parse import quote, urlsplit

MAX_URL_BYTES = 8192
MAX_RESPONSE_BYTES = 256
TIMEOUT_SECONDS = 5.0
FALLBACK = "/usr/bin/xdg-open"
ERRORS = frozenset({"unauthorized", "not_visible", "no_handler", "launch_failed",
                    "unavailable", "timeout", "invalid_url", "invalid_request"})


class OpenError(Exception):
    """Fixed error text only: URLs may contain login credentials in the query."""


def _reject_controls(value, *, raw):
    for char in value:
        if (unicodedata.category(char) in {"Cc", "Cf", "Cs"} or char == "\\"
                or raw and (char.isspace() or char in '\"<>^`{|}')):
            raise OpenError("invalid_url")


def validate_url(value):
    try:
        if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_URL_BYTES:
            raise ValueError()
        _reject_controls(value, raw=True)
        offset = 0
        while offset < len(value):
            if value[offset] != "%":
                offset += 1
                continue
            decoded = bytearray()
            while offset < len(value) and value[offset] == "%":
                encoded = value[offset + 1:offset + 3]
                if len(encoded) != 2 or not re.fullmatch("[0-9A-Fa-f]{2}", encoded):
                    raise ValueError()
                decoded.append(int(encoded, 16))
                offset += 3
            _reject_controls(decoded.decode("utf-8"), raw=False)
        uri = urlsplit(value)
        if (uri.scheme.lower() not in {"http", "https"} or not uri.netloc or not uri.hostname
                or "@" in uri.netloc or "%" in uri.netloc or uri.netloc.endswith(":")):
            raise ValueError()
        uri.netloc.encode("ascii")  # International DNS names must use punycode.
        host = uri.hostname
        if ":" in host:
            ipaddress.IPv6Address(host)
            if not uri.netloc.startswith("["):
                raise ValueError()
        else:
            dns = host.removesuffix(".")
            if not dns or len(dns) > 253 or any(not re.fullmatch(
                    "[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in dns.split(".")):
                raise ValueError()
            last = dns.rsplit(".", 1)[-1]
            if re.fullmatch("[0-9]+|0x[0-9a-f]+", last):
                if len(dns.split(".")) != 4:
                    raise ValueError()
                for part in dns.split("."):
                    if not re.fullmatch("0|[1-9][0-9]{0,2}", part) or int(part) > 255:
                        raise ValueError()
        if uri.port is not None and not 1 <= uri.port <= 65535:
            raise ValueError()
        result = quote(value, safe="/:?#[]@!$&'()*+,;=-._~%")
        result = uri.scheme.lower() + result[len(uri.scheme):]
        if len(result) > MAX_URL_BYTES:
            raise ValueError()
        return result
    except (ValueError, UnicodeError, TypeError):
        raise OpenError("invalid_url") from None


def target_uid(environment):
    value = environment.get("FOLDGPT_URL_UID", environment.get("FOLDGPT_IME_UID", ""))
    if not re.fullmatch("[1-9][0-9]{0,9}", value) or int(value) > 2**31 - 1:
        raise OpenError("unavailable")
    return int(value)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise OpenError("invalid_response")
        result[key] = value
    return result


def open_web_url(url, uid, *, timeout=TIMEOUT_SECONDS, socket_factory=socket.socket):
    canonical = validate_url(url)
    deadline = time.monotonic() + timeout
    try:
        with socket_factory(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
            def remaining():
                duration = deadline - time.monotonic()
                if duration <= 0:
                    raise OpenError("timeout")
                channel.settimeout(duration)

            remaining()
            channel.connect("\0foldgpt-url-" + str(uid))
            # PRoot's getuid() may be virtualized. Verify the server's real
            # kernel credentials against the Android UID supplied by FoldGPT.
            credentials = channel.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            _pid, peer_uid, _gid = struct.unpack("3i", credentials)
            if peer_uid != uid:
                raise OpenError("unauthorized")
            remaining()
            channel.sendall(json.dumps({"url": canonical}, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            response = bytearray()
            while b"\n" not in response:
                remaining()
                chunk = channel.recv(MAX_RESPONSE_BYTES + 1 - len(response))
                if not chunk:
                    raise OpenError("invalid_response")
                response.extend(chunk)
                if len(response) > MAX_RESPONSE_BYTES:
                    raise OpenError("invalid_response")
            if response.count(b"\n") != 1 or not response.endswith(b"\n"):
                raise OpenError("invalid_response")
            value = json.loads(response, object_pairs_hook=_unique)
            if type(value) is not dict or type(value.get("accepted")) is not bool:
                raise OpenError("invalid_response")
            if value["accepted"] and set(value) == {"accepted"}:
                return
            if not value["accepted"] and set(value) == {"accepted", "error"} and value["error"] in ERRORS:
                raise OpenError(value["error"])
            raise OpenError("invalid_response")
    except (TimeoutError, socket.timeout):
        raise OpenError("timeout") from None
    except (OSError, AttributeError):
        raise OpenError("unavailable") from None
    except (ValueError, UnicodeError, TypeError, RecursionError, struct.error):
        raise OpenError("invalid_response") from None


def main(argv=None, *, environment=None, fallback=FALLBACK, execve=os.execve, opener=open_web_url):
    args = list(sys.argv[1:] if argv is None else argv)
    environment = dict(os.environ if environment is None else environment)
    try:
        # Treat malformed http(s) candidates as errors, never as fallback input.
        if len(args) == 1 and args[0].split(":", 1)[0].strip().lower() in {"http", "https"}:
            canonical = validate_url(args[0])
            opener(canonical, target_uid(environment))
            return 0
        if environment.get("FOLDGPT_OPEN_FALLBACK") == "1":
            raise OpenError("fallback_recursion")
        if not os.path.isabs(fallback) or not os.path.isfile(fallback) or not os.access(fallback, os.X_OK):
            raise OpenError("fallback_unavailable")
        if Path(fallback).resolve() == Path(__file__).resolve():
            raise OpenError("fallback_recursion")
        environment["FOLDGPT_OPEN_FALLBACK"] = "1"
        execve(fallback, [fallback, *args], environment)
        raise OpenError("fallback_failed")  # A real execve cannot return success.
    except (OSError, OpenError) as error:
        reason = str(error) if isinstance(error, OpenError) else "fallback_failed"
        print("FoldGPT URL open failed: " + reason, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
