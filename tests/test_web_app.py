import io
import hashlib
import hmac
import json
import re
from http.cookies import SimpleCookie
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults

import pytest

import web_app


@pytest.fixture
def web_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTAL_DB_PATH", str(tmp_path / "portal.sqlite3"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SESSION_SECRET", "test-only-session-secret-at-least-32-chars")
    web_app.portal_db.init_db()


def _request(path, *, method="GET", form=None, cookie="", json_body=None, ingest_key="", headers=None, raw_body=None):
    values = {}
    setup_testing_defaults(values)
    path, _, query_string = path.partition("?")
    values.update({"QUERY_STRING": query_string, "PATH_INFO": path, "REQUEST_METHOD": method, "REMOTE_ADDR": "127.0.0.1",
                   "HTTP_COOKIE": cookie, "wsgi.input": io.BytesIO()})
    if form is not None:
        encoded = urlencode(form).encode()
        values["CONTENT_LENGTH"] = str(len(encoded))
        values["wsgi.input"] = io.BytesIO(encoded)
        values["CONTENT_TYPE"] = "application/x-www-form-urlencoded"
    if json_body is not None:
        encoded = json.dumps(json_body).encode()
        values["CONTENT_LENGTH"] = str(len(encoded))
        values["CONTENT_TYPE"] = "application/json"
        values["wsgi.input"] = io.BytesIO(encoded)
    if ingest_key:
        values["HTTP_X_INGEST_KEY"] = ingest_key
    if raw_body is not None:
        values["CONTENT_LENGTH"] = str(len(raw_body))
        values["CONTENT_TYPE"] = "application/json"
        values["wsgi.input"] = io.BytesIO(raw_body)
    values.update(headers or {})
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    body = b"".join(web_app.application(values, start_response)).decode()
    return captured["status"], captured["headers"], body


def _cookie_value(headers, name):
    values = [value for key, value in headers if key.lower() == "set-cookie"]
    for value in values:
        jar = SimpleCookie()
        jar.load(value)
        if name in jar:
            return jar[name].value
    return ""


def test_login_page_offers_google_only(web_env):
    for path in ("/login", "/"):
        status, headers, body = _request(path)
        assert status == "200 OK"
        assert "Continue with Google" in body
        assert "type='password'" not in body and 'type="password"' not in body
        assert "Content-Security-Policy" in dict(headers)


def test_home_page_explains_the_product_and_the_github_token(web_env):
    status, headers, body = _request("/")
    assert status == "200 OK"
    for text in ("How it works", "Make your repository private", "Tokens (classic)", "<code>repo</code>", "<code>workflow</code>"):
        assert text in body
    assert 'id="hstage-0"' in body
    assert 'id="hstage-1"' in body
    assert 'id="hstage-2"' in body
    assert 'id="hstage-3"' in body
    assert "/assets/home.js" in body
    assert "setHeroStage" in body
    # Verify CSP permits inline and self scripts
    csp = dict(headers)["Content-Security-Policy"]
    assert "script-src 'self' 'unsafe-inline'" in csp
    # Verify /assets/home.js is served
    h_status, h_headers, h_body = _request("/assets/home.js")
    assert h_status == "200 OK"
    assert "setHeroStage" in h_body
    assert "switchShowcase" in h_body


def test_email_signup_and_login_are_gone(web_env):
    for path in ("/signup", "/login"):
        status, headers, _ = _request(path, method="POST",
                                      form={"csrf": "x", "email": "person@example.com", "password": "a-long-test-password"})
        assert status == "303 See Other"
        assert dict(headers)["Location"] == "/login"
        assert not _cookie_value(headers, web_app.SESSION_COOKIE)
    assert web_app.portal_db.get_user_by_email("person@example.com") is None
    status, headers, _ = _request("/signup")
    assert status == "303 See Other" and dict(headers)["Location"] == "/login"


def test_logout_requires_csrf_token(web_env):
    from datetime import timedelta
    user_id = web_app.portal_db.create_user("person@example.com", "")
    session_id = web_app.portal_db.create_session(user_id, "csrf-token-1", (web_app._now() + timedelta(days=1)).isoformat(timespec="seconds"))
    session_cookie = web_app._signed_cookie(session_id)

    status, _, _ = _request("/logout", method="POST", cookie=f"{web_app.SESSION_COOKIE}={session_cookie}", form={})
    assert status == "403 Forbidden"


