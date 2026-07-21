# One-time: mark this repo folder trusted for headless `claude -p` runs.
# Verified 2026-07-20: an UNTRUSTED workspace does not load user-scoped MCP servers
# (warmly) and ignores .claude/settings.json - every scheduled tick stalls. The claude
# CLI's own warning names this exact fix. Backs up ~/.claude.json first. Safe to re-run.
#
# 2026-07-21 hardening: trust is keyed by the RAW path string (case- and slash-exact;
# see claude-code issues #77837/#73317), so write BOTH the literal and resolved-case
# keys. Also: a LIVE claude session rewrites ~/.claude.json from memory when it exits,
# silently undoing this patch - so warn if one is running (scheduled ticks launch one
# every 5 minutes; run.ps1 now self-heals trust each tick as the real safety net).
$Root = Split-Path -Parent $PSScriptRoot
function PyRun { if ($script:UsePyLauncher) { & py -3 @args 2>&1 } else { & python @args 2>&1 } }
$script:UsePyLauncher = -not ((python --version 2>&1) -match "^Python 3")

$live = @(Get-Process -Name claude, node -ErrorAction SilentlyContinue)
if ($live.Count -gt 0) {
    Write-Host "WARNING: $($live.Count) claude/node process(es) running - a live session can" -ForegroundColor Yellow
    Write-Host "overwrite this patch when it exits. Best to run between ticks (or rely on" -ForegroundColor Yellow
    Write-Host "run.ps1's per-tick self-heal)." -ForegroundColor Yellow
}

Copy-Item "$env:USERPROFILE\.claude.json" "$env:USERPROFILE\.claude.json.bak" -Force
$code = @"
import json, pathlib
p = pathlib.Path.home() / '.claude.json'
keys = {r'$Root'.replace('\\', '/'), str(pathlib.Path(r'$Root').resolve()).replace('\\', '/')}
d = json.load(open(p, encoding='utf-8'))
for key in sorted(keys):
    d.setdefault('projects', {}).setdefault(key, {})['hasTrustDialogAccepted'] = True
    print('trusted:', key)
json.dump(d, open(p, 'w', encoding='utf-8'), indent=2)
existing = [k for k in d['projects'] if 'icp' in k.lower()]
print('all ICP-ish project keys on file:', *existing, sep='\n  ')
"@
PyRun -c $code
