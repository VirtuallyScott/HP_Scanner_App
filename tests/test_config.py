import json
from pathlib import Path

import pytest

from hp_scanner.config import (
    Config,
    config_path,
    default_destination,
    expand_path,
    load_config,
    normalize_host,
    normalize_port,
    normalize_scheme,
    resolve_connection,
    save_config,
)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_paths_live_under_home(home):
    assert config_path() == home / ".config" / "hpscan" / "config.json"
    assert default_destination() == home / "Documents" / "HP_Scans"


def test_missing_config_uses_defaults(home):
    config = load_config()
    assert config == Config()
    assert config.scan_root == home / "Documents" / "HP_Scans"


def test_save_creates_dir_and_roundtrips(home):
    config = Config().with_destination(home / "scans")
    path = save_config(config)
    assert path == config_path() and path.exists()
    assert json.loads(path.read_text()) == {
        "destination": str(home / "scans"),
        "host": None,
        "scheme": None,
        "port": None,
    }
    assert load_config() == config
    assert load_config().scan_root == home / "scans"


def test_with_destination_returns_new_object(home):
    original = Config()
    updated = original.with_destination("~/x")
    assert original.destination is None
    assert updated.destination == home / "x"


def test_expand_path_handles_tilde_and_vars(home, monkeypatch):
    monkeypatch.setenv("SCANS", "stuff")
    assert expand_path("~/a") == home / "a"
    assert expand_path("${HOME}/$SCANS") == home / "stuff"
    with pytest.raises(ValueError, match="empty"):
        expand_path("  ")


def test_destination_that_is_a_file_is_rejected(home):
    f = home / "file.txt"
    f.write_text("x")
    with pytest.raises(ValueError, match="not a directory"):
        Config().with_destination(f)


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("{not json", "Invalid JSON"),
        ("[1]", "JSON object"),
        ('{"destination": 5}', "string"),
        ('{"host": "a b"}', "Invalid host"),
        ('{"scheme": "ftp"}', "Invalid scheme"),
        ('{"port": 0}', "Invalid port"),
        ('{"port": true}', "Invalid port"),
    ],
)
def test_bad_config_raises_value_error(content, match):
    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text(content)
    with pytest.raises(ValueError, match=match):
        load_config()


def test_null_destination_means_default(home):
    path = config_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"destination": null}')
    assert load_config().scan_root == Path(home) / "Documents" / "HP_Scans"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("192.168.4.195", "192.168.4.195"),
        (" HPE8FCCW ", "HPE8FCCW"),
        ("HP101F743EF639.local", "HP101F743EF639.local"),
        ("HP101F743EF639.local.", "HP101F743EF639.local"),
        ("printer.example.com", "printer.example.com"),
        ("fe80::1", "[fe80::1]"),
        ("[2001:db8::5]", "[2001:db8::5]"),
    ],
)
def test_normalize_host_accepts_ip_hostname_bonjour(raw, expected):
    assert normalize_host(raw) == expected


@pytest.mark.parametrize("raw", ["", "a b", "-bad.local", "host:80", "https://x", "a" * 64])
def test_normalize_host_rejects(raw):
    with pytest.raises(ValueError):
        normalize_host(raw)


def test_normalize_scheme_and_port():
    assert normalize_scheme(" HTTPS ") == "https"
    assert normalize_port("8080") == 8080
    for bad in ("0", "65536", "x"):
        with pytest.raises(ValueError):
            normalize_port(bad)


def test_resolve_connection_precedence():
    config = Config(host="10.0.0.1", scheme="https", port=9000)
    env = {"HP_SCANNER_HOST": "10.0.0.2", "HP_SCANNER_SCHEME": "http"}
    conn = resolve_connection(config, host="10.0.0.3", env=env)
    assert (conn.host.value, conn.host.source) == ("10.0.0.3", "command line")
    assert (conn.scheme.value, conn.scheme.source) == ("http", "env HP_SCANNER_SCHEME")
    assert (conn.port.value, conn.port.source) == (9000, "config")


def test_resolve_connection_defaults_depend_on_scheme():
    conn = resolve_connection(Config(), env={})
    assert (conn.host.value, conn.scheme.value, conn.port.value) == ("192.168.4.195", "http", 8080)
    assert resolve_connection(Config(scheme="https"), env={}).port.value == 443


def test_without_resets_keys_and_rejects_unknown():
    config = Config(host="h", port=1)
    assert config.without("host") == Config(port=1)
    with pytest.raises(ValueError, match="Unknown"):
        config.without("nope")
