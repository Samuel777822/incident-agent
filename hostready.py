"""Ready to host? (v5) A free look at THIS repository: what parts it has, where each part should go, what would break on the first
deploy, and the click-by-click plan for exactly this app.

Many owners (hackathon teams, beginners) connect a repository that has never been deployed. Everything else in Agent Daemon still
works for them, but nothing can be checked live until the app is online. This module reads the files the push check already
downloaded and understands the app part by part:

  * the parts: a front-end, an API, a Python app, a static site, a Java service... each in its own folder (monorepos too);
  * for each part: the framework, the right host, the exact build and start commands (the real entry file and app object), where
    the build output goes, which settings it reads;
  * what joins the parts: the front-end's API address, CORS on the API, sign-in redirect URLs, the database;
  * what breaks on a first deploy: no start command, a fixed port, calls to localhost, page refresh 404s on single-page apps,
    a SQLite file or uploads folder that free hosts wipe, a committed .env, a server package missing from requirements.

The "Make it host-ready" button hands all of it to the engineer, who reads the whole code and makes this app ready (and writes the
owner's steps). No AI and no network here. Results are stored per project (fx flag hostready:<id>).
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
SKIP = ("node_modules/", "dist/", "build/", ".venv/", "venv/", ".next/")
EXAMPLE_ENV = (".env.example", ".env.sample", ".env.template")
MANIFESTS = ("package.json", "requirements.txt", "pyproject.toml", "Pipfile", "manage.py", "pom.xml", "build.gradle", "build.gradle.kts")
OWN = re.compile(r"(^|/)(incident[-_]agent[-_](monitor|config)[\w.-]*)$", re.I)     # our own monitor files are not the app
JS_SERVER_DEPS = ("express", "fastify", "koa", "@nestjs/core", "hono", "@hapi/hapi")


def _skip(p: str) -> bool:
    return any(f"/{s}" in f"/{p}" for s in SKIP)


def _code(files: dict[str, str]) -> dict[str, str]:
    return {p: t for p, t in files.items() if not _skip(p) and not OWN.search(p) and PurePosixPath(p).suffix.lower()
            in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".vue", ".svelte", ".html")}


def _under(path: str, folder: str) -> bool:
    return not folder or path == folder or path.startswith(folder + "/")


def _rel(path: str, folder: str) -> str:
    return path[len(folder) + 1:] if folder else path


def _part_dirs(names: set[str]) -> list[str]:
    """Folders that hold a project of their own (a manifest), shallowest first; the repo root counts when it has one."""
    dirs = set()
    for p in names:
        if _skip(p) or OWN.search(p):
            continue
        pp = PurePosixPath(p)
        if pp.name in MANIFESTS and len(pp.parts) <= 3:
            dirs.add(str(pp.parent) if str(pp.parent) != "." else "")
    if not dirs and any(p.lower().endswith((".html", ".htm")) for p in names if not _skip(p)):
        tops = sorted({str(PurePosixPath(p).parent) if str(PurePosixPath(p).parent) != "." else "" for p in names
                       if p.lower().endswith("index.html") and not _skip(p)}, key=len)
        dirs.add(tops[0] if tops else "")
    return sorted(dirs, key=lambda x: (x.count("/"), x)) or [""]


def _py_app_object(code: dict[str, str], folder: str, cls: str) -> tuple[str, str]:
    """(module path for the start command, variable name) of the file that creates the Flask / FastAPI app."""
    rx = re.compile(rf"^(\w+)\s*=\s*{cls}\(", re.M)
    ranked = sorted((p for p in code if p.endswith(".py") and _under(p, folder) and rx.search(code[p])),
                    key=lambda p: (PurePosixPath(p).name not in ("app.py", "main.py", "server.py", "wsgi.py"), p.count("/"), p))
    if not ranked:
        return "", ""
    path = _rel(ranked[0], folder)
    module = path[:-3].replace("/", ".")
    return module, rx.search(code[ranked[0]]).group(1)


def _analyse_part(folder: str, files: dict[str, str], present: set[str], code_all: dict[str, str], others: tuple = ()) -> dict:
    mine = lambda p: _under(p, folder) and not any(_under(p, o) for o in others)       # noqa: E731  (sub-projects are their own parts)
    here = {_rel(p, folder): t for p, t in files.items() if mine(p)}
    here_present = {_rel(p, folder) for p in present if mine(p)}
    code = {p: t for p, t in code_all.items() if mine(p)}
    text = "\n".join(code.values())
    pkg = {}
    if "package.json" in here:
        try:
            pkg = json.loads(here["package.json"]) or {}
        except ValueError:
            pkg = {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    scripts = pkg.get("scripts") or {}
    py = [p for p in code if p.endswith(".py")]
    reqs = " ".join(here.get(n, "") for n in ("requirements.txt", "pyproject.toml", "Pipfile")).lower()
    part = {"dir": folder or ".", "kind": "app", "host": "Render", "build": "", "start": "", "output": "", "role": "server",
            "spa": False, "scripts": scripts, "deps": sorted(deps)[:40], "findings": []}

    def add(level, title, fix, code_fix=True):
        part["findings"].append({"level": level, "title": title, "fix": fix, "code": code_fix})

    if "next" in deps:
        part.update(kind="Next.js app", host="Vercel", role="web", build=scripts.get("build") and "npm run build" or "next build")
    elif ("vite" in deps or "react-scripts" in deps or "@vue/cli-service" in deps or "@angular/core" in deps) and not any(k in deps for k in JS_SERVER_DEPS):
        tool = "Vite" if "vite" in deps else "Create React App" if "react-scripts" in deps else "Angular" if "@angular/core" in deps else "Vue CLI"
        lib = "React" if "react" in deps else "Vue" if "vue" in deps else "Svelte" if "svelte" in deps else "Angular" if tool == "Angular" else ""
        part.update(kind=f"{lib + ' ' if lib else ''}front-end ({tool})", host="Vercel", role="web", build="npm run build",
                    output="dist" if tool in ("Vite", "Vue CLI") else "build" if tool == "Create React App" else "dist/<project>")
        part["spa"] = any(k in deps for k in ("react-router-dom", "react-router", "vue-router", "@tanstack/react-router")) or tool == "Angular"
    elif any(k in deps for k in JS_SERVER_DEPS) or (pkg and scripts.get("start")):
        framework = next((k for k in JS_SERVER_DEPS if k in deps), "")
        main = pkg.get("main") or next((n for n in ("server.js", "index.js", "app.js", "src/server.js", "src/index.js", "server.ts",
                                                      "src/index.ts") if n in here), "")
        part.update(kind=f"Node.js server{' (' + framework.split('/')[-1].title() + ')' if framework else ''}", host="Render",
                    build="npm install" + (" && npm run build" if scripts.get("build") else ""),
                    start="npm start" if scripts.get("start") else (f"node {main}" if main else ""))
        if not scripts.get("start"):
            add("error", "There is no start command", "Add a \"start\" script to package.json"
                + (f", for example \"node {main}\"." if main else ", for example \"node server.js\"."))
        if PORT_HARDCODED_JS.search(text) and not PORT_ENV_JS.search(text):
            add("error", "The server uses a fixed port", "Hosts tell the app which port to use: listen on process.env.PORT (with your "
                "current port as the fallback).")
    elif py and re.search(r"\b(Flask|FastAPI|django|streamlit)\b", text):
        if "manage.py" in here or "django" in reqs or re.search(r"\bdjango\b", text):
            wsgi = next((p for p in here if p.endswith("/wsgi.py")), "")
            module = wsgi[:-3].replace("/", ".") if wsgi else "<project>.wsgi"
            part.update(kind="Django app", build="pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate",
                        start=f"gunicorn {module}")
            if "gunicorn" not in reqs:
                add("error", "gunicorn is not in requirements.txt", "Add gunicorn to requirements.txt: it is the server Render uses to run Django.")
            if re.search(r"ALLOWED_HOSTS\s*=\s*\[\s*\]", text):
                add("error", "ALLOWED_HOSTS is empty", "Read the allowed host names from an environment variable (for example "
                    "ALLOWED_HOSTS=your-app.onrender.com), or Django refuses every request online.")
        elif re.search(r"^\s*import streamlit|^\s*from streamlit", text, re.M):
            entry = next((p for p in py if re.search(r"^\s*import streamlit", code[p], re.M)), "app.py")
            part.update(kind="Streamlit app", build="pip install -r requirements.txt",
                        start=f"streamlit run {_rel(entry, folder)} --server.port $PORT --server.address 0.0.0.0")
        elif re.search(r"\bFastAPI\b", text):
            module, var = _py_app_object(code, folder, "FastAPI")
            part.update(kind="FastAPI app", build="pip install -r requirements.txt",
                        start=f"uvicorn {module or 'main'}:{var or 'app'} --host 0.0.0.0 --port $PORT")
            if "uvicorn" not in reqs and reqs:
                add("error", "uvicorn is not in requirements.txt", "Add uvicorn to requirements.txt: it is the server that runs FastAPI online.")
        else:
            module, var = _py_app_object(code, folder, "Flask")
            part.update(kind="Flask app", build="pip install -r requirements.txt", start=f"gunicorn {module or 'app'}:{var or 'app'}")
            if "gunicorn" not in reqs and reqs:
                add("error", "gunicorn is not in requirements.txt", "Add gunicorn to requirements.txt: Flask's own server is for your computer "
                    "only; gunicorn runs it online.")
        if PORT_HARDCODED_PY.search(text) and not PORT_ENV_PY.search(text) and part["kind"] in ("Flask app",):
            add("warn", "The app runs on a fixed port", "Online, gunicorn starts it, so this is fine there; for other hosts read the port from "
                "PORT and listen on 0.0.0.0.")
        if re.search(r"\.run\([^)]*debug\s*=\s*True", text):
            add("warn", "Debug mode is on", "Turn debug mode off for the live site (it shows your code to visitors when something fails).")
    elif "pom.xml" in here or "build.gradle" in here or "build.gradle.kts" in here:
        part.update(kind="Java service (" + ("Maven" if "pom.xml" in here else "Gradle") + ")", host="Render (Docker)",
                    build="docker build", start="java -jar app.jar")
        if "Dockerfile" not in here_present:
            add("error", "There is no Dockerfile", "Render runs Java apps from a Dockerfile: add one that builds the jar and starts it on $PORT.")
    elif any(p.lower().endswith((".html", ".htm")) for p in here):
        part.update(kind="static website", host="Netlify", role="web", build="", output=".")
    if py and not ({"requirements.txt", "pyproject.toml", "Pipfile"} & here_present):
        add("error", "Python dependencies are not listed", "Add a requirements.txt listing the packages the app imports.")
    if pkg and not ({"package-lock.json", "yarn.lock", "pnpm-lock.yaml"} & here_present):
        add("warn", "There is no lock file", "Run npm install once on your computer and commit package-lock.json, so the host installs "
            "exactly the versions you tested.", code_fix=False)
    if part["host"] in ("Vercel", "Netlify") and pkg and not scripts.get("build") and part["kind"] != "static website":
        add("error", "There is no build command", "Add a \"build\" script to package.json (for Vite: \"vite build\").")
    if part["spa"] and not ({"vercel.json", "netlify.toml", "_redirects", "public/_redirects"} & here_present):
        add("error", "Refreshing a page will show 404", "This single-page app uses client-side routes: add a vercel.json with a rewrite of "
            "every path to /index.html (or public/_redirects with \"/* /index.html 200\" on Netlify).")
    hits = sorted({p for p, t in code.items() if LOCALHOST.search(t) and not re.search(r"(^|/)(tests?|__tests__)/", p)})
    if hits:
        add("error", "The code calls localhost", "These files call http://localhost, which does not exist once the app is online: "
            + ", ".join(hits[:5]) + ". Use a relative path (/api/...) or an environment variable for the address.")
    # data that free hosts throw away
    if part["role"] == "server":
        if re.search(r"sqlite3|sqlite:///|better-sqlite3|\.sqlite3?['\"]|\.db['\"]", text):
            add("warn", "Data is kept in a SQLite file", "Free hosts wipe the disk on every deploy, so the data disappears. Use a hosted "
                "database (Render PostgreSQL, Supabase or Neon) for anything you must keep.", code_fix=False)
        if re.search(r"multer\(\s*\{\s*dest|upload_folder|UPLOAD_FOLDER|\.save\(os\.path\.join", text):
            add("warn", "Uploaded files are saved on the server's disk", "They disappear on every deploy of a free host: store uploads in "
                "a storage service (Supabase Storage, Cloudinary, S3).", code_fix=False)
    part["env"] = sorted(n for n in {n for rx in ENV_RE for n in rx.findall(text)} - BUILTIN_ENV
                         if not n.startswith(("AGENT_DAEMON_", "INCIDENT_AGENT_")))[:20]
    part["services"] = _services(text, deps, reqs)
    return part


def _services(text: str, deps: dict, reqs: str) -> list[str]:
    found = []
    checks = [("Supabase", ("@supabase/supabase-js",), "supabase"), ("Firebase", ("firebase", "firebase-admin"), "firebase"),
              ("MongoDB", ("mongoose", "mongodb"), "pymongo"), ("PostgreSQL", ("pg", "postgres", "@prisma/client"), "psycopg"),
              ("Stripe", ("stripe",), "stripe"), ("Google sign-in", ("next-auth", "passport-google-oauth20", "@react-oauth/google"), "authlib")]
    for name, js, pyname in checks:
        if any(k in deps for k in js) or pyname in reqs:
            found.append(name)
    if "signInWithOAuth" in text and "Google sign-in" not in found:
        found.append("Google sign-in")
    return found


def assess(root: Path | str, files: dict[str, str]) -> dict:
    """{kind, host, ready, parts:[...], findings:[{level, title, fix, code}], env:[names], steps:[...], after:[...]}."""
    root = Path(root)
    names = set(files)
    try:
        present = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
                   and "node_modules" not in p.parts}
    except OSError:
        present = set(names)
    code_all = _code(files)
    dirs = _part_dirs(names | present)
    parts = [_analyse_part(d, files, present | names, code_all, tuple(o for o in dirs if o != d and _under(o, d) and d != o))
             for d in dirs]
    parts = [p for p in parts if p["kind"] != "app"] or parts[:1]
    web = [p for p in parts if p["role"] == "web"]
    servers = [p for p in parts if p["role"] == "server"]
    findings: list[dict] = []
    multi = len(parts) > 1
    for p in parts:
        for f in p["findings"]:
            findings.append({**f, "title": (f"{p['dir']}: " if multi else "") + f["title"]})
    if any(PurePosixPath(p).name == ".env" or (PurePosixPath(p).name.startswith(".env.") and PurePosixPath(p).name not in EXAMPLE_ENV)
           for p in present):
        findings.append({"level": "error", "title": "A .env file with secrets is in the repository", "code": False,
                         "fix": "Delete it from GitHub, add .env to .gitignore, and create new keys at each service (anyone who saw the "
                                "repository may have the old ones)."})
    env = sorted({n for p in parts for n in p["env"]})
    if env and not (set(EXAMPLE_ENV) & present) and not any(f"{p['dir']}/{e}" in present for p in parts for e in EXAMPLE_ENV):
        findings.append({"level": "warn", "title": "The settings the app needs are not written down", "code": True,
                         "fix": "Add a .env.example that lists the names (never the values): " + ", ".join(env[:12]) + "."})
    if web and servers:
        front_env = [n for n in web[0]["env"] if re.search(r"API|BACKEND|SERVER|BASE_URL", n)]
        if not front_env:
            findings.append({"level": "error", "title": "The front-end has no setting for the API's address", "code": True,
                             "fix": f"Read the API address in {web[0]['dir']} from an environment variable (for Vite: "
                                    "import.meta.env.VITE_API_URL), so it can point at the deployed API instead of your computer."})
        server_text = " ".join(servers[0]["deps"])
        if not re.search(r"\bcors\b|flask_cors|flask-cors|CORSMiddleware", server_text + " ".join(code_all.values())):
            findings.append({"level": "warn", "title": "The API does not allow the front-end's address (CORS)", "code": True,
                             "fix": "Allow the front-end's address in CORS on the API (read it from a FRONTEND_URL setting), or the "
                                    "browser blocks every call once they are on different addresses."})
    if any(p["host"].startswith("Render") for p in parts) and not ({"render.yaml", "Procfile", "Dockerfile"} & present):
        findings.append({"level": "info", "title": "No hosting file yet", "code": True,
                         "fix": "Optional: a render.yaml lets Render set everything up in one click."})
    ready = not any(f["level"] == "error" for f in findings)
    kind = " + ".join(p["kind"] for p in parts)
    hosts = []
    for p in parts:
        if p["host"] not in hosts:
            hosts.append(p["host"])
    serverless = any(p.startswith(("api/", "netlify/functions/")) for p in names)
    steps, after = plan(parts, serverless)
    return {"kind": kind, "host": " + ".join(hosts), "serverless": serverless, "ready": ready, "findings": findings, "env": env[:20],
            "has_host_file": bool(set(HOST_FILES) & present), "steps": steps, "after": after,
            "parts": [{k: p[k] for k in ("dir", "kind", "host", "build", "start", "output", "env", "services", "spa")} for p in parts]}


def _env_line(env: list[str]) -> str:
    return ("Under Environment Variables add each of these, with the value from where you got the key: " + ", ".join(env[:12])
            + ". (Names that start with VITE_ or NEXT_PUBLIC_ are visible to visitors: never put a secret key in them.)") if env else ""


def plan(parts: list[dict], serverless: bool = False) -> tuple[list[str], list[str]]:
    """Click-by-click for THIS app: the API first (the front-end needs its address), then the front-end, then what to update."""
    ordered = sorted(parts, key=lambda p: p["role"] != "server")
    steps: list[str] = []
    multi = len(parts) > 1
    api_var = ""
    for i, p in enumerate(ordered, 1):
        head = f"Part {i}, {p['kind']} in {p['dir']}: " if multi else ""
        root_line = f"Root Directory: {p['dir']}" if p["dir"] not in (".", "") else ""
        if p["host"] == "Vercel":
            if p["role"] == "web" and multi:
                api_var = next((n for n in p["env"] if re.search(r"API|BACKEND|SERVER|BASE_URL", n)), "VITE_API_URL")
            part_steps = ["Open vercel.com and sign in with GitHub.", "Click Add New, then Project, then Import next to this repository.",
                          root_line, "Vercel detects the framework by itself. Leave Build Command and Output Directory as they are"
                          + (f" (it builds with {p['build']} into {p['output']})." if p.get("output") else "."),
                          (f"Set {api_var} to the address of the API from part 1 (it ends in .onrender.com)." if api_var else ""),
                          _env_line([n for n in p["env"] if n != api_var]), "Click Deploy and wait about one minute."]
            if serverless and not multi:
                part_steps.insert(4, "Your api/ folder becomes serverless functions automatically: nothing to set up.")
        elif p["host"] == "Netlify":
            part_steps = ["Open netlify.com and sign in with GitHub.", "Click Add new site, then Import an existing project, then GitHub, "
                          "then this repository.", (f"Base directory: {p['dir']}" if root_line else ""),
                          "Leave the build settings as they are (for a plain HTML site they stay empty).", _env_line(p["env"]),
                          "Click Deploy and wait about one minute."]
        else:
            docker = p["host"] == "Render (Docker)"
            part_steps = ["Open render.com and sign in with GitHub.", "Click New, then Web Service, then choose this repository.", root_line,
                          ("Language: Docker (Render uses your Dockerfile)." if docker else f"Build Command: {p['build'] or 'npm install'}"),
                          ("" if docker else f"Start Command: {p['start'] or 'the command that starts your app'}"),
                          "Instance type: Free is fine to start.", _env_line(p["env"]),
                          "Click Create Web Service and wait a few minutes until it says Live."]
        steps.extend(head + s for s in part_steps if s)
    web = [p for p in ordered if p["role"] == "web"]
    last = web[-1] if web else ordered[-1]
    ending = {"Vercel": ".vercel.app", "Netlify": ".netlify.app"}.get(last["host"], ".onrender.com")
    steps.append(f"Copy the address of your site (it ends in {ending}) and paste it under Live site address on this project page.")
    after = []
    services = {s for p in parts for s in p.get("services", [])}
    if multi and any(p["role"] == "server" for p in parts) and web:
        after.append("On the API's host, set FRONTEND_URL to your site's address, so the API accepts calls from it (CORS).")
    if "Supabase" in services:
        after.append("In Supabase: Authentication, URL Configuration: set Site URL to your site's address and add it under Redirect URLs.")
    if "Firebase" in services:
        after.append("In Firebase: Authentication, Settings, Authorized domains: add your site's domain.")
    if "Google sign-in" in services:
        after.append("In Google Cloud Console: APIs & Services, Credentials, your OAuth client: add your site's address under Authorized "
                     "JavaScript origins and its sign-in callback under Authorized redirect URIs.")
    if "Stripe" in services:
        after.append("In Stripe: Developers, Webhooks: point the webhook at your API's new address and copy the new signing secret into "
                     "its settings.")
    if "MongoDB" in services:
        after.append("In MongoDB Atlas: Network Access: allow access from anywhere (0.0.0.0/0), because free hosts change their address.")
    return steps + after, after


def deploy_steps(host: str, kind: str, env: list[str], scripts: dict, serverless: bool) -> list[str]:
    """Kept for older callers: the steps for one part."""
    role = "web" if host in ("Vercel", "Netlify") else "server"
    start = "npm start" if scripts.get("start") else ""
    steps, _ = plan([{"dir": ".", "kind": kind, "host": host, "build": "npm install" if scripts else "", "start": start, "output": "",
                      "env": env, "services": [], "spa": False, "role": role}], serverless)
    return steps


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
    """What the 'Make it host-ready' button asks the engineer: understand THIS app, make it deployable, write the plan for it."""
    todo = [f"- {f['title']}: {f['fix']}" for f in result.get("findings", []) if f.get("code") and f.get("level") in ("error", "warn")]
    parts = "\n".join(f"- {p.get('dir')}: {p.get('kind')} -> {p.get('host')}"
                      + (f" (build: {p['build']}; start: {p['start']})" if p.get("start") else "") for p in result.get("parts", []))
    return (f"Make this app ready to put online. Our first look says it is: {result.get('kind', 'an app')}, best hosted on "
            f"{result.get('host', 'a host')}.\n" + (f"Its parts:\n{parts}\n" if parts else "")
            + "First read the whole code and check that first look: correct it if it is wrong (the real entry file, the real app object, "
            "how the parts talk to each other, which settings and services it uses).\n"
            + "Then fix in the code what would stop the first deploy:\n" + ("\n".join(todo) if todo else "- check that it builds and starts the way the host needs")
            + "\nAdd or update the hosting files this app needs (never put secret values in them). Keep everything else working and run the checks."
            + ("" if os.getenv("HOSTREADY_NO_ENV_EXAMPLE") else
               "\nIf the app reads settings from environment variables, list their NAMES (no values) in a .env.example file.")
            + "\nIn owner_steps, write the click-by-click plan for THIS app: which host for each part, the exact build and start "
            "commands, every setting to add and where its value comes from, and what to update after the deploy (sign-in redirect "
            "URLs, CORS, the front-end's API address, database access).")
