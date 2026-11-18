# HANDOFF — hp-scanner

**Date:** 2026-11-17 (updated 2026-11-18: VERSION/requirements-driven packaging + GitHub Actions; auto-named output, `hpscan config` for destination + scanner host/scheme/port, bare `hpscan` quick scan with prompts)
**Repo:** `/Users/scottsmith/tmp/HP_Scanner_App`, remote `VirtuallyScott/HP_Scanner_App`. All work below is committed on
`develop` and pushed; `main` has only the initial commit until `develop` is merged.
**Target device:** HP Officejet 6700 Premium e-All-in-One, hostname `HPE8FCCW`, IP `192.168.4.195`, Bonjour host `HP101F743EF639.local`
**Status:** Glass scans verified live. Feeder (ADF): auto-detect + multi-page job verified live, page saving fixed
(DNL repair) and awaiting a live re-test. CI/Release workflows pass every step locally, but haven't run on GitHub yet.

---

## 1. What this is

A Python wheel (`hp-scanner`, CLI `hpscan`) that scans **color PNG** or **document PDF** from an HP
All-in-One over the network with no drivers, SANE or HPLIP. Pure HTTP via `requests`; image
conversion via `Pillow`.

```bash
make dev && source .venv/bin/activate
hpscan status
hpscan                                # prompts: type [pdf], quality [medium], prefix [none]
hpscan --type png --quality high --prefix receipts   # same, no prompts
hpscan scan                           # gray PDF -> ~/Documents/HP_Scans/YYYY/MM/document-<n>-…pdf
hpscan config --dest ~/Scans          # change that root (saved in ~/.config/hpscan/config.json)
hpscan scan photo.png                 # color, 300 dpi, platen
hpscan scan doc.pdf --source adf      # gray, multi-page -> one PDF
hpscan scan doc.pdf --native-pdf      # device renders the PDF itself
```

## 2. Project layout

```
pyproject.toml          hatchling build; dynamic version (VERSION) + deps (requirements*.txt via hatch-requirements-txt)
VERSION                 SemVer MAJOR.MINOR.PATCH, single source of the version (0.0.1)
requirements.txt        runtime deps (Pillow, requests) -> wheel Requires-Dist
requirements-dev.txt    dev deps -> [dev] extra (build, pytest, pytest-cov, responses, ruff, twine)
scripts/                bump_version.py (major/minor/patch/none), verify_wheel.py (wheel vs VERSION/requirements),
                        install_wheel.py (make install: pip --user by default, or --venv / active venv),
                        shell_path.py (UPDATE_PATH=1: marked PATH block in ~/.zshrc / bash / fish rc)
.github/workflows/      ci.yml (lint/test matrix 3.10-3.14, build, verify, clean-venv install, artifact)
                        release.yml (manual: bump, test, build, commit+tag vX.Y.Z, GitHub Release with dist/*)
Makefile                .PHONY targets: install uninstall dev lint format test coverage test-live build wheel sdist check verify-wheel
                        install-wheel clean distclean all version bump-patch bump-minor bump-major
README.md               user docs + protocol write-up
CLAUDE.md               guidance for Claude Code sessions (commands, architecture, pitfalls, backlog)
src/hp_scanner/
  __init__.py           public exports; __version__ from importlib.metadata (source: VERSION)
  models.py             ScanSettings, ScannerCapabilities, InputCaps, ScannerStatus, errors, PAGE_SIZES
  client.py             connect() / detect_protocol() -> LedmClient | EsclClient; ScannerClient Protocol
  ledm.py               HP LEDM backend (the one this device actually needs)
  escl.py               eSCL/AirScan backend (for newer devices)
  output.py             save_png / save_pdf / save_jpeg / save_pages
  config.py             Config (frozen), load_config/save_config -> ~/.config/hpscan/config.json
  naming.py             auto_output_path(): <root>/YYYY/MM/[<prefix>-]<document|image>-<n>-<timestamp>.<ext>; normalize_prefix
  jpeg.py               fix_dnl_height(): repair HP ADF JPEGs (placeholder SOF height + DNL marker)
  presets.py            --type names (pdf/jpg/png), QUALITY_PRESETS low/medium/high, parse_quality
  prompt.py             prompt_choices() -> QuickChoices for bare `hpscan`
  cli.py                argparse CLI: status | capabilities | scan | config
tests/
  conftest.py           fixtures: capabilities_xml, status_idle_xml, jpeg_page, make_jpeg(), FIXTURES
  fixtures/*.xml        REAL responses captured from the 6700 (eSCL caps/status, LEDM caps/status/job states)
  test_models.py  test_escl.py  test_ledm.py  test_output.py  test_cli.py  test_config.py  test_naming.py
  test_presets.py  test_prompt.py  test_release_tooling.py  test_shell_path.py  test_jpeg.py
                        (268 tests, ~98% coverage via `make coverage`; HTTP mocked via `responses`, HOME redirected to tmp_path)
```

