# Environment verifier. All checks must be green before importing the schedule.
# Changes nothing - safe to re-run any time.
$fail = 0
function Check($name, $ok) { if ($ok) { Write-Host "[OK]   $name" } else { Write-Host "[FAIL] $name"; $script:fail++ } }
Check "Python 3.11+"        ((python --version 2>&1) -match "3\.1[1-9]")
Check "pywin32 importable"  ((python -c "import win32com.client; print(1)" 2>&1) -match "1")
Check "classic Outlook COM" ((python -c "import win32com.client as w; w.Dispatch('Outlook.Application'); print(1)" 2>&1) -match "1")
Check "claude CLI"          ((claude --version 2>&1) -match "\d")
Check "warmly MCP added"    ((claude mcp list 2>&1) -match "warmly")
Check "zoominfo MCP added"  ((claude mcp list 2>&1) -match "zoominfo")
Check "NTP clock sync"      ((w32tm /query /status 2>&1) -match "Source:")
Check "tests green"         ((python -m pytest -q 2>&1) -match "passed")
Check "no REPLACE_ME in config" (-not ((Get-Content config\config.json -Raw) -match "REPLACE_ME"))
if ($fail -gt 0) { Write-Host "`n$fail check(s) failed - fix before go-live."; exit 1 }
Write-Host "`nAll green."
