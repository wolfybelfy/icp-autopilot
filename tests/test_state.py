import json
from pipeline import state

def test_save_is_atomic_and_roundtrips(tmp_path):
    p = tmp_path / "x.json"
    state.save_json(p, {"a": 1})
    assert state.load_json(p, {}) == {"a": 1}
    assert not list(tmp_path.glob("*.tmp"))

def test_load_missing_returns_default(tmp_path):
    assert state.load_json(tmp_path / "nope.json", {"d": True}) == {"d": True}

def test_backup_once_per_day(tmp_path):
    sd = tmp_path / "state"; sd.mkdir()
    state.save_json(sd / "a.json", {"x": 1})
    assert state.backup_state(sd, "2026-07-20") is True
    assert state.backup_state(sd, "2026-07-20") is False
    assert json.loads((sd / "backup" / "2026-07-20" / "a.json").read_text()) == {"x": 1}

def test_count_in_window():
    ts = ["2026-07-14T10:00:00", "2026-07-19T10:00:00", "2026-07-20T09:00:00"]
    assert state.count_in_window(ts, days=7, now="2026-07-20T12:00:00") == 2

def test_prune_daily():
    counts = {"2026-07-01": 5, "2026-07-19": 2, "2026-07-20": 1}
    state.prune_daily(counts, keep_days=8, today_str="2026-07-20")
    assert "2026-07-01" not in counts and counts["2026-07-19"] == 2
