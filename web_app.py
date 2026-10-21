"""Small, server-rendered web application for Agent Daemon.

This deliberately uses Python's standard-library WSGI server and HTML
templates. It is a development entry point; production should run behind an
HTTPS reverse proxy and set the secrets documented in README.md.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
from pathlib import PurePosixPath
from socketserver import ThreadingMixIn
from datetime import datetime, timedelta, timezone
from http import cookies
from io import BytesIO
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen
from wsgiref.simple_server import WSGIServer, make_server

import httpx
from urllib.parse import urlencode

import portal_db
from monitoring_installer import GitHubInstallError, open_monitoring_pr, validate_repository_access

APP_NAME = "Agent Daemon"
SESSION_COOKIE = "agent_session"
CSRF_COOKIE = "agent_csrf"
SESSION_SECONDS = 60 * 60 * 24 * 7
MAX_BODY = 65536
GOOGLE_CALLBACK_PATH = "/auth/google/callback"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
REPO_RE = re.compile(r"^(?:https?://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")

CSS = """
:root{color-scheme:dark;--bg:#0b1020;--panel:#121a2d;--line:#26324a;--muted:#9aa9c2;--text:#edf3ff;--blue:#75a7ff;--green:#55d6a1;--amber:#f0c36b}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 20% -20%,#1b3158 0,transparent 45%),var(--bg);color:var(--text);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}.wrap{max-width:1080px;margin:auto;padding:0 24px}.nav{height:72px;border-bottom:1px solid #ffffff12;display:flex;align-items:center;justify-content:space-between}.brand{font-size:17px;font-weight:750;letter-spacing:.02em;color:var(--text)}.brand-mark{display:inline-grid;place-items:center;width:28px;height:28px;margin-right:9px;background:#274b82;border-radius:9px;color:white}.navlinks{display:flex;gap:20px;align-items:center;color:var(--muted)}.button{display:inline-flex;align-items:center;justify-content:center;padding:10px 16px;border:1px solid #ffffff20;border-radius:10px;background:#19243a;color:var(--text);font:inherit;font-weight:650;cursor:pointer}.button.primary{background:#2f68c8;border-color:#4e88e7;color:white}.button.danger{color:#ffb3b3}.button:hover{filter:brightness(1.12);text-decoration:none}.hero{padding:76px 0 62px;max-width:760px}.eyebrow{color:var(--green);text-transform:uppercase;letter-spacing:.13em;font-size:12px;font-weight:750}.hero h1{font-size:clamp(38px,6vw,64px);line-height:1.04;letter-spacing:-.045em;margin:15px 0 20px}.hero p{font-size:19px;color:#b7c4d8;max-width:640px}.actions{display:flex;gap:12px;align-items:center;margin-top:28px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:16px;margin:22px 0 50px}.card{background:linear-gradient(145deg,#141e33,#101729);border:1px solid var(--line);border-radius:16px;padding:22px;box-shadow:0 18px 50px #0002}.card h2,.card h3{margin:0 0 8px}.muted{color:var(--muted)}.section{padding:18px 0 42px}.section h2{font-size:26px;letter-spacing:-.025em}.form-card{max-width:480px;margin:58px auto}.form-card h1{font-size:32px;margin:0 0 8px}.field{margin:16px 0}.field label{display:block;font-weight:650;margin-bottom:6px}.field input,.field select{width:100%;padding:12px 13px;border-radius:9px;border:1px solid #34425e;background:#0b1324;color:var(--text);font:inherit}.field small{display:block;color:var(--muted);margin-top:5px}.checkbox{display:flex;gap:10px;align-items:flex-start;color:#c7d2e4}.checkbox input{margin-top:6px}.alert{padding:12px 14px;border:1px solid #a47638;border-radius:10px;background:#342918;color:#ffe0a3;margin:16px 0}.stats{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}.pill{display:inline-flex;gap:7px;align-items:center;padding:5px 10px;border-radius:99px;background:#1b2d43;color:#b8c9df;font-size:12px}.pill.green{color:#8ce4c0;background:#14392f}.pill.amber{color:#ffdc91;background:#3a301b}.row{display:flex;justify-content:space-between;align-items:center;gap:16px}.table{width:100%;border-collapse:collapse;margin-top:16px}.table th,.table td{text-align:left;padding:12px 8px;border-bottom:1px solid var(--line);vertical-align:top}.table th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}.footer{border-top:1px solid #ffffff12;padding:24px 0 38px;color:var(--muted);font-size:13px}.empty{padding:30px;text-align:center;border:1px dashed #40506c;border-radius:14px;color:var(--muted)}
@media(max-width:640px){.wrap{padding:0 17px}.navlinks{gap:11px}.hero{padding:54px 0 40px}.hero p{font-size:17px}.actions{align-items:stretch;flex-direction:column}.row{align-items:flex-start;flex-direction:column}.table{font-size:13px}}
.button{transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease}
.button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #75a7ff;outline-offset:3px}
.button:active{transform:translateY(1px)}
.card{transition:border-color .18s ease,transform .18s ease}
a.card:hover{border-color:#4d6c9a;transform:translateY(-2px);text-decoration:none}
.table-wrap{max-width:100%;overflow-x:auto;border:1px solid var(--line);border-radius:12px;margin:16px 0}
.table{min-width:640px;margin:0}
.table th,.table td{padding:14px 12px}
.actions{display:flex;flex-wrap:wrap;gap:8px}
.actions form{margin:0}
.field input:focus,.field select:focus{border-color:var(--blue);box-shadow:0 0 0 3px #75a7ff20;outline:none}
h1,h2,h3{line-height:1.2}
@media(max-width:640px){.nav{height:auto;min-height:68px;align-items:flex-start;padding-top:16px;padding-bottom:16px;gap:12px}.navlinks{flex-wrap:wrap;justify-content:flex-end}.table{min-width:620px}.card{padding:18px}.section{padding-top:12px}}

"""


def _escape(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _secret() -> bytes:
    value = os.getenv("SESSION_SECRET", "")
    if len(value) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 characters")
    return value.encode("utf-8")


def _sign(value: str) -> str:
    mac = hmac.new(_secret(), value.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def _signed_cookie(value: str) -> str:
    return f"{value}.{_sign(value)}"


def _verify_cookie(value: str) -> str | None:
    if not value or "." not in value:
        return None
    raw, signature = value.rsplit(".", 1)
    try:
        return raw if hmac.compare_digest(signature, _sign(raw)) else None
    except RuntimeError:
        return None


class Request:
    def __init__(self, environ):
        self.environ = environ
        self.method = environ.get("REQUEST_METHOD", "GET").upper()
        self.path = urlsplit(environ.get("PATH_INFO", "/")).path
        self.query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        raw_cookie = cookies.SimpleCookie()
        try:
            raw_cookie.load(environ.get("HTTP_COOKIE", ""))
        except cookies.CookieError:
            pass
        self.cookies = {k: v.value for k, v in raw_cookie.items()}
        self.form = {}
        self.raw_body = b""
        if self.method == "POST":
            try:
                length = int(environ.get("CONTENT_LENGTH") or 0)
            except ValueError:
                length = MAX_BODY + 1
            if length > MAX_BODY:
                raise ValueError("Request body is too large")
            self.raw_body = environ.get("wsgi.input", BytesIO()).read(length)
            content_type = environ.get("CONTENT_TYPE", "").split(";", 1)[0].lower()
            if content_type == "application/json":
                try:
                    parsed = json.loads(self.raw_body.decode("utf-8"))
                    self.form = parsed if isinstance(parsed, dict) else {}
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self.form = {}
            else:
                data = self.raw_body.decode("utf-8", errors="replace")
                self.form = {key: values[-1] for key, values in parse_qs(data, keep_blank_values=True).items()}
        self.remote = environ.get("REMOTE_ADDR", "unknown")
        self.session = None
        self.new_csrf_cookie = None
        signed = _verify_cookie(self.cookies.get(SESSION_COOKIE, ""))
        if signed:
            self.session = portal_db.get_session(signed)


class Response:
    def __init__(self, body="", status="200 OK", headers=None):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status
        self.headers = list(headers or [])


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def _google_oauth_settings() -> tuple[str, str, str]:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    if not client_id or not client_secret or not redirect_uri:
        raise RuntimeError("Google sign-in is not configured yet. Ask the deployment owner to finish Google OAuth setup.")
    parsed = urlsplit(redirect_uri)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path != GOOGLE_CALLBACK_PATH or parsed.query or parsed.fragment:
        raise RuntimeError("Google sign-in callback must be the HTTPS /auth/google/callback URL.")
    return client_id, client_secret, redirect_uri


def _google_login_url(state: str, client_id: str, redirect_uri: str) -> str:
    params = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
              "scope": "openid email profile", "state": state, "prompt": "select_account"}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def _verified_google_identity(code: str, state: str, request: Request) -> dict:
    expected_state = _verify_cookie(request.cookies.get("agent_google_state", ""))
    if not state or not expected_state or not hmac.compare_digest(state, expected_state):
        raise ValueError("Google sign-in expired or could not be validated. Please try again.")
    client_id, client_secret, redirect_uri = _google_oauth_settings()
    try:
        token_response = httpx.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": client_id, "client_secret": client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
        }, timeout=10, follow_redirects=False)
        if token_response.status_code != 200:
            raise ValueError("Google could not complete sign-in. Please try again.")
        token_data = token_response.json()
        id_token = token_data.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise ValueError("Google did not return a verified identity.")
        claims_response = httpx.get(GOOGLE_TOKENINFO_URL, params={"id_token": id_token},
                                    timeout=10, follow_redirects=False)
        if claims_response.status_code != 200:
            raise ValueError("Google identity could not be verified. Please try again.")
        claims = claims_response.json()
    except httpx.HTTPError:
        raise ValueError("Google sign-in service could not be reached. Please try again.") from None
    if (claims.get("aud") != client_id or claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com")
            or not claims.get("sub") or claims.get("email_verified") not in (True, "true")):
        raise ValueError("Google account verification failed. Use a verified Google account.")
    email = claims.get("email")
    if not isinstance(email, str) or not EMAIL_RE.fullmatch(email):
        raise ValueError("Google did not provide a valid email address.")
    return {"email": email.lower().strip(), "google_sub": str(claims["sub"]), "email_verified": True}


def _google_begin(request: Request):
    try:
        client_id, _client_secret, redirect_uri = _google_oauth_settings()
    except RuntimeError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div>", request, "503 Service Unavailable")
    state = secrets.token_urlsafe(32)
    state_cookie = _cookie("agent_google_state", _signed_cookie(state), max_age=600, http_only=True)
    return _redirect(_google_login_url(state, client_id, redirect_uri), [state_cookie])


def _google_callback(request: Request):
    if request.method != "GET":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    error = request.query.get("error", [""])[0]
    code = request.query.get("code", [""])[0]
    state = request.query.get("state", [""])[0]
    clear_state = _cookie("agent_google_state", "", max_age=0, http_only=True)
    if error:
        return _redirect("/login", [clear_state])
    if not code:
        return _response("<div class='alert'>Google did not return an authorization code.</div>", request, "400 Bad Request",
                         headers=[clear_state])
    try:
        identity = _verified_google_identity(code, state, request)
        user = portal_db.get_or_create_google_user(identity["email"], identity["google_sub"], identity["email_verified"])
    except (ValueError, RuntimeError) as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div>", request, "400 Bad Request",
                         headers=[clear_state])
    session_headers = _new_session(user["id"])
    session_headers.append(clear_state)
    return _redirect("/admin" if identity["email"] in _admin_emails() else "/dashboard", session_headers)


def _admin_emails() -> set[str]:
    raw = os.getenv("ADMIN_EMAILS", "") or os.getenv("ADMIN_EMAIL", "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}

def _admin_password_env(email: str) -> str:
    key = "ADMIN_PASSWORD_" + re.sub(r"[^A-Z0-9]", "_", email.upper())
    specific = os.getenv(key, "")
    if specific:
        return specific
    admins = _admin_emails()
    return os.getenv("ADMIN_PASSWORD", "") if len(admins) == 1 and email in admins else ""

def _is_admin(request: Request) -> bool:
    return bool(request.session and request.session.get("email", "").lower() in _admin_emails())


def _layout(title: str, body: str, request: Request | None = None) -> str:
    signed_in = bool(request and request.session)
    links = ('<a href="/dashboard">Dashboard</a><a href="/billing">Access</a><form method="post" action="/logout" style="display:inline">'
             f'<input type="hidden" name="csrf" value="{_csrf(request)}"><button class="button" type="submit">Sign out</button></form>') if signed_in else '<a href="/login">Sign in</a><a class="button" href="/signup">Create account</a>'
    if signed_in and _is_admin(request):
        links = '<a href="/admin">Admin</a>' + links
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="AI incident response for Python apps"><title>{_escape(title)} · {APP_NAME}</title><style>{CSS}</style></head><body><header class="wrap nav"><a class="brand" href="/"><span class="brand-mark">A</span>{APP_NAME}</a><nav class="navlinks">{links}</nav></header><main class="wrap">{body}</main><footer class="wrap footer">Agent Daemon · Your changes stay reviewable and reversible.</footer></body></html>"""


def _csrf(request: Request) -> str:
    if request.session:
        return request.session["csrf_token"]
    token = _verify_cookie(request.cookies.get(CSRF_COOKIE, ""))
    if not token:
        token = secrets.token_urlsafe(32)
        request.new_csrf_cookie = _cookie(CSRF_COOKIE, _signed_cookie(token), max_age=7200, http_only=False)
    return token


def _response(body, request=None, status="200 OK", headers=None):
    defaults = [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"),
                ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "same-origin"),
                ("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")]
    response = Response(_layout("Agent Daemon", body, request), status, defaults + list(headers or []))
    if request and request.new_csrf_cookie:
        response.headers.append(request.new_csrf_cookie)
    return response


def _redirect(location: str, headers=None):
    return Response(b"", "303 See Other", [("Location", location), ("Cache-Control", "no-store")] + list(headers or []))


def _cookie(name: str, value: str, *, max_age: int, http_only=True):
    secure = "; Secure" if os.getenv("APP_ENV", "development").lower() == "production" else ""
    http = "; HttpOnly" if http_only else ""
    return ("Set-Cookie", f"{name}={value}; Path=/; Max-Age={max_age}; SameSite=Lax{http}{secure}")


def _csrf_valid(request: Request) -> bool:
    submitted = request.form.get("csrf", "")
    expected = _csrf(request)
    return bool(submitted and expected and hmac.compare_digest(submitted, expected))


def _require_session(request: Request):
    if not request.session:
        return _redirect("/login")
    return None

def _require_access(request: Request):
    gate = _require_session(request)
    if gate:
        return gate
    if _is_admin(request) or portal_db.user_has_active_access(request.session["user_id"]):
        return None
    return _redirect("/billing")


def _new_session(user_id: str):
    csrf = secrets.token_urlsafe(32)
    expires = (_now() + timedelta(seconds=SESSION_SECONDS)).isoformat(timespec="seconds")
    session_id = portal_db.create_session(user_id, csrf, expires)
    return [_cookie(SESSION_COOKIE, _signed_cookie(session_id), max_age=SESSION_SECONDS),
            _cookie(CSRF_COOKIE, "", max_age=0, http_only=False)]


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + salt.hex() + "$" + digest.hex()


def _password_matches(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = stored.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                                n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(expected)))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def _form(title: str, intro: str, fields: str, action: str, submit: str, csrf: str) -> str:
    return f"<section class='card form-card'><h1>{title}</h1><p class='muted'>{intro}</p><form method='post' action='{action}'><input type='hidden' name='csrf' value='{_escape(csrf)}'>{fields}{submit}</form></section>"


def _page_home(request):
    if request.session:
        return _redirect("/admin" if _is_admin(request) else "/dashboard")
    body = """<section class="hero"><div class="eyebrow">Incident response for Python services</div><h1>When production breaks, get to the cause faster.</h1><p>Agent Daemon groups recurring error logs and explains likely causes in a project-scoped incident report. Create an account to request access; projects unlock after trial approval or payment confirmation.</p><div class="actions"><a class="button primary" href="/signup">Create account</a><a class="button" href="/login">Sign in</a></div></section><section class="grid"><article class="card"><h3>See what happened</h3><p class="muted">Turn repeated error logs into incidents with a clear timeline and diagnosis.</p></article><article class="card"><h3>Keep your code in your control</h3><p class="muted">The hosted diagnosis worker reads repository files as evidence. It does not run your code or tests or change your repository.</p></article><article class="card"><h3>Keep control</h3><p class="muted">Pause monitoring or remove the project and its stored data from your dashboard.</p></article></section>"""
    return _response(body, request)


def _page_signup(request):
    if request.method == "GET":
        body = _form("Create your account", "Sign up with Google to request a trial or plan.",
          "<p class='muted'>Use your verified Google account to continue. Email and password sign-up is also available.</p><div class='field'><label>Email</label><input name='email' type='email' autocomplete='email' required maxlength='254'></div><div class='field'><label>Password</label><input name='password' type='password' autocomplete='new-password' minlength='12' required><small>Use at least 12 characters.</small></div>",
          "/signup", "<button class='button primary' type='submit'>Create account</button>", _csrf(request))
        google_button = "<a class='button' href='/auth/google'>Continue with Google</a><div class='divider'>or use email and password</div>"
        return _response("<section class='card form-card'>" + google_button + body + "</section>", request)
    if not _csrf_valid(request):
        return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
    email, password = request.form.get("email", "").strip().lower(), request.form.get("password", "")
    rate_key = "signup:" + hashlib.sha256(request.remote.encode()).hexdigest()
    if not portal_db.check_login_rate_limit(rate_key, maximum=5):
        return _response("<div class='alert'>Too many attempts. Try again in a few minutes.</div>", request, "429 Too Many Requests")
    if not EMAIL_RE.fullmatch(email) or len(password) < 12 or len(password) > 1024:
        return _response("<div class='alert'>Enter a valid email and a password with at least 12 characters.</div>", request, "400 Bad Request")
    if email in _admin_emails():
        return _response("<div class='alert'>This address is reserved for an administrator. Use administrator sign-in credentials.</div>", request, "403 Forbidden")
    try:
        user_id = portal_db.create_user(email, _password_hash(password))
        conn = portal_db.get_connection()
        try:
            portal_db._execute(conn, "UPDATE users SET email_verified=0 WHERE id=?", (user_id,))
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            return _response("<div class='alert'>An account with that email already exists. Sign in instead.</div>", request, "409 Conflict")
        raise
    return _redirect("/dashboard", _new_session(user_id))


def _page_login(request):
    if request.method == "GET":
        body = _form("Welcome back", "Sign in to view your monitored projects.",
          "<div class='field'><label>Email</label><input name='email' type='email' autocomplete='email' required maxlength='254'></div><div class='field'><label>Password</label><input name='password' type='password' autocomplete='current-password' required></div>",
          "/login", "<button class='button primary' type='submit'>Sign in with email</button>", _csrf(request))
        google_button = "<a class='button primary' href='/auth/google'>Continue with Google</a><div class='divider'>or sign in with email</div>"
        return _response("<section class='card form-card'>" + google_button + body + "</section>", request)
    if not _csrf_valid(request):
        return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
    email = request.form.get("email", "").strip().lower()
    rate_key = "login:" + hashlib.sha256((request.remote + "\0" + email).encode()).hexdigest()
    if not portal_db.check_login_rate_limit(rate_key):
        return _response("<div class='alert'>Too many sign-in attempts. Try again in a few minutes.</div>", request, "429 Too Many Requests")
    submitted_password = request.form.get("password", "")
    if email in _admin_emails():
        admin_password = _admin_password_env(email)
        if len(admin_password) < 12 or not hmac.compare_digest(submitted_password, admin_password):
            return _response("<div class='alert'>Administrator credentials are not configured or are incorrect.</div>", request, "401 Unauthorized")
        user = portal_db.get_user_by_email(email)
        user_id = user["id"] if user else portal_db.create_user(email, _password_hash(admin_password))
        return _redirect("/admin", _new_session(user_id))
    user = portal_db.get_user_by_email(email)
    if not user or not _password_matches(submitted_password, user["password_hash"]):
        return _response("<div class='alert'>Email or password is incorrect.</div>", request, "401 Unauthorized")
    return _redirect("/dashboard", _new_session(user["id"]))


def _page_admin(request):
    if not request.session:
        return _redirect("/login")
    if not _is_admin(request):
        return _response("<h1>Not found</h1>", request, "404 Not Found")
    if request.method == "POST":
        if not _csrf_valid(request):
            return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
        user_id = request.form.get("user_id", "")
        action = request.form.get("action", "")
        if action in ("approve_trial", "reject_trial"):
            request_id = request.form.get("request_id", "")
            decision = "approved" if action == "approve_trial" else "rejected"
            trial = portal_db.admin_review_trial_request(request_id, decision, request.session["email"])
            if not trial:
                return _response("<div class='alert'>This trial request was already reviewed or no longer exists.</div>", request, "409 Conflict")
            if decision == "approved":
                portal_db.admin_grant_access(trial["user_id"], 1, "trial", request.session["email"])
            import notifications
            subject = "Your Agent Daemon trial is approved" if decision == "approved" else "Update on your Agent Daemon trial request"
            until = portal_db.get_subscription_active_until(trial["user_id"]) if decision == "approved" else ""
            message = (f"Your one-day trial is approved and expires at {until}. Sign in to connect your project: https://incident-agent-portal.onrender.com" if decision == "approved" else "Your trial request was not approved at this time.")
            sent = notifications.notify_customer(trial["email"], subject, message)
            return _redirect("/admin?updated=1&email=" + ("sent" if sent else "not-configured"))
        if action == "revoke":
            portal_db.admin_revoke_access(user_id)
            return _redirect("/admin?updated=1")
        grant_type = request.form.get("grant_type", "")
        try:
            days = int(request.form.get("days", ""))
        except ValueError:
            days = 0
        if grant_type not in ("trial", "paid") or not 1 <= days <= 3650:
            return _response("<div class='alert'>Choose trial or paid access and enter 1–3650 days.</div>", request, "400 Bad Request")
        try:
            until = portal_db.admin_grant_access(user_id, days, grant_type, request.session["email"])
        except ValueError as exc:
            return _response(f"<div class='alert'>{_escape(exc)}</div>", request, "400 Bad Request")
        return _redirect("/admin?updated=1")
    csrf = _escape(_csrf(request))
    trial_rows = []
    for trial in portal_db.admin_list_trial_requests():
        actions = ""
        if trial["status"] == "pending":
            actions = f"<form method='post' action='/admin' class='actions'><input type='hidden' name='csrf' value='{csrf}'><input type='hidden' name='request_id' value='{_escape(trial['id'])}'><button class='button primary' name='action' value='approve_trial' type='submit'>Approve 1-day trial</button><button class='button danger' name='action' value='reject_trial' type='submit'>Reject</button></form>"
        trial_rows.append(f"<tr><td>{_escape(trial['email'])}</td><td>{_escape(trial['status'])}</td><td>{_escape(trial['requested_at'])}</td><td>{actions}</td></tr>")
    trial_table = ("<div class='table-wrap'><table class='table'><thead><tr><th>Customer</th><th>Status</th><th>Requested</th><th>Decision</th></tr></thead><tbody>" + "".join(trial_rows) + "</tbody></table></div>") if trial_rows else "<div class='empty'>No trial requests yet.</div>"
    rows = []
    now = _now().isoformat(timespec="seconds")
    for user in portal_db.admin_list_users():
        if user["email"].lower() in _admin_emails():
            continue
        until = user.get("active_until") or ""
        active = bool(until and until > now)
        state = f"Access active through {_escape(until)} · {_escape(user.get('grant_type') or 'approved')}" if active else "Awaiting approval or access expired"
        csrf = _escape(_csrf(request))
        rows.append(f"""<tr><td>{_escape(user['email'])}<br><small class='muted'>Joined {_escape(user['created_at'])}</small></td><td>{state}</td><td>
<form method='post' action='/admin' style='min-width:250px'><input type='hidden' name='csrf' value='{csrf}'><input type='hidden' name='user_id' value='{_escape(user['id'])}'><div class='field'><label>Grant access</label><select name='grant_type'><option value='trial'>Trial</option><option value='paid'>Paid plan</option></select><input name='days' type='number' min='1' max='3650' value='14' required aria-label='Days of access'></div><button class='button primary' name='action' value='grant' type='submit'>Approve access</button></form>
<form method='post' action='/admin' style='margin-top:8px'><input type='hidden' name='csrf' value='{csrf}'><input type='hidden' name='user_id' value='{_escape(user['id'])}'><button class='button danger' name='action' value='revoke' type='submit'>Revoke access</button></form></td></tr>""")
    table = ("<table class='table'><thead><tr><th>Account</th><th>Permission</th><th>Admin action</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>") if rows else "<div class='empty'>No customer accounts yet.</div>"
    info = "<div class='alert'>Grant Paid only after payment is confirmed. Grant Trial only after approving the requested trial. Revoking access pauses the customer’s projects.</div>"
    if request.query.get("updated") == ["1"]:
        info = "<div class='pill green'>Access list updated.</div>" + info
    return _response(f"<section class='section'><div class='eyebrow'>Administrator workspace</div><h1>Operations overview</h1><p class='muted'>Signed in as {_escape(request.session['email'])}.</p><h2>Trial requests</h2>{trial_table}<h2>Customer access</h2>{info}{table}</section>", request)


def _page_trial_request(request):
    gate = _require_session(request)
    if gate:
        return gate
    if request.method != "POST":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    if not _csrf_valid(request):
        return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
    existing = portal_db.create_trial_request(request.session["user_id"])
    import notifications
    results = notifications.notify_admins("New Agent Daemon trial request", f"Customer {request.session['email']} requested a one-day trial. Review it here: https://incident-agent-portal.onrender.com/admin")
    sent = bool(results) and all(results.values())
    message = "Trial request saved. Both administrators were notified by email." if sent else "Trial request saved, but email delivery is not confirmed. Administrators can still review it in the dashboard."
    return _response(f"<section class='card form-card'><h1>Request received</h1><p>{_escape(message)}</p><p class='muted'>Status: {_escape(existing['status'])}</p><a class='button primary' href='/billing'>Back to account access</a></section>", request)

def _page_dashboard(request):
    if request.method != "GET":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    gate = _require_access(request)
    if gate:
        return gate
    projects = portal_db.list_projects(request.session["user_id"])
    cards = []
    for project in projects:
        status = "Paused" if project["paused"] else project["status"].replace("_", " ").title()
        css = "amber" if project["paused"] or project["status"] != "connected" else "green"
        cards.append(f"<a class='card' href='/projects/{_escape(project['id'])}'><div class='row'><h3>{_escape(project['name'])}</h3><span class='pill {css}'>{_escape(status)}</span></div><p class='muted'>{_escape(project['repo_owner'])}/{_escape(project['repo_name'])} · {_escape(project['branch'])}</p><p class='muted'>Mode: {_escape(project['mode'])}</p></a>")
    listing = "".join(cards) or "<div class='empty'>No projects yet. Connect a Python app to start monitoring it.</div>"
    body = f"<section class='section'><div class='row'><div><div class='eyebrow'>Workspace</div><h1>Projects</h1><p class='muted'>Signed in as {_escape(request.session['email'])}</p></div><a class='button primary' href='/projects/new'>Connect a project</a></div><div class='grid'>{listing}</div></section>"
    return _response(body, request)


def _encrypt_token(token: str) -> str:
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not configured")
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode("ascii")).encrypt(token.encode("utf-8")).decode("ascii")
    except ImportError as exc:
        raise RuntimeError("Token encryption requires cryptography") from exc
    except Exception as exc:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc


