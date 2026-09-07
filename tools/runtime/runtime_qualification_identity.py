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
    package: str = PACKAGE
    base: str = BASE
    report_version: int = VERSION
    report_directory: str = 'files/runtime-v1'

    @property
    def workspace(self):
        return self.base + '/workspace'

    @property
    def retained_packages(self):
        return ('app.foldgpt', 'app.foldgpt.shizukuprobe',
                'app.foldgpt.kernelqualification.v11', 'app.foldgpt.kernelqualification.v12')

    def report_file(self, name):
        if name not in {'package-info.json', 'report.json'}:
            raise ValueError('Unknown fixed runtime qualification report')
        return self.report_directory + '/' + name


def resolve_runtime_identity(package, base, version):
    if package != PACKAGE or base != BASE or type(version) is not int or version != VERSION:
        raise ValueError('Runtime qualification requires its exact independent package/base/version')
    return RuntimeQualificationIdentity()
