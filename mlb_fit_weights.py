#!/usr/bin/env python3
"""
================================================================================
 mlb_fit_weights.py  —  Fit model weights against real graded outcomes
================================================================================
 WHAT THIS ACTUALLY DOES TODAY
 ------------------------------
 picks_log.csv stores the model's FINAL combined probability/edge per pick,
 not the individual edge-term components (pitcher_fip_edge, team_edge,
 season_form_edge, etc.) that were summed to produce it. That means a true
 per-factor logistic regression — fitting a separate weight for FIP vs team
 form vs bullpen vs everything else — is not honestly possible from today's
 log. Anything claiming to do that from this data would be fitting noise.

 What IS honestly fittable today: whether the market's OWN implied
 probability is itself well-calibrated against what actually happened
 (Platt scaling — a standard, legitimate technique). This directly targets
 the real, measured problem (moneylines losing money) using data that
 genuinely exists, rather than dressing up a fit around data that doesn't.

 WHAT THIS SETS UP FOR THE FUTURE
 ----------------------------------
 mlb_ace.py now logs each individual edge-term value alongside every
 auto-generated pick (see EDGE_COMPONENT_COLS in mlb_ace.py and the
 corresponding write in export logic). Once enough NEW picks accumulate
 with those columns populated and graded (won/profit_1u filled in), this
 script's fit_full_model() will have real per-factor data to regress
 against, and can fit an actual replacement weight for each edge term
 instead of hand-set constants. --status reports exactly how much of that
 data exists right now so it's never ambiguous which mode ran.

 Run
 ---
   python3 mlb_fit_weights.py --status        # how much fittable data exists
   python3 mlb_fit_weights.py --calibrate      # fit + report Platt scaling on market_prob
   python3 mlb_fit_weights.py --full           # attempt full multi-factor fit (once ready)
================================================================================
"""
import csv, json, os, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "picks_log.csv")
CALIBRATION_PATH = os.path.join(HERE, "mlb_calibration.json")

MIN_FOR_CALIBRATION = 100   # Platt scaling needs a reasonable sample to not overfit 2 params
MIN_FOR_FULL_FIT = 150      # per-factor regression needs more, given ~14 factors

# The individual edge-term columns mlb_ace.py now logs per auto-generated
# pick (see mirrored list in mlb_ace.py — EDGE_COMPONENT_COLS). Kept here too
# so this script can check availability without importing mlb_ace.py.
EDGE_COMPONENT_COLS = [
    "c_team_edge", "c_pitcher_fip_edge", "c_pitcher_era_edge", "c_pitcher_whip_edge",
    "c_pitcher_k9_edge", "c_offense_edge", "c_bullpen_edge", "c_season_form_edge",
    "c_h2h_edge", "c_weather_edge", "c_rest_edge", "c_lineup_edge",
    "c_injury_edge", "c_fatigue_edge",
]


def _f(s, d=None):
    try: return float(str(s).strip().replace("+", ""))
    except (ValueError, TypeError, AttributeError): return d


def _american_to_implied(o):
    o = _f(o)
    if o is None: return None
    return (-o)/(-o+100.0) if o < 0 else 100.0/(o+100.0)


