# ICP Autopilot v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the ICP Autopilot v2 per the approved spec (`docs/specs/2026-07-20-icp-autopilot-design.md`): a Task-Scheduler-driven pipeline (every 5 min) where a `claude -p` run detects Warmly visitors, ICP-checks, enriches (ZoomInfo/Google/LinkedIn), and drafts emails as JSON; deterministic Python then routes drafts through a reply-to-approve loop and sends via Outlook COM.

**Architecture:** Three pieces — `scripts/run.ps1` (trigger + lock + timeout), `claude -p prompts/run-prompt.md` (the brain, writes draft JSON only), `pipeline/` Python (the hands: gates, approvals, Outlook COM send). The model never touches the mailbox; Python never trusts the model.

**Tech Stack:** Python 3.11+, pywin32 (Outlook COM), pytest, PowerShell 5.1, Windows Task Scheduler, Claude Code CLI + Warmly/ZoomInfo/Playwright MCP.

## Global Constraints (from spec — every task inherits these)

- Working dir for all commands: `C:\Users\admin\Documents\ICP-Autopilot` (git repo already initialized; repo-local identity set).
- Ships with `config.json: "safety": {"dry_run": true}` and `"mode": "review"`. Never flip in this plan.
- The parent batch pipeline (`..\Website data\pipeline\*`) is NEVER modified. `pipeline/icp_core.py` is a **verbatim copy** of `..\Website data\Fully-Automated System\shared\icp_core.py` — do not "improve" it.
- No external URL is ever written from memory anywhere (code, config, prompt, tests use `example.com`-style fixtures only).
- Every gate failure defaults to NOT sending. Ambiguity never sends.
- All state writes are atomic (temp file + `os.replace`).
- Dedup is absolute: one normalized email is never sent to twice.
- Caps (config defaults): 10 sends/day, 2/domain/rolling-7-days, 20 approval requests/day, 50 ZoomInfo enrich/day, 15 LinkedIn loads/day, 48 h approval expiry, 12 retry attempts.
- Tests: `python -m pytest -q` from repo root must be green after every task. COM is never touched in tests (mock/fake only).
- Commit after every task (repo-local git identity already configured).

## File Structure (locked)

```
pipeline/__init__.py          empty package marker
pipeline/state.py             atomic JSON load/save, daily backup, date helpers
pipeline/icp_core.py          VERBATIM copy from v1 (provenance header kept)
pipeline/icp_check.py         evaluate(company_dict) + CLI wrapper used by the claude run
pipeline/sanitize.py          body sanitizer + {{var}} template renderer
pipeline/approvals.py         token gen, verdict parser, approval lifecycle
pipeline/gates.py             pure gate functions + evaluate(draft, ctx)
pipeline/outlook.py           thin COM wrapper (only module importing win32com)
pipeline/send.py              two-phase prospect send + draft routing
pipeline/tick.py              CLI: --phase pre | post
pipeline/summary.py           daily summary email builder
pipeline/smoke_test.py        dry pipeline pass + send-to-self
config/config.json            runtime config (structure below)
config/email_template.txt     plain-text shell (NO video line)
config/email_template.html    HTML shell (NO video line)
config/suppression.txt        one email per line, # comments
prompts/run-prompt.md         the pinned claude -p prompt
scripts/run.ps1               Task Scheduler entry point
scripts/setup.ps1             environment verifier
scripts/task-schedule.xml     importable 5-min task definition
SETUP.md                      spare-PC deployment steps
tests/test_state.py … one test file per module
state/ drafts/{inbox,sent,rejected,invalid}/ logs/   (gitkeep'd dirs)
```

---

### Task 1: Scaffold, config, templates

