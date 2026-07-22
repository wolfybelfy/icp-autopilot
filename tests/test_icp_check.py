import json, subprocess, sys
from pipeline.icp_check import evaluate

TECH_1K = {"raw_classifications": ["Business Services", "software.crm"], "employees": 5000, "funding_rounds": []}

def test_smart_play_non_primary_tech_qualifies():
    r = evaluate(TECH_1K)
    assert r["is_icp"] is True and r["qualification"] == "Emp 1k+" and r["reason"] == ""

def test_funding_route_qualifies_without_size():
    r = evaluate({"raw_classifications": ["SaaS"], "employees": 200,
                  "funding_rounds": ["Series B"]})
    assert r["is_icp"] is True and r["qualification"].startswith("Funding")

def test_right_industry_below_threshold():
    r = evaluate({"raw_classifications": ["Software"], "employees": 50, "funding_rounds": []})
    assert r["is_icp"] is False and "Below Threshold" in r["reason"]

def test_wrong_industry_right_size():
    r = evaluate({"raw_classifications": ["Retail"], "employees": 9000, "funding_rounds": []})
    assert r["is_icp"] is False and "Wrong Industry" in r["reason"]

def test_no_data_is_not_icp():
    r = evaluate({"raw_classifications": [], "employees": None, "funding_rounds": []})
    assert r["is_icp"] is False

def test_employee_range_string_parsed():
    r = evaluate({"raw_classifications": ["Software"], "employees": None,
                  "employee_range": "1,000 - 4,999", "funding_rounds": []})
    assert r["is_icp"] is True

def test_cli_roundtrip(tmp_path):
    f = tmp_path / "c.json"; f.write_text(json.dumps(TECH_1K))
    out = subprocess.run([sys.executable, "pipeline/icp_check.py", "--json", str(f)],
                         capture_output=True, text=True)
    assert out.returncode == 0 and json.loads(out.stdout)["is_icp"] is True

def test_nontech_with_own_platform_qualifies():
    # health company (not a tech industry) that owns its own AI platform -> ICP
    r = evaluate({"raw_classifications": ["Hospitals & Health Care"], "employees": 3000,
                  "funding_rounds": [], "description": "We build an AI diagnostics platform."})
    assert r["is_icp"] is True

def test_nontech_without_platform_still_rejected():
    r = evaluate({"raw_classifications": ["Hospitals & Health Care"], "employees": 3000,
                  "funding_rounds": [], "description": "A regional hospital network."})
    assert r["is_icp"] is False and "Wrong Industry" in r["reason"]

def test_person_cli_rejects_engineer(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"title": "Principal Software Engineer",
                             "management_level": "Non Manager"}))
    out = subprocess.run([sys.executable, "pipeline/icp_check.py", "--person", "--json", str(f)],
                         capture_output=True, text=True)
    assert out.returncode == 0 and json.loads(out.stdout)["is_fit"] is False
