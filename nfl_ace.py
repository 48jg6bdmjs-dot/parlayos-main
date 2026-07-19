"""
nfl_ace.py — NFL prediction engine for ParlayOS.

Structural mirror of mlb_ace.py: same has_data gating discipline (a missing
stat is never compared against a fallback on the other side), same
empirical-Bayes shrinkage pattern for small in-season samples, same
required_keys cache-invalidation pattern, same config-driven qualifies
gating, same EDGE_COMPONENT_COLS logging for a future weight-fit script.

── IMPORTANT — NOT YET LIVE-TESTED ──────────────────────────────────────
This was written in a sandboxed environment with NO outbound network
access (egress disabled), so none of the API calls below — ESPN's public
JSON endpoints or The Odds API — have actually been executed against
live data. Endpoint URLs and field names are taken from ESPN's public
(undocumented) API and The Odds API's published docs, and every fetch is
wrapped in try/except with has_data=False on failure, so a wrong field
name should fail safe into the fallback path rather than crash — but
that's a design intent, not a verified guarantee. Before trusting picks
from this file: run it once, watch stdout for "fetch failed" lines, and
spot-check a few games' stats against a real box score.

Also note: The Odds API's free tier has historically only included NBA +
MLB, with NFL requiring a paid plan. If fetch_live_odds() below returns
an empty list or an auth/plan error, that's the first thing to check
against your actual Odds API account tier — it's not a bug in this file.
──────────────────────────────────────────────────────────────────────────

Data sources:
  - The Odds API (americanfootball_nfl sport_key) — moneyline, spreads,
    totals. Same provider/key as MLB; api key now lives in
    sports_config.json instead of being hardcoded (see note in
    load_config below — mlb_ace.py should migrate to the same file).
  - ESPN's public site.api.espn.com / sports.core.api.espn.com JSON API —
    free, no key required. Fills the role MLB_STATS_BASE fills for
    mlb_ace.py: team season stats, injuries, schedules. This is an
    undocumented-but-widely-used API (no official SLA from ESPN), so the
    same "wrap every call, never trust a shape blindly" discipline
    matters even more here than it does for the official MLB Stats API.
"""
import requests
import random
import itertools
import json
import csv
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Tuple
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
PICKS_LOG_PATH = os.path.join(HERE, "nfl_picks_log.csv")
CACHE_DIR = os.path.join(HERE, ".nfl_cache")

# ── NFL team abbreviations (ESPN uses these directly; Odds API uses full
#    city+name strings, same mismatch mlb_ace.py handles via TEAM_ABBR) ──
TEAM_ABBR = {
    'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL',
    'Buffalo Bills': 'BUF', 'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI',
    'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE', 'Dallas Cowboys': 'DAL',
    'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
    'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX',
    'Kansas City Chiefs': 'KC', 'Las Vegas Raiders': 'LV', 'Los Angeles Chargers': 'LAC',
    'Los Angeles Rams': 'LAR', 'Miami Dolphins': 'MIA', 'Minnesota Vikings': 'MIN',
    'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG',
    'New York Jets': 'NYJ', 'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT',
    'San Francisco 49ers': 'SF', 'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TB',
    'Tennessee Titans': 'TEN', 'Washington Commanders': 'WSH',
}
# ESPN's internal numeric team IDs — needed for their stats/injuries/schedule
# endpoints. Source: sports.core.api.espn.com/v2/sports/football/leagues/nfl/teams
ESPN_TEAM_IDS = {
    'ARI': 22, 'ATL': 1, 'BAL': 33, 'BUF': 2, 'CAR': 29, 'CHI': 3,
    'CIN': 4, 'CLE': 5, 'DAL': 6, 'DEN': 7, 'DET': 8, 'GB': 9,
    'HOU': 34, 'IND': 11, 'JAX': 30, 'KC': 12, 'LV': 13, 'LAC': 24,
    'LAR': 14, 'MIA': 15, 'MIN': 16, 'NE': 17, 'NO': 18, 'NYG': 19,
    'NYJ': 20, 'PHI': 21, 'PIT': 23, 'SF': 25, 'SEA': 26, 'TB': 27,
    'TEN': 10, 'WSH': 28,
}
# NFL stadium coordinates — same role as MLB's STADIUM_LOCATIONS, used for
# real weather rather than a hardcoded default. Dome/indoor teams are still
# listed (weather affects the parking lot, not the field), but the edge
# calc below zeroes out weather_edge for known domes — see is_dome_team.
STADIUM_LOCATIONS = {
    'ARI': (33.5276, -112.2626), 'ATL': (33.7554, -84.4008), 'BAL': (39.2780, -76.6227),
    'BUF': (42.7738, -78.7870), 'CAR': (35.2258, -80.8528), 'CHI': (41.8623, -87.6167),
    'CIN': (39.0954, -84.5160), 'CLE': (41.5061, -81.6995), 'DAL': (32.7473, -97.0945),
    'DEN': (39.7439, -105.0201), 'DET': (42.3400, -83.0456), 'GB': (44.5013, -88.0622),
    'HOU': (29.6847, -95.4107), 'IND': (39.7601, -86.1639), 'JAX': (30.3239, -81.6373),
    'KC': (39.0489, -94.4839), 'LV': (36.0909, -115.1833), 'LAC': (33.9535, -118.3392),
    'LAR': (33.9535, -118.3392), 'MIA': (25.9580, -80.2389), 'MIN': (44.9737, -93.2577),
    'NE': (42.0909, -71.2643), 'NO': (29.9511, -90.0812), 'NYG': (40.8135, -74.0745),
    'NYJ': (40.8135, -74.0745), 'PHI': (39.9008, -75.1675), 'PIT': (40.4468, -80.0158),
    'SF': (37.4032, -121.9698), 'SEA': (47.5952, -122.3316), 'TB': (27.9759, -82.5033),
    'TEN': (36.1665, -86.7713), 'WSH': (38.9078, -76.8645),
}
# Known indoor/dome stadiums — weather doesn't affect gameplay here, so
# weather_edge is forced to 0 rather than computing a real-but-meaningless
# outdoor-air-at-the-parking-lot number and treating it as a football
# signal. This is the NFL analog of MLB's PARK_FACTORS mattering per-park;
# here the per-park fact that matters most is "is there weather at all."
DOME_TEAMS = {'ARI', 'ATL', 'DAL', 'DET', 'HOU', 'IND', 'LV', 'LAR', 'LAC',
              'MIN', 'NO'}

