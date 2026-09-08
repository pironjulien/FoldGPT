"""Build unmodified ripgrep with externally compiled PCRE2/JIT twice for Bionic.

Windows NDK compiles Android code. WSL's real pkg-config only resolves metadata;
no VM, Android execution or installation is part of this host build recipe.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location("ripgrep_verify", HERE / "verify-ripgrep-build.py")
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)

def text(path, value):
    path.write_text(value, encoding="utf-8")

def wsl_path(path):
    path = path.resolve()
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]

def main():
    sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--cmake", type=Path, default=Path("C:/Program Files/CMake/bin/cmake.exe"))
    parser.add_argument("--ninja", type=Path, required=True)
    parser.add_argument("--msvc", type=Path, required=True)
    parser.add_argument("--windows-sdk", type=Path, default=Path("C:/Program Files (x86)/Windows Kits/10"))
    parser.add_argument("--windows-sdk-version", default="10.0.26100.0")
    parser.add_argument("--wsl-distro", default="Ubuntu-24.04")
    args = parser.parse_args()
    prepared, output, ndk = args.prepared.resolve(), args.output.resolve(), args.ndk.resolve()
    prepared.relative_to(ROOT)
    output.relative_to(ROOT)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.wsl_distro) or re.search(r"[\s&|<>^%!]", str(output)):
        raise ValueError("The pkg-config dispatcher requires simple project/distro paths")
    source_manifest = verify.verify_sources(prepared)
    pins = source_manifest["pins"]
    if "Pkg.Revision = " + pins["ndkRevision"] not in (ndk / "source.properties").read_text(encoding="utf-8").splitlines():
        raise ValueError("Exact pinned NDK required")
    output.mkdir(parents=True, exist_ok=False)
    for name in ("tmp", "cargo-home"):
        (output / name).mkdir()
    recipe_before = [{"path": name, "bytes": (ROOT / name).stat().st_size,
                      "sha256": verify.digest(ROOT / name)} for name in verify.RECIPES]
    source = output / "source"
    source.mkdir()
    for name in ("sources", "vendor", "archives"):
        shutil.copytree(prepared / name, source / name)
    shutil.copyfile(prepared / "source-manifest.json", source / "source-manifest.json")
    llvm = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin"
    clang = llvm / "clang.exe"
    base_env = os.environ.copy()
    base_env.update(PATH=str(args.msvc / "bin/Hostx64/x64") + os.pathsep + str(llvm) + os.pathsep + base_env["PATH"],
                    LIB=os.pathsep.join(str(p) for p in (args.msvc / "lib/x64",
                        args.windows_sdk / "Lib" / args.windows_sdk_version / "ucrt/x64",
                        args.windows_sdk / "Lib" / args.windows_sdk_version / "um/x64")),
                    INCLUDE=os.pathsep.join(str(p) for p in (args.msvc / "include",
                        args.windows_sdk / "Include" / args.windows_sdk_version / "ucrt",
                        args.windows_sdk / "Include" / args.windows_sdk_version / "shared",
                        args.windows_sdk / "Include" / args.windows_sdk_version / "um")),
                    TMP=str(output / "tmp"), TEMP=str(output / "tmp"), CARGO_HOME=str(output / "cargo-home"),
                    SOURCE_DATE_EPOCH=str(source_manifest["sourceDateEpoch"]),
                    GIT_CEILING_DIRECTORIES=str(source / "sources"))
    commands = []
    def run(command, log, cwd=output, env=base_env, timeout=1800):
        command = [str(v) for v in command]
        commands.append({"command": command, "cwd": str(cwd), "log": log.relative_to(output).as_posix()})
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=timeout)
        log.with_suffix(".stdout").write_bytes(result.stdout)
        log.with_suffix(".stderr").write_bytes(result.stderr)
        text(output / "commands.json", json.dumps(commands, indent=2) + "\n")
        if result.returncode:
            print(result.stdout.decode("utf-8", errors="replace")[-5000:])
            print(result.stderr.decode("utf-8", errors="replace")[-5000:])
        result.check_returncode()
        return result.stdout.decode("utf-8").strip()
    toolchain = {
        "clang": run([clang, "--version"], output / "clang-version"),
        "rustc": run(["rustc", "+" + pins["rustToolchain"], "-vV"], output / "rustc-version"),
        "cargo": run(["cargo", "+" + pins["rustToolchain"], "--version"], output / "cargo-version"),
        "cmake": run([args.cmake, "--version"], output / "cmake-version"),
        "ninja": run([args.ninja, "--version"], output / "ninja-version"),
        "pkgConfig": run(["wsl.exe", "-d", args.wsl_distro, "--exec", "pkg-config", "--version"], output / "pkg-config-version"),
        "ndk": pins["ndkRevision"], "host": "windows-x86_64", "target": pins["target"], "api": pins["androidApi"]}
    builtins = Path(run([clang, "--target=aarch64-linux-android35", "--print-libgcc-file-name"], output / "clang-builtins-path"))
    builtins.resolve(strict=True).relative_to(ndk)
    compiler_files = [clang, llvm / "llvm-ar.exe", llvm / "ld.lld.exe", builtins, args.cmake, args.ninja,
        Path(run(["rustup", "which", "--toolchain", pins["rustToolchain"], "rustc"], output / "rustc-path")),
        Path(run(["rustup", "which", "--toolchain", pins["rustToolchain"], "cargo"], output / "cargo-path"))]
    toolchain["files"] = [{"path": path.as_posix(), "bytes": path.stat().st_size,
                           "sha256": verify.digest(path)} for path in compiler_files]
    hardening = "-Wl,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384,-z,common-page-size=16384"
    for part in ("first", "second"):
        directory = output / part
        directory.mkdir()
        for name in ("tmp", "cargo-home", "cargo-target"):
            (directory / name).mkdir()
        prefix = directory / "prefix"
        env = base_env.copy()
        env.update(TMP=str(directory / "tmp"), TEMP=str(directory / "tmp"),
                   CARGO_HOME=str(directory / "cargo-home"), CARGO_TARGET_DIR=str(directory / "cargo-target"),
                   CARGO_INCREMENTAL="0", PCRE2_SYS_STATIC="0", PKG_CONFIG_ALLOW_CROSS="1",
                   PKG_CONFIG_ALL_STATIC="1")
        text(directory / "cargo-home/config.toml", '[source.crates-io]\nreplace-with = "vendored-sources"\n'
             '[source.vendored-sources]\ndirectory = ' + json.dumps((source / "vendor").as_posix()) + '\n')
        cflags = "-O2 -g0 -ffile-prefix-map=" + ROOT.as_posix() + "=/foldgpt-project"
        cflags += " -ffile-prefix-map=" + directory.as_posix() + "=/foldgpt-build"
        run([args.cmake, "-S", source / "sources" / pins["pcre2"]["directory"], "-B", directory / "pcre2",
             "-G", "Ninja", "-DCMAKE_MAKE_PROGRAM=" + args.ninja.as_posix(),
             "-DCMAKE_TOOLCHAIN_FILE=" + (ndk / "build/cmake/android.toolchain.cmake").as_posix(),
             "-DANDROID_ABI=arm64-v8a", "-DANDROID_PLATFORM=android-35", "-DCMAKE_BUILD_TYPE=Release",
             "-DCMAKE_INSTALL_PREFIX=" + prefix.as_posix(), "-DCMAKE_INSTALL_LIBDIR=lib",
             "-DCMAKE_C_FLAGS_RELEASE=" + cflags, "-DCMAKE_EXE_LINKER_FLAGS=" + hardening,
             "-DBUILD_SHARED_LIBS=OFF", "-DBUILD_STATIC_LIBS=ON", "-DPCRE2_STATIC_PIC=ON",
             "-DPCRE2_BUILD_PCRE2_8=ON", "-DPCRE2_BUILD_PCRE2_16=ON", "-DPCRE2_BUILD_PCRE2_32=ON",
             "-DPCRE2_SUPPORT_JIT=ON"], directory / "cmake-configure", env=env)
        run([args.cmake, "--build", directory / "pcre2", "--parallel", "8"], directory / "cmake-build", env=env)
        run([args.cmake, "--install", directory / "pcre2"], directory / "cmake-install", env=env)
        # Dispatch to the genuine resolver. Its generated .pc uses Windows prefixes,
        # so cargo receives native Windows library/include paths for cross linking.
        dispatcher = directory / "pkg-config.cmd"
        text(dispatcher, '@echo off\n@wsl.exe -d ' + args.wsl_distro + ' --exec env '
             'PKG_CONFIG_PATH= PKG_CONFIG_LIBDIR=' + wsl_path(prefix / "lib/pkgconfig")
             + ' pkg-config --static %*\n')
        env["PKG_CONFIG"] = str(dispatcher)
        flags = run([dispatcher, "--libs", "--cflags", "libpcre2-8"], directory / "pkg-config-link", env=env)
        if prefix.as_posix() not in flags or "-lpcre2-8" not in flags:
            raise ValueError("Genuine pkg-config did not select the external PCRE2")
        linker = llvm / "aarch64-linux-android35-clang.cmd"
        env["CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER"] = str(linker)
        rustflags = ["--remap-path-prefix=" + str(ROOT) + "=/foldgpt-project",
                     "--remap-path-prefix=" + str(directory) + "=/foldgpt-build",
                     "-C", "link-arg=" + hardening,
                     # Rust's -nodefaultlibs omits the real ARM instruction-cache
                     # synchronization routine needed after PCRE2 emits JIT code.
                     "-C", "link-arg=" + builtins.as_posix()]
        env["CARGO_ENCODED_RUSTFLAGS"] = "\x1f".join(rustflags)
        run(["cargo", "+" + pins["rustToolchain"], "build", "--locked", "--offline", "--profile", "release-lto",
             "--target", pins["target"], "--features", "pcre2", "--bin", "rg"], directory / "cargo-build",
            cwd=source / "sources" / pins["ripgrep"]["directory"], env=env)
        pcre_outputs = list((directory / "cargo-target" / pins["target"] / "release-lto/build").glob("pcre2-sys-*/output"))
        if len(pcre_outputs) != 1: raise ValueError("Expected exactly one pcre2-sys build metadata file")
        metadata = pcre_outputs[0].read_text(encoding="utf-8")
        if "cargo:rustc-link-lib=static=pcre2-8" not in metadata:
            raise ValueError("Cargo did not select the independently compiled static PCRE2")
        text(directory / "pcre2-sys-link.txt", metadata)
        shutil.copyfile(directory / "cargo-target" / pins["target"] / "release-lto/rg", directory / "libfoldgpt_rg.so")
        run([clang, "--target=aarch64-linux-android35", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
             "-fPIE", "-pie", hardening, "-I" + str(prefix / "include"), HERE / "pcre2-jit-probe.c",
             prefix / "lib/libpcre2-8.a", "-o", directory / "libfoldgpt_pcre2_jit_probe.so"], directory / "probe-build", env=env)
        for name in verify.FILES:
            verify.elf(directory / name)
            run([llvm / "llvm-readelf.exe", "-h", "-l", "-d", directory / name], directory / (name + "-elf"), env=env)
        text(directory / "environment.json", json.dumps({key: env[key] for key in (
            "SOURCE_DATE_EPOCH", "GIT_CEILING_DIRECTORIES", "TMP", "TEMP", "CARGO_HOME", "CARGO_TARGET_DIR",
            "CARGO_INCREMENTAL", "PCRE2_SYS_STATIC", "PKG_CONFIG_ALLOW_CROSS", "PKG_CONFIG_ALL_STATIC", "PKG_CONFIG",
            "CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER", "CARGO_ENCODED_RUSTFLAGS")}, indent=2) + "\n")
        print(part + " Android compile completed", flush=True)
    build_hashes = {name: [verify.digest(output / part / name) for part in ("first", "second")] for name in verify.FILES}
    if any(hashes[0] != hashes[1] for hashes in build_hashes.values()):
        text(output / "nonreproducible.json", json.dumps(build_hashes, indent=2) + "\n")
        raise ValueError("Independent Android builds differ")
    verify.verify_sources(source)
    for name in verify.FILES: shutil.copyfile(output / "first" / name, output / name)
    recipe = [{"path": name, "bytes": (ROOT / name).stat().st_size, "sha256": verify.digest(ROOT / name)} for name in verify.RECIPES]
    if recipe != recipe_before: raise ValueError("Canonical build recipe changed during compilation")
    notices = []
    for tree in (source / "sources", source / "vendor"):
        for path in sorted(tree.rglob("*")):
            if path.is_file() and re.match(r"^(?:COPYING|LICEN[CS]E|UNLICEN[CS]E|COPYRIGHT)(?:$|[._-])", path.name, re.I):
                relative = path.relative_to(source).as_posix()
                notices.append("===== " + relative + " =====\n" + path.read_text(encoding="utf-8", errors="replace"))
    text(output / "ripgrep-notices.txt", "\n\n".join(notices) + "\n")
    evidence_paths = ["commands.json", "ripgrep-notices.txt"]
    for part in ("first", "second"):
        evidence_paths.extend(part + "/" + name for name in (
            "pcre2/CMakeCache.txt", "pcre2/src/config.h", "pcre2-sys-link.txt", "environment.json", "pkg-config.cmd",
            "prefix/lib/libpcre2-8.a", "prefix/lib/libpcre2-16.a", "prefix/lib/libpcre2-32.a",
            "prefix/lib/pkgconfig/libpcre2-8.pc", "cargo-build.stdout", "cargo-build.stderr"))
    evidence = [{"path": name, "bytes": (output / name).stat().st_size,
                 "sha256": verify.digest(output / name)} for name in evidence_paths]
    record = {"schema": "foldgpt.bionic-ripgrep-build.v1", "pins": pins,
        "sourceManifestSha256": verify.digest(source / "source-manifest.json"),
        "cargoLockSha256": source_manifest["cargoLockSha256"], "sourceDateEpoch": source_manifest["sourceDateEpoch"],
        "recipe": recipe, "toolchain": toolchain, "evidence": evidence,
        "reproducible": True, "sourceFilesUnchanged": True,
        "pcre2Jit": True, "pcre2Linkage": "external-static", "androidExecuted": False,
        "files": {name: verify.elf(output / name) for name in verify.FILES}, "buildHashes": build_hashes}
    text(output / "build.json", json.dumps(record, indent=2) + "\n")
    verify.verify(output)
    print(json.dumps({"output": str(output), "files": record["files"], "reproducible": True, "androidExecuted": False}))

if __name__ == "__main__": main()
