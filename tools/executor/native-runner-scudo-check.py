"""Record and verify allocator geometry from the exact static Android ELF.

This inspects existing DWARF/disassembly; it never executes ARM code or changes
Scudo. Different toolchains/layouts require a new review, not a guessed limit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir()
    expected = {
        "RegionSizeLog": ("external/scudo/config/custom_scudo_config.h", 28),
        "RegionSize": ("external/scudo/standalone/primary64.h", 1 << 28),
        "NumClasses": ("external/scudo/standalone/primary64.h", 33),
    }
    for name, (source, constant) in expected.items():
        result = subprocess.run([str(args.toolchain / "llvm-dwarfdump"), f"--name={name}", str(args.elf)],
                                check=True, capture_output=True, text=True).stdout
        (args.output / f"{name}.dwarf.txt").write_text(result)
        blocks = [block for block in re.split(r"\n(?=0x[0-9a-f]+:)", result) if source in block]
        values = {int(value) for block in blocks for value in re.findall(r"DW_AT_const_value\s+\((\d+)\)", block)}
        if values != {constant}:
            raise SystemExit(f"Allocator geometry changed: {name}={values}; review required")
    symbols = [
        "_ZN5scudo20SizeClassAllocator64INS_13PrimaryConfigINS_19AndroidNormalConfigEEEE4initEi",
        "_ZN5scudo19ReservedMemoryLinux10createImplEmmPKcm",
        "_Z13__init_threadP18pthread_internal_t",
    ]
    for index, symbol in enumerate(symbols):
        disassembly = subprocess.run([str(args.toolchain / "llvm-objdump"), f"--disassemble-symbols={symbol}", str(args.elf)],
                                     check=True, capture_output=True, text=True).stdout
        if f"<{symbol}>:" not in disassembly:
            raise SystemExit("Expected allocator/libc symbol missing; review required")
        (args.output / f"{index}-disassembly.txt").write_text(disassembly)
    report = {"elfSha256": hashlib.sha256(args.elf.read_bytes()).hexdigest(),
              "regionSizeLog": 28, "regionSizeBytes": 1 << 28, "numClasses": 33,
              "primaryReservationBytes": 33 << 28, "fixtureAddressHeadroomBytes": 1 << 28,
              "fixtureAddressSpaceBytes": 34 << 28,
              "scope": "Static NDK geometry; virtual reservation, not resident memory or a device test"}
    (args.output / "geometry.json").write_text(json.dumps(report, indent=2) + "\n")
    print("PASS: exact Android ELF Scudo geometry matches the fixture virtual-address budget")


if __name__ == "__main__":
    main()