Design rule: **one vocabulary.** `ScanSettings` uses eSCL names everywhere (`RGB24`, `Grayscale8`,
`Platen`, `Feeder`, `image/jpeg`, `application/pdf`); `ledm.py` translates to LEDM
(`Color`/`Gray`, `Platen`/`Adf`, `Jpeg`/`Pdf`/`Raw`). `ScannerCapabilities.validate()` is shared.

## 3. Verification state

| Check | Result |
|---|---|
| `make lint` (ruff) | clean |
| `make test` | 268 passed |
| `make coverage` | 98% (gate 80%) |
| `make check` (VERSION 0.0.1) | wheel `hp_scanner-0.0.1`, Requires-Dist pillow/requests, verify_wheel OK |
| Wheel in clean venv | pulls Pillow + requests, `pip check` clean, `hpscan 0.0.1` ✔ |
| Wheel built from the sdist | ✔ (sdist ships VERSION + requirements*.txt) |
| GitHub Actions | YAML parses; CI steps reproduced locally (3.11 + 3.14 tests, 3.12 build job) ✔; **first GitHub run pending** |
| `make install` (Homebrew 3.15, PEP 668) | user site `~/Library/Python/3.15`, `hpscan status` → LEDM Idle ✔; bin dir not on PATH (hint printed) |
| `make install INSTALL_VENV=…` | venv created, `hpscan 0.0.1` ✔ |
| `make install` (default) | prints zsh instructions; real `~/.zshrc` untouched (md5 check) ✔ |
| `make install UPDATE_PATH=1` (fake HOME) | block added once, re-run "already adds", new zsh finds `hpscan` ✔ |
| `make uninstall` / `UPDATE_PATH=1` (fake HOME) | note that the block remains / block removed, `.zshrc` byte-identical ✔ |
| `make install` with Apple/Xcode python3 3.9 | clear error asking for `PYTHON=python3.13` ✔ |
| Live `hpscan --type png --quality low --prefix bleh` | `bleh-image-1-…png`, 850×1100 RGB (100 dpi) ✔ |
| Live bare `hpscan` without TTY | defaults → `document-2-…pdf`, 200 dpi gray ✔ (numbering counted the prefixed file) |
| Live bare `hpscan` in a pty (`script`) answering jpg / Enter / receipt | `receipt-image-4-…jpg` ✔ |
| Live `hpscan --host HP101F743EF639.local status` (Bonjour/mDNS) | LEDM, Idle ✔ |
| Live `hpscan --https status` (port 443) | **fails**: TLS handshake failure (weak self-signed cert) |
| `make check` (build + twine) | wheel + sdist PASSED |
| Wheel installed in clean venv, `hpscan status/capabilities` | works |
| Live `hpscan scan x.png -r 75` (auto → LEDM) | 637×825 RGB PNG ✔ |
| Live `hpscan scan x.pdf --native-pdf` | device PDF v1.2 ✔ |
| Live `hpscan scan x.pdf` (Pillow assembly) | PDF v1.4 ✔ |
| Live ADF, auto source (3 sheets) | picked `Adf`, one job, pages 1→3 received, `Completed` ✔ |
| Live ADF save | ✘ first run: Pillow "broken data stream" (placeholder SOF height); pages lost. Fixed with DNL repair + raw fallback; **re-test pending** |
| Live eSCL path | N/A — device 409s eSCL jobs; eSCL code tested only with mocks |

### Output location and config (added 2026-11-18)

- `hpscan scan` with no output path writes to
  `<dest>/YYYY/MM/document-<n>-YYYY-MM-DD-<TZ>-HH-MM-SS.pdf` (pdf) or `image-<n>-….png|.jpg`.
  Default format with no output is `pdf`; `--format` overrides.
