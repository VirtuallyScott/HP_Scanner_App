"""User configuration stored in ``~/.config/hpscan/config.json``.

Connection settings resolve in this order: command-line flag → environment variable →
config file → built-in default (see :func:`resolve_connection`).
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path

from .escl import DEFAULT_HOST, DEFAULT_PORT

CONFIG_FILENAME = "config.json"
SCHEMES = ("http", "https")
DEFAULT_SCHEME = "http"
DEFAULT_HTTPS_PORT = 443
MAX_PORT = 65535
ENV_HOST = "HP_SCANNER_HOST"
ENV_PORT = "HP_SCANNER_PORT"
ENV_SCHEME = "HP_SCANNER_SCHEME"

_HOST_LABEL = r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
_HOSTNAME = re.compile(rf"^{_HOST_LABEL}(?:\.{_HOST_LABEL})*\.?$")
_MAX_HOSTNAME = 253


def config_dir() -> Path:
    """Directory holding hpscan configuration (``$HOME/.config/hpscan``)."""
    return Path.home() / ".config" / "hpscan"


def config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


def default_destination() -> Path:
    """Default scan root (``$HOME/Documents/HP_Scans``)."""
    return Path.home() / "Documents" / "HP_Scans"


def expand_path(raw: str | os.PathLike[str]) -> Path:
    """Expand ``~`` and ``$VARS`` and make the path absolute."""
    text = os.path.expandvars(os.path.expanduser(os.fspath(raw)))
    if not text.strip():
        raise ValueError("Destination path must not be empty")
    return Path(text).resolve()


def normalize_host(raw: str) -> str:
    """Validate an IPv4/IPv6 address, hostname or Bonjour ``.local`` name.

    IPv6 addresses come back in brackets so they can go straight into a URL.
    """
    text = str(raw).strip()
    if "://" in text:
        raise ValueError(f"Host {text!r} must not include a scheme; set it with --scheme")
    inner = text[1:-1] if text.startswith("[") and text.endswith("]") else text
    try:
        ip = ipaddress.ip_address(inner)
    except ValueError:
        ip = None
    if ip is not None:
        return f"[{ip}]" if ip.version == 6 else str(ip)
    if len(text) > _MAX_HOSTNAME or not _HOSTNAME.match(text):
        raise ValueError(
            f"Invalid host {text!r}: use an IP address, hostname or Bonjour name "
            "(e.g. 192.168.4.195, scanner.lan, HP101F743EF639.local); set the port with --port"
        )
    return text.rstrip(".")


def normalize_scheme(raw: str) -> str:
    scheme = str(raw).strip().lower()
    if scheme not in SCHEMES:
        raise ValueError(f"Invalid scheme {raw!r}; choose one of {', '.join(SCHEMES)}")
    return scheme


def normalize_port(raw: int | str) -> int:
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid port {raw!r}; expected a number 1-{MAX_PORT}") from None
    if isinstance(raw, bool) or not 1 <= port <= MAX_PORT:
        raise ValueError(f"Invalid port {raw!r}; expected a number 1-{MAX_PORT}")
    return port


def default_port(scheme: str) -> int:
    return DEFAULT_HTTPS_PORT if scheme == "https" else DEFAULT_PORT


@dataclass(frozen=True)
class Config:
    """Persisted hpscan settings. ``None`` means "use the default"."""

    destination: Path | None = None
    host: str | None = None
    scheme: str | None = None
    port: int | None = None

    @property
    def scan_root(self) -> Path:
        return self.destination or default_destination()

    def with_destination(self, raw: str | os.PathLike[str]) -> Config:
        dest = expand_path(raw)
        if dest.exists() and not dest.is_dir():
            raise ValueError(f"Destination {dest} exists and is not a directory")
        return replace(self, destination=dest)

    def with_host(self, raw: str) -> Config:
        return replace(self, host=normalize_host(raw))

    def with_scheme(self, raw: str) -> Config:
        return replace(self, scheme=normalize_scheme(raw))

    def with_port(self, raw: int | str) -> Config:
        return replace(self, port=normalize_port(raw))

    def without(self, *keys: str) -> Config:
        """Copy with ``keys`` reset to their defaults."""
        unknown = set(keys) - set(CONFIG_KEYS)
        if unknown:
            raise ValueError(f"Unknown config key(s): {', '.join(sorted(unknown))}")
        return replace(self, **dict.fromkeys(keys))

    def to_dict(self) -> dict[str, object]:
        return {
            "destination": str(self.destination) if self.destination else None,
            "host": self.host,
            "scheme": self.scheme,
            "port": self.port,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2) + "\n"

    @classmethod
    def from_dict(cls, data: object) -> Config:
        if not isinstance(data, dict):
            raise ValueError("Config must be a JSON object")
        config = cls()
        for key, apply in _LOADERS.items():
            value = data.get(key)
            if value is None:
                continue
            if key != "port" and not isinstance(value, str):
                raise ValueError(f"Config {key!r} must be a string")
            config = apply(config, value)
        return config


CONFIG_KEYS = tuple(f.name for f in fields(Config))
_LOADERS = {
    "destination": Config.with_destination,
    "host": Config.with_host,
    "scheme": Config.with_scheme,
    "port": Config.with_port,
}


def load_config(path: Path | None = None) -> Config:
    """Read the config file; a missing file yields defaults."""
    path = path or config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config()
    except OSError as exc:
        raise ValueError(f"Cannot read config {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config {path}: {exc}") from exc
    try:
        return Config.from_dict(data)
    except ValueError as exc:
        raise ValueError(f"Invalid config {path}: {exc}") from exc


def save_config(config: Config, path: Path | None = None) -> Path:
    """Write ``config`` to disk, creating the config directory if needed."""
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(config.to_json(), encoding="utf-8")
    tmp.replace(path)
    return path


@dataclass(frozen=True)
class Setting:
    """A resolved value plus where it came from (for ``hpscan config --show``)."""

    value: object
    source: str


@dataclass(frozen=True)
class Connection:
    host: Setting
    scheme: Setting
    port: Setting


def _pick(cli: object, env_name: str, env: Mapping[str, str], stored: object) -> Setting | None:
    if cli is not None:
        return Setting(cli, "command line")
    if env.get(env_name):
        return Setting(env[env_name], f"env {env_name}")
    if stored is not None:
        return Setting(stored, "config")
    return None


def _resolve(
    raw: Setting | None, normalize: Callable[[object], object], default: object
) -> Setting:
    if raw is None:
        return Setting(default, "default")
    try:
        return Setting(normalize(raw.value), raw.source)
    except ValueError as exc:
        raise ValueError(f"{exc} (from {raw.source})") from None


def resolve_connection(
    config: Config,
    host: str | None = None,
    scheme: str | None = None,
    port: int | str | None = None,
    env: Mapping[str, str] | None = None,
) -> Connection:
    """Combine CLI flags, environment and config into the scanner address to use."""
    env = os.environ if env is None else env
    scheme_s = _resolve(
        _pick(scheme, ENV_SCHEME, env, config.scheme), normalize_scheme, DEFAULT_SCHEME
    )
    host_s = _resolve(_pick(host, ENV_HOST, env, config.host), normalize_host, DEFAULT_HOST)
    port_s = _resolve(
        _pick(port, ENV_PORT, env, config.port), normalize_port, default_port(scheme_s.value)
    )
    return Connection(host=host_s, scheme=scheme_s, port=port_s)
