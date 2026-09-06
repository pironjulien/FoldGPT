"""Independently collect one fixed Android HTTPS acquisition diagnostic.

Read-only ADB; no acquisition, package copy, installation, account or profile
access. Targets derive from the fixture and the independently fixed descriptor,
never report paths. Supplied Java build snapshots are recorded separately from
APK/DEX identity; this collector does not attest Java source-to-DEX equivalence.
"""
import argparse
import base64
from datetime import datetime, timezone
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import struct
import subprocess
import uuid
import zipfile

SOURCE_URL = 'https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_arm64.deb'


@dataclass(frozen=True)
class Descriptor:
    version: str
    package_sha: str
    package_bytes: int
    tar_bytes: int
    members: int

    @property
    def document(self):
        return f'foldgpt.https-artifact.v1\n{SOURCE_URL}\n{self.package_bytes}\n{self.package_sha}\n'.encode('ascii')

    @property
    def key(self):
        return hashlib.sha256(self.document).hexdigest()

    @property
    def cache_base(self):
        return 'acquisition-cache/foldgpt-acquisition/' + self.key

    @property
    def artifact(self):
        return self.cache_base + '/verified.artifact'


DESCRIPTORS = {
    '26.901.41600': Descriptor('26.901.41600',
        '8d5141b299ca593255fa25760895e84375937cc305197528c822dfa71ac2a3bf', 388651910, 1365770240, 7360),
    '26.901.51231': Descriptor('26.901.51231',
        '02a2f5c6cb69509c62abcbdd13c76b139cdb2ca9edde7537239ddde024077ea0', 388605714, 1365708800, 7360),
}
REPORT_NAMES = ('report.json', 'progress.json', 'android-completion.txt')
SOURCE_NAMES = ('NativeHttpsAcquisitionProbeService.java', 'TrustedHttpsArtifact.java',
                'AndroidTrustedHttpsArtifact.java', 'AndroidInactiveClientInstaller.java')
CLASSES = {'Lapp/foldgpt/NativeHttpsAcquisitionProbeService;',
           'Lapp/foldgpt/install/TrustedHttpsArtifact;', 'Lapp/foldgpt/install/AndroidTrustedHttpsArtifact;',
           'Lapp/foldgpt/install/AndroidInactiveClientInstaller;'}
COMPONENT = 'app.foldgpt/.NativeHttpsAcquisitionProbeService'
PROCESS = 'app.foldgpt:httpsAcquisitionProbe'
META_FIELDS = {'identity', 'uid', 'gid', 'mode', 'size', 'links', 'kind'}
DIRECTORY_STABLE_FIELDS = ('identity', 'uid', 'gid', 'mode', 'kind')


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON field')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs, parse_constant=lambda value: require(False, 'Nonfinite JSON number'))


def same(left, right):
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def stable_directory(value):
    return {key: value[key] for key in DIRECTORY_STABLE_FIELDS}


def verify_setgid_report(report, uid):
    require(report.get('managedCacheIdentityOwnerModePreserved') is True, 'No Android parent preservation evidence')
    for key in ('managedCacheBefore', 'managedCacheAfter', 'evidenceDirectory'):
        value = report.get(key)
        require(type(value) is dict and set(value) == META_FIELDS and value['kind'] == 'directory'
            and type(value['uid']) is int and value['uid'] == uid and type(value['gid']) is int and value['gid'] > 0
            and isinstance(value['identity'], str) and re.fullmatch(r'[0-9]+:[0-9]+', value['identity'])
            and isinstance(value['mode'], str) and re.fullmatch(r'[0-7]{4}', value['mode'])
            and type(value['size']) is int and value['size'] >= 0 and type(value['links']) is int and value['links'] > 0,
            'Malformed parent/new-directory metadata: ' + key)
    require(same(stable_directory(report['managedCacheBefore']), stable_directory(report['managedCacheAfter']))
        and int(report['managedCacheBefore']['mode'], 8) & 0o2000,
        'Android setgid parent identity/ownership/mode were not preserved')
    require(report['evidenceDirectory']['mode'] == '0700'
        and report['evidenceDirectory']['identity'] == report['evidenceIdentity'], 'New diagnostic directory is not exactly 0700')


