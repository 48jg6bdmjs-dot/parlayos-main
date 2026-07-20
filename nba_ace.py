"""
nba_ace.py ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â NBA prediction engine for ParlayOS.

Structural mirror of nfl_ace.py and mlb_ace.py: has_data gating, empirical-
Bayes shrinkage for small in-season samples, required_keys cache pattern,
config-driven qualifies gating, EDGE_COMPONENT_COLS logging.

ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ IMPORTANT ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â NOT YET LIVE-TESTED ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
Same caveat as nfl_ace.py: written in a sandboxed environment with NO
outbound network access, so none of the ESPN or Odds API calls below have
been executed against live data. Every fetch is wrapped in try/except with
has_data=False on failure. Run once, watch stdout for "fetch failed"
lines, and spot-check a few games' stats before trusting picks.
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

Data sources:
  - The Odds API (basketball_nba sport_key) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â moneyline, spreads, totals.
    NBA is one of the two sports the free tier has historically included
    (alongside MLB), so this one should need no plan upgrade unlike NFL.
  - ESPN's public site.api.espn.com / sports.core.api.espn.com JSON API,
    same role MLB_STATS_BASE and nfl_ace.py's ESPN calls fill: team
    season stats, injuries, schedules.
"""
import requests
import json
import csv
from datetime import datetime, timezone
from typing import List, Dict, Tuple
import os
import re
import math
import pickle
from time import time as _time

HERE = os.path.dirname(os.path.abspath(__file__))


# --- ACCURACY FIX: de-vig helpers ---
import math

def _american_to_implied_prob(american_odds):
    try:
        o = float(str(american_odds).strip().replace("+",""))
    except:
        return None
    if o is None:
        return None
    return (-o)/(-o+100.0) if o < 0 else 100.0/(o+100.0)

def _devig_probs(home_odds, away_odds):
    hi = _american_to_implied_prob(home_odds)
    ai = _american_to_implied_prob(away_odds)
    if hi is None or ai is None:
        return (hi or 0.5), (ai or 0.5)
    total = hi + ai
    if total <= 0:
        return 0.5, 0.5
    return hi/total, ai/total

def _logit(p):
    eps = 1e-6
    p = min(max(p, eps), 1-eps)
    return math.log(p/(1-p))

def _sigmoid(x):
    if x >= 0:
        return 1.0/(1.0+math.exp(-x))
    else:
        e = math.exp(x)
        return e/(1.0+e)

CONFIG_PATH = os.path.join(HERE, "sports_config.json")
PICKS_LOG_PATH = os.path.join(HERE, "nba_picks_log.csv")
CACHE_DIR = os.path.join(HERE, ".nba_cache")

# ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ NBA team abbreviations ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Odds API uses full city+name; ESPN/UI use
#    short codes. Same TEAM_ABBR-as-whitelist pattern as MLB/NFL: any
#    home_team/away_team string not in this dict gets skipped rather than
#    falling through to a [:3] truncation that could silently invent a
#    fake team for an All-Star Game or other non-standard entry (the same
#    bug class mlb_ace.py's real-MLB-team filter guards against).
TEAM_ABBR = {
    'Atlanta Hawks': 'ATL', 'Boston Celtics': 'BOS', 'Brooklyn Nets': 'BKN',
    'Charlotte Hornets': 'CHA', 'Chicago Bulls': 'CHI', 'Cleveland Cavaliers': 'CLE',
    'Dallas Mavericks': 'DAL', 'Denver Nuggets': 'DEN', 'Detroit Pistons': 'DET',
    'Golden State Warriors': 'GSW', 'Houston Rockets': 'HOU', 'Indiana Pacers': 'IND',
    'Los Angeles Clippers': 'LAC', 'Los Angeles Lakers': 'LAL', 'Memphis Grizzlies': 'MEM',
    'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL', 'Minnesota Timberwolves': 'MIN',
    'New Orleans Pelicans': 'NOP', 'New York Knicks': 'NYK', 'Oklahoma City Thunder': 'OKC',
    'Orlando Magic': 'ORL', 'Philadelphia 76ers': 'PHI', 'Phoenix Suns': 'PHX',
    'Portland Trail Blazers': 'POR', 'Sacramento Kings': 'SAC', 'San Antonio Spurs': 'SAS',
    'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTA', 'Washington Wizards': 'WSH',
}
# ESPN's internal numeric team IDs ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â sports.core.api.espn.com/v2/sports/basketball/leagues/nba/teams
ESPN_TEAM_IDS = {
    'ATL': 1, 'BOS': 2, 'BKN': 17, 'CHA': 30, 'CHI': 4, 'CLE': 5,
    'DAL': 6, 'DEN': 7, 'DET': 8, 'GSW': 9, 'HOU': 10, 'IND': 11,
    'LAC': 12, 'LAL': 13, 'MEM': 29, 'MIA': 14, 'MIL': 15, 'MIN': 16,
    'NOP': 3, 'NYK': 18, 'OKC': 25, 'ORL': 19, 'PHI': 20, 'PHX': 21,
    'POR': 22, 'SAC': 23, 'SAS': 24, 'TOR': 28, 'UTA': 26, 'WSH': 27,
}

