"""Put a directory on the user's PATH via their shell startup file (zsh, bash or fish).

The entry is a marked block, so adding is idempotent, a changed directory (e.g. after a Python
upgrade) replaces the old block, and removal deletes only what we wrote::

    # >>> hp-scanner PATH >>>
    export PATH="$HOME/Library/Python/3.15/bin:$PATH"
    # <<< hp-scanner PATH <<<
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

BEGIN = "# >>> hp-scanner PATH >>>"
END = "# <<< hp-scanner PATH <<<"
_BLOCK = re.compile(rf"\n?{re.escape(BEGIN)}\n.*?{re.escape(END)}\n?", re.S)


@dataclass(frozen=True)
class ShellConfig:
    """Which file to edit for ``shell``, the line that adds the directory, and how to reload."""

    shell: str
    rc_file: Path
    line: str
    reload: str

    @property
    def block(self) -> str:
        return f"{BEGIN}\n{self.line}\n{END}\n"


def display(directory: Path, home: Path) -> str:
    """``$HOME/...`` when inside the home directory, so the rc file stays portable."""
    try:
        return f"$HOME/{directory.relative_to(home)}"
    except ValueError:
        return str(directory)


def detect_shell(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return Path(env.get("SHELL", "")).name


def shell_config(
    directory: Path,
    shell: str,
    home: Path,
    env: Mapping[str, str] | None = None,
    platform: str = sys.platform,
) -> ShellConfig | None:
    """Config for zsh/bash/fish, or ``None`` for shells we don't know how to edit."""
    env = os.environ if env is None else env
    shown = display(directory, home)
    export = f'export PATH="{shown}:$PATH"'
    if shell == "zsh":
        rc = Path(env.get("ZDOTDIR") or home) / ".zshrc"
        return ShellConfig("zsh", rc, export, "exec zsh")
    if shell == "bash":
        # macOS Terminal opens login shells (~/.bash_profile); Linux terminals read ~/.bashrc.
        rc = home / (".bash_profile" if platform == "darwin" else ".bashrc")
        return ShellConfig("bash", rc, export, f"source {display(rc, home)}")
    if shell == "fish":
        rc = home / ".config" / "fish" / "conf.d" / "hp-scanner.fish"
        return ShellConfig("fish", rc, f'fish_add_path --path "{shown}"', "exec fish")
    return None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def add_block(config: ShellConfig) -> str:
    """Add or refresh our block. Returns ``"added"``, ``"updated"`` or ``"unchanged"``.

    Writes in place (not via rename) so a symlinked rc file from a dotfiles repo stays a symlink.
    """
    text = _read(config.rc_file)
    match = _BLOCK.search(text)
    if match:
        if match.group(0).strip("\n") == config.block.strip("\n"):
            return "unchanged"
        lead = "\n" if match.group(0).startswith("\n") else ""
        new = text[: match.start()] + lead + config.block + text[match.end() :]
        status = "updated"
    else:
        lead = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
        new, status = text + lead + config.block, "added"
    config.rc_file.parent.mkdir(parents=True, exist_ok=True)
    config.rc_file.write_text(new, encoding="utf-8")
    return status


def has_block(config: ShellConfig) -> bool:
    return bool(_BLOCK.search(_read(config.rc_file)))


def remove_block(config: ShellConfig) -> bool:
    """Delete our block (and the blank line we put before it); returns whether it existed.

    ``add_block`` then ``remove_block`` restores a newline-terminated file byte-for-byte.
    """
    text = _read(config.rc_file)
    match = _BLOCK.search(text)
    if not match:
        return False
    config.rc_file.write_text(text[: match.start()] + text[match.end() :], encoding="utf-8")
    return True


def on_path(directory: Path, path: str | None = None) -> bool:
    path = os.environ.get("PATH", "") if path is None else path
    return str(directory) in path.split(os.pathsep)


def instructions(directory: Path, config: ShellConfig | None, home: Path, script: str) -> str:
    """On-screen steps for putting ``directory`` on PATH by hand (or automatically)."""
    shown = display(directory, home)
    lines = [
        f"{script} was installed to {shown}, which is not on your PATH.",
        "  Add it automatically:  make install UPDATE_PATH=1   (or --update-path)",
    ]
    if config is None:
        lines.append(f"  Or add {directory} to PATH in your shell's startup file.")
    else:
        rc = display(config.rc_file, home)
        lines += [
            f"  Or add it yourself ({config.shell}):",
            f"    echo '{config.line}' >> {rc}",
            f"    {config.reload}",
        ]
    lines.append(f"  Until then, run it as: {shown}/{script}")
    return "\n".join(lines)
