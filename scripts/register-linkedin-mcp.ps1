# scripts\register-linkedin-mcp.ps1
# Register (or re-register) the read-only LinkedIn browser MCP, attaching to the dedicated
# CDP Chrome launched by start-cdp-chrome.ps1 (port 9222).
#
# Uses a splatted argument ARRAY so no argument can merge. A hand-pasted one-liner once
# lost the space between "@latest" and "--cdp-endpoint", producing an invalid package spec
# ("@playwright/mcp@latest--cdp-endpoint=...") and a "Failed to connect" server.
#
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-linkedin-mcp.ps1
$ErrorActionPreference = "Continue"

# Remove any prior (possibly broken) registration; ignore "not found".
try { & claude mcp remove linkedin-browser 2>$null | Out-Null } catch {}

$mcp = @(
    'mcp', 'add', '--scope', 'user', '--transport', 'stdio', 'linkedin-browser', '--',
    'npx', '-y', '@playwright/mcp@latest',
    '--cdp-endpoint=http://127.0.0.1:9222',
    '--cdp-timeout=10000'
)
& claude @mcp

Write-Host ""
Write-Host "=== claude mcp list ===" -ForegroundColor Cyan
& claude mcp list
Write-Host ""
Write-Host "Look for:  linkedin-browser  ...  Connected" -ForegroundColor Green
Write-Host "If it says Failed to connect, make sure Chrome is up first:" -ForegroundColor Yellow
Write-Host "  scripts\start-cdp-chrome.ps1" -ForegroundColor Yellow
