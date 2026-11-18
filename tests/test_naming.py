from datetime import datetime, timedelta, timezone

import pytest

from hp_scanner.naming import auto_output_path, kind_for, next_scan_number, normalize_prefix

NOW = datetime(2026, 11, 18, 14, 5, 9, tzinfo=timezone(timedelta(hours=-8), "PST"))


def test_kind_for():
    assert kind_for("pdf") == "document"
    assert kind_for("png") == "image"
    assert kind_for("jpeg") == "image"


@pytest.mark.parametrize(
    ("fmt", "name"),
    [
        ("pdf", "document-1-2026-11-18-PST-14-05-09.pdf"),
        ("png", "image-1-2026-11-18-PST-14-05-09.png"),
        ("jpeg", "image-1-2026-11-18-PST-14-05-09.jpg"),
    ],
)
def test_auto_output_path_layout(tmp_path, fmt, name):
    path = auto_output_path(tmp_path / "root", fmt, now=NOW)
    assert path == tmp_path / "root" / "2026" / "11" / name
    assert path.parent.is_dir()
    assert not path.exists()


def test_scan_number_increments_across_kinds(tmp_path):
    first = auto_output_path(tmp_path, "pdf", now=NOW)
    first.write_bytes(b"x")
    second = auto_output_path(tmp_path, "png", now=NOW)
    assert second.name.startswith("image-2-")
    (second.parent / "image-7-2026-11-18-PST-14-05-09-2.png").write_bytes(b"x")
    assert auto_output_path(tmp_path, "pdf", now=NOW).name.startswith("document-8-")


def test_next_scan_number_ignores_other_files(tmp_path):
    assert next_scan_number(tmp_path / "missing") == 1
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "document-x-foo.pdf").write_text("x")
    assert next_scan_number(tmp_path) == 1


def test_numbering_resets_per_month(tmp_path):
    auto_output_path(tmp_path, "pdf", now=NOW).write_bytes(b"x")
    december = NOW.replace(month=12)
    assert auto_output_path(tmp_path, "pdf", now=december).name.startswith("document-1-")


def test_timezone_label_is_sanitized(tmp_path):
    now = NOW.replace(tzinfo=timezone(timedelta(hours=5, minutes=30), "India Standard Time"))
    assert "-IndiaStandardTime-" in auto_output_path(tmp_path, "pdf", now=now).name


def test_unknown_format_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        auto_output_path(tmp_path, "tiff", now=NOW)


def test_timezone_without_name_uses_offset(tmp_path):
    now = NOW.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    # unnamed fixed-offset zones render %Z as "UTC+05:30" -> sanitized to "UTC+0530"
    assert "-UTC+0530-" in auto_output_path(tmp_path, "pdf", now=now).name


def test_prefix_is_prepended(tmp_path):
    path = auto_output_path(tmp_path, "pdf", now=NOW, prefix="taxes")
    assert path.name == "taxes-document-1-2026-11-18-PST-14-05-09.pdf"


def test_blank_prefix_means_none(tmp_path):
    assert auto_output_path(tmp_path, "png", now=NOW, prefix="  ").name.startswith("image-1-")


def test_scan_number_counts_prefixed_files(tmp_path):
    auto_output_path(tmp_path, "pdf", now=NOW, prefix="a b.c").write_bytes(b"x")
    auto_output_path(tmp_path, "pdf", now=NOW, prefix="image-x").write_bytes(b"x")
    assert auto_output_path(tmp_path, "png", now=NOW).name.startswith("image-3-")


@pytest.mark.parametrize("bad", ["../up", "a/b", "a\\b", ".hidden", "-dash", "x" * 65, "tab\there"])
def test_bad_prefix_rejected(tmp_path, bad):
    with pytest.raises(ValueError, match="Invalid prefix"):
        auto_output_path(tmp_path, "pdf", now=NOW, prefix=bad)


@pytest.mark.parametrize(
    ("raw", "expected"), [("ok_1", "ok_1"), (" sp ace ", "sp ace"), ("x-", "x")]
)
def test_normalize_prefix(raw, expected):
    assert normalize_prefix(raw) == expected
