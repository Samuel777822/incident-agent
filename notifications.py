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


def _send_brevo(to: str, subject: str, body: str, html: str | None = None) -> None:
    payload = {"sender": {"name": _SENDER_NAME, "email": sender()}, "to": [{"email": to}],
               "subject": subject, "textContent": body}
    if html:
        payload["htmlContent"] = html
    _post_json("Brevo", "https://api.brevo.com/v3/smtp/email",
               {"api-key": os.environ["BREVO_API_KEY"].strip(), "accept": "application/json",
                "content-type": "application/json"},
               payload)


def _send_resend(to: str, subject: str, body: str, html: str | None = None) -> None:
    payload = {"from": f"{_SENDER_NAME} <{sender()}>", "to": [to], "subject": subject, "text": body}
    if html:
        payload["html"] = html
    _post_json("Resend", "https://api.resend.com/emails",
               {"Authorization": "Bearer " + os.environ["RESEND_API_KEY"].strip(),
                "Content-Type": "application/json"},
               payload)


def _send_smtp(to: str, subject: str, body: str, html: str | None = None) -> None:
    port = int(os.getenv("SMTP_PORT", "587"))
    message = EmailMessage()
    message["From"] = sender()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    host = os.environ["SMTP_HOST"].strip()
    client = smtplib.SMTP_SSL(host, port, timeout=15) if port == 465 else smtplib.SMTP(host, port, timeout=15)
    with client as smtp:
        if port != 465:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
        smtp.login(os.environ["SMTP_USERNAME"].strip(), os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


def send_now(to: str, subject: str, body: str, kind: str = "notice", html: str | None = None) -> tuple[bool, str]:
    """Send one message and return (accepted_by_provider, detail). Supports optional HTML."""
    if not configured():
        detail = "Email is not configured. Set BREVO_API_KEY (or RESEND_API_KEY) and EMAIL_FROM."
        log.warning("Email not sent to %s: %s", to, detail)
        _record(kind, to, subject, False, detail)
        return False, detail
    name = provider()
    try:
        {"brevo": _send_brevo, "resend": _send_resend, "smtp": _send_smtp}[name](to, subject, body, html=html)
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



def render_java_launch_email(recipient_email: str, unsubscribe_token: str, base_url: str) -> tuple[str, str]:
    """Render the official Java Integration Launch announcement email.
    Returns (html_content, plain_text_fallback).
    """
    clean_base = base_url.rstrip("/")
    docs_url = f"{clean_base}/docs"
    contact_url = f"{clean_base}/contact"
    unsub_url = f"{clean_base}/unsubscribe?token={unsubscribe_token}"

    plain_text = f"""AGENT DAEMON
Java Support Is Here.

We're excited to announce that Java integration is officially available on Agent Daemon!

You asked. We built.

Agent Daemon is expanding its capabilities to help Java developers monitor application errors, investigate incidents and streamline debugging.

Your journey towards smarter incident response just got bigger.

What's Included:
* Java application monitoring (Spring Boot, Quarkus, Micronaut, and core JVM)
* Intelligent incident detection & recurring stack trace clustering
* AI-powered root cause analysis for JVM runtime exceptions
* Streamlined debugging workflows & automated reviewable GitHub pull requests

Explore Java Integration:
{docs_url}

Thank you for being among the first to show interest in our Java integration. We're excited to have you on this journey.

Regards,
Team Agent Daemon

---
Agent Daemon · Autonomous AI on-call engineer for resilient engineering teams.
Website: {clean_base}/
Contact Support: {contact_url}
Unsubscribe from launch updates: {unsub_url}
"""

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Java Support Is Here · Agent Daemon</title>
  <!--[if mso]>
  <noscript>
    <xml>
      <o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings>
    </xml>
  </noscript>
  <![endif]-->
  <style>
    body {{ margin:0; padding:0; background:#07050b; color:#f2edf7; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif; -webkit-font-smoothing:antialiased; }}
    table {{ border-collapse:collapse; }}
    a {{ color:#ff7a6b; text-decoration:none; }}
    @media only screen and (max-width: 600px) {{
      .wrapper {{ width:100% !important; padding:12px !important; }}
      .card-content {{ padding:24px 18px !important; }}
      .headline {{ font-size:26px !important; line-height:1.25 !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#07050b;color:#f2edf7;">
  <!-- Preview text -->
  <div style="display:none;font-size:1px;color:#07050b;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;">
    Your applications just got a new AI-powered incident response companion.
  </div>

  <table role="presentation" width="100%" bgcolor="#07050b" cellpadding="0" cellspacing="0" style="background:#07050b;padding:36px 12px;">
    <tr>
      <td align="center">
        <!-- Main Container -->
        <table role="presentation" class="wrapper" width="580" cellpadding="0" cellspacing="0" style="max-width:580px;width:100%;background:#120a1b;border:1px solid #3a2338;border-radius:14px;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,0.6);">
          
          <!-- Brand Header -->
          <tr>
            <td style="padding:28px 36px 20px 36px;border-bottom:1px solid #23162b;text-align:left;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td>
                    <span style="display:inline-block;width:28px;height:28px;line-height:28px;text-align:center;border-radius:6px;background:linear-gradient(135deg,#ff4a3a,#9a4dff);color:#ffffff;font-weight:bold;font-size:15px;margin-right:8px;vertical-align:middle;">A</span>
                    <span style="font-size:16px;font-weight:700;letter-spacing:0.04em;color:#ffffff;vertical-align:middle;">AGENT DAEMON</span>
                  </td>
                  <td align="right">
                    <span style="display:inline-block;padding:4px 10px;border-radius:20px;background:rgba(227,189,116,0.15);border:1px solid #e3bd74;color:#e3bd74;font-size:11px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;">
                      ☕ Official Java Release
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Hero & Announcement Body -->
          <tr>
            <td class="card-content" style="padding:36px 36px 28px 36px;text-align:left;">
              <div style="font-size:12px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#ff7a6b;margin-bottom:8px;">
                Major Milestone Announcement
              </div>
              <h1 class="headline" style="margin:0 0 16px 0;font-size:32px;line-height:1.2;color:#ffffff;font-weight:800;letter-spacing:-0.02em;">
                Java Support Is Here.
              </h1>
              <p style="margin:0 0 16px 0;font-size:16px;line-height:1.6;color:#cfc5dc;">
                We're excited to announce that <b>Java integration is officially available</b> on Agent Daemon!
              </p>
              <p style="margin:0 0 18px 0;font-size:15px;line-height:1.6;color:#a99dbb;">
                You asked. We built.
              </p>
              <p style="margin:0 0 24px 0;font-size:15px;line-height:1.6;color:#cfc5dc;">
                Agent Daemon is expanding its capabilities to help Java developers monitor application errors, investigate incidents and streamline debugging. Your journey towards smarter incident response just got bigger.
              </p>

              <!-- Feature Highlights Box -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#1a1024;border:1px solid #331e36;border-radius:10px;margin-bottom:28px;">
                <tr>
                  <td style="padding:20px 22px;">
                    <div style="font-size:13px;font-weight:700;color:#f2edf7;margin-bottom:12px;letter-spacing:0.02em;">
                      ⚡ What Java Support Brings to Your Stack:
                    </div>
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="padding:4px 0;font-size:14px;color:#cfc5dc;line-height:1.5;">
                          <b style="color:#6fe0b0;">✓</b> <b>Java application monitoring:</b> First-class support for Spring Boot, Quarkus, Micronaut, and standalone JVM apps.
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:6px 0;font-size:14px;color:#cfc5dc;line-height:1.5;">
                          <b style="color:#6fe0b0;">✓</b> <b>Intelligent incident detection:</b> Automatically group repeated stack traces into consolidated incidents.
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:6px 0;font-size:14px;color:#cfc5dc;line-height:1.5;">
                          <b style="color:#6fe0b0;">✓</b> <b>AI-powered root cause analysis:</b> Deep diagnostic reasoning on NullPointerExceptions, ClassCastExceptions, and async deadlocks.
                        </td>
                      </tr>
                      <tr>
                        <td style="padding:6px 0;font-size:14px;color:#cfc5dc;line-height:1.5;">
                          <b style="color:#6fe0b0;">✓</b> <b>Streamlined debugging workflows:</b> Generates reviewable pull requests verified against your GitHub CI checks.
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <!-- CTA Button -->
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:28px;">
                <tr>
                  <td align="center">
                    <table role="presentation" cellpadding="0" cellspacing="0">
                      <tr>
                        <td style="border-radius:8px;background:linear-gradient(135deg,#ff4a3a,#e11d2a);box-shadow:0 4px 18px rgba(255,74,58,0.35);">
                          <a href="{docs_url}" target="_blank" style="display:inline-block;padding:14px 28px;font-size:15px;font-weight:700;color:#ffffff;text-decoration:none;letter-spacing:0.02em;">
                            Explore Java Integration &rarr;
                          </a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 16px 0;font-size:14.5px;line-height:1.6;color:#cfc5dc;">
                Thank you for being among the first to show interest in our Java integration. We're excited to have you on this journey.
              </p>

              <p style="margin:0;font-size:14px;line-height:1.5;color:#a99dbb;">
                Regards,<br>
                <b style="color:#f2edf7;">Team Agent Daemon</b>
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:22px 36px 26px 36px;border-top:1px solid #23162b;background:#0d0714;text-align:center;font-size:12px;color:#88799c;line-height:1.6;">
              <p style="margin:0 0 8px 0;">
                <b>Agent Daemon</b> · Autonomous AI on-call engineer for resilient engineering teams.
              </p>
              <p style="margin:0 0 10px 0;">
                <a href="{clean_base}/" style="color:#cfc5dc;text-decoration:underline;">Visit Website</a> &nbsp;·&nbsp;
                <a href="{contact_url}" style="color:#cfc5dc;text-decoration:underline;">Contact Support</a> &nbsp;·&nbsp;
                <a href="{unsub_url}" style="color:#ff7a6b;text-decoration:underline;">Unsubscribe</a>
              </p>
              <p style="margin:0;font-size:11px;color:#6b5e7c;">
                You received this announcement because you signed up for the Java launch waitlist on agent-daemon.com.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return html, plain_text
