import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CLANG = Path(os.environ.get('ANDROID_NDK_CLANG', r'C:\Users\julie\AppData\Local\Android\Sdk\ndk\29.0.14206865\toolchains\llvm\prebuilt\windows-x86_64\bin\clang.exe'))
SYSROOT = ROOT / 'downloads' / 'gpu' / 'sysroot'

def build():
    src = Path(__file__).with_name('quiet_xext.c')
    out = Path(__file__).with_name('libquiet_xext.so')
    cmd = [
        str(CLANG),
        '--target=aarch64-linux-gnu',
        f'--sysroot={SYSROOT}',
        '-shared',
        '-fPIC',
        '-O2',
        '-nostdlib',
        '-Wl,-soname,libquiet_xext.so',
        str(src),
        '-o', str(out)
    ]
    subprocess.run(cmd, check=True)
    print(f'Built {out} ({out.stat().st_size} bytes)')

if __name__ == '__main__':
    build()
