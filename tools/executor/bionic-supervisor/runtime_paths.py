"""Strict runtime-path snapshots without inspecting every ancestor.

Android permits opening /linkerconfig/ld.config.txt while denying getattr on
/linkerconfig. CPython realpath walks parents with lstat; Bionic realpath instead
opens the object with O_PATH and reads /proc/self/fd. Use that descriptor route,
also refusing magic links and checking the returned name still identifies the
same ordinary object. This is admission of the existing immutable runtime
contract, not a lifetime pin or exclusion against an unconfined host writer.
"""
import ctypes
import errno
import os
from pathlib import Path
import stat


class _OpenHow(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64),
                ("resolve", ctypes.c_uint64)]


# Linux x86_64 and arm64 UAPI, also checked by test_runtime_paths.c against the
# host and NDK headers. openat2 is already required by the native supervisor.
_SYS_OPENAT2 = 437
_AT_FDCWD = -100
_NO_MAGICLINKS = 0x02
_NO_SYMLINKS = 0x04
_LIBC = ctypes.CDLL(None, use_errno=True)
_SYSCALL = _LIBC.syscall
_SYSCALL.restype = ctypes.c_long
_SYSCALL.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.c_char_p,
                     ctypes.POINTER(_OpenHow), ctypes.c_size_t]


def native_name(value):
    """Refuse ambiguous spellings rather than normalizing their meaning."""
    value = os.fspath(value)
    if (type(value) is not str or not value.startswith("/") or
            any(ord(c) < 32 or ord(c) == 127 for c in value) or
            value.endswith(" (deleted)") or
            (value != "/" and any(p in ("", ".", "..") for p in value[1:].split("/")))):
        raise ValueError("Runtime requires an unambiguous absolute native path")
    if len(value.encode("utf-8", errors="strict")) >= 4096:
        raise ValueError("Runtime path exceeds the native pathname bound")
    return value


def _pin(path, *, canonical=False):
    if os.uname().machine not in ("x86_64", "aarch64"):
        raise OSError(errno.ENOTSUP, "Unverified runtime resolver syscall ABI")
    how = _OpenHow(os.O_PATH | os.O_CLOEXEC, 0,
                   _NO_MAGICLINKS | (_NO_SYMLINKS if canonical else 0))
    fd = _SYSCALL(_SYS_OPENAT2, _AT_FDCWD, path.encode("utf-8"),
                  ctypes.byref(how), ctypes.sizeof(how))
    if fd < 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), path)
    return fd


def _identity(fd):
    info = os.fstat(fd)
    if not info.st_nlink or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise ValueError("Runtime descriptor must identify a linked ordinary file or directory")
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def descriptor_path(fd):
    """Resolve a borrowed FD; the caller continues to own it even on error."""
    identity = _identity(fd)
    link = f"/proc/self/fd/{fd}"
    physical = native_name(os.readlink(link))
    check = _pin(physical, canonical=True)
    try:
        if _identity(check) != identity or os.readlink(link) != physical:
            raise OSError(errno.ESTALE, "Runtime descriptor name changed during resolution", physical)
    finally:
        os.close(check)
    return physical


def runtime_spellings(path):
    lexical = native_name(path)
    fd = _pin(lexical)
    try:
        physical = descriptor_path(fd)
        check = _pin(lexical)
        try:
            if _identity(check) != _identity(fd) or os.readlink(f"/proc/self/fd/{check}") != physical:
                raise OSError(errno.ESTALE, "Runtime alias changed during resolution", lexical)
        finally:
            os.close(check)
        return lexical, physical
    finally:
        os.close(fd)


def require_outside_workspace(path, workspace):
    for spelling in map(Path, runtime_spellings(path)):
        if spelling.is_relative_to(workspace) or Path(workspace).is_relative_to(spelling):
            raise ValueError("Runtime grants must not physically overlap the managed workspace")
