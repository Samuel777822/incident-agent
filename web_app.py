"""Small, server-rendered web application for Agent Daemon.

This deliberately uses Python's standard-library WSGI server and HTML
templates. It is a development entry point; production should run behind an
HTTPS reverse proxy and set the secrets documented in README.md.
"""

from __future__ import annotations

import base64
import hashlib
import logging
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
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen
from wsgiref.simple_server import WSGIServer, make_server

import httpx
from urllib.parse import urlencode

import notifications
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


CSS += """
.statgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0 8px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
.stat b{display:block;font-size:28px;line-height:1.1}.stat span{color:var(--muted);font-size:13px}
.pill.red{background:#3a1820;color:#ff9aa8;border-color:#6a2b38}
.ok{color:var(--green)}.bad{color:#ff9aa8}
.qr{background:#fff;border-radius:14px;padding:14px;text-align:center;margin:18px 0}
.qr img{display:block;margin:auto;max-width:100%;height:auto}.qr p{color:#222;margin:8px 0 0}
.section h2{margin-top:32px}
.inline{display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap}
select{background:#0d1426;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:9px}
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
    if signed_in:
        signout = ('<form method="post" action="/logout" style="display:inline">'
                   f'<input type="hidden" name="csrf" value="{_csrf(request)}"><button class="button" type="submit">Sign out</button></form>')
        if _is_admin(request):
            links = '<a href="/admin">Admin</a>' + signout
        else:
            links = '<a href="/dashboard">Projects</a><a href="/billing">Plan &amp; billing</a>' + signout
    else:
        links = '<a href="/login">Sign in</a><a class="button" href="/signup">Create account</a>'
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
                ("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")]
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


PLANS = {
    "monthly": {"label": "Monthly", "rupees": 100, "days": 30},
    "yearly": {"label": "Yearly", "rupees": 1000, "days": 365},
}

_INCIDENT_LABELS = {
    "diagnosing": "Diagnosing", "queued": "Diagnosing", "processing": "Diagnosing",
    "diagnosed": "Diagnosed · report ready", "pr_opened": "Fix PR opened · review it",
    "needs_human": "Needs human review", "resolved": "Resolved",
}


def _base_url() -> str:
    return os.getenv("PORTAL_BASE_URL", "https://incident-agent-portal.onrender.com").strip().rstrip("/")


def _parse_iso(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _fmt_time(value) -> str:
    parsed = _parse_iso(value)
    return parsed.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC") if parsed else "never"


def _ago(value) -> str:
    parsed = _parse_iso(value)
    if not parsed:
        return "never"
    seconds = int((_now() - parsed).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def _remaining(value) -> str:
    parsed = _parse_iso(value)
    if not parsed:
        return ""
    seconds = int((parsed - _now()).total_seconds())
    if seconds <= 0:
        return "ended"
    if seconds < 3600:
        return f"{max(1, seconds // 60)} min left"
    if seconds < 86400:
        return f"{seconds // 3600} h left"
    return f"{seconds // 86400} days left"


def _pill(text, css="") -> str:
    return f"<span class='pill {css}'>{_escape(text)}</span>"


def _table(headers, rows, empty="Nothing here yet.") -> str:
    if not rows:
        return f"<div class='empty'>{_escape(empty)}</div>"
    head = "".join(f"<th>{_escape(item)}</th>" for item in headers)
    return f"<div class='table-wrap'><table class='table'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _incident_label(status: str) -> str:
    return _INCIDENT_LABELS.get(status, str(status).replace("_", " ").title())


def _access_state(user_id: str) -> dict:
    until = portal_db.get_subscription_active_until(user_id) or ""
    active = bool(until and until > _now().isoformat(timespec="seconds"))
    kind = ""
    if until:
        conn = portal_db.get_connection()
        try:
            row = portal_db._execute(conn, "SELECT grant_type FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
        finally:
            conn.close()
        kind = row["grant_type"] if row else ""
    return {"active": active, "until": until, "kind": kind,
            "remaining": _remaining(until) if active else "",
            "trial": portal_db.user_trial_status(user_id)}


def _project_state(project: dict, has_access=None):
    if has_access is None:
        until = project.get("active_until") or ""
        has_access = bool(until and until > _now().isoformat(timespec="seconds"))
    if not has_access:
        return "Access ended", "amber"
    if project.get("paused"):
        return "Paused", "amber"
    status = project.get("status", "")
    beat = _parse_iso(project.get("last_heartbeat_at") or "")
    if status == "connected":
        if beat is None:
            return "Connected", "green"
        if (_now() - beat).total_seconds() <= 900:
            return "Live", "green"
        return "No recent check-in", "amber"
    if status == "install_pr_open":
        return "Waiting for monitoring to deploy", "amber"
    return "Setup needed", "amber"


def _razorpay_keys():
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id.startswith(("rzp_test_", "rzp_live_")) or not secret:
        raise RuntimeError("Online payments are not configured yet.")
    return key_id, secret


def _gateway_ready() -> bool:
    try:
        _razorpay_keys()
        return True
    except RuntimeError:
        return False


def _razorpay_settings(plan: str = "yearly"):
    if plan not in PLANS:
        raise RuntimeError("Unknown subscription plan")
    key_id, secret = _razorpay_keys()
    raw = os.getenv(f"RAZORPAY_{plan.upper()}_AMOUNT_PAISE", "").strip()
    amount = int(raw) if raw.isdigit() else PLANS[plan]["rupees"] * 100
    if amount < 100:
        raise RuntimeError("Subscription amount must be at least 100 paise")
    return key_id, secret, amount


def _upi_uri(plan: str) -> str:
    vpa = os.getenv("UPI_ID", "7975291636@ptsbi").strip()
    name = os.getenv("UPI_PAYEE_NAME", "Pranav V Rao").strip()
    amount = PLANS[plan]["rupees"]
    parts = {"pa": vpa, "pn": name, "am": f"{amount:.2f}", "cu": "INR", "tn": f"Agent Daemon {plan}"}
    return "upi://pay?" + "&".join(f"{key}={quote(value, safe='@')}" for key, value in parts.items())


def _qr_data_uri(text: str) -> str:
    try:
        import segno
        return segno.make(text, error="m").svg_data_uri(scale=6, border=2, dark="#0b1020", light="#ffffff")
    except Exception:
        # Never fail silently: a missing 'segno' package would otherwise just hide the QR code.
        logging.getLogger(__name__).exception("Could not generate a QR code (is 'segno' installed? pip install -r requirements.txt)")
        return ""


def _after_payment(order_id: str, payment_id: str) -> None:
    order = portal_db.get_payment_order(order_id)
    if not order:
        return
    email = portal_db.get_user_email(order["user_id"])
    plan = PLANS.get(order["plan"], PLANS["yearly"])
    if email:
        notifications.notify_customer(
            email, "Payment received - your Agent Daemon access is active",
            f"Thanks! We received your payment of INR {plan['rupees']} for the {plan['label'].lower()} plan.\n"
            f"Your access is active now: {_base_url()}/dashboard", "payment_customer")
    notifications.notify_admins(
        f"New paid subscription: {email or order['user_id']}",
        f"{email} paid INR {plan['rupees']} ({plan['label'].lower()}). Access was activated automatically.\n"
        f"{_base_url()}/admin", "payment_admin")


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


_ADMIN_MESSAGES = {
    "trial_approved": ("green", "Trial approved. The customer has access for 1 day, starting now."),
    "trial_rejected": ("amber", "Trial request rejected."),
    "payment_confirmed": ("green", "Payment confirmed. The customer's paid access is active now."),
    "payment_rejected": ("amber", "Payment rejected."),
    "access_granted": ("green", "Access granted."),
    "access_revoked": ("amber", "Access revoked. The customer's projects are paused until access is granted again."),
    "already_done": ("amber", "That request was already handled by someone else. The list below is up to date."),
    "not_found": ("red", "That customer no longer exists."),
    "bad_request": ("red", "That action was not valid."),
    "test_email_ok": ("green", "Test email accepted by the provider for every admin. Check both inboxes."),
    "test_email_failed": ("red", "Test email failed. See the Email status table below for the exact reason."),
}


def _page_admin(request):
    if not request.session:
        return _redirect("/login")
    if not _is_admin(request):
        return _response("<h1>Not found</h1>", request, "404 Not Found")
    if request.method == "POST":
        if not _csrf_valid(request):
            return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
        return _admin_action(request)
    return _admin_view(request)


def _admin_action(request):
    form = request.form
    actor = request.session["email"]
    action = form.get("action", "")
    done = lambda key: _redirect("/admin?msg=" + key)
    if action == "approve_trial":
        trial = portal_db.approve_trial_request(form.get("request_id", ""), actor)
        if not trial:
            return done("already_done")
        notifications.notify_customer(
            trial["email"], "Your Agent Daemon trial is approved",
            f"Your 1-day free trial is active until {_fmt_time(trial['active_until'])}.\nConnect your project: {_base_url()}/dashboard",
            "trial_approved")
        return done("trial_approved")
    if action == "reject_trial":
        trial = portal_db.admin_review_trial_request(form.get("request_id", ""), "rejected", actor)
        if not trial:
            return done("already_done")
        notifications.notify_customer(trial["email"], "Update on your Agent Daemon trial request",
                                      "Your trial request was not approved this time. You can pick a plan any time: "
                                      f"{_base_url()}/billing", "trial_rejected")
        return done("trial_rejected")
    if action == "confirm_payment":
        try:
            payment = portal_db.approve_manual_payment(form.get("payment_id", ""), actor)
        except ValueError:
            return done("bad_request")
        if not payment:
            return done("already_done")
        notifications.notify_customer(
            payment["email"], "Agent Daemon payment confirmed",
            f"We confirmed your payment. Your paid access is active until {_fmt_time(payment['active_until'])}.\n{_base_url()}/dashboard",
            "payment_confirmed")
        return done("payment_confirmed")
    if action == "reject_payment":
        payment = portal_db.admin_review_manual_payment(form.get("payment_id", ""), "rejected", actor)
        if not payment:
            return done("already_done")
        notifications.notify_customer(
            payment["email"], "Agent Daemon payment could not be confirmed",
            "We could not find your payment, so access was not activated. If you did pay, reply to this email with a screenshot "
            "of the successful UPI receipt.", "payment_rejected")
        return done("payment_rejected")
    if action in ("grant", "revoke"):
        user_id = form.get("user_id", "")
        email = portal_db.get_user_email(user_id)
        if not email:
            return done("not_found")
        if action == "revoke":
            portal_db.admin_revoke_access(user_id)
            return done("access_revoked")
        kind, _, days = form.get("grant", "").partition(":")
        if kind not in ("trial", "paid") or not days.isdigit() or not 1 <= int(days) <= 3650:
            return done("bad_request")
        until = portal_db.admin_grant_access(user_id, int(days), kind, actor)
        notifications.notify_customer(email, "Your Agent Daemon access is active",
                                      f"Access is active until {_fmt_time(until)}.\n{_base_url()}/dashboard", "access_granted")
        return done("access_granted")
    if action == "send_test_email":
        results = notifications.send_test_to_admins()
        return done("test_email_ok" if results and all(ok for _, ok, _ in results) else "test_email_failed")
    return done("bad_request")


def _admin_view(request):
    csrf = _escape(_csrf(request))
    admins = _admin_emails()
    stats = portal_db.admin_stats(admins)
    trials = portal_db.admin_list_trial_requests()
    payments = portal_db.admin_list_manual_payments()
    users = [u for u in portal_db.admin_list_users() if u["email"].lower() not in admins]
    projects = portal_db.admin_projects()
    now = _now().isoformat(timespec="seconds")
    states = [_project_state(p) for p in projects]
    live = sum(1 for state, _ in states if state in ("Live", "Connected"))
    flash = ""
    message = _ADMIN_MESSAGES.get(request.query.get("msg", [""])[0])
    if message:
        flash = f"<div class='{'pill ' if message[0] != 'red' else 'alert '}{message[0]}'>{_escape(message[1])}</div>"

    def card(value, label):
        return f"<div class='stat'><b>{_escape(value)}</b><span>{_escape(label)}</span></div>"
    cards = "".join([
        card(stats["customers"], "customers"),
        card(f"{stats['active']}", f"active ({stats['paid_active']} paid, {stats['trial_active']} trial)"),
        card(stats["inactive"], "without access"),
        card(stats["pending_trials"], "trial requests to review"),
        card(stats["pending_payments"], "UPI payments to confirm"),
        card(f"{live}/{stats['projects']}", "apps live / connected"),
        card(stats["open_incidents"], f"open incidents ({stats['needs_human']} need a human)"),
    ])

    pending_trials = [t for t in trials if t["status"] == "pending"]
    trial_rows = [f"<tr><td>{_escape(t['email'])}</td><td>{_escape(_fmt_time(t['requested_at']))}</td><td>"
                  f"<form method='post' action='/admin' class='actions'><input type='hidden' name='csrf' value='{csrf}'>"
                  f"<input type='hidden' name='request_id' value='{_escape(t['id'])}'>"
                  "<button class='button primary' name='action' value='approve_trial' type='submit'>Approve 1-day trial</button>"
                  "<button class='button danger' name='action' value='reject_trial' type='submit'>Reject</button></form></td></tr>"
                  for t in pending_trials]
    pending_payments = [p for p in payments if p["status"] == "pending"]
    payment_rows = [f"<tr><td>{_escape(p['email'])}</td><td>₹{_escape(p['amount'])} · {_escape(p['plan'])}</td>"
                    f"<td><code>{_escape(p['transaction_ref'])}</code><br><small class='muted'>{_escape(_fmt_time(p['created_at']))}</small></td><td>"
                    f"<form method='post' action='/admin' class='actions'><input type='hidden' name='csrf' value='{csrf}'>"
                    f"<input type='hidden' name='payment_id' value='{_escape(p['id'])}'>"
                    f"<button class='button primary' name='action' value='confirm_payment' type='submit'>I received ₹{_escape(p['amount'])} · grant {30 if p['plan'] == 'monthly' else 365} days</button>"
                    "<button class='button danger' name='action' value='reject_payment' type='submit'>Not received</button></form></td></tr>"
                    for p in pending_payments]
    attention = ""
    if trial_rows:
        attention += "<h2>Trial requests</h2>" + _table(["Customer", "Requested", "Decision"], trial_rows)
    if payment_rows:
        attention += ("<h2>UPI payments to confirm</h2><p class='muted'>Open your Paytm app, find this exact reference and amount, "
                      "then confirm. Confirm only money you can see.</p>" + _table(["Customer", "Claimed", "Reference", "Decision"], payment_rows))
    if not attention:
        attention = "<h2>Needs your attention</h2><div class='empty'>Nothing waiting. New trial requests and UPI payments show up here.</div>"

    pending_trial_users = {t["user_id"] for t in pending_trials}
    pending_payment_users = {p["user_id"] for p in pending_payments}
    users.sort(key=lambda u: (0 if (u['id'] in pending_trial_users or u['id'] in pending_payment_users) else 1 if (u.get('active_until') or '') > now else 2))
    customer_rows = []
    for user in users:
        until = user.get("active_until") or ""
        active = bool(until and until > now)
        if active:
            kind = "Paid" if user.get("grant_type") == "paid" else "Trial"
            status = _pill(f"{kind} · {_remaining(until)}", "green") + f"<br><small class='muted'>until {_escape(_fmt_time(until))}</small>"
            action = (f"<form method='post' action='/admin'><input type='hidden' name='csrf' value='{csrf}'>"
                      f"<input type='hidden' name='user_id' value='{_escape(user['id'])}'>"
                      "<button class='button danger' name='action' value='revoke' type='submit'>Revoke access</button></form>")
        else:
            if user["id"] in pending_trial_users:
                status = _pill("Trial requested", "amber")
            elif user["id"] in pending_payment_users:
                status = _pill("Payment to confirm", "amber")
            elif until:
                status = _pill("Expired", "red") + f"<br><small class='muted'>{_escape(_fmt_time(until))}</small>"
            else:
                status = _pill("No access")
            action = (f"<form method='post' action='/admin' class='inline'><input type='hidden' name='csrf' value='{csrf}'>"
                      f"<input type='hidden' name='user_id' value='{_escape(user['id'])}'>"
                      "<select name='grant' aria-label='Access to grant'><option value='trial:1'>Free trial · 1 day</option>"
                      "<option value='paid:30'>Paid · 30 days</option><option value='paid:365'>Paid · 365 days</option></select>"
                      "<button class='button primary' name='action' value='grant' type='submit'>Grant access</button></form>")
        customer_rows.append(f"<tr><td>{_escape(user['email'])}<br><small class='muted'>Joined {_escape(_fmt_time(user['created_at']))}</small></td><td>{status}</td><td>{action}</td></tr>")

    project_rows = []
    for project, (state, css) in zip(projects, states):
        project_rows.append(f"<tr><td>{_escape(project['name'])}<br><small class='muted'>{_escape(project['repo_owner'])}/{_escape(project['repo_name'])}</small></td>"
                            f"<td>{_escape(project['owner_email'])}</td><td>{_pill(state, css)}</td>"
                            f"<td>{_escape(_ago(project.get('last_heartbeat_at')))}</td><td>{_escape(project['open_incidents'])}</td></tr>")
    incident_rows = []
    for item in portal_db.admin_recent_incidents(10):
        pr = f"<a href='{_escape(item['pr_url'])}' target='_blank' rel='noopener'>PR · CI {_escape(item['ci_status'])}</a>" if item.get("pr_url") else ""
        incident_rows.append(f"<tr><td>{_escape(_ago(item['last_seen']))}</td><td>{_escape(item['project_name'])}<br><small class='muted'>{_escape(item['owner_email'])}</small></td>"
                             f"<td>{_escape(item['signature'])}</td><td>{_escape(_incident_label(item['status']))}</td><td>{pr}</td></tr>")

    worker_seen = portal_db.worker_last_seen()
    worker_ok = bool(worker_seen and (_now() - _parse_iso(worker_seen)).total_seconds() < 180)
    worker = (_pill(f"Worker running · seen {_ago(worker_seen)}", "green") if worker_ok else
              _pill(f"Worker not seen recently ({_ago(worker_seen)})", "amber"))
    provider = notifications.provider()
    email_state = (_pill(f"Email: {provider}, from {notifications.sender()}", "green") if notifications.configured() else
                   _pill("Email not configured. Set BREVO_API_KEY and EMAIL_FROM in Render", "red"))
    payments_state = _pill("Instant payments on (Razorpay)", "green") if _gateway_ready() else _pill("Instant payments off: manual UPI confirmation", "amber")
    notif_rows = []
    for item in portal_db.recent_notifications(10):
        result = _pill("accepted", "green") if item["ok"] else _pill("failed", "red")
        notif_rows.append(f"<tr><td>{_escape(_ago(item['created_at']))}</td><td>{_escape(item['recipient'])}</td><td>{_escape(item['kind'])}</td>"
                          f"<td>{result}<br><small class='muted'>{_escape(item['detail'])}</small></td></tr>")
    system = (f"<h2>System</h2><div class='stats'>{worker}{email_state}{payments_state}{_pill('Database: ' + portal_db.database_kind())}</div>"
              f"<form method='post' action='/admin' style='margin-top:12px'><input type='hidden' name='csrf' value='{csrf}'>"
              "<button class='button' name='action' value='send_test_email' type='submit'>Send test email to both admins</button></form>"
              "<h3>Email status</h3><p class='muted'>Accepted means the email provider took the message. It does not guarantee inbox delivery.</p>"
              + _table(["When", "To", "Kind", "Result"], notif_rows, "No emails sent yet."))

    body = (f"<section class='section'><div class='eyebrow'>Administrator</div><h1>Operations</h1>"
            f"<p class='muted'>Signed in as {_escape(request.session['email'])}</p>{flash}<div class='statgrid'>{cards}</div>{attention}"
            f"<h2>Customers</h2>{_table(['Customer', 'Access', 'Action'], customer_rows, 'No customer accounts yet.')}"
            f"<h2>Applications</h2>{_table(['App', 'Owner', 'State', 'Last check-in', 'Open incidents'], project_rows, 'No applications connected yet.')}"
            f"<h2>Recent incidents and fixes</h2>{_table(['When', 'App', 'Error', 'Agent status', 'Fix'], incident_rows, 'No incidents yet.')}"
            f"{system}</section>")
    return _response(body, request)


def _page_trial_request(request):
    gate = _require_session(request)
    if gate:
        return gate
    if _is_admin(request):
        return _redirect("/admin")
    if request.method != "POST":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    if not _csrf_valid(request):
        return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
    try:
        trial = portal_db.create_trial_request(request.session["user_id"])
    except ValueError as exc:
        return _response(f"<section class='card form-card'><h1>Trial not available</h1><p>{_escape(exc)}</p><a class='button primary' href='/billing'>Choose a plan</a></section>", request, "409 Conflict")
    if trial.get("created"):
        notifications.notify_admins(
            f"New trial request: {request.session['email']}",
            f"{request.session['email']} requested a 1-day free trial.\nApprove or reject it here: {_base_url()}/admin", "trial_request")
    return _response("<section class='card form-card'><h1>Request received</h1>"
                     "<p>Your request is saved and waiting for approval. When an admin approves it your 1-day trial starts immediately; "
                     "you will see it on your dashboard and get an email.</p>"
                     "<a class='button primary' href='/billing'>Back to plan &amp; billing</a></section>", request)

def _page_dashboard(request):
    if request.method != "GET":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    gate = _require_session(request)
    if gate:
        return gate
    if _is_admin(request):
        return _redirect("/admin")
    user_id = request.session["user_id"]
    access = _access_state(user_id)
    projects = portal_db.list_projects_with_activity(user_id)
    if access["active"]:
        label = "Paid plan" if access["kind"] == "paid" else "Free trial"
        banner = (f"<article class='card'><div class='row'><div><div class='eyebrow'>Your plan</div><h3>{label}</h3>"
                  f"<p class='muted'>{_escape(access['remaining'])} · active until {_escape(_fmt_time(access['until']))}</p></div>"
                  "<a class='button' href='/billing'>Plan &amp; billing</a></div></article>")
    else:
        if access["trial"] == "pending":
            message, cta = "Your trial request is waiting for approval. Your projects stay paused until then.", "See request status"
        elif access["until"]:
            message, cta = "Your access has ended, so monitoring is paused. Choose a plan to switch it back on.", "Choose a plan"
        else:
            message, cta = "You do not have access yet. Request a free 1-day trial or pick a plan to start monitoring.", "Get access"
        banner = (f"<article class='card'><div class='row'><div><div class='eyebrow'>Access needed</div><h3>Monitoring is off</h3>"
                  f"<p class='muted'>{_escape(message)}</p></div><a class='button primary' href='/billing'>{cta}</a></div></article>")
    cards = []
    for project in projects:
        state, css = _project_state(project, access["active"])
        latest = project.get("latest_incident")
        if latest:
            pr = (f" · <a href='{_escape(latest['pr_url'])}' target='_blank' rel='noopener'>PR</a>" if latest.get("pr_url") else "")
            activity = (f"<p class='muted'>Latest: <a href='/projects/{_escape(project['id'])}/incidents/{_escape(latest['id'])}'>{_escape(latest['signature'])}</a>"
                        f" · {_escape(_incident_label(latest['status']))}{pr}</p>")
        else:
            activity = "<p class='muted'>No incidents yet. The agent is watching for errors.</p>" if css == "green" else ""
        hint = ""
        if state == "Setup needed":
            hint = "<p class='muted'>Open the project to finish setup.</p>"
        elif state == "Waiting for monitoring to deploy":
            hint = "<p class='muted'>Monitoring was added to your repository. It starts when your app redeploys.</p>"
        cards.append(f"<a class='card' href='/projects/{_escape(project['id'])}'><div class='row'><h3>{_escape(project['name'])}</h3>{_pill(state, css)}</div>"
                     f"<p class='muted'>{_escape(project['repo_owner'])}/{_escape(project['repo_name'])} · {_escape(project['branch'])} · {_escape(project['mode'])} mode</p>"
                     f"<p class='muted'>Last check-in: {_escape(_ago(project.get('last_heartbeat_at')))} · Open incidents: {project['incident_open']} of {project['incident_total']}</p>"
                     f"{activity}{hint}</a>")
    listing = "".join(cards) or "<div class='empty'>No projects yet. Connect a Python app to start monitoring it.</div>"
    connect = "<a class='button primary' href='/projects/new'>Connect a project</a>" if access["active"] else ""
    feed_rows = []
    for item in portal_db.recent_activity(user_id, 8):
        pr = f"<a href='{_escape(item['pr_url'])}' target='_blank' rel='noopener'>Open PR</a>" if item.get("pr_url") else ""
        feed_rows.append(f"<tr><td>{_escape(_ago(item['last_seen']))}</td><td>{_escape(item['project_name'])}</td>"
                         f"<td><a href='/projects/{_escape(item['project_id'])}/incidents/{_escape(item['id'])}'>{_escape(item['signature'])}</a></td>"
                         f"<td>{_escape(_incident_label(item['status']))}</td><td>{pr}</td></tr>")
    feed = _table(["When", "Project", "Error", "What the agent did", "Fix"], feed_rows,
                  "Nothing to report yet. When your app raises an error, the agent's diagnosis and fix appear here.")
    body = (f"<section class='section'><div class='row'><div><div class='eyebrow'>Workspace</div><h1>Your projects</h1>"
            f"<p class='muted'>Signed in as {_escape(request.session['email'])}</p></div>{connect}</div>{banner}"
            f"<div class='grid'>{listing}</div><h2>Agent activity</h2>{feed}</section>")
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
        repo_info = validate_repository_access(owner=owner, repo=repo.removesuffix(".git"), token=token)
    except GitHubInstallError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div>", request, "400 Bad Request")
    ingest_key = secrets.token_urlsafe(32)
    ingest_hash = hashlib.sha256(ingest_key.encode()).hexdigest()
    project_id = portal_db.create_project(request.session["user_id"], name=name,
        repo_owner=owner, repo_name=repo.removesuffix(".git"), branch=branch, mode=mode,
        token_ciphertext=ciphertext, ingest_key_hash=ingest_hash,
        app_url=request.form.get("app_url", "").strip(), ai_consent_at=portal_db._now(),
        ingest_key_ciphertext=_encrypt_token(ingest_key))
    portal_db.audit(project_id, "project_connected", {"repo": f"{owner}/{repo}", "mode": mode})
    portal_db.audit(project_id, "ai_diagnosis_consent", {"scope": "selected logs, tracebacks, and repository source sent to Groq"})
    if mode in ("pr", "auto"):
        portal_db.audit(project_id, "remediation_consent", {"mode": mode, "auto_merge_requires_passing_github_checks": mode == "auto"})
    project = {"repo_owner": owner, "repo_name": repo.removesuffix(".git"), "branch": branch}
    result = _install_monitoring(project_id, request.session["user_id"], project, token, ingest_key, bool(repo_info.get("private")))
    key_for_env = "" if (result.get("ok") and result.get("embedded_key")) else ingest_key
    summary = _install_summary(result, key_for_env, project_id)
    return _response(f"<section class='card'><h1>Project saved</h1><p class='muted'>{_escape(name)} is connected. The agent starts watching as soon as monitoring is live.</p></section>{summary}"
                     f"<p><a class='button primary' href='/projects/{_escape(project_id)}'>View project</a></p>", request, "201 Created")


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
    install_card = (f"<article class='card'><h3>Monitoring pull request</h3><p class='muted'>Monitoring was added through this pull request. If it is not merged yet, merge it to switch monitoring on.</p><a class='button primary' href='{_escape(project['install_pr_url'])}'>View installation PR</a></article>" if project.get("install_pr_url") else f"<article class='card'><h3>Install monitoring</h3><p class='muted'>Adds monitoring to your repository through a pull request and merges it automatically when it can.</p><form method='post' action='/projects/{_escape(project_id)}/install'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><button class='button primary' type='submit'>Install monitoring</button></form></article>")
    body = f"<section class='section'><p><a href='/dashboard'>← Projects</a></p><div class='row'><div><div class='eyebrow'>Project</div><h1>{_escape(project['name'])}</h1><p class='muted'><a href='https://github.com/{_escape(project['repo_owner'])}/{_escape(project['repo_name'])}'>{_escape(project['repo_owner'])}/{_escape(project['repo_name'])}</a> · {_escape(project['branch'])} · {_escape(project['mode']).title()} mode</p></div><form method='post'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><input type='hidden' name='paused' value='{'no' if paused else 'yes'}'><button class='button {'primary' if paused else 'danger'}' type='submit'>{button}</button></form></div><div class='stats'><span class='pill {'amber' if paused else 'green'}'>{'Paused' if paused else _escape(project['status'].replace('_',' ').title())}</span><span class='pill'>Mode · {_escape(project['mode'])}</span><span class='pill'>Last check-in · {_escape(_ago(project.get('last_heartbeat_at')))}</span></div><h2>Incident history</h2>{table}<section class='grid'>{install_card}<article class='card'><h3>Update GitHub token</h3><p class='muted'>Use a token authorized for this repository with Contents and Pull requests read/write access. The new token replaces the saved one and is never shown again.</p><form method='post' action='/projects/{_escape(project_id)}/github-token'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><div class='field'><label>New GitHub token</label><input name='github_token' type='password' autocomplete='new-password' required minlength='20' maxlength='500'></div><button class='button primary' type='submit'>Validate and save token</button></form></article><article class='card'><h3>Ingest key</h3><p class='muted'>Rotate the project key if it is exposed. The new key appears once.</p><form method='post' action='/projects/{_escape(project_id)}/rotate-key'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><button class='button' type='submit'>Rotate key</button></form></article><article class='card'><h3>Delete project data</h3><p class='muted'>Remove this project, its incidents, logs, fixes, and stored GitHub token.</p><form method='post' action='/projects/{_escape(project_id)}/delete'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><div class='field'><label>Type DELETE to confirm</label><input name='confirm' required autocomplete='off'></div><button class='button danger' type='submit'>Delete project</button></form></article></section></section>"
    return _response(body, request)


def _install_monitoring(project_id: str, user_id: str, project: dict, token: str, ingest_key: str, private: bool) -> dict:
    """Open (and try to merge) the monitoring PR. The key is embedded only for private repositories."""
    try:
        result = open_monitoring_pr(
            owner=project["repo_owner"], repo=project["repo_name"], base_branch=project["branch"],
            project_id=project_id, token=token, ingest_url=_base_url() + "/ingest",
            ingest_key=ingest_key if (private and ingest_key) else "", auto_merge=True)
    except (GitHubInstallError, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}
    portal_db.record_install_pr(project_id, user_id, result["url"])
    portal_db.audit(project_id, "monitoring_pr_opened", {"pr_url": result["url"], "merged": result["merged"],
                                                          "patched_file": result["patched_file"], "key_embedded": result["embedded_key"]})
    return dict(result, ok=True)


def _install_summary(result: dict, ingest_key: str, project_id: str) -> str:
    """Plain-language outcome of an install attempt, with the key only when the customer must use it."""
    url = _base_url() + "/ingest"
    env_help = (f"<div class='alert'>Set these two values in your app's hosting environment (they are not stored in your repository):"
                f"<br>INCIDENT_AGENT_INGEST_URL = <code>{_escape(url)}</code><br>INCIDENT_AGENT_INGEST_KEY = <code>{_escape(ingest_key)}</code>"
                "<br>This key is shown once.</div>") if ingest_key else ""
    if not result.get("ok"):
        return (f"<div class='alert'>Project saved, but monitoring could not be added yet: {_escape(result.get('error', 'unknown error'))}"
                f" You can retry from the project page.</div>{env_help}")
    notes = []
    if result.get("patched_file"):
        notes.append(f"One line was added to <code>{_escape(result['patched_file'])}</code> so monitoring starts with your app.")
    else:
        notes.append("We could not find your app's entry file. Add <code>import incident_agent_monitor</code> as the first import of it.")
    if result.get("merged"):
        notes.append("The change was merged automatically. Monitoring starts the next time your app deploys.")
    else:
        notes.append(f"Merge <a href='{_escape(result['url'])}' target='_blank' rel='noopener'>this pull request</a> to turn monitoring on (auto-merge was not possible, often because of branch protection).")
    if result.get("embedded_key"):
        notes.append("Your repository is private, so the connection details were added to it. Nothing else to configure.")
    else:
        notes.append("Your repository is public, so the connection key is not stored in it. Add it to your host's environment as shown below.")
    return "<div class='card'><h3>Monitoring setup</h3><p class='muted'>" + "</p><p class='muted'>".join(notes) + "</p></div>" + (env_help if not result.get("embedded_key") else "")


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
        ingest_key = _decrypt_token(project["ingest_key_ciphertext"]) if project.get("ingest_key_ciphertext") else ""
        info = validate_repository_access(owner=project["repo_owner"], repo=project["repo_name"], token=token)
    except (GitHubInstallError, RuntimeError) as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div><p><a href='/projects/{_escape(project_id)}'>Back to project</a></p>", request, "502 Bad Gateway")
    result = _install_monitoring(project_id, request.session["user_id"], project, token, ingest_key, bool(info.get("private")))
    if not result.get("ok"):
        return _response(f"<div class='alert'>{_escape(result['error'])}</div><p><a href='/projects/{_escape(project_id)}'>Back to project</a></p>", request, "502 Bad Gateway")
    key_for_env = "" if result.get("embedded_key") else ingest_key
    return _response(_install_summary(result, key_for_env, project_id) + f"<p><a class='button primary' href='/projects/{_escape(project_id)}'>Back to project</a></p>", request)


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
    if not portal_db.rotate_project_ingest_key(project_id, user_id, key_hash, _encrypt_token(key)):
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
    if _is_admin(request):
        return _redirect("/admin")
    user_id = request.session["user_id"]
    access = _access_state(user_id)
    csrf = _escape(_csrf(request))
    gateway = _gateway_ready()
    banner = "<div class='pill green'>Payment received. Your access is active.</div>" if request.query.get("success") == ["1"] else ""
    if access["active"]:
        label = "Paid plan" if access["kind"] == "paid" else "Free trial"
        current = (f"<article class='card'><div class='eyebrow'>Current plan</div><h2>{label}</h2>"
                   f"<p class='muted'>Active until {_escape(_fmt_time(access['until']))} · {_escape(access['remaining'])}</p>"
                   "<a class='button' href='/dashboard'>Go to my projects</a></article>")
    else:
        current = ("<article class='card'><div class='eyebrow'>Current plan</div><h2>No active access</h2>"
                   "<p class='muted'>Monitoring is paused. Your connected projects come back as soon as access starts.</p></article>")
    trial = access["trial"]
    trial_card = ""
    if not (access["active"] and access["kind"] == "paid") and not access["active"]:
        if trial == "pending":
            trial_card = "<article class='card'><div class='eyebrow'>Free trial</div><h3>Waiting for approval</h3><p class='muted'>The admins have your request. Access starts the moment they approve it and you will see it here and on your dashboard.</p></article>"
        elif trial == "approved":
            trial_card = "<article class='card'><div class='eyebrow'>Free trial</div><h3>Trial used</h3><p class='muted'>Your 1-day trial has ended. Pick a plan below to continue.</p></article>"
        else:
            note = "<p class='muted'>Your last request was not approved. You can ask again.</p>" if trial == "rejected" else "<p class='muted'>Try everything for one day. An admin approves each request.</p>"
            trial_card = (f"<article class='card'><div class='eyebrow'>Free trial</div><h3>1 day, free</h3>{note}"
                          f"<form method='post' action='/billing/trial-request'><input type='hidden' name='csrf' value='{csrf}'>"
                          "<button class='button' type='submit'>Request free trial</button></form></article>")
    plan_cards = []
    for key, plan in PLANS.items():
        if gateway:
            action = (f"<form method='post' action='/billing/order'><input type='hidden' name='csrf' value='{csrf}'>"
                      f"<input type='hidden' name='plan' value='{key}'><button class='button primary' type='submit'>Pay ₹{plan['rupees']:,}</button></form>"
                      "<p class='muted'>UPI (Paytm, PhonePe, GPay), cards or netbanking. Access starts instantly.</p>")
        else:
            action = (f"<a class='button primary' href='/billing/pay?plan={key}'>Pay ₹{plan['rupees']:,} by UPI</a>"
                      "<p class='muted'>After you pay, wait 1 to 2 hours. We check our Paytm account and switch your access on.</p>")
        period = "month" if key == "monthly" else "year"
        plan_cards.append(f"<article class='card'><div class='eyebrow'>{plan['label']}</div><h2>₹{plan['rupees']:,} <small class='muted'>/ {period}</small></h2>"
                          f"<p class='muted'>{plan['days']} days of access.</p>{action}</article>")
    payments = portal_db.user_manual_payments(user_id)
    history = ""
    if payments:
        rows = [f"<tr><td>{_escape(_fmt_time(p['created_at']))}</td><td>₹{_escape(p['amount'])} {_escape(p['plan'])}</td><td>{_escape(p['transaction_ref'])}</td><td>{_escape(p['status'].title())}</td></tr>" for p in payments]
        history = "<h2>Your UPI submissions</h2>" + _table(["Submitted", "Plan", "Reference", "Status"], rows)
    body = (f"<section class='section'><div class='eyebrow'>Account</div><h1>Plan &amp; billing</h1>{banner}"
            f"<div class='grid'>{current}{trial_card}</div><h2>Plans</h2><div class='grid'>{''.join(plan_cards)}</div>{history}</section>")
    return _response(body, request)


def _page_manual_payment(request):
    gate = _require_session(request)
    if gate:
        return gate
    if _is_admin(request) or _gateway_ready():
        return _redirect("/admin" if _is_admin(request) else "/billing")
    if request.method == "POST":
        if not _csrf_valid(request):
            return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
        plan = str(request.form.get("plan", ""))
        if plan not in PLANS:
            return _response("<div class='alert'>Choose a valid plan.</div>", request, "400 Bad Request")
        ref = str(request.form.get("transaction_ref", "")).strip()
        try:
            payment = portal_db.create_manual_payment_request(request.session["user_id"], PLANS[plan]["rupees"], plan, ref)
        except ValueError as exc:
            return _response(f"<div class='alert'>{_escape(exc)}</div><p><a href='/billing/pay?plan={plan}'>Back</a></p>", request, "400 Bad Request")
        if payment.get("created_at") and payment["status"] == "pending":
            notifications.notify_admins(
                f"UPI payment to confirm: INR {PLANS[plan]['rupees']} from {request.session['email']}",
                f"Customer: {request.session['email']}\nPlan: {plan} (INR {PLANS[plan]['rupees']})\nUPI reference: {ref}\n"
                f"Open your Paytm app and look for a payment of INR {PLANS[plan]['rupees']} with this reference. If you see it, confirm it here: {_base_url()}/admin", "payment_submitted")
            notifications.notify_customer(
                request.session["email"], "We received your payment details",
                f"Thanks! You told us you paid INR {PLANS[plan]['rupees']} (reference {ref}).\n"
                "Please wait 1 to 2 hours. We check our Paytm account and switch your access on as soon as we see the payment. "
                "You will get another email when it is active.", "payment_received")
        return _response("<section class='card form-card'><h1>Payment submitted</h1>"
                         "<p>Thanks! Please wait 1 to 2 hours. We check our Paytm account for your payment and your access starts as soon as we see it. "
                         "You will see the status under Plan &amp; billing and get an email.</p>"
                         "<p class='muted'>Do not pay again unless an admin asks you to.</p>"
                         "<a class='button primary' href='/billing'>Back to plan &amp; billing</a></section>", request)
    plan = request.query.get("plan", ["monthly"])[0]
    if plan not in PLANS:
        plan = "monthly"
    rupees = PLANS[plan]["rupees"]
    uri = _upi_uri(plan)
    qr = _qr_data_uri(uri)
    vpa = os.getenv("UPI_ID", "7975291636@ptsbi").strip()
    qr_html = f"<img src='{_escape(qr)}' alt='UPI QR code for ₹{rupees}' width='260' height='260'>" if qr else "<p style='color:#222'>QR code unavailable. Use the button below.</p>"
    plain_uri = "upi://pay?" + "&".join(f"{key}={quote(value, safe='@')}" for key, value in
                                       {"pa": vpa, "pn": os.getenv("UPI_PAYEE_NAME", "Pranav V Rao").strip(), "cu": "INR"}.items())
    plain_qr = _qr_data_uri(plain_uri)
    plain_html = f"<img src='{_escape(plain_qr)}' alt='UPI QR code without an amount' width='220' height='220'>" if plain_qr else ""
    body = (f"<section class='card form-card'><div class='eyebrow'>Pay by UPI</div><h1>Pay ₹{rupees:,}</h1>"
            f"<p class='muted'>{PLANS[plan]['label']} plan · {PLANS[plan]['days']} days. On a phone tap the button to open your UPI app (Paytm, PhonePe, GPay). On a computer scan the QR code with your phone.</p>"
            f"<div class='qr'><a href='{_escape(uri)}' aria-label='Open UPI app'>{qr_html}</a><p>{_escape(vpa)}</p>"
            f"<a class='button primary' style='margin-top:12px' href='{_escape(uri)}'>Open UPI app and pay ₹{rupees:,}</a></div>"
            f"<details><summary>Your app will not accept the amount? Scan this QR and type ₹{rupees:,} yourself.</summary><div class='qr'>{plain_html}<p>{_escape(vpa)}</p></div></details>"
            f"<div class='alert'>Check that your UPI app shows exactly ₹{rupees:,}.00 before you pay. After you pay, enter the UPI reference number (UTR) from your receipt below and press the button. Then please wait 1 to 2 hours: we check our Paytm account for your payment and switch your access on. You will get an email.</div>"
            f"<form method='post' action='/billing/pay'><input type='hidden' name='csrf' value='{_escape(_csrf(request))}'><input type='hidden' name='plan' value='{plan}'>"
            "<div class='field'><label>UPI reference number (UTR)</label><input name='transaction_ref' maxlength='40' required autocomplete='off' placeholder='12-digit number from your payment receipt'>"
            "<small>Only submit after your UPI app shows the payment as successful. Fake references are rejected when an admin checks.</small></div>"
            "<button class='button primary' type='submit'>I have paid ₹" + f"{rupees:,}" + "</button></form></section>")
    return _response(body, request)


def _page_create_order(request):
    gate = _require_session(request)
    if gate:
        return gate
    if _is_admin(request):
        return _redirect("/admin")
    if request.method != "POST":
        return _response("Method not allowed", request, "405 Method Not Allowed")
    if not _csrf_valid(request):
        return _response("<div class='alert'>This form expired. Refresh and try again.</div>", request, "403 Forbidden")
    plan = str(request.form.get("plan", ""))
    if plan not in PLANS:
        return _response("<div class='alert'>Choose a valid subscription plan.</div>", request, "400 Bad Request")
    try:
        key_id, secret, amount = _razorpay_settings(plan)
    except RuntimeError as exc:
        return _response(f"<div class='alert'>{_escape(exc)}</div><p><a href='/billing/pay?plan={plan}'>Pay by UPI QR instead</a></p>", request, "503 Service Unavailable")
    user_id = request.session["user_id"]
    payload = json.dumps({"amount": amount, "currency": "INR",
                          "receipt": "ad-" + secrets.token_hex(8),
                          "notes": {"user_id": user_id, "plan": plan}}).encode("utf-8")
    basic = base64.b64encode(f"{key_id}:{secret}".encode("utf-8")).decode("ascii")
    api_request = UrlRequest("https://api.razorpay.com/v1/orders", data=payload,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json", "User-Agent": "AgentDaemon/1.0"}, method="POST")
    try:
        with urlopen(api_request, timeout=12) as result:
            order = json.loads(result.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return _response("<div class='alert'>The payment provider could not start the payment. Nothing was charged. Try again in a minute.</div>", request, "502 Bad Gateway")
    order_id = str(order.get("id", ""))
    if not re.fullmatch(r"order_[A-Za-z0-9]+", order_id) or order.get("amount") != amount:
        return _response("<div class='alert'>The payment provider returned an invalid order. Nothing was charged.</div>", request, "502 Bad Gateway")
    portal_db.create_payment_order(user_id, order_id, amount, plan)
    nonce = secrets.token_urlsafe(18)
    rupees = amount // 100
    test_banner = "<div class='alert'>Test mode: no real money moves. Use Razorpay's test UPI id <code>success@razorpay</code>.</div>" if key_id.startswith("rzp_test_") else ""
    script = r"""const options={key:__KEY__,amount:__AMOUNT__,currency:'INR',name:'Agent Daemon',description:__DESC__,order_id:__ORDER__,prefill:{email:__EMAIL__},theme:{color:'#75a7ff'},
handler:async function(r){const out=document.getElementById('result');out.textContent='Confirming your payment...';try{const response=await fetch('/billing/verify',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({csrf:__CSRF__,order_id:r.razorpay_order_id,payment_id:r.razorpay_payment_id,signature:r.razorpay_signature})});const data=await response.json();if(response.ok){location.href='/billing?success=1';}else{out.textContent=data.error||'Payment verification failed.';}}catch(e){out.textContent='Could not confirm yet. If money was taken, your access switches on automatically within a minute.';}},
modal:{ondismiss:function(){document.getElementById('result').textContent='Checkout closed. You have not been charged.';}}};
const rzp=new Razorpay(options);rzp.on('payment.failed',function(r){document.getElementById('result').textContent=(r.error&&r.error.description)||'Payment failed. You can try again.';});
document.getElementById('pay').addEventListener('click',function(){rzp.open();});rzp.open();"""
    def js(value):
        return json.dumps(value).replace("</", "<\\/")
    for token, value in (("__KEY__", key_id), ("__AMOUNT__", amount), ("__DESC__", f"Agent Daemon {plan}"), ("__ORDER__", order_id),
                         ("__EMAIL__", request.session["email"]), ("__CSRF__", _csrf(request))):
        script = script.replace(token, js(value))
    body = (f"<section class='card form-card'><div class='eyebrow'>Secure payment</div><h1>Pay ₹{rupees:,}</h1>"
            f"<p class='muted'>{PLANS[plan]['label']} plan · {PLANS[plan]['days']} days. The amount is fixed by the server, so you can only pay ₹{rupees:,}. "
            "Pay with any UPI app (Paytm, PhonePe, GPay), card or netbanking. Access starts the moment the payment succeeds.</p>"
            f"{test_banner}<button class='button primary' id='pay' type='button'>Pay ₹{rupees:,}</button><p id='result' class='muted'></p></section>"
            f"<script src='https://checkout.razorpay.com/v1/checkout.js'></script><script nonce='{nonce}'>{script}</script>")
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
    _after_payment(order_id, payment_id)
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
    portal_db.set_project_connected(project["id"])
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
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return Response(b"invalid event", "400 Bad Request", [("Content-Type", "text/plain")])
    if event.get("event") == "payment.captured" and payment.get("status") == "captured" and payment.get("currency") == "INR":
        order_id, payment_id = str(payment.get("order_id", "")), str(payment.get("id", ""))
        if re.fullmatch(r"order_[A-Za-z0-9]+", order_id) and re.fullmatch(r"pay_[A-Za-z0-9]+", payment_id):
            try:
                amount = int(payment.get("amount", 0))
            except (TypeError, ValueError):
                amount = 0
            # Safe to repeat: complete_payment_order applies each captured payment only once.
            if portal_db.complete_payment_order(order_id, payment_id, amount):
                _after_payment(order_id, payment_id)
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
    if request.path == "/billing/pay":
        return _page_manual_payment(request)
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

