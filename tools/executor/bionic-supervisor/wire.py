"""Private sealed bootstrap envelope; never accepts command-owned policy data."""
import struct
from tools.executor.native_processes import _sealed_environment

MAGIC = b"FGBP0001"
HEADER = struct.Struct("<8s7Q3I")


def frame(value):
    data = value.encode("utf-8", errors="strict")
    if b"\0" in data or len(data) > 65536:
        raise ValueError("Native envelope string is outside its bounds")
    return struct.pack("<I", len(data)) + data


def envelope(*, workspace, cwd_relative, executable, argv, environment, runtime,
             wall_ms, data_bytes, file_bytes, output_bytes, uid_tasks, cpu_seconds, descriptors):
    if not argv or len(argv) > 256 or len(environment) > 128 or len(runtime) > 64:
        raise ValueError("Native envelope cardinality is outside its bounds")
    numeric = (wall_ms, data_bytes, file_bytes, output_bytes, uid_tasks, cpu_seconds, descriptors)
    bounds = ((1, 3600000), (16777216, 2147483648), (1, 1073741824),
              (1, 67108864), (1, 128), (1, 3600), (16, 1024))
    if any(type(value) is not int or not low <= value <= high
           for value, (low, high) in zip(numeric, bounds)):
        raise ValueError("Native resource allowance is outside its bounds")
    payload = HEADER.pack(MAGIC, *numeric, len(argv), len(environment), len(runtime))
    payload += frame(workspace) + frame(cwd_relative) + frame(executable)
    payload += b"".join(frame(value) for value in argv)
    payload += b"".join(frame(value) for value in environment)
    for path, execute in runtime:
        if type(execute) is not bool:
            raise ValueError("Explicit runtime execute flag required")
        payload += struct.pack("<I", int(execute)) + frame(path)
    if len(payload) > 196608:
        raise ValueError("Native launch envelope exceeds its bound")
    return payload


def seal(payload):
    # This helper uses actual libc memfd_create/fcntl and NDK-verified Linux
    # constants, also on the host. Android CPython need not expose these names.
    return _sealed_environment(payload)
