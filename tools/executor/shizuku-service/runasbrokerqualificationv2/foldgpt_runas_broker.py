"""One fixed Android broker workload after the native run-as admission.

The installed APK chooses every path, executable and policy. Stdio carries only
the fixed nonce challenge; fd3 carries cancellation. No model or shell API.
"""
import asyncio
import base64
import importlib
import json
import os
from pathlib import Path
import signal
import stat
import sys
import zipfile

BASE = Path('/data/user/0/app.foldgpt/files/runas-native-v2')
WORKSPACE = BASE / 'workspace'
BROKER = BASE / 'broker'
SESSION = 'runas-broker-v2'
PROCESS = 'kernel-qualification'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(expected_uid, expected_parent):
    require(sys.platform == 'android' and sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,
            'Expected actual isolated Android interpreter')
    require(os.getresuid() == os.getresgid() == (expected_uid,) * 3 and expected_uid >= 10000,
            'Installed FoldGPT credentials differ')
    require(os.getppid() == expected_parent, 'Bootstrap is not the direct service child')
    with open('/proc/self/status', encoding='ascii') as source:
        status = dict(row.split(':', 1) for row in source.read(65536).splitlines() if ':' in row)
    for key in ('CapInh', 'CapPrm', 'CapEff', 'CapAmb'):
        require(int(status[key].strip(), 16) == 0, 'Nonzero ' + key)
    for key in ('NoNewPrivs', 'Seccomp', 'Seccomp_filters'):
        require(int(status[key].strip()) == 0, 'Unexpected ' + key)
    with open('/proc/self/attr/current', encoding='ascii') as source:
        context = source.read(4096).rstrip('\n\0')
    require(context.startswith('u:r:runas_app:'), 'Unexpected actual run-as context')
    return {'pid': os.getpid(), 'parentPid': os.getppid(), 'uid': list(os.getresuid()),
            'gid': list(os.getresgid()), 'context': context,
            'status': {key: value.strip() for key, value in status.items()}}


