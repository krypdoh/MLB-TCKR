"""Runtime hook — runs before main script in frozen (PyInstaller) builds.

Why this hook exists
--------------------
PyInstaller onefile EXEs extract everything to a temporary _MEI{n} folder.
When the app restarts (e.g. switching monitor), it spawns a child process
and then the parent quits.  The parent's atexit handler deletes _MEI{n}.
Any file that the child hasn't yet opened (fonts, images, qwindows.dll,
cacert.pem) gets deleted before the child can use it → crash/missing files.

Fix: on every startup, copy all volatile assets from _MEIPASS to permanent
AppData locations.  The main script already searches those locations first.

Folder layout after first run
------------------------------
%APPDATA%\\MLB-TCKR\\               ← APPDATA_DIR (fonts, standalone images)
%LOCALAPPDATA%\\MLB-TCKR\\certifi\\  ← cacert.pem  (SSL)
%LOCALAPPDATA%\\MLB-TCKR\\qt-platforms\\  ← qwindows.dll etc.  (Qt)
"""

import sys
import os
import shutil
import glob as _glob


def _cache_file(src, dst_dir, label=''):
    """Copy *src* to *dst_dir* if missing or size-changed.  Returns dst path."""
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(src))
    if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
        shutil.copy2(src, dst)
        if label:
            print(f"[Cache] {label}: {os.path.basename(src)}")
    return dst


