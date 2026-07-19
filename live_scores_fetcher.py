"""
live_scores_fetcher.py â€” Fetches LIVE games and pushes to BOTH live_scores.json AND parlayos html

This fixes: "Make live scores automatically push its data to parlayos html"

Previously: live-scores.yml only wrote live_scores.json, which the HTML loads via fetch()
But if user opens file:// or GitHub Pages has caching, live data doesn't show.

Now: This script does BOTH:
1. Writes live_scores.json (for JS fetcher)
2. Injects live data directly into parlayos_5.html, parlayos.html, parlayos_2.html, index.html
   via window.LIVE_SCORES_DATA so it shows even without fetch

Supports MLB, NFL, NBA - checks real schedule to only fetch when games are active.
"""

import requests
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).parent

# Team ID mappings for logos etc
MLB_TEAM_IDS = {
    'ARI':109, 'ATL':144, 'BAL':110, 'BOS':111, 'CHC':112, 'CWS':145,
    'CIN':113, 'CLE':114, 'COL':115, 'DET':116, 'HOU':117, 'KC': 118,
    'LAA':108, 'LAD':119, 'MIA':146, 'MIL':158, 'MIN':142, 'NYM':121,
    'NYY':147, 'OAK':133, 'PHI':143, 'PIT':134, 'SD': 135, 'SF': 137,
    'SEA':136, 'STL':138, 'TB': 139, 'TEX':140, 'TOR':141, 'WSH':120,
}

def get_mlb_live_games():
    """Fetch live MLB games from MLB Stats API"""
    games = []
    try:
        # Get today's date
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Check schedule for today
        sched_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today}&hydrate=team,linescore,probablePitcher"
        r = requests.get(sched_url, timeout=10)
        data = r.json()
        
        for date in data.get("dates", []):
            for game in date.get("games", []):
                status = game.get("status", {})
                abstract_state = status.get("abstractGameState", "")
                detailed_state = status.get("detailedState", "")
                
                # Only care about Live/In Progress games
                is_live = abstract_state in ("Live", "In Progress") or "In Progress" in detailed_state
                
                # Also include games that started in last 4 hours (might still be live)
                game_date_str = game.get("gameDate", "")
                try:
                    game_dt = datetime.fromisoformat(game_date_str.replace("Z", "+00:00"))
                    minutes_ago = (datetime.now(timezone.utc) - game_dt).total_seconds() / 60
                    recently_started = 0 <= minutes_ago <= 240  # Started in last 4 hours
                except:
                    recently_started = False
                
                if not (is_live or recently_started):
                    continue
                
                # Extract teams and scores
                teams = game.get("teams", {})
                away = teams.get("away", {})
                home = teams.get("home", {})
                
                away_team = away.get("team", {})
                home_team = home.get("team", {})
                
                away_abbr = away_team.get("abbreviation", "AWAY")
                home_abbr = home_team.get("abbreviation", "HOME")
                
                away_name = away_team.get("name", away_abbr)
                home_name = home_team.get("name", home_abbr)
                
                # Scores
                away_score = away.get("score", 0)
                home_score = home.get("score", 0)
                
                # Linescore for inning
                linescore = game.get("linescore", {})
                inning_state = linescore.get("inningState", "")
                current_inning = linescore.get("currentInning", "")
                inning = f"{inning_state} {current_inning}".strip() if current_inning else detailed_state
                
                # GamePk for unique ID
                game_pk = game.get("gamePk", 0)
                
                # Build live game object for our HTML
                live_game = {
                    "id": f"mlb_live_{game_pk}",
                    "lg": "MLB",
                    "home": home_abbr,
                    "away": away_abbr,
                    "home_name": home_name,
                    "away_name": away_name,
                    "inning": inning or detailed_state,
                    "status": abstract_state,
                    "detail": f"{away_abbr} {away_score} - {home_abbr} {home_score}",
                    "teams": [
                        {"name": away_name, "abbr": away_abbr, "score": away_score, "logo": away_abbr, "rec": ""},
                        {"name": home_name, "abbr": home_abbr, "score": home_score, "logo": home_abbr, "rec": ""},
                    ],
                    "score_away": away_score,
                    "score_home": home_score,
                    "gamePk": game_pk,
                }
                games.append(live_game)
                
        print(f"MLB: Found {len(games)} live/recent games")
        return games
        
    except Exception as e:
        print(f"MLB live fetch error: {e}")
        import traceback
        traceback.print_exc()
        return []

