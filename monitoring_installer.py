"""Install Agent Daemon monitoring into a customer's repository, for every language in it, with no manual steps.

How it works (the same pattern as the push guard: one commit on a branch, one pull request, merged when GitHub allows):
  1. Safety gate: the repository must be PRIVATE. A public repository gets nothing committed (PublicRepoError), because the
     monitor's connection details would be readable by anyone.
  2. Detect every part of the repo from its file list: Python (Flask, FastAPI, Django, plain), Node (Express, Next.js server,
     plain Node, TypeScript), browser front-ends (plain HTML/JS, React with Vite or Create React App, Next.js client) and
     mixed repos (each part gets its own monitor).
  3. Commit the right monitor file(s) next to each part and wire them in: one import line in the Python entry file,
     `node -r` in the start script (or one require line), a <script> tag as the first script of each HTML page,
     instrumentation files for Next.js.
  4. Every monitor checks in every 30 seconds and reports errors to /ingest with a project-scoped key that can only
     send events for this one project. Our own admin or master secrets are never written into a repository.
"""

from __future__ import annotations

import ast
import base64
import json
import posixpath
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class GitHubInstallError(RuntimeError):
    pass


class PublicRepoError(GitHubInstallError):
    """The repository is public: nothing may be committed to it (the monitor's connection details would be exposed)."""


