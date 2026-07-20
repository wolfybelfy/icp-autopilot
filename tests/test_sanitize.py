import pytest
from pipeline.sanitize import sanitize_body, render, load_template

def test_strips_greeting_signoff_placeholder_subject():
    raw = ("Subject: Quick note\n\nHi Avik,\n\nBody paragraph one about them.\n\n"
           "Second short paragraph.\n\nBest,\n[Your name]")
    out = sanitize_body(raw)
    assert out == "Body paragraph one about them.\n\nSecond short paragraph."
    for bad in ("Hi Avik", "Subject:", "Best,", "[Your name]"):
        assert bad not in out

def test_strips_code_fence_and_various_signoffs():
    for signoff in ("Regards,", "Thanks,", "Cheers,", "Warm regards,", "Sincerely,"):
        raw = f"```\nHello there,\n\nThe message.\n\n{signoff}\nJane Doe\nUnbound IA\n```"
        assert sanitize_body(raw) == "The message."

def test_keeps_clean_body_untouched():
    body = "First paragraph.\n\nSecond paragraph with a clear ask?"
    assert sanitize_body(body) == body

def test_render_and_single_greeting_signature():
    tpl = load_template("txt")
    rendered = render(tpl, {
        "subject": "S", "first_name": "Avik",
        "body": sanitize_body("Hi Avik,\n\nThe pitch.\n\nBest,\n[Your name]"),
        "sender_name": "Uday Pawar", "sender_title": "Unbound IA", "postal_address": "addr",
    })
    assert rendered.count("Hi Avik,") == 1 and rendered.count("Uday Pawar") == 1
    assert "[Your name]" not in rendered and "{{" not in rendered

def test_render_raises_on_missing_var():
    with pytest.raises(KeyError):
        render("Hello {{name}} and {{other}}", {"name": "x"})
