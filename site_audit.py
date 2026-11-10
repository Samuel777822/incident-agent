"""Site audit (v3.2): the agent looks for problems by itself, without waiting for a visitor or a report.

Right after a project is connected (and then once a day), the worker opens the project's live site in the real browser on the
sandbox server (fixengine/investigator.py) and turns what it sees into incidents: API calls that fail, scripts and styles that are
missing, JavaScript errors on the page. The normal pipeline then takes over: the problems are grouped into ONE case per cause
(cases.py), fixed, proven, pushed and checked on the live site again.

Together with the push check that runs on connect (download the code, install, build, test, start) this is the "connect it and it
finds what is broken" path. Cheap by design: one browser visit per project per day, no AI call here, at most a few incidents per
visit, and nothing is created from a plain-fetch fallback (it cannot see JavaScript problems, the 30-second site check covers it).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone

import portal_db

LOG = logging.getLogger("site_audit")
MAX_EVENTS = 4
API_TYPES = ("xhr", "fetch")
ASSET_TYPES = ("script", "stylesheet", "document")


def enabled() -> bool:
    return os.getenv("SITE_AUDIT_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def _every_hours() -> int:
    try:
        return max(1, int(os.getenv("SITE_AUDIT_EVERY_HOURS", "24") or 24))
    except ValueError:
        return 24


def _now() -> datetime:
    return datetime.now(timezone.utc)


def next_due() -> dict | None:
    """One project whose audit is due (never audited, or the last one is older than a day). Oldest connection first."""
    from fixengine import store
    conn = portal_db.get_connection()
    try:
        rows = portal_db._execute(conn, """SELECT id,user_id,name,app_url,gate_state FROM projects
            WHERE paused=0 AND app_url<>'' AND ai_consent_at<>'' AND active_until>? ORDER BY created_at ASC LIMIT 200""",
            (_now().isoformat(timespec="seconds"),)).fetchall()
    finally:
        conn.close()
    now = _now().isoformat(timespec="seconds")
    for row in rows:
        p = dict(row)
        if p.get("gate_state") == getattr(portal_db, "GATE_WAITING", "waiting"):
            continue
        due = store.get_flag(f"audit_next:{p['id']}")
        if not due or due <= now:
            return p
    return None


def events_from(report: dict, page: str) -> list[dict]:
    """The problems of one browser visit as incident events (message, evidence, signature). Pure function."""
    out: list[dict] = []
    site_host = ""
    try:
        from urllib.parse import urlparse
        site_host = (urlparse(page).hostname or "").lower()
    except ValueError:
        pass
    seen = set()
    for f in report.get("failed_requests") or []:
        host, path, status, kind = str(f.get("host") or ""), str(f.get("path") or "/"), int(f.get("status") or 0), str(f.get("type") or "")
        same = host.lower() == site_host
        if kind in API_TYPES and (status >= 400 or (status == 0 and same)):
            pass
        elif kind in ASSET_TYPES and same and status >= 400:
            pass
        else:
            continue                      # pictures, fonts, third-party trackers: not what breaks a site
        key = (host, status, path.rsplit("/", 1)[0])
        if key in seen:
            continue
        seen.add(key)
        method = str(f.get("method") or "GET")
        what = f"HTTP {status}" if status else "a network error"
        ev = {"kind": "failed_request", "page": page.split("?")[0], "request": f"{method} https://{host}{path}", "status": status or "",
              "response": str(f.get("body") or "")[:400], "found_by": "site audit"}
        out.append({"message": f"{method} https://{host}{path} failed with {what} (found by the site audit)", "evidence": ev,
                    "signature": f"audit:http:{host}:{status}:{hashlib.sha1(path.encode()).hexdigest()[:8]}"})
    for err in (report.get("page_errors") or [])[:3]:
        text = " ".join(str(err).split())[:300]
        ev = {"kind": "js_error", "page": page.split("?")[0], "console": text, "found_by": "site audit"}
        out.append({"message": f"JavaScript error on the page: {text} (found by the site audit)", "evidence": ev,
                    "signature": "audit:js:" + hashlib.sha1(text.encode()).hexdigest()[:10]})
    return out[:MAX_EVENTS]


def audit_one(project: dict, investigate=None) -> int:
    """Visit the site once and open incidents for what is broken. Returns how many events were sent."""
    from fixengine import investigator, store
    import site_probe
    pid = project["id"]
    url = site_probe.safe_url(project.get("app_url") or "")
    later = lambda hours: store.set_flag(f"audit_next:{pid}", (_now() + timedelta(hours=hours)).isoformat(timespec="seconds"))
    if not url:
        later(_every_hours())
        return 0
    report = (investigate or investigator.investigate)(url, [])
    if not report.get("ok") or report.get("mode") != "browser":
        later(1)                          # no real browser right now (or the site did not open): try again in an hour
        return 0
    later(_every_hours())
    events = events_from(report, url)
    ts = _now().isoformat(timespec="seconds")
    for e in events:
        portal_db.ingest_event(pid, timestamp=ts, level="ERROR", message=e["message"][:2000],
                               traceback="[evidence] " + json.dumps(e["evidence"]) + "\n", signature=e["signature"][:250])
    portal_db.audit(pid, "site_audit", {"problems": len(events), "ms": report.get("ms")})
    return len(events)


def sweep(investigate=None) -> int:
    """Called by the worker about once a minute: audit ONE due project (the sandbox server runs one browser at a time)."""
    if not enabled():
        return 0
    try:
        from fixengine import investigator
        if not investigator.enabled():
            return 0
        project = next_due()
        if not project:
            return 0
        found = audit_one(project, investigate)
        LOG.info("Site audit for project %s: %s problem(s)", project["id"], found)
        return 1
    except Exception as exc:
        LOG.warning("site audit failed (%s)", exc.__class__.__name__)
        return 0