def test_ingest_authenticates_and_deduplicates_per_project(web_env):
    user_id = web_app.portal_db.create_user("ingest@example.com", "hash")
    web_app.portal_db.admin_grant_access(user_id, 1, "trial", "test-admin")
    raw_key = "project-ingest-key-that-is-long-enough-123"
    project_id = web_app.portal_db.create_project(user_id, name="API", repo_owner="demo",
        repo_name="api", branch="main", mode="pr", token_ciphertext="cipher",
        ingest_key_hash=hashlib.sha256(raw_key.encode()).hexdigest())
    event = {"timestamp": "2026-10-21T10:00:00Z", "level": "ERROR",
             "message": "checkout failed", "traceback": "Traceback: ValueError"}

    status, _, body = _request("/ingest", method="POST", json_body=event, ingest_key="wrong-key-that-is-long-enough-123")
    assert status == "401 Unauthorized"
    first_status, _, first_body = _request("/ingest", method="POST", json_body=event, ingest_key=raw_key)
    second_status, _, second_body = _request("/ingest", method="POST", json_body=event, ingest_key=raw_key)

    assert first_status == "202 Accepted"
    assert json.loads(first_body)["accepted"] is True
    assert second_status == "200 OK"
    assert json.loads(second_body)["duplicate"] is True
    assert web_app.portal_db.list_incidents(project_id)[0]["occurrences"] == 1


def test_payment_only_activates_after_captured_status(web_env, monkeypatch):
    user_id = web_app.portal_db.create_user("payer@example.com", "hash")
    project_id = web_app.portal_db.create_project(user_id, name="API", repo_owner="demo",
        repo_name="api", branch="main", mode="pr", token_ciphertext="cipher",
        ingest_key_hash="payment-project-key")
    web_app.portal_db.create_payment_order(user_id, "order_abc123", 49900)
    csrf = "csrf-session-value"
    session_id = web_app.portal_db.create_session(user_id, csrf,
        (web_app._now() + web_app.timedelta(days=1)).isoformat(timespec="seconds"))
    monkeypatch.setenv("RAZORPAY_MODE", "test")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_example")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "test-secret")
    monkeypatch.setenv("RAZORPAY_YEARLY_AMOUNT_PAISE", "49900")
    payment_id = "pay_abc123"
    signature = hmac.new(b"test-secret", b"order_abc123|pay_abc123", hashlib.sha256).hexdigest()
    monkeypatch.setattr(web_app, "_fetch_razorpay_payment", lambda *_: {
        "id": payment_id, "order_id": "order_abc123", "status": "authorized",
        "amount": 49900, "currency": "INR",
    })

    status, _, body = _request("/billing/verify", method="POST",
        cookie=f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}",
        json_body={"csrf": csrf, "order_id": "order_abc123", "payment_id": payment_id, "signature": signature})

    assert status == "409 Conflict"
    assert "not captured" in body
    assert web_app.portal_db.get_project(project_id, user_id)["active_until"] is None

    monkeypatch.setattr(web_app, "_fetch_razorpay_payment", lambda *_: {
        "id": payment_id, "order_id": "order_abc123", "status": "captured",
        "amount": 49900, "currency": "INR",
    })
    status, _, body = _request("/billing/verify", method="POST",
        cookie=f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}",
        json_body={"csrf": csrf, "order_id": "order_abc123", "payment_id": payment_id, "signature": signature})
    assert status == "200 OK"
    assert json.loads(body)["status"] == "active"
    assert web_app.portal_db.get_project(project_id, user_id)["active_until"]


def test_google_oauth_not_configured_fails_closed(web_env, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)

    status, _, body = _request("/auth/google")

    assert status == "503 Service Unavailable"
    assert "Google sign-in is not configured yet" in body


