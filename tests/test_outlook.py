from pipeline import outlook

class FakeMail:
    def __init__(self):
        self.sent = False
        self.To = self.BCC = self.Subject = self.Body = self.HTMLBody = ""
    def Send(self):
        self.sent = True

class FakeApp:
    def __init__(self):
        self.mail = FakeMail()
    def CreateItem(self, kind):
        assert kind == 0
        return self.mail

def test_send_sets_fields_and_sends():
    o = outlook.Outlook(app=FakeApp())
    o.send("a@b.com", "Subj", "text body", bcc="c@d.com")
    m = o.app.mail
    assert m.sent and m.To == "a@b.com" and m.BCC == "c@d.com" and m.Subject == "Subj"

def test_verify_url_rejects_non_http():
    assert outlook.verify_url("notaurl") is False
    assert outlook.verify_url("ftp://x") is False
