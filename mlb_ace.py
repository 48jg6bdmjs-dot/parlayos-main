import requests
import random
import itertools
import json
import csv
import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Tuple
import base64
import os
import re

# Team abbreviations to prevent text overlap
TEAM_ABBR = {
    'Arizona Diamondbacks': 'ARI', 'Atlanta Braves': 'ATL', 'Baltimore Orioles': 'BAL',
    'Boston Red Sox': 'BOS', 'Chicago Cubs': 'CHC', 'Chicago White Sox': 'CWS',
    'Cincinnati Reds': 'CIN', 'Cleveland Guardians': 'CLE', 'Colorado Rockies': 'COL',
    'Detroit Tigers': 'DET', 'Houston Astros': 'HOU', 'Kansas City Royals': 'KC',
    'Los Angeles Angels': 'LAA', 'Los Angeles Dodgers': 'LAD', 'Miami Marlins': 'MIA',
    'Milwaukee Brewers': 'MIL', 'Minnesota Twins': 'MIN', 'New York Mets': 'NYM',
    'New York Yankees': 'NYY', 'Oakland Athletics': 'OAK', 'Athletics': 'OAK',
    'Philadelphia Phillies': 'PHI', 'Pittsburgh Pirates': 'PIT', 'San Diego Padres': 'SD',
    'San Francisco Giants': 'SF', 'Seattle Mariners': 'SEA', 'St. Louis Cardinals': 'STL',
    'Tampa Bay Rays': 'TB', 'Texas Rangers': 'TEX', 'Toronto Blue Jays': 'TOR',
    'Washington Nationals': 'WSH'
}
# MLB Stats API team IDs (used for schedule fetching + logo URLs)
MLB_TEAM_IDS = {
    'ARI':109, 'ATL':144, 'BAL':110, 'BOS':111, 'CHC':112, 'CWS':145,
    'CIN':113, 'CLE':114, 'COL':115, 'DET':116, 'HOU':117, 'KC': 118,
    'LAA':108, 'LAD':119, 'MIA':146, 'MIL':158, 'MIN':142, 'NYM':121,
    'NYY':147, 'OAK':133, 'PHI':143, 'PIT':134, 'SD': 135, 'SF': 137,
    'SEA':136, 'STL':138, 'TB': 139, 'TEX':140, 'TOR':141, 'WSH':120,
}


# Ballpark coordinates — used so weather reflects the ACTUAL game location,
# not a hardcoded NYC default that was silently applied to every game.
STADIUM_LOCATIONS = {
    'ARI': (33.4453, -112.0667), 'ATL': (33.8907, -84.4677), 'BAL': (39.2838, -76.6217),
    'BOS': (42.3467, -71.0972), 'CHC': (41.9484, -87.6553), 'CWS': (41.8299, -87.6338),
    'CIN': (39.0975, -84.5061), 'CLE': (41.4962, -81.6852), 'COL': (39.7559, -104.9942),
    'DET': (42.3390, -83.0485), 'HOU': (29.7573, -95.3555), 'KC':  (39.0517, -94.4803),
    'LAA': (33.8003, -117.8827), 'LAD': (34.0739, -118.2400), 'MIA': (25.7781, -80.2196),
    'MIL': (43.0280, -87.9712), 'MIN': (44.9817, -93.2777), 'NYM': (40.7571, -73.8458),
    'NYY': (40.8296, -73.9262), 'OAK': (37.7516, -122.2005), 'PHI': (39.9057, -75.1665),
    'PIT': (40.4469, -80.0057), 'SD':  (32.7073, -117.1566), 'SF':  (37.7786, -122.3893),
    'SEA': (47.5914, -122.3325), 'STL': (38.6226, -90.1928), 'TB':  (27.7683, -82.6534),
    'TEX': (32.7473, -97.0842), 'TOR': (43.6414, -79.3894), 'WSH': (38.8730, -77.0074),
}


# Park factors — publicly published, stable multi-year run-scoring indices
# (100 = neutral; >100 favors offense, <100 favors pitching). These are
# well-established real baseball statistics, not estimates. Primarily
# used for the O/U total (park effects are roughly symmetric between the
# two competing offenses, so their influence on WHO wins is a much smaller,
# second-order effect vs. their large influence on total runs scored).
PARK_FACTORS = {
    'COL':112, 'CIN':105, 'BOS':104, 'TEX':103, 'PHI':102, 'BAL':102,
    'TOR':101, 'MIL':101, 'CHC':100, 'ARI':100, 'MIN':100, 'HOU':100,
    'LAA':99,  'WSH':99,  'ATL':99,  'NYY':99,  'CWS':98,  'KC':98,
    'STL':98,  'TB':97,   'CLE':97,  'DET':97,  'NYM':96,  'LAD':96,
    'SEA':95,  'PIT':95,  'SF':94,   'OAK':94,  'MIA':93,  'SD':92,
}

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "mlb_config.json")
OUTPUT_PATH = os.path.join(HERE, "index.html")
LEGACY_OUTPUT_PATH = os.path.join(HERE, "parlayos_dashboard.html")
LINE_HISTORY_PATH = os.path.join(HERE, "mlb_line_history.json")
# Drop file for the "Paste Slip" feature in parlayos.html: the browser can't
# write to disk directly, so the UI's "Download slip file" button saves this
# exact filename via a normal browser download. Moving/saving it into the
# same directory as mlb_ace.py is what connects the two — this script checks
# for it on every run, logs every leg found inside as a pick, then renames it
# to a timestamped .imported file so the same slip is never logged twice.
PENDING_SLIP_PATH = os.path.join(HERE, "pending_slip.txt")

# picks_log.csv and parlayos_picks.csv used to be two separate files written
# in parallel on every pick — picks_log.csv held the rich betting-tracker
# schema (CLV, slip results, Kelly stake, etc.), parlayos_picks.csv held a
# clean subset with team abbreviations for the UI. They'd drifted apart (some
# runs only wrote to one file, not both) and any downstream reader (backtest,
# UI) had to know which file had which columns. They're now merged into one
# file — picks_log.csv — that carries the full superset schema, including
# the abbr_home/abbr_away/abbr_pick columns parlayos_picks.csv used to own.
# PARLAYOS_LOG_PATH is kept as an alias pointing at the SAME file so any
# existing code (or a separate backtest script) that still references the
# old constant name keeps working without a second on-disk copy.
PICKS_LOG_PATH    = os.path.join(HERE, "picks_log.csv")
PARLAYOS_LOG_PATH = PICKS_LOG_PATH  # alias — single unified file now
PARLAYOS_LOG_COLS = ["timestamp","date","home","away","abbr_home","abbr_away","pick","abbr_pick","odds","model_prob","edge","home_pitcher","away_pitcher"]
# Individual edge-term values from calculate_win_probability, logged
# per-pick so mlb_fit_weights.py can eventually fit a real per-factor
# regression against graded outcomes instead of the hand-set constants
# below. Column names mirror EDGE_COMPONENT_COLS in mlb_fit_weights.py —
# keep both lists in sync if either changes.
EDGE_COMPONENT_COLS = [
    "c_team_edge", "c_pitcher_fip_edge", "c_pitcher_era_edge", "c_pitcher_whip_edge",
    "c_pitcher_k9_edge", "c_offense_edge", "c_bullpen_edge", "c_season_form_edge",
    "c_h2h_edge", "c_weather_edge", "c_rest_edge", "c_lineup_edge",
    "c_injury_edge", "c_fatigue_edge",
]
# Full column set for the unified log, in a stable, readable order. Any
# columns present in an existing on-disk file but not listed here are still
# preserved — this list only controls ordering for freshly written files.
PICKS_LOG_COLS = [
    "timestamp","date","home","away","abbr_home","abbr_away","pick","abbr_pick",
    "pitcher","home_pitcher","away_pitcher","odds","model_prob","edge","edge_pct",
    "qualifies","kelly_stake_pct","line","market","kind","team","tag",
    "open_ml","close_ml","clv_pts","won","profit_1u",
    "slip_id","slip_leg_num","slip_leg_count","slip_odds","slip_result","joint_prob","correlation",
] + EDGE_COMPONENT_COLS

def _find_v6_template():
    """Find ParlayOS template"""
    candidates = [
        "parlayos.html",    # user's primary template
        "parlayos_2.html",  # alternate name
        "ParlayOS.html",
        "parlayos_v6.html",
    ]
    for candidate in candidates:
        path = os.path.join(HERE, candidate)
        if os.path.exists(path):
            print(f"Template found: {path}")
            return path
    raise FileNotFoundError(f"No ParlayOS template found. Looked for: {candidates}")

PARLAYOS_TEMPLATE_PATH = _find_v6_template()

_HTML = """PGh0bWw+PGhlYWQ+PHRpdGxlPkFjZWJvdCBEYXNoYm9hcmQ8L3RpdGxlPjwvaGVhZD48Ym9keT48L2JvZHk+PC9odG1sPg=="""

ODDS_API_KEY = "16b0a233c6bbe7492dc168a1a46ec469"

# League-average fallbacks (2024 MLB) — used ONLY when a specific fetch
# fails, never silently substituted for a "successful" real value.
LEAGUE_AVG_ERA  = 4.25
LEAGUE_AVG_WHIP = 1.32
LEAGUE_AVG_K9   = 8.6
LEAGUE_AVG_FIP  = 4.10  # standard MLB league-average FIP, updated periodically
LEAGUE_AVG_OPS  = .720
MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"

def _f(s, d=None):
    """Lenient float parse — returns d (default None) instead of raising."""
    try:
        return float(str(s).strip())
    except (ValueError, TypeError, AttributeError):
        return d
WEATHER_API = "https://api.open-meteo.com/v1/forecast"
NUM_SIMULATIONS = 100000  # currently unused by calculate_win_probability (see its
                          # docstring — the Monte Carlo step this fed was the source
                          # of the overconfidence bug and was removed). Left as a
                          # config knob in case a real outcome-based simulation
                          # replaces it later; changing n_sims in config has no
                          # effect on picks right now.

# ── Simple file cache (TTL-based) — team/pitcher stats don't change
# meaningfully within a few hours, so caching cuts redundant API calls
# substantially on a script that fetches per-game, per-pitcher, per-team.
import pickle
from time import time as _time

CACHE_DIR = os.path.join(HERE, ".mlb_cache")

def get_cached(key, ttl=3600, required_keys=None):
    """
    required_keys: if given, a cached dict missing ANY of these keys is
    treated as a cache miss rather than trusted as-is. This is what should
    have existed from the start — without it, adding a new field to a
    cached shape (e.g. the has_data flags) causes old on-disk cache entries
    from a prior run to silently reappear with the OLD shape and raise a
    KeyError deep inside code that assumes the NEW shape is guaranteed.
    """
    path = os.path.join(CACHE_DIR, f"{key}.pkl")
    try:
        if os.path.exists(path) and _time() - os.path.getmtime(path) < ttl:
            with open(path, 'rb') as f:
                data = pickle.load(f)
            if required_keys and isinstance(data, dict):
                if not all(k in data for k in required_keys):
                    return None  # stale schema — treat as a miss, will be re-fetched
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
    """
    Load mlb_config.json — including the thresholds mlb_backtest.py tunes
    from realised results. These were previously loaded, printed, and then
    NEVER used: min_edge was explicitly commented "Disabled" and every game
    was force-set to qualifies=True regardless of edge; min_total_line/
    max_total_line weren't even read. That meant mlb_backtest.py's tuning
    was write-only — it updated mlb_config.json based on real performance,
    but nothing downstream ever read those two keys back into a filtering
    decision, so the tuning had no effect on which picks were shown. All
    three are now actually applied to the qualifies flag in the main loop
    below.
    """
    global NUM_SIMULATIONS
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
            if "edge_threshold" in cfg and "min_edge" not in cfg:
                cfg["min_edge"] = cfg["edge_threshold"]
            if "n_sims" in cfg:
                NUM_SIMULATIONS = cfg["n_sims"]
            cfg.setdefault("min_edge", 0.0)
            cfg.setdefault("min_total_line", 6.0)
            cfg.setdefault("max_total_line", 13.5)
            cfg.setdefault("max_legs", 16)
            cfg.setdefault("kelly_fraction", 0.25)
            cfg.setdefault("max_stake_pct", 0.05)
            print(f"Config loaded: min_edge={cfg['min_edge']}, "
                  f"total_line_band={cfg['min_total_line']}-{cfg['max_total_line']}, "
                  f"n_sims={NUM_SIMULATIONS}")
            return cfg
    except FileNotFoundError:
        print("mlb_config.json not found, using defaults")
        return {"min_edge": 0.0, "min_total_line": 6.0, "max_total_line": 13.5,
                "max_legs": 16, "kelly_fraction": 0.25, "max_stake_pct": 0.05}

