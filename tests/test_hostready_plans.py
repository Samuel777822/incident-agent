"""The ready-to-host plan fits each app: its parts, its real start command, its services, its own pitfalls."""
import json

import hostready


def _assess(tmp_path, files):
    for p, t in files.items():
        (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / p).write_text(t, encoding="utf-8")
    return hostready.assess(tmp_path, files)


def _titles(r):
    return " | ".join(f["title"] for f in r["findings"])


def test_a_react_single_page_app_needs_a_rewrite_rule_and_goes_to_vercel(tmp_path):
    r = _assess(tmp_path, {"package.json": json.dumps({"dependencies": {"react": "18", "react-router-dom": "6", "vite": "5"},
                                                      "scripts": {"build": "vite build"}}),
                           "package-lock.json": "{}", "src/main.jsx": "import { BrowserRouter } from 'react-router-dom'\n"})
    assert r["kind"] == "React front-end (Vite)" and r["host"] == "Vercel"
    assert "Refreshing a page will show 404" in _titles(r) and not r["ready"]
    assert r["parts"][0]["output"] == "dist" and "vercel.com" in r["steps"][0]


def test_a_front_end_plus_api_repo_is_planned_part_by_part(tmp_path):
    files = {"frontend/package.json": json.dumps({"dependencies": {"react": "18", "vite": "5"}, "scripts": {"build": "vite build"}}),
             "frontend/package-lock.json": "{}",
             "frontend/src/api.js": "export const get = () => fetch('http://localhost:5000/api/items')\n",
             "backend/package.json": json.dumps({"dependencies": {"express": "4"}, "scripts": {"start": "node server.js"}}),
             "backend/package-lock.json": "{}",
             "backend/server.js": "const app = require('express')()\napp.listen(process.env.PORT || 5000)\nprocess.env.MONGO_URL\n"}
    r = _assess(tmp_path, files)
    kinds = {p["dir"]: p["kind"] for p in r["parts"]}
    assert kinds == {"frontend": "React front-end (Vite)", "backend": "Node.js server (Express)"} and r["host"] == "Render + Vercel"
    titles = _titles(r)
    assert "frontend: The code calls localhost" in titles and "no setting for the API's address" in titles and "CORS" in titles
    steps = " ".join(r["steps"])
    assert steps.index("render.com") < steps.index("vercel.com")                          # the API first: the front-end needs its address
    assert "Root Directory: backend" in steps and "Root Directory: frontend" in steps and "Start Command: npm start" in steps
    assert any("FRONTEND_URL" in a for a in r["after"])


def test_a_flask_app_gets_its_real_start_command_and_gunicorn(tmp_path):
    r = _assess(tmp_path, {"requirements.txt": "flask\n", "src/server.py": "from flask import Flask\napplication = Flask(__name__)\n"})
    assert r["kind"] == "Flask app" and r["parts"][0]["start"] == "gunicorn src.server:application"
    assert "gunicorn is not in requirements.txt" in _titles(r)
    assert "Start Command: gunicorn src.server:application" in " ".join(r["steps"])


def test_fastapi_django_and_streamlit_each_get_their_own_command(tmp_path):
    fast = _assess(tmp_path / "f", {"requirements.txt": "fastapi\nuvicorn\n", "main.py": "from fastapi import FastAPI\napi = FastAPI()\n"})
    assert fast["parts"][0]["start"] == "uvicorn main:api --host 0.0.0.0 --port $PORT" and fast["ready"]
    dj = _assess(tmp_path / "d", {"requirements.txt": "django\n", "manage.py": "import django\n", "shop/wsgi.py": "import django\n",
                                  "shop/settings.py": "ALLOWED_HOSTS = []\n"})
    assert dj["parts"][0]["start"] == "gunicorn shop.wsgi" and "gunicorn is not in" in _titles(dj) and "ALLOWED_HOSTS is empty" in _titles(dj)
    st = _assess(tmp_path / "s", {"requirements.txt": "streamlit\n", "dashboard.py": "import streamlit as st\nst.title('x')\n"})
    assert st["kind"] == "Streamlit app" and "streamlit run dashboard.py --server.port $PORT" in st["parts"][0]["start"]


def test_data_that_free_hosts_wipe_is_called_out(tmp_path):
    r = _assess(tmp_path, {"requirements.txt": "flask\ngunicorn\n",
                           "app.py": "from flask import Flask\nimport sqlite3\napp = Flask(__name__)\ndb = sqlite3.connect('data.db')\n"
                                     "app.config['UPLOAD_FOLDER'] = 'uploads'\n"})
    titles = _titles(r)
    assert "SQLite file" in titles and "Uploaded files are saved on the server's disk" in titles


def test_services_add_the_right_after_deploy_steps(tmp_path):
    r = _assess(tmp_path, {"package.json": json.dumps({"dependencies": {"react": "18", "vite": "5", "@supabase/supabase-js": "2"},
                                                      "scripts": {"build": "vite build"}}),
                           "package-lock.json": "{}",
                           "src/auth.js": "supabase.auth.signInWithOAuth({provider: 'google'})\nimport.meta.env.VITE_SUPABASE_URL\n"})
    after = " ".join(r["after"])
    assert "Supabase: Authentication, URL Configuration" in after and "Google Cloud Console" in after
    assert r["parts"][0]["services"] == ["Supabase", "Google sign-in"] and "VITE_SUPABASE_URL" in r["env"]


def test_a_java_service_needs_a_dockerfile(tmp_path):
    r = _assess(tmp_path, {"pom.xml": "<project/>", "src/main/java/App.java": "class App {}"})
    assert r["kind"] == "Java service (Maven)" and "There is no Dockerfile" in _titles(r)


def test_the_engineer_is_asked_to_understand_the_app_and_write_its_own_plan(tmp_path):
    r = _assess(tmp_path, {"requirements.txt": "flask\n", "app.py": "from flask import Flask\napp = Flask(__name__)\n"})
    text = hostready.request_text(r)
    assert "read the whole code and check that first look" in text and "owner_steps" in text and "gunicorn app:app" in text