- `<dest>` = `config.json` `destination`, else `~/Documents/HP_Scans`. Set with
  `hpscan config --dest|--destination PATH` (`~` and `$VARS` expanded, stored absolute).
- `<n>` = max existing `document-`/`image-` number in that month folder + 1 (no state file,
  restarts monthly). `<TZ>` = `%Z` stripped to `[A-Za-z0-9+-]`; time is 24-hour.
- The month folder is created only **after** the scan returns pages, so failed/validated-out scans
  leave nothing behind. Explicit output paths get their parent dirs created too.
- Config dir is always `$HOME/.config/hpscan/` (XDG_CONFIG_HOME is not consulted). Paths are
  computed from `Path.home()` at call time, so tests just `monkeypatch.setenv("HOME", …)`.
- `hpscan config` runs before `connect()`, so it never touches the network.

### Scanner address in config (added 2026-11-18)

- `config.json` also stores `host`, `scheme` (`http`/`https`), `port`; `null` = default.
  `hpscan config --host H --scheme S --port P`, `--unset KEY`, `--show` (effective values + source).
- Resolution per value: CLI flag (`--host/--port/--https/--http`) → env (`HP_SCANNER_HOST/PORT/SCHEME`)
  → config → default (`192.168.4.195`, `http`, 8080; 443 when scheme is https and no port set).
  Implemented in `config.resolve_connection`; global argparse flags default to `None` for this reason.
- Host accepts IPv4, IPv6 (bracketed for URLs), hostnames and Bonjour `.local` names; rejects schemes and
  `host:port`. Bonjour **service** names (`Officejet 6700 [3EF639]`) aren't hostnames — resolve with
  `dns-sd -L "Officejet 6700 [3EF639]" _http._tcp local.` → `HP101F743EF639.local`. `HPE8FCCW.local` does
  not resolve.
- **HTTPS on the 6700 does not work with Python/OpenSSL 3:** port 443 offers TLS 1.2 `AES256-GCM-SHA384`
  with a self-signed cert that OpenSSL flags "EE certificate key too weak" → handshake failure. Supporting it
  would need a custom `ssl.SSLContext` (`@SECLEVEL=0`, no verification) mounted on the session — a
  deliberate security trade-off, not done.

### Quick scan: bare `hpscan` (added 2026-11-18)

- `hpscan [-t|--type pdf|jpg|png] [-q|--quality low|medium|high] [--prefix TEXT]` scans with no subcommand.
  With none of those flags and a TTY it prompts for each (defaults pdf / medium / no prefix); without a TTY
  it uses the defaults silently (one stderr note). Any one flag given → no prompts.
- Presets: low 100 dpi/q50, medium 200 dpi/q75, high 300 dpi/q90. Quick scans: platen, letter, color for
  jpg/png, gray for pdf, auto-named under the configured destination.
- `hpscan scan` gained `-t/--type` (alias of `-f/--format`, accepts `jpg`), `--prefix` (auto-named only) and
  preset names for `-q` (sets dpi unless `-r`). Plain `hpscan scan` still means 300 dpi / q75.
- Prefixed names: `<prefix>-document-<n>-…`; scan numbering counts prefixed files too.
- Ctrl-C now exits 130 with `cancelled` (LEDM still sends its cancel PUT first).
- Prompt answers can't be scripted through a plain pipe (non-TTY → defaults). To exercise the prompt live,
  use a pty: `(sleep 1; printf 'jpg\n'; …; sleep 40) | script -q /dev/null hpscan` — keep the pipe open or
  `script` delivers EOF early and later answers fall back to defaults.

### ADF: auto source + DNL JPEG repair (added 2026-11-18)

- Source `auto` (default): `/Scan/Status` `AdfState=Loaded` → feeder, else glass. Verbatim capture in
  `tests/fixtures/ledm_status_adf_loaded.xml`. Page size stays letter (2550×3300 at 1/300 in).
- First live ADF run: 3 pages received fine, then Pillow failed with `broken data stream when reading image file`.
  Synthetic tests show that exact error comes from a placeholder SOF height larger than the data (65535), which is
  how HP feeders write JPEGs (real height in a `DNL` marker). node-hp-scan-to does the same fix
  (`JpegUtil.fixSizeWithDNL`, applied only for ADF). Our `jpeg.fix_dnl_height` runs on every JPEG page and is a no-op
  without a DNL.
