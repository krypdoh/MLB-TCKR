"""
Author: Paul R. Charovkine
Program: MLB-TCKR.py
Date: 2026.0414.1016
License: GNU AGPLv3

Description:
MLB ticker application that displays live baseball game data in a scrolling ticker bar.
Shows team logos, scores, runners on base, outs, innings, and game times just like a
traditional LED sports ticker. Integrates with Windows AppBar for persistent display.
"""

VERSION = "1.1.0"

import warnings
warnings.filterwarnings(
    'ignore',
    message=r'.*doesn.*t match a supported version.*',
    category=Warning,
)

# Inject the Windows system certificate store into the requests library so that
# SSL verification works with corporate/internal CAs out of the box.  This is a
# no-op on non-Windows platforms and degrades gracefully if the package is absent.
try:
    import importlib
    _wrapt_requests = importlib.import_module("pip_system_certs.wrapt_requests")
    _inject_truststore = getattr(_wrapt_requests, "inject_truststore", None)
    if callable(_inject_truststore):
        _inject_truststore()
        print("[SSL] System certificate store injected into requests")
except Exception:
    pass  # Package not installed — requests falls back to its bundled certifi CA

import sys
import os

# Fix certifi CA bundle path when running as PyInstaller executable
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # The runtime hook (pyi_rth_mlb_qt.py) caches cacert.pem to AppData
    # and sets REQUESTS_CA_BUNDLE before this code runs.  Trust that value
    # if it already points to a real file — this protects against the parent
    # process deleting _MEIPASS before the child finishes.
    _existing_ca = os.environ.get('REQUESTS_CA_BUNDLE', '')
    if _existing_ca and os.path.isfile(_existing_ca):
        print(f"[SSL] CA bundle set to: {_existing_ca}")
    else:
        # Hook didn't cache it (shouldn't happen) — fall back to _MEIPASS
        _ca_bundle_path = os.path.join(sys._MEIPASS, 'certifi', 'cacert.pem')
        if os.path.isfile(_ca_bundle_path):
            os.environ['REQUESTS_CA_BUNDLE'] = _ca_bundle_path
            os.environ['SSL_CERT_FILE'] = _ca_bundle_path
            print(f"[SSL] CA bundle set to: {_ca_bundle_path}")
        else:
            print(f"[SSL WARNING] CA bundle not found at: {_ca_bundle_path}")
import subprocess
import json
import math
import time
import datetime
import random
import requests
import statsapi
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5 import QtSvg
import ctypes
from ctypes import wintypes


# Try to import Cython optimizations for smoother scrolling
try:
    from mlb_ticker_utils_cython import (
        calculate_smooth_scroll, 
        get_pixel_position,
        adjust_speed_for_framerate
    )
    CYTHON_AVAILABLE = True
    print("[MLB-PERF] Using Cython-optimized scrolling")
except ImportError as _cython_err:
    CYTHON_AVAILABLE = False
    print(f"[MLB-PERF] Cython not available, using Python scrolling ({_cython_err})")
    
    # Fallback Python implementations
    def calculate_smooth_scroll(current_offset, speed, max_width):
        new_offset = current_offset + speed
        if new_offset >= max_width:
            new_offset = 0.0
        return new_offset
    
    def get_pixel_position(float_offset):
        return int(float_offset)
    
    def adjust_speed_for_framerate(base_speed, target_fps, base_fps=30):
        return base_speed * (base_fps / target_fps)


# Configuration
APPDATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "MLB-TCKR")
SETTINGS_FILE = os.path.join(APPDATA_DIR, "MLB-TCKR.Settings.json")
TEAM_LOGO_CACHE = {}
MLB_LOGO_CACHE  = {}  # keyed by (logo_size, dpr)
_DIAMOND_CACHE  = {}  # keyed by (runners_key, outs, inning_text, size, dpr)

#  MLB Team Colors — official primary / secondary / tertiary per team
MLB_TEAM_COLORS_ALL = {
    "Diamondbacks": ["#A71930", "#E3D4AD", "#000000"],
    "Braves":       ["#13274F", "#CE1141", "#EAAA00"],
    "Orioles":      ["#DF4601", "#000000", "#A2AAAD"],
    "Red Sox":      ["#BD3039", "#192C55", "#FFFFFF"],
    "Cubs":         ["#0E3386", "#CC3433", "#FFFFFF"],
    "White Sox":    ["#000000", "#C4CED4", "#FFFFFF"],
    "Reds":         ["#C6011F", "#000000", "#FFFFFF"],
    "Guardians":    ["#0C2340", "#E31937", "#FFFFFF"],
    "Rockies":      ["#333366", "#C4CED4", "#000000"],
    "Tigers":       ["#0C2340", "#FA4616", "#FFFFFF"],
    "Astros":       ["#002D62", "#EB6E1F", "#F4871E"],
    "Royals":       ["#004687", "#BD9B60", "#FFFFFF"],
    "Angels":       ["#BA0021", "#003263", "#862633"],
    "Dodgers":      ["#005A9C", "#EF3E42", "#FFFFFF"],
    "Marlins":      ["#00A3E0", "#EF3340", "#000000"],
    "Brewers":      ["#12284B", "#FFC72C", "#FFFFFF"],
    "Twins":        ["#002B5C", "#D31145", "#B9975B"],
    "Mets":         ["#002D72", "#FF5910", "#FFFFFF"],
    "Yankees":      ["#003087", "#E3E4E5", "#FFFFFF"],
    "Athletics":    ["#003831", "#EFB21E", "#FFFFFF"],
    "Phillies":     ["#E81828", "#002D72", "#FFFFFF"],
    "Pirates":      ["#27251F", "#FDB827", "#FFFFFF"],
    "Padres":       ["#2F241D", "#FFC425", "#FFFFFF"],
    "Giants":       ["#FD5A1E", "#27251F", "#EFD19F"],
    "Mariners":     ["#0C2340", "#005C5C", "#C4CED4"],
    "Cardinals":    ["#C41E3A", "#002D62", "#FEDB00"],
    "Rays":         ["#092C5C", "#8FBCE6", "#F5D131"],
    "Rangers":      ["#003278", "#C0111F", "#FFFFFF"],
    "Blue Jays":    ["#134A8E", "#1D2D5C", "#E8291C"],
    "Nationals":    ["#AB0003", "#14225A", "#FFFFFF"],
}

# Primary colors (slot 0) — backward-compatible alias
MLB_TEAM_COLORS_DEFAULT = {team: colors[0] for team, colors in MLB_TEAM_COLORS_ALL.items()}

# AppBar constants
ABM_NEW              = 0x00000000
ABM_REMOVE           = 0x00000001
ABM_QUERYPOS         = 0x00000002
ABM_SETPOS           = 0x00000003
ABM_WINDOWPOSCHANGED = 0x00000009  # notify shell after window move/resize
ABM_ACTIVATE         = 0x00000006
ABE_TOP              = 1

class APPBARDATA(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('hWnd', wintypes.HWND),
        ('uCallbackMessage', wintypes.UINT),
        ('uEdge', wintypes.UINT),
        ('rc', wintypes.RECT),
        ('lParam', wintypes.LPARAM),
    ]


def get_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "speed": 5,
        "update_interval": 10,
        "ticker_height": 64,
        "font": "Ozone",
        "font_scale_percent": 175,
        "player_info_font": "Gotham Black",  # Font for W-L records, pitcher/batter names, pitch counts
        "player_font_scale_percent": 75,  # Scale for player info fonts (W-L, names, pitch counts)
        "show_team_records": True,
        "show_team_cities": False,
        "include_final_games": True,
        "include_scheduled_games": True,
        "led_background": True,
        "glass_overlay": True,
        "background_opacity": 255,
        "content_opacity": 255,
        "show_fps_overlay": False,
        "monitor_index": 0,
        "use_proxy": False,
        "proxy": "",
        "use_cert": False,
        "cert_file": "",
        "team_colors": {},          # Per-team custom color overrides (empty = use slot default)
        "team_name_color_slot": 0,    # 0=primary  1=secondary  2=tertiary  3=custom
        "team_name_custom_color": "#FFFFFF",  # Used when slot=3
        "load_at_startup": False,  # Register in Windows Run key on launch
        "docked": True,  # When True, ticker is docked (not moveable) and registered as AppBar
        "yesterday_cutoff_minutes": 30,  # Show yesterday's finals until N min before first pitch
        "show_moneyline": False,   # Show H2H moneyline odds from The Odds API
        "odds_api_key": "",        # API key for api.the-odds-api.com
        "odds_refresh_minutes": 15, # How often to re-fetch moneyline odds (minutes)
    }


def save_settings(settings):
    os.makedirs(APPDATA_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)


_STARTUP_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_REG_KEY  = "MLB-TCKR"


def get_startup_registry() -> bool:
    """Return True if MLB-TCKR is registered to launch at Windows startup.
    Only functional on Windows; always returns False on other platforms."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG_PATH,
                            0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _STARTUP_REG_KEY)
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_startup_registry(enable: bool) -> None:
    """Add or remove MLB-TCKR from the Windows HKCU Run key.
    Only operates when running as a compiled .exe (sys.frozen is True)."""
    if sys.platform != "win32" or not getattr(sys, 'frozen', False):
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_REG_PATH,
                            0, winreg.KEY_SET_VALUE) as key:
            if enable:
                exe_path = f'"{sys.executable}"'
                winreg.SetValueEx(key, _STARTUP_REG_KEY, 0, winreg.REG_SZ, exe_path)
                print(f"[STARTUP] Registered in Run key: {exe_path}")
            else:
                try:
                    winreg.DeleteValue(key, _STARTUP_REG_KEY)
                    print("[STARTUP] Removed from Run key")
                except FileNotFoundError:
                    pass  # Already absent – nothing to do
    except Exception as e:
        print(f"[STARTUP] Registry error: {e}")


def normalize_proxy_url(proxy_value):
    """Ensure proxy URL has a scheme prefix (http:// added if missing)."""
    if not proxy_value:
        return ""
    proxy_value = proxy_value.strip()
    if not proxy_value:
        return ""
    if not proxy_value.lower().startswith(("http://", "https://")):
        proxy_value = f"http://{proxy_value}"
    return proxy_value


def apply_proxy_settings():
    """Push proxy/cert config into environment variables so that the
    requests library (used by statsapi and all HTTP calls) picks them up
    automatically for all subsequent network requests."""
    settings = get_settings()
    proxy_value = normalize_proxy_url(settings.get('proxy', ''))
    if settings.get('use_proxy') and proxy_value:
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
            os.environ[key] = proxy_value
        print(f"[PROXY] Enabled: {proxy_value}")
    else:
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
            os.environ.pop(key, None)

    cert_file = settings.get('cert_file', '')
    if settings.get('use_cert') and cert_file and os.path.exists(cert_file):
        # User specified a custom certificate file — point requests at it explicitly.
        os.environ['REQUESTS_CA_BUNDLE'] = cert_file
        os.environ['SSL_CERT_FILE'] = cert_file
        print(f"[PROXY] Certificate: {cert_file}")
    else:
        # No custom cert — restore the AppData-cached cacert.pem so that
        # requests always has a working path even after _MEIPASS is deleted.
        _local = os.environ.get('LOCALAPPDATA', '')
        _appdata_cacert = (
            os.path.join(_local, 'MLB-TCKR', 'certifi', 'cacert.pem')
            if _local else ''
        )
        if _appdata_cacert and os.path.isfile(_appdata_cacert):
            os.environ['REQUESTS_CA_BUNDLE'] = _appdata_cacert
            os.environ['SSL_CERT_FILE'] = _appdata_cacert
        elif getattr(sys, '_MEIPASS', None):
            # First-ever run before hook has cached it — use _MEIPASS (fine, not deleted yet)
            _meipass_cacert = os.path.join(sys._MEIPASS, 'certifi', 'cacert.pem')
            if os.path.isfile(_meipass_cacert):
                os.environ['REQUESTS_CA_BUNDLE'] = _meipass_cacert
                os.environ['SSL_CERT_FILE'] = _meipass_cacert
        else:
            os.environ.pop('REQUESTS_CA_BUNDLE', None)


def register_all_font_files():
    """Scan app directories for ALL .ttf/.otf files and register them with Qt.
    This must be called after QApplication is created so fonts are available
    both for rendering and for the Settings font combo."""
    search_dirs = [
        APPDATA_DIR,
        os.path.dirname(os.path.abspath(__file__)),
    ]
    registered = {}
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            if fname.lower().endswith(('.ttf', '.otf')):
                path = os.path.join(d, fname)
                fid = QtGui.QFontDatabase.addApplicationFont(path)
                if fid != -1:
                    families = QtGui.QFontDatabase.applicationFontFamilies(fid)
                    for fam in families:
                        if fam not in registered:
                            registered[fam] = path
                            print(f"[FONT] Registered '{fam}' from {fname}")
    return registered


# Module-level font family caches — populated once on first call
_CUSTOM_FONT_FAMILY  = None
_RECORD_FONT_FAMILY  = None
_OZONE_FONT_FAMILY   = None


def load_custom_font():
    """Load the LED board font from TTF file (cached after first call)."""
    global _CUSTOM_FONT_FAMILY
    if _CUSTOM_FONT_FAMILY is not None:
        return _CUSTOM_FONT_FAMILY

    font_locations = [
        os.path.join(APPDATA_DIR, "led_board-7.ttf"),
        os.path.join(os.path.dirname(__file__), "led_board-7.ttf"),
        "led_board-7.ttf"
    ]
    for font_path in font_locations:
        if os.path.exists(font_path):
            font_id = QtGui.QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                font_families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
                if font_families:
                    print(f"[FONT] Loaded custom font: {font_families[0]} from {font_path}")
                    _CUSTOM_FONT_FAMILY = font_families[0]
                    return _CUSTOM_FONT_FAMILY

    print("[FONT] LED board font not found, using Arial fallback")
    _CUSTOM_FONT_FAMILY = "Arial"
    return _CUSTOM_FONT_FAMILY


def load_record_font_family():
    """Load Gotham Black font for standings data and return its family name (cached)."""
    global _RECORD_FONT_FAMILY
    if _RECORD_FONT_FAMILY is not None:
        return _RECORD_FONT_FAMILY

    target_family = "Gotham Black"
    db = QtGui.QFontDatabase()
    if target_family in db.families():
        _RECORD_FONT_FAMILY = target_family
        print(f"[FONT] Using Gotham Black for standings data")
        return _RECORD_FONT_FAMILY

    print("[FONT] Gotham Black not found, using ticker font for records")
    # Cache None sentinel as empty string so we don't retry on every call
    _RECORD_FONT_FAMILY = ""
    return None


def load_ozone_font():
    """Load Ozone-xRRO.ttf and return its font family name (cached)."""
    global _OZONE_FONT_FAMILY
    if _OZONE_FONT_FAMILY is not None:
        return _OZONE_FONT_FAMILY

    font_locations = [
        os.path.join(APPDATA_DIR, "Ozone-xRRO.ttf"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "Ozone-xRRO.ttf"),
        "Ozone-xRRO.ttf",
    ]
    for font_path in font_locations:
        if os.path.exists(font_path):
            font_id = QtGui.QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    print(f"[FONT] Loaded Ozone font: {families[0]} from {font_path}")
                    _OZONE_FONT_FAMILY = families[0]
                    return _OZONE_FONT_FAMILY

    print("[FONT] Ozone-xRRO.ttf not found, falling back to ticker font")
    _OZONE_FONT_FAMILY = ""
    return None


def get_team_nickname(team_name):
    """Extract team nickname from full team name"""
    # Handle multi-word nicknames
    multi_word_nicknames = {
        'Red Sox': 'Red Sox',
        'White Sox': 'White Sox',
        'Blue Jays': 'Blue Jays',
    }
    
    # Check if it's a known multi-word nickname
    for nickname in multi_word_nicknames.keys():
        if team_name.endswith(nickname):
            return nickname
    
    # Otherwise use last word as team nickname
    return team_name.split()[-1]


def get_team_color(team_name):
    """Return the display color for a team name.

    Priority:
      1. Per-team override from the Team Colors tab
      2. Global color slot: 0=primary, 1=secondary, 2=tertiary, 3=custom
    """
    settings = get_settings()
    custom_colors = settings.get('team_colors', {})

    nickname = get_team_nickname(team_name)

    # Per-team override takes top priority. Support two kinds of stored values:
    # - Hex string like '#ff0000' (custom color)
    # - Integer 0/1/2 indicating which palette slot (primary/secondary/tertiary)
    if nickname in custom_colors:
        val = custom_colors[nickname]
        # If user stored an int index, resolve it against the team's palette
        if isinstance(val, int):
            team_palette = MLB_TEAM_COLORS_ALL.get(nickname)
            if team_palette and 0 <= val < len(team_palette):
                return team_palette[val]
        # If stored as string and looks like a hex color, use it directly
        if isinstance(val, str) and val.startswith('#'):
            return val

    # Global slot
    slot = int(settings.get('team_name_color_slot', 0))
    if slot == 3:
        return settings.get('team_name_custom_color', '#FFFFFF')

    team_palette = MLB_TEAM_COLORS_ALL.get(nickname)
    if team_palette and 0 <= slot < len(team_palette):
        return team_palette[slot]

    return '#FFFFFF'


def get_team_logo(team_name, size=40):
    """Get team logo pixmap"""
    images_dirs = [os.path.join(APPDATA_DIR, "MLB-TCKR.images")]

    # Support bundled assets (PyInstaller onefile/onedir) and local project folder.
    runtime_base = getattr(sys, '_MEIPASS', None)
    if runtime_base:
        images_dirs.append(os.path.join(runtime_base, "MLB-TCKR.images"))
    images_dirs.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "MLB-TCKR.images"))

    # Ensure AppData image folder exists for user overrides.
    os.makedirs(images_dirs[0], exist_ok=True)
    
    # Get team nickname and normalize for filename
    nickname = get_team_nickname(team_name)
    normalized_name = nickname.lower().replace(' ', '')
    cache_key = (normalized_name, int(size))

    # Fast path: return cached scaled logo/fallback pixmap.
    cached_logo = TEAM_LOGO_CACHE.get(cache_key)
    if cached_logo is not None:
        return cached_logo
    
    logo_filename = f"{normalized_name}.png"
    logo_path = None
    for images_dir in images_dirs:
        candidate = os.path.join(images_dir, logo_filename)
        if os.path.exists(candidate):
            logo_path = candidate
            break
    
    print(f"[LOGO] Looking for: {team_name} -> {logo_filename}")

    # Case-insensitive file search if exact match not found
    if logo_path is None:
        for images_dir in images_dirs:
            if not os.path.isdir(images_dir):
                continue
            try:
                files_in_dir = os.listdir(images_dir)
                for filename in files_in_dir:
                    if filename.lower() == logo_filename.lower():
                        logo_path = os.path.join(images_dir, filename)
                        print(f"[LOGO] Found case-insensitive match: {filename}")
                        break
            except Exception as e:
                print(f"[LOGO] Error searching directory: {e}")
            if logo_path is not None:
                break

    if logo_path is None or not os.path.exists(logo_path):
        print(f"[LOGO] File not found: {logo_path}, using fallback")
        # Fallback: create simple colored square with team abbreviation
        pixmap = QtGui.QPixmap(size, size)
        color = QtGui.QColor(get_team_color(team_name))
        pixmap.fill(color)
        
        painter = QtGui.QPainter(pixmap)
        painter.setPen(QtGui.QColor('white'))
        font_family = load_custom_font()
        font = QtGui.QFont(font_family, int(size * 0.25))
        font.setStyleStrategy(
            QtGui.QFont.NoAntialias | QtGui.QFont.NoSubpixelAntialias |
            QtGui.QFont.PreferBitmap | QtGui.QFont.ForceIntegerMetrics
        )
        font.setHintingPreference(QtGui.QFont.PreferFullHinting)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, nickname[:3].upper())
        painter.end()
        TEAM_LOGO_CACHE[cache_key] = pixmap
        return pixmap
    
    print(f"[LOGO] Loading from: {logo_path}")
    pixmap = QtGui.QPixmap(logo_path)
    
    if pixmap.isNull():
        print(f"[LOGO] Failed to load pixmap, using fallback")
        # Fallback if pixmap failed to load
        pixmap = QtGui.QPixmap(size, size)
        color = QtGui.QColor(get_team_color(team_name))
        pixmap.fill(color)
        
        painter = QtGui.QPainter(pixmap)
        painter.setPen(QtGui.QColor('white'))
        font_family = load_custom_font()
        font = QtGui.QFont(font_family, int(size * 0.25))
        font.setStyleStrategy(
            QtGui.QFont.NoAntialias | QtGui.QFont.NoSubpixelAntialias |
            QtGui.QFont.PreferBitmap | QtGui.QFont.ForceIntegerMetrics
        )
        font.setHintingPreference(QtGui.QFont.PreferFullHinting)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, nickname[:3].upper())
        painter.end()
        TEAM_LOGO_CACHE[cache_key] = pixmap
        return pixmap
    
    print(f"[LOGO] Successfully loaded: {logo_path} ({pixmap.width()}x{pixmap.height()})")
    scaled_logo = pixmap.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    TEAM_LOGO_CACHE[cache_key] = scaled_logo
    return scaled_logo


def _fetch_probable_pitchers_parallel(scheduled_games):
    """Fetch probable pitchers for scheduled games in parallel.
    
    Args:
        scheduled_games: List of game_info dicts for scheduled games
        
    Returns:
        Dict mapping game_id -> {'away': {'id': int, 'name': str}, 'home': {...}}
    """
    def format_last_name(player_obj):
        full_name = str(player_obj.get('fullName', '')).strip()
        if not full_name:
            return "Unknown"
        parts = full_name.split()
        # Return last two words for names like "Michael Harris II" → "Harris II"
        return ' '.join(parts[-2:]) if len(parts) > 2 else parts[-1]
    
    def fetch_single_game_probables(game_id):
        """Fetch probable pitchers for a single game."""
        try:
            game_feed = statsapi.get('game', {'gamePk': game_id})
            game_data_obj = game_feed.get('gameData', {})
            probables = game_data_obj.get('probablePitchers', {})
            
            result = {}
            away_probable = probables.get('away', {})
            home_probable = probables.get('home', {})
            
            if away_probable and away_probable.get('fullName'):
                result['away'] = {
                    'id': away_probable.get('id'),
                    'name': format_last_name(away_probable)
                }
            
            if home_probable and home_probable.get('fullName'):
                result['home'] = {
                    'id': home_probable.get('id'),
                    'name': format_last_name(home_probable)
                }
            
            return game_id, result
        except Exception as e:
            print(f"[MLB] Could not get probable pitchers for game {game_id}: {e}")
            return game_id, {}
    
    # Fetch all game feeds in parallel
    probables_map = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_id = {executor.submit(fetch_single_game_probables, g['game_id']): g['game_id'] 
                       for g in scheduled_games}
        for future in as_completed(future_to_id):
            try:
                game_id, result = future.result()
                if result:
                    probables_map[game_id] = result
            except Exception as e:
                print(f"[MLB] Exception fetching game probables: {e}")
    
    return probables_map


def _fetch_pitcher_stats_parallel(game_data):
    """Fetch all pitcher stats in parallel for better performance.
    
    Returns a dict mapping pitcher_id -> {'era': str, 'wins': int, 'losses': int}
    """
    def format_era(era_val):
        """Format ERA value."""
        if era_val is None:
            return '-.--'
        try:
            return f"{float(era_val):.2f}"
        except (ValueError, TypeError):
            return '-.--'
    
    def fetch_single_pitcher(pitcher_id):
        """Fetch stats for a single pitcher."""
        try:
            person_data = statsapi.get('person', {
                'personId': pitcher_id, 
                'hydrate': 'stats(group=pitching,type=season)'
            })
            people = person_data.get('people', [])
            if people and len(people) > 0:
                pitcher_info = people[0]
                stats_list = pitcher_info.get('stats', [])
                for stat_group in stats_list:
                    splits = stat_group.get('splits', [])
                    if splits and 'stat' in splits[0]:
                        pitching = splits[0]['stat']
                        return {
                            'era': format_era(pitching.get('era', '-.--')),
                            'wins': pitching.get('wins', 0),
                            'losses': pitching.get('losses', 0)
                        }
        except Exception as e:
            print(f"[MLB] Could not fetch stats for pitcher {pitcher_id}: {e}")
        return None
    
    # Collect all unique pitcher IDs
    pitcher_ids = set()
    for game in game_data:
        if 'away_pitcher_id' in game:
            pitcher_ids.add(game['away_pitcher_id'])
        if 'home_pitcher_id' in game:
            pitcher_ids.add(game['home_pitcher_id'])
    
    if not pitcher_ids:
        return {}
    
    # Fetch all pitcher stats in parallel
    stats_map = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_id = {executor.submit(fetch_single_pitcher, pid): pid for pid in pitcher_ids}
        for future in as_completed(future_to_id):
            pitcher_id = future_to_id[future]
            try:
                result = future.result()
                if result:
                    stats_map[pitcher_id] = result
            except Exception as e:
                print(f"[MLB] Exception fetching pitcher {pitcher_id}: {e}")
    
    return stats_map


