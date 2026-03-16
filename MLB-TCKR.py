"""
Author: Paul R. Charovkine
Program: MLB-TCKR.py
Date: 2026.03.14
Version: 2.0.0
License: GNU AGPLv3

Description:
MLB ticker application that displays live baseball game data in a scrolling ticker bar.
Shows team logos, scores, runners on base, outs, innings, and game times just like a
traditional LED sports ticker. Integrates with Windows AppBar for persistent display.
"""

import sys
import os
import json
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
except ImportError:
    CYTHON_AVAILABLE = False
    print("[MLB-PERF] Cython not available, using Python scrolling")
    
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
ABM_NEW = 0x00000000
ABM_REMOVE = 0x00000001
ABM_QUERYPOS = 0x00000002
ABM_SETPOS = 0x00000003
ABM_ACTIVATE = 0x00000006
ABE_TOP = 1

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
        "team_colors": {}  # Custom team colors (empty = use defaults)
    }


def save_settings(settings):
    os.makedirs(APPDATA_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)


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


def load_custom_font():
    """Load the LED board font from TTF file"""
    # Try multiple locations for the font file
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
                    return font_families[0]
    
    print("[FONT] LED board font not found, using Arial fallback")
    return "Arial"


def load_record_font_family():
    """Load PixelFont7 font for W-L line and return its family name."""
    target_family = "PixelFont7-G02A"
    db = QtGui.QFontDatabase()
    if target_family in db.families():
        return target_family

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
                    return families[0]

    print("[FONT] PixelFont7-G02A.ttf not found, using ticker font for records")
    return None


