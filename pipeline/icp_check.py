"""Deterministic ICP gate over raw classification data. Thin wrapper around icp_core."""
import argparse, json, re, sys
try:
    from pipeline import icp_core
except ImportError:            # invoked as a script from repo root
    import icp_core

def evaluate(company):
    ind_all = [c for c in (company.get("raw_classifications") or []) if c]
    emp = icp_core.min_employees(company.get("employee_range"), company.get("employees"))
    rounds = [r or "" for r in (company.get("funding_rounds") or [])]
    has_round = any(re.search(r"series\s*[a-f]\b", r.lower()) for r in rounds)
    recent = rounds[0] if rounds else ""
    _, _, _, is_icp, qual, reason = icp_core.icp_eval(ind_all, emp, has_round, recent)
    return {"is_icp": is_icp, "qualification": qual, "reason": reason}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="path to company JSON; stdin if omitted")
    args = ap.parse_args()
    raw = open(args.json, encoding="utf-8").read() if args.json else sys.stdin.read()
    print(json.dumps(evaluate(json.loads(raw))))

if __name__ == "__main__":
    main()
