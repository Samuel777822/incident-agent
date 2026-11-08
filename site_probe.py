"""The real "every 30 seconds" check for sites that have no server of their own (plain HTML/JS, GitHub Pages, Netlify, Vercel).

A monitor inside a static page only runs while a visitor has the page open, so on its own it cannot check in every 30 seconds.
This module is run by the worker every 30 seconds: it opens each project's public site address like a visitor would, and
  * records a check-in ('probe' / 'site') when the site answers, so the dashboard shows "Live" even with no visitors,
  * opens an incident when the site answers with an error page (HTTP 4xx/5xx) or an empty page twice in a row,
  * stays quiet when the host is simply unreachable (DNS, timeout): that is a hosting outage, not a bug in the code, and AI tries
    must not be spent on it.
The site address comes from the project, or is found from the repository's homepage field on GitHub.

SAFETY: the address is typed by a user, so every address (and every redirect) must resolve to a PUBLIC internet address. Private,
loopback, link-local (cloud metadata) and reserved ranges are refused, so this can never be used to reach our own network.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

import portal_db

LOG = logging.getLogger("site_probe")
TIMEOUT = httpx.Timeout(10, connect=6)
MAX_BYTES = 200_000
MAX_REDIRECTS = 3
MAX_PER_SWEEP = 40
BAD_STREAK_FOR_INCIDENT = 2
_STREAK: dict[str, int] = {}
_LAST_DETECT: dict[str, float] = {}
DETECT_EVERY_SECONDS = 6 * 3600


def _public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def safe_url(url: str) -> str:
    """The URL when it is http(s) with a public host and no credentials, else ''."""
    try:
        parts = urlparse(str(url or "").strip())
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return ""
    if parts.port not in (None, 80, 443):
        return ""
    return parts.geturl() if _public(parts.hostname) else ""


def fetch(url: str, client=None) -> dict:
    """{ok, status, ms, size, error}. Follows at most 3 redirects, each re-checked as a public address."""
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": "AgentDaemon-SiteCheck/1.0"})
    started = time.time()
    try:
        current = safe_url(url)
        if not current:
            return {"ok": False, "status": 0, "ms": 0, "size": 0, "error": "address is not a public website"}
        for _ in range(MAX_REDIRECTS + 1):
            with client.stream("GET", current) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    current = safe_url(urljoin(current, resp.headers["location"]))
                    if not current:
                        return {"ok": False, "status": resp.status_code, "ms": 0, "size": 0, "error": "redirected to a non-public address"}
                    continue
                size = 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size >= MAX_BYTES:
                        break
                return {"ok": True, "status": resp.status_code, "ms": int((time.time() - started) * 1000), "size": size, "error": ""}
        return {"ok": False, "status": 0, "ms": 0, "size": 0, "error": "too many redirects"}
    except httpx.HTTPError as exc:
        return {"ok": False, "status": 0, "ms": int((time.time() - started) * 1000), "size": 0, "error": exc.__class__.__name__}
    finally:
        if own:
            client.close()


def judge(result: dict) -> str:
    """'up' | 'bad' (the site answered, but wrongly: a bug candidate) | 'unreachable' (host problem: never a code bug)."""
    if not result.get("ok"):
        return "unreachable"
    status = int(result.get("status") or 0)
    if status in (429, 503, 502, 504):
        return "unreachable"                      # busy or restarting host: not something the code can fix
    if status >= 400:
        return "bad"
    if int(result.get("size") or 0) < 40:
        return "bad"                              # a blank page
    return "up"


def _projects() -> list[dict]:
    conn = portal_db.get_connection()
    try:
        rows = portal_db._execute(conn, """SELECT id,user_id,app_url,repo_owner,repo_name,branch,github_token_ciphertext,gate_state
            FROM projects WHERE paused=0 AND watch_mode IN ('runtime','both') AND active_until>? AND ai_consent_at<>''
            ORDER BY created_at ASC LIMIT ?""", (datetime.now(timezone.utc).isoformat(timespec="seconds"), 500)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _save_url(project_id: str, url: str) -> None:
    conn = portal_db.get_connection()
    try:
        portal_db._execute(conn, "UPDATE projects SET app_url=? WHERE id=? AND app_url=''", (url[:300], project_id))
        conn.commit()
    finally:
        conn.close()


def detect_app_url(project: dict) -> str:
    """The repository's 'homepage' field on GitHub (what most people set to their live site). '' when unknown."""
    try:
        import repo_guard
        from portal_remediation import _token
        info = repo_guard.repo_info(project, _token(project.get("github_token_ciphertext", "")))
        return safe_url(str(info.get("homepage") or ""))
    except Exception:
        return ""


def _incident(project: dict, url: str, result: dict) -> None:
    status = result.get("status")
    what = f"HTTP {status}" if status else "an empty page"
    if status and int(status) < 400:
        what = "an empty page"
    ev = {"kind": "site_down", "page": url.split("?")[0], "status": status, "request": "GET " + url.split("?")[0]}
    portal_db.ingest_event(project["id"], timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"), level="ERROR",
                           message=f"Site is not answering correctly: GET {url.split('?')[0]} returned {what}",
                           traceback="[evidence] " + json.dumps(ev) + "\n", signature=f"site_down:{status or 'blank'}")


def check_one(project: dict, client=None) -> str:
    url = safe_url(project.get("app_url") or "")
    if not url:
        return "skip"
    pid = project["id"]
    if project.get("gate_state") == getattr(portal_db, "GATE_WAITING", "waiting"):
        return "skip"
    result = fetch(url, client)
    verdict = judge(result)
    if verdict == "up":
        _STREAK[pid] = 0
        portal_db.record_heartbeat(pid, "probe", "site", version="1", runtime=f"{result['ms']}ms", touch_project=False)
    elif verdict == "bad":
        _STREAK[pid] = _STREAK.get(pid, 0) + 1
        if _STREAK[pid] == BAD_STREAK_FOR_INCIDENT:
            _incident(project, url, result)
    else:
        _STREAK[pid] = 0
    return verdict


def sweep() -> int:
    """One pass over every project. Returns how many sites were checked."""
    projects = _projects()
    now = time.time()
    todo = []
    for p in projects:
        if p.get("app_url"):
            todo.append(p)
        elif now - _LAST_DETECT.get(p["id"], 0) > DETECT_EVERY_SECONDS:
            _LAST_DETECT[p["id"]] = now
            found = detect_app_url(p)
            if found:
                _save_url(p["id"], found)
                p["app_url"] = found
                todo.append(p)
    todo = todo[:MAX_PER_SWEEP]
    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda p: _safe_check(p), todo))
    return len(todo)


def _safe_check(project: dict) -> str:
    try:
        return check_one(project)
    except Exception as exc:
        LOG.warning("site check for project %s failed (%s)", project.get("id"), exc.__class__.__name__)
        return "error"
