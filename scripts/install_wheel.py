#!/usr/bin/env python3
"""Install (or uninstall) the built wheel for the current user, or into a venv if one is given.

Usage::

    python3 scripts/install_wheel.py dist/hp_scanner-*.whl          # per-user (pip --user)
    python3 scripts/install_wheel.py --venv ~/envs/scan dist/*.whl  # that venv (created if missing)
    python3 scripts/install_wheel.py --uninstall                    # remove from the same target
    python3 scripts/install_wheel.py --update-path dist/*.whl       # also add hpscan to PATH

``--update-path`` (``make install UPDATE_PATH=1``) adds the user scripts folder to PATH in your
shell startup file (zsh ``~/.zshrc``, bash ``~/.bash_profile``/``~/.bashrc``, fish ``conf.d``);
with ``--uninstall`` it removes that entry again. Without it, on-screen instructions are printed.

Target selection: ``--venv PATH`` > an active virtualenv (``$VIRTUAL_ENV``, or this interpreter
is itself a venv) > the per-user site of this interpreter. For per-user installs on interpreters
marked ``EXTERNALLY-MANAGED`` (PEP 668, e.g. Homebrew Python) ``--break-system-packages`` is
added; combined with ``--user`` it only writes to the user site (``~/Library/Python/X.Y`` on
macOS), never to the system's site-packages.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import sysconfig
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import shell_path

PACKAGE = "hp-scanner"
SCRIPT = "hpscan"
DEV_VENV = Path(__file__).resolve().parent.parent / ".venv"  # the project's editable dev env
MIN_PYTHON = (3, 10)  # keep in step with requires-python in pyproject.toml


def check_python(version: tuple[int, ...] = sys.version_info[:2]) -> str | None:
    """Error message if this interpreter is too old to install the package, else ``None``."""
    if tuple(version[:2]) >= MIN_PYTHON:
        return None
    need = ".".join(map(str, MIN_PYTHON))
    have = ".".join(map(str, version[:2]))
    return (
        f"{PACKAGE} needs Python >= {need}, but {sys.executable} is {have}. "
        f"Pick a newer one, e.g.: make install PYTHON=python3.13"
    )


@dataclass(frozen=True)
class Target:
    """Install target: ``python`` runs pip, ``user`` adds ``--user``, ``scripts`` holds hpscan."""

    description: str
    python: Path
    scripts: Path
    user: bool = False
    externally_managed: bool = False

    @property
    def pip_flags(self) -> list[str]:
        flags = ["--user"] if self.user else []
        if self.user and self.externally_managed:
            flags.append("--break-system-packages")
        return flags


def _is_externally_managed() -> bool:
    return (Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED").exists()


def _venv_python(venv: Path) -> Path:
    bindir = "Scripts" if os.name == "nt" else "bin"
    return venv / bindir / ("python.exe" if os.name == "nt" else "python")


def _user_scripts_dir() -> Path:
    return Path(sysconfig.get_path("scripts", sysconfig.get_preferred_scheme("user")))


def _same_path(a: Path, b: Path) -> bool:
    return a.expanduser().resolve() == b.expanduser().resolve()


def _active_venv(env: Mapping[str, str]) -> Path | None:
    """The activated venv (``$VIRTUAL_ENV``), or this interpreter's venv, if any."""
    if env.get("VIRTUAL_ENV"):
        return Path(env["VIRTUAL_ENV"])
    if sys.prefix != sys.base_prefix:
        return Path(sys.prefix)
    return None


def _base_python() -> Path:
    """The interpreter behind this one if it's a venv, so ``--user`` goes to the real user site."""
    if sys.prefix != sys.base_prefix:
        return Path(getattr(sys, "_base_executable", "") or sys.executable)
    return Path(sys.executable)


def choose_target(
    venv: Path | None, env: Mapping[str, str] | None = None, dev_venv: Path = DEV_VENV
) -> Target:
    """Resolve the install target: ``--venv`` > an active venv > the user site.

    The project's own dev venv (``.venv``) only counts when named explicitly with ``--venv``:
    having it activated for development must not replace its editable install with the wheel.
    """
    env = os.environ if env is None else env
    if venv is not None:
        venv = venv.expanduser().resolve()
        return Target(f"venv {venv}", _venv_python(venv), _venv_python(venv).parent)
    active = _active_venv(env)
    if active is not None and not _same_path(active, dev_venv):
        return Target(f"active venv {active}", _venv_python(active), _venv_python(active).parent)
    python = _base_python()
    note = " (ignoring the active dev .venv; INSTALL_VENV=.venv to use it)" if active else ""
    return Target(
        f"user site of {python}{note}",
        python,
        _user_scripts_dir(),
        user=True,
        externally_managed=_is_externally_managed(),
    )


