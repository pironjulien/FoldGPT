"""Bounded guest package step for the leased, inactive FoldGPT Debian root.

Runs the real Debian package manager with the intact pinned official package.
Required dependencies must already be configured in the authenticated base.
No root/network bootstrap, client launch, account/vault edit or activation.
"""
import argparse
import base64
import fcntl
import hashlib
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time
import official_client_package as package


FORMAT = "foldgpt.inactive-client-install.v1"
STATE = Path("/var/lib/foldgpt/client-install")
INPUT = Path("/tmp/foldgpt-client-input")
APT = ["/usr/bin/apt-get", "--simulate", "--no-download", "--no-remove", "--no-upgrade",
       "--no-install-recommends", "-o", "Acquire::AllowInsecureRepositories=false",
       "-o", "Acquire::AllowDowngradeToInsecureRepositories=false",
       "-o", "APT::Get::AllowUnauthenticated=false"]
MAX_OUTPUT = 8 * 1024 * 1024


def identity(path):
    info = path.lstat()
    return f"{info.st_dev}:{info.st_ino}"


def run(command, timeout, log):
    """Bounded output/deadline, real exit status and an owned process group."""
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, start_new_session=True)
    output = bytearray()
    end = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Guest package command deadline expired")
                for key, _ in selector.select(min(remaining, 1)):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    if len(output) + len(data) > MAX_OUTPUT:
                        raise ValueError("Guest package command output exceeds bound")
                    output.extend(data)
            code = child.wait(timeout=max(0.001, end - time.monotonic()))
        with package.regular(log, os.O_RDWR | os.O_CREAT | os.O_EXCL) as stream:
            stream.write(bytes(output))
            stream.flush()
            os.fsync(stream.fileno())
        if code:
            raise RuntimeError(f"Guest package command failed: {Path(command[0]).name}, exit={code}; see {log.name}")
        return bytes(output).decode("utf-8", errors="strict")
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        child.stdout.close()


