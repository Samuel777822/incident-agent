import json
import sqlite3
import pathlib
from datetime import datetime

DB_PATH = "incidents.db"
SCHEMA_PATH = pathlib.Path(__file__).parent / "schema.sql"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='incidents'")
        if not cur.fetchone() and SCHEMA_PATH.exists():
            cur.executescript(SCHEMA_PATH.read_text())
            conn.commit()
    except Exception:
        pass
    return conn


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA_PATH.read_text())
    conn.commit()
    conn.close()


def save_event(ts, level, service, message, traceback=None, signature=None):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO log_events (ts, level, service, message, traceback, signature) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ts, level, service, message, traceback, signature),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id

def record_incident(signature, ts):
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM incidents WHERE signature = ? AND resolved_at IS NULL",
        (signature,),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE incidents SET occurrences = occurrences + 1, last_seen = ? WHERE id = ?",
            (ts, row["id"]),
        )
        incident_id, is_new = row["id"], False
    else:
        cur = conn.execute(
            "INSERT INTO incidents (signature, first_seen, last_seen) VALUES (?, ?, ?)",
            (signature, ts, ts),
        )
        incident_id, is_new = cur.lastrowid, True
    conn.commit()
    conn.close()
    return incident_id, is_new

def get_incident(incident_id=None):
    conn = get_connection()
    try:
        if incident_id is None:
            row = conn.execute(
                "SELECT * FROM incidents "
                "WHERE resolved_at IS NULL AND status = 'diagnosing' "
                "ORDER BY id LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_incident_events(incident_id, limit=20):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, ts, level, service, message, traceback, signature "
            "FROM log_events WHERE incident_id = ? ORDER BY id LIMIT ?",
            (incident_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def save_diagnosis(incident_id, d):
    details = {
        "evidence": d["evidence"],
        "recommended_fix": d["recommended_fix"],
        "still_present_in_current_code": d["still_present_in_current_code"],
        "safe_to_auto_fix": d["safe_to_auto_fix"],
    }
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE incidents SET category = ?, confidence = ?, root_cause = ?, "
            "explanation = ?, report = ?, status = 'diagnosed' WHERE id = ?",
            (
                d["category"], d["confidence"], d["root_cause"],
                json.dumps(details, indent=2), d["report"], incident_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

def save_fix(incident_id, branch, file_path, fixed_file, tests_passed):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO fixes (incident_id, branch, file_path, fixed_file, tests_passed) "
            "VALUES (?, ?, ?, ?, ?)",
            (incident_id, branch, file_path, fixed_file, 1 if tests_passed else 0),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_fix_count(incident_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM fixes WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def update_incident_status(incident_id, status, pr_url=None):
    conn = get_connection()
    try:
        if status == "resolved":
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "UPDATE incidents SET status = ?, pr_url = COALESCE(?, pr_url), resolved_at = ? WHERE id = ?",
                (status, pr_url, now, incident_id),
            )
        else:
            conn.execute(
                "UPDATE incidents SET status = ?, pr_url = COALESCE(?, pr_url) WHERE id = ?",
                (status, pr_url, incident_id),
            )
        conn.commit()
    finally:
        conn.close()


def resolve_incident(incident_id):
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE incidents SET status = 'resolved', resolved_at = ? "
            "WHERE id = ? AND resolved_at IS NULL",
            (now, incident_id),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    print("tables created")