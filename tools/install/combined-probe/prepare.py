#!/usr/bin/env python3
"""Prepare an authenticated local debug fixture and explicit ADB staging plan.

This command only reads local artifacts and writes a new local bundle. It never
opens ADB, installs an APK, starts a service or accesses a phone/account.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import uuid

BASE = {"archiveSha256": "dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f",
        "archiveBytes": 327673156, "archivePayloadBytes": 958101116,
        "archiveTarBytes": 977131520, "archiveMembers": 20240}
CLIENT = {"clientVersion": "26.901.41600",
          "clientSha256": "8d5141b299ca593255fa25760895e84375937cc305197528c822dfa71ac2a3bf",
          "clientBytes": 388651910, "clientTarBytes": 1365770240, "clientMembers": 7360}
SCRIPTS = {"initializer": "tools/install/initialize_keyring.py",
           "supervisor": "tools/install/supervise_keyring.py",
           "verifier": "tools/install/official_client_package.py",
           "installer": "tools/install/install_official_client.py"}
INTEGRATION = {"integrationSha256": "d0d9f2edce1c194ae2188556922373bb8e66d9ae30e8f34197da54a51945c16c",
               "integrationBytes": 41116761,
               "integrationManifestSha256": "a832faca1620125b00256271c236e12d07dc5972f3b403a24407559ca0b0feb0"}
INTEGRATION_HELPERS = {"initializer": "f2a11141839bd3a563e7250275cdf307c9b6c8cb4422c5591c693a82036f39c0",
                       "supervisor": "3e46f4318889d8dca20dedbe43b443ed24c8336671bb62bd38feba03fbbf0dff"}


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--integration", type=Path,
                        help="Use the separately pinned reviewed integration release and the new coordinator v3; omit to retain v2")
    parser.add_argument("--package-deadline-seconds", type=int, default=900)
    parser.add_argument("--total-deadline-seconds", type=int, default=3600)
    args = parser.parse_args()
    if not 0 < args.package_deadline_seconds <= 2147483 or not 0 < args.total_deadline_seconds <= 43200:
        parser.error("deadlines must be positive and within the Android fixture bound")
    if args.total_deadline_seconds < 2 * args.package_deadline_seconds + 120:
        parser.error("total deadline must allow both package calls and both keyring calls")
    repo = Path(__file__).resolve().parents[3]
    archive, package = args.archive.resolve(strict=True), args.package.resolve(strict=True)
    for path, expected_size, expected_hash in ((archive, BASE["archiveBytes"], BASE["archiveSha256"]),
                                              (package, CLIENT["clientBytes"], CLIENT["clientSha256"])):
        if not path.is_file() or path.stat().st_size != expected_size or digest(path) != expected_hash:
            raise ValueError(f"Artifact differs from the independently authenticated fixture: {path.name}")
    integration = args.integration.resolve(strict=True) if args.integration else None
    if integration is not None:
        if (not integration.is_file() or integration.stat().st_size != INTEGRATION["integrationBytes"]
                or digest(integration) != INTEGRATION["integrationSha256"]):
            raise ValueError("Integration input differs from the separately reviewed release")
        with integration.open("rb") as source:
            magic = b"foldgpt.inactive-integration.v1\n"
            if source.read(len(magic)) != magic:
                raise ValueError("Unexpected integration container framing")
            length = struct.unpack(">I", source.read(4))[0]
            if not 0 < length <= 512 * 1024:
                raise ValueError("Integration manifest bound differs")
            manifest = source.read(length)
            if len(manifest) != length or hashlib.sha256(manifest).hexdigest() != INTEGRATION["integrationManifestSha256"]:
                raise ValueError("Integration manifest differs from the reviewed release")
    fixture = uuid.uuid4().hex
    bundle = repo / "downloads/install" / ("combined-probe-" + fixture)
    bundle.mkdir(mode=0o700)
    values = {"schema": "foldgpt.combined-preparation-fixture.v2" if integration else "foldgpt.combined-preparation-fixture.v1", "fixture": fixture,
              **BASE, **CLIENT, "packageDeadlineMillis": args.package_deadline_seconds * 1000,
              "totalDeadlineMillis": args.total_deadline_seconds * 1000}
    files = {"base.tar.gz": archive, "package.deb": package}
    if integration is not None:
        values.update(INTEGRATION)
        files["integration.fgi"] = integration
    for key, relative in SCRIPTS.items():
        source = repo / relative
        data = source.read_bytes().replace(b"\r\n", b"\n")
        data.decode("utf-8", errors="strict")
        if b"\r" in data or b"\x00" in data or not 0 < len(data) <= 1048576:
            raise ValueError("Helper is not canonical bounded UTF-8/LF")
        target = bundle / source.name
        target.write_bytes(data)
        values[key + "Sha256"] = hashlib.sha256(data).hexdigest()
        if integration is not None and key in INTEGRATION_HELPERS and values[key + "Sha256"] != INTEGRATION_HELPERS[key]:
            raise ValueError("Current coordinator helper differs from the pinned integration payload")
        files[source.name] = target
    descriptor = bundle / "fixture.properties"
    descriptor.write_bytes("".join(f"{key}={value}\n" for key, value in sorted(values.items())).encode("ascii"))
    descriptor_hash = digest(descriptor)
    files[descriptor.name] = descriptor
    remote = "cache/combined-input/" + fixture
    plan = {"schema": "foldgpt.combined-probe-staging.v2" if integration else "foldgpt.combined-probe-staging.v1", "fixture": fixture,
            "descriptorSha256": descriptor_hash, "inputDirectory": remote,
            "files": [{"source": str(source), "target": remote + "/" + name,
                       "sha256": digest(source), "bytes": source.stat().st_size} for name, source in files.items()],
            "startArguments": ["shell", "am", "start-foreground-service", "-n",
                               "app.foldgpt/app.foldgpt.install.CombinedPreparationProbeService",
                               "--es", "fixture", fixture, "--es", "descriptorSha256", descriptor_hash],
            "reportPath": "files/.combined-probes/" + fixture + "/report.json",
            "scope": "debug fixture, inactive real combined preparation; no activation or client launch"}
    if integration is not None:
        plan["coordinatorSchema"] = "foldgpt.inactive-preparation.v3"
        plan["scope"] = "debug fixture, inactive real base/account/native-integration/client/vault/collection preparation; no activation or GPU/client launch"
    (bundle / "staging-plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"bundle": str(bundle), "fixture": fixture, "descriptorSha256": descriptor_hash,
                      "plan": str(bundle / "staging-plan.json")}, indent=2))


if __name__ == "__main__":
    main()
