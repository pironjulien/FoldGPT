"""Compatibility entry point for the independent V11 APK verifier; PC only."""
from pathlib import Path
import runpy
import sys

if __name__ == "__main__":
    if any(value == "--version" or value.startswith("--version=") for value in sys.argv[1:]):
        raise SystemExit("This historical entry point is fixed to V11; use verify-qualification.py for other versions")
    runpy.run_path(str(Path(__file__).with_name("verify-qualification.py")))["main"](["--version", "11", *sys.argv[1:]])