def load_ozone_font():
    """Load Ozone-xRRO.ttf and return its font family name."""
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
                    return families[0]
    print("[FONT] Ozone-xRRO.ttf not found, falling back to ticker font")
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
        return full_name.split()[-1]

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
    total_width = size + 14  # Right gutter for inning indicator
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
    
    painter.end()
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
        
        # Background data fetching
        self.data_worker = None
        self.is_fetching = False
        self.waiting_for_next_day = False
        self.last_fetch_date = None

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
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, False)
        
        # Enable mouse tracking for hover-to-pause functionality
        self.setMouseTracking(True)
        
        # Size and position
        screen = QtWidgets.QApplication.primaryScreen().geometry()
        self.ticker_height = self.settings.get('ticker_height', 60)
        self.setGeometry(0, 0, screen.width(), self.ticker_height)
        
        # Device pixel ratio – needed to create off-screen pixmaps at native
        # physical resolution so the compositor doesn't have to upscale them
        # (upscaling is what makes the font look blurry/compressed vs the preview).
        self.dpr = QtWidgets.QApplication.primaryScreen().devicePixelRatio()

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
        self.small_font.setPixelSize(max(6, int(self.ticker_height * 0.22 * font_scale * 0.5)) + 2)
        self.time_font = QtGui.QFont(font_to_use)
        self.time_font.setPixelSize(max(6, int(self.ticker_height * 0.35 * font_scale * 0.6)))
        
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

        SHAppBarMessage works in *physical* pixels (device pixels), while Qt
        geometry and self.ticker_height are in *logical* pixels.  We must scale
        up by the device pixel ratio before handing values to Win32, then scale
        back down when calling setGeometry so Qt positions the window correctly
        at every DPI / display-scale setting (100 %, 125 %, 150 %, 200 % …).
        """
        if sys.platform != "win32":
            return

        shell32 = ctypes.windll.shell32

        hwnd = int(self.winId())
        screen = QtWidgets.QApplication.primaryScreen()
        dpr = screen.devicePixelRatio()  # e.g. 1.25 at 125 % scaling

        # Physical (device) dimensions — what Win32 actually sees
        phys_width  = int(screen.geometry().width()  * dpr)
        phys_height = int(self.ticker_height * dpr)

        abd = APPBARDATA()
        abd.cbSize = ctypes.sizeof(APPBARDATA)
        abd.hWnd = hwnd
        abd.uEdge = ABE_TOP
        abd.rc.left  = 0
        abd.rc.top   = 0
        abd.rc.right = phys_width
        abd.rc.bottom = phys_height

        # Step 1: Register the appbar
        shell32.SHAppBarMessage(ABM_NEW, ctypes.byref(abd))

        # Step 2: Ask Windows where it wants us (respects taskbar / other bars)
        shell32.SHAppBarMessage(ABM_QUERYPOS, ctypes.byref(abd))

        # Step 3: Clamp bottom to exactly our desired physical height
        abd.rc.bottom = abd.rc.top + phys_height

        # Step 4: Commit — reserves the working area so windows won't overlap
        shell32.SHAppBarMessage(ABM_SETPOS, ctypes.byref(abd))

        # Step 5: Move/size the Qt window using *logical* pixels
        self.setGeometry(
            int(abd.rc.left   / dpr),
            int(abd.rc.top    / dpr),
            int((abd.rc.right  - abd.rc.left) / dpr),
            int((abd.rc.bottom - abd.rc.top)  / dpr),
        )

        # Step 6: Notify shell the bar is active
        shell32.SHAppBarMessage(ABM_ACTIVATE, ctypes.byref(abd))

        print(f"[AppBar] Registered — DPR={dpr}, "
              f"phys rect=({abd.rc.left},{abd.rc.top},{abd.rc.right},{abd.rc.bottom}), "
              f"logical height={int((abd.rc.bottom - abd.rc.top) / dpr)}px")
    
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
        self.build_ticker_pixmap()

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
        p.drawText(start_x + logo_w + (gap if logo_pm else 0), text_y, text)
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
                # Kick off normal scrolling now that intro is finished
                self.scroll_timer.start(16)
                print("[INTRO] Complete — starting ticker scroll from off-screen right")

        self.update()

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
        
        for game in self.games:
            pixmap = self.build_game_pixmap(game)
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
        """Load mlb.png scaled to logo_size logical pixels tall, DPR-aware."""
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
                    return scaled
        print("[TICKER] mlb.png not found in images dirs")
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

            # Layout: Team, Logo, Score, Diamond, Score, Logo, Team
            # Gaps mirror each other: name(5)logo(15)score(8)diamond(2)score(15)logo(5)name
            total_width = (away_block_width + 5 + logo_size + 15 + 
                          score_width + 8 + diamond_logical_width + 2 + 
                          score_width + 15 + logo_size + 5 + home_block_width)
        else:
            # Scheduled games only: Team Logo @ Logo Team Time
            status_text = format_game_time_local(game.get('game_datetime'))
            
            status_width = time_metrics.horizontalAdvance(status_text) + 20
            at_width = metrics.horizontalAdvance("@") + 10
            
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
            x += diamond_logical_width + 2  # Tight gap to home score
            
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
            
            # @
            painter.setFont(self.font)
            painter.setPen(QtGui.QColor("#B1ABAB"))
            painter.drawText(x, text_y, "@")
            x += metrics.horizontalAdvance("@") + 15  # 15px after @ (symmetric)
            
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
        """Update scroll position with Cython-optimized smooth scrolling"""
        if not self.ticker_pixmap:
            return
        
        # Use optimized scroll calculation
        speed = self.settings.get('speed', 2)
        adjusted_speed = adjust_speed_for_framerate(speed, 60, 30)
        # ticker_pixmap.width() is physical pixels; convert to logical for scroll range
        max_width = (self.ticker_pixmap.width() / self.dpr) / 2.0
        
        self.scroll_offset = calculate_smooth_scroll(
            self.scroll_offset, 
            adjusted_speed, 
            max_width
        )
        
        self.update()
    
    def paintEvent(self, event):
        """Optimized paint event with cached backgrounds"""
        painter = QtGui.QPainter(self)
        # Use SmoothPixmapTransform for better quality at sub-pixel positions
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        # Always draw the dark background first so the bar is never transparent/white
        settings = get_settings()
        led_background = settings.get('led_background', True)
        glass_overlay = settings.get('glass_overlay', True)
        bg_opacity = settings.get('background_opacity', 230)

        current_settings = {'led': led_background, 'opacity': bg_opacity, 'height': self.height()}
        if self.cached_background is None or self.last_bg_settings != current_settings:
            self.cached_background = QtGui.QPixmap(self.width(), self.height())
            self.cached_background.fill(QtCore.Qt.transparent)

            bg_painter = QtGui.QPainter(self.cached_background)
            if led_background:
                # Deep near-black gradient — dark charcoal at edges, true black center
                gradient = QtGui.QLinearGradient(0, 0, 0, self.height())
                gradient.setColorAt(0.0, QtGui.QColor(8, 8, 8, bg_opacity))
                gradient.setColorAt(0.35, QtGui.QColor(0, 0, 0, bg_opacity))
                gradient.setColorAt(0.65, QtGui.QColor(0, 0, 0, bg_opacity))
                gradient.setColorAt(1.0, QtGui.QColor(8, 8, 8, bg_opacity))
                bg_painter.fillRect(self.cached_background.rect(), gradient)

                # Horizontal scanlines — every other row is slightly darker,
                # mimicking the gap between LED rows on a real board
                scan_color = QtGui.QColor(0, 0, 0, 55)
                for y in range(0, self.height(), 2):
                    bg_painter.fillRect(0, y, self.width(), 1, scan_color)
            else:
                bg_painter.fillRect(self.cached_background.rect(), QtGui.QColor(0, 0, 0, bg_opacity))
            bg_painter.end()

            self.last_bg_settings = current_settings

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
                overlay_gradient = QtGui.QLinearGradient(0, 0, 0, self.height())
                # Very subtle edge-only sheen — keeps the LED look without lightening
                overlay_gradient.setColorAt(0.0, QtGui.QColor(255, 255, 255, 8))
                overlay_gradient.setColorAt(0.15, QtGui.QColor(255, 255, 255, 3))
                overlay_gradient.setColorAt(0.5, QtGui.QColor(0, 0, 0, 0))
                overlay_gradient.setColorAt(0.85, QtGui.QColor(0, 0, 0, 3))
                overlay_gradient.setColorAt(1.0, QtGui.QColor(0, 0, 0, 6))
                overlay_painter.fillRect(self.cached_overlay.rect(), overlay_gradient)
                overlay_painter.end()

                self.last_height = self.height()

            painter.drawPixmap(0, 0, self.cached_overlay)

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
        
        # Unregister AppBar
        if sys.platform == "win32":
            shell32 = ctypes.windll.shell32
            abd = APPBARDATA()
            abd.cbSize = ctypes.sizeof(APPBARDATA)
            abd.hWnd = int(self.winId())
            shell32.SHAppBarMessage(ABM_REMOVE, ctypes.byref(abd))
        
        event.accept()


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
# Standings window
# ---------------------------------------------------------------------------

class StandingsWindow(QtWidgets.QWidget):
    """Full standings window with LED-style background.

    Displays AL or NL standings in three division columns (East / Central / West).
    Clicking the league header toggles between AL and NL.
    Data is fetched on demand in a background thread.
    """

    _DIVISIONS = ['East', 'Central', 'West']

    # Fixed pixel widths for every cell — guarantees perfect table alignment
    _W_LOGO = 44    # logo square
    _W_NAME = 160   # team nickname
    _W_WL   = 90    # W-L
    _W_PCT  = 90    # Pct.
    _W_L10  = 90    # L10
    _ROW_H  = 40    # row height

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint |
                         QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowTitle("MLB Standings")

        self._league  = 'AL'
        self._data    = None
        self._loading = False

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
        outer.setContentsMargins(28, 20, 28, 20)
        outer.setSpacing(0)

        # ── Header ────────────────────────────────────────────────
        title_font = QtGui.QFont(self._ozone_family)
        title_font.setPixelSize(64)
        title_lbl = QtWidgets.QLabel("STANDINGS")
        title_lbl.setAlignment(QtCore.Qt.AlignCenter)
        title_lbl.setFont(title_font)
        title_lbl.setStyleSheet("color: #FFFFFF; padding: 10px 0 4px 0;")
        outer.addWidget(title_lbl)

        league_font = QtGui.QFont(self._ozone_family)
        league_font.setPixelSize(40)

        self._al_lbl = QtWidgets.QLabel("American League")
        self._al_lbl.setAlignment(QtCore.Qt.AlignCenter)
        self._al_lbl.setFont(league_font)
        self._al_lbl.setCursor(QtCore.Qt.PointingHandCursor)
        self._al_lbl.setToolTip("Show AL Standings")
        self._al_lbl.mousePressEvent = lambda _e: self._select_league('AL')

        sep_lbl = QtWidgets.QLabel("  |  ")
        sep_lbl.setAlignment(QtCore.Qt.AlignCenter)
        sep_lbl.setFont(league_font)
        sep_lbl.setStyleSheet("color: #444444; padding: 4px 0 18px 0;")

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

        # Thin gold divider under header
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.HLine)
        sep.setStyleSheet("color: #00FF44; background: #00FF44; max-height: 2px;")
        outer.addWidget(sep)
        outer.addSpacing(16)

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
            div_font.setPixelSize(36)
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
                vsep.setStyleSheet(
                    "color: #555; background: #555; max-width: 2px; margin: 0 16px;"
                )
                cols_row.addWidget(vsep)

        outer.addLayout(cols_row)
        outer.addSpacing(20)

        # ── Loading indicator ─────────────────────────────────────────
        self._loading_lbl = QtWidgets.QLabel("Loading…")
        loading_font = QtGui.QFont(self._ozone_family)
        loading_font.setPixelSize(40)
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
        close_btn_font.setPixelSize(26)
        close_btn.setFont(close_btn_font)
        close_btn.setFixedSize(160, 52)
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
        hdr_font.setPixelSize(26)

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
        name_font.setPixelSize(30)
        stat_font = QtGui.QFont(self._record_family)
        stat_font.setPixelSize(26)

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
                    "background: rgba(255,255,255,12);" if rank % 2 == 0
                    else "background: transparent;"
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
        al_color = "#FF2222" if self._league == 'AL' else "#555555"
        nl_color = "#2266FF" if self._league == 'NL' else "#555555"
        self._al_lbl.setStyleSheet(f"color: {al_color}; padding: 4px 0 18px 0;")
        self._nl_lbl.setStyleSheet(f"color: {nl_color}; padding: 4px 0 18px 0;")

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
        painter.setPen(QtGui.QPen(QtGui.QColor('#00FF44'), 1.5))
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


class _StandingsWorker(QtCore.QThread):
    done = QtCore.pyqtSignal(object)

    def run(self):
        data = fetch_standings()
        self.done.emit(data)


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
    standings_win = [None]  # mutable container so lambda can replace it

    def open_standings():
        if standings_win[0] is None or not standings_win[0].isVisible():
            standings_win[0] = StandingsWindow()
            standings_win[0].show()
        else:
            standings_win[0].raise_()
            standings_win[0].activateWindow()

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