if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    _meipass        = sys._MEIPASS
    _local_appdata  = os.environ.get('LOCALAPPDATA', '')
    _roaming_appdata = os.environ.get('APPDATA', '')

    # AppData directories — mirrors what APPDATA_DIR uses in the main script
    _appdata_dir    = os.path.join(_roaming_appdata, 'MLB-TCKR') if _roaming_appdata else ''
    _local_mlb_dir  = os.path.join(_local_appdata,   'MLB-TCKR') if _local_appdata  else ''

    # ------------------------------------------------------------------
    # 1. Register Qt5/bin so Windows finds Qt DLLs regardless of PATH
    # ------------------------------------------------------------------
    _qt5_bin = os.path.join(_meipass, 'PyQt5', 'Qt5', 'bin')
    if os.path.isdir(_qt5_bin):
        try:
            os.add_dll_directory(_qt5_bin)
        except (OSError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # 2. Cache qwindows.dll (and other platform DLLs) to LocalAppData
    #    qwindows.dll has no open handle until QApplication() is created,
    #    so it gets deleted by the parent's atexit before the child loads it.
    # ------------------------------------------------------------------
    _src_platforms   = os.path.join(_meipass, 'PyQt5', 'Qt5', 'plugins', 'platforms')
    _cache_platforms = os.path.join(_local_mlb_dir, 'qt-platforms') if _local_mlb_dir else ''

    if _cache_platforms and os.path.isdir(_src_platforms):
        try:
            _n = 0
            for _dll in os.listdir(_src_platforms):
                if _dll.lower().endswith('.dll'):
                    _cache_file(os.path.join(_src_platforms, _dll), _cache_platforms)
                    _n += 1
        except Exception as _e:
            print(f"[Qt] Platform DLL cache failed: {_e}")
            _cache_platforms = ''

    _platform_plugins = (
        _cache_platforms if _cache_platforms and os.path.isdir(_cache_platforms)
        else _src_platforms
    )

    _qt_plugins = os.path.join(_meipass, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(_qt_plugins):
        os.environ['QT_PLUGIN_PATH'] = _qt_plugins
        print(f"[Qt] Plugin path set to: {_qt_plugins}")
    if os.path.isdir(_platform_plugins):
        os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = _platform_plugins
        print(f"[Qt] Platform plugins: {_platform_plugins}")

    # ------------------------------------------------------------------
    # 3. Cache certifi CA bundle to LocalAppData
    # ------------------------------------------------------------------
    _src_cacert      = os.path.join(_meipass, 'certifi', 'cacert.pem')
    _cache_cacert_dir = os.path.join(_local_mlb_dir, 'certifi') if _local_mlb_dir else ''

    if _cache_cacert_dir and os.path.isfile(_src_cacert):
        try:
            _dst_cacert = _cache_file(_src_cacert, _cache_cacert_dir)
            os.environ['REQUESTS_CA_BUNDLE'] = _dst_cacert
            os.environ['SSL_CERT_FILE']      = _dst_cacert
        except Exception as _e:
            print(f"[SSL] Certifi cache failed: {_e}")
            os.environ['REQUESTS_CA_BUNDLE'] = _src_cacert
            os.environ['SSL_CERT_FILE']      = _src_cacert

    # ------------------------------------------------------------------
    # 4. Cache fonts + standalone images to %APPDATA%\MLB-TCKR\
    #    The main script's APPDATA_DIR is %APPDATA%\MLB-TCKR and is the
    #    FIRST place it looks for fonts and images — so files here are
    #    always found even after _MEIPASS is deleted.
    # ------------------------------------------------------------------
    _ASSET_EXTS   = {'.ttf', '.otf', '.png', '.ico'}
    _ASSET_FILES  = {'mlb-reverse.png', 'mlb.ico', 'mlb.png',
                     'led_board-7.ttf', 'SubwayTicker.ttf',
                     'PixelGosub-ZaRz.ttf', 'PixelFont7-G02A.ttf',
                     'Ozone-xRRO.ttf'}

    if _appdata_dir:
        try:
            os.makedirs(_appdata_dir, exist_ok=True)
            for _fname in os.listdir(_meipass):
                _ext = os.path.splitext(_fname)[1].lower()
                if _ext in _ASSET_EXTS and _fname in _ASSET_FILES:
                    _cache_file(os.path.join(_meipass, _fname), _appdata_dir)
        except Exception as _e:
            print(f"[Assets] AppData cache failed: {_e}")

    # ------------------------------------------------------------------
    # 5. Diagnostics: list bundled .pyd modules
    # ------------------------------------------------------------------
    _pyqt5_dir = os.path.join(_meipass, 'PyQt5')
    if os.path.isdir(_pyqt5_dir):
        _pyds  = sorted(_glob.glob(os.path.join(_pyqt5_dir, '*.pyd')))
        _names = ', '.join(os.path.basename(f).split('.')[0] for f in _pyds)
        print(f"[Qt] PyQt5 .pyd modules ({len(_pyds)}): {_names or 'NONE FOUND'}")

    # ------------------------------------------------------------------
    # 6. Pre-import PyQt5 so DLLs are memory-mapped (locked) before the
    #    parent's atexit can delete them.
    # ------------------------------------------------------------------
    try:
        import PyQt5.QtCore    # noqa: F401
        import PyQt5.QtGui     # noqa: F401
        import PyQt5.QtWidgets # noqa: F401
        import PyQt5.QtNetwork # noqa: F401
        print("[Qt] Pre-loaded: QtCore, QtGui, QtWidgets, QtNetwork")

        import PyQt5.QtCore as _qc
        print(f"[Qt] libraryPaths: {_qc.QCoreApplication.libraryPaths()}")
        _qt_conf_exists = _qc.QFile.exists(':/qt/etc/qt.conf')
        print(f"[Qt] :/qt/etc/qt.conf exists: {_qt_conf_exists}")
        if _qt_conf_exists:
            _f = _qc.QFile(':/qt/etc/qt.conf')
            _f.open(_qc.QFile.ReadOnly)
            _conf = bytes(_f.readAll()).decode('latin1', errors='replace').strip()
            _f.close()
            print(f"[Qt] qt.conf content: {_conf!r}")
        print(f"[Qt] QT_PLUGIN_PATH env: {os.environ.get('QT_PLUGIN_PATH', 'NOT SET')}")
        print(f"[Qt] QT_QPA_PLATFORM_PLUGIN_PATH env: {os.environ.get('QT_QPA_PLATFORM_PLUGIN_PATH', 'NOT SET')}")
    except Exception as _qt_err:
        print(f"[Qt ERROR] Pre-load failed: {_qt_err}")
        import traceback as _tb
        _tb.print_exc()


if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # Running in PyInstaller bundle
    _meipass = sys._MEIPASS

    # ------------------------------------------------------------------
    # 1. Ensure Qt5/bin DLLs are findable BEFORE any inherited PATH
    #    entries from a parent process can interfere.  We explicitly call
    #    os.add_dll_directory so Windows finds the DLLs regardless of
    #    PATH ordering.
    # ------------------------------------------------------------------
    _qt5_bin = os.path.join(_meipass, 'PyQt5', 'Qt5', 'bin')
    if os.path.isdir(_qt5_bin):
        try:
            os.add_dll_directory(_qt5_bin)
        except (OSError, AttributeError):
            pass

    # 2. Set Qt plugin paths; cache platform DLLs to AppData so they
    #    survive _MEIPASS cleanup when the parent process exits.
    _qt_plugins   = os.path.join(_meipass, 'PyQt5', 'Qt5', 'plugins')
    _src_platforms = os.path.join(_qt_plugins, 'platforms')

    # --- Permanent AppData cache for platforms/ DLLs -------------------
    # qwindows.dll is loaded lazily (only on QApplication creation), so
    # it has no open handle when the parent's atexit deletes _MEIPASS.
    # Copying it to a permanent location makes it immune to that sweep.
    _local_appdata   = os.environ.get('LOCALAPPDATA', '')
    _cache_platforms = (
        os.path.join(_local_appdata, 'MLB-TCKR', 'qt-platforms')
        if _local_appdata else ''
    )

    if _cache_platforms and os.path.isdir(_src_platforms):
        try:
            os.makedirs(_cache_platforms, exist_ok=True)
            _copied = 0
            for _dll in os.listdir(_src_platforms):
                if _dll.lower().endswith('.dll'):
                    _src_f = os.path.join(_src_platforms, _dll)
                    _dst_f = os.path.join(_cache_platforms, _dll)
                    # Copy if missing or file size changed (handles updates)
                    if (not os.path.exists(_dst_f) or
                            os.path.getsize(_dst_f) != os.path.getsize(_src_f)):
                        shutil.copy2(_src_f, _dst_f)
                        _copied += 1
            if _copied:
                print(f"[Qt] Copied {_copied} platform DLL(s) to AppData cache")
        except Exception as _cache_err:
            print(f"[Qt] AppData cache copy failed: {_cache_err}")
            _cache_platforms = ''   # fall back to _MEIPASS

    # Use AppData cache when available; fall back to _MEIPASS at worst
    _platform_plugins = (
        _cache_platforms
        if _cache_platforms and os.path.isdir(_cache_platforms)
        else _src_platforms
    )
    # -------------------------------------------------------------------

    if os.path.isdir(_qt_plugins):
        os.environ['QT_PLUGIN_PATH'] = _qt_plugins
        print(f"[Qt] Plugin path set to: {_qt_plugins}")
    else:
        print(f"[Qt WARNING] Plugin directory not found at: {_qt_plugins}")

    if os.path.isdir(_platform_plugins):
        os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = _platform_plugins
        print(f"[Qt] Platform plugins: {_platform_plugins}")
    else:
        print(f"[Qt WARNING] Platform plugins missing at: {_platform_plugins}")

    # ------------------------------------------------------------------
    # 3. Cache certifi CA bundle to AppData so SSL survives _MEIPASS
    #    cleanup when the parent process exits on restart.
    # ------------------------------------------------------------------
    _src_cacert = os.path.join(_meipass, 'certifi', 'cacert.pem')
    _cache_certifi_dir = (
        os.path.join(_local_appdata, 'MLB-TCKR', 'certifi')
        if _local_appdata else ''
    )
    if _cache_certifi_dir and os.path.isfile(_src_cacert):
        try:
            os.makedirs(_cache_certifi_dir, exist_ok=True)
            _dst_cacert = os.path.join(_cache_certifi_dir, 'cacert.pem')
            if (not os.path.exists(_dst_cacert) or
                    os.path.getsize(_dst_cacert) != os.path.getsize(_src_cacert)):
                shutil.copy2(_src_cacert, _dst_cacert)
                print(f"[SSL] Cached cacert.pem to AppData")
            os.environ['REQUESTS_CA_BUNDLE'] = _dst_cacert
            os.environ['SSL_CERT_FILE'] = _dst_cacert
        except Exception as _ssl_cache_err:
            print(f"[SSL] AppData cache failed: {_ssl_cache_err}")
            # Fall back to _MEIPASS path (may be deleted on restart, but best effort)
            os.environ['REQUESTS_CA_BUNDLE'] = _src_cacert
            os.environ['SSL_CERT_FILE'] = _src_cacert

    # ------------------------------------------------------------------
    # 4. Diagnostic: list bundled .pyd modules
    # ------------------------------------------------------------------
    _pyqt5_dir = os.path.join(_meipass, 'PyQt5')
    if os.path.isdir(_pyqt5_dir):
        _pyds = sorted(_glob.glob(os.path.join(_pyqt5_dir, '*.pyd')))
        _names = ', '.join(os.path.basename(f).split('.')[0] for f in _pyds)
        print(f"[Qt] PyQt5 .pyd modules ({len(_pyds)}): {_names or 'NONE FOUND'}")
    else:
        print(f"[Qt WARNING] PyQt5 directory missing from bundle: {_pyqt5_dir}")

    # ------------------------------------------------------------------
    # 4. Pre-import PyQt5 core submodules so they land in sys.modules
    #    before the main script executes.  This prevents the restart
    #    scenario where inherited PATH from the parent process causes
    #    DLL loading to fail and shows as "cannot import name 'QtWidgets'".
    # ------------------------------------------------------------------
    try:
        import PyQt5.QtCore    # noqa: F401
        import PyQt5.QtGui     # noqa: F401
        import PyQt5.QtWidgets # noqa: F401
        import PyQt5.QtNetwork # noqa: F401
        print("[Qt] Pre-loaded: QtCore, QtGui, QtWidgets, QtNetwork")

        # ------------------------------------------------------------------
        # Diagnostics: show what Qt itself thinks the library paths are.
        # This runs AFTER pre-import, so QtCore is available without a new
        # import.  Helps diagnose "in ''" platform plugin failures.
        # ------------------------------------------------------------------
        import PyQt5.QtCore as _qc
        _lib_paths = _qc.QCoreApplication.libraryPaths()
        print(f"[Qt] libraryPaths: {_lib_paths}")
        _qt_conf_exists = _qc.QFile.exists(':/qt/etc/qt.conf')
        print(f"[Qt] :/qt/etc/qt.conf exists: {_qt_conf_exists}")
        if _qt_conf_exists:
            _f = _qc.QFile(':/qt/etc/qt.conf')
            _f.open(_qc.QFile.ReadOnly)
            _conf_text = bytes(_f.readAll()).decode('latin1', errors='replace').strip()
            _f.close()
            print(f"[Qt] qt.conf content: {_conf_text!r}")
        print(f"[Qt] QT_PLUGIN_PATH env: {os.environ.get('QT_PLUGIN_PATH', 'NOT SET')}")
        print(f"[Qt] QT_QPA_PLATFORM_PLUGIN_PATH env: {os.environ.get('QT_QPA_PLATFORM_PLUGIN_PATH', 'NOT SET')}")
    except Exception as _qt_err:
        print(f"[Qt ERROR] Pre-load failed: {_qt_err}")
        import traceback as _tb
        _tb.print_exc()

