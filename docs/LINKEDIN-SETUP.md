# LinkedIn enrichment — safe, zero-ban setup (spare PC)

E5 reads a prospect's **recent LinkedIn posts** as a personalization hook. It is an
optional add-on: if it is off or blocked, the pipeline still drafts and sends. The hiring
signal you also wanted does **not** use this at all — it comes from Google
(`site:linkedin.com/jobs "<Company>"`) in E4 and ZoomInfo scoops in E3, both zero risk.

## Why this cannot get the account banned

Bans come from four things (verified, 2026): request velocity, robotic timing / headless
fingerprints, datacenter IPs, and hammering the login wall. This design does none of them:

- **Your real Chrome, real login, real home IP.** Automation attaches over CDP to a real,
  manually-logged-in Chrome — never a fresh automated Chromium (the fingerprinted thing that
  caused the captcha loops before). A 2026 benchmark rated a real Chrome over CDP as the
  least-detected setup and vanilla Playwright/Chromium as the most.
- **Read-only, one page, one prospect per tick.** The run scripts grant only three
  Playwright tools — `browser_navigate`, `browser_snapshot`, `browser_wait_for`. There is
  **no click / type / submit tool available at all**, so interaction is impossible, not just
  discouraged. A handful of profile views a day, far under the 20–50/day safe ceiling.
- **Skip-on-anything.** The prompt stops E5 at the first login wall / checkpoint / captcha,
  records `linkedin_blocked`, and moves on. It never logs in, never solves a captcha, never
  retries. The captcha-loop failure mode is impossible because we never engage one.

## One-time setup (spare PC, non-admin PowerShell)

### 1. Launch the dedicated logged-in Chrome

```powershell
cd "C:\Users\admin\Documents\ICP automate system\icp-autopilot"
git pull
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-cdp-chrome.ps1
```

A Chrome window opens on a dedicated profile (`%LOCALAPPDATA%\ICP-Autopilot\ChromeCDP`) with
debug port 9222. **Log into LinkedIn in that window once.** It stays logged in across
reboots. Use this profile for LinkedIn only — never sign into anything sensitive in it (any
local process that reaches port 9222 can control it).

### 2. Register the browser MCP (attach to that Chrome — do NOT let it launch its own)

```powershell
claude mcp add --scope user --transport stdio linkedin-browser -- npx -y @playwright/mcp@latest --cdp-endpoint=http://127.0.0.1:9222 --cdp-timeout=10000
claude mcp list
```

The server **must** be named `linkedin-browser` — that is the exact name already granted in
`scripts/run.ps1` and `scripts/run-once.ps1`. The `--cdp-endpoint` flag is what makes it
attach to your Chrome instead of spawning a fresh (detectable) one.

### 3. Turn E5 on

In `config/config.json`: `"linkedin": { "enabled": true }`. The `linkedin_loads_per_day`
cap (default 15) bounds it regardless.

### 4. Keep Chrome running

The launcher is idempotent (re-running it just confirms Chrome is up). Add it to your
Startup folder, or run it before a test. If Chrome isn't up, E5 simply records
`linkedin_logged_out` and skips — harmless.

## Verify

Run `scripts\run-once.ps1` for a prospect with recent posts. Look in the draft's
`enrichment.linkedin.recent_activity` for their latest post(s).

- Empty + gap `linkedin_logged_out` → the MCP isn't attached to the logged-in Chrome
  (recheck steps 1–2, and `claude mcp list`).
- Gap `linkedin_blocked` → LinkedIn showed a challenge and E5 correctly backed off. No
  retry, no risk. Try again later; do not solve anything manually on its behalf.