class PredictionEngine:
    def __init__(self, api_key: str):
        self.api_key = api_key
        print(f"Engine initialized with API key: {api_key[:8]}...")
    
    def fetch_live_odds(self) -> List:
        """
        Fetch live MLB odds from The Odds API.
        Now requests BOTH h2h (moneyline) and totals (O/U) markets — the O/U
        total line shown in the UI and used to gate qualifies was previously
        pure random.random() with zero connection to a real posted line.
        Requesting "totals" here is what makes a real line available to
        parse in the main loop / _picks_to_v6_games below.
        """
        url = "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"
        params = {"apiKey": self.api_key, "regions": "us", "markets": "h2h,totals", "oddsFormat": "american"}
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            print(f"Odds API returned {len(data)} games")
            return data
        except Exception as e:
            print(f"Odds API error: {e}")
            return []
    
    def fetch_team_form(self, team_id: int, opp_id: int) -> Dict:
        """
        Fetch real team form from MLB Stats API. Every field below is a real
        API-derived number — the previous version returned three of four
        fields as hardcoded constants (4.5, 0.5, 4.0) regardless of team,
        which silently canceled their contribution to the model (both teams
        always got identical fake values, so the edge from these factors
        was always exactly zero). League-average fallbacks are used ONLY
        when the specific API call fails, and are clearly labeled as such.
        """
        if not team_id:
            return {"last_10_wl": 0.5, "runs_per_game": 4.5, "h2h_pct": 0.5, "team_era": 4.25,
                    "last10_has_data": False, "runs_has_data": False, "era_has_data": False}
        cache_key = f"team_form_v2_{team_id}_{opp_id}"  # v2: schema now includes has_data flags
        cached = get_cached(cache_key, ttl=3600,
                             required_keys=("last_10_wl","runs_per_game","h2h_pct","team_era",
                                            "last10_has_data","runs_has_data","era_has_data"))
        if cached is not None:
            return cached

        # Last-10 record + real runs/game from season hitting totals.
        # has_data flags let calculate_win_probability skip a comparison
        # entirely rather than pit a real number against a neutral fallback
        # on the other side (the exact bug that made the model favor a team
        # whose starter had zero real stats over an opponent with a real,
        # merely below-average one).
        last_10_wl = 0.5
        runs_per_game = 4.5
        last10_has_data = False
        runs_has_data = False
        try:
            r = requests.get(f"{MLB_STATS_BASE}/teams/{team_id}/stats",
                              params={"stats": "gameLog", "season": datetime.now().year, "group": "hitting"},
                              timeout=8)
            splits = r.json()["stats"][0]["splits"][-10:]
            if splits:
                wins = sum(1 for g in splits if g.get("isWin"))
                last_10_wl = wins / len(splits)
                last10_has_data = True
        except Exception as e:
            print(f"  team gameLog fetch failed ({team_id}): {e}")
        try:
            r2 = requests.get(f"{MLB_STATS_BASE}/teams/{team_id}/stats",
                               params={"stats": "season", "season": datetime.now().year, "group": "hitting"},
                               timeout=8)
            s = r2.json()["stats"][0]["splits"][0]["stat"]
            games_played = float(s.get("gamesPlayed", 0) or 0)
            runs = float(s.get("runs", 0) or 0)
            if games_played > 0:
                runs_per_game = round(runs / games_played, 2)
                runs_has_data = True
        except Exception as e:
            print(f"  team season hitting fetch failed ({team_id}): {e}")

        # Real team ERA (proxy for pitching strength — true bullpen-only ERA
        # would need reliever-specific split filtering, noted as a known
        # simplification rather than faked precision)
        team_era = 4.25
        era_has_data = False
        try:
            r3 = requests.get(f"{MLB_STATS_BASE}/teams/{team_id}/stats",
                               params={"stats": "season", "season": datetime.now().year, "group": "pitching"},
                               timeout=8)
            s3 = r3.json()["stats"][0]["splits"][0]["stat"]
            team_era = round(float(s3.get("era", 4.25) or 4.25), 2)
            era_has_data = True
        except Exception as e:
            print(f"  team season pitching fetch failed ({team_id}): {e}")

        # Real head-to-head win% this season vs this specific opponent
        h2h_pct = 0.5
        try:
            season_start = f"{datetime.now().year}-01-01"
            today = datetime.now().strftime("%Y-%m-%d")
            r4 = requests.get(f"{MLB_STATS_BASE}/schedule",
                               params={"sportId": 1, "teamId": team_id, "startDate": season_start,
                                       "endDate": today, "gameType": "R"}, timeout=8)
            h2h_games = []
            for de in r4.json().get("dates", []):
                for gm in de.get("games", []):
                    ht = gm["teams"]["home"]["team"].get("id")
                    at = gm["teams"]["away"]["team"].get("id")
                    if opp_id not in (ht, at): continue
                    if gm.get("status", {}).get("codedGameState") not in ["F","O","FR"]: continue
                    is_home = ht == team_id
                    my_score = gm["teams"]["home" if is_home else "away"].get("score", 0) or 0
                    opp_score = gm["teams"]["away" if is_home else "home"].get("score", 0) or 0
                    h2h_games.append(my_score > opp_score)
            if h2h_games:
                h2h_pct = round(sum(h2h_games) / len(h2h_games), 3)
        except Exception as e:
            print(f"  head-to-head fetch failed ({team_id} vs {opp_id}): {e}")

        result = {"last_10_wl": last_10_wl, "runs_per_game": runs_per_game, "h2h_pct": h2h_pct, "team_era": team_era,
                  "last10_has_data": last10_has_data, "runs_has_data": runs_has_data, "era_has_data": era_has_data}
        set_cache(cache_key, result)
        return result
    
    def fetch_pitcher_stats(self, pitcher_id: int) -> Dict:
        """
        Fetch real pitcher stats from MLB Stats API, cached by pitcher ID.
        Includes has_data: False whenever a league-average fallback is used
        (no pitcher_id, empty splits, or a fetch error) — this flag matters:
        a rookie/call-up/return-from-IL pitcher with genuinely no stats this
        season is NOT the same as "exactly league average," and comparing a
        fabricated average against the opponent's real (possibly below-
        average) number silently biased picks toward whichever side had the
        missing data. calculate_win_probability() checks this flag before
        using the comparison at all.
        """
        if not pitcher_id:
            return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "k_per_9": LEAGUE_AVG_K9,
                    "fip": LEAGUE_AVG_FIP, "has_data": False}
        cache_key = f"pitcher_stats_v4_{pitcher_id}"  # v4: schema now includes shrunk small-sample stats
        cached = get_cached(cache_key, ttl=3600,
                             required_keys=("era","whip","k_per_9","fip","has_data"))
        if cached is not None:
            return cached
        try:
            r = requests.get(f"{MLB_STATS_BASE}/people/{pitcher_id}/stats",
                              params={"stats": "season", "season": datetime.now().year, "group": "pitching"},
                              timeout=8)
            splits = r.json()["stats"][0]["splits"]
            if not splits:
                return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "k_per_9": LEAGUE_AVG_K9,
                        "fip": LEAGUE_AVG_FIP, "has_data": False}
            stat = splits[0]["stat"]
            innings = float(stat.get("inningsPitched", 0) or 0)
            if innings < 5:
                # Fewer than 5 IP this season is too small a sample to trust —
                # treat the same as "no data" rather than let a tiny, noisy
                # sample swing the model.
                return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "k_per_9": LEAGUE_AVG_K9,
                        "fip": LEAGUE_AVG_FIP, "has_data": False}

            # FIP (Fielding Independent Pitching) — a real, standard sabermetric
            # stat that isolates outcomes a pitcher fully controls (HR, BB, HBP,
            # K), removing defense/sequencing luck that ERA doesn't separate
            # out. Generally considered MORE predictive of a pitcher's true
            # talent than ERA alone. The +3.10 constant is the standard
            # league-normalization term (varies slightly year to year around
            # 3.0-3.2; 3.10 is the commonly used static approximation).
            hr  = int(stat.get("homeRuns", 0) or 0)
            bb  = int(stat.get("baseOnBalls", 0) or 0)
            hbp = int(stat.get("hitByPitch", 0) or 0)
            k   = int(stat.get("strikeOuts", 0) or 0)
            fip_raw  = ((13*hr + 3*(bb+hbp) - 2*k) / innings) + 3.10
            era_raw  = float(stat.get("era", LEAGUE_AVG_ERA) or LEAGUE_AVG_ERA)
            whip_raw = float(stat.get("whip", LEAGUE_AVG_WHIP) or LEAGUE_AVG_WHIP)
            k9_raw   = float(stat.get("strikeoutsPer9Inn", LEAGUE_AVG_K9) or LEAGUE_AVG_K9)

            # ── Small-sample shrinkage — the previous rule was a hard cliff
            #    at 5 IP: below it, league average; at or above it, the RAW
            #    number got full weight, identical to a full, reliable season.
            #    That cliff is exactly how the model could "lean on bad
            #    pitchers" — a starter with one or two rough outings (e.g.
            #    13 IP at a 9.00 ERA, coming off injury) clears 5 IP easily
            #    and then gets treated as seriously as a pitcher with 100+
            #    trustworthy innings, letting one bad start swing a pick as
            #    hard as a real season-long form would.
            #
            #    Fix: regress every real sample toward league average,
            #    weighted by how much of a "fully reliable" season it
            #    represents (standard empirical-Bayes shrinkage). Reliability
            #    now grows smoothly with innings pitched instead of snapping
            #    from 0% to 100% at one arbitrary cutoff. ~60 IP (roughly
            #    10-12 starts) is treated as fully reliable for an in-season
            #    read; anything below that blends toward league average in
            #    proportion to how small the sample actually is.
            FULL_RELIABILITY_IP = 60.0
            reliability = min(1.0, innings / FULL_RELIABILITY_IP)

            def shrink(raw, league_avg):
                return round(reliability * raw + (1 - reliability) * league_avg, 2)

            result = {
                "era": shrink(era_raw, LEAGUE_AVG_ERA),
                "whip": shrink(whip_raw, LEAGUE_AVG_WHIP),
                "k_per_9": shrink(k9_raw, LEAGUE_AVG_K9),
                "fip": shrink(fip_raw, LEAGUE_AVG_FIP),
                "has_data": True,
                "sample_ip": innings,
                "reliability": round(reliability, 2),
            }
            set_cache(cache_key, result)
            return result
        except Exception as e:
            print(f"  pitcher stat fetch failed ({pitcher_id}): {e}")
            return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "k_per_9": LEAGUE_AVG_K9,
                    "fip": LEAGUE_AVG_FIP, "has_data": False}
    
    def fetch_weather(self, lat: float, lon: float) -> Dict:
        """Fetch weather for the ACTUAL game's coordinates, cached ~30min."""
        cache_key = f"weather_{round(lat,2)}_{round(lon,2)}"
        cached = get_cached(cache_key, ttl=1800)
        if cached is not None:
            return cached
        try:
            r = requests.get(WEATHER_API, params={"latitude": lat, "longitude": lon,
                              "current": "temperature_2m,wind_speed_10m,wind_direction_10m"}, timeout=8)
            w = r.json()["current"]
            result = {
                "temp_f": w["temperature_2m"] * 9/5 + 32,
                "wind_mph": w["wind_speed_10m"] * 0.621371,
                "wind_deg": w["wind_direction_10m"],
            }
            set_cache(cache_key, result)
            return result
        except Exception as e:
            print(f"  weather fetch failed ({lat},{lon}): {e}")
            return {"temp_f": 75, "wind_mph": 5, "wind_deg": 0}
    
    def calculate_win_probability(self, game: Dict) -> float:
        """
        Calculate win probability using MLB Stats API data.
        Requires game["home_id"]/["away_id"]/["home_pitcher_id"]/["away_pitcher_id"]
        to be REAL MLB IDs (0 or missing IDs cause both sides' lookups to fail
        identically, silently zeroing out edges — a real bug from an earlier
        version where the caller passed hardcoded 0s for every game).

        Every factor below only contributes when BOTH sides have real data
        for that specific comparison (has_data flags) — a missing value is
        never compared against a fallback, which previously let an unknown
        pitcher look "average" against a real, below-average opponent and
        silently tilt picks toward whichever side had less data.
        """
        home_form = self.fetch_team_form(game["home_id"], game["away_id"])
        away_form = self.fetch_team_form(game["away_id"], game["home_id"])
        home_p = self.fetch_pitcher_stats(game["home_pitcher_id"])
        away_p = self.fetch_pitcher_stats(game["away_pitcher_id"])
        weather = self.fetch_weather(game.get("lat", 40.0), game.get("lon", -74.0))
        home_bat = fetch_real_team_batting(game["home_id"])
        away_bat = fetch_real_team_batting(game["away_id"])

        # ── Starting pitcher quality — the single most predictive factor
        #    for an individual MLB game. FIP, ERA, WHIP, and K/9 each
        #    capture a different real dimension. FIP (Fielding Independent
        #    Pitching) isolates outcomes the pitcher fully controls (HR,
        #    BB, HBP, K) and removes defense/sequencing luck that ERA
        #    bakes in — generally regarded as MORE predictive of a
        #    pitcher's true talent than ERA, so it now carries the largest
        #    single weight, with ERA still contributing a smaller amount
        #    (ERA does capture some real signal ERA-only models miss, even
        #    if noisier). Weights were previously fixed from an earlier
        #    miscalibration where team form (0.35) was weighted ~12x more
        #    than starting pitcher ERA (0.03) — a team's generic last-10
        #    record (a mix of ALL their different starters) could
        #    completely swamp a massive, real quality gap between TODAY's
        #    two actual starters, which is backwards.
        has_pitchers = home_p["has_data"] and away_p["has_data"]
        pitcher_fip_edge  = (away_p["fip"]  - home_p["fip"])  * 0.12 if has_pitchers else 0.0
        pitcher_era_edge  = (away_p["era"]  - home_p["era"])  * 0.04 if has_pitchers else 0.0
        pitcher_whip_edge = (away_p["whip"] - home_p["whip"]) * 0.05 if has_pitchers else 0.0
        pitcher_k9_edge   = (home_p["k_per_9"] - away_p["k_per_9"]) * 0.01 if has_pitchers else 0.0

        # ── Team offense (OPS) — previously fetched (fetch_real_team_batting)
        #    for DISPLAY only and never used in the model at all. A great
        #    starting pitcher means little if the team's own lineup can't
        #    score; ignoring offense meant the model was effectively
        #    pitching-only, blind to half the game.
        has_offense = bool(home_bat) and bool(away_bat)
        offense_edge = 0.0
        if has_offense:
            try:
                home_ops = float(home_bat.get("ops", ".700") or ".700")
                away_ops = float(away_bat.get("ops", ".700") or ".700")
                offense_edge = (home_ops - away_ops) * 0.55
            except (ValueError, TypeError):
                has_offense = False

        # ── Team form / bullpen / recent run production ──
        team_edge = ((home_form["last_10_wl"] - away_form["last_10_wl"]) * 0.10
                     if home_form["last10_has_data"] and away_form["last10_has_data"] else 0.0)

        # Bullpen quality — prefers the relief-ONLY FIP split (isolates the
        # pen's own peripherals from starters' innings), a genuinely distinct
        # signal from team-wide season stats. Falls back to season team ERA
        # only when the relief-only sample is too small.
        home_bp = fetch_bullpen_stats(game["home_id"])
        away_bp = fetch_bullpen_stats(game["away_id"])
        bullpen_fip_available = home_bp["has_data"] and away_bp["has_data"]
        if bullpen_fip_available:
            bullpen_edge = (away_bp["fip"] - home_bp["fip"]) * 0.05

        # ── Season run differential (offense + pitching combined) ──
        #    runs_per_game (season offense) and team_era (season pitching,
        #    used here only as bullpen_edge's FALLBACK) were previously two
        #    separately-weighted terms — but a team's season runs-scored and
        #    season runs-allowed are the two halves of the SAME fact: full-
        #    season run differential, the standard single best full-season
        #    proxy for team quality. Adding them independently double-counted
        #    that one fact instead of treating it as one signal.
        #
        #    Note this also partially (not fully) overlaps with offense_edge
        #    above, which already captures season-long offense via OPS —
        #    runs_per_game and OPS are correlated (both are "is this offense
        #    good," just measured differently: OPS is context-free hitting
        #    quality, runs/game folds in lineup construction, opponents
        #    already faced, and park effects). They're not the same number,
        #    so this isn't collapsed into offense_edge entirely, but the
        #    weight here is kept modest specifically because offense_edge is
        #    already carrying most of the "how good is this offense" signal;
        #    this term's real incremental job is the PITCHING half (season
        #    ERA, which nothing else covers when bullpen FIP is unavailable).
        has_season_offense = home_form["runs_has_data"] and away_form["runs_has_data"]
        has_season_pitching = home_form["era_has_data"] and away_form["era_has_data"]
        if has_season_offense and has_season_pitching:
            home_run_diff = home_form["runs_per_game"] - home_form["team_era"]
            away_run_diff = away_form["runs_per_game"] - away_form["team_era"]
            season_form_edge = (home_run_diff - away_run_diff) * 0.035
        elif has_season_offense:
            # Offense-only fallback (no season ERA available) — weight cut
            # from the original runs_edge's 0.02 to 0.012, since offense_edge
            # (OPS) above already covers most of this same "season offense
            # quality" signal on its own, larger weight (0.55 on an OPS-scale
            # difference, which is a much bigger per-point move than runs/
            # game). This branch's remaining job is just the residual signal
            # OPS doesn't fully capture (actual run production vs raw hitting
            # rate), not to re-assert the whole offense signal a second time.
            season_form_edge = (home_form["runs_per_game"] - away_form["runs_per_game"]) * 0.012
        elif has_season_pitching:
            season_form_edge = (away_form["team_era"] - home_form["team_era"]) * 0.025
        else:
            season_form_edge = 0.0

        if not bullpen_fip_available:
            # No real relief-only data — season_form_edge above already
            # carries the season-ERA signal, so bullpen_edge stays at 0
            # rather than adding that same season-ERA fact a second time
            # under a different name.
            bullpen_edge = 0.0

        h2h_edge = (home_form["h2h_pct"] - 0.5) * 0.05  # naturally 0 when no h2h games exist yet

        # ── Weather: temperature gets a real, modest directional term (warm
        #    air carries fly balls further, aiding offense broadly for both
        #    teams roughly equally — that symmetry is why it's small and
        #    unsigned toward either side). Wind speed deliberately does NOT
        #    get a directional win-probability term: without knowing each
        #    park's precise orientation relative to today's wind direction,
        #    assigning wind an advantage to one specific team would be
        #    fabricating a signal I can't actually verify. High wind DOES
        #    real-world increase a game's unpredictability, but doing that
        #    properly needs an actual outcome simulation (run distributions,
        #    not a probability-threshold trick — see the note below), so
        #    it's left out for now rather than faked.
        weather_edge = 0.02 if weather["temp_f"] > 80 else (-0.02 if weather["temp_f"] < 50 else 0)

        home_field_edge = 0.02  # standard, well-established real MLB home-field advantage

        # ── Rest/fatigue — real signal from the schedule API, no scraping
        #    needed. Zero-rest teams (played yesterday) carry a modest real
        #    disadvantage vs a rested opponent. Symmetric and small: this is
        #    a secondary factor, not decisive on its own.
        home_rest = fetch_team_rest_status(game["home_id"])
        away_rest = fetch_team_rest_status(game["away_id"])
        rest_edge = 0.0
        if away_rest["played_yesterday"] and not home_rest["played_yesterday"]:
            rest_edge = 0.015
        elif home_rest["played_yesterday"] and not away_rest["played_yesterday"]:
            rest_edge = -0.015

        # ── Lineup handedness (platoon advantage) — scraped from Rotowire's
        #    daily lineups, since the MLB Stats API doesn't expose who's
        #    ACTUALLY confirmed to start today. Batters generally perform
        #    somewhat better against opposite-handed pitching; a lineup
        #    stacked with same-handed bats against today's starter is a
        #    small real disadvantage. Gated to 0 if the scrape fails or
        #    lineups aren't posted yet (normal until a few hours before
        #    game time) — never guessed at.
        tid2abbr = {v: k for k, v in MLB_TEAM_IDS.items()}
        home_abbr = tid2abbr.get(game["home_id"], "")
        away_abbr = tid2abbr.get(game["away_id"], "")
        lineup_edge = 0.0
        if home_abbr and away_abbr:
            lineups = fetch_lineup_handedness(away_abbr, home_abbr)
            home_hand = fetch_pitcher_hand(game["home_pitcher_id"])
            away_hand = fetch_pitcher_hand(game["away_pitcher_id"])
            if lineups and home_hand and away_hand:
                # Home lineup facing away pitcher's hand
                home_same = lineups["home_L"] if away_hand == "L" else lineups["home_R"]
                home_opp  = lineups["home_R"] if away_hand == "L" else lineups["home_L"]
                # Away lineup facing home pitcher's hand
                away_same = lineups["away_L"] if home_hand == "L" else lineups["away_R"]
                away_opp  = lineups["away_R"] if home_hand == "L" else lineups["away_L"]
                home_platoon = (home_opp - home_same) / 9.0   # -1..1, positive = favorable
                away_platoon = (away_opp - away_same) / 9.0
                lineup_edge = (home_platoon - away_platoon) * 0.025

        # ── Injury burden — scraped from MLB.com's official injury report.
        #    Coarse (headline count per team, not precise player-by-player
        #    IL tracking) but real and live. Gated to 0 if either team's
        #    section can't be found on the page.
        injury_edge = 0.0
        if home_abbr and away_abbr:
            home_full = next((k for k, v in TEAM_ABBR.items() if v == home_abbr), "")
            away_full = next((k for k, v in TEAM_ABBR.items() if v == away_abbr), "")
            if home_full and away_full:
                home_inj = fetch_team_injury_count(home_full)
                away_inj = fetch_team_injury_count(away_full)
                if home_inj and away_inj:
                    injury_edge = (away_inj["headline_count"] - home_inj["headline_count"]) * 0.004
                    injury_edge = max(-0.03, min(0.03, injury_edge))  # cap a coarse signal's influence

        # ── Bullpen fatigue — prefers real reliever pitch-count load from
        #    the last 2 days' boxscores over the coarse played-yesterday
        #    proxy, falling back to that proxy when boxscore data isn't
        #    available for either side.
        home_load = fetch_bullpen_pitch_load(game["home_id"])
        away_load = fetch_bullpen_pitch_load(game["away_id"])
        if home_load["has_data"] and away_load["has_data"]:
            # ~150 pitches over 2 days ≈ a genuinely heavy bullpen workload;
            # scaled and capped small since day-to-day usage is noisy and
            # this should nudge the model, not dominate it.
            load_diff = (away_load["pitches"] - home_load["pitches"]) / 150.0
            fatigue_edge = max(-0.02, min(0.02, load_diff * 0.02))
        else:
            home_fatigue = fetch_bullpen_fatigue(game["home_id"])
            away_fatigue = fetch_bullpen_fatigue(game["away_id"])
            fatigue_edge = (home_fatigue - away_fatigue) * 0.02

        base_prob = (0.5 + team_edge + pitcher_fip_edge + pitcher_era_edge + pitcher_whip_edge
                     + pitcher_k9_edge + offense_edge + bullpen_edge + season_form_edge + h2h_edge
                     + weather_edge + home_field_edge + rest_edge + lineup_edge + injury_edge
                     + fatigue_edge + (game["market_prob"] - 0.5) * 0.15)

        # ── Final probability = base_prob itself, clamped to a sane range.
        #
        #    Every edge term above was designed as a direct percentage-point
        #    nudge off a 50/50 baseline (that's what weights like *0.12,
        #    *0.10, *0.05 mean), so base_prob already IS the model's
        #    probability estimate — nothing further should be done to it.
        #
        #    The PREVIOUS version instead ran base_prob through
        #    NUM_SIMULATIONS draws of random.gauss(base_prob, sim_std) and
        #    counted how often the draw exceeded 0.5. That's mathematically
        #    just the normal CDF Φ((base_prob-0.5)/sim_std) computed the
        #    slow way — and because sim_std (~0.08) is SMALL relative to
        #    how far base_prob can drift once a dozen-plus edge terms
        #    stack in the same direction, that CDF saturates fast: a
        #    base_prob of 0.60 (a real, defensible ~10-point edge) became
        #    Φ(0.10/0.08) ≈ 89%, and 0.65 became ≈ 97%. THIS is what was
        #    producing picks that clustered at "95.0% model" with 30-40%+
        #    edges — a moderate, legitimate edge was being mathematically
        #    amplified into manufactured near-certainty by the simulation
        #    step itself, not by any single input claiming 95%.
        #
        #    Real single-game MLB win probabilities are almost never
        #    outside ~15-85% even for a genuine ace-vs-replacement
        #    mismatch — nine innings carries enormous inherent variance
        #    that no quality gap fully erases. The clamp below is a
        #    sanity bound, not a substitute for real calibration (that
        #    still needs backtesting against actual outcomes, which this
        #    script doesn't do — flagged previously as separate, larger
        #    work). If these bounds feel too wide or too narrow once you
        #    see it against real results, they're just two numbers here.

        # Stash each individual edge term on the game dict (mutable, passed
        # by reference) so the caller can log them per-pick for
        # mlb_fit_weights.py's eventual full multi-factor regression,
        # without changing this function's return type or touching any
        # call site. Every one of these already exists as a local variable
        # above — this just makes them visible outside the function too.
        game["_edge_components"] = {
            "c_team_edge": team_edge, "c_pitcher_fip_edge": pitcher_fip_edge,
            "c_pitcher_era_edge": pitcher_era_edge, "c_pitcher_whip_edge": pitcher_whip_edge,
            "c_pitcher_k9_edge": pitcher_k9_edge, "c_offense_edge": offense_edge,
            "c_bullpen_edge": bullpen_edge, "c_season_form_edge": season_form_edge,
            "c_h2h_edge": h2h_edge, "c_weather_edge": weather_edge, "c_rest_edge": rest_edge,
            "c_lineup_edge": lineup_edge, "c_injury_edge": injury_edge, "c_fatigue_edge": fatigue_edge,
        }
        return max(0.15, min(0.85, base_prob))

