# ICP Autopilot v2 — Design Spec

**Date:** 2026-07-20 (absolute; never trust the machine clock — it has been observed behind)
**Status:** Approved design, pre-implementation
**Location:** `C:\Users\admin\Documents\ICP-Autopilot\` (standalone; replaces
`Website data\Fully-Automated System\`, which stays untouched until v2 passes its smoke
test and the operator explicitly confirms deletion)

---

## 1. Purpose

When a website visitor is identified (Warmly) and qualifies as ICP, produce a deeply
personalized, evidence-backed email within ~10 minutes and route it through a human
approval loop (reply-to-approve over email). Once trust is established, one config flip
(`mode: "review"` → `"auto"`) makes the same pipeline fully automatic. Runs unattended on
the spare always-on Windows PC.

### Why v1 failed (and what this design removes)
v1 was code-complete (80 tests) but died at **deployment**: an always-on service, a FastAPI
approval web app, a public HTTPS tunnel, Resend DNS/DKIM verification, a blocked ZoomInfo
headless OAuth, and six ordered human/IT blockers. v2 removes every one of those:

| v1 dependency | v2 replacement |
|---|---|
| Always-on Python service (`run_all.py`) | Task Scheduler fires a short-lived run every 5 min |
| FastAPI approval app + public tunnel | Reply-to-approve over Outlook email |
| Resend + DNS/DKIM verification | Outlook COM send from a real signed-in mailbox |
| ZoomInfo headless OAuth (blocked by vendor allowlist) | ZoomInfo MCP inside `claude -p` (interactive OAuth once, reused) |
| Graph/Entra app registration | Not needed — Outlook session is the auth |

---

## 2. Roles & addresses

| Role | Who | What they do |
|---|---|---|
| Sender mailbox | **Sales director** (address TBD — config `sender_mailbox`; until provided, build/test runs on `upawar@unboundia.com`) | Signed into classic Outlook on the spare PC. All approval requests and prospect emails originate from this mailbox. |
| Approval notification recipient | **Sales director only** | Receives one approval email per draft; replies GOOD/NO. |
| Approvers (whose replies count) | **Sales director AND `upawar@unboundia.com`** | Either address may approve/reject. Nobody else — enforced by sender-address verification. |
| Auditor | `upawar@unboundia.com` | NOT in the approval loop. Audits via: BCC copy of every prospect send, `state/` files, `logs/`, and the daily summary email. |

Config keys: `reviewer_notify` (director), `approver_addresses` (list: director + upawar),
`audit_bcc` (upawar), `summary_to` (upawar).

**Known gap, stated, not hidden:** the sales director's email address was never provided in
v1 and is still unknown. It is a required config value. Until filled, `reviewer_notify`
and the Outlook profile default to upawar's own account so nothing blocks the build.

---

## 3. Architecture — three pieces, no services

```
Windows Task Scheduler ── every 5 min ──> scripts\run.ps1
  run.ps1:
    0. Acquire lockfile (skip run if a live one exists; steal if stale >15 min)
    1. python pipeline\tick.py --phase pre     ← deterministic: kill switch, approvals inbox scan,
    │                                             send approved drafts, expire stale approvals,
    │                                             retry queued sends, daily summary (once/day)
    2. claude -p prompts\run-prompt.md         ← the brain: Warmly poll → ICP gate → ZoomInfo
    │    (timeout 8 min, killed if exceeded)      enrich → web research → draft JSON to drafts\inbox\
    3. python pipeline\tick.py --phase post    ← deterministic: validate new drafts, re-run all
                                                  gates, create approval requests (mode=review)
                                                  or send (mode=auto)