def parse_status(text):
    result = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) != 4 or fields[0] in result:
            raise ValueError("Invalid or duplicate installed-package record")
        name, version, arch, status = fields
        if (re.fullmatch(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?", name) is None
                or re.fullmatch(r"[0-9][A-Za-z0-9.+:~\-]*", version) is None
                or re.fullmatch(r"[a-z0-9]+", arch) is None):
            raise ValueError("Invalid installed-package identity")
        result[name] = {"version": version, "architecture": arch, "status": status}
    if not result:
        raise ValueError("Inactive root has no installed Debian packages")
    return result


def client_record(records):
    selected = [value for name, value in records.items() if name.split(":")[0] == "chatgpt"]
    if len(selected) > 1:
        raise ValueError("Ambiguous installed client architecture")
    return selected[0] if selected else None


def without_client(records):
    return {name: value for name, value in records.items() if name.split(":")[0] != "chatgpt"}


def check_baseline(current, baseline, final=False):
    if current.keys() != baseline.keys():
        raise ValueError("Installation changed the authenticated base package set")
    allowed = {"install ok installed"} if final else {
        "install ok installed", "install ok triggers-pending", "install ok triggers-awaited"}
    for name, entry in current.items():
        if (entry["version"] != baseline[name]["version"]
                or entry["architecture"] != baseline[name]["architecture"] or entry["status"] not in allowed
                or baseline[name]["status"] != "install ok installed"):
            raise ValueError("Authenticated base package changed: " + name)


def check_plan(output):
    installs = 0
    for line in output.splitlines():
        if line.startswith(("Inst ", "Conf ", "Remv ", "Purg ")):
            action, name, *_ = line.split()
            if action not in ("Inst", "Conf") or name.split(":")[0] != "chatgpt":
                raise ValueError("Official client requires dependencies outside the authenticated base")
            if action == "Inst":
                installs += 1
    if installs != 1:
        raise ValueError("APT did not produce an unambiguous client-only installation plan")


def repository_evidence(expected_key):
    # Read actual outputs of the unmodified official postinst. The literal
    # paths/URI are its observed supported repository contract, not a substitute.
    names = ["usr/share/keyrings/chatgpt-archive-keyring.gpg",
             "etc/apt/sources.list.d/chatgpt.sources", "var/lib/chatgpt/repository.sources"]
    result, contents = {}, {}
    with package.directory("/") as root:
        for name in names:
            with package.parent_for(root, name) as (parent, leaf), package.regular(leaf, parent=parent) as stream:
                data = stream.read(package.CONTROL_LIMIT + 1)
                if not data or len(data) > package.CONTROL_LIMIT:
                    raise ValueError("Missing or oversized official repository output")
            contents[name] = data
            result[name] = hashlib.sha256(data).hexdigest()
    source = package.deb822(b"\n".join(line for line in contents[names[1]].splitlines()
                                    if line and not line.startswith(b"#")))
    if (source.get("types") != "deb"
            or source.get("uris") != "https://persistent.oaistatic.com/codex-app-prod/linux/deb"
            or source.get("suites") != "stable" or source.get("components") != "main"
            or source.get("architectures") != "arm64"
            or source.get("signed-by") != "/usr/share/keyrings/chatgpt-archive-keyring.gpg"
            or any(key in source for key in ("trusted", "allow-insecure", "allow-weak", "allow-downgrade-to-insecure"))
            or contents[names[1]] != contents[names[2]]
            or contents[names[0]] != expected_key):
        raise ValueError("Official postinst repository configuration differs")
    return result


def signing_key(input_file, expected):
    with package.regular(input_file) as stream:
        members = package.ar_members(stream, expected["bytes"])
        _, contents, _ = package.inventory_tar(stream, members[1], expected, control=True)
    # Extract bytes from the reviewed official shell assignment without executing
    # any shell expression. A different packaging contract requires new review.
    matches = re.findall(rb"^SIGNING_KEY_BASE64='([A-Za-z0-9+/=]+)'$", contents.get("postinst", b""), re.M)
    if len(matches) != 1:
        raise ValueError("Official postinst signing-key contract changed")
    key = base64.b64decode(matches[0], validate=True)
    if not key:
        raise ValueError("Official postinst contains no repository signing key")
    return key


def sync_installed(inventory, repository):
    paths = {item["path"]: item["kind"] for item in inventory["files"] if item["path"]}
    paths.update({path: "file" for path in repository})
    with package.directory("/") as root:
        for path, kind in sorted(paths.items(), reverse=True):
            with package.parent_for(root, path) as (parent, leaf):
                if kind == "file":
                    with package.regular(leaf, parent=parent) as stream:
                        os.fsync(stream.fileno())
                elif kind == "directory":
                    child = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    try:
                        os.fsync(child)
                    finally:
                        os.close(child)
                os.fsync(parent)
        os.fsync(root)


def provision(expected, installation_id, expected_root, input_root=INPUT, state=STATE, timeout=600):
    expected = package.descriptor(expected)
    if (os.geteuid() != 0 or re.fullmatch(r"[0-9a-f]{64}", installation_id) is None
            or re.fullmatch(r"[0-9]+:[0-9]+", expected_root) is None or identity(Path("/")) != expected_root):
        raise ValueError("Client installation requires the bound inactive guest root")
    # This marker/account is provisioned before this step, never created here.
    import pwd
    with package.regular("/etc/foldgpt-user") as stream:
        selected = stream.read(128)
    account = pwd.getpwnam("foldgpt")
    if selected != b"foldgpt\n" or account.pw_uid <= 0 or account.pw_gid <= 0 or account.pw_dir != "/home/foldgpt":
        raise ValueError("Inactive guest account contract is missing")
    for path in (state.parent, state):
        with package.directory(path.parent) as parent:
            if not path.exists():
                os.mkdir(path.name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        with package.directory(path, private=True) as fd:
            os.fsync(fd)
        with package.directory(path.parent) as fd:
            os.fsync(fd)
    with package.directory(state, private=True) as directory:
        with package.regular("install.lock", os.O_RDWR | os.O_CREAT, directory) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            input_stage = state / "input"
            if not input_stage.exists():
                input_stage.mkdir(mode=0o700)
                os.fsync(directory)
            inventory = package.prepare(input_root / "package.deb", expected, input_stage)
            expected_key = signing_key(input_stage / "package.deb", expected)
            run_id = os.urandom(16).hex()
            step = 0
            def execute(command):
                nonlocal step
                step += 1
                return run(command, timeout, state / f"{run_id}-{step}.log")
            def status():
                return parse_status(execute(["/usr/bin/dpkg-query", "--show",
                    "--showformat=${binary:Package}\t${Version}\t${Architecture}\t${Status}\n"]))
            bindings = {"format": FORMAT, "installationId": installation_id,
                        "rootIdentity": expected_root, "descriptor": expected,
                        "implementation": {name: hashlib.sha256((input_root / name).read_bytes()).hexdigest()
                            for name in ("official_client_package.py", "install_official_client.py")}}
            current = status()
            intent_path = state / "intent.json"
            if intent_path.exists():
                intent = package.read_json("intent.json", directory)
                if (set(intent) != {*bindings, "baseline", "phase"}
                        or any(intent[key] != value for key, value in bindings.items())
                        or intent["phase"] not in ("PLANNED", "UNPACKED", "CONFIGURED", "VERIFIED")):
                    raise ValueError("Inactive client installation intent changed")
                baseline = intent["baseline"]
                check_baseline(without_client(current), baseline)
                existing = client_record(current)
                if existing and (existing["version"] != expected["version"] or existing["architecture"] != "arm64"):
                    raise ValueError("A different client occupies the inactive installation")
            else:
                if client_record(current) is not None or any(os.path.lexists(path) for path in (
                        "/usr/lib/chatgpt", "/usr/share/keyrings/chatgpt-archive-keyring.gpg",
                        "/etc/apt/sources.list.d/chatgpt.sources", "/var/lib/chatgpt", "/etc/default/chatgpt")):
                    raise ValueError("Unbound existing client cannot be adopted by fresh installation")
                baseline = without_client(current)
                check_baseline(baseline, baseline, final=True)
                if execute(["/usr/bin/dpkg", "--audit"]).strip():
                    raise ValueError("Authenticated base requires package repair before client installation")
                check_plan(execute([*APT, "install", str(input_stage / "package.deb")]))
                intent = {**bindings, "baseline": baseline, "phase": "PLANNED"}
                package.publish_json(directory, "intent.json", intent)
            if intent["phase"] != "VERIFIED":
                # Re-unpack only this journal-bound input after an interrupted
                # step. dpkg owns its database recovery and all original scripts.
                execute(["/usr/bin/dpkg", "--unpack", str(input_stage / "package.deb")])
                intent["phase"] = "UNPACKED"
                package.publish_json(directory, "intent.json", intent)
                execute(["/usr/bin/dpkg", "--configure", "chatgpt"])
                intent["phase"] = "CONFIGURED"
                package.publish_json(directory, "intent.json", intent)
            final = status()
            check_baseline(without_client(final), baseline, final=True)
            if client_record(final) != {"version": expected["version"], "architecture": "arm64", "status": "install ok installed"}:
                raise ValueError("Official client is not fully configured")
            if execute(["/usr/bin/dpkg", "--audit"]).strip():
                raise ValueError("Debian package audit did not complete cleanly")
            execute([*APT, "check"])
            files = package.verify_files("/", inventory)
            repository = repository_evidence(expected_key)
            sync_installed(inventory, repository)
            if identity(Path("/")) != expected_root:
                raise ValueError("Inactive root identity changed")
            report = {**bindings, "scope": "configured-client-package-only", "packagedFiles": files,
                      "repositoryFiles": repository, "basePackagesUnchanged": True,
                      "installed": client_record(final)}
            if intent["phase"] == "VERIFIED":
                if package.read_json("report.json", directory) != report:
                    raise ValueError("Previously verified client package evidence changed")
            else:
                package.publish_json(directory, "report.json", report)
                intent["phase"] = "VERIFIED"
                package.publish_json(directory, "intent.json", intent)
            return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--root-identity", required=True)
    parser.add_argument("--timeout", type=int, required=True)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("a positive per-command deadline is required")
    expected = package.descriptor(package.read_json(INPUT / "descriptor.json"))
    result = provision(expected, args.installation_id, args.root_identity, timeout=args.timeout)
    sha = hashlib.sha256(package.canonical(result)).hexdigest()
    print("FOLDGPT_CLIENT_RECEIPT=" + "\t".join((expected["sha256"], expected["version"], args.root_identity, sha)))


if __name__ == "__main__":
    main()
