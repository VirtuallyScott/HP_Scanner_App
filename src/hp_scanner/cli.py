"""``hpscan`` command-line interface."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .client import PROTOCOLS, ScannerClient, connect
from .config import (
    CONFIG_KEYS,
    DEFAULT_HTTPS_PORT,
    ENV_HOST,
    ENV_PORT,
    ENV_SCHEME,
    SCHEMES,
    Config,
    Connection,
    config_path,
    load_config,
    resolve_connection,
    save_config,
)
from .escl import DEFAULT_HOST, DEFAULT_PORT
from .models import COLOR_MODES, PAGE_SIZES, SOURCES, ScannerError, ScanSettings
from .naming import auto_output_path, normalize_prefix
from .output import save_pages
from .presets import (
    DEFAULT_QUALITY,
    DEFAULT_TYPE,
    OUTPUT_TYPES,
    QUALITY_PRESETS,
    QualityPreset,
    normalize_type,
    parse_quality,
    quality_preset,
)
from .prompt import QuickChoices, prompt_choices

DEFAULT_MODES = {"png": "color", "jpeg": "color", "pdf": "gray"}
AUTO_SOURCE = "auto"
DEFAULT_RESOLUTION = 300
DEFAULT_JPEG_QUALITY = 75
EXIT_INTERRUPTED = 130
QUICK_FLAGS = ("quick_type", "quick_quality", "quick_prefix")


@dataclass(frozen=True)
class ScanJob:
    """Everything ``cmd_scan`` needs, independent of which CLI form built it."""

    fmt: str
    mode: str
    resolution: int
    quality: int
    source: str = AUTO_SOURCE  # "auto" | "platen" | "adf"; auto is resolved in cmd_scan
    page: str = "letter"
    native_pdf: bool = False
    validate: bool = True
    output: Path | None = None
    prefix: str | None = None


def _type_arg(raw: str) -> str:
    try:
        return normalize_type(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _quality_arg(raw: str) -> QualityPreset | int:
    try:
        return parse_quality(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _prefix_arg(raw: str) -> str | None:
    try:
        return normalize_prefix(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hpscan",
        description="Scan from an HP All-in-One over HP LEDM or eSCL (AirScan). "
        "Run with no command to scan straight to the configured destination "
        "(prompts for type, quality and prefix when none of those flags are given).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--host",
        help="Scanner IP, hostname or Bonjour name, e.g. HP101F743EF639.local "
        f"(overrides env {ENV_HOST} and config; default {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        help=f"Scanner port for LEDM and eSCL (overrides env {ENV_PORT} and config; "
        f"default {DEFAULT_PORT} for http, {DEFAULT_HTTPS_PORT} for https)",
    )
    scheme = parser.add_mutually_exclusive_group()
    scheme.add_argument(
        "--https",
        dest="scheme",
        action="store_const",
        const="https",
        help=f"Use HTTPS (overrides env {ENV_SCHEME} and config)",
    )
    scheme.add_argument(
        "--http", dest="scheme", action="store_const", const="http", help="Use plain HTTP"
    )
    parser.add_argument(
        "--protocol",
        choices=PROTOCOLS,
        default=os.environ.get("HP_SCANNER_PROTOCOL", "auto"),
        help="Scan protocol (env HP_SCANNER_PROTOCOL, default %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    quick = parser.add_argument_group(
        "quick scan (no command)",
        "Scan to <destination>/YYYY/MM/[<prefix>-]<document|image>-<n>-<timestamp>.<ext>",
    )
    quick.add_argument(
        "-t",
        "--type",
        dest="quick_type",
        type=_type_arg,
        metavar="{" + ",".join(OUTPUT_TYPES) + "}",
        help=f"Output type (default {DEFAULT_TYPE})",
    )
    quick.add_argument(
        "-q",
        "--quality",
        dest="quick_quality",
        type=_preset_arg,
        metavar="{" + ",".join(QUALITY_PRESETS) + "}",
        help=f"Quality preset (default {DEFAULT_QUALITY}): {_preset_help()}",
    )
    quick.add_argument(
        "--prefix",
        dest="quick_prefix",
        type=_prefix_arg,
        metavar="TEXT",
        help="Prefix for the file name, e.g. --prefix taxes -> taxes-document-1-....pdf",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    sub.add_parser("status", help="Show scanner state and ADF state")
    sub.add_parser("capabilities", help="Show scanner model, sources and resolutions")

    cfg = sub.add_parser("config", help="Show or change saved settings (~/.config/hpscan)")
    cfg.add_argument(
        "--dest",
        "--destination",
        dest="destination",
        metavar="PATH",
        help="Root folder for automatically named scans (default ~/Documents/HP_Scans)",
    )
    cfg.add_argument(
        "--host",
        dest="cfg_host",
        metavar="HOST",
        help="Save the scanner address: IP, hostname or Bonjour name (e.g. HP101F743EF639.local)",
    )
    cfg.add_argument(
        "--scheme", dest="cfg_scheme", choices=SCHEMES, help="Save http or https for the scanner"
    )
    cfg.add_argument("--port", dest="cfg_port", metavar="PORT", help="Save the scanner port")
    cfg.add_argument(
        "--unset",
        action="append",
        choices=CONFIG_KEYS,
        default=[],
        metavar="KEY",
        help=f"Reset a saved value to its default ({', '.join(CONFIG_KEYS)}); repeatable",
    )
    cfg.add_argument(
        "--show", action="store_true", help="Show the effective settings and where each comes from"
    )

    scan = sub.add_parser("scan", help="Scan to PNG, PDF or JPEG")
    scan.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="Output file (extension sets format). Omit to save under the configured "
        "destination as YYYY/MM/<document|image>-<n>-<timestamp>.<ext>",
    )
    scan.add_argument(
        "-f",
        "--format",
        "-t",
        "--type",
        dest="format",
        type=_type_arg,
        metavar="{pdf,jpg,png}",
        help="Output type (default: inferred from output extension, or pdf when no output given)",
    )
    scan.add_argument(
        "-m",
        "--mode",
        choices=sorted(COLOR_MODES),
        help="Color mode (default: color for png/jpeg, gray for pdf)",
    )
    scan.add_argument(
        "-r",
        "--resolution",
        type=int,
        help=f"DPI (default: from the quality preset, else {DEFAULT_RESOLUTION})",
    )
    scan.add_argument(
        "-s",
        "--source",
        choices=[AUTO_SOURCE, *sorted(SOURCES)],
        default=AUTO_SOURCE,
        help="Input source: auto = document feeder if it has paper, else the glass "
        "(default %(default)s)",
    )
    scan.add_argument(
        "-p",
        "--page",
        choices=sorted(PAGE_SIZES),
        default="letter",
        help="Page size (default %(default)s)",
    )
    scan.add_argument(
        "-q",
        "--quality",
        type=_quality_arg,
        help=f"JPEG quality 1-100, or a preset low/medium/high that also sets the default DPI "
        f"(default {DEFAULT_JPEG_QUALITY} at {DEFAULT_RESOLUTION} dpi)",
    )
    scan.add_argument(
        "--prefix",
        type=_prefix_arg,
        metavar="TEXT",
        help="Prefix for auto-generated file names (only when no output file is given)",
    )
    scan.add_argument(
        "--native-pdf",
        action="store_true",
        help="Ask the device to render PDF itself (LEDM only) instead of assembling from JPEG",
    )
    scan.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip checking settings against scanner capabilities",
    )
    return parser


def _preset_arg(raw: str) -> QualityPreset:
    try:
        return quality_preset(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _preset_help() -> str:
    return ", ".join(
        f"{p.name}={p.resolution}dpi/q{p.jpeg_quality}" for p in QUALITY_PRESETS.values()
    )


def _infer_format(output: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    ext = output.suffix.lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    if ext not in ("png", "pdf", "jpeg"):
        raise SystemExit(f"Cannot infer format from {output.name!r}; pass --format")
    return ext


def cmd_status(client: ScannerClient) -> int:
    status = client.status()
    print(f"Protocol:  {type(client).__name__.removesuffix('Client').lower()}")
    print(f"State:     {status.state}")
    if status.adf_state:
        print(f"ADF state: {status.adf_state}")
    return 0


def cmd_capabilities(client: ScannerClient) -> int:
    caps = client.capabilities()
    print(f"Model:    {caps.make_and_model}")
    if caps.serial_number:
        print(f"Serial:   {caps.serial_number}")
    print(f"Protocol: {caps.version}")
    print(f"Formats:  {', '.join(caps.formats)}")
    for name, ic in (("Platen", caps.platen), ("ADF", caps.adf)):
        if ic is None:
            continue
        print(f"{name}:")
        print(f"  Max size:    {ic.max_width / 300:.2f} x {ic.max_height / 300:.2f} in")
        print(f"  Resolutions: {', '.join(map(str, ic.resolutions))} dpi")
        print(f"  Color modes: {', '.join(ic.color_modes)}")
    if caps.adf_capacity:
        print(f"  Capacity:    {caps.adf_capacity} sheets")
    return 0


def _apply_config_changes(config: Config, args: argparse.Namespace) -> Config:
    config = config.without(*args.unset)
    if args.destination is not None:
        config = config.with_destination(args.destination)
    if args.cfg_host is not None:
        config = config.with_host(args.cfg_host)
    if args.cfg_scheme is not None:
        config = config.with_scheme(args.cfg_scheme)
    if args.cfg_port is not None:
        config = config.with_port(args.cfg_port)
    return config


def _print_settings(config: Config, conn: Connection) -> None:
    dest_source = "config" if config.destination else "default"
    rows = [
        ("Destination", config.scan_root, dest_source),
        ("Host", conn.host.value, conn.host.source),
        ("Scheme", conn.scheme.value, conn.scheme.source),
        ("Port", conn.port.value, conn.port.source),
    ]
    print(f"Config file: {config_path()}")
    for label, value, source in rows:
        print(f"{label + ':':<12} {value}  ({source})")
    print(f"Scanner URL: {conn.scheme.value}://{conn.host.value}:{conn.port.value}/")


def cmd_config(args: argparse.Namespace) -> int:
    stored = load_config()
    config = _apply_config_changes(stored, args)
    if config != stored:
        save_config(config)
        print(f"Saved {config_path()}", file=sys.stderr)
    _print_settings(config, resolve_connection(config, args.host, args.scheme, args.port))
    return 0


def _output_format(args: argparse.Namespace) -> str:
    if args.output is not None:
        return _infer_format(args.output, args.format)
    return args.format or DEFAULT_TYPE


def job_from_scan_args(args: argparse.Namespace) -> ScanJob:
    """Build a job from ``hpscan scan`` arguments."""
    if args.prefix and args.output is not None:
        raise ValueError("--prefix only applies to auto-named scans; drop the output file")
    fmt = _output_format(args)
    preset = args.quality if isinstance(args.quality, QualityPreset) else None
    if preset:
        quality = preset.jpeg_quality
    else:
        quality = DEFAULT_JPEG_QUALITY if args.quality is None else args.quality
    resolution = args.resolution or (preset.resolution if preset else DEFAULT_RESOLUTION)
    return ScanJob(
        fmt=fmt,
        mode=args.mode or DEFAULT_MODES[fmt],
        resolution=resolution,
        quality=quality,
        source=args.source,
        page=args.page,
        native_pdf=fmt == "pdf" and args.native_pdf,
        validate=not args.no_validate,
        output=args.output,
        prefix=args.prefix,
    )


def job_from_choices(choices: QuickChoices) -> ScanJob:
    """Build a quick-scan job (auto source, letter, auto-named) from type/quality/prefix."""
    fmt = normalize_type(choices.type)
    preset = quality_preset(choices.quality)
    return ScanJob(
        fmt=fmt,
        mode=DEFAULT_MODES[fmt],
        resolution=preset.resolution,
        quality=preset.jpeg_quality,
        prefix=normalize_prefix(choices.prefix),
    )


def _quick_choices(args: argparse.Namespace, interactive: bool) -> QuickChoices:
    """Flags win; with no quick flags at all, prompt (TTY) or use the defaults."""
    if not any(getattr(args, name) is not None for name in QUICK_FLAGS):
        if interactive:
            return prompt_choices()
        print("No terminal to prompt on; using defaults", file=sys.stderr)
        return QuickChoices()
    preset = args.quick_quality
    return QuickChoices(
        type=args.quick_type or DEFAULT_TYPE,
        quality=preset.name if preset else DEFAULT_QUALITY,
        prefix=args.quick_prefix,
    )


def _build_job(args: argparse.Namespace, interactive: bool) -> ScanJob | None:
    """Scan job for ``scan`` / bare ``hpscan`` (prompting happens here, before connecting)."""
    if args.command == "scan":
        return job_from_scan_args(args)
    if args.command is None:
        return job_from_choices(_quick_choices(args, interactive))
    return None


def _output_path(job: ScanJob, scan_root: Path) -> Path:
    """Explicit output (parent dirs created) or the next auto-named path under ``scan_root``."""
    if job.output is None:
        return auto_output_path(scan_root, job.fmt, prefix=job.prefix)
    job.output.parent.mkdir(parents=True, exist_ok=True)
    return job.output


def resolve_source(client: ScannerClient, source: str) -> tuple[str, str]:
    """Turn ``auto`` into ``adf``/``platen`` from the live ADF state; returns (source, why)."""
    if source != AUTO_SOURCE:
        return source, ""
    if client.status().adf_loaded:
        return "adf", " (auto: paper in feeder)"
    return "platen", " (auto: feeder empty)"


def cmd_scan(client: ScannerClient, job: ScanJob, scan_root: Path) -> int:
    source, why = resolve_source(client, job.source)
    settings = ScanSettings.for_page(
        job.page,
        source=SOURCES[source],
        color_mode=COLOR_MODES[job.mode],
        resolution=job.resolution,
        quality=job.quality,
        document_format="application/pdf" if job.native_pdf else "image/jpeg",
    )
    if job.validate:
        client.capabilities().validate(settings)

    print(
        f"Scanning {source}{why} at {job.resolution} dpi ({job.mode}, quality {job.quality})"
        f" -> {job.fmt}",
        file=sys.stderr,
    )
    pages = client.scan(settings)
    output = _output_path(job, scan_root)
    written = save_pages(pages, output, job.fmt, dpi=job.resolution)
    for path in written:
        print(path)
    return 0


def main(argv: list[str] | None = None, interactive: bool | None = None) -> int:
    """Run the CLI.

    ``interactive`` defaults to "stdin is a terminal"; it decides whether bare ``hpscan`` prompts.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command and any(getattr(args, name) is not None for name in QUICK_FLAGS):
        parser.error(
            "--type/--quality/--prefix before a command are for quick scans; "
            "use 'hpscan scan --type/--quality/--prefix' instead"
        )
    if interactive is None:
        interactive = sys.stdin.isatty()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        if args.command == "config":
            return cmd_config(args)
        job = _build_job(args, interactive)
        config = load_config()
        conn = resolve_connection(config, args.host, args.scheme, args.port)
        client = connect(
            host=conn.host.value,
            port=conn.port.value,
            scheme=conn.scheme.value,
            protocol=args.protocol,
        )
        if args.command == "status":
            return cmd_status(client)
        if args.command == "capabilities":
            return cmd_capabilities(client)
        return cmd_scan(client, job, config.scan_root)
    except KeyboardInterrupt:
        print("\ncancelled", file=sys.stderr)
        return EXIT_INTERRUPTED
    except (ScannerError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
