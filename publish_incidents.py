"""Sends a snapshot of incidents.db to the hosted coffee-shop dashboard."""
import json
import os
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # optional: only used to read a local .env file
    def load_dotenv(*_args, **_kwargs):
        return False

from config import get_repo_config
from db import get_connection

load_dotenv(Path(__file__).parent / ".env")


def publish_incidents(service):
    cfg = get_repo_config(service)
    url = os.getenv("APP_URL") or cfg.get("app_url")
    key = os.getenv("INGEST_KEY")
    if not url or not key or "YOUR-APP-NAME" in url:
        return
    conn = get_connection()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM incidents ORDER BY id DESC LIMIT 50")]
        for r in rows:
            r["attempts"] = conn.execute(
                "SELECT COUNT(*) FROM fixes WHERE incident_id = ?", (r["id"],)
            ).fetchone()[0]
    finally:
        conn.close()
    req = urllib.request.Request(
        url.rstrip("/") + "/api/incidents/sync",
        data=json.dumps({"incidents": rows}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "X-Ingest-Key": key},
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as err:
        print(f"[publish] dashboard not reachable yet: {err}")