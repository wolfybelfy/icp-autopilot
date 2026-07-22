"""Spare-PC smoke: default (dry) runs a fixture draft through routing with a fake mailer
(no COM); --send sends ONE real email to the operator's own address via Outlook."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # allow `python pipeline\smoke_test.py`
from pipeline.send import Sender
from pipeline import state

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = {
    "visitor_id": "smoke-1", "detected_at": "",
    "person": {"full_name": "Smoke Test", "first_name": "Smoke",
               "email": "", "title": "VP Marketing", "seniority": "VP Level Exec", "job_function": "Marketing"},
    "company": {"name": "SmokeCo", "domain": "", "country": "US",
                "raw_classifications": ["Software"], "employees": 5000, "funding_rounds": []},
    "visit": {"pages": ["/pricing"], "last_seen": ""},
    "email": {"subject": "Smoke test - ICP Autopilot", "body_paragraphs":
              ["This is the smoke test.", "If you can read this, rendering works."]},
    "sources": [], "enrichment": {"gaps": []},
    "enrich": {"provider": "smoke", "match_level": "FULL_MATCH"},
}

class EchoMailer:
    def send(self, to, subject, body_text, html_body=None, bcc=None):
        print(f"[dry] would send to={to} bcc={bcc} subject={subject!r}")
        return subject
    def inbox_since(self, ts):
        return []

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true",
                    help="ONE real email to the operator's own address via Outlook COM")
    args = ap.parse_args()
    cfg = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    me = cfg["addresses"]["sender_mailbox"]
    d = json.loads(json.dumps(FIXTURE))
    d["detected_at"] = d["visit"]["last_seen"] = state.now_iso()
    d["person"]["email"] = me
    d["company"]["domain"] = me.split("@")[-1]
    p = ROOT / "drafts" / "inbox" / "smoke-1.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    try:
        if args.send:
            from pipeline.outlook import Outlook, verify_url
            cfg2 = json.loads(json.dumps(cfg))
            cfg2["mode"] = "auto"
            cfg2["safety"]["dry_run"] = False
            s = Sender(ROOT, cfg2, Outlook(), verify_url)
        else:
            s = Sender(ROOT, cfg, EchoMailer(), verify_url=lambda u: True)
        out = s.route_draft(p)
        print("smoke result:", out)
    finally:
        # cleanup ALWAYS runs - a crash mid-smoke (e.g. COM failure) must never leave the
        # fixture draft behind for a real tick to pick up and request approval on.
        log_p = ROOT / "state" / "send_log.json"
        log = state.load_json(log_p, {})
        if log.pop(me.lower(), None) is not None:
            state.save_json(log_p, log)
        appr_p = ROOT / "state" / "approvals.json"
        appr = state.load_json(appr_p, {})
        stale = [t for t, r in appr.items() if r.get("recipient") == me.lower()]
        for t in stale:
            del appr[t]
        if stale:
            state.save_json(appr_p, appr)
        for sub in ("inbox", "sent", "rejected", "invalid"):
            for f in (ROOT / "drafts" / sub).glob("smoke-1*.json"):
                f.unlink()
    ok = (out == "sent") if args.send else out.startswith(("approval_requested", "dry_run", "gated"))
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
