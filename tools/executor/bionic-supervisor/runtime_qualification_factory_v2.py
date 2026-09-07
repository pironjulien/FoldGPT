"""V2 APK-owned runtime entry; RPC requests cannot choose its deployment base."""
from pathlib import PurePosixPath
from .runtime_qualification_factory import _factory

BASE = PurePosixPath("/data/local/tmp/foldgpt-bionic-runtime-qualification-v2")


def factory(options):
    return _factory(options, BASE)
