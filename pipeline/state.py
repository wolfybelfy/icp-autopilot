"""Atomic JSON state store + time-window helpers. No COM, no network."""
import json, os, shutil
from datetime import datetime, timedelta
from pathlib import Path

def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()

def today():
    return datetime.now().strftime("%Y-%m-%d")

def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default

def save_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)

def backup_state(state_dir, today_str):
    """Copy state/*.json to state/backup/<date>/ once per date. True if performed."""
    sd = Path(state_dir)
    dest = sd / "backup" / today_str
    if dest.exists():
        return False
    dest.mkdir(parents=True)
    for f in sd.glob("*.json"):
        shutil.copy2(f, dest / f.name)
    return True

def count_in_window(timestamps, days, now=None):
    ref = datetime.fromisoformat(now) if now else datetime.now()
    cutoff = ref - timedelta(days=days)
    return sum(1 for t in timestamps if datetime.fromisoformat(t) > cutoff)

def prune_daily(counts, keep_days=8, today_str=None):
    ref = datetime.strptime(today_str or today(), "%Y-%m-%d")
    cutoff = (ref - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    for k in [k for k in counts if k < cutoff]:
        del counts[k]
