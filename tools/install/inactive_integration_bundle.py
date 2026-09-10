"""Authenticate inputs and build the inactive native integration container.

This is a release assembly tool, not an Android installer. Debian XKB files are
inventoried for in-place verification; only FoldGPT scripts and the reviewed
Mesa runtime subset are included as new payload. No profile or device is read.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import tarfile

import guest_bundle

LEGACY_FORMAT = "foldgpt.inactive-integration.v1"
FORMAT = "foldgpt.inactive-integration.v2"
MAGIC = (FORMAT + "\n").encode("ascii")
GPU_PREFIX = "opt/foldgpt-gpu/mesa-26.2.2-foldgpt5"
GPU_SHA = "e02091631e5f16efbc3678373b2c048ebf81b10d551caf210d61b1954b7671d4"
BASE_SHA = "dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f"
MAX_BUNDLE = 64 * 1024 * 1024
XKB = "usr/share/X11/xkb"
GPU_FILES = (
    "lib/dri/libdril_dri.so", "lib/libEGL.so.1.0.0", "lib/libgallium-26.2.2.so",
    "lib/libGL.so.1.2.0", "lib/libGLESv1_CM.so.1.1.0", "lib/libGLESv2.so.2.0.0",
    "lib/libvulkan_freedreno.so", "share/drirc.d/00-mesa-defaults.conf",
    "share/drirc.d/00-turnip-defaults.conf", "share/drirc.d/00-zink-defaults.conf",
    "share/vulkan/icd.d/freedreno_icd.aarch64.json",
)
GPU_LINKS = {
    "lib/dri/zink_dri.so": "libdril_dri.so", "lib/libEGL.so": "libEGL.so.1",
    "lib/libEGL.so.1": "libEGL.so.1.0.0", "lib/libGL.so": "libGL.so.1",
    "lib/libGL.so.1": "libGL.so.1.2.0", "lib/libGLESv1_CM.so": "libGLESv1_CM.so.1",
    "lib/libGLESv1_CM.so.1": "libGLESv1_CM.so.1.1.0", "lib/libGLESv2.so": "libGLESv2.so.2",
    "lib/libGLESv2.so.2": "libGLESv2.so.2.0.0",
}
LEGACY_CONTRACT_PATH = "usr/local/share/foldgpt/launch-contract.v1"
CONTEXT_HELPER = "usr/local/lib/foldgpt/foldgpt_agent_context.py"
CONTEXT_MANIFEST = "usr/local/share/foldgpt/agent-environment.v1.json"
CONTRACT_PATH = "usr/local/share/foldgpt/launch-contract.v2"
LEGACY_CONTRACT = ("foldgpt.launch-contract.v1\n"
            "scope=declared-launch-inputs-only\n"
            "guest=/usr/local/bin/foldgpt-session\n"
            "guest-shell=/bin/bash\n"
            "guest-identity=etc/foldgpt-user-and-passwd-and-group\n"
            "guest-display=:2\n"
            "native-xkb=usr/share/X11/xkb\n"
            "gpu-prefix=/" + GPU_PREFIX + "\n"
            "gpu-driver=zink\n"
            "vulkan-icd=/" + GPU_PREFIX + "/share/vulkan/icd.d/freedreno_icd.aarch64.json\n"
            "cdp-loopback=127.0.0.1:9223\n"
            "scale=android-display-density\n"
            "bridges=android-process-uid\n"
            "android-root=not-required\n"
            "activation=separate-validator-required\n").encode("ascii")
CONTRACT = LEGACY_CONTRACT.replace(b"foldgpt.launch-contract.v1\n", b"foldgpt.launch-contract.v2\n") + (
    "agent-context-generator=/" + CONTEXT_HELPER + "\nagent-context-manifest=/" + CONTEXT_MANIFEST + "\n"
    "agent-context-consumer=local-codex-global-agents-md\nagent-context-selection=first-nonempty-override-then-agents\n"
    "agent-context-delivery=separate-runtime-observation-required\n").encode("ascii")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(value):
    if (not re.fullmatch(r"[A-Za-z0-9_+./-]{1,256}", value)
            or str(PurePosixPath(value)) != value or value.startswith("/")
            or any(part in (".", "..") for part in value.split("/"))):
        raise ValueError("Noncanonical integration path")
    return value


def entry(scope, kind, path, mode, data=b"", link="-"):
    safe_path(path)
    if link != "-":
        safe_path(link)
        if "/" in link:
            raise ValueError("Only same-directory links are accepted")
    return {"scope": scope, "kind": kind, "mode": mode, "size": len(data),
            "sha256": digest(data) if kind == "F" else "-", "path": path, "link": link}


def snapshot(path, expected, limit):
    data = guest_bundle.read_bounded(path, limit)
    if digest(data) != expected:
        raise ValueError("Input archive SHA-256 differs: " + Path(path).name)
    return data


def inventory_xkb(base_data):
    result = {}
    with tarfile.open(fileobj=io.BytesIO(base_data), mode="r:gz") as archive:
        for item in archive:
            path = item.name.removeprefix("./").rstrip("/")
            if path != XKB and not path.startswith(XKB + "/"):
                continue
            safe_path(path)
            if path in result or item.size > 1024 * 1024:
                raise ValueError("Duplicate or oversized XKB entry")
            if item.isdir():
                record = entry("V", "D", path, item.mode)
            elif item.issym():
                record = entry("V", "L", path, item.mode, link=item.linkname)
            elif item.isfile():
                data = archive.extractfile(item).read(1024 * 1024 + 1)
                if len(data) != item.size:
                    raise ValueError("Truncated XKB file")
                record = entry("V", "F", path, item.mode, data)
            else:
                raise ValueError("Unsupported XKB entry type")
            if record["mode"] != {"D": 0o755, "F": 0o644, "L": 0o777}[record["kind"]]:
                raise ValueError("Unexpected reviewed XKB permissions")
            result[path] = record
    for required in (XKB, XKB + "/rules/base", XKB + "/rules/evdev"):
        if required not in result:
            raise ValueError("Required native XKB entry missing")
    for record in result.values():
        if record["kind"] == "L":
            target = str(PurePosixPath(record["path"]).parent / record["link"])
            if target not in result or result[target]["kind"] != "F":
                raise ValueError("Native XKB link does not resolve to an inventoried file")
    return result


def gpu_payload(gpu_data):
    selected = {GPU_PREFIX + "/" + path for path in (*GPU_FILES, *GPU_LINKS)}
    records, payload, seen = {}, {}, set()
    with tarfile.open(fileobj=io.BytesIO(gpu_data), mode="r:gz") as archive:
        for item in archive:
            path = item.name.removeprefix("./").rstrip("/")
            safe_path(path)
            if path in seen:
                raise ValueError("Duplicate Mesa archive path")
            seen.add(path)
            if path not in selected:
                continue
            relative = path[len(GPU_PREFIX) + 1:]
            if relative in GPU_LINKS:
                if not item.issym() or item.linkname != GPU_LINKS[relative]:
                    raise ValueError("Mesa runtime link contract differs")
                records[path] = entry("I", "L", path, 0o777, link=item.linkname)
            else:
                if not item.isfile() or item.size <= 0 or item.size > 32 * 1024 * 1024:
                    raise ValueError("Invalid Mesa runtime file")
                data = archive.extractfile(item).read(32 * 1024 * 1024 + 1)
                if len(data) != item.size:
                    raise ValueError("Truncated Mesa runtime file")
                if relative.startswith("lib/") and (data[:6] != b"\x7fELF\x02\x01" or data[18:20] != b"\xb7\x00"):
                    raise ValueError("Mesa runtime must be AArch64 ELF64 little-endian")
                mode = 0o755 if relative.startswith("lib/") else 0o644
                records[path] = entry("I", "F", path, mode, data)
                payload[path] = data
    if records.keys() != selected:
        raise ValueError("Reviewed Mesa runtime subset is incomplete")
    icd = json.loads(payload[GPU_PREFIX + "/share/vulkan/icd.d/freedreno_icd.aarch64.json"])
    if icd.get("ICD", {}).get("library_path") != "/" + GPU_PREFIX + "/lib/libvulkan_freedreno.so":
        raise ValueError("Mesa ICD does not select the reviewed prefix")
    return records, payload


def encode(records, payload, base_sha, guest_sha, gpu_sha):
    lines = [FORMAT, "base\t" + base_sha, "guest\t" + guest_sha, "gpu\t" + gpu_sha]
    for path, record in sorted(records.items()):
        lines.append("\t".join((record["scope"], record["kind"], format(record["mode"], "04o"),
                                str(record["size"]), record["sha256"], path, record["link"])))
    manifest = ("\n".join(lines) + "\n").encode("ascii")
    if len(manifest) > 512 * 1024:
        raise ValueError("Integration manifest exceeds bound")
    data = MAGIC + struct.pack(">I", len(manifest)) + manifest + b"".join(payload[path] for path in sorted(payload))
    if len(data) > MAX_BUNDLE:
        raise ValueError("Integration container exceeds bound")
    return data, manifest


def build(guest_path, guest_sha, gpu_path, base_path):
    sources = guest_bundle.verify(snapshot(guest_path, guest_sha, guest_bundle.MAX_BUNDLE_BYTES), guest_sha)
    records, payload = gpu_payload(snapshot(gpu_path, GPU_SHA, 16 * 1024 * 1024))
    records.update(inventory_xkb(snapshot(base_path, BASE_SHA, 400 * 1024 * 1024)))
    for path in guest_bundle.MODES:
        target = "usr/local/share/doc/foldgpt/LICENSE" if path == "LICENSE" else path.removeprefix("payload/")
        mode = guest_bundle.MODES[path]
        # These two are already installed 0600 by inactive keyring preparation.
        if target.startswith("usr/local/lib/foldgpt/install/"):
            mode = 0o600
        payload[target] = sources[path]
        records[target] = entry("I", "F", target, mode, sources[path])
    payload[CONTRACT_PATH] = CONTRACT
    records[CONTRACT_PATH] = entry("I", "F", CONTRACT_PATH, 0o644, CONTRACT)
    return encode(records, payload, BASE_SHA, guest_sha, GPU_SHA)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guest-bundle", type=Path, required=True)
    parser.add_argument("--guest-sha256", required=True)
    parser.add_argument("--gpu-archive", type=Path, required=True)
    parser.add_argument("--base-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data, manifest = build(args.guest_bundle, args.guest_sha256, args.gpu_archive, args.base_archive)
    guest_bundle.write_new_archive(args.output, data)
    guest_bundle.write_new_archive(args.output.with_suffix(".manifest"), manifest)
    print(json.dumps({"format": FORMAT, "bytes": len(data), "sha256": digest(data),
                      "manifestSha256": digest(manifest), "activated": False}))


if __name__ == "__main__":
    main()
