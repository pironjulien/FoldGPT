"""Exercise native ripgrep admission against a real build and corrupted copies."""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build, output = args.build.resolve(strict=True), args.output.resolve()
    build.relative_to(ROOT)
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    checker = module("ripgrep_checker_test", HERE / "verify-ripgrep-build.py")
    admission = module("ripgrep_admission_test", ROOT / "tools/executor/runas-runtime/ripgrep-admission.py")
    baseline = checker.verify(build)
    fixture = output / "fixture"
    fixture.mkdir()
    shutil.copytree(build / "source", fixture / "source")
    files = {"build.json", *checker.FILES, *(r["path"] for r in baseline["evidence"])}
    files.update(part + "/" + name for part in ("first", "second") for name in checker.FILES)
    for name in sorted(files):
        path = fixture / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(build / name, path)
    record_bytes = (fixture / "build.json").read_bytes()
    outputs, provenance = admission.production_ripgrep(fixture)
    if set(outputs) != set(checker.FILES) or provenance["pcre2Jit"] is not True:
        raise AssertionError("Baseline production admission differs")
    outcomes = [{"case": "actual-build-production-admission", "passed": True}]

    def reject(name, change_record=None, change_file=None):
        record = copy.deepcopy(baseline)
        restored = None
        if change_record: change_record(record)
        if change_file:
            relative, transform = change_file
            path = fixture / relative
            before = path.read_bytes()
            restored = (path, before)
            path.write_bytes(transform(before))
        (fixture / "build.json").write_text(json.dumps(record), encoding="utf-8")
        try:
            admission.production_ripgrep(fixture)
        except (ValueError, FileNotFoundError) as error:
            outcomes.append({"case": name, "passed": True, "rejection": str(error)})
        else:
            raise AssertionError("Corruption was admitted: " + name)
        finally:
            (fixture / "build.json").write_bytes(record_bytes)
            if restored: restored[0].write_bytes(restored[1])

    for field, value in (("api", 34), ("target", "aarch64-unknown-linux-gnu"), ("ndk", "28.0")):
        reject("wrong-toolchain-" + field, lambda r, f=field, v=value: r["toolchain"].__setitem__(f, v))
    reject("jit-disabled", lambda r: r.__setitem__("pcre2Jit", False))
    reject("stale-canonical-recipe", lambda r: r["recipe"][0].__setitem__("sha256", "0" * 64))
    reject("duplicate-recipe-row", lambda r: r["recipe"].append(copy.deepcopy(r["recipe"][0])))
    reject("changed-upstream-source", change_file=("source/sources/ripgrep-15.2.0/build.rs", lambda b: b + b"\n"))
    vendor_relative = "source/vendor/" + json.loads((fixture / "source/source-manifest.json").read_text(encoding="utf-8"))["vendorFiles"][0]["path"]
    reject("changed-vendored-crate", change_file=(vendor_relative, lambda b: b + b"\n"))
    reject("changed-independent-build", change_file=("second/libfoldgpt_rg.so", lambda b: b + b"corruption"))
    reject("changed-shipped-executable", change_file=("libfoldgpt_rg.so", lambda b: b + b"corruption"))
    reject("changed-jit-config", change_file=("first/pcre2/src/config.h", lambda b: b.replace(b"#define SUPPORT_JIT 1", b"#define SUPPORT_JIT 0")))
    reject("changed-static-link-metadata", change_file=("first/pcre2-sys-link.txt", lambda b: b.replace(b"static=pcre2-8", b"dylib=pcre2-8")))
    reject("missing-licence-attestation", lambda r: r["evidence"].remove(next(e for e in r["evidence"] if e["path"] == "ripgrep-notices.txt")))
    # Re-hashing hostile ELF metadata cannot turn an unsupported loader/alignment into a valid binary.
    elf_copy = output / "hostile-elf.so"
    data = bytearray(outputs["libfoldgpt_rg.so"])
    header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    for i in range(header[9]):
        offset = header[4] + i * header[8]
        if struct.unpack_from("<I", data, offset)[0] == 1:
            struct.pack_into("<Q", data, offset + 48, 4096)
            break
    elf_copy.write_bytes(data)
    try: checker.elf(elf_copy)
    except ValueError as error: outcomes.append({"case": "real-elf-4KiB-rejected", "passed": True, "rejection": str(error)})
    else: raise AssertionError("Unsupported actual ELF was accepted")
    report = {"schema": "foldgpt.ripgrep-admission-tests.v1", "passed": True,
              "build": build.relative_to(ROOT).as_posix(), "cases": outcomes,
              "buildManifestSha256": hashlib.sha256((build / "build.json").read_bytes()).hexdigest(),
              "androidExecuted": False}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "tests": len(outcomes), "report": str(output / "report.json")}))

if __name__ == "__main__": main()
