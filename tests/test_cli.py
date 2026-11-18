import json
from datetime import datetime
from pathlib import Path

import pytest
import responses
from conftest import FIXTURES, make_jpeg
from PIL import Image
from test_jpeg import adf_jpeg

from hp_scanner import __version__
from hp_scanner.cli import _infer_format, build_parser, main

BASE = "http://192.168.4.195:8080"
JOB = f"{BASE}/eSCL/ScanJobs/5"


@pytest.fixture
def mocked():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        yield rsps


@pytest.fixture
def scanner(mocked, capabilities_xml, status_idle_xml, jpeg_page):
    mocked.get(f"{BASE}/eSCL/ScannerCapabilities", body=capabilities_xml)
    mocked.get(f"{BASE}/eSCL/ScannerStatus", body=status_idle_xml)
    mocked.post(f"{BASE}/eSCL/ScanJobs", status=201, headers={"Location": JOB})
    mocked.get(f"{JOB}/NextDocument", body=jpeg_page, content_type="image/jpeg")
    mocked.get(f"{JOB}/NextDocument", status=404)
    mocked.delete(JOB)
    return mocked


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_host_flags_default_to_none_so_config_can_apply():
    args = build_parser().parse_args(["status"])
    assert (args.host, args.port, args.scheme) == (None, None, None)
    args = build_parser().parse_args(["--https", "--host", "h.local", "--port", "9", "status"])
    assert (args.host, args.port, args.scheme) == ("h.local", "9", "https")


def test_infer_format(tmp_path):
    assert _infer_format(tmp_path / "a.PNG", None) == "png"
    assert _infer_format(tmp_path / "a.jpg", None) == "jpeg"
    assert _infer_format(tmp_path / "a.pdf", None) == "pdf"
    assert _infer_format(tmp_path / "a.tiff", "png") == "png"
    with pytest.raises(SystemExit, match="Cannot infer format"):
        _infer_format(tmp_path / "a.tiff", None)


def test_status_command(mocked, status_idle_xml, capsys):
    mocked.get(f"{BASE}/eSCL/ScannerStatus", body=status_idle_xml)
    assert main(["--protocol", "escl", "--host", "192.168.4.195", "status"]) == 0
    out = capsys.readouterr().out
    assert "State:     Idle" in out
    assert "ScannerAdfEmpty" in out


def test_capabilities_command(mocked, capabilities_xml, capsys):
    mocked.get(f"{BASE}/eSCL/ScannerCapabilities", body=capabilities_xml)
    assert main(["--protocol", "escl", "capabilities"]) == 0
    out = capsys.readouterr().out
    assert "Officejet 6700" in out
    assert "Platen:" in out and "ADF:" in out
    assert "75, 100, 200, 300, 600, 1200, 2400 dpi" in out
    assert "Protocol: 1.0" in out
    assert "Capacity:    35 sheets" in out


def test_scan_png_color(scanner, tmp_path, capsys):
    out = tmp_path / "photo.png"
    assert main(["--protocol", "escl", "scan", str(out), "-r", "600"]) == 0
    assert out.exists()
    assert capsys.readouterr().out.strip() == str(out)

    post = next(c for c in scanner.calls if c.request.method == "POST")
    assert b"<scan:ColorMode>RGB24</scan:ColorMode>" in post.request.body
    assert b"<scan:XResolution>600</scan:XResolution>" in post.request.body


def test_scan_pdf_defaults_to_gray(scanner, tmp_path):
    out = tmp_path / "doc.pdf"
    assert main(["--protocol", "escl", "scan", str(out), "--page", "a4"]) == 0
    assert out.read_bytes().startswith(b"%PDF")

    post = next(c for c in scanner.calls if c.request.method == "POST")
    assert b"<scan:ColorMode>Grayscale8</scan:ColorMode>" in post.request.body
    assert b"<pwg:Width>2480</pwg:Width>" in post.request.body


def test_scan_explicit_format_and_mode(scanner, tmp_path):
    out = tmp_path / "scan.bin"
    assert main(["--protocol", "escl", "scan", str(out), "--format", "pdf", "--mode", "color"]) == 0
    assert out.read_bytes().startswith(b"%PDF")
    post = next(c for c in scanner.calls if c.request.method == "POST")
    assert b"RGB24" in post.request.body


