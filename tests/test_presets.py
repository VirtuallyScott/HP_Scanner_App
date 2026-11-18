import pytest

from hp_scanner.presets import (
    DEFAULT_QUALITY,
    DEFAULT_TYPE,
    QUALITY_PRESETS,
    normalize_type,
    parse_quality,
    quality_preset,
)


def test_defaults():
    assert DEFAULT_TYPE == "pdf"
    assert DEFAULT_QUALITY == "medium"


@pytest.mark.parametrize(
    ("raw", "fmt"),
    [("pdf", "pdf"), ("PNG", "png"), ("jpg", "jpeg"), ("jpeg", "jpeg"), (".jpg", "jpeg")],
)
def test_normalize_type(raw, fmt):
    assert normalize_type(raw) == fmt


def test_normalize_type_rejects_unknown():
    with pytest.raises(ValueError, match="pdf, jpg, png"):
        normalize_type("tiff")


def test_presets_increase_with_level():
    low, medium, high = (QUALITY_PRESETS[k] for k in ("low", "medium", "high"))
    assert low.resolution < medium.resolution < high.resolution
    assert low.jpeg_quality < medium.jpeg_quality < high.jpeg_quality
    # every preset resolution must be one the reference 6700 supports on platen and ADF
    assert {p.resolution for p in QUALITY_PRESETS.values()} <= {75, 100, 200, 300, 600}


def test_quality_preset_lookup():
    assert quality_preset(" High ") is QUALITY_PRESETS["high"]
    with pytest.raises(ValueError, match="low, medium, high"):
        quality_preset("ultra")


@pytest.mark.parametrize(("raw", "expected"), [("1", 1), ("90", 90), ("100", 100)])
def test_parse_quality_numbers(raw, expected):
    assert parse_quality(raw) == expected


def test_parse_quality_presets_and_errors():
    assert parse_quality("low") is QUALITY_PRESETS["low"]
    for bad in ("0", "101", "-5", "best"):
        with pytest.raises(ValueError):
            parse_quality(bad)
