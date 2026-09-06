"""Collect an experimental Mesa artifact, corresponding inputs and ELF needs.

Run in WSL/Linux after package-build.sh. This never installs or publishes a
driver. Its manifest limits validation to the recorded development-device probes.
The upstream archive, FoldGPT patches and build/probe sources accompany the
binary archive; no Debian/Ubuntu or OpenAI binary is added to the bundle.
"""
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = "26.2.2"
SOURCE_SHA256 = "eeb29ca7e56cfaa8e8a79538dcf834e3b18e501c31bef5145e959ea437cc4216"
# This collector is for the reviewed foldgpt5 candidate only. A new build needs
# independent review and an updated digest; never package an arbitrary prefix
# just because its archive paths happen to be safe to extract.
DRIVER_SHA256 = "e02091631e5f16efbc3678373b2c048ebf81b10d551caf210d61b1954b7671d4"
PREFIX = "opt/foldgpt-gpu/mesa-26.2.2-foldgpt5"
PATCHES = (
    "mesa-pseudodrm-dri3.patch", "mesa-pseudodrm-wsi.patch",
    "mesa-kopper-pixmap-import.patch", "mesa-glx-randr-rate.patch",
    "mesa-kgsl-calibrated-timestamps.patch",
    "mesa-tc-renderpass-transition.patch", "mesa-zink-render-area.patch",
)
SOURCES = (
    "prepare-build.sh", "build-mesa.sh", "package-build.sh",
    "build-timestamp-probe.sh", "build-present-probe.sh",
    "vulkan-clear-probe.c", "vulkan-timestamp-probe.c", "glx-clear-probe.c",
    "glx-present-probe.c", "glx-tfp-probe.c", "package-review-bundle.py",
    "zink-partial-resolve-probe.c",
    "deploy-test-prefix.py",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_candidate(driver):
    if digest(driver) != DRIVER_SHA256:
        raise ValueError("GPU candidate digest differs from the independently reviewed artifact")


def collect():
    tool = ROOT / "tools/gpu/deploy-test-prefix.py"
    spec = importlib.util.spec_from_file_location("foldgpt_gpu_archive", tool)
    validation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validation)
    driver = (ROOT / f"downloads/gpu/foldgpt-mesa-{VERSION}-arm64.tar.gz").read_bytes()
    validate_candidate(driver)
    validation.validate_archive(driver)
    upstream = (ROOT / f"downloads/gpu/mesa-{VERSION}.tar.xz").read_bytes()
    if digest(upstream) != SOURCE_SHA256:
        raise ValueError("Mesa upstream source archive digest mismatch")
    files = {
        f"binary/foldgpt-mesa-{VERSION}-arm64.tar.gz": driver,
        f"source/mesa-{VERSION}.tar.xz": upstream,
        "source/FoldGPT-COPYING": (ROOT / "LICENSE").read_bytes(),
    }
    for name in (*PATCHES, *SOURCES):
        files["source/foldgpt/" + name] = (ROOT / "tools/gpu" / name).read_bytes().replace(b"\r\n", b"\n")
    # Preserve the actual upstream licensing overview as well as all notices in
    # the complete upstream archive. Never relabel the entire Mesa tree as GPL.
    with tarfile.open(fileobj=io.BytesIO(upstream), mode="r:xz") as archive:
        notice = archive.extractfile(f"mesa-{VERSION}/docs/license.rst")
        if notice is None:
            raise ValueError("Mesa license overview is missing")
        files["source/Mesa-license.rst"] = notice.read()

    elf = []
    with tempfile.TemporaryDirectory(prefix="foldgpt-elf-review-") as scratch:
        probe = Path(scratch) / "object"
        with tarfile.open(fileobj=io.BytesIO(driver), mode="r:gz") as archive:
            for entry in archive:
                if not entry.isfile():
                    continue
                stream = archive.extractfile(entry)
                data = stream.read()
                if not data.startswith(b"\x7fELF"):
                    continue
                # A private fixed pathname avoids extracting archive paths.
                probe.write_bytes(data)
                result = subprocess.run(["readelf", "-h", "-d", "-V", str(probe)],
                                        check=True, capture_output=True, text=True, timeout=30)
                report = result.stdout
                if not re.search(r"Machine:\s+AArch64", report):
                    raise ValueError("Non-AArch64 ELF in the driver archive")
                elf.append({
                    "path": entry.name, "sha256": digest(data), "bytes": len(data),
                    "needed": sorted(set(re.findall(r"\(NEEDED\).*?\[(.*?)\]", report))),
                    "soname": re.findall(r"\(SONAME\).*?\[(.*?)\]", report),
                    "symbolVersions": sorted(set(re.findall(
                        r"Name: ((?:GLIBC|GLIBCXX|CXXABI)_[0-9.]+)", report))),
                })
    if not elf:
        raise ValueError("No driver ELF files found")
    provided = {name for item in elf for name in item["soname"]}
    manifest = {
        "schemaVersion": 1,
        "status": "selected development driver; bounded device probes passed",
        "mesaVersion": VERSION, "prefix": "/" + PREFIX,
        "reviewedBinarySha256": DRIVER_SHA256,
        "upstream": {"url": f"https://archive.mesa3d.org/mesa-{VERSION}.tar.xz",
                     "sha256": SOURCE_SHA256},
        "patchOrder": list(PATCHES),
        "elf": sorted(elf, key=lambda item: item["path"]),
        "externalNeeded": sorted({name for item in elf for name in item["needed"]} - provided),
        "additionalRuntimeLoads": [{"soname": "libvulkan.so.1",
                                    "reason": "Zink loads the Vulkan loader dynamically"}],
        "scope": "Source inputs and ELF requirements, not proof of reproducible compilation or a runtime test",
        "files": {name: {"sha256": digest(data), "bytes": len(data)}
                  for name, data in sorted(files.items())},
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    files["README.txt"] = (
        "FoldGPT Mesa review bundle — selected development driver\n\n"
        "Bounded Adreno device regressions pass; this is not an installable FoldGPT release.\n"
        "The untouched upstream source archive, ordered patches, FoldGPT build\n"
        "scripts/probes and licenses accompany the exact candidate binary archive.\n"
        "The manifest lists ELF dependencies and symbol versions. Resolve them\n"
        "from the guest distribution; Ubuntu build-sysroot libraries are omitted.\n"
        "Native Android libraries, Debian, OpenAI binaries and private data are\n"
        "not in this bundle. Build details are in the FoldGPT GPU-PROBE.md.\n"
        "Source presence alone does not establish a bit-for-bit reproducible build.\n"
    ).encode()
    return files, manifest


def main():
    if not shutil.which("readelf"):
        raise SystemExit("Run in WSL/Linux with binutils readelf installed")
    files, manifest = collect()
    output = ROOT / "downloads/gpu/review"
    output.mkdir(parents=True, exist_ok=True)
    # Stable metadata makes collection reproducible for identical input bytes.
    with tempfile.NamedTemporaryFile(dir=output, prefix=".bundle-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            with gzip.GzipFile(fileobj=stream, filename="", mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for name, data in sorted(files.items()):
                        item = tarfile.TarInfo(name)
                        item.size, item.mode, item.mtime = len(data), 0o644, 0
                        archive.addfile(item, io.BytesIO(data))
            stream.flush()
        except BaseException:
            stream.close()
            temporary.unlink()
            raise
    checksum = digest(temporary.read_bytes())
    destination = output / ("foldgpt-mesa-review-" + checksum + ".tar.gz")
    try:
        # Publish the completed inode atomically; interruption cannot leave a
        # truncated content-addressed artifact that poisons the next attempt.
        os.link(temporary, destination)
    except FileExistsError:
        if digest(destination.read_bytes()) != checksum:
            raise ValueError("Existing content-addressed bundle has different bytes")
    finally:
        temporary.unlink()
    print(json.dumps({"bundle": str(destination), "sha256": checksum,
                      "elfCount": len(manifest["elf"]),
                      "externalNeeded": manifest["externalNeeded"],
                      "status": manifest["status"]}, indent=2))


if __name__ == "__main__":
    main()
