"""Read-only memory accounting; unavailable process readings never mean zero."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import subprocess


def kib_values(result):
    if result['code'] != 0:
        return {}
    return {key: int(value) for key, value in
            re.findall(r'^(\w+):\s+(\d+) kB\s*$', result['text'], re.M)}


def uid_processes(result, uid):
    if result['code'] != 0:
        raise ValueError('Process enumeration failed')
    lines = result['text'].splitlines()
    if not lines or lines[0].split() != ['UID', 'PID', 'PPID', 'NAME']:
        raise ValueError('Unexpected process table header')
    processes = []
    for line in lines[1:]:
        fields = line.split(None, 3)
        if len(fields) != 4 or not all(value.isdecimal() for value in fields[:3]):
            raise ValueError('Invalid numeric process table')
        if int(fields[0]) == uid:
            processes.append({'pid': int(fields[1]), 'parent': int(fields[2]), 'name': fields[3]})
    if len({p['pid'] for p in processes}) != len(processes):
        raise ValueError('Duplicate process identity')
    return processes


def process_identity(result):
    if result['code'] != 0:
        return None
    # comm can contain spaces and parentheses; field 22 is starttime.
    match = re.fullmatch(r'(\d+) \(.*\) (\S.*)', result['text'].strip(), re.S)
    if not match:
        return None
    fields = match[2].split()
    if len(fields) < 20 or not fields[19].isdecimal():
        return None
    return int(match[1]), int(fields[19])


def summarize_pss(processes, uid, stable_membership):
    observed = []
    unavailable = []
    for record in processes:
        before = process_identity(record['statBefore'])
        after = process_identity(record['statAfter'])
        final = process_identity(record['statFinal'])
        status = record['status']
        uid_match = re.search(r'^Uid:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$',
                              status['text'], re.M) if status['code'] == 0 else None
        same_owner = uid_match is not None and all(int(value) == uid for value in uid_match.groups())
        pss = kib_values(record['smaps_rollup']).get('Pss')
        if before is None or before != after or before != final or before[0] != record['pid'] or not same_owner or pss is None:
            unavailable.append(record['pid'])
        else:
            observed.append(pss)
    complete = stable_membership and not unavailable
    return {
        'summedPssKiB': sum(observed) if complete else None,
        'observedPssKiB': sum(observed) if observed or complete else None,
        'pssObservedCount': len(observed), 'processCount': len(processes),
        'pssUnavailablePids': unavailable, 'pssCoverageComplete': complete,
        'samePidSetAtBoundaries': stable_membership,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial', required=True)
    parser.add_argument('--package', default='app.foldgpt')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output must be new to preserve previous observations')
    adb = [args.adb, '-s', args.serial]

    def read(*parts, app=False):
        argv = ['run-as', args.package, *parts] if app else list(parts)
        try:
            # shell -T retains the remote status, unlike the older exec-out path.
            result = subprocess.run(adb + ['shell', '-T', shlex.join(argv)],
                                    capture_output=True, timeout=15)
            return {'code': result.returncode, 'text': result.stdout.decode(errors='replace'),
                    'stderr': result.stderr.decode(errors='replace')}
        except (OSError, subprocess.TimeoutExpired) as error:
            return {'code': None, 'text': '', 'stderr': str(error)}

    report = {'schemaVersion': 3, 'observedAt': datetime.now(timezone.utc).isoformat(),
              'serial': args.serial, 'package': args.package,
              'scope': 'Sequential process snapshot, not an atomic measurement or reservation; '
                       'PSS excludes some graphics driver accounting and other UIDs (including Shizuku).',
              'bootBefore': read('cat', '/proc/sys/kernel/random/boot_id'),
              'meminfo': read('cat', '/proc/meminfo'), 'processes': []}
    report['memoryKiB'] = kib_values(report['meminfo'])
    failed = False
    try:
        report['uidRead'] = read('id', '-u', app=True)
        uid_text = report['uidRead']['text'].strip()
        if report['uidRead']['code'] != 0 or not uid_text.isdecimal():
            raise ValueError('Package UID could not be read')
        report['uid'] = uid = int(uid_text)
        ps_before = read('ps', '-A', '-o', 'UID,PID,PPID,NAME')
        report['psBefore'] = {key: ps_before[key] for key in ('code', 'stderr')}
        report['processes'] = processes = uid_processes(ps_before, uid)
        for record in processes:
            pid = record['pid']
            record['statBefore'] = read('cat', f'/proc/{pid}/stat', app=True)
            for name in ('status', 'smaps_rollup', 'limits', 'cgroup'):
                record[name] = read('cat', f'/proc/{pid}/{name}', app=True)
            record['statAfter'] = read('cat', f'/proc/{pid}/stat', app=True)
        ps_after = read('ps', '-A', '-o', 'UID,PID,PPID,NAME')
        report['psAfter'] = {key: ps_after[key] for key in ('code', 'stderr')}
        after = uid_processes(ps_after, uid)
        report['psAfter']['pids'] = [p['pid'] for p in after]
        # A PID may be reused after its own PSS window but before the last ps.
        for record in processes:
            record['statFinal'] = read('cat', f"/proc/{record['pid']}/stat", app=True)
        report['bootAfter'] = read('cat', '/proc/sys/kernel/random/boot_id')
        boot_before, boot_after = report['bootBefore'], report['bootAfter']
        stable_boot = (boot_before['code'] == boot_after['code'] == 0 and
                       bool(boot_before['text'].strip()) and
                       boot_before['text'].strip() == boot_after['text'].strip())
        stable_membership = stable_boot and {p['pid'] for p in processes} == {p['pid'] for p in after}
        report.update(summarize_pss(processes, uid, stable_membership))
    except ValueError as error:
        report.update(collectionError=str(error), summedPssKiB=None, pssCoverageComplete=False)
        failed = True
    report['completedAt'] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8', newline='\n') as output:
        json.dump(report, output, indent=2)
        output.write('\n')
    keys = ('observedAt', 'completedAt', 'uid', 'memoryKiB', 'summedPssKiB', 'observedPssKiB',
            'processCount', 'pssObservedCount', 'pssUnavailablePids', 'pssCoverageComplete',
            'samePidSetAtBoundaries', 'collectionError', 'scope')
    print(json.dumps({key: report[key] for key in keys if key in report}, indent=2))
    return 2 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
