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
import site

# ---------------------------------------------------------------------------
# Collect PyQt5 via PyInstaller's native hook mechanism.
# collect_all() properly handles user-installed PyQt5 (AppData path) and
# avoids the PYZ/binary collision that occurs when hiddenimports and
# explicit binaries both process the same .pyd extension modules.
# ---------------------------------------------------------------------------
from PyInstaller.utils.hooks import collect_all as _pyi_collect_all

_pyqt5_datas    = []
_pyqt5_binaries = []
_pyqt5_hidden   = []

# Qt submodules to exclude (heavy, unused by this app)
_QT_EXCLUDE = (
    # Qt module names
    'Qt3D', 'QtWebEngine', 'QtWebEngineCore', 'QtWebEngineWidgets',
    'QtMultimedia', 'QtMultimediaWidgets',
    'QtQml', 'QtQuick', 'QtQuickWidgets',
    'QtSql', 'QtTest', 'QtBluetooth', 'QtPositioning',
    'QtSensors', 'QtSerialPort', 'QtWebSockets',
    'QtXml', 'QtXmlPatterns',
    # Plugin subdirectories whose Qt3D/WebEngine/SQL DLLs are not bundled
    'geometryloaders', 'renderers', 'sceneparsers',
    'sqldrivers', 'webview', 'geoservices',
    # Python 2 compat shims that don't exist in modern PyQt5
    'port_v2',
)

def _qt_keep(name):
    return not any(x.lower() in name.lower() for x in _QT_EXCLUDE)

try:
    import PyQt5
    _pyqt5_path = os.path.dirname(PyQt5.__file__)
    print(f'[SPEC] PyQt5 found at: {_pyqt5_path}')

    _raw_datas, _raw_bins, _raw_hidden = _pyi_collect_all('PyQt5')
    _pyqt5_datas    = [(s, d) for s, d in _raw_datas    if _qt_keep(s)]
    _pyqt5_binaries = [(s, d) for s, d in _raw_bins     if _qt_keep(s)]
    _pyqt5_hidden   = [h      for h    in _raw_hidden    if _qt_keep(h) and h != 'sip']
    print(f'[SPEC] collect_all PyQt5: '
          f'{len(_pyqt5_binaries)} bins, {len(_pyqt5_datas)} datas, '
          f'{len(_pyqt5_hidden)} hidden')
except Exception as _e:
    print(f'[SPEC] collect_all PyQt5 ERROR: {_e}')

# ---------------------------------------------------------------------------
# Locate the Cython extension matching the current Python interpreter
# e.g. mlb_ticker_utils_cython.cp313-win_amd64.pyd
# ---------------------------------------------------------------------------
_spec_dir = os.path.dirname(os.path.abspath(SPEC))
_appdata_mlb_dir = os.path.join(os.environ.get('APPDATA', ''), 'MLB-TCKR')
_appdata_images_dir = os.path.join(_appdata_mlb_dir, 'MLB-TCKR.images')
_pyd_abi_tag = f'cp{sys.version_info.major}{sys.version_info.minor}-win_amd64.pyd'
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
import certifi
_datas = [
    # System-tray / taskbar icon
    ('mlb.ico',          '.'),
    (os.path.join('espnlogos', 'png', 'mlb-reverse.png'), '.'),
    # Certifi CA bundle for requests/SSL
    (certifi.where(), 'certifi'),
    # Play ball sound effect
    ('play-ball-v2-ball-baseball-hammond-music-organ-cgeffex.mp3', '.'),
]

# Include fonts from the project-root fonts/ directory (primary font location)
_fonts_dir = os.path.join(_spec_dir, 'fonts')
if os.path.isdir(_fonts_dir):
    _font_count = 0
    for _font in glob.glob(os.path.join(_fonts_dir, '*.ttf')) + glob.glob(os.path.join(_fonts_dir, '*.otf')):
        _entry = (os.path.abspath(_font), '.')
        if _entry not in _datas:
            _datas.append(_entry)
            _font_count += 1
    print(f'[SPEC] Bundled {_font_count} font(s) from fonts/')
else:
    print(f'[SPEC] WARNING: fonts/ directory not found at {_fonts_dir}')

# Include any extra .ttf / .otf fonts sitting in the project root directory
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

