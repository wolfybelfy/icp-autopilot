"""Draft routing + two-phase prospect send. The only path to a prospect's inbox."""
import json, shutil
from pathlib import Path
from pipeline import gates, state, sanitize
from pipeline.approvals import Approvals, new_token

class Sender:
    def __init__(self, root, cfg, mailer, verify_url):
        self.root = Path(root)
        self.cfg = cfg
        self.mailer = mailer
        self.verify_url = verify_url
        self.approvals = Approvals(self.root / "state" / "approvals.json")

    # ---------- helpers ----------
    def _ctx(self, ignore_dry_run=False):
        cfg = self.cfg
        if ignore_dry_run:
            cfg = json.loads(json.dumps(self.cfg))
            cfg["safety"]["dry_run"] = False
        supp = set()
        sp = self.root / "config" / "suppression.txt"
        if sp.exists():
            supp = {l.strip().lower() for l in sp.read_text(encoding="utf-8").splitlines()
                    if l.strip() and not l.startswith("#")}
        return gates.GateCtx(
            cfg=cfg,
            send_log=state.load_json(self.root / "state" / "send_log.json", {}),
            reserved=self.approvals.reserved_emails(),
            caps=self._caps(),
            suppression=supp, verify_url=self.verify_url, root=self.root,
            now_iso=state.now_iso())

    def _caps(self):
        return state.load_json(self.root / "state" / "caps.json",
                               {"sends": {}, "domain_sends": {}, "approval_requests": {}})

    def render_email(self, draft):
        body = sanitize.sanitize_body("\n\n".join(draft["email"]["body_paragraphs"]))
        vars = {"subject": draft["email"]["subject"],
                "first_name": draft["person"]["first_name"],
                "body": body, "sender_name": self.cfg["sender"]["name"],
                "sender_title": self.cfg["sender"]["title"],
                "postal_address": self.cfg["sender"]["postal_address"]}
        txt = sanitize.render(
            (self.root / "config" / "email_template.txt").read_text(encoding="utf-8"), vars)
        html = sanitize.render(
            (self.root / "config" / "email_template.html").read_text(encoding="utf-8"),
            {**vars, "body": body.replace("\n\n", "</p><p>")})
        subject = txt.splitlines()[0].replace("Subject: ", "", 1)
        text = "\n".join(txt.splitlines()[1:]).lstrip()
        return subject, text, html

    def _move(self, path, sub):
        dest = self.root / "drafts" / sub / Path(path).name
        shutil.move(str(path), dest)
        return dest

    # ---------- public ----------
    def route_draft(self, draft_path):
        try:
            draft = json.loads(Path(draft_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._move(draft_path, "invalid")
            return "invalid"
        if gates.validate_schema(draft):
            self._move(draft_path, "invalid")
            return "invalid"

        if self.cfg["mode"] == "review":
            fails = gates.evaluate(draft, self._ctx(ignore_dry_run=True))
            if fails:
                self._move(draft_path, "rejected")
                return "gated:" + "|".join(fails)
            return self._request_approval(draft, draft_path)

        fails = gates.evaluate(draft, self._ctx())
        if fails == ["dry_run: true - sending disabled"]:
            return "dry_run"
        if fails:
            self._move(draft_path, "rejected")
            return "gated:" + "|".join(fails)
        return self._finalize_send(draft, draft_path)

    def _request_approval(self, draft, draft_path):
        caps = self._caps()
        day = state.today()
        if caps["approval_requests"].get(day, 0) >= self.cfg["caps"]["approval_requests_per_day"]:
            return "gated:cap: approval requests per day reached"
        token = new_token(set(self.approvals.data))
        p, c = draft["person"], draft["company"]
        subject = f"Approval [#{token}] - {p['full_name']} ({p['title']}, {c['name']})"
        psubj, ptext, _ = self.render_email(draft)
        ev = ["EVIDENCE:", f"Pages visited: {', '.join(draft['visit']['pages'])}",
              f"ZoomInfo match: {draft['enrich'].get('match_level', '?')}"]
        ev += [f"- {s['claim']} -- {s['url']}" for s in draft["sources"]]
        gaps = draft.get("enrichment", {}).get("gaps", [])
        if gaps:
            ev.append("Gaps: " + ", ".join(gaps))
        body = ("PROSPECT EMAIL (exactly as it will send)\n"
                f"To: {p['email']}\nSubject: {psubj}\n\n{ptext}\n\n"
                + "\n".join(ev) +
                "\n\nReply GOOD to send. Reply NO to reject. Anything else keeps it on hold. "
                "Expires in 48h.")
        self.mailer.send(self.cfg["addresses"]["reviewer_notify"], subject, body)
        # Rename so the next tick's phase_post cannot re-route it into a duplicate request.
        src = Path(draft_path)
        pending = src.with_name(src.stem + ".pending.json")
        src.rename(pending)
        self.approvals.create(token, str(pending), p["email"])
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
        caps = self._caps()
        day = state.today()
        caps["sends"][day] = caps["sends"].get(day, 0) + 1
        dom = draft["company"]["domain"].lower()
        caps["domain_sends"].setdefault(dom, []).append(state.now_iso())
        state.save_json(self.root / "state" / "caps.json", caps)
        if Path(draft_path).exists():
            self._move(draft_path, "sent")
        return "sent"

    def send_prospect(self, draft, draft_path, token=None):
        """Approved path: ALL gates re-run at this moment. The approval's own
        reservation must not block its own send, so it is excluded from dedup."""
        ctx = self._ctx()
        if token and token in self.approvals.data:
            ctx.reserved = ctx.reserved - {self.approvals.data[token]["recipient"]}
        fails = gates.evaluate(draft, ctx)
        if fails:
            return "gated:" + "|".join(fails)
        return self._finalize_send(draft, draft_path, token=token)
