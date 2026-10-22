"""End-to-end checks for the customer, admin, trial, payment and email flows."""
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import threading
from datetime import timedelta
from pathlib import Path
from wsgiref.simple_server import make_server

import pytest

import notifications
import portal_db
import web_app
from test_web_app import _request, web_env  # noqa: F401  (web_env is a fixture)

ROOT = Path(__file__).resolve().parent.parent


def make_session(email):
    user_id = portal_db.create_user(email, "hash")
    csrf = "csrf-" + user_id[:8]
    session_id = portal_db.create_session(user_id, csrf, (web_app._now() + timedelta(days=1)).isoformat(timespec="seconds"))
    return user_id, csrf, f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}"


def post(path, cookie, csrf, **fields):
    return _request(path, method="POST", cookie=cookie, form={"csrf": csrf, **fields})


def new_project(user_id, key="k" * 40, **extra):
    return portal_db.create_project(user_id, name="Shop", repo_owner="demo", repo_name="shop", branch="main", mode="pr",
                                    token_ciphertext="cipher", ingest_key_hash=hashlib.sha256(key.encode()).hexdigest(), **extra)


def expire(user_id):
    conn = portal_db.get_connection()
    try:
        past = (web_app._now() - timedelta(days=1)).isoformat(timespec="seconds")
        portal_db._execute(conn, "UPDATE subscriptions SET active_until=? WHERE user_id=?", (past, user_id))
        conn.commit()
    finally:
        conn.close()


def location(headers):
    return dict(headers).get("Location", "")


def days_left(until):
    return (portal_db._parse_ts(until) - web_app._now()).total_seconds() / 86400


# --- navigation: every page has its own job ---------------------------------

def test_inactive_customer_sees_dashboard_not_a_redirect(web_env):
    _, _, cookie = make_session("c@example.com")
    status, _, body = _request("/dashboard", cookie=cookie)
    assert status == "200 OK"
    assert "Monitoring is off" in body and "Get access" in body


def test_dashboard_and_plan_pages_are_different(web_env):
    _, _, cookie = make_session("c@example.com")
    _, _, dash = _request("/dashboard", cookie=cookie)
    _, _, bill = _request("/billing", cookie=cookie)
    assert "<h1>Your projects</h1>" in dash and "<h1>Plan &amp; billing</h1>" in bill
    assert ">Projects</a>" in dash and ">Plan &amp; billing</a>" in dash
    assert ">Access</a>" not in dash


def test_admins_go_to_admin_not_customer_pages(web_env):
    _, _, cookie = make_session("admin1@example.com")
    for path in ("/dashboard", "/billing"):
        status, headers, _ = _request(path, cookie=cookie)
        assert status == "303 See Other" and location(headers) == "/admin"


def test_admin_email_cannot_be_registered_publicly(web_env):
    _, headers, body = _request("/signup")
    csrf = re.search(r"name='csrf' value='([^']+)'", body).group(1)
    cookie = f"{web_app.CSRF_COOKIE}={web_app._cookie_value(headers, web_app.CSRF_COOKIE) if hasattr(web_app, '_cookie_value') else ''}"
    from test_web_app import _cookie_value
    cookie = f"{web_app.CSRF_COOKIE}={_cookie_value(headers, web_app.CSRF_COOKIE)}"
    status, _, _ = _request("/signup", method="POST", cookie=cookie,
                            form={"csrf": csrf, "email": "admin1@example.com", "password": "a-long-test-password"})
    assert status == "403 Forbidden"


# --- trial: one request, one decision, one use --------------------------------