def _decrypt_token(ciphertext: str) -> str:
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is required to use saved GitHub credentials")
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode("ascii")).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise RuntimeError("Saved GitHub credential could not be decrypted") from exc


def _page_new_project(request):
    gate = _require_access(request)
    if gate:
        return gate
    if request.method == "GET":
        fields = """<div class='field'><label>Project name</label><input name='name' required maxlength='80' placeholder='Checkout service'></div>
<div class='field'><label>GitHub repository</label><input name='repo' required placeholder='owner/repository'><small>Use a fine-grained token limited to this repository.</small></div>
<div class='field'><label>GitHub token</label><input name='github_token' type='password' autocomplete='off' required><small>Stored encrypted. It is never displayed after saving.</small></div>
<div class='field'><label>Default branch</label><input name='branch' value='main' required maxlength='100'></div>
<div class='field'><label>Agent mode</label><select name='mode'><option value='report' selected>Report only</option><option value='pr'>Pull request</option><option value='auto'>Auto (merge only after passing CI)</option></select><small>Pull request mode opens a reviewable PR. Auto mode also merges only after GitHub reports at least one completed passing check and no failing or pending checks. With no checks, the PR stays open.</small></div>
<div class='field'><label>App URL (optional)</label><input name='app_url' type='url' placeholder='https://app.example.com'></div>
<div class='field'><label class='checkbox'><input name='allow_install' type='checkbox' value='yes' required><span>I authorize Agent Daemon to add its monitoring code to this repository through a reviewable pull request.</span></label></div>
<div class='field'><label class='checkbox'><input name='allow_ai_processing' type='checkbox' value='yes' required><span>I understand that selected error logs, tracebacks, and relevant repository source files will be sent to Groq for AI diagnosis.</span></label></div>
<div class='field'><label class='checkbox'><input name='allow_remediation' type='checkbox' value='yes'><span>For Pull request or Auto mode, I authorize small, high-confidence Python fixes as pull requests. The agent will not run my code or tests. Auto mode may merge only after all GitHub checks it can see pass; no checks, failed checks, or unavailable checks leave the PR open.</span></label></div>"""
        body = _form("Connect a project", "We only monitor after you authorize the installation.", fields,
                     "/projects/new", "<button class='button primary' type='submit'>Save project</button>", _csrf(request))
        return _response(body, request)
    if not _csrf_valid(request):
        return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
    if request.form.get("allow_install") != "yes" or request.form.get("allow_ai_processing") != "yes":
        return _response("<div class='alert'>Authorize monitoring installation and AI diagnosis data processing before continuing.</div>", request, "400 Bad Request")
    repo_match = REPO_RE.fullmatch(request.form.get("repo", "").strip())
    token = request.form.get("github_token", "").strip()
    mode = request.form.get("mode", "report")
    name = request.form.get("name", "").strip()
    branch = request.form.get("branch", "main").strip()
    if not repo_match or not token or not name or not branch or mode not in ("report", "pr", "auto"):
        return _response("<div class='alert'>Check the repository, token, project name, branch, and mode.</div>", request, "400 Bad Request")
    if mode in ("pr", "auto") and request.form.get("allow_remediation") != "yes":
        return _response("<div class='alert'>Authorize pull request remediation before selecting Pull request or Auto mode.</div>", request, "400 Bad Request")
    try:
        ciphertext = _encrypt_token(token)
    except RuntimeError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}. Set it before connecting projects.</div>", request, "503 Service Unavailable")
    owner, repo = repo_match.group(1), repo_match.group(2)
    try:
        validate_repository_access(owner=owner, repo=repo.removesuffix(".git"), token=token)
    except GitHubInstallError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div>", request, "400 Bad Request")
    ingest_key = secrets.token_urlsafe(32)
    ingest_hash = hashlib.sha256(ingest_key.encode()).hexdigest()
    project_id = portal_db.create_project(request.session["user_id"], name=name,
        repo_owner=owner, repo_name=repo.removesuffix(".git"), branch=branch, mode=mode,
        token_ciphertext=ciphertext, ingest_key_hash=ingest_hash,
        app_url=request.form.get("app_url", "").strip(), ai_consent_at=portal_db._now())
    portal_db.audit(project_id, "project_connected", {"repo": f"{owner}/{repo}", "mode": mode})
    portal_db.audit(project_id, "ai_diagnosis_consent", {"scope": "selected logs, tracebacks, and repository source sent to Groq"})
    if mode in ("pr", "auto"):
        portal_db.audit(project_id, "remediation_consent", {"mode": mode, "auto_merge_requires_passing_github_checks": mode == "auto"})
    notice = f"<div class='alert'>Save this ingest key now. It is shown once: <code>{_escape(ingest_key)}</code></div>"
    return _response(notice + f"<section class='card'><h1>Project saved</h1><p class='muted'>The monitoring installer is the next step. Your project is pending until the monitoring pull request is merged and its first heartbeat arrives.</p><a class='button primary' href='/projects/{_escape(project_id)}'>View project</a></section>", request, "201 Created")


