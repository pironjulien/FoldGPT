"""Collect authenticated, exact Debian corresponding sources for a built rootfs.

Host Linux only for collection. No package is installed or executed. Archives
stay local; this prepares release inputs, not a public binary release.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
COLLECTOR_SOURCE = Path(__file__).read_bytes()
REPOSITORIES = (
    ("trixie", "https://deb.debian.org/debian"),
    ("trixie-updates", "https://deb.debian.org/debian"),
    ("trixie-security", "https://security.debian.org/debian-security"),
)
PACKAGE = re.compile(r"[a-z0-9][a-z0-9+.-]*\Z")
VERSION = re.compile(r"[0-9][A-Za-z0-9.+:~\-]*\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_identity(record):
    name, version = record["package"], record["version"]
    source = record.get("source", "")
    if source:
        match = re.fullmatch(r"([a-z0-9][a-z0-9+.-]*)(?: \(([^()\s]+)\))?", source)
        if not match:
            raise ValueError("Malformed Debian Source field")
        name, explicit_version = match.groups()
        if explicit_version is not None:
            version = explicit_version
    if not PACKAGE.fullmatch(name) or not VERSION.fullmatch(version):
        raise ValueError("Malformed source name/version")
    return name, version


def parse_deb822(text):
    records, current, previous = [], {}, None
    for line in text.splitlines() + [""]:
        if not line:
            if current:
                records.append(current)
            current, previous = {}, None
        elif line[0] in " \t":
            if previous is None:
                raise ValueError("Deb822 continuation without field")
            current[previous] += "\n" + line[1:]
        else:
            if ":" not in line:
                raise ValueError("Malformed Deb822 field")
            key, value = line.split(":", 1)
            if not key or key.lower() in {item.lower() for item in current}:
                raise ValueError("Duplicate or empty Deb822 field")
            current[key], previous = value.lstrip(), key
    return records


def safe_filename(name):
    if not name or name in (".", "..") or "/" in name or "\\" in name or ":" in name or any(ord(char) < 32 for char in name):
        raise ValueError("Unsafe source filename")
    return name


def source_files(stanza):
    files, seen = [], set()
    for line in stanza.get("Checksums-Sha256", "").splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 3:
            raise ValueError("Malformed source SHA256 record")
        digest, size, name = fields
        safe_filename(name)
        if not SHA256.fullmatch(digest) or not size.isdigit() or int(size) <= 0 or name in seen:
            raise ValueError("Invalid or duplicate source file")
        seen.add(name)
        files.append({"name": name, "bytes": int(size), "sha256": digest})
    if not files:
        raise ValueError("No source files with SHA256")
    return files


def checked_directory(path):
    path = Path(path)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or path.resolve(strict=True) != path:
        raise ValueError("Expected a real canonical directory: " + str(path))
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
        raise ValueError("Unsafe directory owner/permissions: " + str(path))
    return path


def validate_resume_tree(bundle):
    """Refuse aliases and writable state before any resumed collection writes."""
    for parent, directories, files in os.walk(bundle, followlinks=False):
        checked_directory(Path(parent))
        for name in directories:
            checked_directory(Path(parent) / name)
        for name in files:
            path = Path(parent) / name
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("Resumed bundle has a link or non-regular file: " + str(path))
            if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
                raise ValueError("Unsafe resumed file owner/permissions: " + str(path))


def write_bundle_checksums(bundle, expected):
    """Index precisely the recipe's files; never hash an earlier index itself."""
    bundle = Path(bundle)
    expected = set(expected)
    if "SHA256SUMS.json" in expected:
        raise ValueError("The checksum index cannot include itself")
    directories = set()
    for name in expected:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError("Unsafe expected bundle path")
        directories.update(str(parent) for parent in path.parents if str(parent) != ".")
    actual = set()
    for parent, subdirectories, files in os.walk(bundle, followlinks=False):
        for name in subdirectories:
            path = Path(parent) / name
            if path.is_symlink() or path.relative_to(bundle).as_posix() not in directories:
                raise ValueError("Unexpected bundle directory or symlink: " + str(path))
        for name in files:
            path = Path(parent) / name
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("Unexpected bundle link or special file: " + str(path))
            actual.add(path.relative_to(bundle).as_posix())
    if actual - {"SHA256SUMS.json"} != expected:
        raise ValueError("Unexpected or missing bundle files: " + repr(sorted((actual - {"SHA256SUMS.json"}) ^ expected)))
    checksums = {name: digest_file(bundle / name) for name in sorted(expected)}
    write_json(bundle / "SHA256SUMS.json", checksums)
    return checksums