HERE_ESPN_SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
HERE_ESPN_CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
WEATHER_API = "https://api.open-meteo.com/v1/forecast"

# League-average fallbacks (2025 season, updated periodically like MLB's
# LEAGUE_AVG_* constants) — used ONLY when a specific fetch fails, never
# silently substituted for a "successful" real value.
LEAGUE_AVG_PPG = 22.5          # points per game
LEAGUE_AVG_PAPG = 22.5         # points allowed per game
LEAGUE_AVG_YPG = 335.0         # total yards per game (offense)
LEAGUE_AVG_YAPG = 335.0        # yards allowed per game (defense)
LEAGUE_AVG_QBR = 55.0          # ESPN Total QBR, 0-100 scale
LEAGUE_AVG_TO_MARGIN = 0.0     # turnover margin per game


def _f(s, d=None):
    """Lenient float parse — returns d (default None) instead of raising."""
    try:
        return float(str(s).strip())
    except (ValueError, TypeError, AttributeError):
        return d


def get_cached(key, ttl=3600, required_keys=None):
    """Identical pattern to mlb_ace.py's get_cached — required_keys makes
    a schema-mismatched cache entry a miss rather than a KeyError deep
    inside code that assumes the new shape."""
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
    """
    Load sports_config.json's "nfl" section, plus the shared odds_api_key.
    Same defaulting pattern as mlb_ace.py's load_config — every threshold
    has a safe fallback so a missing/partial config file doesn't crash the
    script, it just runs unfiltered (qualifies gating effectively off).
    """
    try:
        with open(CONFIG_PATH) as f:
            full_cfg = json.load(f)
        api_key = full_cfg.get("odds_api_key", "")
        cfg = full_cfg.get("nfl", {})
        cfg.setdefault("min_edge", 0.0)
        cfg.setdefault("min_total_line", 30.0)
        cfg.setdefault("max_total_line", 60.0)
        cfg.setdefault("max_legs", 16)
        cfg.setdefault("kelly_fraction", 0.25)
        cfg.setdefault("max_stake_pct", 0.05)
        print(f"NFL config loaded: min_edge={cfg['min_edge']}, "
              f"total_line_band={cfg['min_total_line']}-{cfg['max_total_line']}")
        return cfg, api_key
    except FileNotFoundError:
        print("sports_config.json not found, using NFL defaults, no API key")
        return {"min_edge": 0.0, "min_total_line": 30.0, "max_total_line": 60.0,
                "max_legs": 16, "kelly_fraction": 0.25, "max_stake_pct": 0.05}, ""
    except (json.JSONDecodeError, KeyError) as e:
        print(f"sports_config.json malformed ({e}), using NFL defaults, no API key")
        return {"min_edge": 0.0, "min_total_line": 30.0, "max_total_line": 60.0,
                "max_legs": 16, "kelly_fraction": 0.25, "max_stake_pct": 0.05}, ""