def test_trial_flow_end_to_end(web_env):
    user_id, csrf, cookie = make_session("c@example.com")
    _, admin_csrf, admin_cookie = make_session("admin1@example.com")
    status, _, body = post("/billing/trial-request", cookie, csrf)
    assert status == "200 OK" and "Request received" in body
    post("/billing/trial-request", cookie, csrf)  # double click
    assert len([t for t in portal_db.admin_list_trial_requests() if t["user_id"] == user_id]) == 1
    kinds = [n["kind"] for n in portal_db.recent_notifications()]
    assert kinds.count("trial_request") == 2  # one attempt per admin, not per click
    _, _, bill = _request("/billing", cookie=cookie)
    assert "Waiting for approval" in bill and "Request free trial" not in bill

    trial = portal_db.admin_list_trial_requests()[0]
    status, headers, _ = post("/admin", admin_cookie, admin_csrf, action="approve_trial", request_id=trial["id"])
    assert location(headers) == "/admin?msg=trial_approved"
    assert portal_db.user_has_active_access(user_id)
    _, _, dash = _request("/dashboard", cookie=cookie)
    assert "Free trial" in dash and "left" in dash

    expire(user_id)
    _, _, bill = _request("/billing", cookie=cookie)
    assert "Trial used" in bill and "Request free trial" not in bill
    status, _, body = post("/billing/trial-request", cookie, csrf)
    assert status == "409 Conflict" and "already been used" in body


def test_rejected_trial_can_be_requested_again(web_env):
    user_id, csrf, cookie = make_session("c@example.com")
    _, admin_csrf, admin_cookie = make_session("admin1@example.com")
    post("/billing/trial-request", cookie, csrf)
    trial = portal_db.admin_list_trial_requests()[0]
    post("/admin", admin_cookie, admin_csrf, action="reject_trial", request_id=trial["id"])
    assert not portal_db.user_has_active_access(user_id)
    _, _, bill = _request("/billing", cookie=cookie)
    assert "not approved" in bill and "Request free trial" in bill


def test_double_approval_grants_one_day_only(web_env):
    user_id, csrf, cookie = make_session("c@example.com")
    _, admin_csrf, admin_cookie = make_session("admin1@example.com")
    post("/billing/trial-request", cookie, csrf)
    trial = portal_db.admin_list_trial_requests()[0]
    first = post("/admin", admin_cookie, admin_csrf, action="approve_trial", request_id=trial["id"])
    second = post("/admin", admin_cookie, admin_csrf, action="approve_trial", request_id=trial["id"])
    assert location(first[1]).endswith("trial_approved") and location(second[1]).endswith("already_done")
    assert days_left(portal_db.get_subscription_active_until(user_id)) < 1.01


# --- access state rules ---------------------------------------------------------

