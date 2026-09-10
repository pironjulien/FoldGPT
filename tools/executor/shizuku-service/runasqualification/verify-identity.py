#!/usr/bin/env python3
"""Read-only, independent verification of the fixed device identity report."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path


def verify(report: dict) -> dict:
    def require(value: bool, message: str) -> None:
        if not value:
            raise ValueError(message)

    require(report['schema'] == 'foldgpt.runas.identity-activity.v1', 'Wrong Activity schema')
    require(report['action'] == 'app.foldgpt.runasqualification.v1.RUN_IDENTITY_FDS_V1', 'Wrong one-shot action')
    require(report['state'] == 'complete' and report['passed'] is True, 'Activity did not pass')
    service = report['service']
    require(service['schema'] == 'foldgpt.runas.identity-service.v1', 'Wrong service schema')
    require(service['serviceUid'] == 2000, 'UserService was not nonroot shell')
    require(service['state'] == 'complete' and service['waitStatus'] == 0, 'Owned child failed')
    for flag in ('passed', 'nativeSpawnAttempted', 'childReaped', 'pipeReadersComplete', 'pipesClosed', 'cleanupComplete', 'installationUnchanged'):
        require(service[flag] is True, f'Missing service evidence: {flag}')
    require(service['quarantined'] is False, 'Service retained quarantine')
    installation = service['installation']
    require(installation == report['installation'] == report['preflight'], 'Installation identities differ')
    target = installation['target']
    require(target['packageName'] == 'app.foldgpt' and target['dataDir'] == '/data/user/0/app.foldgpt', 'Wrong target')
    require(target['uid'] >= 10000 and target['debuggable'] is True, 'Target is not a regular debug app')
    require(target['signerSha256'] == '30930ffce7c10b673e95e69f2d78bb9e60aa71132db3c21cdc15cf56df77fa16', 'Wrong preserved signer')
    for key in ('apkSha256',):
        require(re.fullmatch('[a-f0-9]{64}', target[key]) is not None, 'Missing APK digest')
    for key in ('probeSha256', 'transportSha256'):
        require(re.fullmatch('[a-f0-9]{64}', installation[key]) is not None, 'Missing native digest')
    child, receipt = json.loads(service['stdout']), json.loads(service['stderr'])
    require(child == service['child'] and receipt == service['receipt'], 'Streams disagree with parsed records')
    require(child['schema'] == 'foldgpt.runas.identity-child.v1', 'Wrong child schema')
    require(receipt['schema'] == 'foldgpt.runas.identity-report.v1', 'Wrong independent fd2 receipt')
    require(re.fullmatch('[a-f0-9]{32}', service['nonce']) is not None, 'Invalid nonce')
    require(child['nonce'] == receipt['nonce'] == service['nonce'], 'FD challenges differ')
    require(child['pid'] == receipt['pid'] == service['ownerPid'], 'FD receipt is not from the reaped owner')
    require(child['parentPid'] == service['servicePid'], 'run-as was not the direct UserService child')
    require(child['uid'] == child['gid'] == [target['uid']] * 3, 'Actual credentials disagree with installed app')
    for flag in ('identityMatches', 'parentMatches', 'zeroCapabilities', 'cwdMatches', 'targetOwned',
                 'noExtraDescriptors', 'descriptorContract', 'stdinChallengeMatches',
                 'controlChallengeMatches', 'contextMatches', 'passed'):
        require(child[flag] is True, f'Missing child evidence: {flag}')
    require(child['noNewPrivileges'] == child['seccomp'] == 0, 'Inherited privilege/filter condition differs')
    require(child['cwd'] == target['dataDir'], 'Kernel cwd is not canonical target data')
    require(child['context'].startswith('u:r:runas_app:'), 'Observed domain does not match run-as')
    require([value & 3 for value in child['fdFlags']] == [0, 1, 1, 0], 'Four actual FD directions differ')
    status = dict(line.split(':', 1) for line in child['procStatus'].splitlines() if ':' in line)
    require([int(value) for value in status['Uid'].split()] == [target['uid']] * 4, 'Kernel Uid disagrees')
    require([int(value) for value in status['Gid'].split()] == [target['uid']] * 4, 'Kernel Gid disagrees')
    for cap in ('CapInh', 'CapPrm', 'CapEff', 'CapAmb'):
        require(int(status[cap].strip(), 16) == 0, f'Nonzero {cap}')
    for condition in ('NoNewPrivs', 'Seccomp', 'Seccomp_filters'):
        require(int(status[condition].strip()) == 0, f'Unexpected {condition}')
    require(receipt['reportFd'] == 2 and receipt['stdoutFlushed'] is True and receipt['passed'] is True, 'FD2 receipt incomplete')
    return {'schema': 'foldgpt.runas.identity-verification.v1', 'passed': True,
            'targetUid': target['uid'], 'ownerPid': child['pid'], 'servicePid': service['servicePid'],
            'scope': 'UserService to run-as to Bionic identity and fd0..3 only; no broker or shared-workspace proof'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    arguments = parser.parse_args()
    print(json.dumps(verify(json.loads(arguments.report.read_text(encoding='utf-8-sig'))), indent=2))
