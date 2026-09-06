"""Static Android ELF/package checks; never executes a target binary."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess


def require(condition, message):
    if not condition:
        raise SystemExit(message)


p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--artifact", type=Path, required=True)
p.add_argument("--ndk", type=Path, required=True)
p.add_argument("--proot", required=True)
p.add_argument("--shmem", required=True)
a = p.parse_args()
readelf = a.ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf"
runtime = a.artifact / "runtime/arm64-v8a"
expected = {"libproot.so", "libproot-loader.so", "libproot-loader32.so", "libtalloc.so", "libandroid-shmem.so"}
require({f.name for f in runtime.iterdir()} == expected, "unexpected native artifact set")
system = {"libc.so", "libm.so", "libdl.so", "liblog.so", "libandroid.so"}
packaged = {"libtalloc.so.2": "libtalloc.so", "libandroid-shmem.so": "libandroid-shmem.so"}
outputs = {}
for path in sorted(runtime.iterdir()):
    data = path.read_bytes()
    require(len(data) >= 64 and data[:4] == b"\x7fELF" and data[5] == 1, f"not little-endian ELF: {path.name}")
    elf_class = data[4]
    is_loader32 = path.name == "libproot-loader32.so"
    require(elf_class == (1 if is_loader32 else 2), f"wrong ELF class: {path.name}")
    header = struct.unpack_from("<HHIQQQIHHHHHH" if elf_class == 2 else "<HHIIIIIHHHHHH", data, 16)
    kind, machine, entry, phoff, phsize, phnum = header[0], header[1], header[3], header[4], header[8], header[9]
    require(machine == (40 if is_loader32 else 183), f"wrong machine: {path.name}")
    loader = path.name.startswith("libproot-loader")
    require(kind == (2 if loader else 3), f"wrong ELF type: {path.name}")
    loads, interpreter, stacks = [], None, []
    for index in range(phnum):
        ph = struct.unpack_from("<IIQQQQQQ" if elf_class == 2 else "<IIIIIIII", data, phoff + index * phsize)
        if elf_class == 2:
            typ, flags, offset, address, _, filesz, memsz, align = ph
        else:
            typ, offset, address, _, filesz, memsz, flags, align = ph
        if typ == 1:
            require(align >= 16384 and offset % 16384 == address % 16384, f"bad 16 KiB segment alignment: {path.name}")
            require(not flags & 1 or not flags & 2, f"writable executable LOAD: {path.name}")
            loads.append({"offset": offset, "vaddr": address, "filesz": filesz, "memsz": memsz, "flags": flags, "align": align})
        elif typ == 3:
            interpreter = data[offset:offset+filesz].rstrip(b"\0").decode()
        elif typ == 0x6474e551:
            stacks.append(flags)
    require(loads and stacks and all(not flags & 1 for flags in stacks), f"missing/non-NX stack: {path.name}")
    if loader or path.name == "libproot.so":
        require(any(segment["vaddr"] <= entry < segment["vaddr"] + segment["memsz"] and segment["flags"] & 1 for segment in loads), f"entrypoint outside executable LOAD: {path.name}")
    require(interpreter == ("/system/bin/linker64" if path.name == "libproot.so" else None), f"unexpected interpreter: {path.name}")
    dynamic = subprocess.check_output([str(readelf), "--dynamic", str(path)], text=True)
    (a.artifact / "build" / (path.name + ".dynamic.txt")).write_text(dynamic)
    needed = re.findall(r"\(NEEDED\).*\[(.*?)\]", dynamic)
    soname = re.findall(r"\(SONAME\).*\[(.*?)\]", dynamic)
    require("(RUNPATH)" not in dynamic and "(RPATH)" not in dynamic, f"embedded runtime path: {path.name}")
    require(all(name in system or name in packaged for name in needed), f"unknown dependency: {path.name}: {needed}")
    if loader:
        require(not needed, f"loader unexpectedly links libc: {path.name}")
    if path.name == "libproot.so":
        require({"libtalloc.so.2", "libandroid-shmem.so"}.issubset(needed), "missing required PRoot libraries")
        require(b"/foldgpt/runtime" in data and a.proot.encode() in data, "missing PRoot build identity/options")
    if path.name == "libtalloc.so":
        require(soname == ["libtalloc.so.2"], "incorrect talloc ABI soname")
    if path.name == "libandroid-shmem.so":
        require(soname == [path.name], "incorrect shmem soname")
    outputs[path.name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "elf_class": elf_class,
                          "machine": machine, "type": kind, "interpreter": interpreter,
                          "needed": needed, "soname": soname, "loads": loads, "non_executable_stack": True}

source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((a.artifact / "sources").iterdir())}
provenance_files = sorted((a.artifact / "build/recipe").glob("*")) + sorted((a.artifact / "notices").glob("*"))
provenance_hashes = {str(path.relative_to(a.artifact)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in provenance_files if path.is_file()}
ndk_archive_hash = (a.artifact / "build/ndk-archive.sha256").read_text().split()[0]
require(ndk_archive_hash == "4abbbcdc842f3d4879206e9695d52709603e52dd68d3c1fff04b3b5e7a308ecf", "unexpected verified NDK archive hash")
manifest = {"status": "cross-compiled and statically verified; Android execution not tested", "api": 30,
            "ndk_revision": "29.0.14206865", "ndk_archive_sha256": ndk_archive_hash,
            "proot_commit": a.proot, "talloc_version": "2.4.3", "android_shmem_version": "0.7", "android_shmem_commit": a.shmem,
            "recipe_reference": "termux/termux-packages@90081438daf30a6b46f6745daff6966dc71cb7bc",
            "required_runtime_alias": {"libtalloc.so.2": "libtalloc.so"}, "sources": source_hashes,
            "recipe_and_notices": provenance_hashes, "artifacts": outputs}
(a.artifact / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("PASS: five real Android ELF outputs; ARM64/ARM32 machines, 16 KiB LOAD alignment, NX stacks, interpreters, SONAMEs and declared dependencies verified. No target execution.")
