"""
sync_and_tail.py - Pull latest code & logs from GitHub, ingest into DB, and return pending incidents.
"""

import json
import os
import re
import sys
from pathlib import Path

from db import get_connection, init_db, record_incident, save_event
from repo_sync import get_local_repo

FRAME = re.compile(r'File "([^"]+)", line (\d+)')
LOG_RELATIVE_PATH = "logs/app.log"


def signature(tb):
    if not tb:
        return None
    lines = [l for l in tb.strip().splitlines() if l.strip()]
    err = lines[-1].split(":")[0].strip()
    frames = FRAME.findall(tb)
    mine = [f for f in frames if "site-packages" not in f[0]]
    path, line = (mine or frames or [("?", "0")])[-1]
    return f"{err}:{os.path.basename(path)}:{line}"


def handle_line(line):
    try:
        e = json.loads(line)
    except json.JSONDecodeError:
        return None, False

    tb = e.get("traceback")
    sig = signature(tb)

    row_id = save_event(
        e.get("ts"),
        e.get("level"),
        e.get("service"),
        e.get("message"),
        tb,
        sig,
    )

    incident_id, is_new = None, False
    if e.get("level") == "ERROR" and sig:
        incident_id, is_new = record_incident(sig, e.get("ts"))
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE log_events SET incident_id = ? WHERE id = ?",
                (incident_id, row_id),
            )
            conn.commit()
        finally:
            conn.close()

    return incident_id, is_new


def sync_and_tail(service: str = "shop-api"):
    folder = get_local_repo(service)
    log_path = Path(folder) / LOG_RELATIVE_PATH
    if not log_path.exists():
        print(f"Log file not found at: {log_path}")
        return 0, []

    init_db()
    lines_read = 0
    new_incidents_count = 0
    created_incident_ids = set()

    with open(log_path, encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if raw_line:
                inc_id, is_new = handle_line(raw_line)
                lines_read += 1
                if is_new and inc_id:
                    new_incidents_count += 1
                    created_incident_ids.add(inc_id)

    # Get all incidents currently waiting for diagnosis
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM incidents WHERE status = 'diagnosing' AND resolved_at IS NULL"
        ).fetchall()
        pending_ids = [r[0] for r in rows]
    finally:
        conn.close()

    return new_incidents_count, pending_ids


if __name__ == "__main__":
    svc = sys.argv[1] if len(sys.argv) > 1 else "shop-api"
    new_count, pending = sync_and_tail(svc)
    print(f"Done. New incidents: {new_count}, Pending diagnosis: {pending}")