def test_scan_rejects_unsupported_resolution(scanner, tmp_path, capsys):
    assert main(["--protocol", "escl", "scan", str(tmp_path / "x.png"), "-r", "150"]) == 1
    assert "Resolution 150" in capsys.readouterr().err
    assert not any(c.request.method == "POST" for c in scanner.calls)


def test_scan_no_validate_skips_capabilities(scanner, tmp_path):
    assert main(["--protocol", "escl", "scan", str(tmp_path / "x.png"), "--no-validate"]) == 0
    assert not any("ScannerCapabilities" in c.request.url for c in scanner.calls)


def test_scan_adf_empty_reports_error(scanner, tmp_path, capsys):
    assert main(["--protocol", "escl", "scan", str(tmp_path / "x.pdf"), "--source", "adf"]) == 1
    assert "ADF is empty" in capsys.readouterr().err


def test_scanner_unreachable_reports_error(mocked, tmp_path, capsys):
    assert main(["--protocol", "escl", "--host", "192.168.4.195", "status"]) == 1
    assert "error:" in capsys.readouterr().err


def test_auto_protocol_prefers_ledm(mocked, capsys):
    mocked.get(f"{BASE}/Scan/Status", body=(FIXTURES / "ledm_status_idle.xml").read_bytes())
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Protocol:  ledm" in out
    assert "State:     Idle" in out
    assert "ScannerAdfEmpty" in out


def test_auto_protocol_falls_back_to_escl(mocked, status_idle_xml, capsys):
    mocked.get(f"{BASE}/Scan/Status", status=404)
    mocked.get(f"{BASE}/eSCL/ScannerStatus", body=status_idle_xml)
    assert main(["status"]) == 0
    assert "Protocol:  escl" in capsys.readouterr().out


def test_ledm_scan_pdf(mocked, jpeg_page, tmp_path):
    job = f"{BASE}/Jobs/JobList/1"
    mocked.get(f"{BASE}/Scan/Status", body=(FIXTURES / "ledm_status_idle.xml").read_bytes())
    mocked.get(f"{BASE}/Scan/ScanCaps", body=(FIXTURES / "ledm_scancaps.xml").read_bytes())
    mocked.post(f"{BASE}/Scan/Jobs", status=201, headers={"Location": "/Jobs/JobList/1"})
    mocked.get(job, body=(FIXTURES / "ledm_job_ready.xml").read_bytes())
    mocked.get(f"{BASE}/Scan/Jobs/1/Pages/1", body=jpeg_page, content_type="image/jpeg")
    mocked.get(job, body=(FIXTURES / "ledm_job_completed.xml").read_bytes())

    out = tmp_path / "doc.pdf"
    assert main(["--protocol", "ledm", "scan", str(out)]) == 0
    assert out.read_bytes().startswith(b"%PDF")
    post = next(c for c in mocked.calls if c.request.method == "POST")
    assert b"<scan:ColorSpace>Gray</scan:ColorSpace>" in post.request.body
    assert b"<scan:InputSource>Platen</scan:InputSource>" in post.request.body
    assert b"<scan:Format>Jpeg</scan:Format>" in post.request.body


def test_ledm_native_pdf_and_quality(mocked, tmp_path):
    job = f"{BASE}/Jobs/JobList/1"
    pdf = b"%PDF-1.4\n%fake device pdf\n%%EOF"
    mocked.get(f"{BASE}/Scan/Status", body=(FIXTURES / "ledm_status_idle.xml").read_bytes())
    mocked.get(f"{BASE}/Scan/ScanCaps", body=(FIXTURES / "ledm_scancaps.xml").read_bytes())
    mocked.post(f"{BASE}/Scan/Jobs", status=201, headers={"Location": "/Jobs/JobList/1"})
    mocked.get(job, body=(FIXTURES / "ledm_job_ready.xml").read_bytes())
    mocked.get(f"{BASE}/Scan/Jobs/1/Pages/1", body=pdf, content_type="application/pdf")
    mocked.get(job, body=(FIXTURES / "ledm_job_completed.xml").read_bytes())

    out = tmp_path / "doc.pdf"
    assert main(["--protocol", "ledm", "scan", str(out), "--native-pdf", "-q", "90"]) == 0
    assert out.read_bytes() == pdf
    post = next(c for c in mocked.calls if c.request.method == "POST")
    assert b"<scan:Format>Pdf</scan:Format>" in post.request.body
    assert b"<scan:CompressionQFactor>10</scan:CompressionQFactor>" in post.request.body


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_config_shows_defaults(home, capsys):
    assert main(["config"]) == 0
    out = capsys.readouterr().out
    assert f"Config file: {home / '.config' / 'hpscan' / 'config.json'}" in out
    assert f"Destination: {home / 'Documents' / 'HP_Scans'}  (default)" in out
    assert "Host:        192.168.4.195  (default)" in out
    assert "Scanner URL: http://192.168.4.195:8080/" in out
    assert not (home / ".config").exists()


