"""Reject an incomplete public source export without building or contacting a device.

Checks build modules, named APK source inputs, guest integration inputs and
recovery patch integrity. Generated native libraries, client binaries and device
qualification evidence are deliberately separate build inputs, not source.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
REQUIRED = (
    "android/app/build.gradle",
    "android/app/src/main/AndroidManifest.xml",
    "android/app/src/main/java/com/termux/x11/FoldRuntimeService.java",
    "android/install-native/CMakeLists.txt",
    "android/install-native/install-files.c",
    "android/shell-loader/build.gradle",
    "tools/recovery/android-signing.gradle",
    "tools/recovery/restore-engine.py",
    "tools/provision-keyring.py",
    "tools/executor/private_exec_broker.py",
    "tools/executor/private_exec_fixture.py",
    "config/agent-context/foldgpt.v1.json",
    "config/pulseaudio/foldgpt-pulse.pa",
    "plugins/foldgpt-android/.codex-plugin/plugin.json",
    "plugins/foldgpt-android/.mcp.json",
    "plugins/foldgpt-android/scripts/server.py",
    "plugins/foldgpt-android/skills/android/SKILL.md",
    "vendor/termux-x11/lorie/build.gradle",
    "vendor/proot/src/GNUmakefile",
    "recovery/engine/manifest.json",
    "tools/gpu/termux-x11-upstream.json",
)
BASH_PATCHES = (
    "config-top.h.patch", "error.c.patch", "lib-readline-complete.c.patch",
    "lib-readline-rlconf.h.patch", "lib-readline-util.c.patch",
    "lib-sh-tmpfile.c.patch", "pathnames.h.in.patch", "shell.c.patch",
)


def main():
    errors = []
    checked = set()

    def require(relative, base=ROOT):
        path = (base / relative).resolve()
        path.relative_to(ROOT)
        checked.add(path)
        if not path.is_file() or not path.stat().st_size:
            errors.append("Missing or empty source: " + path.relative_to(ROOT).as_posix())

    for relative in REQUIRED:
        require(relative)
    settings = (ROOT / "android/settings.gradle").read_text(encoding="utf-8")
    for relative in re.findall(r"projectDir\s*=\s*file\('([^']+)'\)", settings):
        require(relative + "/build.gradle", ROOT / "android")

    app = (ROOT / "android/app/build.gradle").read_text(encoding="utf-8")
    # Gradle includes silently ignore absent inputs; verify explicit source names.
    for relative in re.findall(r"'((?:tools|config|plugins)/[^'*]+)'", app):
        require(relative)
    for relative in re.findall(r"rootProject\.file\('\.\./([^']+)'\)", app):
        if relative.startswith("android/native/"):
            continue  # Documented generated inputs, never copied from a device.
        path = ROOT / relative
        if path.is_dir():
            if not any(item.is_file() for item in path.rglob("*")):
                errors.append("Empty source directory: " + relative)
        else:
            require(relative)

    guest = ast.parse((ROOT / "tools/install/guest_bundle.py").read_text(encoding="utf-8"))
    source_map = next(node.value for node in guest.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "SOURCES" for target in node.targets))
    for relative in ast.literal_eval(source_map):
        require(relative)

    patch_dir = ROOT / "tools/executor/bionic-runtime/termux-bash"
    for name in BASH_PATCHES:
        require(name, patch_dir)
    actual = {path.name for path in patch_dir.glob("*.patch")}
    if actual != set(BASH_PATCHES):
        errors.append("Bash patch set differs; review and update the explicit source inventory")

    records = ROOT / "recovery/engine"
    manifest = json.loads((records / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["patch"], records)
    patch = records / manifest["patch"]
    if patch.is_file() and hashlib.sha256(patch.read_bytes()).hexdigest() != manifest["sha256"]:
        errors.append("Engine recovery patch checksum differs from its manifest")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Source integrity verified: {len(checked)} required files, Gradle modules, guest inputs and patch inventories.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