def fetch_todays_games(fetch_date=None):
    """Fetch all MLB games for today, or for a specific date (YYYY-MM-DD)."""
    def format_last_name(player_obj):
        full_name = str(player_obj.get('fullName', '')).strip()
        if not full_name:
            return "Unknown"
        parts = full_name.split()
        # Return last two words for names like "Michael Harris II" → "Harris II"
        return ' '.join(parts[-2:]) if len(parts) > 2 else parts[-1]

    def get_player_stat(players_map, player_id, stat_group, stat_key):
        if not player_id:
            return None
        player_data = players_map.get(f"ID{player_id}", {})
        season_stats = player_data.get('seasonStats', {})
        stat_group_data = season_stats.get(stat_group, {})
        return stat_group_data.get(stat_key)

    def get_game_stat(players_map, player_id, stat_group, stat_key):
        """Get current-game stats (not season stats) for a player."""
        if not player_id:
            return None
        player_data = players_map.get(f"ID{player_id}", {})
        game_stats = player_data.get('stats', {})
        stat_group_data = game_stats.get(stat_group, {})
        return stat_group_data.get(stat_key)

    def format_era(era_value):
        if era_value is None:
            return "-"
        era_str = str(era_value).strip()
        if not era_str or era_str in ['--', '-', '.---']:
            return "-"
        return era_str

    def format_avg(avg_value):
        if avg_value is None:
            return "-"
        avg_str = str(avg_value).strip()
        if not avg_str or avg_str in ['--', '-', '.---']:
            return "-"
        if avg_str.startswith('0.'):
            return avg_str[1:]
        return avg_str

    def fetch_team_records_map(season_year):
        """Return {team_id: 'W-L'} for all MLB teams from standings."""
        records_map = {}
        try:
            standings = statsapi.get(
                'standings',
                {
                    'leagueId': '103,104',  # AL + NL
                    'season': str(season_year),
                    'standingsTypes': 'regularSeason'
                }
            )
            for group in standings.get('records', []):
                for team_record in group.get('teamRecords', []):
                    team_id = team_record.get('team', {}).get('id')
                    wins = team_record.get('wins')
                    losses = team_record.get('losses')
                    if team_id is not None and wins is not None and losses is not None:
                        records_map[team_id] = f"{wins}-{losses}"
        except Exception as e:
            print(f"[MLB] Could not fetch standings records: {e}")
        return records_map

    try:
        today = fetch_date or datetime.datetime.now().strftime('%Y-%m-%d')
        season_year = int(today[:4])
        print(f"[MLB] Fetching games for {today}")
        
        games = statsapi.schedule(date=today)
        team_records = fetch_team_records_map(season_year)
        game_data = []
        
        for game in games:
            away_team_id = game.get('away_id')
            home_team_id = game.get('home_id')
            away_record = team_records.get(away_team_id, '-')
            home_record = team_records.get(home_team_id, '-')
            game_info = {
                'game_id': game.get('game_id'),
                'status': game.get('status'),
                'away_name': game.get('away_name'),
                'home_name': game.get('home_name'),
                'away_score': game.get('away_score', 0),
                'home_score': game.get('home_score', 0),
                'current_inning': game.get('current_inning', ''),
                'inning_state': game.get('inning_state', ''),
                'game_datetime': game.get('game_datetime'),
                'away_record': away_record,
                'home_record': home_record,
            }
            
            print(f"[MLB] Game: {game_info['away_name']} @ {game_info['home_name']} - Status: {game_info['status']}")
            
            # For live games, try to get detailed game data
            if game_info['status'] in ['In Progress', 'Live']:
                try:
                    # Get live game feed for detailed information
                    game_id = game_info['game_id']
                    
                    # Get game feed which has detailed play-by-play data
                    game_feed = statsapi.get('game', {'gamePk': game_id})
                    
                    # Extract current game state
                    live_data = game_feed.get('liveData', {})
                    plays = live_data.get('plays', {})
                    current_play = plays.get('currentPlay', {})
                    
                    # Get outs/balls/strikes from count
                    count = current_play.get('count', {})
                    game_info['outs'] = count.get('outs', 0)
                    game_info['balls'] = count.get('balls', 0)
                    game_info['strikes'] = count.get('strikes', 0)
                    
                    # Get matchup data (pitcher and batter)
                    matchup = current_play.get('matchup', {})
                    pitcher = matchup.get('pitcher', {})
                    batter = matchup.get('batter', {})
                    pitcher_id = pitcher.get('id')
                    batter_id = batter.get('id')
                    
                    game_info['pitcher_name'] = pitcher.get('fullName', '')
                    game_info['batter_name'] = batter.get('fullName', '')

                    # Get season stats for live pitcher/batter from boxscore players
                    players_map = {}
                    boxscore_data = live_data.get('boxscore', {})
                    teams_data = boxscore_data.get('teams', {})
                    for side in ['away', 'home']:
                        team_players = teams_data.get(side, {}).get('players', {})
                        if team_players:
                            players_map.update(team_players)

                    pitcher_era = format_era(get_player_stat(players_map, pitcher_id, 'pitching', 'era'))
                    batter_avg = format_avg(get_player_stat(players_map, batter_id, 'batting', 'avg'))
                    pitcher_pitches = get_game_stat(players_map, pitcher_id, 'pitching', 'numberOfPitches')

                    pitcher_last = format_last_name(pitcher)
                    batter_last = format_last_name(batter)

                    # Batting order position (stored as e.g. 400 meaning 4th in lineup)
                    batter_order_raw = None
                    if batter_id:
                        batter_player_data = players_map.get(f"ID{batter_id}", {})
                        batter_order_raw = batter_player_data.get('battingOrder')
                    if batter_order_raw is not None:
                        try:
                            batter_order_num = int(str(batter_order_raw).strip()) // 100
                        except (ValueError, TypeError):
                            batter_order_num = None
                    else:
                        batter_order_num = None
                    batter_prefix = f"{batter_order_num}. " if batter_order_num else ""

                    game_info['pitcher_pitches'] = pitcher_pitches

                    # Replace W-L line with live P/B stats once game starts
                    if game_info.get('inning_state', '') == 'Top':
                        game_info['away_subtext'] = f"{batter_prefix}{batter_last} {batter_avg}"
                        game_info['home_subtext'] = f"{pitcher_last} {pitcher_era}"
                        game_info['pitcher_side'] = 'home'
                    else:
                        game_info['away_subtext'] = f"{pitcher_last} {pitcher_era}"
                        game_info['home_subtext'] = f"{batter_prefix}{batter_last} {batter_avg}"
                        game_info['pitcher_side'] = 'away'
                    
                    # Get runners on base from linescore
                    linescore_data = live_data.get('linescore', {})
                    offense = linescore_data.get('offense', {})
                    
                    game_info['runners'] = {
                        'first': offense.get('first') is not None,
                        'second': offense.get('second') is not None,
                        'third': offense.get('third') is not None
                    }
                    
                    print(f"[MLB] Live game data - Outs: {game_info['outs']}, Runners: {game_info['runners']}")
                    if game_info.get('pitcher_name') and game_info.get('batter_name'):
                        print(f"[MLB] Matchup - Pitcher: {game_info['pitcher_name']}, Batter: {game_info['batter_name']}")
                    
                except Exception as e:
                    print(f"[MLB] Could not get detailed game data: {e}")
                    import traceback
                    traceback.print_exc()
                    game_info['outs'] = 0
                    game_info['runners'] = {'first': False, 'second': False, 'third': False}
            elif game_info['status'] in ['Final', 'Completed', 'Game Over']:
                game_info['outs'] = 0
                game_info['runners'] = {'first': False, 'second': False, 'third': False}
                try:
                    game_feed = statsapi.get('game', {'gamePk': game_info['game_id']})
                    live_data = game_feed.get('liveData', {})
                    players_map = {}
                    for side in ['away', 'home']:
                        team_players = (live_data.get('boxscore', {})
                                        .get('teams', {}).get(side, {}).get('players', {}))
                        if team_players:
                            players_map.update(team_players)
                    decisions = live_data.get('decisions', {})
                    winner = decisions.get('winner', {})
                    loser  = decisions.get('loser', {})
                    if winner and loser:
                        wp_id = winner.get('id')
                        lp_id = loser.get('id')
                        wp_era = format_era(get_player_stat(players_map, wp_id, 'pitching', 'era'))
                        wp_w   = get_player_stat(players_map, wp_id, 'pitching', 'wins')
                        wp_l   = get_player_stat(players_map, wp_id, 'pitching', 'losses')
                        wp_rec = f"{wp_w}-{wp_l}" if (wp_w is not None and wp_l is not None) else "-"
                        lp_era = format_era(get_player_stat(players_map, lp_id, 'pitching', 'era'))
                        lp_w   = get_player_stat(players_map, lp_id, 'pitching', 'wins')
                        lp_l   = get_player_stat(players_map, lp_id, 'pitching', 'losses')
                        lp_rec = f"{lp_w}-{lp_l}" if (lp_w is not None and lp_l is not None) else "-"
                        wp_text = f"WP: {format_last_name(winner)} {wp_era} {wp_rec}"
                        lp_text = f"LP: {format_last_name(loser)} {lp_era} {lp_rec}"
                        if game_info['away_score'] > game_info['home_score']:
                            game_info['away_subtext'] = wp_text
                            game_info['home_subtext'] = lp_text
                        else:
                            game_info['home_subtext'] = wp_text
                            game_info['away_subtext'] = lp_text
                        print(f"[MLB] Final decisions — {wp_text} | {lp_text}")
                except Exception as e:
                    print(f"[MLB] Could not get final game decisions: {e}")
            else:
                # Scheduled games — store for batch fetching
                game_info['outs'] = 0
                game_info['runners'] = {'first': False, 'second': False, 'third': False}
            
            game_data.append(game_info)
        
        # Batch fetch probable pitchers for scheduled games in parallel
        scheduled_games = [g for g in game_data if g.get('status') in {'Scheduled', 'Pre-Game', 'Warmup'}]
        probables_map = _fetch_probable_pitchers_parallel(scheduled_games)
        
        # Apply probable pitcher data to games
        for game_info in game_data:
            game_id = game_info.get('game_id')
            if game_id in probables_map:
                probables = probables_map[game_id]
                if 'away' in probables:
                    game_info['away_pitcher_id'] = probables['away']['id']
                    game_info['away_pitcher_name'] = probables['away']['name']
                if 'home' in probables:
                    game_info['home_pitcher_id'] = probables['home']['id']
                    game_info['home_pitcher_name'] = probables['home']['name']
                
                if 'away' not in probables and 'home' not in probables:
                    print(f"[MLB] No probable pitchers for {game_info['away_name']} @ {game_info['home_name']}")
        
        # Batch fetch all pitcher stats in parallel for better performance
        pitcher_stats = _fetch_pitcher_stats_parallel(game_data)
        
        # Apply pitcher stats to games
        for game_info in game_data:
            if 'away_pitcher_id' in game_info:
                pitcher_id = game_info['away_pitcher_id']
                pitcher_name = game_info['away_pitcher_name']
                stats = pitcher_stats.get(pitcher_id)
                if stats:
                    game_info['away_subtext'] = f"P: {pitcher_name}, {stats['era']} {stats['wins']}-{stats['losses']}"
                    print(f"[MLB] Away probable: {game_info['away_subtext']}")
                else:
                    game_info['away_subtext'] = f"P: {pitcher_name}, -.-- -"
                    print(f"[MLB] Away probable (no stats): {game_info['away_subtext']}")
                # Clean up temporary fields
                del game_info['away_pitcher_id']
                del game_info['away_pitcher_name']
            
            if 'home_pitcher_id' in game_info:
                pitcher_id = game_info['home_pitcher_id']
                pitcher_name = game_info['home_pitcher_name']
                stats = pitcher_stats.get(pitcher_id)
                if stats:
                    game_info['home_subtext'] = f"P: {pitcher_name}, {stats['era']} {stats['wins']}-{stats['losses']}"
                    print(f"[MLB] Home probable: {game_info['home_subtext']}")
                else:
                    game_info['home_subtext'] = f"P: {pitcher_name}, -.-- -"
                    print(f"[MLB] Home probable (no stats): {game_info['home_subtext']}")
                # Clean up temporary fields
                del game_info['home_pitcher_id']
                del game_info['home_pitcher_name']
        
        # For scheduled games with no probable pitcher listed, show "P: -" as a placeholder
        scheduled_statuses = {'Scheduled', 'Pre-Game', 'Warmup', 'Preview'}
        for game_info in game_data:
            if game_info.get('status') in scheduled_statuses:
                if not game_info.get('away_subtext'):
                    game_info['away_subtext'] = 'P: -'
                if not game_info.get('home_subtext'):
                    game_info['home_subtext'] = 'P: -'

        # Filter games based on settings
        settings = get_settings()
        filtered_games = []
        
        for game in game_data:
            status = game['status']
            
            # Always include live/in-progress games
            if status in ['In Progress', 'Live']:
                filtered_games.append(game)
            # Include final games if setting allows
            elif status in ['Final', 'Completed', 'Game Over']:
                if settings.get('include_final_games', True):
                    filtered_games.append(game)
            # Include scheduled/pre-game/postponed if setting allows
            elif status in ['Pre-Game', 'Scheduled', 'Warmup', 'Postponed']:
                if settings.get('include_scheduled_games', True):
                    filtered_games.append(game)
        
        print(f"[MLB] Fetched {len(game_data)} games, showing {len(filtered_games)} after filtering")
        return filtered_games
        
    except Exception as e:
        print(f"[MLB ERROR] Failed to fetch games: {e}")
        raise  # Re-raise so GameDataWorker can emit fetch_error instead of empty list


def format_game_time_local(game_datetime):
    """Format MLB API game datetime in local timezone (e.g., EDT) as h:mma/p."""
    if not game_datetime:
        return "TBD"

    try:
        dt_str = str(game_datetime)
        if dt_str.endswith('Z'):
            dt = datetime.datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        else:
            dt = datetime.datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)

        local_dt = dt.astimezone()
        return local_dt.strftime('%I:%M%p').lstrip('0').lower()
    except Exception:
        return "TBD"


# ---------------------------------------------------------------------------
# Odds API helpers
# ---------------------------------------------------------------------------

def fetch_mlb_odds(api_key):
    """Fetch MLB H2H moneyline odds from The Odds API (api.the-odds-api.com).

    Returns a dict mapping normalised team-name pairs to (away_price, home_price)
    integer tuples.  Prices are American-format (e.g. +150 or -110).
    Returns {} on any error so callers can treat missing odds gracefully.
    """
    if not api_key:
        return {}
    try:
        url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds/"
        params = {
            "apiKey": api_key,
            "regions": "us",
            "markets": "h2h",
            "oddsFormat": "american",
        }
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 401:
            print("[ODDS] Invalid API key — check your The Odds API key in Settings")
            return {}
        if resp.status_code == 422:
            print("[ODDS] No MLB odds available right now (422 from The Odds API)")
            return {}
        resp.raise_for_status()
        data = resp.json()
        odds_map = {}
        for game in data:
            away_name = game.get('away_team', '')
            home_name = game.get('home_team', '')
            bookmakers = game.get('bookmakers', [])
            if not bookmakers:
                continue
            # Use the first bookmaker's h2h market
            for bookmaker in bookmakers:
                for market in bookmaker.get('markets', []):
                    if market.get('key') != 'h2h':
                        continue
                    outcomes = market.get('outcomes', [])
                    away_price = None
                    home_price = None
                    for o in outcomes:
                        p = o.get('price')
                        if p is None:
                            continue
                        if o['name'] == away_name:
                            away_price = int(p)
                        elif o['name'] == home_name:
                            home_price = int(p)
                    if away_price is not None and home_price is not None:
                        odds_map[(away_name.lower(), home_name.lower())] = (away_price, home_price)
                    break  # only need first bookmaker's h2h
                break
        print(f"[ODDS] Fetched {len(odds_map)} game(s) from The Odds API")
        return odds_map
    except Exception as e:
        print(f"[ODDS] Error fetching odds: {e}")
        return {}


def format_moneyline(price):
    """Format an American-odds integer price as a string: +150 or -110."""
    if price is None:
        return ''
    return f'+{price}' if price > 0 else str(price)


def _match_team_odds(statsapi_name, odds_map_keys):
    """Find the odds-map key (set of lowercased team names) that best matches
    a statsapi team name like 'Minnesota Twins'.

    Matching strategy (in order):
      1. Exact lowercase match
      2. statsapi name is a suffix of the odds name  (e.g. 'Twins' ⊆ 'Minnesota Twins')
      3. Odds name is a suffix of the statsapi name
    """
    name_lower = statsapi_name.lower()
    for key in odds_map_keys:
        if name_lower == key:
            return key
    for key in odds_map_keys:
        if name_lower in key or key in name_lower:
            return key
    # Last resort: last word of statsapi name appears in any odds key
    last_word = name_lower.split()[-1]
    for key in odds_map_keys:
        if last_word in key:
            return key
    return None


class GameDataWorker(QtCore.QThread):
    """Background thread for fetching game data without blocking UI"""
    data_fetched = QtCore.pyqtSignal(list)  # Signal to emit fetched game data
    fetch_error = QtCore.pyqtSignal()       # Emitted when a network/API error prevents fetch

    def __init__(self, fetch_date=None):
        super().__init__()
        self.fetch_date = fetch_date  # None = today
    
    def run(self):
        """Fetch game data in background thread"""
        try:
            games = fetch_todays_games(self.fetch_date)
            self.data_fetched.emit(games)
        except Exception as e:
            print(f"[MLB WORKER] Fetch failed — emitting fetch_error: {e}")
            self.fetch_error.emit()


class OddsDataWorker(QtCore.QThread):
    """Background thread for fetching moneyline odds from The Odds API."""
    odds_fetched = QtCore.pyqtSignal(dict)  # {(away_lower, home_lower): (away_price, home_price)}

    def __init__(self, api_key):
        super().__init__()
        self.api_key = api_key

    def run(self):
        odds = fetch_mlb_odds(self.api_key)
        self.odds_fetched.emit(odds)


