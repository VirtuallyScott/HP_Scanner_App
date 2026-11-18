# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`hp-scanner` (CLI: `hpscan`) scans color PNG, document PDF, or raw JPEG from HP All-in-One printers
over the LAN using plain HTTP. It needs no drivers, SANE, or HPLIP. Runtime deps are `requests` and
`Pillow`. Python ≥3.10, hatchling, src layout (`src/hp_scanner/`).

**Version and deps have one source each:** `VERSION` (SemVer `MAJOR.MINOR.PATCH`, currently `0.0.1`, no
leading zeros) is read by hatch (`[tool.hatch.version]` regex), and `__version__` comes from
`importlib.metadata`, so never hardcode a version anywhere. Runtime deps live in `requirements.txt` and dev deps in
`requirements-dev.txt`. The `hatch-requirements-txt` plugin maps them to `dependencies` / the `[dev]` extra
(`dynamic = [...]` in `pyproject.toml`). Edit those files, not `pyproject.toml`, and keep them alphabetized.
The sdist `include` list must keep `VERSION` and both requirements files, or wheels built from the sdist break.

Reference device: **HP Officejet 6700 Premium e-All-in-One**, hostname `HPE8FCCW`, IP `192.168.4.195`
(port 8080 by default; LEDM also answers on 80). Bonjour service `Officejet 6700 [3EF639]` resolves to
mDNS host `HP101F743EF639.local` (verified live; `HPE8FCCW.local` does **not** resolve). HTTPS on 443
fails the TLS handshake (self-signed cert, key too weak for OpenSSL), so use http for this device. Its embedded web server Webscan page is
`http://192.168.4.195/#hId-pgWebScan`.

`HANDOFF.md` is the detailed engineering log: full LEDM wire protocol, verification table, pitfalls,
open items. `README.md` is user-facing docs plus a protocol summary. Keep both in sync with behavior changes.

## Commands

```bash
make dev                 # .venv + editable install with [dev] extras (stamp file; re-runs when pyproject.toml, VERSION or requirements*.txt change)
source .venv/bin/activate
make lint                # ruff check src tests scripts
make format              # ruff format + ruff check --fix
make test                # pytest, fully mocked with `responses` (268 tests, ~2.7 s, no scanner needed)
make coverage            # pytest-cov report, fails under 80% (currently ~98%)
make all                 # lint + test + build + twine check + verify_wheel (the full pre-commit gate)
make version             # print VERSION
make bump-patch          # edit VERSION only (also bump-minor / bump-major); usually let the Release workflow do it
make verify-wheel        # dist/*.whl Version == VERSION and Requires-Dist ⊇ requirements.txt
make build / wheel       # sdist+wheel / wheel only into dist/
make install             # build wheel + install for the user (pip --user); INSTALL_VENV=path or an active venv instead
make install UPDATE_PATH=1   # also add the user scripts dir to PATH in the shell rc (marked block)
make uninstall           # same target rules; UPDATE_PATH=1 also removes the rc block
make install-wheel       # wheel into the dev .venv (drops the dev stamp so `make dev` restores editable)
make test-live           # hpscan status + capabilities against SCANNER_HOST (default 192.168.4.195)
make test-live SCANNER_HOST=192.168.1.50

pytest tests/test_ledm.py                     # one file
pytest tests/test_ledm.py -k scan -v          # subset by name
hpscan -v scan /tmp/x.png -r 75               # fastest real scan (75 dpi platen); -v logs every job poll
hpscan                                         # quick scan: prompts type/quality/prefix (defaults pdf/medium/none)
hpscan --type png --quality low --prefix bleh  # quick scan, no prompts (fastest real check: 100 dpi)
hpscan scan                                    # auto-named PDF under the configured destination
hpscan config --show                           # effective settings + source of each value
hpscan config --dest ~/Scans                   # set destination (~/.config/hpscan/config.json)
hpscan config --host HP101F743EF639.local --scheme http --port 8080   # saved scanner address
hpscan config --unset host                     # back to default
hpscan -v scan /tmp/stack.pdf --source adf    # ADF multi-page (needs paper loaded)
```

