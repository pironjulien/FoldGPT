"""APK-selected V11 diagnostic; its fixture never shares V10's retained base."""
from pathlib import Path

from .qualification_factory import _factory

BASE = Path("/data/local/tmp/foldgpt-bionic-supervisor-qualification-v3")


def factory(options):
    return _factory(options, BASE)