ESPN_SITE_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_CORE_BASE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"


def _f(s, d=None):
    try:
        return float(str(s).strip())
    except (ValueError, TypeError, AttributeError):
        return d


def get_cached(key, ttl=3600, required_keys=None):
    path = os.path.join(CACHE_DIR, f"{key}.pkl")
    try:
        if os.path.exists(path) and _time() - os.path.getmtime(path) < ttl:
            with open(path, 'rb') as f:
                data = pickle.load(f)
            if required_keys and isinstance(data, dict):
                if not all(k in data for k in required_keys):
                    return None
            return data
    except Exception:
        pass
    return None


def set_cache(key, data):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(os.path.join(CACHE_DIR, f"{key}.pkl"), 'wb') as f:
            pickle.dump(data, f)
    except Exception as e:
        print(f"  cache write failed ({key}): {e}")


def load_config():
    """Same pattern as nfl_ace.py's load_config, reading the "nba" section
    of the shared sports_config.json."""
    try:
        with open(CONFIG_PATH) as f:
            full_cfg = json.load(f)
        api_key = full_cfg.get("odds_api_key", "")
        cfg = full_cfg.get("nba", {})
        cfg.setdefault("min_edge", 0.0)
        cfg.setdefault("min_total_line", 190.0)
        cfg.setdefault("max_total_line", 250.0)
        cfg.setdefault("max_legs", 16)
        cfg.setdefault("kelly_fraction", 0.25)
        cfg.setdefault("max_stake_pct", 0.05)
        print(f"NBA config loaded: min_edge={cfg['min_edge']}, "
              f"total_line_band={cfg['min_total_line']}-{cfg['max_total_line']}")
        return cfg, api_key
    except FileNotFoundError:
        print("sports_config.json not found, using NBA defaults, no API key")
        return {"min_edge": 0.0, "min_total_line": 190.0, "max_total_line": 250.0,
                "max_legs": 16, "kelly_fraction": 0.25, "max_stake_pct": 0.05}, ""
    except (json.JSONDecodeError, KeyError) as e:
        print(f"sports_config.json malformed ({e}), using NBA defaults, no API key")
        return {"min_edge": 0.0, "min_total_line": 190.0, "max_total_line": 250.0,
                "max_legs": 16, "kelly_fraction": 0.25, "max_stake_pct": 0.05}, ""


# League-average fallbacks (2025-26 season, updated periodically) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â used
# ONLY when a specific fetch fails, never silently substituted for a
# "successful" real value.
LEAGUE_AVG_OFF_RTG = 114.0    # points scored per 100 possessions
LEAGUE_AVG_DEF_RTG = 114.0    # points allowed per 100 possessions
LEAGUE_AVG_PACE = 99.5        # possessions per 48 minutes
LEAGUE_AVG_TS_PCT = 0.570     # true shooting percentage
LEAGUE_AVG_PPG = 114.0        # points per game (raw, unadjusted for pace)

EDGE_COMPONENT_COLS = [
    "c_team_edge", "c_off_rtg_edge", "c_def_rtg_edge", "c_pace_edge",
    "c_ts_pct_edge", "c_rest_edge", "c_injury_edge", "c_home_court_edge",
]
PICKS_LOG_COLS = [
    "timestamp", "date", "home", "away", "abbr_home", "abbr_away", "pick",
    "abbr_pick", "odds", "model_prob", "edge", "edge_pct", "qualifies",
    "kelly_stake_pct", "line", "spread", "market", "kind",
] + EDGE_COMPONENT_COLS


