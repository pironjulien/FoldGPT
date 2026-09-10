"""Select an existing guest account for a developer installation; never create accounts.

The Android runtime independently validates passwd, group and home at startup.
This migration tool refuses to replace an existing selection.
"""
import argparse
import re
import shlex
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--user", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", args.user):
        parser.error("Invalid guest account name")
    adb = ["adb", "-s", args.serial, "shell", "run-as", "app.foldgpt"]
    passwd = subprocess.check_output(adb + ["cat", "files/debian/etc/passwd"], text=True)
    entries = [line.split(":") for line in passwd.splitlines()]
    found = [row for row in entries if row[0] == args.user]
    if len(found) != 1 or len(found[0]) != 7:
        raise RuntimeError("Guest account missing or ambiguous")
    account = found[0]
    if (not account[2].isdigit() or not account[3].isdigit() or int(account[2]) == 0
            or int(account[3]) == 0 or account[5:] != ["/home/" + args.user, "/bin/bash"]):
        raise RuntimeError("Account does not satisfy the interactive guest contract")
    # Names are restricted above. Atomic publication uses rename within the
    # application directory; an existing selection is preserved and compared.
    command = """
set -eu
umask 077
target=files/debian/etc/foldgpt-user
[ ! -L files/debian/etc ] && [ -d files/debian/etc ]
[ ! -L "$target" ]
if [ ! -e "$target" ]; then
    stage=$(mktemp files/debian/etc/.foldgpt-user.XXXXXXXX)
    trap 'rm -f "$stage"' EXIT
    cat > "$stage"
    chmod 644 "$stage"
    sync "$stage"
    mv -n "$stage" "$target"
    sync files/debian/etc
fi
cat "$target"
"""
    expected = (args.user + "\n").encode()
    actual = subprocess.check_output(adb + ["sh", "-c", shlex.quote(command)], input=expected)
    if actual.replace(b"\r\n", b"\n") != expected:
        raise RuntimeError("Existing guest selection differs; preserved without replacement")
    print("Explicit guest identity selected; Android validates the database at startup.")


if __name__ == "__main__":
    main()