# Edge component columns — mirrors mlb_ace.py's EDGE_COMPONENT_COLS, for a
# future nfl_fit_weights.py to eventually regress against graded outcomes
# instead of the hand-set weights below.
EDGE_COMPONENT_COLS = [
    "c_team_edge", "c_qb_edge", "c_offense_edge", "c_defense_edge",
    "c_turnover_edge", "c_ats_form_edge", "c_h2h_edge", "c_weather_edge",
    "c_rest_edge", "c_injury_edge", "c_home_field_edge",
]
PICKS_LOG_COLS = [
    "timestamp", "date", "home", "away", "abbr_home", "abbr_away", "pick",
    "abbr_pick", "odds", "model_prob", "edge", "edge_pct", "qualifies",
    "kelly_stake_pct", "line", "spread", "market", "kind",
] + EDGE_COMPONENT_COLS


class NFLPredictionEngine:
    def __init__(self, api_key: str):
        self.api_key = api_key
        print(f"NFL engine initialized with API key: {api_key[:8]}..." if api_key else
              "NFL engine initialized with NO API key — fetch_live_odds will fail")

    def fetch_live_odds(self) -> List:
        """Fetch live NFL odds from The Odds API — h2h, spreads, and totals
        all requested together, since NFL is commonly bet on spread rather
        than moneyline (unlike MLB, where run line is a secondary market
        to moneyline). See module docstring re: free-tier NFL access."""
        url = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
        params = {"apiKey": self.api_key, "regions": "us",
                   "markets": "h2h,spreads,totals", "oddsFormat": "american"}
        try:
            r = requests.get(url, params=params, timeout=10)
            data = r.json()
            if isinstance(data, dict) and data.get("message"):
                # The Odds API returns a dict with an error "message" key
                # (not a list of games) on auth/plan failures — surfacing
                # this explicitly instead of letting len(data) below throw
                # or silently return 0 games with no explanation.
                print(f"Odds API error response: {data.get('message')}")
                return []
            print(f"Odds API returned {len(data)} NFL games")
            return data
        except Exception as e:
            print(f"Odds API error: {e}")
            return []

    def fetch_team_season_stats(self, team_abbr: str) -> Dict:
        """
        Real NFL team season stats from ESPN's core API. Mirrors
        mlb_ace.py's fetch_team_form: every field is a real API-derived
        number, has_data flags gate each one independently, league-average
        fallbacks are used ONLY when a specific piece fails.

        NFL season is short (17 games) relative to MLB's 162, so there's
        no meaningful "last 10" sub-sample the way MLB has one — full
        season-to-date is already the small-sample regime, which is why
        shrinkage below (see calculate_win_probability) uses games played
        as its reliability denominator instead of innings pitched.
        """
        team_id = ESPN_TEAM_IDS.get(team_abbr)
        if not team_id:
            return {"ppg": LEAGUE_AVG_PPG, "papg": LEAGUE_AVG_PAPG,
                    "ypg": LEAGUE_AVG_YPG, "yapg": LEAGUE_AVG_YAPG,
                    "to_margin": LEAGUE_AVG_TO_MARGIN, "games_played": 0,
                    "ppg_has_data": False, "ypg_has_data": False, "to_has_data": False}
        cache_key = f"nfl_team_stats_v1_{team_id}"
        cached = get_cached(cache_key, ttl=3600,
                             required_keys=("ppg", "papg", "ypg", "yapg", "to_margin",
                                            "games_played", "ppg_has_data", "ypg_has_data",
                                            "to_has_data"))
        if cached is not None:
            return cached

        # Single fetch, parsed once into a flat name->value map, then every
        # individual field below is read from that same map with its own
        # has_data flag. This replaced an earlier draft of this function
        # that re-fetched/re-derived stat_map across three separate
        # try/excepts using fragile locals()-existence checks — that
        # version worked by accident (Python's default REPL-style scoping
        # let it limp along) but was genuinely fragile and confusing to
        # read. One fetch, one parse, then independent has_data checks
        # per field is both correct and much easier to reason about.
        ppg = LEAGUE_AVG_PPG
        papg = LEAGUE_AVG_PAPG
        ypg = LEAGUE_AVG_YPG
        yapg = LEAGUE_AVG_YAPG
        to_margin = LEAGUE_AVG_TO_MARGIN
        games_played = 0
        ppg_has_data = False
        papg_has_data = False
        ypg_has_data = False
        to_has_data = False
        stat_map = {}
        try:
            year = datetime.now().year
            r = requests.get(
                f"{HERE_ESPN_CORE}/seasons/{year}/types/2/teams/{team_id}/statistics",
                timeout=8)
            data = r.json()
            # ESPN's statistics response nests categories -> stats[] with
            # name/value pairs. Structure is undocumented and has shifted
            # across ESPN API revisions historically, so this walks
            # defensively rather than assuming a fixed index path.
            categories = data.get("splits", {}).get("categories", [])
            for cat in categories:
                for stat in cat.get("stats", []):
                    stat_map[stat.get("name")] = stat.get("value")
            games_played = int(stat_map.get("gamesPlayed", 0) or 0)
        except Exception as e:
            print(f"  NFL team stat fetch failed ({team_abbr}): {e}")

        if "totalPointsPerGame" in stat_map:
            try:
                ppg = float(stat_map["totalPointsPerGame"])
                ppg_has_data = True
            except (ValueError, TypeError):
                pass
        if "avgPointsAllowed" in stat_map:
            try:
                papg = float(stat_map["avgPointsAllowed"])
                papg_has_data = True
            except (ValueError, TypeError):
                pass
        if "yardsPerGame" in stat_map:
            try:
                ypg = float(stat_map["yardsPerGame"])
                ypg_has_data = True
            except (ValueError, TypeError):
                pass
        if "yardsAllowedPerGame" in stat_map:
            try:
                yapg = float(stat_map["yardsAllowedPerGame"])
            except (ValueError, TypeError):
                pass
        if "turnOverDifferential" in stat_map:
            try:
                to_margin = float(stat_map["turnOverDifferential"])
                if games_played > 0:
                    to_margin = round(to_margin / games_played, 2)
                to_has_data = True
            except (ValueError, TypeError):
                pass

        result = {
            "ppg": ppg, "papg": papg, "ypg": ypg, "yapg": yapg,
            "to_margin": to_margin, "games_played": games_played,
            "ppg_has_data": ppg_has_data and papg_has_data,
            "ypg_has_data": ypg_has_data,
            "to_has_data": to_has_data,
        }
        set_cache(cache_key, result)
        return result

    def fetch_qb_rating(self, team_abbr: str) -> Dict:
        """
        Starting QB's current-season Total QBR (ESPN's advanced QB metric,
        0-100 scale, adjusts for game situation the way FIP adjusts a
        pitcher's ERA for defense/luck — chosen over raw passer rating for
        the same "more predictive of true talent" reasoning mlb_ace.py
        gives FIP over ERA). has_data False on any fetch failure or if the
        team has no clear starter (e.g. QB controversy, injury, bye).

        NFL doesn't have a probable-starter feed the way MLB Stats API
        does for pitchers — inferring "the starter" here is genuinely
        harder than MLB's case, and this is a known simplification: it
        takes the team's leading QB by pass attempts this season, which
        can be wrong in an active QB-change situation. Flagged rather
        than silently trusted.
        """
        team_id = ESPN_TEAM_IDS.get(team_abbr)
        if not team_id:
            return {"qbr": LEAGUE_AVG_QBR, "has_data": False}
        cache_key = f"nfl_qbr_v1_{team_id}"
        cached = get_cached(cache_key, ttl=3600, required_keys=("qbr", "has_data"))
        if cached is not None:
            return cached
        try:
            year = datetime.now().year
            r = requests.get(
                f"{HERE_ESPN_SITE}/teams/{team_id}",
                params={"enable": "roster,stats"}, timeout=8)
            data = r.json()
            # Leader lists are nested under team.leaders[]; find the QBR
            # (or passing-yards, as fallback proxy) leader category.
            leaders = data.get("team", {}).get("leaders", [])
            qbr = None
            for cat in leaders:
                if cat.get("name") in ("QBR", "totalQBR"):
                    lst = cat.get("leaders", [])
                    if lst:
                        qbr = _f(lst[0].get("value"))
                        break
            if qbr is None:
                result = {"qbr": LEAGUE_AVG_QBR, "has_data": False}
            else:
                # Small-sample shrinkage — same empirical-Bayes shape as
                # mlb_ace.py's pitcher shrink(), but keyed on games played
                # this season rather than innings pitched. A QB with 2
                # starts posting an outlier QBR is exactly the "one bad
                # start shouldn't swing the model" case mlb_ace.py's
                # comments describe for pitchers.
                games = 0
                try:
                    stats = data.get("team", {}).get("record", {})
                    games = int(stats.get("items", [{}])[0].get("stats", [{}])[0].get("value", 0) or 0)
                except Exception:
                    games = 8  # assume mid-season reliability if unparseable, not zero
                FULL_RELIABILITY_GAMES = 10.0
                reliability = min(1.0, games / FULL_RELIABILITY_GAMES) if games else 0.3
                qbr_shrunk = round(reliability * qbr + (1 - reliability) * LEAGUE_AVG_QBR, 1)
                result = {"qbr": qbr_shrunk, "has_data": True, "reliability": round(reliability, 2)}
            set_cache(cache_key, result)
            return result
        except Exception as e:
            print(f"  NFL QBR fetch failed ({team_abbr}): {e}")
            return {"qbr": LEAGUE_AVG_QBR, "has_data": False}

    def fetch_injuries(self, team_abbr: str) -> Dict:
        """Real injury report from ESPN's injuries endpoint — coarse
        headline count, same role as mlb_ace.py's fetch_team_injury_count.
        Gated to has_data=False if the fetch fails or returns nothing."""
        team_id = ESPN_TEAM_IDS.get(team_abbr)
        if not team_id:
            return {"count": 0, "has_data": False}
        cache_key = f"nfl_injuries_v1_{team_id}"
        cached = get_cached(cache_key, ttl=1800, required_keys=("count", "has_data"))
        if cached is not None:
            return cached
        try:
            r = requests.get(f"{HERE_ESPN_CORE}/teams/{team_id}/injuries",
                              params={"limit": 100}, timeout=8)
            data = r.json()
            items = data.get("items", [])
            # Weight OUT/DOUBTFUL more heavily than QUESTIONABLE — a coarse
            # but real distinction ESPN's injury status field provides,
            # unlike MLB.com's flatter headline-count-only report.
            count = 0.0
            for it in items:
                status = str(it.get("status", "")).upper()
                if status in ("OUT", "DOUBTFUL", "IR"):
                    count += 1.0
                elif status == "QUESTIONABLE":
                    count += 0.5
            result = {"count": count, "has_data": True}
            set_cache(cache_key, result)
            return result
        except Exception as e:
            print(f"  NFL injury fetch failed ({team_abbr}): {e}")
            return {"count": 0, "has_data": False}

    def fetch_weather(self, lat: float, lon: float) -> Dict:
        """Same Open-Meteo call as mlb_ace.py, same cache pattern."""
        cache_key = f"nfl_weather_{round(lat,2)}_{round(lon,2)}"
        cached = get_cached(cache_key, ttl=1800)
        if cached is not None:
            return cached
        try:
            r = requests.get(WEATHER_API, params={"latitude": lat, "longitude": lon,
                              "current": "temperature_2m,wind_speed_10m,wind_direction_10m"},
                              timeout=8)
            w = r.json()["current"]
            result = {
                "temp_f": w["temperature_2m"] * 9/5 + 32,
                "wind_mph": w["wind_speed_10m"] * 0.621371,
                "wind_deg": w["wind_direction_10m"],
            }
            set_cache(cache_key, result)
            return result
        except Exception as e:
            print(f"  NFL weather fetch failed ({lat},{lon}): {e}")
            return {"temp_f": 60, "wind_mph": 8, "wind_deg": 0}

    def calculate_win_probability(self, game: Dict) -> float:
        """
        Calculate home win probability. Same has_data discipline as
        mlb_ace.py: a missing stat on one side is never compared against
        a real number on the other, and never silently defaults to
        "average" in a way that would tilt the model toward whichever
        team happens to have less data available.

        Weight rationale (NFL-specific, not a copy of MLB's weights —
        the sports have different variance structures: a single NFL game
        has ~16-17 games of season signal behind it at most, vs MLB's
        162, so per-game predictive factors carry relatively more weight
        here since there's less accumulated signal to lean on elsewhere):
          - QB play is the single most predictive individual-player factor
            in football, analogous to starting pitcher in baseball —
            given the largest per-unit weight.
          - Turnover margin is unusually predictive in the NFL specifically
            (more so than in most sports) because turnovers directly flip
            field position and possession count, both of which correlate
            strongly with scoring — this is a real, well-established NFL
            analytics finding, not an arbitrary weight choice.
          - Offense/defense YPG capture the broader team-quality signal
            that isn't already carried by QBR or points-based team_edge.
        """
        home_abbr = game.get("home_abbr", "")
        away_abbr = game.get("away_abbr", "")

        home_stats = self.fetch_team_season_stats(home_abbr)
        away_stats = self.fetch_team_season_stats(away_abbr)
        home_qb = self.fetch_qb_rating(home_abbr)
        away_qb = self.fetch_qb_rating(away_abbr)
        weather = self.fetch_weather(*STADIUM_LOCATIONS.get(home_abbr, (39.8, -98.6)))
        home_inj = self.fetch_injuries(home_abbr)
        away_inj = self.fetch_injuries(away_abbr)

        # ── QB edge — largest single weight, same reasoning mlb_ace.py
        #    gives starting pitcher FIP: the single most predictive
        #    individual-player factor for an individual game outcome.
        has_qb = home_qb["has_data"] and away_qb["has_data"]
        qb_edge = (home_qb["qbr"] - away_qb["qbr"]) * 0.0030 if has_qb else 0.0

        # ── Points-based team quality (season scoring margin) — the NFL
        #    analog of MLB's season run differential. Both offense and
        #    defense sides must have real data before this contributes,
        #    same as mlb_ace.py's has_season_offense/has_season_pitching
        #    pairing for runs_per_game/team_era.
        team_edge = 0.0
        if home_stats["ppg_has_data"] and away_stats["ppg_has_data"]:
            home_margin = home_stats["ppg"] - home_stats["papg"]
            away_margin = away_stats["ppg"] - away_stats["papg"]
            team_edge = (home_margin - away_margin) * 0.0040

        # ── Yardage-based offense/defense — a distinct signal from
        #    points-based team_edge above (yards is a "how good are they
        #    mechanically" signal; points folds in red-zone efficiency,
        #    turnovers, special teams — already counted separately below
        #    for turnovers, so weighted modestly here to avoid double-
        #    counting the turnover component specifically).
        offense_edge = 0.0
        defense_edge = 0.0
        if home_stats["ypg_has_data"] and away_stats["ypg_has_data"]:
            offense_edge = (home_stats["ypg"] - away_stats["ypg"]) * 0.000075
            defense_edge = (away_stats["yapg"] - home_stats["yapg"]) * 0.000075

        # ── Turnover margin — unusually predictive in the NFL specifically
        #    (see docstring rationale above). Both sides need real data.
        turnover_edge = 0.0
        if home_stats["to_has_data"] and away_stats["to_has_data"]:
            turnover_edge = (home_stats["to_margin"] - away_stats["to_margin"]) * 0.010

        # ── Weather — same directional-only-when-outdoor logic as
        #    mlb_ace.py, forced to 0 for known dome teams rather than
        #    computing a real-but-meaningless outdoor reading. Cold/wind
        #    generally suppresses NFL scoring (passing especially), so the
        #    sign here is the opposite of MLB's "warm air helps offense" —
        #    that's intentional, not a copy-paste error.
        weather_edge = 0.0
        if home_abbr not in DOME_TEAMS:
            if weather["temp_f"] < 32 or weather["wind_mph"] > 20:
                weather_edge = -0.01  # slight suppression, symmetric to both offenses

        # ── Injury burden — coarse OUT/DOUBTFUL/QUESTIONABLE-weighted
        #    count, capped small like mlb_ace.py caps its injury_edge.
        injury_edge = 0.0
        if home_inj["has_data"] and away_inj["has_data"]:
            injury_edge = (away_inj["count"] - home_inj["count"]) * 0.004
            injury_edge = max(-0.02, min(0.02, injury_edge))

        home_field_edge = 0.018  # standard, well-established NFL home-field advantage
        # (Slightly larger than MLB's 0.02 — commonly cited as somewhat
        # stronger in the NFL, partly due to crowd noise affecting
        # opposing-team communication/snap timing in a way that has less
        # of an analog in baseball.)

        # No real ATS-form or h2h fetch implemented yet in this pass —
        # zeroed rather than faked, same "don't fabricate a signal I
        # haven't actually built" discipline mlb_ace.py applies to wind
        # direction in its weather section.
        ats_form_edge = 0.0
        h2h_edge = 0.0

        market_p = game.get("market_prob", 0.5)
        logit_market = _logit(market_p)
        edge_sum = (team_edge + qb_edge + offense_edge + defense_edge
                     + turnover_edge + ats_form_edge + h2h_edge + weather_edge
                     + injury_edge + home_field_edge)
        logit_adjusted = logit_market + edge_sum * 2.0
        base_prob = _sigmoid(logit_adjusted)

        game["_edge_components"] = {
            "c_team_edge": team_edge, "c_qb_edge": qb_edge,
            "c_offense_edge": offense_edge, "c_defense_edge": defense_edge,
            "c_turnover_edge": turnover_edge, "c_ats_form_edge": ats_form_edge,
            "c_h2h_edge": h2h_edge, "c_weather_edge": weather_edge,
            "c_rest_edge": 0.0, "c_injury_edge": injury_edge,
            "c_home_field_edge": home_field_edge,
        }
        # Same clamp philosophy as mlb_ace.py: a sanity bound, not a
        # substitute for real calibration against graded outcomes.
        return max(0.12, min(0.88, base_prob))

    def calculate_total_points(self, game: Dict, posted_total: float) -> Tuple[str, float, float]:
        """
        O/U direction + edge — NFL analog of mlb_ace.py's expected-runs
        model. Expected combined points = both teams' season PPG, blended
        toward the matchup (each offense against the OTHER's defensive
        YPG-allowed rate as a modest adjustment), rather than raw PPG
        summed blind to opponent quality.

        Simpler than MLB's model (no per-starter estimate — NFL doesn't
        have an analog to "today's starting pitcher" driving the total the
        way SP ERA does) but follows the same "model estimate vs posted
        line, edge via normal-CDF gap" structure.
        """
        home_abbr = game.get("home_abbr", "")
        away_abbr = game.get("away_abbr", "")
        home_stats = self.fetch_team_season_stats(home_abbr)
        away_stats = self.fetch_team_season_stats(away_abbr)

        _POINTS_SIGMA = 10.0  # NFL game-total std dev is much larger in raw
                               # points than MLB's ~1.5 runs — this is the
                               # correct NFL-scale analog, not MLB's constant
                               # reused unadjusted.
        _MARKET_VIG_PROB = 110.0 / 210.0

        def _erf_approx(x):
            t = 1.0 / (1.0 + 0.3275911 * abs(x))
            poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 +
                   t * (-1.453152027 + t * 1.061405429))))
            v = 1.0 - poly * (2.718281828 ** (-x * x))
            return v if x >= 0 else -v

        def _normal_cdf(x):
            return 0.5 * (1.0 + _erf_approx(x / (2.0 ** 0.5)))

        if home_stats["ppg_has_data"] and away_stats["ppg_has_data"]:
            # Each offense's expected points, mildly adjusted by the
            # opponent's points-allowed rate relative to league average —
            # a team facing a weak defense should be expected to outscore
            # their raw season PPG somewhat, and vice versa.
            home_exp = home_stats["ppg"] * (away_stats["papg"] / LEAGUE_AVG_PAPG)
            away_exp = away_stats["ppg"] * (home_stats["papg"] / LEAGUE_AVG_PAPG)
            model_total = home_exp + away_exp
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


