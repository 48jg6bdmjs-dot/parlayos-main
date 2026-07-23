"""
live_scores_fetcher.py â€” Fetches LIVE + FINAL games and pushes to live_scores.json AND parlayos html
Compatible with parlayos_3.html new live card renderer (a,b,aScore,bScore + teams)
Updates every 5 minutes via live-scores.yml cron
"""

import requests
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).parent

def get_mlb_games_for_date(date_str):
    """Fetch MLB games for a specific date (both live and final)"""
    games = []
    try:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}&hydrate=team,linescore"
        r = requests.get(url, timeout=12)
        data = r.json()
        for date in data.get("dates", []):
            for game in date.get("games", []):
                status = game.get("status", {})
                abstract = status.get("abstractGameState", "")
                detailed = status.get("detailedState", "")
                coded = status.get("codedGameState", "")
                
                # Include Live, Final, and recently completed
                is_relevant = abstract in ("Live", "Final") or coded in ("F","I","O") or "Final" in detailed or "In Progress" in detailed
                
                # For today, also include preview games starting within 12h? No, only live/final for scores page
                if not is_relevant:
                    # For yesterday, we want finals only for calendar
                    if abstract != "Final" and "Final" not in detailed:
                        continue

                teams = game.get("teams", {})
                away = teams.get("away", {})
                home = teams.get("home", {})
                away_team = away.get("team", {})
                home_team = home.get("team", {})

                away_abbr = away_team.get("abbreviation", "AWAY")
                home_abbr = home_team.get("abbreviation", "HOME")
                away_name = away_team.get("teamName", away_team.get("name", away_abbr))
                home_name = home_team.get("teamName", home_team.get("name", home_abbr))

                away_score = away.get("score", 0)
                home_score = home.get("score", 0)

                linescore = game.get("linescore", {})
                inning_state = linescore.get("inningState", "")
                current_inning = linescore.get("currentInning", "")
                if current_inning:
                    inning_txt = f"{inning_state} {current_inning}".strip()
                else:
                    inning_txt = detailed

                game_pk = game.get("gamePk", 0)
                is_final = abstract == "Final" or "Final" in detailed

                # Build object compatible with BOTH old and new renderer
                # New format: a,b,aScore,bScore,lg,status,final,date
                # Old format: teams array
                g = {
                    "id": f"mlb_{game_pk}",
                    "lg": "MLB",
                    "league": "mlb",
                    "a": away_abbr,
                    "b": home_abbr,
                    "aScore": away_score,
                    "bScore": home_score,
                    "a_name": away_name,
                    "b_name": home_name,
                    "status": inning_txt if not is_final else detailed,
                    "final": is_final,
                    "date": date_str,
                    "gamePk": game_pk,
                    # backward compat
                    "home": home_abbr,
                    "away": away_abbr,
                    "inning": inning_txt,
                    "detail": f"{away_abbr} {away_score} - {home_abbr} {home_score}",
                    "teams": [
                        {"name": away_name, "abbr": away_abbr, "score": away_score, "logo": away_abbr, "rec": ""},
                        {"name": home_name, "abbr": home_abbr, "score": home_score, "logo": home_abbr, "rec": ""},
                    ],
                    "score_away": away_score,
                    "score_home": home_score,
                }
                games.append(g)
        return games
    except Exception as e:
        print(f"MLB fetch error for {date_str}: {e}")
        import traceback; traceback.print_exc()
        return []