Ruff: line length 100, rules `E F I UP B`, target `py310`.

## Architecture

```text
cli.py ──► client.connect() ──► LedmClient (ledm.py)   ← real device uses this
                │                EsclClient (escl.py)   ← newer devices; mock-tested only
                ▼
          models.py  (ScanSettings, ScannerCapabilities.validate, ScannerStatus, errors)
                ▼
          output.save_pages()  (JPEG pages → PNG files / one Pillow PDF; native PDFs passed through)

cli.py ──► config.load_config() (~/.config/hpscan/config.json) ──► naming.auto_output_path()

bare `hpscan` ──► prompt.prompt_choices() / quick flags ──► QuickChoices ─┐
`hpscan scan` ──► job_from_scan_args() ──────────────────────────────────┴─► ScanJob ──► cmd_scan()
                  (presets.py: --type names, low/medium/high QUALITY_PRESETS)
```

- **Protocol detection** (`client.detect_protocol`): `GET /Scan/Status` → 200 means LEDM, otherwise eSCL.
  LEDM is preferred because the 6700 serves eSCL caps and status but answers **every**
  `POST /eSCL/ScanJobs` with an empty 409.
- **`ScannerClient` Protocol**: `base_url`, `status()`, `capabilities()`, `scan(settings, check_status=True) -> list[bytes]`.
  Any new backend must satisfy it, and the CLI only talks to this interface.
- **One-vocabulary rule:** `ScanSettings` and `ScannerCapabilities` always use eSCL terms
  (`RGB24`/`Grayscale8`/`BlackAndWhite1`, `Platen`/`Feeder`, `image/jpeg`/`application/pdf`/`application/octet-stream`).
  `ledm.py` translates with the `COLOR_TO_LEDM`, `SOURCE_TO_LEDM`, `FORMAT_TO_LEDM`, and `LEDM_TO_*` maps.
  LEDM caps are parsed *into* eSCL-named `ScannerCapabilities`, so `validate()` is shared.
  Never put LEDM names in models or the CLI.
- **Units:** regions and offsets are 1/300 inch on both protocols (`PAGE_SIZES` in `models.py`).
  `quality` is 1–100, and LEDM sends `CompressionQFactor = 100 - quality`.
- **LEDM-only tuning** goes through `ScanSettings.extra`: `Gamma`/`Brightness`/`Contrast` (0–2000, 1000 = neutral),
  `Highlite`, `Shadow`, `Threshold`, `SharpeningLevel`, `NoiseRemoval`, `GrayRendering`.
  The eSCL backend dumps `extra` straight into its XML, so keys are protocol-specific.
- **LEDM scan loop** (`LedmClient.scan`): status check → `POST /Scan/Jobs` (`201` + `Location`) → poll the job
  (`JobSnapshot.from_xml`) every `poll_interval` → download `BinaryURL` the moment `PageState=ReadyToUpload`,
  tracking pages by number in a `downloaded` set → stop on `Completed`/`Canceled`/`Aborted`. On timeout,
  `ScannerError`, or Ctrl-C it sends `PUT` `CANCEL_JOB_XML` to the job URL (best effort).
- **`settings_to_xml` element order mirrors the device's own Webscan page exactly.** Some firmware cares,
  so append new elements in the position the EWS uses rather than reordering.
- **CLI defaults:** the format is inferred from the extension (`.jpg`→jpeg). Mode defaults to color for png/jpeg
  and gray for pdf. Settings are validated against capabilities unless `--no-validate` is passed.
  `ScannerError`/`ValueError`/`OSError` print `error: …` and exit 1. Env vars: `HP_SCANNER_HOST`, `HP_SCANNER_PORT`,
  `HP_SCANNER_SCHEME`, `HP_SCANNER_PROTOCOL`.
