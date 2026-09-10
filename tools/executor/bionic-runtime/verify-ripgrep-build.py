"""Revalidate pinned sources, recipes and both real Android ELF outputs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RECIPES = ["tools/executor/bionic-runtime/" + n for n in (
    "ripgrep-inputs.json", "prepare-ripgrep.py", "build-ripgrep-windows.py",
    "verify-ripgrep-build.py", "pcre2-jit-probe.c")]
RECIPES.append("tools/executor/runas-runtime/ripgrep-admission.py")
FILES = ("libfoldgpt_rg.so", "libfoldgpt_pcre2_jit_probe.so")

def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def contained(parent, relative):
    if not isinstance(relative, str): raise ValueError("Non-string evidence path")
    parts = PurePosixPath(relative)
    if (not relative or parts.is_absolute() or parts.as_posix() != relative
            or ".." in parts.parts or "\\" in relative or ":" in relative):
        raise ValueError("Invalid evidence path")
    result = parent
    for part in parts.parts:
        result = result / part
        if result.is_symlink() or result.is_junction(): raise ValueError("Linked evidence path")
    result.resolve(strict=True).relative_to(parent.resolve(strict=True))
    if not result.is_file(): raise ValueError("Evidence must be a regular file")
    return result

def pinned(parent, row):
    path = contained(parent, row["path"])
    if digest(path) != row["sha256"] or path.stat().st_size != row["bytes"]:
        raise ValueError("Changed attested file: " + str(path))
    return path

def inventory(root):
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.is_junction(): raise ValueError("Linked source")
        if path.is_file(): rows.append({"path": path.relative_to(root).as_posix(),
                                       "bytes": path.stat().st_size, "sha256": digest(path)})
    return rows

def verify_sources(source):
    manifest = json.loads((source / "source-manifest.json").read_text(encoding="utf-8"))
    pins = json.loads((HERE / "ripgrep-inputs.json").read_text(encoding="utf-8"))
    if (manifest.get("schema") != "foldgpt.bionic-ripgrep-prepared.v1" or manifest["pins"] != pins
            or manifest["pinsSha256"] != digest(HERE / "ripgrep-inputs.json")
            or manifest["preparerSha256"] != digest(HERE / "prepare-ripgrep.py")):
        raise ValueError("Prepared inputs do not match current pinned recipe")
    for name in ("ripgrep", "pcre2"):
        if digest(source / "archives" / pins[name]["archive"]) != pins[name]["sha256"]:
            raise ValueError("Upstream archive differs")
        if inventory(source / "sources" / pins[name]["directory"]) != manifest["upstreamFiles"][name]:
            raise ValueError("Upstream source closure differs")
    if inventory(source / "vendor") != manifest["vendorFiles"]:
        raise ValueError("Locked Cargo source closure differs")
    if digest(source / "sources" / pins["ripgrep"]["directory"] / "Cargo.lock") != manifest["cargoLockSha256"]:
        raise ValueError("Upstream Cargo.lock differs")
    return manifest

def elf(path):
    data = path.read_bytes()
    def require(ok, message):
        if not ok: raise ValueError(str(path) + ": " + message)
    require(data[:7] == b"\x7fELF\x02\x01\x01", "ELF64 little endian required")
    h = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    require(h[0] == 3 and h[1] == 183 and h[3] != 0 and h[8] == 56 and 1 <= h[9] <= 64, "AArch64 PIE required")
    segments = [struct.unpack_from("<IIQQQQQQ", data, h[4] + i * h[8]) for i in range(h[9])]
    interp = [s for s in segments if s[0] == 3]
    require(len(interp) == 1 and data[interp[0][2]:interp[0][2] + interp[0][5]] == b"/system/bin/linker64\0", "Android loader required")
    loads = [s for s in segments if s[0] == 1]
    require(bool(loads) and all(s[7] == 16384 and s[1] & 3 != 3 for s in loads), "16KiB and W xor X required")
    require(any(s[0] == 0x6474E552 for s in segments), "RELRO required")
    stacks = [s for s in segments if s[0] == 0x6474E551]
    require(len(stacks) == 1 and not stacks[0][1] & 1, "NX stack required")
    dynamic = [s for s in segments if s[0] == 2]
    require(len(dynamic) == 1, "Dynamic section required")
    values = []
    for offset in range(dynamic[0][2], dynamic[0][2] + dynamic[0][5], 16):
        tag, value = struct.unpack_from("<QQ", data, offset)
        if not tag: break
        values.append((tag, value))
    tags = dict(values)
    require(bool(tags.get(30, 0) & 8) and bool(tags.get(0x6FFFFFFB, 0) & 0x8000000), "Immediate binding and PIE flags required")
    require(15 not in tags and 29 not in tags and 22 not in tags, "No runtime paths or text relocations permitted")
    strings = next(s[2] + tags[5] - s[3] for s in loads if s[3] <= tags[5] < s[3] + s[5])
    needed = [data[strings + value:data.index(b"\0", strings + value)].decode("ascii") for tag, value in values if tag == 1]
    require("libc.so" in needed and set(needed) <= {"libc.so", "libdl.so", "libm.so", "liblog.so"}, "Only Android system dependencies permitted")
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "architecture": "aarch64",
            "interpreter": "/system/bin/linker64", "needed": needed, "pie": True, "relro_now": True,
            "nx_stack": True, "load_alignment": 16384, "runpath": None}

def verify(build):
    build = build.resolve(strict=True)
    build.relative_to(ROOT)
    record = json.loads((build / "build.json").read_text(encoding="utf-8"))
    pins = json.loads((HERE / "ripgrep-inputs.json").read_text(encoding="utf-8"))
    if (record.get("schema") != "foldgpt.bionic-ripgrep-build.v1" or record.get("pins") != pins
            or record.get("reproducible") is not True or record.get("sourceFilesUnchanged") is not True
            or record.get("pcre2Jit") is not True or record.get("pcre2Linkage") != "external-static"
            or record.get("androidExecuted") is not False):
        raise ValueError("Explicit source-attested JIT double build required")
    toolchain = record["toolchain"]
    if (toolchain.get("ndk") != pins["ndkRevision"] or toolchain.get("api") != pins["androidApi"]
            or toolchain.get("target") != pins["target"] or toolchain.get("host") != "windows-x86_64"
            or not toolchain.get("rustc", "").startswith("rustc " + pins["rustToolchain"] + " ")
            or not toolchain.get("cargo", "").startswith("cargo " + pins["rustToolchain"] + " ")):
        raise ValueError("Compiler target/API/version attestation differs")
    manifest = verify_sources(build / "source")
    if digest(build / "source/source-manifest.json") != record["sourceManifestSha256"]:
        raise ValueError("Source manifest changed")
    if len(record["recipe"]) != len(RECIPES) or {r["path"] for r in record["recipe"]} != set(RECIPES):
        raise ValueError("Recipe inventory differs")
    for row in record["recipe"]: pinned(ROOT, row)
    evidence_names = {"commands.json", "ripgrep-notices.txt"}
    for part in ("first", "second"):
        evidence_names.update(part + "/" + name for name in (
            "pcre2/CMakeCache.txt", "pcre2/src/config.h", "pcre2-sys-link.txt", "environment.json", "pkg-config.cmd",
            "prefix/lib/libpcre2-8.a", "prefix/lib/libpcre2-16.a", "prefix/lib/libpcre2-32.a",
            "prefix/lib/pkgconfig/libpcre2-8.pc", "cargo-build.stdout", "cargo-build.stderr"))
    if len(record["evidence"]) != len(evidence_names) or {r["path"] for r in record["evidence"]} != evidence_names:
        raise ValueError("Build evidence inventory differs")
    for row in record["evidence"]: pinned(build, row)
    for part in ("first", "second"):
        config = (build / part / "pcre2/src/config.h").read_text(encoding="utf-8")
        if "#define SUPPORT_JIT 1" not in config or "#define SUPPORT_UNICODE 1" not in config:
            raise ValueError("Actual PCRE2 configuration does not enable JIT and Unicode")
        metadata = (build / part / "pcre2-sys-link.txt").read_text(encoding="utf-8")
        if "cargo:rustc-link-lib=static=pcre2-8" not in metadata:
            raise ValueError("Actual Cargo metadata does not select external static PCRE2")
    if set(record["files"]) != set(FILES): raise ValueError("Build output set differs")
    for name in FILES:
        actual = elf(contained(build, name))
        if actual != record["files"][name]: raise ValueError("Actual ELF differs")
        if record["buildHashes"][name] != [actual["sha256"], actual["sha256"]]:
            raise ValueError("Double build hashes differ")
        for part in ("first", "second"):
            if digest(contained(build, part + "/" + name)) != actual["sha256"]:
                raise ValueError("Independent build output differs")
    if manifest["cargoLockSha256"] != record["cargoLockSha256"]: raise ValueError("Lock attestation differs")
    return record

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    args = parser.parse_args()
    record = verify(args.build)
    print(json.dumps({"passed": True, "files": record["files"], "androidExecuted": False}))
