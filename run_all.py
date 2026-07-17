"""
run_all.py — single-command workflow for ParlayOS's three prediction
engines (mlb_ace.py, nfl_ace.py, nba_ace.py).

WHY THIS EXISTS INSTEAD OF ONE MERGED FILE:
mlb_ace.py, nfl_ace.py, and nba_ace.py each define their own TEAM_ABBR,
STADIUM_LOCATIONS, CACHE_DIR, PICKS_LOG_PATH, load_config(), run(),
export_to_html(), and several other same-named things — with genuinely
different content in every case (30 MLB teams vs 32 NFL teams vs 30 NBA
teams; three different stat models; three different log schemas).
Concatenating the three files into one would mean whichever definition
loads last silently overwrites the earlier two in the shared namespace —
no error, no warning, just every earlier engine's fetch functions quietly
looking up team names in the WRONG sport's dictionary. This script instead
imports all three as separate modules (Python already namespaces
mlb_ace.TEAM_ABBR vs nfl_ace.TEAM_ABBR correctly) and calls each one's own
run() function in sequence — same one-command outcome, zero collision
risk, and no logic inside any engine had to change to get here.

USAGE:
    python3 run_all.py

Runs MLB, then NFL, then NBA, each writing into the same ParlayOS HTML
file (auto-detected the same way each engine already does: parlayos.html,
parlayos_2.html, ParlayOS.html, or parlayos_v6.html, first match, in this
script's own directory).

FAILURE ISOLATION:
Each engine runs inside its own try/except. If one sport's API key is
missing, its data source is down, or any other exception occurs partway
through, that failure is printed clearly and the script moves on to the
next sport rather than stopping entirely — a bad NFL run shouldn't cost
you the MLB and NBA picks that would otherwise have worked fine. A
summary at the end reports exactly which sports succeeded and which
didn't, so a partial failure is visible, not silent.
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _find_html_template():
    """Same candidate list every engine already uses individually — found
    ONCE here and handed explicitly to all three run() calls, rather than
    each engine re-resolving it independently at import time (which
    happens to agree today since they all check the same directory, but
    isn't guaranteed to stay that way, and doing it once here makes the
    'all three definitely wrote to the same file' guarantee explicit
    rather than incidental)."""
    candidates = ["parlayos.html", "parlayos_2.html", "ParlayOS.html", "parlayos_v6.html"]
    for c in candidates:
        p = os.path.join(HERE, c)
        if os.path.exists(p):
            return p
    return None


def _run_one(label, module_name):
    """Import and run a single engine, isolated from the others. Returns
    (label, success: bool, picks_or_None, error_or_None)."""
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    try:
        module = __import__(module_name)
    except Exception as e:
        print(f"✗ {label}: FAILED TO IMPORT — {e}")
        traceback.print_exc()
        return (label, False, None, str(e))

    html_path = _find_html_template()
    if html_path is None:
        msg = ("No ParlayOS HTML template found (looked for parlayos.html, "
               "parlayos_2.html, ParlayOS.html, parlayos_v6.html in "
               f"{HERE}) — {label} skipped.")
        print(f"✗ {label}: {msg}")
        return (label, False, None, msg)

    try:
        picks = module.run(html_path)
        qualifying = sum(1 for p in (picks or []) if p.get("qualifies"))
        print(f"✓ {label}: {len(picks or [])} games, {qualifying} qualifying")
        return (label, True, picks, None)
    except Exception as e:
        print(f"✗ {label}: FAILED DURING RUN — {e}")
        traceback.print_exc()
        return (label, False, None, str(e))


def main():
    html_path = _find_html_template()
    if html_path is None:
        print("No ParlayOS HTML template found in this directory. "
              "Looked for: parlayos.html, parlayos_2.html, ParlayOS.html, "
              "parlayos_v6.html")
        print("Nothing to do — place one of those files next to run_all.py "
              "and try again.")
        sys.exit(1)
    print(f"Target HTML file for all three engines: {html_path}")

    results = []
    # Order matters only in the sense that each engine's own console
    # output stays grouped and readable — MLB, NFL, NBA have no runtime
    # dependency on each other and could run in any order without
    # changing the outcome.
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
            print(f"  ✓ {label}: {len(picks or [])} games, {qualifying} qualifying")
        else:
            any_failed = True
            print(f"  ✗ {label}: FAILED — {error}")

    if any_failed:
        print("\nOne or more engines failed — see the per-sport output above "
              "for the specific error. The engines that succeeded still "
              "wrote their picks; this is a partial run, not a total failure.")
        sys.exit(1)
    else:
        print(f"\nAll three engines completed successfully → {html_path}")


if __name__ == "__main__":
    main()
