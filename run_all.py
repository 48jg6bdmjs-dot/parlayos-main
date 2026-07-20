"""
run_all.py ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â single-command workflow for ParlayOS (parlayos.html only)
Runs MLB, NFL, NBA into the single parlayos.html file in repo.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

def _find_html_template():
    """Only parlayos.html exists in repo"""
    p = os.path.join(HERE, "parlayos.html")
    if os.path.exists(p):
        return p
    p2 = os.path.join(HERE, "index.html")
    if os.path.exists(p2):
        return p2
    return None

def _run_one(label, module_name):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    try:
        module = __import__(module_name)
        import importlib
        importlib.reload(module)
    except Exception as e:
        print(f"X {label}: FAILED TO IMPORT - {e}")
        traceback.print_exc()
        return (label, False, None, str(e))

    html_path = _find_html_template()
    if html_path is None:
        msg = f"No parlayos.html found in {HERE} - {label} skipped."
        print(f"X {label}: {msg}")
        return (label, False, None, msg)

    try:
        picks = module.run(html_path)
        qualifying = sum(1 for p in (picks or []) if p.get("qualifies"))
        print(f"OK {label}: {len(picks or [])} games, {qualifying} qualifying -> {os.path.basename(html_path)}")
        return (label, True, picks, None)
    except Exception as e:
        print(f"X {label}: FAILED - {e}")
        traceback.print_exc()
        return (label, False, None, str(e))

def main():
    html_path = _find_html_template()
    if html_path is None:
        print("No parlayos.html found. Place parlayos.html next to run_all.py")
        sys.exit(1)
    print(f"Target: {html_path}")

    results = []
    results.append(_run_one("MLB (mlb_ace.py)", "mlb_ace"))
    results.append(_run_one("NFL (nfl_ace.py)", "nfl_ace"))
    results.append(_run_one("NBA (nba_ace.py)", "nba_ace"))

    print(f"\n{'='*70}")
    print("  SUMMARY")
    print(f"{'='*70}")
    any_failed = False
    for label, success, picks, error in results:
        if success:
            qualifying = sum(1 for p in (picks or []) if p.get("qualifies"))
            print(f"  OK {label}: {len(picks or [])} games, {qualifying} qualifying")
        else:
            any_failed = True
            print(f"  X {label}: FAILED - {error}")

    if any_failed:
        sys.exit(1)
    else:
        print(f"\nAll three done -> {html_path}")

if __name__ == "__main__":
    main()
