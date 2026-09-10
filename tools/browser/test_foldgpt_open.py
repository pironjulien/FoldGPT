import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("foldgpt_open", Path(__file__).with_name("foldgpt-open.py"))
opener = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(opener)


class UriTests(unittest.TestCase):
    def test_web_urls_query_and_unicode_path(self):
        for url in ("https://example.com", "http://localhost:1455/auth/callback?code=fixture&state=fixture",
                    "https://127.0.0.1:443/a%20b", "https://[::1]:1455/", "https://xn--bcher-kva.example/",
                    "https://example.com./a#anchor", "https://example.com/auth?redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fx",
                    "https://example.com/%F0%9F%93%96", "https://example.com/a?encoded=%252F"):
            self.assertEqual(opener.validate_url(url), url)
        self.assertEqual(opener.validate_url("HTTPS://example.com/é"), "https://example.com/%C3%A9")

    def test_unsafe_uri_and_encoding_rejection(self):
        for value in ("file:///etc/passwd", "intent://example.com", "javascript:alert(1)", "//example.com/x",
                      "https:///x", "https://", "https://u:p@example.com", "https://@example.com",
                      "https://example.com@evil.test", "https://%65xample.com/", "https://x%40y/",
                      "https://bücher.example/", "https://a_b.example/", "https://-bad.example/",
                      "https://bad-.example/", "https://a..b/", "https://example.com:/", "https://example.com:0/",
                      "https://example.com:65536/", "https://example.com:+80/", "https://example.com:no/",
                      "https://[broken]/", "https://[fe80::1%25wlan0]/", "http://127.1/", "http://0177.0.0.1/",
                      "http://2130706433/", "http://0x7f000001/", "http://999.1.1.1/", "https://example.123/",
                      " https://example.com", "https://example.com/ ", "https://example.com/\n",
                      "https://example.com/\0", "https://example.com/\u0085", "https://example.com/\u202e",
                      "https://example.com/\\evil", "https://example.com/%0a", "https://example.com/%0D",
                      "https://example.com/%00", "https://example.com/%7f", "https://example.com/%C2%85",
                      "https://example.com/%E2%80%AE", "https://example.com/%5c", "https://example.com/%",
                      "https://example.com/%gg", "https://example.com/%C0%AF", "https://example.com/%ED%A0%80",
                      "https://example.com/%E9", "https://example.com/\ud800", "https://example.com/{bad}",
                      "https://example.com/" + "a" * 8192, "https://example.com/" + "é" * 1500):
            with self.subTest(value=value), self.assertRaises(opener.OpenError):
                opener.validate_url(value)

    def test_uid_prefers_dedicated_android_identity(self):
        self.assertEqual(opener.target_uid({"FOLDGPT_URL_UID": "10345", "FOLDGPT_IME_UID": "10346"}), 10345)
        self.assertEqual(opener.target_uid({"FOLDGPT_IME_UID": "10346"}), 10346)
        for value in ("0", "-1", " 10345", "10345\n", "2147483648", "", "1.5"):
            with self.assertRaises(opener.OpenError):
                opener.target_uid({"FOLDGPT_URL_UID": value, "FOLDGPT_IME_UID": "10346"})

    def test_failure_never_falls_back_or_logs_the_url(self):
        def refuse(_url, _uid):
            raise opener.OpenError("not_visible")
        output = io.StringIO()
        with contextlib.redirect_stderr(output), patch.object(opener.os, "execve") as fallback:
            result = opener.main(["https://example.com/?code=PRIVATE_TEST_VALUE"],
                                 environment={"FOLDGPT_URL_UID": "10345"}, opener=refuse)
        self.assertEqual(result, 1)
        self.assertNotIn("PRIVATE_TEST_VALUE", output.getvalue())
        fallback.assert_not_called()

    def test_other_types_execute_original_opener_with_literal_arguments(self):
        class Executed(Exception): pass
        observed = []
        def execute(path, args, env):
            observed.append((path, args, env))
            raise Executed()
        with tempfile.TemporaryDirectory() as task_dir:
            binary = Path(task_dir) / "xdg-open"
            binary.write_text("fixture")
            binary.chmod(0o700)
            for args in (["file:///tmp/a%20b.pdf"], ["mailto:user@example.com"], ["--help"], ["/tmp/a;touch nope"]):
                with self.assertRaises(Executed):
                    opener.main(args, environment={}, fallback=str(binary), execve=execute)
                self.assertEqual(observed[-1][1], [str(binary), *args])
                self.assertEqual(observed[-1][2]["FOLDGPT_OPEN_FALLBACK"], "1")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(opener.main(["/tmp/a"], environment={"FOLDGPT_OPEN_FALLBACK": "1"},
                                            fallback=str(binary), execve=execute), 1)
                self.assertEqual(opener.main(["/tmp/a"], environment={}, fallback=str(binary),
                                            execve=lambda *_: None), 1)