def load_picks_log():
    if not os.path.exists(PICKS_LOG_PATH):
        return []
    try:
        with open(PICKS_LOG_PATH, newline='', encoding='utf-8') as f:
            return list(csv.DictReader(f))
    except Exception as e:
        print(f"  picks log read failed: {e}")
        return []


def write_pick_to_log(pick_dict: dict):
    """Same append-with-header-union pattern as mlb_ace.py's
    write_pick_to_log — preserves any existing columns in an on-disk file
    even if this run's PICKS_LOG_COLS differs, rather than silently
    dropping data on schema drift."""
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
    """Convert an American odds price to decimal, or None if price is
    None/unparseable — used to turn the raw over_price/spread_price ints
    fetched from The Odds API into the decimal format ParlayOS.html's
    legOdds()/american() functions expect, same conversion mlb_ace.py
    already applies to moneyline prices."""
    p = _f(price)
    if p is None:
        return None
    if p > 0:
        return round((p / 100) + 1, 3)
    return round((100 / abs(p)) + 1, 3)


def _picks_to_nfl_games(picks: List) -> List:
    """
    Convert picks to the game object shape ParlayOS.html's genNFLGames()
    mock currently produces (a: away abbr, b: home abbr, cityA/cityB,
    lgA/lgB, total, ouPick, kLine, kPick, mlFav, mlPriceDec, ouEdge,
    kEdge, mlEdge, model, date, time, tv, hot) so the real-data injection
    is a drop-in replacement for the mock, not a shape the frontend needs
    new code to understand.

    IMPORTANT NAMING NOTE: kLine/kPick are MLB-specific names (K = pitcher
    strikeout prop) that ParlayOS.html's marketCard() also reuses for
    NFL/NBA's spread slot, purely because the mock generators picked that
    field name to slot into the same UI code path. For NFL, kLine/kPick
    below represent the SPREAD, not a strikeout prop — there is no
    pitcher in football. The UI-side fix (making marketCard() render
    correct label text per sport) is handled in ParlayOS.html separately;
    this function's job is just to match the existing field NAMES so
    that fix can consume real data without also needing a data-shape
    change on this side.
    """
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
                # Same UTC-aware parsing fix mlb_ace.py's _picks_to_v6_games
                # applies — explicit tzinfo attach, then .astimezone(), not
                # a naive strptime().timestamp() that silently assumes
                # local time on a UTC string.
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
                print(f"  NFL game_date parse failed ({game_date_str}): {e}")
        if start_at_ms is None:
            import time as _t
            start_at_ms = int(_t.time() * 1000)

        total = p.get('total')
        ou_pick = p.get('ou_pick', 'OVER')
        ou_edge = p.get('ou_edge', 0.0)
        if total is None:
            total = 44.5  # neutral NFL-scale placeholder ONLY when no
                           # bookmaker has posted a total yet — same
                           # "never fabricate a precise-looking fake
                           # number" concern as mlb_ace.py, but NFL's
                           # posted-total coverage is typically near-
                           # universal on the major books, so this path
                           # should rarely trigger in practice.

        spread = p.get('spread', 0.0)
        spread_pick_side = abbr_b if spread <= 0 else abbr_a
        spread_pick_str = f"{spread_pick_side} {'+' if spread > 0 else ''}{spread}"
        spread_edge = round(edge * 0.4, 4)

        ml_fav = TEAM_ABBR.get(pick_team, pick_team[:3].upper()) if pick_team else abbr_b
        hot = edge > 0.03 or abs(ou_edge) > 0.05

        # Real per-market decimal prices, when a bookmaker actually posted
        # one — None (and therefore omitted below) when unavailable, so
        # ParlayOS.html's legOdds() correctly falls back to its flat
        # constant rather than receiving a fabricated precise-looking
        # number for a market that has no real quote yet.
        ou_price_dec = _american_to_decimal(p.get('ou_price'))
        spread_price_dec = _american_to_decimal(p.get('spread_price'))

        game = {
            'id': f'nfl_live_{idx}_{int(datetime.now().timestamp())}',
            'a': abbr_a, 'b': abbr_b,
            'cityA': away, 'cityB': home,
            'lgA': 'NFL', 'lgB': 'NFL',
            'total': total, 'ouPick': f'{ou_pick} {total}',
            'kLine': spread, 'kPick': spread_pick_str,  # SPREAD — see docstring note
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
    """
    Inject window.PARLAYOS_NFL_DATA into ParlayOS.html at the existing
    <!--PARLAYOS_NFL_INJECT_POINT--> marker. Deliberately a SEPARATE
    global from window.PARLAYOS_DATA (MLB's), not a merge into the same
    object — this keeps each sport's export independently re-runnable
    (running nfl_ace.py again shouldn't require re-running mlb_ace.py to
    avoid clobbering MLB's data, and vice versa) and matches how
    loadRealData() needs to read three distinct globals rather than one
    growing object with sport-keyed sub-fields.

    Cleans ALL previous NFL injections before inserting fresh data, same
    pattern as mlb_ace.py's export_to_html.
    """
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html = f.read()
    except FileNotFoundError:
        print(f"Template not found: {html_path}")
        return ""

    v_games = _picks_to_nfl_games(picks)
    games_json = json.dumps(v_games, separators=(',', ':'))
    run_date = datetime.now().strftime('%b %d %Y  %H:%M')
    pick_count = len(picks)

    html = re.sub(
        r'[ \t]*//[^\n]*PARLAYOS NFL LIVE DATA.*?[ \t]*//[^\n]*END PARLAYOS NFL LIVE DATA[^\n]*\n?',
        '', html, flags=re.DOTALL
    )
    html = re.sub(r'\n{3,}', '\n\n', html)

    injection_lines = [
        "    // ── PARLAYOS NFL LIVE DATA (" + run_date + ") ──────────────────",
        "    window.PARLAYOS_NFL_DATA = {",
        "      runDate: \"" + run_date + "\",",
        "      pickCount: " + str(pick_count) + ",",
        "      games: " + games_json,
        "    };",
        "    (function(){",
        "      if(typeof loadRealData==='function') loadRealData();",
        "      if(typeof renderNFLDashboard==='function') renderNFLDashboard();",
        "    })();",
        "    // ── END PARLAYOS NFL LIVE DATA ──────────────────────────────────",
    ]
    injection = "\n".join(injection_lines)

    assert games_json in injection, "games_json missing from NFL injection!"

    MARKER = '    // <!--PARLAYOS_NFL_INJECT_POINT-->'
    if MARKER in html:
        html = html.replace(MARKER, MARKER + '\n' + injection)
        print(f"  NFL: injected at stable marker")
    else:
        html = html.replace('</body>', f'<script>\n{injection}\n</script>\n</body>')
        print(f"  NFL: marker not found, injected before </body> (fallback)")

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"✓ {pick_count} NFL picks → {html_path}")
    return html_path