def dex_classes(data):
    """Read actual DEX class definitions, not merely referenced string names."""
    require(data[:4] == b'dex\n' and data[7:8] == b'\0' and len(data) >= 112, 'Unsupported DEX header')
    size, header_size, endian = struct.unpack_from('<III', data, 32)
    require(size == len(data) and header_size == 112 and endian == 0x12345678, 'Malformed DEX size/endian')
    string_count, string_offset, type_count, type_offset = struct.unpack_from('<IIII', data, 56)
    class_count, class_offset = struct.unpack_from('<II', data, 96)
    require(string_offset + 4 * string_count <= size and type_offset + 4 * type_count <= size
            and class_offset + 32 * class_count <= size, 'DEX table exceeds file')
    names = set()
    for index in range(class_count):
        type_index = struct.unpack_from('<I', data, class_offset + 32 * index)[0]
        require(type_index < type_count, 'Invalid DEX class type index')
        string_index = struct.unpack_from('<I', data, type_offset + 4 * type_index)[0]
        require(string_index < string_count, 'Invalid DEX descriptor index')
        offset = struct.unpack_from('<I', data, string_offset + 4 * string_index)[0]
        for _ in range(5):
            require(offset < size, 'DEX descriptor length exceeds file')
            byte = data[offset]
            offset += 1
            if byte < 128:
                break
        else:
            raise ValueError('Invalid DEX descriptor ULEB128')
        end = data.find(b'\0', offset)
        require(end >= offset, 'Unterminated DEX descriptor')
        # Only ASCII app descriptors are selected; unrelated valid MUTF8 names
        # need not be interpreted to establish these four definitions.
        candidate = data[offset:end]
        if candidate.startswith(b'Lapp/foldgpt/'):
            names.add(candidate.decode('ascii'))
    return names


def verify_traffic(value):
    require(set(value) == {'before', 'after', 'rxBytesDelta', 'txBytesDelta'}, 'Malformed supplementary traffic report')
    for sample in (value['before'], value['after']):
        require({'rxBytes', 'txBytes'} <= set(sample) <= {'rxBytes', 'txBytes', 'unavailableType'}
                and all(type(sample[key]) is int and sample[key] >= -1 for key in ('rxBytes', 'txBytes')),
                'Invalid shared-UID traffic sample')
    for field in ('rxBytes', 'txBytes'):
        first, second = value['before'][field], value['after'][field]
        expected = None if first < 0 or second < first else second - first
        require(same(value[field + 'Delta'], expected), 'Invalid shared-UID traffic delta')


