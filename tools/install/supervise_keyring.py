"""Run fresh keyring preparation in a new, supervised private guest session.

stdin is the installer's original credential pipe. This supervisor never reads
or copies it: initialize_keyring consumes it in this process after the separately
spawned GNOME daemon has acquired its own private bus. No desktop client starts.
"""
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import time

import initialize_keyring as initializer


def private_directory(path):
    """Walk without accepting a symlink at any component of this guest path."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Private guest paths must be absolute")
    cursor = Path("/")
    for part in path.parts[1:]:
        cursor /= part
        info = cursor.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Private guest directory contains a link or non-directory")
    initializer.require_private(path.stat(), directory=True)
    return path


def create_private(parent, name):
    private_directory(parent)
    target = parent / name
    try:
        target.mkdir(mode=0o700)
    except FileExistsError:
        pass
    private_directory(target)
    for path in (target, parent):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return target


def child_death_signal(parent_pid):
    """A supervisor killed before cleanup must not leave a private daemon alive."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "Cannot supervise daemon parent death")
    if os.getppid() != parent_pid:
        os._exit(74)


def spawn(command, env, stdout=subprocess.DEVNULL):
    parent = os.getpid()
    return subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                            stdout=stdout, stderr=subprocess.DEVNULL, close_fds=True,
                            preexec_fn=lambda: child_death_signal(parent))


def stop(process):
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if process.stdout is not None:
        process.stdout.close()


def address_line(bus):
    result = bytearray()
    deadline = time.monotonic() + 10
    with selectors.DefaultSelector() as selection:
        selection.register(bus.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline and bus.poll() is None:
            if not selection.select(max(0, deadline - time.monotonic())):
                break
            value = os.read(bus.stdout.fileno(), 1)
            if not value:
                break
            if value == b"\n":
                return result.decode("ascii")
            result.extend(value)
            if len(result) > 4096:
                raise RuntimeError("Private bus address exceeds limit")
    raise RuntimeError("Private bus did not publish an address")


def sync_data_tree(path):
    """Flush GNOME persistence after the owned daemon has stopped writing."""
    info = path.lstat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("Unsafe private keyring persistence object")
    if stat.S_ISDIR(info.st_mode):
        for child in path.iterdir():
            sync_data_tree(child)
        flags = os.O_DIRECTORY
    elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
        flags = 0
    else:
        raise ValueError("Unexpected object in private keyring persistence")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | flags)
    try:
        actual = os.fstat(fd)
        if (actual.st_dev, actual.st_ino) != (info.st_dev, info.st_ino):
            raise RuntimeError("Keyring persistence inode changed during synchronization")
        os.fsync(fd)
    finally:
        os.close(fd)


def run():
    from secretstorage import dbus_init
    from secretstorage.util import DBusAddressWrapper
    from jeepney.bus_messages import DBus
    home = private_directory(Path(os.environ["HOME"]))
    runtime = private_directory(Path(os.environ["XDG_RUNTIME_DIR"]))
    local = create_private(home, ".local")
    data = create_private(local, "share")
    config = create_private(home, ".config")
    cache = create_private(home, ".cache")
    control = create_private(runtime, "control")
    # Do not inherit a host bus, display, SSH socket or another profile. The
    # daemon's explicit XDG_DATA_HOME is subsequently checked through /proc.
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": str(home),
           "USER": os.environ["USER"], "LOGNAME": os.environ["USER"],
           "XDG_DATA_HOME": str(data), "XDG_RUNTIME_DIR": str(runtime),
           "XDG_CONFIG_HOME": str(config), "XDG_CACHE_HOME": str(cache),
           "PYTHONDONTWRITEBYTECODE": "1"}
    bus = daemon = connection = None
    stage = "private-bus"
    receipt = None
    try:
        socket = runtime / "bus"
        if socket.exists() or socket.is_symlink():
            raise RuntimeError("Private runtime directory already contains a bus")
        bus = spawn(["/usr/bin/dbus-daemon", "--session", "--nofork", "--nopidfile",
                     "--address=unix:path=" + str(socket), "--print-address=1"], env, subprocess.PIPE)
        address = address_line(bus)
        if not address.startswith("unix:path=" + str(socket) + ",guid="):
            raise RuntimeError("Private bus published a different socket")
        env["DBUS_SESSION_BUS_ADDRESS"] = address
        os.environ.clear()
        os.environ.update(env)
        stage = "private-daemon"
        daemon = spawn(["/usr/bin/gnome-keyring-daemon", "--foreground", "--components=secrets",
                        "--control-directory=" + str(control)], env)
        connection = dbus_init()
        deadline = time.monotonic() + 10
        while not connection.send_and_get_reply(DBus().NameHasOwner(initializer.BUS_NAME), timeout=1).body[0]:
            if bus.poll() is not None or daemon.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("Supervised daemon did not acquire its private bus name")
            time.sleep(0.025)
        stage = "verified-initializer"
        # This expected PID is the child just started above, never a discovered
        # owner passed back as its own purported proof of identity.
        sys.argv = [str(Path(initializer.__file__)), "--expected-daemon-pid", str(daemon.pid)]
        with contextlib.redirect_stdout(sys.stderr):
            status = initializer.main()
        if status != 0:
            raise RuntimeError("Keyring initialization did not verify")
        stage = "collection-receipt"
        data_fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            intent = initializer.read_intent(data_fd)
            pinned = initializer.bind_daemon(connection, daemon.pid, data_fd)
            service = DBusAddressWrapper(initializer.SERVICE_PATH, initializer.SERVICE_IFACE, pinned)
            path, = service.call("ReadAlias", "s", "default")
            collection = DBusAddressWrapper(path, initializer.COLLECTION_IFACE, pinned)
            if (intent is None or collection.get_property("Label") != "FoldGPT " + intent["installationId"]
                    or collection.get_property("Locked")
                    or [p for p in service.get_property("Collections") if p != initializer.SESSION_COLLECTION] != [path]):
                raise RuntimeError("Verified collection differs from its journal")
            encoded = (data / initializer.JOURNAL).read_bytes()
            receipt = {"schema": "foldgpt.inactive-keyring.v1", "collection": path,
                       "installationId": intent["installationId"],
                       "dataIdentity": str(intent["dataDevice"]) + ":" + str(intent["dataInode"]),
                       "intentSha256": hashlib.sha256(encoded).hexdigest()}
        finally:
            os.close(data_fd)
        stage = "persistence-sync"
    except Exception as error:
        raise RuntimeError("Inactive keyring preparation failed at " + stage) from error
    finally:
        if connection is not None:
            connection.close()
        try:
            stop(daemon)
        finally:
            stop(bus)
    sync_data_tree(data)
    return receipt


def main():
    def interrupted(signum, frame):
        raise InterruptedError("Private installation process interrupted")
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        receipt = run()
    except Exception:
        # Exception bodies may originate in a Secret Service RPC. Do not copy
        # them, daemon environments or the credential stream into output/logs.
        print("FoldGPT inactive keyring preparation failed", file=sys.stderr, flush=True)
        return 1
    print("FOLDGPT_KEYRING_RECEIPT=" + json.dumps(receipt, sort_keys=True, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