@unittest.skipUnless(hasattr(socket, "SO_PEERCRED") and os.name == "posix", "Requires Linux abstract sockets")
class SocketTests(unittest.TestCase):
    def exchange(self, reply, *, timeout=1.0, hold=False):
        uid = os.getuid()
        ready = threading.Event()
        release = threading.Event()
        seen = []
        errors = []
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind("\0foldgpt-url-" + str(uid))
        server.listen(1)
        def serve():
            try:
                ready.set()
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(2)
                    seen.append(connection.recv(16385))
                    if hold:
                        release.wait(2)
                    else:
                        connection.sendall(reply)
            except OSError as error:
                errors.append(error)
        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        ready.wait(2)
        try:
            opener.open_web_url("https://example.com/?code=fixture", uid, timeout=timeout)
        finally:
            release.set()
            server.close()
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertFalse(errors)
            self.assertEqual(json.loads(seen[0]), {"url": "https://example.com/?code=fixture"})

    def test_actual_kernel_peer_credentials_and_acknowledgement(self):
        # Local fixture acknowledges the transport; this test opens no Activity.
        self.exchange(b'{"accepted":true}\n')

    def test_refusal_timeout_and_malformed_reply_fail_honestly(self):
        for response, reason in ((b'{"accepted":false,"error":"not_visible"}\n', "not_visible"),
                                 (b'{"accepted":true,"accepted":false}\n', "invalid_response"),
                                 (b'{"accepted":true,"extra":1}\n', "invalid_response"),
                                 (b'{"accepted":"true"}\n', "invalid_response"),
                                 (b'{"accepted":true}\n{}', "invalid_response"),
                                 (b'{"accepted":true}', "invalid_response"),
                                 (b'\xff\n', "invalid_response"), (b'x' * 257, "invalid_response")):
            with self.subTest(response=response), self.assertRaisesRegex(opener.OpenError, "^" + reason + "$"):
                self.exchange(response)
        with self.assertRaisesRegex(opener.OpenError, "^timeout$"):
            self.exchange(b"", timeout=.1, hold=True)

    def test_missing_endpoint_is_a_failure(self):
        # Test runs sequentially and all fixtures above close this abstract name.
        with self.assertRaisesRegex(opener.OpenError, "^unavailable$"):
            opener.open_web_url("https://example.com", os.getuid(), timeout=.1)

    def test_wrong_peer_is_rejected_before_any_url_is_sent(self):
        class WrongPeer:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def settimeout(self, _): pass
            def connect(self, _): pass
            def getsockopt(self, *_): return struct.pack("3i", 1, 999, 999)
            def sendall(self, _): raise AssertionError("URL sent to wrong UID")
        with self.assertRaisesRegex(opener.OpenError, "^unauthorized$"):
            opener.open_web_url("https://example.com", 1000, socket_factory=lambda *_: WrongPeer())


if __name__ == "__main__":
    unittest.main()