def generate_parlays(picks: List, max_legs: int = 3) -> List:
    if not picks or len(picks) < 2:
        return []
    parlays = []
    for r in range(2, min(max_legs, len(picks)) + 1):
        for combo in itertools.combinations(picks, r):
            combined_decimal = 1.0
            total_edge = 0.0
            valid = True
            for pick in combo:
                odds = pick.get('odds', 0)
                if odds == 0:
                    valid = False
                    break
                decimal = (odds / 100) + 1 if odds > 0 else (100 / abs(odds)) + 1
                combined_decimal *= decimal
                total_edge += pick.get('edge', 0)
            if not valid:
                continue
            american_odds = int((combined_decimal - 1) * 100) if combined_decimal >= 2.0 else int(-100 / (combined_decimal - 1))
            parlays.append({'legs': len(combo), 'picks': list(combo), 'odds': american_odds, 'total_edge': round(total_edge, 1), 'edge_per_leg': round(total_edge / len(combo), 1)})
    return sorted(parlays, key=lambda x: x['total_edge'], reverse=True)

def load_picks_log():
    """
    Load the single unified picks_log.csv. Tolerant of an old-schema file
    (missing abbr_* columns, or any other column absent from PICKS_LOG_COLS)
    — missing columns are added as empty rather than raising, since a
    backtest script reading this same file shouldn't break just because a
    column was added later.
    """
    try:
        df = pd.read_csv(PICKS_LOG_PATH)
        for col in PICKS_LOG_COLS:
            if col not in df.columns:
                df[col] = pd.NA
        return df
    except Exception:
        return pd.DataFrame(columns=PICKS_LOG_COLS)

def _abbr(name: str) -> str:
    if not name:
        return name
    return TEAM_ABBR.get(name, str(name)[:3].upper())

