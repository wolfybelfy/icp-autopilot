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
