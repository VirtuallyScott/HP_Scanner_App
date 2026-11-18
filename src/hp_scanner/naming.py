"""Automatic output paths.

``<root>/YYYY/MM/[<prefix>-]<kind>-<n>-YYYY-MM-DD-<TZ>-HH-MM-SS.<ext>``
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

EXTENSIONS = {"pdf": ".pdf", "png": ".png", "jpeg": ".jpg"}
# Matches with or without a user prefix, e.g. "invoices-document-3-2026-11-18-...".
_SCAN_NUMBER = re.compile(r"(?:^|-)(?:document|image)-(\d+)-\d{4}-\d{2}-\d{2}-")
_PREFIX = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_. -]*$")
MAX_PREFIX_LENGTH = 64


def kind_for(fmt: str) -> str:
    """``document`` for PDFs, ``image`` for PNG/JPEG."""
    return "document" if fmt == "pdf" else "image"


def normalize_prefix(raw: str | None) -> str | None:
    """Validate a file-name prefix; blank means no prefix.

    Allowed: letters, digits, ``_``, ``-``, ``.`` and spaces, not starting with ``-``/``.``/space,
    and no path separators, so the prefix can't escape the destination folder.
    """
    if raw is None:
        return None
    text = str(raw).strip().rstrip("-")
    if not text:
        return None
    if len(text) > MAX_PREFIX_LENGTH or not _PREFIX.match(text):
        raise ValueError(
            f"Invalid prefix {raw!r}: use up to {MAX_PREFIX_LENGTH} letters, digits, "
            "'_', '-', '.' or spaces, starting with a letter, digit or '_'"
        )
    return text


def _tz_label(now: datetime) -> str:
    label = re.sub(r"[^A-Za-z0-9+-]", "", now.strftime("%Z"))
    return label or now.strftime("%z") or "UTC"


def next_scan_number(directory: Path) -> int:
    """One more than the highest scan number already in ``directory`` (1 if none)."""
    if not directory.is_dir():
        return 1
    numbers = [int(m.group(1)) for p in directory.iterdir() if (m := _SCAN_NUMBER.search(p.name))]
    return max(numbers, default=0) + 1


def auto_output_path(
    root: Path, fmt: str, now: datetime | None = None, prefix: str | None = None
) -> Path:
    """Build the next output path under ``root`` and create ``root/YYYY/MM``.

    ``n`` counts scans of both kinds (prefixed or not) within the month directory.
    """
    prefix = normalize_prefix(prefix)
    if fmt not in EXTENSIONS:
        raise ValueError(f"Unsupported output format {fmt!r}; choose one of {sorted(EXTENSIONS)}")
    now = now or datetime.now()
    if now.tzinfo is None:
        now = now.astimezone()
    directory = Path(root) / f"{now:%Y}" / f"{now:%m}"
    directory.mkdir(parents=True, exist_ok=True)
    n = next_scan_number(directory)
    stamp = f"{now:%Y-%m-%d}-{_tz_label(now)}-{now:%H-%M-%S}"
    lead = f"{prefix}-" if prefix else ""
    return directory / f"{lead}{kind_for(fmt)}-{n}-{stamp}{EXTENSIONS[fmt]}"
