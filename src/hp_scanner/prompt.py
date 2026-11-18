"""Interactive prompts for a bare ``hpscan`` run."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TextIO

from .naming import normalize_prefix
from .presets import (
    DEFAULT_QUALITY,
    DEFAULT_TYPE,
    OUTPUT_TYPES,
    QUALITY_PRESETS,
    normalize_type,
    quality_preset,
)

MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class QuickChoices:
    """What a quick scan needs: output type, quality preset name and optional prefix."""

    type: str = DEFAULT_TYPE
    quality: str = DEFAULT_QUALITY
    prefix: str | None = None


def _ask(
    question: str,
    default: str,
    check: Callable[[str], object],
    read: Callable[[str], str],
    out: TextIO,
) -> str:
    """Ask until ``check`` accepts the answer (bounded); blank or EOF means ``default``."""
    for _ in range(MAX_ATTEMPTS):
        try:
            answer = read(question).strip()
        except EOFError:
            out.write("\n")
            return default
        if not answer:
            return default
        try:
            check(answer)
        except ValueError as exc:
            out.write(f"  {exc}\n")
            continue
        return answer
    raise ValueError(f"No valid answer after {MAX_ATTEMPTS} attempts")


def prompt_choices(
    read: Callable[[str], str] | None = None, out: TextIO | None = None
) -> QuickChoices:
    """Prompt for type, quality and prefix; Enter accepts the default shown in brackets.

    ``read`` defaults to :func:`input`; ``out`` (for validation messages) to ``sys.stderr``.
    """
    read = read or input
    out = out or sys.stderr
    fmt = _ask(
        f"Type ({'/'.join(OUTPUT_TYPES)}) [{DEFAULT_TYPE}]: ",
        DEFAULT_TYPE,
        normalize_type,
        read,
        out,
    )
    quality = _ask(
        f"Quality ({'/'.join(QUALITY_PRESETS)}) [{DEFAULT_QUALITY}]: ",
        DEFAULT_QUALITY,
        quality_preset,
        read,
        out,
    )
    prefix = _ask("File name prefix [none]: ", "", normalize_prefix, read, out)
    return QuickChoices(type=fmt.lower(), quality=quality.lower(), prefix=normalize_prefix(prefix))
