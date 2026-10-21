"""Configurable SMTP email notifications for the customer portal."""
from __future__ import annotations
import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger(__name__)

def admin_emails() -> list[str]:
    raw = os.getenv("ADMIN_EMAILS", "") or os.getenv("ADMIN_EMAIL", "")
    return sorted({item.strip().lower() for item in raw.split(",") if item.strip()})

def send_email(to: str, subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("EMAIL_FROM", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    if not host or not sender or not username or not password:
        log.warning("Email not sent: SMTP_HOST, EMAIL_FROM, SMTP_USERNAME and SMTP_PASSWORD must be configured.")
        return False
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
        message = EmailMessage()
        message["From"] = sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(message)
        return True
    except (OSError, ValueError, smtplib.SMTPException):
        log.exception("Email delivery failed for recipient %s", to)
        return False

def notify_admins(subject: str, body: str) -> dict[str, bool]:
    return {address: send_email(address, subject, body) for address in admin_emails()}

def notify_customer(address: str, subject: str, body: str) -> bool:
    return send_email(address, subject, body)