def _page_project(request, project_id):
    gate = _require_access(request)
    if gate:
        return gate
    project = portal_db.get_project(project_id, request.session["user_id"])
    if not project:
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    if request.method == "POST":
        if not _csrf_valid(request):
            return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
        paused = request.form.get("paused") == "yes"
        conn = portal_db.get_connection()
        try:
            portal_db._execute(conn, "UPDATE projects SET paused=? WHERE id=? AND user_id=?",
                               (1 if paused else 0, project_id, request.session["user_id"]))
            conn.commit()
        finally:
            conn.close()
        portal_db.audit(project_id, "project_paused" if paused else "project_resumed")
        return _redirect(f"/projects/{project_id}")
    incidents = portal_db.list_incidents(project_id)
    rows = "".join(f"<tr><td><a href='/projects/{_escape(project_id)}/incidents/{_escape(i['id'])}'>Incident {_escape(i['id'][:8])}</a></td><td>{_escape(i['status'].replace('_',' ').title())}</td><td>{_escape(i['occurrences'])}</td><td>{_escape(i['last_seen'])}</td></tr>" for i in incidents)
    table = f"<table class='table'><thead><tr><th>Incident</th><th>Status</th><th>Events</th><th>Last seen</th></tr></thead><tbody>{rows}</tbody></table>" if rows else "<div class='empty'>No incidents yet. Once monitoring is installed, incidents will appear here.</div>"
    paused = bool(project["paused"])
    button = ("Resume agent" if paused else "Pause agent")
    install_card = (f"<article class='card'><h3>Monitoring pull request</h3><p class='muted'>Review the opt-in helper and merge it when ready.</p><a class='button primary' href='{_escape(project['install_pr_url'])}'>View installation PR</a></article>" if project.get("install_pr_url") else f"<article class='card'><h3>Install monitoring</h3><p class='muted'>Open a pull request with the opt-in Python error reporting helper. Secrets are not added to the repository.</p><form method='post' action='/projects/{_escape(project_id)}/install'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><button class='button primary' type='submit'>Open monitoring PR</button></form></article>")
    body = f"<section class='section'><p><a href='/dashboard'>← Projects</a></p><div class='row'><div><div class='eyebrow'>Project</div><h1>{_escape(project['name'])}</h1><p class='muted'><a href='https://github.com/{_escape(project['repo_owner'])}/{_escape(project['repo_name'])}'>{_escape(project['repo_owner'])}/{_escape(project['repo_name'])}</a> · {_escape(project['branch'])} · {_escape(project['mode']).title()} mode</p></div><form method='post'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><input type='hidden' name='paused' value='{'no' if paused else 'yes'}'><button class='button {'primary' if paused else 'danger'}' type='submit'>{button}</button></form></div><div class='stats'><span class='pill {'amber' if paused else 'green'}'>{'Paused' if paused else _escape(project['status'].replace('_',' ').title())}</span><span class='pill'>Mode · {_escape(project['mode'])}</span></div><h2>Incident history</h2>{table}<section class='grid'>{install_card}<article class='card'><h3>Update GitHub token</h3><p class='muted'>Use a token authorized for this repository with Contents and Pull requests read/write access. The new token replaces the saved one and is never shown again.</p><form method='post' action='/projects/{_escape(project_id)}/github-token'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><div class='field'><label>New GitHub token</label><input name='github_token' type='password' autocomplete='new-password' required minlength='20' maxlength='500'></div><button class='button primary' type='submit'>Validate and save token</button></form></article><article class='card'><h3>Ingest key</h3><p class='muted'>Rotate the project key if it is exposed. The new key appears once.</p><form method='post' action='/projects/{_escape(project_id)}/rotate-key'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><button class='button' type='submit'>Rotate key</button></form></article><article class='card'><h3>Delete project data</h3><p class='muted'>Remove this project, its incidents, logs, fixes, and stored GitHub token.</p><form method='post' action='/projects/{_escape(project_id)}/delete'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><div class='field'><label>Type DELETE to confirm</label><input name='confirm' required autocomplete='off'></div><button class='button danger' type='submit'>Delete project</button></form></article></section></section>"
    return _response(body, request)


