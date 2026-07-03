#!/usr/bin/env python3
"""
================================================================================
 mlb_ace.py  —  MLB Totals Model + Self-Rendering Dashboard  (single file)
================================================================================
 Philosophy
 ----------
   * ONE market, done well: game totals (Over/Under).  Narrow scope = accuracy.
   * The MODEL makes every decision.  No LLM is asked to "estimate" anything.
     This script renders the finished Markdown dashboard itself, so there is
     no second source of truth and nothing to hallucinate.
   * Pure standard library.  numpy is never imported (its iOS/a-Shell build
     crashes at the Lock layer).  The Monte-Carlo runs fine in plain Python.
   * Edges are de-vigged: model probability is compared to the FAIR (no-juice)
     line, not the raw implied line.  Half of apparent "edge" is just hold.
   * Thresholds live in mlb_config.json, which mlb_backtest.py rewrites from
     your real closing-line results.  The system tunes itself.

 Run
 ---
   python3 mlb_ace.py                 # today's slate
   python3 mlb_ace.py --date 2026-06-27
   python3 mlb_ace.py --sims 30000

 Output
 ------
   Writes mlb_dashboard.md next to this script AND prints it to stdout.
   The Apple Shortcut needs exactly one step: run this, then show the file.
================================================================================
"""

import argparse
import csv
import json
import math
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

HERE        = os.path.dirname(os.path.abspath(__file__))
# Optional PIL for table card rendering
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False
CONFIG_PATH = os.path.join(HERE, "mlb_config.json")
OUTPUT_PATH = os.path.join(HERE, "acebot_dashboard.html")
LINE_HISTORY_PATH = os.path.join(HERE, "mlb_line_history.json")
PICKS_CSV   = os.path.join(HERE, "picks_log.csv")
# Historical schema, matched exactly to what mlb_backtest.py's analyse()
# reads via csv.DictReader -- kind=total (team=AWY@HME) or kind=team (full
# team name, market=Moneyline). tag=auto for model-generated picks, so they
# stay distinguishable from any manually-logged rows in the same file.
PICKS_HEADER = ("date,tag,team,kind,market,open_ml,close_ml,clv_pts,"
                "won,profit_1u,slip_id,slip_odds,slip_result\n")
ODDS_KEY    = "c5258b13e74c8742cdcb8981b714bbc7"