```

**Invariant: the model never touches the mailbox.** All Outlook COM reads/writes live in
Python (`pipeline/`). Claude's only output channel is JSON files in `drafts\inbox\`.
`send.py` trusts nothing in those files — it independently re-verifies every gate.

### 3.1 The brain — `claude -p` run (Phase 2)

Same proven pattern as the parent project's `automation/daily_run.py`. The prompt file
instructs the session to:

1. Read `state/watermark.json` + `state/seen.json`.
2. Call Warmly MCP (`list_warm_visitors`, `list_warm_accounts` — free reads, `take ≤ 50`,
   paginate by offset) for activity since the watermark. **Early exit:** if no new
   identified visitors, update watermark and stop (keeps 288 runs/day cheap).
3. For each new visitor: run `python pipeline\icp_check.py --json <raw>` — a **verbatim
   copy** of the parent smart-play ICP logic (scan ALL industry classifications across
   ZoomInfo tops+subs and Warmly industry+subIndustry; ICP = industry-ICP AND
   (employees ≥ 1000 OR funding Series A–F+)). Deterministic Python — never model judgment.
   Non-ICP → record in `seen.json` with reason, stop there.
4. For ICP visitors with an identified person: enrich via **ZoomInfo MCP** (person title,
   seniority, verified email, company firmographics). Enrichment failure → write a
   `retry` marker, not a guess.
5. Live web research: the pages they visited (from Warmly), company site, recent news.
   **Every URL that will appear in the email must be fetched HTTP 200 in this run. No URL
   is ever written from memory** (parent evidence-discipline rule, inherited verbatim).
6. Draft the email as body paragraphs + subject. Every factual claim carries a source.
   Select the video URL by visited-page rules from `config/page_video_map.json`.
7. Write one JSON file per prospect to `drafts\inbox\<visitor_id>.json` (schema in §5).
8. Append a machine-readable run report to `logs/claude-runs.jsonl` (visitors seen, ICP
   count, drafts written, enrich failures) — the daily summary is built from this.

Allowed tools for the headless session: Warmly MCP, ZoomInfo MCP, WebFetch/WebSearch,
Read/Write (project dir only), Bash restricted to `python pipeline\icp_check.py`.

### 3.2 The hands — `pipeline/` Python (Phases 1 & 3)

`tick.py` orchestrates; `send.py` is the **only** module that can send email. Modules:

- `outlook.py` — thin COM wrapper (pywin32): send mail (To/BCC/HTML body), scan Inbox
  since last scan, resolve true SMTP sender address via `PropertyAccessor`
  (`PR_SMTP_ADDRESS`) because `SenderEmailAddress` may be an Exchange DN.
- `gates.py` — every hard gate as a pure function (unit-testable, no COM).
- `approvals.py` — approval lifecycle (see §4).
- `state.py` — atomic JSON read/write (write temp + `os.replace`), daily rolling backup of
  `state/` to `state/backup/`.
- `send.py` — gate check → send → log. Two-phase: reserve in `send_log` → COM send →
  confirm. A send that errors after reserve stays **unconfirmed** and is surfaced in the
  summary for human reconciliation — **never auto-resent** (v1 invariant R6, kept).
- `icp_check.py` — verbatim smart-play copy with provenance header. Kept in sync with the
  parent by copy; never "improved" here.
- `summary.py` — one daily email to `summary_to`: sends, approvals pending/expired,
  enrich failures, gate rejections, unconfirmed sends, credit warnings.
- `smoke_test.py` — end-to-end dry test + one real send-to-self test.

### 3.3 Hard gates (re-checked deterministically at every send, model never trusted)

All must pass, else the draft is rejected/queued — never "relaxed to make it send":

1. `STOP` file absent (kill switch — drop a file named `STOP` in the project root to halt
   all sending within one tick; delete to resume).
2. `dry_run: false` (ships as `true`; flipped only after the smoke test).
3. Draft JSON schema valid; required fields present and non-empty.
4. **ICP re-verified**: `icp_check.py` re-run on the raw classification data embedded in
   the draft (the model cannot mislabel a company into the pipeline).
5. Recipient email: valid format, not on `config/suppression.txt`, domain matches the
   prospect's company domain (no free-mail sends).
6. **Absolute dedup**: normalized recipient email not in `send_log.json` and not reserved
   by any pending approval. One person is never emailed twice, ever.
7. Caps: ≤ 10 prospect sends/day; ≤ 2 sends/domain/rolling-7-days; ≤ 20 approval
   requests/day (protects the director's inbox).
8. Geo: company country US-only (config `geo_allowlist`; initial default `["US"]`).
9. **Every link in the email re-verified HTTP 200 at send time** (not just at draft time —
   hours may have passed during approval).
10. Mode routing: `review` → approval request; `auto` → direct send.

---

## 4. Approval loop (mode = "review")

### 4.1 Request
For each gated-and-valid draft, `approvals.py`:
- Generates a unique 6-hex-char token, e.g. `[#A7F3B2]` (collision-checked against all
  historical tokens).
- Sends ONE email from the sender mailbox to `reviewer_notify` (director):
  - **Subject:** `Approval [#A7F3B2] — <Full Name> (<Title>, <Company>)`
  - **Body:** the prospect email exactly as it will be sent (subject + rendered body +
    video link), then the evidence block (pages visited, ZoomInfo match level, each claim
    with its source URL), then: *"Reply GOOD to send. Reply NO to reject. Anything else
    keeps it on hold. Expires in 48h."*
- Records `{token, draft, status: "pending", requested_at}` in `state/approvals.json`.
  The recipient email is **reserved** in dedup from this moment.
- If the approval email itself fails to send (Outlook down), status = `notify_pending`,
  retried next tick; the token stays reserved.

### 4.2 Response collection (every tick, Phase 1)
Scan the sender mailbox Inbox (only messages newer than the last scan watermark) for
subjects containing `[#` + a known pending token. For each match, three independent checks:

