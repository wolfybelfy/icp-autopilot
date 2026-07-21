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

def test_prompt_covers_priority_target():
    """scripts/run-once.ps1 forces one visitor through by dropping state/priority.json;
    the prompt must honour it (search Warmly by email regardless of backlog position)."""
    t = P.read_text(encoding="utf-8").lower()
    for required in ("priority target",       # the operator-forced section exists
                     "state/priority.json",   # the exact file it keys on
                     "30 pages",              # bounded search so it can't loop forever
                     "priority_not_found"):    # honest report when the visitor aged out
        assert required in t, f"prompt missing: {required}"

def test_prompt_covers_enrichment_verdict_rules():
    """2026-07-21: k.morrison@f5.com was a ZoomInfo FULL_MATCH (Kyle Morrison, Principal
    SWE at F5, score 91) but E1 misread it as a miss, cached the miss for 7 days, and
    every retry replayed the poisoned cache until the prospect parked. Meanwhile two
    freemail visitors burned retries the send gates could never pass."""
    t = P.read_text(encoding="utf-8").lower()
    for required in ("full_match",           # email-lookup FULL_MATCH = the person, final
                     "identity anchor",      # never re-judged against Warmly's fuzzy name
                     "fallback",             # second query form before declaring a miss
                     "must never\n" "reuse one",   # detection may use cached misses...
                     "never\ntrust a cached person-level miss",  # ...retries may not
                     "freemail_no_business_email"):  # freemail dead-ends park immediately
        assert required.replace("\n", " ") in t.replace("\n", " "), \
            f"prompt missing: {required!r}"