@pytest.mark.parametrize("flag", ["--dest", "--destination"])
def test_config_sets_destination(home, capsys, flag):
    assert main(["config", flag, "~/Scans"]) == 0
    assert f"Destination: {home / 'Scans'}  (config)\n" in capsys.readouterr().out
    saved = (home / ".config" / "hpscan" / "config.json").read_text()
    assert str(home / "Scans") in saved


def test_config_rejects_file_destination(home, capsys):
    home.mkdir()
    (home / "f").write_text("x")
    assert main(["config", "--dest", str(home / "f")]) == 1
    assert "not a directory" in capsys.readouterr().err


def test_bad_config_file_reports_error(home, capsys):
    cfg = home / ".config" / "hpscan" / "config.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("{oops")
    assert main(["config"]) == 1
    assert "Invalid JSON" in capsys.readouterr().err


def test_scan_without_output_uses_default_destination(scanner, home, capsys):
    assert main(["--protocol", "escl", "scan"]) == 0
    written = Path(capsys.readouterr().out.strip())
    month_dir = home / "Documents" / "HP_Scans" / f"{datetime.now():%Y}" / f"{datetime.now():%m}"
    assert written.parent == month_dir
    assert written.name.startswith("document-1-") and written.suffix == ".pdf"
    assert written.read_bytes().startswith(b"%PDF")


def test_scan_without_output_uses_configured_destination(scanner, home, capsys):
    assert main(["config", "--dest", str(home / "custom")]) == 0
    capsys.readouterr()
    assert main(["--protocol", "escl", "scan", "--format", "png"]) == 0
    written = Path(capsys.readouterr().out.strip())
    assert written.is_relative_to(home / "custom")
    assert written.name.startswith("image-1-") and written.suffix == ".png"


def test_failed_scan_creates_no_directories(scanner, home):
    assert main(["--protocol", "escl", "scan", "-r", "150"]) == 1
    assert not (home / "Documents").exists()


def test_scan_explicit_output_creates_parent_dirs(scanner, tmp_path):
    out = tmp_path / "a" / "b" / "x.png"
    assert main(["--protocol", "escl", "scan", str(out)]) == 0
    assert out.exists()


def _cfg(home):
    return json.loads((home / ".config" / "hpscan" / "config.json").read_text())


def test_config_saves_connection_settings(home, capsys):
    assert (
        main(["config", "--host", "HP101F743EF639.local", "--scheme", "https", "--port", "8443"])
        == 0
    )
    assert _cfg(home) == {
        "destination": None,
        "host": "HP101F743EF639.local",
        "scheme": "https",
        "port": 8443,
    }
    out = capsys.readouterr().out
    assert "Host:        HP101F743EF639.local  (config)" in out
    assert "Scanner URL: https://HP101F743EF639.local:8443/" in out


def test_config_show_reports_sources(home, capsys, monkeypatch):
    main(["config", "--host", "10.0.0.5"])
    monkeypatch.setenv("HP_SCANNER_PORT", "81")
    capsys.readouterr()
    assert main(["--https", "config", "--show"]) == 0
    out = capsys.readouterr().out
    assert "Host:        10.0.0.5  (config)" in out
    assert "Scheme:      https  (command line)" in out
    assert "Port:        81  (env HP_SCANNER_PORT)" in out


def test_config_https_without_port_defaults_to_443(home, capsys):
    assert main(["config", "--scheme", "https", "--show"]) == 0
    assert "Port:        443  (default)" in capsys.readouterr().out


def test_config_unset_restores_default(home, capsys):
    main(["config", "--host", "10.0.0.5", "--scheme", "https"])
    assert main(["config", "--unset", "host", "--unset", "scheme"]) == 0
    assert _cfg(home)["host"] is None and _cfg(home)["scheme"] is None
    assert "Host:        192.168.4.195  (default)" in capsys.readouterr().out


def test_config_show_alone_does_not_write(home):
    assert main(["config", "--show"]) == 0
    assert not (home / ".config").exists()


@pytest.mark.parametrize(
    ("args", "msg"),
    [
        (["--host", "http://10.0.0.5"], "must not include a scheme"),
        (["--host", "bad host"], "Invalid host"),
        (["--host", "10.0.0.5:8080"], "Invalid host"),
        (["--port", "70000"], "Invalid port"),
        (["--port", "abc"], "Invalid port"),
    ],
)
def test_config_rejects_bad_values(home, capsys, args, msg):
    assert main(["config", *args]) == 1
    assert msg in capsys.readouterr().err
    assert not (home / ".config").exists()


def test_bad_scheme_rejected_by_parser(home):
    with pytest.raises(SystemExit):
        main(["config", "--scheme", "ftp"])


def test_scan_uses_configured_scanner(home, mocked, capabilities_xml, status_idle_xml, jpeg_page):
    other = "https://scanner.local:8443"
    job = f"{other}/eSCL/ScanJobs/5"
    mocked.get(f"{other}/eSCL/ScannerCapabilities", body=capabilities_xml)
    mocked.get(f"{other}/eSCL/ScannerStatus", body=status_idle_xml)
    mocked.post(f"{other}/eSCL/ScanJobs", status=201, headers={"Location": job})
    mocked.get(f"{job}/NextDocument", body=jpeg_page, content_type="image/jpeg")
    mocked.get(f"{job}/NextDocument", status=404)
    mocked.delete(job)
    main(["config", "--host", "scanner.local", "--scheme", "https", "--port", "8443"])
    assert main(["--protocol", "escl", "scan"]) == 0
    assert all(c.request.url.startswith(other) for c in mocked.calls)


def test_cli_flag_overrides_config_and_env(home, mocked, status_idle_xml, monkeypatch):
    main(["config", "--host", "10.9.9.9", "--scheme", "https"])
    monkeypatch.setenv("HP_SCANNER_HOST", "10.8.8.8")
    mocked.get(f"{BASE}/eSCL/ScannerStatus", body=status_idle_xml)
    assert main(["--protocol", "escl", "--http", "--host", "192.168.4.195", "status"]) == 0


def test_env_overrides_config(home, mocked, status_idle_xml, monkeypatch):
    main(["config", "--host", "10.9.9.9"])
    monkeypatch.setenv("HP_SCANNER_HOST", "192.168.4.195")
    mocked.get(f"{BASE}/eSCL/ScannerStatus", body=status_idle_xml)
    assert main(["--protocol", "escl", "status"]) == 0


def test_bad_env_port_reports_source(home, capsys, monkeypatch):
    monkeypatch.setenv("HP_SCANNER_PORT", "nope")
    assert main(["status"]) == 1
    assert "(from env HP_SCANNER_PORT)" in capsys.readouterr().err


def _posted(mocked):
    return next(c for c in mocked.calls if c.request.method == "POST").request.body


def _month_dir(home):
    now = datetime.now()
    return home / "Documents" / "HP_Scans" / f"{now:%Y}" / f"{now:%m}"


def test_bare_hpscan_prompts_and_uses_defaults(scanner, home, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda q: "")
    assert main(["--protocol", "escl"], interactive=True) == 0
    written = Path(capsys.readouterr().out.strip())
    assert written.parent == _month_dir(home)
    assert written.name.startswith("document-1-") and written.suffix == ".pdf"
    body = _posted(scanner)
    assert b"<scan:XResolution>200</scan:XResolution>" in body  # medium
    assert b"Grayscale8" in body


def test_bare_hpscan_prompt_answers(scanner, home, capsys, monkeypatch):
    replies = iter(["png", "high", "photos"])
    monkeypatch.setattr("builtins.input", lambda q: next(replies))
    assert main(["--protocol", "escl"], interactive=True) == 0
    written = Path(capsys.readouterr().out.strip())
    assert written.name.startswith("photos-image-1-") and written.suffix == ".png"
    body = _posted(scanner)
    assert b"<scan:XResolution>300</scan:XResolution>" in body
    assert b"RGB24" in body


def test_bare_hpscan_without_terminal_uses_defaults(scanner, home, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda q: pytest.fail("must not prompt"))
    assert main(["--protocol", "escl"], interactive=False) == 0
    captured = capsys.readouterr()
    assert "using defaults" in captured.err
    assert Path(captured.out.strip()).name.startswith("document-1-")


@pytest.mark.parametrize(
    ("argv", "name_start", "suffix", "dpi"),
    [
        (["--type", "jpg"], "image-1-", ".jpg", 200),
        (["-t", "png", "-q", "low"], "image-1-", ".png", 100),
        (["--quality", "high"], "document-1-", ".pdf", 300),
        (["--prefix", "bleh"], "bleh-document-1-", ".pdf", 200),
        (
            ["--type", "pdf", "--quality", "medium", "--prefix", "bleh"],
            "bleh-document-1-",
            ".pdf",
            200,
        ),
    ],
)
def test_quick_scan_flags_skip_prompt(
    scanner, home, capsys, monkeypatch, argv, name_start, suffix, dpi
):
    monkeypatch.setattr("builtins.input", lambda q: pytest.fail("must not prompt"))
    assert main(["--protocol", "escl", *argv], interactive=True) == 0
    written = Path(capsys.readouterr().out.strip())
    assert written.name.startswith(name_start) and written.suffix == suffix
    assert f"<scan:XResolution>{dpi}</scan:XResolution>".encode() in _posted(scanner)


def test_quick_scan_uses_configured_destination(scanner, home, capsys):
    main(["config", "--dest", str(home / "out")])
    capsys.readouterr()
    assert main(["--protocol", "escl", "--type", "png"], interactive=False) == 0
    assert Path(capsys.readouterr().out.strip()).is_relative_to(home / "out")


@pytest.mark.parametrize(
    ("argv", "msg"),
    [
        (["--type", "tiff"], "Invalid type"),
        (["--quality", "ultra"], "Invalid quality"),
        (["--prefix", "../x"], "Invalid prefix"),
        (["--type", "pdf", "status"], "quick scans"),
    ],
)
def test_quick_scan_bad_flags(home, capsys, argv, msg):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    assert msg in capsys.readouterr().err


def test_prompt_happens_before_contacting_scanner(mocked, home, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda q: (_ for _ in ()).throw(KeyboardInterrupt))
    assert main(["--protocol", "escl"], interactive=True) == 130
    assert not mocked.calls
    assert "cancelled" in capsys.readouterr().err


def test_scan_subcommand_prefix_and_type(scanner, home, capsys):
    assert main(["--protocol", "escl", "scan", "--type", "jpg", "--prefix", "bleh"]) == 0
    written = Path(capsys.readouterr().out.strip())
    assert written.name.startswith("bleh-image-1-") and written.suffix == ".jpg"


@pytest.mark.parametrize(("extra", "dpi"), [([], 100), (["-r", "600"], 600)])
def test_scan_subcommand_quality_preset_sets_dpi_unless_overridden(scanner, home, extra, dpi):
    assert main(["--protocol", "escl", "scan", "-q", "low", *extra]) == 0
    assert f"<scan:XResolution>{dpi}</scan:XResolution>".encode() in _posted(scanner)


def test_scan_subcommand_numeric_quality_keeps_300_dpi(mocked, home, tmp_path):
    job = f"{BASE}/Jobs/JobList/1"
    mocked.get(f"{BASE}/Scan/Status", body=(FIXTURES / "ledm_status_idle.xml").read_bytes())
    mocked.get(f"{BASE}/Scan/ScanCaps", body=(FIXTURES / "ledm_scancaps.xml").read_bytes())
    mocked.post(f"{BASE}/Scan/Jobs", status=201, headers={"Location": "/Jobs/JobList/1"})
    mocked.get(job, body=(FIXTURES / "ledm_job_ready.xml").read_bytes())
    mocked.get(f"{BASE}/Scan/Jobs/1/Pages/1", body=make_jpeg(), content_type="image/jpeg")
    mocked.get(job, body=(FIXTURES / "ledm_job_completed.xml").read_bytes())
    assert main(["--protocol", "ledm", "scan", str(tmp_path / "x.pdf"), "-q", "high"]) == 0
    body = _posted(mocked)
    assert b"<scan:CompressionQFactor>10</scan:CompressionQFactor>" in body
    assert b"<scan:XResolution>300</scan:XResolution>" in body


def test_scan_subcommand_prefix_with_output_is_error(scanner, home, tmp_path, capsys):
    assert main(["--protocol", "escl", "scan", str(tmp_path / "x.pdf"), "--prefix", "a"]) == 1
    assert "--prefix only applies" in capsys.readouterr().err


def _ledm_scanner(mocked, status_fixture):
    job = f"{BASE}/Jobs/JobList/1"
    mocked.get(f"{BASE}/Scan/Status", body=(FIXTURES / status_fixture).read_bytes())
    mocked.get(f"{BASE}/Scan/ScanCaps", body=(FIXTURES / "ledm_scancaps.xml").read_bytes())
    mocked.post(f"{BASE}/Scan/Jobs", status=201, headers={"Location": "/Jobs/JobList/1"})
    mocked.get(job, body=(FIXTURES / "ledm_job_ready.xml").read_bytes())
    mocked.get(f"{BASE}/Scan/Jobs/1/Pages/1", body=make_jpeg(), content_type="image/jpeg")
    mocked.get(job, body=(FIXTURES / "ledm_job_completed.xml").read_bytes())
    return mocked


@pytest.mark.parametrize(
    ("status_fixture", "source", "why"),
    [
        ("ledm_status_adf_loaded.xml", b"Adf", "adf (auto: paper in feeder)"),
        ("ledm_status_idle.xml", b"Platen", "platen (auto: feeder empty)"),
    ],
)
def test_quick_scan_auto_picks_feeder_when_loaded(
    mocked, home, capsys, status_fixture, source, why
):
    _ledm_scanner(mocked, status_fixture)
    assert main(["--protocol", "ledm", "--type", "pdf"], interactive=False) == 0
    assert f"<scan:InputSource>{source.decode()}</scan:InputSource>".encode() in _posted(mocked)
    assert f"Scanning {why}" in capsys.readouterr().err


def test_bare_hpscan_prompt_uses_feeder_when_loaded(mocked, home, monkeypatch):
    _ledm_scanner(mocked, "ledm_status_adf_loaded.xml")
    monkeypatch.setattr("builtins.input", lambda q: "")
    assert main(["--protocol", "ledm"], interactive=True) == 0
    assert b"<scan:InputSource>Adf</scan:InputSource>" in _posted(mocked)


@pytest.mark.parametrize(
    ("flag", "source"), [("platen", b"Platen"), ("auto", b"Adf"), (None, b"Adf")]
)
def test_scan_subcommand_source(mocked, home, tmp_path, flag, source):
    _ledm_scanner(mocked, "ledm_status_adf_loaded.xml")
    extra = ["--source", flag] if flag else []
    assert main(["--protocol", "ledm", "scan", str(tmp_path / "x.pdf"), *extra]) == 0
    assert f"<scan:InputSource>{source.decode()}</scan:InputSource>".encode() in _posted(mocked)


def test_feeder_scan_is_letter_by_default(mocked, home):
    _ledm_scanner(mocked, "ledm_status_adf_loaded.xml")
    assert main(["--protocol", "ledm"], interactive=False) == 0
    body = _posted(mocked)
    assert b"<scan:InputSource>Adf</scan:InputSource>" in body
    assert b"<scan:Width>2550</scan:Width>" in body  # letter: 8.5 x 11 in at 1/300 in
    assert b"<scan:Height>3300</scan:Height>" in body


def test_feeder_pages_with_dnl_are_saved(mocked, home, capsys):
    _ledm_scanner(mocked, "ledm_status_adf_loaded.xml")
    page = f"{BASE}/Scan/Jobs/1/Pages/1"
    mocked.replace(responses.GET, page, body=adf_jpeg(real_height=48), content_type="image/jpeg")
    assert main(["--protocol", "ledm", "--type", "png"], interactive=False) == 0
    assert Image.open(Path(capsys.readouterr().out.strip())).size == (64, 48)


def test_unconvertible_scan_keeps_raw_pages(mocked, home, capsys):
    _ledm_scanner(mocked, "ledm_status_adf_loaded.xml")
    page = f"{BASE}/Scan/Jobs/1/Pages/1"
    mocked.replace(responses.GET, page, body=b"\xff\xd8garbage", content_type="image/jpeg")
    assert main(["--protocol", "ledm"], interactive=False) == 1
    err = capsys.readouterr().err
    assert "raw pages saved" in err
    raw = next((home / "Documents" / "HP_Scans").rglob("*-raw-1.jpg"))
    assert raw.read_bytes() == b"\xff\xd8garbage"
