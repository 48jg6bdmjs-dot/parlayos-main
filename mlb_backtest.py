#!/usr/bin/env python3
"""
================================================================================
 mlb_backtest.py  —  Results Analyzer + Threshold Tuner + Live Trade Tracker
================================================================================
 Reads picks_log.csv, grades performance, and WRITES tuned thresholds back to
 mlb_config.json so mlb_ace.py reads them on the next run.

 What it tunes
 -------------
   edge_threshold : raised if low-edge bets are losing, lowered if high-edge
                    bets are clearly profitable and you are passing on too many.
   min_total_line / max_total_line : narrowed to bands where realised ROI > 0.

 Live Trades
 -----------
   --track "NYY ML -150"   Log a new live bet with current odds.
   --close "NYY ML -130"   Close the bet at the closing line (fills CLV).
   --grade won|loss|push   Grade the outcome and update P&L.
   --list                  Show all open/pending live trades.
   Live bets are written to picks_log.csv as real rows with tag="live",
   so they flow through to the regular backtest analysis automatically.

 Run
 ---
   python3 mlb_backtest.py                     # analyse + write mlb_config.json
   python3 mlb_backtest.py --dry-run           # analyse only, no config write
   python3 mlb_backtest.py --json              # machine-readable analysis
   python3 mlb_backtest.py --track "PHI ML -130"
   python3 mlb_backtest.py --close "PHI ML -120" --bet-id <id>
   python3 mlb_backtest.py --grade won --bet-id <id>
   python3 mlb_backtest.py --list
================================================================================
"""
import csv, json, os, sys, uuid
from collections import defaultdict
from datetime import date, datetime

HERE        = os.path.dirname(os.path.abspath(__file__))
CSV_PATH    = os.path.join(HERE, "picks_log.csv")
CONFIG_PATH = os.path.join(HERE, "mlb_config.json")

EDGE_MIN, EDGE_MAX   = 0.02, 0.10
LINE_FLOOR, LINE_CEIL = 6.0, 13.5
MIN_BETS_TO_TUNE     = 15

DEFAULTS = {
    "edge_threshold": 0.045, "min_total_line": 6.5, "max_total_line": 13.0,
    "n_sims": 20000, "kelly_fraction": 0.25, "max_stake_pct": 0.05,
}


# ─────────────────────────────────────────────────────────────────────────────
# LIVE TRADE TRACKING
# ─────────────────────────────────────────────────────────────────────────────

def _parse_bet_string(s):
    """
    Parse a bet description like 'NYY ML -150' or 'PHI@DET UNDER 8.0 -110'.
    Returns dict with keys: pick, market, odds (American int).
    """
    parts = s.strip().split()
    odds = None
    for i, p in enumerate(parts):
        try:
            v = int(p.replace('+',''))
            if abs(v) >= 100:
                odds = int(p); parts.pop(i); break
        except ValueError:
            pass
    market = 'Moneyline'
    for keyword in ('OVER','UNDER','K','SPREAD','RL'):
        if any(keyword.lower() in x.lower() for x in parts):
            market = 'Total' if keyword in ('OVER','UNDER') else keyword; break
    pick = ' '.join(parts)
    return {'pick': pick, 'market': market, 'odds': odds}


def _american_to_implied(o):
    o = _f(o)
    if o is None: return None
    return (-o)/(-o+100.0) if o < 0 else 100.0/(o+100.0)


def _clv_pts(open_odds, close_odds):
    """
    CLV in points: positive means you beat the closing line (good long-run signal).
    Standard formula: implied(open) - implied(close), expressed in percentage points.
    If open_implied > close_implied, you got a better number than close → positive CLV.
    """
    op = _american_to_implied(open_odds)
    cl = _american_to_implied(close_odds)
    if op is None or cl is None: return None
    return round((cl - op) * 100, 2)  # positive = you were on the right side of line move