- **Quick scan (no subcommand):** `hpscan [-t pdf|jpg|png] [-q low|medium|high] [--prefix TEXT]`.
  Subparsers are optional (`dest="command"`, `None` = quick scan). Top-level dests are `quick_type`,
  `quick_quality`, `quick_prefix` (`QUICK_FLAGS`) so they can't collide with `scan`'s `format/quality/prefix`;
  using them together with a subcommand is a `parser.error` (exit 2). If **none** of them is given and
  `main(interactive=…)` is true (default `sys.stdin.isatty()`), `prompt.prompt_choices()` asks for each
  (Enter = default, EOF = default, 3 bad answers → `ValueError`). Non-TTY → defaults, no prompt. Prompting
  happens in `_build_job` **before** `connect()`. Ctrl-C anywhere → `cancelled`, exit 130. Quick scans are
  platen/letter, mode from `DEFAULT_MODES`, always auto-named.
- **Source `auto`** (default for quick scans and `hpscan scan`): `cli.resolve_source` calls `client.status()` and
  picks `adf` when `adf_loaded` (LEDM `AdfState=Loaded` → `ScannerAdfLoaded`), else `platen`. `--source platen|adf`
  forces one. Fixture `ledm_status_adf_loaded.xml` is a verbatim capture. Page size stays **letter** by default
  (user requirement, matching the EWS Webscan default); tests pin `Width 2550`/`Height 3300` for ADF jobs.
