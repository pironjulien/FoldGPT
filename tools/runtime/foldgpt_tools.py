"""On-device FoldGPT tools. Diagnostics read app state; commands use the guest ABI.

Run by the APK's Android Python launcher under the ordinary application UID.
No daemon, privileged API, remote execution or replacement Codex runtime.
"""
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

COMMANDS = {
    "git": "/usr/bin/git", "make": "/usr/bin/make",
    "node": "/usr/lib/chatgpt/resources/cua_node/bin/node",
    "npm": "/usr/lib/chatgpt/resources/cua_node/bin/npm",
    "npx": "/usr/lib/chatgpt/resources/cua_node/bin/npx",
    "gcc": "/usr/bin/gcc", "g++": "/usr/bin/g++",
    "diff": "/usr/bin/diff", "tar": "/usr/bin/tar",
    "gzip": "/usr/bin/gzip", "xz": "/usr/bin/xz",
    "workspace-node": "@workspace/dependencies/node/bin/node",
    "workspace-python3": "@workspace/dependencies/python/bin/python3",
    "pnpm": "@workspace/dependencies/bin/fallback/pnpm",
    "pdftoppm": "/usr/bin/pdftoppm", "pdftotext": "/usr/bin/pdftotext",
    "pdfinfo": "/usr/bin/pdfinfo", "libreoffice": "@workspace/dependencies/bin/fallback/libreoffice",
    "soffice": "@workspace/dependencies/bin/fallback/soffice", "heif-convert": "/usr/bin/heif-convert",
    "JxrDecApp": "/usr/bin/JxrDecApp",
}
GUEST_PATH = "/usr/lib/chatgpt/resources/cua_node/bin:/usr/local/bin:/usr/bin:/bin"


def read_json(path, limit=65536):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Expected app-owned regular JSON file")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("JSON input exceeds limit")
    return json.loads(data)