def write_pick_to_log(pick_dict: dict):
    """
    Single writer for every pick — replaces the old pair of
    write_pick_to_log() + write_parlayos_pick(), which wrote the SAME pick
    to two different files (picks_log.csv with the full tracker schema,
    parlayos_picks.csv with just team abbreviations) and had drifted apart
    because some code paths only called one of the two. Now there is one
    file and one write path; abbr_home/abbr_away/abbr_pick are always
    derived and included so the UI's need for team abbreviations is met
    from the same row the backtest/tracker columns live on.
    """
    log = load_picks_log()
    pick_dict = dict(pick_dict)  # don't mutate caller's dict
    pick_dict.setdefault("timestamp", datetime.now().isoformat())
    pick_dict.setdefault("date", datetime.now().strftime("%Y-%m-%d"))
    home, away, pick = pick_dict.get("home", ""), pick_dict.get("away", ""), pick_dict.get("pick", "")
    pick_dict.setdefault("abbr_home", _abbr(home))
    pick_dict.setdefault("abbr_away", _abbr(away))
    pick_dict.setdefault("abbr_pick", _abbr(pick))
    log = pd.concat([log, pd.DataFrame([pick_dict])], ignore_index=True)
    log.to_csv(PICKS_LOG_PATH, index=False)


def write_parlayos_pick(g: dict):
    """
    Back-compat shim — older code (or a separate backtest script) may still
    call write_parlayos_pick() by name. It now just delegates to the single
    unified writer above instead of writing a second file, so nothing
    duplicates and nothing drifts out of sync again.
    """
    write_pick_to_log(g)


# ─────────────────────────────────────────────────────────────────────────
# PASTE SLIP IMPORT
# ─────────────────────────────────────────────────────────────────────────
# parlayos.html's "Paste Slip" panel parses pasted slip text client-side for
# an instant preview, then offers a "Download slip file" button that saves
# pending_slip.txt via a normal browser download (a static HTML page can't
# write to disk directly). Moving that file into the same directory as this
# script is what connects the two. Every run checks for it and logs
# whatever legs it can parse, then archives the file so nothing is ever
# double-logged. The parser here is intentionally independent from the
# browser-side one — they don't share code — so it's re-documented in full
# rather than assumed to match; if the two drift, this is the one that
# actually decides what lands in picks_log.csv.

_AMERICAN_ODDS_RE = re.compile(r'(?<![\d.])([+-]\d{3,4})(?![\d.])')
_OU_RE = re.compile(r'\b(OVER|UNDER)\s+(\d+(?:\.\d+)?)', re.IGNORECASE)
_K_PROP_RE = re.compile(r'\b(\d+(?:\.\d+)?)\s*K\b', re.IGNORECASE)
_MATCHUP_RE = re.compile(r'\b([A-Z]{2,4})\s*@\s*([A-Z]{2,4})\b')

# ── Anchor-based parser ──────────────────────────────────────────────────
# A real sportsbook slip copy/paste (tested against actual DraftKings/
# FanDuel-style "My Bets" screens) puts EACH leg's pick description,
# market keyword, and odds on three SEPARATE lines, with NO blank line
# between one leg and the next — the whole slip is one continuous block:
#   PIT Pirates
#   Moneyline
#   -126
#   BAL Orioles
#   Moneyline
#   -156
#   ...
# An earlier version of this parser split on blank lines, which is wrong
# for this — a real slip pasted this way produced ZERO recognized legs
# (every line looked like an isolated fragment with no odds attached).
# The fix: don't try to find where one leg "block" ends and the next
# begins at all. Instead scan for ANCHOR lines that unambiguously mark a
# market (a bare "Moneyline"/"Total" line, or a "Player Strikeouts
# Thrown" line), and pull the pick description from the line(s) just
# before the anchor and the odds from the line just after. This is what
# actually matches how these apps format a copied slip.
_MARKET_KEYWORDS = {"moneyline", "total", "spread", "run line"}
_STRIKEOUT_PROP_RE = re.compile(r'strikeouts?\s+thrown', re.IGNORECASE)
_NPLUS_RE = re.compile(r'^\d+\+$')
_BARE_ODDS_LINE_RE = re.compile(r'^[+-]\d{3,4}$')
_OU_VALUE_RE = re.compile(r'(?:over|under)\s+(\d+(?:\.\d+)?)', re.IGNORECASE)

_SLIP_SKIP_PREFIXES = (
    'parlayos', 'combined', 'showing', 'same game parlay', 'parlay odds',
    'wager', 'to win', 'sgpx', 'pick parlay', 'pick sgp',
)

def _is_slip_noise_line(line: str) -> bool:
    """Header/footer/summary lines that are never a leg on their own."""
    low = line.strip().lower()
    if not low:
        return True
    if any(low.startswith(p) or p in low[:24] for p in _SLIP_SKIP_PREFIXES):
        return True
    if re.fullmatch(r'\d+\s*picks?', low):
        return True
    if low in ('lost', 'won', 'win', 'push', 'pending'):
        return True
    return False


def _parse_sportsbook_slip(text: str):
    """
    Scans every line for a market anchor and reconstructs each leg from
    the lines immediately around it. Returns a list of pick dicts. This
    is the PRIMARY parse strategy — it's what real copy-pasted sportsbook
    slips (DraftKings, FanDuel, and similar "My Bets" screens) actually
    look like, tested against real examples.
    """
    lines = [l.strip() for l in text.splitlines()]
    legs = []
    i = 0
    while i < len(lines):
        line = lines[i]
        low = line.lower()

        if low in _MARKET_KEYWORDS:
            pick_desc = lines[i - 1] if i > 0 and not _is_slip_noise_line(lines[i - 1]) else ''
            odds = None
            if i + 1 < len(lines) and _BARE_ODDS_LINE_RE.match(lines[i + 1]):
                odds = int(lines[i + 1])
            if low == 'moneyline':
                market = 'Moneyline'
                line_val = None
            else:
                market = line.title()  # "Total", "Spread", "Run Line"
                ou_val_match = _OU_VALUE_RE.search(pick_desc)
                line_val = _f(ou_val_match.group(1)) if ou_val_match else None
            if pick_desc:
                legs.append({
                    "pick": pick_desc, "market": market, "odds": odds, "line": line_val,
                })
            i += 1
            continue

        # Strikeout prop: an "N+" line immediately followed by a
        # "Player Name Strikeouts Thrown" line, e.g.:
        #   4+
        #   Matthew Boyd Strikeouts Thrown
        if _NPLUS_RE.match(line) and i + 1 < len(lines) and _STRIKEOUT_PROP_RE.search(lines[i + 1]):
            player_name = _STRIKEOUT_PROP_RE.sub('', lines[i + 1]).strip()
            threshold_n = _f(line.rstrip('+'))
            legs.append({
                "pick": f"{player_name} {line} K",
                "market": "K Prop",
                "odds": None,
                # A book's "N+" threshold means "N or more" — expressed as
                # a standard Over line, that's N-0.5 (e.g. "4+" == over 3.5).
                "line": (threshold_n - 0.5) if threshold_n is not None else None,
            })
            i += 2
            continue

        i += 1
    return legs


def _split_into_leg_blocks(text: str):
    """
    Groups the pasted text into logical "leg blocks" — the unit that gets
    parsed into one pick. Real sportsbook slips very often split a single
    leg's pick description, team name, and odds across separate lines
    (e.g. a mobile app copy-paste), while ParlayOS's own export puts one
    complete leg on each line. Parsing line-by-line handles the second
    case but mangles the first (the odds end up orphaned on their own
    "leg"). Blank lines are the natural separator real slips use between
    legs, so: split on blank lines first, and only fall back to one-line-
    per-leg if the whole paste has no blank lines to split on at all
    (which is exactly what ParlayOS's own hyphen-prefixed export looks
    like — every real leg already starts with "- ", so treating each of
    those as its own block is correct there too).
    """
    raw_lines = [l for l in text.splitlines()]
    non_blank = [l for l in raw_lines if l.strip()]
    if not non_blank:
        return []

    blank_separated = '\n\n' in text or any(not l.strip() for l in raw_lines)
    if blank_separated:
        blocks, current = [], []
        for l in raw_lines:
            if not l.strip():
                if current:
                    blocks.append(current); current = []
            else:
                current.append(l.strip())
        if current:
            blocks.append(current)
        return blocks
    else:
        # No blank lines anywhere — treat each non-blank line as its own
        # block (matches ParlayOS's own "- leg per line" export format).
        return [[l] for l in non_blank]


def _parse_leg_block(lines: list):
    """
    Parses one leg block (1+ lines belonging to the same pick) into a pick
    dict, or None. Joins the block into one string and reuses the same
    token-extraction rules as before (odds regex, O/U regex, K-prop regex,
    matchup regex) — merging multi-line blocks first is what fixes the
    "-110 ends up alone on its own broken pick" problem, since the odds
    token and the pick description are now in the same string to search.
    """
    joined = ' '.join(lines).strip()
    if not joined:
        return None
    low = joined.lower()
    if (low.startswith('parlayos') or low.startswith('combined') or low.startswith('showing')
            or low.startswith('same game parlay') or low.startswith('parlay odds')
            or low.startswith('wager') or low.startswith('to win')
            or re.fullmatch(r'\d+\s*picks?', low)):
        return None  # slip header/footer/summary lines, not a real leg

    odds_match = _AMERICAN_ODDS_RE.search(joined)
    odds = int(odds_match.group(1)) if odds_match else None

    matchup = _MATCHUP_RE.search(joined)
    abbr_a, abbr_b = (matchup.group(1), matchup.group(2)) if matchup else (None, None)

    ou_match = _OU_RE.search(joined)
    k_match = _K_PROP_RE.search(joined)
    # A block mentioning "strikeout(s)" or ending in a bare "K" line counts
    # as a K-prop context even if the actual "K" token isn't glued to the
    # number on the same line it started on (multi-line blocks can read
    # "Ryan Weathers Total Strikeouts" / "Over 6.5" as two separate lines).
    is_k_context = bool(k_match) or 'strikeout' in low

    if is_k_context and ou_match:
        market = "K Prop"
        pick_desc = joined
        if odds_match:
            pick_desc = pick_desc.replace(odds_match.group(1), '').strip(' •-')
        if matchup:
            pick_desc = pick_desc.replace(matchup.group(0), '').strip(' •-')
        pick_desc = pick_desc.strip(' •-') or joined
        line_val = _f(ou_match.group(2))
    elif ou_match:
        market = "Total"
        pick_desc = f"{ou_match.group(1).upper()} {ou_match.group(2)}"
        line_val = _f(ou_match.group(2))
    else:
        market = "Moneyline"
        pick_desc = joined
        if odds_match:
            pick_desc = pick_desc.replace(odds_match.group(1), '').strip(' •-')
        if matchup:
            pick_desc = pick_desc.replace(matchup.group(0), '').strip(' •-')
        pick_desc = pick_desc.strip()
        line_val = None

    if odds is None and not ou_match:
        # No odds AND no O/U pattern anywhere in the whole block — too
        # ambiguous to trust (a lone team name with no number attached
        # anywhere, a promo line, etc.). Skip rather than guess.
        return None

    return {
        "pick": pick_desc or joined,
        "market": market,
        "odds": odds if odds is not None else "",
        "line": line_val if line_val is not None else "",
        "abbr_home": abbr_b or "",
        "abbr_away": abbr_a or "",
        "home": abbr_b or "",
        "away": abbr_a or "",
        "raw_line": joined,
    }


def import_pending_slip():
    """
    Checks for pending_slip.txt next to this script. If present, tries two
    parse strategies in order:
      1. _parse_sportsbook_slip() — anchor-based, correct for real
         sportsbook copy/paste (team name, market keyword, and odds each
         on their own line, no blank lines between legs). This is the
         common real-world case and is tried FIRST.
      2. _split_into_leg_blocks() + _parse_leg_block() — correct for
         ParlayOS's own "Copy slip" export format (one complete leg per
         line, hyphen-prefixed). Only tried if strategy 1 finds nothing,
         since a real sportsbook paste will never match ParlayOS's own
         export shape and vice versa.
    Every recognized leg is logged (tag='pasted_slip', distinguishable
    from tag='auto' model picks and tag='me' manually-tracked bets), then
    the file is renamed to pending_slip_YYYYMMDD_HHMMSS.imported so the
    same slip can never be logged twice even if the file is left in place.

    Called at the start of main() — every run of mlb_ace.py picks up any
    slip that was dropped since the last run, no separate command needed.
    """
    if not os.path.exists(PENDING_SLIP_PATH):
        return 0
    try:
        with open(PENDING_SLIP_PATH, encoding='utf-8') as f:
            text = f.read()
    except Exception as e:
        print(f"  Could not read {PENDING_SLIP_PATH}: {e}")
        return 0

    legs = _parse_sportsbook_slip(text)
    parse_strategy = "sportsbook-anchor"
    if not legs:
        for block in _split_into_leg_blocks(text):
            parsed = _parse_leg_block(block)
            if parsed:
                legs.append(parsed)
        parse_strategy = "parlayos-export"

    if not legs:
        print(f"  {PENDING_SLIP_PATH} found but no parseable legs inside — leaving file in place for review.")
        return 0

    print(f"  Parsed {len(legs)} leg(s) using the '{parse_strategy}' strategy.")
    now = datetime.now()
    # One shared ID for every leg in THIS pasted slip — this is what lets
    # mlb_backtest.py later compute the parlay's real all-or-nothing result
    # (every leg must win) instead of only being able to report each leg's
    # individual win rate in isolation, which hides exactly the "9 of 10
    # legs won and the ticket still lost" failure mode a parlay actually has.
    slip_id = f"PS{now.strftime('%y%m%d%H%M%S')}"
    for leg_num, leg in enumerate(legs, start=1):
        pick_dict = {
            "date": now.strftime("%Y-%m-%d"),
            "timestamp": now.isoformat(),
            "tag": "pasted_slip",
            "kind": "team" if leg["market"] == "Moneyline" else "prop",
            "market": leg["market"],
            "pick": leg["pick"],
            "home": leg.get("home") or "",
            "away": leg.get("away") or "",
            "odds": leg["odds"] if leg.get("odds") is not None else "",
            "open_ml": leg["odds"] if (leg["market"] == "Moneyline" and leg.get("odds") is not None) else "",
            "line": leg["line"] if leg.get("line") is not None else "",
            "qualifies": True,
            "slip_id": slip_id,
            "slip_leg_num": leg_num,
            "slip_leg_count": len(legs),
        }
        write_pick_to_log(pick_dict)

    archive_path = os.path.join(
        HERE, f"pending_slip_{now.strftime('%Y%m%d_%H%M%S')}.imported"
    )
    try:
        os.rename(PENDING_SLIP_PATH, archive_path)
    except Exception as e:
        print(f"  Logged {len(legs)} legs but could not archive {PENDING_SLIP_PATH}: {e}")
        print(f"  Delete it manually or it may be re-imported on the next run.")
    else:
        print(f"✓ Imported {len(legs)} leg(s) from pasted slip → {PICKS_LOG_PATH}")
        print(f"  Archived as {os.path.basename(archive_path)}")
    return len(legs)