1. **Token** maps to a `pending` approval (already-consumed tokens are ignored + logged).
2. **True SMTP sender** ∈ `approver_addresses` (director or upawar). A forwarded reply
   from anyone else is ignored and logged — it can never approve.
3. **Verdict parse:** strip quoted original (split on `-----Original Message-----`,
   `From:`, `On … wrote:` separators; HTML converted to text first), drop empty lines and
   mobile signatures (`Get Outlook for iOS` etc.), then look for a whole-word verdict in
   the first 5 remaining lines:
   - `GOOD` / `SEND` / `YES` / `APPROVE` (case-insensitive) → **approved**
   - `NO` / `REJECT` / `SKIP` → **rejected**
   - Both present, or neither → **hold**: status unchanged, flagged in the daily summary.
     **Ambiguity never sends.**

### 4.3 Outcomes
- **Approved** → all §3.3 gates re-run at this moment → send to prospect with BCC to
  `audit_bcc` → status `consumed` (a second GOOD can never double-send) → logged in
  `send_log.json`.
- **Rejected** → status `rejected`, draft preserved in `drafts\rejected\` for learning;
  recipient's dedup reservation **kept** (a rejected person is not re-drafted later unless
  the operator manually clears them — prevents nag loops).
- **Expired (48 h)** → status `expired`, reservation kept, listed in the daily summary.
- **Edits are not supported by design** (stated limitation): approve-as-is or reject. If
  editing proves necessary in practice, a Drafts-folder review mode is the planned add-on,
  not a v2 scope item.

### 4.4 Mode flip
`config.json: "mode": "review" | "auto"`. In `auto`, Phase 3 skips §4.1 and sends
directly (all gates identical). Nothing else changes. Flip only after the operator is
satisfied with review-mode output.

---

## 5. Draft JSON contract (`drafts\inbox\<visitor_id>.json`)

```json
{
  "visitor_id": "…",                      // Warmly key — dedup vs seen.json
  "detected_at": "2026-07-20T09:14:00Z",  // from Warmly data, not local clock
  "person":  { "full_name": "", "first_name": "", "email": "", "title": "", "seniority": "" },
  "company": { "name": "", "domain": "", "country": "",
               "raw_classifications": [...],   // verbatim source data → gate #4 re-check
               "employees": 0, "funding_rounds": [...] },
  "visit":   { "pages": [...], "last_seen": "" },
  "email":   { "subject": "", "body_paragraphs": ["", ""] },   // paragraphs ONLY —
                                                               // template owns greeting/sign-off/footer
  "video_url": "",
  "sources": [ { "claim": "", "url": "" } ],   // every URL verified 200 in the drafting run
  "enrich":  { "provider": "zoominfo_mcp", "match_level": "FULL_MATCH" }
}
```

`config/email_template.html` owns the greeting (`Hi {first_name},`), video paragraph,
sign-off/signature, and compliance footer (postal address + unsubscribe line). `send.py`
sanitizes body paragraphs — strips any greeting/sign-off/placeholder the model added
anyway (v1's locked template contract, kept, with its regression tests ported).

---

## 6. State files (`state\`, all atomic-write, daily backup)

| File | Contents |
|---|---|
| `watermark.json` | Last Warmly poll cursor |
| `seen.json` | Every visitor ever evaluated: `{visitor_id: {status, reason, at}}` — statuses: `non_icp`, `no_person`, `drafted`, `retry` (with attempt count), `parked` |
| `approvals.json` | Full approval lifecycle records |
| `send_log.json` | Absolute dedup: normalized email → `{sent_at, message_id, status: reserved/confirmed/unconfirmed}` |
| `caps.json` | Daily/rolling counters (self-pruning) |
| `heartbeat.json` | Last successful tick per phase — staleness drives alerts |
| `inbox_scan.json` | Inbox scan watermark |

`retry` items get up to 12 attempts (~1 h at 5-min cadence), then `parked` + surfaced in
the summary — never silently dropped, never guessed.

---

## 7. Failure modes & handling (explicit, none silent)

| Failure | Handling |
|---|---|
| Previous run still going | Lockfile → skip this tick. Lock older than 15 min → considered stale (crashed run), stolen with a log line. |
| `claude -p` hangs | run.ps1 kills at 8 min; visitors untouched → next tick retries. |
| ZoomInfo MCP token expired | Enrich fails → `retry` → `parked` after 12 attempts → daily summary says "enrichment failing since <time>, re-auth needed". Never silent. |
| Warmly MCP failure | Run exits with no watermark advance; retried next tick. |
| Outlook not running / COM error | `outlook.py` attempts to start Outlook; on failure the send stays queued, retried next tick, summary alert after 3 consecutive failures. |
| Send errors after reservation | `unconfirmed` in send_log; **never auto-resent**; human reconciles by message-id (summary shows it). |
| Ambiguous approval reply | Hold + flag. Never guess. |
| Reply from a non-approver | Ignored + logged. |
| Duplicate GOOD replies | Token already `consumed` → ignored. |
| State file corruption | Atomic writes prevent partial files; daily backups in `state\backup\` allow restore. |
| Machine clock wrong | Setup step: verify NTP sync (`w32tm /query /status`). Caps/expiry use local time and depend on it. Timestamps in data come from source platforms where available. |
| "New Outlook" instead of classic | **Hard requirement:** classic Outlook (COM automation does not work in New Outlook). `setup.ps1` verifies `Outlook.Application` COM registration and fails loudly if absent. |
| AV/Outlook programmatic-access prompt | If COM sends trigger a security prompt, setup doc covers the fix (up-to-date AV detection or the ObjectModelGuard policy). Detected in smoke test, not in production. |
| Subscription usage (288 runs/day) | Early-exit prompt keeps no-visitor runs to one Warmly call. Config `active_hours` (e.g. business hours ± buffer) can restrict the schedule if usage bites. |
| Warmly identification credits | Poll `get_credits_remaining` once/day in the claude run; summary warns < 100 (v1 rule, kept). |

---

## 8. Directory layout

```
ICP-Autopilot\
├── SETUP.md                    # ~8 steps, spare-PC deployment
├── STOP                        # (absent normally) kill switch — presence halts sending
├── config\
│   ├── config.json             # mode, caps, geo, addresses, active_hours, dry_run
│   ├── email_template.html/.txt
│   ├── page_video_map.json     # 5 video URLs — operator-supplied, REQUIRED before go-live
│   └── suppression.txt
├── prompts\run-prompt.md       # the pinned claude -p prompt
├── pipeline\                   # tick.py, send.py, gates.py, approvals.py, outlook.py,
│                               # state.py, icp_check.py, summary.py, smoke_test.py
├── scripts\
│   ├── run.ps1                 # the Task Scheduler entry point
│   ├── setup.ps1               # environment verifier (python, pywin32, classic Outlook COM,
│   │                           # claude CLI + MCPs, NTP)
│   └── task-schedule.xml       # importable Task Scheduler definition (every 5 min)
├── drafts\inbox\ | sent\ | rejected\ | invalid\
├── state\  logs\  docs\specs\  tests\
```

---

## 9. Setup on the spare PC (`SETUP.md`, verified by `setup.ps1`)

1. Install Python 3.11+ and `pip install pywin32 pytest`.
2. Install **classic** Outlook; sign in the sender mailbox (director's account; upawar's
   during build). Confirm mail flows manually once.
3. Install Claude Code CLI; sign in (subscription login, no API key anywhere).
4. `claude mcp add` Warmly and ZoomInfo (HTTP transport; one-time `/mcp` browser auth
   each). Exact URLs come from the live account/v1 scripts at setup time — **never written
   from memory into config**.
5. Copy the `ICP-Autopilot` folder; run `scripts\setup.ps1` — must end all-green.
6. Fill required config: director's address, `page_video_map.json` video URLs, postal
   address for the footer.
7. `python pipeline\smoke_test.py` — dry pipeline pass, then one real send-to-self.
8. Import `task-schedule.xml`; watch two ticks in `logs\`; leave `dry_run: true` until a
   full review-mode approval round-trip has been exercised with a test prospect (self).

Go-live order: smoke pass → `dry_run: false`, `mode: "review"` → operator satisfaction →
`mode: "auto"`.

---

## 10. Testing

- `pytest` on all pure logic: gates (each gate has pass/fail cases), verdict parser
  (plain, HTML, mobile-signature, quoted-thread, ambiguous, both-verdicts replies), dedup,
  caps windows, token lifecycle (double-approve, expired, wrong sender), ICP check
  (ported v1/parent cases incl. smart-play rescues), draft schema validation,
  body sanitizer (double-greeting / placeholder regressions).
- COM layer is thin and mocked in tests; exercised for real only by `smoke_test.py`.
- Replay-style idempotency test: same drafts processed twice → zero duplicate sends.

## 11. Explicit non-goals / stated limitations

- No draft editing via reply (approve-as-is or NO). Drafts-folder edit mode = future add-on.
- No web UI, no tunnel, no cloud host, no Resend/Graph — by design.
- No CRM writeback in v2.
- Old `Fully-Automated System\` folder: untouched until operator confirms deletion
  post-smoke-test. Its `icp_core.py` provenance and template-contract tests are ported by
  copy.
- Non-US ICP visitors are recorded in `seen.json` (visible in the summary) but never
  emailed while `geo_allowlist = ["US"]`.
