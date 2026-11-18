"""Minimal eSCL (AirScan) client for HP All-in-One scanners."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from urllib.parse import urljoin

import requests

from .models import (
    ScanJobError,
    ScannerBusyError,
    ScannerCapabilities,
    ScannerError,
    ScannerStatus,
    ScanSettings,
)

log = logging.getLogger(__name__)

DEFAULT_HOST = "192.168.4.195"
DEFAULT_PORT = 8080


class EsclClient:
    """Talks to a scanner's ``/eSCL`` REST endpoints.

    Args:
        host: Scanner IP address or hostname.
        port: eSCL port (HP devices expose 8080 over HTTP and 443 over HTTPS).
        scheme: ``http`` or ``https``.
        timeout: Connect timeout in seconds for control requests.
        page_timeout: Read timeout in seconds while waiting for a scanned page.
        session: Optional pre-configured :class:`requests.Session`.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        scheme: str = "http",
        timeout: float = 10.0,
        page_timeout: float = 300.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = f"{scheme}://{host}:{port}/"
        self.timeout = timeout
        self.page_timeout = page_timeout
        self.session = session or requests.Session()

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def capabilities(self) -> ScannerCapabilities:
        resp = self._get("eSCL/ScannerCapabilities")
        return ScannerCapabilities.from_xml(resp.content)

    def status(self) -> ScannerStatus:
        resp = self._get("eSCL/ScannerStatus")
        return ScannerStatus.from_xml(resp.content)

    def _get(self, path: str, **kwargs: object) -> requests.Response:
        try:
            resp = self.session.get(self._url(path), timeout=self.timeout, **kwargs)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ScannerError(f"GET {path} failed: {exc}") from exc
        return resp

    def create_job(self, settings: ScanSettings) -> str:
        """Submit a scan job and return its absolute job URL."""
        url = self._url("eSCL/ScanJobs")
        try:
            resp = self.session.post(
                url,
                data=settings.to_xml(),
                headers={"Content-Type": "text/xml"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ScannerError(f"POST ScanJobs failed: {exc}") from exc

        if resp.status_code == 503:
            raise ScannerBusyError("Scanner is busy; try again shortly")
        if resp.status_code == 409:
            raise ScannerBusyError("Scanner rejected job (conflict): is the ADF empty?")
        if resp.status_code not in (200, 201):
            raise ScanJobError(
                f"ScanJobs returned HTTP {resp.status_code}: {resp.text.strip()[:200]}"
            )
        location = resp.headers.get("Location")
        if not location:
            raise ScanJobError("ScanJobs response lacked a Location header")
        return urljoin(self.base_url, location)

    def iter_pages(self, job_url: str, poll_interval: float = 1.0) -> Iterator[bytes]:
        """Yield raw page bytes from ``job_url`` until the scanner reports no more pages."""
        next_url = job_url.rstrip("/") + "/NextDocument"
        while True:
            try:
                resp = self.session.get(next_url, timeout=(self.timeout, self.page_timeout))
            except requests.RequestException as exc:
                raise ScanJobError(f"Fetching page failed: {exc}") from exc

            if resp.status_code == 200:
                log.debug(
                    "Received page (%d bytes, %s)",
                    len(resp.content),
                    resp.headers.get("Content-Type"),
                )
                yield resp.content
            elif resp.status_code == 404:
                return
            elif resp.status_code == 503:
                time.sleep(poll_interval)
            else:
                raise ScanJobError(f"NextDocument returned HTTP {resp.status_code}")

    def delete_job(self, job_url: str) -> None:
        try:
            self.session.delete(job_url, timeout=self.timeout)
        except requests.RequestException as exc:  # cleanup is best-effort
            log.warning("Failed to delete job %s: %s", job_url, exc)

    def scan(self, settings: ScanSettings, check_status: bool = True) -> list[bytes]:
        """Run a full scan job and return the list of page images (one per page).

        Pages are returned in the format requested by ``settings.document_format``.
        """
        if check_status:
            status = self.status()
            if not status.is_idle:
                raise ScannerBusyError(f"Scanner state is {status.state!r}, expected 'Idle'")
            if settings.source == "Feeder" and status.adf_state == "ScannerAdfEmpty":
                raise ScannerBusyError("ADF is empty; load documents or use the platen")

        job_url = self.create_job(settings)
        log.info("Created scan job %s", job_url)
        pages: list[bytes] = []
        try:
            for page in self.iter_pages(job_url):
                pages.append(page)
                log.info("Received page %d", len(pages))
        finally:
            self.delete_job(job_url)

        if not pages:
            raise ScanJobError("Scan job completed without producing any pages")
        return pages
