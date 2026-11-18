import pytest
from conftest import make_jpeg
from PIL import Image
from test_jpeg import adf_jpeg

from hp_scanner.output import PageConversionError, save_jpeg, save_pages, save_pdf, save_png


def test_save_png_single_page(tmp_path, jpeg_page):
    out = tmp_path / "scan.png"
    written = save_png([jpeg_page], out, dpi=200)

    assert written == [out]
    with Image.open(out) as img:
        assert img.format == "PNG"
        assert img.mode == "RGB"
        assert img.size == (40, 60)
        assert tuple(round(v) for v in img.info["dpi"]) == (200, 200)
        # red fill survives JPEG -> PNG round trip
        r, g, b = img.getpixel((20, 30))
        assert r > 150 and g < 80 and b < 80


def test_save_png_multiple_pages_are_numbered(tmp_path):
    pages = [make_jpeg((255, 0, 0)), make_jpeg((0, 255, 0)), make_jpeg((0, 0, 255))]
    written = save_png(pages, tmp_path / "doc.png")

    assert [p.name for p in written] == ["doc-1.png", "doc-2.png", "doc-3.png"]
    assert all(p.exists() for p in written)


def test_save_jpeg_writes_raw_bytes(tmp_path, jpeg_page):
    written = save_jpeg([jpeg_page, jpeg_page], tmp_path / "raw.jpg")
    assert [p.name for p in written] == ["raw-1.jpg", "raw-2.jpg"]
    assert written[0].read_bytes() == jpeg_page


def test_save_pdf_multi_page(tmp_path):
    pages = [make_jpeg(), make_jpeg((0, 0, 0))]
    out = tmp_path / "doc.pdf"
    written = save_pdf(pages, out, dpi=300)

    assert written == [out]
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert data.count(b"/Type /Page\n") == 2 or data.count(b"/Type /Page ") == 2


def test_save_pdf_single_page(tmp_path, jpeg_page):
    out = tmp_path / "one.pdf"
    save_pdf([jpeg_page], out)
    assert out.read_bytes().startswith(b"%PDF")


def test_save_pdf_requires_pages(tmp_path):
    with pytest.raises(ValueError, match="No pages"):
        save_pdf([], tmp_path / "empty.pdf")


@pytest.mark.parametrize(
    ("fmt", "expected_suffix"),
    [("png", ".png"), ("PDF", ".pdf"), ("jpeg", ".jpg"), ("jpg", ".jpg")],
)
def test_save_pages_dispatch(tmp_path, jpeg_page, fmt, expected_suffix):
    out = tmp_path / f"scan{expected_suffix}"
    written = save_pages([jpeg_page], out, fmt)
    assert written == [out]
    assert out.stat().st_size > 0


def test_save_pages_rejects_unknown_format(tmp_path, jpeg_page):
    with pytest.raises(ValueError, match="Unsupported output format"):
        save_pages([jpeg_page], tmp_path / "x.tiff", "tiff")


def test_save_pdf_passes_native_pdf_through(tmp_path):
    pdf = b"%PDF-1.4\n%native\n%%EOF"
    out = tmp_path / "doc.pdf"
    assert save_pdf([pdf], out) == [out]
    assert out.read_bytes() == pdf

    written = save_pdf([pdf, pdf + b"2"], tmp_path / "multi.pdf")
    assert [p.name for p in written] == ["multi-1.pdf", "multi-2.pdf"]


def test_save_pages_repairs_feeder_jpegs(tmp_path):
    pages = [adf_jpeg(real_height=48), adf_jpeg(real_height=30)]
    [pdf] = save_pages(pages, tmp_path / "stack.pdf", "pdf", dpi=200)
    assert b"/Count 2" in pdf.read_bytes()
    pngs = save_pages(pages, tmp_path / "p.png", "png")
    assert [Image.open(p).size for p in pngs] == [(64, 48), (64, 30)]
    jpgs = save_pages(pages, tmp_path / "j.jpeg", "jpeg")
    assert Image.open(jpgs[0]).size == (64, 48)  # raw JPEG output is repaired too


def test_unconvertible_pages_are_kept_raw(tmp_path):
    pages = [b"\xff\xd8\xff\xe0 not really a jpeg", b"%PDF-1.4 fake"]
    with pytest.raises(PageConversionError) as exc:
        save_pages(pages, tmp_path / "doc.pdf", "pdf")
    raw = exc.value.raw_paths
    assert [p.name for p in raw] == ["doc-raw-1.jpg", "doc-raw-2.pdf"]
    assert raw[0].read_bytes() == pages[0]
    assert "raw pages saved" in str(exc.value)
    assert isinstance(exc.value, OSError)  # CLI reports it as "error: ..." and exits 1
