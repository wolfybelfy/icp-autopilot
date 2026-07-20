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
try {
    Say "phase pre"
    PyRun pipeline\tick.py --phase pre | Out-File $Log -Append -Encoding utf8
    Say "claude run"
    $claudeOut = "$Log.claude"
    $p = Start-Process -FilePath "claude" -ArgumentList @("-p", "@prompts/run-prompt.md",
         "--output-format", "text") -NoNewWindow -PassThru -RedirectStandardOutput $claudeOut
    if (-not $p.WaitForExit(480000)) { $p.Kill(); Say "claude run TIMED OUT at 8min - killed" }
    Get-Content $claudeOut -ErrorAction SilentlyContinue | Out-File $Log -Append -Encoding utf8
    Remove-Item $claudeOut -Force -ErrorAction SilentlyContinue
    Say "phase post"
    PyRun pipeline\tick.py --phase post | Out-File $Log -Append -Encoding utf8
} finally { Remove-Item $Lock -Force -ErrorAction SilentlyContinue }
Say "tick done"
