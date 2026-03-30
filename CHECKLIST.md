# MLB-TCKR Build & Run Checklist

## Python Source Files
- [ ] MLB-TCKR.py (main application)
- [ ] mlb_ticker_utils_cython.pyx (Cython optimizations)
- [ ] ticker_utils_cython.pyx (if referenced)
- [ ] ticker_utils_cython.c (if building Cython extension)
- [ ] setup_mlb_cython.py (Cython build script)
- [ ] setup_cython.py (if used for Cython build)

## PyInstaller/Build Files (if making an executable)
- [ ] MLB-TCKR.spec or MLB-TCKR-console.spec
- [ ] pyi_rth_mlb_qt.py
- [ ] pyi_rth_requests_charset.py
- [ ] pyi_rth_unicodedata.py

## Assets
- [ ] led_board-7.ttf (font)
- [ ] Ozone-xRRO.ttf (font)
- [ ] Gotham Black.ttf (font, if used)
- [ ] MLB-TCKR.images/ (folder with team logo PNGs, if present)

## Dependencies
- [ ] requirements.txt (install with pip)
  - [ ] PyQt5
  - [ ] statsapi
  - [ ] numpy
  - [ ] Cython
  - [ ] Any other listed packages

## Documentation (optional)
- [ ] README.md or MLB-TCKR-README.md

## Other
- [ ] Ensure all referenced files/paths exist and are accessible
