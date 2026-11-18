import io

import pytest
from PIL import Image

from hp_scanner.jpeg import fix_dnl_height, is_jpeg, scan_layout


def _jpeg(width=64, height=48, mode="L"):
    buf = io.BytesIO()
    Image.new(mode, (width, height), 128).save(buf, "JPEG")
    return buf.getvalue()


def adf_jpeg(real_height=48, placeholder=0xFFFF, dnl=True, width=64, mode="L"):
    """Mimic an HP feeder page: placeholder SOF height, real line count in a DNL marker."""
    data = bytearray(_jpeg(width, real_height, mode))
    sof = data.index(b"\xff\xc0")
    data[sof + 5 : sof + 7] = placeholder.to_bytes(2, "big")
    eoi = data.rindex(b"\xff\xd9")
    tail = b"\xff\xdc\x00\x04" + real_height.to_bytes(2, "big") if dnl else b""
    return bytes(data[:eoi]) + tail + b"\xff\xd9"


def _decode(data):
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def test_feeder_page_is_unreadable_without_fix():
    with pytest.raises(OSError, match="broken data stream"):
        _decode(adf_jpeg())


@pytest.mark.parametrize("placeholder", [0xFFFF, 0, 4200])
@pytest.mark.parametrize("mode", ["L", "RGB"])
def test_fix_dnl_height_makes_page_decodable(placeholder, mode):
    fixed = fix_dnl_height(adf_jpeg(real_height=48, placeholder=placeholder, mode=mode))
    assert _decode(fixed).size == (64, 48)


def test_scan_layout_reads_sof_and_dnl():
    layout = scan_layout(adf_jpeg(real_height=37))
    assert (layout.height, layout.dnl_lines) == (0xFFFF, 37)
    assert scan_layout(_jpeg()).dnl_lines is None


def test_normal_jpeg_and_non_jpeg_unchanged():
    normal = _jpeg()
    assert fix_dnl_height(normal) is normal
    pdf = b"%PDF-1.4 ..."
    assert fix_dnl_height(pdf) is pdf
    no_dnl = adf_jpeg(dnl=False)
    assert fix_dnl_height(no_dnl) == no_dnl  # nothing to fix it with


def test_fix_returns_new_bytes_without_mutating_input():
    original = adf_jpeg()
    snapshot = bytes(original)
    fixed = fix_dnl_height(original)
    assert original == snapshot and fixed != original and len(fixed) == len(original)


@pytest.mark.parametrize(
    "junk",
    [b"\xff\xd8", b"\xff\xd8\xff", b"\xff\xd8\xff\xc0\x00", b"\xff\xd8\x00\x00", b""],
)
def test_truncated_or_odd_data_does_not_crash(junk):
    assert fix_dnl_height(junk) == junk
    assert is_jpeg(junk) is junk.startswith(b"\xff\xd8")


def test_fill_bytes_and_restart_markers_are_skipped():
    data = bytearray(adf_jpeg(real_height=20))
    sof = data.index(b"\xff\xc0")
    data[sof:sof] = b"\xff"  # an extra fill byte before SOF0
    assert _decode(fix_dnl_height(bytes(data))).size == (64, 20)
