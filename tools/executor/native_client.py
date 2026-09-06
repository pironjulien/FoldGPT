"""Host-side streaming client for native-runner, not the Codex executor protocol.

This client launches only an explicitly supplied trusted native backend. The
backend, not Python, enforces the manifest. No official sandbox is relabeled or
weakened. Completion requires the native cleanup event and real process exit.
"""
from dataclasses import dataclass
import json
import os
import selectors
import signal
import subprocess
import time


class RunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Output:
    stream: str
    data: bytes


@dataclass(frozen=True)
class Event:
    value: dict


def _strict_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise RunnerError("Duplicate native event field")
        value[key] = item
    return value


def _event(data):
    try:
        value = json.loads(data, object_pairs_hook=_strict_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(RunnerError("Nonfinite native event")))
    except (ValueError, UnicodeError) as error:
        raise RunnerError("Malformed native event") from error
    if type(value) is not dict or value.get("type") not in ("started", "result"):
        raise RunnerError("Unknown native event")
    return value


class NativeRun:
    """One bounded, noninteractive command. Use with a context manager.

    read() returns raw output and native control events; wait() validates the
    final result. A stream ending, an exit code of zero, or a started event on
    its own never qualifies as successful cleanup. Cancellation uses SIGTERM,
    allowing the native supervisor to reap children. A crashed/unresponsive
    supervisor is a failure with unknown descendant state, not a success.
    """
    def __init__(self, executable, manifest):
        if os.name != "posix":
            raise RunnerError("Native runner client requires a POSIX host")
        encoded = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        if len(encoded) > 65536:
            raise RunnerError("Native manifest exceeds client transport limit")
        limits = manifest.get("limits", {})
        wall_ms, output_bytes = limits.get("wallMs"), limits.get("outputBytes")
        if (type(wall_ms) is not int or not 1 <= wall_ms <= 86400000
                or type(output_bytes) is not int or not 1 <= output_bytes <= 64 * 1024 * 1024):
            raise RunnerError("Invalid client wall/output bounds")
        self.output_limit = output_bytes
        self.counts = {"stdout": 0, "stderr": 0}
        self.buffer = bytearray()
        self.started = None
        self.result = None
        self.verified = False
        self.cancelled = False
        self.closed = False
        self.process = None
        self.control = None
        self.selector = selectors.DefaultSelector()
        self.deadline = time.monotonic() + wall_ms / 1000 + 10
        read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
        try:
            self.process = subprocess.Popen(
                [os.fspath(executable), "--result-fd", str(write_fd)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={}, close_fds=True, pass_fds=(write_fd,), bufsize=0,
            )
            os.close(write_fd)
            write_fd = None
            self.control = os.fdopen(read_fd, "rb", buffering=0)
            read_fd = None
            # Sending manifests nonblockingly avoids a stalled/broken backend
            # trapping Python before the wall deadline or cancellation applies.
            self.pending = memoryview(encoded)
            os.set_blocking(self.process.stdin.fileno(), False)
            self.selector.register(self.process.stdin, selectors.EVENT_WRITE, "input")
            for stream, name in ((self.process.stdout, "stdout"), (self.process.stderr, "stderr"), (self.control, "control")):
                os.set_blocking(stream.fileno(), False)
                self.selector.register(stream, selectors.EVENT_READ, name)
        except BaseException:
            self.close()
            raise
        finally:
            if read_fd is not None:
                os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)

    def read(self, timeout=1.0):
        if self.closed:
            raise RunnerError("Native run is closed")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RunnerError("Native supervisor did not complete within its deadline")
        events = []
        for key, _ in self.selector.select(min(max(timeout, 0), remaining)):
            stream, name = key.fileobj, key.data
            if name == "input":
                try:
                    written = os.write(stream.fileno(), self.pending)
                    self.pending = self.pending[written:]
                except BrokenPipeError:
                    self.pending = self.pending[:0]
                if not self.pending:
                    self.selector.unregister(stream)
                    stream.close()
                continue
            chunk = os.read(stream.fileno(), 65536)
            if not chunk:
                self.selector.unregister(stream)
                stream.close()
                if name == "control" and self.buffer:
                    raise RunnerError("Truncated native control event")
                continue
            if name != "control":
                self.counts[name] += len(chunk)
                if sum(self.counts.values()) > self.output_limit:
                    raise RunnerError("Native supervisor exceeded its output limit")
                events.append(Output(name, chunk))
                continue
            self.buffer.extend(chunk)
            if len(self.buffer) > 65536:
                raise RunnerError("Oversized native control event")
            while b"\n" in self.buffer:
                line, _, rest = self.buffer.partition(b"\n")
                self.buffer = bytearray(rest)
                value = _event(line)
                if value["type"] == "started":
                    if (self.started is not None or self.result is not None
                            or set(value) != {"type", "pid", "policy"}
                            or type(value["pid"]) is not int or value["pid"] <= 0
                            or value["policy"] != "landlock-basic-data-v1"):
                        raise RunnerError("Invalid native started event")
                    self.started = value
                else:
                    if self.result is not None:
                        raise RunnerError("Repeated native completion")
                    self.result = value
                events.append(Event(value))
        return events

    def cancel(self):
        if self.process is not None and self.process.poll() is None and not self.cancelled:
            self.cancelled = True
            self.process.send_signal(signal.SIGTERM)
            self.deadline = min(self.deadline, time.monotonic() + 10)

    def wait(self, on_output=None):
        while self.selector.get_map():
            for event in self.read():
                if isinstance(event, Output) and on_output is not None:
                    on_output(event)
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RunnerError("Native process exit missed its deadline")
        try:
            code = self.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise RunnerError("Native process did not exit after closing its pipes") from error
        result = self.result
        if result is None:
            raise RunnerError("Native supervisor exited without a completion event")
        if set(result) != {"type", "outcome", "exitCode", "signal", "stdoutBytes", "stderrBytes", "cleanupComplete", "errorStage", "errno"}:
            raise RunnerError("Unexpected native completion fields")
        if (type(result["stdoutBytes"]) is not int or type(result["stderrBytes"]) is not int
                or result["stdoutBytes"] != self.counts["stdout"] or result["stderrBytes"] != self.counts["stderr"]
                or result["cleanupComplete"] is not True or type(result["errno"]) is not int
                or result["errno"] < 0):
            raise RunnerError("Native cleanup/output evidence is incomplete")
        ordinary_exit = (type(result["exitCode"]) is int and 0 <= result["exitCode"] <= 255
                         and result["signal"] is None)
        signalled_exit = (result["exitCode"] is None and type(result["signal"]) is int
                         and 1 <= result["signal"] < signal.NSIG)
        if result["outcome"] == "exited":
            if (code != 0 or self.started is None or not (ordinary_exit or signalled_exit)
                    or result["errorStage"] is not None or result["errno"] != 0):
                raise RunnerError("Native completion contradicts its process evidence")
        elif result["outcome"] in {"timeout", "output_limit", "cancelled", "setup_error", "cleanup_error"}:
            if code != 1 or (result["outcome"] == "setup_error" and self.started is not None):
                raise RunnerError("Native failure contradicts its process evidence")
        else:
            raise RunnerError("Unknown native completion outcome")
        self.verified = True
        return dict(result)

    def close(self):
        if self.closed:
            return
        if self.process is not None and self.process.poll() is None:
            self.cancel()
            # Drain pipes while the supervisor cancels/reaps; simply waiting
            # here can block its final writes behind an abandoned consumer.
            cleanup_deadline = time.monotonic() + 10
            while self.selector.get_map() and time.monotonic() < cleanup_deadline:
                try:
                    self.read(timeout=0.1)
                except (RunnerError, OSError):
                    break
            try:
                self.process.wait(timeout=max(0.1, cleanup_deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                # This only bounds Python teardown. It cannot certify that a
                # crashed backend cleaned descendants; verified remains false.
                self.process.kill()
                self.process.wait(timeout=2)
        self.closed = True
        for key in list(self.selector.get_map().values()):
            key.fileobj.close()
        self.selector.close()
        if self.process is not None:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr, self.control):
                if stream is not None:
                    stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
