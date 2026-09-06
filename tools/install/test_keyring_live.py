"""Real GNOME Keyring integration test, exclusively in a disposable Linux home.

No phone, Android Keystore, account or model request is involved. Requires
gnome-keyring, dbus and python3-secretstorage. Every phase uses a new private bus
and daemon to check persistence across complete restarts, not just memory state.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
HELPER = Path(__file__).with_name("initialize_keyring.py")
PASSWORD = "test-only correct credential é with spaces\n".encode()
WRONG = b"test-only wrong credential"
ITEM = b"test-only persisted item value"
JOURNAL = ".foldgpt-keyring-intent.json"


def load_helper():
    spec = importlib.util.spec_from_file_location("foldgpt_test_initializer", HELPER)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def private_environment(state):
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(state / "home"),
           "XDG_CONFIG_HOME": str(state / "config"), "XDG_CACHE_HOME": str(state / "cache"),
           "XDG_DATA_HOME": str(state / "data"), "XDG_RUNTIME_DIR": str(state / "runtime"),
           "PYTHONDONTWRITEBYTECODE": "1"}
    for key in ("HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_RUNTIME_DIR"):
        Path(env[key]).mkdir(mode=0o700)
    (state / "runtime/control").mkdir(mode=0o700)
    return env


def stop_daemon(daemon):
    daemon.terminate()
    try:
        daemon.wait(timeout=5)
    except subprocess.TimeoutExpired:
        daemon.kill()
        daemon.wait(timeout=5)


def interrupted_helper(pid):
    """Kill this helper after the real Create RPC returns, before alias setting.

    Only the test process gets this fault injection. Production has no crash
    flag, pause hook, fake daemon, or fabricated RPC result.
    """
    from jeepney.low_level import HeaderFields
    helper = load_helper()
    original = helper.PinnedConnection.send_and_get_reply

    def after_reply(self, message):
        member = message.header.fields.get(HeaderFields.member)
        result = original(self, message)
        if member == "CreateWithMasterPassword":
            os._exit(86)
        return result

    helper.PinnedConnection.send_and_get_reply = after_reply
    sys.argv = [str(HELPER), "--expected-daemon-pid", str(pid)]
    raise SystemExit(helper.main())


def worker(phase, foreign_pid=None):
    from secretstorage import dbus_init
    from secretstorage.collection import Collection
    from secretstorage.exceptions import SecretServiceNotAvailableException
    from secretstorage.util import DBusAddressWrapper, open_session, format_secret
    from jeepney.bus_messages import DBus

    state = Path(os.environ["XDG_DATA_HOME"]).parent
    journal = Path(os.environ["XDG_DATA_HOME"]) / JOURNAL
    with (state / (phase + ".daemon.log")).open("wb") as log:
        daemon = subprocess.Popen(["gnome-keyring-daemon", "--foreground", "--components=secrets",
                                   "--control-directory=" + str(state / "runtime/control")],
                                  stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        connection = None
        try:
            connection = dbus_init()
            deadline = time.monotonic() + 10
            while not connection.send_and_get_reply(DBus().NameHasOwner("org.freedesktop.secrets")).body[0]:
                if daemon.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("Private GNOME Keyring daemon did not start")
                time.sleep(0.025)
            service = DBusAddressWrapper("/org/freedesktop/secrets", "org.freedesktop.Secret.Service", connection)

            def provision(password=PASSWORD, success=True, env=None, expected_pid=None, interrupt=False):
                pid = daemon.pid if expected_pid is None else expected_pid
                command = ([sys.executable, str(Path(__file__).resolve()), "--interrupt-helper", str(pid)]
                           if interrupt else [sys.executable, str(HELPER), "--expected-daemon-pid", str(pid)])
                result = subprocess.run(command, input=password, env=env, capture_output=True, timeout=15)
                if (result.returncode != 86 if interrupt else (result.returncode == 0) != success):
                    raise AssertionError("Unexpected keyring initialization result: " + result.stderr.decode())
                if password in result.stdout + result.stderr:
                    raise AssertionError("Credential appeared in helper output")

            if phase == "wrong_bus":
                if foreign_pid is None:
                    raise AssertionError("Expected daemon from the other live bus is required")
                provision(success=False, expected_pid=foreign_pid)
                if journal.exists() or service.call("ReadAlias", "s", "default") != ("/",):
                    raise AssertionError("Wrong bus was modified")
                if [p for p in service.get_property("Collections") if not p.endswith("/session")]:
                    raise AssertionError("Wrong bus acquired a collection")
                print(json.dumps({"phase": phase, "result": "PASS"}), flush=True)
                return

            if phase == "foreign_foldgpt":
                session = open_session(connection)
                internal = DBusAddressWrapper("/org/freedesktop/secrets",
                    "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface", connection)
                path, = internal.call("CreateWithMasterPassword", "a{sv}(oayays)",
                    {"org.freedesktop.Secret.Collection.Label": ("s", "FoldGPT")},
                    format_secret(session, PASSWORD, "text/plain; charset=utf8"))
                collection = Collection(connection, path)
                service.call("SetAlias", "so", "default", path)
                collection.create_item("FoldGPT fixture", {"purpose": "foldgpt-integration-test"}, ITEM)
                DBusAddressWrapper(session.object_path, "org.freedesktop.Secret.Session", connection).call("Close", "")
                snapshot = {p.name: p.read_bytes() for p in (journal.parent / "keyrings").iterdir() if p.is_file()}
                provision(success=False)
                if journal.exists() or collection.is_locked() or collection.get_label() != "FoldGPT":
                    raise AssertionError("Foreign namesake collection was adopted or changed")
                if snapshot != {p.name: p.read_bytes() for p in (journal.parent / "keyrings").iterdir() if p.is_file()}:
                    raise AssertionError("Foreign namesake collection files changed")
            elif phase in ("create", "interrupted_create"):
                provision(interrupt=phase == "interrupted_create")
                paths = [p for p in service.get_property("Collections") if not p.endswith("/session")]
                if len(paths) != 1:
                    raise AssertionError("Creation did not produce exactly one collection")
                path = paths[0]
                collection = Collection(connection, path)
                intent = json.loads(journal.read_text())
                if collection.get_label() != "FoldGPT " + intent["installationId"]:
                    raise AssertionError("Collection label does not match the durable intent")
                if journal.stat().st_mode & 0o077 or journal.stat().st_nlink != 1:
                    raise AssertionError("Installation journal is not private")
                expected_alias = "/" if phase == "interrupted_create" else path
                if service.call("ReadAlias", "s", "default") != (expected_alias,):
                    raise AssertionError("Unexpected alias at creation boundary")
                collection.create_item("FoldGPT fixture", {"purpose": "foldgpt-integration-test"}, ITEM)
                (state / "expected-path").write_text(path)
                (state / "expected-intent").write_bytes(journal.read_bytes())
            else:
                path = (state / "expected-path").read_text()
                collection = Collection(connection, path)
                if not collection.is_locked():
                    raise AssertionError("Collection did not lock across daemon restart")
                if phase in ("wrong_then_resume", "resume_interrupted_create"):
                    provision(WRONG, success=False)
                    if not collection.is_locked():
                        raise AssertionError("Wrong password unlocked the keyring")
                    provision()
                elif phase == "missing_alias":
                    service.call("SetAlias", "so", "default", "/")
                    provision()
                elif phase == "unrelated":
                    # A similarly placed existing keyring must be left alone.
                    provision()
                    previous_label = collection.get_label()
                    collection.set_label("Existing personal collection")
                    provision(success=False)
                    if collection.is_locked() or collection.get_label() != "Existing personal collection":
                        raise AssertionError("Unrelated collection was changed")
                    collection.set_label(previous_label)
                    provision()
                elif phase == "directory_mismatch":
                    provision()
                    other = state / "other-data"
                    other.mkdir(mode=0o700)
                    env = dict(os.environ, XDG_DATA_HOME=str(other))
                    provision(success=False, env=env)
                    if (other / JOURNAL).exists() or collection.is_locked():
                        raise AssertionError("Mismatched data-directory call changed a collection or journal")
                elif phase == "lock_conflict":
                    provision()
                    with (journal.parent / ".foldgpt-keyring-init.lock").open("rb") as lock:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        provision(success=False)
                    if collection.is_locked():
                        raise AssertionError("Conflicting helper mutated the collection")
                elif phase == "two_bus_mismatch":
                    provision()
                    with tempfile.TemporaryDirectory(prefix="foldgpt-keyring-other-bus-") as temporary:
                        other_env = private_environment(Path(temporary))
                        subprocess.run(["dbus-run-session", "--", sys.executable, str(Path(__file__).resolve()),
                                        "--worker", "wrong_bus", str(daemon.pid)],
                                       env=other_env, check=True, timeout=60)
                    if collection.is_locked():
                        raise AssertionError("Other-bus test changed the original collection")
                elif phase == "owner_replacement":
                    helper = load_helper()
                    data_fd = os.open(journal.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                    try:
                        pinned = helper.bind_daemon(connection, daemon.pid, data_fd)
                        stop_daemon(daemon)
                        daemon = subprocess.Popen(["gnome-keyring-daemon", "--foreground", "--components=secrets",
                            "--control-directory=" + str(state / "runtime/control")],
                            stdin=subprocess.DEVNULL, stdout=log, stderr=log)
                        deadline = time.monotonic() + 10
                        while not connection.send_and_get_reply(DBus().NameHasOwner("org.freedesktop.secrets")).body[0]:
                            if daemon.poll() is not None or time.monotonic() >= deadline:
                                raise RuntimeError("Replacement daemon did not start")
                            time.sleep(0.025)
                        owner, = connection.send_and_get_reply(DBus().GetNameOwner("org.freedesktop.secrets")).body
                        if owner == pinned.owner:
                            raise AssertionError("Daemon did not acquire a different unique owner")
                        observed_destinations = []

                        class ObservedConnection:
                            def send_and_get_reply(self, message, **kwargs):
                                from jeepney.low_level import HeaderFields
                                observed_destinations.append(message.header.fields[HeaderFields.destination])
                                return connection.send_and_get_reply(message, **kwargs)

                        pinned.connection = ObservedConnection()
                        try:
                            helper.prepare(bytearray(PASSWORD), pinned, data_fd)
                        except SecretServiceNotAvailableException:
                            pass
                        else:
                            raise AssertionError("Pinned transaction followed a replacement daemon")
                        if observed_destinations != [pinned.owner]:
                            raise AssertionError("Old-owner refusal did not come from the actual pinned RPC")
                        if not collection.is_locked():
                            raise AssertionError("Rejected old-owner transaction changed the new daemon")
                        provision()
                    finally:
                        os.close(data_fd)
                else:
                    raise ValueError("Unknown fixture phase")
                if journal.read_bytes() != (state / "expected-intent").read_bytes():
                    raise AssertionError("Initialization replaced the original durable intent")
            if phase != "interrupted_create" and service.call("ReadAlias", "s", "default") != (path,):
                raise AssertionError("Default collection identity changed")
            items = list(collection.search_items({"purpose": "foldgpt-integration-test"}))
            if len(items) != 1 or items[0].get_secret() != ITEM:
                raise AssertionError("Existing item was not preserved")
            persistent = [p for p in service.get_property("Collections") if not p.endswith("/session")]
            if persistent != [path]:
                raise AssertionError("Unexpected additional persistent collection")
            print(json.dumps({"phase": phase, "result": "PASS"}), flush=True)
        finally:
            if connection is not None:
                connection.close()
            stop_daemon(daemon)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--interrupt-helper":
        interrupted_helper(int(sys.argv[2]))
        return
    if len(sys.argv) in (3, 4) and sys.argv[1] == "--worker":
        worker(sys.argv[2], int(sys.argv[3]) if len(sys.argv) == 4 else None)
        return
    with tempfile.TemporaryDirectory(prefix="foldgpt-keyring-live-") as directory:
        for name, phases in (
                ("ordinary", ("create", "wrong_then_resume", "missing_alias", "unrelated",
                              "directory_mismatch", "lock_conflict", "owner_replacement", "two_bus_mismatch")),
                ("foreign", ("foreign_foldgpt",)),
                ("interrupted", ("interrupted_create", "resume_interrupted_create"))):
            state = Path(directory) / name
            state.mkdir(mode=0o700)
            # Neither the host user bus nor its keyring/control paths are inherited.
            env = private_environment(state)
            for phase in phases:
                subprocess.run(["dbus-run-session", "--", sys.executable, str(Path(__file__).resolve()),
                                "--worker", phase], env=env, check=True, timeout=60)


if __name__ == "__main__":
    main()
