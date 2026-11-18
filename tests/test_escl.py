import pytest
import requests
import responses

from hp_scanner.escl import EsclClient
from hp_scanner.models import ScanJobError, ScannerBusyError, ScannerError, ScanSettings

BASE = "http://192.168.4.195:8080"
JOB = f"{BASE}/eSCL/ScanJobs/1001"


@pytest.fixture
def client():
    return EsclClient(host="192.168.4.195", port=8080)


@pytest.fixture
def mocked():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


def add_idle(rsps, status_idle_xml):
    rsps.get(f"{BASE}/eSCL/ScannerStatus", body=status_idle_xml, content_type="text/xml")


def test_base_url_and_scheme():
    assert EsclClient().base_url == "http://192.168.4.195:8080/"
    assert EsclClient("printer.local", 443, scheme="https").base_url == "https://printer.local:443/"


def test_capabilities_and_status(client, mocked, capabilities_xml, status_idle_xml):
    mocked.get(f"{BASE}/eSCL/ScannerCapabilities", body=capabilities_xml)
    add_idle(mocked, status_idle_xml)

    assert client.capabilities().make_and_model.startswith("Officejet 6700")
    assert client.status().is_idle


def test_get_error_wrapped(client, mocked):
    mocked.get(f"{BASE}/eSCL/ScannerStatus", status=500)
    with pytest.raises(ScannerError, match="GET eSCL/ScannerStatus failed"):
        client.status()


def test_connection_error_wrapped(client, mocked):
    mocked.get(f"{BASE}/eSCL/ScannerStatus", body=requests.ConnectionError("refused"))
    with pytest.raises(ScannerError, match="refused"):
        client.status()


def test_scan_single_page_platen(client, mocked, status_idle_xml, jpeg_page):
    add_idle(mocked, status_idle_xml)
    mocked.post(f"{BASE}/eSCL/ScanJobs", status=201, headers={"Location": JOB})
    mocked.get(f"{JOB}/NextDocument", body=jpeg_page, content_type="image/jpeg")
    mocked.get(f"{JOB}/NextDocument", status=404)
    mocked.delete(JOB, status=200)

    pages = client.scan(ScanSettings())

    assert pages == [jpeg_page]
    post = next(c for c in mocked.calls if c.request.method == "POST")
    assert post.request.headers["Content-Type"] == "text/xml"
    assert b"<pwg:InputSource>Platen</pwg:InputSource>" in post.request.body
    assert mocked.calls[-1].request.method == "DELETE"
    assert mocked.calls[-1].request.url == JOB


def test_scan_multi_page_with_retry_and_relative_location(client, mocked, jpeg_page):
    """ADF jobs return several pages; 503 means 'not ready yet' and should be retried."""
    page2 = jpeg_page + b"\x00"
    mocked.post(f"{BASE}/eSCL/ScanJobs", status=201, headers={"Location": "/eSCL/ScanJobs/77"})
    job = f"{BASE}/eSCL/ScanJobs/77"
    mocked.get(f"{job}/NextDocument", status=503)
    mocked.get(f"{job}/NextDocument", body=jpeg_page)
    mocked.get(f"{job}/NextDocument", status=503)
    mocked.get(f"{job}/NextDocument", body=page2)
    mocked.get(f"{job}/NextDocument", status=404)
    mocked.delete(job)

    pages = client.scan(ScanSettings(source="Feeder"), check_status=False)

    assert pages == [jpeg_page, page2]


def test_scan_refuses_when_not_idle(client, mocked):
    mocked.get(
        f"{BASE}/eSCL/ScannerStatus",
        body=b"""<scan:ScannerStatus xmlns:scan="http://schemas.hp.com/imaging/escl/2011/02/08"
                 xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
                 <pwg:State>Processing</pwg:State></scan:ScannerStatus>""",
    )
    with pytest.raises(ScannerBusyError, match="Processing"):
        client.scan(ScanSettings())
    assert all(c.request.method == "GET" for c in mocked.calls)


def test_scan_refuses_feeder_when_adf_empty(client, mocked, status_idle_xml):
    add_idle(mocked, status_idle_xml)
    with pytest.raises(ScannerBusyError, match="ADF is empty"):
        client.scan(ScanSettings(source="Feeder"))


def test_create_job_busy_and_conflict(client, mocked):
    mocked.post(f"{BASE}/eSCL/ScanJobs", status=503)
    with pytest.raises(ScannerBusyError, match="busy"):
        client.create_job(ScanSettings())

    mocked.replace(responses.POST, f"{BASE}/eSCL/ScanJobs", status=409)
    with pytest.raises(ScannerBusyError, match="conflict"):
        client.create_job(ScanSettings())


def test_create_job_missing_location(client, mocked):
    mocked.post(f"{BASE}/eSCL/ScanJobs", status=201)
    with pytest.raises(ScanJobError, match="Location"):
        client.create_job(ScanSettings())


def test_create_job_unexpected_status(client, mocked):
    mocked.post(f"{BASE}/eSCL/ScanJobs", status=500, body="boom")
    with pytest.raises(ScanJobError, match="HTTP 500: boom"):
        client.create_job(ScanSettings())


def test_scan_no_pages_raises_and_cleans_up(client, mocked):
    mocked.post(f"{BASE}/eSCL/ScanJobs", status=201, headers={"Location": JOB})
    mocked.get(f"{JOB}/NextDocument", status=404)
    mocked.delete(JOB)

    with pytest.raises(ScanJobError, match="without producing any pages"):
        client.scan(ScanSettings(), check_status=False)
    assert mocked.calls[-1].request.method == "DELETE"


def test_iter_pages_unexpected_status(client, mocked):
    mocked.get(f"{JOB}/NextDocument", status=500)
    with pytest.raises(ScanJobError, match="HTTP 500"):
        list(client.iter_pages(JOB))


def test_delete_job_failure_is_swallowed(client, mocked, caplog):
    mocked.delete(JOB, body=requests.ConnectionError("gone"))
    client.delete_job(JOB)  # must not raise
    assert "Failed to delete job" in caplog.text
