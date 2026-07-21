# scripts\start-cdp-chrome.ps1
# Launch a DEDICATED Chrome (its own profile) with a CDP debugging port, for read-only
# LinkedIn enrichment. Idempotent: exits 0 if it's already up. Log into LinkedIn in this
# window ONCE - the session persists in the dedicated profile across reboots.
#
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-cdp-chrome.ps1
$ErrorActionPreference = "Stop"
$Port     = 9222
$ProfDir  = Join-Path $env:LOCALAPPDATA "ICP-Autopilot\ChromeCDP"
$Endpoint = "http://127.0.0.1:$Port/json/version"

# Already running? done.
try { $v = Invoke-RestMethod -Uri $Endpoint -TimeoutSec 3 -ErrorAction Stop
      Write-Host "CDP Chrome already up on $Port ($($v.Browser))."; exit 0 } catch {}

$chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw "Chrome not found in the usual locations." }

New-Item -ItemType Directory -Force $ProfDir | Out-Null
# Dedicated --user-data-dir is REQUIRED: Chrome 136+ ignores the debug port on the default
# profile. This profile is for LinkedIn enrichment ONLY - never sign into anything sensitive.
Start-Process $chrome -ArgumentList @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=`"$ProfDir`"",
    "--no-first-run", "--no-default-browser-check",
    "https://www.linkedin.com/feed/"
)

$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Milliseconds 500
    try { $v = Invoke-RestMethod -Uri $Endpoint -TimeoutSec 2 -ErrorAction Stop
          Write-Host "CDP Chrome ready on $Port ($($v.Browser)). Profile: $ProfDir"
          Write-Host "Log into LinkedIn in this window ONCE if you haven't - it stays logged in."
          exit 0 } catch {}
} while ((Get-Date) -lt $deadline)
throw "Chrome launched but CDP endpoint $Endpoint never came up."
