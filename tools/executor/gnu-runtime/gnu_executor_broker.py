"""Explicit diagnostic GNU executor over the existing private Unix transport.

This supervisor entrypoint does not edit an app profile or select an environment.
The unmodified private-exec-bridge provides its stdio connection. Runtime inputs
and parent environment are supervisor-owned; process RPCs cannot replace them.
"""
import argparse
import asyncio
from functools import partial
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.executor.native_processes import NativeProcessLimits
from tools.executor.private_exec_broker import run
from tools.policy.managed_policy import GuestPath
from gnu_process_adapter import GnuProcessesBackend
from gnu_runtime_address import runtime_address_admission


def _native_path(value, *, directory=False, private=False, executable=False):
    path = Path(value).absolute()
    if path != path.resolve(strict=True):
        raise ValueError("GNU supervisor paths must be canonical and contain no aliases")
    info = path.stat()
    if (directory and not stat.S_ISDIR(info.st_mode)) or (not directory and not stat.S_ISREG(info.st_mode)):
        raise ValueError("GNU supervisor path has the wrong object kind")
    if private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError("GNU writable and IPC roots must be owned and private")
    if executable and not os.access(path, os.X_OK):
        raise ValueError("GNU runtime program is not executable")
    return path


def _guest_program(rootfs, guest):
    # Debian's /bin -> usr/bin alias is a runtime property, not a caller-chosen
    # native path. Require its actual target to remain in this runtime image.
    program = (rootfs / guest.lstrip("/")).resolve(strict=True)
    if not program.is_relative_to(rootfs):
        raise ValueError("GNU guest program escapes its runtime root")
    return _native_path(program, executable=True)


def configuration(args):
    """Validate an explicit workspace profile without opening an endpoint."""
    if os.getuid() == 0 or os.getuid() != os.geteuid():
        raise PermissionError("GNU diagnostic requires an ordinary non-root UID")
    if not 0 < args.peer_uid < 2**31:
        raise ValueError("Expected peer UID must be a positive signed 32-bit integer")
    mount = GuestPath.from_absolute(args.guest_workspace)
    if (mount.path != args.guest_workspace or not mount.parts
            or ":" in mount.path or mount.path.endswith("!")):
        raise ValueError("GNU workspace mount must be a canonical dedicated guest path")
    # A project mount may live under /root or /home, but it must neither hide
    # runtime/control trees nor reuse their grants through a child bind.
    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc", "/tmp", "/dev", "/proc",
                 "/sys", "/system", "/apex", "/linkerconfig"):
        reserved = GuestPath.from_absolute(path)
        if mount.contains(reserved) or reserved.contains(mount):
            raise ValueError("GNU workspace mount overlaps a runtime or control tree")
    home = mount.append((".home",))
    temporary = GuestPath.from_absolute("/tmp")
    paths = {name: _native_path(getattr(args, name), directory=True, private=True)
             for name in ("workspace", "scratch", "guest_tmp", "socket_dir")}
    if any(":" in str(paths[name]) for name in ("workspace", "guest_tmp")):
        raise ValueError("GNU bind source paths cannot contain a PRoot binding separator")
    roots = list(paths.values())
    if any(a == b or a in b.parents or b in a.parents
           for index, a in enumerate(roots) for b in roots[index + 1:]):
        raise ValueError("GNU workspace, runtime scratch, guest temp and IPC roots must be disjoint")
    if len(os.fsencode(paths["socket_dir"] / "exec.sock")) >= 108:
        raise ValueError("Unix socket path exceeds sockaddr_un capacity")
    _native_path(paths["workspace"] / ".home", directory=True, private=True)
    rootfs = _native_path(args.rootfs, directory=True)
    programs = {name: _native_path(getattr(args, name), executable=True)
                for name in ("helper", "handle_helper", "process_runner", "proot", "loader", "loader32")}
    programs["guest_bash"] = _guest_program(rootfs, "/bin/bash")
    programs["guest_env"] = _guest_program(rootfs, "/usr/bin/env")
    if any(path == root or root in path.parents for path in (*programs.values(), rootfs)
           for root in roots):
        raise ValueError("GNU runtime inputs cannot live in writable or IPC roots")
    overrides = {name: getattr(args, "process_" + name) for name in
                 ("wall_ms", "address_space_bytes", "output_bytes", "uid_task_budget")
                 if getattr(args, "process_" + name) is not None}
    if getattr(args, 'android_runtime_address_budget', False):
        if sys.platform != 'android' or 'address_space_bytes' in overrides:
            raise ValueError('Android runtime address budget requires one explicit Android admission')
        overrides['address_space_bytes'] = runtime_address_admission(programs['proot'])['addressSpaceBytes']
    limits = NativeProcessLimits(**overrides)
    # Deliberately never read os.environ: Bionic shell/home paths and ambient
    # credentials are not the GNU supervisor's process environment snapshot.
    parent_environment = {"PATH": "/usr/bin:/bin", "HOME": home.path,
                          "TMPDIR": temporary.path, "SHELL": "/bin/bash", "LANG": "C.UTF-8"}
    info = {"shell": {"name": "bash", "path": "/bin/bash"}, "cwd": mount.uri,
            "userHomeDir": home.uri, "platformOs": "linux",
            "temporaryDirectories": [temporary.uri], "tempDir": temporary.uri}
    factory = partial(GnuProcessesBackend, proot=programs["proot"], rootfs=rootfs,
                      loader=programs["loader"], loader32=programs["loader32"],
                      scratch=paths["scratch"], guest_tmp=paths["guest_tmp"])
    return {"directory": paths["socket_dir"], "helper": programs["helper"],
            "workspace": paths["workspace"], "guest_workspace": mount.path,
            "expected_uid": args.peer_uid, "handle_helper": programs["handle_helper"],
            "process_config": {"process_runner": programs["process_runner"],
                               "process_factory": factory, "limits": limits,
                               "parent_environment": parent_environment},
            "environment_info": info}


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    for name in ("socket-dir", "helper", "handle-helper", "workspace", "process-runner",
                 "proot", "rootfs", "loader", "loader32", "scratch", "guest-tmp"):
        value.add_argument("--" + name, type=Path, required=True)
    value.add_argument("--peer-uid", type=int, required=True)
    value.add_argument("--guest-workspace", default="/workspace")
    value.add_argument("--android-runtime-address-budget", action="store_true")
    for name in ("wall-ms", "address-space-bytes", "output-bytes", "uid-task-budget"):
        value.add_argument("--process-" + name, type=int)
    return value


def main():
    cli = parser()
    try:
        options = configuration(cli.parse_args())
    except (OSError, ValueError) as error:
        cli.error(str(error))
    asyncio.run(run(**options))


if __name__ == "__main__":
    main()
