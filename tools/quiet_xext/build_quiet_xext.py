"""Build the optional GNU/Linux ARM64 X11 diagnostic helper from source."""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]

def build():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clang', type=Path, default=os.environ.get('ANDROID_NDK_CLANG'),
                        help='Path to LLVM Clang; defaults to ANDROID_NDK_CLANG')
    parser.add_argument('--output', type=Path, default=ROOT / 'work' / 'quiet-xext' / 'libquiet_xext.so')
    args = parser.parse_args()
    if args.clang is None or not args.clang.is_file():
        parser.error('Provide an existing LLVM Clang executable with --clang or ANDROID_NDK_CLANG')
    src = Path(__file__).with_name('quiet_xext.c')
    out = args.output.resolve()
    if out.exists():
        parser.error('Output already exists; select a new output path')
    out.parent.mkdir(parents=True, exist_ok=True)
    # The helper has no headers or libc references, so it needs no guest sysroot.
    cmd = [
        str(args.clang.resolve()),
        '--target=aarch64-linux-gnu',
        '-shared',
        '-fPIC',
        '-O2',
        '-nostdlib',
        '-Wl,--no-undefined',
        '-Wl,-soname,libquiet_xext.so',
        str(src),
        '-o', str(out)
    ]
    subprocess.run(cmd, check=True)
    print(f'Built {out} ({out.stat().st_size} bytes)')

if __name__ == '__main__':
    build()
