"""User-facing scan choices: output type names and low/medium/high quality presets."""

from __future__ import annotations

from dataclasses import dataclass

OUTPUT_TYPES = ("pdf", "jpg", "png")
"""Names accepted by ``--type`` (``jpeg`` is also accepted as an alias of ``jpg``)."""
DEFAULT_TYPE = "pdf"

_TYPE_TO_FORMAT = {"pdf": "pdf", "png": "png", "jpg": "jpeg", "jpeg": "jpeg"}


@dataclass(frozen=True)
class QualityPreset:
    """A named quality level: scan resolution plus JPEG compression quality."""

    name: str
    resolution: int
    jpeg_quality: int


QUALITY_PRESETS: dict[str, QualityPreset] = {
    p.name: p
    for p in (
        QualityPreset("low", resolution=100, jpeg_quality=50),
        QualityPreset("medium", resolution=200, jpeg_quality=75),
        QualityPreset("high", resolution=300, jpeg_quality=90),
    )
}
DEFAULT_QUALITY = "medium"


def normalize_type(raw: str) -> str:
    """Map a ``--type`` value (``pdf``/``jpg``/``jpeg``/``png``) to the internal format name."""
    key = str(raw).strip().lower().lstrip(".")
    if key not in _TYPE_TO_FORMAT:
        raise ValueError(f"Invalid type {raw!r}; choose one of {', '.join(OUTPUT_TYPES)}")
    return _TYPE_TO_FORMAT[key]


def quality_preset(raw: str) -> QualityPreset:
    key = str(raw).strip().lower()
    if key not in QUALITY_PRESETS:
        raise ValueError(f"Invalid quality {raw!r}; choose one of {', '.join(QUALITY_PRESETS)}")
    return QUALITY_PRESETS[key]


def parse_quality(raw: str) -> QualityPreset | int:
    """``--quality`` for ``hpscan scan``: a preset name or a JPEG quality number 1-100."""
    text = str(raw).strip()
    if text.isdigit():
        value = int(text)
        if not 1 <= value <= 100:
            raise ValueError(f"Invalid quality {raw!r}; use 1-100 or low/medium/high")
        return value
    return quality_preset(text)
