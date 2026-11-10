"""One case = one fix (v3.1).

A *case* is every incident and report that has the SAME cause. One broken outside API used to become three incidents (the
failed request, the "Failed to load chapter" text on the page, a network error), and each of them got its own paid AI diagnosis.
Now the first one is the case *leader*; the others are attached to it as *followers* (status 'merged'). Followers never get their
own AI diagnosis: their evidence is handed to the leader's fix instead.

Grouping is rule-based and free (cheapest first):
  a. the same AI model id is failing,
  b. the same outside host answers with the same status,
  c. the same page, within a short time window,
  d. an owner's report and a problem the monitor saw at about the same time (or naming the same page / host),
  e. two owner reports that say nearly the same thing.
After a fix is pushed the leader has a *check window* (default 5 minutes): related events in that window are attached and ignored,
so ten clicks on a broken button produce one fix, not ten.

Pure functions only (no database): portal_db.ingest_event() feeds the candidate rows in.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

EVIDENCE_PREFIX = "[evidence] "
PAGE_WINDOW_MINUTES = 15
REPORT_WINDOW_MINUTES = 30
REPORT_NEAR_MINUTES = 10
WEB_KINDS = {"failed_request", "external_api", "js_error", "ui_error_text", "dead_click", "site_down", "journey_failed", "retired_model"}
_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = {"the", "and", "not", "does", "doesn", "this", "that", "with", "when", "page", "site", "website", "working", "work", "loading",
         "load", "error", "broken", "fix", "please", "button", "from", "there", "what", "have", "but", "for", "are", "its", "it's", "any",
         "problem", "problems", "number", "issue", "issues", "something", "doesnt", "isnt", "dont", "cant", "wont", "anymore", "still",
         "again", "all", "now", "can", "you", "our", "my", "your", "just", "some", "shows", "show", "showing", "nothing", "happens", "click"}


def check_window_seconds() -> int:
    try:
        return max(30, int(os.getenv("CASE_CHECK_WINDOW_SECONDS", "300") or 300))
    except ValueError:
        return 300


def evidence_of(traceback: str) -> dict:
    """The '[evidence] {json}' line monitors put at the top of the traceback field ({} when there is none)."""
    for line in str(traceback or "").splitlines()[:6]:
        if line.startswith(EVIDENCE_PREFIX):
            try:
                data = json.loads(line[len(EVIDENCE_PREFIX):])
                return data if isinstance(data, dict) else {}
            except ValueError:
                return {}
    return {}


def infer_kind(message: str) -> str:
    low = (message or "").lower()
    if low.startswith("[user report]"):
        return "user_report"
    if low.startswith("retired ai model") or "no endpoints found" in low:
        return "retired_model"
    if "dead click" in low:
        return "dead_click"
    if "site is not answering" in low or "site down" in low:
        return "site_down"
    if re.search(r"failed with http|failed request|network error|cors", low):
        return "failed_request"
    return ""


def _host_status(ev: dict, message: str) -> tuple[str, str]:
    req = str(ev.get("request") or ev.get("url") or "")
    url = req.split(" ", 1)[-1] if " " in req else req
    host = ""
    if "://" in url:
        try:
            host = (urlparse(url).hostname or "").lower()
        except ValueError:
            host = ""
    if not host and re.search(r"failed with http|failed request|network error|cors", message or "", re.I):
        m = re.search(r"https?://([a-z0-9.-]+)", message or "", re.I)      # only a request failure names its host in the message
        host = m.group(1).lower() if m else ""
    status = str(ev.get("status") or "")
    if not status:
        m = re.search(r"\bhttp\s*(\d{3})\b", message or "", re.I)
        status = m.group(1) if m else ""
    return host, status


def _page_path(page: str) -> str:
    if not page:
        return ""
    try:
        parts = urlparse(page if "://" in page else "https://x" + ("" if page.startswith("/") else "/") + page)
    except ValueError:
        return ""
    return (parts.path or "/").rstrip("/") or "/"


def words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}


def key_for(signature: str, message: str, traceback: str) -> dict:
    """What a case is recognised by. Small and JSON-safe: stored in incidents.case_key."""
    ev = evidence_of(traceback)
    kind = str(ev.get("kind") or "") or infer_kind(message)
    model = str(ev.get("model") or "")
    if not model and str(signature or "").startswith("Retired AI model: "):
        model = signature[len("Retired AI model: "):]
    host, status = _host_status(ev, message)
    text = str(ev.get("owner_report") or "")[:400] if kind == "user_report" else ""
    return {"kind": kind[:30], "model": model[:120], "host": host[:120], "status": status[:5],
            "page": _page_path(str(ev.get("page") or ""))[:200], "text": text}


def _minutes_between(a: str, b: str) -> float:
    try:
        x, y = datetime.fromisoformat(a), datetime.fromisoformat(b)
        if x.tzinfo is None:
            x = x.replace(tzinfo=timezone.utc)
        if y.tzinfo is None:
            y = y.replace(tzinfo=timezone.utc)
        return abs((x - y).total_seconds()) / 60.0
    except (TypeError, ValueError):
        return 1e9


def _report_mentions(report: str, other: dict) -> bool:
    low = (report or "").lower()
    segs = [s for s in (other.get("page") or "").split("/") if len(s) >= 3]
    host = (other.get("host") or "").split(".")
    return any(s.lower() in low for s in segs) or any(len(h) >= 4 and h in low for h in host[:-1])


def related(new: dict, old: dict, *, new_ts: str, old_ts: str) -> str:
    """Why `new` belongs to the case of `old` ('' when it does not). Rules from cheapest/most certain to least."""
    if not new or not old:
        return ""
    gap = _minutes_between(new_ts, old_ts)
    if new.get("model") and new.get("model") == old.get("model"):
        return "the same AI model is failing"
    if new.get("host") and new.get("host") == old.get("host"):
        if not new.get("status") or not old.get("status") or new.get("status") == old.get("status"):
            return f"the same outside service ({new['host']}) is failing"
    if new.get("page") and new.get("page") == old.get("page") and gap <= PAGE_WINDOW_MINUTES \
            and new.get("kind") in WEB_KINDS and old.get("kind") in WEB_KINDS:
        return f"the same page ({new['page']}) at the same time"
    kinds = {new.get("kind"), old.get("kind")}
    if kinds == {"user_report"}:
        a, b = words(new.get("text", "")), words(old.get("text", ""))
        shared = a & b
        overlap = len(shared) / max(1, len(a | b))
        if shared and (overlap >= 0.6 or (overlap >= 0.34 and any(len(w) >= 4 for w in shared))):
            return "a report that says the same thing"
        return ""
    if "user_report" in kinds and (kinds - {"user_report"}) <= WEB_KINDS and gap <= REPORT_WINDOW_MINUTES:
        report, other = (new, old) if new.get("kind") == "user_report" else (old, new)
        if gap <= REPORT_NEAR_MINUTES or _report_mentions(report.get("text", ""), other):
            return "your report and a problem the monitor saw on your site at the same time"
    return ""


def find_leader(candidates: list[dict], key: dict, *, now_iso: str) -> tuple[str, str]:
    """candidates: rows {id, case_key (json), first_seen, last_seen, status, check_until}. Returns (leader_id, reason) or ('', '')."""
    for row in candidates:
        try:
            old = json.loads(row.get("case_key") or "{}")
        except ValueError:
            continue
        if not isinstance(old, dict) or not old:
            continue
        if row.get("status") == "resolved" and not (row.get("check_until") and row["check_until"] > now_iso):
            continue
        why = related(key, old, new_ts=now_iso, old_ts=str(row.get("last_seen") or row.get("first_seen") or ""))
        if why:
            return str(row["id"]), why
    return "", ""
