import xml.etree.ElementTree as ET

import pytest
import requests
import responses
from conftest import FIXTURES

from hp_scanner.client import connect, detect_protocol
from hp_scanner.escl import EsclClient
from hp_scanner.ledm import (
    SCAN_NS,
    JobSnapshot,
    LedmClient,
    parse_capabilities,
    parse_status,
    settings_to_xml,
)
from hp_scanner.models import ScanJobError, ScannerBusyError, ScannerError, ScanSettings

BASE = "http://192.168.4.195:8080"
JOB = f"{BASE}/Jobs/JobList/1"
PAGE1 = f"{BASE}/Scan/Jobs/1/Pages/1"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def client():
    return LedmClient("192.168.4.195", poll_interval=0)


@pytest.fixture
def mocked():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


def test_parse_capabilities_real_device():
    caps = parse_capabilities(fixture("ledm_scancaps.xml"))
    assert caps.make_and_model == "h711g"
    assert caps.version == "LEDM"
    # application/pdf is implicit: the EWS Webscan requests Format=Pdf and it works
    assert caps.formats == ("application/octet-stream", "application/pdf", "image/jpeg")
    assert caps.platen is not None and caps.adf is not None
    assert caps.platen.resolutions == (75, 100, 200, 300, 600, 1200, 2400)
    assert caps.platen.color_modes == ("BlackAndWhite1", "Grayscale8", "RGB24")
    assert (caps.platen.max_width, caps.platen.max_height) == (2550, 3508)
    assert caps.adf.resolutions == (75, 100, 200, 300, 600)
    assert caps.adf.max_height == 4200


def test_capabilities_validate_same_settings_as_escl():
    """The LEDM caps are normalised to eSCL vocabulary so ScanSettings validation is shared."""
    caps = parse_capabilities(fixture("ledm_scancaps.xml"))
    caps.validate(ScanSettings.for_page("letter", color_mode="RGB24", resolution=300))
    with pytest.raises(ValueError, match="Resolution 1200"):
        caps.validate(ScanSettings(source="Feeder", resolution=1200))


def test_parse_status_maps_to_escl_vocabulary():
    status = parse_status(fixture("ledm_status_idle.xml"))
    assert status.is_idle
    assert status.adf_state == "ScannerAdfEmpty"

    busy = parse_status(
        b'<ScanStatus xmlns="http://www.hp.com/schemas/imaging/con/cnx/scan/2008/08/19">'
        b"<ScannerState>BusyWithScanJob</ScannerState><AdfState>Loaded</AdfState></ScanStatus>"
    )
    assert busy.state == "Processing"
    assert busy.adf_loaded


def test_settings_to_xml_color_platen():
    xml = settings_to_xml(ScanSettings.for_page("letter", color_mode="RGB24", resolution=300))
    root = ET.fromstring(xml)
    ns = {"s": SCAN_NS}
    assert root.tag == f"{{{SCAN_NS}}}ScanJob"
    assert root.findtext("s:XResolution", namespaces=ns) == "300"
    assert root.findtext("s:Width", namespaces=ns) == "2550"
    assert root.findtext("s:Height", namespaces=ns) == "3300"
    assert root.findtext("s:Format", namespaces=ns) == "Jpeg"
    assert root.findtext("s:ColorSpace", namespaces=ns) == "Color"
    assert root.findtext("s:BitDepth", namespaces=ns) == "8"
    assert root.findtext("s:InputSource", namespaces=ns) == "Platen"
    assert root.findtext("s:ContentType", namespaces=ns) == "Photo"
    assert root.findtext("s:CompressionQFactor", namespaces=ns) == "25"
    assert root.findtext("s:ToneMap/s:Brightness", namespaces=ns) == "1000"
    # Mirrors the EWS Webscan payload: prefixed scan: namespace, no optional tuning tags
    assert xml.startswith(b"<?xml")
    assert b"<scan:ScanJob xmlns:scan=" in xml and b"<scan:XResolution>300" in xml
    for absent in (b"Threshold", b"SharpeningLevel", b"NoiseRemoval"):
        assert absent not in xml


