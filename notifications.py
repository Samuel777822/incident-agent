"""Email notifications for the customer portal.

Providers, in this order; when one fails, the next configured one is tried:

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
import html as _html
import threading
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

import httpx

log = logging.getLogger(__name__)

_SECRET_ENV = ("BREVO_API_KEY", "RESEND_API_KEY", "SMTP_PASSWORD")
_SENDER_NAME = "Agent Daemon"


# The two founders are the only administrators. ADMIN_EMAILS in Render overrides this list (comma separated);
# leave it unset, or set it to exactly these two addresses. Admin addresses can never be registered on the public sign-up form.
DEFAULT_ADMIN_EMAILS = ("pranavvrao@agentdaemon.xyz", "abhaysamuel@agentdaemon.xyz")
DEFAULT_SUPPORT_EMAIL = "contact@agentdaemon.xyz"


def admin_emails() -> list[str]:
    raw = os.getenv("ADMIN_EMAILS", "") or os.getenv("ADMIN_EMAIL", "") or ",".join(DEFAULT_ADMIN_EMAILS)
    return sorted({item.strip().lower() for item in raw.split(",") if item.strip()})


def support_email() -> str:
    """Public support address (Contact page, footer, ticket emails, chatbot). SUPPORT_EMAIL overrides the default."""
    return os.getenv("SUPPORT_EMAIL", "").strip() or DEFAULT_SUPPORT_EMAIL


def _env(name: str) -> str:
    """An env value without the spaces or quotes people paste by accident ("xkeysib-..." -> xkeysib-...)."""
    return os.getenv(name, "").strip().strip("'\"").strip()


def sender() -> str:
    """The bare address from EMAIL_FROM. Accepts 'Agent Daemon <alerts@domain>' as well as 'alerts@domain'."""
    raw = _env("EMAIL_FROM")
    address = parseaddr(raw)[1] if "<" in raw else raw
    return address.strip()


def sender_name() -> str:
    raw = _env("EMAIL_FROM")
    name = parseaddr(raw)[0] if "<" in raw else ""
    return name.strip() or _env("EMAIL_FROM_NAME") or _SENDER_NAME


def providers() -> list[str]:
    """Every configured provider, best first. A failure with one falls back to the next."""
    found = []
    if _env("BREVO_API_KEY"):
        found.append("brevo")
    if _env("RESEND_API_KEY"):
        found.append("resend")
    if all(_env(name) for name in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD")):
        found.append("smtp")
    return found


def provider() -> str:
    found = providers()
    return found[0] if found else ""


def configured() -> bool:
    return bool(provider() and sender())


def _scrub(text: str) -> str:
    for name in _SECRET_ENV:
        for value in (os.getenv(name, ""), _env(name)):
            if value and len(value) > 3:
                text = text.replace(value, "***")
    return text


def _record(kind: str, recipient: str, subject: str, ok: bool, detail: str) -> None:
    try:
        import portal_db
        portal_db.log_notification(kind, recipient, subject, ok, detail)
    except Exception:  # logging must never break a request
        log.exception("Could not record notification attempt")


class _Temporary(RuntimeError):
    """The provider is busy or unreachable: worth one more try."""


def _post_json(name: str, url: str, headers: dict, payload: dict) -> None:
    try:
        response = httpx.post(url, headers=headers, json=payload, timeout=15)
    except httpx.HTTPError as exc:
        raise _Temporary(f"could not reach {name} ({type(exc).__name__})") from exc
    if response.status_code >= 500 or response.status_code == 429:
        raise _Temporary(f"{name} is busy (HTTP {response.status_code}): {response.text[:160]}")
    if response.status_code >= 300:
        raise RuntimeError(f"{name} rejected the message (HTTP {response.status_code}): {response.text[:200]}")


def html_version(body: str) -> str:
    """A simple, light HTML copy of a plain-text email. Mail with both a text and an HTML part, a real reply-to address and no
    images or tracking pixels looks like a normal person's email, which helps it stay out of spam."""
    lines = _html.escape(body).split("\n")
    paragraphs = "<br>".join(lines)
    return ("<!doctype html><html><body style='margin:0;padding:24px;background:#f6f4fa;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif'>"
            "<div style='max-width:560px;margin:0 auto;background:#ffffff;border-radius:12px;padding:24px;color:#1f1a2b;font-size:15px;line-height:1.6'>"
            f"<div style='font-weight:700;font-size:16px;margin-bottom:14px;color:#6a2bd9'>Agent Daemon</div>{paragraphs}"
            "<div style='margin-top:22px;padding-top:12px;border-top:1px solid #eee;color:#8a8399;font-size:12px'>"
            f"Agent Daemon · {_html.escape(support_email())}</div></div></body></html>")


