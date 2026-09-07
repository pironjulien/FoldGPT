"""Verify a genuine Android shared library, not the dynamic-PIE executable ABI."""
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
    assert kind == 3 and architecture == 183 and entry == 0, "AArch64 shared library required"
    assert stride == 56 and 1 <= count <= 64, "invalid program headers"
    segments = [struct.unpack_from("<IIQQQQQQ", data, offset + i * stride) for i in range(count)]
    assert not any(segment[0] == 3 for segment in segments), "shared library cannot have PT_INTERP"
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
    assert not tags.get(0x6FFFFFFB, 0) & 0x8000000, "library cannot be marked PIE executable"
    assert 15 not in tags and 29 not in tags and 22 not in tags, "no rpath/runpath/text relocations"
    address = tags[5]
    strings = next(segment[2] + address - segment[3] for segment in loads
                   if segment[3] <= address < segment[3] + segment[5])

    def string(value):
        start = strings + value
        return data[start:data.index(b"\0", start)].decode("ascii")

    needed = [string(value) for tag, value in values if tag == 1]
    assert needed == ["libc.so"], needed
    assert string(tags[14]) == "libfoldgpt_bionic_cwd.so", "stable SONAME required"
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "architecture": "aarch64", "kind": "shared-library", "needed": needed,
            "soname": string(tags[14]), "relro_now": True, "nx_stack": True,
            "load_alignment": 16384, "androidExecution": False}


if __name__ == "__main__":
    print(json.dumps(check(Path(sys.argv[1])), indent=2))
