"""Persistence for the multi-project Agent Daemon web application.

The same schema works with SQLite for local development and PostgreSQL in
hosted deployments. Set DATABASE_URL to a PostgreSQL URL in production.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  repo_owner TEXT NOT NULL,
  repo_name TEXT NOT NULL,
  branch TEXT NOT NULL DEFAULT 'main',
  mode TEXT NOT NULL DEFAULT 'pr',
  github_token_ciphertext TEXT NOT NULL,
  ingest_key_hash TEXT NOT NULL UNIQUE,
  app_url TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending_install',
  install_pr_url TEXT NOT NULL DEFAULT '',
  ai_consent_at TEXT NOT NULL DEFAULT '',
  paused INTEGER NOT NULL DEFAULT 0,
  active_until TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS log_events (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  timestamp TEXT NOT NULL,
  level TEXT NOT NULL,
  message TEXT NOT NULL,
  traceback TEXT NOT NULL DEFAULT '',
  signature TEXT NOT NULL,
  dedupe_hash TEXT NOT NULL,
  incident_id TEXT,
  UNIQUE(project_id, dedupe_hash)
);
CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  signature TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'diagnosing',
  category TEXT NOT NULL DEFAULT '',
  confidence TEXT NOT NULL DEFAULT '',
  occurrences INTEGER NOT NULL DEFAULT 1,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  root_cause TEXT NOT NULL DEFAULT '',
  report TEXT NOT NULL DEFAULT '',
  pr_url TEXT NOT NULL DEFAULT '',
  pr_number INTEGER,
  ci_status TEXT NOT NULL DEFAULT 'unknown',
  created_at TEXT NOT NULL,
  resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS incident_jobs (
  incident_id TEXT PRIMARY KEY REFERENCES incidents(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'queued',
  attempts INTEGER NOT NULL DEFAULT 0,
  available_at TEXT NOT NULL,
  locked_until TEXT,
  last_error TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fixes (
  id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  branch TEXT NOT NULL DEFAULT '',
  file_path TEXT NOT NULL DEFAULT '',
  diff TEXT NOT NULL DEFAULT '',
  ci_result TEXT NOT NULL DEFAULT 'pending',
  merged_at TEXT,
  reverted_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  razorpay_payment_id TEXT NOT NULL UNIQUE,
  amount INTEGER NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscriptions (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  active_until TEXT NOT NULL,
  grant_type TEXT NOT NULL DEFAULT 'paid',
  granted_by TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payment_orders (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  razorpay_order_id TEXT NOT NULL UNIQUE,
  amount INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'created',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
  attempt_key TEXT PRIMARY KEY,
  window_started TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ingest_limits (
  project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
  window_started TEXT NOT NULL,
  request_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_incidents_project_seen ON incidents(project_id, last_seen);
CREATE INDEX IF NOT EXISTS idx_log_events_project_time ON log_events(project_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_incident_jobs_ready ON incident_jobs(status, available_at, locked_until);
CREATE INDEX IF NOT EXISTS idx_audit_project_time ON audit_log(project_id, created_at);
CREATE TABLE IF NOT EXISTS trial_requests (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'pending',
  requested_at TEXT NOT NULL,
  reviewed_at TEXT NOT NULL DEFAULT '',
  reviewed_by TEXT NOT NULL DEFAULT '',
  decision_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_trial_requests_status ON trial_requests(status, requested_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id() -> str:
    return str(uuid.uuid4())


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def get_connection():
    """Open one short-lived connection; production must provide PostgreSQL."""
    url = _database_url()
    if url.startswith(("postgres://", "postgresql://")):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL support requires psycopg; install requirements.txt") from exc
        return psycopg.connect(url, row_factory=dict_row, connect_timeout=10)
    if os.getenv("APP_ENV", "development").lower() == "production":
        raise RuntimeError("DATABASE_URL must point to PostgreSQL in production")
    path = os.getenv("PORTAL_DB_PATH", "portal.db")
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _execute(conn, sql: str, params=()):
    if isinstance(conn, sqlite3.Connection):
        return conn.execute(sql, params)
    return conn.execute(sql.replace("?", "%s"), params)


def init_db() -> None:
    conn = get_connection()
    try:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                _execute(conn, statement)
        if isinstance(conn, sqlite3.Connection):
            columns = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
            if "install_pr_url" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN install_pr_url TEXT NOT NULL DEFAULT ''")
            if "ai_consent_at" not in columns:
                conn.execute("ALTER TABLE projects ADD COLUMN ai_consent_at TEXT NOT NULL DEFAULT ''")
        else:
            _execute(conn, "ALTER TABLE projects ADD COLUMN IF NOT EXISTS install_pr_url TEXT NOT NULL DEFAULT ''")
            _execute(conn, "ALTER TABLE projects ADD COLUMN IF NOT EXISTS ai_consent_at TEXT NOT NULL DEFAULT ''")
        if isinstance(conn, sqlite3.Connection):
            columns = {row[1] for row in conn.execute("PRAGMA table_info(subscriptions)").fetchall()}
            if "grant_type" not in columns:
                conn.execute("ALTER TABLE subscriptions ADD COLUMN grant_type TEXT NOT NULL DEFAULT 'paid'")
            if "granted_by" not in columns:
                conn.execute("ALTER TABLE subscriptions ADD COLUMN granted_by TEXT NOT NULL DEFAULT ''")
            order_columns = {row[1] for row in conn.execute("PRAGMA table_info(payment_orders)").fetchall()}
            if "plan" not in order_columns:
                conn.execute("ALTER TABLE payment_orders ADD COLUMN plan TEXT NOT NULL DEFAULT 'yearly'")
        else:
            _execute(conn, "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS grant_type TEXT NOT NULL DEFAULT 'paid'")
            _execute(conn, "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS granted_by TEXT NOT NULL DEFAULT ''")
            _execute(conn, "ALTER TABLE payment_orders ADD COLUMN IF NOT EXISTS plan TEXT NOT NULL DEFAULT 'yearly'")
        conn.commit()
    finally:
        conn.close()


def create_user(email: str, password_hash: str) -> str:
    user_id = _id()
    conn = get_connection()
    try:
        _execute(conn, "INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)",
                 (user_id, email.lower().strip(), password_hash, _now()))
        conn.commit()
        return user_id
    finally:
        conn.close()


def get_user_by_email(email: str):
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_session(user_id: str, csrf_token: str, expires_at: str) -> str:
    session_id = _id()
    conn = get_connection()
    try:
        _execute(conn, "INSERT INTO sessions(id,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",
                 (session_id, user_id, csrf_token, expires_at, _now()))
        conn.commit()
        return session_id
    finally:
        conn.close()


def get_session(session_id: str):
    conn = get_connection()
    try:
        row = _execute(conn,
            "SELECT s.*,u.email FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.expires_at>?",
            (session_id, _now())).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_session(session_id: str) -> None:
    conn = get_connection()
    try:
        _execute(conn, "DELETE FROM sessions WHERE id=?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def check_login_rate_limit(key: str, maximum: int = 8, window_seconds: int = 900) -> bool:
    """Return True when another login attempt is allowed for this key."""
    now = datetime.now(timezone.utc)
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT window_started,attempts FROM login_attempts WHERE attempt_key=?", (key,)).fetchone()
        if row:
            started = datetime.fromisoformat(row["window_started"])
            if (now - started).total_seconds() < window_seconds:
                if row["attempts"] >= maximum:
                    return False
                _execute(conn, "UPDATE login_attempts SET attempts=attempts+1 WHERE attempt_key=?", (key,))
            else:
                _execute(conn, "UPDATE login_attempts SET window_started=?,attempts=1 WHERE attempt_key=?", (now.isoformat(timespec="seconds"), key))
        else:
            _execute(conn, "INSERT INTO login_attempts(attempt_key,window_started,attempts) VALUES(?,?,1)",
                     (key, now.isoformat(timespec="seconds")))
        conn.commit()
        return True
    finally:
        conn.close()


def create_project(user_id: str, *, name: str, repo_owner: str, repo_name: str,
                   branch: str, mode: str, token_ciphertext: str, ingest_key_hash: str,
                   app_url: str = "", ai_consent_at: str = "") -> str:
    project_id = _id()
    conn = get_connection()
    try:
        subscription = _execute(conn, "SELECT active_until FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
        active_until = subscription["active_until"] if subscription else None
        _execute(conn, """INSERT INTO projects
          (id,user_id,name,repo_owner,repo_name,branch,mode,github_token_ciphertext,
           ingest_key_hash,app_url,active_until,created_at,ai_consent_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (project_id,user_id,name,repo_owner,repo_name,branch,mode,token_ciphertext,
           ingest_key_hash,app_url,active_until,_now(),ai_consent_at))
        conn.commit()
        return project_id
    finally:
        conn.close()