def test_production_cookie_domain_covers_apex_and_www_hosts(web_env, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://agentdaemon.xyz/auth/google/callback")
    assert web_app._app_cookie_domain() == "agentdaemon.xyz"

    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://www.agentdaemon.xyz/auth/google/callback")
    assert web_app._app_cookie_domain() == "agentdaemon.xyz"


def test_google_begin_sets_secure_parent_domain_state_cookie(web_env, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://agentdaemon.xyz/auth/google/callback")

    status, headers, _ = _request("/auth/google")
    assert status == "303 See Other"
    state_cookie = next(v for k, v in headers if k.lower() == "set-cookie" and v.startswith("agent_google_state="))
    assert "Domain=agentdaemon.xyz" in state_cookie
    assert "SameSite=Lax" in state_cookie
    assert "HttpOnly" in state_cookie
    assert "Secure" in state_cookie


def test_google_callback_clears_state_cookie_for_same_parent_domain(web_env, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://www.agentdaemon.xyz/auth/google/callback")

    status, headers, _ = _request("/auth/google/callback?error=access_denied")
    assert status == "303 See Other"
    clear_cookie = next(v for k, v in headers if k.lower() == "set-cookie" and v.startswith("agent_google_state="))
    assert "Domain=agentdaemon.xyz" in clear_cookie
    assert "Max-Age=0" in clear_cookie


def test_google_login_url_has_openid_and_state():
    url = web_app._google_login_url("random-state-123", "client-id.apps.googleusercontent.com",
                                    "https://incident-agent-portal.onrender.com/auth/google/callback")
    from urllib.parse import parse_qs, urlsplit
    parsed = urlsplit(url)
    params = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert params["client_id"] == ["client-id.apps.googleusercontent.com"]
    assert params["state"] == ["random-state-123"]
    assert params["response_type"] == ["code"]
    assert "openid" in params["scope"][0].split()
    assert params["redirect_uri"] == ["https://incident-agent-portal.onrender.com/auth/google/callback"]


def test_google_verified_identity_requires_signed_state_cookie(web_env, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://incident-agent-portal.onrender.com/auth/google/callback")
    _, _, body = _request("/login")
    assert "Continue with Google" in body
    state = "state-token"
    signed = web_app._signed_cookie(state)
    request = type("GoogleRequest", (), {"cookies": {"agent_google_state": signed}})()
    with pytest.raises(ValueError, match="expired or could not be validated"):
        web_app._verified_google_identity("authorization-code", "different-state", request)


def test_google_user_is_created_and_reused_by_stable_subject(web_env):
    user1 = web_app.portal_db.get_or_create_google_user("google@example.com", "google-sub-123", True)
    user2 = web_app.portal_db.get_or_create_google_user("google@example.com", "google-sub-123", True)
    assert user1["id"] == user2["id"] == "google-sub-123"
    assert user2["email"] == "google@example.com"
    with pytest.raises(ValueError, match="verified Google identity"):
        web_app.portal_db.get_or_create_google_user("unverified@example.com", "google-sub-456", False)


def test_google_sign_in_links_to_an_existing_account_with_the_same_email(web_env):
    old_id = web_app.portal_db.create_user("admin2@example.com", "old-password-hash")
    user = web_app.portal_db.get_or_create_google_user("Admin2@Example.com", "google-sub-777", True)
    assert user["id"] == old_id and user["email"] == "admin2@example.com"
    again = web_app.portal_db.get_or_create_google_user("admin2@example.com", "google-sub-777", True)
    assert again["id"] == old_id


def test_about_page_and_founder_assets(web_env):
    status, _, body = _request("/about")
    assert status == "200 OK"
    for expected in (
        "About Us &amp; Co-Founders",
        "Abhay Samuel H",
        "Co-Founder &amp; CTO",
        "Pranav V Rao",
        "Co-Founder &amp; Systems Architect",
        "/assets/daemon-founder-abhay.webp",
        "/assets/daemon-founder-pranav.webp",
        "https://github.com/Samuel777822",
        "https://github.com/pranavvrao1-ai",
        "https://www.linkedin.com/in/pranav-v-rao-061040393/",
    ):
        assert expected in body

    # Raw WSGI request for binary assets
    from wsgiref.util import setup_testing_defaults
    values = {}
    setup_testing_defaults(values)
    values.update({"QUERY_STRING": "", "PATH_INFO": "/assets/daemon-founder-abhay.webp", "REQUEST_METHOD": "GET", "REMOTE_ADDR": "127.0.0.1", "wsgi.input": io.BytesIO()})
    captured = {}
    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers
    raw_abhay = b"".join(web_app.application(values, start_response))
    assert captured["status"] == "200 OK"
    assert any(h == ("Content-Type", "image/webp") for h in captured["headers"])
    assert len(raw_abhay) > 1000

    values["PATH_INFO"] = "/assets/daemon-founder-pranav.webp"
    raw_pranav = b"".join(web_app.application(values, start_response))
    assert captured["status"] == "200 OK"
    assert any(h == ("Content-Type", "image/webp") for h in captured["headers"])
    assert len(raw_pranav) > 1000


def test_onboarding_name_prompt_flow(web_env):
    from datetime import timedelta
    user_id = web_app.portal_db.create_user("newuser@example.com", "")
    session_id = web_app.portal_db.create_session(user_id, "csrf-token-123", (web_app._now() + timedelta(days=1)).isoformat(timespec="seconds"))
    cookie = f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}"
    csrf = "csrf-token-123"

    # GET /onboarding/name
    status, _, body = _request("/onboarding/name", cookie=cookie)
    assert status == "200 OK"
    assert "What is your name?" in body
    assert "Continue" in body

    # POST /onboarding/name to set the name
    status, headers, _ = _request("/onboarding/name", method="POST", form={"csrf": csrf, "name": "Jane Developer"}, cookie=cookie)
    assert status == "303 See Other"
    assert dict(headers)["Location"] == "/dashboard"

    # Dashboard reflects the name
    status, _, body = _request("/dashboard", cookie=cookie)
    assert status == "200 OK"
    assert "Jane Developer" in body


def test_chat_and_visitor_endpoints(web_env):
    # 1. Visitor tracking notifies admin once per window
    status, headers, body = _request("/api/visitor/track", method="POST", json_body={"path": "/about", "referrer": "google.com"})
    assert status == "200 OK"
    data = json.loads(body)
    assert data["ok"] is True

    # 2. Chat messages endpoint
    status, _, body = _request("/api/chat/messages")
    assert status == "200 OK"
    data = json.loads(body)
    assert "messages" in data and "conversation_id" in data
    conv_id = data["conversation_id"]

    # 3. Sending visitor inquiry triggers reply and notifies admins
    status, _, body = _request("/api/chat/send", method="POST", json_body={"text": "What are your pricing plans?", "contact": "visitor@example.com"})
    assert status == "200 OK"
    res = json.loads(body)
    assert "reply" in res and len(res["reply"]) > 10

    # 4. Chat JS asset
    status, headers, body = _request("/assets/chat.js")
    assert status == "200 OK"
    assert "daemon-chat-btn" in body

    # 5. Admin chat reply requires session and admin privileges
    status, headers, _ = _request("/api/admin/chat/reply", method="POST", json_body={"conversation_id": conv_id, "text": "Hello!"})
    assert status == "303 See Other" and dict(headers)["Location"] == "/login"

    # With non-admin session, returns 403 Forbidden
    from datetime import timedelta
    u_id = web_app.portal_db.create_user("user_not_admin@example.com", "")
    s_id = web_app.portal_db.create_session(u_id, "csrf-test", (web_app._now() + timedelta(days=1)).isoformat(timespec="seconds"))
    cookie_user = f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(s_id)}"
    status, _, _ = _request("/api/admin/chat/reply", method="POST", json_body={"conversation_id": conv_id, "text": "Hello!"}, cookie=cookie_user)
    assert status == "403 Forbidden"


def test_contact_us_page_and_admin_notifications(web_env):
    # 1. GET /contact renders form and sets CSRF cookie
    status, headers, body = _request("/contact")
    assert status == "200 OK"
    assert "Contact Our Team" in body
    assert "Your Work Email" in body
    assert "Send Message to Support" in body

    # Extract CSRF token and cookie (support both single and double quotes)
    match = re.search(r"name=['\"]csrf['\"]\s+value=['\"]([^'\"]+)['\"]", body)
    csrf = match.group(1) if match else "test-csrf"
    csrf_cookie = _cookie_value(headers, web_app.CSRF_COOKIE)
    contact_cookie = f"{web_app.CSRF_COOKIE}={csrf_cookie}"

    # 2. POST /contact without required fields fails gracefully
    status, _, body_fail = _request(
        "/contact",
        method="POST",
        form={"csrf": csrf, "name": "Tester", "email": "bad-email", "message": ""},
        cookie=contact_cookie,
    )
    assert status == "200 OK"
    assert "Please provide your name, email, and message" in body_fail or "valid email" in body_fail

    # 3. POST /contact with valid fields succeeds and creates support record
    status, _, body_ok = _request(
        "/contact",
        method="POST",
        form={
            "csrf": csrf,
            "name": "Alex Founder",
            "email": "alex@startup.com",
            "subject": "Enterprise monitoring question",
            "message": "We have 15 microservices and want to use Agent Daemon.",
        },
        cookie=contact_cookie,
    )
    assert status == "200 OK"
    assert "Thanks for reaching out!" in body_ok
    assert "alex@startup.com" in body_ok

    # Verify admin support messages list
    support_items = web_app.portal_db.admin_list_support_messages(5)
    assert any(s["email"] == "alex@startup.com" and "Enterprise" in s["subject"] for s in support_items)



def test_help_center_page_and_navigation(web_env):
    # 1. GET /help renders full help centre
    status, _, body = _request("/help")
    assert status == "200 OK"
    assert "Agent Daemon Help Centre" in body
    assert "Y3neE_B2d-M" in body  # YouTube video ID embed
    assert 'referrerpolicy="strict-origin-when-cross-origin"' in body
    assert "https://www.youtube.com/embed/Y3neE_B2d-M" in body
    assert "What the agent may do with a fix" in body
    assert "Auto (pushes proven fixes)" in body
    assert "Pull request" in body
    assert "Report only" in body
    assert "Show the agent: screenshots, voice and" in body
    assert "Troubleshooting Playbooks" in body
    assert "Offline" in body
    assert "GitHub Installation PR Fails" in body
    assert "Auto-Fix Skipped or Marked" in body
    assert "The fix came as a pull request instead of going live" in body
    assert "FastAPI" in body and "Flask" in body and "Django" in body
    assert "help-search" in body

    # 2. Aliases /docs, /help-center, /troubleshooting also work
    for alias in ("/docs", "/help-center", "/troubleshooting"):
        alias_status, _, alias_body = _request(alias)
        assert alias_status == "200 OK"
        assert "Agent Daemon Help Centre" in alias_body

    # 3. Header and footer navigation contain Help Center link
    _, _, home_body = _request("/")
    assert '<a href="/help">Help Center</a>' in home_body

    # 4. Chatbot recognizes help queries
    import chatbot
    reply = chatbot.answer_visitor_query("How do I troubleshoot when my app shows offline?")
    assert "/help" in reply



def test_structured_footer_and_all_links(web_env):
    # 1. Verify structured 4-column footer on home page
    status, _, body = _request("/")
    assert status == "200 OK"
    assert "footer-grid" in body
    assert "Product" in body
    assert "Company" in body
    assert "Resources" in body
    assert "Legal" in body

    # 2. Verify all active Product links
    for path, expected_text in [
        ("/features", "What Agent Daemon does"),
        ("/pricing", "Simple, honest plans"),
        ("/how-it-works", "Play the flow"),
        ("/docs", "Agent Daemon Help Centre"),
        ("/changelog", "Product Releases"),
    ]:
        st, _, b = _request(path)
        assert st == "200 OK", f"Failed for {path}: {st}"
        assert expected_text in b, f"Missing text for {path}"

    # 3. Verify active Company links (About Us, Contact Us)
    for path, expected_text in [
        ("/about", "About Us &amp; Co-Founders"),
        ("/contact", "Contact Our Team"),
    ]:
        st, _, b = _request(path)
        assert st == "200 OK", f"Failed for {path}: {st}"
        assert expected_text in b, f"Missing text for {path}"

    # 4. Verify active Resources links (FAQ, Help Center)
    for path, expected_text in [
        ("/faq", "Frequently Asked Questions"),
        ("/help", "Agent Daemon Help Centre"),
    ]:
        st, _, b = _request(path)
        assert st == "200 OK", f"Failed for {path}: {st}"
        assert expected_text in b, f"Missing text for {path}"

    # 5. Verify active Legal links (Privacy Policy, Terms of Service)
    for path, expected_text in [
        ("/privacy", "Privacy Policy"),
        ("/terms", "Terms of Service"),
    ]:
        st, _, b = _request(path)
        assert st == "200 OK", f"Failed for {path}: {st}"
        assert expected_text in b, f"Missing text for {path}"

    # 6. Verify removed links are not in footer HTML
    for removed in ("Partnerships", "Careers", "System Status", "Cookie Policy"):
        assert removed not in body, f"{removed} should not be in footer"


def test_indian_standard_time_formatting(web_env):
    from web_app import _fmt_time
    import incident_board
    # Given a UTC timestamp: 2026-11-03T14:15:00Z (+5:30 -> 19:45 IST)
    formatted = _fmt_time("2026-11-03T14:15:00Z")
    assert "03 Nov 2026, 19:45 IST" in formatted
    assert "UTC" not in formatted

    # incident_board helper
    ib_formatted = incident_board._fmt_ist("2026-11-03T14:15:00Z")
    assert "03 Nov 2026, 19:45 IST" in ib_formatted
    assert "UTC" not in ib_formatted




def test_support_ticketing_lifecycle(web_env, monkeypatch):
    import notifications
    from datetime import timedelta

    customer_emails_sent = []
    admin_emails_sent = []
    monkeypatch.setattr(notifications, "notify_customer", lambda to, subj, body, kind="": customer_emails_sent.append((to, subj, body, kind)))
    monkeypatch.setattr(notifications, "notify_admins", lambda subj, body, kind="": admin_emails_sent.append((subj, body, kind)))

    # 1. Contact form submission creates a support ticket
    st_get, headers, body = _request("/contact")
    assert st_get == "200 OK"
    match = re.search(r"name=['\"]csrf['\"]\s+value=['\"]([^'\"]+)['\"]", body)
    csrf = match.group(1) if match else "test-csrf"
    csrf_cookie = _cookie_value(headers, web_app.CSRF_COOKIE)
    contact_cookie = f"{web_app.CSRF_COOKIE}={csrf_cookie}"

    status, _, body_ok = _request(
        "/contact",
        method="POST",
        form={
            "csrf": csrf,
            "name": "Jane Developer",
            "email": "jane@company.com",
            "subject": "Issue with auto-fix branch",
            "message": "The PR opened has failing tests.",
        },
        cookie=contact_cookie,
    )
    assert status == "200 OK"
    assert "Thanks for reaching out!" in body_ok
    assert "TICK-" in body_ok

    # Customer gets ticket confirmation email with ticket ID
    assert len(customer_emails_sent) == 1
    to_cust, cust_subj, cust_body, kind = customer_emails_sent[0]
    assert to_cust == "jane@company.com"
    assert "TICK-" in cust_subj
    assert "support ticket" in cust_body.lower() or "ticket reference" in cust_body.lower()

    # Check database status
    tickets = web_app.portal_db.admin_list_support_messages(10)
    assert len(tickets) >= 1
    ticket = [t for t in tickets if t["email"] == "jane@company.com"][0]
    assert ticket["status"] == "open"
    assert ticket["ticket_ref"].startswith("TICK-")

    stats = web_app.portal_db.admin_ticket_stats()
    assert stats["open"] >= 1

    # 2. Admin logs in and views tickets
    user_id = web_app.portal_db.create_user("admin1@example.com", "hash")
    admin_csrf = "csrf-adm-" + user_id[:6]
    session_id = web_app.portal_db.create_session(user_id, admin_csrf, (web_app._now() + timedelta(days=1)).isoformat())
    admin_cookie = f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}"

    st, _, admin_html = _request("/admin", cookie=admin_cookie)
    assert st == "200 OK"
    assert "Support Tickets" in admin_html
    assert ticket["ticket_ref"] in admin_html

    # 3. Admin transitions status to 'for_review' and assigns to admin1
    st, hdrs, _ = _request(
        "/admin",
        method="POST",
        cookie=admin_cookie,
        form={
            "csrf": admin_csrf,
            "action": "update_support_ticket",
            "ticket_id": ticket["id"],
            "status": "for_review",
            "assigned_to": "admin1@example.com",
            "resolution_note": "",
        },
    )
    assert st == "303 See Other"
    loc = dict(hdrs).get("Location", "")
    assert "ticket_updated" in loc

    updated_t = web_app.portal_db.admin_get_support_ticket(ticket["id"])
    assert updated_t["status"] == "for_review"
    assert updated_t["assigned_to"] == "admin1@example.com"

    # 4. Admin closes ticket with resolution note
    st, hdrs, _ = _request(
        "/admin",
        method="POST",
        cookie=admin_cookie,
        form={
            "csrf": admin_csrf,
            "action": "update_support_ticket",
            "ticket_id": ticket["id"],
            "status": "closed",
            "assigned_to": "admin1@example.com",
            "resolution_note": "Fixed branch permission configuration in repo settings.",
        },
    )
    assert st == "303 See Other"
    assert "ticket_closed" in dict(hdrs).get("Location", "")

    closed_t = web_app.portal_db.admin_get_support_ticket(ticket["id"])
    assert closed_t["status"] == "closed"
    assert closed_t["closed_at"] != ""
    assert closed_t["closed_by"] == "admin1@example.com"
    assert closed_t["resolution_note"] == "Fixed branch permission configuration in repo settings."

    # Customer automatically receives closing resolution email
    closing_emails = [e for e in customer_emails_sent if e[3] == "ticket_closed"]
    assert len(closing_emails) == 1
    to_c, sub_c, body_c, _ = closing_emails[0]
    assert to_c == "jane@company.com"
    assert f"[Ticket #{closed_t['ticket_ref']}] Resolved:" in sub_c
    assert "Fixed branch permission configuration in repo settings." in body_c
    assert "Agent Daemon team of engineers" in body_c
