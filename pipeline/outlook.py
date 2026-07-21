"""The ONLY module that talks to Outlook COM. Requires classic Outlook (New Outlook has no COM)."""
import urllib.request

# PR_SENDER_SMTP_ADDRESS on the message - present for internet mail and most Exchange mail.
PR_SENDER_SMTP = "http://schemas.microsoft.com/mapi/proptag/0x5D01001F"

def verify_url(url, timeout=10):
    if not str(url).startswith(("http://", "https://")):
        return False
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False

def sender_smtp(msg):
    """Resolve a message's sender to a real SMTP address.

    Internal Exchange mail reports the sender as an X.500 DN
    ('/o=exchangelabs/...'), which can never match approver_addresses - that
    silently broke approval replies from the approver's own tenant. Try the
    message-level SMTP property first, then resolve the DN through the GAL.
    """
    try:
        s = msg.PropertyAccessor.GetProperty(PR_SENDER_SMTP)
        if s and "@" in s:
            return s
    except Exception:
        pass
    try:
        if getattr(msg, "SenderEmailType", "") == "EX":
            exu = msg.Sender.GetExchangeUser()
            if exu is not None:
                s = exu.PrimarySmtpAddress
                if s and "@" in s:
                    return s
    except Exception:
        pass
    return getattr(msg, "SenderEmailAddress", "") or ""

class Outlook:
    def __init__(self, app=None):
        if app is None:
            import win32com.client
            app = win32com.client.Dispatch("Outlook.Application")
        self.app = app

    def send(self, to, subject, body_text, html_body=None, bcc=None):
        m = self.app.CreateItem(0)                  # olMailItem
        m.To = to
        if bcc:
            m.BCC = bcc
        m.Subject = subject
        if html_body:
            m.HTMLBody = html_body
        else:
            m.Body = body_text
        m.Send()
        return subject

    def inbox_since(self, iso_ts):
        ns = self.app.GetNamespace("MAPI")
        inbox = ns.GetDefaultFolder(6)               # olFolderInbox
        items = inbox.Items
        items.Sort("[ReceivedTime]", True)
        ts = iso_ts.replace("T", " ")[:16]           # 'YYYY-MM-DD HH:MM'
        restricted = items.Restrict(f"[ReceivedTime] >= '{ts}'")
        out = []
        for msg in restricted:
            # Inboxes also contain meeting invites, read receipts, NDRs etc. Anything that
            # can't yield the four fields below is not an approval reply - skip, never crash.
            try:
                if getattr(msg, "Class", 43) != 43:      # 43 = olMail
                    continue
                out.append({"subject": msg.Subject or "",
                            "sender": (sender_smtp(msg) or "").lower(),
                            "body": msg.Body or "",
                            "received": msg.ReceivedTime.strftime("%Y-%m-%dT%H:%M:%S")})
            except Exception:
                continue
        return out