class NBAPredictionEngine:
    def __init__(self, api_key: str):
        self.api_key = api_key
        print(f"NBA engine initialized with API key: {api_key[:8]}..." if api_key else
              "NBA engine initialized with NO API key ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â fetch_live_odds will fail")

    def fetch_live_odds(self) -> List:
        """Fetch live NBA odds from The Odds API ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â h2h, spreads, totals."""
        url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
        params = {"apiKey": self.api_key, "regions": "us",
                   "markets": "h2h,spreads,totals", "oddsFormat": "american"}
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if isinstance(data, dict) and data.get("message"):
                print(f"Odds API error response: {data.get('message')}")
                return []
            print(f"Odds API returned {len(data)} NBA games")
            return data
        except Exception as e:
            print(f"Odds API error: {e}")
            return []

    def fetch_team_advanced_stats(self, team_abbr: str) -> Dict:
        """
        Real NBA team advanced stats (offensive rating, defensive rating,
        pace, true shooting %) from ESPN's core API. Same has_data
        discipline as mlb_ace.py's fetch_team_form and nfl_ace.py's
        fetch_team_season_stats: every field independently gated, league-
        average fallback ONLY on a failed fetch.

        Offensive/defensive RATING (points per 100 possessions) is used
        instead of raw PPG/points-allowed ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â the direct NBA analog of why
        mlb_ace.py prefers FIP over raw runs-allowed: raw points are
        heavily confounded by PACE (a fast team scores and allows more
        points per game than a slow team of identical quality), so rating
        isolates actual offensive/defensive quality from tempo. Pace is
        then modeled as its OWN separate factor below (mainly relevant to
        the O/U total, not who wins), rather than being silently baked
        into a raw-points comparison the way it would if PPG were used
        directly for team_edge.
        """
        team_id = ESPN_TEAM_IDS.get(team_abbr)
        if not team_id:
            return {"off_rtg": LEAGUE_AVG_OFF_RTG, "def_rtg": LEAGUE_AVG_DEF_RTG,
                    "pace": LEAGUE_AVG_PACE, "ts_pct": LEAGUE_AVG_TS_PCT,
                    "games_played": 0, "rtg_has_data": False, "pace_has_data": False,
                    "ts_has_data": False}
        cache_key = f"nba_team_stats_v1_{team_id}"
        cached = get_cached(cache_key, ttl=3600,
                             required_keys=("off_rtg", "def_rtg", "pace", "ts_pct",
                                            "games_played", "rtg_has_data",
                                            "pace_has_data", "ts_has_data"))
        if cached is not None:
            return cached

        off_rtg = LEAGUE_AVG_OFF_RTG
        def_rtg = LEAGUE_AVG_DEF_RTG
        pace = LEAGUE_AVG_PACE
        ts_pct = LEAGUE_AVG_TS_PCT
        games_played = 0
        rtg_has_data = False
        pace_has_data = False
        ts_has_data = False
        stat_map = {}
        try:
            year = datetime.now().year
            # NBA season spans two calendar years (e.g. 2025-26); ESPN's
            # season-year param uses the LATER year for the whole season
            # (so "2026" covers Oct 2025 - Jun 2026). If we're in the back
            # half of the calendar year (Oct-Dec), the current season's
            # ESPN year is next calendar year, not this one.
            season_year = year + 1 if datetime.now().month >= 10 else year
            r = requests.get(
                f"{ESPN_CORE_BASE}/seasons/{season_year}/types/2/teams/{team_id}/statistics",
                timeout=8)
            data = r.json()
            categories = data.get("splits", {}).get("categories", [])
            for cat in categories:
                for stat in cat.get("stats", []):
                    stat_map[stat.get("name")] = stat.get("value")
            games_played = int(stat_map.get("gamesPlayed", 0) or 0)
        except Exception as e:
            print(f"  NBA team stat fetch failed ({team_abbr}): {e}")

        if "offensiveRating" in stat_map and "defensiveRating" in stat_map:
            try:
                off_rtg = float(stat_map["offensiveRating"])
                def_rtg = float(stat_map["defensiveRating"])
                rtg_has_data = True
            except (ValueError, TypeError):
                pass
        if "pace" in stat_map:
            try:
                pace = float(stat_map["pace"])
                pace_has_data = True
            except (ValueError, TypeError):
                pass
        if "trueShootingPct" in stat_map or "TSPct" in stat_map:
            try:
                raw = stat_map.get("trueShootingPct", stat_map.get("TSPct"))
                ts_pct = float(raw)
                # ESPN sometimes returns shooting percentages as a 0-100
                # scale rather than 0-1; normalize if it looks like the
                # former (a true TS% should never realistically exceed 1.0)
                if ts_pct > 1.0:
                    ts_pct = ts_pct / 100.0
                ts_has_data = True
            except (ValueError, TypeError):
                pass

        result = {
            "off_rtg": off_rtg, "def_rtg": def_rtg, "pace": pace, "ts_pct": ts_pct,
            "games_played": games_played, "rtg_has_data": rtg_has_data,
            "pace_has_data": pace_has_data, "ts_has_data": ts_has_data,
        }
        set_cache(cache_key, result)
        return result

    def fetch_injuries(self, team_abbr: str) -> Dict:
        """Same pattern as nfl_ace.py's fetch_injuries. NBA injury reports
        carry disproportionate weight vs. NFL/MLB ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â a single missing star
        player (best-on-team OUT) swings an NBA game far more than one
        missing NFL starter (11-on-11, more redundancy) or one missing MLB
        position player (27-man lineup over 9 innings). This is reflected
        in a larger weight on c_injury_edge in calculate_win_probability
        below, not in this fetch function itself."""
        team_id = ESPN_TEAM_IDS.get(team_abbr)
        if not team_id:
            return {"count": 0, "has_data": False}
        cache_key = f"nba_injuries_v1_{team_id}"
        cached = get_cached(cache_key, ttl=1800, required_keys=("count", "has_data"))
        if cached is not None:
            return cached
        try:
            r = requests.get(f"{ESPN_CORE_BASE}/teams/{team_id}/injuries",
                              params={"limit": 100}, timeout=8)
            data = r.json()
            items = data.get("items", [])
            count = 0.0
            for it in items:
                status = str(it.get("status", "")).upper()
                if status in ("OUT", "DOUBTFUL"):
                    count += 1.0
                elif status in ("QUESTIONABLE", "DAY-TO-DAY"):
                    count += 0.5
            result = {"count": count, "has_data": True}
            set_cache(cache_key, result)
            return result
        except Exception as e:
            print(f"  NBA injury fetch failed ({team_abbr}): {e}")
            return {"count": 0, "has_data": False}

    def calculate_win_probability(self, game: Dict) -> float:
        """
        Calculate home win probability. Same has_data discipline as
        mlb_ace.py/nfl_ace.py.

        Weight rationale (NBA-specific): the NBA has by far the LONGEST
        regular season of the three sports (82 games vs NFL's 17, MLB's
        162 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â actually between MLB and NFL, but with much higher per-game
        signal density: basketball has far more scoring possessions per
        game than baseball has meaningful at-bats or football has
        meaningful drives, so team-quality signal accumulates faster in
        relative terms). This means season-long rating stats (off_rtg/
        def_rtg) are trusted MORE heavily here relative to any single-
        game factor than in NFL, where QB-specific per-game variance
        dominates more.

        There's also no single "starting pitcher" or "starting QB"
        analog in basketball with anywhere near the same game-determining
        weight ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â a star player missing matters (injury_edge below), but
        no NBA player individually controls outcome the way an NFL QB or
        MLB starting pitcher does, so no single-player factor gets a
        FIP/QBR-sized weight here; the model leans more on team-level
        aggregate stats instead.
        """
        home_abbr = game.get("home_abbr", "")
        away_abbr = game.get("away_abbr", "")

        home_stats = self.fetch_team_advanced_stats(home_abbr)
        away_stats = self.fetch_team_advanced_stats(away_abbr)
        home_inj = self.fetch_injuries(home_abbr)
        away_inj = self.fetch_injuries(away_abbr)

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Rating differential (pace-independent team quality) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â largest
        #    single weight, for the reasons in the docstring above: this
        #    is the closest NBA analog to MLB's season run differential,
        #    but MORE reliable relative to raw points because it already
        #    strips out pace confounding.
        team_edge = 0.0
        if home_stats["rtg_has_data"] and away_stats["rtg_has_data"]:
            home_net_rtg = home_stats["off_rtg"] - home_stats["def_rtg"]
            away_net_rtg = away_stats["off_rtg"] - away_stats["def_rtg"]
            team_edge = (home_net_rtg - away_net_rtg) * 0.0045

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ True shooting % ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â a distinct efficiency signal from net
        #    rating (net rating already captures overall scoring margin
        #    per 100 possessions, which INCLUDES shooting efficiency, so
        #    this is weighted modestly to avoid double-counting the same
        #    underlying "how good is this offense" fact twice ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â same
        #    correlation-avoidance concern mlb_ace.py documents for
        #    offense_edge vs. season_form_edge).
        ts_edge = 0.0
        if home_stats["ts_has_data"] and away_stats["ts_has_data"]:
            ts_edge = (home_stats["ts_pct"] - away_stats["ts_pct"]) * 0.075

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Injury burden ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â weighted MORE heavily than NFL/MLB's injury
        #    edge, per the star-player-impact reasoning in fetch_injuries'
        #    docstring. Still capped, since this is a coarse headline-
        #    count signal, not a precise "which specific player and how
        #    much do they individually matter" model.
        injury_edge = 0.0
        if home_inj["has_data"] and away_inj["has_data"]:
            injury_edge = (away_inj["count"] - home_inj["count"]) * 0.006
            injury_edge = max(-0.025, min(0.025, injury_edge))

        home_court_edge = 0.015  # NBA HCA reduced after de-vig
        # (Comparable in magnitude to MLB's 0.02; commonly cited as
        # somewhat SMALLER than NFL's in modern analytics ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â travel/rest
        # patterns matter more than the specific arena environment in the
        # NBA's dense schedule, which shows up separately as rest_edge
        # rather than being folded into home_court_edge itself.)

        # No real back-to-back/rest-differential fetch implemented in this
        # pass ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â genuinely one of the more NBA-specific, well-documented
        # predictive factors (a team on the second night of a back-to-back
        # is measurably worse), zeroed here rather than faked. Flagged as
        # a clear next addition, same as nfl_ace.py's unbuilt ATS-form/h2h.
        rest_edge = 0.0

        market_p = game.get("market_prob", 0.5)
        logit_market = _logit(market_p)
        edge_sum = (team_edge + ts_edge + injury_edge + home_court_edge + rest_edge)
        logit_adjusted = logit_market + edge_sum * 2.0
        base_prob = _sigmoid(logit_adjusted)

        game["_edge_components"] = {
            "c_team_edge": team_edge, "c_off_rtg_edge": 0.0, "c_def_rtg_edge": 0.0,
            "c_pace_edge": 0.0, "c_ts_pct_edge": ts_edge, "c_rest_edge": rest_edge,
            "c_injury_edge": injury_edge, "c_home_court_edge": home_court_edge,
        }
        return max(0.12, min(0.88, base_prob))

    def calculate_total_points(self, game: Dict, posted_total: float) -> Tuple[str, float, float]:
        """
        O/U direction + edge. Unlike NFL (calculate_total_points there has
        no pace concept), NBA's total is dominated by PACE ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â two efficient
        offenses playing at a slow pace can produce a LOWER total than two
        mediocre offenses playing fast. Expected combined pace-adjusted
        scoring = (average of both teams' pace) ÃƒÆ’Ã¢â‚¬â€ (both teams' combined
        offensive rating relative to league average) / 100 ÃƒÆ’Ã¢â‚¬â€ 2, roughly
        modeling "how many total points at this expected possession
        count, at this expected scoring rate per possession."
        """
        home_abbr = game.get("home_abbr", "")
        away_abbr = game.get("away_abbr", "")
        home_stats = self.fetch_team_advanced_stats(home_abbr)
        away_stats = self.fetch_team_advanced_stats(away_abbr)

        _POINTS_SIGMA = 11.0  # NBA game-total std dev in raw points ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â larger
                               # than NFL's ~10 (more scoring events, more
                               # variance in raw point terms even though
                               # per-possession variance is proportionally
                               # lower), and vastly larger than MLB's ~1.5
                               # runs, since this is a fundamentally
                               # different scoring scale.
        _MARKET_VIG_PROB = 110.0 / 210.0

        def _erf_approx(x):
            t = 1.0 / (1.0 + 0.3275911 * abs(x))
            poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 +
                   t * (-1.453152027 + t * 1.061405429))))
            v = 1.0 - poly * (2.718281828 ** (-x * x))
            return v if x >= 0 else -v

        def _normal_cdf(x):
            return 0.5 * (1.0 + _erf_approx(x / (2.0 ** 0.5)))

        if (home_stats["rtg_has_data"] and away_stats["rtg_has_data"]
                and home_stats["pace_has_data"] and away_stats["pace_has_data"]):
            avg_pace = (home_stats["pace"] + away_stats["pace"]) / 2.0
            # Each team's expected points-per-100-possessions against a
            # league-average opponent, scaled by the OTHER team's defensive
            # rating relative to league average (a strong defense should
            # suppress the opposing offense's expected output).
            home_exp_per100 = home_stats["off_rtg"] * (away_stats["def_rtg"] / LEAGUE_AVG_DEF_RTG)
            away_exp_per100 = away_stats["off_rtg"] * (home_stats["def_rtg"] / LEAGUE_AVG_DEF_RTG)
            # Convert per-100-possessions rate to actual expected points at
            # this game's expected possession count (pace is possessions
            # per 48 min, i.e. per full game ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â no additional /48 scaling
            # needed since pace is already a full-game figure).
            model_total = (home_exp_per100 + away_exp_per100) * (avg_pace / 100.0)
        else:
            # FIXED: return 0 edge when no data, not fake -2.3%
            return 'OVER', round(posted_total,1), 0.0

        gap = model_total - posted_total
        if gap >= 0:
            pick = 'OVER'
            model_prob = 1.0 - _normal_cdf(-gap / _POINTS_SIGMA)
        else:
            pick = 'UNDER'
            model_prob = _normal_cdf(-gap / _POINTS_SIGMA)
        edge = round(model_prob - _MARKET_VIG_PROB, 4)
        return pick, round(model_total, 1), edge


