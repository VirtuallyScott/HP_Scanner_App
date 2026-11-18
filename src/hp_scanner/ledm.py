"""LEDM scan client for older HP All-in-One devices.

Many HP devices from the 2010-2014 era (e.g. the Officejet 6700) advertise eSCL but
reject every ``POST /eSCL/ScanJobs`` with HTTP 409. The same devices accept scan jobs via
HP's proprietary LEDM REST protocol on the same port:

1. ``GET /Scan/Status`` -> ``ScannerState`` (``Idle`` / ``BusyWithScanJob``), ``AdfState``
2. ``GET /Scan/ScanCaps`` -> supported resolutions, color types and input sources
3. ``POST /Scan/Jobs`` with a ``ScanSettings`` body -> ``201`` + ``Location: /Jobs/JobList/N``
4. Poll the job URL. Each page appears as ``PreScanPage`` with ``PageState`` progressing
   ``PreparingScan`` -> ``ReadyToUpload`` and a ``BinaryURL``.
5. ``GET BinaryURL`` promptly (the device cancels the page if nobody downloads it).
6. Repeat until ``JobState`` is ``Completed`` (or ``Canceled``/``Aborted``).
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urljoin

import requests

from .models import (
    InputCaps,
    ScanJobError,
    ScannerBusyError,
    ScannerCapabilities,
    ScannerError,
    ScannerStatus,
    ScanSettings,
)

log = logging.getLogger(__name__)

SCAN_NS = "http://www.hp.com/schemas/imaging/con/cnx/scan/2008/08/19"
JOBS_NS = "http://www.hp.com/schemas/imaging/con/ledm/jobs/2009/04/30"
DD_NS = "http://www.hp.com/schemas/imaging/con/dictionaries/1.0/"
FAX_NS = "http://www.hp.com/schemas/imaging/con/fax/2008/06/13"
NS = {"s": SCAN_NS, "j": JOBS_NS}

# Map eSCL vocabulary (used throughout ScanSettings / ScannerCapabilities) to LEDM.
COLOR_TO_LEDM = {"RGB24": ("Color", 8), "Grayscale8": ("Gray", 8), "BlackAndWhite1": ("Gray", 1)}
LEDM_TO_COLOR = {"Color8": "RGB24", "Gray8": "Grayscale8", "K1": "BlackAndWhite1"}
SOURCE_TO_LEDM = {"Platen": "Platen", "Feeder": "Adf"}
FORMAT_TO_LEDM = {
    "image/jpeg": "Jpeg",
    "application/octet-stream": "Raw",
    "application/pdf": "Pdf",
}
LEDM_TO_FORMAT = {v: k for k, v in FORMAT_TO_LEDM.items()}
# The EWS "Webscan" page requests Format=Pdf and the device answers with application/pdf,
# even though ScanCaps only advertises Raw and Jpeg. Treat it as always available.
IMPLICIT_FORMATS = {"application/pdf"}
STATE_TO_ESCL = {"Idle": "Idle", "BusyWithScanJob": "Processing"}
ADF_TO_ESCL = {"Empty": "ScannerAdfEmpty", "Loaded": "ScannerAdfLoaded"}

# JobState values seen on the wire / in HPLIP: Processing, Blocked (keep waiting),
# Completed, Canceled, Aborted. PageState: PreparingScan, ReadyToUpload, UploadCompleted,
# CanceledByDevice, CanceledByClient.
TERMINAL_JOB_STATES = {"Completed", "Canceled", "Aborted"}
CANCELED_PAGE_STATES = {"CanceledByDevice", "CanceledByClient"}

# Same body HPLIP's bb_ledm.c sends (CANCEL_JOB_DATA); PUT to the job URL.
CANCEL_JOB_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    f'<j:Job xmlns:j="{JOBS_NS}" xmlns:dd="{DD_NS}" xmlns:fax="{FAX_NS}" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    f'xsi:schemaLocation="{JOBS_NS} ../schemas/Jobs.xsd">'
    "<j:JobState>Canceled</j:JobState></j:Job>"
)


def parse_capabilities(data: bytes | str) -> ScannerCapabilities:
    root = ET.fromstring(data)
    formats = {
        LEDM_TO_FORMAT[f.text.strip()]
        for f in root.findall("s:ColorEntries/s:ColorEntry/s:Formats/s:Format", NS)
        if f.text and f.text.strip() in LEDM_TO_FORMAT
    } | IMPLICIT_FORMATS

    def input_caps(path: str) -> InputCaps | None:
        el = root.find(path, NS)
        if el is None:
            return None
        resolutions: set[int] = set()
        modes: set[str] = set()
        for res in el.findall("s:SupportedResolutions/s:Resolution", NS):
            x = res.findtext("s:XResolution", namespaces=NS)
            if x:
                resolutions.add(int(x))
            for ct in res.findall("s:ColorTypes/s:ColorType", NS):
                if ct.text and ct.text.strip() in LEDM_TO_COLOR:
                    modes.add(LEDM_TO_COLOR[ct.text.strip()])
        return InputCaps(
            min_width=int(el.findtext("s:MinWidth", default="0", namespaces=NS)),
            max_width=int(el.findtext("s:MaxWidth", default="0", namespaces=NS)),
            min_height=int(el.findtext("s:MinHeight", default="0", namespaces=NS)),
            max_height=int(el.findtext("s:MaxHeight", default="0", namespaces=NS)),
            resolutions=tuple(sorted(resolutions)),
            color_modes=tuple(sorted(modes)),
        )

    model = root.findtext("s:DeviceCaps/s:ModelName", default="", namespaces=NS).strip()
    return ScannerCapabilities(
        make_and_model=model,
        serial_number="",
        version="LEDM",
        formats=tuple(sorted(formats)),
        platen=input_caps("s:Platen/s:InputSourceCaps"),
        adf=input_caps("s:Adf/s:InputSourceCaps"),
        adf_capacity=None,
    )


def parse_status(data: bytes | str) -> ScannerStatus:
    root = ET.fromstring(data)
    state = (root.findtext("s:ScannerState", default="Unknown", namespaces=NS)).strip()
    adf = root.findtext("s:AdfState", namespaces=NS)
    adf = adf.strip() if adf else None
    return ScannerStatus(
        state=STATE_TO_ESCL.get(state, state),
        adf_state=ADF_TO_ESCL.get(adf, adf) if adf else None,
    )


def settings_to_xml(settings: ScanSettings) -> bytes:
    """Build the ``scan:ScanJob`` body the device's own Webscan page posts.

    Captured from the Officejet 6700 embedded web server: element order matters to some
    firmware, so it mirrors the EWS exactly. ``CompressionQFactor`` is ``100 - quality``
    (the EWS "Quality" slider), ``ToneMap`` values are in thousandths with 1000 = neutral.
    Optional tuning (``Threshold``, ``SharpeningLevel``, ``NoiseRemoval``) is only emitted
    when supplied via ``settings.extra``.
    """
    try:
        color_space, bit_depth = COLOR_TO_LEDM[settings.color_mode]
    except KeyError as exc:
        raise ValueError(f"Color mode {settings.color_mode!r} not supported by LEDM") from exc
    try:
        source = SOURCE_TO_LEDM[settings.source]
    except KeyError as exc:
        raise ValueError(f"Input source {settings.source!r} not supported by LEDM") from exc
    try:
        fmt = FORMAT_TO_LEDM[settings.document_format]
    except KeyError as exc:
        raise ValueError(
            f"Format {settings.document_format!r} not supported by LEDM; "
            f"choose one of {sorted(FORMAT_TO_LEDM)}"
        ) from exc

    ET.register_namespace("scan", SCAN_NS)
    root = ET.Element(f"{{{SCAN_NS}}}ScanJob")

    def add(parent: ET.Element, tag: str, value: object) -> ET.Element:
        el = ET.SubElement(parent, f"{{{SCAN_NS}}}{tag}")
        el.text = str(value)
        return el

    add(root, "XResolution", settings.resolution)
    add(root, "YResolution", settings.resolution)
    add(root, "XStart", settings.x_offset)
    add(root, "YStart", settings.y_offset)
    add(root, "Width", settings.width)
    add(root, "Height", settings.height)
    add(root, "Format", fmt)
    add(root, "CompressionQFactor", 100 - settings.quality)
    add(root, "ColorSpace", color_space)
    add(root, "BitDepth", bit_depth)
    add(root, "InputSource", source)
    add(root, "GrayRendering", settings.extra.get("GrayRendering", "NTSC"))
    tone = ET.SubElement(root, f"{{{SCAN_NS}}}ToneMap")
    add(tone, "Gamma", settings.extra.get("Gamma", "1000"))
    add(tone, "Brightness", settings.extra.get("Brightness", "1000"))
    add(tone, "Contrast", settings.extra.get("Contrast", "1000"))
    add(tone, "Highlite", settings.extra.get("Highlite", "179"))
    add(tone, "Shadow", settings.extra.get("Shadow", "25"))
    if "Threshold" in settings.extra:
        add(tone, "Threshold", settings.extra["Threshold"])
    for optional in ("SharpeningLevel", "NoiseRemoval"):
        if optional in settings.extra:
            add(root, optional, settings.extra[optional])
    add(root, "ContentType", "Document" if color_space == "Gray" else "Photo")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


@dataclass(frozen=True)
class JobSnapshot:
    """One poll of a LEDM job URL."""

    state: str
    page_number: int | None
    page_state: str | None
    binary_url: str | None

    @classmethod
    def from_xml(cls, data: bytes | str) -> JobSnapshot:
        root = ET.fromstring(data)
        state = (root.findtext("j:JobState", default="Unknown", namespaces=NS)).strip()
        pre = root.find("s:ScanJob/s:PreScanPage", NS)
        post = root.find("s:ScanJob/s:PostScanPage", NS)
        page = pre if pre is not None else post
        number = page.findtext("s:PageNumber", namespaces=NS) if page is not None else None
        page_state = page.findtext("s:PageState", namespaces=NS) if page is not None else None
        binary = pre.findtext("s:BinaryURL", namespaces=NS) if pre is not None else None
        return cls(
            state=state,
            page_number=int(number) if number else None,
            page_state=page_state.strip() if page_state else None,
            binary_url=binary.strip() if binary else None,
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_JOB_STATES

    @property
    def canceled(self) -> bool:
        return self.state == "Canceled" or self.page_state in CANCELED_PAGE_STATES

    @property
    def ready(self) -> bool:
        return self.page_state == "ReadyToUpload" and self.binary_url is not None


class LedmClient:
    """Scan via HP LEDM. Exposes the same ``capabilities()``/``status()``/``scan()`` API as
    :class:`hp_scanner.escl.EsclClient`."""

    def __init__(
        self,
        host: str,
        port: int = 8080,
        scheme: str = "http",
        timeout: float = 30.0,
        page_timeout: float = 300.0,
        session: requests.Session | None = None,
        poll_interval: float = 0.5,
        job_timeout: float = 600.0,
    ) -> None:
        self.base_url = f"{scheme}://{host}:{port}/"
        self.timeout = timeout
        self.page_timeout = page_timeout
        self.poll_interval = poll_interval
        self.job_timeout = job_timeout
        self.session = session or requests.Session()

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def _get(
        self, path: str, timeout: float | tuple[float, float] | None = None
    ) -> requests.Response:
        try:
            resp = self.session.get(self._url(path), timeout=timeout or self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ScannerError(f"GET {path} failed: {exc}") from exc
        return resp

    def capabilities(self) -> ScannerCapabilities:
        return parse_capabilities(self._get("Scan/ScanCaps").content)

    def status(self) -> ScannerStatus:
        return parse_status(self._get("Scan/Status").content)

    def create_job(self, settings: ScanSettings) -> str:
        try:
            resp = self.session.post(
                self._url("Scan/Jobs"),
                data=settings_to_xml(settings),
                headers={"Content-Type": "text/xml"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ScannerError(f"POST Scan/Jobs failed: {exc}") from exc
        if resp.status_code in (409, 503):
            raise ScannerBusyError(f"Scanner refused job (HTTP {resp.status_code}); is it busy?")
        if resp.status_code not in (200, 201):
            raise ScanJobError(f"Scan/Jobs returned HTTP {resp.status_code}: {resp.text[:200]}")
        location = resp.headers.get("Location")
        if not location:
            raise ScanJobError("Scan/Jobs response lacked a Location header")
        return urljoin(self.base_url, location)

    def poll_job(self, job_url: str) -> JobSnapshot:
        try:
            resp = self.session.get(job_url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ScanJobError(f"Polling job failed: {exc}") from exc
        return JobSnapshot.from_xml(resp.content)

    def download_page(self, binary_url: str) -> bytes:
        resp = self._get(binary_url, timeout=(self.timeout, self.page_timeout))
        if not resp.content:
            raise ScanJobError("Device returned an empty page (download started too late?)")
        return resp.content

    def cancel_job(self, job_url: str) -> None:
        """Best-effort cancel via the LEDM job-state update (``PUT`` ``JobState=Canceled``)."""
        try:
            self.session.put(
                job_url,
                data=CANCEL_JOB_XML,
                headers={"Content-Type": "text/xml"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            log.warning("Failed to cancel job %s: %s", job_url, exc)

    def scan(self, settings: ScanSettings, check_status: bool = True) -> list[bytes]:
        if check_status:
            status = self.status()
            if not status.is_idle:
                raise ScannerBusyError(f"Scanner state is {status.state!r}, expected 'Idle'")
            if settings.source == "Feeder" and status.adf_state == "ScannerAdfEmpty":
                raise ScannerBusyError("ADF is empty; load documents or use the platen")

        job_url = self.create_job(settings)
        log.info("Created LEDM scan job %s", job_url)
        pages: list[bytes] = []
        downloaded: set[int] = set()
        deadline = time.monotonic() + self.job_timeout
        try:
            while True:
                snap = self.poll_job(job_url)
                log.debug("job=%s page=%s state=%s", snap.state, snap.page_number, snap.page_state)
                if snap.ready and snap.page_number not in downloaded:
                    assert snap.binary_url is not None and snap.page_number is not None
                    pages.append(self.download_page(snap.binary_url))
                    downloaded.add(snap.page_number)
                    log.info("Received page %d", snap.page_number)
                    continue
                if snap.is_terminal:
                    if snap.canceled and not pages:
                        raise ScanJobError(
                            f"Scan job was canceled ({snap.page_state or snap.state})"
                        )
                    if snap.state != "Completed" and not pages:
                        raise ScanJobError(
                            f"Scan job ended with state {snap.state!r} ({snap.page_state})"
                        )
                    break
                if time.monotonic() > deadline:
                    self.cancel_job(job_url)
                    raise ScanJobError(f"Scan job did not finish within {self.job_timeout:.0f}s")
                time.sleep(self.poll_interval)
        except (KeyboardInterrupt, ScannerError):
            self.cancel_job(job_url)
            raise

        if not pages:
            raise ScanJobError("Scan job completed without producing any pages")
        return pages
