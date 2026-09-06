"""Read-only checks for a pristine Debian 13 ARM64 guest, not Android validation.

The caller supplies a completed, inactive rootfs built from authenticated Debian
inputs. This does not authenticate packages or prove execution on Android. Host
binfmt/QEMU may execute the checks; no emulator is allowed in the guest payload.
"""
import argparse
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys


DNS_TEMPLATE = b"# DNS is provisioned by the Android bootstrap at activation.\n"
REQUIRED_PACKAGES = frozenset({
    "apt", "dpkg", "debian-archive-keyring", "ca-certificates", "libc6",
    "libgcc-s1", "libstdc++6", "bash", "dash", "coreutils", "python3",
    "python3-websockets", "python3-secretstorage", "dbus-daemon", "dbus-x11",
    "gnome-keyring", "xfwm4", "wmctrl", "xkb-data", "fontconfig",
    "fonts-dejavu-core", "fonts-noto-color-emoji", "git", "libvulkan1",
    "libx11-6", "libx11-xcb1", "libxext6", "libxxf86vm1", "libdrm2",
    "libexpat1", "libxcb1", "libxcb-dri3-0", "libxcb-glx0",
    "libxcb-present0", "libxcb-randr0", "libxcb-shm0", "libxcb-sync1",
    "libxcb-xfixes0", "libxshmfence1", "zlib1g", "libzstd1",
})
MAX_TEXT_BYTES = 8 * 1024 * 1024
PROBE_TIMEOUT = 60


class VerificationError(ValueError):
    """A failed invariant; messages never include file contents or credentials."""


def guest_path(root, name):
    """Resolve Linux guest links lexically; absolute links start at guest /.

    Path.resolve() on a guest absolute symlink would read the host filesystem.
    Reject above-root traversal, cycles, missing components and special files.
    The rootfs must stay inactive and under the caller's control during checks.
    """
    pending = deque(str(name).split("/"))
    parts = []
    hops = 0
    while pending:
        part = pending.popleft()
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise VerificationError("Guest link traverses above the root")
            parts.pop()
            continue
        candidate = root.joinpath(*parts, part)
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode):
            hops += 1
            if hops > 40:
                raise VerificationError("Guest symlink cycle or excessive indirection")
            target = os.readlink(candidate)
            if target.startswith("/"):
                parts.clear()
            pending.extendleft(reversed(target.split("/")))
        else:
            if pending and not stat.S_ISDIR(info.st_mode):
                # Trailing empty components are harmless, but no traversal may
                # pass through a regular file.
                if any(p not in ("", ".") for p in pending):
                    raise VerificationError("Guest path traverses a non-directory")
            parts.append(part)
    return root.joinpath(*parts)


def read_guest(root, name, limit=MAX_TEXT_BYTES):
    path = guest_path(root, name)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise VerificationError("Expected regular guest file: " + name)
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise VerificationError("Guest metadata exceeds verification limit: " + name)
    return data


def verify_elf(root, name):
    path = guest_path(root, name)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise VerificationError("ELF target is not a regular file: " + name)
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        header = stream.read(64)
        if (len(header) != 64 or header[:4] != b"\x7fELF" or header[4:7] != b"\x02\x01\x01"
                or struct.unpack_from("<H", header, 18)[0] != 183
                or struct.unpack_from("<H", header, 16)[0] not in (2, 3)
                or struct.unpack_from("<H", header, 52)[0] != 64):
            raise VerificationError("Expected executable ELF64 little-endian AArch64: " + name)
        hasher.update(header)
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    if not path.stat().st_mode & 0o111:
        raise VerificationError("Guest executable lacks execute permissions: " + name)
    return {"path": name, "resolvedPath": str(path.relative_to(root)), "machine": "AArch64",
            "sha256": hasher.hexdigest(), "bytes": path.stat().st_size}