def emit(fd, record):
    data = (json.dumps(record, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')
    require(len(data) <= 32768, 'Fixed report exceeded its bound')
    offset = 0
    while offset < len(data):
        count = os.write(fd, data[offset:])
        require(count > 0, 'Incomplete fixed report')
        offset += count


async def run(apk, expected_uid, expected_parent, nonce):
    result = {'schema': 'foldgpt.runas.broker-child.v2', 'nonce': nonce, 'pid': os.getpid(),
              'passed': False, 'processStartAttempted': False, 'nativeWorkerStarted': False, 'cleanupComplete': False}
    backend = owner = operation = cancellation = record = None
    entered = False
    cancelled = asyncio.Event()
    loop = asyncio.get_running_loop()

    def control_ready():
        try:
            os.read(3, 1)
        except BlockingIOError:
            return
        loop.remove_reader(3)
        cancelled.set()

    try:
        result['identity'] = identity(expected_uid, expected_parent)
        require(Path.cwd() == Path('/data/user/0/app.foldgpt'), 'run-as cwd differs')
        require(len(nonce) == 32 and all(char in '0123456789abcdef' for char in nonce), 'Wrong nonce')
        os.set_inheritable(3, False)
        os.set_blocking(3, False)
        loop.add_reader(3, control_ready)
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, cancelled.set)
        challenge = ('foldgpt.runas.broker.v2:stdin:' + nonce + '\n').encode('ascii')
        received = bytearray()
        while len(received) <= len(challenge):
            data = os.read(0, len(challenge) + 1 - len(received))
            if not data:
                break
            received.extend(data)
        require(received == challenge, 'Fixed stdin challenge differs')
        result['stdinChallengeMatches'] = True
        with zipfile.ZipFile(apk) as archive:
            config = json.loads(archive.read('assets/foldgpt-runas-broker-config.json'))
        require(config['schema'] == 'foldgpt.runas-broker-config.v2' and config['base'] == str(BASE), 'Wrong installed config')
        native = Path(os.readlink('/proc/self/exe')).parent
        require(sys.executable == str(native / 'libfoldgpt_python_cli.so') and str(native).startswith('/data/app/'),
                'Wrong installed interpreter')
        require(BASE.resolve(strict=True) == BASE and stat.S_IMODE(BASE.stat().st_mode) == 0o700
                and BASE.stat().st_uid == expected_uid, 'Private runtime base differs')
        # The previous identity action never creates these. Existing paths
        # represent a consumed/unknown trial and are not cleaned or retried.
        WORKSPACE.mkdir(mode=0o700, exist_ok=False)
        BROKER.mkdir(mode=0o700, exist_ok=False)
        for relative in ('private', '.git', 'directory'):
            (WORKSPACE / relative).mkdir(mode=0o700)
        for relative, value in {'input': b'pin-memory-ok\n', 'private/secret': b'probe-private-unchanged\n',
                                'directory/marker': b'marker\n'}.items():
            descriptor = os.open(WORKSPACE / relative, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
            try:
                require(os.write(descriptor, value) == len(value), 'Fixture write incomplete')
            finally:
                os.close(descriptor)
        from tools.executor.private_exec_broker import PrivateSessionOwner
        from tools.executor.exec_server import BackendCall, encode_message
        factory = importlib.import_module('tools.executor.bionic-supervisor.factory').factory
        proof = importlib.import_module('tools.executor.bionic-supervisor.qualification')
        limits = {'wall_ms': 3000, 'cpu_seconds': 1, 'uid_task_budget': 2, 'data_bytes': 16777216,
                  'file_bytes': 1048576, 'output_bytes': 8192, 'descriptors': 32}
        options = {'helper': str(native / 'libfoldgpt_native_files.so'),
                   'handleHelper': str(native / 'libfoldgpt_native_file_handle.so'),
                   'processRunner': str(native / 'libfoldgpt_bionic_supervisor.so'),
                   'workspace': str(WORKSPACE), 'executables': {PROCESS: str(native / 'libfoldgpt_qualification_worker.so')},
                   'limits': limits, 'parentEnvironment': {}, 'runtime': [
                       {'path': str(native / 'libfoldgpt_qualification_worker.so'), 'execute': True}] + [
                       {'path': path, 'execute': execute} for path, execute in (
                           ('/system/lib64', True), ('/system/bin/linker64', True), ('/apex/com.android.runtime', True),
                           ('/linkerconfig/ld.config.txt', False), ('/dev/__properties__', False),
                           ('/apex/com.android.tzdata/etc/tz/tzdata', False))]}
        result['options'] = options
        owner = PrivateSessionOwner(str(BROKER))
        owner.begin_process_session(str(WORKSPACE))
        signal.alarm(0)
        entered = True
        backend = factory(options)
        events = []

        async def notify(method, params):
            events.append({'method': method, 'params': params})

        async def workload():
            nonlocal record
            request = proof.process_request(WORKSPACE)
            result['request'] = request
            result['processStartAttempted'] = True
            await backend.handle(BackendCall(SESSION, 1, 'process/start', encode_message(request)), notify)
            record = backend.processes.processes[(SESSION, PROCESS)]
            await asyncio.wait_for(asyncio.shield(record.finished), 15)
            await asyncio.wait_for(asyncio.shield(record.notifier), 2)
            read = await backend.handle(BackendCall(SESSION, 2, 'process/read', encode_message({'processId': PROCESS})), notify)
            streams = {name: b''.join(base64.b64decode(row['chunk'], validate=True) for row in read['chunks']
                                    if row['stream'] == name) for name in ('stdout', 'stderr')}
            result.update({'stdout': streams['stdout'].decode('ascii'), 'stderr': streams['stderr'].decode('ascii'),
                           'read': read, 'nativeResult': record.native_result, 'supervisorPid': record.process.pid,
                           'supervisorReturncode': record.process.returncode, 'processClosed': record.closed})
            result['nativeWorkerStarted'] = record.native_result is not None and record.native_result.get('started') is True
            result['proofs'] = proof.evidence(streams['stdout'], streams['stderr'], record)
            require((WORKSPACE / 'private/secret').read_bytes() == b'probe-private-unchanged\n'
                    and not (WORKSPACE / '.git/config').exists(), 'Fixed protected fixture changed')
            result['passed'] = True

        operation = asyncio.create_task(workload())
        cancellation = asyncio.create_task(cancelled.wait())
        await asyncio.wait((operation, cancellation), return_when=asyncio.FIRST_COMPLETED)
        if cancellation.done() and not operation.done():
            operation.cancel()
        await operation
        result['notifications'] = events
    except BaseException as error:
        result['passed'] = False
        result['error'] = type(error).__name__ + ': ' + str(error)
        if backend is not None:
            record = record or backend.processes.processes.get((SESSION, PROCESS))
            if record is None and backend.processes.failed:
                record = backend.processes.failed[-1]
            if record is not None:
                result.update({'nativeResult': record.native_result,
                               'nativeWorkerStarted': record.native_result is not None and record.native_result.get('started') is True,
                               'setupDiagnostic': record.setup_diagnostic.decode('utf-8', 'replace'),
                               'processClosed': record.closed,
                               'supervisorPid': record.process.pid if record.process else None,
                               'supervisorReturncode': record.process.returncode if record.process else None})
    finally:
        loop.remove_reader(3)
        for task in (operation, cancellation):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (operation, cancellation) if task is not None), return_exceptions=True)
        clean = not entered
        try:
            if backend is not None:
                await backend.close(SESSION)
                clean = not backend.processes.quarantined
            if clean and owner is not None:
                if owner.process_identity is not None:
                    owner.finish_process_session()
                owner.close()
        except BaseException as error:
            clean = False
            result['cleanupError'] = type(error).__name__ + ': ' + str(error)
        result['cleanupComplete'] = clean
        result['quarantined'] = not clean
        result['passed'] = result['passed'] and clean
        emit(1, result)
        emit(2, {'schema': 'foldgpt.runas.broker-report.v2', 'nonce': nonce, 'pid': os.getpid(),
                 'reportFd': 2, 'stdoutFlushed': True, 'passed': result['passed'], 'cleanupComplete': clean})
        if not clean:
            # Keep the actual owner/backend alive, never erase the persistent
            # marker or infer cleanup from a timeout or a disconnected Activity.
            if owner is not None:
                owner.quarantined = True
                owner.retained_backend = backend
            await asyncio.Event().wait()
    return 0 if result['passed'] else 70


def main(arguments):
    if len(arguments) != 4:
        raise ValueError('Fixed installed argument count differs')
    apk, uid, parent, nonce = arguments
    os._exit(asyncio.run(run(apk, int(uid), int(parent), nonce)))