def fetch_real_pitcher_stats(pitcher_id):
    """
    Real season pitching line for a single MLB person ID. {} if unavailable.
    Now applies the same small-sample shrinkage as engine.fetch_pitcher_stats():
    raw ERA/WHIP/K9 are regressed toward league average in proportion to how
    many innings they represent (full weight at 60+ IP, blended below). This
    prevents a pitcher with 3 IP and a 21.6 ERA from exploding the O/U model
    or displaying a misleadingly extreme stat on the dashboard card.
    The raw IP and W/L are still returned unmodified for display purposes.
    """
    if not pitcher_id: return {}
    try:
        r = requests.get(f"{MLB_STATS_BASE}/people/{pitcher_id}/stats",
                          params={"stats":"season","season":datetime.now().year,"group":"pitching"},
                          timeout=8)
        splits = r.json().get("stats",[{}])[0].get("splits",[])
        if not splits: return {}
        s = splits[0].get("stat",{})
        innings = float(s.get("inningsPitched", 0) or 0)
        era_raw  = round(float(s.get("era",  LEAGUE_AVG_ERA)  or LEAGUE_AVG_ERA),  2)
        whip_raw = round(float(s.get("whip", LEAGUE_AVG_WHIP) or LEAGUE_AVG_WHIP), 2)
        k9_raw   = round(float(s.get("strikeoutsPer9Inn", LEAGUE_AVG_K9) or LEAGUE_AVG_K9), 1)
        FULL_RELIABILITY_IP = 60.0
        rel = min(1.0, innings / FULL_RELIABILITY_IP) if innings >= 5 else 0.0
        def shrink(raw, avg): return round(rel * raw + (1 - rel) * avg, 2)
        return {
            "era":  shrink(era_raw,  LEAGUE_AVG_ERA),
            "whip": shrink(whip_raw, LEAGUE_AVG_WHIP),
            "k9":   shrink(k9_raw,   LEAGUE_AVG_K9),
            "ip":   str(s.get("inningsPitched","0.0")),
            "w":    int(s.get("wins",0) or 0),
            "l":    int(s.get("losses",0) or 0),
        }
    except Exception as e:
        print(f"  pitcher stat fetch failed ({pitcher_id}): {e}")
        return {}

def fetch_real_team_batting(team_id):
    """Real season batting line for a team. {} if unavailable."""
    if not team_id: return {}
    try:
        r = requests.get(f"{MLB_STATS_BASE}/teams/{team_id}/stats",
                          params={"stats":"season","season":datetime.now().year,"group":"hitting"},
                          timeout=8)
        splits = r.json().get("stats",[{}])[0].get("splits",[])
        if not splits: return {}
        s = splits[0].get("stat",{})
        return {
            "avg": s.get("avg",".000"), "obp": s.get("obp",".000"),
            "slg": s.get("slg",".000"), "ops": s.get("ops",".000"),
            "hr":  int(s.get("homeRuns",0) or 0), "rbi": int(s.get("rbi",0) or 0),
            "sb":  int(s.get("stolenBases",0) or 0),
        }
    except Exception as e:
        print(f"  team batting fetch failed ({team_id}): {e}")
        return {}

def fetch_today_probable_pitchers():
    """Map (away_abbr,home_abbr) -> real probable pitcher ids/names for today."""
    tid2abbr = {v: k for k, v in MLB_TEAM_IDS.items()}
    out = {}
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        r = requests.get(f"{MLB_STATS_BASE}/schedule",
                          params={"sportId":1,"date":today,"hydrate":"probablePitcher"},
                          timeout=10)
        for de in r.json().get("dates",[]):
            for gm in de.get("games",[]):
                h = gm["teams"]["home"]; a = gm["teams"]["away"]
                ha = tid2abbr.get(h["team"].get("id"))
                aa = tid2abbr.get(a["team"].get("id"))
                if not ha or not aa: continue
                hp = h.get("probablePitcher") or {}
                ap = a.get("probablePitcher") or {}
                out[(aa,ha)] = {
                    "home_id": hp.get("id"), "home_name": hp.get("fullName"),
                    "away_id": ap.get("id"), "away_name": ap.get("fullName"),
                    "game_date": gm.get("gameDate"),  # real ISO 8601 UTC start time
                }
        print(f"  Probable pitchers: {len(out)} matchups found")
    except Exception as e:
        print(f"  Probable pitcher fetch failed: {e}")
    return out

# ═══════════════════════════════════════════════════════════════════
# WEB SCRAPERS — injuries + lineup handedness
#
# These pull data the MLB Stats API doesn't expose: which specific
# players are actually confirmed to start today's lineup (handedness
# composition) and team-level injury burden. Both were verified by
# manually fetching the live pages before writing this code — but I
# could not execute a live requests.get() from my own sandbox (no
# network access there), so this is best-effort: the exact HTML
# structure may have shifted by the time you run it, and both sites
# can change their markup at any time. Parsing is done via TEXT
# PATTERNS on the page's stripped text content rather than fragile
# CSS class names, which tends to be more resilient to redesigns,
# but is still not guaranteed. Every failure mode here degrades to
# "no data" (contributes 0 to the model) rather than crashing or
# fabricating a value — same discipline as the rest of this file.
#
# Both require `beautifulsoup4` (pip install beautifulsoup4 --break-system-packages
# if not already present) and a browser-like User-Agent header, since
# many sites block the default python-requests UA.
# ═══════════════════════════════════════════════════════════════════

_SCRAPE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36")
}


def fetch_confirmed_lineup(away_abbr: str, home_abbr: str) -> dict:
    """
    Scrapes Rotowire's daily lineups page for TODAY's confirmed/expected
    batting order — full player identities (position, name, hand), not
    just handedness counts. Returns {} on any failure (BeautifulSoup
    missing, page structure changed, matchup not found / lineups not
    posted yet — normal until a few hours before first pitch).

    On success:
        {
          "away": [{"pos":"CF","name":"M. Harris","hand":"L"}, ... x9],
          "home": [...9 batters...],
          "away_confirmed": bool, "home_confirmed": bool,
        }
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("  fetch_confirmed_lineup: beautifulsoup4 not installed, skipping")
        return {}

    cache_key = f"lineup_full_{away_abbr}_{home_abbr}_{datetime.now().strftime('%Y-%m-%d')}"
    cached = get_cached(cache_key, ttl=1800,
                         required_keys=("away", "home", "away_confirmed"))
    if cached is not None:
        return cached

    try:
        r = requests.get("https://www.rotowire.com/baseball/daily-lineups.php",
                          headers=_SCRAPE_HEADERS, timeout=12)
        if r.status_code != 200:
            print(f"  fetch_confirmed_lineup: HTTP {r.status_code}")
            return {}
        soup = BeautifulSoup(r.text, "html.parser")
        lines = [s.strip() for s in soup.stripped_strings if s.strip()]
        text_blob = "\n".join(lines)

        away_u, home_u = away_abbr.upper(), home_abbr.upper()
        matchup_pat = re.compile(rf'\b{away_u}\b\s*\n\s*\b{home_u}\b', re.IGNORECASE)
        m = matchup_pat.search(text_blob)
        if not m:
            matchup_pat2 = re.compile(rf'\b{home_u}\b\s*\n\s*\b{away_u}\b', re.IGNORECASE)
            m = matchup_pat2.search(text_blob)
            if not m:
                return {}

        window = text_blob[m.start(): m.start() + 6000]
        POSITIONS = r'(?:CF|1B|2B|3B|SS|LF|RF|C|DH)'

        def extract_batters(segment: str) -> list:
            # (?=\n|$) handles both mid-document matches and the very
            # last batter in the document (no trailing newline after them).
            triples = re.findall(rf'\n({POSITIONS})\n([^\n]+)\n([LRS])(?=\n|$)', segment)
            return [{"pos": pos, "name": name.strip(), "hand": hand} for pos, name, hand in triples]

        sections = re.split(r'(Confirmed Lineup|Expected Lineup)', window)
        if len(sections) < 5:
            return {}

        away_status, away_block = sections[1], sections[2]
        home_status, home_block = sections[3], sections[4]
        away_batters = extract_batters(away_block[:1500])
        home_batters = extract_batters(home_block[:1500])

        if len(away_batters) < 5 or len(home_batters) < 5:
            # Too few parsed — likely mis-aligned window, don't trust it.
            return {}

        result = {
            "away": away_batters, "home": home_batters,
            "away_confirmed": away_status == "Confirmed Lineup",
            "home_confirmed": home_status == "Confirmed Lineup",
        }
        set_cache(cache_key, result)
        return result
    except Exception as e:
        print(f"  fetch_confirmed_lineup failed ({away_abbr}@{home_abbr}): {e}")
        return {}


def fetch_lineup_handedness(away_abbr: str, home_abbr: str) -> dict:
    """Handedness-count view derived from fetch_confirmed_lineup(), kept
    for the win-probability platoon calculation that only needs counts."""
    full = fetch_confirmed_lineup(away_abbr, home_abbr)
    if not full:
        return {}
    def counts(batters):
        return {h: sum(1 for b in batters if b["hand"] == h) for h in ("L", "R", "S")}
    ac, hc = counts(full["away"]), counts(full["home"])
    return {
        "away_L": ac["L"], "away_R": ac["R"], "away_S": ac["S"],
        "home_L": hc["L"], "home_R": hc["R"], "home_S": hc["S"],
        "away_confirmed": full["away_confirmed"], "home_confirmed": full["home_confirmed"],
    }


def search_player_id(name: str, team_id: int = None) -> int:
    """
    Resolves a scraped (often abbreviated, e.g. "M. Harris") player name
    to a real MLB person ID via the Stats API search endpoint. If team_id
    is given and multiple candidates match, prefers the one currently on
    that team. Returns None if no confident match is found — never
    guesses at an ID, since a WRONG player's stats would be worse than
    no stats at all.
    """
    if not name:
        return None
    cache_key = f"player_search_{name.lower().replace(' ','_').replace('.','')}_{team_id or 0}"
    cached = get_cached(cache_key, ttl=86400*7, required_keys=("id",))
    if cached is not None:
        return cached["id"]
    try:
        r = requests.get(f"{MLB_STATS_BASE}/people/search",
                          params={"names": name}, timeout=8)
        people = r.json().get("people", [])
        if not people:
            set_cache(cache_key, {"id": None})
            return None
        pid = None
        if team_id and len(people) > 1:
            for p in people:
                if p.get("currentTeam", {}).get("id") == team_id:
                    pid = p.get("id")
                    break
        if pid is None:
            pid = people[0].get("id")
        set_cache(cache_key, {"id": pid})
        return pid
    except Exception as e:
        print(f"  search_player_id failed ({name}): {e}")
        return None


def fetch_batter_stats(player_id: int) -> dict:
    """Real individual season batting line for one player. {} if unavailable."""
    if not player_id:
        return {}
    cache_key = f"batter_stats_{player_id}"
    cached = get_cached(cache_key, ttl=3600, required_keys=("avg", "ops"))
    if cached is not None:
        return cached
    try:
        r = requests.get(f"{MLB_STATS_BASE}/people/{player_id}/stats",
                          params={"stats": "season", "season": datetime.now().year, "group": "hitting"},
                          timeout=8)
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return {}
        s = splits[0].get("stat", {})
        result = {
            "avg": s.get("avg", ".000"), "obp": s.get("obp", ".000"),
            "slg": s.get("slg", ".000"), "ops": s.get("ops", ".000"),
            "hr": int(s.get("homeRuns", 0) or 0), "rbi": int(s.get("rbi", 0) or 0),
            "sb": int(s.get("stolenBases", 0) or 0),
        }
        set_cache(cache_key, result)
        return result
    except Exception as e:
        print(f"  fetch_batter_stats failed ({player_id}): {e}")
        return {}


def fetch_full_lineup_with_stats(away_abbr: str, home_abbr: str, away_id: int, home_id: int) -> dict:
    """
    Combines fetch_confirmed_lineup() + player ID resolution + individual
    stat fetching into the complete per-batter data needed for display.
    Any batter whose name can't be resolved to a real player ID, or whose
    stats can't be fetched, is included with pos/name/hand only — stats
    fields simply absent, never fabricated.
    """
    lineup = fetch_confirmed_lineup(away_abbr, home_abbr)
    if not lineup:
        return {}

    def enrich(batters, team_id):
        out = []
        for b in batters:
            pid = search_player_id(b["name"], team_id)
            stats = fetch_batter_stats(pid) if pid else {}
            out.append({**b, **stats})
        return out

    return {
        "away": enrich(lineup["away"], away_id),
        "home": enrich(lineup["home"], home_id),
        "away_confirmed": lineup["away_confirmed"],
        "home_confirmed": lineup["home_confirmed"],
    }


def fetch_team_injury_count(team_full_name: str) -> dict:
    """
    Scrapes MLB.com's official injury report for a rough per-team injury
    burden signal. This is NOT a precise player-by-player IL tracker —
    it counts how many injury-related headlines are currently listed
    under a team's section, which is a coarse but real, live proxy for
    "how banged up is this team right now." Returns {} on any failure.

    On success: {"headline_count": int}
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("  fetch_team_injury_count: beautifulsoup4 not installed, skipping")
        return {}

    cache_key = f"injury_count_{team_full_name.replace(' ','_')}_{datetime.now().strftime('%Y-%m-%d-%H')}"
    cached = get_cached(cache_key, ttl=3600, required_keys=("headline_count",))
    if cached is not None:
        return cached

    try:
        r = requests.get("https://www.mlb.com/injury-report",
                          headers=_SCRAPE_HEADERS, timeout=12)
        if r.status_code != 200:
            print(f"  fetch_team_injury_count: HTTP {r.status_code}")
            return {}
        soup = BeautifulSoup(r.text, "html.parser")

        # MLB.com's injury report groups headlines under an <h3> with the
        # team nickname (e.g. "Blue Jays", "Orioles" — not the full "New
        # York Yankees"), followed by a handful of <a> headline links
        # before the next <h3>. Match on the nickname (last word(s) of
        # the full team name) since that's what the page actually uses.
        # Most team names are "City Nickname" (nickname = last word), but
        # three teams have a two-word nickname where a naive last-word
        # split would be wrong ("Blue Jays" -> "Jays" loses "Blue").
        TWO_WORD_NICKNAMES = ("Red Sox", "White Sox", "Blue Jays")
        nickname = team_full_name.split()[-1]
        for two_word in TWO_WORD_NICKNAMES:
            if team_full_name.endswith(two_word):
                nickname = two_word
                break

        headers_found = soup.find_all(['h3'])
        target_idx = None
        for idx, h in enumerate(headers_found):
            if h.get_text(strip=True).lower() == nickname.lower():
                target_idx = idx
                break
        if target_idx is None:
            return {}

        # Count <a> tags between this h3 and the next h3 (or end of doc)
        start_node = headers_found[target_idx]
        end_node = headers_found[target_idx + 1] if target_idx + 1 < len(headers_found) else None
        count = 0
        node = start_node.find_next()
        while node is not None and node is not end_node:
            href = node.get('href', '') if node.name == 'a' else ''
            # Exclude "More" links (…/news/topic/team-injury-report), which
            # aggregate rather than represent an individual headline.
            if href.startswith('https://www.mlb.com/news/') and '/topic/' not in href:
                count += 1
            node = node.find_next()
            if count > 20:  # safety bound
                break

        result = {"headline_count": count}
        set_cache(cache_key, result)
        return result
    except Exception as e:
        print(f"  fetch_team_injury_count failed ({team_full_name}): {e}")
        return {}

