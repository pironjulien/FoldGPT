"""Exact operator-selected identities for retained and independent diagnostics.

No default fixture is selected. A new package cannot target a retained native
base merely by supplying a different report directory or version.
"""
from dataclasses import dataclass


LEGACY_PACKAGE = "app.foldgpt.kernelqualification"
LAB_PACKAGE = "app.foldgpt.shizukuprobe"
V11_PACKAGE = "app.foldgpt.kernelqualification.v11"
V2_BASE = "/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2"
V3_BASE = "/data/local/tmp/foldgpt-bionic-supervisor-qualification-v3"
PACKAGES = (LEGACY_PACKAGE, LAB_PACKAGE, V11_PACKAGE)


@dataclass(frozen=True)
class QualificationIdentity:
    package: str
    base: str
    report_version: int | None
    report_directory: str

    @property
    def workspace(self):
        return self.base + "/workspace"

    def report_file(self, name):
        if name not in {"package-info.json", "report.json"}:
            raise ValueError("Unknown fixed qualification report")
        return self.report_directory + "/" + name

    def matches_evidence(self, app, native):
        if type(app) is not dict or type(native) is not dict or native.get("workspace") != self.workspace:
            return False
        if self.package == V11_PACKAGE:
            return (type(app.get("diagnosticVersion")) is int and app["diagnosticVersion"] == 11
                    and app.get("packageName") == self.package and app.get("nativeBase") == self.base
                    and app.get("requestedAction") == self.package + ".KERNEL_RUN_FIXED_V11")
        return True


def resolve_identity(package, base, report_version):
    if package == V11_PACKAGE:
        if base != V3_BASE or type(report_version) is not int or report_version != 11:
            raise ValueError("V11 requires its independent v3 base and report version 11")
        directory = "files/kernel-v11"
    elif package == LAB_PACKAGE:
        if base != V2_BASE or type(report_version) is not int or report_version not in (2, 3, 4, 5, 6):
            raise ValueError("Retained laboratory reports require the v2 base and version 2 through 6")
        directory = "files/kernel-v" + str(report_version)
    elif package == LEGACY_PACKAGE:
        if base != V2_BASE or report_version is not None:
            raise ValueError("Historical standalone reports require the v2 base and no report version")
        directory = "files"
    else:
        raise ValueError("Unknown fixed qualification application identity")
    return QualificationIdentity(package, base, report_version, directory)
