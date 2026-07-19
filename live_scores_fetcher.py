#!/usr/bin/env python3
"""
ParlayOS Live Scores Fetcher - LIVE GAMES ONLY
Pulls MLB, NFL, NBA live/in-progress games every 5 min via GitHub Actions
Outputs live_scores.json matching ParlayOS glass design

Sources:
- MLB: statsapi.mlb.com (official, no key)
- NFL/NBA: site.api.espn.com (no key)

Usage:
  python live_scores_fetcher.py
  -> writes live_scores.json
"""

import json
import requests
from datetime import datetime, timezone
from collections import defaultdict

HEADERS = {"User-Agent": "ParlayOS-Live/1.0"}

def fetch_mlb_live():
    """MLB live games only"""
    live = []
    try:
        # Today + yesterday + tomorrow to catch late games
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today}&hydrate=team,linescore,decisions,flags"
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        data = r.json()
        for date in data.get("dates", []):
            for g in date.get("games", []):
                status = g.get("status", {})
                abstract = status.get("abstractGameState", "")
                detailed = status.get("detailedState", "")
                # Only live
                if abstract != "Live" and "In Progress" not in detailed:
                    continue
                
                teams = g.get("teams", {})
                away = teams.get("away", {})
                home = teams.get("home", {})
                away_team = away.get("team", {})
                home_team = home.get("team", {})
                
                linescore = g.get("linescore", {})
                inning_state = linescore.get("inningState", "")
                inning = linescore.get("currentInning", "")
                inning_txt = f"{inning_state} {inning}".strip() if inning else detailed
                
                away_score = away.get("score", 0)
                home_score = home.get("score", 0)
                
                # Detail: outs + runners
                outs = linescore.get("outs", "")
                detail = f"{outs} out" + ("s" if outs != 1 else "")
                if linescore.get("offense", {}).get("first"): detail += ", runner on 1st"
                if linescore.get("offense", {}).get("second"): detail += ", runner on 2nd"
                
                live.append({
                    "lg": "MLB",
                    "id": f"mlb_{g.get('gamePk')}",
                    "status": "LIVE",
                    "inning": inning_txt or detailed,
                    "teams": [
                        {
                            "abbr": away_team.get("abbreviation", "AWY"),
                            "name": away_team.get("abbreviation", "Away")[:3].title(),
                            "rec": f"{away.get('leagueRecord', {}).get('wins', 0)}-{away.get('leagueRecord', {}).get('losses', 0)}",
                            "score": away_score,
                            "logo": away_team.get("abbreviation", "AW")[:3].upper()
                        },
                        {
                            "abbr": home_team.get("abbreviation", "HOM"),
                            "name": home_team.get("abbreviation", "Home")[:3].title(),
                            "rec": f"{home.get('leagueRecord', {}).get('wins', 0)}-{home.get('leagueRecord', {}).get('losses', 0)}",
                            "score": home_score,
                            "logo": home_team.get("abbreviation", "HO")[:3].upper()
                        }
                    ],
                    "detail": detail or f"{away_team.get('teamName','')} @ {home_team.get('teamName','')}"
                })
    except Exception as e:
        print(f"[MLB] error: {e}")
    return live

def fetch_espn_live(sport, league):
    """ESPN live for NFL/NBA - only status.type.state == 'in'"""
    live = []
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        data = r.json()
        for ev in data.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            status = comp.get("status", {})
            state = status.get("type", {}).get("state", "")
            if state != "in":
                continue
            
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                continue
            
            # Away is usually first, home second
            away = next((c for c in competitors if c.get("homeAway")=="away"), competitors[0])
            home = next((c for c in competitors if c.get("homeAway")=="home"), competitors[1])
            
            away_team = away.get("team", {})
            home_team = home.get("team", {})
            
            away_score = int(away.get("score", 0) or 0)
            home_score = int(home.get("score", 0) or 0)
            
            period = status.get("period", "")
            clock = status.get("displayClock", "")
            inning_txt = f"Q{period} {clock}".strip() if sport=="football" or sport=="basketball" else f"{period} {clock}"
            if not inning_txt:
                inning_txt = status.get("type", {}).get("detail", "LIVE")
            
            # Detail: possession / situation
            situation = comp.get("situation", {})
            detail = situation.get("lastPlay", {}).get("text", "") if isinstance(situation, dict) else ""
            if not detail:
                detail = f"{away_team.get('shortDisplayName','Away')} @ {home_team.get('shortDisplayName','Home')}"
            
            lg_code = "NFL" if league=="nfl" else "NBA"
            
            live.append({
                "lg": lg_code,
                "id": f"{league}_{ev.get('id')}",
                "status": "LIVE",
                "inning": inning_txt,
                "teams": [
                    {
                        "abbr": away_team.get("abbreviation", "AWY"),
                        "name": away_team.get("abbreviation", "Away")[:3].title(),
                        "rec": away.get("records", [{}])[0].get("summary","0-0") if away.get("records") else "0-0",
                        "score": away_score,
                        "logo": away_team.get("abbreviation", "AW")[:3].upper()
                    },
                    {
                        "abbr": home_team.get("abbreviation", "HOM"),
                        "name": home_team.get("abbreviation", "Home")[:3].title(),
                        "rec": home.get("records", [{}])[0].get("summary","0-0") if home.get("records") else "0-0",
                        "score": home_score,
                        "logo": home_team.get("abbreviation", "HO")[:3].upper()
                    }
                ],
                "detail": detail[:80]
            })
    except Exception as e:
        print(f"[{league.upper()}] error: {e}")
    return live

def main():
    all_live = []
    print("Fetching MLB live...")
    all_live.extend(fetch_mlb_live())
    print("Fetching NFL live...")
    all_live.extend(fetch_espn_live("football", "nfl"))
    print("Fetching NBA live...")
    all_live.extend(fetch_espn_live("basketball", "nba"))
    
    # Sort by league order MLB, NFL, NBA
    order = {"MLB":0, "NFL":1, "NBA":2}
    all_live.sort(key=lambda x: order.get(x["lg"], 9))
    
    out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "count": len(all_live),
        "games": all_live  # ONLY live games
    }
    
    with open("live_scores.json", "w") as f:
        json.dump(out, f, indent=2)
    
    print(f"âœ“ Wrote live_scores.json with {len(all_live)} LIVE games")
    if not all_live:
        print("  (No live games right now - file will be empty array, frontend shows 'No live games')")
    return out

if __name__ == "__main__":
    main()