def verify_source_archive(archive_path, checksums):
    """Read every exported member and reject extras, aliases or damaged bytes."""
    seen = set()
    with tarfile.open(archive_path, "r|") as archive:
        for member in archive:
            name = member.name.removeprefix("./")
            if member.isdir():
                continue
            if not member.isfile() or name in seen or name not in checksums.keys() | {"SHA256SUMS.json"}:
                raise ValueError("Unexpected exported archive member")
            seen.add(name)
            with archive.extractfile(member) as stream:
                if name == "SHA256SUMS.json":
                    if json.load(stream) != checksums:
                        raise ValueError("Exported checksum index changed")
                else:
                    digest = hashlib.sha256()
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                    if digest.hexdigest() != checksums[name]:
                        raise ValueError("Exported archive member hash mismatch: " + name)
    if seen != checksums.keys() | {"SHA256SUMS.json"}:
        raise ValueError("Exported source archive is incomplete")
    return len(seen)


def download(url, target, expected=None):
    """Fetch HTTPS bytes and reject length/digest mismatches before publication."""
    target = Path(target)
    if target.exists():
        if not target.is_file() or target.is_symlink():
            raise ValueError("Unexpected download cache entry")
        if expected is None or (target.stat().st_size == expected["bytes"] and digest_file(target) == expected["sha256"]):
            return
        raise ValueError("Previously downloaded file no longer matches: " + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".download-", dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            with urllib.request.urlopen(url, timeout=60) as response:
                if not response.url.startswith("https://"):
                    raise ValueError("Source download redirected outside HTTPS")
                copied = 0
                while block := response.read(1024 * 1024):
                    copied += len(block)
                    if expected is not None and copied > expected["bytes"]:
                        raise ValueError("Source exceeds authenticated size: " + url)
                    stream.write(block)
        if expected is not None and (temporary.stat().st_size != expected["bytes"] or digest_file(temporary) != expected["sha256"]):
            raise ValueError("Downloaded source size/SHA256 mismatch: " + url)
        os.rename(temporary, target)
    finally:
        # A failed transfer must never become an unverified extra component in
        # the eventual source bundle. Only this call's unique temporary is used.
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def archive_members(archive):
    members = {}
    for member in archive.getmembers():
        name = member.name.removeprefix("./")
        if name in ("", "."):
            continue
        parts = PurePosixPath(name).parts
        if name.startswith("/") or ".." in parts or name in members:
            raise ValueError("Ambiguous or unsafe input archive member")
        members[name] = member
    return members


def read_archive_file(archive, members, path):
    """Resolve guest links without extracting or resolving anything on the host."""
    pending, resolved, links = list(PurePosixPath(path).parts), [], 0
    while pending:
        component = pending.pop(0)
        if component in ("", "."):
            continue
        if component == "..":
            if not resolved:
                raise ValueError("Archive link escapes guest")
            resolved.pop()
            continue
        resolved.append(component)
        key = "/".join(resolved)
        member = members.get(key)
        if member is not None and (member.issym() or member.islnk()):
            links += 1
            if links > 40:
                raise ValueError("Archive link cycle")
            target = member.linkname
            resolved = [] if member.islnk() or target.startswith("/") else resolved[:-1]
            pending = list(PurePosixPath(target.lstrip("/")).parts) + pending
    member = members.get("/".join(resolved))
    if member is None or not member.isfile():
        raise ValueError("Missing regular archive file: " + path)
    with archive.extractfile(member) as stream:
        return stream.read(), "/".join(resolved)


def prepare_base(base, bundle):
    """Verify the completed local build inputs and retain their exact identity."""
    expected = set()
    checksums = json.loads((base / "SHA256SUMS.json").read_text())
    for name, digest in checksums.items():
        safe_filename(name)
        if not SHA256.fullmatch(digest) or digest_file(base / name) != digest:
            raise ValueError("Base artifact SHA256 mismatch: " + name)
    manifest = json.loads((base / "manifest.json").read_text())
    rootfs = manifest["rootfs"]
    if checksums.get(rootfs["archive"]) != rootfs["sha256"] or manifest["architecture"] != "arm64":
        raise ValueError("Unexpected base manifest")
    records = json.loads((base / "downloaded-packages.json").read_text())
    if len(records) != manifest["installedPackageCount"]:
        raise ValueError("Base package count mismatch")
    origin = bundle / "base-evidence"
    origin.mkdir(exist_ok=True)
    for name in ("manifest.json", "SHA256SUMS.json", "downloaded-packages.json", "installed-packages.tsv", "repository-signatures.json"):
        # Do not import DrvFS's synthetic 0777 permissions into the ext4 bundle.
        shutil.copyfile(base / name, origin / name)
        expected.add((origin / name).relative_to(bundle).as_posix())
    provenance = base / "debian-13-arm64-provenance.tar.gz"
    with tarfile.open(provenance, "r:gz") as archive:
        members = archive_members(archive)
        for name in ("bootstrap-debian-archive-keyring.gpg", "seed-debian-archive-keyring.gpg",
                     "keyring-bootstrap/trust-chain.json", "build_rootfs.py", "verify_rootfs.py"):
            data, _ = read_archive_file(archive, members, name)
            destination = origin / Path(name).name
            destination.write_bytes(data)
            expected.add(destination.relative_to(bundle).as_posix())
        # Validate Source metadata from the exact preserved .deb bytes, not a
        # later binary index whose package candidate may have moved.
        for record in records:
            name = safe_filename(record["archive"])
            data, _ = read_archive_file(archive, members, "deb-packages/" + name)
            if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError("Preserved binary archive mismatch")
            with tempfile.NamedTemporaryFile(dir=bundle.parent, suffix=".deb") as stream:
                stream.write(data)
                stream.flush()
                output = subprocess.check_output(["dpkg-deb", "--show", "--showformat=${Package}\t${Version}\t${Architecture}\t${Source}", stream.name], text=True)
            if output.split("\t") != [record["package"], record["version"], record["architecture"], record["source"]]:
                raise ValueError("Binary Source metadata mismatch")
    keyring = origin / "bootstrap-debian-archive-keyring.gpg"
    trust = json.loads((origin / "trust-chain.json").read_text())
    if digest_file(keyring) != trust["keyringSha256"]:
        raise ValueError("Base archive keyring differs from authenticated bootstrap")
    notices = bundle / "notices"
    notices.mkdir(exist_ok=True)
    notice_records = []
    with tarfile.open(base / rootfs["archive"], "r:gz") as archive:
        members = archive_members(archive)
        for record in records:
            data, resolved = read_archive_file(archive, members, "usr/share/doc/" + record["package"] + "/copyright")
            target = notices / (record["package"] + ".copyright")
            target.write_bytes(data)
            expected.add(target.relative_to(bundle).as_posix())
            notice_records.append({"package": record["package"], "path": str(target.relative_to(bundle)), "rootfsPath": resolved, "sha256": digest_file(target)})
        common = notices / "common-licenses"
        common.mkdir(exist_ok=True)
        for name, member in members.items():
            if name.startswith("usr/share/common-licenses/") and not member.isdir():
                data, _ = read_archive_file(archive, members, name)
                target = common / safe_filename(PurePosixPath(name).name)
                target.write_bytes(data)
                expected.add(target.relative_to(bundle).as_posix())
    write_json(bundle / "notices.json", notice_records)
    expected.add("notices.json")
    return manifest, records, keyring, expected


def authenticate_index(bundle, suite, url, keyring):
    directory = bundle / "repositories" / suite
    directory.mkdir(parents=True, exist_ok=True)
    release = directory / "InRelease"
    download(url + "/dists/" + suite + "/InRelease", release)
    result = subprocess.run(["gpgv", "--status-fd=1", "--keyring", str(keyring), str(release)],
                            capture_output=True, text=True, check=True)
    if "[GNUPG:] VALIDSIG " not in result.stdout:
        raise ValueError("No valid source repository signature")
    (directory / "signature.txt").write_text(result.stdout + result.stderr)
    # Parse only the authenticated cleartext message, not armor or signatures.
    text = release.read_text()
    body = text.split("\n\n", 1)[1].split("\n-----BEGIN PGP SIGNATURE-----", 1)[0]
    body = "\n".join(line[2:] if line.startswith("- ") else line for line in body.splitlines())
    fields, = parse_deb822(body)
    if fields.get("Codename") != suite or fields.get("Origin") != "Debian":
        raise ValueError("Unexpected signed repository identity")
    now = datetime.now(timezone.utc)
    if parsedate_to_datetime(fields["Date"]) > now:
        raise ValueError("Repository metadata is dated in the future")
    if "Valid-Until" in fields and parsedate_to_datetime(fields["Valid-Until"]) < now:
        raise ValueError("Repository metadata expired")
    if suite != "trixie" and "Valid-Until" not in fields:
        raise ValueError("Updates/security metadata lacks expiration")
    expected = None
    for line in fields["SHA256"].splitlines():
        if not line.strip():
            continue
        digest, size, name = line.split()
        if name == "main/source/Sources.xz":
            if expected is not None or not SHA256.fullmatch(digest):
                raise ValueError("Ambiguous source index digest")
            expected = {"sha256": digest, "bytes": int(size)}
    if expected is None:
        raise ValueError("Signed release does not describe source index")
    source_index = directory / "Sources.xz"
    download(url + "/dists/" + suite + "/main/source/Sources.xz", source_index, expected)
    with lzma.open(source_index, "rt", encoding="utf-8") as stream:
        stanzas = parse_deb822(stream.read())
    evidence = {"suite": suite, "url": url, "inReleaseSha256": digest_file(release),
                "sourceIndex": expected, "date": fields["Date"], "validUntil": fields.get("Valid-Until"),
                "keyringSha256": digest_file(keyring), "sourceRecordCount": len(stanzas)}
    return stanzas, evidence


def select_sources(records, indexes):
    wanted = {source_identity(record) for record in records}
    selected = {}
    for suite, url, stanzas in indexes:
        for stanza in stanzas:
            identity = (stanza["Package"], stanza["Version"])
            if identity not in wanted:
                continue
            files = source_files(stanza)
            if sum(item["name"].endswith(".dsc") for item in files) != 1:
                raise ValueError("Expected exactly one source descriptor")
            directory = stanza["Directory"]
            if not directory.startswith("pool/") or ".." in PurePosixPath(directory).parts or "\\" in directory:
                raise ValueError("Unsafe Debian source directory")
            value = {"package": identity[0], "version": identity[1], "suite": suite,
                     "repository": url, "directory": directory, "files": files, "stanza": stanza}
            if identity in selected and sorted(selected[identity]["files"], key=lambda item: item["name"]) != sorted(files, key=lambda item: item["name"]):
                raise ValueError("Conflicting exact source version across authenticated indexes")
            selected.setdefault(identity, value)
    missing = wanted - selected.keys()
    if missing:
        raise ValueError("Exact corresponding sources absent from authenticated indexes: " + repr(sorted(missing)))
    return [selected[key] for key in sorted(selected)]


def validate_descriptor(directory, record):
    descriptor = next(item for item in record["files"] if item["name"].endswith(".dsc"))
    text = (directory / descriptor["name"]).read_text()
    if text.startswith("-----BEGIN PGP SIGNED MESSAGE-----"):
        text = text.split("\n\n", 1)[1].split("\n-----BEGIN PGP SIGNATURE-----", 1)[0]
        text = "\n".join(line[2:] if line.startswith("- ") else line for line in text.splitlines())
    stanza, = parse_deb822(text)
    if stanza.get("Source") != record["package"] or stanza.get("Version") != record["version"]:
        raise ValueError("Source descriptor identity differs from authenticated index")
    declared = source_files(stanza)
    expected = [item for item in record["files"] if not item["name"].endswith(".dsc")]
    if sorted(declared, key=lambda item: item["name"]) != sorted(expected, key=lambda item: item["name"]):
        raise ValueError("Descriptor source component hashes differ from authenticated index")


def collect(base, resume=None):
    if sys.platform != "linux" or os.geteuid() != 0 or Path("/system/build.prop").exists():
        raise RuntimeError("Collection requires host Linux root, never Android")
    base = Path(base).resolve(strict=True)
    if resume:
        work = checked_directory(Path(resume))
        if work.parent != Path("/var/tmp") or not work.name.startswith("foldgpt-rootfs-sources-"):
            raise ValueError("Unexpected source collection directory")
        state = json.loads((work / "state.json").read_text())
        if state != {"base": str(base), "schemaVersion": 1}:
            raise ValueError("Resumed base differs from initial source collection")
    else:
        work = Path(tempfile.mkdtemp(prefix="foldgpt-rootfs-sources-", dir="/var/tmp"))
        write_json(work / "state.json", {"base": str(base), "schemaVersion": 1})
    print("Source work directory: " + str(work), flush=True)
    bundle = work / "bundle"
    bundle.mkdir(exist_ok=True)
    checked_directory(bundle)
    validate_resume_tree(bundle)
    base_manifest, binaries, keyring, expected_paths = prepare_base(base, bundle)
    print("Validated exact binary metadata and notices: " + str(len(binaries)), flush=True)
    indexes, repository_evidence = [], []
    for suite, url in REPOSITORIES:
        stanzas, evidence = authenticate_index(bundle, suite, url, keyring)
        indexes.append((suite, url, stanzas))
        repository_evidence.append(evidence)
        expected_paths.update("repositories/" + suite + "/" + name for name in ("InRelease", "Sources.xz", "signature.txt"))
    selected = select_sources(binaries, indexes)
    print("Authenticated exact source versions: " + str(len(selected)), flush=True)
    write_json(bundle / "repositories.json", repository_evidence)
    write_json(bundle / "source-packages.json", selected)
    for record in selected:
        expected_paths.update("sources/" + record["package"] + "/" + record["version"].replace(":", "%3A") + "/" + item["name"] for item in record["files"])

    def retrieve(record):
        directory = bundle / "sources" / record["package"] / record["version"].replace(":", "%3A")
        directory.mkdir(parents=True, exist_ok=True)
        for item in record["files"]:
            download(record["repository"] + "/" + record["directory"] + "/" + item["name"], directory / item["name"], item)
        validate_descriptor(directory, record)
        print("Verified " + record["package"] + " " + record["version"], flush=True)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(retrieve, selected))
    mapping = [{"binary": item["package"], "binaryVersion": item["version"], "architecture": item["architecture"],
                "binarySha256": item["sha256"], "source": source_identity(item)[0], "sourceVersion": source_identity(item)[1]}
               for item in binaries]
    write_json(bundle / "binary-source-map.json", mapping)
    # Capture the source loaded for this run even if the workspace is edited
    # while a long transfer is in progress.
    (bundle / "rootfs_sources.py").write_bytes(COLLECTOR_SOURCE)
    manifest = {"schemaVersion": 1, "kind": "debian-exact-corresponding-source-inputs", "binaryCount": len(binaries),
                "sourceCount": len(selected), "sourceFileCount": sum(len(item["files"]) for item in selected),
                "sourceBytes": sum(file["bytes"] for item in selected for file in item["files"]),
                "rootfsSha256": base_manifest["rootfs"]["sha256"], "baseProvenanceSha256": digest_file(base / "debian-13-arm64-provenance.tar.gz"),
                "collectedAt": datetime.now(timezone.utc).isoformat(), "noticeCount": len(mapping),
                "authentication": "Original local binary provenance; current Debian-signed InRelease -> Sources.xz SHA256 -> exact source component SHA256; .dsc component cross-check",
                "limits": ["No public binary release or legal compliance certification", "Original build uses authenticated live versions; not a reproducible rebuild",
                           "No OpenAI or Android components included", "Exact Debian source packages and installed notices retained; no per-license legal determination",
                           "Build dependency closure and statically linked component source versions are not reconstructed; rust-sequoia-sqv has external Rust build dependencies",
                           "Individual uploader .dsc signatures are retained but trust is established through Debian archive signatures"]}
    write_json(bundle / "manifest.json", manifest)
    expected_paths.update(("repositories.json", "source-packages.json", "binary-source-map.json", "rootfs_sources.py", "manifest.json"))
    checksums = write_bundle_checksums(bundle, expected_paths)
    archive = work / "debian-13-arm64-corresponding-sources.tar"
    subprocess.run(["tar", "--sort=name", "--numeric-owner", "--format=posix", "--pax-option=delete=atime,delete=ctime",
                    "-C", str(bundle), "-cf", str(archive), "."], check=True)
    verified_members = verify_source_archive(archive, checksums)
    archive_digest = digest_file(archive)
    output = ROOT / "downloads/install"
    target = output / ("debian-sources-" + base_manifest["rootfs"]["sha256"][:16] + "-" + archive_digest[:16])
    staging = Path(tempfile.mkdtemp(prefix=".sources-", dir=output))
    for path in (archive, bundle / "manifest.json", bundle / "binary-source-map.json", bundle / "source-packages.json", bundle / "repositories.json", bundle / "notices.json"):
        shutil.copy2(path, staging / path.name)
        if digest_file(staging / path.name) != digest_file(path):
            raise ValueError("Source artifact transfer digest mismatch")
    write_json(staging / "SHA256SUMS.json", {path.name: digest_file(path) for path in sorted(staging.iterdir())})
    verify_source_archive(staging / archive.name, checksums)
    from build_rootfs import publish_directory
    publish_directory(staging, target)
    print(json.dumps({"output": str(target), "sha256": archive_digest, "bytes": archive.stat().st_size,
                      "sourceCount": len(selected), "binaryCount": len(binaries), "verifiedArchiveMembers": verified_members,
                      "workDirectory": str(work)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path, help="Completed pristine rootfs artifact directory")
    parser.add_argument("--resume", type=Path, help="Previously printed /var/tmp source work directory")
    args = parser.parse_args()
    collect(args.base, args.resume)
