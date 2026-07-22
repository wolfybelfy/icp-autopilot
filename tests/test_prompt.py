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

def test_prompt_covers_persona_gate_and_no_surveillance():
    """The persona gate (marketing Manager+ / product Senior+) must run before drafting,
    and drafts must never reference the website visit (creepy)."""
    t = P.read_text(encoding="utf-8").lower()
    for required in ("persona gate",            # E1a
                     "--person",                # deterministic persona script call
                     "job_function", "management_level",   # carried into the draft
                     "never sound like surveillance",      # anti-creepy header
                     "you visited our site"):    # the exact phrasing that's banned
        assert required in t, f"prompt missing: {required}"

def test_prompt_covers_linkedin_antiban_and_jobs_signal():
    """The hiring signal must be zero-risk Google search, and the E5 LinkedIn read must
    bake in the anti-ban operating model (real logged-in Chrome, read-only, skip-on-block,
    never solve a captcha / never re-auth)."""
    t = P.read_text(encoding="utf-8").lower()
    for required in ("site:linkedin.com/jobs",     # hiring signal via search, not browsing
                     "recent-activity",            # E5 reads only the activity page
                     "already-logged-in chrome",   # real browser over CDP, not fresh chromium
                     "read only",                  # no interaction
                     "never solve or wait out a captcha",  # the exact loop we refuse to enter
                     "never re-auth",
                     "linkedin_blocked"):           # graceful skip gap
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
