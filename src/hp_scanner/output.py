"""Convert raw scanner pages (JPEG) into PNG or PDF files."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from .jpeg import fix_dnl_height, is_jpeg


def _open(page: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(page))
    img.load()
    return img


def _numbered(base: Path, index: int, total: int) -> Path:
    if total == 1:
        return base
    return base.with_name(f"{base.stem}-{index}{base.suffix}")


def save_png(pages: list[bytes], output: Path, dpi: int = 300) -> list[Path]:
    """Write each page as a PNG. Multiple pages get ``-1``, ``-2`` … suffixes."""
    output = Path(output)
    written: list[Path] = []
    for i, page in enumerate(pages, start=1):
        path = _numbered(output, i, len(pages))
        img = _open(page)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(path, format="PNG", dpi=(dpi, dpi))
        written.append(path)
    return written


def save_jpeg(pages: list[bytes], output: Path) -> list[Path]:
    """Write the scanner's raw JPEG bytes untouched."""
    output = Path(output)
    written: list[Path] = []
    for i, page in enumerate(pages, start=1):
        path = _numbered(output, i, len(pages))
        path.write_bytes(page)
        written.append(path)
    return written


def is_pdf(page: bytes) -> bool:
    return page.startswith(b"%PDF")


def save_pdf(pages: list[bytes], output: Path, dpi: int = 300) -> list[Path]:
    """Combine all pages into one multi-page PDF sized by ``dpi``.

    Pages that are already PDFs (device-native ``Format=Pdf``) are written as-is: a single
    page goes straight to ``output``; several get ``-1``, ``-2`` … suffixes since merging
    PDFs would need an extra dependency.
    """
    if not pages:
        raise ValueError("No pages to write")
    output = Path(output)
    if all(is_pdf(p) for p in pages):
        written = []
        for i, page in enumerate(pages, start=1):
            path = _numbered(output, i, len(pages))
            path.write_bytes(page)
            written.append(path)
        return written
    images = [_open(p) for p in pages]
    images = [img if img.mode in ("RGB", "L") else img.convert("RGB") for img in images]
    first, rest = images[0], images[1:]
    first.save(
        output,
        format="PDF",
        save_all=bool(rest),
        append_images=rest,
        resolution=float(dpi),
    )
    return [output]


SAVERS = {"png": save_png, "pdf": save_pdf, "jpeg": save_jpeg}


class PageConversionError(OSError):
    """Pages couldn't be converted; the untouched scanner data was saved to ``raw_paths``."""

    def __init__(self, message: str, raw_paths: list[Path]) -> None:
        super().__init__(message)
        self.raw_paths = raw_paths


def _raw_suffix(page: bytes) -> str:
    if is_pdf(page):
        return ".pdf"
    return ".jpg" if is_jpeg(page) else ".bin"


def save_raw_pages(pages: list[bytes], output: Path) -> list[Path]:
    """Write the scanner's bytes as-is to ``<stem>-raw-<n>.<ext>`` next to ``output``."""
    output = Path(output)
    written = []
    for i, page in enumerate(pages, start=1):
        path = output.with_name(f"{output.stem}-raw-{i}{_raw_suffix(page)}")
        path.write_bytes(page)
        written.append(path)
    return written


def save_pages(pages: list[bytes], output: Path, fmt: str, dpi: int = 300) -> list[Path]:
    """Dispatch to the saver for ``fmt`` (``png``, ``pdf`` or ``jpeg``).

    JPEG pages are first repaired with :func:`fix_dnl_height` (document-feeder pages). If
    conversion still fails, the raw pages are saved so the scan isn't lost, and
    :class:`PageConversionError` says where they are.
    """
    fmt = fmt.lower()
    if fmt == "jpg":
        fmt = "jpeg"
    if fmt not in SAVERS:
        raise ValueError(f"Unsupported output format {fmt!r}; choose one of {sorted(SAVERS)}")
    pages = [fix_dnl_height(p) for p in pages]
    try:
        if fmt == "jpeg":
            return save_jpeg(pages, output)
        return SAVERS[fmt](pages, output, dpi=dpi)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raw = save_raw_pages(pages, output)
        names = ", ".join(str(p) for p in raw)
        raise PageConversionError(
            f"could not convert scanned pages to {fmt} ({exc}); raw pages saved: {names}", raw
        ) from exc
