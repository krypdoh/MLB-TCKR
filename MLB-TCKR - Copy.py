"""
Author: Paul R. Charovkine
Program: MLB-TCKR.py
Date: 2026.0320.0908
Version: 0.9 beta
License: GNU AGPLv3

Description:
MLB ticker application that displays live baseball game data in a scrolling ticker bar.
Shows team logos, scores, runners on base, outs, innings, and game times just like a
traditional LED sports ticker. Integrates with Windows AppBar for persistent display.
"""

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
    import pip_system_certs.wrapt_requests
    pip_system_certs.wrapt_requests.inject_truststore()
    print("[SSL] System certificate store injected into requests")
except Exception:
    pass  # Package not installed — requests falls back to its bundled certifi CA

import sys
import os
import json
import math
import time
import datetime
import random
import statsapi
from PyQt5 import QtWidgets, QtCore, QtGui
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

#  MLB Team Colors (Primary colors from official MLB color table)
MLB_TEAM_COLORS_DEFAULT = {
    'Diamondbacks': '#A71930',  # Sedona Red
    'Braves': '#CE1141',  # Scarlet
    'Orioles': '#df6501',  # Orange
    'Red Sox': '#BD3039',  # Red
    'Cubs': '#0E3386',  # Blue
    'White Sox': '#ffffff',  # White
    'Reds': '#C6011F',  # Red
    'Guardians': '#e50000',  # Red
    'Rockies': '#33006F',  # Purple
    'Tigers': '#0C2340',  # Navy Blue
    'Astros': '#ffaa00',  # Gold
    'Royals': '#004687',  # Royal Blue
    'Angels': '#ff0000',  # Red
    'Dodgers': '#005A9C',  # Dodger Blue
    'Marlins': '#00A3E0',  # Miami Blue
    'Brewers': '#12284B',  # Navy Blue
    'Twins': '#002B5C',  # Navy Blue
    'Mets': '#ff8903',  # Orange
    'Yankees': '#003087',  # Navy Blue
    'Athletics': '#06cb3e',  # Green
    'Phillies': '#E81828',  # Red
    'Pirates': '#ffff00',  # Yellow
    'Padres': '#fae608',  # Yellow
    'Giants': '#FD5A1E',  # Orange
    'Mariners': '#0C2C56',  # Navy Blue
    'Cardinals': '#C41E3A',  # Red
    'Rays': '#092C5C',  # Navy Blue
    'Rangers': '#003278',  # Blue
    'Blue Jays': '#134A8E',  # Blue
    'Nationals': '#AB0003',  # Red
}

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
        "font_scale_percent": 150,
        "show_team_records": True,
        "show_team_cities": False,
        "include_final_games": True,
        "include_scheduled_games": True,
        "led_background": True,
        "glass_overlay": True,
        "background_opacity": 255,
        "show_fps_overlay": False,
        "monitor_index": 0,
        "use_proxy": False,
        "proxy": "",
        "use_cert": False,
        "cert_file": "",
        "team_colors": {}  # Custom team colors (empty = use defaults)
        ,
        "docked": True  # When True, ticker is docked (not moveable) and registered as AppBar
    }


