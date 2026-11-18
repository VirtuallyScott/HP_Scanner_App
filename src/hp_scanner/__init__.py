"""hp_scanner: scan color PNGs and document PDFs from an HP All-in-One over LEDM or eSCL."""

from importlib import metadata as _metadata

from .client import PROTOCOLS, ScannerClient, connect, detect_protocol
from .config import (
    Config,
    Connection,
    Setting,
    config_path,
    default_destination,
    load_config,
    normalize_host,
    resolve_connection,
    save_config,
)
from .escl import DEFAULT_HOST, DEFAULT_PORT, EsclClient
from .jpeg import fix_dnl_height
from .ledm import LedmClient
from .models import (
    PAGE_SIZES,
    InputCaps,
    ScanJobError,
    ScannerBusyError,
    ScannerCapabilities,
    ScannerError,
    ScannerStatus,
    ScanSettings,
)
from .naming import auto_output_path, normalize_prefix
from .output import PageConversionError, save_jpeg, save_pages, save_pdf, save_png, save_raw_pages
from .presets import QUALITY_PRESETS, QualityPreset, normalize_type

try:
    __version__ = _metadata.version("hp-scanner")
except (
    _metadata.PackageNotFoundError
):  # pragma: no cover - running from a source tree, not installed
    __version__ = "0+unknown"

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "PAGE_SIZES",
    "PROTOCOLS",
    "PageConversionError",
    "QUALITY_PRESETS",
    "QualityPreset",
    "Config",
    "Connection",
    "EsclClient",
    "InputCaps",
    "LedmClient",
    "ScanJobError",
    "ScanSettings",
    "ScannerBusyError",
    "ScannerCapabilities",
    "ScannerClient",
    "ScannerError",
    "ScannerStatus",
    "Setting",
    "__version__",
    "auto_output_path",
    "config_path",
    "connect",
    "default_destination",
    "detect_protocol",
    "fix_dnl_height",
    "load_config",
    "normalize_host",
    "normalize_prefix",
    "normalize_type",
    "resolve_connection",
    "save_config",
    "save_jpeg",
    "save_pages",
    "save_pdf",
    "save_png",
    "save_raw_pages",
]
