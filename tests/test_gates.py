from pipeline import gates

def good_draft():
    return {
        "visitor_id": "v1", "detected_at": "2026-07-20T09:00:00",
        "person": {"full_name": "Jane Roe", "first_name": "Jane", "email": "jane@acme.com",
                   "title": "VP Marketing", "seniority": "VP Level Exec",
                   "job_function": "Marketing", "management_level": "VP Level Exec"},
        "company": {"name": "Acme", "domain": "acme.com", "country": "US",
                    "raw_classifications": ["Software"], "employees": 5000,
                    "funding_rounds": []},
        "visit": {"pages": ["/pricing"], "last_seen": "2026-07-20T08:59:00"},
        "email": {"subject": "S", "body_paragraphs": ["P1", "P2"]},
        "sources": [{"claim": "c", "url": "https://acme.example.com/x"}],
        "enrichment": {"gaps": []},
        "enrich": {"provider": "zoominfo_mcp", "match_level": "FULL_MATCH"},
    }

def ctx(tmp_path, **over):
    base = dict(
        cfg={"caps": {"sends_per_day": 10, "domain_sends_per_week": 2},
             "geo_allowlist": ["US"],
             "sender": {"name": "Uday", "title": "T", "postal_address": "A"},
             "safety": {"dry_run": False}},
        send_log={}, reserved=set(), caps={"sends": {}, "domain_sends": {}},
        suppression=set(), verify_url=lambda u: True, root=tmp_path,
        now_iso="2026-07-20T12:00:00")
    base.update(over)
    return gates.GateCtx(**base)

def test_clean_draft_passes(tmp_path):
    assert gates.evaluate(good_draft(), ctx(tmp_path)) == []

def test_kill_switch(tmp_path):
    (tmp_path / "STOP").write_text("")
    assert any("kill switch" in r for r in gates.evaluate(good_draft(), ctx(tmp_path)))

def test_dry_run_blocks(tmp_path):
    c = ctx(tmp_path); c.cfg["safety"]["dry_run"] = True
    assert any("dry_run" in r for r in gates.evaluate(good_draft(), c))

def test_schema_missing_field(tmp_path):
    d = good_draft(); del d["email"]
    assert gates.evaluate(d, ctx(tmp_path))

def test_icp_recheck_blocks_non_icp(tmp_path):
    d = good_draft(); d["company"]["employees"] = 50
    assert any("ICP" in r for r in gates.evaluate(d, ctx(tmp_path)))

def test_persona_recheck_blocks_wrong_role(tmp_path):
    d = good_draft()
    d["person"].update(title="Principal Software Engineer", job_function="Engineering",
                       management_level="Non Manager")
    assert any("persona" in r for r in gates.evaluate(d, ctx(tmp_path)))

def test_freemail_blocks(tmp_path):
    d = good_draft(); d["person"]["email"] = "jane@gmail.com"
    assert gates.evaluate(d, ctx(tmp_path))

def test_domain_mismatch_blocks(tmp_path):
    d = good_draft(); d["person"]["email"] = "jane@other-corp.com"
    assert any("does not match" in r for r in gates.evaluate(d, ctx(tmp_path)))

def test_suppression_blocks(tmp_path):
    assert gates.evaluate(good_draft(), ctx(tmp_path, suppression={"jane@acme.com"}))

def test_dedup_sent_and_reserved(tmp_path):
    assert gates.evaluate(good_draft(), ctx(tmp_path, send_log={"jane@acme.com": {}}))
    assert gates.evaluate(good_draft(), ctx(tmp_path, reserved={"jane@acme.com"}))

def test_daily_cap(tmp_path):
    c = ctx(tmp_path, caps={"sends": {"2026-07-20": 10}, "domain_sends": {}})
    assert any("cap" in r for r in gates.evaluate(good_draft(), c))

def test_domain_weekly_cap(tmp_path):
    c = ctx(tmp_path, caps={"sends": {}, "domain_sends":
            {"acme.com": ["2026-07-18T10:00:00", "2026-07-19T10:00:00"]}})
    assert any("domain" in r for r in gates.evaluate(good_draft(), c))

def test_geo_blocks_non_us(tmp_path):
    d = good_draft(); d["company"]["country"] = "IN"
    assert any("geo" in r for r in gates.evaluate(d, ctx(tmp_path)))

def test_dead_link_blocks(tmp_path):
    assert gates.evaluate(good_draft(), ctx(tmp_path, verify_url=lambda u: False))

def test_replace_me_sender_blocks(tmp_path):
    c = ctx(tmp_path); c.cfg["sender"]["name"] = "REPLACE_ME"
    assert any("REPLACE_ME" in r for r in gates.evaluate(good_draft(), c))
