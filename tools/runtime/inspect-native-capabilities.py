"""Read-only capability inventory; never starts Shizuku or exercises isolation.

Kernel config and declared hardware features are not permission tests. Existing
process snapshots distinguish Android app, ADB shell and Shizuku identities.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    observations = {}

    def read(name, command, *, binary=False):
        # shell-v2 carries the remote status and keeps stderr separate. exec-out
        # is reserved for raw binary bytes and has no reliable remote exit code.
        transport = ['exec-out'] if binary else ['shell', '-T']
        result = subprocess.run([args.adb, '-s', args.serial, *transport, shlex.join(command)],
                                capture_output=True, timeout=20)
        suffix = '.bin' if binary else '.txt'
        (args.output / (name + suffix)).write_bytes(result.stdout)
        record = {'command': command, 'exitCode': None if binary else result.returncode,
                  'transportExitCode': result.returncode,
                  'sha256': hashlib.sha256(result.stdout).hexdigest(),
                  'bytes': len(result.stdout), 'stderr': result.stderr.decode(errors='replace')}
        if not binary:
            record['text'] = result.stdout.decode(errors='replace')
        observations[name] = record
        return result

    serial = read('serial', ['getprop', 'ro.serialno'])
    if serial.returncode or serial.stdout.decode().strip() != args.serial:
        raise SystemExit('Connected device serial differs; no further inventory collected')
    props = ['ro.product.model', 'ro.product.device', 'ro.product.manufacturer',
             'ro.soc.model', 'ro.soc.manufacturer', 'ro.board.platform',
             'ro.product.cpu.abilist', 'ro.build.version.release', 'ro.build.version.sdk',
             'ro.build.version.oneui', 'ro.build.version.security_patch',
             'ro.build.fingerprint', 'ro.boot.warranty_bit', 'ro.boot.verifiedbootstate',
             'ro.boot.flash.locked']
    for prop in props:
        read(prop, ['getprop', prop])
    for name, command in {
        'uname': ['uname', '-a'], 'uptime': ['cat', '/proc/uptime'],
        'cpuinfo': ['cat', '/proc/cpuinfo'], 'page-size': ['getconf', 'PAGESIZE'],
        'memory': ['cat', '/proc/meminfo'], 'selinux': ['getenforce'],
        'shell-identity': ['id'], 'shell-context': ['cat', '/proc/self/attr/current'],
        'shell-status': ['cat', '/proc/self/status'],
        'app-run-as-identity': ['run-as', 'app.foldgpt', 'id'],
        'app-run-as-context': ['run-as', 'app.foldgpt', 'cat', '/proc/self/attr/current'],
        'app-run-as-status': ['run-as', 'app.foldgpt', 'cat', '/proc/self/status'],
        'declared-features': ['pm', 'list', 'features'],
        'binder-services': ['service', 'list'],
        'shizuku-package': ['pm', 'path', 'moe.shizuku.privileged.api'],
        'shizuku-package-list': ['pm', 'list', 'packages', '-u', 'shizuku'],
        'shizuku-version': ['sh', '-c', 'dumpsys package moe.shizuku.privileged.api | grep -E "versionCode=|versionName="'],
        'processes': ['ps', '-A', '-o', 'UID,PID,PPID,NAME,LABEL'],
        'active-lsm': ['cat', '/sys/kernel/security/lsm'],
        'unprivileged-bpf': ['cat', '/proc/sys/kernel/unprivileged_bpf_disabled'],
        'gpu-model': ['cat', '/sys/class/kgsl/kgsl-3d0/gpu_model'],
    }.items():
        read(name, command)
    config = read('kernel-config-gzip', ['cat', '/proc/config.gz'], binary=True)
    kernel_settings = {}
    if config.returncode == 0:
        decoded = gzip.decompress(config.stdout)
        (args.output / 'kernel.config').write_bytes(decoded)
        for line in decoded.decode().splitlines():
            if line.startswith('CONFIG_') and '=' in line:
                key, value = line.split('=', 1)
                kernel_settings[key] = value
            elif match := re.fullmatch(r'# (CONFIG_\w+) is not set', line):
                kernel_settings[match[1]] = 'n'
    auxv = read('shell-auxv', ['cat', '/proc/self/auxv'], binary=True)
    capabilities = {}
    if auxv.returncode == 0 and len(auxv.stdout) % 16 == 0:
        # Only publish architecture/page-size entries, not process addresses.
        for tag, value in struct.iter_unpack('<QQ', auxv.stdout):
            if tag in {6, 16, 26}:
                capabilities[{6: 'AT_PAGESZ', 16: 'AT_HWCAP', 26: 'AT_HWCAP2'}[tag]] = hex(value)
    process_rows = []
    for line in observations['processes']['text'].splitlines()[1:]:
        fields = line.split()
        if len(fields) != 5:
            continue
        uid, pid, ppid, name, label = fields
        if name.startswith('app.foldgpt') or 'shizuku' in name.lower():
            if not pid.isdigit():
                raise ValueError('Unexpected process id')
            record = {'uid': uid, 'pid': int(pid), 'ppid': int(ppid), 'name': name, 'label': label}
            result = read('process-' + pid + '-status', ['cat', '/proc/' + pid + '/status'])
            if result.returncode and name.startswith('app.foldgpt'):
                read('process-' + pid + '-status-run-as', ['run-as', 'app.foldgpt', 'cat', '/proc/' + pid + '/status'])
            process_rows.append(record)
    report = {'observedAt': datetime.now(timezone.utc).isoformat(), 'serial': args.serial,
              'scope': 'Read-only inventory, no namespace/seccomp/ptrace probe; run-as is not Zygote',
              'observations': observations, 'kernelSettings': kernel_settings,
              'auxvHardware': capabilities, 'selectedProcesses': process_rows}
    (args.output / 'inventory.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    keys = ['CONFIG_USER_NS', 'CONFIG_PID_NS', 'CONFIG_NAMESPACES', 'CONFIG_NET_NS',
            'CONFIG_SECCOMP', 'CONFIG_SECCOMP_FILTER', 'CONFIG_SECURITY_LANDLOCK', 'CONFIG_KVM']
    print(json.dumps({'observedAt': report['observedAt'], 'kernelSettingsCount': len(kernel_settings),
                      'kernelSelection': {key: kernel_settings.get(key, 'unobserved') for key in keys},
                      'auxvHardware': capabilities, 'selectedProcesses': process_rows,
                      'output': str(args.output)}, indent=2))


if __name__ == '__main__':
    main()
