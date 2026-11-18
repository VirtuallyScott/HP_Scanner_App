import io
from pathlib import Path

import pytest
from PIL import Image

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def capabilities_xml() -> bytes:
    return (FIXTURES / "capabilities.xml").read_bytes()


@pytest.fixture
def status_idle_xml() -> bytes:
    return (FIXTURES / "status_idle.xml").read_bytes()


def make_jpeg(
    color: tuple[int, int, int] = (200, 30, 30), size: tuple[int, int] = (40, 60)
) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def jpeg_page() -> bytes:
    return make_jpeg()
