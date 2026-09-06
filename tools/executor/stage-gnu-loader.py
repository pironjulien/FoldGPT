"""Stage an intact GNU loader from an authenticated Debian base in debug APK libs.

The expected archive hash must come from the independently authenticated base
descriptor. No phone file, proprietary client, PRoot or isolation shim is used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.sha256) != 64 or any(c not in "0123456789abcdef" for c in args.sha256):
        raise ValueError("Expected authenticated SHA-256")
    name = "usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1"
    data = None
    with args.rootfs.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != args.sha256:
            raise ValueError("Authenticated Debian base hash differs")
        source.seek(0)
        with tarfile.open(fileobj=source, mode="r|gz") as archive:
            for member in archive:
                if member.name.removeprefix("./") != name:
                    continue
                if data is not None or not member.isreg() or not 64 <= member.size <= 4194304:
                    raise ValueError("Ambiguous or invalid GNU loader")
                data = archive.extractfile(member).read()
    if data is None or data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("Missing ELF64 GNU loader")
    header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    if header[0] != 3 or header[1] != 183:
        raise ValueError("Expected AArch64 dynamic GNU loader")
    loads = []
    for index in range(header[9]):
        kind, flags, offset, address, _, size, memory, alignment = struct.unpack_from(
            "<IIQQQQQQ", data, header[4] + index * header[8])
        if kind == 3:
            raise ValueError("GNU loader unexpectedly needs another ELF interpreter")
        if kind == 1:
            if alignment < 16384 or offset % 16384 != address % 16384 or flags & 3 == 3:
                raise ValueError("GNU loader has incompatible LOAD segments")
            loads.append({"flags": flags, "alignment": alignment})
    if not loads:
        raise ValueError("Missing GNU loader LOAD segments")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(json.dumps({"archiveSha256": args.sha256, "member": name,
                      "loaderSha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                      "loads": loads, "scope": "debug APK only; intact Debian GNU loader"}))


if __name__ == "__main__":
    main()
