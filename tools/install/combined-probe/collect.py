#!/usr/bin/env python3
"""Read-only, independent Android evidence collector for the v3 debug fixture.

The reviewed local staging plan is the trust input. Device paths are derived
from its fixture ID and a checksummed PREPARED transaction journal, never from
report paths. Only four structural reports are retained. Vault ciphertext and
collection intent are hashed on Android and are never transferred. Native
Toybox stat/hash/readlink observations run outside PRoot. This assumes the
fixture's documented exclusive inactive stage; endpoint checks detect drift,
but do not claim exclusion against a hostile concurrent process with the UID.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import struct
import subprocess
import sys
import uuid

APP = "app.foldgpt"
FORMAT = "foldgpt.inactive-integration.v1"
MAGIC = (FORMAT + "\n").encode("ascii")
XKB = "usr/share/X11/xkb"
GPU = "opt/foldgpt-gpu/mesa-26.2.2-foldgpt5"
NATIVE = ("libproot.so", "libproot-loader.so", "libproot-loader32.so",
          "libtalloc.so", "libandroid-shmem.so")
INPUTS = {"fixture.properties", "base.tar.gz", "package.deb", "integration.fgi",
          "initialize_keyring.py", "supervise_keyring.py",
          "official_client_package.py", "install_official_client.py"}
DESCRIPTOR_KEYS = {"schema", "fixture", "archiveSha256", "archiveBytes",
    "archivePayloadBytes", "archiveTarBytes", "archiveMembers", "clientSha256",
    "clientBytes", "clientTarBytes", "clientMembers", "clientVersion",
    "initializerSha256", "supervisorSha256", "verifierSha256", "installerSha256",
    "integrationSha256", "integrationBytes", "integrationManifestSha256",
    "packageDeadlineMillis", "totalDeadlineMillis"}
SCRIPTS = {"usr/local/bin/foldgpt-session", "usr/local/bin/xdg-open",
    "usr/local/lib/foldgpt/foldgpt_ime.py", "usr/local/lib/foldgpt/foldgpt_keyring.py",
    "usr/local/lib/foldgpt/keyboard-focus.js",
    "usr/local/lib/foldgpt/install/initialize_keyring.py",
    "usr/local/lib/foldgpt/install/supervise_keyring.py",
    "usr/local/share/doc/foldgpt/LICENSE", "usr/local/share/foldgpt/launch-contract.v1"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "Invalid digest")
    return value


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "Duplicate field: " + key)
        result[key] = value
    return result


def json_data(data):
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def text_lines(data):
    text = data.decode("ascii")
    require(text.endswith("\n") and "\r" not in text and "\0" not in text, "Invalid text framing")
    return text[:-1].split("\n")


def properties(data, checksum=False):
    lines = text_lines(data)
    if checksum:
        require(lines[-1] == "checksum=" + sha(("\n".join(lines[:-1]) + "\n").encode()),
                "Coordinator checksum differs")
        lines = lines[:-1]
    result = pairs(line.split("=", 1) for line in lines)
    require(list(result) == sorted(result), "Noncanonical property order")
    return result


def safe_relative(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_+./-]{1,1024}", value)
            and not value.startswith("/") and str(PurePosixPath(value)) == value
            and all(part not in {".", ".."} for part in value.split("/")), "Unsafe relative path")
    return value


def identity(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9]+:[0-9]+", value), "Invalid device/inode")
    return value


def local_inputs(plan_path):
    plan = json_data(plan_path.read_bytes())
    fixture = plan["fixture"]
    require(re.fullmatch(r"[0-9a-f]{32}", fixture), "Invalid fixture")
    require(plan["schema"] == "foldgpt.combined-probe-staging.v2"
            and plan["coordinatorSchema"] == "foldgpt.inactive-preparation.v3", "Not a v3 staging plan")
    remote = "cache/combined-input/" + fixture
    require(plan["inputDirectory"] == remote and
            plan["reportPath"] == f"files/.combined-probes/{fixture}/report.json", "Plan paths differ")
    digest(plan["descriptorSha256"])
    inputs = {}
    for item in plan["files"]:
        require(set(item) == {"source", "target", "sha256", "bytes"}, "Input fields differ")
        name = item["target"].removeprefix(remote + "/")
        require(name in INPUTS and name not in inputs and item["target"] == remote + "/" + name,
                "Unexpected staging input")
        digest(item["sha256"])
        require(type(item["bytes"]) is int and 0 < item["bytes"] <= 2**31, "Invalid input size")
        path = Path(item["source"])
        require(path.is_absolute() and path.is_file() and not path.is_symlink(), "Nonregular local input")
        with path.open("rb") as stream:
            require(path.stat().st_size == item["bytes"]
                    and hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"],
                    "Local input authentication failed: " + name)
        inputs[name] = item
    require(set(inputs) == INPUTS, "Incomplete staging inputs")
    descriptor_bytes = Path(inputs["fixture.properties"]["source"]).read_bytes()
    require(sha(descriptor_bytes) == plan["descriptorSha256"], "Descriptor binding differs")
    desc = properties(descriptor_bytes)
    require(set(desc) == DESCRIPTOR_KEYS and desc["schema"] == "foldgpt.combined-preparation-fixture.v2"
            and desc["fixture"] == fixture, "Invalid descriptor scope")
    for key, value in desc.items():
        if key.endswith("Sha256"):
            digest(value)
        elif key.endswith(("Bytes", "Members", "Millis")):
            require(re.fullmatch(r"[1-9][0-9]{0,12}", value), "Invalid descriptor number")
    require(re.fullmatch(r"[0-9][A-Za-z0-9.+:~-]*", desc["clientVersion"]), "Invalid client version")
    for name, prefix in (("base.tar.gz", "archive"), ("package.deb", "client"), ("integration.fgi", "integration")):
        require(inputs[name]["sha256"] == desc[prefix + "Sha256"]
                and inputs[name]["bytes"] == int(desc[prefix + "Bytes"]), "Descriptor/input mismatch")
    for name, key in (("initialize_keyring.py", "initializerSha256"), ("supervise_keyring.py", "supervisorSha256"),
                      ("official_client_package.py", "verifierSha256"), ("install_official_client.py", "installerSha256")):
        require(inputs[name]["sha256"] == desc[key], "Helper descriptor mismatch")
    return plan, desc, inputs


def manifest_records(item, desc):
    require(item["bytes"] <= 64 * 1024 * 1024, "Integration container too large")
    data = Path(item["source"]).read_bytes()
    require(len(data) == item["bytes"] and sha(data) == desc["integrationSha256"], "Container changed")
    require(data.startswith(MAGIC), "Integration magic differs")
    length = struct.unpack_from(">I", data, len(MAGIC))[0]
    start = len(MAGIC) + 4
    require(0 < length <= 512 * 1024 and start + length <= len(data), "Manifest bound differs")
    manifest = data[start:start + length]
    require(sha(manifest) == desc["integrationManifestSha256"], "Manifest authentication failed")
    lines = text_lines(manifest)
    require(lines[0] == FORMAT and lines[1] == "base\t" + desc["archiveSha256"]
            and lines[2].startswith("guest\t") and lines[3].startswith("gpu\t"), "Manifest header differs")
    digest(lines[2].split("\t")[1]); digest(lines[3].split("\t")[1])
    records, offset = {}, start + length
    for line in lines[4:]:
        fields = line.split("\t")
        require(len(fields) == 7, "Manifest record framing differs")
        scope, kind, mode, size, expected, path, link = fields
        safe_relative(path)
        require(path not in records and scope in {"I", "V"} and kind in {"F", "D", "L"}, "Manifest entry differs")
        require(re.fullmatch(r"0[0-7]{3}", mode) and re.fullmatch(r"0|[1-9][0-9]{0,8}", size), "Manifest numeric field differs")
        require((scope == "V" and (path == XKB or path.startswith(XKB + "/"))) or
                (scope == "I" and (path.startswith(GPU + "/") or path in SCRIPTS)), "Manifest path outside reviewed scope")
        size = int(size)
        if kind == "F":
            digest(expected)
            require(link == "-" and size <= 32 * 1024 * 1024, "File manifest differs")
            if scope == "I":
                require(sha(data[offset:offset + size]) == expected, "Container payload differs")
                offset += size
        else:
            require(size == 0 and expected == "-", "Nonfile manifest differs")
            if kind == "L":
                safe_relative(link)
                require("/" not in link and mode == "0777", "Invalid same-directory link")
            else:
                require(link == "-", "Directory has a link target")
        records[path] = {"scope": scope, "kind": kind, "mode": int(mode, 8),
                         "size": size, "sha256": expected, "link": link}
    require(list(records) == sorted(records) and offset == len(data), "Container ordering/trailing data differs")
    for path, record in records.items():
        if record["kind"] == "L":
            target, seen = path, set()
            while records[target]["kind"] == "L":
                require(target not in seen, "Cyclic manifest link")
                seen.add(target)
                target = str(PurePosixPath(target).parent / records[target]["link"])
                require(target in records, "Uninventoried link target")
            require(records[target]["kind"] == "F", "Manifest link not a regular file")
            record["resolved"] = target
    return records


PREAMBLE = r'''set -eu
export PATH=/system/bin LC_ALL=C
fail() { printf 'collector-refused:%s\n' "$1" >&2; exit 1; }
directory() { [ ! -L "$1" ] && [ -d "$1" ] || fail "directory:$1"; }
regular() { [ ! -L "$1" ] && [ -f "$1" ] || fail "regular:$1"; }
metadata() { printf 'S\t%s\t' "$1"; stat -c '%d:%i|%f|%s|%u|%g|%h' "$2"; }
hashed() { regular "$2"; value=$(sha256sum "$2") || fail hash; printf 'H\t%s\t%s\n' "$1" "${value%% *}"; }
blob() {
  regular "$2"
  size=$(stat -c %s "$2")
  [ "$size" -le "$3" ] || fail size
  metadata "$1" "$2"
  value=$(base64 "$2") || fail base64
  printf 'B\t%s\t' "$1"; printf '%s' "$value" | tr -d '\r\n'; printf '\n'
}
absent() { [ ! -e "$1" ] && [ ! -L "$1" ] || fail activated; }
'''


def command(name, *args):
    return " ".join((name, *(shlex.quote(str(arg)) for arg in args)))


def parent_checks(paths):
    parents = set()
    for path in paths:
        safe_relative(path)
        parents.update(str(item) for item in PurePosixPath(path).parents if str(item) != ".")
    return [command("directory", path) for path in sorted(parents, key=lambda value: (value.count("/"), value))]


class Device:
    def __init__(self, adb, serial):
        self.prefix = [adb, "-s", serial]

    def run(self, arguments, script=None, limit=4 * 1024 * 1024):
        result = subprocess.run(self.prefix + arguments, input=script, capture_output=True, timeout=120)
        require(result.returncode == 0 and not result.stderr.strip(), "ADB read failed: " + result.stderr.decode("utf-8", "replace")[:512])
        require(len(result.stdout) <= limit, "ADB response exceeds bound")
        return result.stdout

    def shell(self, lines):
        # Windows adb exec-out does not forward stdin; shell -T is the actual
        # full-duplex transport. Base64 protects report bytes from CRLF framing.
        script = (PREAMBLE + "\n".join(lines) + "\nexit\n").encode("ascii")
        raw = self.run(["shell", "-T", "run-as", APP, "sh", "-s"], script)
        records = {}
        for line in raw.decode("ascii").replace("\r\n", "\n").splitlines():
            fields = line.split("\t")
            require(len(fields) == 3 and fields[0] in {"S", "H", "B", "L", "R", "T", "U", "P", "A"}, "Unexpected native response framing")
            key = (fields[0], fields[1])
            require(key not in records, "Duplicate native response")
            records[key] = fields[2]
        return records

    def apk_path(self):
        text = self.run(["shell", "pm", "path", APP], limit=4096).decode("ascii").strip()
        require(re.fullmatch(r"package:/data/app/[A-Za-z0-9_=+~./-]+/base\.apk", text)
                and "/../" not in text and "/./" not in text, "Unexpected installed APK path")
        return text.removeprefix("package:")


def observed_stat(observed, tag, kind=None, uid=None, gid=None, mode=None):
    value = observed[("S", tag)].split("|")
    require(len(value) == 6 and re.fullmatch(r"[0-9a-f]+", value[1])
            and all(re.fullmatch(r"[0-9]+", item) for item in value[2:]), "Native stat framing differs")
    result = {"identity": identity(value[0]), "mode": int(value[1], 16), "size": int(value[2]),
              "uid": int(value[3]), "gid": int(value[4]), "links": int(value[5])}
    if kind:
        require(stat.S_IFMT(result["mode"]) == {"F": stat.S_IFREG, "D": stat.S_IFDIR, "L": stat.S_IFLNK}[kind], "Native file kind differs: " + tag)
    if kind == "F":
        require(result["links"] == 1, "Hardlinked evidence file: " + tag)
    if uid is not None:
        require(result["uid"] == uid and result["gid"] == gid, "Native file owner differs: " + tag)
    if mode is not None:
        require(stat.S_IMODE(result["mode"]) == mode, "Native file mode differs: " + tag)
    return result


def observed_blob(observed, tag, bound):
    result = base64.b64decode(observed[("B", tag)], validate=True)
    require(len(result) <= bound and len(result) == observed_stat(observed, tag, "F")["size"], "Report transfer size differs")
    return result


def validate_probe(report, plan, desc, counts):
    require(set(report) == {"schema", "fixture", "runId", "descriptorSha256", "status",
        "activationAttempted", "uid", "gid", "coordinatorSchema", "integrationBundleSha256",
        "integrationManifestSha256", "gpuExecutionAttempted", "files", "cache", "noBackup",
        "phase", "first", "second", "successfulPrepareCalls", "baseAndPackageSourceFreeRetry",
        "integrationRevalidationCalls", "integrationInputOpens", "sameRootAccountIntegrationClientVaultCollection",
        "sourceFreeRetry", "sameRootAccountClientVaultCollection", "archiveOpens", "elapsedMillis"},
        "Unexpected probe report fields (or incomplete PASS)")
    require(report["schema"] == "foldgpt.combined-preparation-probe.v2"
            and report["coordinatorSchema"] == "foldgpt.inactive-preparation.v3"
            and report["fixture"] == plan["fixture"] and report["descriptorSha256"] == plan["descriptorSha256"], "Probe identity differs")
    require(report["status"] == "PASS" and report["phase"] == "verified", "Probe is not PASS: " + str(report.get("status")))
    for key in ("activationAttempted", "gpuExecutionAttempted", "sourceFreeRetry"):
        require(report[key] is False, "Unexpected operation: " + key)
    for key in ("baseAndPackageSourceFreeRetry", "sameRootAccountClientVaultCollection", "sameRootAccountIntegrationClientVaultCollection"):
        require(report[key] is True, "Retry evidence missing: " + key)
    for key in ("successfulPrepareCalls", "integrationRevalidationCalls", "integrationInputOpens"):
        require(type(report[key]) is int and report[key] == 2, "Expected two real calls: " + key)
    require(type(report["archiveOpens"]) is int and report["archiveOpens"] in (0, 1), "Unexpected archive opens")
    require(type(report["elapsedMillis"]) is int and 0 < report["elapsedMillis"] <= int(desc["totalDeadlineMillis"]), "Invalid elapsed time")
    require(str(uuid.UUID(report["runId"])) == report["runId"], "Invalid run UUID")
    require(report["first"] == report["second"], "Prepare snapshots differ")
    snap = report["first"]
    require(set(snap) == {"root", "rootIdentity", "state", "coordinatorStep", "installationId",
        "clientReportSha256", "coordinatorSha256", "packageIdentity", "integrationReportSha256",
        "integrationReportIdentity", "integrationBundleSha256", "integrationManifestSha256",
        "integrationEntryCount", "xkbEntryCount", "installedIntegrationEntryCount", "integrationEvidenceScope",
        "ciphertextSha256", "collectionIntentSha256", "collectionInstallationId", "guestUser", "guestUid", "guestGid"},
        "Unexpected snapshot fields")
    require(snap["state"] == "PREPARED" and snap["coordinatorStep"] == "COLLECTION_PREPARED"
            and snap["integrationEvidenceScope"] == "returned-by-real-coordinator-native-verification", "Incomplete snapshot")
    for key in ("uid", "gid"):
        require(type(report[key]) is int and report[key] > 0 and snap["guest" + key.capitalize()] == report[key], "Guest/application identity differs")
    for key in ("integrationBundleSha256", "integrationManifestSha256"):
        expected = desc["integrationSha256" if key == "integrationBundleSha256" else "integrationManifestSha256"]
        require(report[key] == expected and snap[key] == expected, "Integration input binding differs")
    require((snap["integrationEntryCount"], snap["installedIntegrationEntryCount"], snap["xkbEntryCount"]) == counts, "Manifest counts differ")
    return snap


def collect(args, output):
    plan, desc, inputs = local_inputs(args.plan)
    entries = manifest_records(inputs["integration.fgi"], desc)
    counts = (len(entries), sum(item["scope"] == "I" for item in entries.values()), sum(item["scope"] == "V" for item in entries.values()))
    device = Device(args.adb, args.serial)
    fixture = "files/.combined-probes/" + plan["fixture"]
    files, transaction = fixture + "/files", fixture + "/files/.foldgpt-install/fresh"
    report_path, journal_path = fixture + "/report.json", transaction + "/journal.v1"
    coordinator_path = transaction + "/inactive-preparation.v1"
    initial = device.shell(parent_checks([report_path, journal_path, coordinator_path]) + [
        command("absent", files + "/debian"), command("blob", "report", report_path, 65536),
        command("blob", "transaction", journal_path, 2048), command("blob", "coordinator", coordinator_path, 8192),
        "printf 'U\\tuid\\t%s\\n' \"$(id -u)\"", "printf 'U\\tgid\\t%s\\n' \"$(id -g)\"",
        "printf 'P\\tapp\\t%s\\n' \"$(pwd -P)\"", command("hashed", "descriptor", fixture + "/fixture.properties")])
    report_bytes = observed_blob(initial, "report", 65536)
    report = json_data(report_bytes)
    snap = validate_probe(report, plan, desc, counts)
    uid, gid = int(initial[("U", "uid")]), int(initial[("U", "gid")])
    require((uid, gid) == (report["uid"], report["gid"]), "Actual app identity differs")
    app_path = initial[("P", "app")]
    require(re.fullmatch(r"/data/user/[0-9]+/app\.foldgpt", app_path), "Unexpected application data path")
    require(initial[("H", "descriptor")] == plan["descriptorSha256"], "Device fixture descriptor differs")
    journal_bytes = observed_blob(initial, "transaction", 2048)
    journal = text_lines(journal_bytes)
    require(len(journal) == 11 and journal[0] == "foldgpt.fresh-install.v1"
            and journal[1:6] == [desc[key] for key in ("archiveSha256", "archiveBytes", "archivePayloadBytes", "archiveTarBytes", "archiveMembers")]
            and journal[6] == "PREPARED" and journal[9] == "base-only-no-implicit-activation:proot-termux-l2s-7266fb3-v1"
            and journal[10] == sha(("\n".join(journal[:10]) + "\n").encode()), "Transaction journal differs")
    require(re.fullmatch(r"rootfs-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", journal[7]), "Unsafe stage identity")
    root = transaction + "/stages/" + journal[7] + "/root"
    require(identity(journal[8]) == snap["rootIdentity"], "Root journal identity differs")
    prefixes = {app_path, "/data/data/app.foldgpt"} if app_path == "/data/user/0/app.foldgpt" else {app_path}
    require(snap["root"] in {prefix + "/" + root for prefix in prefixes}
            and report["files"] in {prefix + "/" + files for prefix in prefixes}
            and report["noBackup"] in {prefix + "/" + fixture + "/noBackup" for prefix in prefixes}, "Reported paths do not match the derived fixture")
    require(any(re.fullmatch(re.escape(prefix) + r"/cache/cp-[A-Za-z0-9_-]{1,64}", report["cache"])
                for prefix in prefixes), "Unexpected reported cache path")
    coordinator_bytes = observed_blob(initial, "coordinator", 8192)
    coordinator = properties(coordinator_bytes, checksum=True)
    require(sha(coordinator_bytes) == snap["coordinatorSha256"], "Coordinator snapshot hash differs")
    for tag in ("report", "transaction", "coordinator"):
        observed_stat(initial, tag, "F", uid, gid, 0o600)
    expected = {"schema": "foldgpt.inactive-preparation.v3", "step": "COLLECTION_PREPARED",
        "installationId": digest(snap["installationId"]), "bind.root": snap["rootIdentity"],
        "bind.base": ":".join(journal[1:6]), "bind.uid": str(uid), "bind.gid": str(gid),
        "bind.initializer": desc["initializerSha256"], "bind.supervisor": desc["supervisorSha256"],
        "bind.clientInstaller": desc["installerSha256"], "bind.clientVerifier": desc["verifierSha256"],
        "bind.integration": desc["integrationSha256"], "bind.integrationBytes": desc["integrationBytes"],
        "bind.integrationManifest": desc["integrationManifestSha256"], "clientReportSha256": digest(snap["clientReportSha256"]),
        "integrationReportSha256": digest(snap["integrationReportSha256"]), "vaultSha256": digest(snap["ciphertextSha256"]),
        "collectionIntentSha256": digest(snap["collectionIntentSha256"]), "collectionInstallationId": digest(snap["collectionInstallationId"])}
    binding = ("foldgpt.inactive-client-binding.v1\npackage=chatgpt\narchitecture=arm64\nversion=" + desc["clientVersion"]
               + "\nsha256=" + desc["clientSha256"] + "\nbytes=" + desc["clientBytes"] + "\nmaxTarBytes=" + desc["clientTarBytes"]
               + "\nmaxMembers=" + desc["clientMembers"] + "\n")
    expected["bind.client"] = sha(binding.encode())
    require(set(coordinator) == set(expected) | {"bind.native", "bind.vaultParent", "collectionPath", "dataIdentity"}, "Coordinator field set differs")
    for key, value in expected.items():
        require(coordinator[key] == value, "Coordinator binding differs: " + key)
    digest(coordinator["bind.native"]); identity(coordinator["bind.vaultParent"]); identity(coordinator["dataIdentity"])
    require(coordinator["collectionPath"] == "/org/freedesktop/secrets/collection/FoldGPT_5f" + snap["collectionInstallationId"], "Collection path/identity differs")
    user = snap["guestUser"]
    require(re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user), "Invalid guest username")
    data_path = root + "/home/" + user + "/.local/share"
    client_path = root + "/var/lib/foldgpt/client-install/report.json"
    integration_path = root + "/var/lib/foldgpt/integration-install/report.v1"
    package_path = root + "/var/lib/foldgpt/client-install/input/package.deb"
    vault_path = fixture + "/noBackup/foldgpt-keyring/keyring-password.v1"
    intent_path = data_path + "/.foldgpt-keyring-intent.json"
    apk_path = device.apk_path()
    native_prefix = apk_path.rsplit("/", 1)[0] + "/lib/arm64/"
    paths = [client_path, integration_path, package_path, vault_path, intent_path, data_path, fixture + "/noBackup",
             root + "/etc/foldgpt-user", root + "/etc/passwd", root + "/etc/group"]
    paths.extend(root + "/" + path for path in entries)
    lines = parent_checks(paths) + [command("absent", files + "/debian"), command("metadata", "root", root),
        command("metadata", "noBackup", fixture + "/noBackup"), command("metadata", "collectionData", data_path),
        command("blob", "client", client_path, 1048576), command("blob", "integration", integration_path, 262144),
        command("metadata", "package", package_path), command("hashed", "package", package_path),
        command("metadata", "vault", vault_path), command("hashed", "vault", vault_path),
        command("metadata", "intent", intent_path), command("hashed", "intent", intent_path),
        command("hashed", "apk", apk_path)]
    for name in NATIVE:
        lines.append(command("hashed", name, native_prefix + name))
    lines.append(command("blob", "user", root + "/etc/foldgpt-user", 128))
    # Select only nonsecret identity columns on-device. Even a malformed passwd
    # file containing a credential in column 2 must never transfer that column.
    for path in (root + "/etc/passwd", root + "/etc/group"):
        lines.append(command("regular", path))
    lines.append(command("awk", "-F:", "-v", "user=" + user, "-v", "uid=" + str(uid),
        '$1==user || $3==uid {printf "A\\tpasswd\\t%s:%s:%s:%s:%s\\n",$1,$3,$4,$6,$7}', root + "/etc/passwd"))
    lines.append(command("awk", "-F:", "-v", "user=" + user, "-v", "gid=" + str(gid),
        '$1==user || $3==gid {printf "A\\tgroup\\t%s:%s\\n",$1,$3}', root + "/etc/group"))
    for index, (path, entry) in enumerate(entries.items()):
        tag, target = str(index), root + "/" + path
        lines.append(command("metadata", tag, target))
        if entry["kind"] == "F":
            lines.append(command("hashed", tag, target))
        elif entry["kind"] == "L":
            lines.extend(["printf 'L\\t" + tag + "\\t'; " + command("readlink", target),
                          "printf 'R\\t" + tag + "\\t'; " + command("readlink", "-f", target)])
    for tag, path in (("xkb", XKB), ("gpu", GPU)):
        lines.append("value=$(" + command("find", root + "/" + path, "-print0")
                     + " | base64) || fail tree; printf 'T\\t" + tag + "\\t'; printf '%s' \"$value\" | tr -d '\\r\\n'; printf '\\n'")
    observed = device.shell(lines)
    require(observed[("H", "apk")] == args.apk_sha256, "Installed APK digest differs")
    native_binding = "".join(name + ":" + digest(observed[("H", name)]) + "\n" for name in NATIVE)
    require(sha(native_binding.encode()) == coordinator["bind.native"], "Actual APK native binding differs")
    require(observed_stat(observed, "root", "D", uid, gid)["identity"] == snap["rootIdentity"], "Actual root inode differs")
    require(observed_stat(observed, "noBackup", "D", uid, gid)["identity"] == coordinator["bind.vaultParent"], "Actual vault parent differs")
    require(observed_stat(observed, "collectionData", "D", uid, gid, 0o700)["identity"] == coordinator["dataIdentity"], "Actual collection data differs")
    package_stat = observed_stat(observed, "package", "F", uid, gid, 0o600)
    require(package_stat["identity"] == snap["packageIdentity"] and package_stat["size"] == int(desc["clientBytes"])
            and observed[("H", "package")] == desc["clientSha256"], "Actual retained package differs")
    for tag, expected_sha in (("vault", snap["ciphertextSha256"]), ("intent", snap["collectionIntentSha256"])):
        observed_stat(observed, tag, "F", uid, gid, 0o600)
        require(observed[("H", tag)] == expected_sha, "Actual vault/intent hash differs")
    require(observed_blob(observed, "user", 128) == (user + "\n").encode(), "Actual guest selection differs")
    require(observed[("A", "passwd")] == f"{user}:{uid}:{gid}:/home/{user}:/bin/bash", "Actual guest account differs")
    require(observed[("A", "group")] == f"{user}:{gid}", "Actual guest group differs")
    client_bytes = observed_blob(observed, "client", 1048576)
    integration_bytes = observed_blob(observed, "integration", 262144)
    require(sha(client_bytes) == snap["clientReportSha256"] and sha(integration_bytes) == snap["integrationReportSha256"], "Actual report hashes differ")
    observed_stat(observed, "client", "F", uid, gid, 0o600)
    require(observed_stat(observed, "integration", "F", uid, gid, 0o600)["identity"] == snap["integrationReportIdentity"], "Actual integration report inode differs")
    client = json_data(client_bytes)
    require(set(client) == {"basePackagesUnchanged", "descriptor", "format", "implementation",
        "installationId", "installed", "packagedFiles", "repositoryFiles", "rootIdentity", "scope"}, "Unexpected client report fields")
    require(client["format"] == "foldgpt.inactive-client-install.v1" and client["scope"] == "configured-client-package-only"
            and client["rootIdentity"] == snap["rootIdentity"] and client["installationId"] == snap["installationId"]
            and client["basePackagesUnchanged"] is True, "Client report binding differs")
    require(client["descriptor"] == {"format": "foldgpt.official-client-input.v1", "package": "chatgpt", "architecture": "arm64",
        "version": desc["clientVersion"], "sha256": desc["clientSha256"], "bytes": int(desc["clientBytes"]),
        "maxTarBytes": int(desc["clientTarBytes"]), "maxMembers": int(desc["clientMembers"]),
        "sourceUrl": "https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_arm64.deb",
        "sourceDocument": "https://learn.chatgpt.com/docs/linux/linux-app"}
        and client["installed"] == {"architecture": "arm64", "status": "install ok installed", "version": desc["clientVersion"]}, "Client package report differs")
    root_device, root_inode = map(int, snap["rootIdentity"].split(":"))
    checked = client["packagedFiles"].get("checked")
    require(type(checked) is int and 0 < checked <= int(desc["clientMembers"]), "Invalid packaged-file count")
    require(client["packagedFiles"] == {"checked": checked,
        "packageSha256": desc["clientSha256"], "rootDevice": root_device, "rootInode": root_inode,
        "scope": "packaged-files-only"}, "Client packaged-file evidence differs")
    require(set(client["repositoryFiles"]) == {"etc/apt/sources.list.d/chatgpt.sources",
        "usr/share/keyrings/chatgpt-archive-keyring.gpg", "var/lib/chatgpt/repository.sources"}, "Unexpected client repository report")
    for value in client["repositoryFiles"].values():
        digest(value)
    require(client["implementation"] == {"install_official_client.py": desc["installerSha256"], "official_client_package.py": desc["verifierSha256"]}, "Client helper report differs")
    report_lines = text_lines(integration_bytes)
    require(report_lines[0] == "foldgpt.inactive-integration-report.v1", "Integration report schema differs")
    meta = pairs(line.split("\t") for line in report_lines[1:9])
    require(meta == {"scope": "scripts-gpu-files-native-xkb-and-declared-launch-inputs", "activation": "not-performed",
        "gpuExecution": "not-performed", "installationId": snap["installationId"], "rootIdentity": snap["rootIdentity"],
        "bundleSha256": desc["integrationSha256"], "manifestSha256": desc["integrationManifestSha256"],
        "account": f"{user}:{uid}:{gid}:/home/{user}"}, "Integration metadata differs")
    durable = pairs((fields[0], fields[1:]) for fields in (line.split("\t") for line in report_lines[9:]))
    require(list(durable) == list(entries), "Integration report inventory differs")
    inventory = []
    for index, (path, entry) in enumerate(entries.items()):
        tag = str(index)
        actual = observed_stat(observed, tag, entry["kind"], uid, gid, entry["mode"])
        require(durable[path] == [entry["kind"], format(entry["mode"], "04o"), actual["identity"], entry["sha256"], entry["link"]], "Durable/native entry differs: " + path)
        if entry["kind"] == "F":
            require(actual["size"] == entry["size"] and observed[("H", tag)] == entry["sha256"], "Actual installed bytes differ: " + path)
            actual["sha256"] = observed[("H", tag)]
        elif entry["kind"] == "L":
            require(observed[("L", tag)] == entry["link"] and actual["size"] == len(entry["link"].encode())
                    and observed[("R", tag)] == app_path + "/" + root + "/" + entry["resolved"], "Actual link target differs: " + path)
            actual["link"] = observed[("L", tag)]
            actual["resolved"] = observed[("R", tag)]
        inventory.append({"path": path, **entry, "actual": actual})
    tree_counts = {}
    for tag, prefix in (("xkb", XKB), ("gpu", GPU)):
        raw_tree = base64.b64decode(observed[("T", tag)], validate=True)
        require(raw_tree.endswith(b"\0"), "Native tree framing differs")
        actual_tree = raw_tree[:-1].decode("ascii").split("\0")
        expected_tree = {path for path in entries if path == prefix or path.startswith(prefix + "/")}
        for path in list(expected_tree):
            expected_tree.update(str(parent) for parent in PurePosixPath(path).parents
                                 if str(parent) == prefix or str(parent).startswith(prefix + "/"))
        require(len(actual_tree) == len(set(actual_tree)) and set(actual_tree) == {root + "/" + path for path in expected_tree}, "Actual native tree has missing/extra entries: " + tag)
        tree_counts[tag] = len(actual_tree)
    final_paths = {"report": report_path, "transaction": journal_path, "coordinator": coordinator_path,
        "client": client_path, "integration": integration_path, "vault": vault_path, "intent": intent_path}
    final = device.shell(parent_checks(final_paths.values()) + [command("absent", files + "/debian"),
        command("metadata", "root", root), command("metadata", "package", package_path), command("hashed", "apk", apk_path)]
        + [command("hashed", tag, path) for tag, path in final_paths.items()])
    for tag, expected_sha in (("report", sha(report_bytes)), ("transaction", sha(journal_bytes)), ("coordinator", sha(coordinator_bytes)),
        ("client", sha(client_bytes)), ("integration", sha(integration_bytes)), ("vault", snap["ciphertextSha256"]), ("intent", snap["collectionIntentSha256"]), ("apk", args.apk_sha256)):
        require(final[("H", tag)] == expected_sha, "Evidence changed during collection: " + tag)
    require(final[("S", "root")] == observed[("S", "root")] and final[("S", "package")] == observed[("S", "package")]
            and device.apk_path() == apk_path, "Runtime/package changed during collection")
    for name, data in (("report.json", report_bytes), ("coordinator.txt", coordinator_bytes),
                       ("client-report.json", client_bytes), ("integration-report.txt", integration_bytes)):
        (output / name).write_bytes(data)
    (output / "native-inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    result = {"schema": "foldgpt.combined-v3-independent-collection.v1", "status": "PASS",
        "fixture": plan["fixture"], "runId": report["runId"], "collectedAt": datetime.now(timezone.utc).isoformat(),
        "serial": args.serial, "apkSha256": args.apk_sha256, "descriptorSha256": plan["descriptorSha256"],
        "collectorSha256": sha(Path(__file__).read_bytes()), "localPlanSha256": sha(args.plan.read_bytes()),
        "reportSha256": sha(report_bytes), "coordinatorSha256": sha(coordinator_bytes), "transactionSha256": sha(journal_bytes),
        "clientReportSha256": sha(client_bytes), "integrationReportSha256": sha(integration_bytes),
        "nativeBindingSha256": sha(native_binding.encode()), "rootIdentity": snap["rootIdentity"],
        "packageIdentity": snap["packageIdentity"], "integrationReportIdentity": snap["integrationReportIdentity"],
        "calls": 2, "integrationInputOpens": 2, "archiveOpens": report["archiveOpens"], "entries": counts[0],
        "installedEntries": counts[1], "xkbEntries": counts[2], "physicalTrees": tree_counts,
        "nativeInventorySha256": sha((output / "native-inventory.json").read_bytes()),
        "ciphertextCopied": False, "credentialsCopied": False, "deviceMutated": False,
        "state": "PREPARED", "activationAbsent": True, "elapsedMillis": report["elapsedMillis"],
        "scope": "independent native inactive installation evidence; no GPU/client/model execution"}
    (output / "independent-verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--apk-sha256", required=True)
    args = parser.parse_args()
    digest(args.apk_sha256)
    require(re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", args.serial), "Invalid ADB serial")
    output = Path(__file__).resolve().parents[3] / "downloads/install" / ("combined-device-v3-collected-" + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    try:
        result = collect(args, output)
    except Exception as error:
        failure = {"status": "FAIL", "errorType": type(error).__name__, "error": str(error), "deviceMutated": False}
        (output / "collection-failure.json").write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({**failure, "output": str(output)}))
        return 1
    print(json.dumps({"status": result["status"], "entries": result["entries"], "calls": result["calls"], "output": str(output)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