def _request(url: str, token: str, method: str = "GET", payload=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Agent-Daemon-Monitoring-Installer",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            message = "GitHub rejected this token (401 Bad credentials). Create or regenerate a token, then update it on the project page."
        elif exc.code == 403:
            message = "GitHub denied this token. Confirm it is allowed to access this repository and can create branches and pull requests."
        elif exc.code == 404:
            if "/git/ref/heads/" in url or "/branches/" in url:
                what = "branch"
            elif "/pulls" in url:
                what = "pull request"
            else:
                what = "repository"
            message = (f"GitHub could not find the {what} for this token. "
                       "Check the owner/repository name, the branch name, and that the token has access to this repository.")
        else:
            message = f"GitHub could not complete the request (HTTP {exc.code}). Try again later."
        raise GitHubInstallError(message) from None
    except urllib.error.URLError as exc:
        raise GitHubInstallError("Could not reach GitHub to create the installation pull request.") from exc


def resolve_branch(*, owner: str, repo: str, token: str, requested: str = "", repo_info=None) -> str:
    """Use the requested branch if it exists, otherwise the repository's default branch."""
    api = f"https://api.github.com/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo, safe='')}"
    requested = (requested or "").strip()
    if requested:
        try:
            _request(f"{api}/branches/{urllib.parse.quote(requested, safe='/')}", token)
            return requested
        except GitHubInstallError:
            pass
    info = repo_info or _request(api, token)
    return info.get("default_branch") or requested or "main"


def validate_repository_access(*, owner: str, repo: str, token: str) -> dict:
    """Check that a token is accepted and can see the repository. Returns GitHub's repo record (includes `private`)."""
    owner_q = urllib.parse.quote(owner, safe="")
    repo_q = urllib.parse.quote(repo, safe="")
    return _request(f"https://api.github.com/repos/{owner_q}/{repo_q}", token)


def is_private(repo_info: dict | None) -> bool:
    """Fail closed: only an explicit `private: true` from GitHub counts as private (internal repos report true as well)."""
    return bool(repo_info) and repo_info.get("private") is True


def _blob(api: str, token: str, content: str) -> str:
    return _request(api + "/git/blobs", token, "POST", {
        "content": content,
        "encoding": "utf-8",
    })["sha"]


# ======================================================================================================== monitor sources
MONITOR_DIR = Path(__file__).with_name("monitors")
PY_FILE, PY_CONFIG = "incident_agent_monitor.py", "incident_agent_config.json"
NODE_FILE, NODE_CONFIG = "incident-agent-monitor.cjs", "incident-agent-config.json"
BROWSER_FILE = "incident-agent-monitor.js"
MARKER = "incident-agent-monitor"
ENTRY_CANDIDATES = ("app.py", "main.py", "wsgi.py", "server.py", "run.py", "application.py", "manage.py", "index.py")
IMPORT_LINE = "import incident_agent_monitor  # noqa: F401  (Agent Daemon error monitoring)"
GUARDED_IMPORT = (
    "try:  # Agent Daemon error monitoring (never stops your app)\n"
    "    import incident_agent_monitor  # noqa: F401\n"
    "except ImportError:  # started from another folder: load it from next to this file\n"
    "    import os as _ad_os, runpy as _ad_runpy\n"
    "    _ad_path = _ad_os.path.join(_ad_os.path.dirname(_ad_os.path.abspath(__file__)), \"incident_agent_monitor.py\")\n"
    "    if _ad_os.path.exists(_ad_path):\n"
    "        _ad_runpy.run_path(_ad_path)")
SKIP_DIRS = {"node_modules", ".git", "venv", ".venv", "env", "__pycache__", "dist", "build", ".next", "out", "coverage",
             "vendor", "site-packages", ".vercel", ".netlify", "target", ".idea", ".vscode", ".cache", "bower_components"}
SERVER_FRAMEWORKS = ("express", "fastify", "koa", "@nestjs/core", "@hapi/hapi", "hono", "socket.io", "restify")
SPA_FRAMEWORKS = ("vite", "react-scripts", "react", "vue", "svelte", "@angular/core", "preact", "solid-js")


def _client_source() -> str:
    return Path(__file__).with_name("agent_monitor_client.py").read_text(encoding="utf-8")


def node_source() -> str:
    return (MONITOR_DIR / "node_monitor.cjs").read_text(encoding="utf-8")


def browser_source(config: dict) -> str:
    """The browser monitor with this project's (public, send-only) connection details filled in."""
    text = (MONITOR_DIR / "browser_monitor.js").read_text(encoding="utf-8")
    start, end = text.index("/*__AGENT_DAEMON_CONFIG__*/"), text.index("/*__END__*/") + len("/*__END__*/")
    return text[:start] + json.dumps(config, separators=(", ", ": ")) + text[end:]


def _insert_import(source: str, line: str = IMPORT_LINE):
    """Add the monitoring import as the first real statement. None means the file could not be parsed."""
    if "incident_agent_monitor" in source:
        return source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    lines = source.split("\n")
    insert_at = 0
    while insert_at < min(2, len(lines)) and lines[insert_at].startswith("#") and (
            lines[insert_at].startswith("#!") or "coding" in lines[insert_at]):
        insert_at += 1
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        insert_at = max(insert_at, body[0].end_lineno)
        body = body[1:]
    for node in body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            insert_at = max(insert_at, node.end_lineno)
        else:
            break
    lines.insert(insert_at, line)
    return "\n".join(lines)


def insert_js_require(source: str, statement: str):
    """Put one require/import line at the top of a JS/TS file (after a shebang, 'use strict' and leading comments)."""
    if MARKER in source:
        return source
    lines = source.split("\n")
    i = 0
    if lines and lines[0].startswith("#!"):
        i = 1
    while i < len(lines) and re.match(r"\s*(['\"])use (strict|client|server)\1;?\s*$", lines[i]):
        i += 1
    lines.insert(i, statement)
    return "\n".join(lines)


def inject_script_tag(html: str, tag: str):
    """Make the monitor the FIRST script of the page: right after <head>, else after <html>, else at the top."""
    if MARKER in html:
        return html
    for pattern in (r"<head\b[^>]*>", r"<html\b[^>]*>"):
        match = re.search(pattern, html, re.I)
        if match:
            return html[:match.end()] + "\n    " + tag + html[match.end():]
    return tag + "\n" + html


def _rel(from_dir: str, to_path: str) -> str:
    rel = posixpath.relpath(to_path, from_dir or ".")
    return rel


def _join(*parts: str) -> str:
    return "/".join(p.strip("/") for p in parts if p and p.strip("/"))


# ======================================================================================================== detection
def _visible(path: str) -> bool:
    return not (set(path.split("/")[:-1]) & SKIP_DIRS)


def _json(text) -> dict:
    try:
        data = json.loads(text or "")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _python_entry(base: str, names: set[str], read) -> str:
    """The file that starts a Python app inside `base` (Django wsgi/asgi, FastAPI/Flask app files, ...)."""
    prefix = base + "/" if base else ""
    local = {n[len(prefix):] for n in names if n.startswith(prefix)}
    if "manage.py" in local:                                          # Django: the project package's wsgi.py serves production
        for cand in sorted(local):
            if cand.count("/") == 1 and cand.endswith("/wsgi.py"):
                return prefix + cand
    for cand in ENTRY_CANDIDATES + ("asgi.py", "api/index.py", "app/main.py", "src/main.py", "src/app.py", "app/app.py",
                                    "backend/main.py", "backend/app.py"):
        if cand in local:
            if cand == "manage.py" and any(c.endswith("/wsgi.py") for c in local):
                continue
            return prefix + cand
    for cand in sorted(c for c in local if c.count("/") == 0 and c.endswith(".py")):  # any top-level file that builds a web app
        text = read(prefix + cand) or ""
        if re.search(r"\b(Flask|FastAPI|Starlette|Sanic|Quart)\s*\(|streamlit|gradio|if __name__ == ['\"]__main__['\"]", text):
            return prefix + cand
    return ""


def _node_start_entry(pkg: dict) -> tuple[str, str]:
    """('script', file) when `npm start` is `node <file>`; ('main', file) from the main field; ('', '') otherwise."""
    start = str((pkg.get("scripts") or {}).get("start", "")).strip()
    match = re.match(r"^node\s+((?:--?[\w-]+(?:=\S+)?\s+)*)([\w./@-]+\.(?:c|m)?js)\b", start)
    if match:
        return "script", match.group(2)
    match = re.match(r"^(?:nodemon|node --watch|pm2 start)\s+([\w./@-]+\.(?:c|m)?js)\b", start)
    if match:
        return "file", match.group(1)
    main = str(pkg.get("main") or "")
    if main.endswith((".js", ".cjs", ".mjs")):
        return "file", main
    return "", ""


def detect_targets(paths, read) -> list[dict]:
    """Every part of the repository that needs its own monitor.

    paths: every file path in the repo (posix, relative). read(path) -> text or None.
    Each target: {kind: python|node|browser, base, framework, entry, label}."""
    names = {p for p in paths if _visible(p)}
    targets: list[dict] = []
    handled_html: set[str] = set()
    spa_bases: set[str] = set()

    # --- Node / JavaScript / TypeScript projects (every package.json)
    for pkg_path in sorted(n for n in names if n.endswith("package.json") and n.count("/") <= 3):
        base = posixpath.dirname(pkg_path)
        pkg = _json(read(pkg_path))
        deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
        prefix = base + "/" if base else ""
        if "next" in deps:
            src = "src/" if any(n.startswith(prefix + "src/app/") or n.startswith(prefix + "src/pages/") for n in names) else ""
            version = re.search(r"(\d+)", str(deps.get("next")))
            targets.append({"kind": "node", "base": base, "framework": "next", "entry": prefix + src,
                            "label": "Next.js server", "next_major": int(version.group(1)) if version else 0})
            targets.append({"kind": "browser", "base": base, "framework": "next", "entry": prefix + src,
                            "label": "Next.js pages in the browser", "next_major": int(version.group(1)) if version else 0})
            spa_bases.add(base)
            continue
        spa = next((f for f in SPA_FRAMEWORKS if f in deps), "")
        index = (prefix + "index.html") if (prefix + "index.html") in names else (
            (prefix + "public/index.html") if (prefix + "public/index.html") in names else "")
        if spa and index:
            flavour = "cra" if "react-scripts" in deps else ("vite" if "vite" in deps else "spa")
            targets.append({"kind": "browser", "base": base, "framework": flavour, "entry": index,
                            "label": {"cra": "React app (Create React App)", "vite": "Front-end (Vite)"}.get(flavour, "Front-end")})
            handled_html.add(index)
            spa_bases.add(base)
        server = next((f for f in SERVER_FRAMEWORKS if f in deps), "")
        how, entry = _node_start_entry(pkg)
        if how == "file" and _join(base, entry) not in names:   # e.g. npm init's default "main": "index.js" that does not exist
            how, entry = "", ""
        if not entry:
            for cand in ("server.js", "index.js", "app.js", "src/server.js", "src/index.js", "src/app.js", "server.mjs", "index.mjs",
                         "api/index.js", "server/index.js"):
                if prefix + cand in names:
                    how, entry = "file", cand
                    break
        is_server = bool(server) or (bool(entry) and not spa)
        if is_server:
            module = pkg.get("type") == "module"
            targets.append({"kind": "node", "base": base, "framework": server or "node", "entry": _join(base, entry) if entry else "",
                            "how": how, "esm": module, "label": {"express": "Express server", "fastify": "Fastify server",
                                                                  "@nestjs/core": "NestJS server"}.get(server, "Node.js server")})

    # --- Python projects (one target per project folder; a nested folder is skipped when a parent already has an app)
    py_bases = set()
    for n in names:
        top = posixpath.basename(n)
        if top in ("requirements.txt", "pyproject.toml", "Pipfile", "setup.py", "manage.py") and n.count("/") <= 2:
            py_bases.add(posixpath.dirname(n))
        elif n.endswith(".py") and n.count("/") == 0:
            py_bases.add("")
    found = []
    for base in sorted(py_bases, key=lambda b: (b.count("/"), b)):
        if any(f["entry"] and (not f["base"] or base.startswith(f["base"] + "/")) for f in found):
            continue
        found.append({"base": base, "entry": _python_entry(base, names, read)})
    if len(found) > 1:
        found = [f for f in found if f["entry"]] or found[:1]
    for f in found:
        base, entry = f["base"], f["entry"]
        prefix = base + "/" if base else ""
        text = read(entry) if entry else ""
        framework = ("django" if (prefix + "manage.py") in names else "fastapi" if "FastAPI" in (text or "") else
                     "flask" if "Flask" in (text or "") else "python")
        targets.append({"kind": "python", "base": base, "framework": framework, "entry": entry,
                        "package": bool(entry) and _join(posixpath.dirname(entry), "__init__.py") in names,
                        "label": {"django": "Django app", "fastapi": "FastAPI app", "flask": "Flask app"}.get(framework, "Python app")})
        templates = sorted(n for n in names if n.startswith(prefix + "templates/") and n.endswith(".html"))
        if framework == "flask" and templates:
            targets.append({"kind": "browser", "base": base, "framework": "flask-templates", "entry": prefix + "templates/",
                            "label": "Flask pages in the browser", "pages": templates})
            handled_html.update(templates)

    # --- plain HTML/CSS/JS pages that no framework serves
    loose = sorted((n for n in names if n.lower().endswith((".html", ".htm")) and n not in handled_html
                    and "templates" not in n.split("/")[:-1]
                    and not any(n.startswith(b + "/") or not b for b in spa_bases)), key=lambda n: (n.count("/"), n))
    if loose:
        targets.append({"kind": "browser", "base": "", "framework": "static", "entry": loose[0], "label": "Web pages (HTML/JS)",
                        "pages": loose[:30]})
    return targets


# ======================================================================================================== planning the commit
def plan_install(targets: list[dict], read, *, ingest_url: str, ingest_key: str, project_id: str) -> tuple[dict, list[dict]]:
    """Files to commit ({path: text}) and a plain-language result per target ({label, wired, how, note})."""
    files: dict[str, str] = {}
    results: list[dict] = []
    heartbeat_url = (ingest_url[:-len("/ingest")] if ingest_url.endswith("/ingest") else ingest_url.rsplit("/", 1)[0]) + "/heartbeat"
    embedded = bool(ingest_url and ingest_key)

    def server_config(component: str) -> str:
        return json.dumps({"ingest_url": ingest_url, "heartbeat_url": heartbeat_url, "ingest_key": ingest_key,
                           "project_id": project_id, "component": component}, indent=2) + "\n"

    def current(path):
        return files[path] if path in files else read(path)

    for t in targets:
        label, base = t["label"], t["base"]
        component = f"{t['kind']}:{base or '.'}"
        if t["kind"] == "python":
            entry = t["entry"]
            folder = posixpath.dirname(entry) if entry else base
            files[_join(folder, PY_FILE)] = _client_source()
            if embedded:
                files[_join(folder, PY_CONFIG)] = server_config(component)
            if not entry:
                results.append({"label": label, "kind": "python", "wired": False, "file": "",
                                "note": "We could not find the file that starts this Python app, so the monitor file was added but "
                                        "not switched on. Push guard still tests every push."})
                continue
            nested = folder != base or bool(t.get("package"))   # imported as part of a package: use the guarded import
            source = current(entry) or ""
            patched = _insert_import(source, GUARDED_IMPORT if nested else IMPORT_LINE)
            if patched is None:
                results.append({"label": label, "kind": "python", "wired": False, "file": entry,
                                "note": f"{entry} has a syntax error, so the monitor could not be switched on yet. Fix the error "
                                        "(push guard will show it) and press Install monitoring again."})
                continue
            if patched != source:
                files[entry] = patched
            results.append({"label": label, "kind": "python", "wired": True, "file": entry,
                            "how": f"one import line at the top of {entry}"})
        elif t["kind"] == "node" and t["framework"] == "next":
            folder = t["entry"].rstrip("/")          # project folder (or its src/)
            files[_join(base, NODE_FILE)] = node_source()
            if embedded:
                files[_join(base, NODE_CONFIG)] = server_config(component)
            inst_js, inst_ts = _join(folder, "instrumentation.js"), _join(folder, "instrumentation.ts")
            existing = current(inst_ts) or current(inst_js)
            rel = _rel(folder, _join(base, NODE_FILE))
            rel = rel if rel.startswith(".") else "./" + rel
            if existing is None:
                files[inst_js] = ("// Agent Daemon: start error monitoring when the Next.js server starts.\n"
                                  "export async function register() {\n"
                                  "  if (process.env.NEXT_RUNTIME === 'nodejs') {\n"
                                  f"    await import('{rel}');\n"
                                  "  }\n}\n")
                note = ("" if t.get("next_major", 15) >= 15 or not t.get("next_major") else
                        "Next.js 13/14: also set experimental.instrumentationHook = true in next.config.js.")
                results.append({"label": label, "kind": "node", "wired": True, "file": inst_js, "how": "instrumentation.js", "note": note})
            elif MARKER in existing:
                results.append({"label": label, "kind": "node", "wired": True, "file": inst_ts if current(inst_ts) else inst_js,
                                "how": "already in instrumentation"})
            else:
                results.append({"label": label, "kind": "node", "wired": False, "file": inst_ts if current(inst_ts) else inst_js,
                                "note": "This app already has its own instrumentation file, so we did not change it. "
                                        f"Add `await import('{rel}')` inside its register() function."})
        elif t["kind"] == "node":
            files[_join(base, NODE_FILE)] = node_source()
            if embedded:
                files[_join(base, NODE_CONFIG)] = server_config(component)
            pkg_path = _join(base, "package.json")
            pkg_text = current(pkg_path) or ""
            pkg = _json(pkg_text)
            start = str((pkg.get("scripts") or {}).get("start", "")).strip()
            if t.get("how") == "script" and start.startswith("node ") and MARKER not in start:
                pkg.setdefault("scripts", {})["start"] = "node -r ./" + NODE_FILE + start[len("node"):]
                indent = 2
                match = re.search(r'\n(\s+)"', pkg_text)
                if match:
                    indent = len(match.group(1).replace("\t", "  "))
                files[pkg_path] = json.dumps(pkg, indent=indent, ensure_ascii=False) + ("\n" if pkg_text.endswith("\n") else "")
                results.append({"label": label, "kind": "node", "wired": True, "file": pkg_path,
                                "how": "`npm start` now loads the monitor first (node -r)"})
            elif t.get("entry"):
                entry = t["entry"]
                source = current(entry)
                if source is None:
                    results.append({"label": label, "kind": "node", "wired": False, "file": entry,
                                    "note": f"{entry} is listed as the start file but is not in the repository."})
                    continue
                rel = _rel(posixpath.dirname(entry), _join(base, NODE_FILE))
                rel = rel if rel.startswith(".") else "./" + rel
                esm = entry.endswith(".mjs") or (t.get("esm") and not entry.endswith(".cjs"))
                line = (f"import '{rel}'; // Agent Daemon error monitoring" if esm
                        else f"require('{rel}'); // Agent Daemon error monitoring")
                files[entry] = insert_js_require(source, line)
                results.append({"label": label, "kind": "node", "wired": True, "file": entry, "how": f"one line at the top of {entry}"})
            else:
                results.append({"label": label, "kind": "node", "wired": False, "file": pkg_path,
                                "note": "We could not tell how this Node app starts (no `node <file>` start script or main file). "
                                        "Push guard still tests every push."})
        elif t["kind"] == "browser":
            cfg = {"ingestUrl": ingest_url, "heartbeatUrl": heartbeat_url, "key": ingest_key, "projectId": project_id,
                   "component": component}
            source = browser_source(cfg) if embedded else browser_source({"ingestUrl": "", "key": ""})
            fw = t["framework"]
            if fw == "next":
                folder = t["entry"].rstrip("/")
                monitor = _join(base, "incident-agent-monitor.browser.js")
                files[monitor] = source
                client_js, client_ts = _join(folder, "instrumentation-client.js"), _join(folder, "instrumentation-client.ts")
                existing = current(client_ts) or current(client_js)
                rel = _rel(folder, monitor)
                rel = rel if rel.startswith(".") else "./" + rel
                if existing is None:
                    files[client_js] = f"// Agent Daemon: watch for errors in the browser (Next.js 15.3+ loads this file first).\nimport '{rel}';\n"
                    results.append({"label": label, "kind": "browser", "wired": True, "file": client_js, "how": "instrumentation-client.js",
                                    "note": "" if t.get("next_major", 15) >= 15 else "Needs Next.js 15.3 or newer for the browser part."})
                elif MARKER in existing:
                    results.append({"label": label, "kind": "browser", "wired": True, "file": client_js, "how": "already wired"})
                else:
                    files[client_ts if current(client_ts) else client_js] = insert_js_require(existing, f"import '{rel}'; // Agent Daemon")
                    results.append({"label": label, "kind": "browser", "wired": True, "file": client_ts if current(client_ts) else client_js,
                                    "how": "one import line in instrumentation-client"})
            elif fw in ("cra", "vite", "spa"):
                index = t["entry"]
                public = _join(base, "public")
                files[_join(public, BROWSER_FILE)] = source
                src = {"cra": "%PUBLIC_URL%/", "vite": "%BASE_URL%"}.get(fw, "/") + BROWSER_FILE
                html = current(index) or ""
                files[index] = inject_script_tag(html, f'<script src="{src}"></script>')
                results.append({"label": label, "kind": "browser", "wired": True, "file": index, "how": f"a <script> tag in {index}"})
            elif fw == "flask-templates":
                static = _join(base, "static")
                files[_join(static, BROWSER_FILE)] = source
                wired = []
                for page in t.get("pages", [])[:20]:
                    html = current(page) or ""
                    if re.search(r"<head\b", html, re.I) and MARKER not in html:
                        files[page] = inject_script_tag(html, "<script src=\"{{ url_for('static', filename='" + BROWSER_FILE + "') }}\"></script>")
                        wired.append(page)
                results.append({"label": label, "kind": "browser", "wired": bool(wired), "file": ", ".join(wired[:3]),
                                "how": f"a <script> tag in {len(wired)} template(s)",
                                "note": "" if wired else "No template with a <head> section was found."})
            else:   # plain HTML pages: the monitor sits next to the first page, every page loads it as its first script
                pages = t.get("pages") or [t["entry"]]
                site = posixpath.dirname(pages[0])
                monitor = _join(site, BROWSER_FILE)
                files[monitor] = source
                wired = []
                for page in pages:
                    html = current(page)
                    if html is None or MARKER in html:
                        continue
                    files[page] = inject_script_tag(html, f'<script src="{_rel(posixpath.dirname(page), monitor)}"></script>')
                    wired.append(page)
                results.append({"label": label, "kind": "browser", "wired": True, "file": ", ".join(wired[:3]) + (" …" if len(wired) > 3 else ""),
                                "how": f"a <script> tag at the top of {len(wired)} page(s)"})
    return files, results


# ======================================================================================================== GitHub plumbing
def _find_entry_file(api: str, token: str, ref: str):
    for name in ENTRY_CANDIDATES:
        try:
            data = _request(f"{api}/contents/{urllib.parse.quote(name)}?ref={urllib.parse.quote(ref, safe='')}", token)
        except GitHubInstallError:
            continue
        if isinstance(data, dict) and data.get("encoding") == "base64" and data.get("content"):
            try:
                return name, base64.b64decode(data["content"]).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                continue
    return None, None


def _list_tree(api: str, token: str, sha: str) -> list[str]:
    """Every file path at that commit (one API call). Empty when GitHub cannot list it (then the classic probe is used)."""
    try:
        data = _request(f"{api}/git/trees/{urllib.parse.quote(sha, safe='')}?recursive=1", token)
    except GitHubInstallError:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("tree"), list):
        return []
    return [str(item.get("path")) for item in data["tree"] if item.get("type") == "blob" and item.get("path")
            and int(item.get("size") or 0) <= 400_000]


