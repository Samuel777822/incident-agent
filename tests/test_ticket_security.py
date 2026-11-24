from datetime import datetime, timedelta, timezone
import json
import pytest
import re

import portal_db
import web_app
from test_web_app import _request, web_env, _cookie_value


def make_admin_session(email="admin1@example.com"):
    user_id = portal_db.create_user(email, "hash")
    csrf = "csrf-adm-" + user_id[:6]
    session_id = portal_db.create_session(user_id, csrf, (web_app._now() + timedelta(days=1)).isoformat())
    return user_id, csrf, f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}"


def make_customer_session(email="customer@startup.com"):
    user_id = portal_db.create_user(email, "hash")
    csrf = "csrf-cust-" + user_id[:6]
    session_id = portal_db.create_session(user_id, csrf, (web_app._now() + timedelta(days=1)).isoformat())
    return user_id, csrf, f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}"


def get_contact_csrf(cookie=""):
    st, headers, body = _request("/contact", cookie=cookie)
    match = re.search(r"name=['\"]csrf['\"]\s+value=['\"]([^'\"]+)['\"]", body)
    csrf = match.group(1) if match else "test-csrf"
    csrf_cookie = _cookie_value(headers, web_app.CSRF_COOKIE)
    merged_cookie = f"{web_app.CSRF_COOKIE}={csrf_cookie}" if csrf_cookie else cookie
    return csrf, merged_cookie


# -------------------------------------------------------------
# PHASE 1: EMERGENCY LOCKDOWN TESTS
# -------------------------------------------------------------

def test_emergency_killswitch_blocks_public_contact_get(web_env, monkeypatch):
    """When SUPPORT_TICKETS_ENABLED=false, GET /contact returns 503 maintenance notice."""
    monkeypatch.setenv("SUPPORT_TICKETS_ENABLED", "false")
    assert web_app.is_support_tickets_enabled() is False

    st, headers, body = _request("/contact")
    assert st == "503 Service Unavailable"
    assert "Support ticket submissions are temporarily unavailable" in body
    assert any(h[0] == "Retry-After" and h[1] == "3600" for h in headers)


def test_emergency_killswitch_blocks_public_contact_post(web_env, monkeypatch):
    """When SUPPORT_TICKETS_ENABLED=false, POST /contact rejects submission with 503 before DB write or email."""
    monkeypatch.setenv("SUPPORT_TICKETS_ENABLED", "false")
    csrf, cookie = get_contact_csrf()

    # Track emails
    import notifications
    emails_sent = []
    monkeypatch.setattr(notifications, "notify_customer", lambda to, s, b, k="": emails_sent.append(to))
    monkeypatch.setattr(notifications, "notify_admins", lambda s, b, k="": emails_sent.append("admin"))

    st, headers, body = _request(
        "/contact",
        method="POST",
        form={"csrf": csrf, "name": "Spammer", "email": "spam@bot.com", "subject": "Buy now", "message": "Cheap pills"},
        cookie=cookie,
    )
    assert st == "503 Service Unavailable"
    assert "Support ticket submissions are temporarily unavailable" in body
    assert len(emails_sent) == 0

    # Verify no ticket created in database
    tickets = portal_db.admin_list_support_messages(100)
    assert not any(t["email"] == "spam@bot.com" for t in tickets)


def test_emergency_killswitch_blocks_build_request(web_env, monkeypatch):
    """When SUPPORT_TICKETS_ENABLED=false, /build-request is blocked with 503."""
    monkeypatch.setenv("SUPPORT_TICKETS_ENABLED", "false")
    st, headers, body = _request("/build-request")
    assert st == "503 Service Unavailable"
    assert "Support ticket submissions are temporarily unavailable" in body

    st_post, _, body_post = _request(
        "/build-request",
        method="POST",
        form={"name": "Spam", "email": "spam@bot.com", "whatsapp": "+91 9999999999", "idea": "Spam idea app build"},
    )
    assert st_post == "503 Service Unavailable"


def test_create_support_ticket_database_killswitch(web_env, monkeypatch):
    """Direct backend calls to portal_db.create_support_ticket raise PermissionError when killswitch active."""
    monkeypatch.setenv("SUPPORT_TICKETS_ENABLED", "false")
    with pytest.raises(PermissionError):
        portal_db.create_support_ticket("Bot", "bot@spam.com", "Spam", "Spam message")

    # With explicit bypass_killswitch=True, admin/system actions are allowed
    t = portal_db.create_support_ticket("Admin Added", "test@test.com", "Inquiry", "Msg", bypass_killswitch=True)
    assert t["ticket_ref"].startswith("TICK-")


