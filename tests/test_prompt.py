import pathlib
P = pathlib.Path(__file__).resolve().parents[1] / "prompts" / "run-prompt.md"

def test_prompt_covers_all_stages_and_rules():
    t = P.read_text(encoding="utf-8").lower()
    for required in ("watermark", "seen.json", "icp_check.py", "enrich_contacts",
                     "enrich_companies", "enrich_company_signals", "websearch",
                     "linkedin", "http 200", "never send", "drafts/inbox",
                     "claude-runs.jsonl", "early exit", "retry"):
        assert required in t, f"prompt missing: {required}"
    assert "video" not in t

def test_prompt_covers_live_pipeline_rules():
    """Regressions from the first day of spare-PC ticks — each rule burned a real tick."""
    t = P.read_text(encoding="utf-8").lower()
    for required in ("tick.lock",            # claude must ignore run.ps1's own lock
                     "backfill",             # backlog drain cursor
                     "retry pass",           # retries run even on zero-visitor ticks
                     "never invent a timestamp",   # watermark = observed lastSeen only
                     "paging optimization",  # seen.json, not watermark, defines "new"
                     "scratch"):             # no helper scripts in state/
        assert required in t, f"prompt missing: {required}"
