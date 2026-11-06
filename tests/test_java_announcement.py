import json
import re
from datetime import timedelta
import pytest

import notifications
import portal_db
import web_app
from test_web_app import _request, web_env


def make_admin_session(email="admin1@example.com"):
    user_id = web_app.portal_db.create_user(email, "hash")
    csrf = "csrf-adm-" + user_id[:6]
    session_id = web_app.portal_db.create_session(user_id, csrf, (web_app._now() + timedelta(days=1)).isoformat())
    return user_id, csrf, f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}"


def test_homepage_java_announcement_banner(web_env):
    st, _, body = _request("/")
    assert st == "200 OK"
    # Check main requirements
    assert "JAVA IS COMING TO AGENT DAEMON!" in body
    assert "Your Java Applications Are Next." in body
    assert "We're expanding Agent Daemon beyond Python." in body
    assert "COMING SOON" in body
    assert "Be the First to Know." in body
    assert "Notify Me at Launch" in body
    assert "We'll only use your email to notify you about the Java integration launch." in body
    assert "PaymentController.java" in body
    assert 'id="java-banner-close"' in body
    assert 'id="footer-java-link"' in body


def test_java_waitlist_registration_flow(web_env):
    # 1. Invalid email rejected
    st, _, body = _request("/api/java-waitlist", method="POST", json_body={"email": "invalid-email"})
    assert st == "400 Bad Request"
    data = json.loads(body)
    assert "error" in data

    # 2. Valid email registered successfully
    st, _, body = _request("/api/java-waitlist", method="POST", json_body={"email": "dev@springcorp.com"})
    assert st == "200 OK"
    data = json.loads(body)
    assert data["status"] == "ok"
    assert "You're on the list!" in data["message"]

    # Verify DB record
    stats = portal_db.get_java_waitlist_stats()
    assert stats["total_interested"] == 1
    assert stats["subscribed"] == 1
    assert stats["pending"] == 1
    assert stats["sent"] == 0

    subscribers = portal_db.list_java_waitlist(10)
    assert len(subscribers) == 1
    sub = subscribers[0]
    assert sub["email"] == "dev@springcorp.com"
    assert sub["status"] == "subscribed"
    assert sub["notification_sent"] == 0
    assert len(sub["unsubscribe_token"]) >= 20

    # 3. Duplicate registration handled gracefully
    st, _, body_dup = _request("/api/java-waitlist", method="POST", json_body={"email": "DEV@springcorp.com"})
    assert st == "200 OK"
    data_dup = json.loads(body_dup)
    assert data_dup["status"] == "duplicate"
    assert "already on the list" in data_dup["message"]

    # Total count remains 1
    stats2 = portal_db.get_java_waitlist_stats()
    assert stats2["total_interested"] == 1


def test_banner_analytics_tracking(web_env):
    st, _, body = _request("/api/banner-analytics", method="POST", json_body={"event": "impression"})
    assert st == "200 OK"
    st, _, body = _request("/api/banner-analytics", method="POST", json_body={"event": "dismiss"})
    assert st == "200 OK"

    analytics = portal_db.get_banner_analytics()
    assert analytics.get("impression", 0) >= 1
    assert analytics.get("dismiss", 0) >= 1


def test_unsubscribe_workflow(web_env):
    # Register user
    portal_db.register_java_waitlist("optout@enterprise.org")
    sub = portal_db.list_java_waitlist(1)[0]
    token = sub["unsubscribe_token"]

    # GET /unsubscribe with token renders confirmation page
    st, _, body = _request(f"/unsubscribe?token={token}")
    assert st == "200 OK"
    assert "Unsubscribe from Java Launch Updates?" in body

    # POST /unsubscribe executes unsubscribe
    st, _, body_post = _request("/unsubscribe", method="POST", form={"token": token})
    assert st == "200 OK"
    assert "You've Been Unsubscribed" in body_post
    assert "optout@enterprise.org" in body_post

    # Verify status in database
    updated = portal_db.list_java_waitlist(1)[0]
    assert updated["status"] == "unsubscribed"

    # User is excluded from pending launch recipients
    pending = portal_db.get_pending_java_launch_recipients()
    assert not any(p["email"] == "optout@enterprise.org" for p in pending)

    # Re-registering reactivates the subscription
    ok, reason, rec = portal_db.register_java_waitlist("optout@enterprise.org")
    assert ok is True
    assert reason == "reactivated"
    assert rec["status"] == "subscribed"


