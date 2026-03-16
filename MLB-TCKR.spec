# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for MLB-TCKR
# Build:  pyinstaller MLB-TCKR.spec
# Output: dist\MLB-TCKR.exe  (single-file, no console)
#
# Requirements: pyinstaller >= 6.0  (cipher parameter removed in 6.0)

import sys
import os
import glob

# ---------------------------------------------------------------------------
# Locate the Cython extension matching the current Python interpreter
# e.g. mlb_ticker_utils_cython.cp313-win_amd64.pyd
# ---------------------------------------------------------------------------
_spec_dir = os.path.dirname(os.path.abspath(SPEC))
_appdata_mlb_dir = os.path.join(os.environ.get('APPDATA', ''), 'MLB-TCKR')
_appdata_images_dir = os.path.join(_appdata_mlb_dir, 'MLB-TCKR.images')
_pyd_pattern = os.path.join(
    _spec_dir,
    f'mlb_ticker_utils_cython.cp{sys.version_info.major}{sys.version_info.minor}-win_amd64.pyd'
)
_pyd_matches = glob.glob(_pyd_pattern)
_cython_binaries = [(_pyd_matches[0], '.')] if _pyd_matches else []

if _cython_binaries:
    print(f'[SPEC] Bundling Cython extension: {os.path.basename(_cython_binaries[0][0])}')
else:
    print('[SPEC] No matching Cython .pyd found – falling back to pure-Python scrolling at runtime')

# ---------------------------------------------------------------------------
# Data files to bundle alongside the executable
# ---------------------------------------------------------------------------
_datas = [
    # Fonts loaded via QFontDatabase at runtime
    ('led_board-7.ttf',  '.'),
    ('SubwayTicker.ttf', '.'),
    ('PixelGosub-ZaRz.ttf', '.'),
    ('PixelFont7-G02A.ttf', '.'),
    # System-tray / taskbar icon
    ('mlb.ico',          '.'),
    ('mlb-reverse.png',  '.'),
]

# Include any extra .ttf / .otf fonts sitting in the project directory
for _font in glob.glob(os.path.join(_spec_dir, '*.ttf')) + glob.glob(os.path.join(_spec_dir, '*.otf')):
    _entry = (os.path.abspath(_font), '.')
    if _entry not in _datas:
        _datas.append(_entry)

# Include any fonts from %APPDATA%\MLB-TCKR so user-added fonts are bundled.
if os.path.isdir(_appdata_mlb_dir):
    for _font in glob.glob(os.path.join(_appdata_mlb_dir, '*.ttf')) + glob.glob(os.path.join(_appdata_mlb_dir, '*.otf')):
        _entry = (os.path.abspath(_font), '.')
        if _entry not in _datas:
            _datas.append(_entry)

# Include project logos (if folder exists) as MLB-TCKR.images\* in bundle.
_project_images_dir = os.path.join(_spec_dir, 'MLB-TCKR.images')
if os.path.isdir(_project_images_dir):
    for _img in glob.glob(os.path.join(_project_images_dir, '*')):
        if os.path.isfile(_img):
            _entry = (os.path.abspath(_img), 'MLB-TCKR.images')
            if _entry not in _datas:
                _datas.append(_entry)

# Include AppData logos as MLB-TCKR.images\* in bundle for automatic startup loading.
if os.path.isdir(_appdata_images_dir):
    for _img in glob.glob(os.path.join(_appdata_images_dir, '*')):
        if os.path.isfile(_img):
            _entry = (os.path.abspath(_img), 'MLB-TCKR.images')
            if _entry not in _datas:
                _datas.append(_entry)

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ['MLB-TCKR.py'],
    pathex=[_spec_dir],
    binaries=_cython_binaries,
    datas=_datas,
    hiddenimports=[
        # PyQt5 internals that PyInstaller sometimes misses
        'PyQt5.sip',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.QtNetwork',
        # Qt platform plugin dependency
        'PyQt5.Qt5',
        # MLB Stats API
        'statsapi',
        # requests / SSL stack
        'requests',
        'requests.adapters',
        'requests.auth',
        'requests.exceptions',
        'urllib3',
        'urllib3.util.retry',
        'certifi',
        'charset_normalizer',
        'charset_normalizer.md__mypyc',
        'idna',
        # stdlib modules that may be missed in onefile mode
        'json',
        'datetime',
        'traceback',
        'ctypes',
        'ctypes.wintypes',
    ],
    hookspath=['.'],          # picks up pyi_rth_requests_charset.py as a hook
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy scientific stack – not used by this app
        'numpy',
        'pandas',
        'matplotlib',
        'scipy',
        'numba',
        'llvmlite',
        # GUI toolkits we don't need
        'tkinter',
        '_tkinter',
        'wx',
        # Test / dev tools
        'pytest',
        'IPython',
        'notebook',
        'Cython',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# Single-file EXE  (change to onedir=False / collect_* below for a folder build)
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MLB-TCKR',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                 # Compress with UPX if available (smaller EXE)
    upx_exclude=[
        # Qt DLLs compress poorly and sometimes break with UPX
        'Qt5Core.dll',
        'Qt5Gui.dll',
        'Qt5Widgets.dll',
    ],
    runtime_tmpdir=None,
    console=False,            # No console window – pure GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # PyInstaller 5.3+ accepts PNG; for older versions convert mlb.png to mlb.ico
    icon='mlb.ico',
    version_info=None,
    # Embed a Windows application manifest so the AppBar API works correctly
    # and the app is DPI-aware (matches AA_EnableHighDpiScaling in code)
    uac_admin=False,
    uac_uiaccess=False,
)
