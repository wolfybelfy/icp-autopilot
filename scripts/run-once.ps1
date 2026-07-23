# scripts\run-once.ps1
# Standalone, FOREGROUND single pipeline run. Bypasses Task Scheduler entirely.
#
# TWO MODES:
#   -Email x@y.com   push ONE specific visitor through end-to-end.
#   -FindIcp         find the FIRST prospect in the last -WindowHours (default 48) that
#                    passes BOTH gates (company + marketing-Mgr+/product-Sr+ persona) and
#                    take only that one all the way to a drafted approval email.
#
# It force-kills zombie tick processes, holds state\tick.lock so a scheduled tick can't
# race it, drops state\priority.json, runs Claude then the send phase (each under a hard
# timeout with a full process-tree kill), and prints exactly where the draft + approval
# landed. Nothing here can hang or zombie.
#
# Usage (NON-admin PowerShell, from the repo root, with Outlook OPEN):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-once.ps1 -FindIcp
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-once.ps1 -Email k.morrison@f5.com

param(
    [string]$Email = "",
    [switch]$FindIcp,
    [int]$WindowHours = 48
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
New-Item -ItemType Directory -Force (Join-Path $Root "logs")  | Out-Null
New-Item -ItemType Directory -Force (Join-Path $Root "state") | Out-Null
$Log      = Join-Path $Root ("logs\tick-" + (Get-Date -Format "yyyy-MM-dd") + ".log")
$Lock     = Join-Path $Root "state\tick.lock"
$Priority = Join-Path $Root "state\priority.json"

if (-not $FindIcp -and -not $Email) {
    Write-Host "Give one of:  -FindIcp   OR   -Email someone@company.com" -ForegroundColor Yellow
    exit 2
}

function Step($m) { Write-Host ""; Write-Host ("=== " + $m + " ===") -ForegroundColor Cyan }
function Info($m) { Write-Host "  $m" }
function Say($m)  { ("{0} [run-once] {1}" -f (Get-Date -Format "HH:mm:ss"), $m) | Out-File $Log -Append -Encoding utf8 }

$script:UsePy = -not ((python --version 2>&1) -match "^Python 3")
function PyExe  { if ($script:UsePy) { "py" }        else { "python" } }
function PyArgs([string[]]$a) { if ($script:UsePy) { @("-3") + $a } else { $a } }

# Resolve the claude CLI explicitly. A `powershell -NoProfile -File` child does NOT inherit
# a PATH tweak you made interactively, so bare `claude` can be "not recognized" here even
# when it works in your normal window. Find the binary and prepend its folder to PATH so the
# cmd.exe child in Invoke-TreeProcess finds it too.
function Resolve-Claude {
    $g = Get-Command claude -ErrorAction SilentlyContinue
    if ($g) { return $g.Source }
    $cands = @(
        (Join-Path $env:APPDATA 'npm\claude.cmd'),
        (Join-Path $env:APPDATA 'npm\claude.ps1'),
        (Join-Path $env:USERPROFILE '.local\bin\claude.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\claude\claude.exe')
    )
    foreach ($cand in $cands) { if ($cand -and (Test-Path $cand)) { return $cand } }
    try { $pref = (& npm config get prefix 2>$null); if ($pref) { $q = Join-Path $pref 'claude.cmd'; if (Test-Path $q) { return $q } } } catch {}
    return $null
}
$ClaudeExe = Resolve-Claude
if (-not $ClaudeExe) {
    Write-Host "FATAL: could not find the 'claude' CLI on this machine." -ForegroundColor Red
    Write-Host "  In a normal window run:  where.exe claude   (or reinstall: npm install -g @anthropic-ai/claude-code)" -ForegroundColor Red
    exit 3
}
$env:Path = (Split-Path -Parent $ClaudeExe) + ';' + $env:Path

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

if ($FindIcp) { $what = "first ICP in the last ${WindowHours}h" } else { $what = $Email }
Step "ICP Autopilot - single foreground run for: $what"
Info "Bypasses Task Scheduler. Kills leftovers, runs once. Make sure OUTLOOK IS OPEN."
Info "Up to ~12 minutes. Leave this window open until you see 'DONE'."

Step "[1/5] Clearing stuck / zombie tick processes"
Kill-Zombies
Remove-Item $Lock -Force -ErrorAction SilentlyContinue
New-Item -ItemType File -Force $Lock | Out-Null   # hold the lock so scheduled ticks skip
Say "run-once started; holding lock"

try {
    Step "[2/5] Setting the target"
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    if ($FindIcp) {
        # UTC cutoff computed HERE (reliable clock) and handed to the model, so it never has
        # to invent 'now'. Warmly lastSeen is UTC; comparing in UTC ignores the PC's offset.
        $since = (Get-Date).ToUniversalTime().AddHours(-$WindowHours).ToString("yyyy-MM-ddTHH:mm:ssZ")
        [System.IO.File]::WriteAllText($Priority, ('{"mode": "first_icp", "since": "' + $since + '"}'), $utf8)
        Info "wrote state\priority.json  (mode=first_icp, since=$since UTC)"
    } else {
        [System.IO.File]::WriteAllText($Priority, ('{"email": "' + $Email + '"}'), $utf8)
        Info "wrote state\priority.json  (email=$Email)"
    }

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

    Step "[4/5] Detect + gate (company + persona) + ZoomInfo + enrich + draft (Claude, up to 10 min)"
    Info "Please wait - no output appears until Claude finishes."
    $allowed = "mcp__warmly,mcp__claude_ai_ZoomInfo,mcp__linkedin-browser__browser_navigate,mcp__linkedin-browser__browser_snapshot,mcp__linkedin-browser__browser_wait_for,WebSearch,WebFetch,Read,Glob,Grep,Write,Edit,Bash(python *),Bash(py *),PowerShell"
    $cargs = @("-p", "@prompts/run-prompt.md", "--output-format", "text", "--allowedTools", $allowed)
    if ((& $ClaudeExe --help 2>&1 | Out-String) -match "dontAsk") { $cargs += @("--permission-mode", "dontAsk") }
    $cl = Invoke-TreeProcess "claude" $ClaudeExe $cargs 600
    Write-Host ""
    Write-Host "  --- Claude output ---" -ForegroundColor DarkGray
    Write-Host $cl.Output
    if ($cl.TimedOut) { Info "(Claude was killed at the 10-min timeout - see notes at the end.)" }

    Step "[5/5] Routing draft + sending the approval email (send phase)"
    $post = Invoke-TreeProcess "phase.post" (PyExe) (PyArgs @("pipeline\tick.py", "--phase", "post")) 120
    Write-Host $post.Output
    if ($post.TimedOut) { Info "(Send phase hit its 2-min timeout and was killed - is Outlook open?)" }
}
finally {
    Remove-Item $Priority -Force -ErrorAction SilentlyContinue
    Remove-Item $Lock -Force -ErrorAction SilentlyContinue
    Say "run-once done; priority + lock cleared"
}

Step "RESULT"
foreach ($sub in @("inbox", "sent", "rejected", "invalid")) {
    $d = Join-Path $Root "drafts\$sub"
    if (Test-Path $d) {
        $files = @(Get-ChildItem $d -Filter *.json -ErrorAction SilentlyContinue)
        Write-Host ("  drafts\{0,-9}: {1} file(s)" -f $sub, $files.Count)
        foreach ($f in $files) { Write-Host ("      - " + $f.Name) }
    }
}
# Any approval emails awaiting your reply - print the token so you can search your inbox.
$apr = Join-Path $Root "state\approvals.json"
if (Test-Path $apr) {
    try {
        $a = Get-Content $apr -Raw -Encoding UTF8 | ConvertFrom-Json
        $pending = @($a.PSObject.Properties | Where-Object { $_.Value.status -eq "pending" })
        Write-Host ""
        if ($pending.Count -gt 0) {
            Write-Host "  APPROVAL EMAIL(S) awaiting your reply - search your inbox for the token:" -ForegroundColor Green
            foreach ($p in $pending) {
                Write-Host ("    [#{0}]  recipient={1}  requested={2}" -f $p.Name, $p.Value.recipient, $p.Value.requested_at) -ForegroundColor Green
            }
            Write-Host "  Open it, reply GOOD to approve or NO to reject (dry_run: nothing goes to the prospect)." -ForegroundColor Green
        } else {
            Write-Host "  No pending approval this run." -ForegroundColor Yellow
            Write-Host "  If Claude reported 'no_icp_in_window', the gates simply found no marketing/" -ForegroundColor Yellow
            Write-Host "  product leader in the window - that's a correct result, not a failure." -ForegroundColor Yellow
        }
    } catch {}
}
Write-Host ""
Write-Host "  --- last 25 log lines ---" -ForegroundColor DarkGray
Get-Content $Log -Tail 25 -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "=== DONE - safe to close this window ===" -ForegroundColor Cyan
