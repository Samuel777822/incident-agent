"""Proof of the 30-second monitor heartbeat, using real HTTP requests against the real portal WSGI app.

What it does (nothing is mocked except the data: a throw-away SQLite database and a fake project):
  1. starts the portal (web_app.application) on 127.0.0.1 behind a tiny middleware that stamps the arrival time of every /heartbeat
  2. starts a real monitored Python process that imports agent_monitor_client (the file the installer ships)
  3. records backend receipt times for RUN_SECONDS, then computes the interval between consecutive receipts
  4. every few seconds it also reads the database (projects.last_heartbeat_at, monitor_heartbeats.beats) and the rendered
     project page, so the dashboard status is observed, not assumed
  5. kills the agent -> measures how long until the portal reports "Monitor offline"
  6. restarts the agent -> measures how long until the portal reports "Live" again

Run:  python scripts/prove_heartbeat.py [run_seconds]      Output: verification/heartbeat_proof.json + .md
No secrets are printed or stored: the ingest key is generated for this run only.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RUN_SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 200
tmp = tempfile.mkdtemp(prefix="hb-proof-")
os.environ.update({"PORTAL_DB_PATH": str(Path(tmp) / "portal.sqlite3"), "APP_ENV": "test",
                   "SESSION_SECRET": "proof-only-session-secret-at-least-32-chars", "ADMIN_EMAILS": "admin1@example.com",
                   "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
os.environ.pop("DATABASE_URL", None)
for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(name, None)

import hashlib  # noqa: E402

import portal_db  # noqa: E402
import web_app  # noqa: E402

portal_db.init_db()
user_id = portal_db.create_user("proof@example.com", "hash")
portal_db.admin_grant_access(user_id, 1, "trial", "admin1@example.com")
ingest_key = "proof-key-" + hashlib.sha256(os.urandom(16)).hexdigest()[:30]
project_id = portal_db.create_project(user_id, name="Heartbeat proof", repo_owner="demo", repo_name="shop", branch="main", mode="pr",
                                      token_ciphertext="cipher", ingest_key_hash=hashlib.sha256(ingest_key.encode()).hexdigest())
# A monitor that was "installed" a while ago, so the never-checked-in rule is also exercised honestly.
conn = portal_db.get_connection()
try:
    portal_db._execute(conn, "UPDATE projects SET monitor_installed_at=? WHERE id=?",
                       ((datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds"), project_id))
    conn.commit()
finally:
    conn.close()
csrf = "csrf-proof"
session_id = portal_db.create_session(user_id, csrf, (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(timespec="seconds"))
cookie = f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}"

receipts: list[dict] = []
lock = threading.Lock()


def stamped(app):
    def wrapper(environ, start_response):
        if environ.get("PATH_INFO") == "/heartbeat" and environ.get("REQUEST_METHOD") == "POST":
            t = time.time()
            captured = {}

            def sr(status, headers, exc_info=None):
                captured["status"] = status
                return start_response(status, headers, exc_info)
            result = app(environ, sr)
            with lock:
                receipts.append({"t": t, "utc": datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds"),
                                 "status": captured.get("status", "?")})
            return result
        return app(environ, start_response)
    return wrapper


server = make_server("127.0.0.1", 0, stamped(web_app.application), server_class=web_app.ThreadingWSGIServer)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_port}"

AGENT_CODE = "import time\nimport agent_monitor_client\nwhile True:\n    time.sleep(1)\n"


def start_agent() -> subprocess.Popen:
    env = dict(os.environ)
    env.update({"INCIDENT_AGENT_INGEST_URL": f"{base}/ingest", "INCIDENT_AGENT_INGEST_KEY": ingest_key})
    env.pop("AGENT_DAEMON_HEARTBEAT_SECONDS", None)          # prove the DEFAULT interval, not an override
    return subprocess.Popen([sys.executable, "-c", AGENT_CODE], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def page_headline() -> str:
    req = urllib.request.Request(f"{base}/projects/{project_id}", headers={"Cookie": cookie})
    try:
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "replace")
    except Exception as exc:                                   # noqa: BLE001
        return f"page error: {exc}"
    for label in ("Monitor offline", "Never checked in", "Waiting for the first check-in", "Live"):
        if label in html:
            m = re.search(r"Last check-in at ([^<(]+)", html)
            return label + (f" | Last check-in at {m.group(1).strip()}" if m else "")
    return "no status text found"


def db_view() -> dict:
    project = portal_db.get_project(project_id, user_id)
    beats = portal_db.list_monitor_heartbeats(project_id)
    state = portal_db.monitor_state(project, beats)
    return {"last_heartbeat_at": project["last_heartbeat_at"], "beats": sum(int(b["beats"]) for b in beats),
            "state": state["state"], "headline": state["headline"]}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


timeline: list[dict] = []


def sample(phase: str) -> None:
    timeline.append({"at": now_iso(), "phase": phase, "db": db_view(), "dashboard": page_headline()})


print(f"[proof] portal on {base}  offline threshold = {portal_db.MONITOR_OFFLINE_SECONDS}s  run = {RUN_SECONDS}s", flush=True)
agent = start_agent()
t_start = time.time()
sample("start")
while time.time() - t_start < RUN_SECONDS:
    time.sleep(10)
    sample("agent running")
with lock:
    online_receipts = list(receipts)

# ---- stop the agent, wait for the portal to say offline -----------------------------------------------------------------------
agent.terminate()
agent.wait(timeout=10)
t_stop = time.time()
last_beat_before_stop = online_receipts[-1]["t"] if online_receipts else t_stop
offline_after = None
print("[proof] agent stopped; waiting for the portal to report offline ...", flush=True)
while time.time() - t_stop < portal_db.MONITOR_OFFLINE_SECONDS + 90:
    time.sleep(5)
    sample("agent stopped")
    if timeline[-1]["db"]["state"] == "offline" and offline_after is None:
        offline_after = time.time() - last_beat_before_stop
        break
extra_after_offline = [e for e in timeline if e["phase"] == "agent stopped"][-1]

# ---- restart -> recovery ----------------------------------------------------------------------------------------------------
agent = start_agent()
t_restart = time.time()
recovered_after = None
print("[proof] agent restarted; waiting for the portal to report live ...", flush=True)
while time.time() - t_restart < 90:
    time.sleep(2)
    sample("agent restarted")
    if timeline[-1]["db"]["state"] == "online":
        recovered_after = time.time() - t_restart
        break
agent.terminate()
server.shutdown()

# ---- numbers ----------------------------------------------------------------------------------------------------------------------
times = [r["t"] for r in online_receipts]
intervals = [round(b - a, 2) for a, b in zip(times, times[1:])]
summary = {
    "heartbeats_received_while_running": len(times),
    "run_seconds": RUN_SECONDS,
    "intervals_seconds": intervals,
    "interval_min": min(intervals) if intervals else None,
    "interval_max": max(intervals) if intervals else None,
    "interval_mean": round(statistics.mean(intervals), 2) if intervals else None,
    "interval_stdev": round(statistics.pstdev(intervals), 3) if len(intervals) > 1 else None,
    "all_http_statuses": sorted({r["status"] for r in online_receipts}),
    "offline_detected_seconds_after_last_heartbeat": round(offline_after, 1) if offline_after else None,
    "offline_threshold_seconds": portal_db.MONITOR_OFFLINE_SECONDS,
    "recovered_seconds_after_restart": round(recovered_after, 1) if recovered_after else None,
}
out_dir = ROOT / "verification"
out_dir.mkdir(exist_ok=True)
(out_dir / "heartbeat_proof.json").write_text(json.dumps({"summary": summary, "receipts": online_receipts, "timeline": timeline}, indent=2), encoding="utf-8")
lines = ["# Heartbeat proof (generated by scripts/prove_heartbeat.py)", "", f"Run on {now_iso()} UTC, default interval (no override).", "",
         "| # | Backend receipt (UTC) | HTTP status | Interval since previous (s) |", "|---|---|---|---|"]
for i, r in enumerate(online_receipts):
    lines.append(f"| {i + 1} | {r['utc']} | {r['status']} | {intervals[i - 1] if i else '-'} |")
lines += ["", "```json", json.dumps(summary, indent=2), "```", "", "## Dashboard / database samples", "",
          "| Time (UTC) | Phase | DB state | beats | Dashboard text |", "|---|---|---|---|---|"]
for e in timeline:
    lines.append(f"| {e['at']} | {e['phase']} | {e['db']['state']} | {e['db']['beats']} | {e['dashboard']} |")
(out_dir / "heartbeat_proof.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(json.dumps(summary, indent=2), flush=True)