def load_graded_moneylines(csv_path):
    """Every graded (won + odds present) moneyline row, plus whichever edge
    component columns happen to be present (older rows will have none)."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        has_component_cols = reader.fieldnames and any(c in reader.fieldnames for c in EDGE_COMPONENT_COLS)
        for r in reader:
            won = _f(r.get("won"))
            odds = r.get("odds") or r.get("open_ml")
            market = (r.get("market") or "").strip().lower()
            if won is None or not odds or "moneyline" not in market:
                continue
            implied = _american_to_implied(odds)
            if implied is None:
                continue
            row = {"implied": implied, "won": int(won), "model_prob": _f(r.get("model_prob"))}
            for c in EDGE_COMPONENT_COLS:
                row[c] = _f(r.get(c))
            rows.append(row)
    return rows, has_component_cols


def status(argv):
    rows, has_cols = load_graded_moneylines(CSV_PATH)
    n_total = len(rows)
    n_with_components = sum(1 for r in rows if all(r.get(c) is not None for c in EDGE_COMPONENT_COLS))
    print("=" * 60)
    print("FIT-READINESS STATUS")
    print("=" * 60)
    print(f"  Graded moneyline rows (odds + won present) : {n_total}")
    print(f"  ...of those, with full edge-component data : {n_with_components}")
    print()
    if n_total >= MIN_FOR_CALIBRATION:
        print(f"  ✓ Calibration fit (market_prob Platt scaling): READY (n={n_total} >= {MIN_FOR_CALIBRATION})")
    else:
        print(f"  ✗ Calibration fit: need {MIN_FOR_CALIBRATION - n_total} more graded rows (have {n_total})")
    if n_with_components >= MIN_FOR_FULL_FIT:
        print(f"  ✓ Full multi-factor fit: READY (n={n_with_components} >= {MIN_FOR_FULL_FIT})")
    else:
        need = MIN_FOR_FULL_FIT - n_with_components
        print(f"  ✗ Full multi-factor fit: need {need} more graded rows WITH edge-component data")
        if not has_cols:
            print("    (no rows have edge-component columns yet — these only exist on picks")
            print("     generated by the current mlb_ace.py; older rows predate this)")
    print("=" * 60)


def fit_calibration(argv):
    """
    Platt scaling: fit actual_win ~ sigmoid(a * logit(market_implied_prob) + b)
    on real graded outcomes. This tells us whether the market's own number
    (which the model already partially trusts via market_prob's 0.15 weight
    in calculate_win_probability) is itself running hot/cold on the games
    this system actually bets, and by how much.
    """
    rows, _ = load_graded_moneylines(CSV_PATH)
    n = len(rows)
    if n < MIN_FOR_CALIBRATION:
        print(f"Only {n} graded moneyline rows — need {MIN_FOR_CALIBRATION}+ to fit without overfitting.")
        print("Run --status for the full picture. Not writing a calibration file.")
        return

    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        print("This fit requires numpy + scikit-learn. Install with:")
        print("  pip install numpy scikit-learn --break-system-packages")
        return

    eps = 1e-4
    implied = np.array([[min(max(r["implied"], eps), 1 - eps)] for r in rows])
    y = np.array([r["won"] for r in rows])
    logit_implied = np.log(implied / (1 - implied))

    clf = LogisticRegression()
    clf.fit(logit_implied, y)
    a, b = float(clf.coef_[0][0]), float(clf.intercept_[0])

    mean_implied = float(implied.mean())
    actual_wr = float(y.mean())
    gap = actual_wr - mean_implied

    print("=" * 60)
    print("CALIBRATION FIT — market-implied probability vs reality")
    print("=" * 60)
    print(f"  n = {n} graded moneyline bets")
    print(f"  Mean market-implied win prob : {mean_implied*100:.1f}%")
    print(f"  Actual win rate              : {actual_wr*100:.1f}%")
    print(f"  Gap                          : {gap*100:+.1f} points"
          f"  ({'market running HOT — picks are landing on prices that don' + chr(39) + 't hold up' if gap < -0.02 else 'market running cold' if gap > 0.02 else 'roughly in line'})")
    print(f"  Platt scale factor  a = {a:.4f}  (1.0 = no rescaling needed)")
    print(f"  Platt offset        b = {b:+.4f}  (0.0 = no offset needed)")
    print()
    print("  To apply: recalibrated_prob = sigmoid(a * logit(market_prob) + b)")
    print("  This does NOT change mlb_config.json or mlb_ace.py automatically —")
    print("  reviewing the fit before wiring it into the live model is intentional.")

    out = {
        "fitted_on": date.today().isoformat(),
        "n": n,
        "mean_implied": mean_implied,
        "actual_win_rate": actual_wr,
        "platt_a": a,
        "platt_b": b,
        "note": "Applies to market_prob only. Recompute as more graded picks accumulate — "
                "this is a snapshot fit, not a permanent constant.",
    }
    with open(CALIBRATION_PATH, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Wrote {CALIBRATION_PATH}")
    print("=" * 60)


def fit_full_model(argv):
    """
    True multi-factor logistic regression: fit a weight for EACH edge
    component (pitcher_fip_edge, team_edge, season_form_edge, etc.)
    against real graded outcomes, rather than the hand-set constants
    currently in calculate_win_probability.

    Gated behind a real sample-size check — this does NOT run on
    insufficient data and silently produce fitted-sounding numbers that
    are actually just noise from a 14-feature regression on a handful of
    rows.
    """
    rows, has_cols = load_graded_moneylines(CSV_PATH)
    usable = [r for r in rows if all(r.get(c) is not None for c in EDGE_COMPONENT_COLS)]
    n = len(usable)
    if n < MIN_FOR_FULL_FIT:
        print(f"Only {n} graded rows have full edge-component data — need {MIN_FOR_FULL_FIT}+.")
        print("This data only exists on picks generated by the current mlb_ace.py")
        print("(see EDGE_COMPONENT_COLS logging). Run mlb_ace.py to generate picks,")
        print("grade them (won/profit_1u), then re-run this once enough accumulate.")
        print("\nRun --status to track progress toward this threshold.")
        return

    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except ImportError:
        print("This fit requires numpy + scikit-learn. Install with:")
        print("  pip install numpy scikit-learn --break-system-packages")
        return

    X = np.array([[r[c] for c in EDGE_COMPONENT_COLS] for r in usable])
    y = np.array([r["won"] for r in usable])

    clf = LogisticRegression(max_iter=2000)
    clf.fit(X, y)

    print("=" * 60)
    print("FULL MULTI-FACTOR FIT")
    print("=" * 60)
    print(f"  n = {n} graded picks with full edge-component data")
    print(f"  {'factor':<24} {'current weight (approx)':>24} {'fitted weight':>14}")
    for i, col in enumerate(EDGE_COMPONENT_COLS):
        print(f"  {col:<24} {'—':>24} {clf.coef_[0][i]:>14.4f}")
    print()
    print("  Review before manually updating the corresponding weight constants")
    print("  in mlb_ace.py's calculate_win_probability — this script does not")
    print("  edit that file automatically.")
    print("=" * 60)


def main(argv):
    if "--status" in argv or not argv:
        status(argv)
    elif "--calibrate" in argv:
        fit_calibration(argv)
    elif "--full" in argv:
        fit_full_model(argv)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