def fetch_bullpen_stats(team_id: int) -> dict:
    """
    Real bullpen-ONLY FIP/ERA/WHIP, using the MLB Stats API's documented
    situation-code split system: stats=statSplits with sitCodes="rp"
    ("as a reliever" — confirmed against the API's own situationCodes
    list, alongside "sp" for "as a starter"). This replaces the
    whole-staff team ERA that calculate_win_probability previously used
    as a bullpen proxy, which mixed starters' innings into a number
    meant to represent the pen.

    Same has_data discipline as the rest of this file: too few relief
    innings logged, an empty response, or a request error all return
    has_data=False so the caller falls back to the coarser team-ERA
    proxy rather than trusting a near-empty or malformed split.
    """
    if not team_id:
        return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "fip": LEAGUE_AVG_FIP, "has_data": False}
    cache_key = f"bullpen_stats_v1_{team_id}"
    cached = get_cached(cache_key, ttl=3600, required_keys=("era", "whip", "fip", "has_data"))
    if cached is not None:
        return cached
    try:
        r = requests.get(f"{MLB_STATS_BASE}/teams/{team_id}/stats",
                          params={"stats": "statSplits", "sitCodes": "rp",
                                  "group": "pitching", "season": datetime.now().year},
                          timeout=8)
        splits = r.json().get("stats", [{}])[0].get("splits", [])
        if not splits:
            return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "fip": LEAGUE_AVG_FIP, "has_data": False}
        s = splits[0].get("stat", {})
        ip = float(s.get("inningsPitched", 0) or 0)
        if ip < 20:  # too small a relief sample to trust (e.g. very early season)
            return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "fip": LEAGUE_AVG_FIP, "has_data": False}
        hr  = int(s.get("homeRuns", 0) or 0)
        bb  = int(s.get("baseOnBalls", 0) or 0)
        hbp = int(s.get("hitByPitch", 0) or 0)
        k   = int(s.get("strikeOuts", 0) or 0)
        fip = round(((13 * hr + 3 * (bb + hbp) - 2 * k) / ip) + 3.10, 2)
        result = {
            "era": round(float(s.get("era", LEAGUE_AVG_ERA) or LEAGUE_AVG_ERA), 2),
            "whip": round(float(s.get("whip", LEAGUE_AVG_WHIP) or LEAGUE_AVG_WHIP), 2),
            "fip": fip,
            "has_data": True,
        }
        set_cache(cache_key, result)
        return result
    except Exception as e:
        print(f"  bullpen relief-split fetch failed ({team_id}): {e}")
        return {"era": LEAGUE_AVG_ERA, "whip": LEAGUE_AVG_WHIP, "fip": LEAGUE_AVG_FIP, "has_data": False}


def fetch_bullpen_pitch_load(team_id: int, days_back: int = 2) -> dict:
    """
    Real reliever pitch-count aggregation from boxscores — an upgrade on
    fetch_bullpen_fatigue()'s played-yesterday proxy below. For each of
    the team's completed games in the last `days_back` days, pulls that
    game's boxscore and reads the team's OWN "pitchers" array (appearance
    order per MLB's GUMBO schema — index 0 is always the starter) to sum
    numberOfPitches for everyone EXCEPT the starter. Explicitly reads
    from teams[side] where side is resolved per-game from whether this
    team was home or away in THAT game — a naive version of this that
    always reads teams["home"] would silently attribute the wrong team's
    relievers whenever the team being checked was actually away that day.

    Returns {"pitches": int, "has_data": bool}. has_data=False on any
    fetch error or when no completed games fall in the window (e.g. an
    off day) — callers should treat that as "no signal," not "rested."
    """
    if not team_id:
        return {"pitches": 0, "has_data": False}
    cache_key = f"bp_pitch_load_v1_{team_id}_{datetime.now().strftime('%Y-%m-%d')}"
    cached = get_cached(cache_key, ttl=3600 * 6, required_keys=("pitches", "has_data"))
    if cached is not None:
        return cached
    total_pitches = 0
    games_found = 0
    try:
        for d in range(1, days_back + 1):
            date = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
            r = requests.get(f"{MLB_STATS_BASE}/schedule",
                              params={"sportId": 1, "teamId": team_id, "date": date},
                              timeout=8)
            for de in r.json().get("dates", []):
                for gm in de.get("games", []):
                    if gm.get("status", {}).get("codedGameState") not in ["F", "FR"]:
                        continue
                    is_home = gm["teams"]["home"]["team"].get("id") == team_id
                    side = "home" if is_home else "away"
                    game_pk = gm.get("gamePk")
                    if not game_pk:
                        continue
                    try:
                        box = requests.get(f"{MLB_STATS_BASE}/game/{game_pk}/boxscore", timeout=8).json()
                        team_box = box.get("teams", {}).get(side, {})
                        pitcher_ids = team_box.get("pitchers", [])
                        if len(pitcher_ids) <= 1:
                            continue  # no relief appearances logged for this game
                        relievers = pitcher_ids[1:]  # index 0 = starter
                        players = team_box.get("players", {})
                        for pid in relievers:
                            p = players.get(f"ID{pid}", {})
                            pitches = p.get("stats", {}).get("pitching", {}).get("numberOfPitches", 0)
                            total_pitches += int(pitches or 0)
                        games_found += 1
                    except Exception as e:
                        print(f"  boxscore fetch failed (game {game_pk}): {e}")
        result = {"pitches": total_pitches, "has_data": games_found > 0}
        set_cache(cache_key, result)
        return result
    except Exception as e:
        print(f"  bullpen pitch load fetch failed ({team_id}): {e}")
        return {"pitches": 0, "has_data": False}


def fetch_bullpen_fatigue(team_id: int) -> float:
    """
    Bullpen fatigue proxy — returns a factor in [0.9, 1.0], 1.0 = fully
    rested, 0.9 = played yesterday. FALLBACK ONLY as of the pitch-count
    upgrade above: calculate_win_probability() now prefers
    fetch_bullpen_pitch_load()'s real reliever pitch counts and only
    drops down to this played-yesterday proxy when boxscore data isn't
    available for some reason (API hiccup, doubleheader edge case,
    etc.). Kept as-is rather than removed, since a coarse-but-reliable
    signal beats no signal at all when the precise version fails.
    """
    rest = fetch_team_rest_status(team_id)
    return 0.9 if rest["played_yesterday"] else 1.0


def fetch_pitcher_hand(pitcher_id: int) -> str:
    """Real pitcher handedness (L/R) from the MLB Stats API bio endpoint."""
    if not pitcher_id:
        return ""
    cache_key = f"pitcher_hand_{pitcher_id}"
    cached = get_cached(cache_key, ttl=86400*30, required_keys=("hand",))  # rarely changes
    if cached is not None:
        return cached["hand"]
    try:
        r = requests.get(f"{MLB_STATS_BASE}/people/{pitcher_id}", timeout=8)
        hand = r.json().get("people", [{}])[0].get("pitchHand", {}).get("code", "")
        set_cache(cache_key, {"hand": hand})
        return hand
    except Exception as e:
        print(f"  pitcher hand fetch failed ({pitcher_id}): {e}")
        return ""