def _page_install_monitoring(request, project_id):
    gate = _require_access(request)
    if gate:
        return gate
    if request.method != "POST" or not _csrf_valid(request):
        return _response("<div class='alert'>Request expired or invalid.</div>", request, "403 Forbidden")
    project = portal_db.get_project(project_id, request.session["user_id"])
    if not project:
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    if project.get("install_pr_url"):
        return _redirect(f"/projects/{project_id}")
    try:
        token = _decrypt_token(project["github_token_ciphertext"])
        result = open_monitoring_pr(owner=project["repo_owner"], repo=project["repo_name"],
                                    base_branch=project["branch"], project_id=project_id, token=token)
    except (GitHubInstallError, RuntimeError) as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div><p><a href='/projects/{_escape(project_id)}'>Back to project</a></p>", request, "502 Bad Gateway")
    if not portal_db.record_install_pr(project_id, request.session["user_id"], result["url"]):
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    portal_db.audit(project_id, "monitoring_pr_opened", {"pr_url": result["url"], "pr_number": result["number"]})
    return _redirect(f"/projects/{project_id}")


def _page_update_github_token(request, project_id):
    gate = _require_access(request)
    if gate:
        return gate
    if request.method != "POST" or not _csrf_valid(request):
        return _response("<div class='alert'>Request expired or invalid.</div>", request, "403 Forbidden")
    user_id = request.session["user_id"]
    project = portal_db.get_project(project_id, user_id)
    if not project:
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    token = request.form.get("github_token", "").strip()
    if len(token) < 20 or len(token) > 500:
        return _response("<div class='alert'>Enter the complete GitHub token.</div><p><a href='/projects/" + _escape(project_id) + "'>Back to project</a></p>", request, "400 Bad Request")
    try:
        validate_repository_access(owner=project["repo_owner"], repo=project["repo_name"], token=token)
        ciphertext = _encrypt_token(token)
    except GitHubInstallError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div><p><a href='/projects/{_escape(project_id)}'>Back to project</a></p>", request, "400 Bad Request")
    except RuntimeError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div>", request, "503 Service Unavailable")
    if not portal_db.update_project_github_token(project_id, user_id, ciphertext):
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    portal_db.audit(project_id, "github_token_updated", {"repository": f"{project['repo_owner']}/{project['repo_name']}"})
    return _response("<div class='pill green'>GitHub token validated and updated. You can retry the monitoring pull request.</div><p><a class='button primary' href='/projects/" + _escape(project_id) + "'>Back to project</a></p>", request)