def draw_baseball_diamond(runners, outs, inning_num, is_top, size=50, dpr=1.0, balls=None, strikes=None):
    """
    Draw baseball diamond with runners, outs, and inning indicator

    Args:
        runners: dict with 'first', 'second', 'third' (boolean)
        outs: number of outs (0-2)
        inning_num: inning number
        is_top: True if top of inning, False if bottom
        size: size in logical pixels
        dpr: device pixel ratio (pass screen DPR for crisp rendering)
        balls: current ball count (None = don't show)
        strikes: current strike count (None = don't show)
    """
    # Cache avoids repainting identical diamond states (same runners/outs/inning/count)
    runners_key = (bool(runners.get('first')), bool(runners.get('second')), bool(runners.get('third')))
    inning_txt  = 'F' if (isinstance(inning_num, str) and inning_num == 'F') else f"{'T' if is_top else 'B'}{inning_num}"
    _dc_key = (runners_key, int(outs), inning_txt, int(size), dpr,
               balls if balls is not None else -1, strikes if strikes is not None else -1)
    if _dc_key in _DIAMOND_CACHE:
        return _DIAMOND_CACHE[_dc_key]

    # All internal measurements scale proportionally with size.
    # Reference baseline is size=50 (ticker_height ≈ 71 px).
    scale = size / 50.0

    gutter = int(30 * scale)           # right gutter for inning indicator
    total_width = size + max(20, gutter)
    pixmap = QtGui.QPixmap(int(total_width * dpr), int(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(QtCore.Qt.transparent)

    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)

    center_x = size / 2 - 4 * scale   # shift field left for inning text gutter
    center_y = size / 2 - 4 * scale   # shift slightly upward

    diamond_size = max(6, int(10 * scale))
    pen_w       = max(1, round(2 * scale))

    # Base positions — proper square-rotated-45° diamond (all bases equidistant from center)
    r = 8 * scale  # uniform radius keeps the diamond geometrically square

    second_x = center_x
    second_y = center_y - r      # top of diamond

    first_x  = center_x + r     # right of diamond (same height as center)
    first_y  = center_y

    third_x  = center_x - r     # left of diamond (same height as center)
    third_y  = center_y

    bases = [
        ('second', second_x, second_y),
        ('first',  first_x,  first_y),
        ('third',  third_x,  third_y),
    ]

    for base_name, x, y in bases:
        half = diamond_size / 2
        diamond = QtGui.QPolygon([
            QtCore.QPoint(int(x),        int(y - half)),
            QtCore.QPoint(int(x + half), int(y)),
            QtCore.QPoint(int(x),        int(y + half)),
            QtCore.QPoint(int(x - half), int(y)),
        ])
        if runners.get(base_name):
            painter.setBrush(QtGui.QBrush(QtGui.QColor('#00FF00')))
            painter.setPen(QtGui.QPen(QtGui.QColor('#00FF00'), pen_w))
        else:
            painter.setBrush(QtGui.QBrush(QtCore.Qt.transparent))
            painter.setPen(QtGui.QPen(QtGui.QColor('#666666'), pen_w))
        painter.drawPolygon(diamond)

    # Out indicators — 3 circles scaled with size
    out_radius  = max(2, int(3 * scale))
    out_spacing = max(8, int(14 * scale))
    outs_start_x = center_x - out_spacing
    outs_y = size - max(5, int(9 * scale))

    for i in range(3):
        x = outs_start_x + (i * out_spacing)
        if i < outs:
            painter.setBrush(QtGui.QBrush(QtGui.QColor('#FF0000')))
            painter.setPen(QtGui.QPen(QtGui.QColor('#FF0000'), max(1, pen_w - 1)))
        else:
            painter.setBrush(QtGui.QBrush(QtCore.Qt.transparent))
            painter.setPen(QtGui.QPen(QtGui.QColor('#666666'), pen_w))
        painter.drawEllipse(QtCore.QPointF(x, outs_y), out_radius, out_radius)

    # Inning indicator — font scales with size
    inning_x = size  # just right of the diamond field

    if isinstance(inning_num, str) and inning_num == 'F':
        inning_text = 'F'
    else:
        inning_letter = 'T' if is_top else 'B'
        inning_text = f"{inning_letter}{inning_num}"

    font_family  = load_custom_font()
    font_pt      = max(7, round(10 * scale))   # point size — matches original at scale 1.0
    font = QtGui.QFont(font_family, font_pt)
    font.setStyleStrategy(
        QtGui.QFont.NoAntialias | QtGui.QFont.NoSubpixelAntialias |
        QtGui.QFont.PreferBitmap | QtGui.QFont.ForceIntegerMetrics
    )
    font.setHintingPreference(QtGui.QFont.PreferFullHinting)
    painter.setFont(font)

    field_top = second_y - diamond_size / 2
    fm = QtGui.QFontMetrics(font)
    inning_y = field_top + fm.ascent() - max(2, int(4 * scale))

    painter.setPen(QtGui.QPen(QtGui.QColor('#FFD700')))
    painter.drawText(int(inning_x) + 1, int(inning_y), inning_text)

    # Ball–strike count below inning indicator
    count_text_right = inning_x + fm.horizontalAdvance(inning_text)
    if balls is not None and strikes is not None:
        count_text  = f"{balls}-{strikes}"
        count_pt    = max(6, round(8 * scale))
        count_font  = QtGui.QFont(font_family, count_pt)
        count_font.setStyleStrategy(
            QtGui.QFont.NoAntialias | QtGui.QFont.NoSubpixelAntialias |
            QtGui.QFont.PreferBitmap | QtGui.QFont.ForceIntegerMetrics
        )
        count_font.setHintingPreference(QtGui.QFont.PreferFullHinting)
        painter.setFont(count_font)
        cfm    = QtGui.QFontMetrics(count_font)
        count_y = inning_y + fm.descent() + 1 + cfm.ascent()
        count_y = min(count_y, outs_y - out_radius - 3 + cfm.ascent())
        painter.setPen(QtGui.QPen(QtGui.QColor('#FFFFFF')))
        painter.drawText(int(inning_x), int(count_y), count_text)
        count_text_right = max(count_text_right, inning_x + cfm.horizontalAdvance(count_text))

    # Expose the rightmost rendered x so build_game_pixmap can guarantee a gap.
    pixmap._inning_text_right_phys = count_text_right

    painter.end()
    _DIAMOND_CACHE[_dc_key] = pixmap
    return pixmap


class MLBTickerWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.settings = get_settings()
        self.games = []
        self.scroll_offset = 0.0  # Use float for sub-pixel scrolling
        self.ticker_pixmap = None
        self._ticker_tiles = []  # list of (logical_x, pixmap) for one period
        
        # Performance optimizations
        self.cached_background = None
        self.cached_overlay = None
        self.last_height = 0
        self.last_bg_settings = {}
        self._appbar_registered = False  # set True by setup_appbar(), cleared by remove_appbar()
        
        # Background data fetching
        self.data_worker = None
        self.is_fetching = False
        self.waiting_for_next_day = False
        self.last_fetch_date = None

        # Session-only date override: None = auto (today), "yesterday", "today", "tomorrow"
        self._date_view_override = None

        # Network resilience: keep last-known-good games for display during outages
        self._cached_games = []    # Last successful fetch result
        self._data_delayed = False  # True while showing stale data due to network error
        self._no_data_mode = False  # True when no internet; False when confirmed no games
        self._message_text = ''    # Last message built into the no-games pixmap (detects changes)

        # Yesterday mode: show previous day's finals until today's games are imminent
        self._yesterday_mode = False    # True while displaying previous day's results
        self._pending_today_games = []  # Today's fetched schedule (not yet displayed)
        self._pending_today_date = ''   # Date string for _pending_today_games
        self._yesterday_worker = None   # Keeps the yesterday QThread alive until done
        self._loading_mode = False      # True while fetching new day's data (shows LOADING badge)

        # Per-game and ticker-level render caches
        self._game_pixmap_cache = {}  # game_id → (fingerprint_tuple, QPixmap)
        self._last_ticker_fp = None   # overall fingerprint; None forces first build

        # Intro pixel-reveal animation state
        self.intro_active = True
        self.intro_phase = 'in'   # 'in' | 'hold' | 'out' | 'done'
        self.intro_pixmap = None  # Full rendered intro frame
        self.intro_display = None # Incrementally revealed display pixmap
        self.intro_all_blocks = []
        self.intro_revealed_count = 0
        self.intro_hold_frames = 0
        self.intro_block_size = 3  # Logical pixels per block (small pixels for fine pixelation)
        self._intro_bpf = 1        # Blocks per frame (set in build_intro_animation)
        self._intro_bs_phys = 3    # Physical block size (set in build_intro_animation)
        self.intro_timer_started = False  # True once the 2-s delay has fired

        # Scroll pause state (P key toggle) and hover tracking
        self.scroll_paused = False
        self.is_hovered = False

        # Delta-time scrolling — tracks real elapsed ms so scroll rate is
        # independent of timer jitter (Windows QTimer is only ~15.6 ms accurate).
        self._elapsed_timer = QtCore.QElapsedTimer()
        self._elapsed_timer.start()
        self._last_frame_ms = 0  # QElapsedTimer value at last scroll update

        # Cached per-frame scroll constants (recomputed when pixmap changes)
        self._scroll_speed_px_per_ms = 0.0  # logical pixels per millisecond
        self._scroll_max_width = 0.0        # half the (doubled) ticker pixmap width

        # Cached background settings tuple to avoid per-frame dict allocation
        self._cached_bg_key = None

        # FPS tracking
        self._fps_frame_count = 0
        self._fps_last_ms = 0
        self._fps_display = 0.0

        # Window setup
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        # Enable hardware acceleration for smoother rendering
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, False)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)

        # Enable mouse tracking for hover-to-pause functionality
        self.setMouseTracking(True)

        # Use CustomContextMenu policy — more reliable than contextMenuEvent on
        # frameless AppBar/Tool windows where Qt may not generate the context event.
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(self.mapToGlobal(pos))
        )
        
        # Size and position — use the user-selected monitor (falls back to primary)
        _screens = QtWidgets.QApplication.screens()
        _mon_idx = min(self.settings.get('monitor_index', 0), max(0, len(_screens) - 1))
        self._target_screen = _screens[_mon_idx]
        screen = self._target_screen.geometry()
        self.ticker_height = self.settings.get('ticker_height', 60)
        self.setGeometry(screen.x(), screen.y(), screen.width(), self.ticker_height)
        
        # Device pixel ratio – needed to create off-screen pixmaps at native
        # physical resolution so the compositor doesn't have to upscale them
        # (upscaling is what makes the font look blurry/compressed vs the preview).
        self.dpr = self._target_screen.devicePixelRatio()
        # Font/painter AA strategy: suppress antialiasing only on HiDPI (≥ 2× DPR) where
        # physical resolution is high enough for pixel/LED fonts to look crisp without it.
        # On standard-DPI displays (DPR < 2) keep AA on so rounded glyph shapes stay smooth —
        # this is why the same font looks fine in other apps on a 1× display.
        self._font_style_strategy = (
            QtGui.QFont.NoAntialias | QtGui.QFont.NoSubpixelAntialias |
            QtGui.QFont.ForceIntegerMetrics
            if self.dpr >= 2.0 else
            QtGui.QFont.PreferAntialias | QtGui.QFont.ForceIntegerMetrics
        )
        self._text_aa_hint = self.dpr < 2.0  # True = enable text AA on standard-DPI displays

        # Load custom LED board font
        self.font_family = load_custom_font()
        
        # Font (use setting or fallback to loaded font)
        preferred_font = self.settings.get('font', 'LED Board-7')
        if preferred_font == 'LED Board-7':
            font_to_use = self.font_family
        else:
            font_to_use = preferred_font

        print(f"[FONT] Active ticker font: '{font_to_use}'")
        font_scale = self.settings.get('font_scale_percent', 120) / 100.0
        # Player info font: user-selectable (W-L records, pitcher/batter names, pitch count)
        player_info_font = self.settings.get('player_info_font', 'Gotham Black')
        # Fallback to record_font_family if selected font is not available, then to ticker font
        if player_info_font not in QtGui.QFontDatabase().families():
            player_info_font = load_record_font_family() or font_to_use
        self._qfont = QtGui.QFont(font_to_use)
        self._qfont.setPixelSize(max(12, int(self.ticker_height * 0.40 * font_scale)))
        # Check if the font was resolved correctly (not falling back to system font)
        qfont_info = QtGui.QFontInfo(self._qfont)
        is_main_font_custom = (font_to_use == qfont_info.family())
        print(f"[FONT] Main ticker font requested: '{font_to_use}' -> using: '{qfont_info.family()}'")
        # All fonts are TrueType (.ttf), even LED-styled ones like Ozone
        # PreferBitmap ONLY works with true bitmap fonts, NOT TrueType fonts
        # Using PreferBitmap with .ttf causes rendering to fail after first character
        self._qfont.setStyleStrategy(self._font_style_strategy)
        print(f"[FONT] Main ticker font '{qfont_info.family()}' using TrueType rendering (no PreferBitmap)")
        self._qfont.setHintingPreference(QtGui.QFont.PreferFullHinting)
        
        # Apply player font scale to small_font and tiny_font
        player_font_scale = self.settings.get('player_font_scale_percent', 75) / 100.0
        self.small_font = QtGui.QFont(player_info_font)
        base_small_px = max(6, int(self.ticker_height * 0.22 * font_scale * 0.5)) + 3
        self.small_font.setPixelSize(int(base_small_px * player_font_scale))
        # Apply rendering strategies - but check if this is a custom LED/pixel font
        # System fonts need different strategies to avoid rendering failures
        font_info = QtGui.QFontInfo(self.small_font)
        is_custom_font = (player_info_font == font_info.family())
        print(f"[FONT] Player info font requested: '{player_info_font}' -> using: '{font_info.family()}'")
        # All fonts are TrueType (.ttf), don't use PreferBitmap
        self.small_font.setStyleStrategy(self._font_style_strategy)
        print(f"[FONT] Player info font '{font_info.family()}' using TrueType rendering")
        self.small_font.setHintingPreference(QtGui.QFont.PreferFullHinting)
        
        self.time_font = QtGui.QFont(font_to_use)
        self.time_font.setPixelSize(max(6, int(self.ticker_height * 0.35 * font_scale * 0.6)))
        # All fonts are TrueType (.ttf), don't use PreferBitmap
        self.time_font.setStyleStrategy(self._font_style_strategy)
        self.time_font.setHintingPreference(QtGui.QFont.PreferFullHinting)
        
        self.vs_font = QtGui.QFont(font_to_use)
        self.vs_font.setPixelSize(max(6, int(self.ticker_height * 0.35 * font_scale * 0.5)))
        self.vs_font.setBold(True)
        # All fonts are TrueType (.ttf), don't use PreferBitmap
        self.vs_font.setStyleStrategy(self._font_style_strategy)
        self.vs_font.setHintingPreference(QtGui.QFont.PreferFullHinting)
        
        small_px = self.small_font.pixelSize()
        self.tiny_font = QtGui.QFont(player_info_font)
        self.tiny_font.setPixelSize(max(5, small_px - 2))
        # All fonts are TrueType (.ttf), don't use PreferBitmap
        self.tiny_font.setStyleStrategy(self._font_style_strategy)
        self.tiny_font.setHintingPreference(QtGui.QFont.PreferFullHinting)
        
        # Odds API (moneyline)
        self._odds_cache = {}       # {(away_lower, home_lower): (away_price, home_price)}
        self._odds_worker = None

        # Fire the scroll timer faster than the display refresh rate so at least two
        # callbacks land per VBlank interval.  Qt coalesces the resulting update() calls
        # into one paintEvent per VBlank, and delta-time keeps scroll speed correct.
        # Using round(1000/hz) exactly (e.g. 17 ms at 60 Hz vs 16.67 ms VBlank) creates
        # a ~1 Hz beat that skips a VBlank once per second — the visible judder.
        # Capping at 8 ms eliminates that beat for all display rates up to 120 Hz.
        _screen = QtWidgets.QApplication.primaryScreen()
        _hz = _screen.refreshRate() if _screen else 60.0
        self._scroll_timer_interval_ms = min(8, max(4, round(1000.0 / _hz)))
        print(f"[TICKER] Display refresh: {_hz:.0f} Hz → scroll timer interval: {self._scroll_timer_interval_ms} ms")

        # Animation timer — started after intro finishes
        self.scroll_timer = QtCore.QTimer()
        self.scroll_timer.timeout.connect(self.update_scroll)
        self.scroll_timer.setTimerType(QtCore.Qt.PreciseTimer)  # More accurate timing

        # Intro pixel-reveal timer (~30 fps)
        self.intro_timer = QtCore.QTimer()
        self.intro_timer.timeout.connect(self.update_intro)
        self.intro_timer.setTimerType(QtCore.Qt.PreciseTimer)
        
        # Update timer for live games
        self.update_timer = QtCore.QTimer()
        self.update_timer.timeout.connect(self.start_data_fetch)
        self.update_timer.start(self.settings.get('update_interval', 10) * 1000)

        # Odds refresh timer — interval is user-configurable (default 15 min)
        self.odds_timer = QtCore.QTimer()
        self.odds_timer.timeout.connect(self.start_odds_fetch)
        _odds_interval_ms = max(1, self.settings.get('odds_refresh_minutes', 15)) * 60 * 1000
        self.odds_timer.setInterval(_odds_interval_ms)
        
        # Next day check timer (checks hourly after all games finish)
        self.next_day_timer = QtCore.QTimer()
        self.next_day_timer.timeout.connect(self.check_for_next_day_games)
        self.next_day_timer.setInterval(3600000)  # Check every hour
        
        # Initial fetch
        self.start_data_fetch()

        # Initial odds fetch (if enabled)
        if self.settings.get('show_moneyline', False) and self.settings.get('odds_api_key', ''):
            self.start_odds_fetch()
            self.odds_timer.start()

        self.show()

        # Setup AppBar after window is shown (requires valid, visible HWND)
        # Only register AppBar when 'docked' setting is enabled
        if self.settings.get('docked', True):
            self.setup_appbar()

        # Build intro animation geometry now (window is shown, size is final).
        # Start immediately — data loads in the background while the intro plays.
        self.build_intro_animation()
        self.intro_timer_started = True
        QtCore.QTimer.singleShot(0, self._start_intro)
    
    def _start_intro(self):
        """Launch the intro pixel-reveal timer."""
        if self.intro_active:
            self.intro_timer.start(33)  # ~30 fps
            print("[INTRO] Starting pixel-reveal animation")

    def _restart_intro(self):
        """Reset ticker to intro animation state."""
        # Stop normal scrolling
        if self.scroll_timer.isActive():
            self.scroll_timer.stop()
        # Reset intro state
        self.intro_active = True
        self.intro_phase = 'in'
        self.intro_revealed_count = 0
        self.intro_hold_frames = 0
        # Rebuild and start intro animation
        self.build_intro_animation()
        self._start_intro()
        print("[RESTART] Restarting intro animation")

    def setup_appbar(self):
        """Register as Windows AppBar to reserve desktop space at the top.

        Physical pixel dimensions are sourced directly from Win32
        (GetClientRect + GetMonitorInfo) rather than computed via Qt's DPR
        so the reservation is immune to rounding errors at any scaling factor
        (100 %, 125 %, 150 %, 175 %, 200 % …).

        Any desktop space already reserved by other programs is detected via
        GetMonitorInfo's rcWork rectangle.  ABM_QUERYPOS automatically adjusts
        our requested rectangle to sit below those existing reservations, so we
        never override or clobber another program's reserved region.
        """
        if sys.platform != "win32":
            return

        shell32 = ctypes.windll.shell32
        user32  = ctypes.windll.user32

        hwnd   = int(self.winId())
        screen = getattr(self, '_target_screen', QtWidgets.QApplication.primaryScreen())
        dpr    = screen.devicePixelRatio()

        # ── Physical height: read directly from the live HWND so we get the
        #    exact number of device pixels the window already occupies —
        #    no DPR arithmetic, no truncation/rounding risk.
        client_rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(client_rect))
        phys_height = client_rect.bottom - client_rect.top

        # Safety fallback if the window isn't fully laid out yet.
        if phys_height <= 0:
            phys_height = math.ceil(self.ticker_height * dpr)
            print(f"[AppBar] Warning: GetClientRect returned 0 height; "
                  f"falling back to DPR-scaled height={phys_height}px")

        # ── Physical monitor rectangle: gives us the correct origin for the
        #    AppBar rect (non-zero on secondary/offset monitors) and the full
        #    physical width without any DPR rounding.
        class _MONITORINFO(ctypes.Structure):
            _fields_ = [
                ('cbSize',    ctypes.c_uint32),
                ('rcMonitor', wintypes.RECT),
                ('rcWork',    wintypes.RECT),
                ('dwFlags',   ctypes.c_uint32),
            ]

        MONITOR_DEFAULTTONEAREST = 0x00000002
        hmonitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        user32.GetMonitorInfoW(hmonitor, ctypes.byref(mi))

        phys_x     = mi.rcMonitor.left
        phys_y     = mi.rcMonitor.top
        phys_width = mi.rcMonitor.right - mi.rcMonitor.left

        # ── Pre-flight: report any space already reserved at the top edge so
        #    the operator knows another program's reservation will be honoured.
        #    (ABM_QUERYPOS below will place us below that region automatically.)
        prior_top_reserved = mi.rcWork.top - phys_y
        if prior_top_reserved > 0:
            print(f"[AppBar] {prior_top_reserved}px already reserved at the top "
                  f"of this monitor by another program — honouring that space")

        # ── Build the full-width strip at the top of this monitor. ────────────
        abd = APPBARDATA()
        abd.cbSize    = ctypes.sizeof(APPBARDATA)
        abd.hWnd      = hwnd
        abd.uEdge     = ABE_TOP
        abd.rc.left   = phys_x
        abd.rc.top    = phys_y
        abd.rc.right  = phys_x + phys_width
        abd.rc.bottom = phys_y + phys_height

        # Step 1: Register the appbar.
        shell32.SHAppBarMessage(ABM_NEW, ctypes.byref(abd))
        self._appbar_registered = True

        # Step 2: Query — Windows adjusts rc.top downward past any existing
        #         AppBars / taskbar so our bar slots in below them, not on top.
        shell32.SHAppBarMessage(ABM_QUERYPOS, ctypes.byref(abd))

        # Step 3: Clamp bottom to preserve our exact height from the
        #         (possibly adjusted) top.
        abd.rc.bottom = abd.rc.top + phys_height

        # Step 4: Commit — tell the shell to reserve [rc.top … rc.bottom] and
        #         shrink the desktop work area so other windows won't overlap.
        shell32.SHAppBarMessage(ABM_SETPOS, ctypes.byref(abd))

        # Step 5: Reposition the Qt window in logical pixels to match the
        #         physical rectangle the shell just registered.
        self.setGeometry(
            int(abd.rc.left                  / dpr),
            int(abd.rc.top                   / dpr),
            int((abd.rc.right - abd.rc.left) / dpr),
            int((abd.rc.bottom - abd.rc.top) / dpr),
        )

        # Step 6: Tell the shell the HWND has been moved/resized.  Without
        #         this the work-area boundary may not fully update.
        shell32.SHAppBarMessage(ABM_WINDOWPOSCHANGED, ctypes.byref(abd))

        # Step 7: Notify shell the bar is active.
        shell32.SHAppBarMessage(ABM_ACTIVATE, ctypes.byref(abd))

        print(f"[AppBar] Registered — DPR={dpr}, "
              f"monitor phys=({phys_x},{phys_y},{phys_x+phys_width},{phys_y+phys_height}), "
              f"reserved phys=({abd.rc.left},{abd.rc.top},{abd.rc.right},{abd.rc.bottom}), "
              f"logical height={int((abd.rc.bottom - abd.rc.top) / dpr)}px")

    def remove_appbar(self):
        """Unregister the AppBar and release the reserved desktop space.

        Safe to call multiple times — guarded by _appbar_registered flag.
        Also called via app.aboutToQuit so the reservation is freed even
        when closeEvent is not delivered (common on Windows 10 when the
        process exits via the tray Quit action).
        """
        if sys.platform != "win32":
            return
        if not getattr(self, '_appbar_registered', False):
            return
        self._appbar_registered = False
        try:
            shell32 = ctypes.windll.shell32
            abd = APPBARDATA()
            abd.cbSize = ctypes.sizeof(APPBARDATA)
            abd.hWnd   = int(self.winId())
            shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(abd))
            print("[AppBar] Unregistered — desktop space released")
        except Exception as e:
            print(f"[AppBar] Warning: ABM_REMOVE failed: {e}")

    def _effective_fetch_date(self):
        """Return the date string to fetch, based on any session-only override.
        Returns None when the normal auto-today behaviour should apply."""
        if self._date_view_override is None or self._date_view_override == "today":
            return None  # GameDataWorker will default to today
        today = datetime.datetime.now().date()
        if self._date_view_override == "yesterday":
            return (today - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        if self._date_view_override == "tomorrow":
            return (today + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        return None

    def start_data_fetch(self):
        """Start background data fetch (non-blocking)"""
        # Don't start a new fetch if one is already running
        if self.is_fetching:
            print("[MLB] Fetch already in progress, skipping")
            return
        
        print(f"[MLB] Starting fetch for date: {self._effective_fetch_date()}")
        self.is_fetching = True
        self._loading_mode = True  # Show LOADING badge
        self.update()  # Schedule repaint to show LOADING badge (non-blocking)
        self.data_worker = GameDataWorker(fetch_date=self._effective_fetch_date())
        self.data_worker.data_fetched.connect(self.on_data_received)
        self.data_worker.fetch_error.connect(self.on_fetch_error)
        self.data_worker.finished.connect(self.on_fetch_complete)
        self.data_worker.start()

    def start_odds_fetch(self):
        """Start a background odds fetch from The Odds API (non-blocking).
        Silently skipped if moneyline is disabled or no API key is configured."""
        if not self.settings.get('show_moneyline', False):
            return
        api_key = self.settings.get('odds_api_key', '').strip()
        if not api_key:
            return
        if self._odds_worker and self._odds_worker.isRunning():
            return  # already in flight
        self._odds_worker = OddsDataWorker(api_key)
        self._odds_worker.odds_fetched.connect(self.on_odds_received)
        self._odds_worker.start()

    def on_odds_received(self, odds_map):
        """Store the newly-fetched odds and force a ticker rebuild."""
        self._odds_cache = odds_map
        # Invalidate per-game pixmap cache so odds render on next build
        self._game_pixmap_cache.clear()
        self._last_ticker_fp = None
        self.build_ticker_pixmap()
        self.update()

    def _get_game_odds(self, away_full, home_full):
        """Look up moneyline odds for a game, matching by team name.
        Returns (away_price, home_price) integers or (None, None) if not found."""
        if not self._odds_cache:
            return (None, None)
        all_away_keys = {k[0] for k in self._odds_cache}
        all_home_keys = {k[1] for k in self._odds_cache}
        away_match = _match_team_odds(away_full, all_away_keys)
        home_match = _match_team_odds(home_full, all_home_keys)
        if away_match and home_match:
            result = self._odds_cache.get((away_match, home_match))
            if result:
                return result
        return (None, None)

    def on_fetch_error(self):
        """Network/API error: keep cached games visible with a 'Data Delayed' badge.
        If there is no cache yet (first-ever launch with no internet), show the
        no-games message so the ticker bar is never completely blank."""
        self._loading_mode = False  # Clear loading indicator
        if not self._cached_games:
            print("[MLB] Fetch error with no cache — showing no-data message")
            self._no_data_mode = True
            # Build the no-data pixmap so the bar isn't blank
            self.games = []
            self.build_ticker_pixmap()
            if self.ticker_pixmap:
                raw_speed = self.settings.get('speed', 2)
                self._scroll_speed_px_per_ms = (raw_speed * 0.5) / 16.667
                # _scroll_max_width is set inside build_ticker_pixmap
            self._last_frame_ms = self._elapsed_timer.nsecsElapsed() / 1_000_000.0
            # Slow down retries while offline (no point hammering every 10 s)
            self._reschedule_update_timer()
            self.update()
            return
        print("[MLB] Fetch error — showing cached data with Data Delayed indicator")
        self._data_delayed = True
        self.games = self._cached_games
        # Force a pixmap rebuild to add the delay banner
        self._last_ticker_fp = None
        new_fp = self._games_fingerprint()
        self._last_ticker_fp = new_fp
        self.build_ticker_pixmap()
        if self.ticker_pixmap:
            raw_speed = self.settings.get('speed', 2)
            self._scroll_speed_px_per_ms = (raw_speed * 0.5) / 16.667
            # _scroll_max_width is set inside build_ticker_pixmap
        self.update()

    def _reschedule_update_timer(self):
        """Compute the right polling interval from current game states and apply it.

        Rules:
          - Any game In Progress / Live          → normal interval (user setting)
          - Any game starting within 2 minutes   → normal interval
          - All games Final / done               → stop; switch to next-day mode
          - Otherwise (scheduled, >2 min away)   → idle: poll every 5 minutes
        """
        live_statuses  = {'In Progress', 'Live'}
        final_statuses = {'Final', 'Completed', 'Game Over'}
        normal_ms = self.settings.get('update_interval', 10) * 1000
        idle_ms   = 300_000  # 5 minutes

        has_live  = any(g.get('status') in live_statuses  for g in self.games)
        all_final = bool(self.games) and all(
            g.get('status') in final_statuses for g in self.games
        )

        # Resume from next-day mode if new games appeared
        if self.waiting_for_next_day and not all_final:
            print("[MLB] New day's games detected — resuming normal updates")
            self.waiting_for_next_day = False
            self.next_day_timer.stop()

        if all_final and not self.waiting_for_next_day:
            print("[MLB] All games finished — switching to next-day polling")
            self.waiting_for_next_day = True
            self.update_timer.stop()
            self.next_day_timer.start()
            return

        if self.waiting_for_next_day:
            return  # next_day_timer is already running

        if has_live:
            interval_ms = normal_ms
            label = f"live ({normal_ms // 1000}s)"
        else:
            # Check whether any scheduled game starts within 2 minutes
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            soon = False
            for g in self.games:
                if g.get('status') in final_statuses:
                    continue
                gdt = g.get('game_datetime')
                if not gdt:
                    continue
                try:
                    dt_str = str(gdt)
                    if dt_str.endswith('Z'):
                        dt = datetime.datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                    else:
                        dt = datetime.datetime.fromisoformat(dt_str)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=datetime.timezone.utc)
                    if abs((dt - now_utc).total_seconds()) <= 120:
                        soon = True
                        break
                except Exception:
                    pass
            if soon:
                interval_ms = normal_ms
                label = f"pre-game soon ({normal_ms // 1000}s)"
            else:
                interval_ms = idle_ms
                label = "idle (300s)"

        self.update_timer.stop()
        self.update_timer.start(interval_ms)
        print(f"[MLB] Polling interval → {label}")

    def on_data_received(self, games):
        """Handle newly fetched game data (runs on main thread)"""
        # Successful fetch — update cache and clear any delayed-data flag
        self._cached_games = games
        self._no_data_mode = False  # Connectivity restored
        if self._data_delayed:
            self._data_delayed = False
            self._last_ticker_fp = None  # Force rebuild to remove the delay banner

        # When a manual date override is active, skip yesterday-mode logic entirely
        # and just display the fetched games for that date.
        if self._date_view_override is not None:
            print(f"[MLB] Received {len(games)} games for date override: {self._date_view_override}")
            self._loading_mode = False  # Clear loading indicator
            self.games = games
            self._reschedule_update_timer()
            new_fp = self._games_fingerprint()
            if new_fp != self._last_ticker_fp:
                self._last_ticker_fp = new_fp
                self.build_ticker_pixmap()
                if self.ticker_pixmap:
                    raw_speed = self.settings.get('speed', 2)
                    self._scroll_speed_px_per_ms = (raw_speed * 0.5) / 16.667
                self._last_frame_ms = self._elapsed_timer.nsecsElapsed() / 1_000_000.0
            self.update()
            return

        current_date = datetime.datetime.now().strftime('%Y-%m-%d')
        self.last_fetch_date = current_date

        # If already showing yesterday's finals, update pending games and recheck cutoff
        # rather than replacing the display with today's pre-game schedule.
        if self._yesterday_mode:
            self._pending_today_games = games
            self._pending_today_date = current_date
            self._loading_mode = False
            self._check_yesterday_cutoff()
            return

        # If we already decided to fetch yesterday (pending set but worker hasn't returned
        # yet), just refresh the stored today schedule and stay hidden.  Without this guard,
        # a repeating update_timer firing between the two async fetches would fall through
        # to the normal path and flash today's pre-game schedule before yesterday arrives.
        if self._pending_today_games:
            self._pending_today_games = games
            self._pending_today_date = current_date
            return

        # Determine whether all of today's games are pre-game and first pitch is far enough
        # away to warrant showing yesterday's finals first.
        _not_started = {'Scheduled', 'Pre-Game', 'Warmup', 'Preview'}
        _all_pregame = bool(games) and all(g.get('status') in _not_started for g in games)
        if _all_pregame:
            cutoff = self.settings.get('yesterday_cutoff_minutes', 30)
            delta = self._minutes_to_first_game(games)
            if delta is not None and delta > cutoff:
                self._pending_today_games = games
                self._pending_today_date = current_date
                # Stop the polling timer now — on_yesterday_data_received will re-arm
                # next_day_timer once yesterday's finals are displayed.
                self.update_timer.stop()
                print(f"[MLB] All games pre-game ({delta:.0f} min to first pitch, cutoff {cutoff} min)"
                      " — fetching yesterday's scores")
                QtCore.QTimer.singleShot(200, self._start_yesterday_fetch)
                return  # Don't display today's games yet

        # Normal path: display today's games
        self.games = games
        self._loading_mode = False
        self._reschedule_update_timer()

        # Only rebuild when displayed data has actually changed, avoiding the
        # brief main-thread stall on every refresh where nothing is different.
        new_fp = self._games_fingerprint()
        if new_fp != self._last_ticker_fp:
            self._last_ticker_fp = new_fp
            self.build_ticker_pixmap()
            if self.ticker_pixmap:
                raw_speed = self.settings.get('speed', 2)
                self._scroll_speed_px_per_ms = (raw_speed * 0.5) / 16.667
                # _scroll_max_width is set inside build_ticker_pixmap
            self._last_frame_ms = self._elapsed_timer.nsecsElapsed() / 1_000_000.0

        self.update()
    
    def on_fetch_complete(self):
        """Mark fetch as complete"""
        self.is_fetching = False
        if self.data_worker:
            self.data_worker.deleteLater()
            self.data_worker = None
    
    def check_all_games_finished(self):
        """Check if all games for today are finished"""
        if not self.games:
            return True  # No games = considered finished
        
        finished_statuses = ['Final', 'Completed', 'Game Over']
        all_finished = all(
            game.get('status') in finished_statuses 
            for game in self.games
        )
        return all_finished
    
    def check_for_next_day_games(self):
        """Check if it's a new day and fetch next day's games"""
        # Don't interfere with a manual date override
        if self._date_view_override is not None:
            return

        current_date = datetime.datetime.now().strftime('%Y-%m-%d')

        # If already in yesterday mode with pending today's games, just recheck the cutoff
        if self._yesterday_mode and self._pending_today_date == current_date:
            self._check_yesterday_cutoff()
            return

        # Only fetch if date has changed
        if self.last_fetch_date and current_date != self.last_fetch_date:
            print(f"[MLB] New day detected ({current_date}), peeking at today's schedule...")
            self.start_preview_fetch()
        else:
            # If still same day, just log that we're waiting
            current_hour = datetime.datetime.now().hour
            if current_hour >= 6:  # Only log during reasonable hours
                print(f"[MLB] Waiting for next day's games (current: {current_date})")

    # ------------------------------------------------------------------
    # Yesterday mode — show previous day's finals until today's games near
    # ------------------------------------------------------------------

    def start_preview_fetch(self):
        """Fetch today's schedule without immediately replacing the display.
        Results go to on_preview_data_received instead of on_data_received."""
        if self.is_fetching:
            return
        self.is_fetching = True
        self.data_worker = GameDataWorker()
        self.data_worker.data_fetched.connect(self.on_preview_data_received)
        self.data_worker.fetch_error.connect(self._on_preview_fetch_error)
        self.data_worker.finished.connect(self.on_fetch_complete)
        self.data_worker.start()

    def _start_yesterday_fetch(self):
        """Fetch the previous day's final scores."""
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        print(f"[MLB] Starting yesterday fetch for {yesterday}")
        # Store on self so the QThread isn't garbage-collected before it finishes.
        self._yesterday_worker = GameDataWorker(fetch_date=yesterday)
        self._yesterday_worker.data_fetched.connect(self.on_yesterday_data_received)
        self._yesterday_worker.fetch_error.connect(self._on_yesterday_fetch_error)
        self._yesterday_worker.finished.connect(self._on_yesterday_worker_done)
        self._yesterday_worker.start()

    def _on_yesterday_worker_done(self):
        """Clean up the yesterday worker after it finishes."""
        if self._yesterday_worker:
            self._yesterday_worker.deleteLater()
            self._yesterday_worker = None

    def _on_yesterday_fetch_error(self):
        """Yesterday fetch failed — fall back to today's pre-game schedule."""
        print("[MLB] Yesterday fetch failed — falling back to today's pre-game schedule")
        saved = self._pending_today_games
        self._pending_today_games = []
        self._pending_today_date = ''
        self._loading_mode = False
        if saved:
            self.games = saved
            new_fp = self._games_fingerprint()
            if new_fp != self._last_ticker_fp:
                self._last_ticker_fp = new_fp
                self.build_ticker_pixmap()
                if self.ticker_pixmap:
                    raw_speed = self.settings.get('speed', 2)
                    self._scroll_speed_px_per_ms = (raw_speed * 0.5) / 16.667
            self._reschedule_update_timer()
            self.update()

    def on_yesterday_data_received(self, games):
        """Display yesterday's final scores while today's games are pre-game."""
        final_statuses = {'Final', 'Completed', 'Game Over'}
        yesterday_finals = [g for g in games if g.get('status') in final_statuses]

        if not yesterday_finals:
            print("[MLB] No final games from yesterday — staying with today's pre-game schedule")
            self._pending_today_games = []
            self._pending_today_date = ''
            self._loading_mode = False
            return

        self._yesterday_mode = True
        self._loading_mode = False
        self.games = yesterday_finals
        # Stop normal polling; use next_day_timer every 5 min to recheck the cutoff
        self.waiting_for_next_day = True
        self.update_timer.stop()
        self.next_day_timer.stop()
        self.next_day_timer.start(300_000)  # 5 min

        self._last_ticker_fp = None
        new_fp = self._games_fingerprint()
        self._last_ticker_fp = new_fp
        self.build_ticker_pixmap()
        if self.ticker_pixmap:
            raw_speed = self.settings.get('speed', 2)
            self._scroll_speed_px_per_ms = (raw_speed * 0.5) / 16.667
        self._last_frame_ms = self._elapsed_timer.nsecsElapsed() / 1_000_000.0
        self.update()
        print(f"[MLB] Yesterday mode active — showing {len(yesterday_finals)} final games")

    def _on_preview_fetch_error(self):
        """Preview fetch failed — stay in yesterday mode and retry next cycle."""
        print("[MLB] Preview fetch failed — staying in yesterday mode, will retry")

    def on_preview_data_received(self, games):
        """Handle today's schedule while still showing yesterday's finals."""
        current_date = datetime.datetime.now().strftime('%Y-%m-%d')
        self._pending_today_games = games
        self._pending_today_date = current_date

        # Enter yesterday mode on first successful preview fetch
        if not self._yesterday_mode:
            self._yesterday_mode = True
            print("[MLB] Entering yesterday mode — continuing to show previous day's results")
            # Repaint to show the YESTERDAY badge (badge is rendered in paintEvent)
            self.update()
            # Poll more frequently so we don't miss the cutoff window
            self.next_day_timer.start(300_000)  # Every 5 min instead of hourly

        self._check_yesterday_cutoff()

    def _minutes_to_first_game(self, games):
        """Return minutes until the earliest not-yet-started game.
        Returns None if no scheduled games exist. Negative = already past start."""
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        earliest = None
        not_started = {'Scheduled', 'Pre-Game', 'Warmup'}
        for g in games:
            if g.get('status') not in not_started:
                continue
            gdt = g.get('game_datetime')
            if not gdt:
                continue
            try:
                dt_str = str(gdt)
                if dt_str.endswith('Z'):
                    dt = datetime.datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                else:
                    dt = datetime.datetime.fromisoformat(dt_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=datetime.timezone.utc)
                delta = (dt - now_utc).total_seconds() / 60.0
                if earliest is None or delta < earliest:
                    earliest = delta
            except Exception:
                pass
        return earliest

    def _check_yesterday_cutoff(self):
        """Switch to today's games once the first pitch is within the cutoff window."""
        if not self._pending_today_games:
            return  # Nothing to switch to yet
        cutoff = self.settings.get('yesterday_cutoff_minutes', 30)
        delta = self._minutes_to_first_game(self._pending_today_games)
        if delta is None:
            # No scheduled games (off-day, or all games already in progress/final)
            print("[MLB] No pending scheduled games — switching to today immediately")
            self._exit_yesterday_mode()
        elif delta <= cutoff:
            print(f"[MLB] First game in {delta:.0f} min (≤ {cutoff} min cutoff) — switching to today")
            self._exit_yesterday_mode()
        else:
            print(f"[MLB] Yesterday mode active — first game in {delta:.0f} min (cutoff: {cutoff} min)")

    def _exit_yesterday_mode(self):
        """Transition display from yesterday's finals to today's scheduled/live games."""
        self._yesterday_mode = False
        self.waiting_for_next_day = False
        self.next_day_timer.stop()
        # Promote pending today's data to live display
        self.games = self._pending_today_games
        self._cached_games = self._pending_today_games
        self.last_fetch_date = self._pending_today_date
        self._pending_today_games = []
        self._pending_today_date = ''
        # Rebuild ticker and resume normal polling
        self._last_ticker_fp = None
        new_fp = self._games_fingerprint()
        self._last_ticker_fp = new_fp
        self.build_ticker_pixmap()
        if self.ticker_pixmap:
            raw_speed = self.settings.get('speed', 2)
            self._scroll_speed_px_per_ms = (raw_speed * 0.5) / 16.667
        self._reschedule_update_timer()
        self.update()
        print("[MLB] Exited yesterday mode — showing today's games")

    # ------------------------------------------------------------------
    # Startup intro animation
    # ------------------------------------------------------------------

    def build_intro_animation(self):
        """Build the intro pixmap and initialise the pixel-reveal state.

        All pixmaps are created at native PHYSICAL resolution WITHOUT DPR set so
        that the block-painting loop can work in raw physical pixel coordinates
        regardless of the display scale factor.
        """
        w = self.width() or QtWidgets.QApplication.primaryScreen().geometry().width()
        h = self.ticker_height
        bs = self.intro_block_size  # logical block size

        # Convert everything to physical pixels so block ops are 1:1
        w_phys = int(w * self.dpr)
        h_phys = int(h * self.dpr)
        bs_phys = max(1, int(bs * self.dpr))  # physical block size
        self._intro_bs_phys = bs_phys

        # Font: use Ozone-xRRO for the intro, fall back to ticker font
        ozone_family = load_ozone_font() or self.font_family
        intro_font = QtGui.QFont(ozone_family)
        intro_font.setPixelSize(max(12, int(h_phys * 0.35 * 2.25)))  # size in physical px (+20%)

        text = "MLB-TCKR"
        metrics = QtGui.QFontMetrics(intro_font)
        text_width = metrics.horizontalAdvance(text)
        # Use tightBoundingRect for "MLB-" so only the actual ink width is used
        # (horizontalAdvance includes the font's right-side bearing after the
        # hyphen, which renders as a visible gap before "TCKR").
        part1 = "MLB-"
        part2 = "TCKR"
        # right() of tightBoundingRect is the x of the last ink pixel — draw
        # part2 immediately after that, plus 1px so they don't touch.
        part1_ink_right = metrics.tightBoundingRect(part1).right() + 1

        # Logo – pass physical height so _load_intro_logo returns a raw physical pixmap
        logo_h_phys = int(h_phys * 0.984)  # 0.82 * 1.2 (+20%)
        logo_pm = self._load_intro_logo(logo_h_phys)
        logo_w = logo_pm.width() if logo_pm else 0  # already in physical pixels
        gap = int(14 * self.dpr)

        content_w = logo_w + (gap if logo_pm else 0) + text_width
        start_x = (w_phys - content_w) // 2
        logo_y = (h_phys - logo_h_phys) // 2
        text_y = (h_phys + metrics.ascent() - metrics.descent()) // 2

        # Full intro pixmap at physical resolution — NO DPR set (raw pixel surface)
        self.intro_pixmap = QtGui.QPixmap(w_phys, h_phys)
        self.intro_pixmap.fill(QtCore.Qt.transparent)

        p = QtGui.QPainter(self.intro_pixmap)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, self._text_aa_hint)
        if logo_pm:
            p.drawPixmap(start_x, logo_y, logo_pm)
        p.setFont(intro_font)
        p.setPen(QtGui.QColor('#00FF00'))
        text_x = start_x + logo_w + (gap if logo_pm else 0)
        p.drawText(text_x, text_y, part1)
        p.drawText(text_x + part1_ink_right, text_y, part2)
        p.end()

        # Display pixmap starts fully transparent — NO DPR set.
        # cached_background shows through until blocks are revealed.
        self.intro_display = QtGui.QPixmap(w_phys, h_phys)
        self.intro_display.fill(QtCore.Qt.transparent)

        # Build shuffled block list in physical pixel grid
        cols = max(1, w_phys // bs_phys)
        rows = max(1, h_phys // bs_phys)
        blocks = [(r, c) for r in range(rows) for c in range(cols)]
        random.shuffle(blocks)
        self.intro_all_blocks = blocks
        self.intro_revealed_count = 0
        # ~3 s at 30 fps for both in and out transitions (90 frames per phase)
        self._intro_bpf = max(1, len(blocks) // 90)
        self.intro_hold_frames = 0
        print(f"[INTRO] {len(blocks)} blocks ({cols}x{rows}), {self._intro_bpf} blocks/frame, ~3 s per phase")

    def _load_intro_logo(self, phys_size):
        """Find and return mlb-reverse.png scaled to `phys_size` PHYSICAL pixels tall.

        Returns a raw (no DPR set) pixmap so it can be painted directly onto the
        physical-resolution intro_pixmap surface.
        """
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        search_dirs = [
            os.path.join(APPDATA_DIR, "MLB-TCKR.images"),
            APPDATA_DIR,
            os.path.join(_script_dir, "MLB-TCKR.images"),
            _script_dir,
        ]
        runtime_base = getattr(sys, '_MEIPASS', None)
        if runtime_base:
            search_dirs.insert(1, os.path.join(runtime_base, "MLB-TCKR.images"))
            search_dirs.insert(2, runtime_base)
        for d in search_dirs:
            path = os.path.join(d, "mlb-reverse.png")
            if os.path.exists(path):
                pm = QtGui.QPixmap(path)
                if not pm.isNull():
                    scaled = pm.scaled(
                        int(phys_size), int(phys_size),
                        QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
                    )
                    # No setDevicePixelRatio — raw physical surface
                    print(f"[INTRO] Loaded mlb-reverse.png from {path}")
                    return scaled
        print("[INTRO] mlb-reverse.png not found")
        return None

    def update_intro(self):
        """Advance the pixel-reveal animation by one frame (~30 fps)."""
        if not self.intro_active:
            self.intro_timer.stop()
            return

        blocks = self.intro_all_blocks
        bpf = self._intro_bpf
        bs = self._intro_bs_phys  # physical block size — matches raw pixmap coordinates

        if self.intro_phase == 'in':
            end = min(self.intro_revealed_count + bpf, len(blocks))
            p = QtGui.QPainter(self.intro_display)
            for i in range(self.intro_revealed_count, end):
                r, c = blocks[i]
                p.drawPixmap(
                    QtCore.QRect(c * bs, r * bs, bs, bs),
                    self.intro_pixmap,
                    QtCore.QRect(c * bs, r * bs, bs, bs),
                )
            p.end()
            self.intro_revealed_count = end
            if self.intro_revealed_count >= len(blocks):
                # Snap to the full frame to eliminate any sub-block gaps
                self.intro_display = self.intro_pixmap.copy()
                self.intro_phase = 'hold'
                self.intro_hold_frames = 0

        elif self.intro_phase == 'hold':
            self.intro_hold_frames += 1
            if self.intro_hold_frames >= 150:   # 5 s × 30 fps
                random.shuffle(self.intro_all_blocks)
                self.intro_revealed_count = len(blocks)
                self.intro_phase = 'out'

        elif self.intro_phase == 'out':
            end = max(self.intro_revealed_count - bpf, 0)
            p = QtGui.QPainter(self.intro_display)
            # Erase blocks back to transparent so cached_background shows through
            p.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
            for i in range(end, self.intro_revealed_count):
                r, c = blocks[i]
                p.fillRect(QtCore.QRect(c * bs, r * bs, bs, bs), QtCore.Qt.transparent)
            p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
            p.end()
            self.intro_revealed_count = end
            if self.intro_revealed_count <= 0:
                self.intro_active = False
                self.intro_phase = 'done'
                self.intro_timer.stop()
                self.intro_pixmap = None
                self.intro_display = None
                # Start from off-screen right so the ticker scrolls in from the edge
                self.scroll_offset = -float(self.width())
                # Reset elapsed timer so first delta_ms is sane after the intro pause
                self._last_frame_ms = self._elapsed_timer.nsecsElapsed() / 1_000_000.0
                # Kick off normal scrolling now that intro is finished
                self.scroll_timer.start(self._scroll_timer_interval_ms)
                print("[INTRO] Complete — starting ticker scroll from off-screen right")

        self.update()

    def _games_fingerprint(self):
        """Return a tuple encoding all data that visually affects the ticker.
        If it matches the last build's fingerprint the rebuild is skipped entirely."""
        s = self.settings
        settings_key = (s.get('show_team_records', True), s.get('show_team_cities', False))
        parts = []
        for g in self.games:
            r = g.get('runners', {})
            parts.append((
                g.get('game_id'), g.get('status'),
                g.get('away_score'), g.get('home_score'),
                g.get('current_inning'), g.get('inning_state'), g.get('outs'),
                g.get('balls'), g.get('strikes'),
                g.get('away_subtext'), g.get('home_subtext'),
                g.get('pitcher_pitches'), g.get('pitcher_side'),
                bool(r.get('first')), bool(r.get('second')), bool(r.get('third')),
                g.get('away_record'), g.get('home_record'),
            ))
        return (settings_key, tuple(parts))

    def build_ticker_pixmap(self):
        """Build the complete ticker pixmap with all games"""
        if not self.games:
            # No games today OR no network data — pick the right message
            if self._no_data_mode:
                text = "No data — check network connection"
            else:
                text = "No MLB games scheduled today"

            metrics = QtGui.QFontMetrics(self._qfont)
            text_w = metrics.horizontalAdvance(text)
            margin_l = 40
            margin_r = 120  # gap after the text before the next loop copy
            win_w = max(self.width(), 100)
            # Make each segment at least as wide as the window so only ONE copy of
            # the text is ever visible at a time — no "3 copies" side-by-side.
            segment_w = max(margin_l + text_w + margin_r, win_w + margin_r)
            # Tile enough copies to guarantee the pixmap always fills the window
            # even after the seamless offset-0 wrap.
            num_copies = max(2, (win_w // segment_w) + 2)
            full_w = segment_w * num_copies
            self.ticker_pixmap = QtGui.QPixmap(int(full_w * self.dpr), int(self.ticker_height * self.dpr))
            self.ticker_pixmap.setDevicePixelRatio(self.dpr)
            self.ticker_pixmap.fill(QtCore.Qt.black)
            # Use actual visual bounding rect so pixel/LED fonts center correctly
            _br = metrics.boundingRect('ABCWMgy0123456789')
            text_y = (self.ticker_height - _br.height()) // 2 - _br.top()
            painter = QtGui.QPainter(self.ticker_pixmap)
            painter.setRenderHint(QtGui.QPainter.TextAntialiasing, self._text_aa_hint)
            painter.setFont(self._qfont)
            painter.setPen(QtGui.QColor('#FFFFFF'))
            for i in range(num_copies):
                painter.drawText(i * segment_w + margin_l, text_y, text)
            painter.end()
            self._scroll_max_width = float(segment_w)
            self._ticker_tiles = []  # clear tiles so paintEvent uses the message pixmap
            # Only reset the scroll position when the message itself has changed
            # (avoids jarring off-screen snap on every periodic re-fetch failure).
            if text != self._message_text:
                self._message_text = text
                self.scroll_offset = -float(win_w)
            return
        
        # MLB logo shown at the start of each ticker loop
        logo_size = int(self.ticker_height * 0.625)
        logo_padding = 40  # logical pixels of space on each side of the MLB logo
        mlb_pm = self._load_mlb_logo(logo_size)
        mlb_logical_w = int(mlb_pm.width() / self.dpr) if mlb_pm else 0
        logo_segment_w = (logo_padding + mlb_logical_w + logo_padding) if mlb_pm else 0

        # Calculate total width needed
        game_pixmaps = []
        total_width = logo_segment_w
        spacing = 100

        _settings_key = (
            self.settings.get('show_team_records', True),
            self.settings.get('show_team_cities', False),
        )
        for game in self.games:
            game_id = game.get('game_id')
            r = game.get('runners', {})
            game_fp = (
                game.get('status'), game.get('away_score'), game.get('home_score'),
                game.get('current_inning'), game.get('inning_state'), game.get('outs'),
                game.get('balls'), game.get('strikes'),
                game.get('away_subtext'), game.get('home_subtext'),
                game.get('pitcher_pitches'), game.get('pitcher_side'),
                bool(r.get('first')), bool(r.get('second')), bool(r.get('third')),
                game.get('away_record'), game.get('home_record'),
                game.get('away_name'), game.get('home_name'), _settings_key,
            )
            cached_entry = self._game_pixmap_cache.get(game_id)
            if cached_entry is not None and cached_entry[0] == game_fp:
                pixmap = cached_entry[1]
            else:
                pixmap = self.build_game_pixmap(game)
                self._game_pixmap_cache[game_id] = (game_fp, pixmap)
            game_pixmaps.append(pixmap)
            # pixmap.width() is physical pixels; divide by dpr to get logical width
            total_width += int(pixmap.width() / self.dpr) + spacing

        # Build the tile list for one period instead of pre-baking everything
        # into a single giant pixmap (which exceeds GPU texture limits at high DPR
        # with many games — e.g. 80 000+ physical pixels).
        tiles = []
        x_offset = 0

        # MLB logo tile at the head of the period
        if mlb_pm:
            logo_y = (self.ticker_height - int(mlb_pm.height() / self.dpr)) // 2
            tiles.append((x_offset + logo_padding, logo_y, mlb_pm))
            x_offset += logo_segment_w

        for pixmap in game_pixmaps:
            tiles.append((x_offset, 0, pixmap))
            x_offset += int(pixmap.width() / self.dpr) + spacing

        self._ticker_tiles = tiles
        self._scroll_max_width = float(total_width)
        # Set a truthy sentinel so existing `if self.ticker_pixmap:` checks work.
        # paintEvent uses _ticker_tiles for actual drawing.
        self.ticker_pixmap = True

    def _load_mlb_logo(self, logo_size):
        """Load mlb.png scaled to logo_size logical pixels tall, DPR-aware (cached)."""
        cache_key = (int(logo_size), self.dpr)
        cached = MLB_LOGO_CACHE.get(cache_key)
        if cached is not None:
            return cached

        images_dirs = [
            os.path.join(APPDATA_DIR, "MLB-TCKR.images"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "MLB-TCKR.images"),
        ]
        runtime_base = getattr(sys, '_MEIPASS', None)
        if runtime_base:
            images_dirs.insert(1, os.path.join(runtime_base, "MLB-TCKR.images"))
        for d in images_dirs:
            path = os.path.join(d, "mlb.png")
            if os.path.exists(path):
                pm = QtGui.QPixmap(path)
                if not pm.isNull():
                    phys = int(logo_size * self.dpr)
                    scaled = pm.scaled(phys, phys, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
                    scaled.setDevicePixelRatio(self.dpr)
                    print(f"[TICKER] Loaded mlb.png from {path}")
                    MLB_LOGO_CACHE[cache_key] = scaled
                    return scaled
        print("[TICKER] mlb.png not found in images dirs")
        MLB_LOGO_CACHE[cache_key] = None  # cache the miss so we don't re-scan
        return None
    
    def build_game_pixmap(self, game):
        """Build pixmap for a single game"""
        status = game['status']
        away_team_full = game['away_name']
        home_team_full = game['home_name']
        
        # Use nickname only if show_team_cities is False
        if not self.settings.get('show_team_cities', True):
            away_team = get_team_nickname(away_team_full)
            home_team = get_team_nickname(home_team_full)
        else:
            away_team = away_team_full
            home_team = home_team_full
        
        # Capitalize team names
        away_team = away_team.upper()
        home_team = home_team.upper()
        
        away_score = game['away_score']
        home_score = game['home_score']
        away_record = game.get('away_record', '0-0')
        home_record = game.get('home_record', '0-0')
        show_records = self.settings.get('show_team_records', True)
        live_subtext_enabled = status in ['In Progress', 'Live', 'Final', 'Completed', 'Game Over']
        scheduled_subtext_enabled = status in ['Scheduled', 'Preview', 'Pre-Game']

        # Get subtext (player info) only when show_records is on.
        # When disabled, neither W-L records nor player/pitcher names are shown.
        away_subtext = game.get('away_subtext') if show_records and (live_subtext_enabled or scheduled_subtext_enabled) else None
        home_subtext = game.get('home_subtext') if show_records and (live_subtext_enabled or scheduled_subtext_enabled) else None

        away_record_text = str(away_record).strip('()')
        home_record_text = str(home_record).strip('()')

        away_detail_text = away_subtext if away_subtext else away_record_text
        home_detail_text = home_subtext if home_subtext else home_record_text
        
        logo_size = int(self.ticker_height * 0.625)
        metrics = QtGui.QFontMetrics(self._qfont)
        small_metrics = QtGui.QFontMetrics(self.small_font)
        tiny_metrics = QtGui.QFontMetrics(self.tiny_font)
        time_metrics = QtGui.QFontMetrics(self.time_font)

        # Pitcher pitch count — only for live games
        is_live = status in ['In Progress', 'Live']
        pitcher_pitches = game.get('pitcher_pitches') if is_live else None
        pitcher_side = game.get('pitcher_side', 'home') if is_live else None
        pitch_count_text = f"P:{pitcher_pitches}" if pitcher_pitches is not None else ""
        pitch_count_extra = tiny_metrics.horizontalAdvance(" " + pitch_count_text) if pitch_count_text else 0
        
        # Get team colors (use full name for color lookup)
        away_color = QtGui.QColor(get_team_color(away_team_full))
        home_color = QtGui.QColor(get_team_color(home_team_full))
        
        # Calculate widths
        away_name_width = metrics.horizontalAdvance(away_team)
        home_name_width = metrics.horizontalAdvance(home_team)
        away_record_width = small_metrics.horizontalAdvance(away_detail_text) if show_records else 0
        home_record_width = small_metrics.horizontalAdvance(home_detail_text) if show_records else 0
        # Include pitch count width in the pitcher side's block
        if pitcher_side == 'away':
            away_record_width += pitch_count_extra
        elif pitcher_side == 'home':
            home_record_width += pitch_count_extra
        away_block_width = max(away_name_width, away_record_width)
        home_block_width = max(home_name_width, home_record_width)

        # Moneyline odds — look up from cache, format as +/- string
        # Never show odds on completed/final games (stale cache carries over to next day)
        _game_is_final = status in ['Final', 'Completed', 'Game Over']
        show_moneyline = self.settings.get('show_moneyline', False) and not _game_is_final
        odds_gap = 5  # px between odds text and team name
        away_price, home_price = self._get_game_odds(away_team_full, home_team_full)
        away_odds_text = format_moneyline(away_price) if (show_moneyline and away_price is not None) else ''
        home_odds_text = format_moneyline(home_price) if (show_moneyline and home_price is not None) else ''
        away_odds_w = small_metrics.horizontalAdvance(away_odds_text) if away_odds_text else 0
        home_odds_w = small_metrics.horizontalAdvance(home_odds_text) if home_odds_text else 0
        # W-L record width for the side column (used even when no odds are shown)
        away_record_col_w = small_metrics.horizontalAdvance(away_record_text) if show_records else 0
        home_record_col_w = small_metrics.horizontalAdvance(home_record_text) if show_records else 0
        # Side column width = widest of W-L and odds (whichever is present)
        away_col_w = max(away_record_col_w, away_odds_w)
        home_col_w = max(home_record_col_w, home_odds_w)
        # Widen blocks to fit the side column (away: column on left; home: column on right)
        if away_col_w > 0:
            away_top_w = away_col_w + odds_gap + away_name_width
            away_block_width = max(away_top_w, away_record_width)
        if home_col_w > 0:
            home_top_w = home_name_width + odds_gap + home_col_w
            home_block_width = max(home_top_w, home_record_width)

        # Calculate width based on game status
        if status in ['In Progress', 'Live', 'Final', 'Completed', 'Game Over']:
            # Live or Final game: Team Logo Score | Diamond/F-label | Score Logo Team
            is_final = status in ['Final', 'Completed', 'Game Over']

            score_width = metrics.horizontalAdvance("99")

            if is_final:
                # "F" for 9 innings or fewer; "F10", "F11", etc. for extra innings
                _final_inning = game.get('current_inning', 9)
                try:
                    _final_inning = int(_final_inning)
                except (TypeError, ValueError):
                    _final_inning = 9
                final_label = f"F{_final_inning}" if _final_inning > 9 else "F"
                _vs_fm = QtGui.QFontMetrics(self.vs_font)
                final_label_width = _vs_fm.horizontalAdvance(final_label)
                effective_after_diamond = final_label_width + 16  # 8 px padding each side
                diamond_pixmap = None
            else:
                final_label = None
                diamond_pixmap = draw_baseball_diamond(
                    game['runners'],
                    game['outs'],
                    game.get('current_inning', 1),
                    game.get('inning_state', '') == 'Top',
                    size=int(self.ticker_height * 0.7),
                    dpr=self.dpr,
                    balls=game.get('balls'),
                    strikes=game.get('strikes'),
                )
                diamond_logical_width = int(diamond_pixmap.width() / self.dpr)
                # _inning_text_right_phys is stored in logical coords
                inning_text_right = getattr(diamond_pixmap, '_inning_text_right_phys', 0)
                effective_after_diamond = max(diamond_logical_width, int(inning_text_right)) + 6

            # Layout: Team, Logo, Score, Diamond+gap, Score, Logo, Team
            # Gaps mirror each other: name(5)logo(15)score(8)diamond+gap(6)score(15)logo(5)name
            total_width = (away_block_width + 5 + logo_size + 15 + 
                          score_width + 8 + effective_after_diamond + 
                          score_width + 15 + logo_size + 5 + home_block_width)
        else:
            # Scheduled games: Team Logo Time/vs Logo Team
            # W-L record sits above moneyline (vertically stacked) in side columns
            status_text = format_game_time_local(game.get('game_datetime'))
            
            status_width = time_metrics.horizontalAdvance(status_text) + 10
            _vs_fm = QtGui.QFontMetrics(self.vs_font)
            _vs_w = _vs_fm.horizontalAdvance("vs")
            
            # Reuse away_col_w / home_col_w (max of W-L and odds widths) already computed
            # Calculate subtext width (probable pitcher info)
            away_subtext_w = small_metrics.horizontalAdvance(away_subtext) if away_subtext else 0
            sched_away_w = max(
                (away_col_w + odds_gap if away_col_w > 0 else 0) + away_name_width,
                away_subtext_w)

            home_subtext_w = small_metrics.horizontalAdvance(home_subtext) if home_subtext else 0
            sched_home_w = max(
                home_name_width + (odds_gap + home_col_w if home_col_w > 0 else 0),
                home_subtext_w)

            # Layout: away_block -> logo -> time/vs -> logo -> home_block
            center_element_w = max(status_width, _vs_w)
            total_width = (sched_away_w + 5 + logo_size + 15 +
                          center_element_w + 15 +
                          logo_size + 5 + sched_home_w)

        # Create pixmap at physical resolution so text renders at native DPR
        pixmap = QtGui.QPixmap(int(total_width * self.dpr), int(self.ticker_height * self.dpr))
        pixmap.setDevicePixelRatio(self.dpr)
        pixmap.fill(QtCore.Qt.transparent)
        
        # Verify pixmap creation succeeded
        if pixmap.isNull():
            print(f"[ERROR] Failed to create pixmap: width={total_width} height={self.ticker_height} dpr={self.dpr}")
            return QtGui.QPixmap(1, 1)  # Return minimal pixmap to avoid crash
        
        painter = QtGui.QPainter(pixmap)
        # Disable anti-aliasing for LED fonts - PreferBitmap removed, so let Qt render TrueType normally
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, self._text_aa_hint)
        
        x = 0
        logo_y = (self.ticker_height - logo_size) // 2
        # Use actual visual bounding rect so pixel/LED fonts center correctly
        _br = metrics.boundingRect('ABCWMgy0123456789')
        text_y = (self.ticker_height - _br.height()) // 2 - _br.top()
        time_y = text_y
        record_y = None
        # Calculate record_y only when show_records is on.
        if show_records:
            line_gap = 2  # Minimum spacing between team names and player info
            text_y = -_br.top() + 4
            record_y = text_y + _br.bottom() + line_gap + small_metrics.ascent()
            record_y -= 5  # Move player info up by a few pixels
            max_record_y = self.ticker_height - 2 - small_metrics.descent()
            if record_y > max_record_y:
                delta = record_y - max_record_y
                text_y -= delta
                record_y -= delta
        time_y = text_y
        # odds_y: place the small-font baseline so its cap-letter top aligns with the
        # cap-letter top of the main font. capHeight() is the purpose-built Qt metric
        # for this; fall back to digit-only bounding rect for fonts that omit it.
        _main_cap = metrics.capHeight()
        if _main_cap <= 0:
            _main_cap = -metrics.boundingRect('0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ').top()
        _small_cap = small_metrics.capHeight()
        if _small_cap <= 0:
            _small_cap = -small_metrics.boundingRect('0123456789').top()
        odds_y = text_y - _main_cap + _small_cap

        if status in ['In Progress', 'Live', 'Final', 'Completed', 'Game Over']:
            # Away team name (colored) — W-L record floats to the left, top-aligned;
            # moneyline odds appear below the W-L when present.
            painter.setFont(self._qfont)
            painter.setPen(away_color)
            if away_col_w > 0:
                away_top_w = away_col_w + odds_gap + away_name_width
                unit_off = (away_block_width - away_top_w) // 2
                away_col_draw_x = x + unit_off
                away_name_x = away_col_draw_x + away_col_w + odds_gap
            else:
                away_col_draw_x = None
                away_name_x = x + (away_block_width - away_name_width) // 2
            if away_col_draw_x is not None:
                # W-L on top
                if show_records:
                    painter.setFont(self.small_font)
                    painter.setPen(QtGui.QColor('#BDBDBD'))
                    painter.drawText(away_col_draw_x, odds_y, away_record_text)
                # Moneyline below W-L
                if away_odds_text:
                    _ac = QtGui.QColor('#00FF44') if (away_price or 0) > 0 else QtGui.QColor('#FF6B6B')
                    painter.setFont(self.small_font)
                    painter.setPen(_ac)
                    odds_below_wl_y = odds_y + small_metrics.descent() + 2 + small_metrics.ascent()
                    painter.drawText(away_col_draw_x, odds_below_wl_y, away_odds_text)
                painter.setFont(self._qfont)
                painter.setPen(away_color)
            painter.drawText(away_name_x, text_y, away_team)
            if show_records and record_y is not None:
                painter.setFont(self.small_font)
                painter.setPen(QtGui.QColor('#BDBDBD'))
                # Right-justify player info within away_block (ends near logo)
                detail_w = small_metrics.horizontalAdvance(away_detail_text)
                pc_total_w = (tiny_metrics.horizontalAdvance(pitch_count_text) + 6) if (pitch_count_text and pitcher_side == 'away') else 0
                away_record_x = away_block_width - detail_w - pc_total_w
                painter.drawText(away_record_x, record_y, away_detail_text)
                if pitch_count_text and pitcher_side == 'away':
                    painter.setFont(self.tiny_font)
                    painter.setPen(QtGui.QColor('#BDBDBD'))
                    pc_x = away_record_x + detail_w + 6
                    painter.drawText(pc_x, record_y, pitch_count_text)
            x += away_block_width + 5
            
            # Away team logo
            away_logo = get_team_logo(away_team_full, logo_size)
            painter.drawPixmap(x, logo_y, away_logo)
            x += logo_size + 15  # More space between logo and score
            
            # Away score (on same line as team name)
            painter.setFont(self._qfont)
            painter.setPen(QtGui.QColor('#FFFFFF'))
            score_width = metrics.horizontalAdvance(str(away_score))
            painter.drawText(x, text_y, str(away_score))
            x += score_width + 8
            
            # Diamond (live) or Final label (finished games)
            if is_final:
                _vs_fm_p = QtGui.QFontMetrics(self.vs_font)
                _fl_w  = _vs_fm_p.horizontalAdvance(final_label)
                _fl_br = _vs_fm_p.boundingRect(final_label)
                _fl_x  = x + (effective_after_diamond - _fl_w) // 2 - 6  # Shift left for better centering between scores
                _fl_y  = (self.ticker_height - _fl_br.height()) // 2 - _fl_br.top()
                painter.setFont(self.vs_font)
                painter.setPen(QtGui.QColor('#FFD700'))
                painter.drawText(_fl_x, _fl_y, final_label)
            else:
                diamond_y = (self.ticker_height - int(diamond_pixmap.height() / self.dpr)) // 2 - 2
                painter.drawPixmap(x, diamond_y, diamond_pixmap)
            x += effective_after_diamond

            # Home score (on same line as team name)
            painter.setFont(self._qfont)
            painter.setPen(QtGui.QColor('#FFFFFF'))
            score_width = metrics.horizontalAdvance(str(home_score))
            painter.drawText(x, text_y, str(home_score))
            x += score_width + 15  # Mirror: logo→score gap on away side
            
            # Home logo
            home_logo = get_team_logo(home_team_full, logo_size)
            painter.drawPixmap(x, logo_y, home_logo)
            x += logo_size + 5  # Mirror: name→logo gap on away side
            
            # Home team name (colored) — W-L record floats to the right, top-aligned;
            # moneyline odds appear below the W-L when present.
            painter.setFont(self._qfont)
            painter.setPen(home_color)
            if home_col_w > 0:
                home_top_w = home_name_width + odds_gap + home_col_w
                unit_off = (home_block_width - home_top_w) // 2
                home_name_x = x + unit_off
                home_col_draw_x = home_name_x + home_name_width + odds_gap
            else:
                home_name_x = x + (home_block_width - home_name_width) // 2
                home_col_draw_x = None
            painter.drawText(home_name_x, text_y, home_team)
            if home_col_draw_x is not None:
                # W-L on top
                if show_records:
                    painter.setFont(self.small_font)
                    painter.setPen(QtGui.QColor('#BDBDBD'))
                    painter.drawText(home_col_draw_x, odds_y, home_record_text)
                # Moneyline below W-L
                if home_odds_text:
                    _hc = QtGui.QColor('#00FF44') if (home_price or 0) > 0 else QtGui.QColor('#FF6B6B')
                    painter.setFont(self.small_font)
                    painter.setPen(_hc)
                    odds_below_wl_y = odds_y + small_metrics.descent() + 2 + small_metrics.ascent()
                    painter.drawText(home_col_draw_x, odds_below_wl_y, home_odds_text)
            if show_records and record_y is not None:
                painter.setFont(self.small_font)
                painter.setPen(QtGui.QColor('#BDBDBD'))
                # Left-justify player info at start of home_block (near logo)
                home_record_x = x
                painter.drawText(home_record_x, record_y, home_detail_text)
                if pitch_count_text and pitcher_side == 'home':
                    painter.setFont(self.tiny_font)
                    painter.setPen(QtGui.QColor('#BDBDBD'))
                    detail_w = small_metrics.horizontalAdvance(home_detail_text)
                    pc_x = home_record_x + detail_w + 6
                    painter.drawText(pc_x, record_y, pitch_count_text)

        else:
            # Scheduled games: new layout with time above vs, W-L above moneyline in side columns

            # Away team: W-L (top) and moneyline (below) stacked to left of team name
            if away_col_w > 0:
                away_name_x = x + away_col_w + odds_gap
            else:
                away_name_x = x

            # Draw W-L (top of left column)
            if show_records:
                painter.setFont(self.small_font)
                painter.setPen(QtGui.QColor('#BDBDBD'))
                painter.drawText(x, odds_y, away_record_text)

            # Draw moneyline (below W-L in left column)
            if away_odds_text:
                _ac = QtGui.QColor('#00FF44') if (away_price or 0) > 0 else QtGui.QColor('#FF6B6B')
                painter.setFont(self.small_font)
                painter.setPen(_ac)
                odds_below_wl_y = odds_y + small_metrics.descent() + 2 + small_metrics.ascent()
                painter.drawText(x, odds_below_wl_y, away_odds_text)

            # Draw team name
            painter.setFont(self._qfont)
            painter.setPen(away_color)
            painter.drawText(away_name_x, text_y, away_team)

            # Probable pitcher below team name (right-justified within away block)
            if away_subtext and record_y is not None:
                painter.setFont(self.small_font)
                painter.setPen(QtGui.QColor('#BDBDBD'))
                away_subtext_x = max(x, x + sched_away_w - away_subtext_w)
                painter.drawText(away_subtext_x, record_y, away_subtext)

            x += sched_away_w + 5

            # Away team logo
            away_logo = get_team_logo(away_team_full, logo_size)
            painter.drawPixmap(x, logo_y, away_logo)
            x += logo_size + 15

            # Time above vs (centered in the gap between logos)
            if status in ['Final', 'Completed', 'Game Over']:
                status_text = "FINAL"
            elif status == 'Postponed':
                status_text = "PPD"
            elif 'game_datetime' in game:
                status_text = format_game_time_local(game.get('game_datetime'))
            else:
                status_text = ""
            
            painter.setFont(self.time_font)
            painter.setPen(QtGui.QColor('#00B3FF'))
            time_w = time_metrics.horizontalAdvance(status_text)
            center_element_w = max(time_w, _vs_fm.horizontalAdvance("vs"))
            time_x = x + (center_element_w - time_w) // 2
            # Position time above vs — calculate based on font metrics
            time_br = time_metrics.boundingRect(status_text)
            time_above_y = (self.ticker_height - time_br.height() - _vs_fm.boundingRect("vs").height() - 3) // 2 - time_br.top()
            painter.drawText(time_x, time_above_y, status_text)
            
            # vs below time
            painter.setFont(self.vs_font)
            painter.setPen(QtGui.QColor("#FFFFFF"))
            vs_x = x + (center_element_w - _vs_fm.horizontalAdvance("vs")) // 2
            vs_br = _vs_fm.boundingRect("vs")
            vs_below_y = time_above_y + time_br.bottom() + 1 + _vs_fm.ascent()
            painter.drawText(vs_x, vs_below_y, "vs")
            x += center_element_w + 15
            
            # Home logo
            home_logo = get_team_logo(home_team_full, logo_size)
            painter.drawPixmap(x, logo_y, home_logo)
            x += logo_size + 5
            
            # Home team: team name with W-L (top) and moneyline (below) stacked to right
            painter.setFont(self._qfont)
            painter.setPen(home_color)
            home_name_x = x
            painter.drawText(home_name_x, text_y, home_team)

            # Right column starts after team name + gap
            home_right_col_x = home_name_x + home_name_width + odds_gap

            # Draw W-L (top of right column)
            if show_records:
                painter.setFont(self.small_font)
                painter.setPen(QtGui.QColor('#BDBDBD'))
                painter.drawText(home_right_col_x, odds_y, home_record_text)

            # Draw moneyline (below W-L in right column)
            if home_odds_text:
                _hc = QtGui.QColor('#00FF44') if (home_price or 0) > 0 else QtGui.QColor('#FF6B6B')
                painter.setFont(self.small_font)
                painter.setPen(_hc)
                odds_below_wl_y = odds_y + small_metrics.descent() + 2 + small_metrics.ascent()
                painter.drawText(home_right_col_x, odds_below_wl_y, home_odds_text)

            # Probable pitcher below team name
            if home_subtext and record_y is not None:
                painter.setFont(self.small_font)
                painter.setPen(QtGui.QColor('#BDBDBD'))
                painter.drawText(home_name_x, record_y, home_subtext)
        
        painter.end()
        return pixmap
    
    def update_scroll(self):
        """Trigger a repaint; scroll position is computed at actual render time
        inside paintEvent to avoid timer-callback lag and missed-tick jumps."""
        if not self.ticker_pixmap or self._scroll_max_width == 0:
            return
        self.update()
    
    def paintEvent(self, event):
        """Optimized paint event with cached backgrounds"""
        painter = QtGui.QPainter(self)
        # Antialiasing is off for backgrounds/overlays (pixel-perfect blits).
        # SmoothPixmapTransform is enabled only for the scrolling ticker blit
        # so it can be positioned at sub-pixel offsets without quantization stutter.

        # Always draw the dark background first so the bar is never transparent/white
        settings = self.settings  # already in memory — never read disk inside paintEvent
        led_background = settings.get('led_background', True)
        glass_overlay = settings.get('glass_overlay', True)
        bg_opacity = settings.get('background_opacity', 230)

        # Use a tuple instead of a dict to avoid per-frame heap allocation
        bg_key = (led_background, bg_opacity, self.width(), self.height())
        if self._cached_bg_key != bg_key or self.cached_background is None:
            self.cached_background = QtGui.QPixmap(self.width(), self.height())
            self.cached_background.fill(QtCore.Qt.transparent)

            bg_painter = QtGui.QPainter(self.cached_background)
            if led_background:
                # Deep blue-grey base — each "LED cell" will be 2×2 lit pixels
                # separated by 1px dark gutters on both axes
                gradient = QtGui.QLinearGradient(0, 0, 0, self.height())
                gradient.setColorAt(0.0,  QtGui.QColor(10, 20, 34, bg_opacity))
                gradient.setColorAt(0.40, QtGui.QColor(7,  14, 26, bg_opacity))
                gradient.setColorAt(0.70, QtGui.QColor(5,  11, 20, bg_opacity))
                gradient.setColorAt(1.0,  QtGui.QColor(3,   8, 16, bg_opacity))
                bg_painter.fillRect(self.cached_background.rect(), gradient)

                # LED pixel grid — 1px dark gutter every 3px on both axes.
                # Horizontal row gaps
                h_gap = QtGui.QColor(0, 0, 0, 160)
                for y in range(0, self.height(), 3):
                    bg_painter.fillRect(0, y, self.width(), 1, h_gap)
                # Vertical column gaps — creates the dot-matrix cell grid
                v_gap = QtGui.QColor(0, 0, 0, 130)
                for x in range(0, self.width(), 3):
                    bg_painter.fillRect(x, 0, 1, self.height(), v_gap)
            else:
                bg_painter.fillRect(self.cached_background.rect(), QtGui.QColor(0, 0, 0, bg_opacity))
            bg_painter.end()

            self._cached_bg_key = bg_key
            self.last_bg_settings = bg_key  # keep attribute for compat

        painter.drawPixmap(0, 0, self.cached_background)

        # Intro animation takes priority — draw its display pixmap and return.
        # Scale the raw physical pixmap to fill the logical widget rect so it
        # renders correctly at any display scale factor (DPR).
        if self.intro_active and self.intro_display is not None:
            painter.drawPixmap(QtCore.QRect(0, 0, self.width(), self.height()), self.intro_display)
            # Apply glass overlay over the intro the same way it applies to the normal ticker
            if glass_overlay:
                if self.cached_overlay is None or self.last_height != self.height():
                    self.cached_overlay = QtGui.QPixmap(self.width(), self.height())
                    self.cached_overlay.fill(QtCore.Qt.transparent)
                    overlay_painter = QtGui.QPainter(self.cached_overlay)
                    overlay_gradient = QtGui.QLinearGradient(0, 0, 0, self.height())
                    overlay_gradient.setColorAt(0.00, QtGui.QColor(255, 255, 255, 8))
                    overlay_gradient.setColorAt(0.08, QtGui.QColor(255, 255, 255, 30))
                    overlay_gradient.setColorAt(0.30, QtGui.QColor(255, 255, 255, 20))
                    overlay_gradient.setColorAt(0.55, QtGui.QColor(255, 255, 255, 10))
                    overlay_gradient.setColorAt(0.80, QtGui.QColor(255, 255, 255, 3))
                    overlay_gradient.setColorAt(1.00, QtGui.QColor(255, 255, 255, 0))
                    overlay_painter.fillRect(self.cached_overlay.rect(), overlay_gradient)
                    overlay_painter.end()
                    self.last_height = self.height()
                painter.drawPixmap(0, 0, self.cached_overlay)
            painter.end()
            return

        # Normal ticker (may be None if first fetch hasn't completed yet)
        if not self.ticker_pixmap:
            painter.end()
            return

        # Advance scroll position at actual render time so the displayed position
        # is accurate to *this frame*, not to when the timer callback fired.
        # nsecsElapsed() gives float-ms precision; elapsed() only returns integer ms
        # which causes ~6% delta error at 16 ms frame intervals.
        render_now_ms = self._elapsed_timer.nsecsElapsed() / 1_000_000.0
        # FPS counter: count actual paintEvent calls = true displayed frame rate
        self._fps_frame_count += 1
        _fps_elapsed = render_now_ms - self._fps_last_ms
        if _fps_elapsed >= 1000:
            self._fps_display = self._fps_frame_count * 1000.0 / _fps_elapsed
            self._fps_frame_count = 0
            self._fps_last_ms = render_now_ms
        if not self.is_hovered and not self.scroll_paused and self._scroll_speed_px_per_ms > 0:
            delta_ms = min(render_now_ms - self._last_frame_ms, 100)
            self.scroll_offset += self._scroll_speed_px_per_ms * delta_ms
            if self.scroll_offset >= self._scroll_max_width:
                self.scroll_offset = 0.0
        self._last_frame_ms = render_now_ms

        # Draw ticker at the nearest physical-pixel boundary.
        # Rounding to 1/dpr logical pixels means Qt composites at an exact physical
        # pixel — no bilinear filtering, no per-frame sharpness variation, smooth
        # motion at DPR×1 resolution (0.5 logical-px steps at DPR 2, etc.).
        phys_x = round(self.scroll_offset * self.dpr) / self.dpr
        _content_alpha = settings.get('content_opacity', 255) / 255.0
        painter.setOpacity(_content_alpha)

        # Draw tiles for visible period repetitions (avoids one giant pixmap that
        # can exceed GPU texture limits at high DPR with many games).
        period = self._scroll_max_width
        win_w = self.width()
        if self._ticker_tiles and period > 0:
            # Determine how many full periods to draw to cover the window.
            num_reps = max(2, int(win_w / period) + 2)
            for rep in range(num_reps):
                base_x = rep * period - phys_x
                # Early exit: if this repetition is entirely past the window
                if base_x > win_w:
                    break
                for (tile_x, tile_y, tile_pm) in self._ticker_tiles:
                    draw_x = base_x + tile_x
                    tile_logical_w = tile_pm.width() / self.dpr
                    # Only draw tiles that overlap the visible window
                    if draw_x + tile_logical_w > 0 and draw_x < win_w:
                        painter.drawPixmap(QtCore.QPointF(draw_x, tile_y), tile_pm)
        elif isinstance(self.ticker_pixmap, QtGui.QPixmap):
            # Fallback for no-games message pixmap (small, no GPU issue)
            painter.drawPixmap(QtCore.QPointF(-phys_x, 0), self.ticker_pixmap)

        painter.setOpacity(1.0)

        # Cache overlay if settings haven't changed
        if glass_overlay:
            if self.cached_overlay is None or self.last_height != self.height():
                self.cached_overlay = QtGui.QPixmap(self.width(), self.height())
                self.cached_overlay.fill(QtCore.Qt.transparent)

                overlay_painter = QtGui.QPainter(self.cached_overlay)
                # Glass reflection — soft bloom peaking near the top, fading
                # gradually across most of the ticker height (no hard edge line)
                overlay_gradient = QtGui.QLinearGradient(0, 0, 0, self.height())
                overlay_gradient.setColorAt(0.00, QtGui.QColor(255, 255, 255, 8))
                overlay_gradient.setColorAt(0.08, QtGui.QColor(255, 255, 255, 30))
                overlay_gradient.setColorAt(0.30, QtGui.QColor(255, 255, 255, 20))
                overlay_gradient.setColorAt(0.55, QtGui.QColor(255, 255, 255, 10))
                overlay_gradient.setColorAt(0.80, QtGui.QColor(255, 255, 255, 3))
                overlay_gradient.setColorAt(1.00, QtGui.QColor(255, 255, 255, 0))
                overlay_painter.fillRect(self.cached_overlay.rect(), overlay_gradient)
                overlay_painter.end()

                self.last_height = self.height()

            painter.drawPixmap(0, 0, self.cached_overlay)

        # "Data Delayed" badge — amber text at top-right when showing stale data
        if self._data_delayed:
            delay_text = "DATA DELAYED"
            painter.setFont(self.small_font)
            fm_d = QtGui.QFontMetrics(self.small_font)
            dw = fm_d.horizontalAdvance(delay_text)
            dh = fm_d.height()
            margin = 6
            dx = self.width() - dw - margin
            dy = dh + margin - 2
            painter.fillRect(dx - 3, margin - 2, dw + 6, dh + 2, QtGui.QColor(0, 0, 0, 160))
            painter.setPen(QtGui.QColor('#FFA500'))
            painter.drawText(dx, dy, delay_text)

        # Date badge — shown when displaying a different day's games or loading
        _badge_text = None
        _badge_color = QtGui.QColor('#FFD700')  # Gold for date labels
        if self._loading_mode:
            _badge_text = "LOADING"
            _badge_color = QtGui.QColor('#00B3FF')  # Blue for loading
        elif self._yesterday_mode or self._date_view_override == "yesterday":
            _badge_text = "YESTERDAY"
        elif self._date_view_override == "tomorrow":
            _badge_text = "TOMORROW"
        if _badge_text:
            painter.setFont(self.small_font)
            fm_y = QtGui.QFontMetrics(self.small_font)
            yw = fm_y.horizontalAdvance(_badge_text)
            yh = fm_y.height()
            margin = 6
            yx = self.width() - yw - margin
            yy = yh + margin - 2
            painter.fillRect(yx - 3, margin - 2, yw + 6, yh + 2, QtGui.QColor(0, 0, 0, 160))
            painter.setPen(_badge_color)
            painter.drawText(yx, yy, _badge_text)

        # FPS overlay — bottom-right corner, bright green, small_font
        if settings.get('show_fps_overlay', False) and self._fps_display > 0:
            fps_text = f"{self._fps_display:.1f} FPS"
            painter.setFont(self.small_font)
            fm = QtGui.QFontMetrics(self.small_font)
            tw = fm.horizontalAdvance(fps_text)
            th = fm.height()
            margin = 4
            tx = self.width() - tw - margin
            ty = self.height() - margin
            # Subtle dark backing so the text is readable over any content
            painter.fillRect(tx - 2, ty - th, tw + 4, th + 2, QtGui.QColor(0, 0, 0, 140))
            painter.setPen(QtGui.QColor('#00FF44'))
            painter.drawText(tx, ty, fps_text)

        painter.end()
    
    def enterEvent(self, event):
        """Pause scrolling when mouse enters ticker"""
        self.is_hovered = True
        self.scroll_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Resume scrolling when mouse leaves ticker"""
        self.is_hovered = False
        if not self.intro_active and not self.scroll_paused:
            self._last_frame_ms = self._elapsed_timer.nsecsElapsed() / 1_000_000.0  # reset baseline to avoid jump
            self.scroll_timer.start(self._scroll_timer_interval_ms)
        super().leaveEvent(event)

    def apply_live_settings(self):
        """Re-read settings from disk and apply all hotswappable values immediately."""
        self.settings = get_settings()

        # Speed — update scroll constant directly
        raw_speed = self.settings.get('speed', 2)
        self._scroll_speed_px_per_ms = (raw_speed * 0.5) / 16.667

        # Update interval
        self.update_timer.setInterval(self.settings.get('update_interval', 10) * 1000)

        # Rebuild fonts (size/family may have changed)
        font_scale = self.settings.get('font_scale_percent', 120) / 100.0
        preferred_font = self.settings.get('font', 'LED Board-7')
        font_to_use = self.font_family if preferred_font == 'LED Board-7' else preferred_font
        # Player info font: user-selectable (W-L records, pitcher/batter names, pitch count)
        player_info_font = self.settings.get('player_info_font', 'Gotham Black')
        # Fallback to record_font_family if selected font is not available, then to ticker font
        if player_info_font not in QtGui.QFontDatabase().families():
            player_info_font = load_record_font_family() or font_to_use
        self._qfont = QtGui.QFont(font_to_use)
        self._qfont.setPixelSize(max(12, int(self.ticker_height * 0.40 * font_scale)))
        # Check if the font was resolved correctly (not falling back to system font)
        qfont_info = QtGui.QFontInfo(self._qfont)
        is_main_font_custom = (font_to_use == qfont_info.family())
        self._qfont.setStyleStrategy(self._font_style_strategy)
        self._qfont.setHintingPreference(QtGui.QFont.PreferFullHinting)
        
        # Apply player font scale to small_font and tiny_font
        player_font_scale = self.settings.get('player_font_scale_percent', 75) / 100.0
        self.small_font = QtGui.QFont(player_info_font)
        base_small_px = max(6, int(self.ticker_height * 0.22 * font_scale * 0.5)) + 3
        self.small_font.setPixelSize(int(base_small_px * player_font_scale))
        self.small_font.setStyleStrategy(self._font_style_strategy)
        self.small_font.setHintingPreference(QtGui.QFont.PreferFullHinting)
        
        self.time_font = QtGui.QFont(font_to_use)
        self.time_font.setPixelSize(max(6, int(self.ticker_height * 0.35 * font_scale * 0.6)))
        self.time_font.setStyleStrategy(self._font_style_strategy)
        self.time_font.setHintingPreference(QtGui.QFont.PreferFullHinting)
        self.vs_font = QtGui.QFont(font_to_use)
        self.vs_font.setPixelSize(max(6, int(self.ticker_height * 0.35 * font_scale * 0.5)))
        self.vs_font.setBold(True)
        self.vs_font.setStyleStrategy(self._font_style_strategy)
        self.vs_font.setHintingPreference(QtGui.QFont.PreferFullHinting)
        
        small_px = self.small_font.pixelSize()
        self.tiny_font = QtGui.QFont(player_info_font)
        self.tiny_font.setPixelSize(max(5, small_px - 2))
        self.tiny_font.setStyleStrategy(self._font_style_strategy)
        self.tiny_font.setHintingPreference(QtGui.QFont.PreferFullHinting)

        # Force ticker pixmap rebuild to pick up new fonts / show_records / colors
        self._game_pixmap_cache.clear()
        _DIAMOND_CACHE.clear()
        self._last_ticker_fp = None
        self.build_ticker_pixmap()

        # Odds timer — start or stop based on current settings
        show_ml = self.settings.get('show_moneyline', False)
        api_key = self.settings.get('odds_api_key', '').strip()
        # Always update interval in case the user changed it
        _odds_interval_ms = max(1, self.settings.get('odds_refresh_minutes', 15)) * 60 * 1000
        self.odds_timer.setInterval(_odds_interval_ms)
        if show_ml and api_key:
            if not self.odds_timer.isActive():
                self.odds_timer.start()
            self.start_odds_fetch()   # immediate refresh when settings change
        else:
            self.odds_timer.stop()
            if not show_ml:
                # Clear cached odds so disabled moneyline doesn't render stale data
                self._odds_cache = {}

        # Background cache must be invalidated so opacity/LED/glass changes redraw
        self.cached_background = None
        self.cached_overlay = None
        self._cached_bg_key = None

        self.update()

    def _kb_set_date_override(self, override):
        """Helper: set session date override and re-fetch (does not save settings)."""
        self._date_view_override = override
        if self._yesterday_mode:
            self._yesterday_mode = False
            self.waiting_for_next_day = False
            self.next_day_timer.stop()
            self._pending_today_games = []
            self._pending_today_date = ''
        self.start_data_fetch()
        label = override if override else "auto (today)"
        print(f"[KB] Date view → {label}")

    def _kb_move_to_monitor(self, idx_1based):
        """Helper: move ticker to numbered monitor (1-based) without saving settings."""
        screens = QtWidgets.QApplication.screens()
        idx = idx_1based - 1  # convert to 0-based
        if idx < 0 or idx >= len(screens):
            print(f"[KB] Monitor {idx_1based} not available ({len(screens)} screen(s) detected) — ignored")
            return
        new_screen = screens[idx]
        if new_screen is self._target_screen:
            return  # already there
        self.remove_appbar()
        self._target_screen = new_screen
        self.dpr = new_screen.devicePixelRatio()
        # Recalculate AA strategy for the new screen's DPR
        self._font_style_strategy = (
            QtGui.QFont.NoAntialias | QtGui.QFont.NoSubpixelAntialias |
            QtGui.QFont.ForceIntegerMetrics
            if self.dpr >= 2.0 else
            QtGui.QFont.PreferAntialias | QtGui.QFont.ForceIntegerMetrics
        )
        self._text_aa_hint = self.dpr < 2.0
        for _f in (self._qfont, self.small_font, self.time_font, self.vs_font, self.tiny_font):
            _f.setStyleStrategy(self._font_style_strategy)
        geo = new_screen.geometry()
        self.setGeometry(geo.x(), geo.y(), geo.width(), self.ticker_height)
        self.setup_appbar()
        # Rebuild pixmap at new DPR
        self._game_pixmap_cache.clear()
        self._last_ticker_fp = None
        self.build_ticker_pixmap()
        self.update()
        print(f"[KB] Moved to monitor {idx_1based} ({new_screen.name()})")

    def keyPressEvent(self, event):
        """Keyboard shortcuts (active when ticker window has focus).
        Q          = quit app entirely
        S          = standings window
        .          = settings dialog
        P          = pause/unpause scroll
        G          = refresh games (does not save)
        R          = restart ticker (intro animation)
        Y          = show Yesterday's games (session-only, does not save)
        D          = pin to toDay's games; press again to return to auto (session-only, does not save)
        T          = show Tomorrow's games (session-only, does not save)
        F          = toggle FPS overlay (session-only, does not save)
        1-4        = move ticker to that monitor number (session-only, does not save)
        +/=        = increase scroll speed by 1 (session-only, does not save)
        -          = decrease scroll speed by 1 (session-only, does not save)
        """
        key  = event.text().lower()
        raw  = event.text()
        mods = event.modifiers()
        k    = event.key()

        ctrl = bool(mods & QtCore.Qt.ControlModifier)

        # ── Plus / Minus: adjust speed (session-only, not saved) ──────────────
        if k in (QtCore.Qt.Key_Plus, QtCore.Qt.Key_Equal):
            # session speed starts from stored setting if not yet overridden
            if not hasattr(self, '_session_speed'):
                self._session_speed = self.settings.get('speed', 2)
            self._session_speed = min(16, self._session_speed + 1)
            self._scroll_speed_px_per_ms = (self._session_speed * 0.5) / 16.667
            print(f"[KB] Speed → {self._session_speed}")
            return
        if k == QtCore.Qt.Key_Minus:
            if not hasattr(self, '_session_speed'):
                self._session_speed = self.settings.get('speed', 2)
            self._session_speed = max(1, self._session_speed - 1)
            self._scroll_speed_px_per_ms = (self._session_speed * 0.5) / 16.667
            print(f"[KB] Speed → {self._session_speed}")
            return

        # ── All remaining shortcuts ignore Ctrl ──────────────────────────────────
        if ctrl:
            super().keyPressEvent(event)
            return

        if key == 'q':
            QtWidgets.QApplication.instance().quit()
        elif key == 's':
            if not hasattr(self, '_standings_win') or not self._standings_win.isVisible():
                self._standings_win = StandingsWindow(ticker_widget=self)
                self._standings_win.show()
            else:
                self._standings_win.raise_()
                self._standings_win.activateWindow()
        elif raw == '.':
            SettingsDialog(self).exec_()
        elif key == 'p':
            self.scroll_paused = not self.scroll_paused
            if self.scroll_paused:
                self.scroll_timer.stop()
                print("[KB] Scroll paused")
            else:
                if not self.intro_active and not self.is_hovered:
                    self._last_frame_ms = self._elapsed_timer.nsecsElapsed() / 1_000_000.0
                    self.scroll_timer.start(self._scroll_timer_interval_ms)
                print("[KB] Scroll unpaused")
        elif key == 'g':
            self.start_data_fetch()
            print("[KB] Manual data refresh triggered")
        elif key == 'r':
            self._restart_intro()
            print("[KB] Restart triggered")
        elif key == 'y':
            self._kb_set_date_override("yesterday")
        elif key == 'd':
            # Toggle: if already pinned to today, return to auto; otherwise pin to today.
            if self._date_view_override == "today":
                self._kb_set_date_override(None)
            else:
                self._kb_set_date_override("today")
        elif key == 't':
            self._kb_set_date_override("tomorrow")
        elif key == 'f':
            # Toggle FPS overlay — session-only, not written to disk
            self.settings['show_fps_overlay'] = not self.settings.get('show_fps_overlay', False)
            self.update()
            print(f"[KB] FPS overlay → {self.settings['show_fps_overlay']}")
        elif key in ('1', '2', '3', '4'):
            self._kb_move_to_monitor(int(key))
        else:
            super().keyPressEvent(event)
    
    def closeEvent(self, event):
        """Cleanup on close"""
        # Stop all timers
        self.scroll_timer.stop()
        self.update_timer.stop()
        self.next_day_timer.stop()
        self.intro_timer.stop()
        self.odds_timer.stop()
        
        # Clean up worker threads if running
        if self.data_worker and self.data_worker.isRunning():
            self.data_worker.quit()
            self.data_worker.wait()
        if self._odds_worker and self._odds_worker.isRunning():
            self._odds_worker.quit()
            self._odds_worker.wait()
        
        # Unregister AppBar (guarded against double-call)
        self.remove_appbar()

        event.accept()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
        elif event.button() == QtCore.Qt.RightButton:
            self._show_context_menu(event.globalPos())

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton and hasattr(self, '_drag_pos'):
            self.move(event.globalPos() - self._drag_pos)

    def contextMenuEvent(self, event):
        self._show_context_menu(event.globalPos())

    def _show_context_menu(self, global_pos):
        """Build and display the right-click context menu."""
        menu = QtWidgets.QMenu(self)

        refresh_action = menu.addAction("Refresh Games")
        refresh_action.triggered.connect(self.start_data_fetch)

        restart_action = menu.addAction("Restart")
        restart_action.triggered.connect(self._restart_intro)

        menu.addSeparator()

        # Date submenu — session-only, not saved to settings
        date_menu = menu.addMenu("Show Games For...")
        _date_options = [
            ("Yesterday's Games", "yesterday"),
            ("Today's Games",     "today"),
            ("Tomorrow's Games",  "tomorrow"),
        ]
        for label, key in _date_options:
            act = date_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self._date_view_override == key)
            def _make_date_handler(k=key):
                def _handler(checked):
                    # Clicking the already-active item unchecks it → return to auto mode
                    self._date_view_override = k if checked else None
                    # Exit automatic yesterday mode when switching to a manual date
                    if self._yesterday_mode:
                        self._yesterday_mode = False
                        self.waiting_for_next_day = False
                        self.next_day_timer.stop()
                        self._pending_today_games = []
                        self._pending_today_date = ''
                    self.start_data_fetch()
                return _handler
            act.triggered.connect(_make_date_handler())

        menu.addSeparator()

        pause_label = "Unpause Ticker" if self.scroll_paused else "Pause Ticker"
        pause_action = menu.addAction(pause_label)
        def _toggle_pause():
            self.scroll_paused = not self.scroll_paused
            if self.scroll_paused:
                self.scroll_timer.stop()
            else:
                if not self.intro_active and not self.is_hovered:
                    self._last_frame_ms = self._elapsed_timer.nsecsElapsed() / 1_000_000.0
                    self.scroll_timer.start(self._scroll_timer_interval_ms)
        pause_action.triggered.connect(_toggle_pause)

        menu.addSeparator()

        standings_action = menu.addAction("Standings...")
        def _open_standings():
            if not hasattr(self, '_standings_win') or \
                    self._standings_win is None or \
                    not self._standings_win.isVisible():
                self._standings_win = StandingsWindow(ticker_widget=self)
                self._standings_win.show()
            else:
                self._standings_win.raise_()
                self._standings_win.activateWindow()
        standings_action.triggered.connect(_open_standings)

        menu.addSeparator()

        settings_action = menu.addAction("Settings...")
        settings_action.triggered.connect(lambda: SettingsDialog(self).exec_())  # type: ignore[arg-type]

        menu.addSeparator()

        about_action = menu.addAction("About MLB-TCKR...")
        about_action.triggered.connect(lambda: AboutDialog(self).exec_())  # type: ignore[arg-type]

        menu.addSeparator()

        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(QtWidgets.QApplication.instance().quit)

        menu.exec_(global_pos)


# ---------------------------------------------------------------------------
# Standings data fetch
# ---------------------------------------------------------------------------

# AL/NL division structure
_AL_DIVISIONS = {
    'East':    [147, 110, 111, 139, 141],   # NYY, BAL, BOS, TB, TOR
    'Central': [145, 114, 116, 118, 142],   # CWS, CLE, DET, KC, MIN
    'West':    [117, 108, 133, 136, 140],   # HOU, LAA, OAK, SEA, TEX
}
_NL_DIVISIONS = {
    'East':    [144, 146, 121, 143, 120],   # ATL, MIA, NYM, PHI, WSH
    'Central': [112, 113, 158, 138, 134],   # CHC, CIN, MIL, STL, PIT
    'West':    [109, 115, 119, 135, 137],   # ARI, COL, LAD, SD, SF
}


def fetch_standings():
    """Fetch full standings for the current season.

    Returns a dict:
        {
          'AL': {'East': [...], 'Central': [...], 'West': [...]},
          'NL': {'East': [...], 'Central': [...], 'West': [...]}
        }
    Each team entry:
        {'name': str, 'wins': int, 'losses': int, 'pct': str,
         'last10': str, 'team_id': int}
    Sorted best→worst within each division.
    """
    season_year = datetime.datetime.now().year
    try:
        standings_data = statsapi.get(
            'standings',
            {
                'leagueId': '103,104',
                'season': str(season_year),
                'standingsTypes': 'regularSeason',
                'hydrate': 'team,league,division,streaks,records,standingsInfo',
            }
        )
    except Exception as e:
        print(f"[STANDINGS] Fetch error: {e}")
        return None

    # Build flat map: team_id → row dict
    rows = {}
    for group in standings_data.get('records', []):
        for tr in group.get('teamRecords', []):
            tid = tr.get('team', {}).get('id')
            if tid is None:
                continue
            wins   = tr.get('wins', 0)
            losses = tr.get('losses', 0)
            total  = wins + losses
            pct    = f".{round((wins/total)*1000):03d}" if total else '.000'
            # Last-10 record lives under splitRecords
            last10 = '-'
            for sr in tr.get('records', {}).get('splitRecords', []):
                if sr.get('type') == 'lastTen':
                    last10 = f"{sr.get('wins',0)}-{sr.get('losses',0)}"
                    break
            rows[tid] = {
                'name':    get_team_nickname(tr.get('team', {}).get('name', '')),
                'wins':    wins,
                'losses':  losses,
                'pct':     pct,
                'last10':  last10,
                'team_id': tid,
                'full_name': tr.get('team', {}).get('name', ''),
            }

    def build_division(div_ids):
        teams = [rows[tid] for tid in div_ids if tid in rows]
        teams.sort(key=lambda t: (-t['wins'], t['losses']))
        return teams

    result = {'AL': {}, 'NL': {}}
    for div, ids in _AL_DIVISIONS.items():
        result['AL'][div] = build_division(ids)
    for div, ids in _NL_DIVISIONS.items():
        result['NL'][div] = build_division(ids)
    return result


class FontPreviewDelegate(QtWidgets.QStyledItemDelegate):
    """Renders each font family name in its own typeface inside the combo dropdown."""
    _SUFFIX = "  —  AaBbCc 123"

    def paint(self, painter, option, index):
        family = index.data(QtCore.Qt.DisplayRole) or ""
        is_selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        painter.save()
        bg = option.palette.highlight() if is_selected else option.palette.base()
        painter.fillRect(option.rect, bg)
        item_font = QtGui.QFont(family)
        item_font.setPixelSize(18)
        painter.setFont(item_font)
        fg = option.palette.highlightedText() if is_selected else option.palette.text()
        painter.setPen(fg.color())
        painter.drawText(
            option.rect.adjusted(6, 0, -4, 0),
            QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
            family + self._SUFFIX,
        )
        painter.restore()

    def sizeHint(self, option, index):
        return QtCore.QSize(option.rect.width(), 30)


# ---------------------------------------------------------------------------
# Standings worker thread
# ---------------------------------------------------------------------------

class _StandingsWorker(QtCore.QThread):
    """Background thread that calls fetch_standings() without blocking the UI."""
    done = QtCore.pyqtSignal(object)

    def run(self):
        data = fetch_standings()
        self.done.emit(data)


# ---------------------------------------------------------------------------
# Standings window
# ---------------------------------------------------------------------------

class StandingsWindow(QtWidgets.QWidget):
    """Full standings window with LED-style background.

    Displays AL or NL standings in three division columns (East / Central / West).
    Clicking the league header toggles between AL and NL.
    Data is fetched on demand in a background thread.
    """

    _DIVISIONS = ['East', 'Central', 'West']

    def _compute_scale(self):
        """Return a scale factor ≤ 1.0 so the window fits available screen space."""
        if self._ticker_widget is not None:
            _scr = QtWidgets.QApplication.screenAt(self._ticker_widget.geometry().center())
            if _scr is None:
                _scr = QtWidgets.QApplication.primaryScreen()
        else:
            _scr = QtWidgets.QApplication.primaryScreen()
        avail = _scr.availableGeometry()
        # Design dimensions match the layout at 100 % scale on a 1080p monitor.
        # ideal_w = 3 columns (524 each) + 2 dividers (34 each) + h-margins (56)
        ideal_w = 1696
        # ideal_h = title + league row + divider + div-header + 5 rows + footer
        ideal_h = 580
        scale = min(avail.width()  * 0.92 / ideal_w,
                    avail.height() * 0.92 / ideal_h,
                    1.0)
        return max(scale, 0.5)   # never compress below 50 %

    def _compute_sizes(self):
        """Derive all pixel dimensions from self._scale."""
        s = self._scale
        # Cell widths
        self._W_LOGO = max(24, int(44  * s))
        self._W_NAME = max(110, int(210 * s))
        self._W_WL   = max(48, int(90  * s))
        self._W_PCT  = max(48, int(90  * s))
        self._W_L10  = max(48, int(90  * s))
        self._ROW_H  = max(22, int(40  * s))
        # Font pixel sizes
        self._FS_TITLE   = max(28, int(64 * s))
        self._FS_LEAGUE  = max(18, int(40 * s))
        self._FS_DIV     = max(16, int(36 * s))
        self._FS_HDR     = max(12, int(26 * s))
        self._FS_NAME    = max(14, int(30 * s))
        self._FS_STAT    = max(12, int(26 * s))
        self._FS_LOADING = max(18, int(40 * s))
        self._FS_CLOSE   = max(13, int(26 * s))
        # Layout
        self._MARGIN_H  = max(12, int(28 * s))
        self._MARGIN_V  = max(10, int(20 * s))
        self._CLOSE_W   = max(90,  int(160 * s))
        self._CLOSE_H   = max(30,  int(52  * s))

    def __init__(self, ticker_widget=None, parent=None):
        super().__init__(parent, QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowTitle("MLB Standings")

        self._league         = 'AL'
        self._data           = None
        self._loading        = False
        self._ticker_widget  = ticker_widget

        self._scale = self._compute_scale()
        self._compute_sizes()
        self._build_ui()
        self._position_below_ticker()
        self._fetch()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _league_logo_lbl(self, filename):
        """Return a QLabel showing the league SVG logo, or None if the file isn't found."""
        # Primary locations: MLB-TCKR.images subfolder (AppData, then bundle, then project)
        # Fallback: bare directory roots for backward compatibility
        _images_subdir = 'MLB-TCKR.images'
        script_dir = os.path.dirname(os.path.abspath(__file__))
        search_dirs = [
            os.path.join(APPDATA_DIR, _images_subdir),
            APPDATA_DIR,
        ]
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            search_dirs.append(os.path.join(sys._MEIPASS, _images_subdir))
            search_dirs.append(sys._MEIPASS)
        search_dirs.append(os.path.join(script_dir, _images_subdir))
        search_dirs.append(script_dir)
        path = None
        for d in search_dirs:
            candidate = os.path.join(d, filename)
            if os.path.isfile(candidate):
                path = candidate
                break
        if not path:
            return None
        renderer = QtSvg.QSvgRenderer(path)
        if not renderer.isValid():
            return None
        size = self._FS_LEAGUE + 4   # match the league text height
        default_size = renderer.defaultSize()
        if default_size.height() > 0:
            w = int(size * default_size.width() / default_size.height())
        else:
            w = size
        px = QtGui.QPixmap(w, size)
        px.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(px)
        renderer.render(painter)
        painter.end()
        lbl = QtWidgets.QLabel()
        lbl.setPixmap(px)
        lbl.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignCenter)
        lbl.setFixedSize(w, size)
        return lbl

    def _build_ui(self):
        self._ozone_family  = load_ozone_font() or load_custom_font()
        self._record_family = load_record_font_family() or self._ozone_family

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(self._MARGIN_H, self._MARGIN_V, self._MARGIN_H, self._MARGIN_V)
        outer.setSpacing(0)

        # ── Header ────────────────────────────────────────────────
        title_font = QtGui.QFont(self._ozone_family)
        title_font.setPixelSize(self._FS_TITLE)
        title_lbl = QtWidgets.QLabel("MLB STANDINGS")
        title_lbl.setAlignment(QtCore.Qt.AlignCenter)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet("color: #FFFFFF; padding: 10px 0 4px 0;")
        outer.addWidget(title_lbl)

        league_font = QtGui.QFont(self._ozone_family)
        league_font.setPixelSize(self._FS_LEAGUE)

        self._al_lbl = QtWidgets.QLabel("AMERICAN LEAGUE")
        self._al_lbl.setAlignment(QtCore.Qt.AlignCenter)
        self._al_lbl.setFont(league_font)
        self._al_lbl.setCursor(QtCore.Qt.PointingHandCursor)
        self._al_lbl.setToolTip("Show AL Standings")
        self._al_lbl.mousePressEvent = lambda _e: self._select_league('AL')

        sep_lbl = QtWidgets.QLabel("  |  ")
        sep_lbl.setAlignment(QtCore.Qt.AlignCenter)
        sep_lbl.setFont(league_font)
        _sp_top = max(2, int(4  * self._scale))
        _sp_bot = max(6, int(18 * self._scale))
        sep_lbl.setStyleSheet(f"color: #444444; padding: {_sp_top}px 0 {_sp_bot}px 0;")

        self._nl_lbl = QtWidgets.QLabel("NATIONAL LEAGUE")
        self._nl_lbl.setAlignment(QtCore.Qt.AlignCenter)
        self._nl_lbl.setFont(league_font)
        self._nl_lbl.setCursor(QtCore.Qt.PointingHandCursor)
        self._nl_lbl.setToolTip("Show NL Standings")
        self._nl_lbl.mousePressEvent = lambda _e: self._select_league('NL')

        league_row = QtWidgets.QHBoxLayout()
        league_row.setSpacing(0)
        league_row.addStretch()
        _al_logo = self._league_logo_lbl("american.svg")
        if _al_logo:
            league_row.addWidget(_al_logo)
            league_row.addSpacing(6)
        league_row.addWidget(self._al_lbl)
        league_row.addWidget(sep_lbl)
        league_row.addWidget(self._nl_lbl)
        _nl_logo = self._league_logo_lbl("national.svg")
        if _nl_logo:
            league_row.addSpacing(6)
            league_row.addWidget(_nl_logo)
        league_row.addStretch()
        outer.addLayout(league_row)

        self._update_header_colors()

        # Thin divider under header — colour tracks the active league
        self._header_sep = QtWidgets.QFrame()
        self._header_sep.setFrameShape(QtWidgets.QFrame.HLine)
        outer.addWidget(self._header_sep)
        outer.addSpacing(self._MARGIN_V)

        # ── Division columns ─────────────────────────────────────────
        cols_row = QtWidgets.QHBoxLayout()
        cols_row.setSpacing(0)
        self._col_widgets = {}
        self._div_labels = []   # division title labels (recolored on league switch)
        self._hdr_labels = []   # column header labels  (recolored on league switch)

        for i, div in enumerate(self._DIVISIONS):
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(0)

            # Division title
            div_lbl = QtWidgets.QLabel(div.upper())
            div_font = QtGui.QFont(self._ozone_family)
            div_font.setPixelSize(self._FS_DIV)
            div_lbl.setFont(div_font)
            div_lbl.setAlignment(QtCore.Qt.AlignCenter)
            div_lbl.setStyleSheet("color: #1E90FF; padding-bottom: 8px;")
            div_lbl.setFixedWidth(self._div_width())
            self._div_labels.append(div_lbl)
            col.addWidget(div_lbl)

            # Column header row
            hdr_row, hdr_lbls = self._make_col_header()
            self._hdr_labels.extend(hdr_lbls)
            col.addWidget(hdr_row)

            # Thin separator
            hsep = QtWidgets.QFrame()
            hsep.setFrameShape(QtWidgets.QFrame.HLine)
            hsep.setStyleSheet(
                "color: #555; background: #555; max-height: 1px; margin: 4px 0;"
            )
            col.addWidget(hsep)

            self._col_widgets[div] = col

            wrapper = QtWidgets.QWidget()
            wrapper.setLayout(col)
            wrapper.setStyleSheet("background: transparent;")
            wrapper.setFixedWidth(self._div_width())
            cols_row.addWidget(wrapper)

            if i < len(self._DIVISIONS) - 1:
                vsep = QtWidgets.QFrame()
                vsep.setFrameShape(QtWidgets.QFrame.VLine)
                _vsep_m = max(8, int(16 * self._scale))
                vsep.setStyleSheet(
                    f"color: #555; background: #555; max-width: 2px; margin: 0 {_vsep_m}px;"
                )
                cols_row.addWidget(vsep)

        outer.addLayout(cols_row)
        outer.addSpacing(self._MARGIN_V)

        # ── Loading indicator ─────────────────────────────────────────
        self._loading_lbl = QtWidgets.QLabel("Loading…")
        loading_font = QtGui.QFont(self._ozone_family)
        loading_font.setPixelSize(self._FS_LOADING)
        self._loading_lbl.setFont(loading_font)
        self._loading_lbl.setAlignment(QtCore.Qt.AlignCenter)
        self._loading_lbl.setStyleSheet("color: #888;")
        outer.addWidget(self._loading_lbl)
        self._loading_lbl.hide()

        # ── Bottom bar (close button) ──────────────────────────────────
        bottom = QtWidgets.QHBoxLayout()
        bottom.addStretch()
        close_btn = QtWidgets.QPushButton("✕  Close")
        close_btn_font = QtGui.QFont(self._ozone_family)
        close_btn_font.setPixelSize(self._FS_CLOSE)
        close_btn.setFont(close_btn_font)
        close_btn.setFixedSize(self._CLOSE_W, self._CLOSE_H)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a2a; color: #cccccc;
                border: 1px solid #555; border-radius: 6px;
            }
            QPushButton:hover { background: #3a3a3a; color: #ffffff; }
            QPushButton:pressed { background: #111; }
        """)
        close_btn.clicked.connect(self.close)  # type: ignore[arg-type]
        bottom.addWidget(close_btn)
        outer.addLayout(bottom)

    def _div_width(self):
        return self._W_LOGO + self._W_NAME + self._W_WL + self._W_PCT + self._W_L10

    def _make_col_header(self):
        """Return (widget, [label_refs]) header row matching team row cell widths."""
        row = QtWidgets.QWidget()
        row.setFixedWidth(self._div_width())
        row.setFixedHeight(self._ROW_H)
        row.setStyleSheet("background: transparent;")
        hl = QtWidgets.QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        hdr_font = QtGui.QFont(self._ozone_family)
        hdr_font.setPixelSize(self._FS_HDR)

        # Logo placeholder
        spacer = QtWidgets.QLabel()
        spacer.setFixedWidth(self._W_LOGO)
        hl.addWidget(spacer)

        lbls = []
        for label, width in [("Team", self._W_NAME),
                              ("W-L",  self._W_WL),
                              ("Pct.", self._W_PCT),
                              ("L10",  self._W_L10)]:
            lbl = QtWidgets.QLabel(label.upper())
            lbl.setFont(hdr_font)
            lbl.setFixedWidth(width)
            lbl.setFixedHeight(self._ROW_H)
            lbl.setStyleSheet("color: #1E90FF;")
            if label == "Team":
                lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            else:
                lbl.setAlignment(QtCore.Qt.AlignCenter)
            hl.addWidget(lbl)
            lbls.append(lbl)
        return row, lbls

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _fetch(self):
        if self._loading:
            return
        self._loading = True
        self._loading_lbl.show()
        self._worker = _StandingsWorker()
        self._worker.done.connect(self._on_data)
        self._worker.start()

    def _on_data(self, data):
        self._loading = False
        self._loading_lbl.hide()
        self._data = data
        self._populate()
        self._position_below_ticker()

    def _populate(self):
        """Fill all three division columns with the current league's data."""
        if not self._data:
            return
        league_data = self._data.get(self._league, {})
        name_font = QtGui.QFont(self._ozone_family)
        name_font.setPixelSize(self._FS_NAME)
        stat_font = QtGui.QFont(self._record_family)
        stat_font.setPixelSize(self._FS_STAT)

        for div in self._DIVISIONS:
            col = self._col_widgets[div]
            teams = league_data.get(div, [])

            # Remove old team rows (everything after div title + header + sep = 3)
            while col.count() > 3:
                item = col.takeAt(3)
                if item.widget():
                    item.widget().deleteLater()

            for rank, team in enumerate(teams):
                row_widget = QtWidgets.QWidget()
                row_widget.setFixedWidth(self._div_width())
                row_widget.setFixedHeight(self._ROW_H)
                row_widget.setStyleSheet("background: transparent;")
                hl = QtWidgets.QHBoxLayout(row_widget)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.setSpacing(0)

                # Logo
                logo_px = get_team_logo(team['full_name'], size=self._W_LOGO - 4)
                logo_lbl = QtWidgets.QLabel()
                logo_lbl.setPixmap(logo_px)
                logo_lbl.setFixedSize(self._W_LOGO, self._ROW_H)
                logo_lbl.setAlignment(QtCore.Qt.AlignCenter)
                hl.addWidget(logo_lbl)
                hl.addSpacing(max(4, int(8 * self._scale)))

                # Team name
                name_lbl = QtWidgets.QLabel(team['name'].upper())
                name_lbl.setFont(name_font)
                name_lbl.setFixedWidth(self._W_NAME)
                name_lbl.setFixedHeight(self._ROW_H)
                name_lbl.setStyleSheet("color: #FFFFFF;")
                name_lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
                hl.addWidget(name_lbl)

                # W-L / Pct. / L10
                for val, width in [
                    (f"{team['wins']}-{team['losses']}", self._W_WL),
                    (team['pct'],   self._W_PCT),
                    (team['last10'], self._W_L10),
                ]:
                    lbl = QtWidgets.QLabel(val)
                    lbl.setFont(stat_font)
                    lbl.setFixedWidth(width)
                    lbl.setFixedHeight(self._ROW_H)
                    lbl.setStyleSheet("color: #cccccc;")
                    lbl.setAlignment(QtCore.Qt.AlignCenter)
                    hl.addWidget(lbl)

                col.addWidget(row_widget)

        self._update_header_colors()
        self.adjustSize()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_header_colors(self):
        al_color  = "#FF2222" if self._league == 'AL' else "#555555"
        nl_color  = "#2266FF" if self._league == 'NL' else "#555555"
        sep_color = "#FF2222" if self._league == 'AL' else "#2266FF"
        accent    = "#FF2222" if self._league == 'AL' else "#1E90FF"
        pad_top = max(2, int(4  * self._scale))
        pad_bot = max(6, int(18 * self._scale))
        self._al_lbl.setStyleSheet(f"color: {al_color}; padding: {pad_top}px 0 {pad_bot}px 0;")
        self._nl_lbl.setStyleSheet(f"color: {nl_color}; padding: {pad_top}px 0 {pad_bot}px 0;")
        if hasattr(self, '_header_sep'):
            self._header_sep.setStyleSheet(
                f"color: {sep_color}; background: {sep_color}; max-height: 2px;"
            )
        for lbl in getattr(self, '_div_labels', []):
            lbl.setStyleSheet(f"color: {accent}; padding-bottom: 8px;")
        for lbl in getattr(self, '_hdr_labels', []):
            lbl.setStyleSheet(f"color: {accent};")

    def _select_league(self, league):
        if self._league == league:
            return
        self._league = league
        self._update_header_colors()
        if self._data:
            self._populate()


    def _position_below_ticker(self):
        """Place the window just below the ticker bar, horizontally centered on it.
        Falls back to centering on the primary screen if no ticker reference is held."""
        self.adjustSize()
        ticker = self._ticker_widget
        if ticker is not None:
            _scr = QtWidgets.QApplication.screenAt(ticker.geometry().center())
            if _scr is None:
                _scr = QtWidgets.QApplication.primaryScreen()
        else:
            _scr = QtWidgets.QApplication.primaryScreen()
        screen = _scr.availableGeometry()
        if ticker is not None:
            tg = ticker.frameGeometry()
            x = tg.left() + (tg.width() - self.width()) // 2
            y = tg.bottom() + 8          # 8 px gap below the ticker
        else:
            x = screen.x() + (screen.width()  - self.width())  // 2
            y = screen.y() + (screen.height() - self.height()) // 2
        # Clamp so the window never escapes the available screen area
        x = max(screen.left(), min(x, screen.right()  - self.width()))
        y = max(screen.top(),  min(y, screen.bottom() - self.height()))
        self.move(x, y)

    # ------------------------------------------------------------------
    # LED-style background paint
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect()

        # Rounded dark background
        painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 240)))
        painter.setPen(QtGui.QPen(QtGui.QColor('#FFFFFF'), 1.5))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 10, 10)

        # Scanlines
        scan = QtGui.QColor(0, 0, 0, 35)
        for y in range(0, rect.height(), 2):
            painter.fillRect(0, y, rect.width(), 1, scan)

        painter.end()

    # Allow dragging the window
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton and hasattr(self, '_drag_pos'):
            self.move(event.globalPos() - self._drag_pos)


# ---------------------------------------------------------------------------
# About dialog
# ---------------------------------------------------------------------------

class AboutDialog(QtWidgets.QDialog):
    """Modal About dialog with LED-board aesthetic."""

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowTitle("About MLB-TCKR")
        self.setModal(True)

        font_family = load_ozone_font() or load_custom_font()
        record_family = load_record_font_family() or font_family

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(32, 28, 32, 24)
        outer.setSpacing(0)

        def _lbl(text, size, color, bold=False, top_pad=0, bot_pad=0, family=None):
            l = QtWidgets.QLabel(text)
            f = QtGui.QFont(family or font_family)
            f.setPixelSize(size)
            f.setBold(bold)
            l.setFont(f)
            l.setAlignment(QtCore.Qt.AlignCenter)
            l.setStyleSheet(
                f"color: {color};"
                f" padding-top: {top_pad}px; padding-bottom: {bot_pad}px;"
            )
            l.setWordWrap(True)
            return l

        # App name
        self._title_lbl = _lbl("MLB-TCKR", 52, "#FFFFFF", bold=False, bot_pad=4)
        outer.addWidget(self._title_lbl)

        # Version
        outer.addWidget(_lbl(f"Version {VERSION}", 22, "#AAAAAA", bot_pad=14))

        # Green rule
        rule = QtWidgets.QFrame()
        rule.setFrameShape(QtWidgets.QFrame.HLine)
        rule.setStyleSheet("background: #00FF44; max-height: 2px;")
        self._rule = rule
        outer.addWidget(rule)
        outer.addSpacing(14)

        # Credits block
        outer.addWidget(_lbl("Created by: Paul R. Charovkine",  20, "#DDDDDD", bot_pad=4,  family=record_family))
        outer.addWidget(_lbl("Copyright \u00a9 2026\nAll Rights Reserved", 18, "#AAAAAA", bot_pad=4,  family=record_family))
        outer.addWidget(_lbl("License: GNU AGPLv3",              18, "#AAAAAA", bot_pad=16, family=record_family))


        # Website (clickable)
        url_lbl = QtWidgets.QLabel(
            '<a href="https://krypdoh.github.io/MLB-TCKR/" '
            'style="color:#00AAFF; text-decoration:none;">'
            'https://krypdoh.github.io/MLB-TCKR/</a>'
        )
        url_font = QtGui.QFont(record_family)
        url_font.setPixelSize(18)
        url_lbl.setFont(url_font)
        url_lbl.setAlignment(QtCore.Qt.AlignCenter)
        url_lbl.setOpenExternalLinks(True)
        url_lbl.setTextInteractionFlags(QtCore.Qt.TextBrowserInteraction)
        url_lbl.setStyleSheet("padding-bottom: 8px;")
        outer.addWidget(url_lbl)

        # Donate button (bottom left)
        self._donate_btn = QtWidgets.QPushButton("Donate")
        donate_btn = self._donate_btn
        donate_btn.setCursor(QtCore.Qt.PointingHandCursor)
        donate_btn.setFont(QtGui.QFont(load_custom_font(), 16))
        donate_btn.setStyleSheet("background:#00AAFF; color:#fff; font-size:16px; padding:6px 18px; border-radius:6px;")
        def open_donate():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://paypal.me/paypaulc"))
        donate_btn.clicked.connect(open_donate)
        outer.addWidget(donate_btn)

        # Second rule
        rule2 = QtWidgets.QFrame()
        rule2.setFrameShape(QtWidgets.QFrame.HLine)
        rule2.setStyleSheet("background: #333333; max-height: 1px;")
        outer.addWidget(rule2)
        outer.addSpacing(12)

        # Disclaimer
        outer.addWidget(_lbl(
            "Major League Baseball trademarks, team names, logos, and related marks"
            "are the property of their respective owners.\n\n"
            "MLB-TCKR is an independent fan project and is not affiliated "
            "with or endorsed by Major League Baseball.",
            14, "#777777", bot_pad=16, family=record_family
        ))

        # Close button
        close_btn = QtWidgets.QPushButton("\u2715  Close")
        close_font = QtGui.QFont(font_family)
        close_font.setPixelSize(18)
        close_btn.setFont(close_font)
        close_btn.setFixedSize(140, 44)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a2a; color: #cccccc;
                border: 1px solid #555; border-radius: 6px;
            }
            QPushButton:hover  { background: #3a3a3a; color: #ffffff; }
            QPushButton:pressed { background: #111; }
        """)
        close_btn.clicked.connect(self.accept)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(donate_btn, alignment=QtCore.Qt.AlignLeft)
        btn_row.addStretch()
        btn_row.addWidget(close_btn, alignment=QtCore.Qt.AlignRight)
        outer.addLayout(btn_row)

        # Rainbow pulse timer — cycles hue across title and rule in unison
        self._hue = 0.0
        self._rainbow_timer = QtCore.QTimer(self)
        self._rainbow_timer.timeout.connect(self._pulse_rainbow)
        self._rainbow_timer.start(50)

    def _pulse_rainbow(self):
        self._hue = (self._hue + 0.005) % 1.0
        c = QtGui.QColor.fromHsvF(self._hue, 1.0, 1.0)
        hex_c = c.name()
        self._title_lbl.setStyleSheet(
            f"color: {hex_c}; padding-top: 0px; padding-bottom: 4px;"
        )
        self._rule.setStyleSheet(f"background: {hex_c}; max-height: 2px;")
        self._donate_btn.setStyleSheet(
            f"background: {hex_c}; color: #fff;"
            " font-size:16px; padding:6px 18px; border-radius:6px;"
        )

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect()
        painter.setBrush(QtGui.QBrush(QtGui.QColor(0, 0, 0, 245)))
        painter.setPen(QtGui.QPen(QtGui.QColor('#FFFFFF'), 1.5))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 10, 10)
        scan = QtGui.QColor(0, 0, 0, 30)
        for y in range(0, rect.height(), 2):
            painter.fillRect(0, y, rect.width(), 1, scan)
        painter.end()

    # Allow dragging
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton and hasattr(self, '_drag_pos'):
            self.move(event.globalPos() - self._drag_pos)


# ── Settings dialog dark theme — matches the LED board palette ────────────────
SETTINGS_DIALOG_QSS = """
QDialog {
    background-color: #0f1216;
    color: #dce0ea;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
}

/* ── Tab bar ── */
QTabWidget::pane {
    background-color: #0f1216;
    border: 1px solid #2a3a5e;
    border-top: none;
}
QTabBar {
    background-color: #0f1216;
}
QTabBar::tab {
    background-color: #0a0d14;
    color: #8ab4f8;
    border: 1px solid #2a3a5e;
    border-bottom: none;
    padding: 6px 18px;
    min-width: 90px;
    margin-right: 2px;
    font-weight: bold;
    letter-spacing: 0.5px;
}
QTabBar::tab:selected {
    background-color: #1a2035;
    color: #00FF44;
    border-bottom: 2px solid #00FF44;
}
QTabBar::tab:hover:!selected {
    background-color: #151820;
    color: #dce0ea;
}

/* ── Group boxes ── */
QGroupBox {
    background-color: #151820;
    border: 1px solid #2a3a5e;
    border-radius: 4px;
    margin-top: 10px;
    padding: 8px 6px 4px 6px;
    color: #8ab4f8;
    font-weight: bold;
    font-size: 11px;
    letter-spacing: 0.5px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: #8ab4f8;
    font-weight: bold;
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 1px;
}

/* ── Generic controls ── */
QLabel {
    color: #dce0ea;
    background: transparent;
}
QLabel#restartNote {
    color: #FFA500;
    font-size: 10px;
    font-style: italic;
}

QCheckBox {
    color: #dce0ea;
    spacing: 8px;
    background: transparent;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid #4a5a7e;
    border-radius: 2px;
    background-color: #0a0d14;
}
QCheckBox::indicator:checked {
    background-color: #00FF44;
    border-color: #00FF44;
    image: none;
}
QCheckBox::indicator:hover {
    border-color: #8ab4f8;
}

QSpinBox, QLineEdit, QComboBox {
    background-color: #0a0d14;
    color: #dce0ea;
    border: 1px solid #2a3a5e;
    border-radius: 3px;
    padding: 3px 6px;
    selection-background-color: #1a2035;
    selection-color: #00FF44;
}
QSpinBox:hover, QLineEdit:hover, QComboBox:hover {
    border-color: #4a5a7e;
}
QSpinBox:focus, QLineEdit:focus, QComboBox:focus {
    border-color: #8ab4f8;
    outline: none;
}
QSpinBox::up-button, QSpinBox::down-button {
    background-color: #1a2035;
    border: none;
    width: 16px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: #253050;
}
QSpinBox::up-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #8ab4f8;
    width: 0; height: 0;
}
QSpinBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #8ab4f8;
    width: 0; height: 0;
}

