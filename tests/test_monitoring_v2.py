"""Monitoring v2: the 'never checked in' incident, multi-language auto-install, the public-repo gate, the initial scan and the
retired-AI-model fix pipeline. Everything runs offline: GitHub, AI providers and the sandbox are replaced by local stand-ins;
the monitors themselves are the real files, run in real Python / Node.js processes and a real headless browser."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from wsgiref.simple_server import make_server

import pytest

import monitoring_installer as mi
import portal_db
import push_watch
import web_app
from test_web_app import _request, web_env  # noqa: F401  (web_env is a fixture)

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


# ------------------------------------------------------------------------------------------------ helpers
def make_session(email):
    user_id = portal_db.create_user(email, "hash")
    csrf = "csrf-" + user_id[:8]
    session_id = portal_db.create_session(user_id, csrf, (web_app._now() + timedelta(days=1)).isoformat(timespec="seconds"))
    return user_id, csrf, f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}"


def new_project(user_id, key="k" * 40, **extra):
    extra.setdefault("ai_consent_at", portal_db._now())
    return portal_db.create_project(user_id, name="Chatbot", repo_owner="demo", repo_name="chatbot", branch="main", mode="pr",
                                    token_ciphertext="cipher", ingest_key_hash=hashlib.sha256(key.encode()).hexdigest(), **extra)


@pytest.fixture
def fernet_env(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())


@contextlib.contextmanager
def portal_server():
    server = make_server("127.0.0.1", 0, web_app.application, server_class=web_app.ThreadingWSGIServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


class _RetiredModelProvider(BaseHTTPRequestHandler):
    """A stand-in AI provider that answers like OpenAI does for a retired model."""
    body = {"error": {"message": "The model `gpt-3.5-turbo` has been deprecated", "type": "invalid_request_error",
                      "code": "model_not_found"}}

    def _send(self, code, payload=b""):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self._send(204)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._send(404, json.dumps(self.body).encode())

    def do_GET(self):
        if self.path.startswith("/site"):
            page = self.server.page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html" if self.path.endswith("/") else "application/javascript")
            self.end_headers()
            self.wfile.write(page if self.path.endswith("/") else self.server.script.encode())
            return
        self._send(404, b"{}")

    def log_message(self, *args):
        pass


@contextlib.contextmanager
def fake_provider(page="", script=""):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RetiredModelProvider)
    server.page, server.script = page, script
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()


def clean_env(**extra):
    env = dict(os.environ)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(name, None)
    env.update({"NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
    env.update(extra)
    return env


def active_user(email="dev@example.com"):
    user_id, csrf, cookie = make_session(email)
    portal_db.admin_grant_access(user_id, 30, "paid", "admin1@example.com")
    return user_id, csrf, cookie


# ================================================================================================ Phase 1: the root cause
def test_root_cause_the_old_installer_never_wired_a_javascript_app():
    """The incident: an HTML + JS chatbot. The old install only knew Python entry files, so nothing ever started the
    monitor. Now the page itself loads the browser monitor as its first script."""
    files = {"index.html": "<!doctype html><html><head><title>Chat</title></head><body><script src='chat.js'></script></body></html>",
             "chat.js": "fetch('https://api.openai.com/v1/chat/completions',{method:'POST',body:JSON.stringify({model:'gpt-3.5-turbo'})})"}
    targets = mi.detect_targets(list(files), files.get)
    assert [t["kind"] for t in targets] == ["browser"]
    planned, results = mi.plan_install(targets, files.get, ingest_url="https://portal/ingest", ingest_key="k" * 40, project_id="p1")
    head = planned["index.html"].split("<title>")[0]
    assert '<script src="incident-agent-monitor.js"></script>' in head        # first script on the page, before chat.js
    assert results[0]["wired"] is True and "incident-agent-monitor.js" in planned


def test_browser_monitor_can_reach_the_backend_cors_preflight_and_text_plain(web_env):
    """Root cause #2: /ingest and /heartbeat had no CORS, so a browser could never check in. Both now answer preflights and
    accept a text/plain JSON body carrying the key (a 'simple' request that needs no preflight)."""
    user_id, *_ = active_user()
    key = "b" * 40
    project_id = new_project(user_id, key)
    status, headers, _ = _request("/heartbeat", method="OPTIONS")
    assert status == "204 No Content" and ("Access-Control-Allow-Origin", "*") in headers
    body = json.dumps({"ingest_key": key, "monitor": "browser", "component": "browser:.", "status": "ok", "project_id": project_id}).encode()
    status, headers, text = _request("/heartbeat", method="POST", raw_body=body, headers={"CONTENT_TYPE": "text/plain;charset=UTF-8"})
    assert status == "200 OK" and ("Access-Control-Allow-Origin", "*") in headers and json.loads(text)["interval"] == 30
    beats = portal_db.list_monitor_heartbeats(project_id)
    assert beats and beats[0]["monitor"] == "browser"


def test_a_key_never_speaks_for_another_project(web_env):
    user_id, *_ = active_user()
    project_id = new_project(user_id, "c" * 40)
    other = new_project(user_id, "d" * 40)
    body = json.dumps({"ingest_key": "c" * 40, "monitor": "node", "project_id": other}).encode()
    assert _request("/heartbeat", method="POST", raw_body=body)[0] == "401 Unauthorized"
    assert portal_db.list_monitor_heartbeats(project_id) == []


def test_status_is_never_silent(web_env, monkeypatch):
    user_id, *_ = active_user()
    project_id = new_project(user_id)
    project = portal_db.get_project(project_id, user_id)
    assert portal_db.monitor_state(project)["state"] == "not_installed"
    portal_db.record_monitor_install(project_id, [{"kind": "node", "wired": True, "label": "Express server"}], installed=True)
    project = portal_db.get_project(project_id, user_id)
    assert portal_db.monitor_state(project)["state"] == "waiting_first"
    monkeypatch.setattr(portal_db, "MONITOR_FIRST_CHECKIN_GRACE_SECONDS", -1)
    never = portal_db.monitor_state(project)
    assert never["state"] == "never_checked_in" and never["headline"] == "Never checked in" and never["tone"] == "red"
    portal_db.record_heartbeat(project_id, "node", "node:.")
    online = portal_db.monitor_state(portal_db.get_project(project_id, user_id))
    assert online["state"] == "online" and online["last_checkin"]
    monkeypatch.setattr(portal_db, "MONITOR_OFFLINE_SECONDS", -1)
    assert portal_db.monitor_state(portal_db.get_project(project_id, user_id))["state"] == "offline"
    # the project page says it in words: last check-in time, or never
    _, _, cookie = make_session_for(user_id)
    _, _, page = _request(f"/projects/{project_id}", cookie=cookie)
    assert "Last check-in at" in page and "Monitor offline" in page and "checks in every 30 seconds" in page


def make_session_for(user_id):
    csrf = "csrf-" + user_id[:8]
    session_id = portal_db.create_session(user_id, csrf, (web_app._now() + timedelta(days=1)).isoformat(timespec="seconds"))
    return user_id, csrf, f"{web_app.SESSION_COOKIE}={web_app._signed_cookie(session_id)}"


def test_browser_only_projects_are_idle_not_offline_when_nobody_visits(web_env, monkeypatch):
    user_id, *_ = active_user()
    project_id = new_project(user_id)
    portal_db.record_monitor_install(project_id, [{"kind": "browser", "wired": True}], installed=True)
    portal_db.record_heartbeat(project_id, "browser", "browser:.")
    monkeypatch.setattr(portal_db, "MONITOR_OFFLINE_SECONDS", -1)
    assert portal_db.monitor_state(portal_db.get_project(project_id, user_id))["state"] == "idle_browser"
    assert portal_db.projects_needing_monitor_alert() == []                      # no false alarm e-mails for static sites


def test_worker_emails_the_owner_once_when_a_server_monitor_goes_quiet(web_env, monkeypatch):
    import portal_worker
    user_id, *_ = active_user("owner@example.com")
    project_id = new_project(user_id, gate_state="active")
    portal_db.record_monitor_install(project_id, [{"kind": "python", "wired": True}], installed=True)
    monkeypatch.setattr(portal_db, "MONITOR_FIRST_CHECKIN_GRACE_SECONDS", -1)
    assert portal_worker.monitor_sweep() == 1
    assert portal_worker.monitor_sweep() == 0                                       # once, not every minute
    assert any(n["kind"] == "monitor_offline" for n in portal_db.recent_notifications(10))


# ================================================================================================ Phase 2: install for every language
CASES = {
    "python-flask": ({"requirements.txt": "flask", "app.py": "from flask import Flask\napp = Flask(__name__)\n"}, ["python"]),
    "fastapi-package": ({"requirements.txt": "fastapi", "app/__init__.py": "", "app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n"},
                        ["python"]),
    "django": ({"manage.py": "", "requirements.txt": "django", "site1/__init__.py": "",
                "site1/wsgi.py": "from django.core.wsgi import get_wsgi_application\napplication = get_wsgi_application()\n"}, ["python"]),
    "express": ({"package.json": json.dumps({"scripts": {"start": "node server.js"}, "dependencies": {"express": "4"}}),
                 "server.js": "const express = require('express')\n"}, ["node"]),
    "node-esm-main": ({"package.json": json.dumps({"type": "module", "main": "index.js", "dependencies": {"fastify": "4"}}),
                       "index.js": "import Fastify from 'fastify'\n"}, ["node"]),
    "typescript-node": ({"package.json": json.dumps({"scripts": {"start": "node dist/index.js", "build": "tsc"}, "dependencies": {"express": "4"}}),
                         "tsconfig.json": "{}", "src/index.ts": "import express from 'express'\n"}, ["node"]),
    "plain-html": ({"index.html": "<html><head></head><body></body></html>", "app.js": ""}, ["browser"]),
    "react-vite": ({"package.json": json.dumps({"dependencies": {"react": "18", "vite": "5"}}),
                    "index.html": "<html><head><title>x</title></head></html>", "src/main.jsx": ""}, ["browser"]),
    "react-cra": ({"package.json": json.dumps({"dependencies": {"react": "18", "react-scripts": "5"}}),
                   "public/index.html": "<html><head></head></html>", "src/index.js": ""}, ["browser"]),
    "nextjs": ({"package.json": json.dumps({"dependencies": {"next": "^15.2.0", "react": "19"}}), "app/page.tsx": ""}, ["node", "browser"]),
    "mixed": ({"backend/requirements.txt": "flask", "backend/app.py": "from flask import Flask\napp = Flask(__name__)\n",
               "frontend/package.json": json.dumps({"dependencies": {"react": "18", "vite": "5"}}),
               "frontend/index.html": "<html><head></head></html>",
               "api/package.json": json.dumps({"scripts": {"start": "node server.js"}, "dependencies": {"express": "4"}}),
               "api/server.js": "require('express')\n"}, ["browser", "node", "python"]),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_auto_install_picks_the_right_monitor_for_each_part(name):
    files, kinds = CASES[name]
    targets = mi.detect_targets(list(files), files.get)
    assert sorted(t["kind"] for t in targets) == sorted(kinds), targets
    planned, results = mi.plan_install(targets, files.get, ingest_url="https://portal/ingest", ingest_key="k" * 40, project_id="p1")
    assert all(r["wired"] for r in results), results
    if "python" in kinds:
        entry = [r["file"] for r in results if r["kind"] == "python"][0]
        assert "import incident_agent_monitor" in planned[entry]
        assert any(p.endswith(mi.PY_FILE) for p in planned) and any(p.endswith(mi.PY_CONFIG) for p in planned)
    if "node" in kinds and name != "nextjs":
        assert any(p.endswith(mi.NODE_FILE) for p in planned) and any(p.endswith(mi.NODE_CONFIG) for p in planned)
        wired = [r for r in results if r["kind"] == "node"][0]["file"]
        assert mi.MARKER in planned[wired]
    if name == "nextjs":
        assert "await import('./incident-agent-monitor.cjs')" in planned["instrumentation.js"]
        assert "incident-agent-monitor.browser.js" in planned["instrumentation-client.js"]
    if "browser" in kinds and name != "nextjs":
        html_files = [p for p in planned if p.endswith(".html")]
        assert html_files and all(mi.MARKER in planned[p] for p in html_files)


def test_mixed_repo_gets_one_monitor_per_part_in_the_right_place():
    files, _ = CASES["mixed"]
    planned, _results = mi.plan_install(mi.detect_targets(list(files), files.get), files.get, ingest_url="https://portal/ingest",
                                        ingest_key="k" * 40, project_id="p1")
    assert "backend/incident_agent_monitor.py" in planned and "frontend/public/incident-agent-monitor.js" in planned
    assert "api/incident-agent-monitor.cjs" in planned
    assert json.loads(planned["api/package.json"])["scripts"]["start"] == "node -r ./incident-agent-monitor.cjs server.js"
    assert '%BASE_URL%incident-agent-monitor.js' in planned["frontend/index.html"]
    cfg = json.loads(planned["backend/incident_agent_config.json"])
    assert cfg["project_id"] == "p1" and cfg["heartbeat_url"] == "https://portal/heartbeat" and cfg["component"] == "python:backend"


def test_nested_python_entry_uses_the_guarded_import_that_never_breaks_the_app(tmp_path):
    files, _ = CASES["fastapi-package"]
    planned, _ = mi.plan_install(mi.detect_targets(list(files), files.get), files.get, ingest_url="u/ingest", ingest_key="k" * 40,
                                 project_id="p")
    assert "except ImportError" in planned["app/main.py"]
    # import the patched package from the repo root, the way `uvicorn app.main:app` does: the monitor loads, nothing breaks
    for rel, text in {**files, **planned}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text.replace("from fastapi import FastAPI\napp = FastAPI()\n", "app = 'ok'\n"))
    out = subprocess.run([sys.executable, "-c", "import app.main as m; import sys; print(m.app)"], cwd=tmp_path, capture_output=True,
                         text=True, timeout=30, env=clean_env(AGENT_DAEMON_DISABLE="1"))
    assert out.returncode == 0 and "ok" in out.stdout, out.stderr


def test_install_never_writes_our_own_secrets_into_a_repository(monkeypatch):
    secrets = {"SESSION_SECRET": "S3SSION-secret-value-xyz", "TOKEN_ENCRYPTION_KEY": "TOKEN-enc-key-value-xyz",
               "ANTHROPIC_API_KEY": "sk-ant-OUR-KEY", "GROQ_API_KEY": "gsk_OUR_KEY", "FIXENGINE_SANDBOX_SECRET": "SANDBOX-secret-xyz"}
    for k, v in secrets.items():
        monkeypatch.setenv(k, v)
    for name, (files, _kinds) in CASES.items():
        planned, _ = mi.plan_install(mi.detect_targets(list(files), files.get), files.get, ingest_url="https://portal/ingest",
                                     ingest_key="adi_project-scoped-key-1234567890", project_id="p1")
        blob = "\n".join(planned.values())
        assert not any(v in blob for v in secrets.values()), name
        assert "adi_project-scoped-key-1234567890" in blob                       # only the project-scoped key


def test_every_monitor_checks_in_every_30_seconds_by_default(monkeypatch):
    monkeypatch.delenv("AGENT_DAEMON_HEARTBEAT_SECONDS", raising=False)
    import importlib.util
    spec = importlib.util.spec_from_file_location("m30", ROOT / "agent_monitor_client.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setenv("AGENT_DAEMON_DISABLE", "1")
    spec.loader.exec_module(module)
    assert module.HEARTBEAT_SECONDS == 30
    assert "process.env.AGENT_DAEMON_HEARTBEAT_SECONDS || '30'" in (ROOT / "monitors/node_monitor.cjs").read_text()
    assert "Number(CONFIG.heartbeatSeconds) || 30" in (ROOT / "monitors/browser_monitor.js").read_text()


def test_python_monitor_heartbeats_and_reports_a_retired_model_with_the_full_message(web_env):
    user_id, *_ = active_user()
    key = "py-live-key-" + "x" * 30
    project_id = new_project(user_id, key)
    with portal_server() as portal, fake_provider() as provider:
        code = ("import time, json, urllib.request\nimport agent_monitor_client\n"
                f"req = urllib.request.Request('{provider}/v1/chat/completions', data=b'{{}}', method='POST')\n"
                "try:\n    urllib.request.urlopen(req, timeout=5)\nexcept Exception:\n    pass\n"
                "time.sleep(3.6)\n")
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, timeout=60, capture_output=True, text=True,
                                env=clean_env(INCIDENT_AGENT_INGEST_URL=f"{portal}/ingest", INCIDENT_AGENT_INGEST_KEY=key,
                                              AGENT_DAEMON_HEARTBEAT_SECONDS="1"))
    beats = portal_db.list_monitor_heartbeats(project_id)
    assert beats and beats[0]["monitor"] == "python", result.stderr
    assert "monitor connected" in result.stderr                                  # the first check-in is visible in the app's log
    events = _events(project_id)
    model_error = [e for e in events if "model_not_found" in e["message"] or "deprecated" in e["message"]]
    assert model_error and "gpt-3.5-turbo" in model_error[0]["message"] and "HTTP 404" in model_error[0]["message"], events


def _events(project_id):
    conn = portal_db.get_connection()
    try:
        return [dict(r) for r in portal_db._execute(conn, "SELECT * FROM log_events WHERE project_id=?", (project_id,)).fetchall()]
    finally:
        conn.close()


def test_python_monitor_heartbeat_interval_is_respected(web_env, monkeypatch):
    """Heartbeats are periodic: with the interval set to 1 s, a 4 s run produces a check-in about every second
    (30 s in production; the constant is checked in test_every_monitor_checks_in_every_30_seconds_by_default)."""
    user_id, *_ = active_user()
    key = "py-beat-key-" + "y" * 30
    new_project(user_id, key)
    monkeypatch.setattr(web_app, "HEARTBEAT_WRITE_MIN_SECONDS", 0)
    stamps = []
    original = portal_db.record_heartbeat
    monkeypatch.setattr(portal_db, "record_heartbeat", lambda *a, **k: (stamps.append(time.monotonic()), original(*a, **k)))
    with portal_server() as portal:
        subprocess.run([sys.executable, "-c", "import time, agent_monitor_client\ntime.sleep(4.2)\n"], cwd=ROOT, timeout=60,
                       capture_output=True, env=clean_env(INCIDENT_AGENT_INGEST_URL=f"{portal}/ingest", INCIDENT_AGENT_INGEST_KEY=key,
                                                          AGENT_DAEMON_HEARTBEAT_SECONDS="1"))
    assert len(stamps) >= 4, stamps
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(0.7 < g < 1.8 for g in gaps), gaps


@pytest.mark.skipif(not NODE, reason="Node.js is not installed")
def test_node_monitor_heartbeats_and_reports_fetch_console_and_crashes(web_env, tmp_path):
    user_id, *_ = active_user()
    key = "node-live-key-" + "z" * 30
    project_id = new_project(user_id, key)
    shutil.copy(ROOT / "monitors/node_monitor.cjs", tmp_path / "incident-agent-monitor.cjs")
    with portal_server() as portal, fake_provider() as provider:
        (tmp_path / "incident-agent-config.json").write_text(json.dumps({"ingest_url": f"{portal}/ingest", "ingest_key": key,
                                                                         "project_id": project_id, "component": "node:."}))
        (tmp_path / "server.js").write_text(
            "(async () => {\n"
            f"  const r = await fetch('{provider}/v1/chat/completions', {{method: 'POST', body: '{{}}'}});\n"
            "  console.error('chatbot failed with status', r.status);\n"
            "  await new Promise(res => setTimeout(res, 2500));\n"
            "  throw new Error('checkout exploded');\n"
            "})();\n")
        out = subprocess.run([NODE, "-r", "./incident-agent-monitor.cjs", "server.js"], cwd=tmp_path, capture_output=True, text=True,
                             timeout=60, env=clean_env(AGENT_DAEMON_HEARTBEAT_SECONDS="1"))
    assert out.returncode != 0 and "checkout exploded" in out.stderr                 # the crash still crashes, exactly as before
    beats = portal_db.list_monitor_heartbeats(project_id)
    assert beats and beats[0]["monitor"] == "node" and beats[0]["component"] == "node:.", out.stderr
    messages = " || ".join(e["message"] for e in _events(project_id))
    assert "gpt-3.5-turbo" in messages and "HTTP 404" in messages                     # failed AI call, with the provider's message
    assert "chatbot failed with status 404" in messages                               # console.error
    assert "checkout exploded" in messages                                            # unhandled rejection / crash


def _chromium():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    return sync_playwright


@pytest.mark.skipif(_chromium() is None, reason="Playwright is not installed")
def test_browser_monitor_in_a_real_browser_checks_in_and_reports_the_chatbot_error(web_env):
    user_id, *_ = active_user()
    key = "browser-live-key-" + "w" * 30
    project_id = new_project(user_id, key)
    with portal_server() as portal:
        script = mi.browser_source({"ingestUrl": f"{portal}/ingest", "heartbeatUrl": f"{portal}/heartbeat", "key": key,
                                    "projectId": project_id, "component": "browser:.", "heartbeatSeconds": 1})
        with fake_provider() as provider:
            page_html = mi.inject_script_tag(
                "<html><head><title>chat</title></head><body><script>"
                f"fetch('{provider}/v1/chat/completions',{{method:'POST',body:'{{}}'}}).then(r=>r.json()).then(j=>console.error('bot:',j.error.message));"
                "setTimeout(function(){ undefinedFunctionCall(); }, 300);"
                "</script></body></html>", '<script src="monitor.js"></script>')
            with fake_provider(page=page_html, script=script) as site:
                sync_playwright = _chromium()
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch()
                        page = browser.new_page()
                        page.goto(f"{site}/site/")
                        page.wait_for_timeout(3500)
                        browser.close()
                except Exception as exc:          # no browser binary in this environment
                    pytest.skip(f"headless Chromium unavailable: {exc.__class__.__name__}")
    beats = portal_db.list_monitor_heartbeats(project_id)
    assert beats and beats[0]["monitor"] == "browser" and beats[0]["beats"] >= 1
    messages = " || ".join(e["message"] for e in _events(project_id))
    assert "HTTP 404" in messages and "gpt-3.5-turbo" in messages                       # failed fetch, full provider message
    assert "undefinedFunctionCall" in messages                                          # window.onerror


# ================================================================================================ Phase 3: the public-repo gate
def _connect_form(csrf, **extra):
    form = {"csrf": csrf, "repo": "demo/chatbot", "github_token": "ghp_" + "x" * 30, "name": "chatbot", "branch": "", "mode": "auto",
            "allow_install": "yes", "allow_ai_processing": "yes", "allow_remediation": "yes"}
    form.update(extra)
    return form


@pytest.fixture
def github(monkeypatch):
    """Offline GitHub: visibility is whatever the test says; every write is recorded."""
    state = {"private": False, "installs": [], "webhooks": [], "has_pages": False}
    monkeypatch.setattr(web_app, "validate_repository_access",
                        lambda **kw: {"private": state["private"], "default_branch": "main", "has_pages": state["has_pages"]})
    monkeypatch.setattr(web_app, "resolve_branch", lambda **kw: "main")

    def fake_install(**kw):
        if kw.get("require_private") and not state["private"]:
            raise mi.PublicRepoError("public")
        state["installs"].append(kw)
        return {"url": "https://github.com/demo/chatbot/pull/1", "number": 1, "branch": "agent-daemon/install-x", "base_branch": "main",
                "merged": True, "patched_file": None, "entry_file": "index.html", "embedded_key": True, "workflow_added": True,
                "had_ci": False, "targets": [{"label": "Web pages (HTML/JS)", "kind": "browser", "wired": True,
                                               "how": "a <script> tag at the top of 1 page(s)", "file": "index.html"}]}

    monkeypatch.setattr(web_app, "open_monitoring_pr", fake_install)
    monkeypatch.setattr(push_watch, "install_webhook", lambda project, token: state["webhooks"].append(project["id"]) or {"ok": True, "id": "1"})
    monkeypatch.setattr(push_watch, "branch_head", lambda project: {"sha": "a" * 40, "message": "init", "author": "dev"})
    return state


def test_a_public_repo_connects_in_pull_request_mode_and_says_why(web_env, fernet_env, github):
    user_id, csrf, cookie = active_user()
    status, _, body = _request("/projects/new", method="POST", cookie=cookie, form=_connect_form(csrf))       # asked for Auto
    assert status == "201 Created"
    assert "Your repository is public, so Agent Daemon works in Pull request mode" in body.replace("&#x27;", "'")
    assert github["installs"] == []                                   # no monitor: its key would be visible to everyone
    project = portal_db.list_projects(user_id)[0]
    assert github["webhooks"] == [project["id"]]                      # push checks keep working
    assert project["gate_state"] == "public_pr" and project["mode"] == "pr" and project["watch_mode"] == "push"
    _, _, page = _request(f"/projects/{project['id']}", cookie=cookie)
    assert "Fixes come as pull requests" in page and "I made it private" in page and "Push guard" in page
    assert any(n["kind"] == "repo_public" for n in portal_db.recent_notifications(10))


def test_github_pages_sites_can_stay_public(web_env, fernet_env, github):
    github["has_pages"] = True
    _user, csrf, cookie = active_user()
    status, _, body = _request("/projects/new", method="POST", cookie=cookie, form=_connect_form(csrf))
    assert status == "201 Created" and "Project saved" in body and "Pull request mode" in body


def test_i_made_it_private_while_still_public_says_so(web_env, fernet_env, github):
    user_id, csrf, cookie = active_user()
    _request("/projects/new", method="POST", cookie=cookie, form=_connect_form(csrf))
    project = portal_db.list_projects(user_id)[0]
    status, headers, _ = _request(f"/projects/{project['id']}/recheck-visibility", method="POST", cookie=cookie, form={"csrf": csrf})
    assert status.startswith("30") and "public=still" in dict(headers)["Location"]
    _, _, page = _request(f"/projects/{project['id']}?public=still", cookie=cookie)
    assert "GitHub still says the repository is public" in page
    assert github["installs"] == []


def test_private_again_restores_auto_mode(web_env, fernet_env, github):
    user_id, csrf, cookie = active_user()
    _request("/projects/new", method="POST", cookie=cookie, form=_connect_form(csrf))
    project = portal_db.list_projects(user_id)[0]
    github["private"] = True
    _request(f"/projects/{project['id']}/recheck-visibility", method="POST", cookie=cookie, form={"csrf": csrf})
    project = portal_db.get_project(project["id"], user_id)
    assert project["gate_state"] == "active" and project["mode"] == "auto" and project["watch_mode"] == "both"


def test_install_now_proceeds_once_private_and_runs_the_first_scan(web_env, fernet_env, github):
    user_id, csrf, cookie = active_user()
    _request("/projects/new", method="POST", cookie=cookie, form=_connect_form(csrf))
    project = portal_db.list_projects(user_id)[0]
    github["private"] = True                                                           # the owner made it private
    status, _, body = _request(f"/projects/{project['id']}/recheck-visibility", method="POST", cookie=cookie, form={"csrf": csrf})
    assert status == "200 OK" and "Your repository is private" in body and "Web pages (HTML/JS)" in body
    assert len(github["installs"]) == 1 and github["installs"][0]["require_private"] is True
    assert github["installs"][0]["ingest_key"].startswith("adi_")                      # project-scoped key, never our secrets
    project = portal_db.get_project(project["id"], user_id)
    assert project["gate_state"] == "active" and project["monitor_installed_at"]
    checks = portal_db.list_push_checks(project["id"])
    assert len(checks) == 1 and checks[0]["source"] == "connect"                       # one scan of the head commit (same commit is never queued twice)
    assert set(github["webhooks"]) == {project["id"]}                                  # push checks were on while public, and stay on


def test_private_repo_installs_immediately_on_connect(web_env, fernet_env, github):
    github["private"] = True
    user_id, csrf, cookie = active_user()
    status, _, body = _request("/projects/new", method="POST", cookie=cookie, form=_connect_form(csrf))
    assert status == "201 Created" and "Monitoring setup" in body and len(github["installs"]) == 1
    project = portal_db.list_projects(user_id)[0]
    assert project["gate_state"] == "active" and portal_db.list_push_checks(project["id"])[0]["source"] == "connect"


def test_installer_itself_refuses_a_public_repo_before_writing_anything(monkeypatch):
    writes = []

    def fake_request(url, token, method="GET", payload=None):
        if method != "GET":
            writes.append(url)
        return {"private": False, "default_branch": "main"}

    monkeypatch.setattr(mi, "_request", fake_request)
    with pytest.raises(mi.PublicRepoError):
        mi.open_monitoring_pr(owner="demo", repo="chatbot", base_branch="main", project_id="p" * 36, token="t",
                              ingest_url="https://portal/ingest", ingest_key="k" * 40)
    assert writes == []
    assert mi.is_private({"private": True}) and not mi.is_private({}) and not mi.is_private({"private": "true"})


def test_a_repo_that_turns_public_switches_to_pull_requests_notifies_and_revokes_the_key(web_env, fernet_env, monkeypatch):
    import repo_guard
    user_id, *_ = active_user("owner@example.com")
    project_id = new_project(user_id, "e" * 40, gate_state="active")
    portal_db.record_monitor_install(project_id, [{"kind": "python", "wired": True}], installed=True)
    monkeypatch.setattr(repo_guard, "_token", lambda project: "t")
    monkeypatch.setattr(repo_guard, "validate_repository_access", lambda **kw: {"private": False})
    assert repo_guard.sweep_visibility() == 0                                    # checked at connect: not due yet
    assert repo_guard.sweep_visibility(min_age_seconds=-5) == 1
    project = portal_db.get_project(project_id, user_id)
    assert project["gate_state"] == "public_pr" and project["mode"] == "pr"          # pull requests only from now on
    assert portal_db.get_project_by_ingest_hash(hashlib.sha256(("e" * 40).encode()).hexdigest()) is None   # old key revoked
    assert any(n["kind"] == "repo_public" for n in portal_db.recent_notifications(10))
    with pytest.raises(mi.PublicRepoError):                                       # every later commit is refused too
        repo_guard.ensure_private(project, "t")


# ================================================================================================ Phase 4/5: error -> fix pipeline
class FakeRepo:
    def __init__(self, tmp_path, files):
        self.root = tmp_path / "repo"
        for rel, text in files.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)

    @contextlib.contextmanager
    def snapshot(self, project, cfg=None):
        yield self.root


CHATBOT = {"index.html": "<html><head></head><body><script src='chat.js'></script></body></html>",
           "chat.js": "async function ask(q){\n  const r = await fetch('https://api.openai.com/v1/chat/completions', {method:'POST',\n"
                      "    body: JSON.stringify({model: 'gpt-3.5-turbo', messages:[{role:'user',content:q}]})});\n  return r.json();\n}\n"}


@pytest.fixture
def pipeline(web_env, tmp_path, monkeypatch):
    from fixengine import git_ops, model_catalog
    model_catalog.clear()
    monkeypatch.setenv("MODEL_CATALOG_OFFLINE", "1")
    monkeypatch.setenv("WORKER_MIN_AGE_SECONDS", "0")
    monkeypatch.setenv("FIXENGINE_SANDBOX_MODE", "remote")
    monkeypatch.delenv("FIXENGINE_SANDBOX_URL", raising=False)
    repo = FakeRepo(tmp_path, CHATBOT)
    opened = []
    monkeypatch.setattr(git_ops, "repo_snapshot", repo.snapshot)

    def open_pr(project, **kw):
        opened.append(kw)
        return {"url": "https://github.com/demo/chatbot/pull/9", "number": 9, "branch": "agent-daemon/fix-model", "head_sha": "f" * 40,
                "path": ", ".join(kw["new_files"]), "diff": kw["diff"]}

    monkeypatch.setattr(git_ops, "open_pr", open_pr)
    user_id, *_ = active_user("owner@example.com")
    key = "pipe-key-" + "q" * 32
    project_id = new_project(user_id, key, gate_state="active")
    return {"user_id": user_id, "project_id": project_id, "key": key, "opened": opened, "repo": repo}


def test_a_reported_retired_model_error_is_fixed_end_to_end(pipeline):
    import portal_worker
    event = {"message": "POST https://api.openai.com/v1/chat/completions failed with HTTP 404: The model `gpt-3.5-turbo` has been "
                        "deprecated | {\"error\":{\"code\":\"model_not_found\"}}", "level": "ERROR", "exception_type": "HTTPError",
             "monitor": "browser", "context": {"kind": "http", "host": "api.openai.com", "status": 404}}
    status, _, _ = _request("/ingest", method="POST", raw_body=json.dumps({**event, "ingest_key": pipeline["key"]}).encode(),
                            headers={"CONTENT_TYPE": "text/plain"})
    assert status == "202 Accepted"                                               # 1. reported
    assert portal_worker.process_one() is True                                    # 2-5. download, diagnose, fix, validate, PR
    assert len(pipeline["opened"]) == 1
    change = pipeline["opened"][0]
    assert "gpt-5.6-terra" in change["new_files"]["chat.js"] and "gpt-3.5-turbo" not in change["new_files"]["chat.js"]
    assert "[agent-daemon]" in change["title"] and "retired AI model" in change["title"]
    incident = portal_db.list_incidents(pipeline["project_id"])[0]                 # 6. recorded: error, diagnosis, fix, PR, status
    assert incident["status"] == "pr_opened" and incident["pr_url"].endswith("/pull/9")
    assert "gpt-3.5-turbo" in incident["root_cause"] and "gpt-5.6-terra" in incident["root_cause"]
    assert "parses" in incident["report"]                                         # basic validation ran (no sandbox here)
    conn = portal_db.get_connection()
    fix = dict(portal_db._execute(conn, "SELECT * FROM fixes WHERE incident_id=?", (incident["id"],)).fetchone())
    conn.close()
    assert "+" in fix["diff"] and "gpt-5.6-terra" in fix["diff"]
    assert incident["no_automerge"] == 1                                           # not verified against a live model list: review it


def test_python_and_mixed_repos_are_fixed_the_same_way(pipeline):
    import portal_worker
    for rel in list(CHATBOT):
        (pipeline["repo"].root / rel).unlink()
    (pipeline["repo"].root / "backend").mkdir()
    (pipeline["repo"].root / "backend/app.py").write_text(
        "import anthropic\nclient = anthropic.Anthropic()\n\ndef reply(q):\n"
        "    return client.messages.create(model=\"claude-3-haiku-20240307\", max_tokens=200, messages=[{'role': 'user', 'content': q}])\n")
    (pipeline["repo"].root / "web").mkdir()
    (pipeline["repo"].root / "web/index.html").write_text("<html><head></head></html>")
    portal_db.ingest_event(pipeline["project_id"], timestamp=portal_db._now(), level="ERROR",
                           message="anthropic.NotFoundError: Error code: 404 - {'type': 'error', 'error': {'type': 'not_found_error', "
                                   "'message': 'model: claude-3-haiku-20240307'}}", traceback='File "backend/app.py", line 5, in reply',
                           signature="NotFoundError:app.py:5")
    assert portal_worker.process_one() is True
    change = pipeline["opened"][0]["new_files"]
    assert list(change) == ["backend/app.py"] and 'model="claude-haiku-5-5"' in change["backend/app.py"]


def test_model_only_in_hosting_settings_gets_plain_instructions_not_a_broken_pr(pipeline):
    import portal_worker
    (pipeline["repo"].root / "chat.js").write_text("const model = process.env.OPENAI_MODEL;\n")
    portal_db.ingest_event(pipeline["project_id"], timestamp=portal_db._now(), level="ERROR",
                           message="POST https://api.openai.com/v1/responses failed with HTTP 404: The model `gpt-4-32k` does not exist",
                           traceback="", signature="HTTPError:api.openai.com:404:x")
    portal_worker.process_one()
    incident = portal_db.list_incidents(pipeline["project_id"])[0]
    assert pipeline["opened"] == [] and incident["status"] == "needs_human"
    assert "Environment variables" in incident["report"] and "gpt-5.6-sol" in incident["report"]


def test_a_fix_is_never_pushed_to_a_public_repo(pipeline, monkeypatch):
    import portal_worker
    from fixengine import git_ops

    def public(project, **kw):
        raise mi.PublicRepoError("public")

    monkeypatch.setattr(git_ops, "open_pr", public)
    portal_db.ingest_event(pipeline["project_id"], timestamp=portal_db._now(), level="ERROR",
                           message="The model `gpt-3.5-turbo` has been deprecated (api.openai.com)", traceback="", signature="x:y")
    portal_worker.process_one()
    incident = portal_db.list_incidents(pipeline["project_id"])[0]
    assert incident["stage"] == "waiting_private" and incident["status"] == "queued"


def test_the_first_scan_finds_a_retired_model_without_a_push_and_without_a_sandbox(pipeline):
    """Phase 5: the check queued on connect scans the existing code at once (no sandbox needed), and the finding goes
    through the same fix pipeline."""
    import portal_worker
    project = portal_db.get_project_any(pipeline["project_id"])
    check_id, _ = push_watch.enqueue(project, "b" * 40, source="connect")
    check = portal_db.claim_next_push_check()
    assert check["id"] == check_id
    assert push_watch.run_check(check, snapshot=pipeline["repo"].snapshot) == "waiting"     # sandbox offline: honest wait
    incidents = portal_db.list_incidents(pipeline["project_id"])
    assert len(incidents) == 1 and incidents[0]["source"] == "scan" and "gpt-3.5-turbo" in incidents[0]["signature"]
    assert portal_worker.process_one() is True
    assert pipeline["opened"] and "gpt-5.6-terra" in pipeline["opened"][0]["new_files"]["chat.js"]
    # a later scan of fixed code closes nothing that is still open, and never re-opens the fixed one
    assert portal_db.list_incidents(pipeline["project_id"])[0]["status"] == "pr_opened"


def test_scan_does_not_flag_current_models_or_unrelated_strings():
    from fixengine import model_fix
    files = {"a.js": "const m = 'gpt-4o'; const o = 'o1'; const n = 'claude-sonnet-5-5';", "b.py": "MODEL = 'gpt-5.6-sol'\nx = 'o1'\n",
             ".env": "OPENAI_MODEL=gpt-4\n", "README.md": "we used gpt-4 once"}
    assert model_fix.scan_files(files) == []
    hits = model_fix.scan_files({"c.py": "client.chat.completions.create(model='o1-mini')\n", "d.yaml": "model: gpt-4\n"})
    assert {h["model"] for h in hits} == {"o1-mini", "gpt-4"}


@pytest.mark.parametrize("message,model,provider", [
    ("The model `gpt-4-32k` does not exist or you do not have access to it.", "gpt-4-32k", "openai"),
    ("POST https://api.groq.com/openai/v1/chat/completions failed with HTTP 400: The model `mixtral-8x7b-32768` has been decommissioned",
     "mixtral-8x7b-32768", "groq"),
    ("{'type': 'not_found_error', 'message': 'model: claude-3-opus-20240229'}", "claude-3-opus-20240229", "anthropic"),
    ("models/gemini-1.5-flash is not found for API version v1beta, or is not supported for generateContent.", "gemini-1.5-flash", "google"),
])
def test_discontinued_model_errors_are_recognised(message, model, provider):
    from fixengine import model_fix
    found = model_fix.detect_error(message)
    assert found and found["model"] == model and found["provider"] == provider
    assert model_fix.detect_error("TypeError: Cannot read properties of undefined (reading 'map')") is None


def test_replacement_is_checked_against_the_live_model_list(monkeypatch):
    from fixengine import model_catalog, model_fix
    model_catalog.clear()
    model_catalog.set_for_tests("anthropic", [{"id": "claude-haiku-5-5", "created": 2}, {"id": "claude-sonnet-5-5", "created": 2}])
    choice = model_fix.choose_replacement("claude-3-haiku-20240307", "anthropic")
    assert choice == {**choice, "new": "claude-haiku-5-5", "verified": True, "old_live": False}
    model_catalog.set_for_tests("anthropic", [{"id": "claude-haiku-6-0", "created": 9}])     # the documented one is gone too
    assert model_fix.choose_replacement("claude-3-haiku-20240307", "anthropic")["new"] == "claude-haiku-6-0"
    model_catalog.clear()


def test_no_retired_model_ids_are_left_in_our_own_code():
    from fixengine import model_fix
    ours = {}
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT).as_posix()
        if path.is_file() and path.suffix in (".py", ".js", ".cjs", ".json", ".yaml", ".yml") and not rel.startswith(("tests/", "bench/")) \
                and rel not in ("model_registry.json", "scripts/simulate_monitoring.py"):   # registry + simulation fixtures
            ours[rel] = path.read_text(encoding="utf-8", errors="ignore")
    assert model_fix.scan_files(ours) == []


# ================================================================================================ Phase 6: diagrams and roles
def test_architecture_diagrams_show_every_process_and_respect_roles(web_env):
    st, _, public = _request("/how-it-works")
    assert st == "200 OK" and "Agent Daemon general architecture" in public and "<svg" in public
    assert "model adapter architecture" not in public.lower()                       # normal users: general architecture only
    for step in ("Connect project", "Public-repo check", "Install monitor", "Heartbeat · 30 s", "Error detected", "Sandbox",
                 "Understand", "The engineer", "Fix", "Tests", "Pull request", "Push guard", "dg-play", "prefers-reduced-motion"):
        assert step in public, step
    _, _, user_cookie = make_session("dev@example.com")
    assert _request("/admin/architecture", cookie=user_cookie)[0].startswith("404")
    _, _, admin_cookie = make_session("admin1@example.com")
    st, _, admin = _request("/admin/architecture", cookie=admin_cookie)
    assert st == "200 OK" and "Agent Daemon general architecture" in admin and "Agent Daemon model adapter architecture" in admin
    for part in ("Who works on it", "Normal → High → Extra", "Harm rules", "Never a silent stop", "GUARD", "OpenRouterAdapter"):
        assert part in admin, part


# ================================================================================================ Phase 8: configuration
def test_startup_fails_with_one_clear_message_when_required_settings_are_missing(monkeypatch):
    import config_check
    from cryptography.fernet import Fernet
    monkeypatch.setenv("APP_ENV", "production")
    for name in ("DATABASE_URL", "TOKEN_ENCRYPTION_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SESSION_SECRET", "short")
    with pytest.raises(SystemExit) as info:
        config_check.check("web")
    text = str(info.value)
    assert "DATABASE_URL" in text and "TOKEN_ENCRYPTION_KEY" in text and "SESSION_SECRET" in text
    monkeypatch.setenv("DATABASE_URL", "postgresql://db/agent")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    config_check.check("worker")                         # the worker never signs cookies, so it does not need SESSION_SECRET
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(SystemExit) as info:
        config_check.check("worker")
    assert "Fernet" in str(info.value)


def test_env_example_lists_every_setting_the_new_code_reads():
    text = (ROOT / ".env.example").read_text()
    for name in ("PORTAL_BASE_URL", "TOKEN_ENCRYPTION_KEY", "SESSION_SECRET", "MONITOR_OFFLINE_SECONDS", "VISIBILITY_CHECK_SECONDS",
                 "MODEL_REGISTRY_JSON", "GROQ_MODEL", "FIXENGINE_MODEL_HAIKU"):
        assert name in text, name
    assert not any(line.split("=", 1)[1].strip() for line in text.splitlines()
                   if line.strip() and not line.startswith("#") and "=" in line
                   and any(s in line for s in ("_KEY=", "_SECRET=", "PASSWORD")) and "FIXENGINE_SANDBOX_MODE" not in line)
