"""Unlock the existing default GNOME collection using a password on stdin only."""
import sys

MAX_PASSWORD = 8192
SERVICE_PATH = "/org/freedesktop/secrets"
SERVICE_IFACE = "org.freedesktop.Secret.Service"
INTERNAL_IFACE = "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface"


def read_password(stream):
    password = bytearray(stream.read(MAX_PASSWORD + 1))
    if not password or len(password) > MAX_PASSWORD or 0 in password:
        password[:] = b"\0" * len(password)
        raise ValueError("Invalid credential input")
    return password


def unlock_existing(password, connection, address_type, session_opener, secret_formatter):
    service = address_type(SERVICE_PATH, SERVICE_IFACE, connection)
    collection_path, = service.call("ReadAlias", "s", "default")
    if not collection_path.startswith("/org/freedesktop/secrets/collection/"):
        raise RuntimeError("The default keyring does not exist")
    collection = address_type(collection_path, "org.freedesktop.Secret.Collection", connection)
    if not collection.get_property("Locked"):
        return
    session = session_opener(connection)
    try:
        if not session.encrypted:
            raise RuntimeError("Encrypted keyring transport is unavailable")
        secret = secret_formatter(session, bytes(password), "text/plain; charset=utf8")
        internal = address_type(SERVICE_PATH, INTERNAL_IFACE, connection)
        internal.call("UnlockWithMasterPassword", "o(oayays)", collection_path, secret)
        if collection.get_property("Locked"):
            raise RuntimeError("The default keyring remains locked")
    finally:
        if session.object_path:
            address_type(session.object_path, "org.freedesktop.Secret.Session", connection).call("Close", "")


def main():
    password = bytearray()
    connection = None
    status = 1
    try:
        password = read_password(sys.stdin.buffer)
        from secretstorage import dbus_init
        from secretstorage.util import DBusAddressWrapper, open_session, format_secret
        connection = dbus_init()
        unlock_existing(password, connection, DBusAddressWrapper, open_session, format_secret)
        status = 0
    except Exception:
        # D-Bus exception payloads and input data are never included in the journal.
        print("FoldGPT keyring unlock failed; encrypted credential or service needs attention", file=sys.stderr)
    finally:
        password[:] = b"\0" * len(password)
        if connection is not None:
            try:
                connection.close()
            except Exception:
                print("FoldGPT keyring connection cleanup failed", file=sys.stderr)
                status = 1
    if status == 0:
        print("FoldGPT keyring unlocked", flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
