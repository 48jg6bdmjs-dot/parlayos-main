"""
run_all.py â€” Orchestrates all ACE predictors + live scores
- Runs mlb_ace, nfl_ace, nba_ace, live_scores_fetcher
- Ensures HTML gets all data even if one fails
- Used by GitHub Actions
"""

import subprocess, sys
from pathlib import Path
from datetime import datetime

HERE = Path(__file__).parent

def run_script(name):
    path = HERE / name
    if not path.exists():
        print(f"âš  {name} not found, skipping")
        return False
    try:
        print(f"\n=== Running {name} ===")
        result = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=120)
        print(result.stdout)
        if result.stderr:
            print(f"STDERR: {result.stderr[:1000]}")
        return result.returncode == 0
    except Exception as e:
        print(f"âœ— Failed to run {name}: {e}")
        return False

if __name__ == "__main__":
    print(f"=== ParlayOS Run All - {datetime.now()} ===")
    results = {}
    for script in ["mlb_ace.py", "nfl_ace.py", "nba_ace.py", "live_scores_fetcher.py"]:
        results[script] = run_script(script)
    
    print("\n=== Summary ===")
    for k,v in results.items():
        status = "âœ“" if v else "âœ—"
        print(f"{status} {k}: {'OK' if v else 'FAILED'}")
    
    # Verify HTML has data
    html_files = [HERE / "parlayos_3.html", HERE / "parlayos.html"]
    for hf in html_files:
        if hf.exists():
            text = hf.read_text(encoding='utf-8', errors='ignore')
            has_mlb = "PARLAYOS_DATA" in text
            has_nfl = "PARLAYOS_NFL_DATA" in text
            has_nba = "PARLAYOS_NBA_DATA" in text
            has_live = "PARLAYOS_LIVE_SCORES" in text
            print(f"\n{ hf.name } check: MLB={has_mlb} NFL={has_nfl} NBA={has_nba} LIVE={has_live}")
    
    print("\nDone - HTML should now have all predictions")
