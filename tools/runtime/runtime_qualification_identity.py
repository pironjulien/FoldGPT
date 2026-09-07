"""Independent identity and fixture for the fixed native Bash/Python project."""
from dataclasses import dataclass

PACKAGE = 'app.foldgpt.runtimequalification.v1'
BASE = '/data/local/tmp/foldgpt-bionic-runtime-qualification-v1'
VERSION = 1
SENTINEL = b'probe-private-unchanged\n'
DIRECTORIES = ('broker', 'workspace', 'workspace/private', 'workspace/directory', 'workspace/.git')
FILES = {'workspace/private/secret': SENTINEL}
ENTRIES = {'workspace': {'.git', 'directory', 'private'}, 'workspace/private': {'secret'},
           'workspace/directory': set(), 'workspace/.git': set()}


@dataclass(frozen=True)
class RuntimeQualificationIdentity:
    package: str
    base: str
    report_version: int
    report_directory: str
    backend_factory: str
    run_action: str

    @property
    def workspace(self):
        return self.base + '/workspace'

    @property
    def retained_packages(self):
        common = ('app.foldgpt', 'app.foldgpt.shizukuprobe',
                  'app.foldgpt.kernelqualification.v11', 'app.foldgpt.kernelqualification.v12')
        return common + ((PACKAGE,) if self.report_version == 2 else ())

    def report_file(self, name):
        if name not in {'package-info.json', 'report.json'}:
            raise ValueError('Unknown fixed runtime qualification report')
        return self.report_directory + '/' + name


PROFILES = {
    1: RuntimeQualificationIdentity(PACKAGE, BASE, 1, 'files/runtime-v1',
        'tools.executor.bionic-supervisor.runtime_qualification_factory:factory', '.RUNTIME_RUN_FIXED_V1'),
    2: RuntimeQualificationIdentity('app.foldgpt.runtimequalification.v2',
        '/data/local/tmp/foldgpt-bionic-runtime-qualification-v2', 2, 'files/runtime-v2',
        'tools.executor.bionic-supervisor.runtime_qualification_factory_v2:factory', '.RUNTIME_RUN_FIXED_V2'),
}
PACKAGES = tuple(identity.package for identity in PROFILES.values())
BASES = tuple(identity.base for identity in PROFILES.values())


def runtime_identity(version):
    if type(version) is not int or version not in PROFILES:
        raise ValueError('Only reviewed runtime qualification versions 1 and 2 are admitted')
    return PROFILES[version]


def resolve_runtime_identity(package, base, version):
    identity = runtime_identity(version)
    if package != identity.package or base != identity.base:
        raise ValueError('Runtime qualification requires its exact independent package/base/version')
    return identity