def _page_rotate_ingest_key(request, project_id):
    gate = _require_access(request)
    if gate:
        return gate
    if request.method != "POST" or not _csrf_valid(request):
        return _response("<div class='alert'>Request expired or invalid.</div>", request, "403 Forbidden")
    user_id = request.session["user_id"]
    if not portal_db.get_project(project_id, user_id):
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    if not portal_db.rotate_project_ingest_key(project_id, user_id, key_hash):
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    portal_db.audit(project_id, "ingest_key_rotated")
    body = f"<section class='card form-card'><h1>New ingest key</h1><p class='muted'>The previous key is invalid now. Copy this value into your app environment; it will not be shown again.</p><div class='alert'><code>{_escape(key)}</code></div><a class='button primary' href='/projects/{_escape(project_id)}'>Back to project</a></section>"
    return _response(body, request)


def _page_delete_project(request, project_id):
    gate = _require_access(request)
    if gate:
        return gate
    if request.method != "POST" or not _csrf_valid(request):
        return _response("<div class='alert'>Request expired or invalid.</div>", request, "403 Forbidden")
    if request.form.get("confirm") != "DELETE":
        return _response("<div class='alert'>Type DELETE exactly to confirm removal.</div>", request, "400 Bad Request")
    deleted = portal_db.delete_project(project_id, request.session["user_id"])
    if not deleted:
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    return _redirect("/dashboard")


