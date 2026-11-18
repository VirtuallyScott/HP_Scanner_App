"""Repair JPEG pages from HP document feeders (ADF).

A feeder doesn't know how long a page is when it starts sending, so HP firmware writes a
placeholder height into the frame header (``SOFn``) and puts the real line count in a ``DNL``
("define number of lines", ``FFDC``) marker after the image data. Pillow ignores ``DNL`` and
fails with ``broken data stream when reading image file``. :func:`fix_dnl_height` copies the
``DNL`` value into the frame header. Same approach as node-hp-scan-to's ``fixSizeWithDNL``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

SOI = 0xD8
EOI = 0xD9
SOS = 0xDA
DNL = 0xDC
# Start-of-frame markers C0-CF, except DHT (C4), JPG (C8) and DAC (CC).
SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
# Markers that have no length field.
STANDALONE = frozenset({0x01, SOI, EOI, *range(0xD0, 0xD8)})


@dataclass(frozen=True)
class JpegLayout:
    """Where the frame header's height lives and what ``DNL`` says (``None`` if absent)."""

    height_offset: int | None
    height: int | None
    dnl_lines: int | None


def is_jpeg(data: bytes) -> bool:
    return data[:2] == b"\xff\xd8"


def _skip_entropy_data(data: bytes, i: int) -> int:
    """Index of the first real marker after entropy-coded scan data starting at ``i``."""
    end = len(data) - 1
    while i < end:
        if data[i] == 0xFF and data[i + 1] != 0x00 and not 0xD0 <= data[i + 1] <= 0xD7:
            return i
        i += 1
    return len(data)


def scan_layout(data: bytes) -> JpegLayout:
    """Walk the marker segments, stopping quietly at anything truncated or unreadable."""
    height_offset = height = dnl = None
    i = 2
    n = len(data)
    while i + 1 < n:
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in STANDALONE:
            if marker == EOI:
                break
            i += 2
            continue
        if i + 3 >= n:
            break
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if marker in SOF_MARKERS and height_offset is None and i + 7 <= n:
            height_offset = i + 5  # FF Cn, length(2), precision(1), height(2), width(2)
            height = int.from_bytes(data[i + 5 : i + 7], "big")
        elif marker == DNL and i + 5 < n:
            dnl = int.from_bytes(data[i + 4 : i + 6], "big")
        i += 2 + length
        if marker == SOS:
            i = _skip_entropy_data(data, i)
    return JpegLayout(height_offset, height, dnl)


def fix_dnl_height(data: bytes) -> bytes:
    """Return ``data`` with the frame height taken from its ``DNL`` marker, if it has one."""
    if not is_jpeg(data):
        return data
    layout = scan_layout(data)
    if layout.dnl_lines is None or layout.height_offset is None or layout.dnl_lines == 0:
        return data
    if layout.height == layout.dnl_lines:
        return data
    log.debug("JPEG height %s -> %s (from DNL marker)", layout.height, layout.dnl_lines)
    start = layout.height_offset
    return data[:start] + layout.dnl_lines.to_bytes(2, "big") + data[start + 2 :]
