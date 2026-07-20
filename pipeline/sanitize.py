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
