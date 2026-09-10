"""PC/Linux qualification of the actual JNI fork/FD/wait code, not Android policy.

Run as ordinary UID 65534. A compile-time host-only admission selects that UID;
the Android CMake build never sets FOLDGPT_TRANSPORT_HOST_TEST.
"""
import concurrent.futures
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
JAVA = r'''
package app.foldgpt.shizukuexec;
public final class NativeHostCheck {
    public static void main(String[] args) throws Exception {
        NativeSpawn.load(args[0]);
        int pid = NativeSpawn.launch(args[1], new String[] {args[1], "-I", "-u", "-c", args[2]},
            Integer.parseInt(args[3]), Integer.parseInt(args[4]), Integer.parseInt(args[5]), Integer.parseInt(args[6]));
        int status = NativeSpawn.waitChild(pid);
        System.out.println(status);
    }
}
'''
CHILD = r'''
import os, selectors, sys
try:
    os.fstat(128)
except OSError:
    pass
else:
    raise RuntimeError("Inherited forbidden descriptor")
select = selectors.DefaultSelector()
select.register(0, selectors.EVENT_READ)
select.register(3, selectors.EVENT_READ)
data = bytearray()
while True:
    ready = select.select()
    if any(key.fd == 3 for key, _ in ready):
        os.write(2, b"cancelled\n")
        sys.exit(23)
    chunk = os.read(0, 65536)
    if not chunk:
        break
    data.extend(chunk)
os.write(2, b"stdin-eof\n")
view = memoryview(bytes(data)[::-1])
while view:
    count = os.write(1, view)
    view = view[count:]
'''


def run():
    if os.getuid() != 65534:
        raise SystemExit("Run this PC-only test as UID 65534")
    with tempfile.TemporaryDirectory(prefix="foldgpt-transport-", dir="/var/tmp") as temporary:
        root = Path(temporary)
        jdk = Path(shutil.which("javac")).resolve().parents[1]
        native = root / "libtransport.so"
        subprocess.run(["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
            "-DFOLDGPT_TRANSPORT_HOST_TEST", "-I" + str(jdk / "include"), "-I" + str(jdk / "include/linux"),
            str(HERE / "transport/src/main/cpp/spawn.c"), "-o", str(native)], check=True)
        fixture = root / "NativeHostCheck.java"
        fixture.write_text(JAVA)
        subprocess.run(["javac", "-d", str(root), str(fixture),
            str(HERE / "transport/src/main/java/app/foldgpt/shizukuexec/NativeSpawn.java")], check=True)
        leaked = os.open("/dev/null", os.O_RDONLY)
        os.dup2(leaked, 128, inheritable=True)
        os.close(leaked)
        for cancellation in (False, True):
            stdin = os.pipe()
            stdout = os.pipe()
            report = os.pipe()
            control = os.pipe()
            process = subprocess.Popen(["java", "-cp", str(root), "app.foldgpt.shizukuexec.NativeHostCheck",
                str(native), "/usr/bin/python3", CHILD,
                str(stdin[0]), str(stdout[1]), str(report[1]), str(control[0])],
                pass_fds=(stdin[0], stdout[1], report[1], control[0], 128), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for fd in (stdin[0], stdout[1], report[1], control[0]):
                os.close(fd)
            payload = bytes(range(256)) * 4096

            def write_input():
                with os.fdopen(stdin[1], "wb", buffering=0) as stream:
                    view = memoryview(payload)
                    while view:
                        view = view[stream.write(view):]

            def read_output():
                with os.fdopen(stdout[0], "rb") as stream:
                    return stream.read()

            with concurrent.futures.ThreadPoolExecutor() as pool:
                output = pool.submit(read_output)
                if cancellation:
                    # stdin stays OPEN and empty; dedicated EOF must wake the
                    # bootstrap without depending on a blocked client writer.
                    os.close(control[1])
                else:
                    writing = pool.submit(write_input)
                host_stdout, host_stderr = process.communicate(timeout=10)
                assert process.returncode == 0, host_stderr
                if cancellation:
                    assert host_stdout == b"5888\n", host_stdout  # real waitpid exit 23
                    assert output.result(timeout=2) == b""
                    os.close(stdin[1])
                else:
                    writing.result(timeout=2)
                    assert host_stdout == b"0\n", host_stdout
                    assert output.result(timeout=2) == payload[::-1]
                    os.close(control[1])
            with os.fdopen(report[0], "rb") as stream:
                assert stream.read() == (b"cancelled\n" if cancellation else b"stdin-eof\n")
        os.close(128)
    print("PASS: actual JNI fork/exec; 1 MiB binary input/output; stderr; real stdin EOF; independent cancellation EOF; exit 23/waitpid; inherited FD closure")


if __name__ == "__main__":
    run()