QComboBox::drop-down {
    border: none;
    background-color: #1a2035;
    width: 20px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #8ab4f8;
    width: 0; height: 0;
}
QComboBox QAbstractItemView {
    background-color: #0a0d14;
    color: #dce0ea;
    border: 1px solid #2a3a5e;
    selection-background-color: #1a2035;
    selection-color: #00FF44;
    outline: none;
}

/* ── Slider (Team Font Size) ── */
QSlider::groove:horizontal {
    background-color: #0a0d14;
    border: 1px solid #2a3a5e;
    height: 5px;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background-color: #00FF44;
    border-radius: 2px;
}
QSlider::add-page:horizontal {
    background-color: #1a2035;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: #00FF44;
    border: 2px solid #0a0d14;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background-color: #44ffaa;
}

/* ── Buttons ── */
QPushButton {
    background-color: #1a2035;
    color: #dce0ea;
    border: 1px solid #2a3a5e;
    border-radius: 4px;
    padding: 5px 14px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #253050;
    border-color: #4a5a7e;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #0f1626;
}
QPushButton:default {
    border-color: #00FF44;
}

/* ── Dialog button box ── */
QDialogButtonBox QPushButton {
    min-width: 70px;
}

/* ── Scroll area ── */
QScrollArea {
    background-color: #0f1216;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background-color: #0f1216;
}

