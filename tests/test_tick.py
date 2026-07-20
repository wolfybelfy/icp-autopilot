from pathlib import Path
from pipeline import tick
from pipeline.send import Sender
from tests.test_send import FakeMailer, make_root, write_draft

def approved_reply(token, sender="upawar@unboundia.com", body="GOOD"):
    return {"subject": f"RE: Approval [#{token}] - Jane", "sender": sender,
            "body": body, "received": "2026-07-20T12:00:00"}

class FakeInboxMailer(FakeMailer):
    def __init__(self, msgs):
        super().__init__()
        self.msgs = msgs
    def inbox_since(self, ts):
        return self.msgs

def test_full_approval_roundtrip(tmp_path):
    root, cfg = make_root(tmp_path)                       # review mode, dry_run False
    m = FakeInboxMailer([])
    s = Sender(root, cfg, m, verify_url=lambda u: True)
    out = s.route_draft(write_draft(root))
    token = out.split(":")[1]
    m.msgs = [approved_reply(token)]
    r = tick.phase_pre(root, cfg, m, verify_url=lambda u: True)
    assert r["sent"] == 1
    assert any(x["to"] == "jane@acme.com" for x in m.sent)
    # duplicate GOOD is a no-op
    r2 = tick.phase_pre(root, cfg, m, verify_url=lambda u: True)
    assert r2["sent"] == 0

def test_reply_from_stranger_ignored(tmp_path):
    root, cfg = make_root(tmp_path)
    m = FakeInboxMailer([])
    s = Sender(root, cfg, m, verify_url=lambda u: True)
    token = s.route_draft(write_draft(root)).split(":")[1]
    m.msgs = [approved_reply(token, sender="attacker@evil.com")]
    r = tick.phase_pre(root, cfg, m, verify_url=lambda u: True)
    assert r["sent"] == 0 and r["ignored_strangers"] == 1

def test_rejection_moves_draft(tmp_path):
    root, cfg = make_root(tmp_path)
    m = FakeInboxMailer([])
    s = Sender(root, cfg, m, verify_url=lambda u: True)
    token = s.route_draft(write_draft(root)).split(":")[1]
    m.msgs = [approved_reply(token, body="NO")]
    tick.phase_pre(root, cfg, m, verify_url=lambda u: True)
    assert list((root / "drafts" / "rejected").glob("*.json"))

def test_unsubscribe_appends_suppression(tmp_path):
    root, cfg = make_root(tmp_path)
    m = FakeInboxMailer([{"subject": "unsubscribe", "sender": "jane@acme.com",
                          "body": "unsubscribe", "received": "2026-07-20T12:00:00"}])
    tick.phase_pre(root, cfg, m, verify_url=lambda u: True)
    assert "jane@acme.com" in (root / "config" / "suppression.txt").read_text()

def test_stop_file_halts_pre(tmp_path):
    root, cfg = make_root(tmp_path)
    (root / "STOP").write_text("")
    m = FakeInboxMailer([approved_reply("AAAAAA")])
    assert tick.phase_pre(root, cfg, m, verify_url=lambda u: True) == {"halted": True}

def test_phase_post_routes_inbox_and_skips_pending(tmp_path):
    root, cfg = make_root(tmp_path)
    write_draft(root)
    (root / "drafts" / "inbox" / "x.pending.json").write_text("{}")
    (root / "drafts" / "inbox" / "y.retry.json").write_text("{}")
    m = FakeInboxMailer([])
    r = tick.phase_post(root, cfg, m, verify_url=lambda u: True)
    assert r["drafts_routed"] == 1