def get_project(project_id: str, user_id: str):
    """Every project read includes its owner in the query."""
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM projects WHERE id=? AND user_id=?", (project_id,user_id)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_projects(user_id: str):
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT * FROM projects WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_project_by_ingest_hash(key_hash: str):
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT id,user_id,name,repo_owner,repo_name,branch,mode,status,paused FROM projects WHERE ingest_key_hash=?", (key_hash,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_project_github_token(project_id: str, user_id: str, token_ciphertext: str) -> bool:
    """Replace a project's encrypted GitHub token for its owner."""
    conn = get_connection()
    try:
        cur = _execute(conn, "UPDATE projects SET github_token_ciphertext=? WHERE id=? AND user_id=?",
                       (token_ciphertext, project_id, user_id))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def rotate_project_ingest_key(project_id: str, user_id: str, key_hash: str) -> bool:
    conn = get_connection()
    try:
        cur = _execute(conn, "UPDATE projects SET ingest_key_hash=? WHERE id=? AND user_id=?",
                        (key_hash,project_id,user_id))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def delete_project(project_id: str, user_id: str) -> bool:
    conn = get_connection()
    try:
        cur = _execute(conn, "DELETE FROM projects WHERE id=? AND user_id=?", (project_id,user_id))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def set_project_connected(project_id: str) -> None:
    conn = get_connection()
    try:
        _execute(conn, "UPDATE projects SET status='connected' WHERE id=?", (project_id,))
        conn.commit()
    finally:
        conn.close()


