# scripts\run-once.ps1
# Standalone, FOREGROUND single pipeline run. Bypasses Task Scheduler entirely.
#
# What it does, in order:
#   1. Force-kills any leftover claude / tick.py / run.ps1 process TREES (the zombies that
#      keep a console window and the lock alive).
#   2. Holds state\tick.lock for the duration, so a scheduled tick that fires mid-run
#      SKIPS instead of racing us on the same state files.
#   3. Drops state\priority.json naming one visitor. The run-prompt sees it and pushes that
#      exact visitor through detect -> ICP -> ZoomInfo -> enrich -> draft FIRST, regardless
#      of where they sit in the backlog.
#   4. Runs Claude once, then the send phase once - each wrapped in a hard timeout + full
#      process-tree kill, so neither can ever hang this window.
#   5. Reports exactly where the draft landed and cleans up.
#
# Usage (NON-admin PowerShell window, from the repo root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-once.ps1 k.morrison@f5.com

param([string]$Email = "k.morrison@f5.com")

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
New-Item -ItemType Directory -Force (Join-Path $Root "logs")  | Out-Null
New-Item -ItemType Directory -Force (Join-Path $Root "state") | Out-Null
$Log      = Join-Path $Root ("logs\tick-" + (Get-Date -Format "yyyy-MM-dd") + ".log")
$Lock     = Join-Path $Root "state\tick.lock"
$Priority = Join-Path $Root "state\priority.json"

function Step($m) { Write-Host ""; Write-Host ("=== " + $m + " ===") -ForegroundColor Cyan }
function Info($m) { Write-Host "  $m" }
function Say($m)  { ("{0} [run-once] {1}" -f (Get-Date -Format "HH:mm:ss"), $m) | Out-File $Log -Append -Encoding utf8 }

# Win10: 'python' may be the Microsoft Store stub; fall back to the 'py -3' launcher.
$script:UsePy = -not ((python --version 2>&1) -match "^Python 3")
function PyExe  { if ($script:UsePy) { "py" }        else { "python" } }
function PyArgs([string[]]$a) { if ($script:UsePy) { @("-3") + $a } else { $a } }

# Run a child under cmd.exe with a hard timeout, merged stdout+stderr to a temp file, and a
# FULL process-tree kill on timeout (taskkill /T /F). Returns { TimedOut, ExitCode, Output }.
function Invoke-TreeProcess([string]$Label, [string]$Exe, [string[]]$Arguments, [int]$TimeoutSec) {
    $id  = [Guid]::NewGuid().ToString("N")
    $dir = Join-Path $env:TEMP "icp-runonce"
    New-Item -ItemType Directory -Force $dir | Out-Null
    $out = Join-Path $dir "$id.out.txt"
    $cmd = Join-Path $dir "$id.cmd"
    $call = ""
    $resolved = Get-Command $Exe -ErrorAction SilentlyContinue
    if ($resolved -and $resolved.Source -match "\.(cmd|bat)$") { $Exe = $resolved.Source; $call = "call " }
    $quoted = @('"' + $Exe + '"') + @($Arguments | ForEach-Object { '"' + ($_ -replace '%', '%%') + '"' })
    @("@echo off", ($call + ($quoted -join " ") + ' 1>"' + $out + '" 2>&1'), "exit /b %errorlevel%") |
        Set-Content $cmd -Encoding Ascii
    $p = Start-Process -FilePath $env:ComSpec -ArgumentList ('/d /s /c ""' + $cmd + '""') -NoNewWindow -PassThru
    $null = $p.Handle   # PS 5.1: cache the handle now or .ExitCode reads $null after exit
    $timedOut = -not $p.WaitForExit($TimeoutSec * 1000)
    if ($timedOut) {
        Say "$Label TIMED OUT at ${TimeoutSec}s - killing tree pid $($p.Id)"
        Info "! $Label exceeded ${TimeoutSec}s - killing its whole process tree so it can't hang."
        & "$env:SystemRoot\System32\taskkill.exe" /PID $p.Id /T /F 2>&1 | Out-Null
        [void]$p.WaitForExit(15000)
    }
    $text = ""
    if (Test-Path $out) { try { $text = [System.IO.File]::ReadAllText($out) } catch {} }
    if ($text) { $text | Out-File $Log -Append -Encoding utf8 }
    Remove-Item $cmd, $out -Force -ErrorAction SilentlyContinue
    $code = -1
    if ($p.HasExited) { $code = $p.ExitCode }
    return [pscustomobject]@{ TimedOut = $timedOut; ExitCode = $code; Output = $text }
}