def test_settings_to_xml_gray_adf_and_extras():
    xml = settings_to_xml(
        ScanSettings(
            source="Feeder",
            color_mode="Grayscale8",
            quality=100,
            document_format="application/pdf",
            extra={"Brightness": "1200", "Threshold": "128", "SharpeningLevel": "64"},
        )
    )
    assert b"<scan:InputSource>Adf</scan:InputSource>" in xml
    assert b"<scan:ColorSpace>Gray</scan:ColorSpace>" in xml
    assert b"<scan:Format>Pdf</scan:Format>" in xml
    assert b"<scan:CompressionQFactor>0</scan:CompressionQFactor>" in xml
    assert b"<scan:ContentType>Document</scan:ContentType>" in xml
    assert b"<scan:Brightness>1200</scan:Brightness>" in xml
    assert b"<scan:Threshold>128</scan:Threshold>" in xml
    assert b"<scan:SharpeningLevel>64</scan:SharpeningLevel>" in xml
    assert b"NoiseRemoval" not in xml


def test_settings_to_xml_rejects_unknown():
    with pytest.raises(ValueError, match="Color mode"):
        settings_to_xml(ScanSettings(color_mode="CMYK"))
    with pytest.raises(ValueError, match="Input source"):
        settings_to_xml(ScanSettings(source="Camera"))
    with pytest.raises(ValueError, match="Format"):
        settings_to_xml(ScanSettings(document_format="image/png"))


def test_job_snapshot_parsing():
    ready = JobSnapshot.from_xml(fixture("ledm_job_ready.xml"))
    assert (ready.state, ready.page_number, ready.page_state) == ("Processing", 1, "ReadyToUpload")
    assert ready.binary_url == "/Scan/Jobs/1/Pages/1"
    assert ready.ready and not ready.is_terminal

    done = JobSnapshot.from_xml(fixture("ledm_job_completed.xml"))
    assert (done.state, done.page_number, done.page_state) == ("Completed", 1, "UploadCompleted")
    assert done.binary_url is None
    assert done.is_terminal and not done.ready


def _preparing(n: int = 1) -> bytes:
    return (
        fixture("ledm_job_ready.xml")
        .replace(b"ReadyToUpload", b"PreparingScan")
        .replace(b"<PageNumber>1<", f"<PageNumber>{n}<".encode())
    )


def _ready(n: int) -> bytes:
    return (
        fixture("ledm_job_ready.xml")
        .replace(b"<PageNumber>1<", f"<PageNumber>{n}<".encode())
        .replace(b"/Pages/1", f"/Pages/{n}".encode())
    )


def test_scan_single_page(client, mocked, jpeg_page):
    mocked.get(f"{BASE}/Scan/Status", body=fixture("ledm_status_idle.xml"))
    mocked.post(f"{BASE}/Scan/Jobs", status=201, headers={"Location": "/Jobs/JobList/1"})
    mocked.get(JOB, body=_preparing())
    mocked.get(JOB, body=_preparing())
    mocked.get(JOB, body=fixture("ledm_job_ready.xml"))
    mocked.get(PAGE1, body=jpeg_page, content_type="image/jpeg")
    mocked.get(JOB, body=fixture("ledm_job_completed.xml"))

    pages = client.scan(ScanSettings(resolution=75))

    assert pages == [jpeg_page]
    post = next(c for c in mocked.calls if c.request.method == "POST")
    assert post.request.headers["Content-Type"] == "text/xml"
    assert b"<scan:XResolution>75</scan:XResolution>" in post.request.body


def test_scan_multi_page_adf_downloads_each_page_once(client, mocked, jpeg_page):
    page2 = jpeg_page + b"\x00"
    mocked.post(f"{BASE}/Scan/Jobs", status=201, headers={"Location": JOB})
    mocked.get(JOB, body=_ready(1))
    mocked.get(PAGE1, body=jpeg_page)
    mocked.get(JOB, body=_ready(1))  # device still shows page 1 briefly after upload
    mocked.get(JOB, body=_preparing(2))
    mocked.get(JOB, body=_ready(2))
    mocked.get(f"{BASE}/Scan/Jobs/1/Pages/2", body=page2)
    mocked.get(JOB, body=fixture("ledm_job_completed.xml"))

    pages = client.scan(ScanSettings(source="Feeder"), check_status=False)

    assert pages == [jpeg_page, page2]
    assert sum(1 for c in mocked.calls if "/Pages/" in c.request.url) == 2


