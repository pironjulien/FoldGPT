"""Freeze current native sources and compile Linux helpers without an Android SDK."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def build(project: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    source = destination / "package/tools/executor"
    for relative in ("tools", "tools/executor", "tools/policy"):
        package = destination / "package" / relative
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").touch()
    for relative in ("tools/executor", "tools/executor/bionic-supervisor", "tools/policy"):
        output = destination / "package" / relative
        output.mkdir(parents=True, exist_ok=True)
        for path in sorted((project / relative).glob("*.py")):
            shutil.copyfile(path, output / path.name)
    inputs = {
        "runner": "bionic-supervisor/runner.c",
        "host-runner": "bionic-supervisor/host-runner.c",
        "direct-runner": "bionic-supervisor/direct-runner.c",
        "direct-worker": "bionic-supervisor/direct-worker.c",
        "host-search-only-cwd": "bionic-supervisor/test_host_search_only_cwd.c",
        "native-files": "native-files.c",
        "native-file-handle": "native-file-handle.c",
        "paused-helper": "test_bootstrap_paused_helper.c",
        "qualification-worker": "bionic-supervisor/qualification-worker.c",
        "runtime-paths-test": "bionic-supervisor/test_runtime_paths.c",
        "executable-metadata-test": "bionic-supervisor/test_executable_metadata_worker.c",
        "native-process-fd-abi": "native-process-fd-abi.c",
    }
    for relative in (*inputs.values(), "native-runner-seccomp.h", "bionic-supervisor/host-fd-seccomp.h",
                     "bionic-cwd/cwd.c", "bionic-cwd/exports.map"):
        output = source / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project / "tools/executor" / relative, output)
    common = ["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(source)]
    for name, relative in inputs.items():
        extra = ["-pthread"] if name in ("qualification-worker", "executable-metadata-test", "direct-worker") else []
        subprocess.run([*common, *extra, str(source / relative), "-o", str(destination / name)], check=True)
    # The same two narrowly scoped fault fixtures as the canonical host builder.
    original = (source / "bionic-supervisor/runner.c").read_text()
    faults = {
        "runner-after-final-stop": (
            "(void)packet(final,(size_t)length,1);return ",
            "(void)packet(final,(size_t)length,1);raise(SIGSTOP);return "),
        "runner-getdents-memory-missing": (
            "case SYS_getdents64:{int mem=memory(listener,n);",
            '''case SYS_getdents64:{
      char fault_fd[96],fault_path[MAX_PATH];
      snprintf(fault_fd,sizeof(fault_fd),"/proc/%u/fd/%d",n->pid,(int)n->data.args[0]);
      ssize_t fault_len=readlink(fault_fd,fault_path,sizeof(fault_path)-1);
      int fault_project=fault_len>=8&&!memcmp(fault_path+fault_len-8,"/project",8);
      int mem=fault_project?-1:memory(listener,n);if(fault_project)errno=ENOENT;'''),
    }
    for name, (anchor, replacement) in faults.items():
        if original.count(anchor) != 1:
            raise RuntimeError(f"Canonical fault fixture anchor changed: {name}")
        fixture = destination / f"{name}.c"
        fixture.write_text(original.replace(anchor, replacement))
        subprocess.run([*common, str(fixture), "-o", str(destination / name)], check=True)
    subprocess.run([
        *common, "-fPIC", "-fvisibility=hidden", "-fstack-protector-strong", "-D_FORTIFY_SOURCE=2",
        "-shared", "-Wl,--as-needed,--no-undefined,-z,relro,-z,now,-z,noexecstack",
        f"-Wl,--version-script={source / 'bionic-cwd/exports.map'}", "-Wl,-soname,libfoldgpt_bionic_cwd.so",
        str(source / "bionic-cwd/cwd.c"), "-o", str(destination / "libfoldgpt_bionic_cwd.host.so"),
    ], check=True)
    files = []
    for path in sorted(destination.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Unexpected helper alias: {path}")
        if path.is_file():
            data = path.read_bytes()
            files.append({"path": path.relative_to(destination).as_posix(), "bytes": len(data),
                          "sha256": hashlib.sha256(data).hexdigest()})
    (destination / "manifest.json").write_text(json.dumps({"files": files}, indent=2) + "\n")
