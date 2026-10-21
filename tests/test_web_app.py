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


def _request(path, *, method="GET", form=None, cookie="", json_body=None, ingest_key=""):
    values = {}
    setup_testing_defaults(values)
    values.update({"PATH_INFO": path, "REQUEST_METHOD": method, "REMOTE_ADDR": "127.0.0.1",
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


def test_anonymous_form_uses_signed_csrf_cookie(web_env):
    status, headers, body = _request("/signup")
    csrf_cookie = _cookie_value(headers, web_app.CSRF_COOKIE)
    csrf = re.search(r"name='csrf' value='([^']+)'", body).group(1)

    assert status == "200 OK"
    assert csrf_cookie
    assert web_app._verify_cookie(csrf_cookie) == csrf
    assert "Content-Security-Policy" in dict(headers)


def test_signup_creates_account_and_authenticated_session(web_env):
    _, headers, body = _request("/signup")
    csrf_cookie = _cookie_value(headers, web_app.CSRF_COOKIE)
    csrf = re.search(r"name='csrf' value='([^']+)'", body).group(1)
    status, headers, _ = _request("/signup", method="POST", cookie=f"{web_app.CSRF_COOKIE}={csrf_cookie}",
        form={"csrf": csrf, "email": "person@example.com", "password": "a-long-test-password"})

    assert status == "303 See Other"
    session_cookie = _cookie_value(headers, web_app.SESSION_COOKIE)
    session_id = web_app._verify_cookie(session_cookie)
    assert session_id
    assert web_app.portal_db.get_session(session_id)["email"] == "person@example.com"


def test_logout_requires_csrf_token(web_env):
    _, headers, body = _request("/signup")
    csrf_cookie = _cookie_value(headers, web_app.CSRF_COOKIE)
    csrf = re.search(r"name='csrf' value='([^']+)'", body).group(1)
    _, headers, _ = _request("/signup", method="POST", cookie=f"{web_app.CSRF_COOKIE}={csrf_cookie}",
        form={"csrf": csrf, "email": "person@example.com", "password": "a-long-test-password"})
    session_cookie = _cookie_value(headers, web_app.SESSION_COOKIE)

    status, _, _ = _request("/logout", method="POST", cookie=f"{web_app.SESSION_COOKIE}={session_cookie}", form={})
    assert status == "403 Forbidden"


def test_ingest_authenticates_and_deduplicates_per_project(web_env):
    user_id = web_app.portal_db.create_user("ingest@example.com", "hash")
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
    monkeypatch.setenv("RAZORPAY_AMOUNT_PAISE", "49900")
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