def test_scan_canceled_by_device_raises(client, mocked):
    mocked.post(f"{BASE}/Scan/Jobs", status=201, headers={"Location": JOB})
    mocked.get(
        JOB,
        body=fixture("ledm_job_completed.xml")
        .replace(b"UploadCompleted", b"CanceledByDevice")
        .replace(b">Completed<", b">Canceled<"),
    )
    with pytest.raises(ScanJobError, match="canceled.*CanceledByDevice"):
        client.scan(ScanSettings(), check_status=False)


def test_scan_empty_page_download_raises_and_cancels(client, mocked):
    mocked.post(f"{BASE}/Scan/Jobs", status=201, headers={"Location": JOB})
    mocked.get(JOB, body=fixture("ledm_job_ready.xml"))
    mocked.get(PAGE1, body=b"")
    mocked.put(JOB)
    with pytest.raises(ScanJobError, match="empty page"):
        client.scan(ScanSettings(), check_status=False)
    assert mocked.calls[-1].request.method == "PUT"
    assert "<j:JobState>Canceled</j:JobState>" in mocked.calls[-1].request.body


def test_scan_job_timeout(mocked):
    client = LedmClient("192.168.4.195", poll_interval=0, job_timeout=0)
    mocked.post(f"{BASE}/Scan/Jobs", status=201, headers={"Location": JOB})
    mocked.get(JOB, body=_preparing())
    mocked.put(JOB)
    with pytest.raises(ScanJobError, match="did not finish"):
        client.scan(ScanSettings(), check_status=False)


def test_scan_refuses_busy_and_adf_empty(client, mocked):
    mocked.get(
        f"{BASE}/Scan/Status",
        body=b'<ScanStatus xmlns="http://www.hp.com/schemas/imaging/con/cnx/scan/2008/08/19">'
        b"<ScannerState>BusyWithScanJob</ScannerState><AdfState>Empty</AdfState></ScanStatus>",
    )
    with pytest.raises(ScannerBusyError, match="Processing"):
        client.scan(ScanSettings())

    mocked.replace(responses.GET, f"{BASE}/Scan/Status", body=fixture("ledm_status_idle.xml"))
    with pytest.raises(ScannerBusyError, match="ADF is empty"):
        client.scan(ScanSettings(source="Feeder"))


def test_create_job_errors(client, mocked):
    mocked.post(f"{BASE}/Scan/Jobs", status=409)
    with pytest.raises(ScannerBusyError, match="HTTP 409"):
        client.create_job(ScanSettings())
    mocked.replace(responses.POST, f"{BASE}/Scan/Jobs", status=201)
    with pytest.raises(ScanJobError, match="Location"):
        client.create_job(ScanSettings())
    mocked.replace(responses.POST, f"{BASE}/Scan/Jobs", status=500, body="nope")
    with pytest.raises(ScanJobError, match="HTTP 500: nope"):
        client.create_job(ScanSettings())
    mocked.replace(responses.POST, f"{BASE}/Scan/Jobs", body=requests.ConnectionError("down"))
    with pytest.raises(ScannerError, match="down"):
        client.create_job(ScanSettings())


def test_detect_protocol_and_connect(mocked):
    mocked.get(f"{BASE}/Scan/Status", body=fixture("ledm_status_idle.xml"))
    assert detect_protocol("192.168.4.195", 8080) == "ledm"
    assert isinstance(connect("192.168.4.195", 8080), LedmClient)

    mocked.replace(responses.GET, f"{BASE}/Scan/Status", status=404)
    assert detect_protocol("192.168.4.195", 8080) == "escl"
    assert isinstance(connect("192.168.4.195", 8080), EsclClient)

    assert isinstance(connect("192.168.4.195", 8080, protocol="escl"), EsclClient)
    assert isinstance(connect("192.168.4.195", 8080, protocol="ledm"), LedmClient)
    with pytest.raises(ValueError, match="Unknown protocol"):
        connect("192.168.4.195", 8080, protocol="ipp")


def test_detect_protocol_unreachable(mocked):
    mocked.get(f"{BASE}/Scan/Status", body=requests.ConnectionError("refused"))
    with pytest.raises(ScannerError, match="Cannot reach scanner"):
        detect_protocol("192.168.4.195", 8080)