def test_paid_plan_is_not_downgraded_by_a_later_trial(web_env):
    user_id, *_ = make_session("c@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    portal_db.admin_grant_access(user_id, 1, "trial", "admin1@example.com")
    conn = portal_db.get_connection()
    row = portal_db._execute(conn, "SELECT grant_type FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    assert row["grant_type"] == "paid"
    assert 30.9 < days_left(portal_db.get_subscription_active_until(user_id)) < 31.1


def test_revoke_pauses_projects_and_regrant_resumes_them(web_env):
    user_id, *_ = make_session("c@example.com")
    running, self_paused = new_project(user_id, "a" * 40), new_project(user_id, "b" * 40)
    conn = portal_db.get_connection()
    portal_db._execute(conn, "UPDATE projects SET paused=1 WHERE id=?", (self_paused,))
    conn.commit()
    conn.close()
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    portal_db.admin_revoke_access(user_id)
    assert portal_db.get_project(running, user_id)["paused"] == 2
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    assert portal_db.get_project(running, user_id)["paused"] == 0
    assert portal_db.get_project(self_paused, user_id)["paused"] == 1  # the customer's own pause is respected


# --- manual UPI (used until a payment gateway is configured) --------------------

def test_manual_upi_page_has_inline_qr_and_fixed_amounts(web_env):
    _, _, cookie = make_session("c@example.com")
    status, headers, body = _request("/billing/pay?plan=monthly", cookie=cookie)
    assert status == "200 OK"
    assert "src='data:image/svg+xml" in body and "quickchart" not in body
    assert "am=100.00" in body and "am=1000.00" not in body and "cu=INR" in body and "pa=7975291636@ptsbi" in body
    assert "img-src 'self' data:" in dict(headers)["Content-Security-Policy"]
    _, _, yearly = _request("/billing/pay?plan=yearly", cookie=cookie)
    assert "am=1000.00" in yearly and "am=100.00&" not in yearly


def test_manual_payment_references_are_validated_and_unique(web_env):
    _, csrf1, cookie1 = make_session("one@example.com")
    _, csrf2, cookie2 = make_session("two@example.com")
    assert post("/billing/pay", cookie1, csrf1, plan="monthly", transaction_ref="123")[0] == "400 Bad Request"
    assert post("/billing/pay", cookie1, csrf1, plan="monthly", transaction_ref="not valid!!")[0] == "400 Bad Request"
    assert post("/billing/pay", cookie1, csrf1, plan="monthly", transaction_ref="412345678901")[0] == "200 OK"
    status, _, body = post("/billing/pay", cookie2, csrf2, plan="monthly", transaction_ref="4123 4567 8901")
    assert status == "400 Bad Request" and "already been submitted" in body
    assert post("/billing/pay", cookie1, csrf1, plan="monthly", transaction_ref="412345678901")[0] == "200 OK"
    assert len(portal_db.admin_list_manual_payments()) == 1
    for ref in ("500000000001", "500000000002"):
        post("/billing/pay", cookie1, csrf1, plan="yearly", transaction_ref=ref)
    status, _, body = post("/billing/pay", cookie1, csrf1, plan="yearly", transaction_ref="500000000003")
    assert status == "400 Bad Request" and "waiting for review" in body


def test_admin_confirmation_grants_exactly_the_paid_plan(web_env):
    _, admin_csrf, admin_cookie = make_session("admin1@example.com")
    for email, plan, ref, expected in (("m@example.com", "monthly", "600000000001", 30), ("y@example.com", "yearly", "600000000002", 365)):
        user_id, csrf, cookie = make_session(email)
        post("/billing/pay", cookie, csrf, plan=plan, transaction_ref=ref)
        payment = next(p for p in portal_db.admin_list_manual_payments() if p["user_id"] == user_id)
        status, headers, _ = post("/admin", admin_cookie, admin_csrf, action="confirm_payment", payment_id=payment["id"])
        assert location(headers) == "/admin?msg=payment_confirmed"
        assert expected - 0.1 < days_left(portal_db.get_subscription_active_until(user_id)) < expected + 0.1
        again = post("/admin", admin_cookie, admin_csrf, action="confirm_payment", payment_id=payment["id"])
        assert location(again[1]).endswith("already_done")
        assert expected - 0.1 < days_left(portal_db.get_subscription_active_until(user_id)) < expected + 0.1


def test_rejected_payment_grants_nothing(web_env):
    user_id, csrf, cookie = make_session("c@example.com")
    _, admin_csrf, admin_cookie = make_session("admin1@example.com")
    post("/billing/pay", cookie, csrf, plan="monthly", transaction_ref="700000000001")
    payment = portal_db.admin_list_manual_payments()[0]
    post("/admin", admin_cookie, admin_csrf, action="reject_payment", payment_id=payment["id"])
    assert not portal_db.user_has_active_access(user_id)
    _, _, bill = _request("/billing", cookie=cookie)
    assert "Rejected" in bill


# --- instant payments through the gateway -----------------------------------------

@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_example")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "test-secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "hook-secret")


def test_gateway_mode_shows_instant_pay_buttons_and_hides_manual_page(web_env, gateway):
    _, _, cookie = make_session("c@example.com")
    _, _, bill = _request("/billing", cookie=cookie)
    assert bill.count("action='/billing/order'") == 2 and "Access starts instantly" in bill
    status, headers, _ = _request("/billing/pay?plan=monthly", cookie=cookie)
    assert status == "303 See Other" and location(headers) == "/billing"


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_checkout_amount_is_decided_by_the_server(web_env, gateway, monkeypatch):
    user_id, csrf, cookie = make_session("c@example.com")
    sent = {}

    def fake_urlopen(req, timeout=0):
        sent.update(json.loads(req.data))
        return _FakeResponse({"id": "order_srv123", "amount": sent["amount"]})

    monkeypatch.setattr(web_app, "urlopen", fake_urlopen)
    status, headers, body = post("/billing/order", cookie, csrf, plan="monthly", amount="1")
    assert status == "200 OK" and sent["amount"] == 10000 and "Pay ₹100" in body
    assert "nonce-" in dict(headers)["Content-Security-Policy"]
    conn = portal_db.get_connection()
    row = portal_db._execute(conn, "SELECT amount,plan FROM payment_orders WHERE razorpay_order_id='order_srv123'").fetchone()
    conn.close()
    assert (row["amount"], row["plan"]) == (10000, "monthly")
    assert post("/billing/order", cookie, csrf, plan="bogus")[0] == "400 Bad Request"


def test_webhook_activates_access_even_if_browser_closed(web_env, gateway):
    user_id, *_ = make_session("c@example.com")
    portal_db.create_payment_order(user_id, "order_w1", 100000, "yearly")
    event = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_w1", "order_id": "order_w1", "status": "captured", "amount": 100000, "currency": "INR"}}}}
    raw = json.dumps(event).encode()
    sign = lambda body: hmac.new(b"hook-secret", body, hashlib.sha256).hexdigest()
    assert _request("/webhooks/razorpay", method="POST", raw_body=raw, headers={"HTTP_X_RAZORPAY_SIGNATURE": "bad"})[0] == "401 Unauthorized"
    assert not portal_db.user_has_active_access(user_id)
    assert _request("/webhooks/razorpay", method="POST", raw_body=raw, headers={"HTTP_X_RAZORPAY_SIGNATURE": sign(raw)})[0] == "200 OK"
    until = portal_db.get_subscription_active_until(user_id)
    assert 364.9 < days_left(until) < 365.1
    assert _request("/webhooks/razorpay", method="POST", raw_body=raw, headers={"HTTP_X_RAZORPAY_SIGNATURE": sign(raw)})[0] == "200 OK"
    assert portal_db.get_subscription_active_until(user_id) == until  # replay does not extend access
    assert "payment_customer" in [n["kind"] for n in portal_db.recent_notifications()]


def test_webhook_ignores_wrong_amount(web_env, gateway):
    user_id, *_ = make_session("c@example.com")
    portal_db.create_payment_order(user_id, "order_w2", 100000, "yearly")
    event = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_w2", "order_id": "order_w2", "status": "captured", "amount": 100, "currency": "INR"}}}}
    raw = json.dumps(event).encode()
    signature = hmac.new(b"hook-secret", raw, hashlib.sha256).hexdigest()
    _request("/webhooks/razorpay", method="POST", raw_body=raw, headers={"HTTP_X_RAZORPAY_SIGNATURE": signature})
    assert not portal_db.user_has_active_access(user_id)


# --- email ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


def test_email_via_brevo_is_sent_and_logged(web_env, monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "brevo-secret-key-123456")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    calls = []
    monkeypatch.setattr(notifications.httpx, "post", lambda url, **kw: calls.append((url, kw)) or _Resp(201))
    assert notifications.send_now("a@example.com", "Hi", "Body", "test") == (True, "accepted by brevo")
    url, kw = calls[0]
    assert url == "https://api.brevo.com/v3/smtp/email" and kw["headers"]["api-key"] == "brevo-secret-key-123456"
    assert kw["json"]["to"] == [{"email": "a@example.com"}] and kw["json"]["sender"]["email"] == "sender@example.com"
    assert portal_db.recent_notifications()[0]["ok"] == 1


def test_email_failure_is_logged_without_leaking_the_key(web_env, monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "brevo-secret-key-123456")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.setattr(notifications.httpx, "post", lambda url, **kw: _Resp(401, "bad key brevo-secret-key-123456"))
    ok, detail = notifications.send_now("a@example.com", "Hi", "Body", "test")
    assert ok is False and "401" in detail and "brevo-secret-key-123456" not in detail
    logged = portal_db.recent_notifications()[0]
    assert logged["ok"] == 0 and "brevo-secret-key-123456" not in logged["detail"]


def test_email_not_configured_is_reported_not_hidden(web_env):
    ok, detail = notifications.send_now("a@example.com", "Hi", "Body", "test")
    assert ok is False and "not configured" in detail
    assert portal_db.recent_notifications()[0]["ok"] == 0


def test_every_admin_gets_admin_alerts(web_env, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "resend-secret-key-123456")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    recipients = []
    monkeypatch.setattr(notifications.httpx, "post", lambda url, **kw: recipients.extend(kw["json"]["to"]) or _Resp(200))
    notifications.notify_admins("Subject", "Body")
    assert sorted(recipients) == ["admin1@example.com", "admin2@example.com"]


# --- admin page ---------------------------------------------------------------------------

def test_admin_page_shows_real_numbers_and_email_status(web_env):
    customer_id, *_ = make_session("c@example.com")
    portal_db.admin_grant_access(customer_id, 30, "paid", "admin1@example.com")
    new_project(customer_id)
    _, _, cookie = make_session("admin1@example.com")
    status, _, body = _request("/admin", cookie=cookie)
    assert status == "200 OK"
    for text in ("Operations", "Email status", "Send test email to both admins", "Applications", "Recent incidents and fixes",
                 "1 paid, 0 trial", "Email not configured", "Instant payments off"):
        assert text in body


def test_admin_test_email_button(web_env, monkeypatch):
    _, csrf, cookie = make_session("admin1@example.com")
    assert location(post("/admin", cookie, csrf, action="send_test_email")[1]) == "/admin?msg=test_email_failed"
    monkeypatch.setenv("BREVO_API_KEY", "brevo-secret-key-123456")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.setattr(notifications.httpx, "post", lambda url, **kw: _Resp(201))
    assert location(post("/admin", cookie, csrf, action="send_test_email")[1]) == "/admin?msg=test_email_ok"


def test_admin_grant_and_revoke_show_the_right_button_for_the_state(web_env):
    user_id, *_ = make_session("c@example.com")
    _, csrf, cookie = make_session("admin1@example.com")
    _, _, before = _request("/admin", cookie=cookie)
    assert "value='grant'" in before and "value='revoke'" not in before
    post("/admin", cookie, csrf, action="grant", user_id=user_id, grant="paid:30")
    _, _, after = _request("/admin", cookie=cookie)
    assert "value='revoke'" in after and "value='grant'" not in after and "Paid · " in after
    post("/admin", cookie, csrf, action="revoke", user_id=user_id)
    _, _, final = _request("/admin", cookie=cookie)
    assert "value='grant'" in final and "value='revoke'" not in final and "Expired" not in final


def test_admin_actions_need_admin_and_csrf(web_env):
    _, csrf, customer_cookie = make_session("c@example.com")
    assert post("/admin", customer_cookie, csrf, action="send_test_email")[0] == "404 Not Found"
    _, _, admin_cookie = make_session("admin1@example.com")
    status, _, _ = _request("/admin", method="POST", cookie=admin_cookie, form={"csrf": "wrong", "action": "send_test_email"})
    assert status == "403 Forbidden"
    _, admin_csrf, admin_cookie2 = make_session("admin2@example.com")
    assert location(post("/admin", admin_cookie2, admin_csrf, action="grant", user_id="nobody", grant="paid:30")[1]).endswith("not_found")
    assert location(post("/admin", admin_cookie2, admin_csrf, action="nonsense")[1]).endswith("bad_request")


# --- customer dashboard shows what the agent is really doing ----------------------------------

def test_dashboard_reports_live_project_and_agent_activity(web_env):
    user_id, _, cookie = make_session("c@example.com")
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    project_id = new_project(user_id)
    _, _, before = _request("/dashboard", cookie=cookie)
    assert "Setup needed" in before and "No incidents yet" not in before
    portal_db.set_project_connected(project_id)
    portal_db.ingest_event(project_id, timestamp="2026-10-21T10:00:00+00:00", level="ERROR",
                           message="checkout failed", traceback="", signature="ValueError:cart.py:42")
    _, _, after = _request("/dashboard", cookie=cookie)
    assert "Live" in after and "ValueError:cart.py:42" in after and "Diagnosing" in after
    assert "Paid plan" in after and "days left" in after


def test_ingest_marks_project_connected(web_env):
    user_id, *_ = make_session("c@example.com")
    portal_db.admin_grant_access(user_id, 1, "trial", "admin1@example.com")
    key = "z" * 40
    project_id = new_project(user_id, key)
    event = {"timestamp": "2026-10-21T10:00:00Z", "level": "ERROR", "message": "boom", "traceback": ""}
    assert _request("/ingest", method="POST", json_body=event, ingest_key=key)[0] == "202 Accepted"
    project = portal_db.get_project(project_id, user_id)
    assert project["status"] == "connected" and project["last_heartbeat_at"]


# --- zero-touch monitoring install ------------------------------------------------------------

def _fake_github(monkeypatch, entry_source, private=True, mergeable=True):
    import base64
    import monitoring_installer as mi
    calls = {"blobs": {}, "tree": None, "merged": False}

    def fake_request(url, token, method="GET", payload=None):
        if "/contents/" in url:
            name = url.split("/contents/")[1].split("?")[0]
            if name == "app.py" and entry_source is not None:
                return {"encoding": "base64", "content": base64.b64encode(entry_source.encode()).decode()}
            raise mi.GitHubInstallError("not found")
        if url.endswith("/git/blobs"):
            sha = f"blob{len(calls['blobs'])}"
            calls["blobs"][sha] = payload["content"]
            return {"sha": sha}
        if url.endswith("/git/trees"):
            calls["tree"] = {e["path"]: calls["blobs"][e["sha"]] for e in payload["tree"]}
            return {"sha": "tree1"}
        if url.endswith("/git/commits") and method == "POST":
            return {"sha": "commit1"}
        if "/git/commits/" in url:
            return {"tree": {"sha": "basetree"}}
        if "/git/ref/heads/" in url:
            return {"object": {"sha": "base1"}}
        if url.endswith("/git/refs"):
            return {}
        if url.endswith("/pulls") and method == "POST":
            return {"html_url": "https://github.com/demo/shop/pull/7", "number": 7}
        if url.endswith("/merge"):
            if not mergeable:
                raise mi.GitHubInstallError("not mergeable")
            calls["merged"] = True
            return {}
        return {"private": private}

    monkeypatch.setattr(mi, "_request", fake_request)
    monkeypatch.setattr(mi.time, "sleep", lambda *_: None)
    return mi, calls


def test_installer_patches_entry_file_embeds_key_and_merges(monkeypatch):
    mi, calls = _fake_github(monkeypatch, '"""Shop."""\nfrom __future__ import annotations\nimport flask\n')
    result = mi.open_monitoring_pr(owner="demo", repo="shop", base_branch="main", project_id="11111111-2222-3333-4444-555555555555",
                                   token="t", ingest_url="https://portal/ingest", ingest_key="secret-key")
    files = calls["tree"]
    assert set(files) == {"incident_agent_monitor.py", "incident_agent_config.json", "app.py", "INCIDENT_AGENT_SETUP.md"}
    assert json.loads(files["incident_agent_config.json"]) == {"ingest_url": "https://portal/ingest", "ingest_key": "secret-key"}
    assert files["app.py"].split("\n")[:4] == ['"""Shop."""', "from __future__ import annotations", mi.IMPORT_LINE, "import flask"]
    assert result["merged"] and result["patched_file"] == "app.py" and result["embedded_key"] and calls["merged"]


def test_installer_never_embeds_a_key_when_not_given_and_survives_no_entry_file(monkeypatch):
    mi, calls = _fake_github(monkeypatch, None, mergeable=False)
    result = mi.open_monitoring_pr(owner="demo", repo="shop", base_branch="main", project_id="11111111-2222-3333-4444-555555555555", token="t")
    assert "incident_agent_config.json" not in calls["tree"] and result["patched_file"] is None
    assert result["merged"] is False and "import incident_agent_monitor" in calls["tree"]["INCIDENT_AGENT_SETUP.md"]


@pytest.mark.parametrize("source,expected_index", [
    ("#!/usr/bin/env python\nimport os\n", 1),
    ("import os\n", 0),
    ('"""doc"""\nimport os\n', 1),
])
def test_import_insertion_points(source, expected_index):
    import monitoring_installer as mi
    lines = mi._insert_import(source).split("\n")
    assert lines[expected_index] == mi.IMPORT_LINE


def test_import_insertion_is_idempotent_and_skips_broken_files():
    import monitoring_installer as mi
    once = mi._insert_import("import os\n")
    assert mi._insert_import(once) == once
    assert mi._insert_import("def broken(:\n") is None


def test_monitor_client_reports_errors_and_heartbeats_to_the_portal(web_env):
    user_id, *_ = make_session("c@example.com")
    portal_db.admin_grant_access(user_id, 1, "trial", "admin1@example.com")
    key = "live-key-" + "x" * 30
    project_id = new_project(user_id, key)
    server = make_server("127.0.0.1", 0, web_app.application, server_class=web_app.ThreadingWSGIServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        code = ("import time, logging\nimport agent_monitor_client\n"
                "time.sleep(1.5)\n"
                "try:\n    {}['missing']\nexcept KeyError:\n    logging.getLogger('shop').exception('checkout crashed')\n"
                "time.sleep(1)\nraise RuntimeError('unhandled crash')\n")
        # Keep the normal environment: on Windows, Python cannot open sockets without SYSTEMROOT and friends.
        env = dict(os.environ)
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            env.pop(name, None)
        env.update({"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
                    "INCIDENT_AGENT_INGEST_URL": f"http://127.0.0.1:{server.server_port}/ingest",
                    "INCIDENT_AGENT_INGEST_KEY": key})
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, timeout=60,
                                capture_output=True, text=True)
    finally:
        server.shutdown()
    project = portal_db.get_project(project_id, user_id)
    signatures = {i["signature"] for i in portal_db.list_incidents(project_id)}
    details = f"client process stderr: {result.stderr[-800:]!r}"
    assert project["status"] == "connected" and project["last_heartbeat_at"], details
    assert any(s.startswith("KeyError") for s in signatures), (signatures, details)
    assert any(s.startswith("RuntimeError") for s in signatures), (signatures, details)


# --- the simple manual payment flow: pay the QR, wait 1-2 hours, admin confirms ------------------

def test_customer_is_told_to_wait_and_admins_are_emailed(web_env):
    user_id, csrf, cookie = make_session("c@example.com")
    _, _, page = _request("/billing/pay?plan=monthly", cookie=cookie)
    assert "1 to 2 hours" in page and "Paytm" in page and "automatically" not in page
    assert page.count("src='data:image/svg+xml") == 2  # QR with the amount, plus a plain QR as a fallback
    status, _, body = post("/billing/pay", cookie, csrf, plan="monthly", transaction_ref="412345678901")
    assert status == "200 OK" and "1 to 2 hours" in body
    kinds = [n["kind"] for n in portal_db.recent_notifications(20)]
    assert kinds.count("payment_submitted") == 2  # both admins
    assert kinds.count("payment_received") == 1   # the customer
    assert not portal_db.user_has_active_access(user_id)  # nothing unlocks until an admin confirms


def test_admin_sees_customers_needing_action_first_with_their_plan_state(web_env):
    active, *_ = make_session("a-active@example.com")
    idle, *_ = make_session("b-idle@example.com")
    payer, csrf, cookie = make_session("z-payer@example.com")
    portal_db.admin_grant_access(active, 30, "paid", "admin1@example.com")
    post("/billing/pay", cookie, csrf, plan="yearly", transaction_ref="412345678902")
    _, _, admin_cookie = (lambda r: (r[0], r[1], r[2]))(make_session("admin1@example.com"))
    _, _, body = _request("/admin", cookie=admin_cookie)
    assert body.index("z-payer@example.com") < body.index("a-active@example.com") < body.index("b-idle@example.com")
    assert "Payment to confirm" in body and "Paid · " in body and "No access" in body
    assert "I received ₹1000 · grant 365 days" in body
