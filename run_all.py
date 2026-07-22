import os, sys, traceback, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

def _find_html_template():
    for name in ["parlayos_transparent_v8.html","parlayos_transparent_v7.html","parlayos.html","index.html"]:
        p=os.path.join(HERE,name)
        if os.path.exists(p):
            return p
    return None

def _run_one(label, module_name):
    print(f"\n{'='*70}\n  {label}\n{'='*70}")
    try:
        module=__import__(module_name)
        import importlib
        importlib.reload(module)
    except Exception as e:
        print(f"X {label}: FAILED IMPORT - {e}")
        traceback.print_exc()
        return (label,False,None,str(e))
    html_path=_find_html_template()
    if not html_path:
        msg="No html template found"
        print(msg)
        return (label,False,None,msg)
    try:
        picks=module.run(html_path)
        qual=sum(1 for p in (picks or []) if p.get("qualifies"))
        print(f"OK {label}: {len(picks or [])} games, {qual} qualify")
        return (label,True,picks,None)
    except Exception as e:
        print(f"X {label}: FAILED - {e}")
        traceback.print_exc()
        return (label,False,None,str(e))

def _auto_calibrate():
    # Auto-run calibration if enough graded picks
    for fit_script, log_file in [("mlb_fit_weights.py","picks_log.csv"), ("nfl_fit_weights.py","nfl_picks_log.csv"), ("nba_fit_weights.py","nba_picks_log.csv")]:
        try:
            log_path=os.path.join(HERE,log_file)
            if not os.path.exists(log_path):
                continue
            # count lines
            with open(log_path) as f:
                n=sum(1 for _ in f)-1
            if n>=60:
                print(f"\nAuto-calibrating {fit_script} (n={n})...")
                os.system(f"python {os.path.join(HERE,fit_script)} --calibrate --auto")
        except Exception as e:
            print(f"Auto-calibrate {fit_script} failed: {e}")

def main():
    html_path=_find_html_template()
    if not html_path:
        print("No html template found")
        sys.exit(1)
    print(f"Target: {html_path}")
    results=[]
    results.append(_run_one("MLB (mlb_ace.py)","mlb_ace"))
    results.append(_run_one("NFL (nfl_ace.py)","nfl_ace"))
    results.append(_run_one("NBA (nba_ace.py)","nba_ace"))
    _auto_calibrate()
    print("\n"+"="*70+"\n SUMMARY\n"+"="*70)
    for label,ok,picks,err in results:
        if ok:
            q=sum(1 for p in (picks or []) if p.get("qualifies"))
            print(f"  OK {label}: {len(picks or [])} games, {q} qualify")
        else:
            print(f"  X {label}: {err}")

if __name__=="__main__":
    main()
