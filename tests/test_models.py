import xml.etree.ElementTree as ET

import pytest

from hp_scanner.models import (
    NS,
    PAGE_SIZES,
    ScannerCapabilities,
    ScannerError,
    ScannerStatus,
    ScanSettings,
)


def test_capabilities_parse_real_device(capabilities_xml):
    caps = ScannerCapabilities.from_xml(capabilities_xml)

    assert caps.make_and_model == "Officejet 6700 Premium e-All-in-One"
    assert caps.version == "1.0"
    assert caps.formats == ("application/octet-stream", "image/jpeg")

    assert caps.platen is not None
    assert caps.platen.resolutions == (75, 100, 200, 300, 600, 1200, 2400)
    assert caps.platen.color_modes == ("Grayscale8", "RGB24")
    assert (caps.platen.max_width, caps.platen.max_height) == (2550, 3508)

    assert caps.adf is not None
    assert caps.adf.resolutions == (75, 100, 200, 300, 600)
    assert caps.adf.max_height == 4200
    assert caps.adf_capacity == 35


def test_capabilities_without_adf():
    xml = b"""<?xml version="1.0"?>
    <scan:ScannerCapabilities xmlns:scan="http://schemas.hp.com/imaging/escl/2011/02/08"
        xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">
      <pwg:Version>2.6</pwg:Version>
      <pwg:MakeAndModel>Test</pwg:MakeAndModel>
      <scan:Platen><scan:PlatenInputCaps>
        <scan:MinWidth>1</scan:MinWidth><scan:MaxWidth>100</scan:MaxWidth>
        <scan:MinHeight>1</scan:MinHeight><scan:MaxHeight>100</scan:MaxHeight>
      </scan:PlatenInputCaps></scan:Platen>
    </scan:ScannerCapabilities>"""
    caps = ScannerCapabilities.from_xml(xml)
    assert caps.adf is None
    assert caps.adf_capacity is None
    with pytest.raises(ScannerError, match="Feeder"):
        caps.input_caps("Feeder")


def test_status_parse(status_idle_xml):
    status = ScannerStatus.from_xml(status_idle_xml)
    assert status.state == "Idle"
    assert status.is_idle
    assert status.adf_state == "ScannerAdfEmpty"
    assert not status.adf_loaded


def test_validate_accepts_supported_settings(capabilities_xml):
    caps = ScannerCapabilities.from_xml(capabilities_xml)
    caps.validate(ScanSettings.for_page("letter", resolution=300, color_mode="RGB24"))
    caps.validate(ScanSettings.for_page("legal", source="Feeder", resolution=600))


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (ScanSettings(resolution=150), "Resolution 150"),
        (ScanSettings(source="Feeder", resolution=1200), "Resolution 1200"),
        (ScanSettings(color_mode="BlackAndWhite1"), "Color mode"),
        (ScanSettings(width=9999), "Width 9999"),
        (ScanSettings(height=4200), "Height 4200"),  # legal fits ADF but not platen
        (ScanSettings(document_format="application/pdf"), "Format"),
    ],
)
def test_validate_rejects_unsupported_settings(capabilities_xml, settings, message):
    caps = ScannerCapabilities.from_xml(capabilities_xml)
    with pytest.raises(ValueError, match=message):
        caps.validate(settings)


def test_for_page_sets_dimensions():
    s = ScanSettings.for_page("A4", resolution=200)
    assert (s.width, s.height) == PAGE_SIZES["a4"]
    assert s.resolution == 200


def test_for_page_unknown_size():
    with pytest.raises(ValueError, match="Unknown page size"):
        ScanSettings.for_page("tabloid")


def test_scan_settings_xml():
    settings = ScanSettings(
        source="Feeder",
        color_mode="Grayscale8",
        resolution=200,
        width=2550,
        height=4200,
        extra={"Brightness": "1000"},
    )
    data = settings.to_xml()
    assert data.startswith(b"<?xml")
    root = ET.fromstring(data)

    assert root.tag == "{http://schemas.hp.com/imaging/escl/2011/02/08}ScanSettings"
    assert root.findtext("pwg:Version", namespaces=NS) == "2.0"
    assert root.findtext("pwg:InputSource", namespaces=NS) == "Feeder"
    assert root.findtext("scan:ColorMode", namespaces=NS) == "Grayscale8"
    assert root.findtext("scan:XResolution", namespaces=NS) == "200"
    assert root.findtext("scan:YResolution", namespaces=NS) == "200"
    assert root.findtext("pwg:DocumentFormat", namespaces=NS) == "image/jpeg"
    assert root.findtext("scan:Brightness", namespaces=NS) == "1000"

    region = root.find("pwg:ScanRegions/pwg:ScanRegion", NS)
    assert region is not None
    assert region.findtext("pwg:ContentRegionUnits", namespaces=NS) == (
        "escl:ThreeHundredthsOfInches"
    )
    assert region.findtext("pwg:Width", namespaces=NS) == "2550"
    assert region.findtext("pwg:Height", namespaces=NS) == "4200"


def test_quality_range():
    assert ScanSettings(quality=1).quality == 1
    with pytest.raises(ValueError, match="quality"):
        ScanSettings(quality=0)
    with pytest.raises(ValueError, match="quality"):
        ScanSettings(quality=101)
