"""Verify packaged native bytes and source closure; no Android execution claim."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import zipfile


def digest(value):
    return hashlib.sha256(value).hexdigest()


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
        qualification = json.loads(asset("foldgpt-executor-qualification.json"))
        if qualification["schema"] != "foldgpt.native.package.v1" or qualification["scope"] != "native-production-candidate":
            raise ValueError("APK is not the explicit native candidate")
        for name, key in (("deployment", "deploymentSha256"), ("manifest", "sourceManifestSha256"), ("evidence", "evidenceSha256")):
            if digest(asset("foldgpt-executor-" + name + ".json")) != qualification[key]:
                raise ValueError("Package asset digest differs: " + name)
        config = json.loads(asset("foldgpt-executor-deployment.json"))
        if config["schema"] != "foldgpt.native.deployment.v1":
            raise ValueError("Native deployment schema differs")
        host_schema = "foldgpt.host-files.v1"
        if "assets/foldgpt-host-deployment.json" in names:
            host_bytes = asset("foldgpt-host-deployment.json")
            host = json.loads(host_bytes)
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
        runtime = json.loads(runtime_bytes)
        for item in runtime["dataFiles"]:
            data = asset("bionic-python/" + item["path"])
            if len(data) != item["bytes"] or digest(data) != item["sha256"]:
                raise ValueError("Python data asset differs: " + item["path"])
        source_manifest = json.loads(asset("foldgpt-executor-manifest.json"))
        sources = {entry["path"] for entry in source_manifest}
        actual = {name[len("assets/foldgpt-executor/"):] for name in names if name.startswith("assets/foldgpt-executor/")}
        if sources != actual:
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
        result = {"schema": "foldgpt.native-apk-verification.v1", "success": True,
            "androidProductionExecuted": False, "apkSha256": digest(args.apk.read_bytes()),
            "nativeLibraries": len(config["nativeLibraries"]), "pythonDataFiles": len(runtime["dataFiles"]),
            "runtimeAliases": len(runtime["runtimeAliases"]), "sourceFiles": len(sources), "hostSchema": host_schema}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
