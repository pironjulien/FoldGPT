"""Stage authenticated native production inputs without executing Android code."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[3]
RUNTIME_HOME = "/data/user/0/app.foldgpt/files/native-runtime-v1/python"


def pinned(path, expected):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Authenticated input differs: " + str(path))
    return data


def production_bash(build):
    """Admit only the explicit, source-attested production-prefix double build."""
    build = build.resolve(strict=True)
    build.relative_to(ROOT)
    record_bytes = (build / "build.json").read_bytes()
    record = json.loads(record_bytes)
    if (record.get("schema") != "foldgpt.native-bash-build.v1"
            or record.get("androidPrefix") != RUNTIME_HOME
            or record.get("reproducible") is not True
            or record.get("sourceFilesUnchanged") is not True
            or record.get("ndk") != "29.0.14206865" or record.get("apiLevel") != 35):
        raise ValueError("Bash requires an explicit reproducible production-prefix build")
    manifest_bytes = pinned(build / "source/source-manifest.json", record["sourceManifestSha256"])
    manifest = json.loads(manifest_bytes)
    recipe_root = ROOT / "tools/executor/bionic-runtime"
    if (manifest.get("androidPrefix") != RUNTIME_HOME
            or manifest.get("upstream") != json.loads((recipe_root / "bash-inputs.json").read_bytes())
            or manifest.get("sourceDateEpoch") != record.get("sourceDateEpoch")):
        raise ValueError("Bash source manifest does not identify the pinned production sources")

    def contained_file(parent, relative):
        path = PurePosixPath(relative)
        if (not isinstance(relative, str) or not relative or path.is_absolute()
                or path.as_posix() != relative or ".." in path.parts
                or "\\" in relative or ":" in relative):
            raise ValueError("Invalid Bash evidence path")
        target = parent.joinpath(*path.parts)
        for index in range(1, len(path.parts) + 1):
            component = parent.joinpath(*path.parts[:index])
            if component.is_symlink() or component.is_junction():
                raise ValueError("Bash evidence cannot contain path aliases")
        target.resolve(strict=True).relative_to(parent.resolve(strict=True))
        if not target.is_file():
            raise ValueError("Bash evidence must be a regular file")
        return target

    prepared = manifest["preparedFiles"]
    recorded = {row["path"] for row in prepared}
    source = build / "source/bash-5.3"
    actual = {path.relative_to(source).as_posix() for path in source.rglob("*") if path.is_file()}
    if (not prepared or len(recorded) != len(prepared) or actual != recorded
            or record.get("preparedSourceFilesVerified") != len(prepared)):
        raise ValueError("Bash prepared source inventory differs")
    for row in prepared:
        data = pinned(contained_file(source, row["path"]), row["sha256"])
        if len(data) != row["bytes"] or b"/data/local/tmp/foldgpt-shizuku-lab" in data:
            raise ValueError("Bash prepared source length or runtime prefix differs")
    recipe_names = {"build-bash.sh", "prepare-bash.py", "verify-bash-build.py",
                    "shizuku-check-elf.py", "bash-inputs.json"}
    recipe_names.update(path.relative_to(recipe_root).as_posix()
                        for path in (recipe_root / "termux-bash").glob("*.patch"))
    recipes = record["recipe"]
    if len(recipes) != len(recipe_names) or {row["path"] for row in recipes} != recipe_names:
        raise ValueError("Bash build recipe inventory differs")
    for row in recipes:
        pinned(contained_file(recipe_root, row["path"]), row["sha256"])
    pinned(recipe_root / "prepare-bash.py", manifest["preparerSha256"])
    patches = manifest["termuxPatches"]
    patch_names = {path.name for path in (recipe_root / "termux-bash").glob("*.patch")}
    if len(patches) != len(patch_names) or {row["name"] for row in patches} != patch_names:
        raise ValueError("Bash source patch inventory differs")
    for row in patches:
        pinned(contained_file(recipe_root / "termux-bash", row["name"]), row["originalSha256"])
        pinned(contained_file(build / "source", row["name"]), row["configuredSha256"])
    elf = record["elf"]
    expected = elf["sha256"]
    if record.get("buildHashes") != [expected, expected]:
        raise ValueError("Bash double-build hashes do not match its ELF")
    data = pinned(contained_file(build, "libfoldgpt_bash.so"), expected)
    if len(data) != elf["bytes"]:
        raise ValueError("Bash build length differs")
    for relative in ("first/bash", "second/bash"):
        if pinned(contained_file(build, relative), expected) != data:
            raise ValueError("Bash double-build evidence differs")
    if sys.flags.optimize:
        raise ValueError("Bash ELF admission requires normal Python assertions")
    spec = importlib.util.spec_from_file_location("foldgpt_production_bash_elf", recipe_root / "shizuku-check-elf.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    if checker.check(build / "libfoldgpt_bash.so") != elf:
        raise ValueError("Bash actual ELF differs from its build attestation")
    suffixes = ("bin", "bin:.", "etc/profile", "etc/bash.bashrc", "etc/inputrc", "etc/hosts",
                "tmp", "var/tmp", "share/locale", "share/bashdb/bashdb-main.inc")
    if (b"/data/local/tmp/foldgpt-shizuku-lab" in data
            or any((RUNTIME_HOME + "/" + suffix).encode() + b"\0" not in data for suffix in suffixes)):
        raise ValueError("Bash compiled runtime paths differ from production")
    return data, {"path": build.relative_to(ROOT).as_posix(),
                  "buildManifestSha256": hashlib.sha256(record_bytes).hexdigest(),
                  "sourceManifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
                  "executableSha256": expected, "bytes": len(data), "androidPrefix": RUNTIME_HOME}


def production_direct(build):
    """Verify the exact sources and both compiled outputs before APK staging."""
    build = build.resolve(strict=True)
    build.relative_to(ROOT)

    def artifact(relative, *, directory=False):
        parts = PurePosixPath(relative)
        if (parts.is_absolute() or parts.as_posix() != relative or ".." in parts.parts
                or "\\" in relative or ":" in relative):
            raise ValueError("Invalid ordinary UID evidence path")
        target = build
        for component in parts.parts:
            target /= component
            if target.is_symlink() or target.is_junction():
                raise ValueError("Ordinary UID evidence cannot contain path aliases")
        target.resolve(strict=True).relative_to(build)
        if not (target.is_dir() if directory else target.is_file()):
            raise ValueError("Ordinary UID evidence type differs")
        return target

    record_bytes = artifact("build.json").read_bytes()
    record = json.loads(record_bytes)
    if (record.get("schema") != "foldgpt.direct.native.compile.v1"
            or record.get("ndk") != "29.0.14206865" or record.get("apiLevel") != 35):
        raise ValueError("Ordinary UID runner requires the checked NDK r29/API35 build")
    manifest_bytes = pinned(artifact("sources.json"), record["sourceManifestSha256"])
    sources = json.loads(manifest_bytes)
    recipe = ROOT / "tools/executor/bionic-supervisor"
    expected = {name: recipe / name for name in (
        "direct-runner.c", "direct-worker.c", "direct_wire.py", "direct-design.md", "direct-api.md",
        "test_direct_runner.py", "build-direct-windows.py")}
    expected["check-elf.py"] = ROOT / "tools/executor/bionic-runtime/shizuku-check-elf.py"
    if (len(sources) != len(expected) or {row["path"] for row in sources} != set(expected)
            or {p.name for p in artifact("source", directory=True).iterdir()} != set(expected)):
        raise ValueError("Ordinary UID build source inventory differs")
    for row in sources:
        data = pinned(artifact("source/" + row["path"]), row["sha256"])
        if len(data) != row["bytes"] or pinned(expected[row["path"]], row["sha256"]) != data:
            raise ValueError("Ordinary UID compiled sources differ from the current recipe")
    if "Pkg.Revision = 29.0.14206865" not in artifact("ndk-source.properties").read_text().splitlines():
        raise ValueError("Ordinary UID NDK provenance differs")
    binaries = record["binaries"]
    names = {"libfoldgpt_direct_runner.so", "libfoldgpt_direct_worker.so"}
    if len(binaries) != len(names) or {row["path"] for row in binaries} != names:
        raise ValueError("Ordinary UID compiled binary inventory differs")
    if sys.flags.optimize:
        raise ValueError("Ordinary UID ELF admission requires normal Python assertions")
    spec = importlib.util.spec_from_file_location("foldgpt_production_direct_elf", expected["check-elf.py"])
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    runner = None
    for row in binaries:
        binary = artifact(row["path"])
        data = pinned(binary, row["sha256"])
        stem = row["path"][len("libfoldgpt_"):-len(".so")].replace("_", "-")
        if (row.get("realRecompilationIdentical") is not True or len(data) != row["bytes"]
                or pinned(artifact(stem + ".repeat.so"), row["sha256"]) != data):
            raise ValueError("Ordinary UID double-build evidence differs")
        elf = checker.check(binary)
        if elf != json.loads(artifact(stem + ".elf.json").read_bytes()):
            raise ValueError("Ordinary UID actual ELF differs from the recorded inspection")
        if stem == "direct-runner":
            runner = data
    return runner, {"path": build.relative_to(ROOT).as_posix(),
                    "buildManifestSha256": hashlib.sha256(record_bytes).hexdigest(),
                    "sourceManifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
                    "executableSha256": hashlib.sha256(runner).hexdigest(), "bytes": len(runner)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-cli-build", type=Path, required=True)
    parser.add_argument("--bash-build", type=Path, required=True,
                        help="Explicit source-attested double Bash build at the production runtime prefix")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-build", type=Path)
    parser.add_argument("--model-build", type=Path)
    parser.add_argument("--ordinary-uid-build", type=Path,
                        help="Explicit source-attested direct runner double build")
    args = parser.parse_args()
    cli_build, output = args.python_cli_build.resolve(), args.output.resolve()
    cli_build.relative_to(ROOT)
    output.relative_to(ROOT)
    bash, bash_provenance = production_bash(args.bash_build)
    python = ROOT / "downloads/shizuku-lab/runtime-stage-20260907"
    runtime = json.loads(pinned(python / "manifest.json",
        "bc9ddcfc598c875337af9d114fe0314be4dd09920dff27131f8c61278c95a5cc"))
    cli_record = json.loads((cli_build / "build.json").read_text())
    if cli_record["runtimeHome"] != RUNTIME_HOME:
        raise ValueError("Python deployment prefix differs")
    native = {}
    for item in runtime["nativeFiles"]:
        if item["name"] not in {"libfoldgpt_python_cli.so", "libfoldgpt_bash.so"}:
            native[item["name"]] = pinned(python / "jniLibs/arm64-v8a" / item["name"], item["sha256"])
    native["libfoldgpt_python_cli.so"] = pinned(cli_build / "libfoldgpt_python_cli.so", cli_record["executableSha256"])
    native["libfoldgpt_bash.so"] = bash
    direct_provenance = None
    if args.ordinary_uid_build is not None:
        native["libfoldgpt_direct_runner.so"], direct_provenance = production_direct(args.ordinary_uid_build)
    frozen = ROOT / "downloads/bionic-supervisor/foldgpt-bionic-supervisor-qKM94iHA"
    hashes = dict(reversed(row.split("  ", 1)) for row in pinned(frozen / "BINARIES.sha256",
        "a10ca7cc9ccb8c110cd7ca901d84b9066a7bf5ae73842935da88e1895437b40d").decode().splitlines())
    for name in ("libfoldgpt_bionic_supervisor.so", "libfoldgpt_native_files.so", "libfoldgpt_native_file_handle.so"):
        native[name] = pinned(frozen / name, hashes[name])
    if args.model_build is not None:
        model = args.model_build.resolve(strict=True)
        model.relative_to(ROOT)
        record = json.loads((model / "build.json").read_text())
        if (record.get("schema") != "foldgpt.native-model-build.v1" or record.get("reproducible") is not True
                or record.get("ndk") != "29.0.14206865" or record["elf"]["architecture"] != "aarch64"
                or record["elf"]["interpreter"] != "/system/bin/linker64"):
            raise ValueError("Model runner requires the reproducible checked Windows ARM64 build")
        name = "libfoldgpt_bionic_supervisor.so"
        native[name] = pinned(model / name, record["elf"]["sha256"])
        if len(native[name]) != record["elf"]["bytes"]:
            raise ValueError("Model runner build length differs")
    transport = ROOT / "tools/executor/shizuku-lab/build/frozen-transport-jni/arm64-v8a"
    for name, expected in {
        "libfoldgpt_shizuku_transport.so": "d4bb423a0dbe354485337d947bec486d6012d7b37a2ae0d73d0def8f26fe4ca6",
        "libfoldgpt_bionic_cwd.so": "f65702d47130bf8f3098e7b9a5da5d982bbbc0d20cf50eeb61cc5fd489237157"
    }.items():
        native[name] = pinned(transport / name, expected)
    if args.host_build is not None:
        host = args.host_build.resolve(strict=True)
        host.relative_to(ROOT)
        record = json.loads((host / "build.json").read_text())
        if (record.get("schema") != "foldgpt.native-host-build.v1" or record.get("reproducible") is not True
                or record.get("ndk") != "29.0.14206865" or record["elf"]["architecture"] != "aarch64"
                or record["elf"]["interpreter"] != "/system/bin/linker64"):
            raise ValueError("Human runner requires the reproducible checked Windows ARM64 build")
        name = "libfoldgpt_host_supervisor.so"
        native[name] = pinned(host / name, record["elf"]["sha256"])
        if len(native[name]) != record["elf"]["bytes"]:
            raise ValueError("Human runner build length differs")
    aliases = {item["path"] for item in runtime["runtimeAliases"]}
    for command, library in (("python", "libfoldgpt_python_cli.so"),
                             ("python3", "libfoldgpt_python_cli.so"),
                             ("python3.14", "libfoldgpt_python_cli.so"),
                             ("bash", "libfoldgpt_bash.so"),
                             ("sh", "libfoldgpt_bash.so")):
        path = "bin/" + command
        if path in aliases:
            raise ValueError("Runtime command alias collision: " + path)
        runtime["runtimeAliases"].append({"path": path, "nativeLibrary": library,
            "sha256": hashlib.sha256(native[library]).hexdigest()})
    data_files = {}
    for item in runtime["dataFiles"]:
        data = pinned(python / "assets/bionic-python" / item["path"], item["sha256"])
        if len(data) != item["bytes"]:
            raise ValueError("Data size differs")
        data_files[item["path"]] = data
    for item in runtime["runtimeAliases"]:
        if hashlib.sha256(native[item["nativeLibrary"]]).hexdigest() != item["sha256"]:
            raise ValueError("Alias differs from its attested native library")
    output.mkdir(parents=True, exist_ok=False)
    libraries = output / "jniLibs/arm64-v8a"
    libraries.mkdir(parents=True)
    assets = output / "assets"
    assets.mkdir()
    for name, data in native.items():
        (libraries / name).write_bytes(data)
    for name, data in data_files.items():
        path = assets / "bionic-python" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    runtime["nativeFiles"] = [{"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                              for name, data in sorted(native.items())]
    runtime["runtimeHome"] = cli_record["runtimeHome"]
    (assets / "foldgpt-python-runtime.json").write_text(json.dumps(runtime, indent=2) + "\n")
    lines = ["/* Authenticated production inputs; the admission binary is hashed separately. */",
             "static const struct runtime_file runtime_files[] = {"]
    lines += ["    {%s, %d, %s}," % (json.dumps(item["path"]), item["bytes"], json.dumps(item["sha256"]))
              for item in runtime["dataFiles"]]
    lines += ["};", "static const struct runtime_alias runtime_aliases[] = {"]
    lines += ["    {%s, %s}," % (json.dumps(item["path"]), json.dumps(item["nativeLibrary"]))
              for item in runtime["runtimeAliases"]]
    lines += ["};", "static const struct runtime_file native_files[] = {"]
    lines += ["    {%s, %d, %s}," % (json.dumps(item["name"]), item["bytes"], json.dumps(item["sha256"]))
              for item in runtime["nativeFiles"]]
    lines += ["};", ""]
    (output / "runtime-inventory.h").write_text("\n".join(lines), encoding="ascii")
    files = [{"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size,
              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
             for path in sorted(output.rglob("*")) if path.is_file()]
    stage_manifest = {"schema": "foldgpt.native-production-stage.v1",
        "androidExecuted": False, "runtimeHome": runtime["runtimeHome"],
        "bashBuild": bash_provenance, "files": files}
    if direct_provenance is not None:
        stage_manifest["ordinaryUidBuild"] = direct_provenance
    (output / "manifest.json").write_text(json.dumps(stage_manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), "nativeLibraries": len(native), "dataFiles": len(data_files),
                      "runtimeAliases": len(runtime["runtimeAliases"])}))


if __name__ == "__main__":
    main()
