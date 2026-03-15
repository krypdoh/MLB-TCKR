import statsapi
import datetime

today = datetime.datetime.now().strftime('%Y-%m-%d')
print(f"Fetching games for {today}")

games = statsapi.schedule(date=today)
print(f"Total games: {len(games)}")

for game in games[:10]:
    away = game.get('away_name')
    home = game.get('home_name')
    print(f"{away} @ {home}")
    
    # Show normalized names
    away_norm = away.lower().replace(' ', '').replace('_', '')
    home_norm = home.lower().replace(' ', '').replace('_', '')
    print(f"  Normalized: {away_norm}.png @ {home_norm}.png")