def write_pick_to_log(pick_dict: dict):
    """Same append-with-header-union pattern as nfl_ace.py."""
    file_exists = os.path.exists(PICKS_LOG_PATH)
    existing_cols = []
    if file_exists:
        try:
            with open(PICKS_LOG_PATH, newline='', encoding='utf-8') as f:
                existing_cols = next(csv.reader(f), [])
        except Exception:
            pass
    cols = existing_cols if existing_cols else PICKS_LOG_COLS
    for c in PICKS_LOG_COLS:
        if c not in cols:
            cols.append(c)
    pick_dict = dict(pick_dict)
    pick_dict.setdefault("timestamp", datetime.now().isoformat())
    pick_dict.setdefault("date", datetime.now().strftime('%Y-%m-%d'))
    try:
        with open(PICKS_LOG_PATH, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
            if not file_exists:
                w.writeheader()
            w.writerow(pick_dict)
    except Exception as e:
        print(f"  picks log write failed: {e}")


def _american_to_decimal(price):
    """Same conversion as nfl_ace.py's _american_to_decimal."""
    p = _f(price)
    if p is None:
        return None
    if p > 0:
        return round((p / 100) + 1, 3)
    return round((100 / abs(p)) + 1, 3)


def _picks_to_nba_games(picks: List) -> List:
    """Same field-shape contract as nfl_ace.py's _picks_to_nfl_games ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â see
    that function's docstring for the kLine/kPick naming note (same
    applies here: kLine/kPick represent SPREAD, not a strikeout prop)."""
    v_games = []
    for idx, p in enumerate(picks):
        away = p.get('away', 'Away')
        home = p.get('home', 'Home')
        pick_team = p.get('pick', home)
        odds = p.get('odds', -110)
        model_prob = p.get('model_prob', 50) / 100.0
        edge = p.get('edge', 0) / 100.0

        if odds > 0:
            ml_price_dec = round((odds / 100) + 1, 3)
        else:
            ml_price_dec = round((100 / abs(odds)) + 1, 3)

        abbr_a = TEAM_ABBR.get(away, away[:3].upper())
        abbr_b = TEAM_ABBR.get(home, home[:3].upper())

        game_date_str = p.get('commence_time')
        start_at_ms = None
        time_display = 'TBD'
        date_display = ''
        if game_date_str:
            try:
                dt_utc = datetime.strptime(game_date_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                start_at_ms = int(dt_utc.timestamp() * 1000)
                dt_local = dt_utc.astimezone()
                if os.name != 'nt':
                    time_display = dt_local.strftime('%-I:%M %p')
                    date_display = dt_local.strftime('%a %b %-d')
                else:
                    time_display = dt_local.strftime('%I:%M %p').lstrip('0')
                    date_display = dt_local.strftime('%a %b %d').replace(' 0', ' ')
            except (ValueError, TypeError) as e:
                print(f"  NBA game_date parse failed ({game_date_str}): {e}")
        if start_at_ms is None:
            import time as _t
            start_at_ms = int(_t.time() * 1000)

        total = p.get('total')
        ou_pick = p.get('ou_pick', 'OVER')
        ou_edge = p.get('ou_edge', 0.0)
        if total is None:
            total = 224.5  # neutral NBA-scale placeholder ONLY when no
                            # bookmaker has posted a total yet.

        spread = p.get('spread', 0.0)
        spread_pick_side = abbr_b if spread <= 0 else abbr_a
        spread_pick_str = f"{spread_pick_side} {'+' if spread > 0 else ''}{spread}"
        spread_edge = round(edge * 0.4, 4)

        ml_fav = TEAM_ABBR.get(pick_team, pick_team[:3].upper()) if pick_team else abbr_b
        hot = edge > 0.03 or abs(ou_edge) > 0.05

        ou_price_dec = _american_to_decimal(p.get('ou_price'))
        spread_price_dec = _american_to_decimal(p.get('spread_price'))

        game = {
            'id': f'nba_live_{idx}_{int(datetime.now().timestamp())}',
            'a': abbr_a, 'b': abbr_b,
            'cityA': away, 'cityB': home,
            'lgA': 'NBA', 'lgB': 'NBA',
            'total': total, 'ouPick': f'{ou_pick} {total}',
            'kLine': spread, 'kPick': spread_pick_str,  # SPREAD ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â see _picks_to_nba_games docstring
            'mlFav': ml_fav, 'mlPriceDec': ml_price_dec,
            'ouEdge': round(ou_edge, 4), 'kEdge': spread_edge, 'mlEdge': round(edge, 4),
            'model': round(model_prob, 4),
            'tv': p.get('tv', 'ESPN+'), 'hot': hot,
            'startAt': start_at_ms, 'time': time_display, 'date': date_display,
            'status': 'live',
            'modelProb': round(model_prob, 3),
            'mlPriceAmerican': odds,
            'marketProb': round(1/ml_price_dec, 3) if ml_price_dec > 0 else 0.5,
            'qualifies': bool(p.get('qualifies', True)),
        }
        if ou_price_dec is not None:
            game['ouPriceDec'] = ou_price_dec
        if spread_price_dec is not None:
            game['kPriceDec'] = spread_price_dec
        for _col, _val in p.get("_edge_components", {}).items():
            game[_col] = round(_val, 4)
        v_games.append(game)
    return v_games


def export_to_html(picks: List, html_path: str) -> str:
    """Injects window.PARLAYOS_NBA_DATA at <!--PARLAYOS_NBA_INJECT_POINT-->.
    NOTE: ParlayOS.html currently only has a PARLAYOS_NFL_INJECT_POINT
    marker, not an NBA-specific one ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â see the ParlayOS.html changes in
    this same session for the added NBA marker. If that marker is ever
    removed, this falls back to injecting before </body>, same as
    nfl_ace.py's fallback."""
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
    except FileNotFoundError:
        print(f"Template not found: {html_path}")
        return ""

    v_games = _picks_to_nba_games(picks)
    games_json = json.dumps(v_games, separators=(',', ':'))
    run_date = datetime.now().strftime('%b %d %Y  %H:%M')
    pick_count = len(picks)

    html = re.sub(
        r'[ \t]*//[^\n]*PARLAYOS NBA LIVE DATA.*?[ \t]*//[^\n]*END PARLAYOS NBA LIVE DATA[^\n]*\n?',
        '', html, flags=re.DOTALL
    )
    html = re.sub(r'\n{3,}', '\n\n', html)

    injection_lines = [
        "    // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ PARLAYOS NBA LIVE DATA (" + run_date + ") ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬",
        "    window.PARLAYOS_NBA_DATA = {",
        "      runDate: \"" + run_date + "\",",
        "      pickCount: " + str(pick_count) + ",",
        "      games: " + games_json,
        "    };",
        "    (function(){",
        "      if(typeof loadRealData==='function') loadRealData();",
        "      if(typeof renderNBADashboard==='function') renderNBADashboard();",
        "    })();",
        "    // ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ END PARLAYOS NBA LIVE DATA ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬",
    ]
    injection = "\n".join(injection_lines)

    assert games_json in injection, "games_json missing from NBA injection!"

    MARKER = '    // <!--PARLAYOS_NBA_INJECT_POINT-->'
    if MARKER in html:
        html = html.replace(MARKER, MARKER + '\n' + injection)
        print(f"  NBA: injected at stable marker")
    else:
        html = html.replace('</body>', f'<script>\n{injection}\n</script>\n</body>')
        print(f"  NBA: marker not found, injected before </body> (fallback)")

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Å“ {pick_count} NBA picks ÃƒÂ¢Ã¢â‚¬ Ã¢â‚¬â„¢ {html_path}")
    return html_path


def run(html_path: str):
    """Main entry point ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â mirrors nfl_ace.py's run()."""
    config, api_key = load_config()
    engine = NBAPredictionEngine(api_key)
    odds_data = engine.fetch_live_odds()

    games = []
    seen_matchups = set()
    skipped_non_nba_team = []
    for game in odds_data:
        if len(game.get("bookmakers", [])) > 0:
            h2h = next((m for m in game["bookmakers"][0]["markets"] if m["key"] == "h2h"), None)
            if h2h:
                home = game["home_team"]
                away = game["away_team"]

                if home not in TEAM_ABBR or away not in TEAM_ABBR:
                    skipped_non_nba_team.append(f"{away} @ {home}")
                    continue

                matchup_key = (away, home)
                if matchup_key in seen_matchups:
                    continue
                seen_matchups.add(matchup_key)

                home_odds = next((o["price"] for o in h2h["outcomes"] if o["name"] == home), -110)
                away_odds = next((o["price"] for o in h2h["outcomes"] if o["name"] == away), 100)
                home_true, away_true = _devig_probs(home_odds, away_odds)
                market_prob = home_true

                home_abbr = TEAM_ABBR.get(home, home[:3].upper())
                away_abbr = TEAM_ABBR.get(away, away[:3].upper())

                real_total, over_price, under_price = None, None, None
                totals_mkt = next((m for m in game["bookmakers"][0]["markets"] if m["key"] == "totals"), None)
                if totals_mkt:
                    over_o = next((o for o in totals_mkt["outcomes"] if o["name"] == "Over"), None)
                    under_o = next((o for o in totals_mkt["outcomes"] if o["name"] == "Under"), None)
                    if over_o and "point" in over_o:
                        real_total = _f(over_o["point"])
                        over_price = over_o.get("price")
                    if under_o:
                        under_price = under_o.get("price")

                real_spread, spread_price = None, None
                spreads_mkt = next((m for m in game["bookmakers"][0]["markets"] if m["key"] == "spreads"), None)
                if spreads_mkt:
                    home_spread_o = next((o for o in spreads_mkt["outcomes"] if o["name"] == home), None)
                    if home_spread_o and "point" in home_spread_o:
                        real_spread = _f(home_spread_o["point"])
                        spread_price = home_spread_o.get("price")

                games.append({
                    "home": home, "away": away,
                    "home_abbr": home_abbr, "away_abbr": away_abbr,
                    "market_prob": market_prob, "odds": {"home": home_odds, "away": away_odds, "home_true": home_true, "away_true": away_true},
                    "real_total": real_total, "over_price": over_price,
                    "under_price": under_price, "real_spread": real_spread,
                    "spread_price": spread_price,
                    "commence_time": game.get("commence_time"),
                })

    if skipped_non_nba_team:
        print(f"  Skipped {len(skipped_non_nba_team)} non-NBA-team entries:")
        for s in skipped_non_nba_team:
            print(f"    - {s}")

    kelly_fraction = config.get("kelly_fraction", 0.25)

    def kelly_stake(prob, decimal_odds):
        if decimal_odds <= 1 or prob * decimal_odds <= 1:
            return 0.0
        full_kelly = (prob * decimal_odds - 1) / (decimal_odds - 1)
        return round(max(0.0, full_kelly) * kelly_fraction, 4)

    all_games_data = []
    for g in games:
        prob = engine.calculate_win_probability(g)
        implied = g["market_prob"]

        if prob >= 0.5:
            pick, pick_prob = g["home"], prob
            pick_odds = g["odds"].get("home", -110)
        else:
            pick, pick_prob = g["away"], 1 - prob
            pick_odds = g["odds"].get("away", 100)
        pick_implied = implied if pick == g["home"] else (1 - implied)
        edge = pick_prob - pick_implied
        pick_dec = (pick_odds/100)+1 if pick_odds > 0 else (100/abs(pick_odds))+1
        stake_frac = kelly_stake(pick_prob, pick_dec)

        posted_total = g.get("real_total") if g.get("real_total") is not None else 224.5
        ou_pick, model_total, ou_edge = engine.calculate_total_points(g, posted_total)

        print(f"{g['away']} @ {g['home']}: pick={pick}, prob={pick_prob:.3f}, "
              f"implied={pick_implied:.3f}, edge={edge:.3f}, "
              f"OU model={model_total} vs posted={posted_total} ({ou_pick}, edge={ou_edge:.3f})")

        game_data = {
            "home": g["home"], "away": g["away"], "pick": pick,
            "odds": pick_odds,
            "model_prob": round(pick_prob*100, 1), "edge": round(edge*100, 1),
            "edge_pct": round(edge*100, 1),
            "kelly_stake_pct": round(stake_frac*100, 2),
            "total": g.get("real_total") if g.get("real_total") is not None else model_total,
            "ou_pick": ou_pick, "ou_edge": ou_edge,
            "ou_price": g.get("over_price"),
            "spread": g.get("real_spread") if g.get("real_spread") is not None else 0.0,
            "spread_price": g.get("spread_price"),
            "commence_time": g.get("commence_time"),
            "kind": "team", "market": "Moneyline",
        }
        for _col, _val in g.get("_edge_components", {}).items():
            game_data[_col] = round(_val, 4)

        min_edge = config.get("min_edge", 0.0)
        min_total_line = config.get("min_total_line", 190.0)
        max_total_line = config.get("max_total_line", 250.0)
        edge_ok = edge >= min_edge
        real_total = g.get("real_total")
        line_ok = True if real_total is None else (min_total_line <= real_total <= max_total_line)
        game_data["qualifies"] = bool(edge_ok and line_ok)
        if not game_data["qualifies"]:
            reason = []
            if not edge_ok: reason.append(f"edge {edge*100:.1f}% < min {min_edge*100:.1f}%")
            if not line_ok: reason.append(f"total {real_total} outside {min_total_line}-{max_total_line}")
            print(f"    -> does not qualify ({'; '.join(reason)})")

        all_games_data.append(game_data)
        write_pick_to_log(game_data)

    export_to_html(all_games_data, html_path)
    qualifying = sum(1 for gd in all_games_data if gd["qualifies"])
    print(f"\nÃƒÂ¢Ã…â€œÃ¢â‚¬Å“ {len(all_games_data)} NBA games exported ({qualifying} qualify at current thresholds)")
    print(f"ÃƒÂ¢Ã…â€œÃ¢â‚¬Å“ Picks ÃƒÂ¢Ã¢â‚¬ Ã¢â‚¬â„¢ {PICKS_LOG_PATH}")
    return all_games_data


if __name__ == "__main__":
    candidates = ["parlayos.html", "parlayos_2.html", "ParlayOS.html", "parlayos_v6.html"]
    html_path = None
    for c in candidates:
        p = os.path.join(HERE, c)
        if os.path.exists(p):
            html_path = p
            break
    if html_path is None:
        print(f"No ParlayOS template found. Looked for: {candidates}")
    else:
        run(html_path)