- Safety net: any conversion failure writes the untouched pages as `<stem>-raw-N.jpg|pdf` and exits 1 with their paths.
- Install footgun fixed: an activated dev `.venv` used to be the `make install` target, which replaced its editable
  install with a wheel (tests then imported stale code). The dev venv now needs `INSTALL_VENV=.venv`.

## 4. Key discovery: this device needs LEDM, not eSCL

The 6700 serves `GET /eSCL/ScannerCapabilities` and `/eSCL/ScannerStatus` fine, but **every**
`POST /eSCL/ScanJobs` returns `409` with an empty body (tried every XML variant, both ports,
HTTP/HTTPS, all content-types). The printer's own EWS "Webscan" page uses HP's proprietary
**LEDM** API instead. `connect()` auto-detects: `GET /Scan/Status` → 200 means LEDM.

### LEDM protocol (captured from the EWS Webscan page with Playwright, cross-checked with HPLIP `scan/sane/bb_ledm.c`)

Both port 80 and 8080 work. All URLs relative to `http://192.168.4.195:8080`.

1. `GET /Scan/Status` → `<ScannerState>Idle|BusyWithScanJob</ScannerState><AdfState>Empty|Loaded</AdfState>`
2. `GET /Scan/ScanCaps` → resolutions, `ColorType` `Color8|Gray8|K1`, `Formats` `Raw|Jpeg`, platen/ADF `Min/MaxWidth/Height` (1/300 in), `Risky*Margin`
3. `POST /Scan/Jobs`, `Content-Type: text/xml`, body **exactly** as the EWS sends it:
   ```xml
   <scan:ScanJob xmlns:scan="http://www.hp.com/schemas/imaging/con/cnx/scan/2008/08/19">
     <scan:XResolution>300</scan:XResolution><scan:YResolution>300</scan:YResolution>
     <scan:XStart>0</scan:XStart><scan:YStart>0</scan:YStart>
     <scan:Width>2550</scan:Width><scan:Height>3300</scan:Height>      <!-- 1/300 inch -->
     <scan:Format>Jpeg</scan:Format>                                   <!-- Jpeg | Pdf | Raw -->
     <scan:CompressionQFactor>25</scan:CompressionQFactor>             <!-- = 100 - quality -->
     <scan:ColorSpace>Color</scan:ColorSpace><scan:BitDepth>8</scan:BitDepth>
     <scan:InputSource>Platen</scan:InputSource>                       <!-- Platen | Adf -->
     <scan:GrayRendering>NTSC</scan:GrayRendering>
     <scan:ToneMap><scan:Gamma>1000</scan:Gamma><scan:Brightness>1000</scan:Brightness>
       <scan:Contrast>1000</scan:Contrast><scan:Highlite>179</scan:Highlite><scan:Shadow>25</scan:Shadow></scan:ToneMap>
     <scan:ContentType>Photo</scan:ContentType>                        <!-- Photo (color) | Document (gray) -->
   </scan:ScanJob>
   ```
   → `201 Created`, `Location: http://…/Jobs/JobList/N`. (A `<ScanSettings xmlns=…>` default-ns root
   is also accepted — that's what HPLIP sends — but the manifest says `scan:ScanJob`.)
4. Poll `GET /Jobs/JobList/N` (~0.5 s). `j:JobState` = `Processing|Blocked|Completed|Canceled|Aborted`.
   Each page shows as `<PreScanPage>` with `PageState` `PreparingScan` → `ReadyToUpload` + `BinaryURL`
   `/Scan/Jobs/N/Pages/M` + `BufferInfo` (`ImageWidth`, `ImageHeight`, `BytesPerLine`).
5. `GET BinaryURL` **immediately** when `ReadyToUpload` (chunked `image/jpeg` or `application/pdf`).
   If nobody downloads, the device flips the page to `CanceledByDevice` and the job to `Canceled`.
   `PageState` may bounce back to `PreparingScan` briefly after the download — track pages by number.
6. Terminal: `JobState=Completed` with `<PostScanPage><PageState>UploadCompleted</PageState>`.
7. Cancel: `PUT /Jobs/JobList/N` with HPLIP's body `<j:Job …><j:JobState>Canceled</j:JobState></j:Job>`.
   (The EWS Cancel button sends nothing — it just stops polling.)

Quirks worth knowing:
- `Format=Pdf` **works** even though `ScanCaps` never lists it (`IMPLICIT_FORMATS` in `ledm.py`).
- `ToneMap` values are 0–2000, 1000 = neutral; applied on-device.
- `Raw` = headerless rows, Gray 1 B/px, Color RGB 3 B/px, `ImageWidth = floor(Width*res/300)`. Not implemented (see §6).
- `/Scan/ScanCaps` is slow (>5 s sometimes) — `LedmClient` default timeout is 30 s.
- Self-describing API manifests: `/DevMgmt/DiscoveryTree.xml`, `/Scan/ScanJobManifest.xml`,
  `/Jobs/JobsManifest.xml` (lists verbs per resource; confirms `Put` on `/Jobs/JobList/{id}`).

## 5. Pitfalls hit during development (don't repeat)

- **Unbounded polling loops** against the device hang the session. Every loop now has a cap
  (`LedmClient.job_timeout`, default 600 s) and probes used `timeout 150 …`.
- `curl -m 5` is too short for `/Scan/ScanCaps`; use ≥30 s.
- `tests/` is not a package: import helpers with `from conftest import …` (pytest adds `tests/` to
  `sys.path`), not `from tests.conftest import …`.
- `responses` gives `request.body` as `str` for string payloads and `bytes` for bytes payloads —
  match the type in assertions.
- The EWS JavaScript is eval'd at runtime, not served as files — grep'ing downloaded `.js` finds
  nothing; capture live traffic with Playwright `page.on('request'/'response')` instead.

## 6. Open items / next steps

1. **Re-test ADF saving on hardware.** Load 2–3 sheets, run `hpscan -v`. Protocol side is confirmed (one job,
   `PageNumber` 1→3, `Completed`). Check that `-v` shows `JPEG height … -> N (from DNL marker)` and that the PDF has
   all pages. On failure the raw pages are kept as `<name>-raw-N.jpg`; capture one as a fixture. If it has no
   DNL, use the job's `BufferInfo/ImageHeight` instead.
   Also check whether `--native-pdf` with ADF yields one multi-page PDF or one PDF per page
   (currently multiple native PDFs are written as `name-1.pdf`, `name-2.pdf`…; merging would need `pypdf`).
2. **Watch the first CI run** on `develop` (Actions tab), then merge `develop` → `main` and run the Release
   workflow with `bump=none` to publish `v0.0.1` (later releases: `patch`/`minor`/`major`). Locally verified:
   ruff + format check, pytest + coverage on Python 3.11 and 3.14 in fresh venvs, and the full build job on 3.12
   (build, twine, verify_wheel, clean-venv install, version assertion). Python 3.10 was not run locally.
3. Optional: implement `Raw` decoding (`Image.frombytes` using `BufferInfo`) for lossless scans.
4. Optional: `--brightness/--contrast` CLI flags (currently only via `ScanSettings.extra`).
5. Optional: `K1` 1-bit mode (`COLOR_MODES["bw"]`) — eSCL caps don't list it; LEDM caps do, Raw-only.
6. Optional: live `test-live` Make target could run an actual 75 dpi scan behind an env guard.
7. eSCL backend is untested against real hardware (no eSCL device available).
8. Optional: opt-in legacy TLS for old HP HTTPS (`--insecure-tls`: custom SSLContext, SECLEVEL=0, no verify).
9. Optional: resolve Bonjour service names directly (would need `zeroconf` dependency).

## 7. Reference material

- Fixtures in `tests/fixtures/` are verbatim device responses — reuse them for new parsers.
- Research notes (HPLIP `bb_ledm.c` line refs, other LEDM clients: `manuc66/node-hp-scan-to`,
  `pawitp/py-hp-scan`, `gamunu/smudge`) are summarised in README "How it works".
- EWS Webscan UI: `http://192.168.4.195/#hId-pgWebScan` — options PDF/JPEG, Color/Black,
  A4/Letter/4x6/5x7, 75/200/300/600 dpi, Quality 0–100, Lighter/Darker.
