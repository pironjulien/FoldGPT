"""PTY package admission tests over real compiled bytes and explicit fixtures.

Reads the actual r24 APK for backward compatibility. Optional PTY mutations are
in-memory/minimal-stage unit fixtures, not a built or device-qualified APK.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def digest(data): return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--pty-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    apk, build, output = args.apk.resolve(strict=True), args.pty_build.resolve(strict=True), args.output.resolve()
    for path in (apk, build, output): path.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    admit = module("pty_admission_test", "pty-admission.py")
    verify = module("pty_package_verifier_test", "verify-production-apk.py")
    package = module("pty_package_stage_test", "stage-production-package.py")
    binary, proof = admit.production_pty(build)
    name = admit.NAME
    with zipfile.ZipFile(apk) as archive:
        config = json.loads(archive.read("assets/foldgpt-executor-deployment.json"))
        qualification = json.loads(archive.read("assets/foldgpt-executor-qualification.json"))
        runtime = json.loads(archive.read("assets/foldgpt-python-runtime.json"))
        native = {name: archive.read("lib/arm64-v8a/" + name) for name in config["nativeLibraries"]}
        manifest = json.loads(archive.read("assets/foldgpt-executor-manifest.json"))
        source = {row["path"]: archive.read("assets/foldgpt-executor/" + row["path"]) for row in manifest}
    results = []
    def passed(case): results.append({"case": case, "passed": True})
    def reject(case, call):
        try: call()
        except (ValueError, OSError, AssertionError) as error:
            results.append({"case": case, "passed": True, "rejection": str(error)})
        else: raise AssertionError("Invalid package input accepted: " + case)
    if verify.verify_model_selection(config, qualification, native.__getitem__, set(source)) != ["managed", "ordinaryUid"]:
        raise AssertionError("Actual pre-PTY model profiles changed")
    verify.verify_entrypoints(config, qualification, runtime, native.__getitem__)
    passed("actual-r24-model-selection-and-entrypoints")
    base_config = copy.deepcopy(config)
    base_qualification = copy.deepcopy(qualification)

    config["backendOptions"]["ordinaryUid"]["ptyProcessRunner"] = "@nativeLibraryDir/" + name
    config["nativeLibraries"][name] = digest(binary)
    qualification["ordinaryPtyBuild"] = proof
    native[name] = binary
    runtime["nativeFiles"].append({"name": name, "bytes": len(binary), "sha256": digest(binary)})
    for path, expected in proof["runtimeSourceSha256"].items():
        source[path] = (ROOT / path).read_bytes()
        if digest(source[path]) != expected: raise AssertionError("Actual runtime source changed")
    def check(c=None, q=None, n=None, s=None, r=None):
        c, q, n, s, r = (config if c is None else c, qualification if q is None else q,
            native if n is None else n, source if s is None else s, runtime if r is None else r)
        profiles = verify.verify_model_selection(c, q, n.__getitem__, set(s), read_source=s.__getitem__)
        verify.verify_entrypoints(c, q, r, n.__getitem__)
        return profiles
    if check() != ["managed", "ordinaryUid", "ordinaryPty"]: raise AssertionError("PTY fixture selection differs")
    passed("reviewed-pty-bytes-and-complete-python-fixture")
    q = copy.deepcopy(qualification)
    del q["ordinaryPtyBuild"]
    reject("selection-without-pty-provenance", lambda: check(q=q))
    c = copy.deepcopy(config)
    del c["backendOptions"]["ordinaryUid"]["ptyProcessRunner"]
    reject("pty-provenance-without-selection", lambda: check(c=c))
    c = copy.deepcopy(config)
    del c["backendOptions"]["ordinaryUid"]
    reject("pty-without-ordinary-profile", lambda: check(c=c))
    c = copy.deepcopy(config)
    c["backendOptions"]["ordinaryUid"]["ptyProcessRunner"] = "/system/bin/sh"
    reject("external-pty-runner", lambda: check(c=c))
    c = copy.deepcopy(config)
    del c["nativeLibraries"][name]
    reject("pty-selection-without-native-inventory", lambda: check(c=c))
    reject("changed-packaged-pty-elf", lambda: check(n={**native, name: binary + b"changed"}))
    q = copy.deepcopy(qualification)
    q["ordinaryPtyBuild"]["path"] = "../outside"
    reject("pty-provenance-path-traversal", lambda: check(q=q))
    for path in ("tools/executor/bionic-supervisor/tty_processes.py", "tools/executor/bionic-supervisor/direct_processes.py"):
        changed = {**source, path: source[path] + b"\n# modified but rehashed in a package manifest\n"}
        reject("self-rehashed-" + Path(path).name, lambda changed=changed: check(s=changed))
    missing = dict(source)
    del missing["tools/executor/bionic-supervisor/tty_wire.py"]
    reject("missing-pty-wire-source", lambda: check(s=missing))
    reject("source-names-without-byte-verifier", lambda: verify.verify_model_selection(
        config, qualification, native.__getitem__, set(source)))
    for case in ("missing", "duplicate", "changed"):
        r = copy.deepcopy(runtime)
        rows = [row for row in r["nativeFiles"] if row["name"] == name]
        if case == "missing": r["nativeFiles"].remove(rows[0])
        elif case == "duplicate": r["nativeFiles"].append(copy.deepcopy(rows[0]))
        else: rows[0]["sha256"] = "0" * 64
        reject(case + "-pty-runtime-admission-row", lambda r=r: check(r=r))
    reject("runtime-pty-without-selected-profile", lambda: verify.verify_entrypoints(
        base_config, base_qualification, runtime, native.__getitem__))

    frozen = output / "build-fixture"
    shutil.copytree(build, frozen)
    for path in ("repeat.so", "source/tty-runner.c", "headers/pty.h", "python-source-closure.json",
                 "python-closure/tools/executor/bionic-supervisor/direct_processes.py"):
        target = frozen / path
        original = target.read_bytes()
        target.write_bytes(original + b"changed")
        reject("changed-build-evidence-" + path, lambda: admit.production_pty(frozen))
        target.write_bytes(original)
    (frozen / "source/extra.c").write_bytes(b"unexpected")
    reject("extra-frozen-build-source", lambda: admit.production_pty(frozen))

    stage = output / "stage-fixture"
    (stage / "jniLibs/arm64-v8a").mkdir(parents=True)
    (stage / "assets").mkdir()
    (stage / "jniLibs/arm64-v8a" / name).write_bytes(binary)
    (stage / "assets/foldgpt-python-runtime.json").write_text(json.dumps(runtime), encoding="utf-8")
    inventory = {"ordinaryPtyBuild": proof, "files": [{"path": "jniLibs/arm64-v8a/" + name,
                 "bytes": len(binary), "sha256": digest(binary)}]}
    if package.admit_stage_pty(stage, inventory, ordinary_uid=True) != proof:
        raise AssertionError("Exact minimal PTY stage rejected")
    passed("exact-pty-stage-admitted")
    reject("pty-stage-without-ordinary-option", lambda: package.admit_stage_pty(stage, inventory, ordinary_uid=False))
    reject("pty-stage-without-provenance", lambda: package.admit_stage_pty(stage, {"files": inventory["files"]}, ordinary_uid=True))
    reject("pty-stage-without-file-inventory", lambda: package.admit_stage_pty(stage,
        {**inventory, "files": []}, ordinary_uid=True))
    r = copy.deepcopy(runtime)
    r["nativeFiles"] = [row for row in r["nativeFiles"] if row["name"] != name]
    (stage / "assets/foldgpt-python-runtime.json").write_text(json.dumps(r), encoding="utf-8")
    reject("pty-stage-without-runtime-inventory", lambda: package.admit_stage_pty(stage, inventory, ordinary_uid=True))
    empty = output / "empty-stage"
    empty.mkdir()
    if package.admit_stage_pty(empty, {}, ordinary_uid=False) is not None:
        raise AssertionError("Stage without optional PTY changed")
    passed("non-pty-stage-remains-compatible")
    report = {"schema": "foldgpt.pty-packaging-tests.v1", "passed": True,
              "apkSha256": digest(apk.read_bytes()), "candidateSha256": digest(binary),
              "androidExecuted": False, "apkBuilt": False, "optionalPtyUsesUnitFixtures": True,
              "cases": results, "tests": len(results)}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "tests": len(results), "report": str(output / "report.json")}))


if __name__ == "__main__": main()