def track_live_bet(description, stake=1.0, tag='live'):
    """
    Log a new live bet to picks_log.csv with status='open'.
    Returns the generated bet_id so the user can reference it for --close/--grade.
    """
    parsed = _parse_bet_string(description)
    bet_id = str(uuid.uuid4())[:8].upper()
    row = {
        'date': date.today().isoformat(),
        'timestamp': datetime.now().isoformat(),
        'tag': tag,
        'team': parsed['pick'],
        'pick': parsed['pick'],
        'market': parsed['market'],
        'odds': parsed['odds'],
        'open_ml': parsed['odds'],
        'model_prob': '',
        'edge_pct': '',
        'qualifies': True,
        'won': '',          # filled by --grade
        'profit_1u': '',    # filled by --grade
        'close_ml': '',     # filled by --close
        'clv_pts': '',      # computed from open vs close
        'slip_id': bet_id,  # used as reference ID for --close/--grade
        'kind': 'live_trade',
    }
    exists = os.path.exists(CSV_PATH)
    if exists:
        # Read existing cols to maintain schema consistency
        with open(CSV_PATH, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or list(row.keys())
            for col in row:
                if col not in fieldnames:
                    fieldnames.append(col)
    else:
        fieldnames = list(row.keys())

    with open(CSV_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        if not exists: writer.writeheader()
        writer.writerow(row)

    print(f"✓ Tracked bet [{bet_id}]: {description}")
    print(f"  Use --bet-id {bet_id} with --close or --grade")
    return bet_id


def close_live_bet(bet_id, close_description):
    """
    Fill in the closing line for an open bet and compute CLV.
    """
    parsed = _parse_bet_string(close_description)
    close_odds = parsed['odds']
    rows = []
    updated = False
    with open(CSV_PATH, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            if row.get('slip_id','').upper() == bet_id.upper() and row.get('kind') == 'live_trade':
                open_odds = _f(row.get('open_ml'))
                row['close_ml'] = close_odds
                row['clv_pts'] = _clv_pts(open_odds, close_odds) if open_odds else ''
                updated = True
            rows.append(row)
    if not updated:
        print(f"Bet ID {bet_id} not found or already closed."); return
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)
    clv = next((r.get('clv_pts') for r in rows if r.get('slip_id','').upper()==bet_id.upper()), '')
    print(f"✓ Closed bet [{bet_id}] at {close_description}")
    print(f"  CLV: {'+' if float(clv or 0)>=0 else ''}{clv} pts" if clv!='' else "  CLV: n/a (no open odds)")


def grade_live_bet(bet_id, result):
    """
    Grade an open live bet: result is 'won', 'loss', or 'push'.
    Computes profit_1u from the open odds and writes won/profit_1u.
    """
    result = result.lower().strip()
    if result not in ('won','win','w','loss','lose','l','push','p'):
        print("Result must be won / loss / push"); return
    won = 1 if result in ('won','win','w') else (0 if result in ('loss','lose','l') else None)
    rows = []
    updated = False
    with open(CSV_PATH, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            if row.get('slip_id','').upper() == bet_id.upper() and row.get('kind') == 'live_trade':
                odds = _f(row.get('open_ml') or row.get('odds'))
                if won is None:  # push
                    profit = 0.0; row['won'] = ''; row['profit_1u'] = 0.0
                elif won == 1:
                    profit = (odds/100) if (odds or 0)>0 else (100/abs(odds)) if odds else 0.0
                    row['won'] = 1; row['profit_1u'] = round(profit, 4)
                else:
                    row['won'] = 0; row['profit_1u'] = -1.0
                updated = True
            rows.append(row)
    if not updated:
        print(f"Bet ID {bet_id} not found."); return
    with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)
    print(f"✓ Graded bet [{bet_id}] as {result.upper()}")


def list_live_bets():
    """List all live-tracked bets (kind='live_trade') with their status."""
    if not os.path.exists(CSV_PATH):
        print("No picks_log.csv found."); return
    bets = []
    with open(CSV_PATH, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            if row.get('kind') == 'live_trade':
                bets.append(row)
    if not bets:
        print("No live trades logged yet."); return
    print(f"\n{'ID':<10} {'Date':<12} {'Pick':<24} {'Odds':>7} {'Close':>7} {'CLV':>7} {'Result':>8}")
    print("-"*75)
    for b in bets:
        won = b.get('won','')
        result = 'WON' if str(won)=='1' else ('LOSS' if str(won)=='0' else ('PUSH' if won=='' and b.get('profit_1u')=='0.0' else 'OPEN'))
        clv = b.get('clv_pts','')
        print(f"{b.get('slip_id','?'):<10} {b.get('date',''):<12} {b.get('pick','')[:24]:<24} "
              f"{b.get('open_ml',''):>7} {b.get('close_ml',''):>7} "
              f"{('+' if float(clv)>=0 else '')+clv if clv else '':>7} {result:>8}")


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS + THRESHOLD TUNING (unchanged logic from original)
# ─────────────────────────────────────────────────────────────────────────────

def _f(s, d=None):
    try: return float(str(s).strip().replace("+",""))
    except (ValueError, TypeError, AttributeError): return d

def _is_total(market):
    m = str(market).strip().lower()
    return "over" in m or "under" in m or "total" in m

def _line_from(row):
    for key in ("line","total","ou","number"):
        v = _f(row.get(key)); 
        if v is not None: return v
    for key in ("market","team","kind"):
        for tok in str(row.get(key,"")).replace("/"," ").split():
            v = _f(tok)
            if v is not None and 4.0 <= v <= 16.0: return v
    return None


def analyse(csv_path):
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            won, profit = _f(r.get("won")), _f(r.get("profit_1u"))
            market = (r.get("market") or "").strip()
            if won is None or profit is None or not market or market.lower() == "n/a":
                continue
            rows.append({
                "date": (r.get("date") or "").strip(),
                "market": market, "is_total": _is_total(market),
                "is_moneyline": "moneyline" in market.lower(),
                "line": _line_from(r),
                "open_ml": _f(r.get("open_ml")),
                "implied": _american_to_implied(r.get("open_ml")),
                "edge_pct": _f(r.get("edge_pct")),
                "model_prob": _f(r.get("model_prob")),
                "clv": _f(r.get("clv_pts")),
                "won": int(won), "profit": profit,
                "tag": r.get("tag",""),
                "slip_id": (r.get("slip_id") or "").strip(),
                "pick": (r.get("pick") or "").strip(),
                "odds": _f(r.get("odds") or r.get("open_ml")),
            })
    if not rows: return {"error": "no evaluable rows"}

    def agg(items):
        n = len(items)
        if not n: return None
        return {"bets": n, "wins": sum(i["won"] for i in items),
                "win_rate": sum(i["won"] for i in items)/n,
                "profit": sum(i["profit"] for i in items),
                "roi": sum(i["profit"] for i in items)/n}

    overall = agg(rows)
    totals  = [r for r in rows if r["is_total"]]
    moneylines = [r for r in rows if r["is_moneyline"]]
    live_trades = [r for r in rows if r["tag"] == "live"]

    bucket = defaultdict(list)
    for r in rows:
        bucket["Total" if r["is_total"] else "Other"].append(r)
    by_market = {k: agg(v) for k, v in bucket.items()}

    edge_buckets = defaultdict(list)
    real_edge_n = proxy_edge_n = 0
    for r in totals:
        if r["edge_pct"] is not None:
            d = abs(r["edge_pct"]) / 100.0; real_edge_n += 1
        elif r["implied"] is not None:
            d = abs(r["implied"] - 0.5); proxy_edge_n += 1
        else:
            edge_buckets["unknown"].append(r); continue
        key = "tight (<5%)" if d<0.05 else ("mid (5-10%)" if d<0.10 else "wide (>10%)")
        edge_buckets[key].append(r)
    by_edge = {k: agg(v) for k, v in edge_buckets.items()}
    edge_source = {"real": real_edge_n, "proxy": proxy_edge_n}

    line_bands = defaultdict(list)
    for r in totals:
        if r["line"] is None: continue
        band = "low (<7.5)" if r["line"]<7.5 else ("mid (7.5-9)" if r["line"]<=9.0 else "high (>9)")
        line_bands[band].append(r)
    by_line = {k: agg(v) for k, v in line_bands.items()}

    clv_rows = [r for r in rows if r["clv"] is not None]
    clv = None
    if clv_rows:
        clv = {"n": len(clv_rows),
               "avg": sum(r["clv"] for r in clv_rows)/len(clv_rows),
               "pct_positive": sum(1 for r in clv_rows if r["clv"]>0)/len(clv_rows)}

    calibration = compute_calibration(rows)
    parlays = compute_parlay_analysis(rows)

    return {"overall": overall, "totals": agg(totals), "moneylines": agg(moneylines),
            "by_market": by_market,
            "by_edge": by_edge, "edge_source": edge_source, "by_line": by_line,
            "clv": clv, "live_trades": agg(live_trades) if live_trades else None,
            "live_trades_n": len(live_trades),
            "calibration": calibration,
            "parlays": parlays,
            "_totals_rows": totals}


def compute_parlay_analysis(rows):
    """
    Real parlay-level (all-or-nothing) results, grouped by slip_id — as
    opposed to per-leg win rate, which hides the actual failure mode a
    parlay has: a 12-leg ticket where 11 legs individually won still
    returns exactly $0 if even one leg lost. Per-leg win rate on that
    same ticket would report ~92% win rate, which is a true but
    misleading number for judging whether placing that TICKET was a
    good idea.

    A "slip" here is any group of graded rows sharing a non-empty
    slip_id — currently only rows logged by mlb_ace.py's Paste Slip
    import (tag='pasted_slip') carry one, since those are actual single
    tickets where win/loss is fundamentally coupled across legs. Rows
    with no slip_id (most auto/manual single-bet rows) are single-leg
    "parlays" of size 1 and are correctly excluded from this — grouping
    them would just reproduce the single-bet numbers already shown
    elsewhere under a different label.
    """
    by_slip = defaultdict(list)
    for r in rows:
        if r["slip_id"]:
            by_slip[r["slip_id"]].append(r)
    if not by_slip:
        return {"n_slips": 0, "slips": []}

    slip_results = []
    for slip_id, legs in by_slip.items():
        n_legs = len(legs)
        n_won = sum(1 for l in legs if l["won"] == 1)
        all_won = all(l["won"] == 1 for l in legs)
        # Combined naive win probability from each leg's own implied prob,
        # for comparison against what actually happened — same math as the
        # browser-side pre-download banner, computed here from the
        # ALREADY-GRADED legs so it's a real post-hoc check, not a preview.
        implied_probs = [_american_to_implied(l["odds"]) for l in legs if l["odds"] is not None]
        naive_prob = None
        if implied_probs:
            naive_prob = 1.0
            for p in implied_probs:
                naive_prob *= p
        slip_results.append({
            "slip_id": slip_id, "n_legs": n_legs, "n_legs_won": n_won,
            "all_legs_won": all_won, "naive_win_prob": naive_prob,
            "date": legs[0]["date"],
        })

    n_slips = len(slip_results)
    n_slips_won = sum(1 for s in slip_results if s["all_legs_won"])
    avg_legs = sum(s["n_legs"] for s in slip_results) / n_slips
    avg_naive_prob = None
    with_prob = [s for s in slip_results if s["naive_win_prob"] is not None]
    if with_prob:
        avg_naive_prob = sum(s["naive_win_prob"] for s in with_prob) / len(with_prob)

    return {
        "n_slips": n_slips,
        "n_slips_won": n_slips_won,
        "slip_win_rate": n_slips_won / n_slips,
        "avg_legs_per_slip": avg_legs,
        "avg_naive_win_prob": avg_naive_prob,
        "slips": slip_results,
    }


def compute_calibration(rows):
    """
    The single most important diagnostic for a probability model: does a
    pick the model calls "65%" actually win about 65% of the time? A model
    can have a positive-looking ROI on a small sample purely from favorable
    odds/variance while still being badly miscalibrated — this checks the
    model's own stated confidence against what actually happened, which
    nothing else in this report does.

    Only rows with a real model_prob are used (no proxy/estimate — a
    calibration check is meaningless if the "prediction" being graded isn't
    the model's own actual output). Historically most logged rows predate
    model_prob being written at all; this will fill in and become
    trustworthy as new tag=auto picks accumulate going forward.
    """
    have_prob = [r for r in rows if r["model_prob"] is not None]
    n_missing = len(rows) - len(have_prob)
    if len(have_prob) < 10:
        return {"n": len(have_prob), "n_missing_prob": n_missing, "buckets": [],
                "insufficient": True}

    # Bucket by predicted probability decile-ish bands. model_prob is stored
    # as the probability of the SIDE ACTUALLY PICKED (not home/away), so
    # "won" directly means "the predicted side won" — no sign-flipping needed.
    bands = [(0.50,0.55),(0.55,0.60),(0.60,0.65),(0.65,0.70),(0.70,0.75),(0.75,0.80),(0.80,1.01)]
    out = []
    for lo, hi in bands:
        grp = [r for r in have_prob if lo <= r["model_prob"]/100.0 < hi]
        if not grp: continue
        actual_wr = sum(r["won"] for r in grp) / len(grp)
        predicted_wr = sum(r["model_prob"]/100.0 for r in grp) / len(grp)
        out.append({
            "band": f"{int(lo*100)}-{int(hi*100)}%",
            "n": len(grp),
            "predicted_wr": predicted_wr,
            "actual_wr": actual_wr,
            "gap": actual_wr - predicted_wr,  # negative = overconfident, positive = underconfident
        })
    # Brier score: mean squared error between predicted prob and actual
    # outcome (0/1). Lower is better; 0.25 is what a coin-flip model scores;
    # a well-calibrated, genuinely informative model should be meaningfully
    # below that.
    brier = sum((r["model_prob"]/100.0 - r["won"])**2 for r in have_prob) / len(have_prob)
    return {"n": len(have_prob), "n_missing_prob": n_missing, "buckets": out,
            "brier_score": brier, "insufficient": False}


def tune_config(analysis):
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH) as f:
            cur = json.load(f)
        for k in DEFAULTS:
            if k in cur: cfg[k] = cur[k]
    except Exception: pass

    totals = analysis.get("totals")
    notes = []
    if not totals or totals["bets"] < MIN_BETS_TO_TUNE:
        notes.append("only %s graded totals — keeping defaults (need %d)" %
                     (totals["bets"] if totals else 0, MIN_BETS_TO_TUNE))
        return cfg, notes

    be = analysis["by_edge"]
    tight = be.get("tight (<5%)"); wide = be.get("wide (>10%)")
    new_edge = cfg["edge_threshold"]
    if tight and tight["bets"]>=8 and tight["roi"]<-0.03:
        new_edge += 0.01
        notes.append("tight-edge totals losing (ROI %+.1f%%, n=%d) -> raise edge to %.1f%%"
                     % (100*tight["roi"], tight["bets"], 100*new_edge))
    elif wide and wide["bets"]>=8 and wide["roi"]>0.08 and new_edge>EDGE_MIN+0.005:
        new_edge -= 0.005
        notes.append("wide-edge totals strong (ROI %+.1f%%, n=%d) -> lower edge to %.1f%%"
                     % (100*wide["roi"], wide["bets"], 100*new_edge))
    cfg["edge_threshold"] = round(min(EDGE_MAX, max(EDGE_MIN, new_edge)), 4)

    bl = analysis["by_line"]
    low, high = bl.get("low (<7.5)"), bl.get("high (>9)")
    prev_min, prev_max = cfg["min_total_line"], cfg["max_total_line"]
    new_min, new_max = DEFAULTS["min_total_line"], DEFAULTS["max_total_line"]
    if low and low["bets"]>=8 and low["roi"]<-0.05:
        new_min = max(new_min, 7.5)
        notes.append("low totals (<7.5) losing (ROI %+.1f%%, n=%d) -> min_total_line=7.5"
                     % (100*low["roi"], low["bets"]))
    if high and high["bets"]>=8 and high["roi"]<-0.05:
        new_max = min(new_max, 9.0)
        notes.append("high totals (>9) losing (ROI %+.1f%%, n=%d) -> max_total_line=9.0"
                     % (100*high["roi"], high["bets"]))
    cfg["min_total_line"] = round(max(LINE_FLOOR, new_min), 1)
    cfg["max_total_line"] = round(min(LINE_CEIL, new_max), 1)

    if cfg["max_total_line"] > prev_max:
        notes.append("restoring max_total_line=%.1f (was %.1f)" % (cfg["max_total_line"], prev_max))
    if cfg["min_total_line"] < prev_min:
        notes.append("restoring min_total_line=%.1f (was %.1f)" % (cfg["min_total_line"], prev_min))
    if cfg["min_total_line"] > cfg["max_total_line"]:
        old_min, old_max = cfg["min_total_line"], cfg["max_total_line"]
        cfg["min_total_line"] = DEFAULTS["min_total_line"]
        cfg["max_total_line"] = DEFAULTS["max_total_line"]
        notes.append("min/max inverted (%.1f > %.1f) — reset to defaults" % (old_min, old_max))

    if not notes: notes.append("results within tolerance — thresholds unchanged")
    return cfg, notes


def _pct(v): return "%.1f%%" % (100*v) if v is not None else "n/a"
def _roi(v): return "%+.1f%%" % (100*v) if v is not None else "n/a"

def print_report(a, cfg, notes, wrote):
    if "error" in a: print("ERROR:", a["error"]); return
    W = 58
    o = a["overall"]
    print("="*W)
    print("MLB BACKTEST  —  %s" % date.today().isoformat())
    print("="*W)
    print("  Graded bets : %d   (win %s)" % (o["bets"], _pct(o["win_rate"])))
    print("  Total P&L   : %+.2f u" % o["profit"])
    print("  Overall ROI : %s" % _roi(o["roi"]))
    if a["totals"]:
        t = a["totals"]
        print("  Totals only : %d bets, win %s, ROI %s"
              % (t["bets"], _pct(t["win_rate"]), _roi(t["roi"])))
    if a.get("moneylines"):
        m = a["moneylines"]
        print("  Moneyline   : %d bets, win %s, ROI %s"
              % (m["bets"], _pct(m["win_rate"]), _roi(m["roi"])))

    if a.get("live_trades"):
        lt = a["live_trades"]
        print("  Live trades : %d bets, win %s, ROI %s"
              % (lt["bets"], _pct(lt["win_rate"]), _roi(lt["roi"])))

    print("\n-- TOTALS BY EDGE BUCKET " + "-"*(W-25))
    es = a.get("edge_source") or {}
    if es.get("real") or es.get("proxy"):
        print("  (edge source: %d real, %d proxy-estimated)" % (es.get("real",0), es.get("proxy",0)))
    for k in ("tight (<5%)","mid (5-10%)","wide (>10%)","unknown"):
        b = a["by_edge"].get(k)
        if b: print("  %-13s %3d bets  win %s  ROI %s" % (k, b["bets"], _pct(b["win_rate"]), _roi(b["roi"])))

    print("\n-- TOTALS BY LINE BAND " + "-"*(W-23))
    for k in ("low (<7.5)","mid (7.5-9)","high (>9)"):
        b = a["by_line"].get(k)
        if b: print("  %-13s %3d bets  win %s  ROI %s" % (k, b["bets"], _pct(b["win_rate"]), _roi(b["roi"])))

    if a["clv"]:
        c = a["clv"]
        print("\n-- CLV " + "-"*(W-7))
        print("  n=%d  avg %+.2f pts  positive %s" % (c["n"], c["avg"], _pct(c["pct_positive"])))

    cal = a.get("calibration")
    if cal:
        print("\n-- MODEL CALIBRATION " + "-"*(W-21))
        if cal.get("insufficient"):
            print("  Only %d graded picks have a recorded model_prob (need 10+)." % cal["n"])
            print("  %d graded rows predate model_prob being logged and are excluded." % cal.get("n_missing_prob", 0))
            print("  This fills in automatically as new tag=auto picks get graded.")
        else:
            print("  n=%d picks with recorded confidence (%d older rows lack it, excluded)"
                  % (cal["n"], cal.get("n_missing_prob", 0)))
            print("  Brier score: %.3f  (0.25 = coin flip, lower = better)" % cal["brier_score"])
            print("  %-10s %6s %12s %12s %8s" % ("band", "n", "predicted", "actual", "gap"))
            for b in cal["buckets"]:
                flag = "  <- overconfident" if b["gap"] < -0.08 else ("  <- underconfident" if b["gap"] > 0.08 else "")
                print("  %-10s %6d %11s %11s %+7.1f%%%s"
                      % (b["band"], b["n"], _pct(b["predicted_wr"]), _pct(b["actual_wr"]), 100*b["gap"], flag))

    par = a.get("parlays")
    if par and par["n_slips"]:
        print("\n-- PARLAY RESULTS (all-or-nothing, by slip) " + "-"*(W-45))
        print("  n=%d graded slip(s) (from Paste Slip imports), avg %.1f legs/slip"
              % (par["n_slips"], par["avg_legs_per_slip"]))
        print("  Slip win rate  : %s  (%d of %d slips had EVERY leg win)"
              % (_pct(par["slip_win_rate"]), par["n_slips_won"], par["n_slips"]))
        if par["avg_naive_win_prob"] is not None:
            print("  Avg pre-bet combined win prob (naive, independent legs): %s"
                  % _pct(par["avg_naive_win_prob"]))
            print("  This is per-leg win rate reframed as a TICKET result — a slip where")
            print("  most legs individually won but one didn't still counts as a loss here,")
            print("  same as it did on the actual payout.")
        if par["n_slips"] <= 10:
            print("  %-12s %6s %8s %10s" % ("slip", "legs", "won", "result"))
            for s in par["slips"]:
                result = "ALL WON" if s["all_legs_won"] else f"{s['n_legs_won']}/{s['n_legs']} won"
                print("  %-12s %6d %8s %10s" % (s["slip_id"][:12], s["n_legs"], s["date"], result))

    print("\n-- TUNED THRESHOLDS " + "-"*(W-20))
    print("  edge_threshold : %.1f%%" % (100*cfg["edge_threshold"]))
    print("  total line band: %.1f - %.1f" % (cfg["min_total_line"], cfg["max_total_line"]))
    for n in notes: print("    - " + n)
    print("  %s" % ("WROTE mlb_config.json" if wrote else "dry-run (config not written)"))
    print("="*W)


def main(argv):
    dry = "--dry-run" in argv
    as_json = "--json" in argv

    # Live trade subcommands
    if "--track" in argv:
        idx = argv.index("--track")
        desc = argv[idx+1] if idx+1<len(argv) else ""
        stake = float(argv[argv.index("--stake")+1]) if "--stake" in argv else 1.0
        track_live_bet(desc, stake); return

    if "--close" in argv:
        idx = argv.index("--close"); close_desc = argv[idx+1] if idx+1<len(argv) else ""
        bid = argv[argv.index("--bet-id")+1] if "--bet-id" in argv else ""
        if not bid: print("--close requires --bet-id <id>"); return
        close_live_bet(bid, close_desc); return

    if "--grade" in argv:
        idx = argv.index("--grade"); result = argv[idx+1] if idx+1<len(argv) else ""
        bid = argv[argv.index("--bet-id")+1] if "--bet-id" in argv else ""
        if not bid: print("--grade requires --bet-id <id>"); return
        grade_live_bet(bid, result); return

    if "--list" in argv:
        list_live_bets(); return

    paths = [a for a in argv if not a.startswith("--")]
    csv_path = paths[0] if paths else CSV_PATH
    if not os.path.exists(csv_path):
        print("picks_log.csv not found at", csv_path); sys.exit(1)

    a = analyse(csv_path)
    if "error" in a:
        print(json.dumps(a) if as_json else "ERROR: "+a["error"]); return
    cfg, notes = tune_config(a)

    wrote = False
    if not dry:
        try:
            out = dict(cfg)
            out["_basis"] = "%d graded totals, ROI %s (auto-tuned %s)" % (
                a["totals"]["bets"] if a["totals"] else 0,
                _roi(a["totals"]["roi"]) if a["totals"] else "n/a",
                date.today().isoformat())
            out["_updated"] = date.today().isoformat()
            with open(CONFIG_PATH,"w") as f: json.dump(out,f,indent=2)
            wrote = True
        except Exception as e:
            notes.append("could not write config: %s" % e)

    if as_json:
        a.pop("_totals_rows", None)
        print(json.dumps({"analysis":a,"config":cfg,"notes":notes,"wrote":wrote},indent=2,default=str))
    else:
        print_report(a, cfg, notes, wrote)


if __name__ == "__main__":
    main(sys.argv[1:])