def save_settings(settings):
    os.makedirs(APPDATA_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)


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
        print(f"[PROXY] Certificate: {cert_file}")
    else:
        # No custom cert specified — clear the override so that pip_system_certs
        # (if installed) or requests' default CA bundle handles verification.
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
    """Load PixelFont7 font for W-L line and return its family name (cached)."""
    global _RECORD_FONT_FAMILY
    if _RECORD_FONT_FAMILY is not None:
        return _RECORD_FONT_FAMILY

    target_family = "PixelFont7-G02A"
    db = QtGui.QFontDatabase()
    if target_family in db.families():
        _RECORD_FONT_FAMILY = target_family
        return _RECORD_FONT_FAMILY

    font_locations = [
        os.path.join(APPDATA_DIR, "PixelFont7-G02A.ttf"),
        os.path.join(os.path.dirname(__file__), "PixelFont7-G02A.ttf"),
        "PixelFont7-G02A.ttf"
    ]
    for font_path in font_locations:
        if os.path.exists(font_path):
            font_id = QtGui.QFontDatabase.addApplicationFont(font_path)
            if font_id != -1:
                families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    print(f"[FONT] Loaded record font: {families[0]} from {font_path}")
                    _RECORD_FONT_FAMILY = families[0]
                    return _RECORD_FONT_FAMILY

    print("[FONT] PixelFont7-G02A.ttf not found, using ticker font for records")
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
    """Get primary color for an MLB team (custom or default)"""
    settings = get_settings()
    custom_colors = settings.get('team_colors', {})
    
    # Extract nickname from full team name
    nickname = get_team_nickname(team_name)
    
    # Check for custom color first
    if nickname in custom_colors:
        return custom_colors[nickname]
    
    # Fall back to default
    return MLB_TEAM_COLORS_DEFAULT.get(nickname, '#FFFFFF')


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
        font = QtGui.QFont(font_family, int(size * 0.25), QtGui.QFont.Bold)
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
        font = QtGui.QFont(font_family, int(size * 0.25), QtGui.QFont.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, nickname[:3].upper())
        painter.end()
        TEAM_LOGO_CACHE[cache_key] = pixmap
        return pixmap
    
    print(f"[LOGO] Successfully loaded: {logo_path} ({pixmap.width()}x{pixmap.height()})")
    scaled_logo = pixmap.scaled(size, size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    TEAM_LOGO_CACHE[cache_key] = scaled_logo
    return scaled_logo


def fetch_todays_games():
    """Fetch all MLB games for today"""
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
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        season_year = datetime.datetime.now().year
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
                    
                    # Get outs from count
                    count = current_play.get('count', {})
                    game_info['outs'] = count.get('outs', 0)
                    
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

                    pitcher_last = format_last_name(pitcher)
                    batter_last = format_last_name(batter)

                    # Replace W-L line with live P/B stats once game starts
                    if game_info.get('inning_state', '') == 'Top':
                        game_info['away_subtext'] = f"AB: {batter_last} {batter_avg}"
                        game_info['home_subtext'] = f"P: {pitcher_last} {pitcher_era}"
                    else:
                        game_info['away_subtext'] = f"P: {pitcher_last} {pitcher_era}"
                        game_info['home_subtext'] = f"AB: {batter_last} {batter_avg}"
                    
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
            else:
                game_info['outs'] = 0
                game_info['runners'] = {'first': False, 'second': False, 'third': False}
            
            game_data.append(game_info)
        
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
            # Include scheduled/pre-game if setting allows
            elif status in ['Pre-Game', 'Scheduled', 'Warmup']:
                if settings.get('include_scheduled_games', True):
                    filtered_games.append(game)
        
        print(f"[MLB] Fetched {len(game_data)} games, showing {len(filtered_games)} after filtering")
        return filtered_games
        
    except Exception as e:
        print(f"[MLB ERROR] Failed to fetch games: {e}")
        return []


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


class GameDataWorker(QtCore.QThread):
    """Background thread for fetching game data without blocking UI"""
    data_fetched = QtCore.pyqtSignal(list)  # Signal to emit fetched game data
    
    def run(self):
        """Fetch game data in background thread"""
        games = fetch_todays_games()
        self.data_fetched.emit(games)


def draw_baseball_diamond(runners, outs, inning_num, is_top, size=50, dpr=1.0):
    """
    Draw baseball diamond with runners, outs, and inning indicator
    
    Args:
        runners: dict with 'first', 'second', 'third' (boolean)
        outs: number of outs (0-2)
        inning_num: inning number
        is_top: True if top of inning, False if bottom
        size: size in logical pixels
        dpr: device pixel ratio (pass screen DPR for crisp rendering)
    """
    # Cache avoids repainting identical diamond states (same runners/outs/inning)
    runners_key = (bool(runners.get('first')), bool(runners.get('second')), bool(runners.get('third')))
    inning_txt  = 'F' if (isinstance(inning_num, str) and inning_num == 'F') else f"{'T' if is_top else 'B'}{inning_num}"
    _dc_key = (runners_key, int(outs), inning_txt, int(size), dpr)
    if _dc_key in _DIAMOND_CACHE:
        return _DIAMOND_CACHE[_dc_key]

    total_width = size + 30  # Right gutter for inning indicator (enough for 3-char labels like "B15")
    pixmap = QtGui.QPixmap(int(total_width * dpr), int(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(QtCore.Qt.transparent)
    
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    
    center_x = size / 2 - 4  # Shift field left to leave clean space for inning text
    center_y = size / 2 - 4  # Move bases up by 1 additional pixel
    
    # Draw 3 bases as diamonds in triangle formation
    diamond_size = 10
    
    # Base positions (triangle formation - tighter)
    # 2nd base at top
    second_x = center_x
    second_y = center_y - 6
    
    # 1st base at right
    first_x = center_x + 8
    first_y = center_y + 5
    
    # 3rd base at left
    third_x = center_x - 8
    third_y = center_y + 5
    
    bases = [
        ('second', second_x, second_y),
        ('first', first_x, first_y),
        ('third', third_x, third_y)
    ]
    
    for base_name, x, y in bases:
        # Create diamond polygon (rotated square)
        diamond = QtGui.QPolygon([
            QtCore.QPoint(int(x), int(y - diamond_size/2)),      # top
            QtCore.QPoint(int(x + diamond_size/2), int(y)),      # right
            QtCore.QPoint(int(x), int(y + diamond_size/2)),      # bottom
            QtCore.QPoint(int(x - diamond_size/2), int(y))       # left
        ])
        
        if runners.get(base_name):
            # Runner on base - bright green
            painter.setBrush(QtGui.QBrush(QtGui.QColor('#00FF00')))
            painter.setPen(QtGui.QPen(QtGui.QColor('#00FF00'), 2))
        else:
            # Empty base - gray outline
            painter.setBrush(QtGui.QBrush(QtCore.Qt.transparent))
            painter.setPen(QtGui.QPen(QtGui.QColor('#666666'), 2))
        
        painter.drawPolygon(diamond)
    
    # Draw outs (3 circles below the bases)
    out_radius = 3
    out_spacing = 14
    outs_start_x = center_x - out_spacing
    outs_y = size - 9
    
    for i in range(3):
        x = outs_start_x + (i * out_spacing)
        
        if i < outs:
            # Lit out - bright red
            painter.setBrush(QtGui.QBrush(QtGui.QColor('#FF0000')))
            painter.setPen(QtGui.QPen(QtGui.QColor('#FF0000'), 1))
        else:
            # Unlit out - gray outline only
            painter.setBrush(QtGui.QBrush(QtCore.Qt.transparent))
            painter.setPen(QtGui.QPen(QtGui.QColor('#666666'), 2))
        
        painter.drawEllipse(QtCore.QPointF(x, outs_y), out_radius, out_radius)
    
    # Draw inning indicator (T5 or B5 format, or F for final)
    inning_x = size - 3  # Closer to the diamond field

    # Handle final games (inning_num will be "F")
    if isinstance(inning_num, str) and inning_num == 'F':
        inning_text = 'F'
    else:
        inning_letter = 'T' if is_top else 'B'
        inning_text = f"{inning_letter}{inning_num}"

    # Use custom font if available, otherwise Arial
    font_family = load_custom_font()
    font = QtGui.QFont(font_family, 10, QtGui.QFont.Bold)  # ~1.5pt smaller than before
    painter.setFont(font)

    # Vertically center the inning text within the base diamond field
    # (between top of 2nd base and bottom of 1st/3rd bases, ignoring out circles)
    field_top = second_y - diamond_size / 2
    field_bottom = first_y + diamond_size / 2
    fm = QtGui.QFontMetrics(font)
    inning_y = (field_top + field_bottom) / 2 + (fm.ascent() - fm.descent()) / 2

    painter.setPen(QtGui.QPen(QtGui.QColor('#FFD700')))  # Gold color
    painter.drawText(int(inning_x), int(inning_y), inning_text)

    # Expose the rendered inning text width (in logical px) so callers can
    # guarantee a gap between the diamond and the home score.
    inning_text_right_phys = inning_x + fm.horizontalAdvance(inning_text)
    # Store as an attribute on the pixmap so build_game_pixmap can read it
    pixmap._inning_text_right_phys = inning_text_right_phys

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
        record_font_family = load_record_font_family() or font_to_use
        self.font = QtGui.QFont(font_to_use)
        self.font.setPixelSize(max(12, int(self.ticker_height * 0.35 * font_scale)))
        self.font.setBold(True)
        self.small_font = QtGui.QFont(record_font_family)
        self.small_font.setPixelSize(max(6, int(self.ticker_height * 0.22 * font_scale * 0.5)) + 3)
        self.time_font = QtGui.QFont(font_to_use)
        self.time_font.setPixelSize(max(6, int(self.ticker_height * 0.35 * font_scale * 0.6)))
        self.vs_font = QtGui.QFont(font_to_use)
        self.vs_font.setPixelSize(max(6, int(self.ticker_height * 0.35 * font_scale * 0.5)))
        self.vs_font.setBold(True)
        
        # Animation timer - 60 FPS for smooth scrolling (started after intro finishes)
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
        
        # Next day check timer (checks hourly after all games finish)
        self.next_day_timer = QtCore.QTimer()
        self.next_day_timer.timeout.connect(self.check_for_next_day_games)
        self.next_day_timer.setInterval(3600000)  # Check every hour
        
        # Initial fetch
        self.start_data_fetch()

        self.show()

        # Setup AppBar after window is shown (requires valid, visible HWND)
        # Only register AppBar when 'docked' setting is enabled
        if self.settings.get('docked', True):
            self.setup_appbar()

        # Build intro animation geometry now (window is shown, size is final).
        # The timer is NOT started yet — it fires after the first ticker draw + 2 s.
        self.build_intro_animation()
    
    def _start_intro(self):
        """Launch the intro pixel-reveal timer (called after 2-s delay)."""
        if self.intro_active:
            self.intro_timer.start(33)  # ~30 fps
            print("[INTRO] Starting pixel-reveal animation")

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

    def start_data_fetch(self):
        """Start background data fetch (non-blocking)"""
        # Don't start a new fetch if one is already running
        if self.is_fetching:
            return
        
        self.is_fetching = True
        self.data_worker = GameDataWorker()
        self.data_worker.data_fetched.connect(self.on_data_received)
        self.data_worker.finished.connect(self.on_fetch_complete)
        self.data_worker.start()
    
    def on_data_received(self, games):
        """Handle newly fetched game data (runs on main thread)"""
        self.games = games
        current_date = datetime.datetime.now().strftime('%Y-%m-%d')
        
        # Check if all games are finished
        all_finished = self.check_all_games_finished()
        
        # If we were waiting for next day and found new games, resume normal updates
        if self.waiting_for_next_day and not all_finished:
            print("[MLB] New day's games detected, resuming normal updates")
            self.waiting_for_next_day = False
            self.next_day_timer.stop()
            self.update_timer.start(self.settings.get('update_interval', 10) * 1000)
        
        # If all games just finished, switch to next-day mode
        elif all_finished and not self.waiting_for_next_day:
            print("[MLB] All games finished for today, switching to next-day polling")
            self.waiting_for_next_day = True
            self.update_timer.stop()  # Stop frequent polling
            self.next_day_timer.start()  # Start checking for next day
        
        self.last_fetch_date = current_date

        # Only rebuild when displayed data has actually changed, avoiding the
        # brief main-thread stall on every refresh where nothing is different.
        new_fp = self._games_fingerprint()
        if new_fp != self._last_ticker_fp:
            self._last_ticker_fp = new_fp
            self.build_ticker_pixmap()
            if self.ticker_pixmap:
                raw_speed = self.settings.get('speed', 2)
                self._scroll_speed_px_per_ms = (raw_speed * 0.5) / 16.667
                self._scroll_max_width = (self.ticker_pixmap.width() / self.dpr) / 2.0
            self._last_frame_ms = self._elapsed_timer.elapsed()

        # First time the ticker is ready: schedule intro to start after 2 s
        if self.intro_active and not self.intro_timer_started:
            self.intro_timer_started = True
            QtCore.QTimer.singleShot(2000, self._start_intro)
            print("[INTRO] Ticker ready — intro will start in 2 s")

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
        current_date = datetime.datetime.now().strftime('%Y-%m-%d')
        
        # Only fetch if date has changed
        if self.last_fetch_date and current_date != self.last_fetch_date:
            print(f"[MLB] New day detected ({current_date}), checking for games...")
            self.start_data_fetch()
        else:
            # If still same day, just log that we're waiting
            current_hour = datetime.datetime.now().hour
            if current_hour >= 6:  # Only log during reasonable hours
                print(f"[MLB] Waiting for next day's games (current: {current_date})")

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
        intro_font.setPixelSize(max(12, int(h_phys * 0.35 * 1.5)))  # size in physical px
        intro_font.setBold(True)

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
        logo_h_phys = int(h_phys * 0.82)
        logo_pm = self._load_intro_logo(logo_h_phys)
        logo_w = logo_pm.width() if logo_pm else 0  # already in physical pixels
        gap = int(14 * self.dpr)

        content_w = logo_w + (gap if logo_pm else 0) + text_width
        start_x = (w_phys - content_w) // 2
        logo_y = (h_phys - logo_h_phys) // 2
        text_y = (h_phys + metrics.ascent() - metrics.descent()) // 2

        # Full intro pixmap at physical resolution — NO DPR set (raw pixel surface)
        self.intro_pixmap = QtGui.QPixmap(w_phys, h_phys)
        self.intro_pixmap.fill(QtCore.Qt.black)

        p = QtGui.QPainter(self.intro_pixmap)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, False)
        if logo_pm:
            p.drawPixmap(start_x, logo_y, logo_pm)
        p.setFont(intro_font)
        p.setPen(QtGui.QColor('#00FF00'))
        text_x = start_x + logo_w + (gap if logo_pm else 0)
        p.drawText(text_x, text_y, part1)
        p.drawText(text_x + part1_ink_right, text_y, part2)
        p.end()

        # Display pixmap starts fully black — NO DPR set
        self.intro_display = QtGui.QPixmap(w_phys, h_phys)
        self.intro_display.fill(QtCore.Qt.black)

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
            for i in range(end, self.intro_revealed_count):
                r, c = blocks[i]
                p.fillRect(QtCore.QRect(c * bs, r * bs, bs, bs), QtGui.QColor(0, 0, 0))
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
                self._last_frame_ms = self._elapsed_timer.elapsed()
                # Kick off normal scrolling now that intro is finished
                self.scroll_timer.start(16)
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
                g.get('away_subtext'), g.get('home_subtext'),
                bool(r.get('first')), bool(r.get('second')), bool(r.get('third')),
                g.get('away_record'), g.get('home_record'),
            ))
        return (settings_key, tuple(parts))

    def build_ticker_pixmap(self):
        """Build the complete ticker pixmap with all games"""
        if not self.games:
            # No games today
            width = 800
            self.ticker_pixmap = QtGui.QPixmap(int(width * self.dpr), int(self.ticker_height * self.dpr))
            self.ticker_pixmap.setDevicePixelRatio(self.dpr)
            self.ticker_pixmap.fill(QtCore.Qt.black)
            
            painter = QtGui.QPainter(self.ticker_pixmap)
            painter.setRenderHint(QtGui.QPainter.TextAntialiasing, False)
            painter.setFont(self.font)
            painter.setPen(QtGui.QColor('#FFFFFF'))
            text = "No MLB games scheduled today"
            metrics = QtGui.QFontMetrics(self.font)
            text_y = (self.ticker_height + metrics.ascent() - metrics.descent()) // 2
            painter.drawText(40, text_y, text)
            painter.end()
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
                game.get('away_subtext'), game.get('home_subtext'),
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
        
        # Create full ticker pixmap (double width for seamless scrolling)
        self.ticker_pixmap = QtGui.QPixmap(int(total_width * 2 * self.dpr), int(self.ticker_height * self.dpr))
        self.ticker_pixmap.setDevicePixelRatio(self.dpr)
        self.ticker_pixmap.fill(QtCore.Qt.transparent)
        
        painter = QtGui.QPainter(self.ticker_pixmap)
        
        # Draw games twice for seamless loop
        for repeat in [0, 1]:
            x_offset = repeat * total_width

            # MLB logo at the head of each repetition
            if mlb_pm:
                logo_y = (self.ticker_height - int(mlb_pm.height() / self.dpr)) // 2
                painter.drawPixmap(x_offset + logo_padding, logo_y, mlb_pm)
                x_offset += logo_segment_w

            for pixmap in game_pixmaps:
                logical_width = int(pixmap.width() / self.dpr)
                painter.drawPixmap(x_offset, 0, pixmap)
                x_offset += logical_width + spacing
        
        painter.end()

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
        live_subtext_enabled = status in ['In Progress', 'Live']

        away_subtext = game.get('away_subtext') if live_subtext_enabled else None
        home_subtext = game.get('home_subtext') if live_subtext_enabled else None

        away_record_text = str(away_record).strip('()')
        home_record_text = str(home_record).strip('()')

        away_detail_text = away_subtext if away_subtext else away_record_text
        home_detail_text = home_subtext if home_subtext else home_record_text
        
        logo_size = int(self.ticker_height * 0.625)
        metrics = QtGui.QFontMetrics(self.font)
        small_metrics = QtGui.QFontMetrics(self.small_font)
        time_metrics = QtGui.QFontMetrics(self.time_font)
        
        # Get team colors (use full name for color lookup)
        away_color = QtGui.QColor(get_team_color(away_team_full))
        home_color = QtGui.QColor(get_team_color(home_team_full))
        
        # Calculate widths
        away_name_width = metrics.horizontalAdvance(away_team)
        home_name_width = metrics.horizontalAdvance(home_team)
        away_record_width = small_metrics.horizontalAdvance(away_detail_text) if show_records else 0
        home_record_width = small_metrics.horizontalAdvance(home_detail_text) if show_records else 0
        away_block_width = max(away_name_width, away_record_width)
        home_block_width = max(home_name_width, home_record_width)
        
        # Calculate width based on game status
        if status in ['In Progress', 'Live', 'Final', 'Completed', 'Game Over']:
            # Live or Final game: Team Logo Score | Diamond | Score Logo Team
            # For final games, show F instead of inning
            is_final = status in ['Final', 'Completed', 'Game Over']
            
            diamond_pixmap = draw_baseball_diamond(
                game['runners'],
                game['outs'],
                'F' if is_final else game.get('current_inning', 1),
                game.get('inning_state', '') == 'Top',
                size=int(self.ticker_height * 0.7),
                dpr=self.dpr
            )
            
            score_width = metrics.horizontalAdvance("99")
            diamond_logical_width = int(diamond_pixmap.width() / self.dpr)
            # _inning_text_right_phys is stored in logical coords (painter operates in logical space)
            inning_text_right = getattr(diamond_pixmap, '_inning_text_right_phys', 0)
            effective_after_diamond = max(diamond_logical_width, int(inning_text_right)) + 6

            # Layout: Team, Logo, Score, Diamond+gap, Score, Logo, Team
            # Gaps mirror each other: name(5)logo(15)score(8)diamond+gap(6)score(15)logo(5)name
            total_width = (away_block_width + 5 + logo_size + 15 + 
                          score_width + 8 + effective_after_diamond + 
                          score_width + 15 + logo_size + 5 + home_block_width)
        else:
            # Scheduled games only: Team Logo @ Logo Team Time
            status_text = format_game_time_local(game.get('game_datetime'))
            
            status_width = time_metrics.horizontalAdvance(status_text) + 20
            vs_metrics = QtGui.QFontMetrics(self.vs_font)
            at_width = vs_metrics.horizontalAdvance("vs.") + 10
            
            total_width = (away_block_width + 5 + logo_size + 10 + 
                          at_width + 10 + logo_size + 10 + home_block_width + 10 + 
                          status_width)
        
        # Create pixmap at physical resolution so text renders at native DPR
        pixmap = QtGui.QPixmap(int(total_width * self.dpr), int(self.ticker_height * self.dpr))
        pixmap.setDevicePixelRatio(self.dpr)
        pixmap.fill(QtCore.Qt.transparent)
        
        painter = QtGui.QPainter(pixmap)
        # Disable anti-aliasing for text so the LED font's dot-grid stays sharp.
        # (Antialiasing blurs the pixel boundaries, making it look like the large
        # "ghosted" letters vs. the crisp small fallback logo text.)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, False)
        
        x = 0
        logo_y = (self.ticker_height - logo_size) // 2
        text_y = (self.ticker_height + metrics.ascent() - metrics.descent()) // 2
        time_y = text_y
        record_y = None
        if show_records:
            line_gap = 0
            text_y = 4 + metrics.ascent()
            record_y = text_y + metrics.descent() + line_gap + small_metrics.ascent()
            max_record_y = self.ticker_height - 2 - small_metrics.descent()
            if record_y > max_record_y:
                delta = record_y - max_record_y
                text_y -= delta
                record_y -= delta
        time_y = text_y
        
        if status in ['In Progress', 'Live', 'Final', 'Completed', 'Game Over']:
            # Away team name (colored)
            painter.setFont(self.font)
            painter.setPen(away_color)
            away_name_x = x + (away_block_width - away_name_width) // 2
            painter.drawText(away_name_x, text_y, away_team)
            if show_records and record_y is not None:
                painter.setFont(self.small_font)
                painter.setPen(QtGui.QColor('#BDBDBD'))
                away_record_x = away_name_x + 3
                painter.drawText(away_record_x, record_y, away_detail_text)
            x += away_block_width + 5
            
            # Away team logo
            away_logo = get_team_logo(away_team_full, logo_size)
            painter.drawPixmap(x, logo_y, away_logo)
            x += logo_size + 15  # More space between logo and score
            
            # Away score (on same line as team name)
            painter.setFont(self.font)
            painter.setPen(QtGui.QColor('#FFFFFF'))
            score_width = metrics.horizontalAdvance(str(away_score))
            painter.drawText(x, text_y, str(away_score))
            x += score_width + 8
            
            # Diamond
            diamond_y = (self.ticker_height - int(diamond_pixmap.height() / self.dpr)) // 2 - 2
            painter.drawPixmap(x, diamond_y, diamond_pixmap)
            x += effective_after_diamond

            # Home score (on same line as team name)
            painter.setFont(self.font)
            painter.setPen(QtGui.QColor('#FFFFFF'))
            score_width = metrics.horizontalAdvance(str(home_score))
            painter.drawText(x, text_y, str(home_score))
            x += score_width + 15  # Mirror: logo→score gap on away side
            
            # Home logo
            home_logo = get_team_logo(home_team_full, logo_size)
            painter.drawPixmap(x, logo_y, home_logo)
            x += logo_size + 5  # Mirror: name→logo gap on away side
            
            # Home team name (colored)
            painter.setFont(self.font)
            painter.setPen(home_color)
            home_name_x = x + (home_block_width - home_name_width) // 2
            painter.drawText(home_name_x, text_y, home_team)
            if show_records and record_y is not None:
                painter.setFont(self.small_font)
                painter.setPen(QtGui.QColor('#BDBDBD'))
                home_record_x = home_name_x + home_name_width - home_record_width - 3
                painter.drawText(home_record_x, record_y, home_detail_text)
            
        else:
            # Away team name (colored)
            painter.setFont(self.font)
            painter.setPen(away_color)
            away_name_x = x + (away_block_width - away_name_width) // 2
            painter.drawText(away_name_x, text_y, away_team)
            if show_records and record_y is not None:
                painter.setFont(self.small_font)
                painter.setPen(QtGui.QColor('#BDBDBD'))
                away_record_x = away_name_x + 3
                painter.drawText(away_record_x, record_y, away_detail_text)
            x += away_block_width + 5
            
            # Away team logo
            away_logo = get_team_logo(away_team_full, logo_size)
            painter.drawPixmap(x, logo_y, away_logo)
            x += logo_size + 20  # 20px before @ for symmetric centering
            
            # vs.
            vs_metrics_paint = QtGui.QFontMetrics(self.vs_font)
            vs_y = text_y
            painter.setFont(self.vs_font)
            painter.setPen(QtGui.QColor("#FFFFFF"))
            painter.drawText(x, vs_y, "vs.")
            x += vs_metrics_paint.horizontalAdvance("vs.") + 15  # 15px after vs. (symmetric)
            
            # Home logo
            home_logo = get_team_logo(home_team_full, logo_size)
            painter.drawPixmap(x, logo_y, home_logo)
            x += logo_size + 10
            
            # Home team name (colored)
            painter.setFont(self.font)
            painter.setPen(home_color)
            home_name_x = x + (home_block_width - home_name_width) // 2
            painter.drawText(home_name_x, text_y, home_team)
            if show_records and record_y is not None:
                painter.setFont(self.small_font)
                painter.setPen(QtGui.QColor('#BDBDBD'))
                home_record_x = home_name_x + home_name_width - home_record_width - 3
                painter.drawText(home_record_x, record_y, home_detail_text)
            x += home_block_width + 10
            
            # Time/Final
            status_text = "FINAL" if status in ['Final', 'Completed', 'Game Over'] else ""
            if not status_text and 'game_datetime' in game:
                status_text = format_game_time_local(game.get('game_datetime'))
            
            painter.setFont(self.font)
            painter.setPen(QtGui.QColor('#00B3FF'))
            painter.setFont(self.time_font)
            painter.drawText(x, time_y, status_text)
        
        painter.end()
        return pixmap
    
    def update_scroll(self):
        """Advance scroll offset using real elapsed time (delta-time).

        Using actual milliseconds elapsed instead of a fixed per-tick step
        makes the scroll rate independent of Windows timer jitter, eliminating
        the periodic judder caused by ~15.6 ms timer resolution.
        """
        if not self.ticker_pixmap or self._scroll_max_width == 0:
            return

        now_ms = self._elapsed_timer.elapsed()
        delta_ms = now_ms - self._last_frame_ms
        self._last_frame_ms = now_ms

        # Clamp delta to avoid a large jump after a pause/hover resume
        delta_ms = min(delta_ms, 100)

        self.scroll_offset += self._scroll_speed_px_per_ms * delta_ms
        if self.scroll_offset >= self._scroll_max_width:
            self.scroll_offset = 0.0

        # FPS counter: update display value once per second
        self._fps_frame_count += 1
        elapsed_since = now_ms - self._fps_last_ms
        if elapsed_since >= 1000:
            self._fps_display = self._fps_frame_count * 1000.0 / elapsed_since
            self._fps_frame_count = 0
            self._fps_last_ms = now_ms

        self.update()
    
    def paintEvent(self, event):
        """Optimized paint event with cached backgrounds"""
        painter = QtGui.QPainter(self)
        # No Antialiasing/SmoothPixmapTransform: we're blitting pre-rendered
        # pixel-perfect HiDPI pixmaps — filtering adds GPU overhead for zero gain.

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
                # Blue-tinted near-black gradient matching the reference LED board look
                gradient = QtGui.QLinearGradient(0, 0, 0, self.height())
                gradient.setColorAt(0.0, QtGui.QColor(15, 18, 22, bg_opacity))
                gradient.setColorAt(0.35, QtGui.QColor(10, 12, 16, bg_opacity))
                gradient.setColorAt(0.65, QtGui.QColor(10, 12, 16, bg_opacity))
                gradient.setColorAt(1.0, QtGui.QColor(8, 10, 14, bg_opacity))
                bg_painter.fillRect(self.cached_background.rect(), gradient)

                # Horizontal scanlines — every other row slightly darker,
                # mimicking the gap between LED rows on a real board
                scan_color = QtGui.QColor(0, 0, 0, 55)
                for y in range(0, self.height(), 2):
                    bg_painter.fillRect(0, y, self.width(), 1, scan_color)
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
            painter.end()
            return

        # Normal ticker (may be None if first fetch hasn't completed yet)
        if not self.ticker_pixmap:
            painter.end()
            return

        # Draw scrolling ticker with optimized pixel positioning
        pixel_x = get_pixel_position(self.scroll_offset)
        painter.drawPixmap(-pixel_x, 0, self.ticker_pixmap)

        # Cache overlay if settings haven't changed
        if glass_overlay:
            if self.cached_overlay is None or self.last_height != self.height():
                self.cached_overlay = QtGui.QPixmap(self.width(), self.height())
                self.cached_overlay.fill(QtCore.Qt.transparent)

                overlay_painter = QtGui.QPainter(self.cached_overlay)
                # Glass glare — bright top sheen fading to transparent, matching reference
                overlay_gradient = QtGui.QLinearGradient(0, 0, 0, self.height())
                overlay_gradient.setColorAt(0.00, QtGui.QColor(255, 255, 255, 48))
                overlay_gradient.setColorAt(0.25, QtGui.QColor(255, 255, 255, 12))
                overlay_gradient.setColorAt(0.65, QtGui.QColor(255, 255, 255, 4))
                overlay_gradient.setColorAt(1.00, QtGui.QColor(255, 255, 255, 0))
                overlay_painter.fillRect(self.cached_overlay.rect(), overlay_gradient)
                # 1px top-edge highlight — simulates glass catching light at the bezel
                overlay_painter.fillRect(0, 2, self.width(), 1, QtGui.QColor(255, 255, 255, 55))
                overlay_painter.end()

                self.last_height = self.height()

            painter.drawPixmap(0, 0, self.cached_overlay)

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
            self._last_frame_ms = self._elapsed_timer.elapsed()  # reset baseline to avoid jump
            self.scroll_timer.start(16)  # Resume 60 FPS scrolling
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        """Keyboard shortcuts (active when ticker window has focus).
        Q   = quit app entirely
        S   = standings window
        .   = settings dialog
        R   = refresh data
        P   = pause/unpause scroll
        """
        key = event.text().lower()
        raw = event.text()
        if key == 'q':
            QtWidgets.QApplication.instance().quit()
        elif key == 's':
            if not hasattr(self, '_standings_win') or not self._standings_win.isVisible():
                self._standings_win = StandingsWindow()
                self._standings_win.show()
            else:
                self._standings_win.raise_()
                self._standings_win.activateWindow()
        elif raw == '.':
            SettingsDialog(self).exec_()
        elif key == 'r':
            self.start_data_fetch()
            print("[KB] Manual data refresh triggered")
        elif key == 'p':
            self.scroll_paused = not self.scroll_paused
            if self.scroll_paused:
                self.scroll_timer.stop()
                print("[KB] Scroll paused")
            else:
                if not self.intro_active and not self.is_hovered:
                    self._last_frame_ms = self._elapsed_timer.elapsed()
                    self.scroll_timer.start(16)
                print("[KB] Scroll unpaused")
        else:
            super().keyPressEvent(event)
    
    def closeEvent(self, event):
        """Cleanup on close"""
        # Stop all timers
        self.scroll_timer.stop()
        self.update_timer.stop()
        self.next_day_timer.stop()
        self.intro_timer.stop()
        
        # Clean up worker thread if running
        if self.data_worker and self.data_worker.isRunning():
            self.data_worker.quit()
            self.data_worker.wait()
        
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

        menu.addSeparator()

        pause_label = "Unpause Ticker" if self.scroll_paused else "Pause Ticker"
        pause_action = menu.addAction(pause_label)
        def _toggle_pause():
            self.scroll_paused = not self.scroll_paused
            if self.scroll_paused:
                self.scroll_timer.stop()
            else:
                if not self.intro_active and not self.is_hovered:
                    self._last_frame_ms = self._elapsed_timer.elapsed()
                    self.scroll_timer.start(16)
        pause_action.triggered.connect(_toggle_pause)

        menu.addSeparator()

        standings_action = menu.addAction("Standings...")
        def _open_standings():
            if not hasattr(self, '_standings_win') or \
                    self._standings_win is None or \
                    not self._standings_win.isVisible():
                self._standings_win = StandingsWindow()
                self._standings_win.show()
            else:
                self._standings_win.raise_()
                self._standings_win.activateWindow()
        standings_action.triggered.connect(_open_standings)

        menu.addSeparator()

        settings_action = menu.addAction("Settings...")
        settings_action.triggered.connect(lambda: SettingsDialog(self).exec_())

        menu.addSeparator()

        about_action = menu.addAction("About MLB-TCKR...")
        about_action.triggered.connect(lambda: AboutDialog(self).exec_())

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
        avail = QtWidgets.QApplication.primaryScreen().availableGeometry()
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

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowTitle("MLB Standings")

        self._league  = 'AL'
        self._data    = None
        self._loading = False

        self._scale = self._compute_scale()
        self._compute_sizes()
        self._build_ui()
        self._center_on_desktop()
        self._fetch()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

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

        self._al_lbl = QtWidgets.QLabel("American League")
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

        self._nl_lbl = QtWidgets.QLabel("National League")
        self._nl_lbl.setAlignment(QtCore.Qt.AlignCenter)
        self._nl_lbl.setFont(league_font)
        self._nl_lbl.setCursor(QtCore.Qt.PointingHandCursor)
        self._nl_lbl.setToolTip("Show NL Standings")
        self._nl_lbl.mousePressEvent = lambda _e: self._select_league('NL')

        league_row = QtWidgets.QHBoxLayout()
        league_row.setSpacing(0)
        league_row.addStretch()
        league_row.addWidget(self._al_lbl)
        league_row.addWidget(sep_lbl)
        league_row.addWidget(self._nl_lbl)
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

        for i, div in enumerate(self._DIVISIONS):
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(0)

            # Division title
            div_lbl = QtWidgets.QLabel(div)
            div_font = QtGui.QFont(self._ozone_family)
            div_font.setPixelSize(self._FS_DIV)
            div_lbl.setFont(div_font)
            div_lbl.setAlignment(QtCore.Qt.AlignCenter)
            div_lbl.setStyleSheet("color: #AAAAAA; padding-bottom: 8px;")
            div_lbl.setFixedWidth(self._div_width())
            col.addWidget(div_lbl)

            # Column header row
            col.addWidget(self._make_col_header())

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
        close_btn.clicked.connect(self.close)
        bottom.addWidget(close_btn)
        outer.addLayout(bottom)

    def _div_width(self):
        return self._W_LOGO + self._W_NAME + self._W_WL + self._W_PCT + self._W_L10

    def _make_col_header(self):
        """Return a fixed-width header row widget matching team row cell widths."""
        row = QtWidgets.QWidget()
        row.setFixedWidth(self._div_width())
        row.setFixedHeight(self._ROW_H)
        row.setStyleSheet("background: transparent;")
        hl = QtWidgets.QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        hdr_font = QtGui.QFont(self._record_family)
        hdr_font.setPixelSize(self._FS_HDR)

        # Logo placeholder
        spacer = QtWidgets.QLabel()
        spacer.setFixedWidth(self._W_LOGO)
        hl.addWidget(spacer)

        for label, width in [("Team", self._W_NAME),
                              ("W-L",  self._W_WL),
                              ("Pct.", self._W_PCT),
                              ("L10",  self._W_L10)]:
            lbl = QtWidgets.QLabel(label)
            lbl.setFont(hdr_font)
            lbl.setFixedWidth(width)
            lbl.setFixedHeight(self._ROW_H)
            lbl.setStyleSheet("color: #888888;")
            if label == "Team":
                lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            else:
                lbl.setAlignment(QtCore.Qt.AlignCenter)
            hl.addWidget(lbl)
        return row

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
        self._center_on_desktop()

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
                row_widget.setStyleSheet(
                    "background: rgba(255,255,255,35);" if rank % 2 == 0
                    else "background: rgba(255,255,255,10);"
                )
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

                # Team name
                name_lbl = QtWidgets.QLabel(team['name'])
                name_lbl.setFont(name_font)
                name_lbl.setFixedWidth(self._W_NAME)
                name_lbl.setFixedHeight(self._ROW_H)
                color = get_team_color(team['full_name'])
                name_lbl.setStyleSheet(f"color: {color};")
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
        pad_top = max(2, int(4  * self._scale))
        pad_bot = max(6, int(18 * self._scale))
        self._al_lbl.setStyleSheet(f"color: {al_color}; padding: {pad_top}px 0 {pad_bot}px 0;")
        self._nl_lbl.setStyleSheet(f"color: {nl_color}; padding: {pad_top}px 0 {pad_bot}px 0;")
        if hasattr(self, '_header_sep'):
            self._header_sep.setStyleSheet(
                f"color: {sep_color}; background: {sep_color}; max-height: 2px;"
            )

    def _select_league(self, league):
        if self._league == league:
            return
        self._league = league
        self._update_header_colors()
        if self._data:
            self._populate()


    def _center_on_desktop(self):
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        x = screen.x() + (screen.width()  - self.width())  // 2
        y = screen.y() + (screen.height() - self.height()) // 2
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
        outer.addWidget(_lbl("MLB-TCKR", 52, "#FFFFFF", bold=True, bot_pad=4))

        # Version
        outer.addWidget(_lbl("Version 0.9 Beta", 22, "#AAAAAA", bot_pad=14))

        # Green rule
        rule = QtWidgets.QFrame()
        rule.setFrameShape(QtWidgets.QFrame.HLine)
        rule.setStyleSheet("background: #00FF44; max-height: 2px;")
        outer.addWidget(rule)
        outer.addSpacing(14)

        # Credits block
        outer.addWidget(_lbl("Created by: Paul R. Charovkine",  20, "#DDDDDD", bot_pad=4,  family=record_family))
        outer.addWidget(_lbl("Copyright \u00a9 2026 — All Rights Reserved", 18, "#AAAAAA", bot_pad=4,  family=record_family))
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
        url_lbl.setStyleSheet("padding-bottom: 14px;")
        outer.addWidget(url_lbl)

        # Second rule
        rule2 = QtWidgets.QFrame()
        rule2.setFrameShape(QtWidgets.QFrame.HLine)
        rule2.setStyleSheet("background: #333333; max-height: 1px;")
        outer.addWidget(rule2)
        outer.addSpacing(12)

        # Disclaimer
        outer.addWidget(_lbl(
            "Major League Baseball trademarks, team names, logos, and related marks\n"
            "are the property of their respective owners.\n"
            "MLB-TCKR is an independent fan project and is not affiliated\n"
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
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

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


class SettingsDialog(QtWidgets.QDialog):
    """Settings dialog with tabs for team colors and general settings"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MLB Ticker Settings")
        self.setMinimumSize(600, 500)
        
        # Load current settings
        self.settings = get_settings()
        
        # Create tab widget
        tabs = QtWidgets.QTabWidget()
        
        # General settings tab
        general_tab = self.create_general_tab()
        tabs.addTab(general_tab, "General")
        
        # Team colors tab
        colors_tab = self.create_team_colors_tab()
        tabs.addTab(colors_tab, "Team Colors")

        # Network / proxy tab
        network_tab = self.create_network_tab()
        tabs.addTab(network_tab, "Network")
        
        # Buttons
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.save_and_close)
        button_box.rejected.connect(self.reject)
        
        # Layout
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(tabs)
        layout.addWidget(button_box)
        self.setLayout(layout)
    
    def create_general_tab(self):
        """Create general settings tab"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout()
        
        # Speed
        self.speed_spin = QtWidgets.QSpinBox()
        self.speed_spin.setRange(1, 10)
        self.speed_spin.setValue(self.settings.get('speed', 2))
        layout.addRow("Ticker Speed:", self.speed_spin)
        
        # Update interval
        self.update_spin = QtWidgets.QSpinBox()
        self.update_spin.setRange(5, 300)
        self.update_spin.setValue(self.settings.get('update_interval', 10))
        self.update_spin.setSuffix(" seconds")
        layout.addRow("Update Interval:", self.update_spin)
        
        # Ticker height
        self.height_spin = QtWidgets.QSpinBox()
        self.height_spin.setRange(40, 200)
        self.height_spin.setValue(self.settings.get('ticker_height', 60))
        self.height_spin.setSuffix(" pixels")
        layout.addRow("Ticker Height:", self.height_spin)
        
        # Font selection – populate from all installed fonts
        self.font_combo = QtWidgets.QComboBox()
        self.font_combo.setMaxVisibleItems(20)
        db = QtGui.QFontDatabase()
        all_fonts = sorted(db.families(), key=lambda f: f.lstrip('@').lower())
        # Ensure the custom LED font (if loaded) appears even if not yet in families
        led_font = 'LED Board-7'
        if led_font not in all_fonts:
            all_fonts.insert(0, led_font)
        self.font_combo.addItems(all_fonts)
        current_font = self.settings.get('font', led_font)
        index = self.font_combo.findText(current_font)
        if index >= 0:
            self.font_combo.setCurrentIndex(index)
        else:
            self.font_combo.setCurrentIndex(0)
        # Render each item in the dropdown in its own typeface
        self.font_combo.setItemDelegate(FontPreviewDelegate(self.font_combo))
        self.font_combo.setMinimumHeight(32)
        self.font_combo.setFont(QtGui.QFont(current_font, 13))
        self.font_combo.currentTextChanged.connect(
            lambda f: self.font_combo.setFont(QtGui.QFont(f, 13))
        )
        layout.addRow("Font:", self.font_combo)

        # Font size scale (percent)
        self.font_scale_spin = QtWidgets.QSpinBox()
        self.font_scale_spin.setRange(80, 200)
        self.font_scale_spin.setValue(self.settings.get('font_scale_percent', 120))
        self.font_scale_spin.setSuffix("%")
        self.font_scale_spin.setToolTip("Scale ticker text size without changing logo size")
        layout.addRow("Font Size Scale:", self.font_scale_spin)

        # Show team records
        self.records_check = QtWidgets.QCheckBox()
        self.records_check.setChecked(self.settings.get('show_team_records', True))
        layout.addRow("Show Team Records (W-L):", self.records_check)
        
        # Include final games
        self.final_check = QtWidgets.QCheckBox()
        self.final_check.setChecked(self.settings.get('include_final_games', True))
        layout.addRow("Include Final Games:", self.final_check)
        
        # Include scheduled games
        self.scheduled_check = QtWidgets.QCheckBox()
        self.scheduled_check.setChecked(self.settings.get('include_scheduled_games', True))
        layout.addRow("Include Scheduled Games:", self.scheduled_check)
        
        # Show team cities
        self.cities_check = QtWidgets.QCheckBox()
        self.cities_check.setChecked(self.settings.get('show_team_cities', True))
        layout.addRow("Show Team Cities:", self.cities_check)
        
        # LED Background
        self.led_bg_check = QtWidgets.QCheckBox()
        self.led_bg_check.setChecked(self.settings.get('led_background', True))
        layout.addRow("LED-Style Background:", self.led_bg_check)
        
        # Glass Overlay
        self.glass_check = QtWidgets.QCheckBox()
        self.glass_check.setChecked(self.settings.get('glass_overlay', True))
        layout.addRow("Glass Overlay Effect:", self.glass_check)
        
        # Background Opacity
        self.opacity_spin = QtWidgets.QSpinBox()
        self.opacity_spin.setRange(0, 255)
        self.opacity_spin.setValue(self.settings.get('background_opacity', 230))
        self.opacity_spin.setToolTip("0 = Fully Transparent, 255 = Fully Opaque")
        layout.addRow("Background Opacity:", self.opacity_spin)

        # FPS Overlay
        self.fps_check = QtWidgets.QCheckBox()
        self.fps_check.setChecked(self.settings.get('show_fps_overlay', False))
        layout.addRow("Show FPS Overlay:", self.fps_check)

        # Display selection
        self.monitor_combo = QtWidgets.QComboBox()
        _all_screens = QtWidgets.QApplication.screens()
        for _i, _s in enumerate(_all_screens):
            _g = _s.geometry()
            _label = f"Display {_i + 1}: {_s.name()}  ({_g.width()}\u00d7{_g.height()})"
            self.monitor_combo.addItem(_label)
        _saved_mon = min(self.settings.get('monitor_index', 0), max(0, len(_all_screens) - 1))
        self.monitor_combo.setCurrentIndex(_saved_mon)
        layout.addRow("Display:", self.monitor_combo)

        widget.setLayout(layout)
        return widget

    def create_team_colors_tab(self):
        """Create team colors customization tab"""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        
        # Info label
        info = QtWidgets.QLabel(
            "Customize team colors for the ticker display. "
            "Leave empty to use default MLB colors."
        )
        info.setWordWrap(True)
        info.setStyleSheet("padding: 5px; background: #f0f0f0; border: 1px solid #ccc;")
        layout.addWidget(info)
        
        # Reset button
        reset_btn = QtWidgets.QPushButton("Reset All to Defaults")
        reset_btn.clicked.connect(self.reset_team_colors)
        layout.addWidget(reset_btn)
        
        # Scroll area for team colors
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        
        colors_widget = QtWidgets.QWidget()
        colors_layout = QtWidgets.QFormLayout()
        colors_layout.setSpacing(5)
        
        # Get current custom colors
        custom_colors = self.settings.get('team_colors', {})
        
        # Create color picker for each team
        self.color_buttons = {}
        teams = sorted(MLB_TEAM_COLORS_DEFAULT.keys())
        
        for team in teams:
            # Get current color (custom or default)
            current_color = custom_colors.get(team, MLB_TEAM_COLORS_DEFAULT[team])
            
            # Color button
            color_btn = QtWidgets.QPushButton()
            color_btn.setFixedSize(60, 25)
            color_btn.setStyleSheet(f"background-color: {current_color}; border: 1px solid #000;")
            color_btn.clicked.connect(lambda checked, t=team: self.pick_team_color(t))
            
            # Hex input
            hex_input = QtWidgets.QLineEdit(current_color)
            hex_input.setMaxLength(7)
            hex_input.setFixedWidth(80)
            hex_input.textChanged.connect(lambda text, t=team: self.update_team_color_preview(t, text))
            
            # Default color label
            default_label = QtWidgets.QLabel(f"(Default: {MLB_TEAM_COLORS_DEFAULT[team]})")
            default_label.setStyleSheet("color: #666; font-size: 9px;")
            
            # Horizontal layout for color controls
            h_layout = QtWidgets.QHBoxLayout()
            h_layout.addWidget(color_btn)
            h_layout.addWidget(hex_input)
            h_layout.addWidget(default_label)
            h_layout.addStretch()
            
            colors_layout.addRow(f"{team}:", h_layout)
            
            # Store references
            self.color_buttons[team] = {
                'button': color_btn,
                'input': hex_input,
                'color': current_color
            }
        
        colors_widget.setLayout(colors_layout)
        scroll.setWidget(colors_widget)
        layout.addWidget(scroll)
        
        widget.setLayout(layout)
        return widget
    
    def pick_team_color(self, team):
        """Open color picker for a team"""
        current_color = self.color_buttons[team]['color']
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(current_color),
            self,
            f"Choose color for {team}"
        )
        
        if color.isValid():
            hex_color = color.name()
            self.color_buttons[team]['color'] = hex_color
            self.color_buttons[team]['input'].setText(hex_color)
            self.color_buttons[team]['button'].setStyleSheet(
                f"background-color: {hex_color}; border: 1px solid #000;"
            )
    
    def update_team_color_preview(self, team, hex_color):
        """Update color preview when hex input changes"""
        if hex_color.startswith('#') and len(hex_color) == 7:
            try:
                QtGui.QColor(hex_color)  # Validate
                self.color_buttons[team]['color'] = hex_color
                self.color_buttons[team]['button'].setStyleSheet(
                    f"background-color: {hex_color}; border: 1px solid #000;"
                )
            except:
                pass
    
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
                default_color = MLB_TEAM_COLORS_DEFAULT[team]
                widgets['color'] = default_color
                widgets['input'].setText(default_color)
                widgets['button'].setStyleSheet(
                    f"background-color: {default_color}; border: 1px solid #000;"
                )
    
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

    def save_and_close(self):
        """Save settings and close dialog"""
        # General settings
        self.settings['speed'] = self.speed_spin.value()
        self.settings['update_interval'] = self.update_spin.value()
        self.settings['ticker_height'] = self.height_spin.value()
        self.settings['font'] = self.font_combo.currentText()
        self.settings['font_scale_percent'] = self.font_scale_spin.value()
        self.settings['show_team_records'] = self.records_check.isChecked()
        self.settings['include_final_games'] = self.final_check.isChecked()
        self.settings['include_scheduled_games'] = self.scheduled_check.isChecked()
        self.settings['show_team_cities'] = self.cities_check.isChecked()
        self.settings['led_background'] = self.led_bg_check.isChecked()
        self.settings['glass_overlay'] = self.glass_check.isChecked()
        self.settings['background_opacity'] = self.opacity_spin.value()
        self.settings['show_fps_overlay'] = self.fps_check.isChecked()
        self.settings['monitor_index'] = self.monitor_combo.currentIndex()

        # Network / proxy settings
        self.settings['use_proxy'] = self.use_proxy_check.isChecked()
        self.settings['proxy'] = self.proxy_url_edit.text().strip()
        self.settings['use_cert'] = self.use_cert_check.isChecked()
        self.settings['cert_file'] = self.cert_file_edit.text().strip()
        
        # Team colors
        team_colors = {}
        for team, widgets in self.color_buttons.items():
            color = widgets['color']
            # Only save if different from default
            if color != MLB_TEAM_COLORS_DEFAULT[team]:
                team_colors[team] = color
        
        self.settings['team_colors'] = team_colors
        
        # Save to file
        save_settings(self.settings)

        # Apply proxy settings immediately so subsequent fetches use the new config
        apply_proxy_settings()
        
        # Notify user
        QtWidgets.QMessageBox.information(
            self,
            "Settings Saved",
            "Settings saved successfully! Restart the ticker for changes to take effect."
        )
        
        self.accept()


def main():
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
    settings_action.triggered.connect(lambda: SettingsDialog(window).exec_())
    
    tray_menu.addSeparator()
    
    quit_action = tray_menu.addAction("Quit")
    quit_action.triggered.connect(app.quit)
    
    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()
    tray_icon.setToolTip("MLB Ticker")
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
