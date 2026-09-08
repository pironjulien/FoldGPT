"""Recover unused preinstalled SDK space on a disposable GitHub Linux runner."""
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
            or os.name != "posix"):
        raise RuntimeError("Storage preparation is restricted to disposable hosted Linux jobs")
    root = Path(__file__).resolve().parents[2]
    output = root / "work/ci/evidence/runner-storage.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"before": shutil.disk_usage(root)._asdict(), "removedUnusedSdks": [],
              "removedRedundantToolchains": []}
    # These SDKs are supplied by the runner image and are not inputs to the
    # GNU Rust/C build. Preserve Python, Rust, compilers and every project file.
    for name in ("/usr/local/lib/android", "/usr/share/dotnet", "/usr/local/.ghcup",
                 "/opt/hostedtoolcache/CodeQL"):
        path = Path(name)
        if not path.exists():
            continue
        if path.is_symlink() or path.resolve(strict=True) != path or not path.is_dir():
            raise RuntimeError("Preinstalled SDK path is not the expected ordinary directory")
        subprocess.run(["sudo", "rm", "-rf", "--", name], check=True)
        report["removedUnusedSdks"].append(name)
    # The workflow installs and caches its pinned toolchain in the checkout.
    # The runner image's independent default Rust toolchains are never selected
    # by these jobs; retain its cargo/rustup shims and every selected toolchain.
    selected = root / "work/ci/cache/rustup"
    if Path(os.environ.get("RUSTUP_HOME", "")).resolve() != selected:
        raise RuntimeError("Pinned project-local Rust toolchain selection is required")
    redundant = Path("/home/runner/.rustup")
    if redundant.exists():
        if redundant.is_symlink() or redundant.resolve(strict=True) != redundant or not redundant.is_dir():
            raise RuntimeError("Image Rust toolchain directory is not the expected ordinary directory")
        subprocess.run(["sudo", "rm", "-rf", "--", str(redundant)], check=True)
        report["removedRedundantToolchains"].append(str(redundant))
    report["after"] = shutil.disk_usage(root)._asdict()
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
