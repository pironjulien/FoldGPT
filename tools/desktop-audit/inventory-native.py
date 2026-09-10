"""Static ELF inventory of an extracted desktop package; never execute package code.

All proprietary dumps and generated data remain in this project's ignored work
directory. Extraction inventory, ELF bytes and analysis-tool hashes are recorded.
Windows extended paths are required: ordinary is_file silently misses long names.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import gzip
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "foldgpt.desktop-native-inventory.v1"
SYMBOL_GROUPS = {
    "process_and_identity": r"(?:fork|vfork|execv(?:e|p|pe)?|execl(?:p|e)?|posix_spawn(?:p)?|wait(?:pid|id|4)?|kill|tgkill|raise|prctl|ptrace|clone|clone3|unshare|setns|chroot|set(?:res|re|e)?[ug]id|pidfd_.*|syscall)",
    "terminal": r"(?:forkpty|openpty|posix_openpt|grantpt|unlockpt|ptsname(?:_r)?|tc(?:get|set)attr|tc(?:get|set)pgrp|tcflush|tcsendbreak|cf(?:get|set)[io]speed|setsid|setpgid|ioctl)",
    "filesystem_and_locks": r"(?:open(?:at|64|at64)?|stat(?:x|64)?|[lf]stat(?:at|64|at64)?|__.*stat.*|mkdir(?:at)?|rename(?:at|at2)?|unlink(?:at)?|rmdir|readlink(?:at)?|symlink(?:at)?|link(?:at)?|fcntl(?:64)?|flock|f(?:data)?sync|truncate(?:64)?|ftruncate(?:64)?|chmod|fchmod(?:at)?|chown|fchown(?:at)?|pread(?:64)?|pwrite(?:64)?|getdents(?:64)?|getrandom|realpath|readv|writev)",
    "file_watchers": r"(?:inotify_.*|fanotify_.*|kqueue|kevent)",
    "sockets_and_events": r"(?:socket(?:pair)?|bind|connect|listen|accept(?:4)?|send(?:msg|mmsg|to)?|recv(?:msg|mmsg|from)?|get(?:peer|sock)name|[sg]etsockopt|epoll_.*|eventfd(?:_read|_write)?|timerfd_.*|poll|ppoll|select|pselect|pipe(?:2)?|shutdown)",
    "memory_and_threads": r"(?:mmap(?:64)?|munmap|mremap|mprotect|madvise|mlock|memfd_create|shm_.*|pthread_.*|sem_.*|dlopen|dlsym|dlclose|dlerror|dl_iterate_phdr)",
    "desktop_services": r"(?:dbus_.*|g_bus_.*|g_dbus_.*|g_settings_.*|g_application_.*|gtk_.*|gdk_.*|atk_.*|atspi_.*|cups.*|snd_.*|pa_.*|udev_.*|libusb_.*|X(?!ML_)[A-Z].*|Xkb.*|xcb_.*|wl_.*|gbm_.*|drm.*|egl.*|vk.*)",
    "sandbox_wrappers": r"(?:seccomp.*|landlock.*|cap_(?:get|set)_.*|capget|capset|setns|unshare|prctl|ptrace)",
}
SYMBOL_PATTERNS = {key: re.compile("^(?:" + pattern + ")$") for key, pattern in SYMBOL_GROUPS.items()}
STRINGS_OF_INTEREST = re.compile(
    rb"(?:/(?:proc|sys|dev|run)/|DBUS_SESSION_BUS_ADDRESS|XDG_RUNTIME_DIR|WAYLAND_DISPLAY|DISPLAY|"
    rb"--no-sandbox|--disable-setuid-sandbox|--disable-gpu-sandbox|bwrap|bubblewrap|CLONE_NEWUSER|"
    rb"CLONE_NEWPID|landlock_|pidfd_|user_namespaces|org\.freedesktop\.|xdg-open|xdg-mime)")


def extended(path):
    path = Path(path)
    return Path("\\\\?\\" + str(path.resolve())) if os.name == "nt" and not str(path).startswith("\\\\?\\") else path


def digest(path):
    with extended(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load(path):
    return json.loads(extended(path).read_bytes())


def safe_relative(value):
    if (not isinstance(value, str) or not value or value.startswith("/") or "\\" in value or ":" in value
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise ValueError("Unadmitted inventory path")
    return PurePosixPath(value)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scan_strings(path, limit=128):
    """Bounded literal evidence only; a string is not an executed system call."""
    found = set()
    grouped = defaultdict(set)
    carry = b""
    with extended(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            data = carry + chunk
            # Retain only a bounded printable tail for literals crossing blocks.
            end = len(data)
            lower = max(0, end - 4096)
            while end > lower and 32 <= data[end - 1] < 127:
                end -= 1
            carry = data[end:]
            for match in STRINGS_OF_INTEREST.finditer(data):
                start = match.start()
                while start > max(0, match.start() - 80) and 32 <= data[start - 1] < 127:
                    start -= 1
                end = match.end()
                while end < min(len(data), match.end() + 100) and 32 <= data[end] < 127:
                    end += 1
                literal = data[start:end].decode("ascii", errors="replace")
                found.add(literal)
                grouped[match.group().decode("ascii")].add(literal)
    ordered = sorted(found)
    return {"matches": ordered[:limit], "uniqueMatchCount": len(ordered), "truncated": len(ordered) > limit,
            "tokenMatches": {token: {"examples": sorted(values)[:16], "count": len(values)} for token, values in sorted(grouped.items())}}


def abi_summary(needed, versions, interpreter):
    if any(value.startswith("GLIBC_") for value in versions) or "libc.so.6" in needed:
        return "gnu-glibc"
    if interpreter and "ld-musl-" in interpreter or any("musl" in name for name in needed):
        return "musl"
    if "libc.so" in needed and ("libdl.so" in needed or "libm.so" in needed):
        return "android-bionic-convention"
    if not needed and not interpreter:
        return "static-elf-libc-unidentified"
    return "unresolved-static-abi"


def numeric_max(versions, family):
    selected = [value for value in versions if re.fullmatch(re.escape(family) + r"[0-9]+(?:\.[0-9]+)*", value)]
    return max(selected, key=lambda value: tuple(map(int, value[len(family):].split(".")))) if selected else None


def package_identity(package, relative, asar):
    paths = [package / relative]
    for prefix in ("usr/lib/chatgpt/resources/app.asar.unpacked/", "resources/app.asar.unpacked/"):
        if asar and str(relative).startswith(prefix):
            paths.append(asar / str(relative)[len(prefix):])
    for origin in paths:
        for parent in origin.parents:
            if parent == package.parent or asar and parent == asar.parent:
                break
            candidate = parent / "package.json"
            if extended(candidate).is_file():
                value = load(candidate)
                return {"name": value.get("name"), "version": value.get("version"),
                        "manifest": str(candidate.relative_to(ROOT)).replace("\\", "/"), "manifestSha256": digest(candidate)}
    return None


def inspect(path, row, reader, output, index, package, asar):
    before = extended(path).stat()
    expected = row["sha256"]
    if digest(path) != expected or before.st_size != row["bytes"]:
        raise ValueError("Extracted ELF differs from inventory: " + row["path"])
    command = [str(reader), "--elf-output-style=JSON", "--file-header", "--program-headers", "--dynamic-table", "--dyn-syms", "--version-info", str(extended(path))]
    result = subprocess.run(command, capture_output=True, timeout=120)
    stem = f"{index:03d}-{expected[:16]}"
    raw = output / "raw" / (stem + ".json")
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(result.stdout)
    (output / "raw" / (stem + ".stderr")).write_bytes(result.stderr)
    result.check_returncode()
    decoded = json.loads(result.stdout)
    if len(decoded) != 1:
        raise ValueError("Unexpected readelf result count")
    value = decoded[0]
    header = value["ElfHeader"]
    needed, soname, search = [], None, {}
    for entry in value.get("DynamicSection", []):
        if entry["Type"] == "NEEDED":
            needed.append(entry["Library"])
        elif entry["Type"] == "SONAME":
            soname = entry["Name"]
        elif entry["Type"] in ("RPATH", "RUNPATH"):
            search[entry["Type"]] = entry
    requirements = {}
    for entry in value.get("VersionRequirements", []):
        dependency = entry["Dependency"]
        requirements[dependency["FileName"]] = [item["Entry"]["Name"] for item in dependency["Entries"]]
    versions = sorted({version for names in requirements.values() for version in names})
    symbols, exports = [], []
    for entry in value.get("DynamicSymbols", []):
        symbol = entry["Symbol"]
        name = symbol["Name"]["Name"]
        if not name:
            continue
        if symbol["Section"]["Name"] == "Undefined":
            symbols.append({"name": name, "binding": symbol["Binding"]["Name"], "type": symbol["Type"]["Name"]})
        elif re.search(r"napi_register_module|node_api_module_get_api_version|node_register_module|sqlite3_(?:open|close)|leveldb_", name):
            exports.append(name)
    symbols.sort(key=lambda symbol: (symbol["name"], symbol["binding"]))
    plain = {symbol["name"].split("@", 1)[0] for symbol in symbols}
    groups = {group: sorted(name for name in plain if pattern.fullmatch(name)) for group, pattern in SYMBOL_PATTERNS.items()}
    full_result = subprocess.run([str(reader), "--symbols", "--wide", str(extended(path))], capture_output=True, timeout=120)
    full_result.check_returncode()
    full_path = output / "raw" / (stem + ".symbols.txt.gz")
    full_path.write_bytes(gzip.compress(full_result.stdout, mtime=0))
    defined_functions = set()
    full_symbol_count = 0
    for line in full_result.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split(None, 7)
        if len(parts) != 8 or not re.fullmatch(r"[0-9]+:", parts[0]):
            continue
        full_symbol_count += 1
        name = parts[7].split()[0].split("@", 1)[0]
        if parts[3] == "FUNC" and parts[6] != "UND" and any(pattern.fullmatch(name) for pattern in SYMBOL_PATTERNS.values()):
            defined_functions.add(name)
    interpreter = None
    loads = []
    with extended(path).open("rb") as stream:
        for entry in value.get("ProgramHeaders", []):
            segment = entry["ProgramHeader"]
            kind = segment["Type"]["Name"]
            if kind == "PT_INTERP":
                if segment["FileSize"] > 4096:
                    raise ValueError("Unbounded ELF interpreter")
                stream.seek(segment["Offset"])
                interpreter = stream.read(segment["FileSize"]).rstrip(b"\0").decode("ascii")
            elif kind == "PT_LOAD":
                loads.append({"alignment": segment["Alignment"], "flags": segment["Flags"]["Value"]})
    literals = scan_strings(path)
    after = extended(path).stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or digest(path) != expected:
        raise ValueError("ELF changed during analysis: " + row["path"])
    return {"path": row["path"], "bytes": before.st_size, "sha256": expected,
            "machine": header["Machine"]["Name"], "elfClass": header["Ident"]["Class"]["Name"],
            "osAbi": header["Ident"]["OS/ABI"]["Name"], "type": header["Type"], "interpreter": interpreter,
            "needed": needed, "soname": soname, "loaderSearch": search, "loadSegments": loads,
            "versionRequirements": requirements, "highestReferencedGlibc": numeric_max(versions, "GLIBC_"),
            "highestReferencedGlibcxx": numeric_max(versions, "GLIBCXX_"),
            "abiEvidence": abi_summary(needed, versions, interpreter),
            "undefinedSymbols": symbols, "structuralImports": groups, "selectedExports": sorted(exports),
            "weakUndefinedSymbols": [symbol["name"] for symbol in symbols if symbol["binding"] == "Weak"],
            "fullSymbolTableRows": full_symbol_count, "definedStructuralFunctions": sorted(defined_functions),
            "rawFullSymbolsGzip": full_path.relative_to(output).as_posix(), "rawFullSymbolsSha256": digest(full_path),
            "napiImportCount": sum(name.startswith("napi_") or name.startswith("node_api_") for name in plain),
            "literals": literals, "nodeModule": row["path"].endswith(".node"),
            "packageIdentity": package_identity(package, PurePosixPath(row["path"]), asar),
            "rawReadelf": raw.relative_to(output).as_posix(), "rawReadelfSha256": digest(raw),
            "readelfWarning": result.stderr.decode("utf-8", errors="replace")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--asar-root", type=Path)
    parser.add_argument("--asar-file", type=Path, help="ASAR collected separately from installed ELF files")
    parser.add_argument("--layout", choices=("debian", "installed"), default="debian")
    parser.add_argument("--installed-asar-receipt", type=Path)
    parser.add_argument("--readelf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package, inventory, provenance, reader, output = [getattr(args, name).resolve() for name in (
        "package_root", "inventory", "provenance", "readelf", "output")]
    for path in (package, inventory, provenance):
        path.relative_to(ROOT)
    output.relative_to(ROOT / "work")
    output.mkdir(parents=True, exist_ok=False)
    asar = args.asar_root.resolve() if args.asar_root else None
    if asar:
        asar.relative_to(ROOT)
    rows = load(inventory)
    if not isinstance(rows, list):
        raise ValueError("Extraction inventory must be an array")
    paths = set()
    candidates = []
    observed_files = 0
    unextracted_non_elf = 0
    for row in rows:
        relative = safe_relative(row["path"])
        if row["path"] in paths:
            raise ValueError("Duplicate inventory path")
        paths.add(row["path"])
        if row["kind"] != "file":
            continue
        path = package / relative
        if not extended(path).exists() and not row["elf"]:
            # The source extractor inventories every archive member but only
            # writes ELF and selected scripts/assets. Missing ELF always fails.
            unextracted_non_elf += 1
            continue
        with extended(path).open("rb") as stream:
            elf = stream.read(4) == b"\x7fELF"
        observed_files += 1
        if elf != row["elf"]:
            raise ValueError("ELF classification differs from extraction inventory")
        if elf:
            candidates.append(row)
    origin = load(provenance)
    if origin.get("nativeElfCount", origin.get("elfCount")) != len(candidates):
        raise ValueError("Provenance ELF count differs")
    app_root = package / "usr/lib/chatgpt" if args.layout == "debian" else package
    asar_path = args.asar_file.resolve() if args.asar_file else app_root / "resources/app.asar"
    asar_path.relative_to(ROOT)
    actual_asar_hash = digest(asar_path)
    if actual_asar_hash != origin["asarSha256"]:
        raise ValueError("Package ASAR does not match extraction provenance")
    if args.layout == "installed" and origin.get("stableAsarDuringCollection") is not True:
        raise ValueError("Installed-file provenance does not declare stable ASAR during collection")
    package_metadata = app_root / "resources/linux-package-metadata.json"
    package_version = load(package_metadata)["version"]
    if origin.get("packageVersion", package_version) != package_version:
        raise ValueError("Package metadata version differs from provenance")
    version = subprocess.run([str(reader), "--version"], capture_output=True, check=True, timeout=20).stdout.decode()
    save(output / "invocation.json", {"argv": __import__("sys").argv, "analyzerSha256": digest(Path(__file__)),
                                     "readelfSha256": digest(reader), "readelfVersion": version})
    entries = []
    for index, row in enumerate(sorted(candidates, key=lambda row: row["path"]), 1):
        entries.append(inspect(package / PurePosixPath(row["path"]), row, reader, output, index, package, asar))
        print(f"ELF {index}/{len(candidates)} {row['path']}", flush=True)
    providers = defaultdict(list)
    for entry in entries:
        for name in {entry["soname"], PurePosixPath(entry["path"]).name} - {None}:
            providers[(entry["machine"], name)].append(entry["path"])
    dependencies = defaultdict(list)
    for entry in entries:
        entry["sameArchitectureBundledCandidates"] = {
            name: providers[(entry["machine"], name)] for name in entry["needed"] if (entry["machine"], name) in providers}
        entry["neededOutsideThisPackage"] = [name for name in entry["needed"] if (entry["machine"], name) not in providers]
        for name in entry["needed"]:
            dependencies[name].append(entry["path"])
    comparison = {"currentPhoneNativeBytesCompared": args.layout == "installed", "sameAsObservedPhoneAsar": None}
    if args.installed_asar_receipt:
        receipt_path = args.installed_asar_receipt.resolve()
        receipt_path.relative_to(ROOT)
        receipt = load(receipt_path)
        if (receipt.get("stableDuringRead") is not True or receipt["beforeSha256"] != receipt["afterSha256"]
                or receipt["beforeSha256"] != receipt["localSha256"]):
            raise ValueError("Phone ASAR receipt is not internally stable")
        comparison.update({"receiptSha256": digest(receipt_path), "observedPhoneAsarSha256": receipt["localSha256"],
                           "sameAsObservedPhoneAsar": actual_asar_hash == receipt["localSha256"]})
    groups = defaultdict(list)
    for entry in entries:
        groups[entry["sha256"]].append(entry["path"])
    summary = {"schema": SCHEMA, "scope": "static ELF dependencies and import/literal evidence; no package execution",
               "packageVersion": package_version, "sourceLayout": args.layout,
               "packageMetadataSha256": digest(package_metadata),
               "packageSha256FromExtraction": origin.get("packageSha256"),
               "sourceArchiveSha256FromExtraction": origin.get("archiveSha256", origin.get("packageSha256")),
               "asarSha256": actual_asar_hash, "extractionInventorySha256": digest(inventory),
               "extractionProvenanceSha256": digest(provenance), "filesMagicChecked": observed_files,
               "unextractedNonElfFiles": unextracted_non_elf,
               "elfCount": len(entries), "nodeModuleCount": sum(entry["nodeModule"] for entry in entries),
               "uniqueElfHashes": len(groups), "architectures": dict(Counter(entry["machine"] for entry in entries)),
               "abiEvidenceCounts": dict(Counter(entry["abiEvidence"] for entry in entries)),
               "phoneComparison": comparison,
               "limits": ["Imports may belong to conditional paths; presence is not execution or mandatory feature use.",
                          "Strings are literal evidence only; syscall(), inline syscalls and dlopen targets are not exhaustively resolved.",
                          "A same-name bundled library is only a candidate; runtime linker resolution is not simulated.",
                          "Every extracted inventory file's magic is checked; every ELF is required and hashed before/after reading.",
                          "ARM64 CPU compatibility does not establish Android/Bionic ABI, device access or confinement.",
                          "A different phone ASAR prevents presenting this package version as the installed current client."],
               "duplicates": [paths for paths in groups.values() if len(paths) > 1], "entries": entries}
    save(output / "native-inventory.json", summary)
    save(output / "dependencies.json", {name: consumers for name, consumers in sorted(dependencies.items())})
    compact = {key: value for key, value in summary.items() if key not in ("entries", "duplicates")}
    save(output / "summary.json", compact)
    metadata_fields = (
        "path", "bytes", "sha256", "machine", "elfClass", "osAbi", "type", "interpreter", "needed", "soname",
        "loaderSearch", "loadSegments", "versionRequirements", "highestReferencedGlibc", "highestReferencedGlibcxx",
        "abiEvidence", "structuralImports", "selectedExports", "napiImportCount", "nodeModule", "packageIdentity",
        "sameArchitectureBundledCandidates", "neededOutsideThisPackage", "fullSymbolTableRows",
        "rawReadelfSha256", "rawFullSymbolsSha256", "readelfWarning")
    metadata = {**compact, "invocation": load(output / "invocation.json"), "duplicates": summary["duplicates"],
                "entries": [{**{key: entry[key] for key in metadata_fields},
                             "undefinedSymbolCount": len(entry["undefinedSymbols"]),
                             "definedStructuralFunctions": entry["definedStructuralFunctions"]}
                            for entry in entries]}
    save(output / "native-metadata.json", metadata)
    print(json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    main()
