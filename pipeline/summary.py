"""Once-daily operator summary. Silent failure is the enemy — surface everything."""
from pathlib import Path
from pipeline import state

def build_summary(root):
    root = Path(root)
    log = state.load_json(root / "state" / "send_log.json", {})
    appr = state.load_json(root / "state" / "approvals.json", {})
    hb = state.load_json(root / "state" / "heartbeat.json", {})
    lines = [f"ICP Autopilot daily summary - {state.today()}", ""]
    by = lambda st: sum(1 for r in log.values() if r.get("status") == st)
    lines.append(f"Sends confirmed: {by('confirmed')}   reserved: {by('reserved')}")
    if by("unconfirmed"):
        lines.append(f"*** UNCONFIRMED SENDS (human reconcile needed, never auto-resent): {by('unconfirmed')} ***")
        lines += [f"  - {e}" for e, r in log.items() if r.get("status") == "unconfirmed"]
    st = lambda s: sum(1 for r in appr.values() if r["status"] == s)
    lines.append(f"Approvals - pending: {st('pending')}  approved: {st('approved')}  "
                 f"rejected: {st('rejected')}  expired: {st('expired')}  consumed: {st('consumed')}")
    if st("approved"):
        lines.append("*** APPROVED BUT NOT SENT (gated at send time - check logs) ***")
    for sub in ("inbox", "sent", "rejected", "invalid"):
        n = len(list((root / "drafts" / sub).glob("*.json")))
        lines.append(f"drafts/{sub}: {n}")
    lines.append(f"Heartbeat - pre: {hb.get('pre', 'never')}  post: {hb.get('post', 'never')}")
    return "\n".join(lines)

def maybe_send_summary(root, cfg, mailer):
    root = Path(root)
    hb_p = root / "state" / "heartbeat.json"
    hb = state.load_json(hb_p, {})
    if hb.get("last_summary") == state.today():
        return False
    mailer.send(cfg["addresses"]["summary_to"],
                f"ICP Autopilot summary {state.today()}", build_summary(root))
    hb["last_summary"] = state.today()
    state.save_json(hb_p, hb)
    return True