class Installation:
    def __init__(self, config):
        if config.get("schema") != "foldgpt.local-tools.v1" or config.get("uid") != os.getuid() or os.getuid() == 0:
            raise ValueError("Local tools require the ordinary FoldGPT UID")
        self.files = Path(config["filesDir"]).resolve(strict=True)
        if not re.fullmatch(r"/data/(?:data|user/[0-9]+)/app\.foldgpt/files", str(self.files)):
            raise ValueError("Unexpected application files directory")
        if self.files.stat().st_uid != os.getuid():
            raise ValueError("Application files owner differs")
        self.native = Path(config["nativeLibraryDir"]).resolve(strict=True)
        if not str(self.native).startswith("/data/app/"):
            raise ValueError("Expected APK-owned native libraries")
        executable = Path("/proc/self/exe").resolve(strict=True)
        if executable != self.native / "libfoldgpt_python_cli.so":
            raise ValueError("Invoke local tools with FoldGPT's native Python")
        self.guest = self.files / "debian"
        self.home = config["guestHome"]
        self.user = config["guestUser"]
        self.ids = config["guestIds"]
        if self.home != "/home/" + self.user or not re.fullmatch(r"[a-z_][a-z0-9_-]*", self.user):
            raise ValueError("Guest identity differs")
        if not re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", self.ids):
            raise ValueError("Guest tools must use the selected nonroot identity")
        self.version = config["versionCode"]
        self.workspace_runtime = self.home + "/.cache/codex-runtimes/codex-primary-runtime"

    def tool_target(self, command):
        return COMMANDS[command].replace("@workspace", self.workspace_runtime)

    def physical(self, value):
        path = PurePosixPath(value)
        if not path.is_absolute() or ".." in path.parts or "\0" in value:
            raise ValueError("Use an absolute path without parent traversal")
        for candidate in self.aliases():
            if value == str(candidate) or value.startswith(str(candidate) + "/"):
                return str(self.files) + value[len(str(candidate)):]
        for guest, native in (("/dev/shm", self.files.parent / "cache/shm"),
                              ("/tmp", self.files.parent / "cache/x11")):
            if value == guest or value.startswith(guest + "/"):
                return str(native) + value[len(guest):]
        if any(value == root or value.startswith(root + "/")
               for root in ("/dev", "/proc", "/sys", "/system", "/apex")):
            return value
        return str(self.guest / value.lstrip("/"))

    def aliases(self):
        candidates = [self.files, Path("/data/data/app.foldgpt/files"),
                      Path("/data/user") / str(os.getuid() // 100000) / "app.foldgpt/files"]
        result = []
        for path in candidates:
            if path not in result and path.exists() and os.path.samefile(path, self.files):
                result.append(path)
        return result

    def invocation(self, command, arguments, cwd=None, environment=None):
        if command not in COMMANDS:
            raise ValueError("Unknown guest tool")
        target = self.tool_target(command)
        # Opening the actual file also works when an Android access(2) probe
        # cannot model the permissions of the eventual interpreter.
        with (self.guest / target.lstrip("/")).open("rb") as stream:
            stream.read(1)
        cwd = os.path.realpath(cwd or os.getcwd(), strict=True)
        if not any(cwd == str(p) or cwd.startswith(str(p) + "/") for p in self.aliases()):
            raise ValueError("Run guest tools from FoldGPT's app-private files")
        env = dict(os.environ if environment is None else environment)
        for name in ("LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH", "PYTHONPYCACHEPREFIX"):
            env.pop(name, None)
        guest_environment = []
        guest_path = GUEST_PATH
        metadata_path = self.guest / self.workspace_runtime.lstrip("/") / "runtime.json"
        if metadata_path.is_file():
            metadata = read_json(metadata_path)
            if metadata.get("provider") != "FoldGPT":
                provider = read_json(self.guest / 'usr/local/share/foldgpt/workspace-runtime/provider.json')
                if provider.get('source') not in ('official-manifest', 'official-catalog'):
                    raise ValueError("Unexpected workspace dependency provider")
            if metadata.get("targetArch", "arm64") not in ("arm64", "aarch64"):
                raise ValueError("Unexpected workspace dependency architecture")
            runtime = self.workspace_runtime
            guest_path = runtime + "/dependencies/node/bin:" + runtime + "/dependencies/python/bin:" + \
                runtime + "/dependencies/bin/fallback:" + GUEST_PATH
            guest_environment += ["PYTHONHOME=" + runtime + "/dependencies/python", "PYTHONPATH=",
                "PYTHONDONTWRITEBYTECODE=1", "NODE_PATH=" + runtime + "/dependencies/node/node_modules"]
            # Helpers launched inside GNU must use GNU engines directly. Map
            # only this bundle's published paths; preserve explicit other inputs.
            helpers = {
                "RUNTIME_NODE": ("foldgpt-tools/bin/workspace-node", runtime + "/dependencies/node/bin/node"),
                "RUNTIME_PYTHON": ("foldgpt-tools/bin/workspace-python3", runtime + "/dependencies/python/bin/python3"),
                "RUNTIME_NODE_MODULES": ("debian" + runtime + "/dependencies/node/node_modules", runtime + "/dependencies/node/node_modules"),
                "RUNTIME_BIN_DIR": ("foldgpt-tools/bin", runtime + "/dependencies/bin/override"),
            }
            for key, (published, guest) in helpers.items():
                if key not in env or any(env[key] == str(alias / published) for alias in self.aliases()):
                    guest_environment.append(key + "=" + guest)
        # Android denies hardlink creation in app data. Git supports publishing
        # completed objects with rename on such filesystems; use that mode also
        # for Git invoked by npm/Make, without changing the user's config files.
        count = env.get("GIT_CONFIG_COUNT", "0")
        if not count.isdecimal():
            raise ValueError("Invalid inherited Git config count")
        index = int(count)
        env["GIT_CONFIG_KEY_" + str(index)] = "core.createObject"
        env["GIT_CONFIG_VALUE_" + str(index)] = "rename"
        env["GIT_CONFIG_COUNT"] = str(index + 1)
        env.update(LD_LIBRARY_PATH=str(self.files / "native") + ":" + str(self.native),
                   PROOT_LOADER=str(self.native / "libproot-loader.so"),
                   PROOT_LOADER_32=str(self.native / "libproot-loader32.so"),
                   PROOT_TMP_DIR=str(self.files.parent / "cache/x11"))
        # link2symlink would leave artificial .l2s aliases in Git's object store,
        # which the native workspace's startup validation correctly refuses.
        args = [str(self.native / "libproot.so"), "--kill-on-exit", "--sysvipc",
                "-r", str(self.guest), "-i", self.ids, "-w", cwd]
        for mount in ["/dev", "/proc", "/sys", "/system", "/apex"]:
            args += ["-b", mount]
        for alias in self.aliases():
            args += ["-b", str(self.files) + ":" + str(alias)]
        args += ["-b", str(self.files.parent / "cache/x11") + ":/tmp",
                 "-b", str(self.files.parent / "cache/shm") + ":/dev/shm"]
        home = env.get("HOME", self.home)
        args += ["/usr/bin/env", "-u", "LD_LIBRARY_PATH", "PATH=" + guest_path,
                 "HOME=" + home, "USER=" + self.user, "LOGNAME=" + self.user,
                 "SHELL=/bin/bash", "TMPDIR=/tmp", "LANG=" + env.get("LANG", "C.UTF-8"),
                 "SAL_ENABLE_FILE_LOCKING=1",
                 *guest_environment, target, *arguments]
        return args, env

    def status(self):
        value = read_json(self.files / "native-executor-status.json")
        native = value.get("lastNativeSessionStatus") or {}
        pid = native.get("bootstrapPid")
        processes = []
        for path in Path("/proc").iterdir():
            if not path.name.isdecimal():
                continue
            try:
                if path.stat().st_uid != os.getuid():
                    continue
                fields = dict(line.split(":", 1) for line in (path / "status").read_text().splitlines() if ":" in line)
                processes.append({"pid": int(path.name), "name": fields["Name"].strip(),
                                  "parentPid": int(fields["PPid"]), "tracerPid": int(fields["TracerPid"])})
            except (OSError, KeyError, ValueError):
                continue
        return {"schema": "foldgpt.local-status.v1", "versionCode": self.version,
                "uid": os.getuid(), "platform": sys.platform, "python": sys.version.split()[0],
                "cwd": os.getcwd(), "filesDir": str(self.files), "guestRoot": str(self.guest),
                "guestHome": self.home, "guestHomePhysical": self.physical(self.home),
                "codexHomePhysical": self.physical(self.home + "/.codex"),
                "recordedRuntimeState": value.get("state"), "recordedOwnerPid": pid,
                "recordedOwnerPresent": any(row["pid"] == pid for row in processes),
                "appProcessCount": len(processes), "processes": processes,
                "countScope": "Current readable UID processes, including this diagnostic; not Android's global phantom-process count",
                "tools": {name: {"guestPath": target, "physicalPath": self.physical(target),
                                  "present": (self.guest / target.lstrip("/")).exists(), "abi": "GNU/Linux ARM64 through PRoot"}
                          for name in COMMANDS for target in [self.tool_target(name)]}}

    def logs(self):
        # Report known error families, without copying tokens, prompts, URLs
        # with credentials or arbitrary text from application logs into a chat.
        path = self.files / "runtime.log"
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError("Runtime log owner or type differs")
            offset = max(0, info.st_size - 262144)
            stream.seek(offset)
            data = stream.read(262144).decode("utf-8", "replace")
        markers = {"workspace_manifest_404": "Failed to download primary runtime manifest (404",
                   "workspace_dependencies_missing": "installed=false problemCount=",
                   "procps_boot_time": "Unable to get system boot time",
                   "pthread_getschedparam": "pthread_getschedparam failed",
                   "xlib_missing_extension": "Xlib:  extension",
                   "native_runtime_failure": "Native endpoint failure"}
        return {"source": str(path), "bytesRead": len(data.encode()), "tailOnly": offset > 0,
                "knownErrors": {key: data.count(marker) for key, marker in markers.items()},
                "scope": "Counts of known error text in the bounded log tail; zero is not a clean-health assertion"}


def main():
    installation = Installation(read_json(Path(__file__).with_name("installation.json")))
    arguments = sys.argv[1:]
    if not arguments or arguments[0] in ("help", "--help", "-h"):
        print("foldgpt status [--logs] | logs | path ABSOLUTE_GUEST_PATH\nGuest tools: " + ", ".join(COMMANDS))
        return
    command, *rest = arguments
    if command in COMMANDS:
        args, env = installation.invocation(command, rest)
        os.execve(args[0], args, env)
    if command == "status" and rest in ([], ["--logs"]):
        value = installation.status()
        if rest:
            value["logs"] = installation.logs()
    elif command == "logs" and not rest:
        value = installation.logs()
    elif command == "path" and len(rest) == 1:
        print(installation.physical(rest[0]))
        return
    else:
        raise ValueError("Unknown command or arguments; use foldgpt --help")
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print("foldgpt: " + str(error), file=sys.stderr)
        raise SystemExit(1)