def _page_incident(request, project_id, incident_id):
    gate = _require_access(request)
    if gate:
        return gate
    project = portal_db.get_project(project_id, request.session["user_id"])
    if not project:
        return _response("<h1>Project not found</h1>", request, "404 Not Found")
    conn = portal_db.get_connection()
    try:
        row = portal_db._execute(conn, "SELECT * FROM incidents WHERE id=? AND project_id=?", (incident_id, project_id)).fetchone()
        incident = dict(row) if row else None
        fixes = portal_db._execute(conn, "SELECT * FROM fixes WHERE incident_id=? ORDER BY created_at DESC", (incident_id,)).fetchall() if incident else []
    finally:
        conn.close()
    if not incident:
        return _response("<h1>Incident not found</h1>", request, "404 Not Found")
    diff = "".join(f"<article class='card'><div class='row'><strong>{_escape(f['file_path'])}</strong><span class='pill'>{_escape(f['ci_result'])}</span></div><pre style='overflow:auto;white-space:pre-wrap;color:#c7d2e4'>{_escape(f['diff'])}</pre></article>" for f in fixes) or "<div class='empty'>No proposed fix has been saved yet.</div>"
    pr_link = (f"<p><a class='button primary' href='{_escape(incident['pr_url'])}' target='_blank' rel='noopener'>Open fix pull request</a></p>"
               if incident.get("pr_url") else "")
    body = f"<section class='section'><p><a href='/projects/{_escape(project_id)}'>← {_escape(project['name'])}</a></p><div class='eyebrow'>Incident</div><h1>{_escape(incident['signature'])}</h1><div class='stats'><span class='pill'>{_escape(incident['status'])}</span><span class='pill'>Occurrences · {_escape(incident['occurrences'])}</span><span class='pill'>CI · {_escape(incident['ci_status'])}</span></div>{pr_link}<article class='card'><h2>What happened</h2><p>{_escape(incident['root_cause']) or 'Diagnosis is pending.'}</p><p class='muted' style='white-space:pre-wrap'>{_escape(incident['report'])}</p></article><h2>Proposed changes</h2>{diff}</section>"
    return _response(body, request)


def _razorpay_settings(plan: str = "yearly"):
    if plan not in ("monthly", "yearly"):
        raise RuntimeError("Unknown subscription plan")
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    mode = os.getenv("RAZORPAY_MODE", "test").strip().lower()
    if mode == "test" and not key_id.startswith("rzp_test_"):
        raise RuntimeError("Configure a Razorpay test key beginning with rzp_test_")
    if mode == "live" and not key_id.startswith("rzp_live_"):
        raise RuntimeError("Live mode requires a Razorpay live key beginning with rzp_live_")
    if mode not in ("test", "live") or not secret:
        raise RuntimeError("Configure Razorpay mode and key credentials")
    name = "RAZORPAY_MONTHLY_AMOUNT_PAISE" if plan == "monthly" else "RAZORPAY_YEARLY_AMOUNT_PAISE"
    amount = os.getenv(name, "").strip() or ("10000" if plan == "monthly" else "100000")
    try:
        amount_paise = int(amount)
    except ValueError as exc:
        raise RuntimeError("Subscription amount must be a positive integer in paise") from exc
    if amount_paise < 100:
        raise RuntimeError("Subscription amount must be at least 100 paise")
    return key_id, secret, amount_paise


