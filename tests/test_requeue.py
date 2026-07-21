import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from requeue import requeue  # noqa: E402


def _setup(root):
    (root / "state").mkdir()
    (root / "drafts" / "inbox").mkdir(parents=True)
    (root / "state" / "seen.json").write_text(json.dumps({
        "k.morrison@f5.com": {"status": "parked", "reason": "E1", "at": "2026-07-21T01:00:00Z"},
        "other@example.com": {"status": "non_icp", "reason": "x", "at": "2026-07-21T01:00:00Z"},
    }), encoding="utf-8")
    (root / "state" / "enrich_cache.json").write_text(json.dumps({
        "person:k.morrison@f5.com": {"miss": True, "ttl_days": 7},
        "company:f5.com": {"employees": 6500},
        "person:other@example.com": {"miss": True},
    }), encoding="utf-8")
    (root / "drafts" / "inbox" / "k.morrison@f5.com.retry.json").write_text(
        json.dumps({"attempts": 12, "visitor": {"email": "k.morrison@f5.com"}}), encoding="utf-8")
    (root / "drafts" / "inbox" / "keeper.retry.json").write_text(
        json.dumps({"attempts": 1, "visitor": {"email": "keeper@x.com"}}), encoding="utf-8")
    (root / "state" / "backfill.json").write_text(json.dumps({"offset": 60, "done": False}),
                                                  encoding="utf-8")


def test_requeue_clears_exactly_the_target(tmp_path):
    _setup(tmp_path)
    r = requeue(tmp_path, "k.morrison@f5.com")
    seen = json.loads((tmp_path / "state" / "seen.json").read_text(encoding="utf-8"))
    cache = json.loads((tmp_path / "state" / "enrich_cache.json").read_text(encoding="utf-8"))
    assert "k.morrison@f5.com" not in seen and "other@example.com" in seen
    # the poisoned person-miss AND any cache value mentioning the email are purged;
    # unrelated entries survive
    assert "person:k.morrison@f5.com" not in cache
    assert "company:f5.com" in cache and "person:other@example.com" in cache
    assert not (tmp_path / "drafts" / "inbox" / "k.morrison@f5.com.retry.json").exists()
    assert (tmp_path / "drafts" / "inbox" / "keeper.retry.json").exists()
    bf = json.loads((tmp_path / "state" / "backfill.json").read_text(encoding="utf-8"))
    assert bf == {"offset": 0, "done": False}
    assert r["seen_removed"] == ["k.morrison@f5.com"]


def test_requeue_refuses_short_needles(tmp_path):
    _setup(tmp_path)
    try:
        requeue(tmp_path, "f5")
    except ValueError:
        pass
    else:
        raise AssertionError("short needle must raise, not mass-delete")


def test_requeue_survives_missing_files(tmp_path):
    (tmp_path / "state").mkdir()
    r = requeue(tmp_path, "nobody@nowhere.com")
    assert r == {"seen_removed": [], "cache_purged": [], "retry_deleted": []}
    assert json.loads((tmp_path / "state" / "backfill.json").read_text(encoding="utf-8")) == \
        {"offset": 0, "done": False}