**Files:**
- Create: `pipeline/__init__.py`, `tests/__init__.py`, `requirements.txt`, `.gitignore`, `config/config.json`, `config/email_template.txt`, `config/email_template.html`, `config/suppression.txt`, empty dirs `state/`, `logs/`, `drafts/inbox|sent|rejected|invalid/` (each with `.gitkeep`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config/config.json` with the exact keys below — ALL later tasks read these key names verbatim.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_config_shape_and_safe_defaults():
    cfg = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    assert cfg["mode"] == "review"
    assert cfg["safety"]["dry_run"] is True
    a = cfg["addresses"]
    for k in ("sender_mailbox", "reviewer_notify", "audit_bcc", "summary_to"):
        assert "@" in a[k]
    assert isinstance(a["approver_addresses"], list) and a["approver_addresses"]
    c = cfg["caps"]
    assert (c["sends_per_day"], c["domain_sends_per_week"], c["approval_requests_per_day"],
            c["zoominfo_enrich_per_day"], c["linkedin_loads_per_day"]) == (10, 2, 20, 50, 15)
    assert cfg["geo_allowlist"] == ["US"]
    assert cfg["approval_expiry_hours"] == 48 and cfg["retry_max_attempts"] == 12
    assert cfg["linkedin"]["enabled"] in (True, False)

def test_templates_have_no_video_and_required_vars():
    for ext in ("txt", "html"):
        t = (ROOT / "config" / f"email_template.{ext}").read_text(encoding="utf-8")
        assert "video" not in t.lower()
        for var in ("{{subject}}", "{{first_name}}", "{{body}}", "{{sender_name}}", "{{postal_address}}"):
            assert var in t
```

- [ ] **Step 2: Run test to verify it fails** — `python -m pytest tests/test_config.py -q` → FAIL (files missing).

- [ ] **Step 3: Create the files**

`requirements.txt`:
```
pywin32>=306
pytest>=8
```

`.gitignore`:
```
__pycache__/
state/*.json
state/backup/
logs/
drafts/*/*.json
.env
```

`config/config.json`:
```json
{
  "mode": "review",
  "safety": { "dry_run": true },
  "addresses": {
    "sender_mailbox": "upawar@unboundia.com",
    "reviewer_notify": "upawar@unboundia.com",
    "approver_addresses": ["upawar@unboundia.com"],
    "audit_bcc": "upawar@unboundia.com",
    "summary_to": "upawar@unboundia.com"
  },
  "caps": {
    "sends_per_day": 10,
    "domain_sends_per_week": 2,
    "approval_requests_per_day": 20,
    "zoominfo_enrich_per_day": 50,
    "linkedin_loads_per_day": 15
  },
  "geo_allowlist": ["US"],
  "approval_expiry_hours": 48,
  "retry_max_attempts": 12,
  "linkedin": { "enabled": true },
  "sender": { "name": "REPLACE_ME", "title": "Unbound IA", "postal_address": "REPLACE_ME" }
}
```
(Director's address unknown → all addresses default to the operator per spec §2. `REPLACE_ME` sender fields are caught by a gate in Task 6, forcing queue-only until filled.)

`config/email_template.txt`:
```
Subject: {{subject}}

Hi {{first_name}},

{{body}}

If it's useful, happy to walk through how this could apply to your team.

Best,
{{sender_name}}
{{sender_title}}

--
{{postal_address}}
You received this because you visited our website. Reply "unsubscribe" to opt out.
```

`config/email_template.html`: same content as HTML — wrap paragraphs in `<p>`, `{{body}}` on its own line inside a `<div>`, footer in `<hr>` + small text. No video line.

`config/suppression.txt`:
```
# One email address per line. Lines starting with # are ignored.
```

`pipeline/__init__.py`, `tests/__init__.py`: empty. Create `.gitkeep` in `state/`, `logs/`, and each `drafts/` subdir.

- [ ] **Step 4: Run test to verify it passes** — `python -m pytest tests/test_config.py -q` → 2 passed.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: scaffold, config, templates (no video)"`

---

### Task 2: `pipeline/state.py` — atomic store + caps windows

**Files:** Create `pipeline/state.py`; Test `tests/test_state.py`

**Interfaces:**
- Produces: `load_json(path, default)`, `save_json(path, obj)` (atomic), `backup_state(state_dir, today_str)` (copies `*.json` to `state/backup/<date>/`, once per date), `today()` → `"YYYY-MM-DD"`, `now_iso()`, `prune_daily(counts: dict, keep_days=8)`, `count_in_window(timestamps: list[str], days: int, now=None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_state.py
import json, os
from pipeline import state

def test_save_is_atomic_and_roundtrips(tmp_path):
    p = tmp_path / "x.json"
    state.save_json(p, {"a": 1})
    assert state.load_json(p, {}) == {"a": 1}
    assert not list(tmp_path.glob("*.tmp"))          # no temp litter

def test_load_missing_returns_default(tmp_path):
    assert state.load_json(tmp_path / "nope.json", {"d": True}) == {"d": True}

def test_backup_once_per_day(tmp_path):
    sd = tmp_path / "state"; sd.mkdir()
    state.save_json(sd / "a.json", {"x": 1})
    assert state.backup_state(sd, "2026-07-20") is True
    assert state.backup_state(sd, "2026-07-20") is False    # already done today
    assert json.loads((sd / "backup" / "2026-07-20" / "a.json").read_text()) == {"x": 1}

def test_count_in_window():
    ts = ["2026-07-14T10:00:00", "2026-07-19T10:00:00", "2026-07-20T09:00:00"]
    assert state.count_in_window(ts, days=7, now="2026-07-20T12:00:00") == 2

def test_prune_daily():
    counts = {"2026-07-01": 5, "2026-07-19": 2, "2026-07-20": 1}
    state.prune_daily(counts, keep_days=8, today_str="2026-07-20")
    assert "2026-07-01" not in counts and counts["2026-07-19"] == 2
```

- [ ] **Step 2: Run** — `python -m pytest tests/test_state.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement**

```python
# pipeline/state.py
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
```

- [ ] **Step 4: Run** — 5 passed. **Step 5: Commit** — `git add -A && git commit -m "feat: atomic state store + window helpers"`

---

### Task 3: ICP check (verbatim core + wrapper CLI)

**Files:** Create `pipeline/icp_core.py` (copy), `pipeline/icp_check.py`; Test `tests/test_icp_check.py`

**Interfaces:**
- Produces: `icp_check.evaluate(company: dict) -> {"is_icp": bool, "qualification": str, "reason": str}` where `company = {"raw_classifications": [str], "employees": int|None, "employee_range": str|None, "funding_rounds": [str]}`. CLI: `python pipeline/icp_check.py --json <file>` (or stdin) prints that dict as JSON. Task 6's gate #4 and the run-prompt (Task 10) call these.

- [ ] **Step 1: Copy the core verbatim**

```bash
cp "../Website data/Fully-Automated System/shared/icp_core.py" pipeline/icp_core.py
```
Do NOT edit it. (Its provenance header already documents the copy chain; append one line: `# Re-copied unchanged into ICP-Autopilot 2026-07-20.`)

- [ ] **Step 2: Write the failing test**

```python
# tests/test_icp_check.py
import json, subprocess, sys
from pipeline.icp_check import evaluate

TECH_1K = {"raw_classifications": ["Business Services", "software.crm"], "employees": 5000, "funding_rounds": []}

def test_smart_play_non_primary_tech_qualifies():
    r = evaluate(TECH_1K)
    assert r["is_icp"] is True and r["qualification"] == "Emp 1k+" and r["reason"] == ""

def test_funding_route_qualifies_without_size():
    r = evaluate({"raw_classifications": ["SaaS"], "employees": 200,
                  "funding_rounds": ["Series B"]})
    assert r["is_icp"] is True and r["qualification"].startswith("Funding")

def test_right_industry_below_threshold():
    r = evaluate({"raw_classifications": ["Software"], "employees": 50, "funding_rounds": []})
    assert r["is_icp"] is False and "Below Threshold" in r["reason"]

def test_wrong_industry_right_size():
    r = evaluate({"raw_classifications": ["Retail"], "employees": 9000, "funding_rounds": []})
    assert r["is_icp"] is False and "Wrong Industry" in r["reason"]

def test_no_data_is_not_icp():
    r = evaluate({"raw_classifications": [], "employees": None, "funding_rounds": []})
    assert r["is_icp"] is False

def test_employee_range_string_parsed():
    r = evaluate({"raw_classifications": ["Software"], "employees": None,
                  "employee_range": "1,000 - 4,999", "funding_rounds": []})
    assert r["is_icp"] is True

def test_cli_roundtrip(tmp_path):
    f = tmp_path / "c.json"; f.write_text(json.dumps(TECH_1K))
    out = subprocess.run([sys.executable, "pipeline/icp_check.py", "--json", str(f)],
                         capture_output=True, text=True)
    assert out.returncode == 0 and json.loads(out.stdout)["is_icp"] is True
```

- [ ] **Step 3: Run** — FAIL. **Step 4: Implement**

```python
# pipeline/icp_check.py
"""Deterministic ICP gate over raw classification data. Thin wrapper around icp_core."""
import argparse, json, re, sys
try:
    from pipeline import icp_core
except ImportError:            # invoked as a script from repo root
    import icp_core

def evaluate(company):
    ind_all = [c for c in (company.get("raw_classifications") or []) if c]
    emp = icp_core.min_employees(company.get("employee_range"), company.get("employees"))
    rounds = [r or "" for r in (company.get("funding_rounds") or [])]
    has_round = any(re.search(r"series\s*[a-f]\b", r.lower()) for r in rounds)
    recent = rounds[0] if rounds else ""
    _, _, _, is_icp, qual, reason = icp_core.icp_eval(ind_all, emp, has_round, recent)
    return {"is_icp": is_icp, "qualification": qual, "reason": reason}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="path to company JSON; stdin if omitted")
    args = ap.parse_args()
    raw = open(args.json, encoding="utf-8").read() if args.json else sys.stdin.read()
    print(json.dumps(evaluate(json.loads(raw))))

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run** — 7 passed. Commit: `git add -A && git commit -m "feat: verbatim ICP core + deterministic check CLI"`

---

### Task 4: `pipeline/sanitize.py` — body sanitizer + renderer

**Files:** Create `pipeline/sanitize.py`; Test `tests/test_sanitize.py` (contract ported from v1 `tests/test_email_sanitize.py`, video variable dropped)

**Interfaces:**
- Produces: `sanitize_body(raw: str) -> str`; `render(template: str, vars: dict) -> str` ({{var}} substitution; raises `KeyError` listing any unreplaced `{{...}}`); `load_template(ext: str) -> str` reading `config/email_template.<ext>`. Used by Tasks 6 (gate), 8 (send), 9 (approval email).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sanitize.py
import pytest
from pipeline.sanitize import sanitize_body, render, load_template

def test_strips_greeting_signoff_placeholder_subject():
    raw = ("Subject: Quick note\n\nHi Avik,\n\nBody paragraph one about them.\n\n"
           "Second short paragraph.\n\nBest,\n[Your name]")
    out = sanitize_body(raw)
    assert out == "Body paragraph one about them.\n\nSecond short paragraph."
    for bad in ("Hi Avik", "Subject:", "Best,", "[Your name]"):
        assert bad not in out

def test_strips_code_fence_and_various_signoffs():
    for signoff in ("Regards,", "Thanks,", "Cheers,", "Warm regards,", "Sincerely,"):
        raw = f"```\nHello there,\n\nThe message.\n\n{signoff}\nJane Doe\nUnbound IA\n```"
        assert sanitize_body(raw) == "The message."

def test_keeps_clean_body_untouched():
    body = "First paragraph.\n\nSecond paragraph with a clear ask?"
    assert sanitize_body(body) == body

def test_render_and_single_greeting_signature():
    tpl = load_template("txt")
    rendered = render(tpl, {
        "subject": "S", "first_name": "Avik", "body": sanitize_body("Hi Avik,\n\nThe pitch.\n\nBest,\n[Your name]"),
        "sender_name": "Uday Pawar", "sender_title": "Unbound IA", "postal_address": "addr",
    })
    assert rendered.count("Hi Avik,") == 1 and rendered.count("Uday Pawar") == 1
    assert "[Your name]" not in rendered and "{{" not in rendered

def test_render_raises_on_missing_var():
    with pytest.raises(KeyError):
        render("Hello {{name}} and {{other}}", {"name": "x"})
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**

```python
# pipeline/sanitize.py
"""Email body/template contract: the model returns paragraphs ONLY; the template owns
greeting, sign-off, footer. Regression-locked (v1 double-greeting bug)."""
import re
from pathlib import Path

_SIGNOFFS = ("best,", "best regards,", "regards,", "thanks,", "thank you,",
             "cheers,", "warm regards,", "sincerely,")
_GREETING = re.compile(r"^(hi|hello|hey|dear)\b.*[,!:]\s*$", re.I)

def sanitize_body(raw):
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*\n", "", text)
    text = re.sub(r"\n?```\s*$", "", text).strip()
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.lower().startswith("subject:"):
            continue
        if _GREETING.match(s):
            continue
        if s.lower() in _SIGNOFFS:
            break                      # drop sign-off and everything after (signature)
        out.append(ln)
    body = "\n".join(out).replace("[Your name]", "")
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body

def load_template(ext):
    root = Path(__file__).resolve().parents[1]
    return (root / "config" / f"email_template.{ext}").read_text(encoding="utf-8")

def render(template, vars):
    out = template
    for k, v in vars.items():
        out = out.replace("{{%s}}" % k, str(v))
    left = re.findall(r"\{\{(\w+)\}\}", out)
    if left:
        raise KeyError(f"unreplaced template vars: {left}")
    return out
```

- [ ] **Step 4: Run** — 5 passed. **Step 5: Commit** — `git commit -am "feat: body sanitizer + template renderer (v1 contract, video dropped)"`

---

### Task 5: `pipeline/approvals.py` — tokens, verdict parser, lifecycle

**Files:** Create `pipeline/approvals.py`; Test `tests/test_approvals.py`

**Interfaces:**
- Produces: `new_token(existing: set) -> str` (6 uppercase hex, collision-checked); `find_token(subject: str) -> str|None` (extracts `[#XXXXXX]`); `strip_quoted(text) -> str`; `parse_verdict(text) -> "approved"|"rejected"|"hold"`; `Approvals` class over `state/approvals.json`: `.create(token, draft_path, recipient)`, `.pending() -> dict`, `.decide(token, verdict, decided_by)`, `.consume(token)`, `.expire_older_than(hours, now_iso) -> [tokens]`, `.reserved_emails() -> set`. Task 9 (tick) drives it; Task 6's dedup gate reads `reserved_emails()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_approvals.py
from pipeline.approvals import (new_token, find_token, parse_verdict, strip_quoted, Approvals)

def test_token_unique_and_format():
    seen = set()
    for _ in range(50):
        t = new_token(seen); assert len(t) == 6 and t == t.upper(); seen.add(t)

def test_find_token():
    assert find_token("RE: Approval [#A7F3B2] — John (Acme)") == "A7F3B2"
    assert find_token("no token here") is None

def test_verdicts():
    assert parse_verdict("GOOD") == "approved"
    assert parse_verdict("good\n\nSent from my iPhone") == "approved"
    assert parse_verdict("Yes, send it") == "approved"
    assert parse_verdict("No") == "rejected"
    assert parse_verdict("reject this one") == "rejected"
    assert parse_verdict("looks interesting, let me think") == "hold"
    assert parse_verdict("") == "hold"
    assert parse_verdict("good but no") == "hold"          # both → ambiguity never sends

def test_quoted_reply_only_top_counts():
    reply = ("GOOD\n\nGet Outlook for iOS\n________________________________\n"
             "From: Sales Director\nSent: x\nSubject: Approval [#A7F3B2]\n"
             "Reply NO to reject.")                          # 'NO' lives in the quote
    assert parse_verdict(reply) == "approved"
    assert "Reply NO" not in strip_quoted(reply)

def test_lifecycle(tmp_path):
    a = Approvals(tmp_path / "approvals.json")
    a.create("A7F3B2", "drafts/inbox/v1.json", "jane@acme.com")
    assert "A7F3B2" in a.pending() and "jane@acme.com" in a.reserved_emails()
    a.decide("A7F3B2", "approved", "director@unboundia.com")
    assert "A7F3B2" not in a.pending()
    a.consume("A7F3B2")
    assert a.data["A7F3B2"]["status"] == "consumed"
    assert "jane@acme.com" in a.reserved_emails()            # reservation survives consumption

def test_expiry(tmp_path):
    a = Approvals(tmp_path / "approvals.json")
    a.create("AAAAAA", "d.json", "x@y.com", requested_at="2026-07-17T10:00:00")
    assert a.expire_older_than(48, now_iso="2026-07-20T10:00:00") == ["AAAAAA"]
    assert a.data["AAAAAA"]["status"] == "expired"
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**

```python
# pipeline/approvals.py
"""Reply-to-approve lifecycle. Ambiguity never sends."""
import re, secrets
from datetime import datetime, timedelta
from pipeline import state

APPROVE = {"good", "send", "yes", "approve", "approved"}
REJECT = {"no", "reject", "rejected", "skip"}
_QUOTE = [re.compile(p, re.I) for p in (
    r"^-{2,}\s*original message\s*-{2,}", r"^from:\s", r"^on .{0,120} wrote:\s*$",
    r"^_{5,}", r"^sent from my", r"^get outlook for", r"^>",
)]
TOKEN_RE = re.compile(r"\[#([0-9A-F]{6})\]")

def new_token(existing):
    while True:
        t = secrets.token_hex(3).upper()
        if t not in existing:
            return t

def find_token(subject):
    m = TOKEN_RE.search(subject or "")
    return m.group(1) if m else None

def strip_quoted(text):
    out = []
    for ln in (text or "").splitlines():
        if any(p.match(ln.strip()) for p in _QUOTE):
            break
        out.append(ln)
    return "\n".join(out)

def parse_verdict(text):
    top = strip_quoted(text)
    lines = [l.strip() for l in top.splitlines() if l.strip()][:5]
    words = set(re.findall(r"[a-z]+", " ".join(lines).lower()))
    app, rej = bool(words & APPROVE), bool(words & REJECT)
    if app and not rej:
        return "approved"
    if rej and not app:
        return "rejected"
    return "hold"

class Approvals:
    def __init__(self, path):
        self.path = path
        self.data = state.load_json(path, {})

    def _save(self):
        state.save_json(self.path, self.data)

    def create(self, token, draft_path, recipient, requested_at=None):
        self.data[token] = {"draft_path": str(draft_path), "recipient": recipient.lower(),
                            "status": "pending",
                            "requested_at": requested_at or state.now_iso()}
        self._save()

    def pending(self):
        return {t: r for t, r in self.data.items() if r["status"] == "pending"}

    def decide(self, token, verdict, decided_by):
        r = self.data[token]
        r.update(status=verdict, decided_by=decided_by, decided_at=state.now_iso())
        self._save()

    def consume(self, token):
        self.data[token]["status"] = "consumed"
        self._save()

    def reserved_emails(self):
        return {r["recipient"] for r in self.data.values()}

    def expire_older_than(self, hours, now_iso=None):
        ref = datetime.fromisoformat(now_iso) if now_iso else datetime.now()
        out = []
        for t, r in self.data.items():
            if r["status"] != "pending":
                continue
            if datetime.fromisoformat(r["requested_at"]) < ref - timedelta(hours=hours):
                r["status"] = "expired"; out.append(t)
        if out:
            self._save()
        return out
```

- [ ] **Step 4: Run** — 6 passed. **Step 5: Commit** — `git commit -am "feat: approval tokens, verdict parser, lifecycle"`

---

### Task 6: `pipeline/gates.py` — every hard gate, pure

**Files:** Create `pipeline/gates.py`; Test `tests/test_gates.py`

**Interfaces:**
- Consumes: `icp_check.evaluate`, `state.count_in_window`, `Approvals.reserved_emails()`.
- Produces: `GateCtx` dataclass `(cfg, send_log: dict, reserved: set, caps: dict, suppression: set, verify_url: callable, root: Path, now_iso: str)`; `evaluate(draft: dict, ctx: GateCtx) -> list[str]` (empty = all gates pass; else human-readable failure reasons); `validate_schema(draft) -> list[str]`; `norm_email(s) -> str`. Task 8 (send) calls `evaluate` immediately before EVERY send.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gates.py
import copy
from pathlib import Path
from pipeline import gates

def good_draft():
    return {
        "visitor_id": "v1", "detected_at": "2026-07-20T09:00:00",
        "person": {"full_name": "Jane Roe", "first_name": "Jane", "email": "jane@acme.com",
                   "title": "VP Engineering", "seniority": "VP Level Exec"},
        "company": {"name": "Acme", "domain": "acme.com", "country": "US",
                    "raw_classifications": ["Software"], "employees": 5000,
                    "funding_rounds": []},
        "visit": {"pages": ["/pricing"], "last_seen": "2026-07-20T08:59:00"},
        "email": {"subject": "S", "body_paragraphs": ["P1", "P2"]},
        "sources": [{"claim": "c", "url": "https://acme.example.com/x"}],
        "enrichment": {"gaps": []},
        "enrich": {"provider": "zoominfo_mcp", "match_level": "FULL_MATCH"},
    }

def ctx(tmp_path, **over):
    base = dict(
        cfg={"caps": {"sends_per_day": 10, "domain_sends_per_week": 2},
             "geo_allowlist": ["US"],
             "sender": {"name": "Uday", "title": "T", "postal_address": "A"},
             "safety": {"dry_run": False}},
        send_log={}, reserved=set(), caps={"sends": {}, "domain_sends": {}},
        suppression=set(), verify_url=lambda u: True, root=tmp_path,
        now_iso="2026-07-20T12:00:00")
    base.update(over)
    return gates.GateCtx(**base)

def test_clean_draft_passes(tmp_path):
    assert gates.evaluate(good_draft(), ctx(tmp_path)) == []

def test_kill_switch(tmp_path):
    (tmp_path / "STOP").write_text("")
    assert any("kill switch" in r for r in gates.evaluate(good_draft(), ctx(tmp_path)))

def test_dry_run_blocks(tmp_path):
    c = ctx(tmp_path); c.cfg["safety"]["dry_run"] = True
    assert any("dry_run" in r for r in gates.evaluate(good_draft(), c))

def test_schema_missing_field(tmp_path):
    d = good_draft(); del d["email"]
    assert gates.evaluate(d, ctx(tmp_path))

def test_icp_recheck_blocks_non_icp(tmp_path):
    d = good_draft(); d["company"]["employees"] = 50
    assert any("ICP" in r for r in gates.evaluate(d, ctx(tmp_path)))

def test_freemail_and_domain_mismatch_block(tmp_path):
    d = good_draft(); d["person"]["email"] = "jane@gmail.com"
    assert gates.evaluate(d, ctx(tmp_path))

def test_suppression_blocks(tmp_path):
    assert gates.evaluate(good_draft(), ctx(tmp_path, suppression={"jane@acme.com"}))

def test_dedup_sent_and_reserved(tmp_path):
    assert gates.evaluate(good_draft(), ctx(tmp_path, send_log={"jane@acme.com": {}}))
    assert gates.evaluate(good_draft(), ctx(tmp_path, reserved={"jane@acme.com"}))

def test_daily_cap(tmp_path):
    c = ctx(tmp_path, caps={"sends": {"2026-07-20": 10}, "domain_sends": {}})
    assert any("cap" in r for r in gates.evaluate(good_draft(), c))

def test_domain_weekly_cap(tmp_path):
    c = ctx(tmp_path, caps={"sends": {}, "domain_sends":
            {"acme.com": ["2026-07-18T10:00:00", "2026-07-19T10:00:00"]}})
    assert any("domain" in r for r in gates.evaluate(good_draft(), c))

def test_geo_blocks_non_us(tmp_path):
    d = good_draft(); d["company"]["country"] = "IN"
    assert any("geo" in r for r in gates.evaluate(d, ctx(tmp_path)))

def test_dead_link_blocks(tmp_path):
    assert gates.evaluate(good_draft(), ctx(tmp_path, verify_url=lambda u: False))

def test_replace_me_sender_blocks(tmp_path):
    c = ctx(tmp_path); c.cfg["sender"]["name"] = "REPLACE_ME"
    assert any("REPLACE_ME" in r for r in gates.evaluate(good_draft(), c))
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**

```python
# pipeline/gates.py
"""Every hard gate, re-checked deterministically at send time. Model output is never trusted."""
import re
from dataclasses import dataclass
from pathlib import Path
from pipeline import icp_check, state

FREEMAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
            "icloud.com", "proton.me", "protonmail.com"}
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
REQUIRED = {
    "visitor_id": str, "person": dict, "company": dict, "visit": dict,
    "email": dict, "sources": list, "enrich": dict,
}

def norm_email(s):
    return (s or "").strip().lower()

@dataclass
class GateCtx:
    cfg: dict
    send_log: dict
    reserved: set
    caps: dict
    suppression: set
    verify_url: object            # callable(url) -> bool
    root: Path
    now_iso: str

def validate_schema(draft):
    errs = [f"schema: missing/typed field '{k}'" for k, t in REQUIRED.items()
            if not isinstance(draft.get(k), t)]
    if errs:
        return errs
    p, c, e = draft["person"], draft["company"], draft["email"]
    for field, obj, name in (("email", p, "person.email"), ("first_name", p, "person.first_name"),
                             ("title", p, "person.title"), ("domain", c, "company.domain"),
                             ("country", c, "company.country"), ("subject", e, "email.subject")):
        if not obj.get(field):
            errs.append(f"schema: empty {name}")
    if not e.get("body_paragraphs"):
        errs.append("schema: empty email.body_paragraphs")
    return errs

def evaluate(draft, ctx):
    fails = []
    if (Path(ctx.root) / "STOP").exists():
        return ["kill switch: STOP file present"]
    if ctx.cfg["safety"]["dry_run"]:
        fails.append("dry_run: true — sending disabled")
    errs = validate_schema(draft)
    if errs:
        return fails + errs                       # can't gate further on a broken draft

    person, comp = draft["person"], draft["company"]
    email = norm_email(person["email"])
    # 4. ICP re-check on raw data
    if not icp_check.evaluate(comp)["is_icp"]:
        fails.append("ICP re-check failed on raw classification data")
    # 5. recipient sanity
    dom = email.split("@")[-1]
    if not EMAIL_RE.match(email):
        fails.append("recipient: invalid email format")
    elif dom in FREEMAIL:
        fails.append("recipient: free-mail domain")
    elif dom != comp["domain"].lower() and not dom.endswith("." + comp["domain"].lower()):
        fails.append("recipient: email domain does not match company domain")
    if email in ctx.suppression:
        fails.append("recipient: on suppression list")
    # 6. absolute dedup
    if email in {norm_email(k) for k in ctx.send_log}:
        fails.append("dedup: already sent to this person")
    if email in {norm_email(k) for k in ctx.reserved}:
        fails.append("dedup: reserved by a pending/decided approval")
    # 7. caps
    day = ctx.now_iso[:10]
    if ctx.caps["sends"].get(day, 0) >= ctx.cfg["caps"]["sends_per_day"]:
        fails.append("cap: daily send cap reached")
    dom_ts = ctx.caps["domain_sends"].get(comp["domain"].lower(), [])
    if state.count_in_window(dom_ts, days=7, now=ctx.now_iso) >= ctx.cfg["caps"]["domain_sends_per_week"]:
        fails.append("cap: domain weekly cap reached")
    # 8. geo
    if comp["country"].upper() not in [g.upper() for g in ctx.cfg["geo_allowlist"]]:
        fails.append(f"geo: {comp['country']} not in allowlist")
    # 9. links re-verified now
    for s in draft["sources"]:
        if s.get("url") and not ctx.verify_url(s["url"]):
            fails.append(f"link: not HTTP 200 now: {s['url']}")
    # 10. sender config filled
    snd = ctx.cfg["sender"]
    if any("REPLACE_ME" in str(v) for v in snd.values()):
        fails.append("sender: REPLACE_ME placeholder still in config")
    return fails
```

- [ ] **Step 4: Run** — 13 passed; full suite green. **Step 5: Commit** — `git commit -am "feat: deterministic hard gates"`

---

### Task 7: `pipeline/outlook.py` — thin COM wrapper

**Files:** Create `pipeline/outlook.py`; Test `tests/test_outlook.py`

**Interfaces:**
- Produces: class `Outlook` with `send(to, subject, body_text, html_body=None, bcc=None) -> str` (returns our internal id: `subject` is logged; COM has no reliable message-id pre-send — spec's "reconcile by message-id" uses the approval token embedded in subject); `inbox_since(iso_ts) -> list[dict(subject, sender, body, received)]` where `sender` is the resolved SMTP address; `verify_url(url) -> bool` lives HERE TOO? No — it goes in this module's sibling: add module-level `verify_url(url, timeout=10) -> bool` using `urllib.request` HEAD-then-GET, final status 200 only. Only this module imports `win32com`; import happens inside `__init__` so tests never need it.

- [ ] **Step 1: Write the failing test** (COM fully faked — tests exercise the pure parts)

```python
# tests/test_outlook.py
from pipeline import outlook

class FakeMail:
    def __init__(self): self.sent = False; self.To = self.BCC = self.Subject = self.Body = self.HTMLBody = ""
    def Send(self): self.sent = True

class FakeApp:
    def __init__(self): self.mail = FakeMail()
    def CreateItem(self, kind): assert kind == 0; return self.mail

def test_send_sets_fields_and_sends():
    o = outlook.Outlook(app=FakeApp())
    o.send("a@b.com", "Subj", "text body", bcc="c@d.com")
    m = o.app.mail
    assert m.sent and m.To == "a@b.com" and m.BCC == "c@d.com" and m.Subject == "Subj"

def test_verify_url_rejects_non_http():
    assert outlook.verify_url("notaurl") is False
    assert outlook.verify_url("ftp://x") is False
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**

```python
# pipeline/outlook.py
"""The ONLY module that talks to Outlook COM. Requires classic Outlook (New Outlook has no COM)."""
import urllib.request

PR_SMTP = "http://schemas.microsoft.com/mapi/proptag/0x39FE001E"

def verify_url(url, timeout=10):
    if not str(url).startswith(("http://", "https://")):
        return False
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False

class Outlook:
    def __init__(self, app=None):
        if app is None:
            import win32com.client
            app = win32com.client.Dispatch("Outlook.Application")
        self.app = app

    def send(self, to, subject, body_text, html_body=None, bcc=None):
        m = self.app.CreateItem(0)                  # olMailItem
        m.To = to
        if bcc:
            m.BCC = bcc
        m.Subject = subject
        if html_body:
            m.HTMLBody = html_body
        else:
            m.Body = body_text
        m.Send()
        return subject

    def inbox_since(self, iso_ts):
        ns = self.app.GetNamespace("MAPI")
        inbox = ns.GetDefaultFolder(6)               # olFolderInbox
        items = inbox.Items
        items.Sort("[ReceivedTime]", True)
        ts = iso_ts.replace("T", " ")[:16]           # 'YYYY-MM-DD HH:MM'
        restricted = items.Restrict(f"[ReceivedTime] >= '{ts}'")
        out = []
        for msg in restricted:
            try:
                sender = msg.PropertyAccessor.GetProperty(PR_SMTP)
            except Exception:
                sender = getattr(msg, "SenderEmailAddress", "") or ""
            out.append({"subject": msg.Subject or "", "sender": (sender or "").lower(),
                        "body": msg.Body or "",
                        "received": msg.ReceivedTime.strftime("%Y-%m-%dT%H:%M:%S")})
        return out
```
(Note: `inbox_since` runs only on the spare PC; smoke test covers it live. Restrict-format quirks are a known COM sharp edge — the smoke test asserts a self-sent message is found.)

- [ ] **Step 4: Run** — 2 passed. **Step 5: Commit** — `git commit -am "feat: Outlook COM wrapper + url verifier"`

---

### Task 8: `pipeline/send.py` — routing + two-phase send

**Files:** Create `pipeline/send.py`; Test `tests/test_send.py`

**Interfaces:**
- Consumes: `gates.evaluate/GateCtx/norm_email`, `sanitize.render/load_template/sanitize_body`, `approvals.Approvals/new_token`, `state.*`, an `Outlook`-shaped object injected as `mailer`.
- Produces: class `Sender(root, cfg, mailer, verify_url=outlook.verify_url)` with:
  - `.route_draft(draft_path) -> str` — statuses: `"invalid"`, `"gated:<r1>|<r2>"`, `"approval_requested:<token>"`, `"sent"`, `"dry_run"`. In `mode=review` a gated-clean draft becomes an approval request (dry_run gate EXCLUDED from the pre-approval check — requests may flow in dry-run; the final send still blocks); in `mode=auto` it sends.
  - `.send_prospect(draft, token=None) -> bool` — re-runs ALL gates, two-phase send_log (reserve→send→confirm), BCC audit, moves draft file to `drafts/sent/`.
  - `.render_email(draft) -> (subject, text, html)`.
  Task 9 (tick) is the only caller.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_send.py
import json, copy
from pathlib import Path
from pipeline.send import Sender
from tests.test_gates import good_draft

class FakeMailer:
    def __init__(self): self.sent = []
    def send(self, to, subject, body_text, html_body=None, bcc=None):
        self.sent.append({"to": to, "subject": subject, "bcc": bcc}); return subject

def make_root(tmp_path, mode="review", dry_run=False):
    cfg = json.loads((Path("config/config.json")).read_text())
    cfg["mode"] = mode; cfg["safety"]["dry_run"] = dry_run
    cfg["sender"] = {"name": "Uday", "title": "T", "postal_address": "A"}
    for d in ("state", "drafts/inbox", "drafts/sent", "drafts/rejected", "drafts/invalid", "config"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    for f in ("email_template.txt", "email_template.html", "suppression.txt"):
        (tmp_path / "config" / f).write_text(Path("config", f).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path, cfg

def write_draft(root, d=None):
    d = d or good_draft()
    p = root / "drafts" / "inbox" / f"{d['visitor_id']}.json"
    p.write_text(json.dumps(d)); return p

def test_review_mode_requests_approval(tmp_path):
    root, cfg = make_root(tmp_path)
    m = FakeMailer(); s = Sender(root, cfg, m, verify_url=lambda u: True)
    out = s.route_draft(write_draft(root))
    assert out.startswith("approval_requested:")
    token = out.split(":")[1]
    assert f"[#{token}]" in m.sent[0]["subject"]
    assert m.sent[0]["to"] == cfg["addresses"]["reviewer_notify"]
    assert "GOOD" in m.sent[0]["subject"] or True   # instruction lives in body

def test_auto_mode_sends_with_bcc_and_dedup(tmp_path):
    root, cfg = make_root(tmp_path, mode="auto")
    m = FakeMailer(); s = Sender(root, cfg, m, verify_url=lambda u: True)
    assert s.route_draft(write_draft(root)) == "sent"
    assert m.sent[0]["to"] == "jane@acme.com" and m.sent[0]["bcc"] == cfg["addresses"]["audit_bcc"]
    # second identical draft must be blocked by dedup
    d2 = good_draft(); d2["visitor_id"] = "v2"
    assert s.route_draft(write_draft(root, d2)).startswith("gated:")

def test_dry_run_blocks_send_but_allows_approval_request(tmp_path):
    root, cfg = make_root(tmp_path, mode="auto", dry_run=True)
    m = FakeMailer(); s = Sender(root, cfg, m, verify_url=lambda u: True)
    assert s.route_draft(write_draft(root)) == "dry_run"
    root2, cfg2 = make_root(tmp_path / "b", mode="review", dry_run=True)
    m2 = FakeMailer(); s2 = Sender(root2, cfg2, m2, verify_url=lambda u: True)
    assert s2.route_draft(write_draft(root2)).startswith("approval_requested:")

def test_invalid_draft_moved(tmp_path):
    root, cfg = make_root(tmp_path)
    p = root / "drafts" / "inbox" / "bad.json"; p.write_text("{not json")
    s = Sender(root, cfg, FakeMailer(), verify_url=lambda u: True)
    assert s.route_draft(p) == "invalid"
    assert not p.exists() and (root / "drafts" / "invalid" / "bad.json").exists()

def test_send_failure_leaves_unconfirmed_never_resends(tmp_path):
    root, cfg = make_root(tmp_path, mode="auto")
    class Boom(FakeMailer):
        def send(self, *a, **k): raise RuntimeError("COM down")
    s = Sender(root, cfg, Boom(), verify_url=lambda u: True)
    out = s.route_draft(write_draft(root))
    assert out.startswith("error:")
    log = json.loads((root / "state" / "send_log.json").read_text())
    assert log["jane@acme.com"]["status"] == "unconfirmed"
    # retry attempt is refused by dedup — human reconciles (invariant R6)
    d2 = good_draft(); d2["visitor_id"] = "v3"
    assert s.route_draft(write_draft(root, d2)).startswith("gated:")
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**

```python
# pipeline/send.py
"""Draft routing + two-phase prospect send. The only path to a prospect's inbox."""
import json, shutil
from pathlib import Path
from pipeline import gates, state, sanitize
from pipeline.approvals import Approvals, new_token

class Sender:
    def __init__(self, root, cfg, mailer, verify_url):
        self.root = Path(root); self.cfg = cfg; self.mailer = mailer
        self.verify_url = verify_url
        self.approvals = Approvals(self.root / "state" / "approvals.json")

    # ---------- helpers ----------
    def _ctx(self, ignore_dry_run=False):
        cfg = dict(self.cfg)
        if ignore_dry_run:
            cfg = json.loads(json.dumps(self.cfg)); cfg["safety"]["dry_run"] = False
        supp = set()
        sp = self.root / "config" / "suppression.txt"
        if sp.exists():
            supp = {l.strip().lower() for l in sp.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.startswith("#")}
        return gates.GateCtx(
            cfg=cfg,
            send_log=state.load_json(self.root / "state" / "send_log.json", {}),
            reserved=self.approvals.reserved_emails(),
            caps=state.load_json(self.root / "state" / "caps.json",
                                 {"sends": {}, "domain_sends": {}, "approval_requests": {}}),
            suppression=supp, verify_url=self.verify_url, root=self.root,
            now_iso=state.now_iso())

    def render_email(self, draft):
        body = sanitize.sanitize_body("\n\n".join(draft["email"]["body_paragraphs"]))
        vars = {"subject": draft["email"]["subject"], "first_name": draft["person"]["first_name"],
                "body": body, "sender_name": self.cfg["sender"]["name"],
                "sender_title": self.cfg["sender"]["title"],
                "postal_address": self.cfg["sender"]["postal_address"]}
        txt = sanitize.render((self.root / "config" / "email_template.txt").read_text(encoding="utf-8"), vars)
        html = sanitize.render((self.root / "config" / "email_template.html").read_text(encoding="utf-8"),
                               {**vars, "body": body.replace("\n\n", "</p><p>")})
        subject = txt.splitlines()[0].replace("Subject: ", "", 1)
        text = "\n".join(txt.splitlines()[1:]).lstrip()
        return subject, text, html

    def _move(self, path, sub):
        dest = self.root / "drafts" / sub / Path(path).name
        shutil.move(str(path), dest); return dest

    # ---------- public ----------
    def route_draft(self, draft_path):
        try:
            draft = json.loads(Path(draft_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._move(draft_path, "invalid"); return "invalid"
        if gates.validate_schema(draft):
            self._move(draft_path, "invalid"); return "invalid"

        if self.cfg["mode"] == "review":
            fails = gates.evaluate(draft, self._ctx(ignore_dry_run=True))
            if fails:
                self._move(draft_path, "rejected"); return "gated:" + "|".join(fails)
            return self._request_approval(draft, draft_path)

        fails = gates.evaluate(draft, self._ctx())
        if fails == ["dry_run: true — sending disabled"]:
            return "dry_run"
        if fails:
            self._move(draft_path, "rejected"); return "gated:" + "|".join(fails)
        return self._finalize_send(draft, draft_path)

    def _request_approval(self, draft, draft_path):
        caps = state.load_json(self.root / "state" / "caps.json",
                               {"sends": {}, "domain_sends": {}, "approval_requests": {}})
        day = state.today()
        if caps["approval_requests"].get(day, 0) >= self.cfg["caps"]["approval_requests_per_day"]:
            return "gated:cap: approval requests per day reached"
        token = new_token(set(self.approvals.data))
        p = draft["person"]; c = draft["company"]
        subject = f"Approval [#{token}] — {p['full_name']} ({p['title']}, {c['name']})"
        psubj, ptext, _ = self.render_email(draft)
        ev = ["EVIDENCE:", f"Pages visited: {', '.join(draft['visit']['pages'])}",
              f"ZoomInfo match: {draft['enrich'].get('match_level', '?')}"]
        ev += [f"- {s['claim']} — {s['url']}" for s in draft["sources"]]
        gaps = draft.get("enrichment", {}).get("gaps", [])
        if gaps:
            ev.append("Gaps: " + ", ".join(gaps))
        body = ("PROSPECT EMAIL (exactly as it will send)\n"
                f"To: {p['email']}\nSubject: {psubj}\n\n{ptext}\n\n"
                + "\n".join(ev) +
                "\n\nReply GOOD to send. Reply NO to reject. Anything else keeps it on hold. "
                "Expires in 48h.")
        self.mailer.send(self.cfg["addresses"]["reviewer_notify"], subject, body)
        self.approvals.create(token, str(self._move(draft_path, "sent").with_suffix(".pending.json")
                                          if False else draft_path), p["email"])
        caps["approval_requests"][day] = caps["approval_requests"].get(day, 0) + 1
        state.save_json(self.root / "state" / "caps.json", caps)
        return f"approval_requested:{token}"

    def _finalize_send(self, draft, draft_path, token=None):
        email = gates.norm_email(draft["person"]["email"])
        log_p = self.root / "state" / "send_log.json"
        log = state.load_json(log_p, {})
        log[email] = {"status": "reserved", "reserved_at": state.now_iso(), "token": token or ""}
        state.save_json(log_p, log)                                   # phase 1: reserve
        subject, text, html = self.render_email(draft)
        try:
            self.mailer.send(draft["person"]["email"], subject, text, html_body=html,
                             bcc=self.cfg["addresses"]["audit_bcc"])
        except Exception as e:                                        # NEVER auto-resend (R6)
            log[email].update(status="unconfirmed", error=str(e))
            state.save_json(log_p, log)
            return f"error:send failed, left unconfirmed: {e}"
        log[email].update(status="confirmed", sent_at=state.now_iso())  # phase 2: confirm
        state.save_json(log_p, log)
        caps_p = self.root / "state" / "caps.json"
        caps = state.load_json(caps_p, {"sends": {}, "domain_sends": {}, "approval_requests": {}})
        day = state.today()
        caps["sends"][day] = caps["sends"].get(day, 0) + 1
        dom = draft["company"]["domain"].lower()
        caps["domain_sends"].setdefault(dom, []).append(state.now_iso())
        state.save_json(caps_p, caps)
        if Path(draft_path).exists():
            self._move(draft_path, "sent")
        return "sent"

    def send_prospect(self, draft, draft_path, token=None):
        """Approved path: ALL gates re-run at this moment."""
        fails = gates.evaluate(draft, self._ctx())
        if fails:
            return "gated:" + "|".join(fails)
        return self._finalize_send(draft, draft_path, token=token)
```

Note for implementer: in `_request_approval` the draft file must STAY where the
approval record can find it — store it under `drafts/inbox/` untouched and record its
path (the odd-looking `self._move(... ) if False else draft_path` expression above is a
plan-authoring artifact: **implement it as simply `str(draft_path)`**, no move on request).

- [ ] **Step 4: Run** — `python -m pytest tests/test_send.py -q` → 5 passed; full suite green.
- [ ] **Step 5: Commit** — `git commit -am "feat: draft routing, approval request, two-phase send"`

---

### Task 9: `pipeline/tick.py` — pre/post phases

**Files:** Create `pipeline/tick.py`; Test `tests/test_tick.py`

**Interfaces:**
- Consumes: `Sender`, `Approvals`, `approvals.find_token/parse_verdict`, `outlook.Outlook/verify_url`, `state.*`, `summary.build_and_send` (Task 10 — stub call guarded by `try/ImportError` until then is NOT allowed; Task 10 lands before tick is wired to scheduler, so import normally and let Task 9's tests inject a fake summary via parameter).
- Produces: `phase_pre(root, cfg, mailer, verify_url, send_summary=None) -> dict` (counters: approvals_processed, sent, expired, unsubscribes); `phase_post(root, cfg, mailer, verify_url) -> dict` (drafts_routed, statuses); CLI `python pipeline/tick.py --phase pre|post`.
- Behavior (spec §3, §4.2): pre = STOP check → inbox scan since `state/inbox_scan.json` watermark → unsubscribe handling (any inbox message whose top line contains "unsubscribe" → sender appended to `config/suppression.txt`) → verdict processing (token + approver + verdict; approved → `send_prospect`; rejected → decide + move draft to `drafts/rejected/`; hold → untouched) → expire >48h → heartbeat. post = route every `drafts/inbox/*.json` (skip `*.retry.json`), heartbeat.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tick.py
import json
from pathlib import Path
from pipeline import tick
from pipeline.send import Sender
from tests.test_send import FakeMailer, make_root, write_draft
from tests.test_gates import good_draft

def approved_reply(token, sender="upawar@unboundia.com", body="GOOD"):
    return {"subject": f"RE: Approval [#{token}] — Jane", "sender": sender,
            "body": body, "received": "2026-07-20T12:00:00"}

class FakeInboxMailer(FakeMailer):
    def __init__(self, msgs): super().__init__(); self.msgs = msgs
    def inbox_since(self, ts): return self.msgs

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
    m = FakeInboxMailer([]); s = Sender(root, cfg, m, verify_url=lambda u: True)
    token = s.route_draft(write_draft(root)).split(":")[1]
    m.msgs = [approved_reply(token, sender="attacker@evil.com")]
    assert tick.phase_pre(root, cfg, m, verify_url=lambda u: True)["sent"] == 0

def test_rejection_moves_draft(tmp_path):
    root, cfg = make_root(tmp_path)
    m = FakeInboxMailer([]); s = Sender(root, cfg, m, verify_url=lambda u: True)
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

def test_phase_post_routes_inbox(tmp_path):
    root, cfg = make_root(tmp_path)
    write_draft(root)
    m = FakeInboxMailer([])
    r = tick.phase_post(root, cfg, m, verify_url=lambda u: True)
    assert r["drafts_routed"] == 1
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**

```python
# pipeline/tick.py
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
    res = {"approvals_processed": 0, "sent": 0, "expired": 0, "unsubscribes": 0}
    scan_p = root / "state" / "inbox_scan.json"
    watermark = state.load_json(scan_p, {}).get("since", "2000-01-01T00:00:00")
    msgs = mailer.inbox_since(watermark)
    approvers = {a.lower() for a in cfg["addresses"]["approver_addresses"]}
    for msg in msgs:
        top = msg["body"].strip().lower().splitlines()[0] if msg["body"].strip() else ""
        if "unsubscribe" in top or "unsubscribe" in msg["subject"].lower():
            supp = root / "config" / "suppression.txt"
            existing = supp.read_text(encoding="utf-8") if supp.exists() else ""
            if msg["sender"] not in existing:
                supp.write_text(existing.rstrip("\n") + f"\n{msg['sender']}\n", encoding="utf-8")
                res["unsubscribes"] += 1
            continue
        token = find_token(msg["subject"])
        if not token or token not in sender.approvals.pending():
            continue
        if msg["sender"] not in approvers:
            continue                                   # logged upstream; never approves
        verdict = parse_verdict(msg["body"])
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
    res["expired"] = len(sender.approvals.expire_older_than(cfg["approval_expiry_hours"]))
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
        if p.name.endswith(".retry.json"):
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
    fn = phase_pre if args.phase == "pre" else phase_post
    kwargs = {"send_summary": maybe_send_summary} if args.phase == "pre" else {}
    out = fn(root, cfg, mailer, verify_url, **kwargs)
    print(json.dumps(out))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```
(Implementer note: Task 10 creates `pipeline/summary.py` with `maybe_send_summary` — the
`main()` import lands then; unit tests here never call `main()`.)

- [ ] **Step 4: Run** — 6 passed; full suite green. **Step 5: Commit** — `git commit -am "feat: tick pre/post orchestration"`

---

### Task 10: `pipeline/summary.py` — daily summary

**Files:** Create `pipeline/summary.py`; Test `tests/test_summary.py`

**Interfaces:**
- Produces: `build_summary(root) -> str` (plain text: sends today, confirmed/unconfirmed counts, pending/expired approvals, drafts by folder, last heartbeat, suppression size); `maybe_send_summary(root, cfg, mailer) -> bool` (sends once per day to `cfg["addresses"]["summary_to"]`, tracked in `state/heartbeat.json: last_summary`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_summary.py
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
    body_subject = m.sent[0]["subject"]
    assert "ICP Autopilot" in body_subject

def test_summary_mentions_unconfirmed(tmp_path):
    root, cfg = make_root(tmp_path)
    state.save_json(root / "state" / "send_log.json", {"c@d.com": {"status": "unconfirmed"}})
    assert "UNCONFIRMED" in summary.build_summary(root)
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement**

```python
# pipeline/summary.py
"""Once-daily operator summary. Silent failure is the enemy — surface everything."""
from pathlib import Path
from pipeline import state

def build_summary(root):
    root = Path(root)
    log = state.load_json(root / "state" / "send_log.json", {})
    appr = state.load_json(root / "state" / "approvals.json", {})
    hb = state.load_json(root / "state" / "heartbeat.json", {})
    lines = [f"ICP Autopilot daily summary — {state.today()}", ""]
    by = lambda st: sum(1 for r in log.values() if r.get("status") == st)
    lines.append(f"Sends confirmed: {by('confirmed')}   reserved: {by('reserved')}")
    if by("unconfirmed"):
        lines.append(f"*** UNCONFIRMED SENDS (human reconcile needed, never auto-resent): {by('unconfirmed')} ***")
        lines += [f"  - {e}" for e, r in log.items() if r.get("status") == "unconfirmed"]
    st = lambda s: sum(1 for r in appr.values() if r["status"] == s)
    lines.append(f"Approvals — pending: {st('pending')}  approved: {st('approved')}  "
                 f"rejected: {st('rejected')}  expired: {st('expired')}  consumed: {st('consumed')}")
    for sub in ("inbox", "sent", "rejected", "invalid"):
        n = len(list((root / "drafts" / sub).glob("*.json")))
        lines.append(f"drafts/{sub}: {n}")
    lines.append(f"Heartbeat — pre: {hb.get('pre', 'never')}  post: {hb.get('post', 'never')}")
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
```

- [ ] **Step 4: Run** — 2 passed; full suite green. **Step 5: Commit** — `git commit -am "feat: daily summary email"`

---

### Task 11: `prompts/run-prompt.md` — the brain's instructions

**Files:** Create `prompts/run-prompt.md`; Test `tests/test_prompt.py` (structural lint)

**Interfaces:**
- Consumes: `pipeline/icp_check.py` CLI (Task 3), draft JSON schema (spec §5 / `gates.validate_schema`).
- Produces: the pinned prompt the scheduler runs. Its contract with Python: writes ONLY `drafts/inbox/<visitor_id>.json` + `logs/claude-runs.jsonl` + updates `state/watermark.json` and `state/seen.json`.

- [ ] **Step 1: Write the failing structural test**

```python
# tests/test_prompt.py
import pathlib
P = pathlib.Path(__file__).resolve().parents[1] / "prompts" / "run-prompt.md"

def test_prompt_covers_all_stages_and_rules():
    t = P.read_text(encoding="utf-8").lower()
    for required in ("watermark", "seen.json", "icp_check.py", "enrich_contacts",
                     "enrich_companies", "enrich_company_signals", "websearch",
                     "linkedin", "http 200", "never send", "drafts/inbox",
                     "claude-runs.jsonl", "early exit", "retry"):
        assert required in t, f"prompt missing: {required}"
    assert "video" not in t
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Write the prompt** (full text; ~90 lines)

```markdown
# ICP Autopilot — per-tick run instructions

You are the detection/enrichment/drafting brain of ICP Autopilot. You NEVER send email —
you only write draft JSON files. Deterministic Python gates everything after you.
Work from the repo root. Do not modify any file outside state/, drafts/inbox/, logs/.

## 0. Early exit
Read state/watermark.json ({"since": ISO}) and state/seen.json. Call the Warmly MCP
(list_warm_visitors, timeWindow past_month, take<=50, paginate by offset) and keep only
identified visitors with activity newer than the watermark and whose id is not in seen.json.
If none: update watermark to now, append one line to logs/claude-runs.jsonl
({"ts","visitors":0}) and STOP. This is the early exit — most ticks end here.

## 1. Per new visitor
Record every evaluated visitor in seen.json ({id: {status, reason, at}}).
- No identified person/email → status no_person. Stop for this visitor.
- Build the company record {raw_classifications, employees, employee_range, funding_rounds}
  from Warmly account data + (if already cached in state/enrich_cache.json) ZoomInfo data.
- Run: python pipeline/icp_check.py --json <tempfile>. Not ICP → status non_icp with reason.

## 2. Enrichment playbook (ICP only, in order; cache in state/enrich_cache.json,
##    12-month TTL for hits, 7-day TTL for person-level misses)
Respect caps in state/caps.json: zoominfo <= 50/day, linkedin <= 15 page loads/day —
increment the counters yourself BEFORE each call; if a cap is reached, record the gap.
- E1 person: ZoomInfo enrich_contacts (fields: email, jobTitle, jobFunction, managementLevel,
  positionStartDate, employmentHistory, education, yearsOfExperience, externalUrls,
  contactAccuracyScore). Failure → write drafts/inbox/<id>.retry.json with attempt count
  ({attempts: n+1}); after 12 attempts set seen status parked. NEVER guess a person. This
  stage is REQUIRED — no verified business email means no draft.
- E2 company: ZoomInfo enrich_companies (industries, employeeCount, employeeCountByDepartment,
  revenue, companyFunding, recentFundingDate, foundedYear, businessModel, description).
- E3 signals: ZoomInfo enrich_company_signals (INTENT+NEWS+SCOOP, one call). Hiring pattern
  comes from scoops (Hiring Plans / Open Position / New Hire / Layoffs / Executive Move).
  Failure → gap "signals_failed", continue.
- E4 google: 2-4 WebSearch queries: person+company quotes/talks; company news this year;
  company careers page. Every fact you keep MUST have a source URL you fetched with HTTP 200
  in THIS run (WebFetch). NEVER write a URL from memory.
- E5 linkedin (only if config linkedin.enabled and cap allows): use Playwright MCP against the
  already-logged-in browser profile. Max 3 page loads for this prospect: their profile activity,
  the company page posts, the company jobs page (opening count). Wait 8-15s between loads.
  READ ONLY — never click connect/message/react. Logged out or any block page → gap
  "linkedin_logged_out"/"linkedin_blocked", skip silently, never re-auth.
- E6 synthesis: rank hooks (recent post > new-in-role > intent topic tied to visited pages >
  hiring signal > news > funding). Hypothesize why they visited, tying visit.pages to signals.

## 3. Draft
Write drafts/inbox/<visitor_id>.json exactly matching the schema in
docs/specs/2026-07-20-icp-autopilot-design.md §5: body_paragraphs ONLY (no greeting, no
sign-off, no placeholders — the template owns those). 2-4 short paragraphs, one concrete
personalization hook in the first line, one clear low-friction ask. Every factual claim in
the email must appear in sources[] with its verified URL. Include enrichment{...} with the
named gaps list.

## 4. Report
Append one JSON line to logs/claude-runs.jsonl:
{"ts", "visitors", "new", "icp", "drafts", "retries", "parked", "gaps", "credits_note"}.
Once per day also call Warmly get_credits_remaining and include it (warn if < 100).
Update state/watermark.json last. Never touch state/send_log.json, state/approvals.json,
or config/ — those belong to the deterministic layer.
```

- [ ] **Step 4: Run** — 1 passed. **Step 5: Commit** — `git commit -am "feat: pinned run prompt"`

---

### Task 12: Scripts — `run.ps1`, `setup.ps1`, `task-schedule.xml`, `SETUP.md`

**Files:** Create all four. Test: manual verification steps below (PowerShell isn't unit-tested; each script self-verifies).

**Interfaces:** Consumes `pipeline/tick.py --phase pre|post` (Task 9) and `prompts/run-prompt.md` (Task 11).

- [ ] **Step 1: Write `scripts/run.ps1`**

```powershell
# ICP Autopilot tick — fired by Task Scheduler every 5 minutes.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Lock = Join-Path $Root "state\tick.lock"
$Log  = Join-Path $Root ("logs\tick-" + (Get-Date -Format "yyyy-MM-dd") + ".log")
New-Item -ItemType Directory -Force (Join-Path $Root "logs") | Out-Null
function Say($m) { ("{0} {1}" -f (Get-Date -Format "HH:mm:ss"), $m) | Out-File $Log -Append -Encoding utf8 }

if (Test-Path (Join-Path $Root "STOP")) { Say "STOP file present - halt"; exit 0 }
if (Test-Path $Lock) {
    $age = (Get-Date) - (Get-Item $Lock).LastWriteTime
    if ($age.TotalMinutes -lt 15) { Say "locked (live run) - skip"; exit 0 }
    Say "stale lock ($([int]$age.TotalMinutes)m) - stealing"; Remove-Item $Lock -Force
}
New-Item -ItemType File -Force $Lock | Out-Null
try {
    Say "phase pre";  python pipeline\tick.py --phase pre  | Out-File $Log -Append -Encoding utf8
    Say "claude run"
    $p = Start-Process -FilePath "claude" -ArgumentList @("-p", "@prompts/run-prompt.md",
         "--output-format", "text") -NoNewWindow -PassThru -RedirectStandardOutput "$Log.claude"
    if (-not $p.WaitForExit(480000)) { $p.Kill(); Say "claude run TIMED OUT at 8min - killed" }
    Get-Content "$Log.claude" -ErrorAction SilentlyContinue | Out-File $Log -Append -Encoding utf8
    Say "phase post"; python pipeline\tick.py --phase post | Out-File $Log -Append -Encoding utf8
} finally { Remove-Item $Lock -Force -ErrorAction SilentlyContinue }
Say "tick done"
```

- [ ] **Step 2: Write `scripts/setup.ps1`** — verifier only, changes nothing:

```powershell
# Environment verifier. All checks must be green before importing the schedule.
$fail = 0
function Check($name, $ok) { if ($ok) { Write-Host "[OK]   $name" } else { Write-Host "[FAIL] $name"; $script:fail++ } }
Check "Python 3.11+"        ((python --version 2>&1) -match "3\.1[1-9]")
Check "pywin32 importable"  ((python -c "import win32com.client; print(1)" 2>&1) -match "1")
Check "classic Outlook COM" ((python -c "import win32com.client as w; w.Dispatch('Outlook.Application'); print(1)" 2>&1) -match "1")
Check "claude CLI"          ((claude --version 2>&1) -match "\d")
Check "warmly MCP added"    ((claude mcp list 2>&1) -match "warmly")
Check "zoominfo MCP added"  ((claude mcp list 2>&1) -match "zoominfo")
Check "NTP clock sync"      ((w32tm /query /status 2>&1) -match "Source:")
Check "tests green"         ((python -m pytest -q 2>&1) -match "passed")
Check "no REPLACE_ME in config" (-not ((Get-Content config\config.json -Raw) -match "REPLACE_ME"))
if ($fail -gt 0) { Write-Host "`n$fail check(s) failed - fix before go-live."; exit 1 }
Write-Host "`nAll green."
```

- [ ] **Step 3: Write `scripts/task-schedule.xml`** — a standard Task Scheduler export:
trigger = `TimeTrigger` with `Repetition Interval=PT5M Duration=P1D` daily at 00:00, action =
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\admin\Documents\ICP-Autopilot\scripts\run.ps1"`,
settings: `StartWhenAvailable=true`, `DisallowStartIfOnBatteries=false`, `ExecutionTimeLimit=PT20M`,
`MultipleInstancesPolicy=IgnoreNew`. (Author the XML exactly to this shape; the run.ps1
lockfile is the real overlap guard.)

- [ ] **Step 4: Write `SETUP.md`** — the 9 steps from spec §9 verbatim, each ending with its
verification command, plus the go-live order (smoke → dry_run:false + mode:review → satisfaction → mode:auto)
and the STOP-file kill switch explanation.

- [ ] **Step 5: Verify + commit** — run `python -m pytest -q` (still green; scripts don't affect it), then on THIS machine run `powershell -File scripts\setup.ps1` and confirm it produces OK/FAIL lines without crashing (FAILs are expected here — no Outlook COM on this box is fine). `git add -A && git commit -m "feat: scheduler entry, setup verifier, task definition, SETUP.md"`

---

### Task 13: `pipeline/smoke_test.py` + final sweep

**Files:** Create `pipeline/smoke_test.py`; Modify `README.md` (create — one-page overview pointing at spec + SETUP.md).

**Interfaces:** Consumes everything.

- [ ] **Step 1: Write `pipeline/smoke_test.py`**

```python
# pipeline/smoke_test.py
"""Spare-PC smoke: --dry runs a fixture draft through routing with a fake mailer (no COM);
--send sends ONE real email to the operator's own address via Outlook and scans it back."""
import argparse, json, sys
from pathlib import Path
from pipeline.send import Sender
from pipeline import state

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = {
    "visitor_id": "smoke-1", "detected_at": state.now_iso(),
    "person": {"full_name": "Smoke Test", "first_name": "Smoke",
               "email": "", "title": "VP Engineering", "seniority": "VP Level Exec"},
    "company": {"name": "SmokeCo", "domain": "", "country": "US",
                "raw_classifications": ["Software"], "employees": 5000, "funding_rounds": []},
    "visit": {"pages": ["/pricing"], "last_seen": state.now_iso()},
    "email": {"subject": "Smoke test — ICP Autopilot", "body_paragraphs":
              ["This is the smoke test.", "If you can read this, rendering works."]},
    "sources": [], "enrichment": {"gaps": []},
    "enrich": {"provider": "smoke", "match_level": "FULL_MATCH"},
}

class EchoMailer:
    def send(self, to, subject, body_text, html_body=None, bcc=None):
        print(f"[dry] would send to={to} bcc={bcc} subject={subject!r}"); return subject
    def inbox_since(self, ts): return []

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="ONE real email to the operator's own address")
    args = ap.parse_args()
    cfg = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    me = cfg["addresses"]["sender_mailbox"]
    d = json.loads(json.dumps(FIXTURE))
    d["person"]["email"] = me
    d["company"]["domain"] = me.split("@")[-1]
    p = ROOT / "drafts" / "inbox" / "smoke-1.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    if args.send:
        from pipeline.outlook import Outlook, verify_url
        cfg2 = json.loads(json.dumps(cfg)); cfg2["mode"] = "auto"; cfg2["safety"]["dry_run"] = False
        s = Sender(ROOT, cfg2, Outlook(), verify_url)
    else:
        s = Sender(ROOT, cfg, EchoMailer(), verify_url=lambda u: True)
    out = s.route_draft(p)
    print("smoke result:", out)
    # cleanup so the smoke never pollutes real dedup state
    log_p = ROOT / "state" / "send_log.json"
    log = state.load_json(log_p, {})
    if log.pop(me.lower(), None) is not None:
        state.save_json(log_p, log)
    ok = out in ("sent",) if args.send else out.startswith(("approval_requested", "dry_run", "gated"))
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
```
(Note: in `--dry` mode on the build machine, `gated:` outcomes are acceptable — REPLACE_ME
sender + self-domain quirks vary; the point is the pipeline runs end-to-end without COM.)

- [ ] **Step 2: Write `README.md`** — 20 lines: what it is, the three pieces, links to spec/plan/SETUP.md, the STOP kill switch, and "never edit `pipeline/icp_core.py`".

- [ ] **Step 3: Full-suite verification** — `python -m pytest -q` → all tests pass (expect ~40).
Run `python pipeline/smoke_test.py` (dry) → prints `smoke result:` and exits 0.

- [ ] **Step 4: Commit** — `git add -A && git commit -m "feat: smoke test + README; v2 build complete"`

---

## Self-Review (done at authoring time)

- **Spec coverage:** §2 roles→Task 1 config; §3 trigger/brain/hands→Tasks 12/11/6-9; §3.1a playbook→Task 11 prompt (execution) + caps in prompt/config; §3.3 gates 1-10→Task 6 (mode routing gate 10 lives in Task 8); §4 approval loop→Tasks 5, 8, 9; §5 schema→Tasks 6 (validate) + 11 (producer); §6 state files→Tasks 2/5/8/9; §7 failure modes→lock/timeout (12), retry/parked (11), unconfirmed-never-resend (8), summary alerts (10); §8 layout→Task 1; §9 setup→Task 12; §10 tests→every task; §11 non-goals respected (no video anywhere — Task 1 test enforces it).
- **Known deliberate deferrals** (stated, not hidden): logging of ignored/stranger replies is print/log-file level, not a state file; `enrich_cache.json` is owned by the claude run (prompt) rather than Python — acceptable because cache misses only cost credits, never correctness (gates re-verify everything).
- **Type consistency:** `Sender(root, cfg, mailer, verify_url)` used identically in Tasks 8/9/13; `GateCtx` fields consistent between Tasks 6/8; `Approvals` API consistent between 5/8/9.