def _fetch_razorpay_payment(payment_id: str, key_id: str, secret: str):
    if not re.fullmatch(r"pay_[A-Za-z0-9]+", payment_id):
        return None
    basic = base64.b64encode(f"{key_id}:{secret}".encode("utf-8")).decode("ascii")
    req = UrlRequest(f"https://api.razorpay.com/v1/payments/{payment_id}",
        headers={"Authorization": f"Basic {basic}", "Accept": "application/json", "User-Agent": "AgentDaemon/1.0"},
        method="GET")
    try:
        with urlopen(req, timeout=12) as result:
            return json.loads(result.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None


def _page_billing(request):
    gate = _require_session(request)
    if gate:
        return gate
    user_id = request.session["user_id"]
    active_until = portal_db.get_subscription_active_until(user_id)
    active = bool(active_until and active_until > _now().isoformat(timespec="seconds"))
    requests = [item for item in portal_db.admin_list_trial_requests() if item["user_id"] == user_id]
    latest = requests[0] if requests else None
    success = "<div class='pill green'>Payment verified and access activated.</div>" if request.query.get("success") == ["1"] else ""
    if active:
        info = f"<div class='alert'>Your access is active through {_escape(active_until)}.</div><p class='muted'>Your existing projects remain attached to your account.</p>"
    else:
        if latest and latest["status"] == "pending":
            trial = "<div class='alert'>Your one-day trial request is pending administrator review.</div>"
        elif latest and latest["status"] == "rejected":
            trial = "<div class='alert'>Your latest trial request was not approved. You can still choose a paid plan.</div>"
        else:
            trial = f"<form method='post' action='/billing/trial-request'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><button class='button' type='submit'>Request a free 1-day trial</button></form>"
        info = f"""{trial}
<div class='grid'>
<article class='card'><div class='eyebrow'>Monthly</div><h2>₹100 <small class='muted'>/ month</small></h2><p class='muted'>30 days of access.</p><form method='post' action='/billing/order'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><input type='hidden' name='plan' value='monthly'><button class='button primary' type='submit'>Choose monthly</button></form></article>
<article class='card'><div class='eyebrow'>Yearly</div><h2>₹1,000 <small class='muted'>/ year</small></h2><p class='muted'>365 days of access.</p><form method='post' action='/billing/order'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><input type='hidden' name='plan' value='yearly'><button class='button primary' type='submit'>Choose yearly</button></form></article>
</div><p class='muted'>Checkout requires valid Razorpay credentials configured on the server. Access is activated only after payment is verified server-side.</p>"""
    body = f"<section class='section'><div class='eyebrow'>Account access</div><h1>{'Your subscription' if active else 'Choose your access'}</h1>{success}{info}</section>"
    return _response(body, request)

def _page_create_order(request):
    gate = _require_session(request)
    if gate:
        return gate
    if request.method != "POST":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    if not _csrf_valid(request):
        return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
    plan = str(request.form.get("plan", "yearly"))
    if plan not in ("monthly", "yearly"):
        return _response("<div class='alert'>Choose a valid subscription plan.</div>", request, "400 Bad Request")
    try:
        key_id, secret, amount = _razorpay_settings(plan)
    except RuntimeError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div>", request, "503 Service Unavailable")
    user_id = request.session["user_id"]
    payload = json.dumps({"amount": amount, "currency": "INR",
                          "receipt": "ad-" + user_id.replace("-", "")[:32],
                          "notes": {"user_id": user_id}}).encode("utf-8")
    basic = base64.b64encode(f"{key_id}:{secret}".encode("utf-8")).decode("ascii")
    api_request = UrlRequest("https://api.razorpay.com/v1/orders", data=payload,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json", "User-Agent": "AgentDaemon/1.0"}, method="POST")
    try:
        with urlopen(api_request, timeout=12) as result:
            order = json.loads(result.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return _response("<div class='alert'>Razorpay could not create a test order. Check the test keys and retry.</div>", request, "502 Bad Gateway")
    order_id = str(order.get("id", ""))
    if not re.fullmatch(r"order_[A-Za-z0-9]+", order_id) or order.get("amount") != amount:
        return _response("<div class='alert'>Razorpay returned an invalid order. No payment was started.</div>", request, "502 Bad Gateway")
    portal_db.create_payment_order(user_id, order_id, amount, plan)
    csrf = json.dumps(_csrf(request)).replace("</", "<\\/")
    key = json.dumps(key_id)
    order_value = json.dumps(order_id)
    nonce = secrets.token_urlsafe(18)
    body = f"""<section class='card form-card'><h1>Complete test payment</h1><p class='muted'>Razorpay test checkout will open. No live charge is possible in this build.</p><button class='button primary' id='pay' type='button'>Open secure checkout</button><p id='result' class='muted'></p></section>
<script src='https://checkout.razorpay.com/v1/checkout.js'></script><script nonce='{nonce}'>
const options={{key:{key},amount:{amount},currency:'INR',name:'Agent Daemon',description:{json.dumps(plan)},order_id:{order_value},handler:async function(r){{const response=await fetch('/billing/verify',{{method:'POST',headers:{{'Content-Type':'application/json'}},credentials:'same-origin',body:JSON.stringify({{csrf:{csrf},order_id:r.razorpay_order_id,payment_id:r.razorpay_payment_id,signature:r.razorpay_signature}})}});const data=await response.json();if(response.ok)location.href='/billing?success=1';else document.getElementById('result').textContent=data.error||'Payment verification failed.';}},modal:{{ondismiss:function(){{document.getElementById('result').textContent='Checkout closed. No subscription was activated.';}}}}}};
document.getElementById('pay').addEventListener('click',()=>new Razorpay(options).open());
</script>"""
    headers = [("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"),
        ("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "same-origin"),
        ("Content-Security-Policy", f"default-src 'self'; script-src 'self' https://checkout.razorpay.com 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://*.razorpay.com; frame-src https://checkout.razorpay.com https://api.razorpay.com; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")]
    return Response(_layout("Checkout", body, request), "200 OK", headers)


def _page_verify_payment(request):
    if request.method != "POST" or not request.session:
        return Response(json.dumps({"error": "Sign in is required."}), "401 Unauthorized", [("Content-Type", "application/json")])
    if not _csrf_valid(request):
        return Response(json.dumps({"error": "Request expired; reload checkout."}), "403 Forbidden", [("Content-Type", "application/json")])
    order_id = str(request.form.get("order_id", ""))
    payment_id = str(request.form.get("payment_id", ""))
    signature = str(request.form.get("signature", ""))
    try:
        key_id, secret, _ = _razorpay_settings()
    except RuntimeError:
        return Response(json.dumps({"error": "Test checkout is unavailable."}), "503 Service Unavailable", [("Content-Type", "application/json")])
    expected = hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    if not re.fullmatch(r"order_[A-Za-z0-9]+", order_id) or not re.fullmatch(r"pay_[A-Za-z0-9]+", payment_id) or not hmac.compare_digest(signature, expected):
        return Response(json.dumps({"error": "Payment signature could not be verified."}), "400 Bad Request", [("Content-Type", "application/json")])
    conn = portal_db.get_connection()
    try:
        order = portal_db._execute(conn, "SELECT amount FROM payment_orders WHERE razorpay_order_id=? AND user_id=?",
                                   (order_id,request.session["user_id"])).fetchone()
    finally:
        conn.close()
    if not order:
        return Response(json.dumps({"error": "The order is invalid for this account."}), "404 Not Found", [("Content-Type", "application/json")])
    payment = _fetch_razorpay_payment(payment_id, key_id, secret)
    if not payment or payment.get("status") != "captured" or payment.get("order_id") != order_id or int(payment.get("amount", 0)) != int(order["amount"]) or payment.get("currency") != "INR":
        return Response(json.dumps({"error": "Payment is not captured yet. Wait for confirmation and retry."}), "409 Conflict", [("Content-Type", "application/json")])
    activated = portal_db.complete_payment_order(order_id, payment_id, int(payment["amount"]))
    if not activated:
        return Response(json.dumps({"error": "This payment was already processed or the order is invalid."}), "409 Conflict", [("Content-Type", "application/json")])
    return Response(json.dumps({"status": "active"}), "200 OK", [("Content-Type", "application/json"), ("Cache-Control", "no-store")])


def _json_response(payload: dict, status="200 OK"):
    return Response(json.dumps(payload, separators=(",", ":")), status,
                    [("Content-Type", "application/json; charset=utf-8"),
                     ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")])


def _incident_signature(message: str, traceback: str, payload: dict) -> str:
    frames = re.findall(r'File "([^"\n]+)", line (\d+)', traceback)
    app_frames = [(path, line) for path, line in frames if "site-packages" not in path.replace("\\", "/")]
    error_type = str(payload.get("exception_type", "")).strip() or message.split(":", 1)[0].strip() or "Error"
    if app_frames:
        path, line = app_frames[-1]
        return f"{error_type}:{PurePosixPath(path.replace('\\', '/')).name}:{line}"[:250]
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:16]
    return f"{error_type}:unknown:{digest}"


def _authorized_ingest_project(request: Request):
    raw_key = request.environ.get("HTTP_X_INGEST_KEY", "").strip()
    if len(raw_key) < 24 or len(raw_key) > 256:
        return None
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return portal_db.get_project_by_ingest_hash(key_hash)


def _page_ingest(request):
    if request.method != "POST" or not request.raw_body:
        return _json_response({"error": "POST a JSON error event."}, "400 Bad Request")
    if request.environ.get("CONTENT_TYPE", "").split(";", 1)[0].lower() != "application/json":
        return _json_response({"error": "Content-Type must be application/json."}, "415 Unsupported Media Type")
    project = _authorized_ingest_project(request)
    if not project:
        return _json_response({"error": "Invalid ingest key."}, "401 Unauthorized")
    if project["paused"] or not portal_db.user_has_active_access(project["user_id"]):
        return _json_response({"accepted": False, "reason": "access_not_active"}, "202 Accepted")
    if not portal_db.allow_ingest(project["id"]):
        return _json_response({"error": "Ingest rate limit exceeded."}, "429 Too Many Requests")
    data = request.form
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return _json_response({"error": "message is required."}, "400 Bad Request")
    message = message.strip()[:10000]
    traceback = data.get("traceback", "")
    if not isinstance(traceback, str):
        traceback = ""
    traceback = traceback[:30000]
    level = str(data.get("level", "ERROR")).upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        return _json_response({"error": "level must be DEBUG, INFO, WARNING, ERROR, or CRITICAL."}, "400 Bad Request")
    timestamp = str(data.get("timestamp") or data.get("ts") or "")
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed_timestamp.tzinfo is None:
            parsed_timestamp = parsed_timestamp.replace(tzinfo=timezone.utc)
        timestamp = parsed_timestamp.astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        timestamp = _now().isoformat(timespec="seconds")
    signature = _incident_signature(message, traceback, data)
    incident_id, inserted = portal_db.ingest_event(project["id"], timestamp=timestamp,
        level=level, message=message, traceback=traceback, signature=signature)
    return _json_response({"accepted": inserted, "duplicate": not inserted,
                           "incident_id": incident_id}, "202 Accepted" if inserted else "200 OK")


def _page_heartbeat(request):
    if request.method != "POST":
        return _json_response({"error": "POST required."}, "405 Method Not Allowed")
    project = _authorized_ingest_project(request)
    if not project:
        return _json_response({"error": "Invalid ingest key."}, "401 Unauthorized")
    if project["paused"] or not portal_db.user_has_active_access(project["user_id"]):
        return _json_response({"status": "access_not_active"}, "403 Forbidden")
    if not portal_db.allow_ingest(project["id"], maximum=60):
        return _json_response({"error": "Heartbeat rate limit exceeded."}, "429 Too Many Requests")
    portal_db.set_project_connected(project["id"])
    return _json_response({"status": "connected"})


def _razorpay_webhook(request):
    if request.method != "POST":
        return Response(b"method not allowed", "405 Method Not Allowed", [("Content-Type", "text/plain")])
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    provided = request.environ.get("HTTP_X_RAZORPAY_SIGNATURE", "")
    if not secret or not provided:
        return Response(b"not configured", "503 Service Unavailable", [("Content-Type", "text/plain")])
    expected = hmac.new(secret.encode(), request.raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(provided, expected):
        return Response(b"invalid signature", "401 Unauthorized", [("Content-Type", "text/plain")])
    try:
        event = json.loads(request.raw_body.decode("utf-8"))
        payment = event["payload"]["payment"]["entity"]
        if event.get("event") == "payment.captured" and payment.get("status") == "captured" and payment.get("currency") == "INR":
            # Payments are reviewed by the administrator before account access is granted.
            pass
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return Response(b"invalid event", "400 Bad Request", [("Content-Type", "text/plain")])
    return Response(b"ok", "200 OK", [("Content-Type", "text/plain"), ("Cache-Control", "no-store")])


def _page_logout(request):
    if request.method != "POST":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    if not request.session or not _csrf_valid(request):
        return _response("<div class='alert'>Sign-in expired. Please sign in again.</div>", request, "403 Forbidden")
    portal_db.delete_session(request.session["id"])
    return _redirect("/", [_cookie(SESSION_COOKIE, "", max_age=0), _cookie(CSRF_COOKIE, "", max_age=0, http_only=False)])


def _dispatch(request: Request) -> Response:
    if request.method == "GET" and request.path == "/":
        return _page_home(request)
    if request.path == "/auth/google":
        if request.method != "GET":
            return _response("Method not allowed", request, "405 Method Not Allowed")
        return _google_begin(request)
    if request.path == GOOGLE_CALLBACK_PATH:
        return _google_callback(request)
    if request.path in ("/signup", "/login") and request.method in ("GET", "POST"):
        return _page_signup(request) if request.path == "/signup" else _page_login(request)
    if request.path == "/logout":
        return _page_logout(request)
    if request.path == "/admin":
        return _page_admin(request)
    if request.path == "/dashboard":
        return _page_dashboard(request)
    if request.path == "/billing":
        return _page_billing(request)
    if request.path == "/billing/trial-request":
        return _page_trial_request(request)
    if request.path == "/billing/order":
        return _page_create_order(request)
    if request.path == "/billing/verify":
        return _page_verify_payment(request)
    if request.path == "/webhooks/razorpay":
        return _razorpay_webhook(request)
    if request.path == "/ingest":
        return _page_ingest(request)
    if request.path == "/heartbeat":
        return _page_heartbeat(request)
    if request.path == "/projects/new":
        return _page_new_project(request)
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})/github-token", request.path)
    if match:
        return _page_update_github_token(request, match.group(1))
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})/rotate-key", request.path)
    if match:
        return _page_rotate_ingest_key(request, match.group(1))
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})/install", request.path)
    if match:
        return _page_install_monitoring(request, match.group(1))
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})/delete", request.path)
    if match:
        return _page_delete_project(request, match.group(1))
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})", request.path)
    if match:
        return _page_project(request, match.group(1))
    match = re.fullmatch(r"/projects/([0-9a-f-]{36})/incidents/([0-9a-f-]{36})", request.path)
    if match:
        return _page_incident(request, *match.groups())
    if request.path == "/health":
        return Response(b"ok", "200 OK", [("Content-Type", "text/plain; charset=utf-8")])
    return _response("<h1>Page not found</h1><p class='muted'>That route does not exist.</p>", request, "404 Not Found")


def application(environ, start_response):
    try:
        request = Request(environ)
        if request.method == "POST" and request.path not in ("/login", "/signup", "/webhooks/razorpay", "/ingest", "/heartbeat") and not request.session:
            response = _redirect("/login")
        else:
            response = _dispatch(request)
    except ValueError as exc:
        response = Response(_escape(exc), "400 Bad Request", [("Content-Type", "text/plain; charset=utf-8")])
    except RuntimeError as exc:
        response = Response(_escape(exc), "503 Service Unavailable", [("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")])
    if os.getenv("APP_ENV", "development").lower() == "production":
        response.headers.extend([
            ("Strict-Transport-Security", "max-age=31536000; includeSubDomains"),
            ("X-Frame-Options", "DENY"),
            ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
        ])
    start_response(response.status, response.headers)
    return [response.body]


def main():
    portal_db.init_db()
    # Validate startup configuration before accepting traffic.
    _secret()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    with make_server(host, port, application, server_class=ThreadingWSGIServer) as server:
        print(f"{APP_NAME} web app listening on http://{host}:{port}")
        server.serve_forever()


if __name__ == "__main__":
    main()

