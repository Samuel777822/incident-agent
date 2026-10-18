"""
sync_and_tail.py - pull the latest code, ingest only NEW log lines, and
return the incidents that are waiting for a diagnosis.
"""

import json
import os
import re
import sys
from pathlib import Path

from config import get_repo_config
from db import get_connection, init_db, record_incident, save_event
from repo_sync import get_local_repo

FRAME = re.compile(r'File "([^"]+)", line (\d+)')
LOG_RELATIVE_PATH = "logs/app.log"
OFFSETS_FILE = Path(__file__).parent / "log_offsets.json"


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
    if not isinstance(e, dict):
        return None, False

    tb = e.get("traceback")
    sig = signature(tb)

    row_id = save_event(
        e.get("ts"), e.get("level"), e.get("service"), e.get("message"), tb, sig
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


def _load_offsets():
    try:
        return json.loads(OFFSETS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_offsets(offsets):
    OFFSETS_FILE.write_text(json.dumps(offsets, indent=2), encoding="utf-8")


def resolve_log_path(service, folder):
    # LOG_PATH_<SERVICE> in .env or the environment overrides repos.json
    env_name = "LOG_PATH_" + service.upper().replace("-", "_")
    configured = os.environ.get(env_name) or get_repo_config(service).get("log_path")
    if configured:
        return Path(configured)
    return Path(folder) / LOG_RELATIVE_PATHH


def read_new_lines(log_path):
    """Return only the complete lines added since the last call (a byte bookmark)."""
    offsets = _load_offsets()
    key = str(log_path)
    offset = int(offsets.get(key, 0))
    try:
        if log_path.stat().st_size < offset:
            offset = 0  # the file was truncated or replaced: start over
        with open(log_path, "rb") as f:
            f.seek(offset)
            data = f.read()
    except OSError as err:
        print(f"Could not read the log file: {err}")
        return []

    pieces = data.split(b"\n")
    complete = pieces[:-1]  # the last piece is a partial line (or empty): wait for the rest
    consumed = sum(len(p) + 1 for p in complete)

    lines = []
    for raw in complete:
        text = raw.decode("utf-8", errors="replace").strip()
        if text:
            lines.append(text)

    offsets[key] = offset + consumed
    _save_offsets(offsets)
    return lines


def sync_and_tail(service: str = "shop-api"):
    folder = get_local_repo(service)
    log_path = resolve_log_path(service, folder)
    init_db()

    new_incidents = 0
    if not log_path.exists():
        print(f"Log file not found at: {log_path}")
    else:
        for line in read_new_lines(log_path):
            incident_id, is_new = handle_line(line)
            if is_new and incident_id:
                new_incidents += 1

    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id FROM incidents WHERE status = 'diagnosing' AND resolved_at IS NULL"
        ).fetchall()
        pending_ids = [r[0] for r in rows]
    finally:
        conn.close()

    return new_incidents, pending_ids


if __name__ == "__main__":
    svc = sys.argv[1] if len(sys.argv) > 1 else "shop-api"
    new_count, pending = sync_and_tail(svc)
    print(f"Done. New incidents: {new_count}, pending diagnosis: {pending}")
