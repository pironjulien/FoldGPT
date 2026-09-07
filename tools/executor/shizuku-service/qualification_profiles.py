"""Reviewed fixed APK identities; never accepts a runtime-selected fixture."""
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class QualificationProfile:
    version: int
    base: str

    @property
    def package(self):
        return "app.foldgpt.kernelqualification.v" + str(self.version)

    @property
    def factory_module(self):
        return "qualification_factory_v" + str(self.version)

    @property
    def inputs(self):
        return HERE / ("qualification-inputs-v" + str(self.version) + ".json")

    @property
    def build_root(self):
        return HERE / "build" if self.version == 11 else HERE / "build" / ("qualification-v" + str(self.version))

    @property
    def stage(self):
        return self.build_root / ("qualification-stage-v" + str(self.version))

    @property
    def apk(self):
        module = HERE / "qualification/build" if self.version == 11 else self.build_root / "modules/qualification"
        return module / "outputs/apk/debug/qualification-debug.apk"


PROFILES = {
    11: QualificationProfile(11, "/data/local/tmp/foldgpt-bionic-supervisor-qualification-v3"),
    12: QualificationProfile(12, "/data/local/tmp/foldgpt-bionic-supervisor-qualification-v4"),
}
BY_PACKAGE = {profile.package: profile for profile in PROFILES.values()}


def for_version(version):
    if type(version) is not int or version not in PROFILES:
        raise ValueError("Only reviewed independent qualification versions are admitted")
    return PROFILES[version]
