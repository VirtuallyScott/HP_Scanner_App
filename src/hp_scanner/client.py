"""Protocol selection: pick LEDM or eSCL for a given scanner."""

from __future__ import annotations

import logging
from typing import Protocol

import requests

from .escl import DEFAULT_HOST, DEFAULT_PORT, EsclClient
from .ledm import LedmClient
from .models import ScannerCapabilities, ScannerError, ScannerStatus, ScanSettings

log = logging.getLogger(__name__)

PROTOCOLS = ("auto", "ledm", "escl")


class ScannerClient(Protocol):
    base_url: str

    def capabilities(self) -> ScannerCapabilities: ...
    def status(self) -> ScannerStatus: ...
    def scan(self, settings: ScanSettings, check_status: bool = True) -> list[bytes]: ...


def detect_protocol(
    host: str,
    port: int,
    scheme: str = "http",
    timeout: float = 5.0,
    session: requests.Session | None = None,
) -> str:
    """Return ``"ledm"`` if the device answers ``GET /Scan/Status``, else ``"escl"``.

    LEDM is preferred because HP firmware that exposes it typically rejects eSCL jobs.
    """
    session = session or requests.Session()
    try:
        resp = session.get(f"{scheme}://{host}:{port}/Scan/Status", timeout=timeout)
    except requests.RequestException as exc:
        raise ScannerError(f"Cannot reach scanner at {host}:{port}: {exc}") from exc
    protocol = "ledm" if resp.status_code == 200 else "escl"
    log.debug("Detected protocol %s (Scan/Status -> HTTP %d)", protocol, resp.status_code)
    return protocol


def connect(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    scheme: str = "http",
    protocol: str = "auto",
    session: requests.Session | None = None,
) -> ScannerClient:
    """Build a client for ``host`` using ``protocol`` (``auto``, ``ledm`` or ``escl``)."""
    if protocol not in PROTOCOLS:
        raise ValueError(f"Unknown protocol {protocol!r}; choose one of {PROTOCOLS}")
    session = session or requests.Session()
    if protocol == "auto":
        protocol = detect_protocol(host, port, scheme, session=session)
    if protocol == "ledm":
        return LedmClient(host, port, scheme, session=session)
    return EsclClient(host, port, scheme, session=session)
