"""Check ARM64 GNU imports against the preserved libraries collected from Fold.

Only readelf executes, on the PC. This proves static linking compatibility with
those exact collected files; it does not execute or qualify the phone runtime.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect(path, readelf):
    def read(*options):
        return subprocess.check_output([readelf, *options, str(path)], text=True)
    header = read("--file-header", "--program-headers", "--wide")
    if not re.search(r"Machine:\s+AArch64\b", header) or not re.search(r"Class:\s+ELF64\b", header):
        raise RuntimeError(f"Wrong ELF architecture: {path}")
    interpreter = re.search(r"Requesting program interpreter: ([^\]]+)", header)
    dynamic = read("--dynamic", "--wide")
    symbols = read("--dyn-syms", "--wide")
    imports, exports = [], []
    for line in symbols.splitlines():
        fields = line.split()
        if len(fields) < 8 or not fields[0].rstrip(":").isdigit():
            continue
        if fields[4] not in ("GLOBAL", "WEAK", "UNIQUE"):
            continue
        name, _, version = fields[7].partition("@")
        entry = {"name": name, "version": version.lstrip("@") or None,
                 "default": "@@" in fields[7], "weak": fields[4] == "WEAK"}
        if fields[6] == "UND":
            imports.append(entry)
        elif fields[5] in ("DEFAULT", "PROTECTED"):
            exports.append(entry)
    return {
        "path": str(path), "sha256": digest(path), "bytes": path.stat().st_size,
        "interpreter": interpreter.group(1) if interpreter else None,
        "needed": re.findall(r"\(NEEDED\).*Shared library: \[([^\]]+)\]", dynamic),
        "imports": imports, "exports": exports,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binaries", required=True, type=Path)
    parser.add_argument("--libraries", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--readelf", default="aarch64-linux-gnu-readelf")
    args = parser.parse_args()
    readelf = shutil.which(args.readelf)
    if not readelf:
        parser.error("ARM64 readelf is unavailable")
    collected = json.loads((args.libraries / "collection.json").read_text())
    libraries = {}
    for record in collected["files"]:
        name = Path(record["path"]).name
        path = args.libraries / name
        if record["returncode"] != 0 or digest(path) != record["sha256"] or path.stat().st_size != record["bytes"]:
            raise RuntimeError(f"Collected phone library identity mismatch: {name}")
        libraries[name] = inspect(path, readelf)
    observations = []
    for name in ("codex", "codex-code-mode-host"):
        binary = inspect(args.binaries / name, readelf)
        if binary["interpreter"] != "/lib/ld-linux-aarch64.so.1":
            raise RuntimeError(f"Unexpected interpreter in {name}: {binary['interpreter']}")
        closure = {}
        pending = list(binary["needed"])
        missing = []
        while pending:
            dependency = pending.pop()
            if dependency in closure or dependency in missing:
                continue
            if dependency not in libraries:
                missing.append(dependency)
                continue
            closure[dependency] = libraries[dependency]
            pending.extend(libraries[dependency]["needed"])
        definitions = [symbol for obj in [binary, *closure.values()] for symbol in obj["exports"]]
        unresolved, weak = [], []
        for provider, obj in [(name, binary), *closure.items()]:
            for symbol in obj["imports"]:
                resolved = any(export["name"] == symbol["name"] and (
                    export["version"] == symbol["version"] if symbol["version"] else
                    export["version"] is None or export["default"])
                    for export in definitions)
                if not resolved:
                    (weak if symbol["weak"] else unresolved).append({"object": provider, **symbol})
        observations.append({"binary": name, "sha256": binary["sha256"],
            "bytes": binary["bytes"], "interpreter": binary["interpreter"],
            "dependencies": sorted(closure), "missingLibraries": missing,
            "unresolvedStrongImports": unresolved, "unresolvedWeakImports": weak,
            "requiredVersions": sorted({s["version"] for s in binary["imports"] if s["version"]}),
            "passed": not missing and not unresolved})
    result = {"scope": "PC static inspection against exact historical Fold library collection",
        "androidExecution": False, "runtimeQualified": False,
        "method": "readelf dynamic closure and named/versioned dynamic imports; weak absence recorded",
        "libraries": {name: {key: value for key, value in obj.items() if key not in ("imports", "exports")}
                      for name, obj in libraries.items()},
        "binaries": observations, "passed": all(record["passed"] for record in observations)}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": result["passed"], "report": str(args.output)}))
    if not result["passed"]:
        raise SystemExit("Static compatibility check failed; details retained")


if __name__ == "__main__":
    main()
