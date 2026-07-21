"""Diagnose why approval replies aren't being processed. READ-ONLY - changes nothing.

Run on the machine that runs ticks, from the repo root:
    python scripts\\debug_inbox.py

Prints every inbox message from the last 2 days and, for each, exactly which
approval check passes or fails (token found / token pending / sender is an
approver / parsed verdict). One of these will name the bug.
"""
import json, sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import state
from pipeline.approvals import Approvals, find_token, parse_verdict
from pipeline.outlook import Outlook

def main():
    root = Path(__file__).resolve().parents[1]
    cfg = json.loads((root / "config" / "config.json").read_text(encoding="utf-8"))
    approvers = {a.lower() for a in cfg["addresses"]["approver_addresses"]}
    approvals = Approvals(root / "state" / "approvals.json")
    scan = state.load_json(root / "state" / "inbox_scan.json", {})

    print("approver_addresses:", sorted(approvers))
    print("inbox_scan watermark:", scan.get("since", "<none>"))
    print("approvals on file:")
    for t, r in approvals.data.items():
        print(f"  [#{t}] status={r['status']} recipient={r['recipient']}"
              f" requested_at={r['requested_at']}")
    pending = approvals.pending()
    print("pending tokens:", sorted(pending) if pending else "<none>")

    since = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    print(f"\n--- Outlook inbox_since({since}) ---")
    msgs = Outlook().inbox_since(since)
    print(f"{len(msgs)} message(s) visible to the scanner\n")
    for m in msgs:
        token = find_token(m["subject"])
        first = next((l for l in (m["body"] or "").splitlines() if l.strip()), "")
        checks = []
        if token is None:
            checks.append("NO_TOKEN_IN_SUBJECT")
        elif token in pending:
            checks.append(f"token_[#{token}]_pending_ok")
        else:
            st = approvals.data.get(token, {}).get("status", "unknown-token")
            checks.append(f"TOKEN_[#{token}]_NOT_PENDING(status={st})")
        checks.append("approver_ok" if m["sender"] in approvers
                      else f"NOT_APPROVER(sender={m['sender']!r})")
        checks.append("verdict=" + parse_verdict(m["body"]))
        print(f"* {m['received']} | {m['sender']} | subject={m['subject'][:70]!r}")
        print(f"    first body line: {first[:70]!r}")
        print(f"    -> {', '.join(checks)}\n")

if __name__ == "__main__":
    main()
