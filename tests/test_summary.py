from pipeline import summary, state
from tests.test_send import FakeMailer, make_root

def test_summary_sends_once_per_day(tmp_path):
    root, cfg = make_root(tmp_path)
    state.save_json(root / "state" / "send_log.json",
                    {"a@b.com": {"status": "confirmed"}, "c@d.com": {"status": "unconfirmed"}})
    m = FakeMailer()
    assert summary.maybe_send_summary(root, cfg, m) is True
    assert summary.maybe_send_summary(root, cfg, m) is False
    assert len(m.sent) == 1 and m.sent[0]["to"] == cfg["addresses"]["summary_to"]
    assert "ICP Autopilot" in m.sent[0]["subject"]

def test_summary_mentions_unconfirmed(tmp_path):
    root, cfg = make_root(tmp_path)
    state.save_json(root / "state" / "send_log.json", {"c@d.com": {"status": "unconfirmed"}})
    assert "UNCONFIRMED" in summary.build_summary(root)
