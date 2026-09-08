#!/usr/bin/env python3
"""Command-line statistics calculator."""

import argparse
import math
import sys


def calculate(values):
    """Return min, max, sum, and average for a non-empty iterable."""
    numbers = list(values)
    if not numbers:
        raise ValueError("at least one number is required")
    if any(not isinstance(number, (int, float)) for number in numbers):
        raise ValueError("all values must be numbers")
    return {
        "count": len(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "sum": math.fsum(numbers),
        "average": math.fsum(numbers) / len(numbers),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Calculate basic statistics.")
    parser.add_argument("numbers", nargs="*", help="numbers to calculate")
    args = parser.parse_args(argv)
    try:
        values = [float(value) for value in args.numbers]
        result = calculate(values)
    except (ValueError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for name in ("count", "min", "max", "sum", "average"):
        print(f"{name}: {result[name]:g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
