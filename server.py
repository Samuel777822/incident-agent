"""HTTP health/status API for the single-repository Render daemon."""

from __future__ import annotations

import hmac
import json
import os
import signal
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from agent_daemon import start_daemon
from config import REPOS_FILE
from db import get_connection, init_db


PROJECT = os.getenv("AGENT_PROJECT", "coffee-shop").strip()
POLL_SECONDS = max(5, int(os.getenv("AGENT_POLL_SECONDS", "10")))
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
MAX_RESPONSE_BYTES = 1_000_000
worker_thread: threading.Thread | None = None
http_server: ThreadingHTTPServer | None = None


def _projects() -> list[str]:
    data = json.loads(REPOS_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("repos.json must contain a JSON object")
    return sorted(data)


def _missing_config() -> list[str]:
    missing = [name for name in ("GROQ_API_KEY", "GITHUB_TOKEN", "INGEST_KEY")
               if not os.getenv(name, "").strip()]
    if not ADMIN_KEY:
        missing.append("ADMIN_KEY")
    elif len(ADMIN_KEY) < 32:
        missing.append("ADMIN_KEY (at least 32 characters)")
    return missing


def _validate_config() -> list[str]:
    projects = _projects()
    if PROJECT not in projects:
        raise RuntimeError(f"AGENT_PROJECT '{PROJECT}' is not configured in repos.json")
    return projects


def _worker_main() -> None:
    try:
        start_daemon(PROJECT, POLL_SECONDS)
    except BaseException as exc:
        # Keep the HTTP process available so health/status can report the worker failure.
        print(f"[daemon] Worker stopped: {type(exc).__name__}", flush=True)


def _json_bytes(value: object) -> bytes:
    body = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Response is too large")
    return body


def _incident_snapshot() -> list[dict]:
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, signature, status, category, confidence, occurrences, "
            "first_seen, last_seen, root_cause, report, pr_url, pr_number, "
            "ci_status, created_at, resolved_at FROM incidents "
            "ORDER BY id DESC LIMIT 100"
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["fix_count"] = conn.execute(
                "SELECT COUNT(*) FROM fixes WHERE incident_id = ?", (item["id"],)
            ).fetchone()[0]
            result.append(item)
        return result
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentDaemon"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:
        # Do not log request headers, which can contain the admin credential.
        print("[http] " + (fmt % args), flush=True)

    def _send(self, status: int, value: object) -> None:
        try:
            body = _json_bytes(value)
        except (TypeError, ValueError):
            status, body = 500, b'{"error":"response unavailable"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-Admin-Key", "")
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        return bool(ADMIN_KEY and supplied and hmac.compare_digest(supplied, ADMIN_KEY))

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/health":
            # Render can serve the setup screen before secrets exist; worker state
            # is reported separately at /api/status.
            worker_failed = worker_thread is not None and not worker_thread.is_alive()
            self._send(503 if worker_failed else 200,
                       {"status": "degraded" if worker_failed else "ok"})
            return
        if path == "/api/status":
            try:
                projects = _projects()
            except Exception:
                projects = []
            self._send(200, {
                "worker_alive": bool(worker_thread and worker_thread.is_alive()),
                "projects": projects,
                "project": PROJECT,
                "missing_configuration": _missing_config(),
            })
            return
        if path == "/api/incidents":
            if not self._authorized():
                self._send(401, {"error": "unauthorized"})
                return
            try:
                self._send(200, {"incidents": _incident_snapshot()})
            except Exception as exc:
                print(f"[api] Incident lookup failed: {type(exc).__name__}", flush=True)
                self._send(503, {"error": "incident data unavailable"})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        self._send(405, {"error": "method not allowed"})

    def do_HEAD(self) -> None:
        self._head_only = True
        self.do_GET()


def main() -> None:
    global worker_thread, http_server
    projects = _validate_config()
    init_db()
    try:
        git_version = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=5, check=True
        ).stdout.strip()
    except Exception:
        git_version = "git unavailable"
    print("AGENT DAEMON starting", flush=True)
    print(f"git: {git_version}", flush=True)
    print(f"Projects loaded from repos.json: {projects}", flush=True)

    missing = _missing_config()
    if missing:
        print("Worker paused until Render secrets are set: " + ", ".join(missing), flush=True)
    else:
        worker_thread = threading.Thread(target=_worker_main, name="incident-agent-worker", daemon=True)
        worker_thread.start()

    port = int(os.getenv("PORT", "10000"))
    http_server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    http_server.daemon_threads = True

    def stop(_signum, _frame) -> None:
        if http_server:
            threading.Thread(target=http_server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"Agent Daemon API listening on port {port}", flush=True)
    try:
        http_server.serve_forever(poll_interval=0.5)
    finally:
        http_server.server_close()


if __name__ == "__main__":
    main()
