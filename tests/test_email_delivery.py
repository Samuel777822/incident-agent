import notifications


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


def test_email_from_with_a_display_name_and_quotes_is_understood(monkeypatch):
    monkeypatch.setenv("EMAIL_FROM", '"Agent Daemon <alerts@agentdaemon.xyz>"')
    assert notifications.sender() == "alerts@agentdaemon.xyz" and notifications.sender_name() == "Agent Daemon"
    monkeypatch.setenv("EMAIL_FROM", " alerts@agentdaemon.xyz ")
    assert notifications.sender() == "alerts@agentdaemon.xyz"


def test_a_failing_provider_falls_back_to_the_next_one(temp_db, monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "'brevo-secret-key-123456'")
    monkeypatch.setenv("RESEND_API_KEY", "resend-secret-key-123456")
    monkeypatch.setenv("EMAIL_FROM", "alerts@example.com")
    calls = []

    def post(url, **kw):
        calls.append((url, kw))
        return _Resp(401, '{"message":"We have detected you are using an unrecognised IP address"}') if "brevo" in url else _Resp(200)
    monkeypatch.setattr(notifications.httpx, "post", post)
    ok, detail = notifications.send_now("a@example.com", "Hi", "Body", "test")
    assert ok and detail.startswith("accepted by resend")
    assert calls[0][1]["headers"]["api-key"] == "brevo-secret-key-123456"        # pasted quotes removed
    resend = calls[1][1]["json"]
    assert resend["reply_to"] and "<" in resend["from"] and resend["html"] and resend["text"] == "Body"


def test_busy_provider_is_retried_once(temp_db, monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "brevo-secret-key-123456")
    monkeypatch.setenv("EMAIL_FROM", "alerts@example.com")
    monkeypatch.setenv("EMAIL_RETRY_SECONDS", "0")
    answers = [_Resp(503, "busy"), _Resp(201)]
    monkeypatch.setattr(notifications.httpx, "post", lambda url, **kw: answers.pop(0))
    assert notifications.send_now("a@example.com", "Hi", "Body", "test") == (True, "accepted by brevo")


def test_common_provider_errors_get_a_plain_fix():
    assert "Authorized IPs" in notifications.explain("RuntimeError: Brevo rejected the message (HTTP 401): unrecognised IP address")
    assert "xkeysib" in notifications.explain("RuntimeError: Brevo rejected the message (HTTP 401): Key not found")
    assert "Add a sender" in notifications.explain("Brevo rejected the message (HTTP 400): Sending has been rejected because the sender you used is not valid")
    assert "App Password" in notifications.explain("SMTPAuthenticationError: (535, b'Authentication Failed')")
    assert notifications.explain("something nobody has seen") == ""
