# MLB-TCKR Build & Run Checklist

## Python Source Files (Required)
- [ ] MLB-TCKR.py (main application — required)
- [ ] mlb_ticker_utils_cython.pyx (Cython scroll extension source)
- [ ] setup_mlb_cython.py (Cython build script — used by build_performance.bat)

## Cython Build Outputs (Required at Runtime)
- [ ] mlb_ticker_utils_cython.cp313-win_amd64.pyd (built Cython extension, Python 3.13)
  - Note: cp314 variant also present for Python 3.14 — only the one matching the active interpreter is needed
- [ ] mlb_ticker_utils_cython.c (generated C file — intermediate build artifact, not needed at runtime)

## PyInstaller / Build Files
- [ ] MLB-TCKR.spec (main PyInstaller spec — single-file, no-console EXE)
- [ ] MLB-TCKR-console.spec (alternate spec — console EXE for debugging)
- [ ] build_performance.bat (full build automation: Cython → versioning → PyInstaller → cleanup)
- [ ] pyi_rth_mlb_qt.py (runtime hook: Qt plugin paths, CA bundle caching to AppData)
- [ ] pyi_rth_requests_charset.py (runtime hook: charset_normalizer discovery)
- [ ] pyi_rth_unicodedata.py (runtime hook: unicodedata availability in frozen exe)

## Fonts (Required — bundled into EXE and loaded at runtime)
- [ ] led_board-7.ttf
- [ ] SubwayTicker.ttf
- [ ] PixelGosub-ZaRz.ttf
- [ ] PixelFont7-G02A.ttf
- [ ] Ozone-xRRO.ttf
  - Note: Duplicates exist in `fonts/` subfolder AND project root AND `docs/` — only root-level copies are bundled by the spec

## Icons / Images (Required — bundled into EXE)
- [ ] mlb.ico (taskbar / system-tray icon)
- [ ] mlb-reverse.png (alternate icon used in UI)

## Team Logos (Required — bundled as MLB-TCKR.images/ in EXE)
- [ ] espnlogos/png/*.png (30 team logo PNGs: ari, atl, bal, bos, chc, chw, cin, cle, col, det, hou, kc, laa, lad, mia, mil, min, nym, nyy, oak, phi, pit, sd, sea, sf, stl, tb, tex, tor, wsh)
  - Also loaded at runtime from %APPDATA%\MLB-TCKR\MLB-TCKR.images\ (user-populated)
  - Also loaded from MLB-TCKR.images\ in project dir if present

## Conference Logos (Runtime UI — may be optional)
- [ ] american.png (American League logo — displayed in ticker)
- [ ] national.png (National League logo — displayed in ticker)

## SSL / Networking (Auto-bundled)
- [ ] certifi CA bundle (auto-located via `certifi.where()` in spec; cached to AppData by runtime hook)

## Version File
- [ ] version-mlb-tckr.txt (read by build_performance.bat for auto-increment; read by app at runtime)

## Dependencies (install via pip)
- [ ] requirements.txt
  - [ ] PyQt5
  - [ ] statsapi
  - [ ] numpy
  - [ ] Cython
  - [ ] requests
  - [ ] certifi
  - [ ] charset-normalizer
  - [ ] idna
  - [ ] urllib3

## Documentation
- [ ] README.md
- [ ] MLB-TCKR-README.md
- [ ] CHANGELOG.txt
- [ ] PERFORMANCE.md

---

## Extra Files (NOT required to run or build the program)

These files exist in the repository but are not needed to run, build, or bundle MLB-TCKR:

### Duplicate / Superseded Source
- `MLB-TCKR - Copy.py` — stale copy of main file; not used
- `MLB-TCKR-NEW.py` — development scratch file; not used
- `ticker_utils_cython.pyx` — older/duplicate Cython source; spec uses `mlb_ticker_utils_cython.pyx`
- `ticker_utils_cython.c` — generated from old pyx; not used in build
- `ticker_utils_cython.cp313-win_amd64.pyd` — built from old pyx; not used at runtime
- `setup_cython.py` — old setup script; build uses `setup_mlb_cython.py`
- `mlb_ticker_utils_cython.cp314-win_amd64.pyd` — Python 3.14 variant (keep only if targeting 3.14)

### Logo Download Scripts (Dev Utility Only)
- `espnlogos/download_mlb_logos.ps1` — one-time download script; logos already in `espnlogos/png/`
- `newlogos/download_mlb_logos.ps1` — duplicate download script
- `newlogos/getlogosmlb.ps1` — alternate download script
- `newlogos/png/` — alternate/unused logo set (not referenced in spec or app)

### Docs Folder (Marketing/Screenshots — not needed for app)
- `docs/` — all contents: screenshots, MP4 recordings, duplicate font copies, HTML/CSS/JS for project web page

### Fonts Subfolder (Redundant — root-level copies are used)
- `fonts/` — duplicate of root-level .ttf files; spec bundles from root, not this folder

### Dev / Test Files
- `convert_svg_to_png.py` — one-time utility to convert logos; not needed at runtime

### Miscellaneous
- `debug.log` — local debug output; should not be committed
- `file-list.txt` — scratch file list; not used by app or build
- `mlb.bmp` — bitmap version of icon; spec uses `mlb.ico` and `mlb-reverse.png`
- `mlb-orig.ico` — old icon variant; not referenced in spec
- `mlb.png` — unused PNG icon variant
- `play-ball-v2-ball-baseball-hammond-music-organ-cgeffex.mp3` — audio file; not referenced in the application code
- `dist/MLB-TCKR.exe - Shortcut.lnk` — Windows shortcut; not a build artifact to track
- `build/` — PyInstaller intermediate build cache; safe to delete before a clean build
- `.cursor/`, `.kilo/`, `.vscode/`, `.hintrc` — IDE/editor config; not needed for build or runtime
