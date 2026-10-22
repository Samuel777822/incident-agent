"""Email notifications for the customer portal.

Providers, first configured one wins:

1. Brevo HTTPS API   BREVO_API_KEY  + EMAIL_FROM   (works on Render's free tier)
2. Resend HTTPS API  RESEND_API_KEY + EMAIL_FROM
3. SMTP              SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD + EMAIL_FROM
                     (Render's free tier blocks outbound SMTP, so prefer 1 or 2)

Every attempt is written to the notification_log table, so the admin page can
show what really happened. "ok" means the provider accepted the message. It
does not prove inbox placement. Secrets are never logged.
"""
from __future__ import annotations

import logging
import os
import smtplib
import threading
from email.message import EmailMessage

import httpx

log = logging.getLogger(__name__)

_SECRET_ENV = ("BREVO_API_KEY", "RESEND_API_KEY", "SMTP_PASSWORD")
_SENDER_NAME = "Agent Daemon"


def admin_emails() -> list[str]:
    raw = os.getenv("ADMIN_EMAILS", "") or os.getenv("ADMIN_EMAIL", "")
    return sorted({item.strip().lower() for item in raw.split(",") if item.strip()})


def sender() -> str:
    return os.getenv("EMAIL_FROM", "").strip()


def provider() -> str:
    if os.getenv("BREVO_API_KEY", "").strip():
        return "brevo"
    if os.getenv("RESEND_API_KEY", "").strip():
        return "resend"
    if all(os.getenv(name, "").strip() for name in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD")):
        return "smtp"
    return ""


def configured() -> bool:
    return bool(provider() and sender())


def _scrub(text: str) -> str:
    for name in _SECRET_ENV:
        value = os.getenv(name, "")
        if value and len(value) > 3:
            text = text.replace(value, "***")
    return text


def _record(kind: str, recipient: str, subject: str, ok: bool, detail: str) -> None:
    try:
        import portal_db
        portal_db.log_notification(kind, recipient, subject, ok, detail)
    except Exception:  # logging must never break a request
        log.exception("Could not record notification attempt")


def _post_json(name: str, url: str, headers: dict, payload: dict) -> None:
    response = httpx.post(url, headers=headers, json=payload, timeout=15)
    if response.status_code >= 300:
        raise RuntimeError(f"{name} rejected the message (HTTP {response.status_code}): {response.text[:200]}")


def _send_brevo(to: str, subject: str, body: str) -> None:
    _post_json("Brevo", "https://api.brevo.com/v3/smtp/email",
               {"api-key": os.environ["BREVO_API_KEY"].strip(), "accept": "application/json",
                "content-type": "application/json"},
               {"sender": {"name": _SENDER_NAME, "email": sender()}, "to": [{"email": to}],
                "subject": subject, "textContent": body})


def _send_resend(to: str, subject: str, body: str) -> None:
    _post_json("Resend", "https://api.resend.com/emails",
               {"Authorization": "Bearer " + os.environ["RESEND_API_KEY"].strip(),
                "Content-Type": "application/json"},
               {"from": f"{_SENDER_NAME} <{sender()}>", "to": [to], "subject": subject, "text": body})


def _send_smtp(to: str, subject: str, body: str) -> None:
    port = int(os.getenv("SMTP_PORT", "587"))
    message = EmailMessage()
    message["From"] = sender()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    host = os.environ["SMTP_HOST"].strip()
    client = smtplib.SMTP_SSL(host, port, timeout=15) if port == 465 else smtplib.SMTP(host, port, timeout=15)
    with client as smtp:
        if port != 465:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
        smtp.login(os.environ["SMTP_USERNAME"].strip(), os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


def send_now(to: str, subject: str, body: str, kind: str = "notice") -> tuple[bool, str]:
    """Send one message and return (accepted_by_provider, detail)."""
    if not configured():
        detail = "Email is not configured. Set BREVO_API_KEY (or RESEND_API_KEY) and EMAIL_FROM."
        log.warning("Email not sent to %s: %s", to, detail)
        _record(kind, to, subject, False, detail)
        return False, detail
    name = provider()
    try:
        {"brevo": _send_brevo, "resend": _send_resend, "smtp": _send_smtp}[name](to, subject, body)
    except Exception as exc:
        detail = _scrub(f"{type(exc).__name__}: {exc}")[:300]
        log.warning("Email to %s failed via %s: %s", to, name, detail)
        _record(kind, to, subject, False, detail)
        return False, detail
    detail = f"accepted by {name}"
    _record(kind, to, subject, True, detail)
    return True, detail


def queue(to: str, subject: str, body: str, kind: str = "notice") -> None:
    """Send in the background so a slow mail provider never blocks a page."""
    if os.getenv("NOTIFY_SYNC") == "1":
        send_now(to, subject, body, kind)
        return
    threading.Thread(target=send_now, args=(to, subject, body, kind), daemon=True).start()


def notify_admins(subject: str, body: str, kind: str = "admin") -> list[str]:
    addresses = admin_emails()
    if not addresses:
        log.warning("No ADMIN_EMAILS configured; admin notification skipped: %s", subject)
        _record(kind, "(no admins configured)", subject, False, "ADMIN_EMAILS is empty")
    for address in addresses:
        queue(address, subject, body, kind)
    return addresses


def notify_customer(address: str, subject: str, body: str, kind: str = "customer") -> None:
    queue(address, subject, body, kind)


def send_test_to_admins() -> list[tuple[str, bool, str]]:
    results = []
    for address in admin_emails():
        ok, detail = send_now(address, "Agent Daemon test email",
                              "This is a test message from the Agent Daemon admin page.\n"
                              "If you can read it, admin alerts reach this inbox.", "test")
        results.append((address, ok, detail))
    return results
