# One-time: mark this repo folder trusted for headless `claude -p` runs.
# Verified 2026-07-20: an UNTRUSTED workspace does not load user-scoped MCP servers
# (warmly) and ignores .claude/settings.json - every scheduled tick stalls. The claude
# CLI's own warning names this exact fix. Backs up ~/.claude.json first. Safe to re-run.
$Root = Split-Path -Parent $PSScriptRoot
function PyRun { if ($script:UsePyLauncher) { & py -3 @args 2>&1 } else { & python @args 2>&1 } }
$script:UsePyLauncher = -not ((python --version 2>&1) -match "^Python 3")
Copy-Item "$env:USERPROFILE\.claude.json" "$env:USERPROFILE\.claude.json.bak" -Force
$code = @"
import json, pathlib
p = pathlib.Path.home() / '.claude.json'
key = str(pathlib.Path(r'$Root').resolve()).replace('\\', '/')
d = json.load(open(p, encoding='utf-8'))
d.setdefault('projects', {}).setdefault(key, {})['hasTrustDialogAccepted'] = True
json.dump(d, open(p, 'w', encoding='utf-8'), indent=2)
print('trusted:', key)
"@
PyRun -c $code