def fetch_team_rest_status(team_id: int) -> dict:
    """
    Real fatigue signal from the MLB Stats API — no scraping, no new data
    source. Checks whether a team played a game YESTERDAY (0 days rest
    before today) vs having had at least one day off. A team on zero rest
    facing a well-rested opponent is a modest, real, well-documented
    disadvantage (bullpen usage carries over, travel, etc.).
    """
    cache_key = f"rest_status_{team_id}_{datetime.now().strftime('%Y-%m-%d')}"
    cached = get_cached(cache_key, ttl=3600*12, required_keys=("played_yesterday",))
    if cached is not None:
        return cached
    if not team_id:
        return {"played_yesterday": False}
    try:
        yesterday = (datetime.now() - __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")
        r = requests.get(f"{MLB_STATS_BASE}/schedule",
                          params={"sportId": 1, "teamId": team_id, "date": yesterday},
                          timeout=8)
        played = False
        for de in r.json().get("dates", []):
            for gm in de.get("games", []):
                if gm.get("status", {}).get("codedGameState") in ["F", "O", "FR"]:
                    played = True
        result = {"played_yesterday": played}
        set_cache(cache_key, result)
        return result
    except Exception as e:
        print(f"  rest status fetch failed ({team_id}): {e}")
        return {"played_yesterday": False}

def _picks_to_v6_games(picks: List) -> List:
    """
    Convert picks to the full game object expected by ParlayOS.
    Enriches every game with REAL pitcher stats (ERA/WHIP/K9/IP/W/L) and
    REAL team batting stats (AVG/OBP/SLG/OPS/HR/RBI/SB) fetched from the
    MLB Stats API. Fields are omitted (left as None) when real data is
    unavailable rather than being filled with fabricated numbers.
    """
    import time
    import random

    # Fetch once, reuse across all games this run
    probables = fetch_today_probable_pitchers()
    pitcher_cache = {}   # pitcher_id -> stats dict
    team_cache    = {}   # team_id    -> stats dict

    def pitcher_stats_for(pid):
        if not pid: return {}
        if pid not in pitcher_cache:
            pitcher_cache[pid] = fetch_real_pitcher_stats(pid)
        return pitcher_cache[pid]

    def team_stats_for(tid):
        if not tid: return {}
        if tid not in team_cache:
            team_cache[tid] = fetch_real_team_batting(tid)
        return team_cache[tid]

    v6_games = []
    for idx, p in enumerate(picks):
        # Extract basic info
        away = p.get('away', 'Away')
        home = p.get('home', 'Home')
        pick_team = p.get('pick', home)
        odds = p.get('odds', -110)
        model_prob = p.get('model_prob', 50) / 100.0
        edge = p.get('edge', 0) / 100.0

        # Decimal odds from American
        if odds > 0:
            ml_price_dec = round((odds / 100) + 1, 3)
        else:
            ml_price_dec = round((100 / abs(odds)) + 1, 3)

        # Abbreviations
        abbr_a = TEAM_ABBR.get(away, away[:3].upper())
        abbr_b = TEAM_ABBR.get(home, home[:3].upper())

        # ── Real probable pitchers for this matchup (if today) ──
        real = probables.get((abbr_a, abbr_b), {})
        away_pitcher = real.get('away_name') or p.get('away_pitcher', 'TBD')
        home_pitcher = real.get('home_name') or p.get('home_pitcher', 'TBD')
        away_pid = real.get('away_id')
        home_pid = real.get('home_id')

        # ── Real game start time — was previously hardcoded to
        #    time.time()+3600 (literally "whenever this script happens to
        #    run, plus an hour"), which would display a wrong time on
        #    every card regardless of the game's actual schedule. Now
        #    parsed from the real ISO 8601 gameDate the schedule API
        #    already returns (captured in fetch_today_probable_pitchers).
        game_date_str = real.get('game_date')
        start_at_ms = None
        time_display = 'TBD'
        date_display = ''
        if game_date_str:
            try:
                # BUG FIX: strptime() with '%Z'-less format produces a NAIVE
                # datetime even though the string is UTC (the trailing "Z"
                # in MLB's gameDate means UTC, but the format string here
                # just consumes the literal "Z" character without attaching
                # tzinfo). Calling .timestamp() on that naive value silently
                # assumes it's already LOCAL time, not UTC — on a system
                # west of UTC this shifts every game time forward, which is
                # exactly why West Coast evening games were showing up as
                # "Fri 12-2 AM" instead of "Thu evening." Fix: explicitly
                # attach tzinfo=utc after parsing, then use .astimezone()
                # (not fromtimestamp()) to convert to the system's real
                # local timezone correctly.
                dt_utc = datetime.strptime(game_date_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                start_at_ms = int(dt_utc.timestamp() * 1000)
                dt_local = dt_utc.astimezone()
                if os.name != 'nt':
                    time_display = dt_local.strftime('%-I:%M %p')
                    date_display = dt_local.strftime('%a %b %-d')  # e.g. "Wed Jul 9"
                else:
                    time_display = dt_local.strftime('%I:%M %p').lstrip('0')
                    date_display = dt_local.strftime('%a %b %d').replace(' 0', ' ')
            except (ValueError, TypeError) as e:
                print(f"  game_date parse failed ({game_date_str}): {e}")
        if start_at_ms is None:
            # No real schedule data for this matchup — fall back to "unknown"
            # rather than fabricating a plausible-looking but fake time.
            start_at_ms = int(time.time() * 1000)

        # ── Real pitcher season stats ──
        pa = pitcher_stats_for(away_pid)
        pb = pitcher_stats_for(home_pid)

        # ── Real team batting season stats ──
        tid_a = MLB_TEAM_IDS.get(abbr_a)
        tid_b = MLB_TEAM_IDS.get(abbr_b)
        bat_a = team_stats_for(tid_a)
        bat_b = team_stats_for(tid_b)

        # ── Total line: real posted line preferred, OPS-based estimate fallback ──
        real_line = p.get('line')
        if real_line is not None:
            total = round(float(real_line), 1)
        else:
            _lg_ops = 0.720
            try:
                _ops_a = float(bat_a.get('ops', _lg_ops) or _lg_ops) if bat_a else _lg_ops
            except (ValueError, TypeError):
                _ops_a = _lg_ops
            try:
                _ops_b = float(bat_b.get('ops', _lg_ops) or _lg_ops) if bat_b else _lg_ops
            except (ValueError, TypeError):
                _ops_b = _lg_ops
            _pf = PARK_FACTORS.get(abbr_b, 100) / 100.0
            total = round(max(6.0, min(13.0, 8.5 * (_ops_a + _ops_b) / (2 * _lg_ops) * _pf)), 1)

        # ── Over/Under direction — real expected-runs model ──────────────────
        # Replaces random.random() with a genuine signal:
        #
        # Expected combined runs = (SP run rate × estimated IP × opp offense factor)
        #   for both starters + both bullpens, scaled by park factor.
        # The direction (OVER/UNDER) is whichever side the model estimate falls on
        # relative to the posted total. Edge is computed via a normal-CDF
        # approximation: total MLB run distributions have σ ≈ 1.5 runs around
        # any model estimate, so a 0.75-run gap → ~17% edge, a 1.5-run gap → ~32%.
        #
        # All ERA values in pa/pb have already been shrunk toward league average
        # proportional to IP sample size (via fetch_real_pitcher_stats), so
        # a pitcher with 3 IP and 21.00 ERA becomes ~4.25 (league avg), not an
        # outlier that blows up the run estimate.
        #
        # Constants:
        _LEAGUE_AVG_ERA  = 4.25
        _LEAGUE_AVG_OPS  = 0.720
        _EST_SP_IP       = 5.5   # median modern SP start
        _EST_BULL_IP     = 3.5   # pen innings after SP leaves
        _RUN_SIGMA       = 1.5   # std dev of actual MLB game totals
        _MARKET_VIG_PROB = 110.0 / 210.0  # -110 both sides → 52.38% implied

        def _erf_approx(x):
            # Horner-form rational approximation (Abramowitz & Stegun 7.1.26)
            t = 1.0 / (1.0 + 0.3275911 * abs(x))
            poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 +
                   t * (-1.453152027 + t * 1.061405429))))
            v = 1.0 - poly * (2.718281828 ** (-x * x))
            return v if x >= 0 else -v

        def _normal_cdf(x):
            return 0.5 * (1.0 + _erf_approx(x / (2.0 ** 0.5)))

        era_a = pa.get('era') or _LEAGUE_AVG_ERA
        era_b = pb.get('era') or _LEAGUE_AVG_ERA
        ops_fa = float(bat_a.get('ops', _LEAGUE_AVG_OPS) or _LEAGUE_AVG_OPS) if bat_a else _LEAGUE_AVG_OPS
        ops_fb = float(bat_b.get('ops', _LEAGUE_AVG_OPS) or _LEAGUE_AVG_OPS) if bat_b else _LEAGUE_AVG_OPS
        park_f = PARK_FACTORS.get(abbr_b, 100) / 100.0

        # Away SP faces home lineup; home SP faces away lineup
        sp_runs_a   = (era_a / 9.0) * _EST_SP_IP   * (ops_fb / _LEAGUE_AVG_OPS)
        sp_runs_b   = (era_b / 9.0) * _EST_SP_IP   * (ops_fa / _LEAGUE_AVG_OPS)
        # Both bullpens face the respective opposing lineup at league-avg ERA
        bull_runs_a = (_LEAGUE_AVG_ERA / 9.0) * _EST_BULL_IP * (ops_fb / _LEAGUE_AVG_OPS)
        bull_runs_b = (_LEAGUE_AVG_ERA / 9.0) * _EST_BULL_IP * (ops_fa / _LEAGUE_AVG_OPS)
        model_total_ou = (sp_runs_a + sp_runs_b + bull_runs_a + bull_runs_b) * park_f

        ou_gap = model_total_ou - total  # positive → OVER; negative → UNDER
        if ou_gap >= 0:
            ou_pick      = 'OVER'
            ou_model_prob = 1.0 - _normal_cdf(-ou_gap / _RUN_SIGMA)
        else:
            ou_pick      = 'UNDER'
            ou_model_prob = _normal_cdf(-ou_gap / _RUN_SIGMA)  # P(actual < total)
        ou_pick_str = f'{ou_pick} {total}'
        ou_edge = round(ou_model_prob - _MARKET_VIG_PROB, 4)

        # K-line — grounded in the away pitcher's real K/9 rate over an
        # estimated ~6 innings per start, instead of a pure random line.
        league_avg_k9 = 8.6
        pa_k9 = pa.get('k9') if pa else None
        est_k9 = pa_k9 if pa_k9 else league_avg_k9
        k_line = round(max(3.5, min(11.0, est_k9 * 0.67)) + (random.random()-0.5)*0.6, 1)
        k_pick = 'OVER' if random.random() > 0.5 else 'UNDER'
        k_pick_str = f'{k_pick} {k_line} K'
        ml_fav = TEAM_ABBR.get(pick_team, pick_team[:3].upper()) if pick_team else abbr_b

        k_edge = round(edge * 0.4, 4)
        hot = edge > 0.03 or abs(ou_edge) > 0.05  # hot if either ML or O/U has real edge

        game = {
            'id': f'live_{idx}_{int(time.time())}',
            'a': abbr_a, 'b': abbr_b,
            'abbrA': abbr_a, 'abbrB': abbr_b,
            'cityA': away, 'cityB': home,
            'lgA': 'MLB', 'lgB': 'MLB',
            'total': total, 'ouPick': ou_pick_str,
            'kLine': k_line, 'kPick': k_pick_str,
            'mlFav': ml_fav, 'mlPriceDec': ml_price_dec,
            'ouEdge': ou_edge, 'kEdge': k_edge, 'mlEdge': round(edge, 4),
            'model': round(model_prob, 4),
            'pitcherA': away_pitcher, 'pitcherB': home_pitcher,
            'tv': 'ESPN+', 'hot': hot,
            'spr': 0, 'sprEdge': 0, 'tot': total, 'totEdge': 0,
            'startAt': start_at_ms, 'time': time_display, 'date': date_display,
            'logo': '', 'logoB': '', 'status': 'live',
            'modelProb': round(model_prob, 3),
            'mlPriceAmerican': odds,
            'marketProb': round(1/ml_price_dec, 3) if ml_price_dec > 0 else 0.5,
            # ── qualifies now passes through the REAL flag computed in the
            #    main loop (edge vs config min_edge, total vs the tuned
            #    line band) instead of being hardcoded True here — this was
            #    a second, disconnected place the flag got force-set,
            #    independent of the one in the main loop that writes to
            #    picks_log.csv, so the UI and the log could disagree about
            #    whether a pick actually qualified.
            'qualifies': bool(p.get('qualifies', True)),
            # ── Real pitcher stats (None when unavailable — never fabricated) ──
            'pitcherA_era':  pa.get('era'),  'pitcherA_whip': pa.get('whip'),
            'pitcherA_k9':   pa.get('k9'),   'pitcherA_ip':   pa.get('ip'),
            'pitcherA_w':    pa.get('w'),    'pitcherA_l':    pa.get('l'),
            'pitcherB_era':  pb.get('era'),  'pitcherB_whip': pb.get('whip'),
            'pitcherB_k9':   pb.get('k9'),   'pitcherB_ip':   pb.get('ip'),
            'pitcherB_w':    pb.get('w'),    'pitcherB_l':    pb.get('l'),
            # ── Real team batting stats ──
            'teamA_avg': bat_a.get('avg'), 'teamA_obp': bat_a.get('obp'),
            'teamA_slg': bat_a.get('slg'), 'teamA_ops': bat_a.get('ops'),
            'teamA_hr':  bat_a.get('hr'),  'teamA_rbi': bat_a.get('rbi'),
            'teamA_sb':  bat_a.get('sb'),
            'teamB_avg': bat_b.get('avg'), 'teamB_obp': bat_b.get('obp'),
            'teamB_slg': bat_b.get('slg'), 'teamB_ops': bat_b.get('ops'),
            'teamB_hr':  bat_b.get('hr'),  'teamB_rbi': bat_b.get('rbi'),
            'teamB_sb':  bat_b.get('sb'),
        }

        # ── Confirmed daily lineup with individual batter stats — only
        #    fetched if the game has real team IDs (needed for player ID
        #    disambiguation). Absent entirely (no 'lineupA'/'lineupB' keys)
        #    if lineups haven't posted yet or the scrape fails — the HTML
        #    side treats missing keys the same as an empty result.
        if tid_a and tid_b:
            full_lineup = fetch_full_lineup_with_stats(abbr_a, abbr_b, tid_a, tid_b)
            if full_lineup:
                game['lineupA'] = full_lineup['away']
                game['lineupB'] = full_lineup['home']
                game['lineupA_confirmed'] = full_lineup['away_confirmed']
                game['lineupB_confirmed'] = full_lineup['home_confirmed']

        v6_games.append(game)
    return v6_games


def fetch_month_schedule_all_teams(team_abbrs: list) -> dict:
    """Fetch this month's real game results and future times for given teams."""
    import calendar as _cal
    now = datetime.now()
    start_date = now.replace(day=1).strftime("%Y-%m-%d")
    end_date   = now.replace(day=_cal.monthrange(now.year, now.month)[1]).strftime("%Y-%m-%d")
    tid2abbr   = {v: k for k, v in MLB_TEAM_IDS.items()}
    schedules  = {a: [] for a in team_abbrs}
    try:
        r = requests.get(f"{MLB_STATS_BASE}/schedule",
            params={"sportId":1,"startDate":start_date,"endDate":end_date,
                    "season":str(now.year),"hydrate":"linescore"}, timeout=15)
        today_str = now.strftime("%Y-%m-%d")
        for de in r.json().get("dates",[]):
            gdate = de.get("date","")
            for gm in de.get("games",[]):
                ht = gm["teams"]["home"]; at = gm["teams"]["away"]
                final = gm.get("status",{}).get("codedGameState","") in ["F","O","FR"]
                for (home_side, my_t, opp_t) in [(True,ht,at),(False,at,ht)]:
                    my_abbr  = tid2abbr.get(my_t["team"].get("id"))
                    opp_abbr = tid2abbr.get(opp_t["team"].get("id"),"???")
                    if my_abbr not in schedules: continue
                    entry = {"date":gdate,"opp":opp_abbr,"home":home_side}
                    if final:
                        ms = my_t.get("score",0) or 0; os = opp_t.get("score",0) or 0
                        entry.update({"result":"W" if ms>os else "L","myScore":ms,"oppScore":os})
                    elif gdate != today_str:
                        gt = gm.get("gameDate","")
                        entry["time"] = gt[11:16]+"P" if "T" in gt else "TBD"
                    else:
                        entry["today"] = True
                    schedules[my_abbr].append(entry)
        print(f"  Schedules: fetched for {sum(1 for v in schedules.values() if v)} teams")
    except Exception as e:
        print(f"  Schedule error: {e}")
    return schedules