def verify_report(report, progress, completion, raw_report, uid, fixture, descriptor):
    """Validate terminal diagnostic claims without choosing any device targets."""
    require(report.get('schema') == 'foldgpt.https-acquisition-probe.v1'
            and report.get('status') in {'PASS', 'FAIL', 'CANCELLED'}, 'No terminal HTTPS report')
    status = report['status']
    require(completion == f'{status} uid={uid} reportSha256={sha(raw_report)}\n'.encode('ascii'),
            'Completion does not bind the exact terminal report bytes and UID')
    constants = {'scope': 'official-client-https-acquisition-and-cache-revalidation-only', 'uid': uid,
        'process': PROCESS, 'trustedClientVersion': descriptor.version, 'trustedClientSha256': descriptor.package_sha,
        'trustedClientBytes': descriptor.package_bytes, 'trustedClientTarBytes': descriptor.tar_bytes, 'trustedClientMembers': descriptor.members,
        'sourceDeclaration': 'AndroidInactiveClientInstaller.Descriptor.sourceUrl',
        'installationAttempted': False, 'activationAttempted': False, 'liveProfileAccessAttempted': False,
        'keyringAccessAttempted': False, 'tlsConfiguration': 'platform-default-trust-and-hostname-verification',
        'downloadDeadlineMillis': 1200000, 'cacheDeadlineMillis': 180000, 'serviceDeadlineMillis': 1500000,
        'workerFinalizationReached': True, 'uidTrafficScope': 'shared-app-uid-counter-not-an-http-request-counter'}
    for key, value in constants.items():
        require(key in report and same(report[key], value), 'Fixed diagnostic contract differs: ' + key)
    require(str(uuid.UUID(report['runId'])) == report['runId'], 'Invalid diagnostic run UUID')
    for key in ('gid', 'pid', 'androidApi', 'startedElapsedRealtimeMillis', 'durationMillis',
                'firstProgressCallbacks', 'firstReceivedBytes', 'secondProgressCallbacks'):
        require(type(report.get(key)) is int and report[key] >= 0, 'Invalid diagnostic numeric field: ' + key)
    require(report['gid'] > 0 and report['pid'] > 0 and report['androidApi'] >= 35, 'Unexpected Android execution identity')
    require(report['firstReceivedBytes'] <= descriptor.package_bytes, 'Acquisition progress exceeds the trusted descriptor')
    if 'evidenceLeaf' in report:
        require(report['evidenceLeaf'] == fixture, 'Report belongs to a different fixture')
    if progress is not None:
        require(set(progress) == {'schema', 'received', 'expected', 'elapsedMillis'}
                and progress['schema'] == 'foldgpt.https-acquisition-progress.v1'
                and type(progress['received']) is int and 0 < progress['received'] <= descriptor.package_bytes
                and type(progress['expected']) is int and progress['expected'] == descriptor.package_bytes
                and type(progress['elapsedMillis']) is int and 0 <= progress['elapsedMillis'] <= report['durationMillis'],
                'Invalid actual progress checkpoint')
    if status != 'PASS':
        if status == 'CANCELLED' and report.get('cancellationReason') in {'SERVICE_DEADLINE', 'SERVICE_DESTROYED'}:
            return status
        errors = report.get('errors', report.get('cacheInventoryErrors'))
        require(type(errors) is list and 1 <= len(errors) <= 8 and all(set(error) == {'type', 'message'}
            and isinstance(error['type'], str) and isinstance(error['message'], str) and len(error['message']) <= 512
            for error in errors), 'Failed terminal report lacks a bounded real error chain')
        return status
    require('errors' not in report and 'cacheInventoryErrors' not in report and report['phase'] == 'complete',
            'PASS report contains an error or unfinished phase')
    verify_setgid_report(report, uid)
    require(progress is not None and progress['received'] == descriptor.package_bytes
            and report['firstReceivedBytes'] == descriptor.package_bytes and 0 < report['firstProgressCallbacks'] <= descriptor.package_bytes,
            'No evidence of a complete actual first body download')
    required = {'evidenceLeaf': fixture, 'cacheInitiallyEmpty': True, 'sourceUrl': SOURCE_URL,
        'descriptorCacheKey': descriptor.key, 'artifactRelativePath': descriptor.artifact, 'firstResumedFrom': 0,
        'cacheNetworkGuard': 'worker-only-StrictMode-detectNetwork-penaltyDeathOnNetwork',
        'cacheNetworkGuardPassed': True, 'sameArtifactInode': True, 'cacheReuseVerified': True,
        'secondProgressCallbacks': 0, 'cancellationReason': '-'}
    for key, value in required.items():
        require(key in report and same(report[key], value), 'Acquisition/revalidation proof differs: ' + key)
    for key in ('firstAcquireMillis', 'cacheAcquireMillis'):
        require(type(report.get(key)) is int and 0 <= report[key] <= report['durationMillis'], 'Invalid acquisition duration')
    require(progress['elapsedMillis'] <= report['firstAcquireMillis'], 'Body progress completed after acquisition returned')
    require(report['firstAcquireMillis'] + report['cacheAcquireMillis'] <= report['durationMillis'], 'Durations are inconsistent')
    for name in ('firstUidTraffic', 'secondUidTraffic'):
        verify_traffic(report[name])
    for name in ('firstFile', 'secondFile'):
        file = report[name]
        require(set(file) == META_FIELDS | {'sha256', 'hashedBytes'} and file['kind'] == 'file'
                and file['mode'] == '0600' and type(file['links']) is int and file['links'] == 1
                and type(file['uid']) is int and file['uid'] == uid and type(file['size']) is int
                and file['size'] == file['hashedBytes'] == descriptor.package_bytes and file['sha256'] == descriptor.package_sha,
                'Actual independent file verification differs from trusted descriptor')
    require(same(report['firstFile'], report['secondFile']), 'First and cached physical artifact evidence differ')
    inventory = report['cacheInventory']
    require(type(inventory) is list and len(inventory) == 6 and all(set(row) == META_FIELDS | {'path'} for row in inventory),
            'Unexpected final private cache inventory')
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('serial', 'fixture'):
        parser.add_argument('--' + name, required=True)
    for name in ('apk', 'build-sources', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument("--descriptor-version", choices=sorted(DESCRIPTORS), required=True)
    args = parser.parse_args()
    descriptor = DESCRIPTORS[args.descriptor_version]
    require(re.fullmatch(r'https-[0-9]{1,20}', args.fixture), 'Expected exact announced HTTPS fixture name')
    remote = 'cache/' + args.fixture
    adb = ['adb', '-s', args.serial]
    apk_sha = sha(args.apk.read_bytes())
    collector_source = Path(__file__).read_bytes()
    source_data = {}
    for name in SOURCE_NAMES:
        source = args.build_sources / name
        require(source.is_file() and not source.is_symlink() and source.stat().st_size <= 1024 * 1024,
                'Missing ordinary bounded build-source snapshot: ' + name)
        source_data[name] = source.read_bytes()

    def shell(*command, app=True, allow_absent=False):
        argv = ['run-as', 'app.foldgpt', *command] if app else list(command)
        result = subprocess.run(adb + ['shell', '-T', shlex.join(argv)], timeout=60, capture_output=True)
        require((result.returncode == 0 or allow_absent and result.returncode == 1 and not result.stdout)
                and not result.stderr, 'Device read failed: ' + command[0])
        return result.stdout

    def remote_hash(target):
        digest = shell('sha256sum', target).split(maxsplit=1)[0].decode('ascii')
        require(re.fullmatch(r'[0-9a-f]{64}', digest), 'Invalid native SHA-256 response')
        return digest

    def apk_pin():
        lines = shell('pm', 'path', 'app.foldgpt', app=False).decode().splitlines()
        require(len(lines) == 1 and re.fullmatch(r'package:/data/app/[A-Za-z0-9_+=.~/-]+/base\.apk', lines[0]),
                'Expected one Package Manager owned APK')
        path = lines[0][8:]
        require('..' not in PurePosixPath(path).parts, 'Invalid package location')
        digest = remote_hash(path)
        require(digest == apk_sha, 'Installed APK differs from the supplied tested APK')
        return {'path': path, 'sha256': digest}

    before = apk_pin()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'collector-source.py').write_bytes(collector_source)
    (args.output / 'build-sources').mkdir()
    for name, data in source_data.items():
        (args.output / 'build-sources' / name).write_bytes(data)
    dex_hashes, definitions = {}, set()
    with zipfile.ZipFile(args.apk) as apk:
        require(len(apk.namelist()) == len(set(apk.namelist())), 'Duplicate APK entries')
        for name in apk.namelist():
            if re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex', name):
                data = apk.read(name)
                definitions.update(dex_classes(data))
                dex_hashes[name] = sha(data)
        require(CLASSES <= definitions, 'APK does not define the four acquisition classes')
    uid = int(shell('id', '-u').strip())
    require(uid > 0, 'Expected nonroot application UID')
    snapshots = {}

    def raw_metadata(target):
        fields = shell('stat', '-c', '%f %u %g %s %d %i %a %h', target).decode().split()
        require(len(fields) == 8, 'Malformed native file metadata')
        mode = int(fields[0], 16)
        kind = 'directory' if stat.S_ISDIR(mode) else 'file' if stat.S_ISREG(mode) else 'other'
        item = {'identity': fields[4] + ':' + fields[5], 'uid': int(fields[1]), 'gid': int(fields[2]),
                'mode': format(int(fields[6], 8), '04o'), 'size': int(fields[3]), 'links': int(fields[7]), 'kind': kind}
        require(item['uid'] == uid and kind != 'other'
                and (kind == 'directory' or item['links'] == 1), 'Unexpected ownership, alias or public diagnostic target')
        return item

    def metadata(relative):
        value = raw_metadata(remote + ('/' + relative if relative else ''))
        require(not int(value['mode'], 8) & 0o077, 'Diagnostic target is not private')
        return value

    parent_before = raw_metadata('cache')
    require(parent_before['kind'] == 'directory', 'Android cache parent is not a real directory')
    root_info = metadata('')
    require(root_info['kind'] == 'directory', 'Diagnostic leaf is not a directory')

    def present(relative):
        path = shlex.quote(remote + '/' + relative)
        value = shell('sh', '-c', f'if test -e {path} || test -L {path}; then echo present; else echo absent; fi').strip()
        require(value in (b'present', b'absent'), 'Invalid diagnostic existence response')
        return value == b'present'

    def read_fixed(relative, maximum=65536):
        info = metadata(relative)
        require(info['kind'] == 'file' and info['mode'] == '0600' and info['size'] <= maximum, 'Not a bounded private report')
        data = base64.b64decode(b''.join(shell('base64', remote + '/' + relative).splitlines()), validate=True)
        require(len(data) == info['size'] and remote_hash(remote + '/' + relative) == sha(data), 'Report changed during read')
        snapshots[relative] = {'metadata': info, 'sha256': sha(data)}
        target = args.output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return data

    presence = {name: present(name) for name in REPORT_NAMES}
    data = {name: read_fixed(name) for name, exists in presence.items() if exists}
    raw_report = data.get('report.json')
    report = strict_json(raw_report) if raw_report is not None else None
    progress = strict_json(data['progress.json']) if presence['progress.json'] else None
    status = 'INCOMPLETE_EVIDENCE'
    if report is not None and presence['android-completion.txt']:
        terminal = verify_report(report, progress, data['android-completion.txt'], raw_report, uid, args.fixture, descriptor)
        status = 'PASS' if terminal == 'PASS' else 'OBSERVED_FAILURE'
    elif presence['android-completion.txt']:
        raise ValueError('Completion exists without its exact report')
    # No payload-selected path is used. Inspect only the exact cache layout
    # derived above; a failed/incomplete acquisition may have only a prefix.
    expected_children = {'': set(REPORT_NAMES) | {'acquisition-cache'},
        'acquisition-cache': {'foldgpt-acquisition'}, 'acquisition-cache/foldgpt-acquisition': {descriptor.key},
        descriptor.cache_base: {'descriptor.v1', 'lease', 'verified.artifact', 'download.part', 'descriptor.next'}}
    cache_inventory = []
    for directory in ('', 'acquisition-cache', 'acquisition-cache/foldgpt-acquisition', descriptor.cache_base):
        if directory and not present(directory):
            continue
        info = metadata(directory)
        require(info['kind'] == 'directory', 'Expected ordinary cache directory')
        names = shell('ls', '-A', remote + ('/' + directory if directory else '')).decode('utf-8').splitlines()
        require(len(names) == len(set(names)) and set(names) <= expected_children[directory], 'Unknown entry in strict diagnostic cache')
        if status == 'PASS':
            require(info['mode'] == '0700', 'PASS cache directory has unexpected special bits/mode')
            wanted = expected_children[directory] - ({'download.part', 'descriptor.next'} if directory == descriptor.cache_base else set())
            require(set(names) == wanted, 'PASS diagnostic cache is incomplete or has partial artifacts')
        if directory:
            cache_inventory.append({**info, 'path': '.' if directory == 'acquisition-cache' else directory.removeprefix('acquisition-cache/')})
    for name in ('descriptor.v1', 'lease', 'verified.artifact', 'download.part', 'descriptor.next'):
        relative = descriptor.cache_base + '/' + name
        if not present(relative):
            continue
        info = metadata(relative)
        require(info['kind'] == 'file' and info['mode'] == '0600', 'Unexpected cache file type or mode')
        if name in ('descriptor.v1', 'descriptor.next'):
            require(read_fixed(relative, 16384) == descriptor.document, 'Physical cache descriptor differs from independent constant')
        elif name == 'lease':
            require(info['size'] == 0, 'Lease file unexpectedly contains data')
            snapshots[relative] = {'metadata': info, 'sha256': remote_hash(remote + '/' + relative)}
        else:
            require(info['size'] <= descriptor.package_bytes, 'Private downloaded file exceeds trusted size')
            digest = remote_hash(remote + '/' + relative)  # Never copy proprietary package bytes.
            snapshots[relative] = {'metadata': info, 'sha256': digest}
            if status == 'PASS':
                require(name == 'verified.artifact' and info['size'] == descriptor.package_bytes and digest == descriptor.package_sha,
                        'Actual published package bytes differ from independently trusted descriptor')
        cache_inventory.append({**info, 'path': relative.removeprefix('acquisition-cache/')})
    if status == 'PASS':
        require(same(stable_directory(parent_before), stable_directory(report['managedCacheBefore']))
            and same(stable_directory(root_info), stable_directory(report['evidenceDirectory'])),
            'Reported setgid parent/new-directory identity, owner or mode differ from actual paths')
        require(report['evidenceIdentity'] == root_info['identity'] and report['cacheIdentity'] == metadata('acquisition-cache')['identity'],
                'Report directory identities differ from actual fixture')
        artifact = snapshots[descriptor.artifact]
        require(same({key: report['firstFile'][key] for key in META_FIELDS}, artifact['metadata']), 'Reported file metadata differs from actual package')
        actual_rows = {row['path']: row for row in cache_inventory}
        reported_rows = {row['path']: row for row in report['cacheInventory']}
        require(len(reported_rows) == len(report['cacheInventory']) and same(actual_rows, reported_rows), 'Reported cache inventory differs from physical tree')
    # Independently inspect the one fixed service. A cached Android process may
    # remain after stopSelf; it is not itself a running foreground service.
    service_state = shell('dumpsys', 'activity', 'services', COMPONENT, app=False)
    (args.output / 'service-state.txt').write_bytes(service_state)
    service_inactive = b'ServiceRecord{' not in service_state
    process_ids = shell('pidof', PROCESS, app=False, allow_absent=True).decode().split()
    require(len(process_ids) <= 1 and all(re.fullmatch(r'[1-9][0-9]*', pid) for pid in process_ids), 'Unexpected diagnostic process identity')
    process_info = {'pids': process_ids, 'serviceInactive': service_inactive, 'threads': []}
    if process_ids:
        pid = process_ids[0]
        native_status = shell('cat', '/proc/' + pid + '/status').decode()
        uid_line = re.search(r'^Uid:\s+([0-9]+)\s+([0-9]+)\s+([0-9]+)\s+([0-9]+)', native_status, re.M)
        require(uid_line is not None and all(int(value) == uid for value in uid_line.groups()), 'Diagnostic process UID differs')
        tids = shell('ls', '/proc/' + pid + '/task').decode().split()
        require(len(tids) <= 128 and all(re.fullmatch(r'[1-9][0-9]*', tid) for tid in tids), 'Invalid dedicated process task list')
        for tid in tids:
            name = shell('cat', '/proc/' + pid + '/task/' + tid + '/comm').decode().strip()
            process_info['threads'].append({'tid': int(tid), 'name': name})
        process_info['workerThreadsAbsent'] = not any(thread['name'] in {
            'FoldGPT-https-acquisition-probe'[:15], 'FoldGPT-https-probe-disconnect'[:15]}
            for thread in process_info['threads'])
    if status == 'PASS':
        require(service_inactive and process_info.get('workerThreadsAbsent', True),
                'Terminal PASS exists while its service or worker/disconnect thread is still active')
    for name, info in snapshots.items():
        require(same(metadata(name), info['metadata']) and remote_hash(remote + '/' + name) == info['sha256'], 'Private evidence changed during collection')
    require({name: present(name) for name in REPORT_NAMES} == presence, 'Report publication changed during collection')
    after = apk_pin()
    parent_after = raw_metadata('cache')
    require(same(stable_directory(parent_before), stable_directory(parent_after)),
            'Android cache parent identity, ownership or mode changed during collection')
    require(before == after and sha(args.apk.read_bytes()) == apk_sha, 'APK changed during collection')
    require(Path(__file__).read_bytes() == collector_source
            and all((args.build_sources / name).read_bytes() == value for name, value in source_data.items()),
            'Collector or supplied build snapshot changed during collection')
    result = {'schema': 'foldgpt.https-acquisition-independent.v1', 'status': status,
        'fixture': args.fixture, 'uid': uid, 'collectedAtUtc': datetime.now(timezone.utc).isoformat(),
        'reportStatus': report.get('status') if report else None, 'reportFilesPresent': presence,
        'apkSha256': apk_sha, 'testedApkPath': str(args.apk.resolve()), 'installedApkBefore': before, 'installedApkAfter': after,
        'dexSha256': dex_hashes, 'requiredDexDefinitions': sorted(CLASSES),
        'buildSourceSnapshotsSha256': {name: sha(value) for name, value in source_data.items()},
        'buildSourceLimit': 'Integrator-supplied build-input snapshots, separately hashed; no source-to-DEX equivalence attestation.',
        'fixedDescriptor': {'version': descriptor.version, 'url': SOURCE_URL, 'bytes': descriptor.package_bytes, 'sha256': descriptor.package_sha, 'cacheKey': descriptor.key},
        'physicalCacheInventory': cache_inventory, 'fixtureFiles': snapshots, 'processState': process_info,
        'managedCacheBeforeCollection': parent_before, 'managedCacheAfterCollection': parent_after,
        'parentComparisonScope': 'Identity, UID/GID, kind and mode only; directory size/link counts may change normally.',
        'collectorSha256': sha(collector_source),
        'evidenceSha256': {path.relative_to(args.output).as_posix(): sha(path.read_bytes()) for path in args.output.rglob('*') if path.is_file()},
        'scope': 'Actual fixed HTTPS acquisition/cache-revalidation evidence and physical private package hash only; no proprietary package copied, no installation, activation or profile access. Shared-UID traffic is not a request count or proof of zero network traffic.'}
    (args.output / 'independent-verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'fixture', 'reportStatus', 'apkSha256', 'reportFilesPresent')}, indent=2))


if __name__ == '__main__':
    main()
