"""Data models for eSCL scanner capabilities, status, and scan settings."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

SCAN_NS = "http://schemas.hp.com/imaging/escl/2011/02/08"
PWG_NS = "http://www.pwg.org/schemas/2010/12/sm"
NS = {"scan": SCAN_NS, "pwg": PWG_NS}

# eSCL scan regions are expressed in 1/300ths of an inch regardless of resolution.
UNITS_PER_INCH = 300

PAGE_SIZES: dict[str, tuple[int, int]] = {
    "letter": (2550, 3300),
    "legal": (2550, 4200),
    "a4": (2480, 3508),
    "a5": (1748, 2480),
}

COLOR_MODES = {"color": "RGB24", "gray": "Grayscale8", "bw": "BlackAndWhite1"}
SOURCES = {"platen": "Platen", "adf": "Feeder"}


class ScannerError(Exception):
    """Base error for scanner communication problems."""


class ScannerBusyError(ScannerError):
    """Raised when the scanner is not idle or the ADF is empty."""


class ScanJobError(ScannerError):
    """Raised when a scan job fails or produces no pages."""


@dataclass(frozen=True)
class InputCaps:
    """Dimension and resolution limits for one input source (platen or ADF)."""

    min_width: int
    max_width: int
    min_height: int
    max_height: int
    resolutions: tuple[int, ...]
    color_modes: tuple[str, ...]

    @classmethod
    def from_xml(cls, el: ET.Element) -> InputCaps:
        resolutions: list[int] = []
        modes: set[str] = set()
        for res in el.findall("scan:SupportedResolutions/scan:Resolution", NS):
            x = res.findtext("scan:XResolution", namespaces=NS)
            if x is not None:
                resolutions.append(int(x))
            for ref in res.findall("scan:ColorReferences/scan:ColorReference", NS):
                if ref.text:
                    modes.add(ref.text.strip())
        return cls(
            min_width=int(el.findtext("scan:MinWidth", default="0", namespaces=NS)),
            max_width=int(el.findtext("scan:MaxWidth", default="0", namespaces=NS)),
            min_height=int(el.findtext("scan:MinHeight", default="0", namespaces=NS)),
            max_height=int(el.findtext("scan:MaxHeight", default="0", namespaces=NS)),
            resolutions=tuple(sorted(set(resolutions))),
            color_modes=tuple(sorted(modes)),
        )


@dataclass(frozen=True)
class ScannerCapabilities:
    make_and_model: str
    serial_number: str
    version: str
    formats: tuple[str, ...]
    platen: InputCaps | None
    adf: InputCaps | None
    adf_capacity: int | None = None

    @classmethod
    def from_xml(cls, data: bytes | str) -> ScannerCapabilities:
        root = ET.fromstring(data)
        formats: set[str] = set()
        for fmt in root.findall(".//scan:Formats/pwg:DocumentFormat", NS):
            if fmt.text:
                formats.add(fmt.text.strip())

        platen_el = root.find("scan:Platen/scan:PlatenInputCaps", NS)
        adf_el = root.find("scan:Adf/scan:AdfSimplexInputCaps", NS)
        capacity = root.findtext("scan:Adf/scan:FeederCapacity", namespaces=NS)

        return cls(
            make_and_model=(root.findtext("pwg:MakeAndModel", default="", namespaces=NS)).strip(),
            serial_number=(root.findtext("pwg:SerialNumber", default="", namespaces=NS)).strip(),
            version=(root.findtext("pwg:Version", default="", namespaces=NS)).strip(),
            formats=tuple(sorted(formats)),
            platen=InputCaps.from_xml(platen_el) if platen_el is not None else None,
            adf=InputCaps.from_xml(adf_el) if adf_el is not None else None,
            adf_capacity=int(capacity) if capacity else None,
        )

    def input_caps(self, source: str) -> InputCaps:
        caps = self.platen if source == "Platen" else self.adf
        if caps is None:
            raise ScannerError(f"Scanner has no input source {source!r}")
        return caps

    def validate(self, settings: ScanSettings) -> None:
        """Raise ``ValueError`` if ``settings`` are outside this scanner's capabilities."""
        caps = self.input_caps(settings.source)
        if settings.resolution not in caps.resolutions:
            raise ValueError(
                f"Resolution {settings.resolution} not supported by {settings.source}; "
                f"choose one of {list(caps.resolutions)}"
            )
        if settings.color_mode not in caps.color_modes:
            raise ValueError(
                f"Color mode {settings.color_mode!r} not supported by {settings.source}; "
                f"choose one of {list(caps.color_modes)}"
            )
        if not caps.min_width <= settings.width <= caps.max_width:
            raise ValueError(
                f"Width {settings.width} out of range [{caps.min_width}, {caps.max_width}]"
            )
        if not caps.min_height <= settings.height <= caps.max_height:
            raise ValueError(
                f"Height {settings.height} out of range [{caps.min_height}, {caps.max_height}]"
            )
        if self.formats and settings.document_format not in self.formats:
            raise ValueError(
                f"Format {settings.document_format!r} not supported; "
                f"choose one of {list(self.formats)}"
            )


