"""Deterministic pre/post phases around the claude run. CLI entry for run.ps1."""
import argparse, json, sys
from pathlib import Path
from pipeline import state
from pipeline.approvals import find_token, parse_verdict
from pipeline.send import Sender

def _load_cfg(root):
    return json.loads((Path(root) / "config" / "config.json").read_text(encoding="utf-8"))

def phase_pre(root, cfg, mailer, verify_url, send_summary=None):
    root = Path(root)
    if (root / "STOP").exists():
        return {"halted": True}
    sender = Sender(root, cfg, mailer, verify_url)
    res = {"approvals_processed": 0, "sent": 0, "expired": 0, "unsubscribes": 0,
           "ignored_strangers": 0}
    scan_p = root / "state" / "inbox_scan.json"
    watermark = state.load_json(scan_p, {}).get("since", "2000-01-01T00:00:00")
    msgs = mailer.inbox_since(watermark)
    approvers = {a.lower() for a in cfg["addresses"]["approver_addresses"]}
    for msg in msgs:
        body = msg.get("body", "") or ""
        top = body.strip().lower().splitlines()[0] if body.strip() else ""
        if "unsubscribe" in top or "unsubscribe" in msg["subject"].lower():
            supp = root / "config" / "suppression.txt"
            existing = supp.read_text(encoding="utf-8") if supp.exists() else ""
            if msg["sender"] and msg["sender"] not in existing:
                supp.write_text(existing.rstrip("\n") + f"\n{msg['sender']}\n", encoding="utf-8")
                res["unsubscribes"] += 1
            continue
        token = find_token(msg["subject"])
        if not token or token not in sender.approvals.pending():
            continue
        if msg["sender"] not in approvers:
            res["ignored_strangers"] += 1          # can never approve; surfaced in counters
            continue
        verdict = parse_verdict(body)
        if verdict == "hold":
            continue
        res["approvals_processed"] += 1
        rec = sender.approvals.data[token]
        sender.approvals.decide(token, verdict, msg["sender"])
        draft_path = Path(rec["draft_path"])
        if verdict == "rejected":
            if draft_path.exists():
                sender._move(draft_path, "rejected")
            continue
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        out = sender.send_prospect(draft, draft_path, token=token)
        if out == "sent":
            sender.approvals.consume(token)
            res["sent"] += 1
    expired = sender.approvals.expire_older_than(cfg["approval_expiry_hours"])
    res["expired"] = len(expired)
    for t in expired:                               # tidy expired drafts out of inbox
        p = Path(sender.approvals.data[t]["draft_path"])
        if p.exists():
            sender._move(p, "rejected")
    state.save_json(scan_p, {"since": state.now_iso()})
    if send_summary:
        send_summary(root, cfg, mailer)
    hb = state.load_json(root / "state" / "heartbeat.json", {})
    hb["pre"] = state.now_iso()
    state.save_json(root / "state" / "heartbeat.json", hb)
    state.backup_state(root / "state", state.today())
    return res

def phase_post(root, cfg, mailer, verify_url):
    root = Path(root)
    if (root / "STOP").exists():
        return {"halted": True}
    sender = Sender(root, cfg, mailer, verify_url)
    res = {"drafts_routed": 0, "statuses": []}
    for p in sorted((root / "drafts" / "inbox").glob("*.json")):
        if p.name.endswith((".pending.json", ".retry.json")):
            continue
        status = sender.route_draft(p)
        res["drafts_routed"] += 1
        res["statuses"].append({p.name: status})
    hb = state.load_json(root / "state" / "heartbeat.json", {})
    hb["post"] = state.now_iso()
    state.save_json(root / "state" / "heartbeat.json", hb)
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=["pre", "post"])
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    cfg = _load_cfg(root)
    from pipeline.outlook import Outlook, verify_url
    from pipeline.summary import maybe_send_summary
    mailer = Outlook()
    if args.phase == "pre":
        out = phase_pre(root, cfg, mailer, verify_url, send_summary=maybe_send_summary)
    else:
        out = phase_post(root, cfg, mailer, verify_url)
    print(json.dumps(out))
    return 0

if __name__ == "__main__":
    sys.exit(main())