def verify_accounts(root):
    accounts = {}
    shadow_references = set()
    for line in read_guest(root, "etc/passwd").decode().splitlines():
        fields = line.split(":")
        if len(fields) != 7 or fields[0] in accounts:
            raise VerificationError("Invalid or duplicate passwd entry")
        name, password, uid, gid, _, _, _ = fields
        if (not uid.isdecimal() or not gid.isdecimal() or password not in ("x", "!", "*")
                or (int(uid) >= 1000 and not (name == "nobody" and int(uid) == 65534))
                or (int(uid) == 0 and name != "root")):
            raise VerificationError("Guest account is not a locked Debian system account")
        accounts[name] = int(uid)
        if password == "x":
            shadow_references.add(name)
    if accounts.get("root") != 0:
        raise VerificationError("Guest root account is missing")
    try:
        shadow = read_guest(root, "etc/shadow").decode()
    except FileNotFoundError:
        # Debian's minimal base-passwd format locks accounts directly with '*'
        # and legitimately omits shadow/passwd tooling. An unresolved 'x'
        # reference is not accepted as a proof that its password is locked.
        if shadow_references:
            raise VerificationError("Guest passwd refers to an absent shadow database")
        shadow = None
    shadow_names = set()
    for line in shadow.splitlines() if shadow is not None else ():
        fields = line.split(":")
        if len(fields) != 9 or fields[0] in shadow_names:
            raise VerificationError("Invalid or duplicate shadow entry")
        shadow_names.add(fields[0])
        if not fields[1].startswith(("!", "*")):
            raise VerificationError("A guest account password is not locked")
    if shadow is not None and shadow_names != set(accounts):
        raise VerificationError("Passwd and shadow accounts do not agree")
    for directory in ("home", "root"):
        path = guest_path(root, directory)
        allowed = {".bashrc", ".profile", ".bash_logout"} if directory == "root" else set()
        for child in path.iterdir():
            if child.name not in allowed or not stat.S_ISREG(child.lstat().st_mode):
                raise VerificationError("Guest home contains non-pristine data")
    return {"systemAccounts": len(accounts), "humanAccounts": 0, "passwordsLocked": True,
            "passwordDatabase": "shadow" if shadow is not None else "locked-passwd"}


def verify_identity(root):
    if read_guest(root, "etc/hostname") != b"foldgpt\n":
        raise VerificationError("Guest hostname is not the neutral template")
    if read_guest(root, "etc/resolv.conf") != DNS_TEMPLATE:
        raise VerificationError("Guest DNS contains data other than the activation template")
    for name in ("etc/machine-id", "var/lib/dbus/machine-id"):
        try:
            content = read_guest(root, name)
        except FileNotFoundError:
            continue
        if content:
            raise VerificationError("Guest contains an initialized machine identity")
    aliases = {"localhost", "foldgpt", "ip6-localhost", "ip6-loopback",
               "ip6-allnodes", "ip6-allrouters", "ip6-localnet", "ip6-mcastprefix"}
    addresses = {"127.0.0.1", "127.0.1.1", "::1", "ff02::1", "ff02::2", "fe00::0", "ff00::0"}
    for line in read_guest(root, "etc/hosts").decode().splitlines():
        fields = line.partition("#")[0].split()
        if fields and (len(fields) < 2 or fields[0] not in addresses or not set(fields[1:]) <= aliases):
            raise VerificationError("Guest hosts file contains non-template network identity")


