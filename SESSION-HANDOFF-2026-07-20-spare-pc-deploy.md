# Session Handoff — 2026-07-20 — Spare-PC Deployment of ICP Autopilot (v2)

## Intent
Deploy `ICP-Autopilot` (built earlier today, 55 tests green, repo
`https://github.com/wolfybelfy/icp-autopilot`, HEAD `9fb4382`) on the operator's
**Windows 10 spare PC** at `C:\Users\admin\Documents\ICP automate system\ICP-Autopilot`.
System: Task Scheduler every 5 min → `scripts/run.ps1` → `claude -p prompts/run-prompt.md`
(Warmly detect → ICP check → ZoomInfo/Google enrich → draft JSON) → `pipeline/tick.py`
(reply-to-approve over Outlook COM). `dry_run: true`, `mode: review` — nothing sends to
prospects yet. Hard directive this session: **no more account lockouts/bans** — one auth
attempt max, stop on failure.

## Issues faced → resolutions (in order)

1. **ZoomInfo account LOCKED** — user-scoped `zoominfo` MCP browser OAuth on the new PC
   rejected a correct OTP repeatedly (likely clock skew — NTP check was failing then) and
   locked the account. *Resolution:* abandoned local ZoomInfo OAuth entirely. The
   **claude.ai ZoomInfo connector** is account-level, arrives pre-authenticated on any PC
   signed into the Claude account (21 tools incl. enrich_contacts/enrich_companies/
   enrich_company_signals). Removed stale entry: `claude mcp remove zoominfo -s user`.
   Account unlock (email link / license admin) is a background errand, not a blocker.
   ⚠️ Headless availability of the claude.ai connector on the spare PC is still
   UNVERIFIED (earlier "21 tools" evidence was interactive `/mcp`, not `claude -p`).
2. **PowerShell execution policy** — `powershell -File ...` blocked. *Resolution:* use
   `powershell -ExecutionPolicy Bypass -File ...` (task XML already carries Bypass).
3. **Outlook COM "Server execution failed"** during `smoke_test.py --send` — ran from an
   **admin** PowerShell; COM can't cross elevation. *Resolution:* run everything from a
   normal window. `--send` then succeeded (email received).
4. **Task XML wrong path** — hardcoded `Documents\ICP-Autopilot`; real clone is under
   `ICP automate system\`. *Resolution:* user edited the two path lines before
   `schtasks /Create`. Task installed as `ICP-Autopilot-Tick`.
5. **First tick: `phase pre` crash** — `AttributeError: <unknown>.ReceivedTime` on a
   non-mail inbox item. *Fix `e2d03b7`:* `outlook.inbox_since` skips non-olMail items,
   per-item try/except.
6. **Smoke fixture leak** — the crashed `--send` left `smoke-1.json` in `drafts/inbox`;
   a real tick picked it up and emailed a real approval request `[#10A0D8]` to all
   reviewers. *Fix `e2d03b7`:* smoke cleanup moved to `finally`. Pending action: operator
   replies **NO** (plain Reply, not Reply-All — goes only to own mailbox) to exercise the
   rejection path. Testers' replies were correctly counted as `ignored_strangers` —
   approver security works.
7. **Headless claude stalled on permission prompts** (Warmly tool call waiting for
   approval nobody can click). *Fix `e2d03b7`:* `.claude/settings.json` allow-list —
   insufficient. *Fix `862d49b`:* rules rewritten to `Edit(path)` form (CLI ignores
   `Write(path)` deny rules). Still stalled →
8. **ROOT CAUSE (proven by experiment on build machine):** an **untrusted workspace does
   not load user-scoped MCP servers at all** in `claude -p` and ignores settings.json.
   Same Warmly call: untrusted folder → server absent; trusted folder → returned real
   credits (5202). *Fix `9fb4382`:* (a) `run.ps1` passes `--allowedTools
   "mcp__warmly,mcp__claude_ai_ZoomInfo,WebSearch,WebFetch,Read,Glob,Grep,Write,Edit,
   Bash(python:*),Bash(py:*)"` — honored regardless of trust; (b) new
   `scripts/trust-workspace.ps1` sets `hasTrustDialogAccepted` for the repo's resolved
   path in `~/.claude.json` (backs it up first); (c) `setup.ps1` gained check
   "workspace trusted (headless)"; (d) SETUP.md updated.
9. **Config changes on request:** reviewer_notify/audit_bcc briefly included 3 testers
   (snikhare, gpf, akaderkutty @unboundia.com), then reverted to **upawar only**.
   `approver_addresses` was always only upawar. `linkedin.enabled: false` (deliberate —
   highest ban-risk stage stays off until the rest is proven). Sender REPLACE_ME fields
   filled. Never commit repo-side changes to `config/config.json` (would clobber local).

## Current state / where we're stuck
- Spare-PC verifier: **9/10 OK** (incl. trust, both MCPs Connected, NTP now OK).
- **STUCK ON: `[FAIL] tests green`.** Diagnosis pending — operator to run
  `py -3 -m pytest -q` and paste output. Prime suspect: spare PC has BOTH Python 3.12 and
  3.13 (seen in tracebacks); requirements were likely pip-installed into one while
  `py -3` runs the other → `No module named pytest`. Likely fix:
  `py -3 -m pip install -r requirements.txt`. If instead real test failures → code-level
  3.13 issue, fix in repo.

## Next steps (ordered)
1. Resolve pytest failure → re-run verifier → **All green.**
2. Reply **NO** to `Approval [#10A0D8]` (plain Reply) → `schtasks /Run /TN
   ICP-Autopilot-Tick` → log must show `approvals_processed: 1`, no permission stalls,
   clean `claude run` (Warmly read works).
3. Verify ZoomInfo headless on spare PC: `claude -p "List the names of every ZoomInfo
   tool available to you. Do not call any."` — if absent headless, visitors park as
   `.retry.json` (safe); fallback plan = ZoomInfo REST creds.
4. Watch two scheduled ticks; keep PC logged in, sleep disabled.
5. When drafts look good: `dry_run: false` (keep review mode). Director's address into
   `reviewer_notify` + `approver_addresses` when provided. Much later: `mode: "auto"`.
6. Old v1 folder (`Website data\Fully-Automated System\` and the spare-PC
   `fully-automated-system` clone) — delete only after operator confirms.

## Standing rules
Kill switch = `STOP` file in repo root. One auth attempt max, stop on failure. Never
weaken gates/caps. `pipeline/icp_core.py` stays a verbatim copy. Evidence discipline per
parent CLAUDE.md — no assumptions, no URLs from memory.