@dataclass(frozen=True)
class ScannerStatus:
    state: str
    adf_state: str | None = None

    @classmethod
    def from_xml(cls, data: bytes | str) -> ScannerStatus:
        root = ET.fromstring(data)
        adf = root.findtext("scan:AdfState", namespaces=NS)
        return cls(
            state=(root.findtext("pwg:State", default="Unknown", namespaces=NS)).strip(),
            adf_state=adf.strip() if adf else None,
        )

    @property
    def is_idle(self) -> bool:
        return self.state == "Idle"

    @property
    def adf_loaded(self) -> bool:
        return self.adf_state == "ScannerAdfLoaded"


@dataclass
class ScanSettings:
    """Protocol-neutral parameters for one scan job (eSCL vocabulary; LEDM translates).

    Dimensions and offsets are in 1/300ths of an inch (eSCL ``ThreeHundredthsOfInches``).
    """

    source: str = "Platen"
    color_mode: str = "RGB24"
    resolution: int = 300
    width: int = PAGE_SIZES["letter"][0]
    height: int = PAGE_SIZES["letter"][1]
    x_offset: int = 0
    y_offset: int = 0
    document_format: str = "image/jpeg"
    quality: int = 75
    """JPEG quality 1-100 (LEDM ``CompressionQFactor`` is ``100 - quality``)."""
    version: str = "2.0"
    extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 1 <= self.quality <= 100:
            raise ValueError(f"quality must be 1-100, got {self.quality}")

    @classmethod
    def for_page(cls, page: str, **kwargs: object) -> ScanSettings:
        try:
            width, height = PAGE_SIZES[page.lower()]
        except KeyError as exc:
            raise ValueError(
                f"Unknown page size {page!r}; choose one of {sorted(PAGE_SIZES)}"
            ) from exc
        return cls(width=width, height=height, **kwargs)  # type: ignore[arg-type]

    def to_xml(self) -> bytes:
        ET.register_namespace("scan", SCAN_NS)
        ET.register_namespace("pwg", PWG_NS)
        root = ET.Element(f"{{{SCAN_NS}}}ScanSettings")
        ET.SubElement(root, f"{{{PWG_NS}}}Version").text = self.version

        regions = ET.SubElement(root, f"{{{PWG_NS}}}ScanRegions")
        region = ET.SubElement(regions, f"{{{PWG_NS}}}ScanRegion")
        ET.SubElement(
            region, f"{{{PWG_NS}}}ContentRegionUnits"
        ).text = "escl:ThreeHundredthsOfInches"
        ET.SubElement(region, f"{{{PWG_NS}}}XOffset").text = str(self.x_offset)
        ET.SubElement(region, f"{{{PWG_NS}}}YOffset").text = str(self.y_offset)
        ET.SubElement(region, f"{{{PWG_NS}}}Width").text = str(self.width)
        ET.SubElement(region, f"{{{PWG_NS}}}Height").text = str(self.height)

        ET.SubElement(root, f"{{{PWG_NS}}}InputSource").text = self.source
        ET.SubElement(root, f"{{{SCAN_NS}}}ColorMode").text = self.color_mode
        ET.SubElement(root, f"{{{SCAN_NS}}}XResolution").text = str(self.resolution)
        ET.SubElement(root, f"{{{SCAN_NS}}}YResolution").text = str(self.resolution)
        ET.SubElement(root, f"{{{PWG_NS}}}DocumentFormat").text = self.document_format
        for tag, value in self.extra.items():
            ET.SubElement(root, f"{{{SCAN_NS}}}{tag}").text = value

        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
