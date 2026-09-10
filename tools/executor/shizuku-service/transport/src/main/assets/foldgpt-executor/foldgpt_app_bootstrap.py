"""Android application entry into the shared installed native owner.

The distinct C ELF has already required seccomp 2 and verified the complete
runtime inventory before importing this module. No launch input selects or
changes the origin, and the original run-as entry remains strict seccomp 0.
"""
import asyncio
import os
import re
import stat

import foldgpt_native_bootstrap as native


def admit_data_path(canonical, declared_stat, canonical_stat, uid):
    """Check the two Android spellings against actual lstat identities."""
    if (canonical.as_posix() not in (native.DATA.as_posix(), "/data/data/app.foldgpt")
            or type(uid) is not int or uid < 10000
            or (declared_stat.st_dev, declared_stat.st_ino) != (canonical_stat.st_dev, canonical_stat.st_ino)):
        raise ValueError("Application data views do not identify the same admitted directory")
    for info in (declared_stat, canonical_stat):
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_gid != uid
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError("Application data directory must be real, private and app-owned")
    return canonical


def admit_private_suffix(declared, data, resolved, canonical_resolved, info, uid, mask):
    """Validate an observed suffix without accepting an application alias."""
    suffix = declared.relative_to(native.DATA)
    expected = data / suffix
    if resolved != expected or canonical_resolved != expected:
        raise ValueError("Private application path contains an unadmitted alias")
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_gid != uid
            or stat.S_IMODE(info.st_mode) & mask):
        raise ValueError("Private application path ownership or mode differs")
    return expected


def private_suffix(declared, data, uid, mask):
    """Translate only the verified system prefix; every suffix remains exact."""
    expected = data / declared.relative_to(native.DATA)
    return admit_private_suffix(declared, data, declared.resolve(strict=True),
                                expected.resolve(strict=True), expected.lstat(), uid, mask)


def application_paths(uid):
    canonical = native.DATA.resolve(strict=True)
    data = admit_data_path(canonical, native.DATA.lstat(), canonical.lstat(), uid)
    private_suffix(native.DATA / "files", data, uid, 0)
    private_suffix(native.DATA / "files/native-runtime-v1", data, uid, 0o077)
    runtime = private_suffix(native.RUNTIME, data, uid, 0o077)
    projects = private_suffix(native.PROJECTS, data, uid, 0o077)
    broker = private_suffix(native.BROKER, data, uid, 0o077)
    return native.BootstrapPaths(data, runtime, projects, broker)


def application_context(status, context):
    # ps -AZ observed this exact domain for FoldGPT, :runtime and the separate
    # probe on 2026-09-08. MCS categories differ with package UID; their literal
    # numbers are not portable identities. UID/GID/parent are checked separately.
    if (int(status["TracerPid"].strip()) != 0
            or re.fullmatch(r"u:r:untrusted_app:s0:c[0-9]+(?:,c[0-9]+)*", context) is None):
        raise ValueError("Native application owner has an unexpected Android process context")


def identity(uid, parent, nonce, launch_path):
    return native.identity(uid, parent, nonce, launch_path, launch_origin="android-app")


def deployment(apk):
    return native.deployment(apk, launch_origin="android-app")


async def run(apk, uid, parent, nonce, launch_path, control_fd=3):
    return await native.run(apk, uid, parent, nonce, launch_path, control_fd,
                            launch_origin="android-app")


def main(arguments):
    if len(arguments) != 5:
        raise ValueError("Installed application launch argument count differs")
    apk, uid, parent, nonce, launch_path = arguments
    os._exit(asyncio.run(run(apk, int(uid), int(parent), nonce, launch_path)))