def export_to_html(picks: List, output_path: str = None) -> str:
    """
    Inject PARLAYOS_DATA into parlayos.html.
    Uses a stable <!--PARLAYOS_INJECT_POINT--> marker; falls back to boot() search.
    Cleans ALL previous injections before inserting fresh data.
    """
    out_path = output_path or PARLAYOS_TEMPLATE_PATH
    try:
        with open(out_path, 'r', encoding='utf-8') as f:
            html = f.read()
    except FileNotFoundError:
        print(f"Template not found: {out_path}"); return ""

    # ── Build game objects (now enriched with real pitcher/team stats) ──
    v6_games   = _picks_to_v6_games(picks)
    games_json = json.dumps(v6_games, separators=(',', ':'))

    # ── Real monthly schedules for calendar ──
    all_abbrs = list(set(g.get('a','') for g in v6_games) | set(g.get('b','') for g in v6_games))
    schedules = fetch_month_schedule_all_teams([a for a in all_abbrs if a])
    schedules_json = json.dumps(schedules, separators=(',', ':'))

    # ── Collect real team batting stats for the standalone Batting tab ──
    team_stats = {}
    for g in v6_games:
        for side, abbr in [('A', g.get('a')), ('B', g.get('b'))]:
            if not abbr or abbr in team_stats:
                continue
            avg = g.get(f'team{side}_avg')
            if avg is None:
                continue  # no real data fetched for this team — omit rather than fabricate
            team_stats[abbr] = {
                'avg': avg, 'obp': g.get(f'team{side}_obp'),
                'slg': g.get(f'team{side}_slg'), 'ops': g.get(f'team{side}_ops'),
                'hr':  g.get(f'team{side}_hr'),  'rbi': g.get(f'team{side}_rbi'),
                'sb':  g.get(f'team{side}_sb'),
            }
    team_stats_json = json.dumps(team_stats, separators=(',', ':'))

    run_date   = datetime.now().strftime('%b %d %Y  %H:%M')
    pick_count = len(picks)

    # ── Strip ALL previous injections (handles garbled AND clean box-drawing chars) ──
    html = re.sub(
        r'[ \t]*//[^\n]*PARLAYOS LIVE DATA.*?[ \t]*//[^\n]*END PARLAYOS LIVE DATA[^\n]*\n?',
        '', html, flags=re.DOTALL
    )
    html = re.sub(r'\n{3,}', '\n\n', html)

    # ── Build fresh injection — games, schedules, and teamStats ALL included ──
    injection_lines = [
        "    // ── PARLAYOS LIVE DATA (" + run_date + ") ──────────────────────────",
        "    window.PARLAYOS_DATA = {",
        "      runDate: \"" + run_date + "\",",
        "      pickCount: " + str(pick_count) + ",",
        "      games: " + games_json + ",",
        "      schedules: " + schedules_json + ",",
        "      teamStats: " + team_stats_json,
        "    };",
        "    // Refresh UI with live data",
        "    (function(){",
        "      if(typeof loadRealData   ==='function') loadRealData();",
        "      if(typeof renderDashboard==='function') renderDashboard();",
        "      if(typeof renderAll      ==='function') renderAll();",
        "    })();",
        "    // ── END PARLAYOS LIVE DATA ──────────────────────────────────────────",
    ]
    injection = "\n".join(injection_lines)

    # ── Sanity check before writing: every field must actually be present ──
    assert '"games":' not in injection or True  # games is a bare array, not keyed this way — skip
    assert games_json in injection, "games_json missing from injection!"
    assert schedules_json in injection, "schedules_json missing from injection!"
    assert team_stats_json in injection, "team_stats_json missing from injection!"

    # ── Insert at stable marker (preferred) ──
    MARKER = '    // <!--PARLAYOS_INJECT_POINT-->'
    if MARKER in html:
        html = html.replace(MARKER, MARKER + '\n' + injection)
        print(f"  Injected at stable marker")
    else:
        boot_line = re.search(r'([ \t]+boot\(\);)', html)
        if boot_line:
            end = boot_line.end()
            html = html[:end] + '\n' + injection + html[end:]
            print(f"  Injected after boot(); (fallback)")
        else:
            html = html.replace('</body>', f'<script>\n{injection}\n</script>\n</body>')
            print(f"  Injected before </body> (last resort)")

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"✓ {pick_count} picks → {out_path}")
    print(f"✓ {len(schedules)} team schedules, {len(team_stats)} team batting lines included")
    return out_path


if __name__ == "__main__":
    # Check for a pasted slip dropped since the last run — see
    # import_pending_slip()'s docstring. Runs first and independently of
    # everything else below: even if the odds API is down or rate-limited,
    # a slip the person already pasted still gets logged.
    import_pending_slip()

    config = load_config()
    engine = PredictionEngine(ODDS_API_KEY)
    odds_data = engine.fetch_live_odds()

    # Fetch real probable pitchers ONCE up front (was previously only used
    # much later in _picks_to_v6_games for display — the actual prediction
    # model never saw real pitcher IDs at all, it always got 0).
    probables = fetch_today_probable_pitchers()

    games = []
    seen_matchups = set()  # (away, home) — dedup same game from multiple bookmakers
    skipped_non_mlb_team = []
    for game in odds_data:  # Process ALL games
        if len(game.get("bookmakers", [])) > 0:
            h2h = next((m for m in game["bookmakers"][0]["markets"] if m["key"] == "h2h"), None)
            if h2h:
                home = game["home_team"]
                away = game["away_team"]

                # ── Real-MLB-team filter ──
                # The Odds API's baseball_mlb sport key isn't limited to
                # regular-season games between the 30 real franchises — it
                # can also include the All-Star Game (home_team/away_team
                # come back as "American League"/"National League", not a
                # real team), and potentially other non-standard entries.
                # Neither of those names exists in TEAM_ABBR (the
                # authoritative list of the 30 real MLB team names this
                # script knows about), so this uses that dict as a
                # whitelist: if a name isn't a real team, skip the game
                # entirely rather than let it fall through to the [:3]
                # truncation fallback used elsewhere for display purposes.
                # That fallback produced "AME"/"NAT" abbreviations for a
                # fictional matchup with no real roster, season stats, or
                # schedule behind it — every downstream stats lookup then
                # silently fell back to league-average placeholders, and
                # the model produced a confident-looking pick built
                # entirely out of noise for a game that was never
                # meaningfully bettable in the first place.
                if home not in TEAM_ABBR or away not in TEAM_ABBR:
                    skipped_non_mlb_team.append(f"{away} @ {home}")
                    continue

                matchup_key = (away, home)
                if matchup_key in seen_matchups:
                    continue  # same game from a second bookmaker entry — skip
                seen_matchups.add(matchup_key)
                home_odds = next(o["price"] for o in h2h["outcomes"] if o["name"] == home)
                market_prob = 100/(home_odds+100) if home_odds > 0 else -home_odds/(-home_odds+100)

                # Resolve REAL team IDs (was hardcoded 0 for every game, which
                # made calculate_win_probability's team/pitcher lookups fail
                # identically for both sides and silently zero out those
                # factors — the model was effectively only market_prob+noise).
                home_abbr = TEAM_ABBR.get(home, home[:3].upper())
                away_abbr = TEAM_ABBR.get(away, away[:3].upper())
                home_id = MLB_TEAM_IDS.get(home_abbr, 0)
                away_id = MLB_TEAM_IDS.get(away_abbr, 0)

                # Resolve REAL probable pitchers for this matchup (was
                # hardcoded "TBD"/id=0 for every game — fetch_today_probable_
                # pitchers() existed but was never called before this point).
                real = probables.get((away_abbr, home_abbr), {})
                home_pitcher_id = real.get('home_id', 0)
                away_pitcher_id = real.get('away_id', 0)
                home_pitcher_name = real.get('home_name') or "TBD"
                away_pitcher_name = real.get('away_name') or "TBD"

                # Resolve REAL ballpark coordinates for weather (was hardcoded
                # to NYC's lat/lon for every single game regardless of venue).
                lat, lon = STADIUM_LOCATIONS.get(home_abbr, (40.0, -74.0))

                # Real O/U total line — was previously never fetched at all;
                # _picks_to_v6_games synthesized a fake total from
                # random.random(). fetch_live_odds() now requests the
                # "totals" market alongside h2h, so the real posted line (and
                # its Over/Under prices) is available here to attach to the
                # game and, further down, to actually gate qualifies against
                # min_total_line/max_total_line. real_total stays None (never
                # a fabricated number) when no bookmaker has posted a total
                # yet — the caller must treat that as "unknown," not "8.5."
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

                games.append({
                    "home": home, "away": away, "home_id": home_id, "away_id": away_id,
                    "home_pitcher_id": home_pitcher_id, "away_pitcher_id": away_pitcher_id,
                    "home_pitcher": home_pitcher_name, "away_pitcher": away_pitcher_name,
                    "market_prob": market_prob, "odds": {"home": home_odds},
                    "lat": lat, "lon": lon,
                    "real_total": real_total, "over_price": over_price, "under_price": under_price,
                })

    if skipped_non_mlb_team:
        print(f"  Skipped {len(skipped_non_mlb_team)} non-regular-season entr"
              f"{'y' if len(skipped_non_mlb_team)==1 else 'ies'} (e.g. All-Star Game — "
              f"not a real matchup between two of the 30 MLB teams):")
        for s in skipped_non_mlb_team:
            print(f"    - {s}")

    kelly_fraction = config.get("kelly_fraction", 0.25)

    def kelly_stake(prob, decimal_odds):
        """Fraction of bankroll to stake, scaled by kelly_fraction for safety."""
        if decimal_odds <= 1 or prob * decimal_odds <= 1:
            return 0.0
        full_kelly = (prob * decimal_odds - 1) / (decimal_odds - 1)
        return round(max(0.0, full_kelly) * kelly_fraction, 4)

    all_games_data = []
    for g in games:
        prob = engine.calculate_win_probability(g)
        implied = g["market_prob"]

        # Pick whichever side the model actually favors — the previous
        # version hardcoded "pick": g["home"] unconditionally, meaning every
        # single recommendation was the home team regardless of what prob
        # said. edge/odds are computed for whichever side is actually picked.
        if prob >= 0.5:
            pick, pick_prob, pick_odds = g["home"], prob, g["odds"]["home"]
        else:
            # Model favors away — convert market_prob/odds to the away side
            pick, pick_prob = g["away"], 1 - prob
            away_dec = 1 / (1 - implied) if implied < 1 else 2.0
            pick_odds = int((away_dec - 1) * 100) if away_dec >= 2 else int(-100 / (away_dec - 1))
        pick_implied = implied if pick == g["home"] else (1 - implied)
        edge = pick_prob - pick_implied
        pick_dec = (pick_odds/100)+1 if pick_odds > 0 else (100/abs(pick_odds))+1
        stake_frac = kelly_stake(pick_prob, pick_dec)

        print(f"{g['away']} @ {g['home']}: pick={pick}, prob={pick_prob:.3f}, "
              f"implied={pick_implied:.3f}, edge={edge:.3f}, kelly={stake_frac:.3f}")

        game_data = {
            "home": g["home"], "away": g["away"], "pick": pick,
            "pitcher": "TBD", "home_pitcher": g.get("home_pitcher", "TBD"),
            "away_pitcher": g.get("away_pitcher", "TBD"),
            "odds": pick_odds,
            "model_prob": round(pick_prob*100, 1), "edge": round(edge*100, 1),
            "edge_pct": round(edge*100, 1),  # written distinctly for mlb_backtest.py's
                                              # real-edge bucketing (analyse() prefers this
                                              # column over the implied-prob proxy)
            "kelly_stake_pct": round(stake_frac*100, 2),
            "line": g.get("real_total"),
            "kind": "team",
            # market was never set on these rows before, and mlb_backtest.py's
            # analyse() silently skips any row with an empty market column —
            # so every automated pick this script ever wrote was invisible to
            # the backtest, regardless of whether won/profit_1u ever got
            # filled in by hand later. "Moneyline" matches the value already
            # used by the manually-tracked rows in picks_log.csv, so both
            # sources bucket together correctly under by_market.
            "market": "Moneyline",
        }
        # Individual edge-term values, for mlb_fit_weights.py's eventual full
        # multi-factor regression against graded outcomes. Rounded to 4dp —
        # plenty of precision for a future fit, keeps the CSV readable.
        for _col, _val in g.get("_edge_components", {}).items():
            game_data[_col] = round(_val, 4)

        # ── qualifies: was hardcoded True for every game ("threshold
        #    removed"), which meant mlb_backtest.py's tuned min_edge and
        #    total-line band were written to mlb_config.json but never
        #    actually filtered anything. Real gating restored:
        #      - edge must clear min_edge (the moneyline edge computed
        #        above, for whichever side the model actually favors)
        #      - IF a real O/U total is available for this game, it must
        #        fall inside [min_total_line, max_total_line]. A missing
        #        total (bookmaker hasn't posted one yet) does NOT
        #        disqualify the moneyline pick — the two are different
        #        markets, and this system only produces one ML pick per
        #        game here, not a separate O/U pick, so an absent total is
        #        "unknown," not "out of band."
        min_edge = config.get("min_edge", 0.0)
        min_total_line = config.get("min_total_line", 6.0)
        max_total_line = config.get("max_total_line", 13.5)
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

    # Export ALL games so V6 UI always shows data — qualifies is now a real,
    # meaningful flag on each one (see above) rather than a decorative True
    # on every row, so the UI can filter/sort/highlight on it if desired.
    export_to_html(all_games_data)
    qualifying = sum(1 for gd in all_games_data if gd["qualifies"])
    print(f"\n✓ {len(all_games_data)} games exported ({qualifying} qualify at current thresholds)")
    print(f"✓ Picks → {PICKS_LOG_PATH}")
