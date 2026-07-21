"""Operator tool: requeue a visitor for a fresh end-to-end pipeline pass.

Usage: python scripts/requeue.py <email-or-visitor-id-substring>

Removes the visitor from state/seen.json, purges their (possibly poisoned)
entries from state/enrich_cache.json, deletes any matching retry file, and
resets state/backfill.json so the backlog drain re-encounters them within a
few ticks. send_log.json and approvals.json are never touched - dedup and
approval history survive a requeue.
"""
import json
import sys
import time
from pathlib import Path


def _load(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def requeue(root, needle):
    root = Path(root)
    needle = needle.strip().lower()
    if len(needle) < 4:
        raise ValueError("needle too short - refusing to mass-match seen.json")
    result = {"seen_removed": [], "cache_purged": [], "retry_deleted": []}

    seen_p = root / "state" / "seen.json"
    seen = _load(seen_p, {})
    result["seen_removed"] = [k for k in seen if needle in k.lower()]
    for k in result["seen_removed"]:
        del seen[k]
    if result["seen_removed"]:
        seen_p.write_text(json.dumps(seen, indent=2), encoding="utf-8")

    cache_p = root / "state" / "enrich_cache.json"
    cache = _load(cache_p, {})
    result["cache_purged"] = [k for k, v in cache.items()
                              if needle in k.lower() or needle in json.dumps(v).lower()]
    for k in result["cache_purged"]:
        del cache[k]
    if result["cache_purged"]:
        cache_p.write_text(json.dumps(cache, indent=2), encoding="utf-8")

    inbox = root / "drafts" / "inbox"
    if inbox.is_dir():
        for f in inbox.glob("*.retry.json"):
            if needle in f.name.lower() or needle in f.read_text(encoding="utf-8").lower():
                f.unlink()
                result["retry_deleted"].append(f.name)

    bf_p = root / "state" / "backfill.json"
    bf_p.write_text(json.dumps({"offset": 0, "done": False}), encoding="utf-8")
    return result


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    root = Path(__file__).resolve().parents[1]
    lock = root / "state" / "tick.lock"
    if lock.exists() and (time.time() - lock.stat().st_mtime) < 15 * 60:
        print("WARNING: a tick appears to be running right now (state/tick.lock is fresh).")
        print("State edits may race with it - safest is to re-run between ticks.")
    try:
        r = requeue(root, argv[1])
    except ValueError as e:
        print(f"ERROR: {e}")
        return 2
    print(f"seen.json: removed {r['seen_removed'] or 'nothing'}")
    print(f"enrich_cache.json: purged {r['cache_purged'] or 'nothing'}")
    print(f"retry files: deleted {r['retry_deleted'] or 'nothing'}")
    print('backfill.json: reset to {"offset": 0, "done": false} - drain re-sweeps from newest')
    if not any(r.values()):
        print("WARNING: nothing matched - check the spelling/id")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
