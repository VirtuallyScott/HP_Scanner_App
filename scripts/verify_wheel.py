#!/usr/bin/env python3
"""Check a built wheel's metadata against ``VERSION`` and ``requirements.txt``.

Usage::

    python scripts/verify_wheel.py dist/hp_scanner-*.whl

Fails (exit 1) if the wheel's ``Version`` differs from ``VERSION`` or if any requirement in
``requirements.txt`` is missing from the wheel's unconditional ``Requires-Dist`` entries.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read_requirements(path: Path) -> set[str]:
    """Requirement lines from a requirements file, ignoring comments, blanks and options."""
    reqs = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            reqs.add(_canonical(line))
    return reqs


def _canonical(req: str) -> str:
    """Normalize ``Pillow >= 10.0`` / ``pillow>=10.0`` to one comparable form."""
    return "".join(req.split()).lower().replace("_", "-")


def wheel_metadata(wheel: Path) -> tuple[str, set[str]]:
    """Return (version, unconditional requirements) from a wheel's METADATA."""
    with zipfile.ZipFile(wheel) as zf:
        name = next((n for n in zf.namelist() if n.endswith(".dist-info/METADATA")), None)
        if name is None:
            raise ValueError(f"{wheel} has no .dist-info/METADATA")
        meta = Parser().parsestr(zf.read(name).decode("utf-8"))
    requires = {
        _canonical(r)
        for r in meta.get_all("Requires-Dist") or []
        if ";" not in r  # skip extras
    }
    return meta["Version"], requires


def verify(wheel: Path, version_file: Path, requirements: Path) -> list[str]:
    """Return a list of problems (empty when the wheel matches)."""
    problems = []
    version, requires = wheel_metadata(wheel)
    expected = version_file.read_text(encoding="utf-8").strip()
    if version != expected:
        problems.append(f"wheel version {version} != VERSION {expected}")
    missing = read_requirements(requirements) - requires
    problems.extend(
        f"requirement {req!r} missing from wheel Requires-Dist" for req in sorted(missing)
    )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--version-file", type=Path, default=ROOT / "VERSION")
    parser.add_argument("--requirements", type=Path, default=ROOT / "requirements.txt")
    args = parser.parse_args(argv)
    try:
        problems = verify(args.wheel, args.version_file, args.requirements)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"{args.wheel.name}: version and requirements OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