def build_live_json():
    """Build live_scores.json with today + yesterday for finals"""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    all_games = []
    # Today: live + final
    today_games = get_mlb_games_for_date(today)
    all_games.extend(today_games)

    # Yesterday: finals for calendar
    yest_games = get_mlb_games_for_date(yesterday)
    # Only finals for yesterday
    yest_finals = [g for g in yest_games if g["final"]]
    # If today has < 7 games (like sample), also include yesterday finals to fill
    if len(today_games) < 7:
        all_games.extend(yest_finals)

    # Deduplicate by id
    seen = {}
    for g in all_games:
        seen[g["id"]] = g
    all_games = list(seen.values())

    # Sort: live first, then final
    def sort_key(g):
        is_live = not g["final"]
        return (0 if is_live else 1, g["date"])
    all_games.sort(key=sort_key)


    # Fallback: if no games fetched (offline or no games), keep existing json
    if len(all_games) == 0:
        try:
            existing_paths = [HERE / "live_scores.json", HERE / "data" / "live_scores.json"]
            for ep in existing_paths:
                if ep.exists():
                    with open(ep) as f:
                        existing = json.load(f)
                        if existing.get("games"):
                            print(f"Using existing data from {ep} as fallback ({len(existing['games'])} games)")
                            return existing
        except Exception as e:
            print(f"Fallback failed: {e}")

    live_data = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "date": today,
        "count": len(all_games),
        "games": all_games,
        "mlb_count": len([g for g in all_games if g["lg"]=="MLB"]),
        "nfl_count": 0,
        "nba_count": 0,
        "next_check": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }

    # Write files
    for p in [HERE / "live_scores.json", HERE / "data" / "live_scores.json"]:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w") as f:
                json.dump(live_data, f, indent=2)
            print(f"Wrote {p} ({len(all_games)} games)")
        except Exception as e:
            print(f"Failed to write {p}: {e}")

    return live_data

def inject_into_html(live_data):
    """Inject live data into parlayos html files WITHOUT overwriting custom card UI"""
    # Find html files
    candidates = [
        HERE / "parlayos_3.html",
        HERE / "parlayos.html",
        HERE / "parlayOS_3.html",
        HERE / "index.html",
        HERE / "docs" / "index.html",
    ]
    # Also glob for any parlay*.html
    for html_file in HERE.glob("parlay*.html"):
        if html_file not in candidates:
            candidates.append(html_file)

    html_files = [p for p in candidates if p.exists()]
    if not html_files:
        print("No HTML files found to inject")
        return

    # Build minimal injection - just data, no HTML rendering
    # This lets the live-json-fetcher in the HTML do the proper rendering with correct card spacing
    injection = f"""
// â”€â”€ LIVE SCORES AUTO-PUSH (generated {live_data['updated']}) â”€â”€
window.PARLAYOS_LIVE_SCORES = {json.dumps(live_data)};
window.__EMBEDDED_LIVE_SCORES = {json.dumps(live_data)};
window.PARLAYOS_LIVE_GAMES = {json.dumps(live_data['games'])};
// â”€â”€ END LIVE SCORES AUTO-PUSH â”€â”€
"""

    for html_path in html_files:
        try:
            text = html_path.read_text(encoding="utf-8", errors="ignore")

            # Remove old auto-push blocks
            text = re.sub(r"// â”€â”€ LIVE SCORES AUTO-PUSH.*?// â”€â”€ END LIVE SCORES AUTO-PUSH â”€â”€\s*\n", "", text, flags=re.DOTALL)
            text = re.sub(r'<script id="live-auto-push">.*?</script>\s*\n', '', text, flags=re.DOTALL)
            text = re.sub(r'<script id="live-data-embedding">.*?</script>\s*\n', '', text, flags=re.DOTALL)

            # Inject new data block before </body>
            # Use a dedicated id for data embedding
            embed_script = f'<script id="live-data-embedding">\n{injection}\n</script>\n'

            if '</body>' in text:
                text = text.replace('</body>', embed_script + '</body>')
            else:
                text += embed_script

            html_path.write_text(text, encoding="utf-8")
            print(f"âœ“ Injected live data into {html_path.name} ({live_data['count']} games)")

        except Exception as e:
            print(f"âœ— Failed to inject into {html_path.name}: {e}")
            import traceback; traceback.print_exc()

if __name__ == "__main__":
    print("=== Live Scores Fetcher - Every 5min ===")
    live_data = build_live_json()
    inject_into_html(live_data)
    print(f"Done: {live_data['count']} games pushed")
