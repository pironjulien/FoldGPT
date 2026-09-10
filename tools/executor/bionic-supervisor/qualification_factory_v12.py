"""APK-selected V12 diagnostic, isolated from both retained earlier fixtures."""
from pathlib import Path

from .qualification_factory import _factory

BASE = Path("/data/local/tmp/foldgpt-bionic-supervisor-qualification-v4")


def factory(options):
    return _factory(options, BASE)
