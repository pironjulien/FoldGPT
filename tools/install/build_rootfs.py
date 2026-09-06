"""Build a pristine Debian 13 ARM64 base from authenticated Debian repositories.

Host Linux root and QEMU user-mode are build tools only. Nothing is installed
on Android; no OpenAI client, account, keyring, GPU candidate or shim is included.
The source rootfs and evidence stay on ext4 until the completed archive is made.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
SUITE = "trixie"
ARCH = "arm64"
MIRROR = "https://deb.debian.org/debian"
SECURITY = "https://security.debian.org/debian-security"
SEED_KEYRING = Path("/usr/share/keyrings/debian-archive-keyring.gpg")
PACKAGES = (
    "debian-archive-keyring", "ca-certificates", "bash", "coreutils", "mawk",
    "python3", "python3-websockets", "python3-secretstorage", "dbus-x11",
    "gnome-keyring", "xfwm4", "wmctrl", "xkb-data", "fonts-dejavu-core",
    "fonts-noto-core", "fonts-noto-color-emoji", "fontconfig", "git", "xz-utils",
    "libgtk-3-0t64", "libnotify4", "libnss3", "xdg-utils", "libatspi2.0-0t64",
    "libdrm2", "libgbm1", "libxcb-dri3-0", "libglib2.0-bin", "libasound2t64",
    "libatk-bridge2.0-0t64", "libatk1.0-0t64", "libcairo2", "libcups2t64",
    "libdbus-1-3", "libexpat1", "libgcc-s1", "libgdk-pixbuf-2.0-0", "libgl1",
    "libglib2.0-0t64", "libnspr4", "libpango-1.0-0", "libstdc++6", "libudev1",
    "libusb-1.0-0", "libx11-6", "libx11-xcb1", "libxcb1", "libxcomposite1",
    "libxdamage1", "libxext6", "libxfixes3", "libxkbcommon0", "libxrandr2",
    "libvulkan1", "mesa-vulkan-drivers",
)


def digest_file(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def run(command, log=None, **kwargs):
    command = [str(item) for item in command]
    if log is None:
        return subprocess.check_output(command, text=True, **kwargs)
    with Path(log).open("ab") as stream:
        stream.write(("COMMAND " + shlex.join(command) + "\n").encode())
        stream.flush()
        subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT, **kwargs)


def prepare_apt_directories(parent):
    for suffix in ("lists/partial", "archives/partial"):
        path = parent / suffix
        path.mkdir(parents=True, mode=0o755)
        account = pwd.getpwnam("_apt")
        os.chown(path, account.pw_uid, account.pw_gid)


def bootstrap_keyring(work):
    """Use trusted Bookworm metadata to acquire the keyring containing Trixie keys."""
    directory = work / "keyring-bootstrap"
    directory.mkdir(mode=0o755)
    prepare_apt_directories(directory)
    (directory / "status").write_text("")
    (directory / "sources.list").write_text(
        f"deb [signed-by={SEED_KEYRING}] {MIRROR} bookworm main\n")
    options = [
        "-o", f"Dir::Etc::sourcelist={directory / 'sources.list'}",
        "-o", "Dir::Etc::sourceparts=-",
        "-o", f"Dir::State::status={directory / 'status'}",
        "-o", f"Dir::State::lists={directory / 'lists'}",
        "-o", f"Dir::Cache::archives={directory / 'archives'}",
        "-o", f"Dir::Cache::pkgcache={directory / 'pkgcache.bin'}",
        "-o", f"Dir::Cache::srcpkgcache={directory / 'srcpkgcache.bin'}",
        "-o", f"Dir::Etc::Trusted={SEED_KEYRING}", "-o", "Dir::Etc::TrustedParts=-",
        "-o", "Acquire::AllowInsecureRepositories=false",
        "-o", "APT::Get::AllowUnauthenticated=false",
    ]
    log = directory / "apt.log"
    run(["apt-get", *options, "update"], log)
    run(["apt-get", *options, "--download-only", "--no-install-recommends", "-y",
         "install", "debian-archive-keyring"], log)
    metadata = run(["apt-cache", *options, "show", "--no-all-versions", "debian-archive-keyring"])
    (directory / "keyring-package-metadata.txt").write_text(metadata)
    expected = [line.split(": ", 1)[1] for line in metadata.splitlines() if line.startswith("SHA256: ")]
    packages = list((directory / "archives").glob("debian-archive-keyring_*.deb"))
    if len(packages) != 1 or len(expected) != 1 or digest_file(packages[0]) != expected[0]:
        raise RuntimeError("Authenticated keyring package digest did not match")
    extracted = directory / "extracted"
    run(["dpkg-deb", "--extract", packages[0], extracted], log)
    keyring = extracted / "usr/share/keyrings/debian-archive-keyring.gpg"
    if not keyring.is_file():
        raise RuntimeError("Debian archive keyring missing from authenticated package")
    evidence = {
        "bootstrapRepository": MIRROR, "bootstrapSuite": "bookworm",
        "seedKeyringSha256": digest_file(SEED_KEYRING),
        "seedKeyringPackage": run(["dpkg-query", "-W", "-f=${Version}", "debian-archive-keyring"]),
        "package": packages[0].name, "packageSha256": expected[0],
        "keyringSha256": digest_file(keyring),
    }
    write_json(directory / "trust-chain.json", evidence)
    return keyring


def customize(root, evidence):
    """mmdebstrap customize hook, before temporary mount teardown and cleanup."""
    root, evidence = Path(root), Path(evidence)
    if not root.is_absolute() or not str(root).startswith("/var/tmp/foldgpt-rootfs-"):
        raise ValueError("Unexpected disposable rootfs location")
    # Do not distribute the build host's network identity or resolver settings.
    (root / "etc/hostname").write_text("foldgpt\n")
    (root / "etc/hosts").write_text("127.0.0.1 localhost\n::1 localhost ip6-localhost ip6-loopback\n")
    (root / "etc/resolv.conf").write_text(
        "# DNS is provisioned by the Android bootstrap at activation.\n")
    sources = "".join(
        f"deb [signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] {uri} {suite} main\n"
        for uri, suite in ((MIRROR, SUITE), (MIRROR, SUITE + "-updates"),
                           (SECURITY, SUITE + "-security")))
    (root / "etc/apt/sources.list").write_text(sources)
    for name in ("proc", "sys", "dev", "system", "apex", "tmp", "run", "home"):
        (root / name).mkdir(exist_ok=True)
    records = []
    # These bytes were acquired by APT against authenticated package indexes.
    # Preserve them in provenance, not in the phone payload's download cache.
    packages = evidence / "deb-packages"
    packages.mkdir()
    for path in sorted((root / "var/cache/apt/archives").glob("*.deb")):
        fields = run(["dpkg-deb", "--show", "--showformat=${Package}\t${Version}\t${Architecture}\t${Source}\n", path]).rstrip("\n").split("\t")
        if len(fields) != 4:
            raise RuntimeError("Unexpected Debian package metadata")
        target = packages / path.name
        os.link(path, target)
        records.append({"package": fields[0], "version": fields[1], "architecture": fields[2],
                        "source": fields[3], "archive": path.name,
                        "sha256": digest_file(path), "bytes": path.stat().st_size})
    if not records:
        raise RuntimeError("No authenticated Debian package archives preserved")
    write_json(evidence / "downloaded-packages.json", records)
    # Package inventory is static metadata; no profile or guest process is used.
    inventory = run(["dpkg-query", "--admindir=" + str(root / "var/lib/dpkg"), "-W",
                     "-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n"])
    (evidence / "installed-packages.tsv").write_text(inventory)
    wanted = {(line.split("\t")[0].split(":")[0], line.split("\t")[1], line.split("\t")[2])
              for line in inventory.splitlines() if line.split("\t")[3].startswith("ii")}
    preserved = {(item["package"], item["version"], item["architecture"]) for item in records}
    if not wanted.issubset(preserved):
        raise RuntimeError("Missing downloaded .deb provenance for installed packages: " + str(sorted(wanted - preserved)))
    lists = evidence / "apt-lists"
    lists.mkdir()
    for path in (root / "var/lib/apt/lists").iterdir():
        if path.is_file() and path.name != "lock":
            shutil.copy2(path, lists / path.name)
    for path in (root / "var/cache/apt/archives").glob("*.deb"):
        path.unlink()


def validate_signatures(work, evidence, keyring):
    result = []
    # Bookworm is cross-signed by its old keys and Trixie's new key. APT already
    # authenticated bootstrap with the seed keys; recheck all signatures using
    # the updated keyring obtained through that authenticated bootstrap.
    for parent, ring in ((work / "keyring-bootstrap/lists", keyring),
                         (evidence / "apt-lists", keyring)):
        for path in sorted(parent.glob("*InRelease")):
            signature = run(["gpgv", "--status-fd=1", "--keyring", ring, path], stderr=subprocess.STDOUT)
            if "[GNUPG:] VALIDSIG " not in signature:
                raise RuntimeError("No valid repository signature")
            name = path.name + ".gpgv.txt"
            (evidence / name).write_text(signature)
            result.append({"inRelease": path.name, "sha256": digest_file(path),
                           "keyringSha256": digest_file(ring), "verification": name})
    if len(result) != 4:
        raise RuntimeError("Expected authenticated Bookworm, Trixie, updates and security metadata")
    write_json(evidence / "repository-signatures.json", result)


def publish_directory(staging, target):
    """Atomically promote a completed directory, refusing any existing target."""
    # WSL's DrvFS does not implement Linux RENAME_NOREPLACE. Native Windows
    # os.rename has the required no-replacement semantics on the same NTFS
    # volume. Use that actual filesystem API rather than weakening the flag.
    if (str(staging).startswith("/mnt/c/") and "microsoft" in Path("/proc/version").read_text().lower()
            and shutil.which("python.exe")):
        source_windows = run(["wslpath", "-w", staging]).strip()
        target_windows = run(["wslpath", "-w", target]).strip()
        windows_publish = (
            "import os,sys\n"
            "if os.name != 'nt':\n"
            "    raise RuntimeError('Native Windows Python is required for NTFS publication')\n"
            "os.rename(sys.argv[1],sys.argv[2])\n"
        )
        run(["python.exe", "-X", "utf8", "-c", windows_publish,
             source_windows, target_windows], stderr=subprocess.STDOUT)
        return
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    libc.renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    libc.renameat2.restype = ctypes.c_int
    if libc.renameat2(-100, os.fsencode(staging), -100, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(target))


def build():
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("Build requires host Linux root; never run this on Android")
    if Path("/system/build.prop").exists() or not Path("/etc/os-release").is_file():
        raise RuntimeError("This is a host Linux build tool, not an Android installer")
    for program in ("mmdebstrap", "apt-get", "apt-cache", "dpkg-deb", "dpkg-query",
                    "gpgv", "arch-test", "tar", "gzip", "chroot", "python3"):
        if shutil.which(program) is None:
            raise RuntimeError("Missing host prerequisite: " + program)
    run(["arch-test", ARCH])
    output = ROOT / "downloads/install"
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="foldgpt-rootfs-", dir="/var/tmp"))
    # Only public Debian inputs are staged here. APT's _apt process must traverse.
    work.chmod(0o755)
    evidence = work / "evidence"
    evidence.mkdir()
    root = work / "rootfs"
    print("Build directory: " + str(work), flush=True)
    print("Authenticating current Debian archive keyring through Bookworm", flush=True)
    keyring = bootstrap_keyring(work)
    hook = shlex.quote(sys.executable) + " " + shlex.quote(str(Path(__file__).resolve()))
    hook += ' customize "$1" ' + shlex.quote(str(evidence))
    command = ["mmdebstrap", "--mode=root", "--variant=apt", "--format=directory",
               "--architectures=" + ARCH, "--keyring=" + str(keyring),
               "--include=" + ",".join(PACKAGES), "--skip=essential/unlink",
               "--skip=cleanup/apt", "--aptopt=Acquire::AllowInsecureRepositories false",
               "--aptopt=APT::Get::AllowUnauthenticated false", "--customize-hook=" + hook,
               SUITE, str(root),
               f"deb {MIRROR} {SUITE} main", f"deb {MIRROR} {SUITE}-updates main",
               f"deb {SECURITY} {SUITE}-security main"]
    write_json(evidence / "build-command.json", command)
    print("Building and configuring pristine Debian ARM64 (host QEMU only)", flush=True)
    run(command, evidence / "mmdebstrap.log")
    finish(work)


def finish(work):
    """Verify and package an already completed, inactive disposable build."""
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("Finalization requires host Linux root")
    work = Path(work)
    if work.resolve(strict=True) != work or work.parent != Path("/var/tmp") or not work.name.startswith("foldgpt-rootfs-"):
        raise ValueError("Unexpected disposable build directory")
    root, evidence = work / "rootfs", work / "evidence"
    dev = root / "dev"
    # This CLI can resume a supplied build path. Validate every directory that
    # controls cleanup or evidence writes before the first filesystem mutation.
    # Root ownership and no group/other writes prevent an unprivileged process
    # from swapping /dev after validation. Nested symlinks are unlinked, never
    # traversed, by the cleanup below.
    for directory in (work, root, evidence, dev):
        metadata = directory.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or directory.resolve(strict=True) != directory:
            raise ValueError("Build directories must be real directories without symlink aliases: " + str(directory))
        if metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise ValueError("Build directories must be root-owned and not group/other writable: " + str(directory))
    if not dev.resolve(strict=True).is_relative_to(root):
        raise ValueError("Build /dev must resolve inside the rootfs")
    output = ROOT / "downloads/install"
    keyring = work / "keyring-bootstrap/extracted/usr/share/keyrings/debian-archive-keyring.gpg"
    # mmdebstrap has finished its mount cleanup. Never archive a host bind mount.
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        point = line.split()[4].replace("\\040", " ")
        if point == str(root) or point.startswith(str(root) + "/"):
            raise RuntimeError("Rootfs still contains a mount; refusing archive")
    # Android provides /dev through a bind. Device nodes cannot be installed by
    # an ordinary app UID. Remove only mmdebstrap's disposable /dev entries.
    for path in dev.iterdir():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    validate_signatures(work, evidence, keyring)
    print("Verifying pristine rootfs and read-only ARM64 probes", flush=True)
    verification = run([sys.executable, "-B", ROOT / "tools/install/verify_rootfs.py", root])
    (evidence / "rootfs-verification.json").write_text(verification)
    host_packages = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\n",
                         "mmdebstrap", "debootstrap", "debian-archive-keyring", "qemu-user-static", "arch-test"])
    (evidence / "host-toolchain.tsv").write_text(host_packages)
    for source in ("build_rootfs.py", "verify_rootfs.py"):
        shutil.copy2(ROOT / "tools/install" / source, evidence / source)
    shutil.copy2(SEED_KEYRING, evidence / "seed-debian-archive-keyring.gpg")
    shutil.copy2(keyring, evidence / "bootstrap-debian-archive-keyring.gpg")
    shutil.copytree(work / "keyring-bootstrap", evidence / "keyring-bootstrap", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("pkgcache.bin", "srcpkgcache.bin", "extracted", "partial", "lock"))
    archive = work / "debian-13-arm64-rootfs.tar.gz"
    print("Archiving verified rootfs and preserving package provenance", flush=True)
    with archive.open("wb") as stream:
        tar = subprocess.Popen(["tar", "--sort=name", "--numeric-owner", "--format=posix",
                                "--pax-option=delete=atime,delete=ctime", "-C", str(root), "-cf", "-", "."], stdout=subprocess.PIPE)
        try:
            gzip = subprocess.run(["gzip", "-n", "-6"], stdin=tar.stdout, stdout=stream, check=True)
            tar.stdout.close()
            if tar.wait() != 0:
                raise RuntimeError("Rootfs tar failed")
        finally:
            if tar.poll() is None:
                tar.terminate()
                tar.wait()
    archive_digest = digest_file(archive)
    records = json.loads((evidence / "downloaded-packages.json").read_text())
    manifest = {"schemaVersion": 1, "kind": "pristine-debian-base", "suite": SUITE,
                "debianMajor": 13, "architecture": ARCH, "builtAtUnix": int(time.time()),
                "rootfs": {"archive": archive.name, "sha256": archive_digest, "bytes": archive.stat().st_size},
                "requestedPackages": list(PACKAGES), "installedPackageCount": len(records),
                "openaiClientIncluded": False, "accountProfileIncluded": False,
                "keyringInitialized": False, "compatibilityShimIncluded": False,
                "foldgptGpuCandidateIncluded": False, "androidTested": False,
                "buildOnlyEmulation": "QEMU aarch64 user-mode through host binfmt; no QEMU in rootfs",
                "verification": json.loads(verification),
                "limits": ["Not an APK or activated Android rootfs", "No release signing/authenticated update channel yet",
                           "Android activation must provision DNS, guest identity and a new keyring",
                           "Package versions follow authenticated live Debian repositories; not bit-for-bit pinned"]}
    write_json(evidence / "manifest.json", manifest)
    evidence_archive = work / "debian-13-arm64-provenance.tar.gz"
    run(["tar", "--sort=name", "--numeric-owner", "-C", evidence, "-czf", evidence_archive, "."])
    target = output / ("debian-13-arm64-" + archive_digest[:16])
    if target.exists():
        raise FileExistsError("Refusing to replace existing rootfs output: " + str(target))
    staging = Path(tempfile.mkdtemp(prefix=".rootfs-", dir=output))
    try:
        for path in (archive, evidence_archive, evidence / "manifest.json", evidence / "installed-packages.tsv",
                     evidence / "downloaded-packages.json", evidence / "repository-signatures.json"):
            shutil.copy2(path, staging / path.name)
            if digest_file(staging / path.name) != digest_file(path):
                raise RuntimeError("Artifact transfer digest mismatch")
        write_json(staging / "SHA256SUMS.json", {path.name: digest_file(path) for path in sorted(staging.iterdir())})
        # Link-free output directory was created by this process, and is never
        # used for runtime activation. Linux NOREPLACE protects concurrent builds.
        publish_directory(staging, target)
    except BaseException:
        # Keep failed public build outputs for inspection; do not remove any
        # source rootfs or potentially existing final revision automatically.
        raise
    print(json.dumps({"output": str(target), "sha256": archive_digest,
                      "buildDirectory": str(work), "androidTested": False}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("build", "customize", "finalize"))
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    if args.operation == "customize":
        if len(args.paths) != 2:
            parser.error("customize requires disposable ROOTFS and EVIDENCE directories")
        customize(*args.paths)
    elif args.operation == "finalize":
        if len(args.paths) != 1:
            parser.error("finalize requires one completed disposable BUILD directory")
        finish(Path(args.paths[0]))
    else:
        if args.paths:
            parser.error("build does not take paths")
        build()