def _send_brevo(to: str, subject: str, body: str, html: str | None = None) -> None:
    payload = {"sender": {"name": sender_name(), "email": sender()}, "to": [{"email": to}],
               "replyTo": {"email": support_email(), "name": sender_name()},
               "subject": subject, "textContent": body, "htmlContent": html or html_version(body)}
    _post_json("Brevo", "https://api.brevo.com/v3/smtp/email",
               {"api-key": _env("BREVO_API_KEY"), "accept": "application/json", "content-type": "application/json"},
               payload)


def _send_resend(to: str, subject: str, body: str, html: str | None = None) -> None:
    payload = {"from": f"{sender_name()} <{sender()}>", "to": [to], "subject": subject, "text": body,
               "html": html or html_version(body), "reply_to": support_email()}
    _post_json("Resend", "https://api.resend.com/emails",
               {"Authorization": "Bearer " + _env("RESEND_API_KEY"), "Content-Type": "application/json"},
               payload)


def _send_smtp(to: str, subject: str, body: str, html: str | None = None) -> None:
    port = int(_env("SMTP_PORT") or "587")
    message = EmailMessage()
    message["From"] = f"{sender_name()} <{sender()}>"
    message["To"] = to
    message["Subject"] = subject
    message["Reply-To"] = support_email()
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=sender().split("@")[-1] or None)
    message.set_content(body)
    message.add_alternative(html or html_version(body), subtype="html")
    host = _env("SMTP_HOST")
    try:
        client = smtplib.SMTP_SSL(host, port, timeout=15) if port == 465 else smtplib.SMTP(host, port, timeout=15)
    except OSError as exc:
        raise _Temporary(f"could not connect to {host}:{port} ({type(exc).__name__}: {exc})") from exc
    with client as smtp:
        if port != 465:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
        smtp.login(_env("SMTP_USERNAME"), os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


_SENDERS = {"brevo": _send_brevo, "resend": _send_resend, "smtp": _send_smtp}


def _send_with(name: str, to: str, subject: str, body: str, html: str | None) -> None:
    """One provider, with a single retry when it is only busy or unreachable."""
    try:
        _SENDERS[name](to, subject, body, html=html)
    except _Temporary:
        time.sleep(float(os.getenv("EMAIL_RETRY_SECONDS", "2")))
        _SENDERS[name](to, subject, body, html=html)


def send_now(to: str, subject: str, body: str, kind: str = "notice", html: str | None = None) -> tuple[bool, str]:
    """Send one message and return (accepted_by_provider, detail). Tries every configured provider in turn."""
    if not configured():
        detail = ("Email is not configured. Set BREVO_API_KEY (or RESEND_API_KEY) and EMAIL_FROM." if sender() else
                  "Email is not configured: EMAIL_FROM is not set. Add EMAIL_FROM (for example alerts@agentdaemon.xyz) in Render.")
        log.warning("Email not sent to %s: %s", to, detail)
        _record(kind, to, subject, False, detail)
        return False, detail
    failures = []
    for name in providers():
        try:
            _send_with(name, to, subject, body, html)
        except Exception as exc:
            failure = _scrub(f"{type(exc).__name__}: {exc}")[:260]
            log.warning("Email to %s failed via %s: %s", to, name, failure)
            failures.append(failure)
            continue
        detail = f"accepted by {name}" + (f" (after {len(failures)} other provider failed: {failures[0][:160]})" if failures else "")
        _record(kind, to, subject, True, detail)
        return True, detail
    detail = " | ".join(failures)[:300]
    _record(kind, to, subject, False, detail)
    return False, detail


# Plain explanations of what providers answer, with the exact place to fix it. Shown under every failed row on the admin page.
_EXPLAIN = [
    (("unrecognised ip", "unrecognized ip", "ip address"),
     "Brevo blocked the message because it came from Render's server, an address Brevo does not know. In Brevo: your name (top right), "
     "Security, Authorized IPs, then turn OFF 'Block unknown IP addresses' (Render's addresses change, so adding one IP will not last). "
     "Then press 'Send test email' again."),
    (("key not found", "api key is invalid", "unauthorized", "http 401"),
     "The API key in Render is wrong or was deleted. In Brevo: SMTP & API, API Keys, Generate a new API key (it starts with xkeysib-). "
     "In Render: your web service AND the worker, Environment, BREVO_API_KEY, paste it with no quotes or spaces, Save."),
    (("sender", "not valid"), "The sender address in EMAIL_FROM is not approved by the email service. In Brevo: Senders, Domains & "
     "Dedicated IPs, Senders, Add a sender with exactly the EMAIL_FROM address, then confirm the code Brevo emails to it (open it in Zoho). "
     "Better still, authenticate the whole domain under Domains (this is also what keeps mail out of spam)."),
    (("not yet activated", "not activated", "account is under validation", "permission_denied", "http 403"),
     "The email account is not allowed to send yet. In Brevo: open Transactional (or Campaigns, Settings) and finish the account "
     "activation form; new Brevo accounts are checked before they can send. If it says 'under validation', wait for Brevo's email."),
    (("domain is not verified", "verify a domain", "only send testing emails"),
     "Resend only sends from a verified domain. In Resend: Domains, Add domain, copy the records it shows into your DNS, press Verify."),
    (("smtpauthenticationerror", "authentication failed", "username and password not accepted", "535"),
     "The SMTP user name or password is wrong. For Zoho, create an App Password (Zoho Accounts, Security, App Passwords) and put it in "
     "SMTP_PASSWORD."),
    (("could not connect", "timed out", "network is unreachable", "connecttimeout", "connecterror"),
     "Render could not reach the email service. If this is SMTP: Render's free plan blocks email ports, use BREVO_API_KEY instead. "
     "Otherwise it was a short outage: try again in a minute."),
    (("http 400", "invalid_parameter", "email is not valid", "invalid email"),
     "The email service did not accept an address. Check EMAIL_FROM and ADMIN_EMAILS in Render for typos (no quotes, comma separated)."),
    (("not configured", "email_from is not set"),
     "In Render (web service AND worker), Environment: add BREVO_API_KEY and EMAIL_FROM (an address on your domain), then Save."),
]


def explain(detail: str) -> str:
    """The fix for a failed send, in plain words ('' when we do not recognise the error)."""
    text = (detail or "").lower()
    for needles, fix in _EXPLAIN:
        if needles == ("sender", "not valid"):
            if "sender" in text and ("not valid" in text or "invalid" in text or "not verified" in text):
                return fix
            continue
        if any(n in text for n in needles):
            return fix
    return ""


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
        ok, detail = send_now(address, "Test message from your Agent Daemon admin page",
                              "Hi,\n\nYou pressed 'Send test email' on the Agent Daemon admin page. If you can read this, admin alerts "
                              "(paused cases, spending limits, errors) reach this inbox.\n\nIf this landed in Spam, mark it as Not spam once "
                              "and add the sender to your contacts.\n\nAgent Daemon", "test")
        results.append((address, ok, detail))
    return results