def _reader(api: str, token: str, ref: str):
    cache: dict[str, str | None] = {}

    def read(path: str):
        if path in cache:
            return cache[path]
        try:
            data = _request(f"{api}/contents/{urllib.parse.quote(path, safe='/')}?ref={urllib.parse.quote(ref, safe='')}", token)
            text = base64.b64decode(data["content"]).decode("utf-8") if isinstance(data, dict) and data.get("content") else None
        except (GitHubInstallError, ValueError, UnicodeDecodeError, KeyError, TypeError):
            text = None
        cache[path] = text
        return text
    return read


WORKFLOW_PATH = ".github/workflows/agent-daemon-tests.yml"
# Works for Python, JavaScript/TypeScript and mixed repos: each part runs only when its files exist.
# Python: syntax check always, pytest only when tests exist (exit code 5 = none collected).
# JS/TS: npm install, then the project's own build and test scripts (the npm default "no test specified" script is skipped).
WORKFLOW_SOURCE = """name: tests
on:
  pull_request:
  push:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        if: hashFiles('**/*.py') != ''
        with:
          python-version: "3.12"
      - name: Install Python dependencies
        if: hashFiles('**/*.py') != ''
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
          pip install pytest
      - name: Python syntax check
        if: hashFiles('**/*.py') != ''
        run: python -m compileall -q -x '/(\\.venv|venv|node_modules)/' .
      - name: Python tests
        if: hashFiles('**/*.py') != ''
        run: |
          code=0
          python -m pytest -q || code=$?
          if [ "$code" -eq 5 ]; then echo "No tests found; only the syntax check ran."; exit 0; fi
          exit "$code"
      - uses: actions/setup-node@v4
        if: hashFiles('**/package.json') != ''
        with:
          node-version: "20"
      - name: JavaScript / TypeScript build and tests
        if: hashFiles('**/package.json') != ''
        run: |
          for f in $(find . -maxdepth 3 -name package.json -not -path "*/node_modules/*"); do
            d=$(dirname "$f"); echo "== $d"
            (cd "$d" && (npm ci || npm install) \\
              && if node -e "process.exit(((require('./package.json').scripts||{}).build)?0:1)"; then npm run build; fi \\
              && if node -e "const t=((require('./package.json').scripts||{}).test||'');process.exit(t&&!/no test specified/.test(t)?0:1)"; then npm test; fi) || exit 1
          done
"""


