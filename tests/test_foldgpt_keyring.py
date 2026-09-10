import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("foldgpt_keyring", ROOT / "foldgpt_keyring.py")
keyring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(keyring)


class FakeService:
    def __init__(self, encrypted=True, exists=True, stays_locked=False):
        self.calls = []
        self.locked = True
        self.exists = exists
        self.stays_locked = stays_locked
        self.session = SimpleNamespace(encrypted=encrypted, object_path="/org/freedesktop/secrets/session/test")

    def address(self, path, interface, connection):
        owner = self

        class Address:
            def call(self, method, signature, *args):
                owner.calls.append((path, method, signature, args))
                if method == "ReadAlias":
                    return ("/org/freedesktop/secrets/collection/default" if owner.exists else "/",)
                if method == "UnlockWithMasterPassword":
                    owner.locked = owner.stays_locked
                return ()

            def get_property(self, prop):
                if prop != "Locked":
                    raise AssertionError("The helper must not read keyring contents")
                return owner.locked

        return Address()

    def unlock(self):
        return keyring.unlock_existing(bytearray(b"test credential"), object(), self.address,
                                       lambda _: self.session,
                                       lambda session, password, kind: (session.object_path, b"iv", b"encrypted", kind))


class KeyringTests(unittest.TestCase):
    def test_unlocks_existing_alias_and_verifies_state(self):
        service = FakeService()
        service.unlock()
        self.assertFalse(service.locked)
        self.assertEqual([call[1] for call in service.calls], ["ReadAlias", "UnlockWithMasterPassword", "Close"])
        self.assertEqual(service.calls[1][2], "o(oayays)")
        self.assertEqual(service.calls[1][3][1][2], b"encrypted")

    def test_missing_alias_never_creates_collection(self):
        service = FakeService(exists=False)
        with self.assertRaises(RuntimeError):
            service.unlock()
        self.assertEqual([call[1] for call in service.calls], ["ReadAlias"])

    def test_plaintext_transport_rejected_before_password_send(self):
        service = FakeService(encrypted=False)
        with self.assertRaises(RuntimeError):
            service.unlock()
        self.assertEqual([call[1] for call in service.calls], ["ReadAlias", "Close"])

    def test_unsuccessful_unlock_is_failure_and_session_closes(self):
        service = FakeService(stays_locked=True)
        with self.assertRaises(RuntimeError):
            service.unlock()
        self.assertEqual(service.calls[-1][1], "Close")

    def test_already_unlocked_does_not_send_credential(self):
        service = FakeService()
        service.locked = False
        service.unlock()
        self.assertEqual([call[1] for call in service.calls], ["ReadAlias"])

    def test_password_preserves_unicode_spaces_and_newlines(self):
        value = "  mot de passe é \n".encode()
        self.assertEqual(keyring.read_password(io.BytesIO(value)), value)

    def test_empty_nul_and_oversized_password_rejected(self):
        for value in (b"", b"a\x00b", b"x" * 8193):
            with self.subTest(length=len(value)), self.assertRaises(ValueError):
                keyring.read_password(io.BytesIO(value))

    def test_failure_does_not_log_exception_payload(self):
        output = io.StringIO()
        with patch.object(keyring.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(b"private-input"))), \
             patch.object(keyring, "read_password", side_effect=RuntimeError("sensitive exception payload")), \
             contextlib.redirect_stderr(output):
            self.assertEqual(keyring.main(), 1)
        self.assertNotIn("sensitive exception payload", output.getvalue())
        self.assertNotIn("private-input", output.getvalue())


if __name__ == "__main__":
    unittest.main()