# Include ESPN logos (espnlogos/png/*.png) as MLB-TCKR.images\* so the bundled
# exe ships with pre-downloaded team logo PNGs without needing AppData populated.
_espn_logos_dir = os.path.join(_spec_dir, 'espnlogos', 'png')
if os.path.isdir(_espn_logos_dir):
    _espn_count = 0
    for _img in glob.glob(os.path.join(_espn_logos_dir, '*.png')):
        _entry = (os.path.abspath(_img), 'MLB-TCKR.images')
        if _entry not in _datas:
            _datas.append(_entry)
            _espn_count += 1
    print(f'[SPEC] Bundled {_espn_count} ESPN logo(s) from espnlogos/png')
else:
    print(f'[SPEC] WARNING: espnlogos/png not found at {_espn_logos_dir} — logos not bundled')

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ['MLB-TCKR.py'],
    pathex=[_spec_dir],
    binaries=_cython_binaries + _pyqt5_binaries,
    datas=_datas + _pyqt5_datas,
    hiddenimports=[
        # sip is bundled inside PyQt5 on Python 3.14+ (no standalone top-level sip)
        'PyQt5.sip',
        # MLB Stats API
        'statsapi',
        # Cython extension dependency
        'numpy',
        'numpy.core',
        'numpy.core.multiarray',
        # requests / SSL stack
        'requests',
        'requests.adapters',
        'requests.auth',
        'requests.exceptions',
        'urllib3',
        'urllib3.util.retry',
        'certifi',
        'charset_normalizer',
        'charset_normalizer.md',
        'charset_normalizer.models',
        'charset_normalizer.cd',
        'charset_normalizer.utils',
        'charset_normalizer.constant',
        'idna',
        'idna.core',
        'idna.codec',
        # stdlib modules that may be missed in onefile mode
        'unicodedata',
        'encodings',
        'encodings.idna',
        'encodings.utf_8',
        'encodings.ascii',
        'encodings.latin_1',
        'encodings.cp1252',
        'json',
        'datetime',
        'traceback',
        'ctypes',
        'ctypes.wintypes',
        # SVG rendering
        'PyQt5.QtSvg',
    ] + _pyqt5_hidden,
    hookspath=['.'],          # picks up pyi_rth_requests_charset.py as a hook
    hooksconfig={},
    runtime_hooks=['pyi_rth_unicodedata.py', 'pyi_rth_mlb_qt.py'],
    excludes=[
        # Heavy scientific stack – not used by this app
        # NOTE: numpy must NOT be excluded — the Cython extension links against it.
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
        # Qt modules not used by this app
        'PyQt5.Qt3DAnimation',
        'PyQt5.Qt3DCore',
        'PyQt5.Qt3DExtras',
        'PyQt5.Qt3DInput',
        'PyQt5.Qt3DLogic',
        'PyQt5.Qt3DRender',
        'PyQt5.QtWebEngine',
        'PyQt5.QtWebEngineCore',
        'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtMultimedia',
        'PyQt5.QtMultimediaWidgets',
        'PyQt5.QtQml',
        'PyQt5.QtQuick',
        'PyQt5.QtQuickWidgets',
        'PyQt5.QtSql',
        'PyQt5.QtTest',
        'PyQt5.QtBluetooth',
        'PyQt5.QtPositioning',
        'PyQt5.QtSensors',
        'PyQt5.QtSerialPort',
        'PyQt5.QtWebSockets',
        'PyQt5.QtXml',
        'PyQt5.QtXmlPatterns',
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
        # Qt DLLs: compress poorly and sometimes break with UPX
        'Qt5Core.dll', 'Qt5Gui.dll', 'Qt5Widgets.dll',
        'Qt5Network.dll', 'Qt5PrintSupport.dll',
        # Python extension modules (.pyd) MUST NOT be UPX-compressed –
        # UPX corrupts their import tables, causing ImportError at runtime.
        f'QtWidgets.{_pyd_abi_tag}',
        f'QtCore.{_pyd_abi_tag}',
        f'QtGui.{_pyd_abi_tag}',
        f'QtNetwork.{_pyd_abi_tag}',
        f'QtPrintSupport.{_pyd_abi_tag}',
        f'sip.{_pyd_abi_tag}',
        f'mlb_ticker_utils_cython.{_pyd_abi_tag}',
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
    version='version-mlb-tckr.txt',
    # Embed a Windows application manifest so the AppBar API works correctly
    # and the app is DPI-aware (matches AA_EnableHighDpiScaling in code)
    uac_admin=False,
    uac_uiaccess=False,
)
