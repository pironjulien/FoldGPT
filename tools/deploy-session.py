"""Update only FoldGPT's own guest integration scripts in the debug APK."""
import argparse
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serial", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
adb = ["adb", "-s", args.serial]
for name, target in {
    "foldgpt_keyring.py": "usr/local/lib/foldgpt/foldgpt_keyring.py",
    "foldgpt_ime.py": "usr/local/lib/foldgpt/foldgpt_ime.py",
    "keyboard-focus.js": "usr/local/lib/foldgpt/keyboard-focus.js",
    "foldgpt-session.sh": "usr/local/bin/foldgpt-session",
}.items():
    data = (root / name).read_bytes().replace(b"\r\n", b"\n")
    subprocess.run(adb + ["shell", "run-as", "app.foldgpt", "sh", "-c",
                         f"'cat > files/debian/{target}'"], input=data, check=True)
subprocess.run(adb + ["shell", "run-as", "app.foldgpt", "chmod", "700",
                     "files/debian/usr/local/bin/foldgpt-session"], check=True)
print("Updated guest integration scripts. Restart FoldGPT to load them.")
