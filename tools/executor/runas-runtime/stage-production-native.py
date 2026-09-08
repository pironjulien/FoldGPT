"""Stage authenticated native production inputs without executing Android code."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def pinned(path, expected):
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Authenticated input differs: " + str(path))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-cli-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-build", type=Path)
    parser.add_argument("--model-build", type=Path)
    args = parser.parse_args()
    cli_build, output = args.python_cli_build.resolve(), args.output.resolve()
    cli_build.relative_to(ROOT)
    output.relative_to(ROOT)
    python = ROOT / "downloads/shizuku-lab/runtime-stage-20260907"
    runtime = json.loads(pinned(python / "manifest.json",
        "bc9ddcfc598c875337af9d114fe0314be4dd09920dff27131f8c61278c95a5cc"))
    cli_record = json.loads((cli_build / "build.json").read_text())
    if cli_record["runtimeHome"] != "/data/user/0/app.foldgpt/files/native-runtime-v1/python":
        raise ValueError("Python deployment prefix differs")
    native = {}
    for item in runtime["nativeFiles"]:
        if item["name"] != "libfoldgpt_python_cli.so":
            native[item["name"]] = pinned(python / "jniLibs/arm64-v8a" / item["name"], item["sha256"])
    native["libfoldgpt_python_cli.so"] = pinned(cli_build / "libfoldgpt_python_cli.so", cli_record["executableSha256"])
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
    (output / "manifest.json").write_text(json.dumps({"schema": "foldgpt.native-production-stage.v1",
        "androidExecuted": False, "runtimeHome": runtime["runtimeHome"], "files": files}, indent=2) + "\n")
    print(json.dumps({"output": str(output), "nativeLibraries": len(native), "dataFiles": len(data_files),
                      "runtimeAliases": len(runtime["runtimeAliases"])}))


if __name__ == "__main__":
    main()
