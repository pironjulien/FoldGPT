"""Verify packaged native bytes and source closure; no Android execution claim."""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import zipfile


def digest(value):
    return hashlib.sha256(value).hexdigest()


def strict_json(data):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate package JSON field: " + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite package value")))


def verify_launch_origin(config, qualification, read_asset, read_library, sources):
    schema = config.get("schema")
    native = config["nativeLibraries"]
    app_libraries = {"libfoldgpt_app_bootstrap.so", "libfoldgpt_app_transport.so"}
    if schema == "foldgpt.native.deployment.v1":
        if ("launchOrigin" in config or "launchOrigin" in qualification or "appLaunchBuildSha256" in qualification
                or app_libraries & set(native) or "libfoldgpt_native_bootstrap.so" not in native):
            raise ValueError("Run-as deployment mixes application-origin inputs")
        if "foldgpt_native_bootstrap.py" not in sources:
            raise ValueError("Run-as bootstrap source is absent")
        return "run-as"
    if (schema != "foldgpt.native.deployment.v2" or config.get("launchOrigin") != "android-app"
            or qualification.get("launchOrigin") != "android-app"
            or "libfoldgpt_native_bootstrap.so" in native or not app_libraries <= set(native)
            or not {"foldgpt_app_bootstrap.py", "foldgpt_native_bootstrap.py"} <= sources):
        raise ValueError("Application deployment mixes launch origins or lacks its source closure")
    data = read_asset("foldgpt-app-launch-build.json")
    if digest(data) != qualification.get("appLaunchBuildSha256"):
        raise ValueError("Application launcher build attestation is absent or changed")
    spec = importlib.util.spec_from_file_location("foldgpt_apk_app_launch", Path(__file__).with_name("app-launch-admission.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify(strict_json(data), native, read_library)


def verify_model_selection(config, qualification, read_library, sources, *, read_source=None):
    """Validate the explicit installed option, independently of mere ELF presence."""
    options = config["backendOptions"]
    pty_name = "libfoldgpt_direct_pty_supervisor.so"
    if "ordinaryUid" not in options:
        if ("ordinaryUidBuild" in qualification or "ordinaryPtyBuild" in qualification
                or pty_name in config["nativeLibraries"]):
            raise ValueError("Ordinary UID attestation exists without explicit deployment selection")
        return ["managed"]
    direct = options["ordinaryUid"]
    name = "libfoldgpt_direct_runner.so"
    if (type(direct) is not dict or not {"processRunner", "limits"} <= set(direct)
            or set(direct) - {"processRunner", "limits", "ptyProcessRunner"}
            or direct["processRunner"] != "@nativeLibraryDir/" + name
            or type(direct["limits"]) is not dict or direct["limits"]):
        raise ValueError("Ordinary UID package selection is not the exact installed contract")
    provenance = qualification.get("ordinaryUidBuild")
    fields = {"path", "buildManifestSha256", "sourceManifestSha256", "executableSha256", "bytes"}
    if type(provenance) is not dict or set(provenance) != fields:
        raise ValueError("Ordinary UID package lacks its complete source/build attestation")
    relative = provenance["path"]
    if (type(relative) is not str or not relative or PurePosixPath(relative).is_absolute()
            or PurePosixPath(relative).as_posix() != relative or ".." in PurePosixPath(relative).parts
            or "\\" in relative or ":" in relative):
        raise ValueError("Ordinary UID build provenance path is not project-relative")
    for field in ("buildManifestSha256", "sourceManifestSha256", "executableSha256"):
        if type(provenance[field]) is not str or re.fullmatch("[0-9a-f]{64}", provenance[field]) is None:
            raise ValueError("Ordinary UID provenance digest is malformed")
    data = read_library(name)
    if (type(provenance["bytes"]) is not int or provenance["bytes"] != len(data)
            or config["nativeLibraries"].get(name) != provenance["executableSha256"]
            or digest(data) != provenance["executableSha256"]):
        raise ValueError("Ordinary UID attestation does not identify the packaged runner")
    required = {"tools/executor/native_model_profiles.py", "tools/executor/ordinary_uid_files.py",
                "tools/executor/bionic-supervisor/direct_processes.py", "tools/executor/bionic-supervisor/direct_wire.py"}
    if not required <= sources:
        raise ValueError("Ordinary UID selected without its complete model implementation")
    has_pty = "ptyProcessRunner" in direct
    if (("ordinaryPtyBuild" in qualification) != has_pty
            or (pty_name in config["nativeLibraries"]) != has_pty):
        raise ValueError("Model PTY requires explicit selection and complete build attestation")
    if has_pty:
        if direct["ptyProcessRunner"] != "@nativeLibraryDir/" + pty_name:
            raise ValueError("Model PTY runner is not the admitted APK-owned library")
        provenance = qualification["ordinaryPtyBuild"]
        if type(provenance) is not dict or type(provenance.get("path")) is not str:
            raise ValueError("Model PTY build provenance is malformed")
        spec = importlib.util.spec_from_file_location("foldgpt_apk_pty_admission",
            Path(__file__).with_name("pty-admission.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        binary, actual = module.production_pty(module.ROOT / provenance["path"])
        if (provenance != actual or read_library(pty_name) != binary
                or config["nativeLibraries"][pty_name] != digest(binary)):
            raise ValueError("Packaged model PTY differs from its reviewed source and build")
        if not {"tools/executor/bionic-supervisor/tty_processes.py",
                "tools/executor/bionic-supervisor/tty_wire.py"} <= sources:
            raise ValueError("Model PTY selected without its implementation")
        if read_source is None:
            raise ValueError("Model PTY requires verification of its actual packaged Python bytes")
        for path, expected in actual["runtimeSourceSha256"].items():
            if path not in sources or digest(read_source(path)) != expected:
                raise ValueError("Packaged model PTY runtime source differs from qualification: " + path)
        return ["managed", "ordinaryUid", "ordinaryPty"]
    return ["managed", "ordinaryUid"]


def verify_entrypoints(config, qualification, runtime, read_library):
    """Check command selection, runtime aliases and the optional native rg build."""
    marker = "@nativeLibraryDir/"
    commands = {"bash": "libfoldgpt_bash.so", "python": "libfoldgpt_python_cli.so",
                "python3": "libfoldgpt_python_cli.so"}
    rg_name, probe_name = "libfoldgpt_rg.so", "libfoldgpt_pcre2_jit_probe.so"
    native = config["nativeLibraries"]
    has_rg = rg_name in native
    if has_rg:
        commands["rg"] = rg_name
    if (probe_name in native) != has_rg or ("ripgrepBuild" in qualification) != has_rg:
        raise ValueError("Ripgrep requires its complete native outputs and build attestation")
    pty_name = "libfoldgpt_direct_pty_supervisor.so"
    runtime_pty = [item for item in runtime["nativeFiles"] if item["name"] == pty_name]
    if pty_name in native:
        data = read_library(pty_name)
        if runtime_pty != [{"name": pty_name, "bytes": len(data), "sha256": native[pty_name]}]:
            raise ValueError("Model PTY is absent or changed in the admitted runtime inventory")
    elif runtime_pty:
        raise ValueError("Runtime inventories an unselected model PTY library")
    if config["backendOptions"]["executables"] != {name: marker + library for name, library in commands.items()}:
        raise ValueError("Package entrypoints differ from the exact native commands")
    aliases = runtime["runtimeAliases"]
    by_path = {item["path"]: item for item in aliases}
    if len(by_path) != len(aliases):
        raise ValueError("Duplicate runtime alias")
    for item in aliases:
        library = item["nativeLibrary"]
        if library not in native or item["sha256"] != native[library]:
            raise ValueError("Runtime alias differs from its packaged native library")
    for name, library in commands.items():
        if by_path.get("bin/" + name) != {"path": "bin/" + name, "nativeLibrary": library,
                                         "sha256": native[library]}:
            raise ValueError("Native command lacks its exact runtime alias: " + name)
    if not has_rg:
        if "bin/rg" in by_path:
            raise ValueError("Unattested rg runtime alias")
        return sorted(commands)
    provenance = qualification["ripgrepBuild"]
    fields = {"path", "buildManifestSha256", "sourceManifestSha256", "executableSha256", "bytes",
              "probeSha256", "probeBytes", "ripgrepVersion", "pcre2Version", "pcre2Jit", "androidExecuted"}
    if type(provenance) is not dict or set(provenance) != fields:
        raise ValueError("Ripgrep package lacks its complete source/build attestation")
    relative = provenance["path"]
    if (type(relative) is not str or not relative or PurePosixPath(relative).is_absolute()
            or PurePosixPath(relative).as_posix() != relative or ".." in PurePosixPath(relative).parts
            or "\\" in relative or ":" in relative):
        raise ValueError("Ripgrep build provenance path is not project-relative")
    for field in ("buildManifestSha256", "sourceManifestSha256", "executableSha256", "probeSha256"):
        if type(provenance[field]) is not str or re.fullmatch("[0-9a-f]{64}", provenance[field]) is None:
            raise ValueError("Ripgrep provenance digest is malformed")
    if (provenance["ripgrepVersion"] != "15.2.0" or provenance["pcre2Version"] != "10.47"
            or provenance["pcre2Jit"] is not True or provenance["androidExecuted"] is not False):
        raise ValueError("Ripgrep/PCRE2 provenance versions differ from the reviewed build")
    for name, hash_key, size_key in ((rg_name, "executableSha256", "bytes"),
                                     (probe_name, "probeSha256", "probeBytes")):
        data = read_library(name)
        if (type(provenance[size_key]) is not int or provenance[size_key] != len(data)
                or native[name] != provenance[hash_key] or digest(data) != provenance[hash_key]):
            raise ValueError("Ripgrep attestation differs from its actual packaged ELF: " + name)
    return sorted(commands)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with zipfile.ZipFile(args.apk) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate APK entries")
        def asset(name):
            return archive.read("assets/" + name)
        qualification = strict_json(asset("foldgpt-executor-qualification.json"))
        if qualification["schema"] != "foldgpt.native.package.v1" or qualification["scope"] != "native-production-candidate":
            raise ValueError("APK is not the explicit native candidate")
        for name, key in (("deployment", "deploymentSha256"), ("manifest", "sourceManifestSha256"), ("evidence", "evidenceSha256")):
            if digest(asset("foldgpt-executor-" + name + ".json")) != qualification[key]:
                raise ValueError("Package asset digest differs: " + name)
        config = strict_json(asset("foldgpt-executor-deployment.json"))
        if config["schema"] not in ("foldgpt.native.deployment.v1", "foldgpt.native.deployment.v2"):
            raise ValueError("Native deployment schema differs")
        if "ripgrepBuild" in qualification:
            notices = asset("notices/ripgrep.txt")
            if (not notices or digest(notices) != qualification.get("ripgrepNoticesSha256")
                    or b"ripgrep-15.2.0" not in notices or b"pcre2-10.47" not in notices):
                raise ValueError("Ripgrep/PCRE2 notices are absent or changed")
        elif "ripgrepNoticesSha256" in qualification or "assets/notices/ripgrep.txt" in names:
            raise ValueError("Ripgrep notices present without the attested feature")
        spec = importlib.util.spec_from_file_location("foldgpt_apk_ripgrep_notices",
            Path(__file__).with_name("ripgrep-notices.py"))
        notice_verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(notice_verifier)
        notice_files = notice_verifier.verify_assets(qualification, asset,
            [name[len("assets/"):] for name in names if name.startswith("assets/")])
        host_schema = "foldgpt.host-files.v1"
        if "assets/foldgpt-host-deployment.json" in names:
            host_bytes = asset("foldgpt-host-deployment.json")
            host = strict_json(host_bytes)
            if (digest(host_bytes) != qualification.get("hostDeploymentSha256")
                    or set(host) != {"schema", "runner", "runnerSha256"}
                    or host["schema"] != "foldgpt.host.v2"
                    or host["runner"] != "libfoldgpt_host_supervisor.so"
                    or config["nativeLibraries"].get(host["runner"]) != host["runnerSha256"]):
                raise ValueError("Human host selection differs from its attested native package")
            host_schema = host["schema"]
        elif "hostDeploymentSha256" in qualification:
            raise ValueError("Attested human host deployment asset is absent")
        for name, sha in config["nativeLibraries"].items():
            data = archive.read("lib/arm64-v8a/" + name)
            if digest(data) != sha:
                raise ValueError("APK native ELF changed during packaging: " + name)
        runtime_bytes = asset(config["pythonRuntime"]["manifestAsset"])
        if digest(runtime_bytes) != config["pythonRuntime"]["manifestSha256"]:
            raise ValueError("Python manifest digest differs")
        runtime = strict_json(runtime_bytes)
        for item in runtime["dataFiles"]:
            data = asset("bionic-python/" + item["path"])
            if len(data) != item["bytes"] or digest(data) != item["sha256"]:
                raise ValueError("Python data asset differs: " + item["path"])
        source_manifest = strict_json(asset("foldgpt-executor-manifest.json"))
        sources = {entry["path"] for entry in source_manifest}
        actual = {name[len("assets/foldgpt-executor/"):] for name in names if name.startswith("assets/foldgpt-executor/")}
        if sources != actual or len(sources) != len(source_manifest):
            raise ValueError("Executor source inventory is incomplete")
        for item in source_manifest:
            data = asset("foldgpt-executor/" + item["path"])
            if digest(data) != item["sha256"]:
                raise ValueError("Executor source digest differs: " + item["path"])
            tree = ast.parse(data, filename=item["path"])
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("tools."):
                    module = node.module.replace(".", "/")
                    if module + ".py" not in sources and module + "/__init__.py" not in sources:
                        raise ValueError("Packaged source import is unresolved: " + node.module)
        launch_origin = verify_launch_origin(config, qualification, asset,
            lambda name: archive.read("lib/arm64-v8a/" + name), sources)
        profiles = verify_model_selection(config, qualification,
            lambda name: archive.read("lib/arm64-v8a/" + name), sources,
            read_source=lambda path: asset("foldgpt-executor/" + path))
        commands = verify_entrypoints(config, qualification, runtime,
            lambda name: archive.read("lib/arm64-v8a/" + name))
        result = {"schema": "foldgpt.native-apk-verification.v1", "success": True,
            "androidProductionExecuted": False, "apkSha256": digest(args.apk.read_bytes()),
            "nativeLibraries": len(config["nativeLibraries"]), "pythonDataFiles": len(runtime["dataFiles"]),
            "runtimeAliases": len(runtime["runtimeAliases"]), "sourceFiles": len(sources), "hostSchema": host_schema,
            "modelProfiles": profiles, "nativeCommands": commands, "launchOrigin": launch_origin}
        if notice_files:
            result["ripgrepToolchainNoticeFiles"] = notice_files
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