def test_admin_java_launch_controls(web_env, monkeypatch):
    # Setup test subscribers
    portal_db.register_java_waitlist("user1@javadev.io")
    portal_db.register_java_waitlist("user2@javadev.io")
    portal_db.register_java_waitlist("unsub@javadev.io")
    unsub_sub = [s for s in portal_db.list_java_waitlist(10) if s["email"] == "unsub@javadev.io"][0]
    portal_db.unsubscribe_java_waitlist(unsub_sub["unsubscribe_token"])

    emails_sent = []
    monkeypatch.setattr(notifications, "send_now", lambda to, subj, body, kind="", html=None:
                        emails_sent.append((to, subj, body, kind, html)) or (True, "accepted"))

    _, admin_csrf, admin_cookie = make_admin_session("admin1@example.com")

    # 1. Admin views dashboard
    st, _, admin_body = _request("/admin", cookie=admin_cookie)
    assert st == "200 OK"
    assert "Java Integration Launch &amp; Waitlist" in admin_body
    assert "user1@javadev.io" in admin_body

    # 2. Admin sends test preview email
    st, hdrs, _ = _request("/admin", method="POST", cookie=admin_cookie,
                           form={"csrf": admin_csrf, "action": "send_java_test_email"})
    assert st == "303 See Other"
    assert "java_test_email_ok" in dict(hdrs).get("Location", "")
    assert len(emails_sent) >= 1
    test_msg = emails_sent[0]
    assert "[TEST]" in test_msg[1]
    assert "Java Support Is Here" in test_msg[4]  # HTML body

    emails_sent.clear()

    # 3. Admin triggers official Java launch (without confirmation checkbox fails)
    st_fail, _, _ = _request("/admin", method="POST", cookie=admin_cookie,
                             form={"csrf": admin_csrf, "action": "trigger_java_launch"})
    assert st_fail == "303 See Other"
    assert len(emails_sent) == 0

    # Admin confirms launch
    st_launch, hdrs_launch, _ = _request("/admin", method="POST", cookie=admin_cookie,
                                         form={"csrf": admin_csrf, "action": "trigger_java_launch", "confirm_launch": "yes"})
    assert st_launch == "303 See Other"
    assert "java_launch_triggered" in dict(hdrs_launch).get("Location", "")

    # Emails were sent ONLY to eligible active subscribers (user1 and user2, NOT unsub)
    sent_recipients = [e[0] for e in emails_sent]
    assert "user1@javadev.io" in sent_recipients
    assert "user2@javadev.io" in sent_recipients
    assert "unsub@javadev.io" not in sent_recipients
    assert len(emails_sent) == 2

    # Verify launch email content
    sample_email = emails_sent[0]
    assert sample_email[1] == "Java Has Arrived at Agent Daemon!"
    assert "Java Support Is Here." in sample_email[4]
    assert "Explore Java Integration" in sample_email[4]
    assert "/unsubscribe?token=" in sample_email[4]

    # Verify database update
    stats = portal_db.get_java_waitlist_stats()
    assert stats["sent"] == 2
    assert stats["pending"] == 0

    # 4. Idempotency: Triggering again does not double-send
    emails_sent.clear()
    _request("/admin", method="POST", cookie=admin_cookie,
             form={"csrf": admin_csrf, "action": "trigger_java_launch", "confirm_launch": "yes"})
    assert len(emails_sent) == 0


def test_admin_retry_failed_notifications(web_env, monkeypatch):
    portal_db.register_java_waitlist("failuser@tech.org")
    rec = [s for s in portal_db.list_java_waitlist(10) if s["email"] == "failuser@tech.org"][0]

    # Simulate failure
    portal_db.mark_java_notification_failed(rec["id"], "Connection timeout to mail server")

    stats = portal_db.get_java_waitlist_stats()
    assert stats["failed"] == 1

    _, admin_csrf, admin_cookie = make_admin_session("admin1@example.com")

    # Admin views retry button on admin page
    st, _, admin_html = _request("/admin", cookie=admin_cookie)
    assert "Retry 1 Failed Notifications" in admin_html

    # Admin triggers retry with successful mail provider
    retry_sent = []
    monkeypatch.setattr(notifications, "send_now", lambda to, subj, body, kind="", html=None:
                        retry_sent.append((to, subj)) or (True, "accepted"))

    st_retry, hdrs, _ = _request("/admin", method="POST", cookie=admin_cookie,
                                 form={"csrf": admin_csrf, "action": "retry_failed_java_notifications"})
    assert st_retry == "303 See Other"
    assert "java_retry_complete" in dict(hdrs).get("Location", "")
    assert len(retry_sent) == 1
    assert retry_sent[0][0] == "failuser@tech.org"

    # Status now marked sent
    stats_after = portal_db.get_java_waitlist_stats()
    assert stats_after["failed"] == 0
    assert stats_after["sent"] == 1
