#!/usr/bin/env python3
"""Bump the semantic version stored in ``VERSION``.

Usage::

    python scripts/bump_version.py {major,minor,patch,none} [--file VERSION] [--dry-run]

Prints the resulting version on stdout. ``none`` validates and prints the current version
without changing it (used to release the version already in the file, e.g. the first 0.0.1).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PARTS = ("major", "minor", "patch", "none")
DEFAULT_FILE = Path(__file__).resolve().parent.parent / "VERSION"
# SemVer 2.0 core: integers without leading zeros (so 0.0.1, never 0.0.01).
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse(text: str) -> tuple[int, int, int]:
    match = SEMVER.match(text.strip())
    if not match:
        raise ValueError(f"Not a MAJOR.MINOR.PATCH semantic version: {text.strip()!r}")
    major, minor, patch = (int(g) for g in match.groups())
    return major, minor, patch


def bump(version: str, part: str) -> str:
    """Return ``version`` with ``part`` incremented (lower parts reset to 0)."""
    major, minor, patch = parse(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if part == "none":
        return f"{major}.{minor}.{patch}"
    raise ValueError(f"Unknown part {part!r}; choose one of {', '.join(PARTS)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("part", choices=PARTS)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    args = parser.parse_args(argv)
    try:
        new = bump(args.file.read_text(encoding="utf-8"), args.part)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not args.dry_run:
        args.file.write_text(new + "\n", encoding="utf-8")
    print(new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