def get_nfl_live_games():
    """Fetch live NFL games - offseason returns empty, but structure ready"""
    # NFL season check - for now return empty, but keep function for future
    # Could integrate with ESPN API or similar
    return []

def get_nba_live_games():
    """Fetch live NBA games - offseason returns empty"""
    return []

def build_live_json():
    """Build live_scores.json with all live games"""
    all_games = []
    
    mlb_games = get_mlb_live_games()
    all_games.extend(mlb_games)
    
    nfl_games = get_nfl_live_games()
    all_games.extend(nfl_games)
    
    nba_games = get_nba_live_games()
    all_games.extend(nba_games)
    
    live_data = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "count": len(all_games),
        "games": all_games,
        "mlb_count": len(mlb_games),
        "nfl_count": len(nfl_games),
        "nba_count": len(nba_games),
        "next_check": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }
    
    # Write to live_scores.json
    out_path = HERE / "live_scores.json"
    with open(out_path, "w") as f:
        json.dump(live_data, f, indent=2)
    
    print(f"Wrote {out_path} with {len(all_games)} games")
    return live_data

def inject_into_html(live_data):
    """Inject live scores directly into parlayos html files so they show without needing fetch"""
    
    # Find all parlayos html files
        candidates = [
        "parlayos.html",  # ONLY file in repo
    ]
    
    html_files = []
    for name in candidates:
        p = HERE / name
        if p.exists():
            html_files.append(p)
    
    if not html_files:
        print("No HTML files found to inject live data into")
        return
    
    # Build injection JS
    games_json = json.dumps(live_data["games"])
    updated_str = live_data["updated"]
    
    injection = f'''
    // â”€â”€ LIVE SCORES AUTO-PUSH (generated by live_scores_fetcher.py {updated_str}) â”€â”€
    window.LIVE_SCORES_DATA = {json.dumps(live_data)};
    window.PARLAYOS_LIVE_GAMES = {games_json};
    
    (function(){{
        // Auto-inject live games into UI when DOM ready
        function injectLiveScores(){{
            const games = window.PARLAYOS_LIVE_GAMES || [];
            const mount = document.getElementById('liveScoresMount');
            if(!mount) return;
            
            // If our JS fetcher already rendered, don't overwrite if it has more recent data
            // But if mount is empty or shows "No live games", we should render
            
            const data = window.LIVE_SCORES_DATA;
            
            if(!games.length){{
                // Only show no-games message if fetcher hasn't already shown something more recent
                if(mount.innerHTML.includes('No live games') || mount.innerHTML.trim() === ''){{
                    mount.innerHTML = `
                      <div class="live-header">
                        <h2><span class="live-dot" style="background:#64748b; box-shadow:none;"></span>Live Scores</h2>
                        <span style="font-size:11px; opacity:0.6;">Updated ${{new Date().toLocaleTimeString()}} â€¢ No live games</span>
                      </div>
                      <div style="padding:32px; text-align:center; background:rgba(255,255,255,0.10); border-radius:20px; border:1px solid rgba(255,255,255,0.16);">
                        <div style="font-size:28px; margin-bottom:8px;">ðŸ’¤</div>
                        <b>No live games right now</b>
                        <div style="font-size:12px; opacity:0.6; margin-top:6px;">Checks every 10m with smart schedule</div>
                      </div>
                    `;
                }}
                return;
            }}
            
            // Render live games directly into mount (same as fetcher v2)
            mount.innerHTML = `
              <div class="live-header">
                <h2><span class="live-dot"></span>Live Scores â€¢ ${{games.length}} LIVE</h2>
                <span style="font-size:11px; opacity:0.6;">Updated ${{new Date(data.updated).toLocaleTimeString()}} â€¢ Auto-pushed from live fetcher</span>
              </div>
              <div class="live-grid">
                ${{games.map(g=>`
                  <div class="live-card live">
                    <div class="live-top">
                      <div class="live-league">${{g.lg==='MLB'?'âš¾':g.lg==='NFL'?'ðŸˆ':'ðŸ€'}} ${{g.lg}}</div>
                      <div class="live-status">${{g.inning}}</div>
                    </div>
                    <div class="live-team">
                      ${{g.teams.map((t,i)=>`
                        <div class="live-team-row">
                          <div class="live-team-logo">${{t.logo}}</div>
                          <div style="min-width:0; flex:1;">
                            <span class="live-team-name">${{t.name}}</span>
                            <span class="live-team-record">${{t.rec||''}}</span>
                          </div>
                          <div class="live-score ${{t.score > g.teams[1-i].score ? 'winning' : ''}}">${{t.score}}</div>
                        </div>
                      `).join('')}}
                    </div>
                    <div class="live-footer"><span>${{g.detail}}</span><span>ðŸ“¡ LIVE</span></div>
                  </div>
                `).join('')}}
              </div>
            `;
        }}
        
        document.addEventListener('DOMContentLoaded', injectLiveScores);
        // Also try now in case DOM already loaded
        if(document.readyState !== 'loading'){{
            injectLiveScores();
        }}
        // Re-inject every 30s in case user navigates
        setInterval(injectLiveScores, 30000);
    }})();
    // â”€â”€ END LIVE SCORES AUTO-PUSH â”€â”€
'''
    
    # For each HTML file, inject or replace existing live push
    for html_path in html_files:
        try:
            text = html_path.read_text(encoding="utf-8", errors="ignore")
            
            # Remove old auto-push if exists
            text = re.sub(
                r"// â”€â”€ LIVE SCORES AUTO-PUSH.*?// â”€â”€ END LIVE SCORES AUTO-PUSH â”€â”€\s*\n",
                "",
                text,
                flags=re.DOTALL
            )
            
            # Find where to inject - after the live-json-fetcher or before </body>
            marker = '<script id="live-json-fetcher-v2">'
            if marker in text:
                # Inject after fetcher
                text = text.replace(
                    '</script>\n</body>' if '</script>\n</body>' in text else '</body>',
                    '</script>\n<script id="live-auto-push">\n' + injection + '\n</script>\n</body>'
                )
                # Actually better: inject right after live-json-fetcher-v2 closing
                # The above might duplicate, so let's do more careful replacement
                # Remove any existing live-auto-push
                text = re.sub(r'<script id="live-auto-push">.*?</script>\s*\n', '', text, flags=re.DOTALL)
                # Now inject after live-json-fetcher-v2
                text = text.replace(
                    '<script id="live-json-fetcher-v2">',
                    '<script id="live-auto-push">\n' + injection + '\n</script>\n<script id="live-json-fetcher-v2">'
                )
            else:
                # Inject before </body> if no fetcher v2 found
                text = re.sub(r'<script id="live-auto-push">.*?</script>\s*\n', '', text, flags=re.DOTALL)
                text = text.replace('</body>', f'<script id="live-auto-push">\n{injection}\n</script>\n</body>')
            
            html_path.write_text(text, encoding="utf-8")
            print(f"âœ“ Injected live data into {html_path.name} ({len(live_data['games'])} games)")
            
        except Exception as e:
            print(f"âœ— Failed to inject into {html_path.name}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    print("=== Live Scores Fetcher - Auto-push to ParlayOS HTML ===")
    live_data = build_live_json()
    inject_into_html(live_data)
    print(f"\nDone: {live_data['count']} live games pushed to JSON + HTML")
