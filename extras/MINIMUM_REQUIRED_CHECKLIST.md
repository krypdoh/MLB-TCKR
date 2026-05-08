# MLB-TCKR Minimum Required Files Checklist

Use this quick checklist to verify you have the minimum Python files for each workflow.

## 1) Run From Source Only

- [ ] MLB-TCKR.py (required)

Notes:
- Runtime hooks are not used when launching from source.
- Cython is optional; app falls back to pure Python scrolling.

## 2) Build EXE (Pure-Python Fallback, No Cython)

- [ ] MLB-TCKR.py (required)
- [ ] pyi_rth_mlb_qt.py (required by current .spec runtime_hooks)
- [ ] pyi_rth_unicodedata.py (required by current .spec runtime_hooks)

Optional:
- [ ] pyi_rth_requests_charset.py (optional compatibility hook)

Notes:
- Current spec files can build without a Cython .pyd.
- Runtime falls back to Python scrolling if Cython module is absent.

## 3) Build EXE (With Cython Acceleration)

Required for build + runtime acceleration:
- [ ] MLB-TCKR.py
- [ ] setup_mlb_cython.py
- [ ] mlb_ticker_utils_cython.pyx
- [ ] pyi_rth_mlb_qt.py
- [ ] pyi_rth_unicodedata.py

Generated during build:
- [ ] mlb_ticker_utils_cython.cpXXX-win_amd64.pyd (Python-version specific output)

Optional:
- [ ] pyi_rth_requests_charset.py

Notes:
- Run setup_mlb_cython.py build_ext --inplace before PyInstaller build.
- If the .pyd does not match the Python ABI, EXE still runs with Python fallback.

## Not Required For Current Main App/EXE Path

- [ ] setup_cython.py (legacy/alternate Cython build script)
- [ ] ticker_utils_cython.pyx (legacy/alternate Cython source)
- [ ] extras/convert_svg_to_png.py (asset utility only)