def _has_workflows(api: str, token: str, ref: str) -> bool:
    """True when the repository already has at least one GitHub Actions workflow file."""
    try:
        data = _request(f"{api}/contents/.github/workflows?ref={urllib.parse.quote(ref, safe='')}", token)
    except GitHubInstallError:
        return False
    return isinstance(data, list) and any(
        isinstance(item, dict) and str(item.get("name", "")).endswith((".yml", ".yaml")) for item in data)


def _setup_guide(project_id: str, patched_file, embedded: bool, workflow: bool = False, had_ci: bool = False,
                 results: list[dict] | None = None) -> str:
    lines = ["# Agent Daemon monitoring", "",
             "This pull request was opened by Agent Daemon after you connected this repository.", "",
             "Each monitor checks in with Agent Daemon every 30 seconds and reports errors: crashes, unhandled promise rejections, "
             "logged / console errors and failed API calls (for example an AI model that was retired). "
             "It never raises into your app and uses short timeouts.", "", "## What was added", ""]
    for r in results or []:
        state = "on" if r.get("wired") else "NOT switched on yet"
        detail = r.get("how") or r.get("note") or ""
        lines.append(f"- **{r['label']}**: monitor {state}" + (f" ({detail})" if detail else "") + ".")
        if r.get("wired") and r.get("note"):
            lines.append(f"  - Note: {r['note']}")
    if not results:
        if patched_file:
            lines.append(f"- `{patched_file}` gets one added line, `{IMPORT_LINE}`, so monitoring starts with your app.")
        else:
            lines.append("- Add `import incident_agent_monitor` as the first import of your app's entry file.")
    lines.append("")
    if embedded:
        lines.append("- The monitor files hold this project's ingest URL and a project key. The key can only SEND heartbeats and error "
                     "reports for this one project; it cannot read anything. You can rotate it on your Agent Daemon project page. "
                     "Keep this repository private.")
    else:
        lines.append("- Set `INCIDENT_AGENT_INGEST_URL` and `INCIDENT_AGENT_INGEST_KEY` in your host's environment (shown on your Agent Daemon project page).")
    if workflow:
        lines.append(f"- `{WORKFLOW_PATH}` runs a syntax check, your build and your tests (pytest / npm test) on every pull request. "
                     "Agent Daemon's Auto mode merges a fix only after this check passes.")
    elif had_ci:
        lines.append("- Your repository already has GitHub Actions workflows, so none was added. Auto mode relies on them.")
    else:
        lines.append("- No GitHub Actions workflow could be added (the token needs the Workflows read and write permission). "
                     "Without a passing check, Auto mode will not merge fixes.")
    lines += ["", f"Project: `{project_id}`", ""]
    return "\n".join(lines)


