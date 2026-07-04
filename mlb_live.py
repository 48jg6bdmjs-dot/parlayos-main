import requests
import json
from datetime import datetime
import pytz

def get_live_mlb_scores():
    """Pull live MLB scores from official MLB Stats API - free, no key needed"""
    
    # Get today's date in ET since MLB uses Eastern
    et = pytz.timezone('US/Eastern')
    today = datetime.now(et).strftime('%Y-%m-%d')
    
    # MLB Stats API endpoint - hydrate gets us linescore + status
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today}&hydrate=linescore,team,probablePitcher"
    
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"Error fetching MLB data: {e}")
        return []
    
    games = []
    for date in data.get('dates', []):
        for g in date.get('games', []):
            away = g['teams']['away']
            home = g['teams']['home']
            linescore = g.get('linescore', {})
            
            # Build clean game object
            game_data = {
                "game_id": g['gamePk'],
                "matchup": f"{away['team']['abbreviation']} @ {home['team']['abbreviation']}",
                "away_team": away['team']['name'],
                "home_team": home['team']['name'],
                "away_abbr": away['team']['abbreviation'],
                "home_abbr": home['team']['abbreviation'],
                "away_score": away.get('score', 0),
                "home_score": home.get('score', 0),
                "status": g['status']['detailedState'],  # "Live", "Final", "Scheduled"
                "status_code": g['status']['statusCode'],  # "I"=In Progress, "F"=Final, "S"=Scheduled
                "inning": linescore.get('currentInning', ''),
                "inning_state": linescore.get('inningState', ''),  # "Top", "Bottom", "Middle"
                "outs": linescore.get('outs', 0),
                "venue": g['venue']['name'],
                "away_sp": away.get('probablePitcher', {}).get('fullName', 'TBD'),
                "home_sp": home.get('probablePitcher', {}).get('fullName', 'TBD'),
                "start_time": g['gameDate'],
                "is_live": g['status']['statusCode'] == 'I',
                "is_final": g['status']['statusCode'] == 'F'
            }
            
            # Add readable status for your terminal
            if game_data['is_live']:
                game_data['display'] = f"{game_data['inning_state']} {game_data['inning']} | {game_data['away_score']}-{game_data['home_score']}"
            elif game_data['is_final']:
                game_data['display'] = f"FINAL {game_data['away_score']}-{game_data['home_score']}"
            else:
                start_et = datetime.fromisoformat(g['gameDate'].replace('Z', '+00:00')).astimezone(et)
                game_data['display'] = f"{start_et.strftime('%-I:%M %p ET')}"
                
            games.append(game_data)
    
    return games

if __name__ == "__main__":
    games = get_live_mlb_scores()
    
    output = {
        "last_updated": datetime.now(pytz.timezone('US/Eastern')).isoformat(),
        "date": datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d'),
        "game_count": len(games),
        "games": games
    }
    
    with open('mlb_live.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"Success: {len(games)} games written to mlb_live.json")
    
    # Print for quick terminal check
    for g in games:
        print(f"{g['matchup']}: {g['display']}")