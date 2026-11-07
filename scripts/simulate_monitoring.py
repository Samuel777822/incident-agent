"""Local end-to-end simulation of the monitoring loop. Needs no internet, no GitHub and no AI keys.

    python scripts/simulate_monitoring.py              # fast: monitors check in every 2 s (about 15 s in total)
    python scripts/simulate_monitoring.py --real       # production timing: every 30 s (about 70 s in total)

What it does:
  1. starts the Agent Daemon web app on 127.0.0.1 with a throw-away SQLite database,
  2. starts a fake AI provider that answers like a retired model ("The model `gpt-3.5-turbo` has been deprecated", 404),
  3. runs the REAL Python monitor and (if Node.js is installed) the REAL Node.js monitor against it,
  4. prints every check-in with the time between them, and the error reports that arrived,
  5. runs the worker once on the reported error with an offline copy of a small chatbot repo and a fake GitHub,
     and prints the fix pull request it would open.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, make_server

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Quiet(WSGIRequestHandler):
    def log_message(self, *args):
        pass


class RetiredModel(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = json.dumps({"error": {"message": "The model `gpt-3.5-turbo` has been deprecated", "code": "model_not_found"}}).encode()
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="use the production 30-second heartbeat")
    args = parser.parse_args()
    interval = 30 if args.real else 2
    run_for = 65 if args.real else 7

    tmp = Path(tempfile.mkdtemp(prefix="ad-sim-"))
    os.environ.update({"PORTAL_DB_PATH": str(tmp / "portal.db"), "APP_ENV": "development", "SESSION_SECRET": "s" * 40,
                       "MODEL_CATALOG_OFFLINE": "1", "WORKER_MIN_AGE_SECONDS": "0", "FIXENGINE_SANDBOX_MODE": "remote",
                       "NOTIFY_SYNC": "1"})
    os.environ.pop("FIXENGINE_SANDBOX_URL", None)
    import portal_db
    import web_app
    web_app.HEARTBEAT_WRITE_MIN_SECONDS = 0
    portal_db.init_db()
    user_id = portal_db.create_user("sim@example.com", "x")
    portal_db.admin_grant_access(user_id, 1, "trial", "simulator")
    key = "adi_simulation-" + "k" * 30
    project_id = portal_db.create_project(user_id, name="Chatbot", repo_owner="demo", repo_name="chatbot", branch="main", mode="pr",
                                          token_ciphertext="x", ingest_key_hash=hashlib.sha256(key.encode()).hexdigest(),
                                          ai_consent_at=portal_db._now(), gate_state="active")
    beats: list[tuple[float, str]] = []
    original = portal_db.record_heartbeat

    def spy(pid, monitor, *rest, **kw):
        beats.append((time.monotonic(), monitor))
        return original(pid, monitor, *rest, **kw)

    portal_db.record_heartbeat = spy
    portal = make_server("127.0.0.1", 0, web_app.application, server_class=web_app.ThreadingWSGIServer, handler_class=Quiet)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), RetiredModel)
    for server in (portal, provider):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    ingest = f"http://127.0.0.1:{portal.server_port}/ingest"
    ai = f"http://127.0.0.1:{provider.server_port}/v1/chat/completions"
    env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
    env.update({"NO_PROXY": "127.0.0.1", "INCIDENT_AGENT_INGEST_URL": ingest, "INCIDENT_AGENT_INGEST_KEY": key,
                "AGENT_DAEMON_HEARTBEAT_SECONDS": str(interval)})
    print(f"Portal on {ingest[:-7]}, fake retired-model provider on {ai}, heartbeat every {interval}s, running {run_for}s\n")
    start = time.monotonic()
    procs = [subprocess.Popen([sys.executable, "-c",
                               "import time, urllib.request, agent_monitor_client\n"
                               f"try:\n    urllib.request.urlopen(urllib.request.Request('{ai}', data=b'{{}}', method='POST'), timeout=5)\n"
                               "except Exception:\n    pass\n"
                               f"time.sleep({run_for})\n"], cwd=ROOT, env=env, stderr=subprocess.PIPE, text=True)]
    node = shutil.which("node")
    if node:
        work = tmp / "node-app"
        work.mkdir()
        shutil.copy(ROOT / "monitors" / "node_monitor.cjs", work / "incident-agent-monitor.cjs")
        (work / "server.js").write_text(f"fetch('{ai}', {{method: 'POST', body: '{{}}'}}).then(r => console.error('chatbot reply status', r.status));\n"
                                        f"setTimeout(() => {{}}, {run_for * 1000});\n")
        procs.append(subprocess.Popen([node, "-r", "./incident-agent-monitor.cjs", "server.js"], cwd=work, env=env,
                                      stderr=subprocess.PIPE, text=True))
    for proc in procs:
        try:
            proc.wait(timeout=run_for + 30)
        except subprocess.TimeoutExpired:
            proc.kill()
    print("Check-ins received:")
    last: dict[str, float] = {}
    for stamp, monitor in beats:
        gap = f"+{stamp - last[monitor]:.1f}s" if monitor in last else "first"
        last[monitor] = stamp
        print(f"  t={stamp - start:5.1f}s  {monitor:7s}  {gap}")
    conn = portal_db.get_connection()
    events = [dict(r) for r in portal_db._execute(conn, "SELECT level,message FROM log_events WHERE project_id=?", (project_id,)).fetchall()]
    conn.close()
    print("\nError reports received:")
    for e in events:
        print(f"  {e['level']}: {e['message'][:150]}")

    # the fix pipeline, offline: a small chatbot repo and a fake GitHub
    import portal_worker
    from fixengine import git_ops
    repo = tmp / "repo"
    repo.mkdir()
    (repo / "index.html").write_text("<html><head></head><body><script src='chat.js'></script></body></html>")
    (repo / "chat.js").write_text("fetch('https://api.openai.com/v1/chat/completions', {method: 'POST',\n"
                                  "  body: JSON.stringify({model: 'gpt-3.5-turbo', messages: []})});\n")
    git_ops.repo_snapshot = lambda project, cfg=None: contextlib.nullcontext(repo)
    opened = []
    git_ops.open_pr = lambda project, **kw: opened.append(kw) or {"url": "https://github.com/demo/chatbot/pull/1", "number": 1,
                                                                  "branch": "agent-daemon/fix-model", "head_sha": "", "path": "chat.js",
                                                                  "diff": kw["diff"]}
    handled = 0
    while portal_worker.process_one() and handled < 10:
        handled += 1
    print("\nFix pipeline:")
    for incident in portal_db.list_incidents(project_id):
        print(f"  incident {incident['signature'][:60]} -> {incident['status']} {incident.get('pr_url') or ''}")
    for pr in opened:
        print(f"  pull request: {pr['title']}\n{pr['diff']}")
    portal.shutdown()
    provider.shutdown()
    ok = bool(beats) and bool(events) and bool(opened)
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
