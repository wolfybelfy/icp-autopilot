# ICP Autopilot

Real-time-ish (≤10 min) website-visitor → ICP check → deep enrichment → personalized
email pipeline, running unattended on a spare Windows PC. Replaces the abandoned
`Website data/Fully-Automated System` (v1).

## The three pieces

1. **Trigger** — Windows Task Scheduler fires `scripts/run.ps1` every 5 minutes
   (lockfile-guarded, 8-min claude timeout, no always-on service).
2. **Brain** — `claude -p prompts/run-prompt.md`: Warmly detection, deterministic ICP
   check (`pipeline/icp_check.py`), ZoomInfo person/company/signals enrichment, Google +
   LinkedIn research, draft JSON to `drafts/inbox/`. **Never sends anything.**
3. **Hands** — `pipeline/tick.py` (pre/post): reply-to-approve loop over Outlook,
   deterministic hard gates re-checked at send time, two-phase Outlook COM send with BCC
   audit, daily summary.

## Operate

- **Kill switch:** create a file named `STOP` here → halts within one tick. Delete to resume.
- **Modes:** `config/config.json → mode: "review"` (director replies GOOD/NO to approval
  emails) or `"auto"` (same gates, no human detour). Ships `review` + `dry_run: true`.
- **Deploy:** follow `SETUP.md` top to bottom. Design: `docs/specs/`, plan: `docs/superpowers/plans/`.
- **Tests:** `python -m pytest -q` (all green required before any change lands).

## Do not

- Edit `pipeline/icp_core.py` — it is a verbatim copy of the parent project's canonical
  ICP logic; re-sync by copy only.
- Weaken any gate in `pipeline/gates.py` "to make it send".
- Touch the parent `Website data/` batch pipeline from here.
