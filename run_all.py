"""
run_all.py â€” ACE V3 ULTRA Orchestrator
Runs MLB + NBA + NFL with highlights, parallel, unified injection.
"""
import os, sys
from datetime import datetime
HERE = os.path.dirname(os.path.abspath(__file__))

def find_template():
    for c in ["parlayos.html","index.html","parlayos_v6.html","parlayos_2.html"]:
        p=os.path.join(HERE,c)
        if os.path.exists(p): return p
    return None

def main():
    html_path=find_template()
    if not html_path:
        print("No template found"); return
    print(f"=== ACE V3 ULTRA RUN {datetime.now()} ===")
    print(f"Template: {html_path}")
    try:
        import mlb_ace
        print("\n--- MLB V3 ULTRA ---")
        mlb_games=mlb_ace.run(html_path)
        print(f"MLB done: {len(mlb_games)}")
    except Exception as e:
        import traceback; traceback.print_exc()
        mlb_games=[]
    try:
        import nba_ace
        print("\n--- NBA V3 ULTRA ---")
        nba_games=nba_ace.run(html_path)
        print(f"NBA done: {len(nba_games)}")
    except Exception as e:
        import traceback; traceback.print_exc()
        nba_games=[]
    try:
        import nfl_ace
        print("\n--- NFL V3 ULTRA ---")
        nfl_games=nfl_ace.run(html_path)
        print(f"NFL done: {len(nfl_games)}")
    except Exception as e:
        import traceback; traceback.print_exc()
        nfl_games=[]
    total=len(mlb_games)+len(nba_games)+len(nfl_games)
    print(f"\n=== SUMMARY V3 ULTRA ===")
    print(f"MLB:{len(mlb_games)} NBA:{len(nba_games)} NFL:{len(nfl_games)} TOTAL:{total}")
    print("Highlights: MLB Content API + ESPN scoreboard videos")
    print("Odds: Multi-book consensus Pinnacle 2.5x, Circa 1.8x")
    print("Model: Bayesian ensemble market+stats, Monte Carlo totals, Weather V3 wind vector")

if __name__=="__main__":
    main()
