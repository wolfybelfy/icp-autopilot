# ICP Autopilot tick - fired by Task Scheduler every 5 minutes.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Lock = Join-Path $Root "state\tick.lock"
$Log  = Join-Path $Root ("logs\tick-" + (Get-Date -Format "yyyy-MM-dd") + ".log")
New-Item -ItemType Directory -Force (Join-Path $Root "logs") | Out-Null
function Say($m) { ("{0} {1}" -f (Get-Date -Format "HH:mm:ss"), $m) | Out-File $Log -Append -Encoding utf8 }
# Win10: 'python' may be the Microsoft Store stub; fall back to the 'py -3' launcher.
function PyRun { if ($script:UsePyLauncher) { & py -3 @args 2>&1 } else { & python @args 2>&1 } }
$script:UsePyLauncher = -not ((python --version 2>&1) -match "^Python 3")

if (Test-Path (Join-Path $Root "STOP")) { Say "STOP file present - halt"; exit 0 }
if (Test-Path $Lock) {
    $age = (Get-Date) - (Get-Item $Lock).LastWriteTime
    if ($age.TotalMinutes -lt 15) { Say "locked (live run) - skip"; exit 0 }
    Say "stale lock ($([int]$age.TotalMinutes)m) - stealing"; Remove-Item $Lock -Force
}
New-Item -ItemType File -Force $Lock | Out-Null
# Sandboxed claude runs can create but not delete scratch files in state\ - sweep them
# here so they never accumulate. Real state files never start with '_' or 'tmp'.
Get-ChildItem (Join-Path $Root "state") -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "_*" -or $_.Name -like "tmp*" } |
    Remove-Item -Force -ErrorAction SilentlyContinue
# Trust self-heal: an exiting claude session or a CLI update can rewrite ~/.claude.json and
# drop this workspace's trust key. Untrusted = user-scoped MCP servers (Warmly) never load,
# so every tick would stall. Runs before claude launches (no live session to overwrite us).
# Trust is keyed by the RAW path string, so cover both this path's literal and resolved case.
$trustCode = @"
import json, pathlib, sys
p = pathlib.Path.home() / '.claude.json'
try:
    d = json.load(open(p, encoding='utf-8'))
except Exception:
    sys.exit(0)
keys = {r'$Root'.replace('\\', '/'), str(pathlib.Path(r'$Root').resolve()).replace('\\', '/')}
fixed = []
for key in keys:
    proj = d.setdefault('projects', {}).setdefault(key, {})
    if proj.get('hasTrustDialogAccepted') is not True:
        proj['hasTrustDialogAccepted'] = True
        fixed.append(key)
if fixed:
    json.dump(d, open(p, 'w', encoding='utf-8'), indent=2)
    print('restored: ' + ', '.join(fixed))
"@
$healed = PyRun -c $trustCode
if ($healed) { Say "workspace trust self-healed ($healed)" }
try {
    Say "phase pre"
    PyRun pipeline\tick.py --phase pre | Out-File $Log -Append -Encoding utf8
    Say "claude run"
    $claudeOut = "$Log.claude"
    # Headless runs have no one to click permission prompts. Grant the run-prompt's tools
    # explicitly on the CLI - honored regardless of workspace-trust state, unlike
    # .claude/settings.json. Comma-separated, no spaces (Start-Process arg quoting).
    # dontAsk (when the CLI supports it) denies anything NOT allowed instead of stalling.
    $allowed = "mcp__warmly,mcp__claude_ai_ZoomInfo,mcp__linkedin-browser__browser_navigate,mcp__linkedin-browser__browser_snapshot,mcp__linkedin-browser__browser_wait_for,WebSearch,WebFetch,Read,Glob,Grep,Write,Edit,Bash(python:*),Bash(py:*)"
    $claudeArgs = @("-p", "@prompts/run-prompt.md", "--output-format", "text",
                    "--allowedTools", $allowed)
    if ((& claude --help 2>&1 | Out-String) -match "dontAsk") {
        $claudeArgs += @("--permission-mode", "dontAsk")
    }
    $p = Start-Process -FilePath "claude" -ArgumentList $claudeArgs -NoNewWindow -PassThru -RedirectStandardOutput $claudeOut
    if (-not $p.WaitForExit(480000)) { $p.Kill(); Say "claude run TIMED OUT at 8min - killed" }
    Get-Content $claudeOut -ErrorAction SilentlyContinue | Out-File $Log -Append -Encoding utf8
    Remove-Item $claudeOut -Force -ErrorAction SilentlyContinue
    Say "phase post"
    PyRun pipeline\tick.py --phase post | Out-File $Log -Append -Encoding utf8
} finally { Remove-Item $Lock -Force -ErrorAction SilentlyContinue }
Say "tick done"
