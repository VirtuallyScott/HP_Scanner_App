#!/usr/bin/env python3
"""Write the GitHub Release body: install instructions for this version, then the changelog.

Usage::

    python scripts/release_notes.py 0.0.1 --repo owner/name [--changelog generated.md] > notes.md

The changelog file (GitHub's auto-generated "What's Changed") is appended when given.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PACKAGE = "hp_scanner"
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def wheel_name(version: str) -> str:
    return f"{PACKAGE}-{version}-py3-none-any.whl"


def install_section(version: str, repo: str) -> str:
    """Markdown with copy-paste install commands pinned to ``version``."""
    if not _VERSION.match(version):
        raise ValueError(f"version must be MAJOR.MINOR.PATCH, got {version!r}")
    if not _REPO.match(repo):
        raise ValueError(f"repo must be owner/name, got {repo!r}")
    wheel = wheel_name(version)
    url = f"https://github.com/{repo}/releases/download/v{version}/{wheel}"
    return f"""## Install

Requires Python 3.10+. Installs the `hpscan` command for your user, pulling in Pillow and requests.

```bash
python3 -m pip install --user {url}
```

On Homebrew Python (macOS), which is "externally managed", add `--break-system-packages`
(with `--user` it only writes to your own user site):

```bash
python3 -m pip install --user --break-system-packages {url}
```

Into a virtualenv instead:

```bash
python3 -m venv ~/venvs/hpscan && ~/venvs/hpscan/bin/pip install {url}
```

Or download first with the GitHub CLI:

```bash
gh release download v{version} -R {repo} -p '*.whl'
python3 -m pip install --user {wheel}
```

Then check it and point it at your scanner:

```bash
hpscan --version
hpscan config --host <scanner-ip-or-name.local>
hpscan            # prompts for type / quality / prefix, then scans
```

If `hpscan` isn't found, the user scripts folder isn't on your PATH: on macOS that's
`~/Library/Python/3.X/bin`, on Linux `~/.local/bin`.

Upgrade by running the install command for a newer release; uninstall with
`python3 -m pip uninstall hp-scanner`.
"""


def build_notes(version: str, repo: str, changelog: str = "") -> str:
    notes = install_section(version, repo)
    if changelog.strip():
        notes += "\n" + changelog.strip() + "\n"
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version")
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--changelog", type=Path, help="Markdown to append (generated notes)")
    args = parser.parse_args(argv)
    try:
        changelog = args.changelog.read_text(encoding="utf-8") if args.changelog else ""
        sys.stdout.write(build_notes(args.version, args.repo, changelog))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
