"""Separate sealed human launch envelope; never accepted by the model runner."""
import struct

from .runtime_paths import native_name, require_outside_workspace
from .wire import HEADER, frame, seal

MAGIC = b"FGBH0001"


def envelope(*, workspace, cwd, executable, argv, environment, runtime,
             timeout_ms, output_bytes, data_bytes, file_bytes, uid_tasks,
             cpu_seconds, descriptors):
    workspace, cwd, executable = map(native_name, (workspace, cwd, executable))
    if cwd != "/" and cwd != workspace and not cwd.startswith(workspace + "/"):
        raise ValueError("Host cwd must be / or within its owned workspace")
    if not argv or len(argv) > 256 or len(environment) > 128 or not runtime or len(runtime) > 64:
        raise ValueError("Native host envelope cardinality exceeds its bounds")
    # Zero in this private human schema means absent. Model FGBP0001 still
    # rejects it. No timeout, CPU timer or output truncation is synthesized.
    optional = (timeout_ms, output_bytes, cpu_seconds)
    if any(value is not None and (type(value) is not int or not 1 <= value <= 2**53 - 1)
           for value in optional):
        raise ValueError("Host optional resource allowance requires a positive integer or None")
    bounded = (data_bytes, file_bytes, uid_tasks, descriptors)
    bounds = ((16777216, 2147483648), (1, 1073741824), (1, 128), (16, 1024))
    if any(type(value) is not int or not low <= value <= high
           for value, (low, high) in zip(bounded, bounds)):
        raise ValueError("Host native resources exceed the owner's admitted bounds")
    numeric = (timeout_ms or 0, data_bytes, file_bytes, output_bytes or 0,
               uid_tasks, cpu_seconds or 0, descriptors)
    payload = HEADER.pack(MAGIC, *numeric, len(argv), len(environment), len(runtime))
    payload += frame(workspace) + frame(cwd) + frame(executable)
    payload += b"".join(frame(value) for value in argv)
    payload += b"".join(frame(value) for value in environment)
    for path, execute in runtime:
        if type(execute) is not bool:
            raise ValueError("Host runtime execute flag must be explicit")
        path = native_name(path)
        require_outside_workspace(path, workspace)
        payload += struct.pack("<I", int(execute)) + frame(path)
    if len(payload) > 196608:
        raise ValueError("Host native launch envelope exceeds its bound")
    return payload
