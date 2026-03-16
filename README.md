# MLB-TCKR

**Professional MLB Live Game Ticker for Windows**

A sleek, performant scrolling ticker that displays live Major League Baseball game data at the top of your screen - just like the tickers you see on sports networks and in sports bars.

![Version](https://img.shields.io/badge/version-2.2.0-blue)
![Python](https://img.shields.io/badge/python-3.13-green)
![License](https://img.shields.io/badge/license-GNU%20AGPLv3-red)

---

## Features

### 🎯 Live Game Data
- **Real-time scores** from MLB-StatsAPI
- **Runners on base** displayed as bright green diamonds
- **Outs count** shown as bright red circles
- **Inning indicator** with Top/Bottom format (T5, B5) or Final (F)
- **Team logos** for all 30 MLB teams
- **Official team colors** with custom override support

### ⚡ Performance Optimized
- **60 FPS rendering** for silky smooth scrolling
- **Sub-pixel accuracy** eliminates visible stepping
- **Background threading** prevents interruptions during data fetches
- **Intelligent polling** stops when games finish, resumes next day
- **Cached rendering** reduces CPU usage by 40%
- **Optional Cython optimization** for maximum performance
- **Hardware acceleration** with SmoothPixmapTransform

### 📊 Standings Window
- **Full AL/NL standings** in a sleek LED-style popup window
- **"STANDINGS" header** in bright white with league selector below
- **American League** (bright red) and **National League** (bright blue) — click to switch
- **Three division columns** (East / Central / West) with fixed-width table alignment
- **Per-team rows**: logo, colored nickname, W-L, Pct., Last 10
- **Background fetch** — non-blocking, loads while window is open
- **Draggable**, frameless, always-on-top; auto-centers on screen
- Access via system tray → **Standings...** or press **S**

### ⌨️ Keyboard Shortcuts
| Key | Action |
|-----|--------|
| `S` | Open Standings window |
| `.` | Open Settings dialog |
| `R` | Force data refresh |
| `P` | Pause / unpause scroll |
| `Q` | Quit application |

### 🎨 Customizable Appearance
- **LED-style gradient background** with glass overlay effect
- **Adjustable transparency** (0-255 opacity)
- **Custom team colors** - override any team's color
- **Multiple font options** with live in-dropdown preview (each name shown in its own typeface)
- **Configurable ticker height** (40-200 pixels)
- **Hover-to-pause** - ticker pauses when mouse is over it
- **Startup intro animation** - pixel-reveal block effect with MLB logo and app name

### ⚙️ Flexible Configuration
- **Scroll speed control** (1-10)
- **Update interval** (5-300 seconds)
- **Toggle display options**:
  - Team records (W-L)
  - Team cities vs nicknames only
  - Final games
  - Scheduled games
- **Settings persist** across sessions

### 🖥️ Windows Integration
- **AppBar integration** - docks persistently at top of screen, DPI-aware (works at 100 %, 125 %, 150 %, 200 % display scaling)
- **System tray icon** with quick access menu
- **Stays on top** of all windows
- **Transparent background** blends with desktop

---

## Requirements

- **Operating System**: Windows 10/11
- **Python**: 3.13 (recommended)
  - Path: `C:\Users\prc\AppData\Local\Programs\Python\Python313\python.exe`
- **Dependencies**:
  - `statsapi` - MLB game data
  - `PyQt5` - GUI framework
  - `Cython` (optional) - performance optimizations

---

## Installation

### 1. Clone or Download
```bash
git clone https://github.com/yourusername/MLB-TCKR.git
cd MLB-TCKR
```

### 2. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 3. Setup Assets
The ticker automatically creates directories in `%APPDATA%\MLB-TCKR\`:
- `MLB-TCKR.images\` - Place team logo PNG files here (e.g., `yankees.png`, `dodgers.png`)
- `led_board-7.ttf` - Custom LED font (optional)
- `mlb.png` - System tray icon (optional)
- `MLB-TCKR.Settings.json` - Auto-generated settings file

### 4. Run
```powershell
python MLB-TCKR.py
```

---

## Performance Build (Optional)

For maximum smoothness, compile the Cython optimizations:

```powershell
.\build_performance.bat
```

This enables:
- `calculate_smooth_scroll()` - Optimized scroll calculations
- `get_pixel_position()` - Fast float-to-int conversion
- `adjust_speed_for_framerate()` - FPS-aware speed scaling

The application automatically falls back to Python if Cython modules aren't available.

---

## Usage

### System Tray Menu
Right-click the system tray icon to access:
- **Refresh Games** - Force immediate data update
- **Standings...** - Open standings window
- **Settings** - Open settings dialog
- **Quit** - Exit the ticker

### Keyboard Shortcuts
Click the ticker bar to give it focus, then:
- **S** — Open Standings window
- **.** — Open Settings dialog
- **R** — Force data refresh
- **P** — Pause / unpause scrolling
- **Q** — Quit application

### Settings Dialog

#### General Tab
- **Ticker Speed** - How fast the content scrolls (1-10)
- **Update Interval** - Frequency of API calls (5-300 seconds)
- **Ticker Height** - Vertical size in pixels (40-200)
- **Font** - Choose from available fonts
- **Display Options**:
  - Show Team Records (W-L)
  - Show Team Cities
  - Include Final Games
  - Include Scheduled Games
- **Visual Effects**:
  - LED-Style Background
  - Glass Overlay Effect
  - Background Opacity (0-255)

#### Team Colors Tab
- Customize the color for any team
- Color picker or hex input (#RRGGBB)
- Reset to MLB official colors anytime
- Only modified colors are saved

---

## Project Structure

```
MLB-TCKR/
│
├── MLB-TCKR.py                    # Main application (v2.0.0)
├── mlb_ticker_utils_cython.pyx    # Cython optimizations
├── setup_mlb_cython.py            # Cython build config
├── build_performance.bat          # Windows build script
├── requirements.txt               # Python dependencies
├── CHANGELOG.txt                  # Version history
├── README.md                      # This file
├── PERFORMANCE.md                 # Optimization guide
│
└── %APPDATA%\MLB-TCKR\            # User data directory
    ├── MLB-TCKR.Settings.json     # Settings file
    ├── led_board-7.ttf            # Custom font
    ├── mlb.png                    # Tray icon
    └── MLB-TCKR.images\           # Team logos
        ├── yankees.png
        ├── dodgers.png
        └── ... (30 teams)
```

---

## How It Works

### Data Flow
1. **Background Worker Thread** (`GameDataWorker`) fetches data from MLB-StatsAPI
2. **Signal/Slot Communication** passes game data to main UI thread
3. **Ticker Builder** creates pixmap with all games (duplicated for seamless loop)
4. **60 FPS Animation** scrolls content smoothly with sub-pixel precision
5. **Intelligent Polling** adjusts update frequency based on game status

### Game States
- **Live/In Progress**: Shows scores, runners, outs, inning (updates every 10s)
- **Final/Completed**: Shows final scores with "F" indicator
- **Scheduled/Pre-Game**: Shows game time

### Polling Intelligence
- **Active Games**: Updates every 10 seconds (configurable)
- **All Games Finished**: Switches to hourly checks
- **Midnight Rollover**: Detects new day, fetches next day's schedule
- **Automatic Resume**: Returns to normal polling when games start

### Baseball Diamond
- **Three Bases**: Triangle formation (1st, 2nd, 3rd)
  - Green (#00FF00) when runner on base
  - Gray outline when empty
- **Three Outs**: Circles below bases
  - Red (#FF0000) for recorded outs
  - Gray outline for remaining outs
- **Inning Indicator**: Gold text (#FFD700)
  - "T5" = Top of 5th
  - "B5" = Bottom of 5th
  - "F" = Final

---

## Configuration Files

### Settings Location
`%APPDATA%\MLB-TCKR\MLB-TCKR.Settings.json`

### Default Settings
```json
{
    "speed": 5,
    "update_interval": 10,
    "ticker_height": 64,
    "font": "Ozone",
    "font_scale_percent": 150,
    "show_team_records": true,
    "show_team_cities": false,
    "include_final_games": true,
    "include_scheduled_games": true,
    "led_background": true,
    "glass_overlay": true,
    "background_opacity": 255,
    "team_colors": {}
}
```

---

## Team Logos

Logo files should be placed in `%APPDATA%\MLB-TCKR\MLB-TCKR.images\`

### Naming Convention
Use team nickname (lowercase, no spaces):
- `yankees.png`
- `redsox.png`
- `dodgers.png`
- `whitesox.png`
- `bluejays.png`
- etc.

The application performs case-insensitive searches and automatically falls back to colored squares with team abbreviations if logos are missing.

---

## Performance Tips

1. **Enable Cython**: Run `build_performance.bat` for best results
2. **Adjust Update Interval**: Increase to 30-60 seconds if CPU usage is a concern
3. **Disable Visual Effects**: Turn off LED background and glass overlay for minimal resource usage
4. **Reduce Ticker Height**: Smaller height = less rendering work
5. **Close Settings Dialog**: Keep it closed during normal operation

### Performance Metrics
- **With Cython**: Smooth 60 FPS, ~1-2% CPU usage
- **Without Cython**: Smooth 60 FPS, ~3-5% CPU usage
- **API Usage**: 1 call per update interval (or 1/hour when games finished)

---

## Troubleshooting

### Ticker doesn't appear
- Check if another window is in fullscreen mode
- Restart the application
- Verify Windows AppBar registration in console output

### Logos don't show
- Ensure PNG files are in `%APPDATA%\MLB-TCKR\MLB-TCKR.images\`
- Check file naming (should match team nickname, lowercase)
- Application will use colored fallback if logos missing

### Scrolling is choppy
- Run `build_performance.bat` to enable Cython optimizations
- Close resource-heavy applications
- Reduce ticker height in settings

### Games not updating
- Check internet connection
- Verify MLB-StatsAPI is accessible
- Check console for error messages
- Try manual refresh from tray menu

### Settings don't save
- Ensure `%APPDATA%\MLB-TCKR\` directory is writable
- Check for JSON syntax errors in settings file
- Try resetting to defaults

---

## Development

### Code Structure
- **Main Classes**:
  - `MLBTickerWindow` - Main application window with DPI-aware AppBar integration
  - `GameDataWorker` - Background thread for API calls
  - `StandingsWindow` - AL/NL standings popup with LED-style background
  - `_StandingsWorker` - Background thread for standings fetch
  - `FontPreviewDelegate` - Custom item delegate for font combo box
  - `SettingsDialog` - Configuration UI with tabs
- **Key Methods**:
  - `fetch_todays_games()` - MLB API integration
  - `fetch_standings()` - AL/NL standings from statsapi
  - `build_ticker_pixmap()` - Render complete ticker
  - `draw_baseball_diamond()` - Create diamond visualization
  - `update_scroll()` - 60 FPS animation loop
  - `setup_appbar()` - DPI-aware Win32 AppBar registration
  - `check_all_games_finished()` - Game status detection
  - `check_for_next_day_games()` - Midnight rollover

### Cython Modules
- `calculate_smooth_scroll()` - Sub-pixel scroll calculation
- `get_pixel_position()` - Fast float-to-int conversion
- `adjust_speed_for_framerate()` - FPS-aware speed scaling

### Build System
- `build_performance.bat` - Automated Cython compilation for Windows
- `setup_mlb_cython.py` - Distutils configuration with MSVC optimizations

---

## License

**GNU Affero General Public License v3.0 (AGPL-3.0)**

This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

---

## Author

**Paul R. Charovkine**

- Program: MLB-TCKR.py
- Version: 2.2.0
- Date: 2026.03.16

---

## Acknowledgments

- **MLB-StatsAPI** - MLB game data provider
- **PyQt5** - Cross-platform GUI framework
- **Cython** - Python to C compiler for optimizations
- **LED Board-7 Font** - Custom LED-style font for authentic ticker appearance

---

## Support

For issues, questions, or feature requests:
1. Check the CHANGELOG.txt for known issues
2. Review PERFORMANCE.md for optimization guidance
3. Check console output for error messages
4. Verify all dependencies are installed

---

## Roadmap

### Potential Future Features
- [ ] Game alerts and notifications
- [ ] Score change pop-ups
- [ ] Expanded statistics display
- [ ] Multi-monitor support
- [ ] Custom positioning (top/bottom/left/right)
- [ ] Additional visual themes
- [ ] Playoff bracket visualization
- [ ] Player statistics integration
- [ ] Audio alerts for favorite teams

---

**Enjoy your MLB ticker! ⚾**
