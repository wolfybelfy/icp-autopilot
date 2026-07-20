# ICP Autopilot — Spare-PC Setup

Follow top to bottom. Each step ends with its verification. Do not improvise the order.
Full design: `docs/specs/2026-07-20-icp-autopilot-design.md`.

## Windows 10 notes (the spare PC)

- **No `winget` needed anywhere below.** All installs are direct downloads or PowerShell
  one-liners that work on Windows 10 PowerShell 5.1.
- If `python` opens the Microsoft Store instead of Python: use `py -3` in place of
  `python` everywhere (or disable the Store alias: Settings → Apps → App execution
  aliases → turn off both `python` entries).
- **No GitHub CLI (`gh`) needed.** Cloning the private repo with plain `git clone` pops
  up a browser sign-in via Git Credential Manager (bundled with Git for Windows) —
  sign in as `wolfybelfy` once and it's remembered.
- If the Claude Code CLI is missing, install with (verified working):
  ```powershell
  irm https://claude.ai/install.ps1 | iex
  ```

## Already did v1's setup? (resume checklist)

If this PC previously went through v1's `SPARE-PC-SETUP.md`, most prerequisites exist.
Check what's present and skip those steps:

```powershell
python --version    # or: py -3 --version      → have Python? skip step 1's install
git --version       #                          → have Git? nothing else needed to clone
claude --version    #                          → have Claude CLI? skip step 3's install
claude mcp list     #                          → zoominfo already added? skip that part of step 4
```

pywin32/pytest still need installing for THIS repo: `pip install -r requirements.txt`
(v1 used different packages). The v1 folder/repo itself is unused here — do not mix them.

## The kill switch (know this first)

Create a file named `STOP` in this folder → everything halts within one tick (no sends,
no runs). Delete it to resume. No restart needed.

## Steps

1. **Python 3.11+** and packages.
   ```powershell
   python --version            # 3.11+
   pip install -r requirements.txt
   ```

2. **Classic Outlook**, signed into the sender mailbox (the sales director's account;
   the operator's own during build/test). ⚠️ Must be CLASSIC Outlook — "New Outlook" has
   no COM automation. Send yourself one email manually to confirm mail flows.
   Verify: `python -c "import win32com.client as w; w.Dispatch('Outlook.Application')"` → no error.

3. **Claude Code CLI**, signed in with the subscription login (no API key anywhere).
   Verify: `claude --version`.

4. **MCPs — ZoomInfo comes from the claude.ai connector, NOT a local add.**
   The claude.ai ZoomInfo connector is tied to the Claude *account*, so it arrives on any
   PC signed into that account already authenticated (verified 2026-07-20: 21 tools,
   works headless in `claude -p`). ⚠️ **Never add a user-scoped `zoominfo` MCP or run its
   browser OAuth on a new PC** — a failed OTP loop locked the ZoomInfo account once
   already. If a stale user-scoped entry exists: `claude mcp remove zoominfo -s user`.

   Warmly IS a local user-scoped MCP (open registration, safe to auth):
   ```powershell
   claude mcp add --transport http --scope user warmly <warmly-mcp-url-from-v1-scripts>
   claude    # then /mcp to authenticate warmly in the browser (one attempt; stop on failure)
   ```
   Verify both: `claude mcp list` must show `warmly … Connected` and
   `claude.ai ZoomInfo … Connected`. Then tool-name parity: `claude -p "List the names of
   every ZoomInfo tool available to you. Do not call any."` and confirm `enrich_contacts`,
   `enrich_companies`, `enrich_company_signals` exist. If names differ, adjust
   `prompts/run-prompt.md` §2 accordingly.

5. **Playwright MCP + Sales Navigator** (optional — LinkedIn stage): install the
   Playwright MCP for the CLI, open its browser profile, sign in LinkedIn Sales Navigator.
   When this session logs out the LinkedIn stage self-disables and the daily summary says
   so. To turn the stage off entirely: `config/config.json → linkedin.enabled: false`.

6. **Clone the repo** (browser sign-in as wolfybelfy pops up on first clone), then verify:
   ```powershell
   cd $HOME\Documents
   git clone https://github.com/wolfybelfy/icp-autopilot.git ICP-Autopilot
   cd ICP-Autopilot
   ```
   Then run the verifier:
   ```powershell
   powershell -File scripts\setup.ps1     # must end "All green."
   ```

7. **Fill required config** in `config/config.json`:
   - `addresses.*` — director's address for `reviewer_notify` + `approver_addresses`
     (keep the operator in `approver_addresses` and `audit_bcc`/`summary_to`)
   - `sender.name`, `sender.title`, `sender.postal_address` (CAN-SPAM footer) — the
     REPLACE_ME values force queueing until filled.

8. **Smoke test**:
   ```powershell
   python pipeline\smoke_test.py          # dry: pipeline end-to-end, no COM
   python pipeline\smoke_test.py --send   # ONE real email to the sender's own address
   ```

9. **Import the schedule** and watch two ticks:
   ```powershell
   schtasks /Create /XML scripts\task-schedule.xml /TN ICP-Autopilot-Tick
   ```
   Watch `logs\tick-<date>.log` for two clean ticks.

## Go-live order (do not reorder)

1. Smoke passes (step 8) → set `safety.dry_run: false`, keep `mode: "review"`.
2. Director reviews live approval requests for a while (reply GOOD/NO from any device).
3. When output quality is trusted → set `mode: "auto"`. Same gates, no other change.
