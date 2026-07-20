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