/* ── Scroll bars ── */
QScrollBar:vertical {
    background-color: #0a0d14;
    width: 10px;
    margin: 0;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #2a3a5e;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background-color: #4a5a7e;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0; background: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    background-color: #0a0d14;
    height: 10px;
    margin: 0;
    border: none;
}
QScrollBar::handle:horizontal {
    background-color: #2a3a5e;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background-color: #4a5a7e;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0; background: none;
}
"""


class SettingsDialog(QtWidgets.QDialog):
    """Settings dialog with tabs for team colors and general settings"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MLB-TCKR Settings")
        self.setMinimumSize(700, 640)

        # Load current settings
        self.settings = get_settings()
        
        # Secret admin tab trigger
        self._admin_click_count = 0
        self._admin_click_timer = QtCore.QTimer()
        self._admin_click_timer.setSingleShot(True)
        self._admin_click_timer.timeout.connect(lambda: setattr(self, '_admin_click_count', 0))
        self._admin_tab_shown = False
        
        # Create tab widget (instance variable so we can add admin tab later)
        self.tabs = QtWidgets.QTabWidget()
        
        # General settings tab
        general_tab = self.create_general_tab()
        self.tabs.addTab(general_tab, "General")
        
        # Team colors tab
        colors_tab = self.create_team_colors_tab()
        self.tabs.addTab(colors_tab, "Team Colors")

        # Network / proxy tab
        network_tab = self.create_network_tab()
        self.tabs.addTab(network_tab, "Network")

        # Hotkeys reference tab
        hotkeys_tab = self.create_hotkeys_tab()
        self.tabs.addTab(hotkeys_tab, "Hotkeys")
        
        # Secret trigger label at top (click 7 times to reveal admin tab)
        self.secret_label = QtWidgets.QLabel(f"Version: {VERSION}")
        self.secret_label.setAlignment(QtCore.Qt.AlignRight)
        self.secret_label.setStyleSheet("color: #555; font-size: 9px; padding: 2px 8px;")
        self.secret_label.setCursor(QtCore.Qt.PointingHandCursor)
        self.secret_label.installEventFilter(self)
        
        # Buttons
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        apply_btn = button_box.addButton("Apply", QtWidgets.QDialogButtonBox.ApplyRole)
        apply_btn.clicked.connect(self.apply_settings)
        button_box.accepted.connect(self.save_and_close)
        button_box.rejected.connect(self.reject)
        
        # Layout
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self.secret_label)
        layout.addWidget(self.tabs)
        layout.addWidget(button_box)
        self.setLayout(layout)

        # Apply dark theme
        self.setStyleSheet(SETTINGS_DIALOG_QSS)

        # Auto-size to show all General-tab content without scrolling.
        # ensurePolished() applies styles/fonts so sizeHint() is accurate.
        self.ensurePolished()
        _content_h = self._general_container.sizeHint().height()
        # chrome = tab bar (~28) + tab frame (~8) + button box (~36)
        #        + outer layout margins (16) + spacing (6) = ~94; use 110 to be safe
        _chrome_h = 110
        _screen = QtWidgets.QApplication.primaryScreen()
        _avail_h = _screen.availableGeometry().height() - 80  # leave room for taskbar/title
        _target_h = min(_content_h + _chrome_h, _avail_h)
        self.resize(800, max(640, _target_h))

    def eventFilter(self, obj, event):
        """Event filter to detect secret clicks on version label."""
        if obj == self.secret_label and event.type() == QtCore.QEvent.MouseButtonPress:
            if event.button() == QtCore.Qt.LeftButton:
                self._admin_click_count += 1
                self._admin_click_timer.start(2000)  # Reset counter after 2 seconds
                
                if self._admin_click_count >= 7 and not self._admin_tab_shown:
                    # Reveal admin tab!
                    self._admin_tab_shown = True
                    admin_tab = self.create_admin_tab()
                    self.tabs.addTab(admin_tab, "Admin")
                    self.secret_label.setText("Admin Unlocked!")
                    self.secret_label.setStyleSheet("color: #4CAF50; font-size: 9px; padding: 2px 8px; font-weight: bold;")
                    # Switch to admin tab
                    self.tabs.setCurrentIndex(self.tabs.count() - 1)
                    return True
        return super().eventFilter(obj, event)

    def create_admin_tab(self):
        """Create hidden admin settings tab with advanced options."""
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        container = QtWidgets.QWidget()
        outer_layout = QtWidgets.QVBoxLayout(container)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(10)

        # Admin settings group
        admin_group = QtWidgets.QGroupBox("Advanced Font Settings")
        admin_form = QtWidgets.QFormLayout(admin_group)
        admin_form.setContentsMargins(10, 14, 10, 10)
        admin_form.setVerticalSpacing(7)
        admin_form.setHorizontalSpacing(16)

        # Player Font Size slider
        player_font_size_layout = QtWidgets.QHBoxLayout()
        self.player_font_scale_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.player_font_scale_slider.setRange(50, 200)
        self.player_font_scale_slider.setSingleStep(5)
        self.player_font_scale_slider.setPageStep(10)
        self.player_font_scale_slider.setValue(self.settings.get('player_font_scale_percent', 75))
        self.player_font_scale_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.player_font_scale_slider.setTickInterval(25)
        
        self.player_font_scale_label = QtWidgets.QLabel(f"{self.player_font_scale_slider.value()}%")
        self.player_font_scale_label.setMinimumWidth(50)
        self.player_font_scale_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        
        self.player_font_scale_slider.valueChanged.connect(
            lambda v: self.player_font_scale_label.setText(f"{v}%")
        )
        
        player_font_size_layout.addWidget(self.player_font_scale_slider)
        player_font_size_layout.addWidget(self.player_font_scale_label)
        
        admin_form.addRow("Player Font Size:", player_font_size_layout)
        
        # Info label
        info_label = QtWidgets.QLabel(
            "Controls the size of pitcher/batter names, W-L records, and pitch counts.\n"
            "Default is 75%. Changes apply immediately."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #888; font-size: 11px; padding: 8px;")
        admin_form.addRow("", info_label)

        outer_layout.addWidget(admin_group)
        outer_layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def create_general_tab(self):
        """Create general settings tab — grouped into logical sections."""
        # Outer scroll area so the tab is usable on small screens
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        container = QtWidgets.QWidget()
        outer_layout = QtWidgets.QVBoxLayout(container)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(10)

        def make_form(group_title):
            """Create a QGroupBox with an inner QFormLayout and return (group, form)."""
            group = QtWidgets.QGroupBox(group_title)
            form = QtWidgets.QFormLayout(group)
            form.setContentsMargins(10, 14, 10, 10)
            form.setVerticalSpacing(7)
            form.setHorizontalSpacing(16)
            form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            return group, form

        # ── 1. Display ──────────────────────────────────────────────────────
        # ── 1. Display ──────────────────────────────────────────────────────
        grp_display, form_display = make_form("Display")

        self.height_spin = QtWidgets.QSpinBox()
        self.height_spin.setRange(40, 200)
        self.height_spin.setValue(self.settings.get('ticker_height', 64))
        self.height_spin.setSuffix(" px")
        form_display.addRow("Ticker Height:", self.height_spin)

        self.monitor_combo = QtWidgets.QComboBox()
        _all_screens = QtWidgets.QApplication.screens()
        for _i, _s in enumerate(_all_screens):
            _g = _s.geometry()
            _label = f"Display {_i + 1}: {_s.name()}  ({_g.width()}\u00d7{_g.height()})"
            self.monitor_combo.addItem(_label)
        _saved_mon = min(self.settings.get('monitor_index', 0), max(0, len(_all_screens) - 1))
        self.monitor_combo.setCurrentIndex(_saved_mon)
        form_display.addRow("Monitor:", self.monitor_combo)

        restart_note = QtWidgets.QLabel("\u26a0  Ticker Height and Monitor changes require a program restart.")
        restart_note.setObjectName("restartNote")
        restart_note.setWordWrap(True)
        form_display.addRow(restart_note)

        outer_layout.addWidget(grp_display)

        # ── 2. Performance ──────────────────────────────────────────────────
        grp_perf, form_perf = make_form("Performance")

        self.speed_spin = QtWidgets.QSpinBox()
        self.speed_spin.setRange(1, 16)
        self.speed_spin.setValue(self.settings.get('speed', 5))
        self.speed_spin.setToolTip("Scroll speed of the ticker (1 = slowest, 16 = fastest)")
        form_perf.addRow("Ticker Speed:", self.speed_spin)

        self.update_spin = QtWidgets.QSpinBox()
        self.update_spin.setRange(5, 300)
        self.update_spin.setValue(self.settings.get('update_interval', 10))
        self.update_spin.setSuffix(" seconds")
        form_perf.addRow("Update Interval:", self.update_spin)

        self.fps_check = QtWidgets.QCheckBox("Show overlay")
        self.fps_check.setChecked(self.settings.get('show_fps_overlay', False))
        form_perf.addRow("FPS Counter:", self.fps_check)

        outer_layout.addWidget(grp_perf)

        # ── 3. Appearance ───────────────────────────────────────────────────
        grp_appearance, form_appearance = make_form("Appearance")

        self.led_bg_check = QtWidgets.QCheckBox("Enabled")
        self.led_bg_check.setChecked(self.settings.get('led_background', True))
        form_appearance.addRow("LED-Style Background:", self.led_bg_check)

        self.glass_check = QtWidgets.QCheckBox("Enabled")
        self.glass_check.setChecked(self.settings.get('glass_overlay', True))
        form_appearance.addRow("Glass Overlay Effect:", self.glass_check)

        _opacity_row = QtWidgets.QHBoxLayout()
        self.opacity_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        bg_opacity_pct = int(round(self.settings.get('background_opacity', 255) * 100 / 255))
        self.opacity_slider.setValue(bg_opacity_pct)
        self.opacity_slider.setToolTip("0% = Fully Transparent  ·  100% = Fully Opaque")
        self.opacity_slider.setMinimumWidth(160)
        self._opacity_label = QtWidgets.QLabel(f"{self.opacity_slider.value()}%")
        self._opacity_label.setFixedWidth(36)
        self._opacity_label.setStyleSheet("color: #00FF44; font-weight: bold; font-size: 13px;")
        self.opacity_slider.valueChanged.connect(
            lambda v: self._opacity_label.setText(f"{v}%")
        )
        _opacity_row.addWidget(self.opacity_slider)
        _opacity_row.addWidget(self._opacity_label)
        form_appearance.addRow("Background Opacity:", _opacity_row)

        _content_opacity_row = QtWidgets.QHBoxLayout()
        self.content_opacity_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.content_opacity_slider.setRange(0, 100)
        content_opacity_pct = int(round(self.settings.get('content_opacity', 255) * 100 / 255))
        self.content_opacity_slider.setValue(content_opacity_pct)
        self.content_opacity_slider.setToolTip("0% = Fully Transparent  ·  100% = Fully Opaque")
        self.content_opacity_slider.setMinimumWidth(160)
        self._content_opacity_label = QtWidgets.QLabel(f"{self.content_opacity_slider.value()}%")
        self._content_opacity_label.setFixedWidth(36)
        self._content_opacity_label.setStyleSheet("color: #00FF44; font-weight: bold; font-size: 13px;")
        self.content_opacity_slider.valueChanged.connect(
            lambda v: self._content_opacity_label.setText(f"{v}%")
        )
        _content_opacity_row.addWidget(self.content_opacity_slider)
        _content_opacity_row.addWidget(self._content_opacity_label)
        form_appearance.addRow("Content Opacity:", _content_opacity_row)

        outer_layout.addWidget(grp_appearance)

        # ── 4. Font ─────────────────────────────────────────────────────────
        grp_font, form_font = make_form("Font")

        self.font_combo = QtWidgets.QComboBox()
        self.font_combo.setMaxVisibleItems(20)
        db = QtGui.QFontDatabase()
        led_font = 'LED Board-7'
        all_fonts = sorted(db.families(), key=lambda f: f.lstrip('@').lower())
        if led_font not in all_fonts:
            all_fonts.insert(0, led_font)
        self.font_combo.addItems(all_fonts)
        current_font = self.settings.get('font', led_font)
        idx = self.font_combo.findText(current_font)
        self.font_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.font_combo.setItemDelegate(FontPreviewDelegate(self.font_combo))
        self.font_combo.setMinimumHeight(32)
        self.font_combo.setFont(QtGui.QFont(current_font, 13))
        self.font_combo.currentTextChanged.connect(
            lambda f: self.font_combo.setFont(QtGui.QFont(f, 13))
        )
        form_font.addRow("Font Family:", self.font_combo)

        # Team Font Size — slider + live % label
        font_slider_row = QtWidgets.QHBoxLayout()
        self.font_scale_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.font_scale_slider.setRange(80, 200)
        self.font_scale_slider.setValue(self.settings.get('font_scale_percent', 175))
        self.font_scale_slider.setTickInterval(10)
        self.font_scale_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.font_scale_label = QtWidgets.QLabel(
            f"{self.font_scale_slider.value()}%"
        )
        self.font_scale_label.setMinimumWidth(40)
        self.font_scale_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.font_scale_label.setStyleSheet("color: #00FF44; font-weight: bold; font-size: 13px;")
        self.font_scale_slider.valueChanged.connect(
            lambda v: self.font_scale_label.setText(f"{v}%")
        )
        font_slider_row.addWidget(self.font_scale_slider)
        font_slider_row.addWidget(self.font_scale_label)
        form_font.addRow("Team Font Size:", font_slider_row)

        # Player Info Font — for W-L records, pitcher/batter names, pitch counts
        self.player_info_font_combo = QtWidgets.QComboBox()
        self.player_info_font_combo.setMaxVisibleItems(20)
        all_fonts_player = sorted(db.families(), key=lambda f: f.lstrip('@').lower())
        # Ensure Gotham Black is in the list (it's the default)
        if 'Gotham Black' not in all_fonts_player:
            all_fonts_player.insert(0, 'Gotham Black')
        self.player_info_font_combo.addItems(all_fonts_player)
        current_player_font = self.settings.get('player_info_font', 'Gotham Black')
        idx_player = self.player_info_font_combo.findText(current_player_font)
        self.player_info_font_combo.setCurrentIndex(idx_player if idx_player >= 0 else 0)
        self.player_info_font_combo.setItemDelegate(FontPreviewDelegate(self.player_info_font_combo))
        self.player_info_font_combo.setMinimumHeight(32)
        self.player_info_font_combo.setFont(QtGui.QFont(current_player_font, 11))
        self.player_info_font_combo.currentTextChanged.connect(
            lambda f: self.player_info_font_combo.setFont(QtGui.QFont(f, 11))
        )
        form_font.addRow("Player Info Font:", self.player_info_font_combo)

        outer_layout.addWidget(grp_font)

        # ── 5. Content ──────────────────────────────────────────────────────
        grp_content, form_content = make_form("Content")

        self.records_check = QtWidgets.QCheckBox("Enabled")
        self.records_check.setChecked(self.settings.get('show_team_records', True))
        form_content.addRow("Show Player Names, Record:", self.records_check)

        self.cities_check = QtWidgets.QCheckBox("Enabled")
        self.cities_check.setChecked(not self.settings.get('show_team_cities', False))
        form_content.addRow("Show Only Team Name:", self.cities_check)

        self.final_check = QtWidgets.QCheckBox("Enabled")
        self.final_check.setChecked(self.settings.get('include_final_games', True))
        form_content.addRow("Include Final Games:", self.final_check)

        self.scheduled_check = QtWidgets.QCheckBox("Enabled")
        self.scheduled_check.setChecked(self.settings.get('include_scheduled_games', True))
        form_content.addRow("Include Scheduled Games:", self.scheduled_check)

        # Show Game Moneyline (The Odds API)
        ml_row = QtWidgets.QHBoxLayout()
        self.moneyline_check = QtWidgets.QCheckBox("Enabled")
        self.moneyline_check.setChecked(self.settings.get('show_moneyline', False))
        ml_row.addWidget(self.moneyline_check)
        ml_row.addSpacing(12)
        ml_row.addWidget(QtWidgets.QLabel("API Key:  "))
        self.odds_api_key_edit = QtWidgets.QLineEdit()
        self.odds_api_key_edit.setPlaceholderText("the-odds-api key...")
        self.odds_api_key_edit.setText(self.settings.get('odds_api_key', ''))
        self.odds_api_key_edit.setMinimumWidth(180)
        self.odds_api_key_edit.setToolTip("the-odds-api.com API key for fetching moneyline odds")
        ml_row.addWidget(self.odds_api_key_edit)
        ml_row.addSpacing(12)
        ml_row.addWidget(QtWidgets.QLabel("Refresh:  "))
        self.odds_refresh_spin = QtWidgets.QSpinBox()
        self.odds_refresh_spin.setRange(1, 120)
        self.odds_refresh_spin.setValue(self.settings.get('odds_refresh_minutes', 15))
        self.odds_refresh_spin.setSuffix(" min")
        self.odds_refresh_spin.setToolTip("How often to fetch updated moneyline odds (1–120 min)")
        ml_row.addWidget(self.odds_refresh_spin)
        ml_row.addStretch()
        form_content.addRow("Show Game Moneyline:", ml_row)

        self.yesterday_cutoff_spin = QtWidgets.QSpinBox()
        self.yesterday_cutoff_spin.setRange(0, 240)
        self.yesterday_cutoff_spin.setValue(self.settings.get('yesterday_cutoff_minutes', 30))
        self.yesterday_cutoff_spin.setSuffix(" min before first pitch")
        self.yesterday_cutoff_spin.setToolTip(
            "After all games finish, keep showing yesterday's final scores until this many\n"
            "minutes before today's first pitch. Set to 0 to switch at midnight."
        )
        form_content.addRow("Switch to Today's Games:", self.yesterday_cutoff_spin)

        outer_layout.addWidget(grp_content)

        # ── 6. Startup ───────────────────────────────────────────────────────
        grp_startup, form_startup = make_form("Startup")

        self.startup_check = QtWidgets.QCheckBox("Load at Windows Startup")
        self.startup_check.setChecked(get_startup_registry())
        form_startup.addRow(self.startup_check)

        outer_layout.addWidget(grp_startup)

        outer_layout.addStretch()
        scroll.setWidget(container)
        self._general_container = container  # measured in __init__ for auto-sizing
        return scroll

    def create_team_colors_tab(self):
        """Create team colors customization tab — AL on left, NL on right."""
        widget = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout()
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # Info label
        info = QtWidgets.QLabel(
            "Choose Primary, Secondary, or Tertiary to use an official MLB palette color, "
            "or pick Custom to enter any hex color. Changes apply per-team."
        )
        info.setWordWrap(True)
        info.setStyleSheet("padding: 5px; background: #151820; border: 1px solid #2a3a5e; color: #dce0ea;")
        outer.addWidget(info)

        # Reset button
        reset_btn = QtWidgets.QPushButton("Reset All to Defaults")
        reset_btn.clicked.connect(self.reset_team_colors)
        outer.addWidget(reset_btn)

        # Get current custom colors
        custom_colors = self.settings.get('team_colors', {})
        self.color_buttons = {}

        # League / division structure
        AL_DIVISIONS = [
            ("AL East",    ["Orioles", "Red Sox", "Yankees", "Rays", "Blue Jays"]),
            ("AL Central", ["White Sox", "Guardians", "Tigers", "Royals", "Twins"]),
            ("AL West",    ["Astros", "Angels", "Athletics", "Mariners", "Rangers"]),
        ]
        NL_DIVISIONS = [
            ("NL East",    ["Braves", "Marlins", "Mets", "Phillies", "Nationals"]),
            ("NL Central", ["Cubs", "Reds", "Brewers", "Pirates", "Cardinals"]),
            ("NL West",    ["Diamondbacks", "Rockies", "Dodgers", "Padres", "Giants"]),
        ]

        def make_color_row(team):
            """Build slot-combo + swatch + hex row and register in self.color_buttons."""
            palette = MLB_TEAM_COLORS_ALL.get(team, ['#FFFFFF', '#FFFFFF', '#FFFFFF'])
            stored  = custom_colors.get(team)

            # Resolve initial slot and custom hex from stored value
            if isinstance(stored, int) and 0 <= stored <= 2:
                init_slot = stored
                init_hex  = palette[stored]
            elif isinstance(stored, str) and stored.startswith('#'):
                init_slot = 3            # Custom
                init_hex  = stored
            else:
                init_slot = 0            # Primary (default)
                init_hex  = palette[0]

            # Slot combo: Primary / Secondary / Tertiary / Custom
            slot_combo = QtWidgets.QComboBox()
            slot_combo.setFixedWidth(106)
            slot_combo.addItems(["Primary", "Secondary", "Tertiary", "Custom"])
            slot_combo.setCurrentIndex(init_slot)

            # Colour swatch — always shows the effective colour
            swatch_color = palette[init_slot] if init_slot < 3 else init_hex
            color_btn = QtWidgets.QPushButton()
            color_btn.setFixedSize(28, 22)
            color_btn.setStyleSheet(
                f"background-color: {swatch_color}; border: 1px solid #4a5a7e;"
            )
            color_btn.setEnabled(init_slot == 3)
            color_btn.clicked.connect(lambda checked, t=team: self.pick_team_color(t))

            # Hex input — only editable / relevant in Custom mode
            hex_input = QtWidgets.QLineEdit(init_hex)
            hex_input.setMaxLength(7)
            hex_input.setFixedWidth(68)
            hex_input.setEnabled(init_slot == 3)
            hex_input.textChanged.connect(
                lambda text, t=team: self.update_team_color_preview(t, text)
            )

            self.color_buttons[team] = {
                'slot_combo': slot_combo,
                'button':     color_btn,
                'input':      hex_input,
                'color':      swatch_color,
            }

            slot_combo.currentIndexChanged.connect(
                lambda i, t=team: self._on_team_slot_changed(t, i)
            )

            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            row.addWidget(slot_combo)
            row.addWidget(color_btn)
            row.addWidget(hex_input)
            row.addStretch()
            return row

        def make_league_column(divisions):
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(6)
            for div_name, teams in divisions:
                grp = QtWidgets.QGroupBox(div_name)
                form = QtWidgets.QFormLayout(grp)
                form.setContentsMargins(8, 12, 8, 8)
                form.setVerticalSpacing(5)
                form.setHorizontalSpacing(8)
                for team in teams:
                    form.addRow(f"{team}:", make_color_row(team))
                col.addWidget(grp)
            col.addStretch()
            return col

        # Scroll area containing the two-column layout
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QtWidgets.QWidget()
        cols_layout = QtWidgets.QHBoxLayout(scroll_widget)
        cols_layout.setContentsMargins(4, 4, 4, 4)
        cols_layout.setSpacing(10)
        cols_layout.addLayout(make_league_column(AL_DIVISIONS))
        cols_layout.addLayout(make_league_column(NL_DIVISIONS))
        scroll.setWidget(scroll_widget)
        outer.addWidget(scroll)

        widget.setLayout(outer)
        return widget
    
    def pick_team_color(self, team):
        """Open color picker — auto-switches the row to Custom slot."""
        widgets = self.color_buttons.get(team)
        if not widgets:
            return
        # Ensure Custom slot is active before opening the dialog
        if widgets['slot_combo'].currentIndex() != 3:
            widgets['slot_combo'].setCurrentIndex(3)   # fires _on_team_slot_changed
        current_color = widgets['color']
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(current_color), self, f"Choose color for {team}"
        )
        if color.isValid():
            hex_color = color.name()
            widgets['color'] = hex_color
            widgets['input'].setText(hex_color)
            widgets['button'].setStyleSheet(
                f"background-color: {hex_color}; border: 1px solid #4a5a7e;"
            )
    
    def update_team_color_preview(self, team, hex_color):
        """Update swatch preview when the Custom hex input changes."""
        if hex_color.startswith('#') and len(hex_color) == 7:
            try:
                QtGui.QColor(hex_color)   # Validate colour string
                widgets = self.color_buttons.get(team)
                if widgets:
                    widgets['color'] = hex_color
                    widgets['button'].setStyleSheet(
                        f"background-color: {hex_color}; border: 1px solid #4a5a7e;"
                    )
            except Exception:
                pass

    def _on_team_slot_changed(self, team, index):
        """React to slot-combo changes: update swatch and enable/disable custom controls."""
        widgets = self.color_buttons.get(team)
        if not widgets:
            return
        palette   = MLB_TEAM_COLORS_ALL.get(team, ['#FFFFFF', '#FFFFFF', '#FFFFFF'])
        is_custom = (index == 3)
        widgets['button'].setEnabled(is_custom)
        widgets['input'].setEnabled(is_custom)
        if not is_custom:
            # Show the chosen palette colour in the swatch
            color = palette[index] if index < len(palette) else palette[0]
            widgets['color'] = color
            widgets['button'].setStyleSheet(
                f"background-color: {color}; border: 1px solid #4a5a7e;"
            )
        else:
            # Restore swatch to whatever is in the hex input
            cur = widgets['input'].text()
            if cur.startswith('#') and len(cur) == 7:
                widgets['color'] = cur
                widgets['button'].setStyleSheet(
                    f"background-color: {cur}; border: 1px solid #4a5a7e;"
                )
    
    def reset_team_colors(self):
        """Reset all team colors to defaults"""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Reset Team Colors",
            "Reset all team colors to MLB defaults?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            for team, widgets in self.color_buttons.items():
                palette = MLB_TEAM_COLORS_ALL.get(team, ['#FFFFFF', '#FFFFFF', '#FFFFFF'])
                primary = palette[0]
                # setCurrentIndex(0) fires _on_team_slot_changed → updates swatch automatically
                widgets['slot_combo'].setCurrentIndex(0)
                widgets['color'] = primary
                widgets['input'].setText(primary)
    
    def create_network_tab(self):
        """Create network/proxy settings tab"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setAlignment(QtCore.Qt.AlignTop)
        layout.setSpacing(12)
        layout.setContentsMargins(12, 12, 12, 12)

        # Proxy group
        proxy_group = QtWidgets.QGroupBox("Proxy")
        proxy_form = QtWidgets.QFormLayout()
        proxy_form.setSpacing(8)
        proxy_form.setContentsMargins(10, 12, 10, 10)

        self.use_proxy_check = QtWidgets.QCheckBox("Enable Proxy")
        self.use_proxy_check.setChecked(bool(self.settings.get('use_proxy', False)))
        proxy_form.addRow(self.use_proxy_check)

        self.proxy_url_edit = QtWidgets.QLineEdit(
            normalize_proxy_url(self.settings.get('proxy', ''))
        )
        self.proxy_url_edit.setPlaceholderText("http://proxy.example.com:8080")
        self.proxy_url_edit.setEnabled(self.use_proxy_check.isChecked())
        self.use_proxy_check.toggled.connect(self.proxy_url_edit.setEnabled)
        proxy_form.addRow("Proxy URL:", self.proxy_url_edit)

        proxy_group.setLayout(proxy_form)
        layout.addWidget(proxy_group)

        # Certificate group
        cert_group = QtWidgets.QGroupBox("SSL Certificate (Optional)")
        cert_form = QtWidgets.QFormLayout()
        cert_form.setSpacing(8)
        cert_form.setContentsMargins(10, 12, 10, 10)

        self.use_cert_check = QtWidgets.QCheckBox("Use Certificate File")
        self.use_cert_check.setChecked(bool(self.settings.get('use_cert', False)))
        cert_form.addRow(self.use_cert_check)

        cert_row = QtWidgets.QHBoxLayout()
        self.cert_file_edit = QtWidgets.QLineEdit(self.settings.get('cert_file', ''))
        self.cert_file_edit.setPlaceholderText("Path to .pem / .crt certificate file")
        self.cert_file_edit.setEnabled(self.use_cert_check.isChecked())
        self.use_cert_check.toggled.connect(self.cert_file_edit.setEnabled)
        self._cert_browse_btn = QtWidgets.QPushButton("Browse…")
        self._cert_browse_btn.setFixedWidth(80)
        self._cert_browse_btn.setEnabled(self.use_cert_check.isChecked())
        self.use_cert_check.toggled.connect(self._cert_browse_btn.setEnabled)
        self._cert_browse_btn.clicked.connect(self.browse_cert_file)
        cert_row.addWidget(self.cert_file_edit)
        cert_row.addWidget(self._cert_browse_btn)
        cert_form.addRow("Certificate File:", cert_row)

        cert_group.setLayout(cert_form)
        layout.addWidget(cert_group)

        widget.setLayout(layout)
        return widget

    def create_hotkeys_tab(self):
        """Create read-only keyboard shortcuts reference tab."""
        SHORTCUTS = [
            ("+  /  =" , "Increase scroll speed by 1  (max 16)"),
            ("-"       , "Decrease scroll speed by 1  (min 1)"),
            ("Y"       , "Show Yesterday's games"),
            ("D"       , "Show Today's games  (return to auto mode)"),
            ("T"       , "Show Tomorrow's games"),
            ("R"       , "Restart ticker  (replay intro animation)"),
            ("G"       , "Refresh / fetch latest game data"),
            ("F"       , "Toggle FPS counter overlay on/off"),
            ("P"       , "Pause / unpause scrolling"),
            ("S"       , "Open Standings window"),
            ("."       , "Open Settings dialog"),
            ("1 – 4"   , "Move ticker to that monitor number"),
            ("Q"       , "Quit"),
        ]

        KEY_QSS   = (
            "background:#1e2530; color:#e0e8ff; border:1px solid #3a4a6a;"
            "border-radius:4px; padding:2px 8px; font-family:Consolas,monospace;"
            "font-size:12px; font-weight:bold;"
        )
        DESC_QSS  = "color:#c8d8f0; font-size:12px;"
        NOTE_QSS  = "color:#667788; font-size:10px; font-style:italic;"

        widget = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout()
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        grp = QtWidgets.QGroupBox("Keyboard Shortcuts  (ticker must have focus)")
        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(12, 16, 12, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        for row, (key, desc) in enumerate(SHORTCUTS):
            key_lbl  = QtWidgets.QLabel(key)
            key_lbl.setStyleSheet(KEY_QSS)
            key_lbl.setAlignment(QtCore.Qt.AlignCenter)
            key_lbl.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)

            desc_lbl = QtWidgets.QLabel(desc)
            desc_lbl.setStyleSheet(DESC_QSS)

            grid.addWidget(key_lbl,  row, 0)
            grid.addWidget(desc_lbl, row, 1)

        grp.setLayout(grid)
        outer.addWidget(grp)

        note = QtWidgets.QLabel("All shortcuts are session-only and do not modify saved settings.")
        note.setStyleSheet(NOTE_QSS)
        note.setWordWrap(True)
        outer.addWidget(note)
        outer.addStretch()

        widget.setLayout(outer)
        return widget

    def browse_cert_file(self):
        """Open a file dialog to select an SSL certificate file."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Certificate File",
            "",
            "Certificate Files (*.pem *.crt *.cer *.ca-bundle);;All Files (*)"
        )
        if path:
            self.cert_file_edit.setText(path)

    def _collect_settings(self):
        """Read all dialog controls into self.settings and save to disk."""
        self.settings['speed'] = self.speed_spin.value()
        self.settings['update_interval'] = self.update_spin.value()
        self.settings['ticker_height'] = self.height_spin.value()
        self.settings['font'] = self.font_combo.currentText()
        self.settings['font_scale_percent'] = self.font_scale_slider.value()
        self.settings['player_info_font'] = self.player_info_font_combo.currentText()
        self.settings['show_team_records'] = self.records_check.isChecked()
        self.settings['include_final_games'] = self.final_check.isChecked()
        self.settings['include_scheduled_games'] = self.scheduled_check.isChecked()
        self.settings['show_moneyline'] = self.moneyline_check.isChecked()
        self.settings['odds_api_key'] = self.odds_api_key_edit.text().strip()
        self.settings['odds_refresh_minutes'] = self.odds_refresh_spin.value()
        self.settings['yesterday_cutoff_minutes'] = self.yesterday_cutoff_spin.value()
        self.settings['show_team_cities'] = not self.cities_check.isChecked()
        self.settings['led_background'] = self.led_bg_check.isChecked()
        self.settings['glass_overlay'] = self.glass_check.isChecked()
        self.settings['background_opacity'] = int(round(self.opacity_slider.value() * 255 / 100))
        self.settings['content_opacity'] = int(round(self.content_opacity_slider.value() * 255 / 100))
        self.settings['show_fps_overlay'] = self.fps_check.isChecked()
        self.settings['monitor_index'] = self.monitor_combo.currentIndex()

        # Startup — always save the setting; only touch the registry when frozen
        enabled = self.startup_check.isChecked()
        self.settings['load_at_startup'] = enabled
        if getattr(sys, 'frozen', False):
            set_startup_registry(enabled)

        # Network / proxy settings
        self.settings['use_proxy'] = self.use_proxy_check.isChecked()
        self.settings['proxy'] = self.proxy_url_edit.text().strip()
        self.settings['use_cert'] = self.use_cert_check.isChecked()
        self.settings['cert_file'] = self.cert_file_edit.text().strip()

        # Team colors — store slot index (1/2) for Secondary/Tertiary, hex for Custom,
        # nothing for Primary (slot 0, the default).
        team_colors = {}
        for team, widgets in self.color_buttons.items():
            slot_index = widgets['slot_combo'].currentIndex()
            if slot_index in (1, 2):
                team_colors[team] = slot_index          # int: 1=secondary 2=tertiary
            elif slot_index == 3:
                hex_val = widgets['input'].text()
                if hex_val.startswith('#') and len(hex_val) == 7:
                    team_colors[team] = hex_val         # custom hex string
            # slot 0 (Primary) = default → omit from saved dict
        self.settings['team_colors'] = team_colors
        
        # Admin tab settings (if shown)
        if self._admin_tab_shown:
            self.settings['player_font_scale_percent'] = self.player_font_scale_slider.value()

        save_settings(self.settings)
        apply_proxy_settings()

    # Settings that cannot be applied live — require a full restart
    _RESTART_KEYS = ('ticker_height', 'monitor_index')

    def _needs_restart(self, old_settings):
        """Return True if any restart-required setting changed."""
        return any(old_settings.get(k) != self.settings.get(k)
                   for k in self._RESTART_KEYS)

    def _offer_restart(self):
        """Ask the user whether to restart now; if yes, relaunch the process."""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Restart Required",
            "Ticker height and/or monitor changes require a restart to take effect.\n\nRestart now?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            if getattr(sys, 'frozen', False):
                args = sys.argv          # PyInstaller .exe: argv[0] is the exe
            else:
                args = [sys.executable] + sys.argv
            # Strip Qt env vars inherited from this (parent) process.
            # The child's PyInstaller runtime hooks will re-set them to
            # the child's own _MEI temp dir.  Inheriting the parent's
            # _MEI paths (which are being deleted as the parent quits)
            # causes Qt to report 'Could not find platform plugin in ""'.
            _child_env = os.environ.copy()
            for _qt_var in (
                'QT_PLUGIN_PATH',
                'QML2_IMPORT_PATH',
                'QT_QPA_PLATFORM_PLUGIN_PATH',
            ):
                _child_env.pop(_qt_var, None)
            # Release the AppBar reservation NOW, before spawning the child.
            # If we wait until the 3-s quit timer fires the child will call
            # setup_appbar() while our strip is still registered and Windows
            # will push it below us — the "new ticker appears below the old one"
            # symptom.  Releasing first gives the shell time to free the work
            # area before the child process initialises Qt (which takes ~1-2 s).
            _ticker = self.parent()
            if _ticker and hasattr(_ticker, 'remove_appbar'):
                _ticker.remove_appbar()
                QtWidgets.QApplication.processEvents()  # let shell digest ABM_REMOVE

            subprocess.Popen(args, env=_child_env)
            # Delay 3 s before quitting so the child process has time to
            # bootstrap Python and lock its Qt DLLs before our atexit
            # handler sweeps the shared _MEI temp folder.  Without this
            # delay, qwindows.dll (locked lazily at QApplication creation)
            # can be deleted by the parent before the child ever uses it.
            _app = QtWidgets.QApplication.instance()
            QtCore.QTimer.singleShot(3000, _app.quit)

    def apply_settings(self):
        """Save settings and apply hotswappable values to the live ticker."""
        old = {k: self.settings.get(k) for k in self._RESTART_KEYS}
        self._collect_settings()
        if self.parent() and hasattr(self.parent(), 'apply_live_settings'):
            self.parent().apply_live_settings()
        if self._needs_restart(old):
            self._offer_restart()

    def save_and_close(self):
        """Save settings, apply live, and close dialog."""
        old = {k: self.settings.get(k) for k in self._RESTART_KEYS}
        self._collect_settings()
        if self.parent() and hasattr(self.parent(), 'apply_live_settings'):
            self.parent().apply_live_settings()
        needs_restart = self._needs_restart(old)
        self.accept()
        if needs_restart:
            self._offer_restart()