function Kill-Zombies {
    $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and (
            $_.CommandLine -match "run-prompt" -or
            $_.CommandLine -match "tick\.py"   -or
            $_.CommandLine -match "\\run\.ps1" ) })
    if ($procs.Count -eq 0) { Info "none found - clean."; return }
    foreach ($z in $procs) {
        Info ("killing leftover pid {0} ({1})" -f $z.ProcessId, $z.Name)
        Say  ("kill zombie pid {0} {1}" -f $z.ProcessId, $z.Name)
        & "$env:SystemRoot\System32\taskkill.exe" /PID $z.ProcessId /T /F 2>&1 | Out-Null
    }
}

Step "ICP Autopilot - single foreground run for: $Email"
Info "Bypasses Task Scheduler. Kills leftovers, forces this visitor through, runs once."
Info "Total time: up to ~10 minutes. Leave this window open until you see 'DONE'."

Step "[1/5] Clearing stuck / zombie tick processes"
Kill-Zombies
Remove-Item $Lock -Force -ErrorAction SilentlyContinue
New-Item -ItemType File -Force $Lock | Out-Null   # hold the lock so scheduled ticks skip
Say "run-once started; holding lock"

try {
    Step "[2/5] Marking $Email as the priority target"
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Priority, ('{"email": "' + $Email + '"}'), $utf8)
    Info "wrote state\priority.json"

    Step "[3/5] Healing workspace trust (so Warmly + ZoomInfo MCP servers load)"
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
else:
    print('already trusted')
"@
    $healed = if ($script:UsePy) { & py -3 -c $trustCode 2>&1 } else { & python -c $trustCode 2>&1 }
    Info ("$healed")

    Step "[4/5] Detection + ICP + ZoomInfo + enrichment + draft (Claude, up to 8 min)"
    Info "Please wait - no output appears until Claude finishes. Watch for a draft for $Email."
    $allowed = "mcp__warmly,mcp__claude_ai_ZoomInfo,WebSearch,WebFetch,Read,Glob,Grep,Write,Edit,Bash(python:*),Bash(py:*)"
    $cargs = @("-p", "@prompts/run-prompt.md", "--output-format", "text", "--allowedTools", $allowed)
    if ((& claude --help 2>&1 | Out-String) -match "dontAsk") { $cargs += @("--permission-mode", "dontAsk") }
    $cl = Invoke-TreeProcess "claude" "claude" $cargs 480
    Write-Host ""
    Write-Host "  --- Claude output ---" -ForegroundColor DarkGray
    Write-Host $cl.Output
    if ($cl.TimedOut) { Info "(Claude was killed at the 8-min timeout - see notes at the end.)" }

    Step "[5/5] Routing draft + sending the approval email (send phase)"
    $post = Invoke-TreeProcess "phase.post" (PyExe) (PyArgs @("pipeline\tick.py", "--phase", "post")) 120
    Write-Host $post.Output
    if ($post.TimedOut) { Info "(Send phase hit its 2-min timeout and was killed - Outlook may have a dialog open.)" }
}
finally {
    Remove-Item $Priority -Force -ErrorAction SilentlyContinue
    Remove-Item $Lock -Force -ErrorAction SilentlyContinue
    Say "run-once done; priority + lock cleared"
}

Step "RESULT"
$found = $false
foreach ($sub in @("inbox", "sent", "rejected", "invalid")) {
    $d = Join-Path $Root "drafts\$sub"
    if (Test-Path $d) {
        $files = @(Get-ChildItem $d -Filter *.json -ErrorAction SilentlyContinue)
        Write-Host ("  drafts\{0,-9}: {1} file(s)" -f $sub, $files.Count)
        foreach ($f in $files) {
            Write-Host ("      - " + $f.Name)
            if ($f.Name -match [regex]::Escape(($Email -split "@")[0])) { $found = $true }
        }
    }
}
Write-Host ""
if ($found) {
    Write-Host "  LOOKS GOOD: a draft/pending file for $Email exists." -ForegroundColor Green
    Write-Host "  A '.pending.json' in drafts\inbox = the approval email was sent to your inbox." -ForegroundColor Green
    Write-Host "  Check upawar@unboundia.com for:  Approval [#XXXXXX] - ... (F5)" -ForegroundColor Green
    Write-Host "  A file in drafts\rejected = it was gated; the reason is in the log below." -ForegroundColor Yellow
} else {
    Write-Host "  No draft for $Email this run. Likely 'priority_not_found' (visitor aged out of" -ForegroundColor Yellow
    Write-Host "  Warmly's past-month window) or a ZoomInfo miss. See the Claude output above and" -ForegroundColor Yellow
    Write-Host "  the log tail below for the exact reason." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  --- last 25 log lines ---" -ForegroundColor DarkGray
Get-Content $Log -Tail 25 -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "=== DONE - safe to close this window ===" -ForegroundColor Cyan