- **ADF JPEGs** (`jpeg.py`): HP writes a placeholder SOF height (Pillow error "broken data stream when reading image
  file") and the real lines in a `DNL` (`FFDC`) marker. `output.save_pages` runs `fix_dnl_height` on every page
  (returns new bytes), and on any conversion failure writes `<stem>-raw-N.<ext>` and raises `PageConversionError`
  (an `OSError`). Never drop scanned bytes: the paper has already gone through the feeder. Tests build synthetic
  DNL JPEGs with `tests/test_jpeg.py::adf_jpeg` (it reproduces the exact Pillow error).
- **Presets** (`presets.py`): `low`=100 dpi/q50, `medium`=200/q75, `high`=300/q90; all are resolutions the 6700
  supports (a test enforces that). `normalize_type` maps `jpg`/`jpeg`→internal `jpeg`. `hpscan scan -q` accepts
  1-100 **or** a preset (`parse_quality`); a preset sets the dpi only when `-r` is absent. Without a preset
  `scan` keeps 300 dpi / q75.
- **`ScanJob`** (frozen, in `cli.py`) is the single input to `cmd_scan`; build it with `job_from_scan_args`
  or `job_from_choices`. Don't pass `argparse.Namespace` into `cmd_scan` again.
- **Prefix** (`naming.normalize_prefix`): `[A-Za-z0-9_][A-Za-z0-9_. -]*`, ≤64 chars, trailing `-` stripped, blank
  → none. No separators, so it can't escape the destination. `hpscan scan --prefix` with an explicit output
  file is a `ValueError`.
- **Auto output (no `output` arg):** `scan` defaults to `pdf` and writes
  `<dest>/YYYY/MM/[<prefix>-]document-<n>-YYYY-MM-DD-<TZ>-HH-MM-SS.pdf` (`image-<n>-….png|.jpg` for png/jpeg).
  `<dest>` comes from `config.json` `destination`, else `~/Documents/HP_Scans`. `<n>` is the max existing
  `document-`/`image-` number in that month folder + 1, prefixed files included (`_SCAN_NUMBER` uses `search`
  and requires the date after `<n>`; no counter file). Dirs are created only after
  pages arrive. Explicit output paths also get parent dirs created.
- **Config:** `config.py` holds a frozen `Config(destination, host, scheme, port)`; `None` = default.
  Change it only via `with_destination/with_host/with_scheme/with_port/without(*keys)` (each validates and
  returns a copy). `from_dict` runs the same validators, so a hand-edited bad file fails loudly.
  Always `$HOME/.config/hpscan/config.json`, resolved via `Path.home()` at call time; tests isolate by
  setting `HOME` to `tmp_path`. Bad JSON/values raise `ValueError` → `error: …`, exit 1.
- **Connection resolution** (`config.resolve_connection`): per value, CLI flag → env
  (`HP_SCANNER_HOST/PORT/SCHEME`) → config → default (`192.168.4.195`, `http`, port 8080, or 443 for https).
  Returns `Setting(value, source)` triples so `config --show` can print where each came from. Global
  `--host/--port/--https/--http` therefore default to `None`; never put env lookups back into argparse
  defaults or config/env stop working. `main()` resolves once and passes values to `connect()`.
- **Host validation** (`normalize_host`): IPv4, IPv6 (returned bracketed for URLs), or RFC-1123 hostname
  incl. Bonjour `.local`. Rejects `http://…` and `host:port`. Bonjour *service* names (with spaces) are not
  resolved; users resolve them with `dns-sd -L`.
- **`hpscan config`**: dispatched before `connect()` (never touches the network). Flags `--dest|--destination`,
  `--host`, `--scheme {http,https}`, `--port`, `--unset KEY` (repeatable), `--show`. Its subparser dests are
  `cfg_host/cfg_scheme/cfg_port` — they must not reuse `host/port/scheme` or argparse would clobber the
  global flags. Writes only if the config actually changed; always prints the effective settings.
- **Output naming:** multi-page PNG/JPEG and multiple native PDFs become `name-1.ext`, `name-2.ext`, ….
  Pillow-assembled PDFs are always one multi-page file.

## Installing the wheel (`scripts/install_wheel.py`, behind `make install`)

- The user wants **per-user installs with the normal Python by default**, and a venv only when one is specified.
  Don't switch to pipx. Target order: `--venv`/`INSTALL_VENV` → `$VIRTUAL_ENV` → the interpreter is itself a venv →
  `pip --user` of `$(PYTHON)`.
- Homebrew Python is PEP 668 `EXTERNALLY-MANAGED`. For user installs only, the script adds `--break-system-packages`,
  which with `--user` writes to `~/Library/Python/3.X` only. It runs `--force-reinstall --no-deps` on the wheel
  (so same-version rebuilds really reinstall), then a plain install to pull missing deps without reinstalling them.
- `~/Library/Python/3.X/bin` is not on the user's PATH. By default the script prints shell-specific on-screen
  instructions and edits nothing. With `--update-path` / `UPDATE_PATH=1`, `scripts/shell_path.py` writes a marked
  `# >>> hp-scanner PATH >>>` block to zsh `~/.zshrc` (`$ZDOTDIR`), bash `~/.bash_profile` (macOS) / `~/.bashrc`, or
  fish `conf.d/hp-scanner.fish`. Writing is idempotent, a changed dir rewrites the block, and uninstall with the flag
  removes it byte-exactly. Files are written in place (not by rename) so symlinked dotfiles survive. Never edit the
  user's real rc file in tests or manual checks: use a fake `HOME` + `SHELL`.
- The project's dev `.venv` is **never** the implicit target. If it's activated (or `$(PYTHON)` is its python),
  `make install` goes to the user site via `sys._base_executable`; only `INSTALL_VENV=.venv` installs there. (An
  activated dev venv once got its editable install replaced by the wheel, so tests ran stale code.)
- `install_wheel.py` refuses Python <3.10 (`MIN_PYTHON`, keep in sync with `requires-python`). `/usr/bin/python3` and
  Xcode's `python3` are 3.9 on macOS, so PATH order matters. Pip runs with `--no-warn-script-location` because we
  print our own PATH guidance.
- Scripts import each other (`install_wheel` → `shell_path`); tests put `scripts/` on `sys.path` before loading by path.
- On this machine pipx's shared libs are Python 3.13 while its default interpreter is 3.15, so `pipx install`
  crashes. That's another reason not to use pipx.

## CI and releases (`.github/workflows/`)

- `ci.yml`: push to `main`/`develop`, PRs. Test matrix Python 3.10–3.14 (`ruff check`, `ruff format --check`,
  pytest with `--cov-fail-under=80`). Then the build job runs `python -m build`, `twine check`, `scripts/verify_wheel.py`,
  a clean-venv install with `pip check` and an `hpscan --version` == `VERSION` assertion, and uploads `dist/` as an artifact.
  Run `make format` locally before pushing, because CI fails on unformatted code.
- `release.yml`: manual `workflow_dispatch` on `main` only, with input `bump` ∈ patch/minor/major/none (`none` releases
  `VERSION` unchanged, used for the first `0.0.1`). It runs tests, then `scripts/bump_version.py`, build + verify, commits
  `VERSION` as `github-actions[bot]`, tags `vX.Y.Z`, pushes, and runs `gh release create` with `dist/*`. It fails if the tag exists.
  `GITHUB_TOKEN` pushes don't retrigger CI, so there's no loop.
- Actions are pinned to major tags (`checkout@v7`, `setup-python@v7`, `upload-artifact@v7`). Inputs reach shell
  steps only via `env:`, never by inlining `${{ inputs.* }}` into `run:` (script injection).
- `scripts/` (stdlib only, linted with ruff) is tested by `tests/test_release_tooling.py`, which loads the scripts by path.

## Working against the real scanner

- **Every polling or retry loop must be bounded.** Unbounded loops against the device hung earlier sessions.
  `LedmClient.job_timeout` defaults to 600 s. Wrap ad-hoc `curl`/script probes in `timeout 150 …`.
- `/Scan/ScanCaps` can take >5 s. Use ≥30 s timeouts (`LedmClient.timeout` = 30 s; `curl -m 5` is too short).
- Download pages immediately. An undownloaded page goes `CanceledByDevice` and the job flips to `Canceled`.
  `PageState` can bounce back to `PreparingScan` after a download, so key on `PageNumber`, not state.
- `JobState=Blocked` means keep waiting, not failure.
- `LedmClient` defaults: `timeout=30`, `page_timeout=300` (page download read timeout), `poll_interval=0.5`, `job_timeout=600`.
- `Format=Pdf` works even though ScanCaps lists only `Raw`/`Jpeg` (`IMPLICIT_FORMATS`).
- To learn new LEDM behavior, capture the EWS Webscan page's live traffic with Playwright
  (`page.on('request'/'response')`). Its JS is eval'd at runtime, so grepping downloaded `.js` finds nothing.
  The device also self-describes via `/DevMgmt/DiscoveryTree.xml`, `/Scan/ScanJobManifest.xml`, and
  `/Jobs/JobsManifest.xml` (verbs per resource).
- Prior art to cross-check: HPLIP `scan/sane/bb_ledm.c`, `manuc66/node-hp-scan-to`, `pawitp/py-hp-scan`, `gamunu/smudge`.
- Write test scans to `/tmp` or the scratchpad. `*.png/*.jpg/*.pdf` are gitignored everywhere except `tests/fixtures/`.

## Tests

- **CI-portability rules** (learned while preparing the first push):
  - Scripts loaded by path must be registered in `sys.modules` before `exec_module`, because `@dataclass` on
    Python ≤3.11 looks the module up there (`tests/test_release_tooling.py::_load`).
  - Never assume the suite runs inside the repo's `.venv`; CI installs into the runner's Python. Fake the
    interpreter layout with the `running_in_venv` fixture (monkeypatches `sys.prefix`/`base_prefix`/`_base_executable`).
  - To reproduce CI locally, make a fresh venv with an older Python (`/opt/homebrew/opt/python@3.11/bin/python3.11
    -m venv /tmp/ci && /tmp/ci/bin/pip install -e ".[dev]" && /tmp/ci/bin/pytest`). The dev venv runs 3.15 and hides
    version-specific breakage.

- All tests mock HTTP with `responses`; none touch the network. New device-facing code needs mocked tests in the
  matching `tests/test_<module>.py`.
- `tests/fixtures/*.xml` are **verbatim captures from the 6700** (eSCL caps/status; LEDM caps, status,
  job-ready, job-completed). Add new captures there and build parser tests on real responses, not hand-written XML.
- `tests/` is not a package: import helpers with `from conftest import make_jpeg, FIXTURES`.
- `responses` exposes `request.body` as `str` for str payloads and `bytes` for bytes payloads, so match the type
  in assertions (LEDM job bodies are bytes from `ET.tostring`).
- CLI tests that write auto-named files use the `home` fixture (sets `HOME` to `tmp_path/home`).
- Quick-scan tests pass `main(argv, interactive=True|False)` and monkeypatch `builtins.input`;
  `prompt_choices` resolves `input` at call time for exactly this reason. Use `pytest.fail` in the fake
  `input` to assert "must not prompt". Each `responses` `NextDocument` mock serves one page, so one scan
  per test (parametrize instead of scanning twice).
- Build `LedmClient(..., poll_interval=0)` in loop tests (and `job_timeout=0` to hit the timeout path) so the suite stays fast.

## Status and open work (from HANDOFF.md)

Verified live: platen PNG via LEDM, device-native PDF, Pillow-assembled PDF, wheel install in a clean venv.
ADF protocol side verified live (2026-11-18): auto-source picked `Adf`, one job delivered pages 1–3, then
`Completed`. **Not verified on hardware:** saving those ADF pages (the first run died on Pillow before the DNL
fix existed, and the pages were lost), `--native-pdf` + ADF, and the whole eSCL backend.

Backlog, roughly by priority:

1. Re-run a 2–3 sheet ADF scan (`hpscan -v`) and confirm the DNL fix produces a readable multi-page PDF (`-v`
   logs `JPEG height 65535 -> N (from DNL marker)`). If it still fails, the `-raw-N.jpg` files are left next to
   the target, so inspect them with `jpeg.scan_layout` and save one as a fixture. If there's no DNL, fall back to
   the job's `BufferInfo/ImageHeight` (`JobSnapshot` would need to carry it). Also check `--native-pdf` + ADF
   (one PDF or one per page; merging would need `pypdf`).
2. Work is committed on `develop` (pushed to origin; `main` still holds only the initial commit). Watch the first
   CI run on GitHub (the matrix's Python 3.10 leg was never run locally), then merge to `main` and run the Release
   workflow with `bump=none` to publish `v0.0.1`.
3. `Raw` format decoding for lossless scans: `Image.frombytes` using `BufferInfo`
   (`ImageWidth = floor(Width*res/300)`, `BytesPerLine`; Gray 1 B/px, Color 3 B/px, headerless rows).
   `JobSnapshot` would need to carry `BufferInfo`.
4. `--brightness` / `--contrast` CLI flags mapping to `ScanSettings.extra` (LEDM only).
5. `bw` / `K1` 1-bit mode. `COLOR_TO_LEDM` already maps `BlackAndWhite1 → (Gray, 1)`, but the device only
   offers K1 as Raw, so it depends on item 3.
6. An env-guarded live scan in `make test-live`.
7. Opt-in legacy TLS so `https` works on old HP firmware (custom `SSLContext`, `@SECLEVEL=0`, no verify).
8. Resolve Bonjour service names directly (needs `zeroconf`).

## Adding a feature: checklist

- New scan option: add a field to `ScanSettings` (or an `extra` key if LEDM-only) → translate it in
  `ledm.settings_to_xml` and/or `ScanSettings.to_xml` (eSCL) → add a CLI flag in `cli.build_parser`/`cmd_scan`
  → add the validation in `ScannerCapabilities.validate` if the device advertises limits → add tests → update the
  README options table and HANDOFF.md.
- New persisted setting: add a field to `config.Config`, a `with_<field>` validator, an entry in `_LOADERS`
  and `to_dict`, a `cfg_<field>` flag on the `config` subparser, a row in `_print_settings`; tests in
  `tests/test_config.py` + `tests/test_cli.py`; document it in README "Configuration".
- New quick-scan choice: add the flag to the `quick` group with a `quick_<name>` dest and add it to
  `QUICK_FLAGS`, a field on `prompt.QuickChoices` + a prompt in `prompt_choices`, map it in
  `job_from_choices`; mirror it on `hpscan scan`; update README "Quick scan".
- New public symbol: export it in `__init__.py` `__all__`.
- New runtime dependency: add it to `requirements.txt` (alphabetical), not `pyproject.toml`; `verify_wheel.py`
  will then check that it reaches the wheel.
- Run `make all` (and `make coverage`, ≥80%) before calling it done.
