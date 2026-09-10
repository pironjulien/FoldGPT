#!/usr/bin/env python3
"""Host socketpair tests using the production writer and exact checked JNI body."""
import hashlib
import json
import pathlib
import subprocess


def main():
    repo = pathlib.Path(__file__).resolve().parents[2]
    native = repo / "vendor/termux-x11/lorie/src/main/cpp/lorie"
    output = repo / "work/native-input-20260909/client-writer"
    output.mkdir(parents=True, exist_ok=True)
    activity = (native / "activity.cpp").read_text()
    header = (native / "lorie.h").read_text()
    keymap = header[header.index("static int android_to_linux_keycode"):]
    keymap = keymap[:keymap.index("\n};") + 3]
    function = activity[activity.index("static jint sendInputEventChecked"):]
    function = function[:function.index("\nextern char* __progname;")]
    (output / "keymap.c").write_text("#include <linux/input-event-codes.h>\n" + keymap.replace("static int ", "int ", 1))
    (output / "checked-input-under-test.inc").write_text('extern "C" int android_to_linux_keycode[304];\n' + function)
    sources = [native / name for name in ("activity.cpp", "client-writer.h", "clipboard-reader.h", "event-protocol.h", "lorie.h", "renderer.cpp")]
    sources += [pathlib.Path(__file__), repo / "tools/gpu/test-native-client-writer.cpp"]
    hashes = {str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    (output / "source-input.json").write_text(json.dumps(hashes, indent=2) + "\n")
    subprocess.run(["gcc", "-c", "-fsanitize=address,undefined", "-g",
                    str(output / "keymap.c"), "-o", str(output / "keymap.o")], check=True)
    command = ["g++", "-std=gnu++17", "-pthread", "-Wall", "-Wextra", "-Werror",
               "-fsanitize=address,undefined", "-g",
               "-I", str(native), "-I", str(output),
               str(repo / "tools/gpu/test-native-client-writer.cpp"),
               str(output / "keymap.o"),
               "-o", str(output / "client-writer-test")]
    subprocess.run(command, check=True)
    result = subprocess.run([str(output / "client-writer-test")], capture_output=True, text=True, timeout=45)
    (output / "test-output.txt").write_text(result.stdout + result.stderr)
    print(result.stdout + result.stderr, end="")
    result.check_returncode()


if __name__ == "__main__":
    main()
