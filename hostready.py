"""Ready to host? (v4.2) A free, rule-based look at a repository: would it work if you put it online today, and where should it go.

Many owners (hackathon teams, beginners) connect a repository that has never been deployed. Everything else in Agent Daemon still
works for them (the sandbox tests every push, the engineer fixes what they ask), but nothing here can be checked live until the app
is online. This module finds the usual reasons a first deploy fails, picks the right kind of host for the stack, and writes the
click-by-click steps. The "Make it host-ready" button hands the code findings to the engineer as a normal request.

No AI, no network: it reads the files the push check already downloaded. Results are stored per project (fx flag hostready:<id>).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePosixPath

PORT_HARDCODED_JS = re.compile(r"\.listen\(\s*(\d{4,5})\s*[,)]")
PORT_ENV_JS = re.compile(r"process\.env\.PORT")
PORT_HARDCODED_PY = re.compile(r"\.run\([^)]*port\s*=\s*(\d{4,5})")
PORT_ENV_PY = re.compile(r"""(os\.environ|os\.getenv|environ\.get)\(?\s*\[?\s*['"]PORT['"]""")
LOCALHOST = re.compile(r"""['"`]https?://(?:localhost|127\.0\.0\.1)(?::\d+)?[^'"`]*['"`]""")
ENV_RE = [re.compile(r"process\.env\.([A-Z][A-Z0-9_]{1,60})"), re.compile(r"import\.meta\.env\.([A-Z][A-Z0-9_]{1,60})"),
          re.compile(r"os\.(?:getenv|environ\.get)\(\s*['\"]([A-Z][A-Z0-9_]{1,60})['\"]"),
          re.compile(r"os\.environ\[['\"]([A-Z][A-Z0-9_]{1,60})['\"]\]")]
BUILTIN_ENV = {"NODE_ENV", "PORT", "MODE", "DEV", "PROD", "SSR", "BASE_URL", "PYTHONPATH", "HOME", "PATH", "CI", "RENDER", "VERCEL"}
HOST_FILES = ("vercel.json", "netlify.toml", "render.yaml", "Procfile", "Dockerfile", "fly.toml", "railway.json", "app.yaml")
SKIP = ("node_modules/", "dist/", "build/", ".venv/", "venv/")
EXAMPLE_ENV = (".env.example", ".env.sample", ".env.template")


OWN = re.compile(r"(^|/)(incident[-_]agent[-_](monitor|config)[\w.-]*)$", re.I)     # our own monitor files are not the app


def _code(files: dict[str, str]) -> dict[str, str]:
    return {p: t for p, t in files.items() if not p.startswith(SKIP) and not OWN.search(p) and PurePosixPath(p).suffix.lower()
            in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".vue", ".svelte", ".html")}


def assess(root: Path | str, files: dict[str, str]) -> dict:
    """{kind, host, ready, findings:[{level, title, fix, code}], env:[names], has_host_file, steps:[...]}. Pure apart from listing root."""
    root = Path(root)
    names = set(files)
    try:
        present = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
                   and "node_modules" not in p.parts}
    except OSError:
        present = set(names)
    code = _code(files)
    pkg = {}
    if "package.json" in files:
        try:
            pkg = json.loads(files["package.json"]) or {}
        except ValueError:
            pkg = {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    scripts = pkg.get("scripts") or {}
    py = [p for p in code if p.endswith(".py")]
    text_all = "\n".join(code.values())

    # ---- what kind of app is it, and where should it go
    if "next" in deps:
        kind, host = "Next.js app", "Vercel"
    elif ("vite" in deps or "react-scripts" in deps) and not any(k in deps for k in ("express", "fastify", "koa", "@nestjs/core")):
        kind, host = "front-end (" + ("Vite" if "vite" in deps else "Create React App") + ")", "Vercel"
    elif any(k in deps for k in ("express", "fastify", "koa", "@nestjs/core")) or (pkg and scripts.get("start")):
        kind, host = "Node.js server", "Render"
    elif py and re.search(r"\b(Flask|FastAPI|django)\b", text_all):
        kind, host = ("Django" if "django" in text_all else "FastAPI" if "FastAPI" in text_all else "Flask") + " app", "Render"
    elif any(p.lower().endswith((".html", ".htm")) for p in names):
        kind, host = "static website", "Netlify"
    else:
        kind, host = "app", "Render"
    serverless = any(p.startswith(("api/", "netlify/functions/")) for p in names)

    findings: list[dict] = []

    def add(level, title, fix, code_fix=True):
        findings.append({"level": level, "title": title, "fix": fix, "code": code_fix})

    # ---- the usual reasons a first deploy fails
    if pkg:
        if host in ("Vercel", "Netlify") and not scripts.get("build"):
            add("error", "There is no build command", "Add a \"build\" script to package.json (for Vite: \"vite build\").")
        if kind == "Node.js server" and not scripts.get("start"):
            add("error", "There is no start command", "Add a \"start\" script to package.json, for example \"node server.js\".")
        if "package-lock.json" not in present and "yarn.lock" not in present and "pnpm-lock.yaml" not in present:
            add("warn", "There is no lock file", "Run npm install once on your computer and commit package-lock.json, so the host installs "
                "exactly the versions you tested.", code_fix=False)
    if py and not ({"requirements.txt", "pyproject.toml", "Pipfile"} & present):
        add("error", "Python dependencies are not listed", "Add a requirements.txt listing the packages the app imports.")
    if kind in ("Node.js server",) and PORT_HARDCODED_JS.search(text_all) and not PORT_ENV_JS.search(text_all):
        add("error", "The server uses a fixed port", "Hosts tell the app which port to use: listen on process.env.PORT (with your "
            "current port as the fallback).")
    if py and PORT_HARDCODED_PY.search(text_all) and not PORT_ENV_PY.search(text_all):
        add("error", "The server uses a fixed port", "Read the port from the PORT environment variable and listen on 0.0.0.0.")
    if re.search(r"\.run\([^)]*debug\s*=\s*True", text_all):
        add("warn", "Debug mode is on", "Turn debug mode off for the live site (it shows your code to visitors when something fails).")
    hits = sorted({p for p, t in code.items() if LOCALHOST.search(t) and not re.search(r"(^|/)(tests?|__tests__)/", p)})
    if hits:
        add("error", "The code calls localhost", "These files call http://localhost, which does not exist once the app is online: "
            + ", ".join(hits[:5]) + ". Use a relative path (/api/...) or an environment variable for the address.")
    if any(PurePosixPath(p).name == ".env" or (PurePosixPath(p).name.startswith(".env.") and PurePosixPath(p).name not in EXAMPLE_ENV)
           for p in present):
        add("error", "A .env file with secrets is in the repository", "Delete it from GitHub, add .env to .gitignore, and create new "
            "keys at each service (anyone who saw the repository may have the old ones).", code_fix=False)
    env = sorted(n for n in {n for rx in ENV_RE for n in rx.findall(text_all)} - BUILTIN_ENV
                 if not n.startswith(("AGENT_DAEMON_", "INCIDENT_AGENT_")))
    if env and not (set(EXAMPLE_ENV) & present):
        add("warn", "The settings the app needs are not written down", "Add a .env.example that lists the names (never the values): "
            + ", ".join(env[:12]) + ".")
    if host == "Render" and not ({"render.yaml", "Procfile", "Dockerfile"} & present):
        add("info", "No hosting file yet", "Optional: a render.yaml lets Render set everything up in one click.")
    ready = not any(f["level"] == "error" for f in findings)
    return {"kind": kind, "host": host, "serverless": serverless, "ready": ready, "findings": findings, "env": env[:20],
            "has_host_file": bool(set(HOST_FILES) & present), "steps": deploy_steps(host, kind, env, scripts, serverless)}


def deploy_steps(host: str, kind: str, env: list[str], scripts: dict, serverless: bool) -> list[str]:
    """Click-by-click, for someone who has never deployed anything."""
    env_line = ("Under Environment Variables add each of these, with the value from where you got the key: " + ", ".join(env[:12])
                + ". (Names that start with VITE_ or NEXT_PUBLIC_ are visible to visitors: never put a secret key in them.)") if env else ""
    if host == "Vercel":
        steps = ["Open vercel.com and sign in with GitHub.", "Click Add New, then Project, then Import next to this repository.",
                 "Vercel detects the framework by itself. Leave Build Command and Output Directory as they are.",
                 env_line, "Click Deploy and wait about one minute.",
                 "Copy the address Vercel shows (it ends in .vercel.app) and paste it under Live site address on this project page."]
        if serverless:
            steps.insert(3, "Your api/ folder becomes serverless functions automatically: nothing to set up.")
    elif host == "Netlify":
        steps = ["Open netlify.com and sign in with GitHub.", "Click Add new site, then Import an existing project, then GitHub, "
                 "then this repository.", "Leave the build settings as they are (for a plain HTML site they stay empty).", env_line,
                 "Click Deploy and wait about one minute.",
                 "Copy the address Netlify shows (it ends in .netlify.app) and paste it under Live site address on this project page."]
    else:
        start = "npm start" if scripts.get("start") else ("gunicorn app:app" if "Flask" in kind else
                                                          "uvicorn main:app --host 0.0.0.0 --port $PORT" if "FastAPI" in kind else
                                                          "gunicorn <project>.wsgi" if "Django" in kind else "the command that starts your app")
        build = "npm install" if scripts else "pip install -r requirements.txt"
        steps = ["Open render.com and sign in with GitHub.", "Click New, then Web Service, then choose this repository.",
                 f"Build Command: {build}", f"Start Command: {start}", "Instance type: Free is fine to start.", env_line,
                 "Click Create Web Service and wait a few minutes until it says Live.",
                 "Copy the address Render shows (it ends in .onrender.com) and paste it under Live site address on this project page."]
    return [s for s in steps if s]


def save(project_id: str, result: dict) -> None:
    from fixengine import store
    store.set_flag(f"hostready:{project_id}", json.dumps(result)[:20000])


def load(project_id: str) -> dict:
    try:
        from fixengine import store
        data = json.loads(store.get_flag(f"hostready:{project_id}", "") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def request_text(result: dict) -> str:
    """What the 'Make it host-ready' button asks the engineer to do."""
    todo = [f"- {f['title']}: {f['fix']}" for f in result.get("findings", []) if f.get("code") and f.get("level") in ("error", "warn")]
    return (f"Make this {result.get('kind', 'app')} ready to put online on {result.get('host', 'a host')}. Fix these in the code:\n"
            + ("\n".join(todo) if todo else "- check that it builds and starts the way the host needs")
            + "\nAdd or update the hosting file if it helps (never put secret values in it). Keep everything else working; run the checks."
            + ("" if os.getenv("HOSTREADY_NO_ENV_EXAMPLE") else
               "\nIf the app reads settings from environment variables, list their NAMES (no values) in a .env.example file."))
