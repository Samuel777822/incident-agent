"""Database tables and helpers for bugs, attempts (the cost ledger), router decisions, grants and admin actions.

Uses portal_db's connection, so it works on SQLite locally and PostgreSQL in production.
Every model call writes exactly one fx_attempts row. That table powers quotas, the admin
dashboard, the burn rate, the kill switch and the router's learning (plan 4.9).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import portal_db
from portal_db import _execute, get_connection

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS fx_bugs (
      id TEXT PRIMARY KEY, project_id TEXT NOT NULL, user_id TEXT NOT NULL, incident_id TEXT NOT NULL UNIQUE,
      fingerprint TEXT NOT NULL DEFAULT '', fingerprint_json TEXT NOT NULL DEFAULT '{}',
      bug_class TEXT NOT NULL DEFAULT 'medium', category TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL DEFAULT 'open', stop_reason TEXT NOT NULL DEFAULT '',
      spent_inr REAL NOT NULL DEFAULT 0, tries INTEGER NOT NULL DEFAULT 0,
      baseline_failing INTEGER, baseline_output TEXT NOT NULL DEFAULT '', review_report TEXT NOT NULL DEFAULT '', pr_url TEXT NOT NULL DEFAULT '',
      strong_diagnosis TEXT NOT NULL DEFAULT '', user_pinned_tier TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, closed_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS fx_attempts (
      id TEXT PRIMARY KEY, bug_id TEXT NOT NULL, user_id TEXT NOT NULL, project_id TEXT NOT NULL,
      tier TEXT NOT NULL, model TEXT NOT NULL DEFAULT '', bug_class TEXT NOT NULL DEFAULT '',
      used_strong_diag INTEGER NOT NULL DEFAULT 0,
      tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0, cache_read INTEGER NOT NULL DEFAULT 0,
      cost_inr REAL NOT NULL DEFAULT 0, result TEXT NOT NULL DEFAULT 'pending',
      error_summary TEXT NOT NULL DEFAULT '', progress INTEGER NOT NULL DEFAULT 0,
      failing_before INTEGER, failing_after INTEGER, diagnosis TEXT NOT NULL DEFAULT '',
      patch_json TEXT NOT NULL DEFAULT '', info_hash TEXT NOT NULL DEFAULT '',
      period TEXT NOT NULL, pack_try INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_fx_attempts_user ON fx_attempts(user_id, period, tier)",
    "CREATE INDEX IF NOT EXISTS idx_fx_attempts_bug ON fx_attempts(bug_id)",
    """CREATE TABLE IF NOT EXISTS fx_router_decisions (
      id TEXT PRIMARY KEY, bug_id TEXT NOT NULL, state_json TEXT NOT NULL, options_json TEXT NOT NULL,
      chosen TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS fx_grants (
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL, period TEXT NOT NULL, tier TEXT NOT NULL,
      tries INTEGER NOT NULL, source TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS fx_admin_actions (
      id TEXT PRIMARY KEY, kind TEXT NOT NULL, user_id TEXT NOT NULL DEFAULT '',
      detail_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL)""",
    "CREATE TABLE IF NOT EXISTS fx_flags (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS fx_user_settings (user_id TEXT PRIMARY KEY, mode TEXT NOT NULL DEFAULT 'auto', updated_at TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS fx_pending_choices (
      id TEXT PRIMARY KEY, bug_id TEXT NOT NULL, user_id TEXT NOT NULL, tier TEXT NOT NULL,
      message TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'waiting', choice TEXT NOT NULL DEFAULT '',
      expires_at TEXT, created_at TEXT NOT NULL, resolved_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS fx_holds (
      id TEXT PRIMARY KEY, user_id TEXT NOT NULL, period TEXT NOT NULL, tier TEXT NOT NULL,
      tries_requested INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'held',
      analysis_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, resolved_at TEXT)""",
]


def ensure_schema(conn) -> None:
    for statement in SCHEMA:
        _execute(conn, statement)
    conn.commit()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def now() -> str:
    return _now_dt().isoformat(timespec="microseconds")


def now_s() -> str:
    """Seconds-resolution timestamp, the same format portal_db compares against for its job queue."""
    return _now_dt().isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


def current_period(at: datetime | None = None) -> str:
    return (at or _now_dt()).strftime("%Y-%m")


def _one(sql, params=()):
    conn = get_connection()
    try:
        row = _execute(conn, sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _all(sql, params=()):
    conn = get_connection()
    try:
        return [dict(r) for r in _execute(conn, sql, params).fetchall()]
    finally:
        conn.close()


def _run(sql, params=()):
    conn = get_connection()
    try:
        cur = _execute(conn, sql, params)
        conn.commit()
        return cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---- bugs -------------------------------------------------------------------------------------
def create_bug(*, project_id, user_id, incident_id, fingerprint_json: dict, bug_class, category) -> dict:
    existing = get_bug_by_incident(incident_id)
    if existing:
        return existing
    bug_id = new_id()
    _run("""INSERT INTO fx_bugs(id,project_id,user_id,incident_id,fingerprint,fingerprint_json,bug_class,category,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
         (bug_id, project_id, user_id, incident_id, fingerprint_json.get("hash", ""),
          json.dumps(fingerprint_json, sort_keys=True), bug_class, category, now()))
    return get_bug(bug_id)


def get_bug(bug_id):
    return _one("SELECT * FROM fx_bugs WHERE id=?", (bug_id,))


def get_bug_by_incident(incident_id):
    return _one("SELECT * FROM fx_bugs WHERE incident_id=?", (incident_id,))


_BUG_FIELDS = {"baseline_output", "status", "stop_reason", "spent_inr", "tries", "baseline_failing", "review_report", "pr_url",
               "strong_diagnosis", "user_pinned_tier", "bug_class", "category", "fingerprint", "fingerprint_json",
               "closed_at"}


def update_bug(bug_id, **fields) -> None:
    bad = set(fields) - _BUG_FIELDS
    if bad:
        raise ValueError("unknown bug fields: " + ", ".join(sorted(bad)))
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields)
    _run(f"UPDATE fx_bugs SET {sets} WHERE id=?", (*fields.values(), bug_id))


def count_prior_failures(project_id, fingerprint) -> int:
    row = _one("""SELECT COUNT(*) AS n FROM fx_bugs WHERE project_id=? AND fingerprint=?
                  AND status IN ('needs_human','failed')""", (project_id, fingerprint))
    return int(row["n"]) if row else 0


# ---- attempts / ledger ---------------------------------------------------------------------------
def add_attempt(*, bug, tier, model, used_strong_diag, info_hash, pack_try=False) -> str:
    attempt_id = new_id()
    _run("""INSERT INTO fx_attempts(id,bug_id,user_id,project_id,tier,model,bug_class,used_strong_diag,info_hash,
            period,pack_try,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
         (attempt_id, bug["id"], bug["user_id"], bug["project_id"], tier, model, bug["bug_class"],
          1 if used_strong_diag else 0, info_hash, current_period(), 1 if pack_try else 0, now()))
    return attempt_id


_ATTEMPT_FIELDS = {"tokens_in", "tokens_out", "cache_read", "cost_inr", "result", "error_summary", "progress",
                   "failing_before", "failing_after", "diagnosis", "patch_json", "model"}


def finish_attempt(attempt_id, **fields) -> None:
    bad = set(fields) - _ATTEMPT_FIELDS
    if bad:
        raise ValueError("unknown attempt fields: " + ", ".join(sorted(bad)))
    sets = ",".join(f"{k}=?" for k in fields)
    _run(f"UPDATE fx_attempts SET {sets} WHERE id=?", (*fields.values(), attempt_id))


def list_attempts(bug_id) -> list[dict]:
    return _all("SELECT * FROM fx_attempts WHERE bug_id=? ORDER BY created_at ASC, id ASC", (bug_id,))


def tier_used(user_id, tier, period=None) -> int:
    """Tries counted against the quota. System faults are restored (plan 18)."""
    row = _one("""SELECT COUNT(*) AS n FROM fx_attempts WHERE user_id=? AND tier=? AND period=?
                  AND result NOT IN ('system_fault','review')""", (user_id, tier, period or current_period()))
    return int(row["n"]) if row else 0          # a review of a fix is our quality check, never one of the customer's tries


def pack_tries_used(user_id, tier, period=None) -> int:
    row = _one("""SELECT COUNT(*) AS n FROM fx_attempts WHERE user_id=? AND tier=? AND period=?
                  AND pack_try=1 AND result NOT IN ('system_fault','review')""", (user_id, tier, period or current_period()))
    return int(row["n"]) if row else 0


def groq_used_today(user_id) -> int:
    start = _now_dt().replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="microseconds")
    row = _one("""SELECT COUNT(*) AS n FROM fx_attempts WHERE user_id=? AND tier='groq' AND created_at>=?
                  AND result<>'system_fault'""", (user_id, start))
    return int(row["n"]) if row else 0


def tries_last_hour(user_id) -> int:
    since = (_now_dt() - timedelta(hours=1)).isoformat(timespec="microseconds")
    # Only real tries count. A provider fault, a skipped free model or a review is not a try: counting them is how the hourly
    # limit filled up with nothing done ("Too many tries this hour").
    row = _one("""SELECT COUNT(*) AS n FROM fx_attempts WHERE user_id=? AND created_at>=?
                  AND result NOT IN ('system_fault','review','pending')""", (user_id, since))
    return int(row["n"]) if row else 0


def minutes_until_try_frees(user_id) -> int:
    """Minutes until the oldest counted try of the last hour is an hour old (when the hourly limit lets the next one through)."""
    since = (_now_dt() - timedelta(hours=1)).isoformat(timespec="microseconds")
    row = _one("""SELECT MIN(created_at) AS t FROM fx_attempts WHERE user_id=? AND created_at>=?
                  AND result NOT IN ('system_fault','review','pending')""", (user_id, since))
    try:
        oldest = datetime.fromisoformat(row["t"])
        return max(1, int((oldest + timedelta(hours=1) - _now_dt()).total_seconds() // 60) + 1)
    except (TypeError, ValueError, KeyError):
        return 5


def new_bugs_last_hour(user_id) -> int:
    since = (_now_dt() - timedelta(hours=1)).isoformat(timespec="microseconds")
    row = _one("SELECT COUNT(*) AS n FROM fx_bugs WHERE user_id=? AND created_at>=?", (user_id, since))
    return int(row["n"]) if row else 0


def recent_failed_bugs(user_id, minutes) -> int:
    since = (_now_dt() - timedelta(minutes=minutes)).isoformat(timespec="microseconds")
    row = _one("""SELECT COUNT(*) AS n FROM fx_bugs WHERE user_id=? AND status IN ('needs_human','failed')
                  AND closed_at>=?""", (user_id, since))
    return int(row["n"]) if row else 0


def spend_inr(*, period=None, user_id=None, since: str | None = None, tier: str | None = None, project_id: str | None = None) -> float:
    sql, params = "SELECT COALESCE(SUM(cost_inr),0) AS s FROM fx_attempts WHERE 1=1", []
    if project_id:
        sql += " AND project_id=?"; params.append(project_id)
    if period:
        sql += " AND period=?"; params.append(period)
    if user_id:
        sql += " AND user_id=?"; params.append(user_id)
    if since:
        sql += " AND created_at>=?"; params.append(since)
    if tier:
        sql += " AND tier=?"; params.append(tier)
    row = _one(sql, tuple(params))
    return float(row["s"]) if row else 0.0


def spend_by_project(since: str) -> list[dict]:
    """Spend per project since a time, biggest first (the spike breaker uses it to pause ONE project, not everyone)."""
    return _all("""SELECT project_id, COALESCE(SUM(cost_inr),0) AS spend FROM fx_attempts WHERE created_at>=?
                   GROUP BY project_id ORDER BY spend DESC""", (since,))


def month_spend_by_user(period=None) -> list[dict]:
    return _all("""SELECT user_id, COALESCE(SUM(cost_inr),0) AS spend, COUNT(*) AS tries
                   FROM fx_attempts WHERE period=? GROUP BY user_id ORDER BY spend DESC""", (period or current_period(),))


def spend_by_tier(period=None) -> list[dict]:
    # `tries` counts real model attempts only. A provider or sandbox fault is not a try (it never counts against a quota), so it is
    # reported separately as `faults` instead of making a broken provider look like a lot of unsuccessful bug fixing.
    return _all("""SELECT tier, model,
                   COALESCE(SUM(CASE WHEN result<>'system_fault' THEN 1 ELSE 0 END),0) AS tries,
                   COALESCE(SUM(CASE WHEN result='system_fault' THEN 1 ELSE 0 END),0) AS faults,
                   COALESCE(SUM(cost_inr),0) AS spend,
                   COALESCE(SUM(tokens_in),0) AS tokens_in, COALESCE(SUM(tokens_out),0) AS tokens_out,
                   COALESCE(SUM(CASE WHEN result='pass' THEN 1 ELSE 0 END),0) AS passes
                   FROM fx_attempts WHERE period=? GROUP BY tier, model""", (period or current_period(),))


def success_stats() -> dict:
    """{(bug_class, cell): (successes, tries)} for the router's learning. Cell: tier, or 'haiku_diag'."""
    rows = _all("""SELECT bug_class, tier, used_strong_diag, COUNT(*) AS n,
                   SUM(CASE WHEN result='pass' THEN 1 ELSE 0 END) AS ok
                   FROM fx_attempts WHERE result IN ('pass','fail','unusable','no_progress') GROUP BY bug_class, tier, used_strong_diag""")
    out: dict = {}
    for r in rows:
        cell = "haiku_diag" if r["tier"] == "haiku" and r["used_strong_diag"] else r["tier"]
        key = (r["bug_class"], cell)
        ok, n = out.get(key, (0, 0))
        out[key] = (ok + int(r["ok"] or 0), n + int(r["n"]))
    return out


# ---- decisions, grants, admin actions, flags -------------------------------------------------------
def log_decision(bug_id, state: dict, options: list, chosen: str, reason: str) -> None:
    _run("INSERT INTO fx_router_decisions(id,bug_id,state_json,options_json,chosen,reason,created_at) VALUES(?,?,?,?,?,?,?)",
         (new_id(), bug_id, json.dumps(state, sort_keys=True, default=str), json.dumps(options, default=str),
          chosen, reason[:300], now()))


def list_decisions(bug_id) -> list[dict]:
    return _all("SELECT * FROM fx_router_decisions WHERE bug_id=? ORDER BY created_at ASC", (bug_id,))


def add_grant(user_id, tier, tries, source, note="", period=None) -> str:
    if source not in ("plan", "pack", "bonus", "admin", "topup"):          # v6: "topup" = rupees added to a bar
        raise ValueError("bad grant source")
    grant_id = new_id()
    _run("INSERT INTO fx_grants(id,user_id,period,tier,tries,source,note,created_at) VALUES(?,?,?,?,?,?,?,?)",
         (grant_id, user_id, period or current_period(), tier, int(tries), source, note[:300], now()))
    return grant_id


def grants_total(user_id, tier, source, period=None) -> int:
    row = _one("SELECT COALESCE(SUM(tries),0) AS n FROM fx_grants WHERE user_id=? AND tier=? AND source=? AND period=?",
               (user_id, tier, source, period or current_period()))
    return int(row["n"]) if row else 0


def log_admin_action(kind, user_id="", detail: dict | None = None) -> None:
    _run("INSERT INTO fx_admin_actions(id,kind,user_id,detail_json,created_at) VALUES(?,?,?,?,?)",
         (new_id(), kind, user_id, json.dumps(detail or {}, sort_keys=True, default=str), now()))


def list_admin_actions(limit=30) -> list[dict]:
    return _all("SELECT * FROM fx_admin_actions ORDER BY created_at DESC LIMIT ?", (limit,))


def get_flag(key, default="") -> str:
    row = _one("SELECT value FROM fx_flags WHERE key=?", (key,))
    return row["value"] if row else default


def set_flag(key, value) -> None:
    updated = _run("UPDATE fx_flags SET value=?,updated_at=? WHERE key=?", (str(value), now(), key))
    if not updated:
        _run("INSERT INTO fx_flags(key,value,updated_at) VALUES(?,?,?)", (key, str(value), now()))


def paused_tiers() -> set[str]:
    paused = {t for t in ("groq", "haiku", "sonnet", "opus") if get_flag(f"pause_{t}") == "1"}
    for provider, tiers in (("anthropic", ("haiku", "sonnet", "opus")), ("groq", ("groq",))):
        until = get_flag(f"outage_{provider}_until")
        if until and until > now():
            paused.update(tiers)
    return paused


# ---- user settings, choices, holds -------------------------------------------------------------------
def get_mode(user_id) -> str:
    row = _one("SELECT mode FROM fx_user_settings WHERE user_id=?", (user_id,))
    return row["mode"] if row else "auto"


def set_mode(user_id, mode) -> None:
    if mode not in ("auto", "ask", "economy"):
        raise ValueError("mode must be auto, ask or economy")
    if not _run("UPDATE fx_user_settings SET mode=?,updated_at=? WHERE user_id=?", (mode, now(), user_id)):
        _run("INSERT INTO fx_user_settings(user_id,mode,updated_at) VALUES(?,?,?)", (user_id, mode, now()))


def create_choice(bug_id, user_id, tier, message, wait_minutes: int | None) -> str:
    open_one = _one("SELECT id FROM fx_pending_choices WHERE bug_id=? AND status='waiting'", (bug_id,))
    if open_one:
        return open_one["id"]
    choice_id = new_id()
    expires = (_now_dt() + timedelta(minutes=wait_minutes)).isoformat(timespec="microseconds") if wait_minutes else None
    _run("INSERT INTO fx_pending_choices(id,bug_id,user_id,tier,message,expires_at,created_at) VALUES(?,?,?,?,?,?,?)",
         (choice_id, bug_id, user_id, tier, message[:500], expires, now()))
    return choice_id


def get_choice(choice_id):
    return _one("SELECT * FROM fx_pending_choices WHERE id=?", (choice_id,))


def waiting_choice_for_bug(bug_id):
    return _one("SELECT * FROM fx_pending_choices WHERE bug_id=? AND status='waiting'", (bug_id,))


def list_user_choices(user_id) -> list[dict]:
    return _all("SELECT * FROM fx_pending_choices WHERE user_id=? AND status='waiting' ORDER BY created_at", (user_id,))


def resolve_choice(choice_id, choice) -> bool:
    return bool(_run("UPDATE fx_pending_choices SET status='resolved',choice=?,resolved_at=? WHERE id=? AND status='waiting'",
                     (choice, now(), choice_id)))


def expired_choices() -> list[dict]:
    return _all("SELECT * FROM fx_pending_choices WHERE status='waiting' AND expires_at IS NOT NULL AND expires_at<=?", (now(),))


def create_hold(user_id, tier, tries, analysis: dict, status="held") -> str:
    hold_id = new_id()
    _run("INSERT INTO fx_holds(id,user_id,period,tier,tries_requested,status,analysis_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
         (hold_id, user_id, current_period(), tier, int(tries), status, json.dumps(analysis, sort_keys=True, default=str), now()))
    return hold_id


def get_hold(hold_id):
    return _one("SELECT * FROM fx_holds WHERE id=?", (hold_id,))


def open_hold(user_id, tier):
    return _one("SELECT * FROM fx_holds WHERE user_id=? AND tier=? AND period=? AND status='held'",
                (user_id, tier, current_period()))


def list_holds(status="held") -> list[dict]:
    return _all("SELECT * FROM fx_holds WHERE status=? ORDER BY created_at", (status,))


def resolve_hold(hold_id, status) -> bool:
    return bool(_run("UPDATE fx_holds SET status=?,resolved_at=? WHERE id=? AND status='held'", (status, now(), hold_id)))


# ---- incident / project plumbing used by the orchestrator -------------------------------------------------------------------
def get_project_row(project_id):
    return _one("SELECT id,user_id,name,repo_owner,repo_name,branch,mode,github_token_ciphertext,app_url FROM projects WHERE id=?", (project_id,))


def park_incident(incident_id, project_id, *, waiting_for_choice: bool, delay_seconds: int = 0) -> None:
    """Take an incident out of the worker's queue until a choice arrives, or put it back after a delay."""
    ts = now()
    conn = get_connection()
    try:
        if waiting_for_choice:
            _execute(conn, "UPDATE incidents SET status='awaiting_choice' WHERE id=? AND project_id=?", (incident_id, project_id))
            _execute(conn, "UPDATE incident_jobs SET status='waiting',locked_until=NULL,attempts=0,updated_at=? WHERE incident_id=?", (ts, incident_id))
        else:
            when = (_now_dt() + timedelta(seconds=delay_seconds)).isoformat(timespec="seconds")
            _execute(conn, "UPDATE incidents SET status='diagnosing' WHERE id=? AND project_id=?", (incident_id, project_id))
            _execute(conn, "UPDATE incident_jobs SET status='queued',locked_until=NULL,attempts=0,available_at=?,updated_at=? WHERE incident_id=?",
                     (when, ts, incident_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def unpark_incident(incident_id, project_id) -> None:
    park_incident(incident_id, project_id, waiting_for_choice=False, delay_seconds=0)


def block_automerge(incident_id) -> None:
    _run("UPDATE incidents SET no_automerge=1 WHERE id=?", (incident_id,))


def record_pr(incident_id, project_id, *, branch, file_path, diff, pr_url, pr_number, verification_text) -> None:
    ts = now()
    conn = get_connection()
    try:
        _execute(conn, "INSERT INTO fixes(id,incident_id,branch,file_path,diff,ci_result,created_at) VALUES(?,?,?,?,?,?,?)",
                 (new_id(), incident_id, branch, file_path[:500], diff[:50000], "pending", ts))
        _execute(conn, """UPDATE incidents SET status='pr_opened',pr_url=?,pr_number=?,ci_status='pending',
                          report=COALESCE(report,'') || ? WHERE id=? AND project_id=?""",
                 (pr_url, pr_number, "\n\nFix pull request opened: " + pr_url + ". " + verification_text, incident_id, project_id))
        _execute(conn, "INSERT INTO audit_log(id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                 (new_id(), project_id, "fix_pr_opened", json.dumps({"incident_id": incident_id, "pr_url": pr_url}, sort_keys=True), ts))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def incident_for_bug(bug_id):
    return _one("""SELECT b.id AS bug_id,b.incident_id,b.project_id,b.user_id,b.status AS bug_status,i.status AS incident_status
                   FROM fx_bugs b JOIN incidents i ON i.id=b.incident_id WHERE b.id=?""", (bug_id,))


def user_bugs(user_id, limit=20) -> list[dict]:
    return _all("""SELECT b.id,b.incident_id,b.status,b.stop_reason,b.bug_class,b.tries,b.spent_inr,b.pr_url,b.created_at,
                   b.review_report,p.name AS project_name
                   FROM fx_bugs b JOIN projects p ON p.id=b.project_id WHERE b.user_id=? ORDER BY b.created_at DESC LIMIT ?""",
                (user_id, limit))


def recover_pending(bug_id) -> int:
    """A worker that died mid-try leaves a 'pending' row. We hold the lease now, so restore that try (plan 18)."""
    return _run("""UPDATE fx_attempts SET result='system_fault',error_summary='worker interrupted before the try finished'
                   WHERE bug_id=? AND result='pending'""", (bug_id,))


def bonus_grants_count(user_id, tier, period=None) -> int:
    row = _one("SELECT COUNT(*) AS n FROM fx_grants WHERE user_id=? AND tier=? AND period=? AND source='bonus'",
               (user_id, tier, period or current_period()))
    return int(row["n"]) if row else 0


def paths_for_incidents(incident_ids) -> dict:
    """{incident_id: {"status": bug status, "tiers": [tier, ...] in order, counting only real tries}} for the incident cards."""
    ids = [str(i) for i in incident_ids if i]
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = _all(f"""SELECT b.incident_id AS incident_id, b.status AS status, a.tier AS tier, a.result AS result
                    FROM fx_bugs b LEFT JOIN fx_attempts a ON a.bug_id=b.id
                    WHERE b.incident_id IN ({marks}) ORDER BY a.created_at ASC, a.id ASC""", tuple(ids))
    out: dict = {}
    for r in rows:
        entry = out.setdefault(r["incident_id"], {"status": r["status"], "tiers": []})
        if r["tier"] and r["result"] not in ("system_fault", "pending"):
            entry["tiers"].append(r["tier"])
    return out


# ---- v3: the GitHub proof loop (state lives in fx_flags so no schema migration is needed) ----------------------------------
def bugs_by_status(status: str, limit: int = 50) -> list[dict]:
    return _all("SELECT * FROM fx_bugs WHERE status=? ORDER BY created_at ASC LIMIT ?", (status, limit))


def gh_state(bug_id) -> dict:
    try:
        data = json.loads(get_flag(f"gh:{bug_id}", "") or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def save_gh_state(bug_id, state: dict) -> None:
    set_flag(f"gh:{bug_id}", json.dumps(state, sort_keys=True)[:60000])


def record_direct_push(incident_id, project_id, *, branch, file_path, diff, head_sha, verification_text) -> None:
    """The fix is on the customer's tracked branch: store it like a merged fix and resolve the incident."""
    ts = now()
    conn = get_connection()
    try:
        _execute(conn, "INSERT INTO fixes(id,incident_id,branch,file_path,diff,ci_result,created_at) VALUES(?,?,?,?,?,?,?)",
                 (new_id(), incident_id, branch, (file_path or "")[:500], (diff or "")[:50000], "merged", ts))
        _execute(conn, "UPDATE incidents SET report=COALESCE(report,'') || ? WHERE id=? AND project_id=?",
                 ("\n\nFix pushed directly to your branch (commit " + str(head_sha)[:7] + "). " + verification_text, incident_id, project_id))
        _execute(conn, "INSERT INTO audit_log(id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                 (new_id(), project_id, "fix_pushed_direct", json.dumps({"incident_id": incident_id, "sha": head_sha}, sort_keys=True), ts))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    portal_db.update_portal_pr_status(incident_id, "merged", merged=True)


# ---- v3.1: the client's replies on a case (answers to the agent's question, "it still does not work on Psalms") ----------------
def add_client_reply(incident_id: str, text: str) -> list[str]:
    replies = client_replies(incident_id)
    replies.append(" ".join(str(text).split())[:1000])
    set_flag(f"replies:{incident_id}", json.dumps(replies[-10:]))
    return replies


def client_replies(incident_id: str) -> list[str]:
    try:
        data = json.loads(get_flag(f"replies:{incident_id}", "") or "[]")
        return [str(x) for x in data] if isinstance(data, list) else []
    except ValueError:
        return []
