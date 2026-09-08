"""Independently check the real new run-as broker result (no device actions)."""
import argparse
import json
from pathlib import Path

PROOFS = {'memoryRead', 'memoryWrite', 'pidfdGetfd', 'sharedOffset', 'privateReadDenied',
          'protectedWriteDenied', 'rawChdirDenied', 'networkDenied', 'ioctlDenied', 'binderDenied',
          'threadMemory', 'threadPidfdGetfd'}


def verify(report):
    def require(value, message):
        if not value:
            raise ValueError(message)
    require(report['schema'] == 'foldgpt.runas.broker-activity.v2', 'Wrong Activity schema')
    require(report['action'] == 'app.foldgpt.runasbrokerqualification.v2.RUN_BROKER_V2', 'Wrong independent action')
    require(report['state'] == 'complete' and report['passed'] is True, 'Activity failed')
    service = report['service']
    require(service['schema'] == 'foldgpt.runas.broker-service.v2', 'Wrong service schema')
    require(service['serviceUid'] == 2000 and service['waitStatus'] == 0, 'Wrong shell identity or failed owner')
    for key in ('passed', 'childReaped', 'pipeReadersComplete', 'pipesClosed', 'cleanupComplete',
                'nativeCleanupVerified', 'installationUnchanged'):
        require(service[key] is True, 'Missing service proof: ' + key)
    require(service['quarantined'] is False, 'Service quarantine retained')
    require(report['installation'] == report['preflight'] == service['installation'], 'Install identity mismatch')
    installed = service['installation']
    require(installed['target']['packageName'] == 'app.foldgpt' and installed['target']['debuggable'] is True, 'Wrong target app')
    require(installed['qualification']['packageName'] == 'app.foldgpt.runasbrokerqualification.v2', 'Wrong diagnostic APK')
    require(installed['nativeLibraries']['libfoldgpt_bionic_supervisor.so']
            == '6bccc77b4f2dff0f78fd22e4f6427263ee159d87b35c740e8be0622319fd4dd4', 'Runner is not the reviewed qKM94iHA')
    require(installed['nativeLibraries']['libfoldgpt_qualification_worker.so']
            == '0769ff3a7877cfcf13dc8cd49d5d3b865eef524718358e0e5b93951903166b3a', 'Wrong fixed Bionic workload')
    child, receipt = json.loads(service['stdout']), json.loads(service['stderr'])
    require(child == service['child'] and receipt == service['receipt'], 'Raw streams mismatch parsed records')
    require(child['schema'] == 'foldgpt.runas.broker-child.v2' and receipt['schema'] == 'foldgpt.runas.broker-report.v2', 'Wrong native receipt schemas')
    require(child['pid'] == receipt['pid'] == service['ownerPid'], 'Reaped owner mismatch')
    require(child['nonce'] == receipt['nonce'] == service['nonce'], 'Native correlation nonce differs')
    for record in (child, receipt):
        require(record['passed'] is True and record['cleanupComplete'] is True, 'Native cleanup was not proved')
    require(child['quarantined'] is False and child['stdinChallengeMatches'] is True, 'Native challenge/quarantine differs')
    identity = child['identity']
    require(identity['pid'] == service['ownerPid'] and identity['parentPid'] == service['servicePid'], 'Wrong actual Python ancestry')
    require(identity['uid'] == identity['gid'] == [installed['target']['uid']] * 3, 'Python is not the target app UID/GID')
    require(identity['context'].startswith('u:r:runas_app:'), 'Python domain differs')
    for key in ('CapInh', 'CapPrm', 'CapEff', 'CapAmb'):
        require(int(identity['status'][key], 16) == 0, 'Nonzero Python ' + key)
    for key in ('NoNewPrivs', 'Seccomp', 'Seccomp_filters'):
        require(int(identity['status'][key]) == 0, 'Wrong inherited Python ' + key)
    require(child['supervisorReturncode'] == 0 and child['processClosed'] is True, 'Supervisor was not really waited cleanly')
    result = child['nativeResult']
    require(result['started'] is True and result['cleanupComplete'] is True and result['outcome'] == 'exited'
            and result['exitCode'] == result['signal'] == 0, 'Trusted native lifecycle report failed')
    proofs = json.loads(child['stdout'])
    require(proofs == child['proofs'], 'Worker stream differs from result')
    require(set(proofs) == PROOFS | {'type', 'success'} and proofs['type'] == 'kernel-qualification', 'Wrong exact proof set')
    require(all(proofs[key] is True for key in PROOFS | {'success'}) and child['stderr'] == '', 'Real broker mechanism failed')
    require(child['options']['workspace'] == '/data/user/0/app.foldgpt/files/runas-native-v2/workspace', 'Workspace is not app-private')
    return {'schema': 'foldgpt.runas-broker-verification.v2', 'passed': True, 'kernelProofs': len(PROOFS),
            'targetUid': installed['target']['uid'], 'bootstrapPid': child['pid'], 'supervisorPid': child['supervisorPid'],
            'scope': 'Actual UserService/run-as/Bionic native broker; PRoot shared paths and UI remain unqualified'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(json.loads(args.report.read_text(encoding='utf-8-sig'))), indent=2))
