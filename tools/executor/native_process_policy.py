"""Private managed-acquisition policy and native diagnostic driver.

This is not an official process RPC backend. It preserves the full supported
portable policy and evaluates every acquisition from the native supervisor's
copied pathname. The supervisor performs native resolution and FD injection.
One exclusively owned ordinary workspace, fixed cwd, static native executables,
no TTY/network/PRoot, no directory handles or pathname metadata/mutation API.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import selectors
import signal
import socket
import stat
import subprocess
import time

from tools.executor.native_files import NativeFilesBackend
from tools.executor.policy_intent import prepare_policy_intent
from tools.policy.managed_policy import parse_context


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate native control field")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite control value")))


class NativeProcessPolicy:
    def __init__(self, helper, workspace, context, *, session_id="private-session", request_id="private-process",
                 guest_workspace="/workspace", backend=None):
        self.intent = prepare_policy_intent(context, session_id=session_id, request_id=request_id,
                                            method="process/start")
        self.policy = parse_context(self.intent.context_json)
        # A composed executor lends its already pinned/leased filesystem backend
        # while holding that backend's mutation lock for the process lifetime.
        self.owns_backend = backend is None
        self.backend = backend if backend is not None else NativeFilesBackend(helper, workspace, guest_workspace=guest_workspace)
        self.decisions = []
        try:
            if self.policy.cwd != self.backend.mount:
                raise ValueError("The initial native process profile requires its pinned workspace cwd")
            self.backend._inspect(self.policy)
        except BaseException:
            if self.owns_backend:
                os.close(self.backend.root)
                self.backend.closed = True
            raise

    @property
    def root(self):
        return self.backend.root

    def decide(self, message):
        if (type(message) is not dict or set(message) != {"type", "id", "syscall", "flags", "mode", "pathHex", "pid", "pathAddress", "howAddress"}
                or message["type"] != "open" or type(message["pathHex"]) is not str):
            raise ValueError("Invalid native acquisition request")
        for name in ("id", "syscall", "flags", "mode", "pid", "pathAddress", "howAddress"):
            if type(message[name]) is not int or not 0 <= message[name] < 2**64:
                raise ValueError("Invalid native acquisition integer")
        raw = bytes.fromhex(message["pathHex"])
        if not raw or len(raw) >= 4096 or raw.hex() != message["pathHex"]:
            raise ValueError("Invalid copied native pathname")
        path = raw.decode("utf-8", errors="strict")
        parts = tuple(path.split("/"))
        if any(part in ("", ".", "..") or "\0" in part for part in parts):
            raise ValueError("Invalid native relative pathname")
        guest = self.backend.mount.append(parts)
        metadata, directories, _, nodes = self.backend._inspect(self.policy)
        target, parent = nodes.get(parts), directories.get(parts[:-1])
        decision = self.policy.decide_uri(guest.uri)
        flags = message["flags"]
        access = flags & os.O_ACCMODE
        reading = access != os.O_WRONLY
        writing = access != os.O_RDONLY or bool(flags & os.O_TRUNC) or (bool(flags & os.O_CREAT) and target is None)
        allowed = not reading or decision.can_read
        if writing:
            try:
                self.backend._require_write(self.policy, guest, metadata)
                if parts[-1] == ".git":
                    raise PermissionError("gitdir-file creation needs the native alias resolver")
            except PermissionError:
                allowed = False
        if target is not None and not stat.S_ISREG(target.st_mode):
            allowed = False
        response = {"id": message["id"], "allow": int(allowed),
                    "device": target.st_dev if target else 0, "inode": target.st_ino if target else 0,
                    "parentDevice": parent.st_dev if parent else 0, "parentInode": parent.st_ino if parent else 0}
        self.decisions.append({"path": guest.uri, "reading": reading, "writing": writing,
                               "allowed": bool(allowed), "syscall": message["syscall"]})
        return response

    def close(self):
        if self.owns_backend and not self.backend.closed:
            self.backend.closed = True
            os.close(self.backend.root)


@dataclass(frozen=True)
class NativeManagedResult:
    returncode: int
    events: tuple
    stdout: bytes
    stderr: bytes
    decisions: tuple


def run_native_managed(binary, executable, workspace, context, arguments, *, wall_ms=10000,
                       address_space_bytes=256 * 1024 * 1024, output_bytes=1024 * 1024,
                       uid_task_budget=128, cancel_after=None, reply_transform=None):
    """Run a real native process and service only its private policy channel.

    reply_transform is a diagnostic fault injector on the trusted side. It is
    not a worker protocol or production permission override. Completion events
    remain raw evidence; the conformance fixture independently checks them.
    """
    policy = NativeProcessPolicy(binary, workspace, context)
    parent = child = process = None
    selector = selectors.DefaultSelector()
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    events = []
    try:
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        process = subprocess.Popen([str(binary), str(policy.root), str(child.fileno()), str(Path(executable).resolve()),
                                    str(wall_ms), str(address_space_bytes), str(output_bytes), str(uid_task_budget), "--", *arguments],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   pass_fds=(policy.root, child.fileno()), close_fds=True, env={}, bufsize=0)
        child.close()
        parent.setblocking(False)
        selector.register(parent, selectors.EVENT_READ, "control")
        for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        start = time.monotonic()
        deadline = start + wall_ms / 1000 + 8
        cancelled = False
        while selector.get_map():
            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError("Native acquisition supervisor did not finish cleanup")
            if cancel_after is not None and not cancelled and now - start >= cancel_after:
                process.send_signal(signal.SIGTERM)
                cancelled = True
            for key, _ in selector.select(min(0.05, deadline - now)):
                if key.data == "control":
                    data, ancillary, flags, _ = parent.recvmsg(16384)
                    if ancillary or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                        raise ValueError("Unexpected native control descriptors or truncated frame")
                    if not data:
                        selector.unregister(parent)
                        continue
                    message = strict_json(data)
                    if message.get("type") == "open":
                        reply = policy.decide(message)
                        if reply_transform is not None:
                            reply = reply_transform(message, reply)
                        encoded = reply if type(reply) is bytes else json.dumps(reply, separators=(",", ":")).encode()
                        parent.send(encoded)
                    else:
                        events.append(message)
                else:
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                    else:
                        outputs[key.data].extend(data)
                        if sum(map(len, outputs.values())) > output_bytes + 4096:
                            raise ValueError("Native output exceeded the diagnostic contract")
        code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        return NativeManagedResult(code, tuple(events), bytes(outputs["stdout"]), bytes(outputs["stderr"]),
                                   tuple(policy.decisions))
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            # Closing policy transport prevents an abandoned native request
            # from waiting for a decision while cleanup is requested.
            if parent is not None:
                parent.close()
            try:
                process.communicate(timeout=7)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=2)
        selector.close()
        for endpoint in (parent, child):
            if endpoint is not None:
                endpoint.close()
        if process is not None:
            process.stdout.close()
            process.stderr.close()
        policy.close()
