"""Reject an unsupported static PIE before an Android qualification deployment."""
import hashlib
import json
from pathlib import Path
import struct
import sys


def check(path):
    data = path.read_bytes()
    assert data[:7] == b"\x7fELF\x02\x01\x01", "ELF64 little endian required"
    header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    kind, architecture, _, entry, offset = header[:5]
    stride, count = header[8:10]
    assert kind == 3 and architecture == 183 and entry, "AArch64 PIE required"
    assert stride == 56 and 1 <= count <= 64, "invalid program headers"
    segments = [struct.unpack_from("<IIQQQQQQ", data, offset + i * stride)
                for i in range(count)]
    interpreters = [segment for segment in segments if segment[0] == 3]
    assert len(interpreters) == 1, (
        "Exactly one Android PT_INTERP required: NDK Bionic static PIE startup "
        "does not relocate its own image")
    interpreter = interpreters[0]
    assert data[interpreter[2]:interpreter[2] + interpreter[5]] == b"/system/bin/linker64\0", (
        "unsupported Android interpreter")
    loads = [segment for segment in segments if segment[0] == 1]
    assert loads and all(segment[7] == 16384 for segment in loads), "16 KiB LOAD alignment required"
    assert all(segment[1] & 3 != 3 for segment in loads), "writable executable segment"
    assert any(segment[0] == 0x6474E552 for segment in segments), "RELRO required"
    stacks = [segment for segment in segments if segment[0] == 0x6474E551]
    assert len(stacks) == 1 and not stacks[0][1] & 1, "NX stack required"
    dynamics = [segment for segment in segments if segment[0] == 2]
    assert len(dynamics) == 1, "dynamic section required"
    dynamic = dynamics[0]
    values = []
    for position in range(dynamic[2], dynamic[2] + dynamic[5], 16):
        tag, value = struct.unpack_from("<QQ", data, position)
        if not tag:
            break
        values.append((tag, value))
    tags = dict(values)
    assert tags.get(30, 0) & 8, "immediate binding required"
    assert tags.get(0x6FFFFFFB, 0) & 0x8000000, "PIE flag required"
    assert 15 not in tags and 29 not in tags, "guard must use the system loader search"
    address = tags[5]
    strings = next(segment[2] + address - segment[3] for segment in loads
                   if segment[3] <= address < segment[3] + segment[5])
    needed = []
    for tag, value in values:
        if tag == 1:
            start = strings + value
            needed.append(data[start:data.index(b"\0", start)].decode("ascii"))
    assert "libc.so" in needed and set(needed) <= {"libc.so", "libdl.so"}, needed
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "architecture": "aarch64", "interpreter": "/system/bin/linker64",
            "needed": needed, "pie": True, "relro_now": True, "nx_stack": True,
            "load_alignment": 16384}


if __name__ == "__main__":
    print(json.dumps(check(Path(sys.argv[1])), indent=2))
