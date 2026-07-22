"""Deterministic ICP gate. Company fit = frozen icp_core; person fit = icp_persona."""
import argparse, json, re, sys
try:
    from pipeline import icp_core, icp_persona
except ImportError:            # invoked as a script from repo root
    import icp_core, icp_persona

# A company in a NON-tech industry still qualifies on industry if it owns its OWN
# software / platform / AI product (operator rule 2026-07-22). Detected from the
# company's description / business model / keywords when those are supplied.
PRODUCT_SIGNAL = ["platform", "software", "saas", " api ", "developer tool",
                  "artificial intelligence", "machine learning", "proprietary software",
                  "own software", "cloud platform", "mobile app", "web app",
                  "ai product", "ml platform", "data platform"]


def _has_product_signal(company):
    blob = " ".join(str(company.get(k) or "") for k in
                     ("description", "business_model", "businessModel", "tagline")).lower()
    kw = company.get("keywords")
    if isinstance(kw, (list, tuple)):
        blob += " " + " ".join(str(x) for x in kw).lower()
    elif kw:
        blob += " " + str(kw).lower()
    return bool(blob.strip()) and any(s in blob for s in PRODUCT_SIGNAL)


def evaluate(company):
    ind_all = [c for c in (company.get("raw_classifications") or []) if c]
    if _has_product_signal(company):
        # feed the frozen icp_core a synthetic tech classification so a non-tech company
        # with its own product qualifies on industry, without touching icp_core.
        ind_all = ind_all + ["proprietary software platform"]
    emp = icp_core.min_employees(company.get("employee_range"), company.get("employees"))
    rounds = [r or "" for r in (company.get("funding_rounds") or [])]
    has_round = any(re.search(r"series\s*[a-f]\b", r.lower()) for r in rounds)
    recent = rounds[0] if rounds else ""
    _, _, _, is_icp, qual, reason = icp_core.icp_eval(ind_all, emp, has_round, recent)
    return {"is_icp": is_icp, "qualification": qual, "reason": reason}


def evaluate_person(person):
    """Persona gate (marketing Manager+ / product Senior+). See icp_persona."""
    return icp_persona.person_fit(person)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="path to JSON; stdin if omitted")
    ap.add_argument("--person", action="store_true",
                    help="evaluate a PERSON record {title, job_function, management_level} "
                         "instead of a company")
    args = ap.parse_args()
    raw = open(args.json, encoding="utf-8").read() if args.json else sys.stdin.read()
    rec = json.loads(raw)
    print(json.dumps(evaluate_person(rec) if args.person else evaluate(rec)))


if __name__ == "__main__":
    main()