def verify_pristine_tree(root):
    regular_files = 0
    elf_files = 0
    for parent, directories, names in os.walk(root, followlinks=False):
        for name in directories + names:
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            lower = name.lower()
            if (relative == "etc/ld.so.preload" or "fake_userns" in lower
                    or lower.startswith("qemu")
                    or lower in ("chatgpt", "codex", ".codex", ".ssh", ".gnupg")
                    or relative.endswith("/.local/share/keyrings")
                    or lower.startswith(("chatgpt-", "codex-"))):
                raise VerificationError("Guest contains a forbidden runtime or private-state path: " + relative)
            info = path.lstat()
            if stat.S_ISREG(info.st_mode):
                regular_files += 1
                with path.open("rb") as stream:
                    header = stream.read(20)
                if header.startswith(b"\x7fELF"):
                    if (len(header) < 20 or header[4:7] != b"\x02\x01\x01"
                            or struct.unpack_from("<H", header, 18)[0] != 183):
                        raise VerificationError("Guest contains a foreign ELF object: " + relative)
                    elf_files += 1
            elif not (stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                raise VerificationError("Pristine guest contains a special file: " + relative)
    for name in ("tmp", "run", "proc", "sys", "dev"):
        children = list(guest_path(root, name).iterdir())
        if (name == "run" and len(children) == 1 and children[0].name == "lock"
                and stat.S_ISDIR(children[0].lstat().st_mode) and not any(children[0].iterdir())):
            # Debian retains the empty /run/lock mount-point directory. Its
            # presence is not live state; populated locks are still rejected.
            continue
        if children:
            raise VerificationError("Guest contains live runtime state or mounted content: " + name)
    for name in ("var/lib/systemd/random-seed", "var/lib/urandom/random-seed"):
        if (root / name).exists() or (root / name).is_symlink():
            raise VerificationError("Guest contains an initialized random seed")
    return {"regularFiles": regular_files, "aarch64ElfFiles": elf_files}


# Executed only by the host interpreter inside an ephemeral mount namespace.
# A read-only bind prevents incidental fontconfig/Python/dpkg cache writes.
# A separate private tmpfs supplies only /dev/null, as Android's runtime bind
# would. No node is created in the rootfs and no host device tree is exposed.
READONLY_PROBE = r"""
import os,stat,subprocess,sys
root,mount,chroot,*command=sys.argv[1:]
subprocess.run([mount,'--bind',root,root],check=True,timeout=10)
subprocess.run([mount,'-o','remount,bind,ro,nosuid,nodev',root],check=True,timeout=10)
device_dir=root+'/dev'
subprocess.run([mount,'-t','tmpfs','-o','size=64k,mode=0755,nosuid,noexec','tmpfs',device_dir],check=True,timeout=10)
os.mknod(device_dir+'/null',stat.S_IFCHR|0o666,os.makedev(1,3))
subprocess.run([mount,'-o','remount,ro,nosuid,noexec',device_dir],check=True,timeout=10)
environment={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C','LC_ALL':'C',
 'HOME':'/nonexistent','PYTHONDONTWRITEBYTECODE':'1','XDG_CACHE_HOME':'/nonexistent'}
os.execve(chroot,[chroot,root,*command],environment)
"""


def probe(root, command):
    executables = {name: shutil.which(name) for name in ("unshare", "mount", "chroot")}
    if not all(executables.values()):
        raise VerificationError("Host unshare, mount and chroot are required for read-only probes")
    args = [executables["unshare"], "--mount", "--propagation", "private", sys.executable,
            "-B", "-c", READONLY_PROBE, str(root), executables["mount"], executables["chroot"], *command]
    try:
        result = subprocess.run(args, check=False, capture_output=True, text=True,
                                timeout=PROBE_TIMEOUT, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                                         "LC_ALL": "C"})
    except subprocess.TimeoutExpired as error:
        raise VerificationError("Read-only guest probe timed out: " + command[0]) from error
    if result.returncode:
        # Do not relay arbitrary guest stderr or account/file content.
        raise VerificationError("Read-only guest probe failed: " + command[0]
                                + " (exit " + str(result.returncode) + ")")
    return result.stdout


def package_inventory(text):
    packages = []
    seen = set()
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) != 4:
            raise VerificationError("Malformed dpkg inventory")
        name, version, architecture, status = fields
        if (not re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", name) or name in seen or not version
                or architecture not in ("arm64", "all") or status != "install ok installed"):
            raise VerificationError("dpkg contains foreign, incomplete or duplicate package state")
        seen.add(name)
        packages.append({"name": name, "version": version, "architecture": architecture})
    missing = REQUIRED_PACKAGES - seen
    if missing:
        raise VerificationError("Required guest packages missing: " + ", ".join(sorted(missing)))
    if not seen & {"mawk", "gawk"}:
        raise VerificationError("Guest awk implementation is missing")
    return sorted(packages, key=lambda item: item["name"])


def verify_no_mounts(root):
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        raw = line.split()[4]
        point = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), raw)
        if point == str(root) or point.startswith(str(root) + "/"):
            raise VerificationError("Guest must be inactive and contain no host mounts")


