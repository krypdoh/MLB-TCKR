# MLB-TCKR - Live Baseball Ticker

A Windows application that displays live MLB game data in a scrolling ticker bar at the top of your screen, just like a traditional LED sports ticker!

## Features

✅ **Live Game Updates** - Shows all MLB games for today with real-time scores  
✅ **Baseball Diamond Visualization** - Displays runners on base, outs, and current inning  
✅ **Team Colors** - Team names shown in their primary colors (Red Sox in red, Yankees in navy, etc.)  
✅ **Team Records** - Shows W-L records below team names  
✅ **Game Status** - Displays game times, live scores, or FINAL for completed games  
✅ **Auto-Updates** - Fetches latest game data every 30 seconds  
✅ **AppBar Integration** - Stays docked at top of screen, other windows won't overlap  

## Display Format

### Live Games
```
Twins [LOGO] 5  [⬆️2nd ◆ ◆ ◆ ●●○]  3 [LOGO] Blue Jays
      22-20                                 20-22
```

### Scheduled Games
```
Yankees [LOGO] @ [LOGO] Mets  4:05pm
        30-15              18-25
```

### Completed Games
```
Red Sox [LOGO] 8  FINAL  2 [LOGO] Orioles
        25-20                    22-23
```

## Installation

1. **Install required library:**
   ```powershell
   pip install MLB-StatsAPI
   ```

2. **Add LED board font (optional):**
   - Place `led_board-7.ttf` in one of these locations:
     - `%APPDATA%\MLB-TCKR\led_board-7.ttf`
     - Same folder as `MLB-TCKR.py`
   - If not found, the ticker will use Arial as fallback

3. **Run the ticker:**
   ```powershell
   python MLB-TCKR.py
   ```

## Team Logos

The ticker will automatically create simple colored logos with team abbreviations. For better-looking logos:

1. Create folder: `%APPDATA%\MLB-TCKR\MLB-TCKR.images\`
2. Add PNG files using lowercase team names with no spaces or underscores:
   - `yankees.png`
   - `redsox.png`
   - `bluejays.png`
   - `whitesox.png`
   - etc.
3. Recommended size: 128x128 pixels or larger
4. File search is case-insensitive, so `Yankees.png` will also work

## Configuration

Settings are stored in: `%APPDATA%\MLB-TCKR\MLB-TCKR.Settings.json`

Available settings:
- `speed` - Scroll speed (default: 2)
- `update_interval` - Seconds between game data updates (default: 30)
- `ticker_height` - Height in pixels (default: 60)
- `show_team_records` - Show W-L records (default: true)
- `include_final_games` - Show completed games (default: true)
- `include_scheduled_games` - Show upcoming games (default: true)

## Baseball Diamond Legend

- **Yellow bases (◆)** - Runner on base
- **Gray bases** - Base is empty
- **Red circles (●)** - Outs recorded
- **Gray circles (○)** - Outs remaining
- **▲** - Top of inning (away team batting)
- **▼** - Bottom of inning (home team batting)

## System Tray

Right-click the system tray icon to:
- **Refresh Games** - Manually fetch latest game data
- **Quit** - Close the ticker

## MLB-StatsAPI

This ticker uses the excellent [MLB-StatsAPI](https://github.com/toddrob99/MLB-StatsAPI) library by Todd Roberts to fetch official MLB data.

## Troubleshooting

**No games showing?**
- Check if there are actually games today (ticker will show "No MLB games scheduled today")
- Verify internet connection (API requires internet access)

**Ticker not staying on top?**
- The ticker uses Windows AppBar registration - other windows should automatically position below it
- Try restarting the ticker

**Update errors?**
- The ticker will continue showing last known data if updates fail
- Check internet connection and try refreshing manually

## Future Enhancements

Potential features to add:
- Filtering to show only specific teams
- Pitch-by-pitch updates for selected games
- Playoff series scores
- Customizable LED effects from the original stock ticker
- Multi-day view (yesterday/today/tomorrow)
- Win probability indicators
- Starting pitchers display

## Credits

- Author: Paul R. Charovkine
- Date: March 14, 2026
- License: GNU AGPLv3
- Based on the TCKR stock ticker framework

Enjoy your MLB ticker! ⚾
