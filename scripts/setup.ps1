# Environment verifier. All checks must be green before importing the schedule.
# Changes nothing - safe to re-run any time. Windows 10 / PowerShell 5.1 compatible.
$fail = 0
function Check($name, $ok) { if ($ok) { Write-Host "[OK]   $name" } else { Write-Host "[FAIL] $name"; $script:fail++ } }
# Win10: 'python' may be the Microsoft Store stub; fall back to the 'py -3' launcher.
function PyRun { if ($script:UsePyLauncher) { & py -3 @args 2>&1 } else { & python @args 2>&1 } }
$script:UsePyLauncher = -not ((python --version 2>&1) -match "^Python 3")
Check "Python 3.11+"        ((PyRun --version) -match "3\.1[1-9]")
Check "pywin32 importable"  ((PyRun -c "import win32com.client; print(1)") -match "1")
Check "classic Outlook COM" ((PyRun -c "import win32com.client as w; w.Dispatch('Outlook.Application'); print(1)") -match "1")
Check "claude CLI"          ((claude --version 2>&1) -match "\d")
# One health-checked listing for both MCP checks. "Connected" is required, not just the
# name — a server stuck at "Needs authentication" must show FAIL here.
$mcpList = claude mcp list 2>&1
Check "warmly MCP connected"   ($mcpList -match "warmly.*Connected")
Check "zoominfo MCP connected" ($mcpList -match "(?i)zoominfo.*Connected")
Check "NTP clock sync"      ((w32tm /query /status 2>&1) -match "Source:")
Check "tests green"         ((PyRun -m pytest -q) -match "passed")
Check "no REPLACE_ME in config" (-not ((Get-Content config\config.json -Raw) -match "REPLACE_ME"))
if ($fail -gt 0) { Write-Host "`n$fail check(s) failed - fix before go-live."; exit 1 }
Write-Host "`nAll green."
