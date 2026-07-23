"""Seed ONE realistic draft addressed to the operator's OWN inbox, then exit.

Unlike smoke_test.py (which sends a dummy email immediately), this leaves a real,
personalized draft for the NORMAL review pipeline. The operator then runs the tick,
gets the real approval email in their own inbox, and replies GOOD/NO - exercising the
full human-in-the-loop path with no Claude step, no external recipient, and no config
change (dry_run stays on; the approval email is sent regardless, the prospect send is
not). Re-runnable: clears its own prior test artifacts first.

Run on the spare PC (Outlook open):
    python pipeline/seed_test_draft.py          # drop the draft
    python pipeline/tick.py --phase post        # -> approval email to your inbox
    (reply GOOD or NO to that email in Outlook)
    python pipeline/tick.py --phase pre         # applies your reply
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import state

ROOT = Path(__file__).resolve().parents[1]
VID = "test-approval-1"


def main():
    cfg = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    me = cfg["addresses"]["sender_mailbox"]
    dom = me.split("@")[-1]

    # make the test repeatable: wipe any prior run's traces for THIS test only
    for sub in ("inbox", "sent", "rejected", "invalid"):
        for f in (ROOT / "drafts" / sub).glob(VID + "*.json"):
            f.unlink()
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

    now = state.now_iso()
    draft = {
        "visitor_id": VID,
        "detected_at": now,
        "person": {
            "full_name": "Test Prospect", "first_name": "Test",
            "email": me, "title": "VP of Marketing",
            "seniority": "VP Level Exec", "job_function": "Marketing",
        },
        "company": {
            "name": "Approval Test Co", "domain": dom, "country": "US",
            "raw_classifications": ["Software"], "employees": 5000, "funding_rounds": [],
        },
        "visit": {"pages": ["/pricing", "/product"], "last_seen": now},
        "email": {
            "subject": "Quick idea for your Q3 pipeline goals",
            "body_paragraphs": [
                "Hi Test,",
                "Most marketing leaders I speak with are trying to squeeze more pipeline "
                "out of the same budget heading into Q3.",
                "We help B2B marketing teams turn anonymous website traffic into "
                "qualified, ready-to-contact leads automatically - no extra headcount.",
                "Worth a 15-minute look? Happy to share how a couple of teams your size "
                "are running it.",
            ],
        },
        "sources": [],
        "enrichment": {"gaps": []},
        "enrich": {"provider": "seed_test", "match_level": "FULL_MATCH"},
    }
    p = ROOT / "drafts" / "inbox" / (VID + ".json")
    p.write_text(json.dumps(draft, indent=2), encoding="utf-8")
    print("seeded draft ->", p)
    print("recipient is YOUR OWN inbox:", me)
    print("next: python pipeline/tick.py --phase post   (sends the approval email to you)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
