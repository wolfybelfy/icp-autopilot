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
        fails.append("dry_run: true - sending disabled")
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
