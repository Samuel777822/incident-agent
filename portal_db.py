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
import re

import plans

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

CREATE TABLE IF NOT EXISTS case_images (
  id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  mime TEXT NOT NULL,
  data TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_case_images_incident ON case_images(incident_id, created_at);

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
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  email TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  rating INTEGER NOT NULL,
  text TEXT NOT NULL DEFAULT '',
  can_publish INTEGER NOT NULL DEFAULT 0,
  project_id TEXT NOT NULL DEFAULT '',
  incident_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_time ON reviews(created_at DESC);

CREATE TABLE IF NOT EXISTS push_checks (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL,
  sha TEXT NOT NULL,
  branch TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'webhook',
  pusher TEXT NOT NULL DEFAULT '',
  commit_message TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued',
  stage TEXT NOT NULL DEFAULT 'queued',
  stage_detail TEXT NOT NULL DEFAULT '',
  stacks_json TEXT NOT NULL DEFAULT '[]',
  output TEXT NOT NULL DEFAULT '',
  incident_id TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  available_at TEXT NOT NULL,
  locked_until TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT NOT NULL DEFAULT '',
  finished_at TEXT NOT NULL DEFAULT '',
  UNIQUE(project_id, sha)
);
CREATE INDEX IF NOT EXISTS idx_push_checks_ready ON push_checks(status, available_at);
CREATE INDEX IF NOT EXISTS idx_push_checks_project ON push_checks(project_id, created_at);

CREATE TABLE IF NOT EXISTS monitor_heartbeats (
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  monitor TEXT NOT NULL,
  component TEXT NOT NULL DEFAULT '',
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  beats INTEGER NOT NULL DEFAULT 0,
  version TEXT NOT NULL DEFAULT '',
  runtime TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (project_id, monitor, component)
);

"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id() -> str:
    return str(uuid.uuid4())


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


import threading as _threading
import time as _time

_POOL = _threading.local()
POOL_MAX_IDLE = 4            # open connections kept per thread
POOL_MAX_AGE = 300.0         # seconds: older connections are replaced
POOL_PING_AFTER = 60.0       # seconds idle: ping before reuse (the server may have closed it)


class _PooledConnection:
    """A PostgreSQL connection that goes back to a small per-thread pool on close() instead of being closed.

    Why: every query used to open a NEW connection (network + TLS handshake to the database). One dashboard load made dozens,
    which made the projects page take seconds. close() rolls back anything uncommitted first, so nothing leaks between uses; a
    nested get_connection() always gets a DIFFERENT connection, so one function never rolls back another's transaction."""

    __slots__ = ("_raw", "_born", "_done")

    def __init__(self, raw, born: float):
        self._raw, self._born, self._done = raw, born, False

    def __getattr__(self, name):
        return getattr(self._raw, name)

    def close(self) -> None:
        if self._done:
            return
        self._done = True
        raw = self._raw
        try:
            if raw.closed or raw.broken:
                raise RuntimeError("connection is gone")
            from psycopg import pq
            if raw.info.transaction_status != pq.TransactionStatus.IDLE:
                raw.rollback()
            idle = getattr(_POOL, "idle", None)
            if idle is None:
                idle = _POOL.idle = []
            if len(idle) < POOL_MAX_IDLE and _time.monotonic() - self._born < POOL_MAX_AGE:
                idle.append((raw, self._born, _time.monotonic()))
                return
        except Exception:
            pass
        try:
            raw.close()
        except Exception:
            pass


def _pooled_pg(url: str):
    import psycopg
    from psycopg.rows import dict_row
    idle = getattr(_POOL, "idle", None) or []
    now = _time.monotonic()
    while idle:
        raw, born, last = idle.pop()
        try:
            if raw.closed or raw.broken or now - born > POOL_MAX_AGE:
                raise RuntimeError("stale")
            if now - last > POOL_PING_AFTER:
                raw.execute("SELECT 1")
                raw.rollback()
            return _PooledConnection(raw, born)
        except Exception:
            try:
                raw.close()
            except Exception:
                pass
    return _PooledConnection(psycopg.connect(url, row_factory=dict_row, connect_timeout=10), now)


def get_connection():
    """A PostgreSQL connection (reused from a small per-thread pool) or SQLite locally; production must provide PostgreSQL."""
    url = _database_url()
    if url.startswith(("postgres://", "postgresql://")):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("PostgreSQL support requires psycopg; install requirements.txt") from exc
        if os.getenv("DB_POOL", "1").strip().lower() in ("0", "false", "no", "off"):
            return psycopg.connect(url, row_factory=dict_row, connect_timeout=10)
        return _pooled_pg(url)
    if os.getenv("APP_ENV", "development").lower() == "production":
        raise RuntimeError("DATABASE_URL must point to PostgreSQL in production")
    path = os.getenv("PORTAL_DB_PATH", "portal.db")
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def pg_sql(sql: str) -> str:
    """SQLite-style SQL ('?' placeholders) to psycopg style ('%s').

    A literal '%' (for example in LIKE 'user_report:%') must be doubled first: psycopg reads every single '%' as the start of a
    placeholder, which crashed the 'Tell the agent what's broken' box on PostgreSQL ("Something went wrong on our side").
    Values with '%' are always passed as parameters, so doubling the SQL text itself is always correct."""
    return sql.replace("%", "%%").replace("?", "%s")


def _execute(conn, sql: str, params=()):
    if isinstance(conn, sqlite3.Connection):
        return conn.execute(sql, params)
    return conn.execute(pg_sql(sql), params)


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
            ("subscriptions", "plan", "TEXT NOT NULL DEFAULT 'basic'"),          # v6: basic | pro (trials use grant_type='trial')
            ("payment_orders", "plan", "TEXT NOT NULL DEFAULT 'yearly'"),
            ("manual_payments", "ref_norm", "TEXT NOT NULL DEFAULT ''"),
            ("incidents", "no_automerge", "INTEGER NOT NULL DEFAULT 0"),
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
            ("manual_payments", "name", "TEXT NOT NULL DEFAULT ''"),
            ("manual_payments", "phone", "TEXT NOT NULL DEFAULT ''"),
            ("manual_payments", "referral_source", "TEXT NOT NULL DEFAULT ''"),
            ("manual_payments", "organization", "TEXT NOT NULL DEFAULT ''"),
            # Architecture v3: push-time checks, paid project slots, live stages on the dashboard.
            ("users", "project_slots", "INTEGER NOT NULL DEFAULT 0"),
            ("projects", "watch_mode", "TEXT NOT NULL DEFAULT 'both'"),
            ("projects", "webhook_id", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "webhook_secret_ciphertext", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "last_checked_sha", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "last_check_status", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "last_check_at", "TEXT NOT NULL DEFAULT ''"),
            ("incidents", "source", "TEXT NOT NULL DEFAULT 'runtime'"),
            ("incidents", "commit_sha", "TEXT NOT NULL DEFAULT ''"),
            ("incidents", "stage", "TEXT NOT NULL DEFAULT ''"),
            ("incidents", "stage_detail", "TEXT NOT NULL DEFAULT ''"),
            ("incidents", "stage_tier", "TEXT NOT NULL DEFAULT ''"),
            ("incidents", "stage_at", "TEXT NOT NULL DEFAULT ''"),
            # Monitoring v2: public-repo gate, multi-language monitors, check-in tracking, initial scan.
            ("projects", "gate_state", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "gate_checked_at", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "gate_notified_at", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "monitor_targets_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("projects", "monitor_installed_at", "TEXT NOT NULL DEFAULT ''"),
            ("projects", "monitor_alerted_at", "TEXT NOT NULL DEFAULT ''"),
            ("push_checks", "static_done", "INTEGER NOT NULL DEFAULT 0"),
            # v3.1: one case = one fix. Followers point at their case leader and never get their own AI diagnosis.
            ("incidents", "case_id", "TEXT NOT NULL DEFAULT ''"),
            ("incidents", "case_key", "TEXT NOT NULL DEFAULT ''"),
            ("incidents", "merged_count", "INTEGER NOT NULL DEFAULT 0"),
            ("incidents", "check_until", "TEXT NOT NULL DEFAULT ''"),
            ("incidents", "live_result", "TEXT NOT NULL DEFAULT ''"),
            # v4: the owner decides which cases the agent works on
            ("projects", "auto_start", "INTEGER NOT NULL DEFAULT 1"),
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
            from fixengine import store as _fx_store  # auto-fix engine tables (ledger, quotas, router log)
            _fx_store.ensure_schema(conn)
        except Exception:
            conn.rollback()
            raise
        try:
            _execute(conn, "CREATE UNIQUE INDEX IF NOT EXISTS idx_manual_payments_ref "
                           "ON manual_payments(ref_norm) WHERE ref_norm <> ''")
            conn.commit()
        except Exception:
            conn.rollback()
        _ensure_one_open_incident_index(conn)
    finally:
        conn.close()


OPEN_SQL = "status NOT IN ('resolved','reverted','merged')"


def _ensure_one_open_incident_index(conn) -> None:
    """At most ONE open incident per (project, signature), enforced by the database (v3.1).

    Older databases can already hold duplicates (the old check-then-insert could race on PostgreSQL). They are merged first:
    the newest one stays, the others become followers of it (status 'merged'), so the unique index can be created safely."""
    try:
        groups = _execute(conn, f"""SELECT project_id, signature, COUNT(*) AS n FROM incidents WHERE {OPEN_SQL}
                                    GROUP BY project_id, signature HAVING COUNT(*) > 1""").fetchall()
        for g in groups:
            rows = _execute(conn, f"""SELECT id FROM incidents WHERE project_id=? AND signature=? AND {OPEN_SQL}
                                      ORDER BY created_at DESC""", (g["project_id"], g["signature"])).fetchall()
            keep = rows[0]["id"]
            for r in rows[1:]:
                _execute(conn, "UPDATE incidents SET status='merged',case_id=?,stage='merged',stage_detail=? WHERE id=?",
                         (keep, "Merged into the newer incident with the same error", r["id"]))
                _execute(conn, "UPDATE incident_jobs SET status='done',locked_until=NULL WHERE incident_id=?", (r["id"],))
            _execute(conn, "UPDATE incidents SET merged_count=merged_count+? WHERE id=?", (len(rows) - 1, keep))
        _execute(conn, f"CREATE UNIQUE INDEX IF NOT EXISTS idx_incidents_one_open ON incidents(project_id, signature) WHERE {OPEN_SQL}")
        _execute(conn, "CREATE INDEX IF NOT EXISTS idx_incidents_case ON incidents(project_id, case_id)")
        conn.commit()
    except Exception:
        conn.rollback()
        import logging
        logging.getLogger("portal_db").exception("could not create the one-open-incident index")


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
                   app_url: str = "", ai_consent_at: str = "", ingest_key_ciphertext: str = "",
                   watch_mode: str = "both", enforce_slots: bool = False, gate_state: str = "") -> str:
    """enforce_slots: refuse (ValueError) when the account already uses every project slot it has (1 + paid extra slots).
    Checked inside the same connection as the insert so two quick submissions cannot both slip through."""
    if watch_mode not in WATCH_MODES:
        raise ValueError("Unknown watch mode")
    project_id = _id()
    conn = get_connection()
    try:
        if enforce_slots:
            used = _execute(conn, "SELECT COUNT(*) AS n FROM projects WHERE user_id=?", (user_id,)).fetchone()["n"]
            row = _execute(conn, "SELECT project_slots FROM users WHERE id=?", (user_id,)).fetchone()
            limit = plans.INCLUDED_PROJECTS + int((row["project_slots"] if row else 0) or 0)
            if used >= limit:
                raise ValueError("project_limit")
        subscription = _execute(conn, "SELECT active_until FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
        active_until = subscription["active_until"] if subscription else None
        _execute(conn, """INSERT INTO projects
          (id,user_id,name,repo_owner,repo_name,branch,mode,github_token_ciphertext,
           ingest_key_hash,app_url,active_until,created_at,ai_consent_at,ingest_key_ciphertext,watch_mode,gate_state,gate_checked_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (project_id,user_id,name,repo_owner,repo_name,branch,mode,token_ciphertext,
           ingest_key_hash,app_url,active_until,_now(),ai_consent_at,ingest_key_ciphertext,watch_mode,gate_state,
           _now() if gate_state else ""))
        conn.commit()
        return project_id
    finally:
        conn.close()


WATCH_MODES = ("push", "runtime", "both")


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
        row = _execute(conn, "SELECT id,user_id,name,repo_owner,repo_name,branch,mode,status,paused,gate_state FROM projects WHERE ingest_key_hash=?", (key_hash,)).fetchone()
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
                 traceback: str = "", signature: str = "unknown", case_ok: bool = True) -> tuple[str | None, bool]:
    """Deduplicate and attach an event to a project-scoped open incident.

    case_ok=False (a failed push check): never attach to another case or to a just-fixed incident: a broken build is always handled."""
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
        row = _execute(conn, f"""SELECT id,occurrences,status,last_seen FROM incidents
          WHERE project_id=? AND signature=? AND {OPEN_SQL}
          ORDER BY created_at DESC LIMIT 1""", (project_id,signature)).fetchone()
        if not row:
            attached = _attach_to_case(conn, project_id, event_id, signature, message, traceback, timestamp) if case_ok else None
            if attached:
                conn.commit()
                return attached, True
            incident_id = _id()
            import cases
            key = json.dumps(cases.key_for(signature, message, traceback), sort_keys=True) if case_ok else ""
            cur = _execute(conn, f"""INSERT INTO incidents
              (id,project_id,signature,first_seen,last_seen,created_at,case_key)
              VALUES(?,?,?,?,?,?,?) ON CONFLICT (project_id,signature) WHERE {OPEN_SQL} DO NOTHING""",
              (incident_id,project_id,signature,timestamp,timestamp,_now(),key))
            if cur.rowcount == 1:
                _execute(conn, "UPDATE log_events SET incident_id=? WHERE id=? AND project_id=?",
                         (incident_id,event_id,project_id))
                if case_ok and not str(signature).startswith("user_report:"):
                    auto = _execute(conn, "SELECT auto_start FROM projects WHERE id=?", (project_id,)).fetchone()
                    if auto is not None and int(auto["auto_start"] or 0) == 0:
                        _execute(conn, """UPDATE incidents SET status='paused',stage='paused',stage_detail=?,stage_at=? WHERE id=?""",
                                 ("Found automatically. It waits until you press Start (auto-start is off for this project).", _now(), incident_id))
                _execute(conn, "INSERT INTO incident_jobs(incident_id,status,available_at,updated_at) VALUES(?,?,?,?) ON CONFLICT(incident_id) DO NOTHING",
                         (incident_id,"queued",_now(),_now()))
                conn.commit()
                return incident_id, True
            # Another worker created the same open incident a moment ago (the race the unique index closes): join it.
            row = _execute(conn, f"""SELECT id,occurrences,status,last_seen FROM incidents
              WHERE project_id=? AND signature=? AND {OPEN_SQL} ORDER BY created_at DESC LIMIT 1""", (project_id,signature)).fetchone()
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
            raise RuntimeError("could not create or find the open incident")
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


CASE_ACTIVE = ("diagnosing", "queued", "processing", "awaiting_choice", "diagnosed", "paused")


def _attach_to_case(conn, project_id: str, event_id: str, signature: str, message: str, traceback: str,
                    timestamp: str) -> str | None:
    """Attach a new event to an existing case instead of opening a new paid investigation. Returns the incident id it was
    attached to, or None when this is a genuinely new problem. Runs inside ingest_event's transaction."""
    import cases
    now = _now()
    active = ",".join("'" + s + "'" for s in CASE_ACTIVE)
    # 1. The same error was just fixed (inside the check window) or already belongs to a case: count it, spend nothing.
    prior = _execute(conn, """SELECT id,status,case_id,check_until FROM incidents WHERE project_id=? AND signature=?
        AND status IN ('resolved','merged') ORDER BY created_at DESC LIMIT 1""", (project_id, signature)).fetchone()
    if prior:
        leader_id = prior["case_id"] if prior["status"] == "merged" and prior["case_id"] else prior["id"]
        leader = _execute(conn, "SELECT id,status,check_until FROM incidents WHERE id=? AND project_id=?",
                          (leader_id, project_id)).fetchone()
        if leader and (leader["status"] in CASE_ACTIVE or (leader["check_until"] and leader["check_until"] > now)):
            _execute(conn, "UPDATE incidents SET occurrences=occurrences+1,last_seen=? WHERE id=?", (timestamp, prior["id"]))
            _execute(conn, "UPDATE log_events SET incident_id=? WHERE id=? AND project_id=?", (prior["id"], event_id, project_id))
            return prior["id"]
    # 2. A different error text with the same cause (same model, same outside host, same page, report + monitor at once).
    key = cases.key_for(signature, message, traceback)
    if not any(key.values()):
        return None
    rows = _execute(conn, f"""SELECT id,case_key,first_seen,last_seen,status,check_until FROM incidents
        WHERE project_id=? AND case_id='' AND case_key<>'' AND (status IN ({active}) OR (status='resolved' AND check_until>?))
        ORDER BY last_seen DESC LIMIT 25""", (project_id, now)).fetchall()
    leader_id, why = cases.find_leader([dict(r) for r in rows], key, now_iso=now)
    if not leader_id:
        return None
    follower = _id()
    _execute(conn, """INSERT INTO incidents (id,project_id,signature,status,first_seen,last_seen,created_at,case_id,case_key,stage,stage_detail,stage_at)
        VALUES(?,?,?,'merged',?,?,?,?,?,'merged',?,?)""",
        (follower, project_id, signature, timestamp, timestamp, now, leader_id, json.dumps(key, sort_keys=True),
         ("Same cause as an open case: " + why)[:300], now))
    _execute(conn, "UPDATE log_events SET incident_id=? WHERE id=? AND project_id=?", (follower, event_id, project_id))
    _execute(conn, "UPDATE incidents SET merged_count=merged_count+1,last_seen=? WHERE id=? AND project_id=?", (timestamp, leader_id, project_id))
    _execute(conn, "INSERT INTO audit_log(id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
             (_id(), project_id, "incident_merged", json.dumps({"incident_id": follower, "case": leader_id, "why": why}, sort_keys=True), now))
    return follower


def case_followers(incident_id: str, limit: int = 8) -> list[dict]:
    """The followers of a case (newest first), each with its first event: their evidence goes to the leader's fix."""
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT i.id,i.signature,i.occurrences,i.first_seen,
              (SELECT message FROM log_events e WHERE e.incident_id=i.id ORDER BY e.timestamp ASC LIMIT 1) AS message,
              (SELECT traceback FROM log_events e WHERE e.incident_id=i.id ORDER BY e.timestamp ASC LIMIT 1) AS traceback
            FROM incidents i WHERE i.case_id=? ORDER BY i.first_seen DESC LIMIT ?""", (incident_id, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def start_check_window(incident_id: str, seconds: int | None = None) -> str:
    """After a fix is pushed: related events for a few minutes are the old problem draining away, not new work."""
    import cases
    until = (datetime.now(timezone.utc) + timedelta(seconds=seconds or cases.check_window_seconds())).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        _execute(conn, "UPDATE incidents SET check_until=? WHERE id=?", (until, incident_id))
        conn.commit()
    finally:
        conn.close()
    return until


CASE_IMAGES_KEPT = 10                   # up to 3 owner screenshots per message, plus the browser check's phone and desktop shots


def add_case_image(incident_id: str, project_id: str, mime: str, data: bytes, note: str = "") -> str:
    """Keep a screenshot the owner sent with a case (base64 text, works on SQLite and PostgreSQL). Only the newest few are kept."""
    import base64
    image_id = _id()
    conn = get_connection()
    try:
        _execute(conn, "INSERT INTO case_images(id,incident_id,project_id,mime,data,note,created_at) VALUES(?,?,?,?,?,?,?)",
                 (image_id, incident_id, project_id, mime[:40], base64.b64encode(data).decode("ascii"), note[:200], _now()))
        old = _execute(conn, "SELECT id FROM case_images WHERE incident_id=? ORDER BY created_at DESC", (incident_id,)).fetchall()
        for row in old[CASE_IMAGES_KEPT:]:
            _execute(conn, "DELETE FROM case_images WHERE id=?", (row["id"],))
        conn.commit()
    finally:
        conn.close()
    return image_id


def case_images(incident_id: str, limit: int = CASE_IMAGES_KEPT, with_data: bool = True) -> list[dict]:
    """Newest first: {id, mime, note, created_at[, data (bytes)]}."""
    import base64
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT * FROM case_images WHERE incident_id=? ORDER BY created_at DESC LIMIT ?", (incident_id, limit)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        item = {"id": r["id"], "mime": r["mime"], "note": r["note"], "created_at": r["created_at"], "project_id": r["project_id"]}
        if with_data:
            item["data"] = base64.b64decode(r["data"])
        out.append(item)
    return out


def get_case_image(image_id: str, incident_id: str, project_id: str) -> dict | None:
    import base64
    conn = get_connection()
    try:
        r = _execute(conn, "SELECT * FROM case_images WHERE id=? AND incident_id=? AND project_id=?",
                     (image_id, incident_id, project_id)).fetchone()
    finally:
        conn.close()
    return {"mime": r["mime"], "data": base64.b64decode(r["data"])} if r else None


def set_live_result(incident_id: str, text: str) -> None:
    conn = get_connection()
    try:
        _execute(conn, "UPDATE incidents SET live_result=? WHERE id=?", (text[:2000], incident_id))
        conn.commit()
    finally:
        conn.close()


def recent_open_report(project_id: str, signature: str, minutes: int = 5) -> str | None:
    """The same report text sent again within a few minutes (double click, impatient re-send): the id of the case on it."""
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        row = _execute(conn, """SELECT id,case_id FROM incidents WHERE project_id=? AND signature=? AND created_at>?
            ORDER BY created_at DESC LIMIT 1""", (project_id, signature, since)).fetchone()
        if not row:
            return None
        return row["case_id"] or row["id"]
    finally:
        conn.close()


def list_incidents(project_id: str, limit: int = 100):
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT * FROM incidents WHERE project_id=? AND status<>'merged' ORDER BY last_seen DESC LIMIT ?",
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
                    i.first_seen,i.last_seen,i.source,i.commit_sha,p.repo_owner,p.repo_name,p.branch,p.mode,
                    p.github_token_ciphertext,p.active_until,p.paused,p.ai_consent_at
          FROM incident_jobs j
          JOIN incidents i ON i.id=j.incident_id
          JOIN projects p ON p.id=i.project_id
          WHERE i.status IN ('diagnosing','queued','processing') AND i.occurrences>=? AND i.first_seen<=?
            AND p.paused=0 AND p.ai_consent_at<>'' AND p.active_until>? AND j.attempts<?
            AND NOT EXISTS (SELECT 1 FROM incidents o WHERE o.project_id=i.project_id AND o.id<>i.id AND o.status='processing')
            AND NOT EXISTS (SELECT 1 FROM fx_bugs b WHERE b.project_id=i.project_id AND b.incident_id<>i.id
                            AND b.status IN ('github_testing','verifying'))
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
                  "\n\nFix pull request opened: " + pr_url + ".",
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
    safe_reason = str(reason).replace("\n", " ")[:400]
    try:
        _execute(conn, "UPDATE incidents SET status='needs_human',report=COALESCE(report,'') || ? WHERE id=? AND project_id=?",
                 ("\n\nNo fix PR was created: " + safe_reason, incident_id, project_id))
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
          WHERE p.mode='auto' AND p.paused=0 AND i.status='pr_opened' AND i.no_automerge=0
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
        until = (max(now, existing_until) + timedelta(days=plans.PLAN_DAYS.get(order["plan"], 365))).isoformat(timespec="seconds")
        cur = _execute(conn, "INSERT INTO payments(id,user_id,razorpay_payment_id,amount,status,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(razorpay_payment_id) DO NOTHING",
                       (_id(),order["user_id"],payment_id,int(amount),"captured",now.isoformat(timespec="seconds")))
        if cur.rowcount == 0:
            conn.commit()
            return False
        _execute(conn, "UPDATE payment_orders SET status='paid' WHERE razorpay_order_id=?", (order_id,))
        _execute(conn, "INSERT INTO subscriptions(user_id,active_until,grant_type,granted_by,updated_at,plan) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET active_until=excluded.active_until,grant_type='paid',granted_by='',updated_at=excluded.updated_at,plan=excluded.plan",
                 (order["user_id"],until,"paid","",now.isoformat(timespec="seconds"),plans.PLAN_OF_PRODUCT.get(order["plan"], "basic")))
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


def get_subscription(user_id: str) -> dict | None:
    """{active_until, grant_type, plan} or None. v6: the plan decides the size of the usage bars."""
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT active_until,grant_type,plan FROM subscriptions WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None
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


def _grant_in_conn(conn, user_id: str, days: int, grant_type: str, granted_by: str, plan: str | None = None) -> str:
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
    if plan in ("basic", "pro") and grant_type == "paid":
        _execute(conn, "UPDATE subscriptions SET plan=? WHERE user_id=?", (plan, user_id))
    _execute(conn, "UPDATE projects SET active_until=? WHERE user_id=?", (until, user_id))
    _execute(conn, "UPDATE projects SET paused=0 WHERE user_id=? AND paused=2", (user_id,))
    return until


def admin_grant_access(user_id: str, days: int, grant_type: str, granted_by: str, plan: str | None = None) -> str:
    if not 1 <= int(days) <= 3650 or grant_type not in ("trial", "paid"):
        raise ValueError("Access grant must be 1-3650 days and trial or paid")
    if plan not in (None, "basic", "pro"):
        raise ValueError("Plan must be basic or pro")
    conn = get_connection()
    try:
        until = _grant_in_conn(conn, user_id, days, grant_type, granted_by, plan)
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
    if not plans.valid_amount(plan, amount):
        raise ValueError("The amount does not match the selected plan.")
    if plan in plans.ADDON_PRODUCTS and not user_has_active_access(user_id):
        raise ValueError("Add-ons need an active plan. Pick a plan first.")
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
        # Current prices, or the pre-v2 prices for a payment the customer submitted before the change.
        if not plans.valid_amount_or_legacy(row["plan"], row["amount"]):
            raise ValueError("This payment record has an invalid plan or amount.")
        cur = _execute(conn, """UPDATE manual_payments SET status='approved',reviewed_at=?,reviewed_by=?
            WHERE id=? AND status='pending'""", (_now(), reviewed_by, payment_id))
        if cur.rowcount != 1:
            conn.rollback()
            return None
        result = dict(row)
        if row["plan"] == "project_slot":
            _execute(conn, "UPDATE users SET project_slots=COALESCE(project_slots,0)+1 WHERE id=?", (row["user_id"],))
            conn.commit()
            result.update(status="approved", product="project_slot", days=0, active_until="")
            return result
        if row["plan"] in plans.TOPUP_TIERS or row["plan"] in plans.PACK_TIERS:
            conn.commit()
            # The bar ledger lives in the fix engine's tables (same database).
            from fixengine import admin_tools
            if row["plan"] in plans.TOPUP_TIERS:
                credited = admin_tools.sell_topup(row["user_id"], plans.TOPUP_TIERS[row["plan"]], reviewed_by)
            else:
                credited = admin_tools.sell_pack(row["user_id"], plans.PACK_TIERS[row["plan"]][0], reviewed_by)
            result.update(status="approved", product=row["plan"], days=0, active_until="", credited=credited)
            return result
        days = plans.PLAN_DAYS.get(row["plan"], 365)
        until = _grant_in_conn(conn, row["user_id"], days, "paid", reviewed_by, plans.PLAN_OF_PRODUCT.get(row["plan"], "basic"))
        conn.commit()
        result.update(status="approved", product=row["plan"], days=days, active_until=until)
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
        rows = _execute(conn, """SELECT p.*,u.email AS owner_email,
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


def add_review(user_id: str, email: str, name: str, rating: int, text: str, can_publish: bool,
               project_id: str = "", incident_id: str = "") -> dict:
    """v6: a customer's review (1-5 stars, words, and whether we may show it on the website). Collected during the launch
    pilots as proof for the next organizer."""
    rating = int(rating)
    if not 1 <= rating <= 5:
        raise ValueError("Rating must be 1 to 5")
    conn = get_connection()
    try:
        rid = _id()
        _execute(conn, """INSERT INTO reviews(id, user_id, email, name, rating, text, can_publish, project_id, incident_id, created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                 (rid, user_id, email.strip().lower(), name.strip()[:120], rating, text.strip()[:2000], 1 if can_publish else 0,
                  project_id[:64], incident_id[:64], _now()))
        conn.commit()
        return dict(_execute(conn, "SELECT * FROM reviews WHERE id=?", (rid,)).fetchone())
    finally:
        conn.close()


def list_reviews(limit: int = 100) -> list[dict]:
    conn = get_connection()
    try:
        return [dict(r) for r in _execute(conn, "SELECT * FROM reviews ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]
    finally:
        conn.close()


def review_stats() -> dict:
    """{count, average (one decimal, 0 when none), publishable}."""
    conn = get_connection()
    try:
        row = dict(_execute(conn, "SELECT COUNT(*) AS n, AVG(rating) AS avg, SUM(can_publish) AS pub FROM reviews").fetchone())
    finally:
        conn.close()
    return {"count": int(row.get("n") or 0), "average": round(float(row.get("avg") or 0), 1), "publishable": int(row.get("pub") or 0)}


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

_BOT_REGEX = re.compile(
    r"(googlebot|bingbot|yandexbot|duckduckbot|baiduspider|slurp|twitterbot|facebookexternalhit|"
    r"linkedinbot|embedly|quora link preview|showyoubot|outbrain|pinterest|slackbot|vkshare|"
    r"w3c_validator|headlesschrome|curl|wget|python-requests|urllib|postman|uptimerobot|"
    r"pingdom|render|crawler|spider|bot\b)",
    re.IGNORECASE
)


def record_unique_visitor(visitor_id: str, user_agent: str = "") -> bool:
    """Record a unique website visitor in visitor_tracking.
    Filters bots and automated requests.
    Returns True if this is a newly recorded unique visitor.
    """
    clean_id = str(visitor_id or "").strip()
    if not clean_id or not re.fullmatch(r"[0-9a-f-]{36}", clean_id):
        return False
    if user_agent and _BOT_REGEX.search(user_agent):
        return False
    conn = get_connection()
    try:
        now = _now()
        row = _execute(conn, "SELECT visitor_id, visit_count FROM visitor_tracking WHERE visitor_id = ?",
                       (clean_id,)).fetchone()
        if not row:
            _execute(conn, "INSERT INTO visitor_tracking(visitor_id, first_seen, last_notified, visit_count) VALUES(?,?,?,1)",
                     (clean_id, now, now))
            conn.commit()
            return True
        else:
            _execute(conn, "UPDATE visitor_tracking SET visit_count = visit_count + 1 WHERE visitor_id = ?",
                     (clean_id,))
            conn.commit()
            return False
    finally:
        conn.close()


def get_total_unique_visitors() -> int:
    """Return the cumulative number of unique human website visitors recorded to date."""
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT COUNT(*) as cnt FROM visitor_tracking").fetchone()
        return int(row["cnt"]) if row else 0
    finally:
        conn.close()


# ============================================================================================================
# Architecture v3: push-time checks ("catch it before you deploy"), project slots and live stages.
# ============================================================================================================

PUSH_FINAL = ("passed", "failed", "error", "superseded", "skipped")


def project_slot_info(user_id: str) -> dict:
    """{used, limit, free, extra}: every plan includes plans.INCLUDED_PROJECTS project(s); each paid slot adds one."""
    conn = get_connection()
    try:
        used = _execute(conn, "SELECT COUNT(*) AS n FROM projects WHERE user_id=?", (user_id,)).fetchone()["n"]
        row = _execute(conn, "SELECT project_slots FROM users WHERE id=?", (user_id,)).fetchone()
    finally:
        conn.close()
    extra = int((row["project_slots"] if row else 0) or 0)
    limit = plans.INCLUDED_PROJECTS + extra
    return {"used": int(used), "limit": limit, "free": max(0, limit - int(used)), "extra": extra}


def admin_add_project_slots(user_id: str, count: int = 1) -> int:
    conn = get_connection()
    try:
        _execute(conn, "UPDATE users SET project_slots=COALESCE(project_slots,0)+? WHERE id=?", (int(count), user_id))
        conn.commit()
        row = _execute(conn, "SELECT project_slots FROM users WHERE id=?", (user_id,)).fetchone()
        return int(row["project_slots"]) if row else 0
    finally:
        conn.close()


def set_project_watch(project_id: str, user_id: str, watch_mode: str) -> bool:
    if watch_mode not in WATCH_MODES:
        return False
    conn = get_connection()
    try:
        cur = _execute(conn, "UPDATE projects SET watch_mode=? WHERE id=? AND user_id=?", (watch_mode, project_id, user_id))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def set_project_webhook(project_id: str, webhook_id: str, secret_ciphertext: str) -> None:
    conn = get_connection()
    try:
        _execute(conn, "UPDATE projects SET webhook_id=?,webhook_secret_ciphertext=? WHERE id=?",
                 (str(webhook_id or ""), secret_ciphertext, project_id))
        conn.commit()
    finally:
        conn.close()


def get_project_any(project_id: str):
    """Owner-less read for trusted server code only (webhooks, worker). Never use it to answer a browser request."""
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def enqueue_push_check(project_id: str, user_id: str, sha: str, branch: str, *, source: str = "webhook",
                       pusher: str = "", commit_message: str = "") -> tuple[str, bool]:
    """Queue a sandbox check of one pushed commit. The same commit is never queued twice (webhook + poll + manual).
    Older checks of the same project that have not started yet are marked superseded: only the newest commit matters."""
    sha = str(sha or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{7,64}", sha):
        raise ValueError("Invalid commit id")
    conn = get_connection()
    try:
        existing = _execute(conn, "SELECT id FROM push_checks WHERE project_id=? AND sha=?", (project_id, sha)).fetchone()
        if existing:
            return existing["id"], False
        check_id = _id()
        now = _now()
        _execute(conn, """UPDATE push_checks SET status='superseded',stage='superseded',finished_at=?
                          WHERE project_id=? AND status='queued'""", (now, project_id))
        _execute(conn, """INSERT INTO push_checks(id,project_id,user_id,sha,branch,source,pusher,commit_message,status,stage,
                          available_at,created_at) VALUES(?,?,?,?,?,?,?,?,'queued','queued',?,?)""",
                 (check_id, project_id, user_id, sha, branch[:250], source, pusher[:100], commit_message[:300], now, now))
        conn.commit()
        return check_id, True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim_next_push_check(lease_seconds: int = 900, max_attempts: int = 6):
    """Lease one queued check whose project is active (paid or trial, not paused). Returns the check joined with its project."""
    now = datetime.now(timezone.utc)
    now_s = now.isoformat(timespec="seconds")
    lease = (now + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        if isinstance(conn, sqlite3.Connection):
            conn.execute("BEGIN IMMEDIATE")
        lock = "" if isinstance(conn, sqlite3.Connection) else " FOR UPDATE OF c SKIP LOCKED"
        row = _execute(conn, f"""SELECT c.id FROM push_checks c
            JOIN projects p ON p.id=c.project_id
            JOIN subscriptions s ON s.user_id=p.user_id
            WHERE ((c.status='queued' AND c.available_at<=?) OR (c.status='running' AND c.locked_until<?))
              AND c.attempts<? AND p.paused=0 AND s.active_until>? AND p.gate_state<>'waiting_private'
            ORDER BY c.available_at ASC LIMIT 1{lock}""", (now_s, now_s, max_attempts, now_s)).fetchone()
        if not row:
            conn.rollback()
            return None
        _execute(conn, """UPDATE push_checks SET status='running',stage='downloading',stage_detail='',attempts=attempts+1,
                          locked_until=?,started_at=CASE WHEN started_at='' THEN ? ELSE started_at END WHERE id=?""",
                 (lease, now_s, row["id"]))
        conn.commit()
        claimed = _execute(conn, """SELECT c.*, p.name AS project_name, p.repo_owner, p.repo_name, p.branch AS project_branch,
                p.mode, p.github_token_ciphertext, p.watch_mode, p.gate_state FROM push_checks c JOIN projects p ON p.id=c.project_id
                WHERE c.id=?""", (row["id"],)).fetchone()
        return dict(claimed) if claimed else None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_push_check_stage(check_id: str, stage: str, detail: str = "") -> None:
    conn = get_connection()
    try:
        _execute(conn, "UPDATE push_checks SET stage=?,stage_detail=? WHERE id=?", (stage, detail[:300], check_id))
        conn.commit()
    finally:
        conn.close()


def finish_push_check(check_id: str, status: str, *, output: str = "", stacks: list | None = None, incident_id: str = "",
                      stage: str | None = None, detail: str = "") -> None:
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT project_id,sha FROM push_checks WHERE id=?", (check_id,)).fetchone()
        _execute(conn, """UPDATE push_checks SET status=?,stage=?,stage_detail=?,output=?,stacks_json=?,incident_id=?,
                          locked_until=NULL,finished_at=? WHERE id=?""",
                 (status, stage or status, detail[:300], output[-6000:], json.dumps(stacks or []), incident_id, _now(), check_id))
        if row and status in ("passed", "failed"):
            _execute(conn, "UPDATE projects SET last_checked_sha=?,last_check_status=?,last_check_at=?,status=CASE WHEN status IN ('pending_install','') THEN 'connected' ELSE status END WHERE id=?",
                     (row["sha"], status, _now(), row["project_id"]))
        conn.commit()
    finally:
        conn.close()


def retry_push_check(check_id: str, delay_seconds: int, reason: str) -> None:
    """A fault on our side (sandbox offline, GitHub timeout): put the check back in the queue, never count it as a result."""
    when = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        _execute(conn, """UPDATE push_checks SET status=CASE WHEN attempts>=6 THEN 'error' ELSE 'queued' END,
                          stage=CASE WHEN attempts>=6 THEN 'error' ELSE 'waiting_retry' END,
                          stage_detail=?,available_at=?,locked_until=NULL WHERE id=?""", (reason[:300], when, check_id))
        conn.commit()
    finally:
        conn.close()


def list_push_checks(project_id: str, limit: int = 15) -> list[dict]:
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT * FROM push_checks WHERE project_id=? AND status<>'superseded' ORDER BY created_at DESC LIMIT ?",
                        (project_id, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def user_push_checks(user_id: str, limit: int = 10) -> list[dict]:
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT c.*, p.name AS project_name FROM push_checks c JOIN projects p ON p.id=c.project_id
                                 WHERE p.user_id=? AND c.status<>'superseded' ORDER BY c.created_at DESC LIMIT ?""",
                        (user_id, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def projects_to_poll() -> list[dict]:
    """Active projects that want push checks. The worker compares each branch head with the last commit it saw."""
    now_s = _now()
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT p.* FROM projects p JOIN subscriptions s ON s.user_id=p.user_id
                                 WHERE p.paused=0 AND s.active_until>? AND p.watch_mode IN ('push','both')
                                   AND p.gate_state<>'waiting_private'""", (now_s,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def latest_push_sha(project_id: str) -> str:
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT sha FROM push_checks WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
        return row["sha"] if row else ""
    finally:
        conn.close()


def push_checks_last_hour(project_id: str) -> int:
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        return int(_execute(conn, "SELECT COUNT(*) AS n FROM push_checks WHERE project_id=? AND created_at>? AND status<>'superseded'",
                            (project_id, since)).fetchone()["n"])
    finally:
        conn.close()


def mark_incident_source(incident_id: str, source: str, commit_sha: str = "") -> None:
    conn = get_connection()
    try:
        _execute(conn, "UPDATE incidents SET source=?,commit_sha=? WHERE id=?", (source, commit_sha[:64], incident_id))
        conn.commit()
    finally:
        conn.close()


def set_incident_stage(incident_id: str, stage: str, detail: str = "", tier: str = "") -> None:
    """What the agent is doing for this incident right now (shown live on the dashboard)."""
    conn = get_connection()
    try:
        _execute(conn, "UPDATE incidents SET stage=?,stage_detail=?,stage_tier=?,stage_at=? WHERE id=?",
                 (stage, detail[:300], tier, _now(), incident_id))
        conn.commit()
    finally:
        conn.close()


def get_incident_row(incident_id: str):
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def resolve_incident(incident_id: str, project_id: str, note: str = "") -> None:
    conn = get_connection()
    try:
        _execute(conn, """UPDATE incidents SET status='resolved',resolved_at=?,stage='resolved',stage_detail=?,stage_at=?
                          WHERE id=? AND project_id=?""", (_now(), note[:300], _now(), incident_id, project_id))
        _execute(conn, "UPDATE incident_jobs SET status='done',locked_until=NULL,updated_at=? WHERE incident_id=?", (_now(), incident_id))
        conn.commit()
    finally:
        conn.close()


def user_live_work(user_id: str, limit: int = 12) -> dict:
    """Everything the agent is doing (or just did) for this customer: open incidents and recent push checks."""
    conn = get_connection()
    try:
        incidents = _execute(conn, """SELECT i.*, p.name AS project_name, p.mode AS project_mode, p.branch AS project_branch
            FROM incidents i JOIN projects p ON p.id=i.project_id WHERE p.user_id=? AND i.status<>'merged'
            ORDER BY CASE WHEN i.status IN ('resolved','reverted') THEN 1 ELSE 0 END, i.last_seen DESC LIMIT ?""",
            (user_id, limit)).fetchall()
        checks = _execute(conn, """SELECT c.*, p.name AS project_name FROM push_checks c JOIN projects p ON p.id=c.project_id
            WHERE p.user_id=? AND c.status<>'superseded' ORDER BY c.created_at DESC LIMIT ?""", (user_id, limit)).fetchall()
        return {"incidents": [dict(r) for r in incidents], "checks": [dict(r) for r in checks]}
    finally:
        conn.close()


def admin_push_check_stats() -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT status, COUNT(*) AS n FROM push_checks WHERE created_at>? GROUP BY status", (since,)).fetchall()
        return {r["status"]: int(r["n"]) for r in rows}
    finally:
        conn.close()


def resolve_push_incidents(project_id: str, note: str) -> int:
    """A later push passed every check: close the push-detected incidents that are not being worked on right now."""
    now = _now()
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT id FROM incidents WHERE project_id=? AND source='push'
            AND status NOT IN ('resolved','reverted') AND stage NOT IN ('thinking','testing_fix','pushing')""", (project_id,)).fetchall()
        for r in rows:
            _execute(conn, """UPDATE incidents SET status='resolved',resolved_at=?,stage='resolved',stage_detail=?,stage_at=? WHERE id=?""",
                     (now, note[:300], now, r["id"]))
            _execute(conn, "UPDATE incident_jobs SET status='done',locked_until=NULL,updated_at=? WHERE incident_id=?", (now, r["id"]))
        conn.commit()
        return len(rows)
    finally:
        conn.close()


# ============================================================================================================
# Monitoring v2: public-repo gate, multi-language monitors and check-in (heartbeat) tracking.
# ============================================================================================================
GATE_WAITING = "waiting_private"   # repository is public: nothing is committed until it is private
GATE_ACTIVE = "active"             # repository verified private: monitor installed / fixes allowed
GATE_PUBLIC = "public_pr"          # repository is public: pull requests only, push checks on, no live monitor (its key would be public)


def set_project_mode_and_watch(project_id: str, mode: str | None = None, watch_mode: str | None = None) -> None:
    conn = get_connection()
    try:
        if mode:
            _execute(conn, "UPDATE projects SET mode=? WHERE id=?", (mode, project_id))
        if watch_mode:
            _execute(conn, "UPDATE projects SET watch_mode=? WHERE id=?", (watch_mode, project_id))
        conn.commit()
    finally:
        conn.close()
MONITOR_OFFLINE_SECONDS = int(os.getenv("MONITOR_OFFLINE_SECONDS", "120") or 120)       # 4 missed 30-second check-ins
MONITOR_FIRST_CHECKIN_GRACE_SECONDS = int(os.getenv("MONITOR_FIRST_CHECKIN_GRACE_SECONDS", "1800") or 1800)


def set_gate_state(project_id: str, state: str, *, notified: bool = False) -> None:
    conn = get_connection()
    try:
        now = _now()
        if notified:
            _execute(conn, "UPDATE projects SET gate_state=?,gate_checked_at=?,gate_notified_at=? WHERE id=?", (state, now, now, project_id))
        else:
            _execute(conn, "UPDATE projects SET gate_state=?,gate_checked_at=? WHERE id=?", (state, now, project_id))
        conn.commit()
    finally:
        conn.close()


def record_monitor_install(project_id: str, targets: list, *, installed: bool) -> None:
    """Remember which monitors were put into the repo (shown on the project page) and when."""
    conn = get_connection()
    try:
        if installed:
            _execute(conn, "UPDATE projects SET monitor_targets_json=?,monitor_installed_at=? WHERE id=?",
                     (json.dumps(targets or [])[:20000], _now(), project_id))
        else:
            _execute(conn, "UPDATE projects SET monitor_targets_json=? WHERE id=?", (json.dumps(targets or [])[:20000], project_id))
        conn.commit()
    finally:
        conn.close()


def record_heartbeat(project_id: str, monitor: str, component: str = "", version: str = "", runtime: str = "", touch_project: bool = True) -> None:
    """One check-in from one monitor (python / node / browser) of one part of the repo."""
    monitor = (monitor or "unknown")[:20]
    component = (component or "")[:80]
    now = _now()
    conn = get_connection()
    try:
        _execute(conn, """INSERT INTO monitor_heartbeats(project_id,monitor,component,first_seen,last_seen,beats,version,runtime)
                          VALUES(?,?,?,?,?,1,?,?) ON CONFLICT(project_id,monitor,component) DO UPDATE SET
                          last_seen=excluded.last_seen,beats=monitor_heartbeats.beats+1,version=excluded.version,runtime=excluded.runtime""",
                 (project_id, monitor, component, now, now, version[:20], runtime[:40]))
        if touch_project:     # the site check ('probe') must not hide that the monitor itself was never deployed
            _execute(conn, "UPDATE projects SET status='connected',last_heartbeat_at=?,monitor_alerted_at='' WHERE id=?", (now, project_id))
        conn.commit()
    finally:
        conn.close()


def list_monitor_heartbeats(project_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT * FROM monitor_heartbeats WHERE project_id=? ORDER BY monitor, component", (project_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _age_seconds(value: str) -> float | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds()


def monitor_state(project: dict, beats: list[dict] | None = None) -> dict:
    """Plain-language monitor status for one project. Never silent: 'never checked in' and 'offline' are states too.

    Returns {state, tone, headline, detail, last_checkin, server_side}. States:
      waiting_private | not_installed | install_failed | waiting_first | never_checked_in | online | offline | idle_browser | push_only
    """
    watch = project.get("watch_mode") or "both"
    if project.get("gate_state") == GATE_WAITING:
        return {"state": "waiting_private", "tone": "amber", "headline": "Waiting for private repo",
                "detail": "Make the repository private to finish setup. Nothing has been installed yet.", "last_checkin": "", "server_side": False}
    if watch == "push":
        return {"state": "push_only", "tone": "", "headline": "Live monitor off (push checks only)", "detail": "", "last_checkin": "",
                "server_side": False}
    beats = beats if beats is not None else list_monitor_heartbeats(project["id"])
    beats = [b for b in beats if b["monitor"] != "probe"]          # the site check has its own line (site_check_state)
    try:
        targets = json.loads(project.get("monitor_targets_json") or "[]")
    except ValueError:
        targets = []
    server_kinds = {t.get("kind") for t in targets if t.get("wired")} - {"browser"}
    last = project.get("last_heartbeat_at") or max((b["last_seen"] for b in beats), default="")
    age = _age_seconds(last)
    installed_age = _age_seconds(project.get("monitor_installed_at") or "")
    server_beats = [b for b in beats if b["monitor"] != "browser"]
    if age is None:
        if not project.get("monitor_installed_at") and not project.get("install_pr_url"):
            return {"state": "not_installed", "tone": "amber", "headline": "Monitor not installed",
                    "detail": "Press Install monitoring below.", "last_checkin": "", "server_side": bool(server_kinds)}
        if installed_age is not None and installed_age > MONITOR_FIRST_CHECKIN_GRACE_SECONDS:
            return {"state": "never_checked_in", "tone": "red", "headline": "Never checked in",
                    "detail": "Why: the monitor lives inside your app and only reports while the app is running online. If your app is not hosted (deployed) anywhere yet, it can never check in. That is not an error: push checks and your own reports to the agent work without it. If your app IS online: it was not re-deployed after monitoring was added. Open your host "
                              "(Vercel, Render, Netlify ...), press Redeploy, then open your site once.",
                    "last_checkin": "", "server_side": bool(server_kinds)}
        return {"state": "waiting_first", "tone": "amber", "headline": "Waiting for the first check-in",
                "detail": "Why: the monitor lives inside your app and only reports while the app is running online. If your app is not hosted (deployed) anywhere yet, it can never check in. That is not an error: push checks and your own reports to the agent work without it. When your app is online: re-deploy it (and merge the monitoring pull request if one is still "
                          "open), then open your site once. The first check-in arrives within 30 seconds.", "last_checkin": "", "server_side": bool(server_kinds)}
    if age <= MONITOR_OFFLINE_SECONDS:
        return {"state": "online", "tone": "green", "headline": "Live", "detail": "", "last_checkin": last, "server_side": bool(server_kinds)}
    if not server_kinds and not server_beats:
        return {"state": "idle_browser", "tone": "", "headline": "No visitors right now",
                "detail": "Your site is only watched while someone has it open in a browser. It checks in again with the next visitor.",
                "last_checkin": last, "server_side": False}
    return {"state": "offline", "tone": "red", "headline": "Monitor offline",
            "detail": "No check-in for a while. Your app may be down, asleep (free hosting sleeps after ~15 minutes), or was "
                      "re-deployed without the monitor.", "last_checkin": last, "server_side": True}


def site_check_state(project: dict, beats: list[dict] | None = None) -> dict:
    """The 30-second check of the site address itself: {state: answering|silent|no_address, headline, detail}."""
    if not (project.get("app_url") or "").strip():
        return {"state": "no_address", "tone": "", "headline": "Site check: no site address yet",
                "detail": "Add your live site address (or set it as the repository's website on GitHub) and the agent checks it every 30 seconds."}
    beats = beats if beats is not None else list_monitor_heartbeats(project["id"])
    probe = next((b for b in beats if b["monitor"] == "probe"), None)
    age = _age_seconds(probe["last_seen"]) if probe else None
    if age is not None and age <= 120:
        return {"state": "answering", "tone": "green", "headline": "Site check: your site is answering", "detail": "Checked every 30 seconds.",
                "last_checkin": probe["last_seen"]}
    return {"state": "silent", "tone": "amber", "headline": "Site check: no good answer lately",
            "detail": "The agent could not get a normal page from your site address in the last two minutes (the host may be down or asleep).",
            "last_checkin": probe["last_seen"] if probe else ""}


def projects_needing_monitor_alert() -> list[dict]:
    """Projects whose server-side monitor went offline (or never checked in) and whose owner was not told yet."""
    now_s = _now()
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT p.* FROM projects p JOIN subscriptions s ON s.user_id=p.user_id
            WHERE p.paused=0 AND s.active_until>? AND p.watch_mode IN ('runtime','both') AND p.gate_state<>'waiting_private'
              AND p.monitor_installed_at<>'' AND p.monitor_alerted_at=''""", (now_s,)).fetchall()
        projects = [dict(r) for r in rows]
    finally:
        conn.close()
    out = []
    for p in projects:
        state = monitor_state(p)
        if state["state"] in ("offline", "never_checked_in") and state["server_side"]:
            out.append({**p, "monitor": state})
    return out


def set_monitor_alerted(project_id: str) -> None:
    conn = get_connection()
    try:
        _execute(conn, "UPDATE projects SET monitor_alerted_at=? WHERE id=?", (_now(), project_id))
        conn.commit()
    finally:
        conn.close()


def projects_for_visibility_check(min_age_seconds: int = 1800) -> list[dict]:
    """Active (installed) projects whose repository visibility was not re-checked recently."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=min_age_seconds)).isoformat(timespec="seconds")
    now_s = _now()
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT p.* FROM projects p JOIN subscriptions s ON s.user_id=p.user_id
            WHERE p.paused=0 AND s.active_until>? AND p.gate_checked_at<?""",
                        (now_s, cutoff)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def projects_waiting_private(user_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = _execute(conn, "SELECT * FROM projects WHERE user_id=? AND gate_state='waiting_private' ORDER BY created_at",
                        (user_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def mark_static_done(check_id: str) -> None:
    conn = get_connection()
    try:
        _execute(conn, "UPDATE push_checks SET static_done=1 WHERE id=?", (check_id,))
        conn.commit()
    finally:
        conn.close()


def resolve_scan_incidents(project_id: str, keep_signatures: set[str], note: str) -> int:
    """Close scan findings (retired AI models) that the newest scan no longer finds."""
    now = _now()
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT id,signature FROM incidents WHERE project_id=? AND source='scan'
            AND status NOT IN ('resolved','reverted','pr_opened')""", (project_id,)).fetchall()
        closed = 0
        for r in rows:
            if r["signature"] in keep_signatures:
                continue
            _execute(conn, "UPDATE incidents SET status='resolved',resolved_at=?,stage='resolved',stage_detail=?,stage_at=? WHERE id=?",
                     (now, note[:300], now, r["id"]))
            _execute(conn, "UPDATE incident_jobs SET status='done',locked_until=NULL,updated_at=? WHERE incident_id=?", (now, r["id"]))
            closed += 1
        conn.commit()
        return closed
    finally:
        conn.close()


def park_incident_for_gate(incident_id: str, project_id: str, delay_seconds: int = 1800) -> None:
    """The repository is public: keep the incident, try again later (after the owner makes the repo private)."""
    when = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        _execute(conn, "UPDATE incidents SET status='queued',stage='waiting_private',stage_detail=?,stage_at=? WHERE id=? AND project_id=?",
                 ("Your repository is public, so the fix was not pushed. Make it private and it continues.", _now(), incident_id, project_id))
        _execute(conn, """UPDATE incident_jobs SET status='queued',available_at=?,locked_until=NULL,
                          attempts=CASE WHEN attempts>0 THEN attempts-1 ELSE 0 END,updated_at=? WHERE incident_id=?""",
                 (when, _now(), incident_id))
        conn.commit()
    finally:
        conn.close()


def unpark_gate_incidents(project_id: str) -> int:
    conn = get_connection()
    try:
        cur = _execute(conn, """UPDATE incident_jobs SET available_at=?,updated_at=? WHERE incident_id IN
            (SELECT id FROM incidents WHERE project_id=? AND stage='waiting_private')""", (_now(), _now(), project_id))
        _execute(conn, "UPDATE incidents SET stage='queued',stage_detail='the repository is private again: continuing' WHERE project_id=? AND stage='waiting_private'",
                 (project_id,))
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()


def project_history(project_id: str, limit: int = 6) -> list[dict]:
    """Earlier cases of this project and what fixed them (the on-call engineer's memory of this client)."""
    conn = get_connection()
    try:
        rows = _execute(conn, """SELECT signature,root_cause,status,COALESCE(resolved_at,last_seen) AS when_at FROM incidents
            WHERE project_id=? AND case_id='' AND root_cause<>'' ORDER BY last_seen DESC LIMIT ?""", (project_id, limit)).fetchall()
        return [{"signature": r["signature"], "root_cause": r["root_cause"], "status": r["status"], "when": r["when_at"] or ""} for r in rows]
    finally:
        conn.close()


def reopen_incident_with_reply(incident_id: str, project_id: str, text: str) -> bool:
    """The client replied on a case: answer to the agent's question, or 'it still does not work'. The SAME case continues
    (never a new incident), and it is queued again right away."""
    now = _now()
    conn = get_connection()
    try:
        row = _execute(conn, "SELECT id,status,case_id FROM incidents WHERE id=? AND project_id=?", (incident_id, project_id)).fetchone()
        if not row:
            return False
        target = row["case_id"] or row["id"]
        _execute(conn, "INSERT INTO log_events(id,project_id,timestamp,level,message,traceback,signature,dedupe_hash,incident_id) "
                       "VALUES(?,?,?,?,?,?,?,?,?)",
                 (_id(), project_id, now, "INFO", "[client reply] " + text[:300], "", "client_reply",
                  hashlib.sha256(f"{target}\0{now}\0{text}".encode("utf-8")).hexdigest(), target))
        cur = _execute(conn, f"""UPDATE incidents SET status='diagnosing',stage='queued',stage_detail=?,stage_at=?,check_until=''
            WHERE id=? AND project_id=? AND status NOT IN ('merged')""",
            ("Your reply was added to this case. The agent continues now.", now, target, project_id))
        if cur.rowcount != 1:
            conn.rollback()
            return False
        _execute(conn, """INSERT INTO incident_jobs(incident_id,status,attempts,available_at,locked_until,last_error,updated_at)
            VALUES(?,?,?,?,NULL,'',?) ON CONFLICT(incident_id) DO UPDATE SET status='queued',attempts=0,available_at=excluded.available_at,
            locked_until=NULL,last_error='',updated_at=excluded.updated_at""", (target, "queued", 0, now, now))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def requeue_incident(incident_id: str, project_id: str, detail: str) -> bool:
    """Put a case back in the queue (the live site still fails after the pushed fix)."""
    now = _now()
    conn = get_connection()
    try:
        cur = _execute(conn, """UPDATE incidents SET status='diagnosing',resolved_at=NULL,check_until='',stage='queued',stage_detail=?,stage_at=?
            WHERE id=? AND project_id=? AND status<>'merged'""", (detail[:300], now, incident_id, project_id))
        if cur.rowcount != 1:
            conn.rollback()
            return False
        _execute(conn, """INSERT INTO incident_jobs(incident_id,status,attempts,available_at,locked_until,last_error,updated_at)
            VALUES(?,?,?,?,NULL,'',?) ON CONFLICT(incident_id) DO UPDATE SET status='queued',attempts=0,available_at=excluded.available_at,
            locked_until=NULL,last_error='',updated_at=excluded.updated_at""", (incident_id, "queued", 0, now, now))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


# ---- v4: pause / resume a case, auto-start, long engineer runs ------------------------------------------------------------------
PAUSABLE = ("diagnosing", "queued", "processing", "awaiting_choice")


def pause_incident(incident_id: str, project_id: str) -> bool:
    """The owner pauses one case: the agent stops working on it (a running engineer stops at its next step) and spends nothing."""
    now = _now()
    conn = get_connection()
    try:
        marks = ",".join("'" + s + "'" for s in PAUSABLE)
        cur = _execute(conn, f"""UPDATE incidents SET status='paused',stage='paused',stage_detail=?,stage_at=?
            WHERE id=? AND project_id=? AND status IN ({marks})""", ("Paused by you. Nothing is spent while it is paused.", now, incident_id, project_id))
        if cur.rowcount != 1:
            conn.rollback()
            return False
        _execute(conn, "UPDATE incident_jobs SET status='paused',locked_until=NULL,updated_at=? WHERE incident_id=?", (now, incident_id))
        _execute(conn, "INSERT INTO audit_log(id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                 (_id(), project_id, "incident_paused", json.dumps({"incident_id": incident_id}), now))
        conn.commit()
        return True
    finally:
        conn.close()


def resume_incident(incident_id: str, project_id: str) -> bool:
    now = _now()
    conn = get_connection()
    try:
        cur = _execute(conn, """UPDATE incidents SET status='diagnosing',stage='queued',stage_detail=?,stage_at=?
            WHERE id=? AND project_id=? AND status='paused'""", ("Started. The agent picks it up in a few seconds.", now, incident_id, project_id))
        if cur.rowcount != 1:
            conn.rollback()
            return False
        _execute(conn, """INSERT INTO incident_jobs(incident_id,status,attempts,available_at,locked_until,last_error,updated_at)
            VALUES(?,?,?,?,NULL,'',?) ON CONFLICT(incident_id) DO UPDATE SET status='queued',attempts=0,available_at=excluded.available_at,
            locked_until=NULL,last_error='',updated_at=excluded.updated_at""", (incident_id, "queued", 0, now, now))
        _execute(conn, "INSERT INTO audit_log(id,project_id,action,detail,created_at) VALUES(?,?,?,?,?)",
                 (_id(), project_id, "incident_resumed", json.dumps({"incident_id": incident_id}), now))
        conn.commit()
        return True
    finally:
        conn.close()


def pause_all_incidents(project_id: str) -> int:
    rows = [r["id"] for r in list_incidents(project_id, 200) if r.get("status") in PAUSABLE]
    return sum(1 for iid in rows if pause_incident(iid, project_id))


def set_auto_start(project_id: str, user_id: str, on: bool) -> bool:
    conn = get_connection()
    try:
        cur = _execute(conn, "UPDATE projects SET auto_start=? WHERE id=? AND user_id=?", (1 if on else 0, project_id, user_id))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def extend_lease(incident_id: str, seconds: int = 1200) -> None:
    """A long engineer run keeps its claim on the case (otherwise the worker would think it died after 10 minutes)."""
    until = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")
    conn = get_connection()
    try:
        _execute(conn, "UPDATE incident_jobs SET locked_until=? WHERE incident_id=? AND status='processing'", (until, incident_id))
        conn.commit()
    finally:
        conn.close()