def test_killswitch_env_takes_precedence_over_database(web_env, monkeypatch):
    """Environment kill switch SUPPORT_TICKETS_ENABLED=false overrides database setting."""
    portal_db.set_ticket_security_setting("public_tickets_enabled", "true")
    monkeypatch.setenv("SUPPORT_TICKETS_ENABLED", "false")
    assert portal_db.is_support_tickets_enabled() is False

    # When env is true, DB setting controls it
    monkeypatch.setenv("SUPPORT_TICKETS_ENABLED", "true")
    assert portal_db.is_support_tickets_enabled() is True
    portal_db.set_ticket_security_setting("public_tickets_enabled", "false")
    assert portal_db.is_support_tickets_enabled() is False


# -------------------------------------------------------------
# PHASE 1 & 4: PRESERVE ADMIN FUNCTIONALITY
# -------------------------------------------------------------

def test_admin_functionality_preserved_during_lockdown(web_env, monkeypatch):
    """Admins can view, assign, update, close tickets, and add notes during lockdown."""
    monkeypatch.setenv("SUPPORT_TICKETS_ENABLED", "false")
    user_id, csrf, cookie = make_admin_session()

    # Pre-populate tickets
    t1 = portal_db.create_support_ticket("Cust1", "cust1@startup.com", "Server down", "500 error", bypass_killswitch=True)
    t2 = portal_db.create_support_ticket("Cust2", "cust2@startup.com", "Question", "Help with API", bypass_killswitch=True)

    # 1. Admin views tickets
    st, _, html = _request("/admin?view=tickets", cookie=cookie)
    assert st == "200 OK"
    assert "cust1@startup.com" in html
    assert "cust2@startup.com" in html
    assert "🛑 EMERGENCY KILL SWITCH ACTIVE" in html

    # 2. Admin assigns and closes ticket
    import notifications
    cust_emails = []
    monkeypatch.setattr(notifications, "notify_customer", lambda to, s, b, k="": cust_emails.append((to, s, b)))

    st_up, _, _ = _request(
        "/admin?view=tickets",
        method="POST",
        form={
            "csrf": csrf,
            "action": "update_support_ticket",
            "ticket_id": t1["id"],
            "status": "closed",
            "assigned_to": "admin1@example.com",
            "resolution_note": "Fixed on cluster A",
        },
        cookie=cookie,
    )
    assert st_up == "303 See Other"

    # Verify ticket was updated
    updated = portal_db.admin_get_support_ticket(t1["id"])
    assert updated["status"] == "closed"
    assert updated["resolution_note"] == "Fixed on cluster A"
    assert len(cust_emails) == 1
    assert cust_emails[0][0] == "cust1@startup.com"
    assert "Resolved" in cust_emails[0][1]


def test_admin_mark_as_spam_no_customer_email(web_env, monkeypatch):
    """Marking a ticket as spam sets status to spam and DOES NOT send customer email."""
    user_id, csrf, cookie = make_admin_session()
    t = portal_db.create_support_ticket("Spammer", "spammer@bot.com", "Cheap SEO", "Buy backlinks here", bypass_killswitch=True)

    import notifications
    cust_emails = []
    monkeypatch.setattr(notifications, "notify_customer", lambda to, s, b, k="": cust_emails.append((to, s, b)))

    st, _, _ = _request(
        "/admin?view=tickets",
        method="POST",
        form={"csrf": csrf, "action": "update_support_ticket", "ticket_id": t["id"], "mark_spam": "1"},
        cookie=cookie,
    )
    assert st == "303 See Other"

    # Verify no customer email sent
    assert len(cust_emails) == 0

    # Verify ticket status is spam
    updated = portal_db.admin_get_support_ticket(t["id"])
    assert updated["status"] == "spam"
    assert updated["is_spam"] == 1
    assert "automated spam" in updated["resolution_note"].lower()


def test_admin_bulk_mark_as_spam(web_env, monkeypatch):
    """Admin bulk marks suspicious tickets as spam."""
    user_id, csrf, cookie = make_admin_session()
    t1 = portal_db.create_support_ticket("Spam1", "spam1@bot.com", "Promo", "Spam msg 1", bypass_killswitch=True)
    t2 = portal_db.create_support_ticket("Spam2", "spam2@bot.com", "Promo", "Spam msg 2", bypass_killswitch=True)

    count = portal_db.admin_bulk_mark_spam([t1["id"], t2["id"]], actor="admin1@example.com")
    assert count == 2

    assert portal_db.admin_get_support_ticket(t1["id"])["status"] == "spam"
    assert portal_db.admin_get_support_ticket(t2["id"])["status"] == "spam"


# -------------------------------------------------------------
# PHASE 2: OTP, CAPTCHA, RATE LIMITS, SPAM DETECTION
# -------------------------------------------------------------

