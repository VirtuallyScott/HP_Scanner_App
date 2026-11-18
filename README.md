# hp-scanner

[![CI](https://github.com/VirtuallyScott/HP_Scanner_App/actions/workflows/ci.yml/badge.svg)](https://github.com/VirtuallyScott/HP_Scanner_App/actions/workflows/ci.yml)

Scan **color PNGs** and **document PDFs** from an HP All-in-One printer over the
network. No HP drivers, SANE, or HPLIP required — just Python, `requests`, and
`Pillow`.

Two protocols are supported and auto-detected:

- **LEDM** — HP's proprietary REST/XML scan API (`/Scan/Jobs`), used by the
  printer's own *Webscan* page and by HPLIP. Required for 2010-2015 era HP
  devices which advertise eSCL but reject every eSCL scan job with HTTP 409.
- **eSCL / AirScan** — the Mopria standard (`/eSCL/ScanJobs`), for newer devices.

Developed against an **HP Officejet 6700 Premium e-All-in-One** (hostname
`HPE8FCCW`, default IP `192.168.4.195`), which needs LEDM.

## Features

- `hpscan` — just run it: prompts for type (pdf/jpg/png), quality (low/medium/high) and an optional
  file-name prefix, then scans. Or skip the prompts: `hpscan --type png --quality high --prefix receipts`
- `hpscan scan` — no filename needed: saves to `~/Documents/HP_Scans/YYYY/MM/` with an
  auto-numbered, timestamped name (destination configurable with `hpscan config --dest`)
- `hpscan scan photo.png` — color PNG from the feeder if loaded, else the flatbed (`--source platen` forces the glass)
- `hpscan scan doc.pdf --source adf` — multi-page grayscale PDF from the document feeder
- `hpscan scan doc.pdf --native-pdf` — let the device render the PDF itself (LEDM)
- Settings are validated against the scanner's advertised capabilities before a job starts
- Library API (`connect`, `LedmClient`, `EsclClient`, `ScanSettings`, `save_pages`)
- Save the scanner's address (IP, hostname or Bonjour `.local` name), http/https and port once with
  `hpscan config`; override per run with flags or `HP_SCANNER_HOST` / `HP_SCANNER_PORT` /
  `HP_SCANNER_SCHEME` / `HP_SCANNER_PROTOCOL`

## Requirements

- Python 3.10+
- An HP scanner reachable on your LAN (both LEDM and eSCL live on `http://<ip>:8080`;
  LEDM also answers on port 80)

## Installation

`hpscan` installs **for your user with your normal Python** by default, and into a virtualenv
only when you ask for one.

From this checkout:

```bash
make install                            # build the wheel, pip install --user it
make install UPDATE_PATH=1              # ... and put hpscan on your PATH (edits your shell startup file)
make install INSTALL_VENV=~/envs/scan   # or into that venv (created if missing)
make uninstall                          # remove it again (same target rules)
make uninstall UPDATE_PATH=1            # ... and remove the PATH entry it added
```

`make install` picks the target in this order: `INSTALL_VENV=path` → an **activated** venv
(`$VIRTUAL_ENV`) → the per-user site of `python3` (override with `PYTHON=python3.13`). On macOS
the user install lands in `~/Library/Python/3.X/`, and the command lives in `~/Library/Python/3.X/bin`.
That folder usually isn't on PATH. You have two options:

- **Automatic**: `make install UPDATE_PATH=1` (or `scripts/install_wheel.py --update-path`) adds this
  marked block to your shell startup file. It never adds it twice, and it rewrites the block if the path
  changes, e.g. after a Python upgrade:

  ```bash
  # >>> hp-scanner PATH >>>
  export PATH="$HOME/Library/Python/3.15/bin:$PATH"
  # <<< hp-scanner PATH <<<
  ```

  | Shell | File edited |
  | --- | --- |
  | zsh | `~/.zshrc` (or `$ZDOTDIR/.zshrc`) |
  | bash | `~/.bash_profile` on macOS, `~/.bashrc` on Linux |
  | fish | `~/.config/fish/conf.d/hp-scanner.fish` (`fish_add_path`) |

  Then open a new terminal (or `exec zsh`). `make uninstall UPDATE_PATH=1` removes exactly that block.
  Symlinked startup files (dotfiles repos) are edited in place and stay symlinks.
- **On-screen instructions** (default): without `UPDATE_PATH=1`, nothing is edited. `make install`
  prints the exact commands for your shell:

  ```text
  hpscan was installed to $HOME/Library/Python/3.15/bin, which is not on your PATH.
    Add it automatically:  make install UPDATE_PATH=1   (or --update-path)
    Or add it yourself (zsh):
      echo 'export PATH="$HOME/Library/Python/3.15/bin:$PATH"' >> $HOME/.zshrc
      exec zsh
    Until then, run it as: $HOME/Library/Python/3.15/bin/hpscan
  ```

Venv installs don't touch PATH, because you activate the venv instead. `make install` needs Python ≥3.10.
If `python3` is older (e.g. Apple's 3.9), it stops and asks for `PYTHON=python3.13`.

Homebrew's Python is marked *externally managed* (PEP 668), which makes plain `pip install --user`
refuse. `make install` then adds `--break-system-packages`. Together with `--user` that only writes
to your user site and never touches Homebrew's own packages.

**From a GitHub Release** (no checkout needed). Every release on the
[Releases page](https://github.com/VirtuallyScott/HP_Scanner_App/releases) has the wheel attached and
copy-paste install commands for that version at the top of its notes. Install straight from the URL:

```bash
python3 -m pip install --user \
  https://github.com/VirtuallyScott/HP_Scanner_App/releases/download/v0.0.1/hp_scanner-0.0.1-py3-none-any.whl
# Homebrew Python: add --break-system-packages
hpscan --version
```

Or fetch the latest release with the GitHub CLI:

```bash
gh release download -R VirtuallyScott/HP_Scanner_App -p '*.whl'   # latest release
python3 -m pip install --user hp_scanner-*.whl
```

Runtime dependencies are declared in `requirements.txt` and baked into the wheel's metadata at
build time, so `pip install <wheel>` installs them; no separate `pip install -r` is needed.

For development:

```bash
make dev          # creates .venv and installs editable with dev extras
source .venv/bin/activate
```

## Usage

### Quick scan: `hpscan`

```bash
hpscan                                      # prompts; press Enter to accept each default
hpscan --type pdf                           # no prompts: pdf, medium, no prefix
hpscan --type jpg --quality high            # color JPEG at 300 dpi
hpscan --type png --quality low --prefix bleh   # -> .../bleh-image-<n>-<timestamp>.png
hpscan -t pdf -q medium --prefix taxes      # short flags
```

```text
$ hpscan
Type (pdf/jpg/png) [pdf]:
Quality (low/medium/high) [medium]: high
File name prefix [none]: receipts
Scanning platen at 300 dpi (gray, quality 90) -> pdf
/Users/you/Documents/HP_Scans/2026/11/receipts-document-4-2026-11-18-EST-08-09-28.pdf
```

| Flag | Values | Default |
| --- | --- | --- |
| `-t, --type` | `pdf`, `jpg`, `png` (`jpeg` also accepted) | `pdf` |
| `-q, --quality` | `low`, `medium`, `high` | `medium` |
| `--prefix` | text | none |

| Quality | Resolution | JPEG quality |
| --- | --- | --- |
| `low` | 100 dpi | 50 |
| `medium` | 200 dpi | 75 |
| `high` | 300 dpi | 90 |

- Prompts appear only when **none** of `--type` / `--quality` / `--prefix` is given. Pass any one of
  them and the rest use their defaults without asking.
- Without a terminal (cron, pipes, scripts) bare `hpscan` doesn't prompt; it scans with the defaults.
- An invalid answer is asked again (up to 3 times). Ctrl-C cancels with exit code 130 before the
  scanner is contacted.
- **Feeder or glass is automatic:** if the document feeder (ADF) has paper, the whole stack is scanned
  from it (one multi-page PDF); otherwise the flatbed glass is used. The "Scanning adf (auto: paper in
  feeder)" line shows which one was picked.
- Quick scans are **letter** size, color for jpg/png and grayscale for pdf, saved under the configured
  destination. Use `hpscan scan` for page size, mode, a forced source or explicit file names.
- Prefix: letters, digits, `_`, `-`, `.` and spaces, up to 64 characters, no `/`, and it can't start
  with `-`, `.` or a space. `--type/--quality/--prefix` must come **before** no command;
  `hpscan --type pdf status` is an error. `hpscan scan` has its own `--type/--quality/--prefix`.

### Other commands

```bash
# Verify the scanner is reachable
hpscan status
hpscan capabilities

# Grayscale PDF, auto-named under ~/Documents/HP_Scans/YYYY/MM/
hpscan scan

# Color PNG, auto-named
hpscan scan --format png        # --type png is the same

# Auto-named with a prefix and a quality preset (sets dpi unless -r is given)
hpscan scan --type jpg --quality high --prefix receipts
hpscan scan --source adf --quality low --prefix stack

# Color PNG at 300 dpi from the flatbed to an explicit file
hpscan scan photo.png

# Higher resolution color PNG, A4 area
hpscan scan photo.png --resolution 600 --page a4

# Grayscale document PDF from the ADF (all loaded sheets -> one PDF)
hpscan scan contract.pdf --source adf

# Color PDF
hpscan scan brochure.pdf --mode color

# Device-rendered PDF (smaller, exactly what the EWS Webscan page produces)
hpscan scan contract.pdf --native-pdf

# Higher JPEG quality (default 75)
hpscan scan photo.png --quality 95

# Force a protocol instead of auto-detecting
hpscan --protocol escl status

# Raw JPEGs straight from the device, one file per page (scan-1.jpg, scan-2.jpg, ...)
hpscan scan scan.jpg --source adf

# Different scanner
hpscan --host 192.168.1.50 scan out.png
HP_SCANNER_HOST=192.168.1.50 hpscan scan out.png

# Or save it once
hpscan config --host HP101F743EF639.local
```

### Where scans are saved

Bare `hpscan`, and `hpscan scan` with no output file, write to

```text
<destination>/YYYY/MM/[<prefix>-]document-<n>-YYYY-MM-DD-<TZ>-HH-MM-SS.pdf   # type pdf (default)
<destination>/YYYY/MM/[<prefix>-]image-<n>-YYYY-MM-DD-<TZ>-HH-MM-SS.png      # type png
<destination>/YYYY/MM/[<prefix>-]image-<n>-YYYY-MM-DD-<TZ>-HH-MM-SS.jpg      # type jpg
```

e.g. `~/Documents/HP_Scans/2026/11/document-3-2026-11-18-PST-14-05-09.pdf`, or with
`--prefix bleh`, `bleh-document-3-2026-11-18-PST-14-05-09.pdf`.

- `<destination>` defaults to `~/Documents/HP_Scans`.
- `<n>` is the scan number: one more than the highest number already in that month's folder
  (shared by `document-` and `image-` files, prefixed or not, so it restarts at 1 each month).
- `<TZ>` is the local time zone abbreviation; time is 24-hour.
- Missing folders are created. An explicit output path also gets its parent folders created.
- Multi-page PNG/JPEG scans add `-1`, `-2`, … to the auto name as usual.

### Document feeder pages

HP feeders don't know a page's length up front, so each feeder JPEG carries a placeholder height plus
the real line count in a JPEG `DNL` marker. Most decoders, Pillow included, can't read that ("broken
data stream when reading image file"). `hpscan` fixes the height before saving (`hp_scanner.fix_dnl_height`).
If a page still can't be converted, the scan isn't lost: the untouched pages are written next to the
target as `<name>-raw-1.jpg`, … and the error message lists them.

### Configuration

Settings live in `~/.config/hpscan/config.json`. Anything not set uses the built-in default.

```bash
hpscan config --show                   # effective settings and where each value comes from
hpscan config --host 192.168.4.195     # IP address ...
hpscan config --host scanner.lan       # ... hostname ...
hpscan config --host HP101F743EF639.local   # ... or Bonjour/mDNS name
hpscan config --scheme https           # http (default) or https
hpscan config --port 8080              # optional; default 8080 for http, 443 for https
hpscan config --dest ~/Scans           # scan destination (--destination also works; ~ and $VARS expand)
hpscan config --unset host --unset port     # back to defaults (destination, host, scheme, port)
```

```text
$ hpscan config --show
Config file: /Users/you/.config/hpscan/config.json
Destination: /Users/you/Scans  (config)
Host:        HP101F743EF639.local  (config)
Scheme:      http  (default)
Port:        8080  (default)
Scanner URL: http://HP101F743EF639.local:8080/
```

```json
{
  "destination": "/Users/you/Scans",
  "host": "HP101F743EF639.local",
  "scheme": null,
  "port": null
}
```

Every scanner command (`status`, `capabilities`, `scan`) uses these settings. Each value is
taken from the first place that sets it:

1. command-line flag: `--host`, `--port`, `--https` / `--http`
2. environment: `HP_SCANNER_HOST`, `HP_SCANNER_PORT`, `HP_SCANNER_SCHEME`
3. `~/.config/hpscan/config.json`
4. default: `192.168.4.195`, `http`, port `8080` (`443` for https), `~/Documents/HP_Scans`

Hosts are checked when saved: IPv4, IPv6 (bracketed automatically) or a DNS/Bonjour hostname.
Don't include `http://` or `:port` in `--host`; use `--scheme` and `--port`. Invalid values are
rejected and nothing is written. `hpscan config` never contacts the scanner.

**Finding the Bonjour name (macOS):** Bonjour lists a *service* name such as
`Officejet 6700 [3EF639]`, which is not a hostname. Resolve it to the `.local` host:

```bash
dns-sd -B _http._tcp local.                                  # list services (Ctrl-C to stop)
dns-sd -L "Officejet 6700 [3EF639]" _http._tcp local.        # "... can be reached at HP101F743EF639.local.:80"
```

**HTTPS caveat:** the Officejet 6700 serves TLS 1.2 with a self-signed certificate whose key
modern OpenSSL rejects as too weak, so `--https` fails the handshake against that model. Use
`http` for it; `https` is for newer devices with acceptable certificates.

### `hpscan scan` options

| Option | Values | Default |
| --- | --- | --- |
| `[output]` | file path | auto-named under the configured destination |
| `-f, --format`, `-t, --type` | `pdf`, `jpg`, `png` (`jpeg` also accepted) | inferred from the output extension; `pdf` when no output |
| `--prefix` | text (auto-named scans only) | none |
| `-m, --mode` | `color`, `gray`, `bw` | `color` for png/jpeg, `gray` for pdf |
| `-r, --resolution` | dpi supported by the device | the `--quality` preset's dpi, else `300` |
| `-s, --source` | `auto`, `platen`, `adf` | `auto`: feeder if it has paper, else the glass |
| `-p, --page` | `letter`, `legal`, `a4`, `a5` | `letter` |
| `-q, --quality` | 1-100 JPEG quality, or `low`/`medium`/`high` | `75` |
| `--native-pdf` | | assemble PDF client-side from JPEG pages |
| `--no-validate` | | validate settings against capabilities |

Global: `--host`, `--port`, `--https` / `--http`, `--protocol {auto,ledm,escl}`, `-v`.
`--host`/`--port`/scheme override the environment and the config file for that run.

Multi-page PNG/JPEG scans are written as `name-1.png`, `name-2.png`, …;
PDF scans always produce a single multi-page file.

### Officejet 6700 capabilities (as reported by the device)

| | Platen | ADF (simplex, 35 sheets) |
| --- | --- | --- |
| Resolutions | 75, 100, 200, 300, 600, 1200, 2400 dpi | 75, 100, 200, 300, 600 dpi |
| Color modes | RGB24, Grayscale8 | RGB24, Grayscale8 |
| Max area | 8.5 × 11.69 in (A4/Letter) | 8.5 × 14 in (Legal) |
| Native formats | `Jpeg`, `Raw`, `Pdf` | `Jpeg`, `Raw`, `Pdf` |

`ScanCaps` only advertises `Raw` and `Jpeg`, but the EWS Webscan page requests
`Format=Pdf` and the device happily returns `application/pdf`. By default `hpscan`
assembles PDFs from JPEG pages with Pillow (so an ADF stack becomes one file);
`--native-pdf` asks the device for PDF instead.

## Library API

```python
from hp_scanner import connect, ScanSettings, save_pages

client = connect(host="192.168.4.195")   # picks LedmClient or EsclClient
print(client.status())                   # ScannerStatus(state='Idle', adf_state='ScannerAdfEmpty')

settings = ScanSettings.for_page("letter", color_mode="RGB24", resolution=300, quality=90)
client.capabilities().validate(settings)

pages = client.scan(settings)            # list[bytes] of JPEG pages
save_pages(pages, "photo.png", "png", dpi=300)

# or use the configured destination + auto naming (creates YYYY/MM folders)
from hp_scanner import auto_output_path, load_config
save_pages(pages, auto_output_path(load_config().scan_root, "pdf", prefix="taxes"), "pdf")

# quality presets used by the CLI
from hp_scanner import QUALITY_PRESETS
QUALITY_PRESETS["high"]   # QualityPreset(name='high', resolution=300, jpeg_quality=90)
```

Both clients share one vocabulary (`ScanSettings` uses eSCL names such as `RGB24`,
`Grayscale8`, `Platen`, `Feeder`; `LedmClient` translates to `Color`/`Gray`/`Adf`).
LEDM-only tuning goes in `ScanSettings.extra`: `Brightness`, `Contrast`, `Gamma`
(0-2000, 1000 = neutral), `Threshold`, `SharpeningLevel`, `NoiseRemoval`.

Errors raise `ScannerError` subclasses: `ScannerBusyError` (not idle / ADF empty)
and `ScanJobError` (job rejected or returned no pages).

## Development

```bash
make help          # list targets
make dev           # venv + editable install with dev extras
make lint          # ruff
make test          # pytest (fully mocked, no scanner required)
make coverage      # pytest with coverage report; fails under 80%
make test-live     # status + capabilities against SCANNER_HOST (default 192.168.4.195)
make build         # sdist + wheel in dist/
make wheel         # wheel only
make check         # twine check dist/* + verify wheel version/deps against VERSION/requirements.txt
make verify-wheel  # just the wheel metadata check
make version       # print the current version
make bump-patch    # 0.0.1 -> 0.0.2 (also bump-minor, bump-major); edits VERSION only
make install       # build + install for your user (or INSTALL_VENV=path / active venv); UPDATE_PATH=1 adds to PATH
make uninstall     # remove that install (UPDATE_PATH=1 also removes the PATH entry)
make install-wheel # install the built wheel into the dev .venv (replaces the editable install)
make clean         # remove build artifacts and caches
make distclean     # also remove .venv
make all           # lint + test + build + check
```

Override the scanner for live targets: `make test-live SCANNER_HOST=192.168.1.50`.

### Versioning, dependencies and releases

- **Version**: `VERSION` holds a [SemVer](https://semver.org) `MAJOR.MINOR.PATCH` (no leading zeros, so
  the first release is `0.0.1`; the patch number simply grows: `0.0.9` → `0.0.10` → … `0.0.100`).
  `pyproject.toml` reads it dynamically (`[tool.hatch.version]`), and `hp_scanner.__version__` /
  `hpscan --version` come from the installed package metadata.
- **Dependencies**: `requirements.txt` (runtime) and `requirements-dev.txt` (the `[dev]` extra) are the
  single source; the `hatch-requirements-txt` build plugin copies them into the wheel metadata.
  After changing either file (or `VERSION`), `make dev` reinstalls automatically.
- **CI** (`.github/workflows/ci.yml`, on pushes to `main`/`develop` and on PRs): ruff + pytest with an 80%
  coverage gate on Python 3.10–3.14, then builds the sdist and wheel, runs `twine check` and
  `scripts/verify_wheel.py`, installs the wheel into a clean venv (`pip check`, `hpscan --version`) and
  uploads `dist/` as the `hp-scanner-<version>` artifact.
- **Release** (`.github/workflows/release.yml`): Actions → *Release* → *Run workflow* on `main`, choose
  `patch` / `minor` / `major`, or `none` to release the current `VERSION` as-is (use `none` for the
  first `0.0.1`). It tests, bumps `VERSION`, builds and verifies, commits `chore: release vX.Y.Z`, tags
  `vX.Y.Z`, pushes both to `main` and creates a GitHub Release with the wheel and sdist attached. The release
  notes start with install commands pinned to that version (`scripts/release_notes.py`), followed by
  GitHub's generated changelog. Finally it installs the published wheel **from its download URL** into a
  clean venv as a check. It refuses to reuse an existing tag. If `main` is branch-protected, allow
  `github-actions[bot]` to push. From a terminal: `gh workflow run release.yml --ref main -f bump=patch`.

### How it works

Protocol detection: `GET /Scan/Status` returning 200 means LEDM; otherwise eSCL.

**LEDM** (reverse-engineered from the Officejet 6700's own Webscan page with
Playwright, cross-checked against HPLIP's `scan/sane/bb_ledm.c`):

1. `GET /Scan/Status` — `ScannerState` must be `Idle`; `AdfState` is `Empty`/`Loaded`
2. `GET /Scan/ScanCaps` — resolutions, `ColorType`s (`Color8`/`Gray8`/`K1`), platen/ADF extents
3. `POST /Scan/Jobs` with a `<scan:ScanJob>` body (resolution, region in 1/300 in,
   `Format`, `CompressionQFactor = 100 - quality`, `ColorSpace`, `BitDepth`,
   `InputSource`, `ToneMap`, `ContentType`) — `201 Created` + `Location: /Jobs/JobList/N`
4. Poll `GET /Jobs/JobList/N`: each page appears as `PreScanPage` with `PageState`
   `PreparingScan` → `ReadyToUpload` and a `BinaryURL`
5. `GET /Scan/Jobs/N/Pages/M` promptly — the device cancels a page nobody downloads
   (`CanceledByDevice`)
6. Repeat until `JobState` is `Completed` (`PostScanPage` / `UploadCompleted`);
   `Canceled`/`Aborted` end the job; `Blocked` means keep waiting
7. On error or Ctrl-C: `PUT /Jobs/JobList/N` with `<j:JobState>Canceled</j:JobState>`

The device also exposes self-describing manifests (`/DevMgmt/DiscoveryTree.xml`,
`/Scan/ScanJobManifest.xml`, `/Jobs/JobsManifest.xml`) listing the verbs each
resource accepts.

**eSCL**:

1. `GET /eSCL/ScannerStatus` — ensure the scanner is `Idle` (and the ADF is loaded for feeder scans)
2. `GET /eSCL/ScannerCapabilities` — validate resolution, color mode and page size
3. `POST /eSCL/ScanJobs` with a `ScanSettings` XML body — returns a job `Location`
4. `GET {job}/NextDocument` repeatedly — `200` yields a page, `503` means wait, `404` means done
5. `DELETE {job}` — release the job

Finally, JPEG pages are converted to PNG or combined into a PDF with Pillow
(native PDF pages are written through untouched).

## License

MIT
