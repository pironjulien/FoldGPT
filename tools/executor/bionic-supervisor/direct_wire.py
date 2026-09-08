"""Sealed ordinary-UID launch intent, separate from managed and human profiles."""
import struct

from .wire import frame, seal

MAGIC = b"FGBD0001"
HEADER = struct.Struct("<8s8Q2I")


def envelope(*, cwd, executable, argv, environment, wall_ms=None, data_bytes=None,
             file_bytes=None, output_bytes=None, uid_tasks=None, cpu_seconds=None,
             descriptors=None, cleanup_grace_ms=5000):
    """Zero numeric fields mean no new resource limit, never an invented limit."""
    if (type(cwd) is not str or not cwd.startswith("/") or type(executable) is not str
            or not executable.startswith("/") or type(argv) not in (list, tuple)
            or not 1 <= len(argv) <= 256 or type(environment) not in (list, tuple)
            or len(environment) > 128):
        raise ValueError("Explicit native cwd, executable, argv and environment required")
    values = (wall_ms, data_bytes, file_bytes, output_bytes, uid_tasks, cpu_seconds,
              descriptors, cleanup_grace_ms)
    if any(value is not None and (type(value) is not int or not 1 <= value < 2**53)
           for value in values) or cleanup_grace_ms is None:
        raise ValueError("Resource limits must be positive integers or None")
    if descriptors is not None and descriptors < 8:
        raise ValueError("At least eight descriptors are required for child setup")
    if any(type(value) is not str or "=" not in value or value.startswith("=")
           for value in environment):
        raise ValueError("Environment must contain explicit nonempty names")
    keys = [value.split("=", 1)[0] for value in environment]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate environment name")
    payload = HEADER.pack(MAGIC, *(value or 0 for value in values), len(argv), len(environment))
    payload += b"".join(frame(value) for value in (cwd, executable, *argv, *environment))
    if len(payload) > 196608:
        raise ValueError("Native launch envelope exceeds its bound")
    return payload
