import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_config_shape_and_safe_defaults():
    cfg = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    assert cfg["mode"] == "review"
    assert cfg["safety"]["dry_run"] is True
    a = cfg["addresses"]
    for k in ("sender_mailbox", "reviewer_notify", "audit_bcc", "summary_to"):
        assert "@" in a[k]
    assert isinstance(a["approver_addresses"], list) and a["approver_addresses"]
    c = cfg["caps"]
    assert (c["sends_per_day"], c["domain_sends_per_week"], c["approval_requests_per_day"],
            c["zoominfo_enrich_per_day"], c["linkedin_loads_per_day"]) == (10, 2, 20, 50, 15)
    assert cfg["geo_allowlist"] == ["US"]
    assert cfg["approval_expiry_hours"] == 48 and cfg["retry_max_attempts"] == 12
    assert cfg["linkedin"]["enabled"] in (True, False)

def test_templates_have_no_video_and_required_vars():
    for ext in ("txt", "html"):
        t = (ROOT / "config" / f"email_template.{ext}").read_text(encoding="utf-8")
        assert "video" not in t.lower()
        for var in ("{{subject}}", "{{first_name}}", "{{body}}", "{{sender_name}}", "{{postal_address}}"):
            assert var in t