def verify(root):
    if sys.platform != "linux" or os.geteuid() != 0:
        raise VerificationError("Rootfs verification requires host Linux root for read-only mount/chroot probes")
    root = Path(root).resolve(strict=True)
    if root == Path("/") or not root.is_dir():
        raise VerificationError("Expected a separate inactive guest root directory")
    verify_no_mounts(root)
    release = {}
    for line in read_guest(root, "etc/os-release").decode().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            parsed = shlex.split(value)
            if len(parsed) == 1:
                release[key] = parsed[0]
    if release.get("ID") != "debian" or release.get("VERSION_ID") != "13":
        raise VerificationError("Guest is not Debian 13")
    verify_identity(root)
    accounts = verify_accounts(root)
    tree = verify_pristine_tree(root)
    elfs = [verify_elf(root, name) for name in ("usr/bin/dash", "usr/bin/python3", "usr/bin/git")]
    xkb = root / "usr/share/X11/xkb/rules/base"
    # Deliberately native-host resolution: Xlorie reads these files outside PRoot.
    native_xkb = xkb.resolve(strict=True)
    if not native_xkb.is_relative_to(root) or not native_xkb.is_file() or not os.access(native_xkb, os.R_OK):
        raise VerificationError("XKB rules are not directly accessible inside the root from Android")
    if not native_xkb.stat().st_mode & 0o400:
        raise VerificationError("XKB rules lack owner read permission for Android extraction")
    for directory in (native_xkb.parent, *native_xkb.parent.parents):
        if not directory.is_relative_to(root):
            break
        if not directory.stat().st_mode & 0o100:
            raise VerificationError("XKB path lacks owner search permission")
    if not read_guest(root, "usr/share/X11/xkb/rules/base"):
        raise VerificationError("Guest XKB rules are empty")
    for name in ("var/lib/dpkg/status", "usr/share/keyrings/debian-archive-keyring.gpg",
                 "etc/ssl/certs/ca-certificates.crt", "usr/share/common-licenses/GPL-3"):
        if not read_guest(root, name):
            raise VerificationError("Required package metadata, trust store or notice is empty: " + name)
    apt = guest_path(root, "etc/apt")
    sources = [apt / "sources.list", *(apt / "sources.list.d").glob("*.sources"),
               *(apt / "sources.list.d").glob("*.list")]
    nonempty_sources = []
    for source in sources:
        try:
            content = read_guest(root, source.relative_to(root).as_posix())
        except FileNotFoundError:
            continue
        if content.strip():
            nonempty_sources.append(source.relative_to(root).as_posix())
    if not nonempty_sources:
        raise VerificationError("Guest APT source configuration is missing")
    if probe(root, ["/usr/bin/dpkg", "--audit"]).strip():
        raise VerificationError("dpkg --audit reports unfinished package state")
    packages = package_inventory(probe(root, ["/usr/bin/dpkg-query", "-W",
        "-f=${Package}\t${Version}\t${Architecture}\t${Status}\n"]))
    for package in packages:
        name = "usr/share/doc/" + package["name"] + "/copyright"
        if not read_guest(root, name):
            raise VerificationError("Installed package copyright notice is empty")
    probe(root, ["/usr/bin/python3", "-B", "-c", "import websockets, secretstorage"])
    git_version = probe(root, ["/usr/bin/git", "--version"]).strip()
    if not re.fullmatch(r"git version [0-9][^\n]*", git_version):
        raise VerificationError("Guest Git version check failed")
    fonts = probe(root, ["/usr/bin/fc-list", "--format", "%{file}\n"]).splitlines()
    if not fonts:
        raise VerificationError("Guest fontconfig found no fonts")
    for name in fonts:
        font = guest_path(root, name)
        if not font.is_file() or not str(name).startswith("/usr/share/fonts/"):
            raise VerificationError("Fontconfig reported a font outside the distribution font tree")
    return {"schemaVersion": 1, "kind": "pristine-debian-rootfs-validation", "debianVersion": "13",
            "architecture": "arm64", "packages": packages, "packageCount": len(packages),
            "tree": tree, "accounts": accounts, "elf": elfs, "fontCount": len(set(fonts)),
            "gitVersion": git_version, "xkbReadableOutsideGuest": True,
            "probes": {"dpkgAudit": "pass", "pythonImports": "pass", "mountReadOnly": True},
            "guestEmulatorPresent": False, "openAIClientPresent": False, "shimPresent": False,
            "scope": "Host checks only; package authentication belongs to build provenance. "
                     "Host binfmt/QEMU may run probes; Android runtime has not been tested."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.root), indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (VerificationError, OSError, UnicodeError) as error:
        print("FoldGPT rootfs verification: " + str(error), file=sys.stderr)
        raise SystemExit(1)
