import json
from pathlib import Path
from pipeline.send import Sender
from tests.test_gates import good_draft

class FakeMailer:
    def __init__(self):
        self.sent = []
    def send(self, to, subject, body_text, html_body=None, bcc=None):
        self.sent.append({"to": to, "subject": subject, "body": body_text, "bcc": bcc})
        return subject
    def inbox_since(self, ts):
        return []

def make_root(tmp_path, mode="review", dry_run=False):
    cfg = json.loads(Path("config/config.json").read_text(encoding="utf-8"))
    cfg["mode"] = mode
    cfg["safety"]["dry_run"] = dry_run
    cfg["sender"] = {"name": "Uday", "title": "T", "postal_address": "A"}
    for d in ("state", "drafts/inbox", "drafts/sent", "drafts/rejected", "drafts/invalid", "config"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    for f in ("email_template.txt", "email_template.html", "suppression.txt"):
        (tmp_path / "config" / f).write_text(Path("config", f).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path, cfg

def write_draft(root, d=None):
    d = d or good_draft()
    p = root / "drafts" / "inbox" / f"{d['visitor_id']}.json"
    p.write_text(json.dumps(d))
    return p

def test_review_mode_requests_approval(tmp_path):
    root, cfg = make_root(tmp_path)
    m = FakeMailer()
    s = Sender(root, cfg, m, verify_url=lambda u: True)
    out = s.route_draft(write_draft(root))
    assert out.startswith("approval_requested:")
    token = out.split(":")[1]
    assert f"[#{token}]" in m.sent[0]["subject"]
    assert m.sent[0]["to"] == cfg["addresses"]["reviewer_notify"]
    assert "Reply GOOD to send" in m.sent[0]["body"]
    # draft renamed to .pending.json so next tick can't re-route it
    assert (root / "drafts" / "inbox" / "v1.pending.json").exists()
    assert not (root / "drafts" / "inbox" / "v1.json").exists()

def test_auto_mode_sends_with_bcc_and_dedup(tmp_path):
    root, cfg = make_root(tmp_path, mode="auto")
    m = FakeMailer()
    s = Sender(root, cfg, m, verify_url=lambda u: True)
    assert s.route_draft(write_draft(root)) == "sent"
    assert m.sent[0]["to"] == "jane@acme.com" and m.sent[0]["bcc"] == cfg["addresses"]["audit_bcc"]
    d2 = good_draft(); d2["visitor_id"] = "v2"
    assert s.route_draft(write_draft(root, d2)).startswith("gated:")

def test_dry_run_blocks_send_but_allows_approval_request(tmp_path):
    root, cfg = make_root(tmp_path, mode="auto", dry_run=True)
    m = FakeMailer()
    s = Sender(root, cfg, m, verify_url=lambda u: True)
    assert s.route_draft(write_draft(root)) == "dry_run"
    root2, cfg2 = make_root(tmp_path / "b", mode="review", dry_run=True)
    m2 = FakeMailer()
    s2 = Sender(root2, cfg2, m2, verify_url=lambda u: True)
    assert s2.route_draft(write_draft(root2)).startswith("approval_requested:")

def test_invalid_draft_moved(tmp_path):
    root, cfg = make_root(tmp_path)
    p = root / "drafts" / "inbox" / "bad.json"
    p.write_text("{not json")
    s = Sender(root, cfg, FakeMailer(), verify_url=lambda u: True)
    assert s.route_draft(p) == "invalid"
    assert not p.exists() and (root / "drafts" / "invalid" / "bad.json").exists()

def test_send_failure_leaves_unconfirmed_never_resends(tmp_path):
    root, cfg = make_root(tmp_path, mode="auto")
    class Boom(FakeMailer):
        def send(self, *a, **k):
            raise RuntimeError("COM down")
    s = Sender(root, cfg, Boom(), verify_url=lambda u: True)
    out = s.route_draft(write_draft(root))
    assert out.startswith("error:")
    log = json.loads((root / "state" / "send_log.json").read_text())
    assert log["jane@acme.com"]["status"] == "unconfirmed"
    d2 = good_draft(); d2["visitor_id"] = "v3"
    assert s.route_draft(write_draft(root, d2)).startswith("gated:")