def record_install_pr(project_id: str, user_id: str, pr_url: str) -> bool:
    conn = get_connection()
    try:
        cur = _execute(conn, "UPDATE projects SET status='install_pr_open',install_pr_url=? WHERE id=? AND user_id=?",
                       (pr_url, project_id, user_id))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def allow_ingest(project_id: str, maximum: int = 300, window_seconds: int = 60) -> bool:
    """Atomic per-project sliding window counter for the ingest endpoint."""
    now = datetime.now(timezone.utc)
    conn = get_connection()
    try:
        if isinstance(conn, sqlite3.Connection):
            conn.execute("BEGIN IMMEDIATE")
        _execute(conn, "INSERT INTO ingest_limits(project_id,window_started,request_count) VALUES(?,?,0) ON CONFLICT(project_id) DO NOTHING",
                 (project_id,now.isoformat(timespec="seconds")))
        lock = " FOR UPDATE" if not isinstance(conn, sqlite3.Connection) else ""
        row = _execute(conn, "SELECT window_started,request_count FROM ingest_limits WHERE project_id=?" + lock,
                       (project_id,)).fetchone()
        if not row:
            conn.rollback()
            return False
        started = datetime.fromisoformat(row["window_started"])
        count = int(row["request_count"])
        if (now - started).total_seconds() >= window_seconds:
            _execute(conn, "UPDATE ingest_limits SET window_started=?,request_count=1 WHERE project_id=?",
                     (now.isoformat(timespec="seconds"),project_id))
            allowed = True
        elif count >= maximum:
            allowed = False
        else:
            _execute(conn, "UPDATE ingest_limits SET request_count=request_count+1 WHERE project_id=?", (project_id,))
            allowed = True
        conn.commit()
        return allowed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ingest_event(project_id: str, *, timestamp: str, level: str, message: str,
                 traceback: str = "", signature: str = "unknown") -> tuple[str | None, bool]:
    """Deduplicate and attach an event to a project-scoped open incident."""
    digest = hashlib.sha256("\0".join((timestamp, level, message, traceback)).encode("utf-8")).hexdigest()
    conn = get_connection()
    try:
        event_id = _id()
        cur = _execute(conn, """INSERT INTO log_events
          (id,project_id,timestamp,level,message,traceback,signature,dedupe_hash)
          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id,dedupe_hash) DO NOTHING""",
          (event_id,project_id,timestamp,level,message,traceback,signature,digest))
        if cur.rowcount == 0:
            conn.commit()
            return None, False
        row = _execute(conn, """SELECT id,occurrences,status,last_seen FROM incidents
          WHERE project_id=? AND signature=? AND status NOT IN ('resolved','reverted')
          ORDER BY created_at DESC LIMIT 1""", (project_id,signature)).fetchone()
        if row:
            incident_id = row["id"]
            reopened = False
            if row["status"] in ("diagnosed", "needs_human"):
                try:
                    previous = datetime.fromisoformat(row["last_seen"])
                    current = datetime.fromisoformat(timestamp)
                    if previous.tzinfo is None:
                        previous = previous.replace(tzinfo=timezone.utc)
                    if current.tzinfo is None:
                        current = current.replace(tzinfo=timezone.utc)
                    reopened = (current - previous).total_seconds() > 60
                except (TypeError, ValueError):
                    reopened = False
            if reopened:
                _execute(conn, """UPDATE incidents SET status='diagnosing',category='',confidence='',occurrences=1,
                  first_seen=?,last_seen=?,root_cause='',report='',ci_status='unknown'
                  WHERE id=? AND project_id=?""", (timestamp,timestamp,incident_id,project_id))
                _execute(conn, """INSERT INTO incident_jobs(incident_id,status,attempts,available_at,locked_until,last_error,updated_at)
                  VALUES(?,?,?,?,NULL,'',?) ON CONFLICT(incident_id) DO UPDATE SET
                  status='queued',attempts=0,available_at=excluded.available_at,locked_until=NULL,last_error='',updated_at=excluded.updated_at""",
                  (incident_id,"queued",0,_now(),_now()))
            else:
                _execute(conn, "UPDATE incidents SET occurrences=occurrences+1,last_seen=? WHERE id=? AND project_id=?",
                         (timestamp,incident_id,project_id))
        else:
            incident_id = _id()
            _execute(conn, """INSERT INTO incidents
              (id,project_id,signature,first_seen,last_seen,created_at)
              VALUES(?,?,?,?,?,?)""", (incident_id,project_id,signature,timestamp,timestamp,_now()))
        _execute(conn, "UPDATE log_events SET incident_id=? WHERE id=? AND project_id=?",
                 (incident_id,event_id,project_id))
        _execute(conn, "INSERT INTO incident_jobs(incident_id,status,available_at,updated_at) VALUES(?,?,?,?) ON CONFLICT(incident_id) DO NOTHING",
                 (incident_id,"queued",_now(),_now()))
        conn.commit()
        return incident_id, True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_incidents(project_id: str, limit: int = 100):
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT * FROM incidents WHERE project_id=? ORDER BY last_seen DESC LIMIT ?",
                        (project_id,limit)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def claim_next_incident(*, min_occurrences: int = 5, min_age_seconds: int = 30,
                        lease_seconds: int = 600, max_attempts: int = 3):
    """Claim one eligible, subscribed project's diagnosis job with a lease."""
    now = datetime.now(timezone.utc)
    now_s = now.isoformat(timespec="seconds")
    eligible_before = (now - timedelta(seconds=min_age_seconds)).isoformat(timespec="seconds")
    lease_until = (now + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        if isinstance(conn, sqlite3.Connection):
            conn.execute("BEGIN IMMEDIATE")
            lock_clause = ""
        else:
            lock_clause = " FOR UPDATE OF j SKIP LOCKED"
        exhausted = _execute(conn, """SELECT j.incident_id,i.project_id FROM incident_jobs j
          JOIN incidents i ON i.id=j.incident_id
          WHERE j.status='processing' AND j.locked_until<=? AND j.attempts>=? AND i.status='processing'""" + lock_clause,
          (now_s,max_attempts)).fetchall()
        for stale in exhausted:
            detail = json.dumps({"incident_id":stale["incident_id"],"error":"Worker lease expired after max attempts","terminal":True},sort_keys=True)
            _execute(conn, "UPDATE incident_jobs SET status='failed',locked_until=NULL,last_error=?,updated_at=? WHERE incident_id=?",
                     ("Worker lease expired after max attempts",now_s,stale["incident_id"]))
            _execute(conn, "UPDATE incidents SET status='needs_human' WHERE id=? AND project_id=? AND status='processing'",
                     (stale["incident_id"],stale["project_id"]))
            _execute(conn, "INSERT INTO audit_log(id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                     (_id(),stale["project_id"],"diagnosis_failed",detail,now_s))
        row = _execute(conn, """SELECT j.incident_id,j.attempts,i.project_id,i.signature,i.occurrences,
                    i.first_seen,i.last_seen,p.repo_owner,p.repo_name,p.branch,p.mode,
                    p.github_token_ciphertext,p.active_until,p.paused,p.ai_consent_at
          FROM incident_jobs j
          JOIN incidents i ON i.id=j.incident_id
          JOIN projects p ON p.id=i.project_id
          WHERE i.status IN ('diagnosing','queued','processing') AND i.occurrences>=? AND i.first_seen<=?
            AND p.paused=0 AND p.ai_consent_at<>'' AND p.active_until>? AND j.attempts<?
            AND ((j.status='queued' AND j.available_at<=?)
              OR (j.status='processing' AND j.locked_until<=?))
          ORDER BY i.first_seen ASC LIMIT 1""" + lock_clause,
          (min_occurrences,eligible_before,now_s,max_attempts,now_s,now_s)).fetchone()
        if not row:
            conn.commit()
            return None
        incident_id = row["incident_id"]
        _execute(conn, "UPDATE incident_jobs SET status='processing',attempts=attempts+1,locked_until=?,updated_at=? WHERE incident_id=?",
                 (lease_until,now_s,incident_id))
        _execute(conn, "UPDATE incidents SET status='processing' WHERE id=? AND project_id=?",
                 (incident_id,row["project_id"]))
        event = _execute(conn, """SELECT message,traceback,timestamp FROM log_events
          WHERE project_id=? AND incident_id=? AND timestamp>=? ORDER BY timestamp ASC LIMIT 1""",
          (row["project_id"],incident_id,row["first_seen"])).fetchone()
        conn.commit()
        claimed = dict(row)
        claimed["first_event"] = dict(event) if event else None
        return claimed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def complete_diagnosis(incident_id: str, project_id: str, result: dict) -> bool:
    """Save diagnosis and mark only this project's job complete."""
    conn = get_connection()
    now = _now()
    try:
        cur = _execute(conn, """UPDATE incidents SET status='diagnosed',category=?,confidence=?,
          root_cause=?,report=? WHERE id=? AND project_id=? AND status='processing'""",
          (str(result.get("category", "unknown"))[:80],str(result.get("confidence", "low"))[:20],
           str(result.get("root_cause", ""))[:4000],str(result.get("report", ""))[:30000],incident_id,project_id))
        if cur.rowcount != 1:
            conn.rollback()
            return False
        _execute(conn, "UPDATE incident_jobs SET status='done',locked_until=NULL,last_error='',updated_at=? WHERE incident_id=?",
                 (now,incident_id))
        _execute(conn, "INSERT INTO audit_log(id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                 (_id(),project_id,"incident_diagnosed",json.dumps({"incident_id":incident_id},sort_keys=True),now))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fail_diagnosis(incident_id: str, project_id: str, error: str, *, retry_delay_seconds: int = 60,
                   max_attempts: int = 3) -> None:
    """Retry transient worker failures without persisting credentials or tracebacks."""
    conn = get_connection()
    now = datetime.now(timezone.utc)
    try:
        row = _execute(conn, "SELECT attempts FROM incident_jobs WHERE incident_id=?", (incident_id,)).fetchone()
        if not row:
            return
        terminal = int(row["attempts"]) >= max_attempts
        status = "failed" if terminal else "queued"
        next_at = now if terminal else now + timedelta(seconds=retry_delay_seconds)
        safe_error = str(error).replace("\n", " ")[:500]
        _execute(conn, "UPDATE incident_jobs SET status=?,available_at=?,locked_until=NULL,last_error=?,updated_at=? WHERE incident_id=?",
                 (status,next_at.isoformat(timespec="seconds"),safe_error,now.isoformat(timespec="seconds"),incident_id))
        _execute(conn, "UPDATE incidents SET status=? WHERE id=? AND project_id=? AND status='processing'",
                 ("needs_human" if terminal else "diagnosing",incident_id,project_id))
        _execute(conn, "INSERT INTO audit_log(id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                 (_id(),project_id,"diagnosis_failed",json.dumps({"incident_id":incident_id,"error":safe_error,"terminal":terminal},sort_keys=True),now.isoformat(timespec="seconds")))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def record_remediation(incident_id: str, project_id: str, *, branch: str, file_path: str,
                       diff: str, pr_url: str, pr_number: int, ci_status: str = "pending") -> None:
    """Persist a reviewable fix diff and its GitHub pull request."""
    conn = get_connection()
    now = _now()
    try:
        _execute(conn, "INSERT INTO fixes(id,incident_id,branch,file_path,diff,ci_result,created_at) VALUES(?,?,?,?,?,?,?)",
                 (_id(), incident_id, branch, file_path, diff[:50000], ci_status, now))
        _execute(conn, """UPDATE incidents SET status='pr_opened',pr_url=?,pr_number=?,ci_status=?,
                          report=COALESCE(report,'') || ? WHERE id=? AND project_id=?""",
                 (pr_url, pr_number, ci_status,
                  "\\n\\nFix pull request opened: " + pr_url + ". Customer code and tests were not run.",
                  incident_id, project_id))
        _execute(conn, "INSERT INTO audit_log(id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                 (_id(), project_id, "fix_pr_opened", json.dumps({"incident_id":incident_id,"pr_url":pr_url},sort_keys=True), now))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def mark_remediation_needs_human(incident_id: str, project_id: str, reason: str) -> None:
    """Keep diagnosis available while recording that no safe PR was created."""
    conn = get_connection()
    now = _now()
    safe_reason = str(reason).replace("\\n", " ")[:400]
    try:
        _execute(conn, "UPDATE incidents SET status='needs_human',report=COALESCE(report,'') || ? WHERE id=? AND project_id=?",
                 ("\\n\\nNo fix PR was created: " + safe_reason, incident_id, project_id))
        _execute(conn, "INSERT INTO audit_log(id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                 (_id(), project_id, "fix_pr_not_created", json.dumps({"incident_id":incident_id,"reason":safe_reason},sort_keys=True), now))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_auto_prs(limit: int = 20):
    """List auto-mode PRs that still need a CI check or merge attempt."""
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT i.id AS incident_id,i.project_id,i.pr_number,i.ci_status,
                    p.repo_owner,p.repo_name,p.github_token_ciphertext
          FROM incidents i JOIN projects p ON p.id=i.project_id
          WHERE p.mode='auto' AND p.paused=0 AND i.status='pr_opened'
            AND i.pr_number IS NOT NULL AND i.ci_status IN ('pending','unknown','unavailable','success')
          ORDER BY i.created_at ASC LIMIT ?""", (max(1,min(int(limit),100)),)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_portal_pr_status(incident_id: str, ci_status: str, *, merged: bool = False) -> None:
    """Update CI state; resolve an incident only after GitHub confirms a merge."""
    allowed = {"pending","success","failed","no_checks","merged","unavailable"}
    if ci_status not in allowed:
        raise ValueError("Invalid CI status")
    conn = get_connection()
    now = _now()
    try:
        if merged:
            _execute(conn, "UPDATE incidents SET ci_status='merged',status='resolved',resolved_at=? WHERE id=?",
                     (now,incident_id))
            _execute(conn, "UPDATE fixes SET ci_result='merged',merged_at=? WHERE incident_id=?",
                     (now,incident_id))
        else:
            _execute(conn, "UPDATE incidents SET ci_status=? WHERE id=?", (ci_status,incident_id))
            _execute(conn, "UPDATE fixes SET ci_result=? WHERE incident_id=? AND merged_at IS NULL",
                     (ci_status,incident_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def audit(project_id: str, action: str, detail: dict | None = None) -> None:
    conn = get_connection()
    try:
        _execute(conn,"INSERT INTO audit_log(id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                 (_id(),project_id,action,json.dumps(detail or {},sort_keys=True),_now()))
        conn.commit()
    finally:
        conn.close()


def create_payment_order(user_id: str, order_id: str, amount: int, plan: str = "yearly") -> None:
    if plan not in ("monthly", "yearly"):
        raise ValueError("Plan must be monthly or yearly")
    conn = get_connection()
    try:
        _execute(conn, "INSERT INTO payment_orders(id,user_id,razorpay_order_id,amount,status,created_at,plan) VALUES(?,?,?,?,?,?,?)",
                 (_id(),user_id,order_id,amount,"created",_now(),plan))
        conn.commit()
    finally:
        conn.close()


def complete_payment_order(order_id: str, payment_id: str, amount: int) -> bool:
    """Record a verified capture once and extend only that user's projects."""
    conn = get_connection()
    try:
        order = _execute(conn, "SELECT user_id,amount,status,plan FROM payment_orders WHERE razorpay_order_id=?", (order_id,)).fetchone()
        if not order or int(order["amount"]) != int(amount) or order["status"] == "paid":
            return False
        now = datetime.now(timezone.utc)
        subscription = _execute(conn, "SELECT active_until FROM subscriptions WHERE user_id=?", (order["user_id"],)).fetchone()
        existing_until = datetime.fromisoformat(subscription["active_until"]) if subscription else now
        if existing_until.tzinfo is None:
            existing_until = existing_until.replace(tzinfo=timezone.utc)
        until = (max(now, existing_until) + timedelta(days=30 if order["plan"] == "monthly" else 365)).isoformat(timespec="seconds")
        cur = _execute(conn, "INSERT INTO payments(id,user_id,razorpay_payment_id,amount,status,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(razorpay_payment_id) DO NOTHING",
                       (_id(),order["user_id"],payment_id,int(amount),"captured",now.isoformat(timespec="seconds")))
        if cur.rowcount == 0:
            conn.commit()
            return False
        _execute(conn, "UPDATE payment_orders SET status='paid' WHERE razorpay_order_id=?", (order_id,))
        _execute(conn, "INSERT INTO subscriptions(user_id,active_until,grant_type,granted_by,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET active_until=excluded.active_until,grant_type='paid',granted_by='',updated_at=excluded.updated_at",
                 (order["user_id"],until,"paid","",now.isoformat(timespec="seconds")))
        _execute(conn, "UPDATE projects SET active_until=? WHERE user_id=?", (until,order["user_id"]))
        project_rows = _execute(conn, "SELECT id FROM projects WHERE user_id=?", (order["user_id"],)).fetchall()
        detail = json.dumps({"payment_id":payment_id,"active_until":until})
        for project in project_rows:
            _execute(conn, "INSERT INTO audit_log(id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                     (_id(),project["id"],"subscription_activated",detail,now.isoformat(timespec="seconds")))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_subscription_active_until(user_id: str):
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT active_until FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
        return row["active_until"] if row else None
    finally:
        conn.close()


def user_has_active_access(user_id: str) -> bool:
    active_until = get_subscription_active_until(user_id)
    return bool(active_until and active_until > _now())


def admin_list_users():
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT u.id,u.email,u.created_at,s.active_until,
            COALESCE(s.grant_type,'') AS grant_type
            FROM users u LEFT JOIN subscriptions s ON s.user_id=u.id
            ORDER BY u.created_at DESC""").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def admin_grant_access(user_id: str, days: int, grant_type: str, granted_by: str) -> str:
    if not 1 <= int(days) <= 3650 or grant_type not in ("trial", "paid"):
        raise ValueError("Access grant must be 1–3650 days and trial or paid")
    now = datetime.now(timezone.utc)
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT active_until FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
        existing = datetime.fromisoformat(row["active_until"]) if row else now
        if existing.tzinfo is None:
            existing = existing.replace(tzinfo=timezone.utc)
        until = (max(now, existing) + timedelta(days=int(days))).isoformat(timespec="seconds")
        _execute(conn, """INSERT INTO subscriptions(user_id,active_until,grant_type,granted_by,updated_at)
            VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
            active_until=excluded.active_until,grant_type=excluded.grant_type,
            granted_by=excluded.granted_by,updated_at=excluded.updated_at""",
            (user_id, until, grant_type, granted_by, now.isoformat(timespec="seconds")))
        _execute(conn, "UPDATE projects SET active_until=? WHERE user_id=?", (until, user_id))
        conn.commit()
        return until
    finally:
        conn.close()


def admin_revoke_access(user_id: str) -> bool:
    conn = get_connection()
    try:
        cur = _execute(conn, "DELETE FROM subscriptions WHERE user_id=?", (user_id,))
        _execute(conn, "UPDATE projects SET active_until=NULL,paused=1 WHERE user_id=?", (user_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()



def create_trial_request(user_id: str) -> dict:
    """Create one pending trial request per customer; return its current record."""
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM trial_requests WHERE user_id=? AND status='pending' ORDER BY requested_at DESC LIMIT 1", (user_id,)).fetchone()
        if row:
            return dict(row)
        request_id = _id()
        now = _now()
        _execute(conn, "INSERT INTO trial_requests(id,user_id,status,requested_at) VALUES(?,?,?,?)",
                 (request_id, user_id, "pending", now))
        conn.commit()
        row = _execute(conn, "SELECT * FROM trial_requests WHERE id=?", (request_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def admin_list_trial_requests():
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT tr.*,u.email FROM trial_requests tr
            JOIN users u ON u.id=tr.user_id
            ORDER BY CASE WHEN tr.status='pending' THEN 0 ELSE 1 END, tr.requested_at DESC""").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def admin_review_trial_request(request_id: str, status: str, reviewed_by: str, note: str = "") -> dict | None:
    if status not in ("approved", "rejected"):
        raise ValueError("Trial request status must be approved or rejected")
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM trial_requests WHERE id=?", (request_id,)).fetchone()
        if not row or row["status"] != "pending":
            return None
        now = _now()
        _execute(conn, """UPDATE trial_requests SET status=?,reviewed_at=?,reviewed_by=?,decision_note=?
            WHERE id=? AND status='pending'""", (status, now, reviewed_by, note[:500], request_id))
        conn.commit()
        updated = _execute(conn, "SELECT tr.*,u.email FROM trial_requests tr JOIN users u ON u.id=tr.user_id WHERE tr.id=?", (request_id,)).fetchone()
        return dict(updated) if updated else None
    finally:
        conn.close()
