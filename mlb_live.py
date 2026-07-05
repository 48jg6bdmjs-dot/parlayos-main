#!/usr/bin/env python3
"""
fetch_mlb_live.py
Fetches today's MLB games from the free MLB Stats API and writes mlb_live.json
in the exact schema ACEBOT Terminal expects.

Usage:
    python fetch_mlb_live.py              # today's games (ET)
    python fetch_mlb_live.py 2026-07-04  # specific date
    python fetch_mlb_live.py --output /path/to/mlb_live.json
"""

import json
import sys
import argparse
from datetime import datetime, timezone, timedelta

import requests

# ── Constants ─────────────────────────────────────────────────────────────────

API_BASE  = "https://statsapi.mlb.com/api/v1"
HYDRATE   = "linescore,probablePitcher(note)"
ET_OFFSET = timedelta(hours=-4)   # EDT; change to -5 for EST in winter


# ── Helpers ───────────────────────────────────────────────────────────────────

def et_now() -> datetime:
    """Current time in US Eastern (approx — avoids pytz dependency)."""
    return datetime.now(timezone.utc).astimezone(timezone(ET_OFFSET))


def to_et(iso_str: str) -> datetime | None:
    """Parse an ISO-8601 game-date string and convert to ET."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone(ET_OFFSET))
    except ValueError:
        return None


def format_display(game: dict, is_live: bool, is_final: bool,
                   inning: int | str, inning_state: str,
                   away_score: int, home_score: int,
                   start_time_iso: str) -> str:
    """Build the human-readable display string for a game."""
    if is_live and inning:
        return f"{inning_state} {inning} | {away_score}-{home_score}"
    if is_final:
        return f"Final {away_score}-{home_score}"
    # Pregame / Scheduled — show local start time in ET
    dt_et = to_et(start_time_iso)
    if dt_et:
        hour   = dt_et.strftime("%I").lstrip("0") or "12"
        minute = dt_et.strftime("%M")
        ampm   = dt_et.strftime("%p")
        return f"{hour}:{minute} {ampm} ET"
    return game.get("status", {}).get("detailedState", "")


# ── Main fetch ────────────────────────────────────────────────────────────────

def fetch_games(date: str) -> dict:
    """
    Pull today's schedule from the MLB Stats API and return a dict
    matching the mlb_live.json schema.
    """
    url    = f"{API_BASE}/schedule"
    params = {
        "sportId" : 1,
        "date"    : date,
        "hydrate" : HYDRATE,
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    raw = resp.json()

    games = []

    for date_block in raw.get("dates", []):
        for g in date_block.get("games", []):

            # ── Status ────────────────────────────────────────────────────────
            status_obj    = g.get("status", {})
            status        = status_obj.get("detailedState", "")
            status_code   = status_obj.get("statusCode", "")
            abstract      = status_obj.get("abstractGameState", "")
            is_live       = abstract == "Live"
            is_final      = abstract == "Final"

            # ── Teams ─────────────────────────────────────────────────────────
            away_data     = g["teams"]["away"]
            home_data     = g["teams"]["home"]
            away_team_obj = away_data.get("team", {})
            home_team_obj = home_data.get("team", {})

            away_abbr     = away_team_obj.get("abbreviation", "")
            home_abbr     = home_team_obj.get("abbreviation", "")
            away_name     = away_team_obj.get("name", "")
            home_name     = home_team_obj.get("name", "")
            away_score    = away_data.get("score") or 0
            home_score    = home_data.get("score") or 0

            # ── Linescore ─────────────────────────────────────────────────────
            ls            = g.get("linescore", {})
            inning        = ls.get("currentInning", "")
            inning_state  = ls.get("inningState", "")
            outs          = ls.get("outs", 0)

            # ── Venue ─────────────────────────────────────────────────────────
            venue         = g.get("venue", {}).get("name", "")

            # ── Probable pitchers ─────────────────────────────────────────────
            away_sp = away_data.get("probablePitcher", {}).get("fullName", "")
            home_sp = home_data.get("probablePitcher", {}).get("fullName", "")

            # ── Start time ────────────────────────────────────────────────────
            start_time    = g.get("gameDate", "")

            # ── Display string ────────────────────────────────────────────────
            display = format_display(
                g, is_live, is_final,
                inning, inning_state,
                away_score, home_score,
                start_time,
            )

            games.append({
                "game_id"     : g.get("gamePk"),
                "matchup"     : f"{away_abbr} @ {home_abbr}",
                "away_team"   : away_name,
                "home_team"   : home_name,
                "away_abbr"   : away_abbr,
                "home_abbr"   : home_abbr,
                "away_score"  : away_score,
                "home_score"  : home_score,
                "status"      : status,
                "status_code" : status_code,
                "inning"      : inning,
                "inning_state": inning_state,
                "outs"        : outs,
                "venue"       : venue,
                "away_sp"     : away_sp,
                "home_sp"     : home_sp,
                "start_time"  : start_time,
                "is_live"     : is_live,
                "is_final"    : is_final,
                "display"     : display,
            })

    return {
        "last_updated": et_now().isoformat(),
        "date"        : date,
        "game_count"  : len(games),
        "games"       : games,
    }


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch live MLB games → mlb_live.json")
    parser.add_argument("date",   nargs="?", default=None,
                        help="Date in YYYY-MM-DD format (default: today ET)")
    parser.add_argument("--output", "-o", default="mlb_live.json",
                        help="Output file path (default: mlb_live.json)")
    args = parser.parse_args()

    date = args.date or et_now().strftime("%Y-%m-%d")

    print(f"Fetching MLB games for {date} …")
    try:
        data = fetch_games(date)
    except requests.RequestException as exc:
        print(f"ERROR: API request failed — {exc}", file=sys.stderr)
        sys.exit(1)

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)

    print(f"✓ {data['game_count']} games written to {args.output}")
    print(f"  Updated: {data['last_updated']}")

    # Quick summary
    live  = [g for g in data["games"] if g["is_live"]]
    final = [g for g in data["games"] if g["is_final"]]
    sched = [g for g in data["games"] if not g["is_live"] and not g["is_final"]]
    print(f"  Live: {len(live)}  |  Final: {len(final)}  |  Scheduled: {len(sched)}")


if __name__ == "__main__":
    main()