def main():
    # Set Windows multimedia timer resolution to 1 ms so QTimer(8 ms) fires
    # accurately instead of at the default 15.6 ms system-clock granularity.
    # The OS automatically restores the previous resolution when the process exits.
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

    # Must be set before QApplication is created so Qt renders at native DPI
    # instead of letting Windows stretch a low-DPI bitmap (fixes font compression
    # at display scales like 125%, 150%, 200%, etc.)
    if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Register ALL font files from app directories so user-chosen fonts work.
    # Must happen after QApplication is created and before any window/dialog.
    register_all_font_files()

    # Apply proxy / certificate settings from config before any network calls
    apply_proxy_settings()

    # Print performance info
    print("\n" + "="*60)
    print("MLB-TCKR Performance Status")
    print("="*60)
    print(f"Cython Optimizations: {'ENABLED' if CYTHON_AVAILABLE else 'DISABLED (using Python fallback)'}")
    print(f"Frame Rate: 60 FPS (16ms frame time)")
    print(f"Scrolling: Sub-pixel smooth scrolling")
    print(f"Rendering: Cached backgrounds and overlays")
    if not CYTHON_AVAILABLE:
        print("\nTIP: For best performance, run: build_performance.bat")
    print("="*60 + "\n")
    
    window = MLBTickerWindow()

    # Ensure AppBar reservation is always freed when the process exits,
    # even on Windows 10 where closeEvent can arrive after the event loop ends.
    app.aboutToQuit.connect(window.remove_appbar)

    # System tray icon: support bundled onefile/onedir assets and both ICO/PNG.
    runtime_base = getattr(sys, '_MEIPASS', None)
    icon_locations = [
        os.path.join(APPDATA_DIR, "mlb.ico"),
        os.path.join(APPDATA_DIR, "mlb.png"),
        os.path.join(os.path.dirname(__file__), "mlb.ico"),
        os.path.join(os.path.dirname(__file__), "mlb.png"),
        "mlb.ico",
        "mlb.png",
    ]
    if runtime_base:
        icon_locations.insert(0, os.path.join(runtime_base, "mlb.ico"))
        icon_locations.insert(1, os.path.join(runtime_base, "mlb.png"))
    
    icon = QtGui.QIcon()
    for icon_path in icon_locations:
        if os.path.exists(icon_path):
            icon = QtGui.QIcon(icon_path)
            if not icon.isNull():
                print(f"[TRAY] Loaded icon from {icon_path}")
                break
    
    if icon.isNull():
        # Ensure tray icon is visible even when bundled icon file is missing.
        fallback_pixmap = QtGui.QPixmap(32, 32)
        fallback_pixmap.fill(QtGui.QColor('#0B5FA5'))
        fallback_painter = QtGui.QPainter(fallback_pixmap)
        fallback_painter.setPen(QtGui.QColor('#FFFFFF'))
        fallback_painter.setFont(QtGui.QFont('Arial', 14, QtGui.QFont.Bold))
        fallback_painter.drawText(fallback_pixmap.rect(), QtCore.Qt.AlignCenter, 'M')
        fallback_painter.end()
        icon = QtGui.QIcon(fallback_pixmap)
        print("[TRAY] Icon file not found, using generated fallback icon")

    app.setWindowIcon(icon)
    window.setWindowIcon(icon)
    
    tray_icon = QtWidgets.QSystemTrayIcon(icon, app)
    tray_menu = QtWidgets.QMenu()
    
    refresh_action = tray_menu.addAction("Refresh Games")
    refresh_action.triggered.connect(window.start_data_fetch)

    restart_action = tray_menu.addAction("Restart")
    restart_action.triggered.connect(window._restart_intro)

    tray_menu.addSeparator()

    pause_action = tray_menu.addAction("Pause Ticker")
    def _tray_toggle_pause():
        window.scroll_paused = not window.scroll_paused
        if window.scroll_paused:
            window.scroll_timer.stop()
        else:
            if not window.intro_active and not window.is_hovered:
                window._last_frame_ms = window._elapsed_timer.nsecsElapsed() / 1_000_000.0
                window.scroll_timer.start(window._scroll_timer_interval_ms)
    pause_action.triggered.connect(_tray_toggle_pause)

    def _update_tray_pause_label():
        pause_action.setText("Unpause Ticker" if window.scroll_paused else "Pause Ticker")
    tray_menu.aboutToShow.connect(_update_tray_pause_label)

    tray_menu.addSeparator()

    # Date submenu — session-only, not saved to settings
    date_menu = tray_menu.addMenu("Show Games For...")
    _tray_date_actions = {}
    for _label, _key in [("Yesterday's Games", "yesterday"),
                          ("Today's Games",     "today"),
                          ("Tomorrow's Games",  "tomorrow")]:
        _act = date_menu.addAction(_label)
        _act.setCheckable(True)
        _tray_date_actions[_key] = _act
        def _make_tray_date_handler(k=_key):
            def _handler(checked):
                # Clicking the already-active item unchecks it → return to auto mode
                window._date_view_override = k if checked else None
                if window._yesterday_mode:
                    window._yesterday_mode = False
                    window.waiting_for_next_day = False
                    window.next_day_timer.stop()
                    window._pending_today_games = []
                    window._pending_today_date = ''
                window.start_data_fetch()
            return _handler
        _act.triggered.connect(_make_tray_date_handler())

    def _update_tray_date_checks():
        for k, act in _tray_date_actions.items():
            act.setChecked(window._date_view_override == k)
    tray_menu.aboutToShow.connect(_update_tray_date_checks)

    tray_menu.addSeparator()

    standings_action = tray_menu.addAction("Standings...")

    def open_standings():
        # Share the same standings window with the ticker bar context menu
        if not hasattr(window, '_standings_win') or \
                window._standings_win is None or \
                not window._standings_win.isVisible():
            window._standings_win = StandingsWindow()
            window._standings_win.show()
        else:
            window._standings_win.raise_()
            window._standings_win.activateWindow()

    standings_action.triggered.connect(open_standings)

    tray_menu.addSeparator()

    settings_action = tray_menu.addAction("Settings...")
    settings_action.triggered.connect(lambda: SettingsDialog(window).exec_())  # type: ignore[arg-type]

    tray_menu.addSeparator()

    about_action = tray_menu.addAction("About MLB-TCKR...")
    about_action.triggered.connect(lambda: AboutDialog(window).exec_())  # type: ignore[arg-type]
    
    tray_menu.addSeparator()
    
    quit_action = tray_menu.addAction("Quit")
    quit_action.triggered.connect(app.quit)
    
    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()
    tray_icon.setToolTip("MLB Ticker")
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()


