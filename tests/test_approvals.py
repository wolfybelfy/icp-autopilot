from pipeline.approvals import (new_token, find_token, parse_verdict, strip_quoted, Approvals)

def test_token_unique_and_format():
    seen = set()
    for _ in range(50):
        t = new_token(seen); assert len(t) == 6 and t == t.upper(); seen.add(t)

def test_find_token():
    assert find_token("RE: Approval [#A7F3B2] — John (Acme)") == "A7F3B2"
    assert find_token("no token here") is None

def test_verdicts():
    assert parse_verdict("GOOD") == "approved"
    assert parse_verdict("good\n\nSent from my iPhone") == "approved"
    assert parse_verdict("Yes, send it") == "approved"
    assert parse_verdict("No") == "rejected"
    assert parse_verdict("reject this one") == "rejected"
    assert parse_verdict("looks interesting, let me think") == "hold"
    assert parse_verdict("") == "hold"
    assert parse_verdict("good but no") == "hold"          # both -> ambiguity never sends

def test_quoted_reply_only_top_counts():
    reply = ("GOOD\n\nGet Outlook for iOS\n________________________________\n"
             "From: Sales Director\nSent: x\nSubject: Approval [#A7F3B2]\n"
             "Reply NO to reject.")                          # 'NO' lives in the quote
    assert parse_verdict(reply) == "approved"
    assert "Reply NO" not in strip_quoted(reply)

def test_lifecycle(tmp_path):
    a = Approvals(tmp_path / "approvals.json")
    a.create("A7F3B2", "drafts/inbox/v1.json", "jane@acme.com")
    assert "A7F3B2" in a.pending() and "jane@acme.com" in a.reserved_emails()
    a.decide("A7F3B2", "approved", "director@unboundia.com")
    assert "A7F3B2" not in a.pending()
    a.consume("A7F3B2")
    assert a.data["A7F3B2"]["status"] == "consumed"
    assert "jane@acme.com" in a.reserved_emails()            # reservation survives consumption

def test_expiry(tmp_path):
    a = Approvals(tmp_path / "approvals.json")
    a.create("AAAAAA", "d.json", "x@y.com", requested_at="2026-07-17T10:00:00")
    assert a.expire_older_than(48, now_iso="2026-07-20T10:00:00") == ["AAAAAA"]
    assert a.data["AAAAAA"]["status"] == "expired"
