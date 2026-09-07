"""Package trusted executor sources for the APK import root (never model input).

The caller provides a deployment JSON and backend factory source root. A
deployment is not enabled by building the transport AAR alone. All generated
files remain under this independent project's build directory.
"""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MODULES = ("exec_server", "native_executor_backend", "native_file_streams", "native_files",
           "native_processes", "native_process_policy", "native_environment", "native_environment_unicode",
           "policy_intent", "private_exec_broker")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", type=Path, required=True)
    parser.add_argument("--backend-sources", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.deployment.read_text(encoding="utf-8"))
    root = HERE / "build" / "installed-assets"
    destination = root / "foldgpt-executor"
    # Exclusive build generation: never erase a prior reviewed deployment.
    destination.mkdir(parents=True, exist_ok=False)
    files = [(HERE / "transport/src/main/assets/foldgpt-executor/foldgpt_shizuku_bootstrap.py", Path("foldgpt_shizuku_bootstrap.py"))]
    files.extend((REPO / "tools/executor" / (name + ".py"), Path("tools/executor") / (name + ".py")) for name in MODULES)
    files.append((REPO / "tools/policy/managed_policy.py", Path("tools/policy/managed_policy.py")))
    manifest = []
    for package in ("tools", "tools/executor", "tools/policy"):
        target = destination / package
        target.mkdir(parents=True, exist_ok=True)
        (target / "__init__.py").write_text("", encoding="utf-8")
        manifest.append({"path": package + "/__init__.py", "sha256": hashlib.sha256(b"").hexdigest()})
    source_root = args.backend_sources.resolve(strict=True)
    for path in sorted(source_root.rglob("*.py")):
        if path.is_symlink() or not path.resolve().is_relative_to(source_root):
            raise ValueError("Backend source alias is not admitted")
        files.append((path, path.relative_to(source_root)))
    for source, relative in files:
        target = destination / relative
        if target.exists():
            raise ValueError("Installed source collision: " + str(relative))
        target.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_bytes()
        compile(content, str(relative), "exec")
        target.write_bytes(content)
        manifest.append({"path": relative.as_posix(), "sha256": hashlib.sha256(content).hexdigest()})
    module, _ = config["backendFactory"].split(":")
    if not (destination / (module.replace(".", "/") + ".py")).is_file():
        raise ValueError("Configured backend factory is absent from installed sources")
    (root / "foldgpt-executor-deployment.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (HERE / "build/installed-assets-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (root / "foldgpt-executor-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(root)


if __name__ == "__main__":
    main()