def ensure_venv(target: Target, venv: Path | None) -> None:
    if venv is not None and not target.python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv.expanduser())], check=True)


def install_commands(target: Target, wheel: Path) -> list[list[str]]:
    """Reinstall the wheel itself (even at the same version), then ensure its deps are present."""
    # We print our own PATH guidance, so silence pip's generic "not on PATH" warning.
    pip = [
        str(target.python),
        "-m",
        "pip",
        "install",
        "--no-warn-script-location",
        *target.pip_flags,
    ]
    return [
        [*pip, "--force-reinstall", "--no-deps", str(wheel)],
        [*pip, "--quiet", str(wheel)],
    ]


def uninstall_command(target: Target) -> list[str]:
    """``pip uninstall`` has no ``--user``; it finds user-site installs itself."""
    flags = [f for f in target.pip_flags if f != "--user"]
    return [str(target.python), "-m", "pip", "uninstall", "-y", *flags, PACKAGE]


def _shell_config(target: Target) -> shell_path.ShellConfig | None:
    return shell_path.shell_config(target.scripts, shell_path.detect_shell(), Path.home())


def report_path(target: Target, update_path: bool, path: str | None = None) -> str | None:
    """After an install: edit the rc file (``update_path``) or explain how to; ``None`` if fine."""
    if not target.user:
        if update_path:
            return "note: --update-path only applies to user installs; activate the venv instead"
        return None
    config = _shell_config(target)
    if update_path and config is not None:
        status = shell_path.add_block(config)
        where = shell_path.display(config.rc_file, Path.home())
        if status == "unchanged":
            return f"PATH: {where} already adds {target.scripts}"
        return (
            f"PATH: {status} {target.scripts} in {where}\n"
            f"  Open a new terminal, or run: {config.reload}"
        )
    if shell_path.on_path(target.scripts, path):
        return None
    if update_path:  # unknown shell
        print("note: can't detect a zsh/bash/fish startup file to edit", file=sys.stderr)
    return shell_path.instructions(target.scripts, config, Path.home(), SCRIPT)


def report_uninstall_path(target: Target, update_path: bool) -> str | None:
    """After an uninstall: remove our PATH block (``update_path``) or mention it's still there."""
    config = _shell_config(target) if target.user else None
    if config is None or not shell_path.has_block(config):
        return None
    where = shell_path.display(config.rc_file, Path.home())
    if update_path:
        shell_path.remove_block(config)
        return f"PATH: removed hp-scanner entry from {where}"
    return (
        f"note: {where} still adds {target.scripts} to PATH (remove: make uninstall UPDATE_PATH=1)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wheel", type=Path, nargs="?", help="Wheel to install")
    parser.add_argument("--venv", type=Path, help="Install into this venv (created if missing)")
    parser.add_argument("--uninstall", action="store_true", help=f"Uninstall {PACKAGE}")
    parser.add_argument(
        "--update-path",
        action="store_true",
        help="Add (or with --uninstall, remove) the scripts folder in your shell startup file",
    )
    args = parser.parse_args(argv)
    too_old = check_python()
    if too_old:
        print(f"error: {too_old}", file=sys.stderr)
        return 1
    if not args.uninstall and (args.wheel is None or not args.wheel.is_file()):
        parser.error(f"wheel not found: {args.wheel}; run 'make wheel' first")

    target = choose_target(args.venv)
    print(
        f"{'Uninstalling from' if args.uninstall else 'Installing into'} {target.description}",
        flush=True,
    )
    try:
        if args.uninstall:
            subprocess.run(uninstall_command(target), check=True)
            _print(report_uninstall_path(target, args.update_path))
            return 0
        ensure_venv(target, args.venv)
        for cmd in install_commands(target, args.wheel):
            subprocess.run(cmd, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Installed: {target.scripts / SCRIPT}")
    try:
        _print(report_path(target, args.update_path))
    except OSError as exc:
        print(f"error: could not update your shell startup file: {exc}", file=sys.stderr)
        return 1
    return 0


def _print(message: str | None) -> None:
    if message:
        print(message)


if __name__ == "__main__":
    sys.exit(main())