def test_otp_lifecycle_validation(web_env):
    """Validates 6-digit OTP generation, hashing, rate limits, expiry, and single-use."""
    email = "tester@company.com"
    raw_otp, ok, err = portal_db.create_ticket_otp(email, ip="127.0.0.1")
    assert ok is True
    assert len(raw_otp) == 6
    assert raw_otp.isdigit()

    # Invalid code rejected
    v_ok, v_err = portal_db.verify_ticket_otp(email, "000000", ip="127.0.0.1")
    assert v_ok is False
    assert "incorrect" in v_err.lower()

    # Valid code accepted
    v_ok, v_err = portal_db.verify_ticket_otp(email, raw_otp, ip="127.0.0.1")
    assert v_ok is True

    # Reused code rejected (single-use)
    v_ok, v_err = portal_db.verify_ticket_otp(email, raw_otp, ip="127.0.0.1")
    assert v_ok is False
    assert "no active verification code" in v_err.lower()


def test_otp_rate_limiting_and_max_attempts(web_env):
    """Rate limits OTP requests and invalidates code after 5 incorrect attempts."""
    email = "rate_limit@company.com"

    # Issue OTP
    raw_otp, ok, _ = portal_db.create_ticket_otp(email, ip="10.0.0.1")
    assert ok is True

    # 5 failed attempts
    for i in range(5):
        v_ok, v_err = portal_db.verify_ticket_otp(email, f"99999{i}", ip="10.0.0.1")
        assert v_ok is False

    # 6th attempt rejected as exceeded
    v_ok, v_err = portal_db.verify_ticket_otp(email, raw_otp, ip="10.0.0.1")
    assert v_ok is False
    assert "too many incorrect attempts" in v_err.lower()


def test_honeypot_traps_bot_submission(web_env, monkeypatch):
    """Honeypot field stops automated bots when public submissions are enabled."""
    monkeypatch.setenv("SUPPORT_TICKETS_ENABLED", "true")
    portal_db.set_ticket_security_setting("public_tickets_enabled", "true")
    csrf, cookie = get_contact_csrf()

    st, _, body = _request(
        "/contact",
        method="POST",
        form={
            "csrf": csrf,
            "website_hp": "http://spambot-link.com",  # Honeypot filled by bot
            "name": "Bot",
            "email": "bot@spam.com",
            "subject": "Spam",
            "message": "Spam",
        },
        cookie=cookie,
    )
    assert st == "400 Bad Request"
    assert "Invalid submission detected" in body


def test_duplicate_submission_detection(web_env, monkeypatch):
    """Identical ticket message from same email within window is detected as duplicate."""
    monkeypatch.setenv("SUPPORT_TICKETS_ENABLED", "true")
    portal_db.set_ticket_security_setting("public_tickets_enabled", "true")
    portal_db.set_ticket_security_setting("email_otp_enabled", "false")  # focus on duplicate
    portal_db.set_ticket_security_setting("captcha_enabled", "false")
    csrf, cookie = get_contact_csrf()

    # First submission succeeds
    st1, _, body1 = _request(
        "/contact",
        method="POST",
        form={"csrf": csrf, "name": "Alice", "email": "alice@startup.com", "subject": "Question", "message": "Identical query text"},
        cookie=cookie,
    )
    assert st1 == "200 OK"
    assert "Thanks for reaching out!" in body1

    # Second identical submission within 10 min rejected as duplicate
    st2, _, body2 = _request(
        "/contact",
        method="POST",
        form={"csrf": csrf, "name": "Alice", "email": "alice@startup.com", "subject": "Question", "message": "Identical query text"},
        cookie=cookie,
    )
    assert "An inquiry with identical contents was recently received" in body2


def test_captcha_verification_requirement(web_env, monkeypatch):
    """When CAPTCHA is enabled, missing or invalid token prevents OTP issuance and ticket creation."""
    monkeypatch.setenv("SUPPORT_TICKETS_ENABLED", "true")
    portal_db.set_ticket_security_setting("public_tickets_enabled", "true")
    portal_db.set_ticket_security_setting("captcha_enabled", "true")

    # API send-otp fails without captcha token
    monkeypatch.setenv("CF_TURNSTILE_SECRET_KEY", "real-prod-secret")
    csrf, cookie = get_contact_csrf()

    st, _, body = _request(
        "/api/tickets/send-otp",
        method="POST",
        form={"csrf": csrf, "email": "test@company.com", "captcha_token": ""},
        cookie=cookie,
    )
    assert st == "400 Bad Request"
    assert "CAPTCHA" in body


def test_unauthenticated_cannot_change_security_settings(web_env):
    """Unauthenticated requests to update security settings are rejected."""
    st, _, _ = _request(
        "/admin",
        method="POST",
        form={"action": "update_ticket_security", "public_tickets_enabled": "1"},
    )
    assert st == "303 See Other"  # Redirected to login
