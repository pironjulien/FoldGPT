"""Generate and synchronize a bounded FoldGPT block in the selected global AGENTS file.

Runs against an explicitly selected guest root, never ADB. Does not change
config.toml, client binaries, Android permissions or any file outside that root.
Only the synchronizer's own block and content-addressed manifest are managed.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile

BEGIN = b"<!-- foldgpt:environment:v1 begin -->"
END = b"<!-- foldgpt:environment:v1 end -->"
LIMIT = 32768


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate manifest key")
        value[key] = item
    return value


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def read(path, limit=LIMIT):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Context input must be a single-link regular file")
        data = stream.read(limit + 1)
        if len(data) > limit or b"\0" in data:
            raise ValueError("Context input exceeds its text bound")
        data.decode("utf-8", errors="strict")
        return data


def manifest(path):
    value = json.loads(read(path), object_pairs_hook=unique)
    if set(value) != {"schema", "revision", "clientHost", "guest", "compute", "capabilities", "rules"} or value["schema"] != "foldgpt.agent-environment.v1":
        raise ValueError("Unsupported context manifest")
    if value["clientHost"].get("androidRoot") is not False or value["clientHost"].get("bootloaderModification") is not False:
        raise ValueError("Context must retain the unrooted Android contract")
    identifiers = set()
    for entry in value["capabilities"]:
        if set(entry) != {"id", "status", "description", "evidence"} or entry["id"] in identifiers or entry["status"] not in {"verified-bounded", "diagnostic-only", "unavailable"}:
            raise ValueError("Unknown or duplicate context capability")
        identifiers.add(entry["id"])
    return value


def real_directory(path, create=False):
    path = Path(path).absolute()
    if path.parent != path:
        real_directory(path.parent)
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not create:
            raise
        path.mkdir(mode=0o700)
        info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("Context path traverses a non-directory or symlink")
    return path


def guest_path(root, guest):
    path = PurePosixPath(guest)
    if not path.is_absolute() or str(path) != guest or any(part in (".", "..") for part in path.parts):
        raise ValueError("Context guest path must be canonical and absolute")
    return root.joinpath(*path.parts[1:])


def identity(root):
    etc = real_directory(root / "etc")
    selected = read(etc / "foldgpt-user", 128).decode()
    if re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}\n", selected) is None:
        raise ValueError("Invalid selected guest account")
    user = selected[:-1]
    rows = [line.split(":") for line in read(etc / "passwd", 1048576).decode().splitlines()]
    if any(len(row) != 7 or not row[2].isdecimal() or not row[3].isdecimal() for row in rows):
        raise ValueError("Malformed guest passwd")
    if len({int(row[2]) for row in rows}) != len(rows):
        raise ValueError("Ambiguous guest UID")
    selected = [row for row in rows if row[0] == user]
    if len(selected) != 1 or int(selected[0][2]) <= 0 or int(selected[0][3]) <= 0 or selected[0][5:] != ["/home/" + user, "/bin/bash"]:
        raise ValueError("Invalid selected nonroot guest identity")
    row = selected[0]
    groups = [line.split(":") for line in read(etc / "group", 1048576).decode().splitlines()]
    if any(len(item) != 4 or not item[2].isdecimal() for item in groups):
        raise ValueError("Malformed guest group")
    matching = [item for item in groups if item[0] == user or int(item[2]) == int(row[3])]
    if len(matching) != 1 or matching[0][0] != user or int(matching[0][2]) != int(row[3]):
        raise ValueError("Guest primary group differs")
    real_directory(guest_path(root, row[5]))
    return {"user": user, "uid": int(row[2]), "gid": int(row[3]), "home": row[5], "shell": row[6]}


def render(value, account, codex_home):
    bound = {"manifest": value, "guestBinding": account, "codexHome": codex_home,
             "bindingSource": "selected-guest-root-files", "modelDeliveryVerified": False}
    payload = canonical(bound)
    sha = hashlib.sha256(payload).hexdigest()
    location = codex_home + "/foldgpt/environment-" + sha + ".json"
    host, guest, compute = value["clientHost"], value["guest"], value["compute"]
    lines = [BEGIN.decode(), "# Environnement de l'interface FoldGPT", "",
             "Référence " + value["revision"] + ". Cette carte concerne le client FoldGPT ; vérifier l'environnement réellement sélectionné pour les outils.",
             "Hôte de référence : " + host["referenceDevice"] + ", Android API " + str(host["referenceApi"]) + ", " + host["architecture"] + ", application " + host["applicationId"] + ", sans root Android ni modification du bootloader.",
             "Invité : " + guest["platform"] + ". " + guest["mechanism"] + ".",
             "Compte invité résolu : " + account["user"] + " (" + str(account["uid"]) + ":" + str(account["gid"]) + "), HOME=" + account["home"] + ", shell=" + account["shell"] + ".",
             "CODEX_HOME ciblé : " + codex_home + ". Le dossier de travail de chaque tâche est celui indiqué par son environnement, pas automatiquement HOME.",
             "Racine Android : " + guest["rootLocation"] + ". Session : " + guest["session"] + ". Client : " + guest["client"] + ". Codex : " + guest["codex"] + ".",
             "", compute["cpu"], compute["gpu"], compute["model"], "", "Capacités et limites :"]
    lines += ["- " + item["id"] + " [" + item["status"] + "] : " + item["description"] for item in value["capabilities"]]
    lines += ["", "Règles d'interprétation :"] + ["- " + item for item in value["rules"]]
    lines += ["", "Manifeste détaillé : " + location + ". SHA-256 : " + sha + ".", END.decode(), ""]
    block = "\n".join(lines).encode()
    if len(block) > LIMIT or len(payload) > LIMIT:
        raise ValueError("Rendered context exceeds its bound")
    return block, payload, sha, location


def merge(original, block):
    if original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1:
        raise ValueError("Ambiguous existing FoldGPT context block")
    if BEGIN not in original:
        result = original + (b"\n" if original and not original.endswith(b"\n") else b"") + block
    else:
        start, end = original.index(BEGIN), original.index(END) + len(END)
        if end <= start or start and original[start - 1:start] != b"\n" or original[end:end + 1] not in (b"", b"\n"):
            raise ValueError("Malformed existing FoldGPT context boundaries")
        if original[end:end + 1] == b"\n":
            end += 1
        result = original[:start] + block + original[end:]
    if len(result) > LIMIT:
        raise ValueError("Combined AGENTS file exceeds context budget; user instructions remain unchanged")
    return result


def atomic(path, data):
    previous = path.lstat() if path.exists() or path.is_symlink() else None
    if previous is not None:
        read(path)
        if previous.st_uid != os.geteuid():
            raise ValueError("Existing context file must belong to the synchronizing account")
    descriptor, scratch = tempfile.mkstemp(prefix=".foldgpt-context-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            if previous is not None:
                os.fchmod(stream.fileno(), stat.S_IMODE(previous.st_mode))
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(scratch, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(scratch):
            os.unlink(scratch)


def synchronize(root, source, codex_home=None, check=False):
    root = real_directory(root)
    value = manifest(source)
    account = identity(root)
    if root == Path("/") and (os.geteuid() != account["uid"] or os.getegid() != account["gid"] or os.environ.get("HOME") != account["home"]):
        raise ValueError("Live context synchronization requires the selected nonroot guest account and HOME")
    codex_home = codex_home or account["home"] + "/.codex"
    target = guest_path(root, codex_home)
    real_directory(target, create=not check)
    lock = os.open(target / ".foldgpt-context.lock", os.O_RDWR | (0 if check else os.O_CREAT) | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Invalid context synchronization lease")
        fcntl.flock(lock, fcntl.LOCK_EX)
        override = target / "AGENTS.override.md"
        selected = override if (override.exists() or override.is_symlink()) and read(override).strip() else target / "AGENTS.md"
        original = read(selected) if selected.exists() or selected.is_symlink() else b""
        block, payload, sha, location = render(value, account, codex_home)
        combined = merge(original, block)
        store = real_directory(target / "foldgpt", create=not check)
        destination = store / ("environment-" + sha + ".json")
        if check:
            if original != combined or read(destination) != payload:
                raise ValueError("Selected context file or manifest is out of sync")
        else:
            if destination.exists() or destination.is_symlink():
                if read(destination) != payload:
                    raise ValueError("Content-addressed context manifest differs")
            else:
                atomic(destination, payload)
            if original != combined:
                atomic(selected, combined)
            if read(selected) != combined or read(destination) != payload:
                raise ValueError("Context readback differs")
        return {"status": "IN_SYNC", "selectedGuestFile": codex_home + "/" + selected.name,
                "selectedPhysicalFile": str(selected), "manifestGuestFile": location,
                "manifestSha256": sha, "agentsSha256": hashlib.sha256(combined).hexdigest(),
                "guestBinding": account, "modelDeliveryVerified": False,
                "scope": "filesystem synchronization only; official task loading requires separate observation"}
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guest-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--codex-home", help="Actual absolute guest CODEX_HOME; defaults to selected HOME/.codex")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(synchronize(args.guest_root, args.manifest, args.codex_home, args.check), indent=2))


if __name__ == "__main__":
    main()