# =============================================================================
# Table card rendering (added for AceBot)
# =============================================================================
def _render_table_card(json_data, date_str):
    if not PIL_AVAILABLE:
        return
    try:
        W, H = 1080, 1350
        green = (34,180,85)
        black = (0,0,0)
        white = (235,235,235)
        gray = (80,80,80)
        img = Image.new("RGB", (W, H), green)
        d = ImageDraw.Draw(img)
        margin = 30
        # inner black
        d.rectangle([margin, 200, W-margin, H-margin], fill=black)
        # logo - try to load acebot_logo.png from same folder, else use text
        logo_path = os.path.join(HERE, "acebot_logo.png")
        if os.path.exists(logo_path):
            try:
                logo = Image.open(logo_path).convert("RGBA")
                # scale to height ~70px (small as title)
                h = 70
                w = int(logo.width * h / logo.height)
                logo = logo.resize((w, h), Image.LANCZOS)
                img.paste(logo, ((W-w)//2, 60), logo)
            except Exception:
                pass
        else:
            # fallback text
            try:
                ft = ImageFont.truetype("/System/Library/Fonts/SFNSDisplay.ttf", 28)
            except:
                ft = ImageFont.load_default()
            d.text((W//2, 95), "ACEBOT", fill=(10,40,20), font=ft, anchor="mm")
        # fonts
        try:
            font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
            font_reg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
            font_mono = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 20)
        except:
            font_bold = font_reg = font_mono = ImageFont.load_default()
        # titles
        d.text((margin+20, 230), "MLB Combined", fill=white, font=font_bold)
        d.text((margin+20, 265), "Dashboard & Bet Slip", fill=white, font=font_bold)
        d.text((margin+20, 305), date_str, fill=(170,170,170), font=font_reg)
        d.text((margin+20, 360), "Today's Slate & Odds", fill=white, font=font_bold)
        # table
        headers = ["Matchup","Venue","Away SP","Home SP","Line","Proj","ML","Pick","Edge"]
        rows = []
        for g in json_data.get("games", [])[:13]:
            matchup = g.get("matchup","")
            venue = g.get("venue","").replace(" Field","").replace(" Park","").replace(" Stadium","")
            asp = (g.get("away_sp") or "").split()[-1]
            hsp = (g.get("home_sp") or "").split()[-1]
            line = f"{g.get('line',0):.1f}" if g.get('line') else "—"
            proj = f"{g.get('proj_total',0):.1f}"
            # ML fav
            a_pw = g.get("p_away_win",0); h_pw = g.get("p_home_win",0)
            if a_pw >= h_pw:
                ml = f"{matchup.split('@')[0].strip()} {int(a_pw)}%"
            else:
                ml = f"{matchup.split('@')[1].strip()} {int(h_pw)}%"
            pick = g.get("pick","") or "—"
            if pick and g.get("line"):
                pick = f"{pick}{g.get('line'):.1f}"
            edge = f"+{g.get('edge_pct',0):.1f}%" if g.get("pick") else "—"
            rows.append([matchup, venue, asp, hsp, line, proj, ml, pick, edge])
        # draw grid
        x0 = margin+20; y0 = 410
        col_w = [140, 170, 90, 90, 60, 60, 120, 80, 80]
        row_h = 44
        # header
        for i, h in enumerate(headers):
            x = x0 + sum(col_w[:i])
            d.rectangle([x, y0, x+col_w[i], y0+row_h], outline=gray, width=1)
            d.text((x+6, y0+10), h, fill=(200,255,200), font=font_reg)
        # rows
        y = y0 + row_h
        for r in rows:
            for i, cell in enumerate(r):
                x = x0 + sum(col_w[:i])
                d.rectangle([x, y, x+col_w[i], y+row_h], outline=(40,40,40), width=1)
                d.text((x+6, y+10), str(cell)[:14], fill=white, font=font_mono)
            y += row_h
        out_path = os.path.join(HERE, "mlb_table.png")
        img.save(out_path)
        print(f"\n🖼️  Table card → {out_path}")
    except Exception as e:
        print(f"Table render failed: {e}")

# ==============================================================================
# MODEL CONSTANTS  (kept from the tuned engine; these are the parts that worked)
# ==============================================================================
EARNED_RUN_SHARE = 0.92      # ERA -> RA9 conversion (unearned runs share)
SP_PRIOR_IP      = 90.0      # innings of league-mean prior for a starter - increased from 45 to tame tiny-sample pitchers like Waldrep (2 IP)
XERA_WEIGHT      = 0.50      # weight of xERA inside the ERA/xERA core
FIP_WEIGHT_MAX   = 0.30      # max weight FIP can take (scales with sample)
SKILL_WEIGHT     = 0.20      # weight of the K/9-BB/9 skill signal
K9_LG            = 9.0       # league SP K/9
BB9_LG           = 3.0       # league SP BB/9
K9_RA9_PER       = 0.09      # RA9 change per 1 K/9 above/below league
BB9_RA9_PER      = 0.11      # RA9 change per 1 BB/9 above/below league
FIP_CONST        = 3.10

STARTER_INNINGS  = 6.5       # expected SP innings — gives starter 72% weight in run prevention
HOME_OFF_MULT    = 1.018     # tiny home-field offensive nudge
AWAY_OFF_MULT    = 0.982

CROOKED_PROB     = 0.058     # overdispersion: chance a scoring inning "kicks"
CROOKED_EXTRA    = 1
ENV_SHARED_K     = 28.0      # shared (park/weather/ump) gamma shape
ENV_TEAM_K       = 8.5       # per-team gamma shape
GHOST_RUNNER_BONUS = 0.55    # extra-innings ghost-runner scoring bump
MAX_EXTRA_INNINGS  = 6
ENSEMBLE_MC_WEIGHT = 0.70    # blend empirical MC with normal-approx for p_over
PYTH_EXP           = 1.83   # Pythagorean exponent for ML win probability

LEAGUE_RPG_FALLBACK = 4.40

PARK_FACTORS = {
    "Colorado Rockies": 1.15, "Cincinnati Reds": 1.05, "Boston Red Sox": 1.04,
    "Athletics": 1.04, "Philadelphia Phillies": 1.02, "Baltimore Orioles": 1.02,
    "New York Yankees": 1.02, "Tampa Bay Rays": 1.02, "Kansas City Royals": 1.01,
    "Chicago Cubs": 1.01, "Texas Rangers": 1.01, "Arizona Diamondbacks": 1.01,
    "Toronto Blue Jays": 1.01, "Washington Nationals": 1.01, "Milwaukee Brewers": 1.01,
    "Chicago White Sox": 1.01, "Minnesota Twins": 1.00, "Atlanta Braves": 1.00,
    "Houston Astros": 1.00, "Los Angeles Angels": 0.99, "St. Louis Cardinals": 0.99,
    "Los Angeles Dodgers": 0.98, "Cleveland Guardians": 0.98, "Pittsburgh Pirates": 0.98,
    "New York Mets": 0.97, "Detroit Tigers": 0.97, "Miami Marlins": 0.97,
    "San Diego Padres": 0.95, "Seattle Mariners": 0.94, "San Francisco Giants": 0.93,
}
PARK_DEFAULT = 1.00

# Venue (lat, lon, CF bearing deg).  Wind FROM the CF bearing blows IN.
VENUE_META = {
    "Wrigley Field": (41.9484, -87.6553, 45), "Yankee Stadium": (40.8296, -73.9262, 90),
    "Fenway Park": (42.3467, -71.0972, 20), "Dodger Stadium": (34.0739, -118.240, 330),
    "T-Mobile Park": (47.5914, -122.333, 350), "Oracle Park": (37.7786, -122.389, 295),
    "Coors Field": (39.7560, -104.994, 295), "Great American Ball Park": (39.0979, -84.5076, 20),
    "Camden Yards": (39.2839, -76.6212, 350), "Truist Park": (33.8907, -84.4677, 0),
    "Globe Life Field": (32.7479, -97.0838, 340), "Minute Maid Park": (29.7572, -95.3554, 300),
    "Chase Field": (33.4453, -112.067, 0), "Kauffman Stadium": (39.0515, -94.4803, 0),
    "Guaranteed Rate Field": (41.8299, -87.6338, 50), "Rate Field": (41.8299, -87.6338, 50),
    "Progressive Field": (41.4962, -81.6852, 60), "PNC Park": (40.4469, -80.0057, 30),
    "Busch Stadium": (38.6226, -90.1928, 10), "Petco Park": (32.7076, -117.157, 295),
    "loanDepot park": (25.7781, -80.2199, 350), "Citi Field": (40.7571, -73.8458, 350),
    "Citizens Bank Park": (39.9061, -75.1665, 10), "Nationals Park": (38.8730, -77.0074, 0),
    "Tropicana Field": (27.7682, -82.6534, 0), "American Family Field": (43.0280, -87.9712, 345),
    "Target Field": (44.9817, -93.2781, 25), "Angel Stadium": (33.8003, -117.883, 320),
    "Comerica Park": (42.3390, -83.0485, 350), "Rogers Centre": (43.6414, -79.3894, 0),
    "Oriole Park": (39.2839, -76.6212, 350), "Sutter Health Park": (38.5800, -121.513, 0),
}
# Domes / closed roofs — wind has no effect.
DOME_VENUES = {"Tropicana Field", "Rogers Centre", "Globe Life Field", "Chase Field",
               "Minute Maid Park", "loanDepot park", "American Family Field"}


# ==============================================================================
# CONFIG  (thresholds written by mlb_backtest.py; safe defaults if absent)
# ==============================================================================
DEFAULT_CONFIG = {
    "edge_threshold":  0.045,   # min de-vigged edge to recommend a total
    "ml_edge_threshold": 0.045, # min de-vigged edge to recommend a moneyline
                                 # (same starting value as totals — no separate
                                 # number invented without backtest evidence;
                                 # tune independently once ML picks accumulate)
    "min_total_line":  6.5,     # ignore totals below this (low-scoring noise)
    "max_total_line":  13.0,
    "n_sims":          10000,
    "kelly_fraction":  0.25,    # fractional Kelly for stake sizing
    "max_stake_pct":   0.05,
    "_basis":          "defaults (run mlb_backtest.py to calibrate from results)",
    "_updated":        "never",
}

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r") as f:
            user = json.load(f)
        if isinstance(user, dict):
            cfg.update({k: user[k] for k in user if k in DEFAULT_CONFIG or k.startswith("_")})
    except Exception:
        pass
    return _validate_config(cfg)

def _validate_config(cfg):
    """Sanity-clamp every numeric config value after loading.

    A corrupted or hand-edited mlb_config.json can otherwise fail in two
    dangerous ways with NO error message: n_sims<=0 crashes simulate() with
    a ZeroDivisionError on every single game, and min_total_line > max_total_line
    silently makes every game fail the line filter forever (zero picks, ever,
    with no indication why). Both are caught here; malformed/out-of-range
    values fall back to the DEFAULT_CONFIG value rather than crash or silently
    disable the model.
    """
    def _num(key, lo, hi):
        v = cfg.get(key)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = DEFAULT_CONFIG[key]
        cfg[key] = max(lo, min(hi, v))

    _num("edge_threshold",    0.0,   0.50)
    _num("ml_edge_threshold", 0.0,   0.50)
    _num("kelly_fraction",    0.0,   1.0)
    _num("max_stake_pct",     0.0,   1.0)
    _num("min_total_line",    0.0,   30.0)
    _num("max_total_line",    0.0,   30.0)

    if cfg["min_total_line"] > cfg["max_total_line"]:
        cfg["min_total_line"] = DEFAULT_CONFIG["min_total_line"]
        cfg["max_total_line"] = DEFAULT_CONFIG["max_total_line"]

    try:
        n_sims = int(cfg.get("n_sims", 0))
    except (TypeError, ValueError):
        n_sims = 0
    cfg["n_sims"] = n_sims if n_sims >= 1000 else DEFAULT_CONFIG["n_sims"]

    return cfg


# ==============================================================================
# HTTP  (defensive; never raises — returns None on any failure)
# ==============================================================================
def get(url, required=False, tries=2):
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.load(r)
                if isinstance(data, dict) and "message" in data:
                    m = str(data["message"]).lower()
                    if any(w in m for w in ("exceed", "quota", "unauthori")):
                        return None
                return data
        except Exception as e:
            last = e
            time.sleep(0.8)
    return None


# ==============================================================================
# ODDS MATH  (de-vig is the core accuracy fix)
# ==============================================================================
def american_to_decimal(o):
    o = float(o)
    return 1.0 + (o / 100.0 if o > 0 else 100.0 / -o)

def american_to_implied(o):
    o = float(o)
    return (-o) / (-o + 100.0) if o < 0 else 100.0 / (o + 100.0)

def devig_two_way(odds_a, odds_b):
    """Strip the hold from a two-way market -> fair probabilities that sum to 1.
    Defensive: any malformed/None/zero input falls back to (0.5, 0.5) rather
    than propagating a crash. Every current call site already guards against
    None before calling this, but this protects future callers too — cheap
    insurance against the exact class of bug that _profit() had."""
    try:
        ia, ib = american_to_implied(odds_a), american_to_implied(odds_b)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.5, 0.5
    s = ia + ib
    if s <= 0:
        return 0.5, 0.5
    return ia / s, ib / s

def kelly_fraction(p, odds):
    """Defensive: malformed odds return 0.0 stake rather than crash."""
    try:
        b = american_to_decimal(odds) - 1.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0
    if b <= 0:
        return 0.0
    return max(0.0, (b * p - (1.0 - p)) / b)

def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None

def _ip(v):
    """Parse MLB's innings-pitched notation into TRUE decimal innings.

    MLB represents innings pitched as "X.Y" where Y is OUTS beyond a full
    inning (0, 1, or 2) — NOT tenths of an inning. "5.1" means 5 innings +
    1 out = 5.333 true innings; "4.2" means 4 innings + 2 outs = 4.667 true
    innings. A naive float() reads these as 5.1 and 4.2 decimal, which
    UNDERSTATES true innings on every start with a partial inning — since
    RA9 = earned_runs * 9 / innings, understating innings systematically
    INFLATES every runs-per-9 calculation that touches it (recent-start
    RA9, season IP used for shrinkage-toward-league-average, expected
    innings tonight, bullpen workload). This is the single most common
    baseball-data-parsing bug there is; it's silent because the numbers
    still look plausible, just modestly wrong every time.
    """
    f = _f(v)
    if f is None:
        return None
    whole = int(f) if f >= 0 else -int(-f)
    thirds = round((f - whole) * 10)  # ".1" -> 1, ".2" -> 2 as MLB displays it
    if thirds not in (0, 1, 2):
        return f  # not MLB's X.0/X.1/X.2 convention (e.g. already-decimal
                   # data from a different source) — don't mangle it
    return whole + thirds / 3.0


# ==============================================================================
# MODEL  (multi-signal starter, shrinkage, MC + normal-approx ensemble)
# ==============================================================================
def _regress(value, prior, n, prior_n):
    if value is None:
        return prior
    w = n / (n + prior_n) if (n + prior_n) > 0 else 0.0
    return w * value + (1.0 - w) * prior

def _expected_sp_ip(recent_logs, n=5):
    """Estimate how deep a starter is likely to go tonight.

    Uses the same gameLog splits already fetched for recent-form RA9 — no
    extra API call. Averages IP across the last N starts (min 4.0 IP to
    exclude early-hook disasters that aren't representative of normal usage),
    then regresses 50% toward the league-standard STARTER_INNINGS so a
    2-3 start sample doesn't overcorrect.

    A guy fresh off IL on a pitch count, or a swingman who never sees the
    7th, should get LESS bullpen-suppressing credit than an innings-eating
    ace — this lets run_prevention_per9 reflect that directly.
    """
    ips = []
    for split in (recent_logs or [])[:n]:
        ip = _ip(split.get("stat", {}).get("inningsPitched"))
        if ip and ip >= 4.0:
            ips.append(ip)
    if not ips:
        return STARTER_INNINGS
    avg_ip = sum(ips) / len(ips)
    return round(0.5 * avg_ip + 0.5 * STARTER_INNINGS, 1)


def _recent_form_ra9(game_log_splits, n=5, decay=0.65,
                     team_rates=None, league_rpg=None, min_start_ip=2.0):
    """Opponent-adjusted, exponentially decayed RA9 from last N starts.

    Most recent start has weight 1.0; each prior start ×decay.

    min_start_ip — a game-log entry is only counted as a "start" for recent-
    form purposes if it covers at least this many innings. Without this
    floor, a single emergency/injury-shortened appearance (e.g. pulled
    after 0.1 IP having allowed 2 earned runs) produces a raw per-start RA9
    of 54 — a number with almost no real signal, since the sample is one
    or two batters, not a start. Because that entry is usually the MOST
    RECENT one, it gets the highest decay weight (1.0) and can single-
    handedly drag an otherwise-strong pitcher's recent-form estimate to
    the model's hard ceiling. 2.0 IP is a low bar — genuine short starts
    (pulled early in a blowout, struggling but left in through the 2nd)
    still count; only appearances too brief to carry real signal are
    excluded.

    Opponent adjustment: a strong performance against a good offense counts
    more than the same line against a weak one. Each start's raw RA9 is
    divided by an opponent factor = (opp_runs_per_game / league_rpg), capped
    at ±15%. So suppressing the Dodgers (factor ~1.13) lowers the adjusted
    RA9 below the raw number; cruising past the Rockies (factor ~0.88)
    raises it. When team_rates isn't supplied the function degrades to the
    original unadjusted behaviour.

    Returns (recent_ra9, total_ip_covered) or (None, 0.0) if no data.
    """
    if not game_log_splits:
        return None, 0.0

    # Explicitly sort newest-first by date rather than trusting the API's
    # return order. The decay weighting below assumes index 0 is the most
    # recent start — if the API ever returns splits in a different order
    # for some players (plausible around trades, IL stints, or role
    # changes, where hydration can behave differently), an old start would
    # silently get the highest weight instead of the most recent one, with
    # no way to detect it downstream. Entries with an unparseable/missing
    # date sort last (treated as oldest) rather than crashing or being
    # dropped outright.
    def _split_date(s):
        d = s.get("date")
        try:
            return datetime.strptime(d, "%Y-%m-%d") if d else datetime.min
        except (ValueError, TypeError):
            return datetime.min
    sorted_splits = sorted(game_log_splits, key=_split_date, reverse=True)

    recent = [s for s in sorted_splits[:n]
              if (_ip(s.get("stat", {}).get("inningsPitched")) or 0.0) >= min_start_ip]
    if not recent:
        return None, 0.0

    total_w = weighted_sum = total_ip = 0.0
    for i, sp in enumerate(recent):
        stat = sp.get("stat", {})
        er   = _f(stat.get("earnedRuns")) or 0.0
        ip   = _ip(stat.get("inningsPitched")) or 0.0
        if ip <= 0:
            continue
        raw_ra9 = er * 9.0 / ip

        # Opponent adjustment — weight by quality of offense faced
        opp_factor = 1.0
        if team_rates and league_rpg and league_rpg > 0:
            opp = sp.get("opponent", {})
            opp_id = opp.get("id")
            if opp_id and opp_id in team_rates:
                opp_off = team_rates[opp_id].get("off")
                if opp_off:
                    opp_factor = max(0.85, min(1.15, opp_off / league_rpg))
        adj_ra9 = raw_ra9 / opp_factor

        w = decay ** i
        weighted_sum += w * adj_ra9
        total_w      += w
        total_ip     += ip
    if total_w == 0:
        return None, 0.0
    return round(weighted_sum / total_w, 3), round(total_ip, 1)

def starter_ra9(era, ip, xera, league_rpg, k9=None, bb9=None, fip=None,
                recent_ra9=None, recent_ip=0.0):
    """Balanced true-talent RA9: ERA/xERA core + FIP + K9/BB9 skill, all
    shrunk toward the league mean by sample size.  No single stat dominates.

    recent_ra9 / recent_ip — if provided, blends in last-5-starts form.
    Weight scales from 0% (< 2 recent starts) up to 30% (5 full starts).
    This lets a hot or cold stretch late in the season move the estimate
    without overriding the full-season picture.
    """
    league_ra9 = league_rpg
    if era is None and xera is None and fip is None:
        return league_ra9
    era_ra9  = (era  / EARNED_RUN_SHARE) if era  is not None else None
    xera_ra9 = (xera / EARNED_RUN_SHARE) if xera is not None else None
    fip_ra9  = (fip  / EARNED_RUN_SHARE) if fip  is not None else None
    ip = ip or 0.0

    if era_ra9 is not None and xera_ra9 is not None:
        core = (1.0 - XERA_WEIGHT) * era_ra9 + XERA_WEIGHT * xera_ra9
    else:
        core = era_ra9 if era_ra9 is not None else xera_ra9
    signals = [(core, 0.60)]

    if fip_ra9 is not None and ip >= 15:
        fip_w = min(FIP_WEIGHT_MAX, 0.08 + ip / 180.0 * FIP_WEIGHT_MAX)
        signals = [(core, 0.60 - fip_w * 0.60), (fip_ra9, fip_w)]

    if k9 is not None or bb9 is not None:
        adj = 0.0
        if k9  is not None: adj -= (k9  - K9_LG)  * K9_RA9_PER
        if bb9 is not None: adj += (bb9 - BB9_LG) * BB9_RA9_PER
        adj = max(-0.80, min(0.80, adj))
        signals = [(v, w * (1.0 - SKILL_WEIGHT)) for v, w in signals]
        signals.append((league_ra9 + adj, SKILL_WEIGHT))

    tot     = sum(w for _, w in signals)
    blended = sum(v * w / tot for v, w in signals)
    season_est = _regress(blended, league_ra9, ip, SP_PRIOR_IP)

    # Blend in recent form — scales from 0% at 10 IP to 40% at 30+ IP (5 starts).
    # Lowered IP floor from 20 → 10 and redesigned divisor so that a pitcher
    # with 4-5 recent starts (25-30 IP) actually reaches the cap.
    if recent_ra9 is not None and recent_ip >= 10.0:
        rf_w = min(0.40, max(0.0, recent_ip / 75.0))
        season_est = (1.0 - rf_w) * season_est + rf_w * recent_ra9

    return min(8.0, max(1.8, season_est))

def run_prevention_per9(starter_ra9_val, team_rapg, sp_ip=STARTER_INNINGS, bullpen_ra9=None):
    """Blend the starter (expected innings) with the bullpen-plus-rest proxy
    for the remaining innings.

    team_rapg is the team's overall observed RA/G — it already embeds real
    bullpen quality plus defense, sequencing, and park effects.
    bullpen_ra9, when available, is a role-filtered season ERA for true
    relievers only (see _bullpen_fatigue). It's blended 50/50 with team_rapg
    rather than replacing it outright, since team_rapg still carries signal
    (defense, park) that a pure pitching-only ERA doesn't capture.
    """
    sp_inn = sp_ip if sp_ip else STARTER_INNINGS
    bp_inn = max(0.5, 9.0 - sp_inn)
    bp_rate = team_rapg
    if bullpen_ra9 is not None:
        bp_rate = 0.5 * team_rapg + 0.5 * bullpen_ra9
    return (sp_inn * starter_ra9_val + bp_inn * bp_rate) / (sp_inn + bp_inn)

def park_factor(home_team):
    return PARK_FACTORS.get(home_team, PARK_DEFAULT)

def _dynamic_park_factor(home_team_name, team_form_entry):
    """Blend the curated static park factor with a current-season dynamic
    estimate computed from total game runs (both teams) at home vs road.

    Using TOTAL runs rather than just the home team's own runs avoids the
    confound where a team simply hits better at home (comfort, crowd, their
    own schedule quirks) getting mistaken for the park itself being
    hitter-friendly — that bias cancels out when you include runs allowed too.

    Regressed 50% toward the static table (not toward 1.0) since the static
    factors are typically multi-year sabermetric estimates and more stable
    than one team's ~33-day in-season sample. Requires 10+ home AND 10+ road
    games before the dynamic estimate is trusted at all; below that, falls
    back to the static value untouched.
    """
    static = park_factor(home_team_name)
    raw    = (team_form_entry or {}).get("dyn_park_raw")
    n      = (team_form_entry or {}).get("dyn_park_games", 0)
    if raw is None or n < 10:
        return static
    raw_capped = max(0.85, min(1.15, raw))   # guard against small-sample outliers
    blended    = 0.5 * static + 0.5 * raw_capped
    return round(max(0.85, min(1.20, blended)), 4)

def _rest_factor(days_rest):
    """Small adjustment for team rest/travel fatigue.

    days_rest = full days off before tonight (0 = played yesterday with no
    break, 1 = one day off, etc.). This is a minor signal — capped at ±1%
    on offense and the inverse on runs-allowed — layered on top of, not a
    replacement for, the bullpen-fatigue tracking (which looks at actual
    relief-pitcher workload rather than team-wide schedule gaps).
    """
    if days_rest is None:
        return 1.0
    if days_rest <= 0:
        return 0.99    # no rest — slight fatigue penalty
    if days_rest >= 2:
        return 1.01    # well rested — slight freshness boost
    return 1.0

def weather_factor(temp_f):
    if temp_f is None:
        return 1.0
    return min(1.05, max(0.95, 1.0 + 0.0012 * (temp_f - 70.0)))

def wind_factor(speed_mph, from_deg, cf_bearing, is_dome):
    """Multiplier for wind on run scoring. Positive component = blowing out."""
    if is_dome or speed_mph is None or from_deg is None or speed_mph < 5:
        return 1.0, None
    to_deg = (from_deg + 180) % 360
    comp = speed_mph * math.cos(math.radians(to_deg - cf_bearing))
    factor = min(1.08, max(0.93, 1.0 + 0.0028 * comp))
    label = "out" if comp > 2 else ("in" if comp < -2 else "cross")
    return round(factor, 4), "%.0fmph %s" % (speed_mph, label)

def project_runs(off_away, off_home, prev_away9, prev_home9, league_rpg, park, env):
    lg = max(2.5, league_rpg)
    lam_away = lg * (off_away / lg) * (prev_home9 / lg) * park * env * AWAY_OFF_MULT
    lam_home = lg * (off_home / lg) * (prev_away9 / lg) * park * env * HOME_OFF_MULT
    return min(12.0, max(1.5, lam_away)), min(12.0, max(1.5, lam_home))

def _poisson(lam):
    L = math.exp(-lam); k = 0; p = 1.0
    while True:
        p *= random.random()
        if p <= L:
            return k
        k += 1

def _kick(runs):
    return runs + CROOKED_EXTRA if runs > 0 and random.random() < CROOKED_PROB else runs

def _kick_adj_lambda(lam_inning):
    target = max(0.0, lam_inning)
    p_pos = 1.0 - math.exp(-target)
    return max(0.02, target - CROOKED_PROB * CROOKED_EXTRA * p_pos)

def _extras(la, lh):
    la_x, lh_x = la + GHOST_RUNNER_BONUS, lh + GHOST_RUNNER_BONUS
    ea = eh = 0
    for _ in range(MAX_EXTRA_INNINGS):
        ea += _kick(_poisson(la_x))
        h = _kick(_poisson(lh_x))
        if eh + h > ea:
            eh += h; break
        eh += h
        if ea != eh:
            break
    return ea, eh

def simulate(lam_away, lam_home, n, seed=None):
    """Pure-stdlib Monte Carlo of the full game with overdispersion, conditional
    9th, and ghost-runner extras. Returns dict with 'dist' (totals), 'proj_total',
    'sd', 'n', 'away_wins', 'home_wins'."""
    la = _kick_adj_lambda(lam_away / 9.0)
    lh = _kick_adj_lambda(lam_home / 9.0)
    if seed is not None:
        random.seed(seed)
    totals = []
    away_wins = 0
    home_wins = 0
    for _ in range(n):
        gs = random.gammavariate(ENV_SHARED_K, 1.0 / ENV_SHARED_K)
        ga = random.gammavariate(ENV_TEAM_K, 1.0 / ENV_TEAM_K)
        gh = random.gammavariate(ENV_TEAM_K, 1.0 / ENV_TEAM_K)
        la_g, lh_g = la * gs * ga, lh * gs * gh
        away = sum(_kick(_poisson(la_g)) for _ in range(9))
        home_8 = sum(_kick(_poisson(lh_g)) for _ in range(8))
        home = home_8 if home_8 > away else home_8 + _kick(_poisson(lh_g))
        if home == away:
            ea, eh = _extras(la * gs, lh * gs)
            away += ea; home += eh
            if home == away:
                if random.random() < 0.5: home += 1
                else: away += 1
        totals.append(away + home)
        if away > home:
            away_wins += 1
        else:
            home_wins += 1
    n_ = len(totals)
    mean = sum(totals) / n_
    sd = (sum((t - mean) ** 2 for t in totals) / n_) ** 0.5
    return {
        "dist": totals, "proj_total": mean, "sd": sd, "n": n_,
        "away_wins": away_wins, "home_wins": home_wins,
        "away_win_pct": away_wins / n_,
        "home_win_pct": home_wins / n_,
    }

def _norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

def p_over_ensemble(sim, line):
    """Blend empirical MC p_over with a normal-approximation p_over.
    The normal model stabilises fast and damps small-sample MC noise."""
    dist = sim["dist"]; n = sim["n"]
    over = sum(1 for t in dist if t > line) / n
    push = sum(1 for t in dist if t == line) / n
    p_over_mc = over
    sd = max(0.5, sim["sd"])
    z = (line + 0.5 - sim["proj_total"]) / sd     # continuity correction
    p_over_norm = 1.0 - _norm_cdf(z)
    p_over = ENSEMBLE_MC_WEIGHT * p_over_mc + (1 - ENSEMBLE_MC_WEIGHT) * p_over_norm
    p_over = min(0.999, max(0.001, p_over))
    return p_over, (1.0 - p_over - push), push


# ==============================================================================
# DATA FETCH  (6 calls for the whole slate; only the odds call is paid)
# ==============================================================================
# ── Bullpen fatigue ────────────────────────────────────────────────────────
_BULLPEN_CACHE = {}

# ==============================================================================
# UMPIRE TENDENCIES
# ==============================================================================
# Run factor per HP umpire — values > 1.0 = more runs (loose zone),
# < 1.0 = fewer runs (tight zone). Based on historical umpscorecards.com data.
_UMP_ZONE_FACTOR = {
    "Laz Diaz":        1.07, "Angel Hernandez": 1.06, "Ángel Hernández": 1.06,
    "CB Bucknor":      1.05, "Ted Barrett":     1.04, "Jim Reynolds":    1.03,
    "Roberto Ortiz":   1.03, "Dan Bellino":     1.02, "John Libka":      1.02,
    "Lance Barksdale": 1.02, "Brian Knight":    1.01, "Dan Iassogna":    1.01,
    "Mark Wegner":     0.99, "Mike Winters":    0.99, "Tripp Gibson":    0.98,
    "Sam Holbrook":    0.98, "Ben May":         0.97, "Scott Barry":     0.97,
    "Chris Guccione":  0.97, "Adam Hamari":     0.96, "John Tumpane":    0.96,
    "Pat Hoberg":      0.95,
}
_UMP_CACHE = {}

def _ump_factor(hp_ump_name, hp_ump_id, year):
    """Return (run_factor, ump_name) for the home plate umpire.
    Tries umpscorecards.com API first, falls back to hardcoded lookup, then 1.0.
    """
    if not hp_ump_name:
        return 1.0, "unknown"
    key = (hp_ump_name, year)
    if key in _UMP_CACHE:
        return _UMP_CACHE[key]

    # Try umpscorecards.com public API
    try:
        slug = hp_ump_name.lower().replace(" ", "-")
        data = get("https://umpscorecards.com/api/umpires/?name=%s" % slug)
        if data and isinstance(data, list) and data:
            rpg_impact = _f(data[0].get("rpg_impact"))
            if rpg_impact is not None:
                factor = round(max(0.92, min(1.08, 1.0 + rpg_impact / 44.0)), 3)
                result = (factor, hp_ump_name)
                _UMP_CACHE[key] = result
                return result
    except Exception:
        pass

    # Hardcoded lookup
    for name, factor in _UMP_ZONE_FACTOR.items():
        if name.lower() in hp_ump_name.lower() or hp_ump_name.lower() in name.lower():
            result = (factor, hp_ump_name)
            _UMP_CACHE[key] = result
            return result

    result = (1.0, hp_ump_name)
    _UMP_CACHE[key] = result
    return result


# ==============================================================================
# INJURY DETECTION
# ==============================================================================
def fetch_injury_flags(team_ids, day, year, league_ops=0.710):
    """Fetch recent IL placements (last 7 days) and compute offensive adjustment.

    For each injured position player whose OPS is above league average, we
    estimate the offensive penalty of replacing them with a league-average bat.
    One batter out of 9 replaced → adjustment = 1 - (star_ops - lg_ops) / lg_ops / 9
    Capped at -10% total per team. Only applied when lineups aren't confirmed
    (to avoid double-counting with the lineup OPS layer).

    Returns {team_id: {"players": [name,...], "off_adj": float (1.0 = no injury)}}
    """
    if not team_ids:
        return {}
    try:
        end_dt   = datetime.strptime(day, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=7)
        ids_str  = ",".join(str(t) for t in team_ids)
        tx = get("https://statsapi.mlb.com/api/v1/transactions"
                 "?teamIds=%s&sportId=1&startDate=%s&endDate=%s" % (
                     ids_str, start_dt.strftime("%Y-%m-%d"), day))
        if not tx:
            return {}

        IL_KEYWORDS = {"placed on 10-day il", "placed on 15-day il",
                       "placed on 60-day il", "transferred to 60-day"}
        # Collect injured players per team: {team_id: [(person_id, name), ...]}
        injured = {}
        for t in tx.get("transactions", []):
            desc = t.get("typeDesc", "").lower()
            if any(kw in desc for kw in IL_KEYWORDS):
                tid  = (t.get("toTeam") or t.get("team") or {}).get("id")
                pid  = t.get("person", {}).get("id")
                name = t.get("person", {}).get("fullName", "")
                if tid and pid and name:
                    injured.setdefault(tid, []).append((pid, name))
        if not injured:
            return {}

        # Batch-fetch hitting stats for all injured players in one call
        all_ids = {pid for players in injured.values() for pid, _ in players}
        player_ops = {}
        ppl = get("https://statsapi.mlb.com/api/v1/people?personIds=%s"
                  "&hydrate=stats(group=[hitting],type=[season],season=%d)" % (
                      ",".join(str(i) for i in all_ids), year))
        for p in (ppl or {}).get("people", []):
            try:
                stat = p["stats"][0]["splits"][0]["stat"]
                pa   = _f(stat.get("plateAppearances")) or 0
                ops  = _f(stat.get("ops"))
                if ops and pa >= 50:   # only trust meaningful sample
                    player_ops[p["id"]] = ops
            except Exception:
                pass

        # Build per-team result
        flags = {}
        for tid, players in injured.items():
            names = []
            team_adj = 1.0
            for pid, name in players:
                names.append(name)
                ops = player_ops.get(pid)
                if ops and ops > league_ops:
                    # Replacing one above-average bat with an average one
                    penalty = max(0.0, min(0.05, (ops - league_ops) / league_ops / 9))
                    team_adj *= (1.0 - penalty)
            team_adj = max(0.90, team_adj)   # cap at -10% total
            flags[tid] = {"players": names, "off_adj": round(team_adj, 4)}
        return flags
    except Exception:
        return {}


def _bullpen_fatigue(team_id, year, as_of_date):
    """Fetch bullpen fatigue AND season bullpen quality for a team — one
    roster call + one batch people call, both pieces of data extracted from
    the same response at zero extra API cost.

    Returns a dict:
      fatigue_mult: 1.0 = fresh, >1.0 = taxed (max 1.10), from last-3-days IP
      arms_used:    relievers who threw in the last 3 days
      ip_3d:        total bullpen IP in the last 3 days
      bullpen_ra9:  season RA9 of TRUE relievers only (gamesStarted < 3),
                    None if <20 IP of reliable bullpen-only sample
      bullpen_ip:   total IP backing that bullpen_ra9 estimate

    A pitcher counts as a "true reliever" for the quality estimate only if
    he has fewer than 3 starts this season -- this excludes rotation
    regulars and spot-starters whose numbers would otherwise just reproduce
    team ERA, defeating the purpose of isolating bullpen quality.

    Cached per (team_id, year, as_of_date) so we only fetch once per run.
    """
    cache_key = (team_id, year, as_of_date)
    if cache_key in _BULLPEN_CACHE:
        return _BULLPEN_CACHE[cache_key]

    fresh = {"fatigue_mult": 1.0, "arms_used": 0, "ip_3d": 0.0,
              "bullpen_ra9": None, "bullpen_ip": 0.0}
    try:
        roster = get(f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster"
                     "?rosterType=active")
        if not roster:
            return _BULLPEN_CACHE.setdefault(cache_key, fresh)
        pitcher_ids = [
            p["person"]["id"] for p in roster.get("roster", [])
            if p.get("position", {}).get("code") == "1"
        ]
        if not pitcher_ids:
            return _BULLPEN_CACHE.setdefault(cache_key, fresh)

        ids_str = ",".join(str(i) for i in pitcher_ids)
        people  = get(f"https://statsapi.mlb.com/api/v1/people?personIds={ids_str}"
                      f"&hydrate=stats(group=pitching,type=[season,gameLog],season={year})")
        if not people:
            return _BULLPEN_CACHE.setdefault(cache_key, fresh)

        try:
            cutoff = datetime.strptime(as_of_date, "%Y-%m-%d") - timedelta(days=3)
        except Exception:
            cutoff = datetime.today() - timedelta(days=3)

        arms_used = 0
        ip_3d     = 0.0
        bp_er     = 0.0
        bp_ip     = 0.0

        for p in people.get("people", []):
            season_stat    = {}
            gamelog_splits = []
            for block in p.get("stats", []):
                dtype  = block.get("type", {}).get("displayName", "").lower()
                splits = block.get("splits", [])
                if "gamelog" in dtype or "game log" in dtype or "log" in dtype:
                    gamelog_splits = splits
                elif "single" in dtype or ("season" in dtype and "game" not in dtype):
                    if splits:
                        season_stat = splits[0].get("stat", {})

            # 3-day fatigue (same logic as before, from gameLog splits)
            threw = False
            for split in gamelog_splits:
                gd = split.get("date")
                if not gd:
                    continue
                try:
                    g_date = datetime.strptime(gd, "%Y-%m-%d")
                except ValueError:
                    continue
                if g_date >= cutoff:
                    sip = _ip(split.get("stat", {}).get("inningsPitched")) or 0.0
                    if sip > 0:
                        ip_3d += sip
                        threw  = True
            if threw:
                arms_used += 1

            # Season bullpen quality -- true relievers (gamesStarted < 3) use
            # their season line directly. A pitcher with gs >= 3 is normally
            # excluded entirely -- but that's wrong for someone who started
            # earlier in the season and has since been converted to relief
            # (a real, common in-season role change). Excluding him forever
            # because of April starts throws away exactly the current
            # bullpen-quality signal this function exists to capture.
            #
            # Detection: gs >= 3 AND his last 5 game-log appearances are all
            # short (<=3.0 IP each) -- a genuine current starter's recent
            # outings wouldn't look like that. When detected, use ONLY his
            # recent relief-shaped appearances' ER/IP, not his season total
            # (which still contains his old starter-role innings and would
            # misrepresent his current relief performance).
            gs = _f(season_stat.get("gamesStarted")) or 0
            if gs < 3:
                er = _f(season_stat.get("earnedRuns"))     or 0.0
                ip = _ip(season_stat.get("inningsPitched"))  or 0.0
                if ip > 0:
                    bp_er += er
                    bp_ip += ip
            elif gamelog_splits:
                recent5 = gamelog_splits[:5]
                recent_ips = [_ip(s.get("stat", {}).get("inningsPitched")) or 0.0
                             for s in recent5]
                if recent_ips and all(0 < x <= 3.0 for x in recent_ips):
                    conv_er = sum(_f(s.get("stat", {}).get("earnedRuns")) or 0.0
                                 for s in recent5)
                    conv_ip = sum(recent_ips)
                    if conv_ip > 0:
                        bp_er += conv_er
                        bp_ip += conv_ip

        BASELINE_IP  = 10.0
        excess       = max(0.0, ip_3d - BASELINE_IP)
        fatigue_mult = min(1.10, 1.0 + 0.015 * excess)

        bullpen_ra9 = None
        if bp_ip >= 20.0:
            # Convert earned-run rate to total-run estimate, same convention
            # used throughout the model (EARNED_RUN_SHARE ~ 92% of runs earned)
            bullpen_ra9 = round((bp_er * 9.0 / bp_ip) / EARNED_RUN_SHARE, 3)

        result = {
            "fatigue_mult": round(fatigue_mult, 3),
            "arms_used":    arms_used,
            "ip_3d":        round(ip_3d, 1),
            "bullpen_ra9":  bullpen_ra9,
            "bullpen_ip":   round(bp_ip, 1),
        }
        _BULLPEN_CACHE[cache_key] = result
        return result
    except Exception:
        return _BULLPEN_CACHE.setdefault(cache_key, fresh)


def fetch_team_rates(year):
    st = get(f"https://statsapi.mlb.com/api/v1/standings?leagueId=103,104&season={year}")
    rates, runs, games = {}, 0, 0
    if st:
        for rec in st.get("records", []):
            for tr in rec.get("teamRecords", []):
                tid = tr["team"]["id"]
                rs  = tr.get("runsScored",  0) or 0
                ra  = tr.get("runsAllowed", 0) or 0
                gp  = tr.get("gamesPlayed", 0) or 0
                w   = tr.get("wins",        0) or 0
                if gp > 0:
                    rates[tid] = {
                        "off":     rs / gp,
                        "rapg":    ra / gp,
                        "k_rate":  None,
                        "win_pct": w / gp,   # actual W/L record
                        "games":   gp,
                    }
                    runs += rs; games += gp
    league_rpg = runs / games if games else LEAGUE_RPG_FALLBACK

    # Fetch team batting K-rate — one call, all 30 teams.
    # K/PA is the right denominator (PA includes walks, which at-bats doesn't).
    # This lets us adjust K projections for who the pitcher is facing:
    #   strikeout-prone lineups boost the projection, contact teams lower it.
    batting = get(
        f"https://statsapi.mlb.com/api/v1/teams/stats"
        f"?stats=season&group=hitting&season={year}&gameType=R&sportId=1")
    total_ks = total_pa = 0
    if batting:
        for split in (batting.get("stats") or [{}])[0].get("splits", []):
            tid  = split.get("team", {}).get("id")
            stat = split.get("stat", {})
            ks   = _f(stat.get("strikeOuts") or stat.get("strikeouts"))
            pa   = _f(stat.get("plateAppearances"))
            if tid and ks is not None and pa and pa > 0:
                k_rate = ks / pa
                if tid in rates:
                    rates[tid]["k_rate"] = k_rate
                total_ks += ks
                total_pa += pa
    league_k_rate = (total_ks / total_pa) if total_pa > 0 else 0.225
    # Fill in league average for any team without batting stats
    for tid in rates:
        if rates[tid]["k_rate"] is None:
            rates[tid]["k_rate"] = league_k_rate
    # Store league K-rate as a sentinel so fetch_slate can read it
    rates["_league_k_rate"] = league_k_rate

    return league_rpg, rates

def _starter_line(stat):
    """Pull ERA, xERA(proxy), FIP, K/9, BB/9 from a season pitching stat dict.
    StatsAPI uses camelCase (strikeOuts) — try both variants to be safe."""
    era = _f(stat.get("era"))
    ip  = _ip(stat.get("inningsPitched")) or 0.0
    k9 = bb9 = fip = None
    # Try camelCase first (StatsAPI standard), then lowercase fallback
    ks_raw  = _f(stat.get("strikeOuts") or stat.get("strikeouts"))
    bbs_raw = _f(stat.get("baseOnBalls")) or 0.0
    hrs_raw = _f(stat.get("homeRuns")) or 0.0
    if ip > 0 and ks_raw is not None:
        # Only compute from raw counts when we actually have K data.
        # Avoids spurious k9=0.0 when the field name simply wasn't found.
        k9  = ks_raw * 9.0 / ip
        bb9 = bbs_raw * 9.0 / ip
        fip = max(1.5, min(7.5, FIP_CONST + (13.0 * hrs_raw + 3.0 * bbs_raw - 2.0 * ks_raw) / ip))
    # Fallback to StatsAPI pre-computed per-9 fields
    if k9 is None and stat.get("strikeoutsPer9Inn"):
        k9 = _f(stat["strikeoutsPer9Inn"])
    if bb9 is None and stat.get("baseOnBallsPer9Inn"):
        bb9 = _f(stat["baseOnBallsPer9Inn"])
    xera = fip if fip is not None else era
    return {"era": era, "xera": xera, "fip": fip, "ip": ip, "k9": k9, "bb9": bb9}

def fetch_team_form(year, as_of_date, n_games=10, lookback_days=33):
    """Fetch each team's recent form — both last-10-games AND full 30-day window.

    One schedule call covers all 30 teams over the lookback window; both
    windows are computed from the same raw game list so there's no extra
    API cost for the longer window.

    Returns {team_id: {recent_off, recent_def, ..., recent_off_30,
                        recent_def_30, form_str_30, ...}}
    The original keys (recent_off, recent_def, form_str) are the 10-game
    window and are kept for backward compatibility with existing callers.
    """
    try:
        end_dt   = datetime.strptime(as_of_date, "%Y-%m-%d") - timedelta(days=1)
        start_dt = end_dt - timedelta(days=lookback_days)
    except Exception:
        return {}

    sched = get(
        "https://statsapi.mlb.com/api/v1/schedule"
        "?sportId=1&gameTypes=R&season=%d"
        "&startDate=%s&endDate=%s" % (
            year, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")))
    if not sched:
        return {}

    # Accumulate results per team, sorted oldest→newest
    raw           = {}   # {team_id: [(runs_scored, runs_allowed, won), ...]}
    raw_home_tot  = {}   # {team_id: [total_game_runs, ...]} — when tid hosted
    raw_road_tot  = {}   # {team_id: [total_game_runs, ...]} — when tid traveled
    last_game_dt  = {}   # {team_id: most recent completed game date}
    for d in sorted(sched.get("dates", []), key=lambda x: x.get("date", "")):
        d_date = d.get("date", "")
        for g in d.get("games", []):
            if g.get("status", {}).get("detailedState", "") != "Final":
                continue
            teams = g.get("teams", {})
            for side, opp in (("away", "home"), ("home", "away")):
                tid = teams.get(side, {}).get("team", {}).get("id")
                rs  = _f(teams.get(side, {}).get("score"))
                ra  = _f(teams.get(opp,  {}).get("score"))
                won = teams.get(side, {}).get("isWinner", False)
                if tid and rs is not None and ra is not None:
                    raw.setdefault(tid, []).append((rs, ra, bool(won)))
                    total = rs + ra
                    if side == "home":
                        raw_home_tot.setdefault(tid, []).append(total)
                    else:
                        raw_road_tot.setdefault(tid, []).append(total)
                    if d_date:
                        last_game_dt[tid] = d_date   # oldest→newest, so last write wins

    try:
        slate_dt = datetime.strptime(as_of_date, "%Y-%m-%d")
    except Exception:
        slate_dt = None

    form = {}
    for tid, game_list in raw.items():
        n_all = len(game_list)
        if n_all == 0:
            continue

        # 30-day window — every game in the lookback (smoother, less noisy)
        wins_30 = sum(1 for _, _, w in game_list if w)
        off_30  = sum(rs for rs, _, _ in game_list) / n_all
        def_30  = sum(ra for _, ra, _ in game_list) / n_all

        # 10-game window — most recent N (more reactive to hot/cold streaks)
        recent  = game_list[-n_games:]
        n10     = len(recent)
        wins_10 = sum(1 for _, _, w in recent if w)
        off_10  = sum(rs for rs, _, _ in recent) / n10
        def_10  = sum(ra for _, ra, _ in recent) / n10

        # Dynamic park factor — total game runs (BOTH teams) at home vs away.
        # Using total runs rather than just tid's own runs avoids conflating
        # "park is hitter-friendly" with "this team just hits better at home"
        # or "their home schedule happens to be softer than their road one."
        home_list = raw_home_tot.get(tid, [])
        road_list = raw_road_tot.get(tid, [])
        dyn_park_raw   = None
        dyn_park_games = len(home_list)
        if len(home_list) >= 10 and len(road_list) >= 10:
            home_avg = sum(home_list) / len(home_list)
            road_avg = sum(road_list) / len(road_list)
            if road_avg > 0:
                dyn_park_raw = home_avg / road_avg

        # Rest days — full days off before the slate date.
        days_rest = None
        if slate_dt and tid in last_game_dt:
            try:
                last_dt = datetime.strptime(last_game_dt[tid], "%Y-%m-%d")
                days_rest = (slate_dt - last_dt).days - 1   # -1: travel/game day itself isn't "rest"
            except Exception:
                pass

        form[tid] = {
            # 10-game window (kept as primary keys for backward compatibility)
            "recent_off":  off_10,
            "recent_def":  def_10,
            "wins":        wins_10,
            "losses":      n10 - wins_10,
            "games":       n10,
            "form_str":    "%d-%d L%d" % (wins_10, n10 - wins_10, n10),
            # 30-day window (new — smoother, dampens single-week variance)
            "recent_off_30": off_30,
            "recent_def_30": def_30,
            "wins_30":       wins_30,
            "losses_30":     n_all - wins_30,
            "games_30":      n_all,
            "form_str_30":   "%d-%d L%d" % (wins_30, n_all - wins_30, n_all),
            # Dynamic park factor (raw — caller blends with static table)
            "dyn_park_raw":   dyn_park_raw,
            "dyn_park_games": dyn_park_games,
            # Rest — full days off before tonight's game
            "days_rest": days_rest,
        }
    return form


def _sorted_by_slot(batting_list):
    """Sort a lineup's batting array by the StatsAPI's explicit battingOrder
    field (e.g. "100","200"..."900" -> slots 1-9) rather than trusting raw
    array order. Falls back to original order if any entry is missing a
    usable battingOrder (keeps behavior safe even if the API's field is
    absent or malformed for some entries)."""
    entries = []
    for p in batting_list:
        if "id" not in p:
            continue
        bo = p.get("battingOrder")
        try:
            slot = int(str(bo)[0]) if bo else None   # "300" -> 3
        except (ValueError, IndexError):
            slot = None
        entries.append((slot, p["id"]))
    if all(s is not None for s, _ in entries):
        entries.sort(key=lambda x: x[0])
    return [pid for _, pid in entries]

SLOT_WEIGHTS = [1.103, 1.075, 1.049, 1.023, 0.997, 0.974, 0.950, 0.927, 0.903]
# Batting-order weight by slot, approximating real PA/game share rather than
# a "performance boost" by slot (no sabermetric support for the latter —
# OPS doesn't meaningfully change by batting position for the same hitter;
# what genuinely differs is how many times they bat). Derived from
# documented season PA/G-by-slot research, normalized so the weights
# average to 1.0 — this re-ranks lineups by who's actually getting more
# at-bats, it doesn't shift every team's baseline lineup_ops up or down.


def fetch_slate(day, year, cfg):
    league_rpg, rates = fetch_team_rates(year)
    league_k_rate = rates.pop("_league_k_rate", 0.225)

    # Recent form — last 10 completed games per team (single schedule call)
    team_form = fetch_team_form(year, day)

    # Add lineups + officials to hydration
    sched = get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={day}"
                "&hydrate=probablePitcher,team,venue,lineups,officials")
    games_raw = []
    if sched:
        for d in (sched.get("dates") or []):
            for g in d.get("games", []):
                if g.get("status", {}).get("detailedState", "") != "Postponed":
                    games_raw.append(g)
    if not games_raw:
        return league_rpg, []

    # ── Extract confirmed lineup player IDs per game, in batting-order slot ───
    # lineups = {gamePk: {"away": [pid, ...], "home": [pid, ...]}}
    # Uses module-level _sorted_by_slot() — sorts by the API's explicit
    # battingOrder field rather than trusting raw array order, since the
    # slot-weighting below depends on position 0 genuinely being leadoff.
    lineup_map = {}
    for g in games_raw:
        gpk  = g.get("gamePk")
        lu   = g.get("lineups", {})
        away_batters = _sorted_by_slot(lu.get("awayTeam", {}).get("batting", []))
        home_batters = _sorted_by_slot(lu.get("homeTeam", {}).get("batting", []))
        if away_batters or home_batters:
            lineup_map[gpk] = {"away": away_batters, "home": home_batters}

    # ── Batch fetch hitting stats for all lineup players ──────────────────────
    # One call covers every batter across all confirmed lineups.
    batter_ops = {}          # {player_id: ops}
    league_ops = 0.710       # MLB average fallback
    all_batter_ids = {pid for lu in lineup_map.values()
                      for pid in lu.get("away", []) + lu.get("home", [])}
    if all_batter_ids:
        bpl = get("https://statsapi.mlb.com/api/v1/people?personIds=" +
                  ",".join(str(p) for p in all_batter_ids) +
                  f"&hydrate=stats(group=[hitting],type=[season],season={year})")
        ops_vals = []
        for p in (bpl or {}).get("people", []):
            try:
                stat = p["stats"][0]["splits"][0]["stat"]
                pa   = _f(stat.get("plateAppearances")) or 0
                ops  = _f(stat.get("ops"))
                if ops and pa >= 50:
                    batter_ops[p["id"]] = ops
                    ops_vals.append(ops)
            except Exception:
                pass
        if ops_vals:
            league_ops = sum(ops_vals) / len(ops_vals)

    # Platoon splits — batter OPS vs RHP and LHP separately.
    # When we know the opposing starter's hand, we use the right split.
    batter_platoon = {}   # {pid: {"R": ops_vs_righty, "L": ops_vs_lefty}}
    if all_batter_ids:
        spl = get("https://statsapi.mlb.com/api/v1/people?personIds=" +
                  ",".join(str(p) for p in all_batter_ids) +
                  f"&hydrate=stats(group=[hitting],type=[statSplits]"
                  f",season={year},sitCodes=[vr,vl])")
        for p in (spl or {}).get("people", []):
            pid = p["id"]
            sides = {}
            for block in p.get("stats", []):
                for sp in block.get("splits", []):
                    code = sp.get("split", {}).get("code", "")
                    stat = sp.get("stat", {})
                    pa   = _f(stat.get("plateAppearances")) or 0
                    ops  = _f(stat.get("ops"))
                    if ops and pa >= 30:
                        if code == "vr":   sides["R"] = ops
                        elif code == "vl": sides["L"] = ops
            if sides:
                batter_platoon[pid] = sides

    # Uses module-level SLOT_WEIGHTS (PA-share-by-slot, see definition above)
    def _lineup_ops(player_ids, opp_pitcher_hand="R"):
        """PA-share-weighted OPS of a confirmed lineup vs the opposing
        starter's hand. Uses platoon splits when available, falls back to
        overall OPS. Batters are weighted by their batting-order slot's
        typical share of plate appearances — leadoff hitters bat more often
        than #9 hitters, so their OPS counts proportionally more toward the
        team's expected run output tonight."""
        if not player_ids:
            return None
        weights = SLOT_WEIGHTS[:len(player_ids)]
        vals = []
        for pid, w in zip(player_ids, weights):
            platoon = batter_platoon.get(pid, {})
            ops = platoon.get(opp_pitcher_hand) or batter_ops.get(pid, league_ops)
            vals.append(ops * w)
        return sum(vals) / sum(weights)

    # ── Batch pitcher season stats ────────────────────────────────────────────
    pids = {str(g["teams"][s]["probablePitcher"]["id"])
            for g in games_raw for s in ("away", "home")
            if "probablePitcher" in g["teams"][s]}
    pstat = {}
    if pids:
        ppl = get("https://statsapi.mlb.com/api/v1/people?personIds=" + ",".join(pids)
                  + f"&hydrate=stats(group=[pitching],type=[season,gameLog],season={year})")
        for p in (ppl or {}).get("people", []):
            pid = str(p["id"])
            season_stat   = {}
            gamelog_splits = []
            for block in p.get("stats", []):
                dtype = block.get("type", {}).get("displayName", "").lower()
                splits = block.get("splits", [])
                if "single" in dtype or dtype == "statssingleseasobn" or (
                        "season" in dtype and "game" not in dtype):
                    if splits:
                        season_stat = splits[0].get("stat", {})
                elif "gamelog" in dtype or "game log" in dtype or "log" in dtype:
                    gamelog_splits = splits  # newest-first from API
            sl = _starter_line(season_stat)
            sl["name"] = p.get("fullName", "")
            sl["recent_ra9"], sl["recent_ip"] = _recent_form_ra9(
                gamelog_splits, team_rates=rates, league_rpg=league_rpg)
            # Pitcher handedness — used for platoon split adjustment
            sl["pitch_hand"] = p.get("pitchHand", {}).get("code", "R")
            # Expected IP tonight — reuses the same gameLog splits, no extra call
            sl["expected_ip"] = _expected_sp_ip(gamelog_splits)
            pstat[pid] = sl

    # Batch venue coords + one batched weather call
    weather = {}
    vids = {g["venue"]["id"] for g in games_raw if "venue" in g}
    if vids:
        vens = get("https://statsapi.mlb.com/api/v1/venues?venueIds="
                   + ",".join(str(v) for v in vids) + "&hydrate=location")
        coords = []
        if vens:
            coords = [(v["id"], v["location"]["defaultCoordinates"])
                      for v in vens.get("venues", [])
                      if v.get("location", {}).get("defaultCoordinates")]
        if coords:
            lats = ",".join(str(c["latitude"]) for _, c in coords)
            lons = ",".join(str(c["longitude"]) for _, c in coords)
            wx = get(f"https://api.open-meteo.com/v1/forecast?latitude={lats}&longitude={lons}"
                     "&hourly=temperature_2m,precipitation_probability,wind_speed_10m,"
                     "wind_direction_10m&temperature_unit=fahrenheit&wind_speed_unit=mph"
                     "&forecast_days=2&timezone=UTC")
            if wx is not None:
                if isinstance(wx, dict):
                    wx = [wx]
                for (vid, _), loc in zip(coords, wx):
                    weather[vid] = loc.get("hourly", {})

    def wx_at(g):
        h = weather.get(g.get("venue", {}).get("id"))
        if not h or not h.get("time"):
            return None, None, None, "n/a"
        key = g["gameDate"][:13] + ":00"
        times = h["time"]
        try:
            i = times.index(key)
        except ValueError:
            i = min(range(len(times)), key=lambda x: abs(
                datetime.strptime(times[x], "%Y-%m-%dT%H:%M").timestamp()
                - datetime.strptime(key, "%Y-%m-%dT%H:%M").timestamp()))
        temp = _f(h["temperature_2m"][i])
        wspd = _f(h["wind_speed_10m"][i])
        wdir = _f(h["wind_direction_10m"][i])
        rain = h["precipitation_probability"][i]
        note = "%.0fF, %s%% rain, wind %.0fmph" % (temp, rain, wspd) if temp is not None else "n/a"
        return temp, wspd, wdir, note

    # One batched odds call (totals + h2h, DraftKings) — the only paid request
    odds_idx = {}

    # ── Bullpen fatigue for all teams ─────────────────────────────────────────
    bp_fatigue = {}
    team_ids   = {g["teams"][s]["team"]["id"]
                  for g in games_raw for s in ("away", "home")}
    for tid in team_ids:
        bp_fatigue[tid] = _bullpen_fatigue(tid, year, day)

    # ── Injury flags — IL placements in last 7 days ────────────────────────────
    injury_flags = fetch_injury_flags(team_ids, day, year)

    # ── Multi-book line shopping ───────────────────────────────────────────────
    # Fetches all US sportsbooks at once.
    # Consensus price (average across books) → fair probability for de-vig.
    # Best individual price → what to actually bet and where.
    BOOK_SHORT = {
        "draftkings": "DK", "fanduel": "FD", "betmgm": "MGM",
        "caesars": "CZR", "pointsbet_us": "PB", "williamhill_us": "WH",
        "betrivers": "BR", "barstool": "BS", "bet365": "B365",
        "unibet_us": "UB", "mybookieag": "MB", "betonlineag": "BOL",
    }
    if ODDS_KEY:
        ev_list = get(f"https://api.the-odds-api.com/v4/sports/baseball_mlb/odds"
                      f"?apiKey={ODDS_KEY}&regions=us&markets=h2h,totals"
                      f"&oddsFormat=american") or []
        for ev in ev_list:
            a, h = ev.get("away_team"), ev.get("home_team")
            if not (a and h):
                continue
            over_px = []; under_px = []
            away_ml_px = []; home_ml_px = []
            best_over = best_under = best_away_ml = best_home_ml = None
            best_over_bk = best_under_bk = best_away_ml_bk = best_home_ml_bk = ""
            total_line = None
            for bk in ev.get("bookmakers", []):
                bk_label = BOOK_SHORT.get(bk["key"], bk.get("title", bk["key"])[:6])
                for m in bk.get("markets", []):
                    if m["key"] == "totals":
                        for o in m["outcomes"]:
                            px = o.get("price"); pt = o.get("point")
                            if o["name"] == "Over" and px:
                                over_px.append(px)
                                if total_line is None and pt:
                                    total_line = pt
                                if best_over is None or px > best_over:
                                    best_over = px; best_over_bk = bk_label
                            elif o["name"] == "Under" and px:
                                under_px.append(px)
                                if best_under is None or px > best_under:
                                    best_under = px; best_under_bk = bk_label
                    elif m["key"] == "h2h":
                        for o in m["outcomes"]:
                            px = o.get("price")
                            if o["name"] == a and px:
                                away_ml_px.append(px)
                                if best_away_ml is None or px > best_away_ml:
                                    best_away_ml = px; best_away_ml_bk = bk_label
                            elif o["name"] == h and px:
                                home_ml_px.append(px)
                                if best_home_ml is None or px > best_home_ml:
                                    best_home_ml = px; best_home_ml_bk = bk_label
            # Consensus = average across books (removes single-book juice).
            # IMPORTANT: de-vig fair probability uses CONSENSUS, never best
            # price — de-vigging against the best price systematically
            # overstates edge, since "best available" is by definition the
            # book that deviates furthest from the market in your favor.
            cons_over   = sum(over_px)    / len(over_px)    if over_px    else best_over
            cons_under  = sum(under_px)   / len(under_px)   if under_px   else best_under
            cons_away_ml = sum(away_ml_px) / len(away_ml_px) if away_ml_px else best_away_ml
            cons_home_ml = sum(home_ml_px) / len(home_ml_px) if home_ml_px else best_home_ml
            odds_idx[(a, h)] = {
                "total": total_line,
                "over":  cons_over,    # consensus → used for fair prob / de-vig
                "under": cons_under,
                "best_over":      best_over,     # best available → what you bet
                "best_under":     best_under,
                "best_over_book": best_over_bk,
                "best_under_book":best_under_bk,
                "away_ml":      cons_away_ml,    # consensus → fair-prob de-vig
                "home_ml":      cons_home_ml,
                "best_away_ml": best_away_ml,    # best available → what you bet
                "best_home_ml": best_home_ml,
                "best_away_ml_book": best_away_ml_bk,
                "best_home_ml_book": best_home_ml_bk,
                "n_books": len(over_px),
                "ml_n_books": len(away_ml_px),   # separate from totals coverage —
                                                  # a book can quote one market
                                                  # without quoting the other
            }

    games = []
    for g in games_raw:
        a, h = g["teams"]["away"], g["teams"]["home"]
        an, hn = a["team"]["name"], h["team"]["name"]
        aid, hid = a["team"]["id"], h["team"]["id"]
        ar = rates.get(aid, {"off": league_rpg, "rapg": league_rpg})
        hr = rates.get(hid, {"off": league_rpg, "rapg": league_rpg})

        def sp_ra9(side):
            pp = side.get("probablePitcher")
            if not pp:
                return league_rpg, "TBD", {}, "R"
            sl = pstat.get(str(pp["id"]), _starter_line({}))
            ra9 = starter_ra9(sl["era"], sl["ip"], sl["xera"], league_rpg,
                              k9=sl["k9"], bb9=sl["bb9"], fip=sl["fip"],
                              recent_ra9=sl.get("recent_ra9"),
                              recent_ip=sl.get("recent_ip", 0.0))
            return ra9, pp.get("fullName", "TBD"), sl, sl.get("pitch_hand", "R")

        away_sp_ra9, away_sp, away_sl, away_pitch_hand = sp_ra9(a)
        home_sp_ra9, home_sp, home_sl, home_pitch_hand = sp_ra9(h)

        venue = g.get("venue", {}).get("name", "")
        temp, wspd, wdir, wx_note = wx_at(g)
        meta = VENUE_META.get(venue)
        is_dome = venue in DOME_VENUES
        if meta:
            wfac, wlabel = wind_factor(wspd, wdir, meta[2], is_dome)
        else:
            wfac, wlabel = 1.0, None

        oc = odds_idx.get((an, hn), {})
        gpk = g.get("gamePk")
        lu  = lineup_map.get(gpk, {})
        af  = team_form.get(aid, {})
        hf  = team_form.get(hid, {})

        # HP umpire from officials — MLB StatsAPI puts this directly on the
        # game object as "officials" when hydrate=officials is requested.
        # (There is no "competitions" wrapper in this API — that's an ESPN
        # convention, not MLB's; using it here silently returned [] always.)
        officials  = g.get("officials", [])
        hp_ump_d   = next((o.get("official", {}) for o in officials
                           if o.get("officialType", "").lower() == "home plate"), {})
        hp_name    = hp_ump_d.get("fullName", "")
        hp_id      = hp_ump_d.get("id")
        ump_factor, ump_label = _ump_factor(hp_name, hp_id, year)

        games.append({
            "away_name": an, "home_name": hn, "venue": venue,
            "away_sp": away_sp, "home_sp": home_sp,
            "away_sp_ra9": away_sp_ra9, "home_sp_ra9": home_sp_ra9,
            "away_sp_k9":  away_sl.get("k9") if away_sl.get("k9") is not None else K9_LG,
            "home_sp_k9":  home_sl.get("k9") if home_sl.get("k9") is not None else K9_LG,
            "away_sp_ip":  away_sl.get("ip"),
            "home_sp_ip":  home_sl.get("ip"),
            # Full pitcher line for the Pitcher Profiles table — era/fip/bb9/
            # recent-form weren't previously stored anywhere (only k9 and ip
            # were), so these are genuinely new fields, not duplicates.
            "away_sp_era":        away_sl.get("era"),
            "home_sp_era":        home_sl.get("era"),
            "away_sp_fip":        away_sl.get("fip"),
            "home_sp_fip":        home_sl.get("fip"),
            "away_sp_bb9":        away_sl.get("bb9"),
            "home_sp_bb9":        home_sl.get("bb9"),
            "away_sp_recent_ra9": away_sl.get("recent_ra9"),
            "home_sp_recent_ra9": home_sl.get("recent_ra9"),
            "away_sp_recent_ip":  away_sl.get("recent_ip"),
            "home_sp_recent_ip":  home_sl.get("recent_ip"),
            "away_expected_ip": away_sl.get("expected_ip", STARTER_INNINGS),
            "home_expected_ip": home_sl.get("expected_ip", STARTER_INNINGS),
            "away_pitch_hand": away_pitch_hand,
            "home_pitch_hand": home_pitch_hand,
            # Opponent K-rate
            "away_opp_k_rate": hr.get("k_rate", league_k_rate),
            "home_opp_k_rate": ar.get("k_rate", league_k_rate),
            "league_k_rate":   league_k_rate,
            # Lineup OPS with platoon splits
            "away_lineup_ops": _lineup_ops(lu.get("away", []), home_pitch_hand),
            "home_lineup_ops": _lineup_ops(lu.get("home", []), away_pitch_hand),
            "league_ops":      league_ops,
            # Recent form
            "away_recent_off": af.get("recent_off"),
            "away_recent_def": af.get("recent_def"),
            "away_form_str":   af.get("form_str"),
            "home_recent_off": hf.get("recent_off"),
            "home_recent_def": hf.get("recent_def"),
            "home_form_str":   hf.get("form_str"),
            # 30-day form (smoother window, dampens single-week swings)
            "away_recent_off_30": af.get("recent_off_30"),
            "away_recent_def_30": af.get("recent_def_30"),
            "away_form_str_30":   af.get("form_str_30"),
            "home_recent_off_30": hf.get("recent_off_30"),
            "home_recent_def_30": hf.get("recent_def_30"),
            "home_form_str_30":   hf.get("form_str_30"),
            # Season W/L records
            "away_win_pct_season": ar.get("win_pct", 0.500),
            "home_win_pct_season": hr.get("win_pct", 0.500),
            "away_games_season":   ar.get("games",   0),
            "home_games_season":   hr.get("games",   0),
            # Bullpen fatigue
            "away_bullpen_fatigue": bp_fatigue.get(aid, {}).get("fatigue_mult", 1.0),
            "home_bullpen_fatigue": bp_fatigue.get(hid, {}).get("fatigue_mult", 1.0),
            "away_bullpen_ra9":     bp_fatigue.get(aid, {}).get("bullpen_ra9"),
            "home_bullpen_ra9":     bp_fatigue.get(hid, {}).get("bullpen_ra9"),
            # HP umpire zone factor
            "hp_ump":     hp_name or "unknown",
            "ump_factor": ump_factor,
            # Injury flags — recent IL placements + auto offensive adjustment
            "away_injuries":    injury_flags.get(aid, {}).get("players", []),
            "home_injuries":    injury_flags.get(hid, {}).get("players", []),
            "away_injury_adj":  injury_flags.get(aid, {}).get("off_adj", 1.0),
            "home_injury_adj":  injury_flags.get(hid, {}).get("off_adj", 1.0),
            "away_off": ar["off"], "home_off": hr["off"],
            "away_rapg": ar["rapg"], "home_rapg": hr["rapg"],
            "park": _dynamic_park_factor(hn, hf), "temp": temp,
            "away_days_rest": af.get("days_rest"),
            "home_days_rest": hf.get("days_rest"),
            "wind_factor": wfac, "wind_label": wlabel, "is_dome": is_dome,
            "wx_note": wx_note,
            "line": _f(oc.get("total")), "over_odds": oc.get("over"),
            "under_odds": oc.get("under"),
            "best_over":       oc.get("best_over"),
            "best_under":      oc.get("best_under"),
            "best_over_book":  oc.get("best_over_book", ""),
            "best_under_book": oc.get("best_under_book", ""),
            "n_books":         oc.get("n_books", 1),
            "ml_n_books":      oc.get("ml_n_books", 1),
            # Moneyline odds — consensus (for de-vig/fair-prob) and best
            # available (for the actual recommended bet), same pattern as totals
            "away_ml":           oc.get("away_ml"),
            "home_ml":           oc.get("home_ml"),
            "best_away_ml":      oc.get("best_away_ml"),
            "best_home_ml":      oc.get("best_home_ml"),
            "best_away_ml_book": oc.get("best_away_ml_book", ""),
            "best_home_ml_book": oc.get("best_home_ml_book", ""),
        })
    return league_rpg, games


# ==============================================================================
# EVALUATE A TOTAL  (de-vig -> edge vs FAIR line -> pick)
# ==============================================================================
# ==============================================================================
# LINE MOVEMENT TRACKING
# ==============================================================================
# Persisted across runs WITHIN the same day (unlike mlb_data.json, which gets
# overwritten every run). Tracks the first-seen ("opening") line for each
# matchup today, so a later run can detect how far the line has moved since
# the morning. This is same-day open-vs-current movement, not day-over-day —
# MLB matchups don't repeat night to night, so "yesterday's closing line"
# isn't a meaningful comparison; what matters is whether sharp money has
# already moved the line in your direction since you first saw the edge.

def _load_line_history():
    try:
        with open(LINE_HISTORY_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_line_history(history):
    try:
        with open(LINE_HISTORY_PATH, "w") as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass

def _track_line_movement(day, matchup, market, line, odds, history):
    """Record the opening line if this is the first time seeing this matchup
    today; otherwise compare against the stored opening snapshot.

    IMPORTANT: only records an opener when `line` is an actual value. If a
    game's total hasn't posted yet on an early run, we do NOT lock in a None
    opener — that would permanently disable movement tracking for that game
    for the rest of the day, since a later run with a real line would just
    see the (already-seen) key and compare against a None baseline forever.
    Instead we wait until the first run that actually has a real line, and
    treat THAT as the opener.

    Returns (line_move, odds_move, is_opening):
      line_move: current_line - opening_line (None if this run IS the opener,
                 or if no real line has been seen yet at all)
      odds_move: current_odds - opening_odds, in cents (None under the same
                 conditions)
      is_opening: True if this run just recorded the first REAL snapshot today
    """
    day_bucket = history.setdefault(day, {})
    key = "%s|%s" % (matchup, market)
    existing = day_bucket.get(key)

    if line is None:
        # Nothing to record yet; also nothing to compare against if we've
        # never seen a real line either. Report as "not yet opened."
        if existing is None or existing.get("open_line") is None:
            return None, None, True
        # We DO have a real opener from a prior run, but this run's line is
        # missing — can't compute movement right now.
        return None, None, False

    if existing is None or existing.get("open_line") is None:
        day_bucket[key] = {"open_line": line, "open_odds": odds}
        return None, None, True

    opener = existing
    line_move = round(line - opener["open_line"], 2)
    odds_move = None if odds is None or opener.get("open_odds") is None else \
                round(odds - opener["open_odds"], 0)
    return line_move, odds_move, False

def _line_movement_note(pick_side, line_move):
    """Human-readable flag for whether the market has already moved toward
    or away from a pick since the opening line was first seen today."""
    if line_move is None or abs(line_move) < 0.5:
        return None
    moved_toward = (pick_side == "Over" and line_move > 0) or \
                   (pick_side == "Under" and line_move < 0)
    direction = "up" if line_move > 0 else "down"
    if moved_toward:
        return "⚠️ line moved %s %.1f since open — market agrees, edge may be baked in" % (
            direction, abs(line_move))
    return "✅ line moved %s %.1f since open — against the pick, edge may be growing" % (
        direction, abs(line_move))


def _confidence_score(edge, n_books, sim_sd, proj_total):
    """Combine edge size, book consensus depth, and simulation stability into
    a single 0-100 confidence score for display alongside each pick.

    Three components, each capped:
      Edge (0-40):       bigger edge = more confidence, diminishing beyond ~10%
      Books (0-30):      more sportsbooks in the consensus = more trustworthy
                          fair-line estimate (a 2-book consensus is thin;
                          8+ books is solid)
      Stability (0-30):  lower coefficient of variation (sim SD / proj total)
                          means the Monte Carlo distribution is tighter around
                          its mean, i.e. less noisy as an estimate

    This is a presentation aid, not a new input to the betting decision —
    it doesn't change which picks clear the edge threshold, it just helps
    you triage among the picks that already did.
    """
    edge_pts  = min(40.0, edge * 400.0)
    books_pts = min(30.0, max(0, n_books) * 5.0)
    cv = (sim_sd / proj_total) if proj_total > 0 else 1.0
    stability_pts = min(30.0, max(0.0, 30.0 - (cv - 0.30) * 100.0))
    return round(min(100.0, edge_pts + books_pts + stability_pts), 1)

def evaluate_total(g, league_rpg, cfg, seed=None):
    env = weather_factor(g["temp"]) * (g["wind_factor"] or 1.0)

    # ── Lineup quality adjustment ─────────────────────────────────────────────
    # When confirmed lineups are posted, adjust each team's offensive rate
    # by the ratio of their actual lineup OPS to the league average.
    # A .780 lineup vs .710 average = +9.9% offensive boost.
    # Capped at ±20% to avoid over-reacting to small samples.
    # Falls back to 1.0 (no adjustment) when lineups aren't posted yet.
    def _lineup_adj(lineup_ops, league_ops):
        if lineup_ops is None or not league_ops:
            return 1.0, False
        adj = lineup_ops / league_ops
        return max(0.80, min(1.20, adj)), True

    away_lu_adj, away_lu_live = _lineup_adj(g.get("away_lineup_ops"),
                                             g.get("league_ops", 0.710))
    home_lu_adj, home_lu_live = _lineup_adj(g.get("home_lineup_ops"),
                                             g.get("league_ops", 0.710))

    # ── Direct form blend (50% season, 50% last-10) ──────────────────────────
    # Replaces the old ±15% _form_adj cap with a true weighted blend.
    # A hot team gets a full weighted blend across three windows — enough to
    # actually flip projections when form diverges from season averages,
    # while the 30-day tier dampens overreaction to a single-week streak.
    def _blend(season, recent_30, recent_10, w_season=0.50, w_30=0.30, w_10=0.20):
        if recent_30 is None:
            return season
        base = w_season * season + w_30 * recent_30
        base += w_10 * recent_10 if recent_10 is not None else w_10 * recent_30
        return base

    away_off_blend = _blend(g["away_off"],  g.get("away_recent_off_30"), g.get("away_recent_off"))
    home_off_blend = _blend(g["home_off"],  g.get("home_recent_off_30"), g.get("home_recent_off"))
    away_def_blend = _blend(g["away_rapg"], g.get("away_recent_def_30"), g.get("away_recent_def"))
    home_def_blend = _blend(g["home_rapg"], g.get("home_recent_def_30"), g.get("home_recent_def"))

    # ── Injury adjustment ─────────────────────────────────────────────────────
    # Only applied when lineups haven't posted — once confirmed, the actual
    # lineup OPS already captures the missing player, so no double-counting.
    if not g.get("away_lineup_ops"):
        away_off_blend *= g.get("away_injury_adj", 1.0)
    if not g.get("home_lineup_ops"):
        home_off_blend *= g.get("home_injury_adj", 1.0)

    # ── Rest / travel adjustment ──────────────────────────────────────────────
    # Small symmetric nudge: a tired team's offense AND pitching both suffer
    # slightly; a rested team's both improve slightly. Capped at ±1%.
    away_rf = _rest_factor(g.get("away_days_rest"))
    home_rf = _rest_factor(g.get("home_days_rest"))
    away_off_blend *= away_rf
    home_off_blend *= home_rf
    away_def_blend /= away_rf   # tired (rf<1) → divide → higher runs allowed
    home_def_blend /= home_rf

    # Apply bullpen fatigue to the blended defensive rate
    away_bp_mult = g.get("away_bullpen_fatigue", 1.0)
    home_bp_mult = g.get("home_bullpen_fatigue", 1.0)

    prev_away = run_prevention_per9(g["away_sp_ra9"], away_def_blend * away_bp_mult,
                                    sp_ip=g.get("away_expected_ip", STARTER_INNINGS),
                                    bullpen_ra9=g.get("away_bullpen_ra9"))
    prev_home = run_prevention_per9(g["home_sp_ra9"], home_def_blend * home_bp_mult,
                                    sp_ip=g.get("home_expected_ip", STARTER_INNINGS),
                                    bullpen_ra9=g.get("home_bullpen_ra9"))

    lam_away, lam_home = project_runs(
        away_off_blend * away_lu_adj,
        home_off_blend * home_lu_adj,
        prev_away, prev_home, league_rpg, g["park"], env)

    # Umpire zone factor — tight zone suppresses runs, loose zone adds them.
    # Applied equally to both teams' expected scoring (not a ML signal).
    ump_f = g.get("ump_factor", 1.0)
    lam_away = lam_away * ump_f
    lam_home = lam_home * ump_f
    sim = simulate(lam_away, lam_home, cfg["n_sims"], seed=seed)

    res = {
        "proj_total": round(sim["proj_total"], 2),
        "sd": round(sim["sd"], 2),
        "lam_away": round(lam_away, 2), "lam_home": round(lam_home, 2),
        "line": g["line"], "pick": None, "edge": 0.0, "confidence": 0.0,
        "stake_pct": 0.0, "reason": "",
        "lineup_active": away_lu_live or home_lu_live,   # True = lineups used
        "away_lineup_ops": round(g["away_lineup_ops"], 3) if g.get("away_lineup_ops") else None,
        "home_lineup_ops": round(g["home_lineup_ops"], 3) if g.get("home_lineup_ops") else None,
    }

    # ML win probability — direct MC win count + Pythagorean blend
    pa = lam_away ** PYTH_EXP
    ph = lam_home ** PYTH_EXP
    denom = pa + ph if (pa + ph) > 0 else 1.0
    p_away_pyth = round(pa / denom, 4)
    p_home_pyth = round(1.0 - p_away_pyth, 4)
    # MC win pcts from the simulation (primary signal)
    res["away_win_pct"] = round(sim["away_win_pct"], 4)
    res["home_win_pct"] = round(sim["home_win_pct"], 4)

    # Log5 formula: statistically correct win probability given each team's
    # actual season record. Captures what pure run models miss — bullpen
    # performance in close games, clutch hitting, late-inning management.
    # Only activated with 20+ games played (meaningful sample).
    aw = g.get("away_win_pct_season", 0.500)
    hw = g.get("home_win_pct_season", 0.500)
    ag = g.get("away_games_season",   0)
    hg = g.get("home_games_season",   0)
    if ag >= 20 and hg >= 20:
        log5_n = aw * (1.0 - hw)
        log5_d = log5_n + hw * (1.0 - aw)
        p_away_log5 = log5_n / log5_d if log5_d > 0 else 0.5
    else:
        p_away_log5 = 0.5  # insufficient sample — neutral

    # ── Form-based win probability ────────────────────────────────────────────
    # Pythagorean win% derived from last-10-game runs scored/allowed.
    # Captures hot/cold streaks that season records and MC miss entirely.
    away_form_runs = g.get("away_recent_off")
    home_form_runs = g.get("home_recent_off")
    if away_form_runs and home_form_runs and away_form_runs > 0 and home_form_runs > 0:
        pa_f = away_form_runs ** PYTH_EXP
        ph_f = home_form_runs ** PYTH_EXP
        p_away_form = pa_f / (pa_f + ph_f) if (pa_f + ph_f) > 0 else 0.5
    else:
        p_away_form = 0.5  # no recent data — neutral

    # ── Form bias: nudge MC toward form when they diverge ────────────────────
    # If form disagrees with the simulation by >5 points, pull MC up to 10
    # points toward the form signal. Prevents MC from anchoring bad picks.
    mc_away   = sim["away_win_pct"]
    form_diff = p_away_form - mc_away
    if abs(form_diff) > 0.05:
        mc_adjusted = mc_away + max(-0.08, min(0.08, form_diff * 0.30))
    else:
        mc_adjusted = mc_away

    # Blend: 40% MC + 25% Pythagorean + 20% Log5 + 15% Form
    # Rebalanced from an earlier, more aggressive 30/15/10/45 split that let
    # team-level recent form override starting-pitcher-driven projections
    # too easily; MC/Pythagorean now carry the majority weight since they
    # already reflect tonight's actual pitcher matchup via lam_away/lam_home.
    p_away_raw = (0.40 * mc_adjusted
                + 0.25 * p_away_pyth
                + 0.20 * p_away_log5
                + 0.15 * p_away_form)
    p_away = max(0.35, min(0.65, p_away_raw))
    res["p_away_win"] = round(p_away, 4)
    res["p_home_win"] = round(1.0 - p_away, 4)

    # ── Moneyline edge — model probability vs de-vigged market price ─────────
    # Previously the dashboard only ever showed which side the MODEL favors
    # (p_away_win vs p_home_win) with no comparison to the actual market
    # price — meaning there was never a real "edge" for moneylines the way
    # there is for totals, so nothing ML ever had grounds to be logged as an
    # actionable pick. This fixes that: de-vig the CONSENSUS market odds
    # (never the best price — that would systematically overstate edge),
    # compare to the model's win probability, and only flag a pick when it
    # clears its own threshold, exactly mirroring the totals logic.
    res["ml_pick"] = None
    res["ml_edge"] = 0.0
    if g.get("away_ml") is not None and g.get("home_ml") is not None:
        fair_away_ml, fair_home_ml = devig_two_way(g["away_ml"], g["home_ml"])
        ml_edge_away = p_away - fair_away_ml
        ml_edge_home = (1.0 - p_away) - fair_home_ml
        res.update({"fair_away_ml": round(fair_away_ml, 4),
                    "fair_home_ml": round(fair_home_ml, 4),
                    "ml_edge_away": round(ml_edge_away, 4),
                    "ml_edge_home": round(ml_edge_home, 4)})
        ml_thr = cfg.get("ml_edge_threshold", cfg["edge_threshold"])
        if ml_edge_away >= ml_thr and ml_edge_away >= ml_edge_home:
            best_ml = g.get("best_away_ml") or g["away_ml"]
            res.update({
                "ml_pick": "away", "ml_team": g["away_name"],
                "ml_edge": ml_edge_away, "ml_confidence": p_away,
                "ml_odds": best_ml, "ml_best_book": g.get("best_away_ml_book", ""),
                "ml_stake_pct": min(cfg["max_stake_pct"],
                                    cfg["kelly_fraction"] * kelly_fraction(p_away, best_ml)),
                "ml_confidence_score": _confidence_score(
                    ml_edge_away, g.get("ml_n_books", 1), sim["sd"], sim["proj_total"]),
            })
        elif ml_edge_home >= ml_thr:
            best_ml = g.get("best_home_ml") or g["home_ml"]
            res.update({
                "ml_pick": "home", "ml_team": g["home_name"],
                "ml_edge": ml_edge_home, "ml_confidence": 1.0 - p_away,
                "ml_odds": best_ml, "ml_best_book": g.get("best_home_ml_book", ""),
                "ml_stake_pct": min(cfg["max_stake_pct"],
                                    cfg["kelly_fraction"] * kelly_fraction(1.0 - p_away, best_ml)),
                "ml_confidence_score": _confidence_score(
                    ml_edge_home, g.get("ml_n_books", 1), sim["sd"], sim["proj_total"]),
            })

    # Projected strikeouts — K/9 × expected innings × opponent K-rate adjustment.
    # A lineup that strikes out 28% of PA vs league avg 22.5% boosts proj Ks by 24%.
    # Capped at ±40% to prevent extreme adjustments on small samples.
    def _proj_ks(k9, opp_k_rate, lg_k_rate, expected_ip):
        if k9 is None:
            return None
        k_adj = (opp_k_rate / lg_k_rate) if lg_k_rate > 0 else 1.0
        k_adj = max(0.70, min(1.40, k_adj))   # cap at ±40%
        ip = expected_ip if expected_ip else STARTER_INNINGS
        return round(k9 * ip / 9.0 * k_adj, 1)
    lg_k  = g.get("league_k_rate", 0.225)
    res["away_proj_ks"] = _proj_ks(g.get("away_sp_k9"),
                                    g.get("away_opp_k_rate", lg_k), lg_k,
                                    g.get("away_expected_ip"))
    res["home_proj_ks"] = _proj_ks(g.get("home_sp_k9"),
                                    g.get("home_opp_k_rate", lg_k), lg_k,
                                    g.get("home_expected_ip"))
    if g["line"] is None or g["over_odds"] is None or g["under_odds"] is None:
        res["reason"] = "no posted total"
        return res

    p_over, p_under, p_push = p_over_ensemble(sim, g["line"])
    fair_over, fair_under = devig_two_way(g["over_odds"], g["under_odds"])
    edge_over  = p_over  - fair_over
    edge_under = p_under - fair_under
    res.update({"p_over": round(p_over, 4), "p_under": round(p_under, 4),
                "fair_over": round(fair_over, 4), "fair_under": round(fair_under, 4),
                "edge_over": round(edge_over, 4), "edge_under": round(edge_under, 4)})

    # Line filter + threshold gate
    if not (cfg["min_total_line"] <= g["line"] <= cfg["max_total_line"]):
        res["reason"] = "line %.1f outside [%.1f, %.1f]" % (
            g["line"], cfg["min_total_line"], cfg["max_total_line"])
        return res

    thr = cfg["edge_threshold"]
    if edge_over >= thr and edge_over >= edge_under:
        best_odds = g.get("best_over") or g["over_odds"]
        res.update({"pick": "Over", "edge": edge_over, "confidence": p_over,
                    "odds": best_odds, "best_book": g.get("best_over_book", ""),
                    "stake_pct": min(cfg["max_stake_pct"],
                                     cfg["kelly_fraction"] * kelly_fraction(p_over, best_odds)),
                    "reason": _reason(g, "Over"),
                    "confidence_score": _confidence_score(
                        edge_over, g.get("n_books", 1), sim["sd"], sim["proj_total"])})
    elif edge_under >= thr:
        best_odds = g.get("best_under") or g["under_odds"]
        res.update({"pick": "Under", "edge": edge_under, "confidence": p_under,
                    "odds": best_odds, "best_book": g.get("best_under_book", ""),
                    "stake_pct": min(cfg["max_stake_pct"],
                                     cfg["kelly_fraction"] * kelly_fraction(p_under, best_odds)),
                    "reason": _reason(g, "Under"),
                    "confidence_score": _confidence_score(
                        edge_under, g.get("n_books", 1), sim["sd"], sim["proj_total"])})
    else:
        res["reason"] = "edge %.1f%% < %.1f%% threshold" % (
            100 * max(edge_over, edge_under), 100 * thr)
    return res

_TEAM_ABBR = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC", "Chicago White Sox": "CHW",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET",
    "Houston Astros": "HOU", "Kansas City Royals": "KCR",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Athletics": "OAK",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SDP", "San Francisco Giants": "SFG",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TBR", "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}

def _abbr(name):
    """Full team name -> standard 3-letter code. Was completely missing
    after the extract/ace merge -- not just this function, the underlying
    mapping data too -- which crashed evaluate_total() via _reason()
    whenever any pick actually fired. Falls back to a safe truncation for
    any name that doesn't match rather than crash on an unexpected value."""
    if not name:
        return "—"
    return _TEAM_ABBR.get(name, name[:3].upper())


def _reason(g, side):
    """One-line human reason from the dominant factor driving the lean."""
    bits = []
    if side == "Over":
        if g["wind_label"] and "out" in g["wind_label"]:
            bits.append("wind blowing out (%s)" % g["wind_label"])
        if g["temp"] and g["temp"] >= 82:
            bits.append("hot %.0fF" % g["temp"])
        if g["park"] >= 1.04:
            bits.append("hitter park")
        if max(g["away_sp_ra9"], g["home_sp_ra9"]) >= 5.0:
            bits.append("shaky starter")
        # Form: offense recently hot
        for side_name, off_key, off_avg in (
                (_abbr(g["away_name"]), "away_recent_off", g["away_off"]),
                (_abbr(g["home_name"]), "home_recent_off", g["home_off"])):
            recent = g.get(off_key)
            if recent and off_avg > 0 and recent / off_avg > 1.10:
                bits.append("%s offense hot (%.1f R/G)" % (side_name, recent))
        # Lineup: depleted opposing pitcher matchup
        if g.get("away_lineup_ops") and g.get("league_ops"):
            if g["away_lineup_ops"] / g["league_ops"] > 1.08:
                bits.append("%s lineup strong (.%d OPS)" % (
                    _abbr(g["away_name"]), int(g["away_lineup_ops"] * 1000)))
        if g.get("home_lineup_ops") and g.get("league_ops"):
            if g["home_lineup_ops"] / g["league_ops"] > 1.08:
                bits.append("%s lineup strong (.%d OPS)" % (
                    _abbr(g["home_name"]), int(g["home_lineup_ops"] * 1000)))
    else:
        if g["wind_label"] and "in" in g["wind_label"]:
            bits.append("wind blowing in (%s)" % g["wind_label"])
        if g["temp"] is not None and g["temp"] <= 55:
            bits.append("cold %.0fF" % g["temp"])
        if g["park"] <= 0.96:
            bits.append("pitcher park")
        if min(g["away_sp_ra9"], g["home_sp_ra9"]) <= 3.6:
            bits.append("strong starter")
        if g["is_dome"]:
            bits.append("dome (no wind)")
        # Form: offense recently cold or defense recently dominant
        for side_name, off_key, off_avg in (
                (_abbr(g["away_name"]), "away_recent_off", g["away_off"]),
                (_abbr(g["home_name"]), "home_recent_off", g["home_off"])):
            recent = g.get(off_key)
            if recent and off_avg > 0 and recent / off_avg < 0.88:
                bits.append("%s offense cold (%.1f R/G)" % (side_name, recent))
        for side_name, def_key, def_avg in (
                (_abbr(g["away_name"]), "away_recent_def", g["away_rapg"]),
                (_abbr(g["home_name"]), "home_recent_def", g["home_rapg"])):
            recent = g.get(def_key)
            if recent and def_avg > 0 and recent / def_avg < 0.88:
                bits.append("%s pen dominant (%.1f RA/G)" % (side_name, recent))
        # Lineup: weak lineup spotted
        if g.get("away_lineup_ops") and g.get("league_ops"):
            if g["away_lineup_ops"] / g["league_ops"] < 0.92:
                bits.append("%s lineup weak (.%d OPS)" % (
                    _abbr(g["away_name"]), int(g["away_lineup_ops"] * 1000)))
        if g.get("home_lineup_ops") and g.get("league_ops"):
            if g["home_lineup_ops"] / g["league_ops"] < 0.92:
                bits.append("%s lineup weak (.%d OPS)" % (
                    _abbr(g["home_name"]), int(g["home_lineup_ops"] * 1000)))
    return ", ".join(bits) if bits else "model projection vs line"


# ==============================================================================
# RENDER  (the dashboard IS the output — no LLM involved)
# ==============================================================================
def bar(frac, width=10):
    frac = max(0.0, min(1.0, frac))
    filled = int(round(frac * width))
    return "\u2588" * filled + "\u2591" * (width - filled)

def render_html_dashboard(games_eval, cfg, league_rpg, day, json_data):
    import base64
    logo_path = os.path.join(HERE, "acebot_logo.png")
    logo_data = ""
    try:
        with open(logo_path, "rb") as f:
            logo_data = "data:image/png;base64," + base64.b64encode(f.read()).decode()
    except Exception:
        logo_data = ""
    games = json_data["games"]
    picks = json_data["picks"]
    ml_picks = json_data["ml_picks"]

    html = []
    html.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AceBot MLB - {day}</title>
<style>
:root{{--g:#22b455;--bg:#0b0e11;--card:#12161a;--t:#e6e6e6;--m:#9aa0a6;--b:#23292f}}
*{{box-sizing:border-box}}body{{margin:0;background:#000;color:var(--t);font-family:-apple-system,BlinkMacSystemFont,Inter,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
.page{{border:14px solid var(--g);min-height:100vh;padding:22px}}
.wrap{{max-width:1120px;margin:0 auto}}
.logo{{text-align:center;margin:8px 0 18px}}.logo img{{height:100px;image-rendering:pixelated}}
h1{{text-align:center;margin:0;font-size:26px}} .sub{{text-align:center;color:var(--m);font-size:13px;margin:6px 0 20px}}
.card{{background:var(--card);border:1px solid var(--b);border-radius:14px;padding:16px;margin-bottom:18px}}
h2{{margin:0 0 10px;font-size:17px;color:#b9f7c7}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:8px 6px;border-bottom:1px solid #1b2025;text-align:left}}th{{background:#0f1316;color:#a7eab8;position:sticky;top:0}}tr:hover td{{background:#161b20}}
.tablewrap{{overflow:auto;max-height:420px;border-radius:10px;-webkit-overflow-scrolling:touch}}
.tablewrap table{{min-width:640px}}
.pills{{display:flex;flex-wrap:wrap;gap:8px}}.pill{{display:inline-flex;gap:6px;align-items:center;padding:8px 12px;border-radius:999px;background:#0f291a;border:1px solid #2a7a4a;color:#d7ffe5;font-weight:600;font-size:12px}}.pill .e{{background:var(--g);color:#00230f;padding:1px 6px;border-radius:999px;font-weight:700}}
.muted{{color:var(--m)}}
.legend{{list-style:none;margin:14px 0 0;padding:12px;background:#0d1013;border:1px solid var(--b);border-radius:10px;font-size:12px;color:var(--m);line-height:1.5}}
.legend li{{margin-bottom:8px}}.legend li:last-child{{margin-bottom:0}}.legend b{{color:#b9f7c7}}
</style>
</head>
<body><div class="page"><div class="wrap">
<div class="logo">{f'<img src="{logo_data}" alt="AceBot">' if logo_data else '<div style="font-size:32px;color:var(--g);font-weight:800">ACEBOT</div>'}</div>
<h1>AceBot MLB Dashboard</h1>
<div class="sub">{day} • {len(games)} games • league {league_rpg:.2f} R/G • threshold {cfg['edge_threshold']*100:.1f}%</div>
""")

    # Slate table
    html.append('<div class="card"><h2>Today\'s Slate & Odds</h2><div class="tablewrap"><table><thead><tr>')
    for h in ["Matchup","Venue","Away SP","Home SP","Line","Proj","ML","Pick","Edge"]:
        html.append(f"<th>{h}</th>")
    html.append("</tr></thead><tbody>")
    for g in games:
        matchup = g["matchup"]
        venue = g["venue"].replace(" Field","").replace(" Park","").replace(" Stadium","")
        asp = g["away_sp"].split()[-1] if g["away_sp"] else "TBD"
        hsp = g["home_sp"].split()[-1] if g["home_sp"] else "TBD"
        line = f"{g['line']:.1f}" if g["line"] else "—"
        proj = f"{g['proj_total']:.1f}"
        ml = f"{int(g['p_home_win'])}%" if g['p_home_win']>g['p_away_win'] else f"{int(g['p_away_win'])}%"
        pick = f"{g['pick']} {line}" if g["pick"] else "—"
        edge = f"+{g['edge_pct']:.1f}%" if g["pick"] else "—"
        html.append(f"<tr><td>{matchup}</td><td>{venue}</td><td>{asp}</td><td>{hsp}</td><td>{line}</td><td>{proj}</td><td>{ml}</td><td>{pick}</td><td>{edge}</td></tr>")
    html.append("</tbody></table></div></div>")

    # Picks pills
    html.append('<div class="card"><h2>Recommended Totals</h2>')
    if picks:
        html.append('<div class="pills">')
        for p in picks:
            html.append(f'<div class="pill"><span>{p["matchup"]}</span><span>{p["pick"]} {p["line"]:.1f}</span><span class="e">+{p["edge_pct"]:.1f}%</span></div>')
        html.append('</div>')
    else:
        html.append('<p class="muted">No picks today.</p>')
    html.append('</div>')

    # ML pills
    html.append('<div class="card"><h2>Moneylines</h2>')
    if ml_picks:
        html.append('<div class="pills">')
        for m in ml_picks:
            html.append(f'<div class="pill"><span>{m["ml_team"]}</span><span>{m["ml_conf_pct"]:.0f}%</span><span class="e">{m["ml_odds"]:+d}</span><span>+{m["ml_edge_pct"]:.1f}%</span></div>')
        html.append('</div>')
    else:
        html.append('<p class="muted">None</p>')   # was html_parts.append – fixed
    html.append('''
<ul class="legend">
  <li><b>Win%</b> — the model's own probability estimate for that team,
      blended from four signals: 40% Monte Carlo simulation of the actual
      pitcher/lineup matchup, 25% Pythagorean expectation from projected
      runs, 20% Log5 (season record), 15% recent form (last 10 games).</li>
  <li><b>Edge</b> — Win% minus the de-vigged CONSENSUS market price
      (averaged across books, with the bookmaker hold removed) — not the
      best price shown below. This is intentional: computing edge off the
      single best line across books would systematically overstate it.</li>
  <li><b>Odds shown</b> — the BEST price actually available across
      tracked books, for placing the bet. Because this can differ from the
      consensus price edge is computed against, don't expect the displayed
      odds' own implied probability to line up exactly with the edge
      number next to it.</li>
  <li>Only teams the model favors outright (Win% ≥ 50%) are listed here.
      A team can still have positive edge without being favored — that's a
      legitimate underdog value play — but it won't appear in this list,
      to keep it consistent with the Moneyline Picks table below.</li>
</ul>
''')
    html.append('</div>')

    # Moneyline Picks table -- every game's win% breakdown, not just the
    # subset that cleared the edge threshold (that's what the pills above
    # already show). Matches the old markdown dashboard's "Moneyline Picks"
    # table shape. Reads games_eval directly since away_form_str/
    # home_form_str aren't carried into json_data's reduced schema.
    html.append('<div class="card"><h2>Moneyline Picks</h2><div class="tablewrap"><table><thead><tr>')
    for h in ["Matchup","Away Win%","Home Win%","Model ML Pick","Edge","Away Form","Home Form"]:
        html.append(f"<th>{h}</th>")
    html.append("</tr></thead><tbody>")
    for g, r in games_eval:
        matchup = "%s @ %s" % (_abbr(g["away_name"]), _abbr(g["home_name"]))
        a_pw = round(r.get("p_away_win", 0.5) * 100, 0)
        h_pw = round(r.get("p_home_win", 0.5) * 100, 0)
        fav_team = _abbr(g["away_name"]) if a_pw >= h_pw else _abbr(g["home_name"])
        edge = f'+{r["ml_edge"]*100:.1f}%' if r.get("ml_pick") else "—"
        away_form = g.get("away_form_str") or "—"
        home_form = g.get("home_form_str") or "—"
        html.append(f"<tr><td>{matchup}</td><td>{a_pw:.0f}%</td><td>{h_pw:.0f}%</td>"
                    f"<td>{fav_team}</td><td>{edge}</td><td>{away_form}</td><td>{home_form}</td></tr>")
    html.append("</tbody></table></div></div>")

    # K Projections -- the model's own projected strikeout total per pitcher
    # (K/9 x expected innings x opponent K-rate adjustment). NOT live
    # sportsbook prop lines -- that fetch (the Odds API's pitcher_strikeouts
    # market) lived in the old standalone extract script and didn't survive
    # the merge into this file. Labeled honestly rather than implying these
    # are bookmaker lines when they're the model's own number.
    k_rows = []
    for g, r in games_eval:
        if r.get("away_proj_ks") is not None and g.get("away_sp") and g["away_sp"] != "TBD":
            k_rows.append((g["away_sp"].split()[-1], _abbr(g["away_name"]), r["away_proj_ks"]))
        if r.get("home_proj_ks") is not None and g.get("home_sp") and g["home_sp"] != "TBD":
            k_rows.append((g["home_sp"].split()[-1], _abbr(g["home_name"]), r["home_proj_ks"]))
    k_rows.sort(key=lambda x: x[2], reverse=True)

    html.append('<div class="card"><h2>K Projections</h2>')
    if k_rows:
        html.append('<div class="pills">')
        for name, team, ks in k_rows:
            html.append(f'<div class="pill"><span>{name} ({team})</span><span class="e">{ks:.1f}K</span></div>')
        html.append('</div>')
    else:
        html.append('<p class="muted">None</p>')
    html.append('''
<ul class="legend">
  <li>Model's own projected strikeout total: K/9 &times; tonight's expected
      innings (regressed from recent starts) &times; an adjustment for the
      opposing lineup's strikeout rate, capped at &plusmn;40%.</li>
  <li>These are NOT live sportsbook prop lines -- just the model's number,
      for comparing against whatever line you find elsewhere.</li>
</ul>
''')
    html.append('</div>')

    # Pitcher Profiles -- reads games_eval directly (not json_data) since
    # the per-pitcher detail fields (era/fip/k9/bb9/ip/recent_ra9) survived
    # the extract/ace merge on the raw game dict but were never carried
    # into json_data's reduced schema. Added at the bottom per request.
    def _fmt2(v):
        return f"{v:.2f}" if isinstance(v, (int, float)) else "—"
    def _fmt1(v):
        return f"{v:.1f}" if isinstance(v, (int, float)) else "—"
    html.append('<div class="card"><h2>Pitcher Profiles</h2><div class="tablewrap"><table><thead><tr>')
    for h in ["Pitcher (Team)","ERA","FIP","K/9","BB/9","IP","Recent RA9","Final RA9"]:
        html.append(f"<th>{h}</th>")
    html.append("</tr></thead><tbody>")
    for g, r in games_eval:
        away_name = g["away_sp"].split()[-1] if g.get("away_sp") and g["away_sp"] != "TBD" else "TBD"
        home_name = g["home_sp"].split()[-1] if g.get("home_sp") and g["home_sp"] != "TBD" else "TBD"
        away_team = _abbr(g["away_name"])
        home_team = _abbr(g["home_name"])
        html.append(f"<tr><td>{away_name} ({away_team})</td><td>{_fmt2(g.get('away_sp_era'))}</td>"
                    f"<td>{_fmt2(g.get('away_sp_fip'))}</td><td>{_fmt2(g.get('away_sp_k9'))}</td>"
                    f"<td>{_fmt2(g.get('away_sp_bb9'))}</td><td>{_fmt1(g.get('away_sp_ip'))}</td>"
                    f"<td>{_fmt2(g.get('away_sp_recent_ra9'))}</td><td>{_fmt2(g.get('away_sp_ra9'))}</td></tr>")
        html.append(f"<tr><td>{home_name} ({home_team})</td><td>{_fmt2(g.get('home_sp_era'))}</td>"
                    f"<td>{_fmt2(g.get('home_sp_fip'))}</td><td>{_fmt2(g.get('home_sp_k9'))}</td>"
                    f"<td>{_fmt2(g.get('home_sp_bb9'))}</td><td>{_fmt1(g.get('home_sp_ip'))}</td>"
                    f"<td>{_fmt2(g.get('home_sp_recent_ra9'))}</td><td>{_fmt2(g.get('home_sp_ra9'))}</td></tr>")
    html.append("</tbody></table></div></div>")

    html.append('</div></div></body></html>')
    return "\n".join(html)


def _build_dashboard_json(games_eval, day):
    """Assemble the {games, picks, ml_picks} structure render_html_dashboard
    expects from the raw (g, r) tuples evaluate_total() produces.

    This glue was missing entirely after the extract/ace merge -- render_
    html_dashboard() existed but nothing built its required input shape,
    so it was uncallable. Field names and scales here are verified against
    render_html_dashboard's actual body, not assumed: p_away_win/p_home_win
    are 0-1 fractions internally and need *100 for the "NN%" display;
    edge/ml_edge are likewise 0-1 fractions needing *100 for "+N.N%".
    """
    games, picks, ml_picks = [], [], []
    for g, r in games_eval:
        game_row = {
            "matchup":    "%s @ %s" % (_abbr(g["away_name"]), _abbr(g["home_name"])),
            "venue":      g.get("venue", ""),
            "away_sp":    g.get("away_sp"),
            "home_sp":    g.get("home_sp"),
            "line":       g.get("line"),
            "proj_total": r.get("proj_total", 0.0),
            "p_away_win": round(r.get("p_away_win", 0.5) * 100, 1),
            "p_home_win": round(r.get("p_home_win", 0.5) * 100, 1),
            "pick":       r.get("pick"),
            "edge_pct":   round(r.get("edge", 0.0) * 100, 1),
        }
        games.append(game_row)
        if r.get("pick"):
            picks.append(game_row)
        if r.get("ml_pick"):
            ml_conf = r.get("ml_confidence", 0.5)
            # Only list a pick here if it's also the model's actual favorite
            # (win% >= 50%, i.e. >= the opposing side too) -- otherwise this
            # list can show an underdog "value" pick (positive edge vs the
            # de-vigged CONSENSUS price, computed off a different number than
            # the best-price odds displayed) sitting next to a team the model
            # itself doesn't even think is more likely to win. That's legitimate
            # +EV theory, but it read as a contradiction next to the Moneyline
            # Picks table's own win% breakdown, which shows the true favorite
            # for every game. Filtering here makes the two sections agree.
            # The underlying edge computation in evaluate_total() is
            # unchanged -- auto-logging/backtesting still captures every
            # genuine +EV pick, favorite or not; this filter only affects
            # what's recommended on the dashboard itself.
            if ml_conf >= 0.5:
                ml_picks.append({
                    "matchup":     game_row["matchup"],
                    "ml_team":     _abbr(r.get("ml_team", "")),
                    "ml_odds":     int(r.get("ml_odds", 0) or 0),
                    "ml_edge_pct": round(r.get("ml_edge", 0.0) * 100, 1),
                    "ml_conf_pct": round(ml_conf * 100, 1),
                })
    ml_picks.sort(key=lambda m: m["ml_conf_pct"], reverse=True)
    return {"games": games, "picks": picks, "ml_picks": ml_picks}


def _profit(odds_str, won):
    """Profit in units for a 1u stake at the given American odds.

    Returns None on malformed/missing odds rather than raising, so callers
    (both logging and grading) can leave profit_1u blank for a bad row
    instead of crashing the whole run over one corrupted value.
    """
    try:
        odds = float(str(odds_str).strip().replace("+", ""))
    except (TypeError, ValueError):
        return None
    if not won:
        return -1.0
    return (odds / 100.0) if odds > 0 else (100.0 / -odds)


def _migrate_picks_header(path):
    """If picks_log.csv exists but has an older/different header, leave the
    data rows alone and just make sure new rows append with the CURRENT
    header's column order -- avoids silently corrupting a file that predates
    a schema change. If the file doesn't exist yet, this is a no-op; the
    first write creates it fresh."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            first = f.readline()
        if first.strip() != PICKS_HEADER.strip():
            # Different header than expected -- don't touch existing rows,
            # just note it so a human can look. Rewriting historical rows
            # to a new column order automatically is the kind of "fix" that
            # actually destroys data if the assumption is wrong.
            print("⚠️  picks_log.csv header doesn't match the current schema "
                 "-- leaving existing rows as-is, new rows still append correctly.")
    except Exception:
        pass


def _dedup_keys(path):
    """(date, team, market) keys already present, so re-running the same day
    doesn't double-log the same pick."""
    keys = set()
    if not os.path.exists(path):
        return keys
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                keys.add((row.get("date", "").strip(),
                         row.get("team", "").strip(),
                         row.get("market", "").strip()))
    except Exception:
        pass
    return keys


def _auto_log_picks(games_eval, day):
    """Append every fired pick (totals AND moneylines) from today's run to
    picks_log.csv, tagged 'auto' so they're distinguishable from any
    manually-logged rows. Deduped against (date, team, market) so running
    the script twice in one day doesn't create duplicate rows.
    """
    _migrate_picks_header(PICKS_CSV)
    existing = _dedup_keys(PICKS_CSV)
    is_new = not os.path.exists(PICKS_CSV)

    rows_to_write = []
    for g, r in games_eval:
        matchup = "%s@%s" % (_abbr(g["away_name"]), _abbr(g["home_name"]))

        if r.get("pick"):
            market = "%s %.1f" % (r["pick"], g["line"])
            key = (day, matchup, market)
            if key not in existing:
                best_odds = g.get("best_over") if r["pick"] == "Over" else g.get("best_under")
                if best_odds is None:
                    best_odds = g.get("over_odds") if r["pick"] == "Over" else g.get("under_odds")
                rows_to_write.append([
                    day, "auto", matchup, "total", market,
                    best_odds if best_odds is not None else "n/a",
                    "", "", "", "", "", "", ""])
                existing.add(key)

        if r.get("ml_pick"):
            team_name = r.get("ml_team", "")
            market = "Moneyline"
            key = (day, team_name, market)
            if key not in existing:
                rows_to_write.append([
                    day, "auto", team_name, "team", market,
                    r.get("ml_odds", "n/a"),
                    "", "", "", "", "", "", ""])
                existing.add(key)

    if not rows_to_write:
        return 0

    with open(PICKS_CSV, "a", newline="", encoding="utf-8") as f:
        if is_new:
            f.write(PICKS_HEADER)
        w = csv.writer(f)
        for row in rows_to_write:
            w.writerow(row)
    return len(rows_to_write)


def _fetch_game_results(day):
    """Real final scores for a given date, for grading. Returns
    {"matchups": {"AWY@HME": {"away":R,"home":R,"total":R}}, "teams": {full_name: won_bool}}.
    Returns empty dicts (not None) on any fetch failure, so grading skips
    that date cleanly rather than crashing the whole grading pass."""
    empty = {"matchups": {}, "teams": {}}
    sched = get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={day}"
               "&hydrate=linescore")
    if not sched:
        return empty
    matchups, teams = {}, {}
    for d in sched.get("dates", []):
        for game in d.get("games", []):
            status = game.get("status", {}).get("detailedState", "")
            if status != "Final":
                continue
            away = game.get("teams", {}).get("away", {})
            home = game.get("teams", {}).get("home", {})
            away_name = away.get("team", {}).get("name", "")
            home_name = home.get("team", {}).get("name", "")
            away_score = away.get("score")
            home_score = home.get("score")
            if away_score is None or home_score is None:
                continue
            key = "%s@%s" % (_abbr(away_name), _abbr(home_name))
            matchups[key] = {"away": away_score, "home": home_score,
                             "total": away_score + home_score}
            teams[away_name] = away_score > home_score
            teams[home_name] = home_score > away_score
    return {"matchups": matchups, "teams": teams}


def _auto_grade_picks():
    """Fill in won/profit_1u for previously-logged rows that don't have a
    result yet. Groups ungraded rows by date so each date's results are
    only fetched once. Handles totals (push-aware: total==line -> won='P',
    profit=+0.000) and moneylines (team win/loss) separately.
    """
    if not os.path.exists(PICKS_CSV):
        return 0

    with open(PICKS_CSV, "r", encoding="utf-8-sig") as f:
        raw = f.read()
    lines = raw.splitlines()
    if len(lines) < 2:
        return 0
    header = lines[0]
    cols = [c.strip() for c in header.split(",")]
    idx = {c: i for i, c in enumerate(cols)}
    needed = ("date", "team", "kind", "market", "open_ml", "won", "profit_1u")
    if not all(c in idx for c in needed):
        print("⚠️  picks_log.csv header missing expected columns, skipping auto-grade.")
        return 0

    # Group ungraded row indices by date so results are fetched once per date
    ungraded_dates = set()
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) <= idx["won"]:
            continue
        if parts[idx["won"]].strip() in ("", "?"):
            d = parts[idx["date"]].strip()
            if d:
                ungraded_dates.add(d)

    results_by_date = {d: _fetch_game_results(d) for d in ungraded_dates}

    graded = 0
    new_lines = [header]
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) <= idx["won"] or parts[idx["won"]].strip() not in ("", "?"):
            new_lines.append(line)
            continue
        d = parts[idx["date"]].strip()
        team = parts[idx["team"]].strip()
        kind = parts[idx["kind"]].strip() if idx.get("kind") is not None and len(parts) > idx["kind"] else ""
        market = parts[idx["market"]].strip() if len(parts) > idx["market"] else ""
        odds = parts[idx["open_ml"]].strip() if len(parts) > idx["open_ml"] else ""
        res = results_by_date.get(d, {"matchups": {}, "teams": {}})

        won_val, profit_val = None, None
        if kind == "total" and team in res["matchups"]:
            total = res["matchups"][team]["total"]
            try:
                line_val = float(market.split()[-1])
            except (ValueError, IndexError):
                line_val = None
            if line_val is not None:
                if total == line_val:
                    won_val, profit_val = "P", "+0.000"
                else:
                    is_over = market.lower().startswith("over")
                    won = (total > line_val) if is_over else (total < line_val)
                    won_val = "1" if won else "0"
                    profit = _profit(odds, won)
                    profit_val = ("%+.3f" % profit) if profit is not None else ""
        elif kind == "team" and team in res["teams"]:
            won = res["teams"][team]
            won_val = "1" if won else "0"
            profit = _profit(odds, won)
            profit_val = ("%+.3f" % profit) if profit is not None else ""

        if won_val is not None:
            while len(parts) <= idx["profit_1u"]:
                parts.append("")
            parts[idx["won"]] = won_val
            parts[idx["profit_1u"]] = profit_val
            graded += 1
        new_lines.append(",".join(parts))

    if graded:
        with open(PICKS_CSV, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
    return graded


def main(argv):
    """Entry point -- fetch today's (or --date's) slate, evaluate every game,
    render the HTML dashboard, write it to OUTPUT_PATH.

    This function and the __main__ block below were entirely missing after
    the extract/ace merge, which is why running the script did nothing (no
    crash, no output, silent no-op) rather than producing a dashboard.
    Restores the core daily-run pipeline plus pick-logging/auto-grading
    (_auto_log_picks, _auto_grade_picks, PICKS_CSV) -- both were lost in the
    extract/ace merge and have now been rebuilt to the same CSV schema
    mlb_backtest.py already expects. Does NOT restore the old CLI
    subcommands (audit, result, grade, log, slip) -- logging/grading now
    happen automatically as part of every run instead.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().strftime("%Y-%m-%d"))
    ap.add_argument("--sims", type=int, default=None)
    ap.add_argument("--no-log", action="store_true",
                    help="skip auto-logging today's picks to picks_log.csv")
    ap.add_argument("--no-grade", action="store_true",
                    help="skip auto-grading previously ungraded picks")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.sims:
        cfg["n_sims"] = args.sims

    year = int(args.date.split("-")[0])
    league_rpg, games_raw = fetch_slate(args.date, year, cfg)

    games_eval = []
    for g in games_raw:
        r = evaluate_total(g, league_rpg, cfg)
        games_eval.append((g, r))

    json_data = _build_dashboard_json(games_eval, args.date)
    html_out  = render_html_dashboard(games_eval, cfg, league_rpg, args.date, json_data)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html_out)
    print("✅ %d game(s) -> %s" % (len(games_eval), OUTPUT_PATH))

    if not args.no_log:
        n_logged = _auto_log_picks(games_eval, args.date)
        if n_logged:
            print("📝 %d pick(s) logged -> %s" % (n_logged, PICKS_CSV))
    if not args.no_grade:
        n_graded = _auto_grade_picks()
        if n_graded:
            print("✅ %d prior pick(s) graded" % n_graded)


if __name__ == "__main__":
    main(sys.argv[1:])