def open_monitoring_pr(*, owner: str, repo: str, base_branch: str, project_id: str, token: str,
                       ingest_url: str = "", ingest_key: str = "", auto_merge: bool = True, require_private: bool = True):
    """Open (and try to merge) a PR that installs monitoring for every part of the repository with no manual steps.

    require_private (default): refuse with PublicRepoError, before anything is written, when GitHub does not say the
    repository is private. The ingest key is only ever written into private repositories.
    """
    owner_q = urllib.parse.quote(owner, safe="")
    repo_q = urllib.parse.quote(repo, safe="")
    api = f"https://api.github.com/repos/{owner_q}/{repo_q}"
    info = validate_repository_access(owner=owner, repo=repo, token=token)
    if require_private and not is_private(info):
        raise PublicRepoError("This repository is public, so nothing was installed. Make it private, then press "
                              "\"I've made it private, install now\".")
    base_branch = resolve_branch(owner=owner, repo=repo, token=token, requested=base_branch, repo_info=info)
    ref = urllib.parse.quote(base_branch, safe="")
    base = _request(f"{api}/git/ref/heads/{ref}", token)["object"]["sha"]
    base_commit = _request(f"{api}/git/commits/{base}", token)
    branch = f"agent-daemon/install-{project_id.replace('-', '')[:12]}"
    try:
        _request(f"{api}/git/ref/heads/{urllib.parse.quote(branch, safe='/')}", token)
        branch += f"-{int(time.time())}"  # an earlier install branch exists (a retry): never collide with it
    except GitHubInstallError:
        pass

    embedded = bool(ingest_key and ingest_url)
    paths = _list_tree(api, token, base)
    read = _reader(api, token, base_branch)
    if paths:
        targets = detect_targets(paths, read)
        base_files, results = plan_install(targets, read, ingest_url=ingest_url, ingest_key=ingest_key, project_id=project_id)
        python_hits = [r for r in results if r["kind"] == "python" and r.get("wired")]
        patched_file = python_hits[0]["file"] if python_hits else next((r["file"] for r in results if r.get("wired")), None)
        entry_name = patched_file or next((r["file"] for r in results if r.get("file")), None)
    else:   # the file list could not be read: the classic Python-only install
        targets, results = [], []
        base_files = {PY_FILE: _client_source()}
        if embedded:
            base_files[PY_CONFIG] = json.dumps({"ingest_url": ingest_url, "heartbeat_url": ingest_url.rsplit("/", 1)[0] + "/heartbeat",
                                                "ingest_key": ingest_key, "project_id": project_id, "component": "python:."},
                                               indent=2) + "\n"
        entry_name, entry_source = _find_entry_file(api, token, base_branch)
        patched_file = None
        if entry_name:
            patched = _insert_import(entry_source)
            if patched is not None and patched != entry_source:
                base_files[entry_name] = patched
                patched_file = entry_name
        results = [{"label": "Python app", "kind": "python", "wired": bool(patched_file or (entry_name and entry_source and "incident_agent_monitor" in entry_source)),
                    "file": entry_name or "", "how": f"one import line at the top of {entry_name}" if entry_name else "",
                    "note": "" if entry_name else "We could not find the file that starts your app."}]
    had_ci = _has_workflows(api, token, base_branch)

    def build_files(with_workflow: bool) -> dict:
        out = dict(base_files)
        if with_workflow:
            out[WORKFLOW_PATH] = WORKFLOW_SOURCE
        out["INCIDENT_AGENT_SETUP.md"] = _setup_guide(project_id, patched_file, embedded, with_workflow, had_ci, results if paths else None)
        return out

    def push(file_map: dict) -> bool:
        """Create the install branch. Returns False when it would change nothing."""
        entries = [{"path": path, "mode": "100644", "type": "blob", "sha": _blob(api, token, content)}
                   for path, content in file_map.items()]
        tree = _request(api + "/git/trees", token, "POST", {"base_tree": base_commit["tree"]["sha"], "tree": entries})["sha"]
        if tree == base_commit["tree"]["sha"]:
            return False
        commit = _request(api + "/git/commits", token, "POST", {
            "message": "chore: add Agent Daemon error monitoring", "tree": tree, "parents": [base]})["sha"]
        _request(api + "/git/refs", token, "POST", {"ref": f"refs/heads/{branch}", "sha": commit})
        return True

    summary = {"targets": results, "kinds": sorted({r["kind"] for r in results})}
    workflow_added = not had_ci
    try:
        pushed = push(build_files(workflow_added))
    except GitHubInstallError:
        if not workflow_added:
            raise
        # Most likely the token lacks the Workflows permission: still install monitoring, without the workflow.
        workflow_added = False
        pushed = push(build_files(False))
    if not pushed:  # a retry where everything is already installed and the workflow still cannot be added
        return {"url": "", "number": 0, "branch": "", "base_branch": base_branch, "merged": False,
                "patched_file": patched_file, "entry_file": entry_name, "embedded_key": embedded,
                "workflow_added": False, "had_ci": had_ci, "unchanged": True, **summary}
    body = ("Adds Agent Daemon error monitoring for every part of this repository. Merging this pull request is the only step "
            "needed: monitoring starts the next time your app deploys and checks in every 30 seconds. If your repository had no "
            "GitHub Actions workflow, one is added so Auto mode has a passing check to wait for.\n\nSee INCIDENT_AGENT_SETUP.md for what changed.")
    try:
        pr = _request(api + "/pulls", token, "POST", {
            "title": "Add Agent Daemon error monitoring", "head": branch, "base": base_branch, "body": body})
    except GitHubInstallError as exc:
        if "already exists" not in str(exc).lower():
            raise
        query = urllib.parse.urlencode({"head": f"{owner}:{branch}", "state": "open"})
        existing = _request(api + f"/pulls?{query}", token)
        if not existing:
            raise
        pr = existing[0]
    merged = False
    if auto_merge:
        for attempt in range(3):
            try:
                _request(f"{api}/pulls/{pr['number']}/merge", token, "PUT", {"merge_method": "squash"})
                merged = True
                break
            except GitHubInstallError:
                time.sleep(1.5)
    return {"url": pr["html_url"], "number": pr["number"], "branch": branch, "base_branch": base_branch, "merged": merged,
            "patched_file": patched_file, "entry_file": entry_name, "embedded_key": embedded,
            "workflow_added": workflow_added, "had_ci": had_ci, **summary}