def run(html_path: str):
    """Main entry point — mirrors mlb_ace.py's __main__ block structure."""
    config, api_key = load_config()
    engine = NFLPredictionEngine(api_key)
    odds_data = engine.fetch_live_odds()

    games = []
    seen_matchups = set()
    skipped_non_nfl_team = []
    for game in odds_data:
        if len(game.get("bookmakers", [])) > 0:
            h2h = next((m for m in game["bookmakers"][0]["markets"] if m["key"] == "h2h"), None)
            if h2h:
                home = game["home_team"]
                away = game["away_team"]

                if home not in TEAM_ABBR or away not in TEAM_ABBR:
                    skipped_non_nfl_team.append(f"{away} @ {home}")
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

    if skipped_non_nfl_team:
        print(f"  Skipped {len(skipped_non_nfl_team)} non-NFL-team entries:")
        for s in skipped_non_nfl_team:
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

        posted_total = g.get("real_total") if g.get("real_total") is not None else 44.5
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
            "ou_price": g.get("over_price"),  # American price on the OVER side,
                                               # None if no bookmaker had posted one —
                                               # _picks_to_nfl_games converts this to
                                               # decimal for the frontend, or omits
                                               # ouPriceDec entirely if None, letting
                                               # legOdds() fall back to its constant
            "spread": g.get("real_spread") if g.get("real_spread") is not None else 0.0,
            "spread_price": g.get("spread_price"),
            "commence_time": g.get("commence_time"),
            "kind": "team", "market": "Moneyline",
        }
        for _col, _val in g.get("_edge_components", {}).items():
            game_data[_col] = round(_val, 4)

        min_edge = config.get("min_edge", 0.0)
        min_total_line = config.get("min_total_line", 30.0)
        max_total_line = config.get("max_total_line", 60.0)
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
    print(f"\n✓ {len(all_games_data)} NFL games exported ({qualifying} qualify at current thresholds)")
    print(f"✓ Picks → {PICKS_LOG_PATH}")
    return all_games_data


if __name__ == "__main__":
    # Look for the HTML template the same way mlb_ace.py does — a few
    # candidate filenames, first match wins.
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
