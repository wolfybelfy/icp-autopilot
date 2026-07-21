# LinkedIn enrichment — safe, zero-ban setup (spare PC)

E5 reads a prospect's **recent LinkedIn posts** as a personalization hook. It is an
optional add-on: if it is off or blocked, the pipeline still drafts and sends. The hiring
signal you also asked for does **not** use this at all — it comes from Google
(`site:linkedin.com/jobs "<Company>"`) in E4 and from ZoomInfo scoops in E3, both of which
carry zero LinkedIn-account risk.

## Why this design cannot get the account banned

Bans come from four things (verified against 2026 guidance): high request velocity,
robotic timing / headless fingerprints, datacenter IPs, and hammering the login wall.
This design does none of them:

- **Your real Chrome, your real login, your real home IP.** We attach to the browser you
  already use — not a fresh automated Chromium (the thing that gets fingerprinted and was
  almost certainly the cause of the captcha loops on the other project). A 2026 benchmark
  put vanilla Playwright/Chromium as the *most* detected tool; a real Chrome driven over
  CDP is the least.
- **Read-only, one page, one prospect per tick.** No clicks, no messages, no follows, no
  typing. A handful of profile views per day — far under the 20–50/day "safe" ceiling.
- **Skip-on-anything.** The prompt's hard rule: at the first sign of a login wall,
  checkpoint, or captcha, E5 stops and moves on. It NEVER logs in, NEVER solves a captcha,
  NEVER retries. The captcha-loop failure mode is impossible because we never engage one.

## One-time setup

### 1. Keep a Chrome signed in to LinkedIn, with a remote-debugging port

Use a dedicated Chrome profile (so it never fights your normal browsing) and launch it
with remote debugging. Create a shortcut / scheduled command:

```
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="C:\Users\admin\icp-chrome-profile"
```

Sign in to LinkedIn (and Sales Navigator if you use it) **once** in that window. Leave it
running. The session persists in that profile, so it stays logged in across reboots as
long as you relaunch with the same `--user-data-dir`.

### 2. Point the browser MCP at that Chrome (CDP), not a new browser

The MCP must **connect** to the running Chrome, not launch its own. With the Playwright
MCP that is the `--cdp-endpoint` option; with the chrome-devtools MCP it is
`--browserUrl` / the CDP connect flag. Example (Playwright MCP):

```
claude mcp add playwright -- npx @playwright/mcp@latest --cdp-endpoint http://localhost:9222
```

> Confirm the exact MCP server name you register here (`playwright`, or whatever you name
> it). That name is what goes into `--allowedTools` in step 3.

### 3. Allow the browser MCP for the headless run

`scripts/run.ps1` and `scripts/run-once.ps1` build an `--allowedTools` string. Add your
browser MCP server to it, e.g. append `,mcp__playwright`. (Left out until you confirm the
server name, so a wrong name can't silently break a tick — until then E5 just records
`linkedin_logged_out` and skips, which is harmless.)

### 4. Turn E5 on

In `config/config.json` set `"linkedin": { "enabled": true }`. The `linkedin` cap
(`linkedin_loads_per_day`, default 15) bounds it regardless.

## Verifying it works

Run `scripts/run-once.ps1` for a prospect you know has recent posts. In the draft's
`enrichment.linkedin.recent_activity` you should see their latest post(s). If you instead
see gap `linkedin_logged_out`, the MCP isn't connected to the logged-in Chrome (recheck
steps 1–3). If you see `linkedin_blocked`, LinkedIn showed a challenge and E5 correctly
backed off — no retry, no risk.
