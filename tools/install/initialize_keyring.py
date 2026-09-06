"""Provision a fresh guest's keyring before starting any client.

Requires a private guest D-Bus session and the actual PID of the GNOME daemon
launched by the installer. The caller must persist the per-installation password
in Android Keystore first and supply the same bytes on stdin after an interrupted
attempt. This tool is not called by the existing runtime and never resets a
master password. The caller must keep other clients out until activation.
"""
import argparse
import ctypes
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time

BUS_NAME = "org.freedesktop.secrets"
SERVICE_PATH = "/org/freedesktop/secrets"
SERVICE_IFACE = "org.freedesktop.Secret.Service"
COLLECTION_IFACE = "org.freedesktop.Secret.Collection"
INTERNAL_IFACE = "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface"
SESSION_COLLECTION = SERVICE_PATH + "/collection/session"
JOURNAL = ".foldgpt-keyring-intent.json"
JOURNAL_SCHEMA = "foldgpt.keyring-intent.v1"
MAX_PASSWORD = 8192


def require_private(info, directory=False):
    if (not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or info.st_uid != os.getuid() or info.st_mode & 0o077
            or (not directory and info.st_nlink != 1)):
        raise ValueError("Unsafe installation data object")


class PinnedConnection:
    """Route all SecretStorage calls, including OpenSession, to one unique owner.

    This preserves SecretStorage's existing crypto implementation without
    changing process-global constants or following a replacement daemon.
    """
    def __init__(self, connection, owner):
        self.connection = connection
        self.owner = owner
        self.deadline = time.monotonic() + 10

    def send_and_get_reply(self, message):
        from jeepney.low_level import HeaderFields
        if message.header.fields.get(HeaderFields.destination) != BUS_NAME:
            raise RuntimeError("Unexpected keyring message destination")
        message.header.fields[HeaderFields.destination] = self.owner
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Keyring transaction deadline expired")
        return self.connection.send_and_get_reply(message, timeout=remaining)


def bind_daemon(connection, expected_pid, data_fd):
    from jeepney.bus_messages import DBus
    from jeepney.wrappers import unwrap_msg

    def query(message):
        return unwrap_msg(connection.send_and_get_reply(message, timeout=5))

    owner, = query(DBus().GetNameOwner(BUS_NAME))
    if not isinstance(owner, str) or not owner.startswith(":"):
        raise RuntimeError("Secret service has no unique bus owner")
    pid, = query(DBus().GetConnectionUnixProcessID(owner))
    if pid != expected_pid or expected_pid <= 0:
        raise RuntimeError("Secret service does not belong to the expected daemon")
    # Failure to inspect the actual daemon is a failed precondition. Never
    # fall back to trusting the data-directory variable of this helper alone.
    with open(f"/proc/{pid}/environ", "rb") as source:
        environment = source.read(1024 * 1024 + 1)
    if len(environment) > 1024 * 1024:
        raise RuntimeError("Unexpected daemon environment size")
    entries = [item.partition(b"=")[2] for item in environment.split(b"\0")
               if item.startswith(b"XDG_DATA_HOME=")]
    if len(entries) != 1 or not entries[0].startswith(b"/"):
        raise RuntimeError("Daemon has no explicit private data directory")
    daemon_data = os.open(entries[0], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        actual, expected = os.fstat(daemon_data), os.fstat(data_fd)
        require_private(actual, directory=True)
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise RuntimeError("Daemon and transaction data directories differ")
    finally:
        os.close(daemon_data)
    if query(DBus().GetNameOwner(BUS_NAME)) != (owner,):
        raise RuntimeError("Secret service owner changed during verification")
    return PinnedConnection(connection, owner)


def read_intent(data_fd):
    try:
        fd = os.open(JOURNAL, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=data_fd)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        require_private(info)
        if not 0 < info.st_size <= 4096:
            raise ValueError("Invalid installation journal size")
        encoded = source.read(4097)
        if len(encoded) != info.st_size:
            raise ValueError("Installation journal changed during read")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate installation journal field")
            result[key] = value
        return result

    intent = json.loads(encoded, object_pairs_hook=unique_keys)
    identity = os.fstat(data_fd)
    if (not isinstance(intent, dict)
            or set(intent) != {"schema", "installationId", "dataDevice", "dataInode"}
            or intent["schema"] != JOURNAL_SCHEMA
            or not isinstance(intent["installationId"], str)
            or re.fullmatch("[0-9a-f]{64}", intent["installationId"]) is None
            or type(intent["dataDevice"]) is not int or type(intent["dataInode"]) is not int
            or (intent["dataDevice"], intent["dataInode"]) != (identity.st_dev, identity.st_ino)):
        raise ValueError("Invalid or displaced installation journal")
    return intent


def create_intent(data_fd):
    identity = os.fstat(data_fd)
    intent = {"schema": JOURNAL_SCHEMA, "installationId": secrets.token_hex(32),
              "dataDevice": identity.st_dev, "dataInode": identity.st_ino}
    encoded = (json.dumps(intent, sort_keys=True) + "\n").encode("ascii")
    temporary = ".foldgpt-keyring-intent." + secrets.token_hex(16) + ".new"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=data_fd)
    try:
        with os.fdopen(fd, "wb") as output:
            require_private(os.fstat(output.fileno()))
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        # Atomic no-replace publication, without Android-forbidden hardlinks.
        rename = ctypes.CDLL(None, use_errno=True).renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(data_fd, os.fsencode(temporary), data_fd, os.fsencode(JOURNAL), 1) != 0:
            raise OSError(ctypes.get_errno(), "Cannot commit installation journal")
        os.fsync(data_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=data_fd)
        except FileNotFoundError:
            pass
    if read_intent(data_fd) != intent:
        raise RuntimeError("Installation journal verification failed")
    return intent


