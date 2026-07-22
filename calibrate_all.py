#!/usr/bin/env python3
"""
calibrate_all.py - Run calibration for all leagues with proper reporting
"""
import os, subprocess, json
HERE=os.path.dirname(os.path.abspath(__file__))
for league, fit_file, cal_file in [
    ("MLB","mlb_fit_weights.py","mlb_calibration.json"),
    ("NFL","nfl_fit_weights.py","nfl_calibration.json"),
    ("NBA","nba_fit_weights.py","nba_calibration.json"),
]:
    print(f"\n{'='*60}\n {league} CALIBRATION\n{'='*60}")
    fit_path=os.path.join(HERE,fit_file)
    if not os.path.exists(fit_path):
        print(f"  Skip - {fit_file} not found")
        continue
    subprocess.run(["python", fit_path, "--status"])
    # Try calibrate
    subprocess.run(["python", fit_path, "--calibrate"])
    # Show result
    cal_path=os.path.join(HERE,cal_file)
    if os.path.exists(cal_path):
        with open(cal_path) as f:
            data=json.load(f)
        print(f"  -> {cal_file}: n={data.get('n')} mean={data.get('mean_implied',0)*100:.1f}% actual={data.get('actual_win_rate',0)*100:.1f}% a={data.get('platt_a')} b={data.get('platt_b')}")

print("\nDone. Now rerun run_all.py to use new calibration.")
