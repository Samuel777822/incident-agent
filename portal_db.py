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
  name TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  referral_source TEXT NOT NULL DEFAULT '',
  organization TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL DEFAULT '',
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
  ci_workflow TEXT NOT NULL DEFAULT '',
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

CREATE TABLE IF NOT EXISTS manual_payments (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount INTEGER NOT NULL,
  plan TEXT NOT NULL,
  transaction_ref TEXT NOT NULL,
  ref_norm TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  referral_source TEXT NOT NULL DEFAULT '',
  organization TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  reviewed_at TEXT NOT NULL DEFAULT '',
  reviewed_by TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_manual_payments_status ON manual_payments(status, created_at);

CREATE TABLE IF NOT EXISTS trial_requests (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  referral_source TEXT NOT NULL DEFAULT '',
  organization TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  requested_at TEXT NOT NULL,
  reviewed_at TEXT NOT NULL DEFAULT '',
  reviewed_by TEXT NOT NULL DEFAULT '',
  decision_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_trial_requests_status ON trial_requests(status, requested_at);

CREATE TABLE IF NOT EXISTS notification_log (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  recipient TEXT NOT NULL,
  subject TEXT NOT NULL,
  ok INTEGER NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_notification_log_time ON notification_log(created_at);

CREATE TABLE IF NOT EXISTS worker_status (
  name TEXT PRIMARY KEY,
  last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_conversations (
  id TEXT PRIMARY KEY,
  visitor_id TEXT NOT NULL,
  visitor_name TEXT NOT NULL DEFAULT '',
  visitor_email TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_conv_visitor ON chat_conversations(visitor_id);
CREATE INDEX IF NOT EXISTS idx_chat_conv_updated ON chat_conversations(updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
  sender TEXT NOT NULL,
  sender_name TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_msg_conv_time ON chat_messages(conversation_id, created_at ASC);

CREATE TABLE IF NOT EXISTS visitor_tracking (
  visitor_id TEXT PRIMARY KEY,
  first_seen TEXT NOT NULL,
  last_notified TEXT NOT NULL,
  visit_count INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS support_messages (
  id TEXT PRIMARY KEY,
  ticket_ref TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  subject TEXT NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  assigned_to TEXT NOT NULL DEFAULT '',
  resolution_note TEXT NOT NULL DEFAULT '',
  closed_at TEXT NOT NULL DEFAULT '',
  closed_by TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_support_messages_time ON support_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_support_messages_status ON support_messages(status, created_at DESC);

CREATE TABLE IF NOT EXISTS java_waitlist (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  consent INTEGER NOT NULL DEFAULT 1,
  source TEXT NOT NULL DEFAULT 'homepage_banner',
  created_at TEXT NOT NULL,
  notification_sent INTEGER NOT NULL DEFAULT 0,
  notification_sent_at TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'subscribed',
  unsubscribe_token TEXT NOT NULL DEFAULT '',
  delivery_error TEXT NOT NULL DEFAULT '',
  attempt_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_java_waitlist_email ON java_waitlist(email);
CREATE INDEX IF NOT EXISTS idx_java_waitlist_status ON java_waitlist(status, notification_sent);

CREATE TABLE IF NOT EXISTS banner_analytics (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_banner_analytics_event ON banner_analytics(event_type, created_at DESC);
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
        # Safe, repeatable migrations for databases created by older versions.
        additions = [
            ("users", "name", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "install_pr_url", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "ci_workflow", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "ai_consent_at", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "last_heartbeat_at", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "ingest_key_ciphertext", "TEXT NOT NULL DEFAULT ''"),
            ("subscriptions", "grant_type", "TEXT NOT NULL DEFAULT 'paid'"),
            ("subscriptions", "granted_by", "TEXT NOT NULL DEFAULT ''"),
            ("payment_orders", "plan", "TEXT NOT NULL DEFAULT 'yearly'"),
            ("manual_payments", "ref_norm", "TEXT NOT NULL DEFAULT ''"),
            ("users", "phone", "TEXT NOT NULL DEFAULT ''"),
            ("users", "referral_source", "TEXT NOT NULL DEFAULT ''"),
            ("users", "organization", "TEXT NOT NULL DEFAULT ''"),
            ("trial_requests", "name", "TEXT NOT NULL DEFAULT ''"),
            ("trial_requests", "phone", "TEXT NOT NULL DEFAULT ''"),
            ("trial_requests", "referral_source", "TEXT NOT NULL DEFAULT ''"),
            ("trial_requests", "organization", "TEXT NOT NULL DEFAULT ''"),
            ("support_messages", "ticket_ref", "TEXT NOT NULL DEFAULT ''"),
            ("support_messages", "assigned_to", "TEXT NOT NULL DEFAULT ''"),
            ("support_messages", "resolution_note", "TEXT NOT NULL DEFAULT ''"),
            ("support_messages", "closed_at", "TEXT NOT NULL DEFAULT ''"),
            ("support_messages", "closed_by", "TEXT NOT NULL DEFAULT ''"),
            ("support_messages", "updated_at", "TEXT NOT NULL DEFAULT ''"),
            ("java_waitlist", "consent", "INTEGER NOT NULL DEFAULT 1"),
            ("java_waitlist", "source", "TEXT NOT NULL DEFAULT 'homepage_banner'"),
            ("java_waitlist", "notification_sent", "INTEGER NOT NULL DEFAULT 0"),
            ("java_waitlist", "notification_sent_at", "TEXT NOT NULL DEFAULT ''"),
            ("java_waitlist", "status", "TEXT NOT NULL DEFAULT 'subscribed'"),
            ("java_waitlist", "unsubscribe_token", "TEXT NOT NULL DEFAULT ''"),
            ("java_waitlist", "delivery_error", "TEXT NOT NULL DEFAULT ''"),
            ("java_waitlist", "attempt_count", "INTEGER NOT NULL DEFAULT 0"),
            ("manual_payments", "name", "TEXT NOT NULL DEFAULT ''"),
            ("manual_payments", "phone", "TEXT NOT NULL DEFAULT ''"),
            ("manual_payments", "referral_source", "TEXT NOT NULL DEFAULT ''"),
            ("manual_payments", "organization", "TEXT NOT NULL DEFAULT ''"),
        ]
        for table, column, ddl in additions:
            if isinstance(conn, sqlite3.Connection):
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                if column not in columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            else:
                _execute(conn, f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}")
        conn.commit()
        try:
            _execute(conn, "CREATE UNIQUE INDEX IF NOT EXISTS idx_manual_payments_ref "
                           "ON manual_payments(ref_norm) WHERE ref_norm <> ''")
            conn.commit()
        except Exception:
            conn.rollback()
    finally:
        conn.close()


def create_user(email: str, password_hash: str, name: str = "") -> str:
    user_id = _id()
    conn = get_connection()
    try:
        _execute(conn, "INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)",
                 (user_id, email.lower().strip(), name.strip(), password_hash, _now()))
        conn.commit()
        return user_id
    finally:
        conn.close()


def update_user_name(user_id: str, name: str) -> None:
    conn = get_connection()
    try:
        _execute(conn, "UPDATE users SET name=? WHERE id=?", (name.strip(), user_id))
        conn.commit()
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> dict | None:
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_user_details(user_id: str, name: str = "", phone: str = "", referral_source: str = "", organization: str = "") -> None:
    conn = get_connection()
    try:
        current = _execute(conn, "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not current:
            return
        c_keys = current.keys() if hasattr(current, "keys") else []
        new_name = name.strip() or (current["name"] if "name" in c_keys and current["name"] else "")
        new_phone = phone.strip() or (current["phone"] if "phone" in c_keys and current["phone"] else "")
        new_ref = referral_source.strip() or (current["referral_source"] if "referral_source" in c_keys and current["referral_source"] else "")
        new_org = organization.strip() or (current["organization"] if "organization" in c_keys and current["organization"] else "")
        _execute(conn, "UPDATE users SET name=?, phone=?, referral_source=?, organization=? WHERE id=?",
                 (new_name, new_phone, new_ref, new_org, user_id))
        conn.commit()
    finally:
        conn.close()


def get_or_create_google_user(email: str, google_sub: str, email_verified: bool, name: str = "") -> dict:
    email = email.lower().strip()
    if not email or not google_sub or not email_verified:
        raise ValueError('A verified Google identity is required')
    name = (name or "").strip()
    # Use the verified Google subject as the internal ID to avoid altering existing production schema.
    conn = get_connection()
    try:
        row = _execute(conn, 'SELECT * FROM users WHERE id=?', (google_sub,)).fetchone()
        if row:
            if row['email'].lower() != email:
                raise ValueError('This Google account email changed. Contact support to update it safely.')
            if name and not row['name']:
                _execute(conn, 'UPDATE users SET name=? WHERE id=?', (name, google_sub))
                conn.commit()
                row = _execute(conn, 'SELECT * FROM users WHERE id=?', (google_sub,)).fetchone()
            return dict(row)
        by_email = _execute(conn, 'SELECT * FROM users WHERE email=?', (email,)).fetchone()
        if by_email:
            # Google has verified this address, so the person owns it. Sign in to the existing account
            # (keeping its id, projects and billing) instead of refusing, which used to lock people out.
            if name and not by_email['name']:
                _execute(conn, 'UPDATE users SET name=? WHERE id=?', (name, by_email['id']))
                conn.commit()
                by_email = _execute(conn, 'SELECT * FROM users WHERE id=?', (by_email['id'],)).fetchone()
            return dict(by_email)
        _execute(conn, 'INSERT INTO users(id,email,name,password_hash,created_at) VALUES(?,?,?,?,?)', (google_sub, email, name, '', _now()))
        conn.commit()
        return dict(_execute(conn, 'SELECT * FROM users WHERE id=?', (google_sub,)).fetchone())
    finally:
        conn.close()


def get_user_by_google_sub(google_sub: str):
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM users WHERE id = ?", (google_sub,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_email(email: str):
    conn = get_connection()
    try:
        row = _execute(conn, 'SELECT * FROM users WHERE email = ?', (email.lower().strip(),)).fetchone()
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
            "SELECT s.*,u.email,u.name FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.id=? AND s.expires_at>?",
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
                   app_url: str = "", ai_consent_at: str = "", ingest_key_ciphertext: str = "") -> str:
    project_id = _id()
    conn = get_connection()
    try:
        subscription = _execute(conn, "SELECT active_until FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
        active_until = subscription["active_until"] if subscription else None
        _execute(conn, """INSERT INTO projects
          (id,user_id,name,repo_owner,repo_name,branch,mode,github_token_ciphertext,
           ingest_key_hash,app_url,active_until,created_at,ai_consent_at,ingest_key_ciphertext)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (project_id,user_id,name,repo_owner,repo_name,branch,mode,token_ciphertext,
           ingest_key_hash,app_url,active_until,_now(),ai_consent_at,ingest_key_ciphertext))
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


def rotate_project_ingest_key(project_id: str, user_id: str, key_hash: str, key_ciphertext: str = "") -> bool:
    conn = get_connection()
    try:
        cur = _execute(conn, "UPDATE projects SET ingest_key_hash=?,ingest_key_ciphertext=? WHERE id=? AND user_id=?",
                        (key_hash, key_ciphertext, project_id, user_id))
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
    """Mark a project connected and remember when it last checked in."""
    conn = get_connection()
    try:
        _execute(conn, "UPDATE projects SET status='connected',last_heartbeat_at=? WHERE id=?",
                 (_now(), project_id))
        conn.commit()
    finally:
        conn.close()


def record_install_pr(project_id: str, user_id: str, pr_url: str, ci_workflow: str = "") -> bool:
    """ci_workflow: 'added', 'existing' or 'missing' (no test workflow could be added, so Auto mode cannot merge)."""
    conn = get_connection()
    try:
        cur = _execute(conn, "UPDATE projects SET status='install_pr_open',install_pr_url=?,ci_workflow=? WHERE id=? AND user_id=?",
                       (pr_url, ci_workflow, project_id, user_id))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def set_ci_workflow(project_id: str, user_id: str, ci_workflow: str) -> bool:
    conn = get_connection()
    try:
        cur = _execute(conn, "UPDATE projects SET ci_workflow=? WHERE id=? AND user_id=?", (ci_workflow, project_id, user_id))
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
            AND i.pr_number IS NOT NULL AND i.ci_status IN ('pending','unknown','unavailable','success','no_checks')
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
        _execute(conn, "UPDATE projects SET paused=0 WHERE user_id=? AND paused=2", (order["user_id"],))
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
        rows = _execute(conn, """SELECT u.id,u.email,u.name,u.phone,u.referral_source,u.organization,u.created_at,s.active_until,
            COALESCE(s.grant_type,'') AS grant_type
            FROM users u LEFT JOIN subscriptions s ON s.user_id=u.id
            ORDER BY u.created_at DESC""").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _grant_in_conn(conn, user_id: str, days: int, grant_type: str, granted_by: str) -> str:
    """Extend (never replace) access inside the caller's transaction.

    A paid plan is never downgraded to "trial" by a later trial grant.
    """
    now = datetime.now(timezone.utc)
    row = _execute(conn, "SELECT active_until,grant_type FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
    existing = _parse_ts(row["active_until"]) if row else None
    active = bool(existing and existing > now)
    base = existing if active else now
    until = (base + timedelta(days=int(days))).isoformat(timespec="seconds")
    final_type = "paid" if grant_type == "paid" or (active and row["grant_type"] == "paid") else "trial"
    stamp = now.isoformat(timespec="seconds")
    _execute(conn, """INSERT INTO subscriptions(user_id,active_until,grant_type,granted_by,updated_at)
        VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
        active_until=excluded.active_until,grant_type=excluded.grant_type,
        granted_by=excluded.granted_by,updated_at=excluded.updated_at""",
        (user_id, until, final_type, granted_by, stamp))
    _execute(conn, "UPDATE projects SET active_until=? WHERE user_id=?", (until, user_id))
    _execute(conn, "UPDATE projects SET paused=0 WHERE user_id=? AND paused=2", (user_id,))
    return until


def admin_grant_access(user_id: str, days: int, grant_type: str, granted_by: str) -> str:
    if not 1 <= int(days) <= 3650 or grant_type not in ("trial", "paid"):
        raise ValueError("Access grant must be 1-3650 days and trial or paid")
    conn = get_connection()
    try:
        until = _grant_in_conn(conn, user_id, days, grant_type, granted_by)
        conn.commit()
        return until
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def admin_revoke_access(user_id: str) -> bool:
    """Remove access. Projects the customer did not pause themselves are marked
    paused=2 so they resume automatically when access is granted again."""
    conn = get_connection()
    try:
        cur = _execute(conn, "DELETE FROM subscriptions WHERE user_id=?", (user_id,))
        _execute(conn, "UPDATE projects SET active_until=NULL,paused=CASE WHEN paused=0 THEN 2 ELSE paused END WHERE user_id=?",
                 (user_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()




def normalize_payment_ref(value: str) -> str:
    return "".join(str(value).split()).upper()


def create_manual_payment_request(user_id: str, amount: int, plan: str, transaction_ref: str,
                                  name: str = "", phone: str = "", referral_source: str = "", organization: str = "") -> dict:
    """Record a customer's claimed UPI payment for manual verification.

    The reference must look like a UPI reference and be unique across ALL
    customers. This does not prove that money moved; an admin must check.
    """
    if (plan, amount) not in (("monthly", 100), ("yearly", 1000)):
        raise ValueError("The amount does not match the selected plan.")
    transaction_ref = " ".join(str(transaction_ref).split())
    norm = normalize_payment_ref(transaction_ref)
    if not norm.isalnum() or not 8 <= len(norm) <= 35:
        raise ValueError("Enter the 12-digit UPI reference (UTR) from your payment receipt.")
    conn = get_connection()
    try:
        user_row = _execute(conn, "SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        u_keys = user_row.keys() if user_row and hasattr(user_row, "keys") else []
        u_name = name.strip() or (user_row["name"] if "name" in u_keys and user_row["name"] else "")
        u_phone = phone.strip() or (user_row["phone"] if "phone" in u_keys and user_row["phone"] else "")
        u_ref = referral_source.strip() or (user_row["referral_source"] if "referral_source" in u_keys and user_row["referral_source"] else "")
        u_org = organization.strip() or (user_row["organization"] if "organization" in u_keys and user_row["organization"] else "")

        if any([name.strip(), phone.strip(), referral_source.strip(), organization.strip()]):
            _execute(conn, "UPDATE users SET name=?, phone=?, referral_source=?, organization=? WHERE id=?",
                     (u_name, u_phone, u_ref, u_org, user_id))

        existing = _execute(conn, "SELECT * FROM manual_payments WHERE ref_norm=?", (norm,)).fetchone()
        if existing:
            if existing["user_id"] == user_id:
                return dict(existing)
            raise ValueError("That reference has already been submitted.")
        pending = _execute(conn, "SELECT COUNT(*) AS n FROM manual_payments WHERE user_id=? AND status='pending'",
                           (user_id,)).fetchone()["n"]
        if pending >= 3:
            raise ValueError("You already have payments waiting for review. Please wait for them to be confirmed.")
        payment_id = _id()
        try:
            _execute(conn, """INSERT INTO manual_payments
                (id,user_id,amount,plan,transaction_ref,ref_norm,name,phone,referral_source,organization,status,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (payment_id, user_id, amount, plan, transaction_ref, norm, u_name, u_phone, u_ref, u_org, 'pending', _now()))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise ValueError("That reference has already been submitted.") from None
            raise
        return dict(_execute(conn, "SELECT * FROM manual_payments WHERE id=?", (payment_id,)).fetchone())
    finally:
        conn.close()


def admin_list_manual_payments():
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT p.*, u.email,
            COALESCE(NULLIF(p.name, ''), u.name, '') AS user_name,
            COALESCE(NULLIF(p.phone, ''), u.phone, '') AS user_phone,
            COALESCE(NULLIF(p.referral_source, ''), u.referral_source, '') AS user_referral,
            COALESCE(NULLIF(p.organization, ''), u.organization, '') AS user_organization
            FROM manual_payments p
            JOIN users u ON u.id=p.user_id ORDER BY
            CASE WHEN p.status='pending' THEN 0 ELSE 1 END, p.created_at DESC""").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def admin_review_manual_payment(payment_id: str, decision: str, reviewed_by: str):
    """Reject (or mark) a pending payment exactly once. Use approve_manual_payment to approve."""
    if decision not in ("approved", "rejected"):
        raise ValueError("Invalid payment decision.")
    conn = get_connection()
    try:
        cur = _execute(conn, """UPDATE manual_payments SET status=?,reviewed_at=?,reviewed_by=?
            WHERE id=? AND status='pending'""", (decision, _now(), reviewed_by, payment_id))
        if cur.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
        row = _execute(conn, "SELECT p.*,u.email FROM manual_payments p JOIN users u ON u.id=p.user_id WHERE p.id=?",
                       (payment_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def approve_manual_payment(payment_id: str, reviewed_by: str):
    """Approve a pending payment and grant the matching access in ONE transaction."""
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT p.*,u.email FROM manual_payments p JOIN users u ON u.id=p.user_id WHERE p.id=?",
                       (payment_id,)).fetchone()
        if not row or row["status"] != "pending":
            return None
        if (row["plan"], row["amount"]) not in (("monthly", 100), ("yearly", 1000)):
            raise ValueError("This payment record has an invalid plan or amount.")
        cur = _execute(conn, """UPDATE manual_payments SET status='approved',reviewed_at=?,reviewed_by=?
            WHERE id=? AND status='pending'""", (_now(), reviewed_by, payment_id))
        if cur.rowcount != 1:
            conn.rollback()
            return None
        days = 30 if row["plan"] == "monthly" else 365
        until = _grant_in_conn(conn, row["user_id"], days, "paid", reviewed_by)
        conn.commit()
        result = dict(row)
        result.update(status="approved", days=days, active_until=until)
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def user_trial_status(user_id: str) -> str:
    """none | pending | approved | rejected. "approved" means the one trial was used."""
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT status FROM trial_requests WHERE user_id=?", (user_id,)).fetchall()
    finally:
        conn.close()
    statuses = {row["status"] for row in rows}
    for status in ("approved", "pending", "rejected"):
        if status in statuses:
            return status
    return "none"


def create_trial_request(user_id: str, name: str = "", phone: str = "", referral_source: str = "", organization: str = "") -> dict:
    """One trial per customer, ever. Re-requesting while pending returns the same request."""
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT * FROM trial_requests WHERE user_id=? ORDER BY requested_at DESC", (user_id,)).fetchall()
        if any(row["status"] == "approved" for row in rows):
            raise ValueError("Your free trial has already been used. Choose a plan to continue.")
        user_row = _execute(conn, "SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        u_keys = user_row.keys() if user_row and hasattr(user_row, "keys") else []
        u_name = name.strip() or (user_row["name"] if "name" in u_keys and user_row["name"] else "")
        u_phone = phone.strip() or (user_row["phone"] if "phone" in u_keys and user_row["phone"] else "")
        u_ref = referral_source.strip() or (user_row["referral_source"] if "referral_source" in u_keys and user_row["referral_source"] else "")
        u_org = organization.strip() or (user_row["organization"] if "organization" in u_keys and user_row["organization"] else "")

        if any([name.strip(), phone.strip(), referral_source.strip(), organization.strip()]):
            _execute(conn, "UPDATE users SET name=?, phone=?, referral_source=?, organization=? WHERE id=?",
                     (u_name, u_phone, u_ref, u_org, user_id))

        pending = next((row for row in rows if row["status"] == "pending"), None)
        if pending:
            existing = dict(pending)
            existing["created"] = False
            if any([name.strip(), phone.strip(), referral_source.strip(), organization.strip()]):
                _execute(conn, "UPDATE trial_requests SET name=?, phone=?, referral_source=?, organization=? WHERE id=?",
                         (u_name, u_phone, u_ref, u_org, existing["id"]))
                conn.commit()
                existing["name"] = u_name
                existing["phone"] = u_phone
                existing["referral_source"] = u_ref
                existing["organization"] = u_org
            return existing
        request_id = _id()
        _execute(conn, """INSERT INTO trial_requests
            (id,user_id,name,phone,referral_source,organization,status,requested_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            (request_id, user_id, u_name, u_phone, u_ref, u_org, "pending", _now()))
        conn.commit()
        created = dict(_execute(conn, "SELECT * FROM trial_requests WHERE id=?", (request_id,)).fetchone())
        created["created"] = True
        return created
    finally:
        conn.close()


def admin_list_trial_requests():
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT tr.*, u.email,
            COALESCE(NULLIF(tr.name, ''), u.name, '') AS user_name,
            COALESCE(NULLIF(tr.phone, ''), u.phone, '') AS user_phone,
            COALESCE(NULLIF(tr.referral_source, ''), u.referral_source, '') AS user_referral,
            COALESCE(NULLIF(tr.organization, ''), u.organization, '') AS user_organization
            FROM trial_requests tr
            JOIN users u ON u.id=tr.user_id
            ORDER BY CASE WHEN tr.status='pending' THEN 0 ELSE 1 END, tr.requested_at DESC""").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def admin_review_trial_request(request_id: str, status: str, reviewed_by: str, note: str = "") -> dict | None:
    """Review a pending request exactly once (used for rejection; approval uses approve_trial_request)."""
    if status not in ("approved", "rejected"):
        raise ValueError("Trial request status must be approved or rejected")
    conn = get_connection()
    try:
        cur = _execute(conn, """UPDATE trial_requests SET status=?,reviewed_at=?,reviewed_by=?,decision_note=?
            WHERE id=? AND status='pending'""", (status, _now(), reviewed_by, note[:500], request_id))
        if cur.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
        row = _execute(conn, "SELECT tr.*,u.email FROM trial_requests tr JOIN users u ON u.id=tr.user_id WHERE tr.id=?",
                       (request_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def approve_trial_request(request_id: str, reviewed_by: str) -> dict | None:
    """Approve a pending trial and grant one day of access in ONE transaction."""
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT tr.*,u.email FROM trial_requests tr JOIN users u ON u.id=tr.user_id WHERE tr.id=?",
                       (request_id,)).fetchone()
        if not row or row["status"] != "pending":
            return None
        cur = _execute(conn, """UPDATE trial_requests SET status='approved',reviewed_at=?,reviewed_by=?
            WHERE id=? AND status='pending'""", (_now(), reviewed_by, request_id))
        if cur.rowcount != 1:
            conn.rollback()
            return None
        until = _grant_in_conn(conn, row["user_id"], 1, "trial", reviewed_by)
        conn.commit()
        result = dict(row)
        result.update(status="approved", active_until=until)
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Notification log, worker status and dashboard read models
# ---------------------------------------------------------------------------

def database_kind() -> str:
    return "postgresql" if _database_url() else "sqlite"


def log_notification(kind: str, recipient: str, subject: str, ok: bool, detail: str = "") -> None:
    conn = get_connection()
    try:
        _execute(conn, "INSERT INTO notification_log(id,created_at,kind,recipient,subject,ok,detail) VALUES(?,?,?,?,?,?,?)",
                 (_id(), _now(), kind[:40], recipient[:254], subject[:200], 1 if ok else 0, detail[:300]))
        _execute(conn, """DELETE FROM notification_log WHERE id NOT IN
            (SELECT id FROM notification_log ORDER BY created_at DESC LIMIT 200)""")
        conn.commit()
    finally:
        conn.close()


def recent_notifications(limit: int = 12) -> list[dict]:
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT * FROM notification_log ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def touch_worker(name: str = "portal_worker") -> None:
    conn = get_connection()
    try:
        _execute(conn, """INSERT INTO worker_status(name,last_seen) VALUES(?,?)
            ON CONFLICT(name) DO UPDATE SET last_seen=excluded.last_seen""", (name, _now()))
        conn.commit()
    finally:
        conn.close()


def worker_last_seen(name: str = "portal_worker"):
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT last_seen FROM worker_status WHERE name=?", (name,)).fetchone()
        return row["last_seen"] if row else None
    finally:
        conn.close()


def get_user_email(user_id: str) -> str:
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
        return row["email"] if row else ""
    finally:
        conn.close()


def get_payment_order(order_id: str):
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT user_id,amount,status,plan FROM payment_orders WHERE razorpay_order_id=?",
                       (order_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def user_manual_payments(user_id: str, limit: int = 5) -> list[dict]:
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT * FROM manual_payments WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                        (user_id, limit)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_projects_with_activity(user_id: str) -> list[dict]:
    """Projects plus real incident counts and the latest incident, for the customer dashboard."""
    projects = list_projects(user_id)
    conn = get_connection()
    try:
        for project in projects:
            counts = _execute(conn, """SELECT COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN status<>'resolved' THEN 1 ELSE 0 END),0) AS open_count
                FROM incidents WHERE project_id=?""", (project["id"],)).fetchone()
            project["incident_total"] = int(counts["total"] or 0)
            project["incident_open"] = int(counts["open_count"] or 0)
            latest = _execute(conn, """SELECT id,signature,status,last_seen,pr_url,ci_status FROM incidents
                WHERE project_id=? ORDER BY last_seen DESC LIMIT 1""", (project["id"],)).fetchone()
            project["latest_incident"] = dict(latest) if latest else None
        return projects
    finally:
        conn.close()


def recent_activity(user_id: str, limit: int = 8) -> list[dict]:
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT i.id,i.project_id,i.signature,i.status,i.last_seen,i.occurrences,
            i.pr_url,i.ci_status,p.name AS project_name
            FROM incidents i JOIN projects p ON p.id=i.project_id
            WHERE p.user_id=? ORDER BY i.last_seen DESC LIMIT ?""", (user_id, limit)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def admin_projects() -> list[dict]:
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT p.id,p.name,p.repo_owner,p.repo_name,p.status,p.paused,p.mode,
            p.last_heartbeat_at,p.active_until,u.email AS owner_email,
            (SELECT COUNT(*) FROM incidents i WHERE i.project_id=p.id AND i.status<>'resolved') AS open_incidents
            FROM projects p JOIN users u ON u.id=p.user_id ORDER BY p.created_at DESC""").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def admin_recent_incidents(limit: int = 12) -> list[dict]:
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT i.id,i.project_id,i.signature,i.status,i.occurrences,i.last_seen,
            i.pr_url,i.ci_status,p.name AS project_name,u.email AS owner_email
            FROM incidents i JOIN projects p ON p.id=i.project_id JOIN users u ON u.id=p.user_id
            ORDER BY i.last_seen DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def admin_stats(admin_emails: set[str]) -> dict:
    """Headline numbers for the admin page, computed from real rows."""
    now = _now()
    customers = [u for u in admin_list_users() if u["email"].lower() not in admin_emails]
    active = [u for u in customers if u.get("active_until") and u["active_until"] > now]
    conn = get_connection()
    try:
        def count(sql):
            return int(_execute(conn, sql).fetchone()["n"])
        stats = {
            "customers": len(customers),
            "active": len(active),
            "inactive": len(customers) - len(active),
            "paid_active": sum(1 for u in active if u.get("grant_type") == "paid"),
            "trial_active": sum(1 for u in active if u.get("grant_type") != "paid"),
            "pending_trials": count("SELECT COUNT(*) AS n FROM trial_requests WHERE status='pending'"),
            "pending_payments": count("SELECT COUNT(*) AS n FROM manual_payments WHERE status='pending'"),
            "projects": count("SELECT COUNT(*) AS n FROM projects"),
            "open_incidents": count("SELECT COUNT(*) AS n FROM incidents WHERE status<>'resolved'"),
            "needs_human": count("SELECT COUNT(*) AS n FROM incidents WHERE status='needs_human'"),
        }
    finally:
        conn.close()
    return stats


def update_project_branch(project_id: str, user_id: str, branch: str) -> bool:
    conn = get_connection()
    try:
        cur = _execute(conn, "UPDATE projects SET branch=? WHERE id=? AND user_id=?", (branch[:100], project_id, user_id))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


# --- Chat & Visitor Tracking Persistence -------------------------------------

def track_visitor_visit(visitor_id: str, cooldown_seconds: int = 1800) -> bool:
    """Records a visitor visit. Returns True if admins should be notified (first visit or after cooldown)."""
    conn = get_connection()
    try:
        now = _now()
        row = _execute(conn, "SELECT visitor_id, last_notified, visit_count FROM visitor_tracking WHERE visitor_id = ?",
                       (visitor_id,)).fetchone()
        if not row:
            _execute(conn, "INSERT INTO visitor_tracking(visitor_id, first_seen, last_notified, visit_count) VALUES(?,?,?,?)",
                     (visitor_id, now, now, 1))
            conn.commit()
            return True
        last_dt = _parse_ts(row["last_notified"]) if isinstance(row["last_notified"], str) else row["last_notified"]
        now_dt = datetime.now(timezone.utc)
        should_notify = (now_dt - last_dt) > timedelta(seconds=cooldown_seconds)
        new_last = now if should_notify else row["last_notified"]
        _execute(conn, "UPDATE visitor_tracking SET last_notified=?, visit_count=visit_count+1 WHERE visitor_id=?",
                 (new_last, visitor_id))
        conn.commit()
        return should_notify
    finally:
        conn.close()


def get_or_create_conversation(visitor_id: str, name: str = "", email: str = "") -> dict:
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM chat_conversations WHERE visitor_id = ? ORDER BY updated_at DESC LIMIT 1",
                       (visitor_id,)).fetchone()
        now = _now()
        if row:
            conv = dict(row)
            updates = []
            params = []
            if name and not conv.get("visitor_name"):
                updates.append("visitor_name = ?")
                params.append(name.strip())
            if email and not conv.get("visitor_email"):
                updates.append("visitor_email = ?")
                params.append(email.strip().lower())
            if updates:
                params.append(conv["id"])
                _execute(conn, f"UPDATE chat_conversations SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()
                row = _execute(conn, "SELECT * FROM chat_conversations WHERE id = ?", (conv["id"],)).fetchone()
                return dict(row)
            return conv
        conv_id = _id()
        _execute(conn, "INSERT INTO chat_conversations(id, visitor_id, visitor_name, visitor_email, status, created_at, updated_at) "
                       "VALUES(?,?,?,?,?,?,?)",
                 (conv_id, visitor_id, name.strip(), email.strip().lower(), "open", now, now))
        conn.commit()
        return dict(_execute(conn, "SELECT * FROM chat_conversations WHERE id = ?", (conv_id,)).fetchone())
    finally:
        conn.close()


def add_chat_message(conversation_id: str, sender: str, text: str, sender_name: str = "") -> dict:
    conn = get_connection()
    try:
        msg_id = _id()
        now = _now()
        _execute(conn, "INSERT INTO chat_messages(id, conversation_id, sender, sender_name, text, created_at) VALUES(?,?,?,?,?,?)",
                 (msg_id, conversation_id, sender, sender_name.strip(), text.strip(), now))
        _execute(conn, "UPDATE chat_conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        conn.commit()
        row = _execute(conn, "SELECT * FROM chat_messages WHERE id = ?", (msg_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_chat_messages(conversation_id: str, after_time: str = "") -> list[dict]:
    conn = get_connection()
    try:
        if after_time:
            rows = _execute(conn, "SELECT * FROM chat_messages WHERE conversation_id = ? AND created_at > ? ORDER BY created_at ASC",
                            (conversation_id, after_time)).fetchall()
        else:
            rows = _execute(conn, "SELECT * FROM chat_messages WHERE conversation_id = ? ORDER BY created_at ASC",
                            (conversation_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def admin_list_chat_conversations(limit: int = 30) -> list[dict]:
    conn = get_connection()
    try:
        rows = _execute(conn, """
            SELECT c.*,
                   (SELECT COUNT(*) FROM chat_messages m WHERE m.conversation_id = c.id) AS message_count,
                   (SELECT text FROM chat_messages m WHERE m.conversation_id = c.id ORDER BY m.created_at DESC LIMIT 1) AS last_message,
                   (SELECT sender FROM chat_messages m WHERE m.conversation_id = c.id ORDER BY m.created_at DESC LIMIT 1) AS last_sender
            FROM chat_conversations c
            ORDER BY c.updated_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_conversation_visitor_details(conversation_id: str, name: str, email: str) -> None:
    conn = get_connection()
    try:
        _execute(conn, "UPDATE chat_conversations SET visitor_name = ?, visitor_email = ?, updated_at = ? WHERE id = ?",
                 (name.strip(), email.strip().lower(), _now(), conversation_id))
        conn.commit()
    finally:
        conn.close()


def create_support_ticket(name: str, email: str, subject: str, message: str, assigned_to: str = "") -> dict:
    conn = get_connection()
    try:
        msg_id = _id()
        ticket_ref = f"TICK-{msg_id[:8].upper()}"
        now = _now()
        _execute(conn, """INSERT INTO support_messages(id, ticket_ref, name, email, subject, message, status, assigned_to, resolution_note, closed_at, closed_by, updated_at, created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (msg_id, ticket_ref, name.strip(), email.strip().lower(), subject.strip() or "General Support Inquiry", message.strip(), "open", assigned_to.strip(), "", "", "", now, now))
        conn.commit()
        row = _execute(conn, "SELECT * FROM support_messages WHERE id = ?", (msg_id,)).fetchone()
        d = dict(row)
        if not d.get("ticket_ref"):
            d["ticket_ref"] = ticket_ref
        return d
    finally:
        conn.close()


def create_support_message(name: str, email: str, subject: str, message: str) -> dict:
    return create_support_ticket(name, email, subject, message)


def admin_list_support_messages(limit: int = 50, status: str | None = None) -> list[dict]:
    conn = get_connection()
    try:
        if status and status != "all":
            rows = _execute(conn, "SELECT * FROM support_messages WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit)).fetchall()
        else:
            rows = _execute(conn, "SELECT * FROM support_messages ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        tickets = []
        for r in rows:
            d = dict(r)
            if not d.get("ticket_ref"):
                d["ticket_ref"] = f"TICK-{d['id'][:8].upper()}"
            tickets.append(d)
        return tickets
    finally:
        conn.close()


def admin_get_support_ticket(ticket_id: str) -> dict | None:
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM support_messages WHERE id = ? OR ticket_ref = ?", (ticket_id, ticket_id)).fetchone()
        if not row:
            return None
        d = dict(row)
        if not d.get("ticket_ref"):
            d["ticket_ref"] = f"TICK-{d['id'][:8].upper()}"
        return d
    finally:
        conn.close()


def admin_update_support_ticket(ticket_id: str, status: str, assigned_to: str = "", resolution_note: str = "", actor: str = "") -> dict | None:
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM support_messages WHERE id = ? OR ticket_ref = ?", (ticket_id, ticket_id)).fetchone()
        if not row:
            return None
        cur = dict(row)
        now = _now()
        closed_at = now if status == "closed" and cur.get("status") != "closed" else cur.get("closed_at", "")
        closed_by = actor if status == "closed" and cur.get("status") != "closed" else cur.get("closed_by", "")
        res_note = resolution_note.strip() if resolution_note.strip() else cur.get("resolution_note", "")
        assignee = assigned_to.strip() if assigned_to.strip() else cur.get("assigned_to", "")

        _execute(conn, """UPDATE support_messages 
                       SET status = ?, assigned_to = ?, resolution_note = ?, closed_at = ?, closed_by = ?, updated_at = ?
                       WHERE id = ?""",
                 (status, assignee, res_note, closed_at, closed_by, now, cur["id"]))
        conn.commit()
        updated_row = _execute(conn, "SELECT * FROM support_messages WHERE id = ?", (cur["id"],)).fetchone()
        res = dict(updated_row)
        if not res.get("ticket_ref"):
            res["ticket_ref"] = f"TICK-{res['id'][:8].upper()}"
        return res
    finally:
        conn.close()


def admin_ticket_stats() -> dict:
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT status, COUNT(*) as cnt FROM support_messages GROUP BY status").fetchall()
        counts = {"open": 0, "for_review": 0, "closed": 0, "total": 0}
        for r in rows:
            st = str(r["status"]).lower()
            cnt = int(r["cnt"])
            if st in counts:
                counts[st] += cnt
            else:
                counts["open"] += cnt
            counts["total"] += cnt
        return counts
    finally:
        conn.close()



# --- Java Integration Waitlist & Launch Notification Functions ---

def register_java_waitlist(email: str, consent: bool = True, source: str = "homepage_banner") -> tuple[bool, str, dict]:
    """Register an email address for the Java launch announcement.
    Returns (success, reason, record_dict).
    reason is one of: 'created', 'reactivated', 'duplicate'
    """
    clean_email = email.strip().lower()
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM java_waitlist WHERE email = ?", (clean_email,)).fetchone()
        now = _now()
        if row:
            d = dict(row)
            if d.get("status") == "subscribed":
                return False, "duplicate", d
            # Reactivate previously unsubscribed email
            _execute(conn, """UPDATE java_waitlist 
                           SET status = 'subscribed', notification_sent = 0, delivery_error = '', consent = ? 
                           WHERE email = ?""", (1 if consent else 0, clean_email))
            conn.commit()
            updated = _execute(conn, "SELECT * FROM java_waitlist WHERE email = ?", (clean_email,)).fetchone()
            return True, "reactivated", dict(updated)

        rec_id = _id()
        unsub_token = uuid.uuid4().hex + uuid.uuid4().hex[:8]
        _execute(conn, """INSERT INTO java_waitlist(id, email, consent, source, created_at, notification_sent, 
                                                 notification_sent_at, status, unsubscribe_token, delivery_error, attempt_count)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                 (rec_id, clean_email, 1 if consent else 0, source.strip() or "homepage_banner",
                  now, 0, "", "subscribed", unsub_token, "", 0))
        conn.commit()
        created = _execute(conn, "SELECT * FROM java_waitlist WHERE id = ?", (rec_id,)).fetchone()
        return True, "created", dict(created)
    finally:
        conn.close()


def unsubscribe_java_waitlist(token_or_email: str) -> tuple[bool, str]:
    """Unsubscribe a user from Java launch notifications using their token or email."""
    val = token_or_email.strip()
    if not val:
        return False, ""
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM java_waitlist WHERE unsubscribe_token = ? OR email = ?", (val, val.lower())).fetchone()
        if not row:
            return False, ""
        clean_email = row["email"]
        _execute(conn, "UPDATE java_waitlist SET status = 'unsubscribed' WHERE id = ?", (row["id"],))
        conn.commit()
        return True, clean_email
    finally:
        conn.close()


def get_java_waitlist_stats() -> dict:
    """Return aggregated statistics on Java waitlist registrations and notification progress."""
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT status, notification_sent, attempt_count FROM java_waitlist").fetchall()
        stats = {
            "total_interested": len(rows),
            "subscribed": 0,
            "unsubscribed": 0,
            "sent": 0,
            "pending": 0,
            "failed": 0,
        }
        for r in rows:
            st = r["status"]
            sent = r["notification_sent"]
            attempts = r["attempt_count"]
            if st == "subscribed":
                stats["subscribed"] += 1
                if sent:
                    stats["sent"] += 1
                else:
                    stats["pending"] += 1
                    if attempts > 0:
                        stats["failed"] += 1
            elif st == "unsubscribed":
                stats["unsubscribed"] += 1
                if sent:
                    stats["sent"] += 1
        return stats
    finally:
        conn.close()


def list_java_waitlist(limit: int = 100) -> list[dict]:
    """List registered users for admin view."""
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT * FROM java_waitlist ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pending_java_launch_recipients() -> list[dict]:
    """Return all subscribers who have not yet received the official launch notification."""
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT * FROM java_waitlist 
                               WHERE status = 'subscribed' AND notification_sent = 0 
                               ORDER BY created_at ASC""").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_failed_java_launch_recipients() -> list[dict]:
    """Return subscribers whose notification attempt failed and are ready to be retried."""
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT * FROM java_waitlist 
                               WHERE status = 'subscribed' AND notification_sent = 0 AND attempt_count > 0 
                               ORDER BY created_at ASC""").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_java_notification_sent(record_id: str) -> None:
    """Mark a subscriber as successfully notified."""
    conn = get_connection()
    try:
        now = _now()
        _execute(conn, """UPDATE java_waitlist 
                       SET notification_sent = 1, notification_sent_at = ?, delivery_error = '' 
                       WHERE id = ?""", (now, record_id))
        conn.commit()
    finally:
        conn.close()


def mark_java_notification_failed(record_id: str, error: str) -> None:
    """Record a failed delivery attempt and error detail for safe retry."""
    conn = get_connection()
    try:
        _execute(conn, """UPDATE java_waitlist 
                       SET attempt_count = attempt_count + 1, delivery_error = ? 
                       WHERE id = ?""", (str(error)[:300], record_id))
        conn.commit()
    finally:
        conn.close()


def record_banner_event(event_type: str) -> None:
    """Record an analytics event for the homepage announcement banner."""
    clean_type = event_type.strip().lower()[:50]
    if not clean_type:
        return
    conn = get_connection()
    try:
        _execute(conn, "INSERT INTO banner_analytics(id, event_type, created_at) VALUES(?,?,?)",
                 (_id(), clean_type, _now()))
        conn.commit()
    finally:
        conn.close()


def get_banner_analytics() -> dict:
    """Return counts of banner impressions, dismissals, registration attempts, etc."""
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT event_type, COUNT(*) as cnt FROM banner_analytics GROUP BY event_type").fetchall()
        counts = {"impression": 0, "dismiss": 0, "attempt": 0, "success": 0, "duplicate": 0}
        for r in rows:
            et = str(r["event_type"]).lower()
            if et in counts:
                counts[et] = int(r["cnt"])
            else:
                counts[et] = int(r["cnt"])
        return counts
    finally:
        conn.close()