def prepare(password, connection, data_fd):
    from secretstorage.util import DBusAddressWrapper, open_session, format_secret

    def address(path, interface):
        return DBusAddressWrapper(path, interface, connection)

    service = address(SERVICE_PATH, SERVICE_IFACE)
    default, = service.call("ReadAlias", "s", "default")
    paths = [p for p in service.get_property("Collections") if p != SESSION_COLLECTION]
    if len(paths) > 1 or (default != "/" and default not in paths):
        raise RuntimeError("Guest keyring is not a fresh installation")
    intent = read_intent(data_fd)
    if intent is None:
        if paths:
            raise RuntimeError("Existing collection has no installation journal")
        intent = create_intent(data_fd)
    label = "FoldGPT " + intent["installationId"]
    if paths and address(paths[0], COLLECTION_IFACE).get_property("Label") != label:
        raise RuntimeError("Collection does not belong to this installation intent")
    # A previous attempt may have published the journal then failed its
    # directory fsync. Retry must confirm that name's durability before creation.
    os.fsync(data_fd)

    session = open_session(connection)
    try:
        if not session.encrypted:
            raise RuntimeError("Encrypted keyring transport is unavailable")
        secret = format_secret(session, bytes(password), "text/plain; charset=utf8")
        internal = address(SERVICE_PATH, INTERNAL_IFACE)
        if not paths:
            path, = internal.call("CreateWithMasterPassword", "a{sv}(oayays)",
                                  {COLLECTION_IFACE + ".Label": ("s", label)}, secret)
            if not path.startswith(SERVICE_PATH + "/collection/") or path == SESSION_COLLECTION:
                raise RuntimeError("Unexpected collection path")
        else:
            path = paths[0]
        collection = address(path, COLLECTION_IFACE)
        # GNOME skips credential checking on an already-unlocked collection.
        # Only this journal's collection is locked, before any client can run.
        locked, prompt = service.call("Lock", "ao", [path])
        if prompt != "/" or path not in locked or not collection.get_property("Locked"):
            raise RuntimeError("Cannot verify the new collection's credential")
        internal.call("UnlockWithMasterPassword", "o(oayays)", path, secret)
        if collection.get_property("Locked"):
            raise RuntimeError("Collection remains locked")
        current, = service.call("ReadAlias", "s", "default")
        if current not in ("/", path):
            raise RuntimeError("The default alias changed during initialization")
        if current == "/":
            service.call("SetAlias", "so", "default", path)
        current, = service.call("ReadAlias", "s", "default")
        if current != path:
            raise RuntimeError("The default alias was not persisted")
        return path
    finally:
        if session.object_path:
            address(session.object_path, "org.freedesktop.Secret.Session").call("Close", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-daemon-pid", required=True, type=int)
    arguments = parser.parse_args()
    password = bytearray()
    connection = None
    lock = data_fd = None
    status = 1
    try:
        if arguments.expected_daemon_pid <= 0:
            raise ValueError("Invalid daemon PID")
        password = bytearray(sys.stdin.buffer.read(MAX_PASSWORD + 1))
        if not password or len(password) > MAX_PASSWORD or 0 in password:
            raise ValueError("Invalid credential input")
        data = Path(os.environ["XDG_DATA_HOME"])
        if not data.is_absolute():
            raise ValueError("An absolute installation data directory is required")
        data_fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        require_private(os.fstat(data_fd), directory=True)
        lock = os.open(".foldgpt-keyring-init.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                       0o600, dir_fd=data_fd)
        require_private(os.fstat(lock))
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        from secretstorage import dbus_init
        connection = dbus_init()
        pinned = bind_daemon(connection, arguments.expected_daemon_pid, data_fd)
        prepare(password, pinned, data_fd)
        status = 0
    except Exception:
        print("FoldGPT keyring initialization failed; existing credentials were not replaced", file=sys.stderr)
    finally:
        password[:] = b"\0" * len(password)
        if connection is not None:
            try:
                connection.close()
            except Exception:
                print("FoldGPT keyring connection cleanup failed", file=sys.stderr)
                status = 1
        if lock is not None:
            os.close(lock)
        if data_fd is not None:
            os.close(data_fd)
    if status == 0:
        print("FoldGPT fresh keyring prepared", flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
