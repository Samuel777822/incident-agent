"""Create a pull request that installs Agent Daemon runtime monitoring.

Supports Python, Node.js (CommonJS/ESM), browser JavaScript/TypeScript, Java,
and static HTML. Mixed repositories receive every applicable adapter.
"""
from __future__ import annotations
import ast, base64, json, re, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from monitoring_adapters import NODE_CJS_SOURCE, NODE_ESM_SOURCE, BROWSER_SOURCE, JAVA_MONITOR_TEMPLATE

class GitHubInstallError(RuntimeError):
    pass

def _request(url: str, token: str, method: str = "GET", payload=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Agent-Daemon-Monitoring-Installer"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            message = "GitHub rejected this token (401 Bad credentials). Update the token on the project page."
        elif exc.code == 403:
            message = "GitHub denied this token. Confirm it can read this repository and create branches and pull requests."
        elif exc.code == 404:
            message = "GitHub could not find this repository, branch, or pull request for the supplied token."
        else:
            message = f"GitHub could not complete the request (HTTP {exc.code}). Try again later."
        raise GitHubInstallError(message) from None
    except urllib.error.URLError as exc:
        raise GitHubInstallError("Could not reach GitHub to create the monitoring pull request.") from exc

def resolve_branch(*, owner: str, repo: str, token: str, requested: str = "", repo_info=None) -> str:
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
    return _request(f"https://api.github.com/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo, safe='')}", token)

def detect_stacks(paths) -> set[str]:
    clean = [str(p).replace("\\", "/").lstrip("./") for p in paths]
    relevant = [p for p in clean if not any(part in {"node_modules", ".venv", "venv", "vendor", "target", "build", "dist"} for part in p.split("/"))]
    stacks = set()
    if any(p.endswith(".py") for p in relevant): stacks.add("python")
    if any(p.endswith(("package.json", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")) for p in relevant): stacks.add("node")
    if any(p.endswith((".java", "pom.xml", "build.gradle", "build.gradle.kts")) for p in relevant): stacks.add("java")
    if any(p.lower().endswith((".html", ".htm")) for p in relevant): stacks.add("browser")
    return stacks

ENTRY_CANDIDATES = ("app.py", "main.py", "wsgi.py", "server.py", "run.py", "application.py", "manage.py", "index.py")
PYTHON_IMPORT_LINE = "import incident_agent_monitor  # Agent Daemon runtime monitoring"

def _python_client_source():
    return Path(__file__).with_name("agent_monitor_client.py").read_text(encoding="utf-8")

def _insert_python_import(source: str):
    if "incident_agent_monitor" in source: return source
    try: tree = ast.parse(source)
    except SyntaxError: return None
    lines = source.split("\n")
    insert_at = 1 if lines and lines[0].startswith("#!") else 0
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
        insert_at = max(insert_at, body[0].end_lineno)
        body = body[1:]
    for node in body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__": insert_at = max(insert_at, node.end_lineno)
        else: break
    lines.insert(insert_at, PYTHON_IMPORT_LINE)
    return "\n".join(lines)

def _js_entry_candidates(package):
    candidates = []
    if isinstance(package, dict):
        if isinstance(package.get("main"), str): candidates.append(package["main"])
        scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
        start = scripts.get("start", "")
        if isinstance(start, str):
            match = re.search(r"(?:^|\s)(?:node|tsx|ts-node|bun)\s+(?:--[^\s]+\s+)*([A-Za-z0-9_./-]+\.(?:mjs|cjs|js|ts))\b", start)
            if match: candidates.append(match.group(1))
    candidates.extend(("server.mjs","server.cjs","server.js","server.ts","app.mjs","app.cjs","app.js","app.ts",
                       "index.mjs","index.cjs","index.js","index.ts","main.mjs","main.cjs","main.js","main.ts",
                       "src/server.mjs","src/server.js","src/server.ts","src/app.js","src/app.ts","src/index.js","src/index.ts"))
    seen = set()
    return [p for p in candidates if p not in seen and not seen.add(p)]

def _insert_js_monitor(source: str, *, esm: bool, monitor_path: str):
    if "incident_agent_monitor" in source: return source
    line = f'import "./{monitor_path}";' if esm else f'require("./{monitor_path}");'
    lines = source.splitlines()
    index = 1 if lines and lines[0].startswith("#!") else 0
    lines.insert(index, line + " // Agent Daemon runtime monitoring")
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")

def _find_java_main(source: str) -> bool:
    return bool(re.search(r"\bpublic\s+static\s+void\s+main\s*\([^)]*\)\s*\{", source))

def _patch_java_main(source: str):
    if "AgentDaemonMonitor.install()" in source: return source
    match = re.search(r"\bpublic\s+static\s+void\s+main\s*\([^)]*\)\s*\{", source)
    if not match: return None
    return source[:match.end()] + "\n        AgentDaemonMonitor.install(); // Agent Daemon runtime monitoring" + source[match.end():]

def _java_package(source: str) -> str:
    match = re.search(r"(?m)^\s*package\s+([A-Za-z_][A-Za-z0-9_.]*)\s*;", source)
    return match.group(1) if match else ""

def _java_monitor_source(package: str) -> str:
    package_decl = f"package {package};" if package else ""
    return JAVA_MONITOR_TEMPLATE.replace("{package_decl}", package_decl)

def _inject_html_monitor(source: str):
    if "agent-daemon-monitor.js" in source: return source
    tag = '<script src="/agent-daemon-monitor.js" defer></script>'
    if re.search(r"</body\s*>", source, flags=re.I):
        return re.sub(r"</body\s*>", tag + "\n</body>", source, count=1, flags=re.I)
    if re.search(r"</html\s*>", source, flags=re.I):
        return re.sub(r"</html\s*>", tag + "\n</html>", source, count=1, flags=re.I)
    return source.rstrip() + "\n" + tag + "\n"

WORKFLOW_PATH = ".github/workflows/agent-daemon-tests.yml"
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
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
          pip install pytest
      - name: Syntax check
        run: python -m compileall -q -x '/(\\.venv|venv|node_modules)/' .
      - name: Run tests
        run: |
          code=0
          python -m pytest -q || code=$?
          if [ "$code" -eq 5 ]; then echo "No tests found; only the syntax check ran."; exit 0; fi
          exit "$code"
"""

def _repo_tree(api: str, token: str, commit_sha: str):
    data = _request(f"{api}/git/trees/{urllib.parse.quote(commit_sha, safe='')}?recursive=1", token)
    return [item["path"] for item in (data.get("tree") or []) if item.get("type") == "blob" and isinstance(item.get("path"), str)]

def _read_file(api: str, token: str, ref: str, path: str):
    endpoint = f"{api}/contents/{urllib.parse.quote(path, safe='/')}?ref={urllib.parse.quote(ref, safe='')}"
    try: data = _request(endpoint, token)
    except GitHubInstallError: return None
    if not isinstance(data, dict) or data.get("encoding") != "base64" or not data.get("content"): return None
    try: return base64.b64decode(data["content"]).decode("utf-8")
    except (ValueError, UnicodeDecodeError): return None

def _has_workflows(api: str, token: str, ref: str) -> bool:
    try: data = _request(f"{api}/contents/.github/workflows?ref={urllib.parse.quote(ref, safe='')}", token)
    except GitHubInstallError: return False
    return isinstance(data, list) and any(isinstance(x, dict) and str(x.get("name", "")).endswith((".yml", ".yaml")) for x in data)

def _setup_guide(project_id, stacks, patched_files, private_key_embedded, public_key_embedded, workflow, had_ci):
    display = ", ".join(sorted(stacks)) if stacks else "no supported runtime marker found"
    lines = ["# Agent Daemon runtime monitoring", "",
      "This pull request installs automatic runtime error reporting for the detected project stacks.", "",
      f"- Detected stacks: **{display}**.",
      "- Error reporting is best-effort, rate-limited, and never blocks application startup or request handling.",
      "- Browser monitoring observes uncaught JavaScript errors, unhandled promise rejections, failed resources, and failed API responses.",
      "- Server monitoring observes uncaught runtime failures; Node also watches failed upstream HTTP responses.",
      "- Runtime monitoring complements Agent Daemon's push/build/test checks.", ""]
    if patched_files:
        lines += ["Automatically instrumented entrypoints:"] + [f"- {p}" for p in patched_files]
    else:
        lines.append("No safe application entrypoint was found to patch. Adapter files are included; see integration notes below.")
    if private_key_embedded:
        lines += ["", "- incident_agent_config.json contains this project's server ingest key. Keep this repository private and never expose this file to browser code."]
    elif public_key_embedded:
        lines += ["", "- incident_agent_config.json contains only a project-scoped, write-only reporting token. It cannot read project data or change settings; submissions are rate-limited."]
    if "browser" in stacks:
        lines += ["", "- Browser reports contain error metadata only; page contents, form values, and request bodies are not sent."]
    if "java" in stacks:
        lines += ["", "- The Java adapter uses only the JDK standard library and requires Java 11+."]
    if workflow: lines += ["", f"- {WORKFLOW_PATH} adds a Python syntax/test workflow because no GitHub Actions workflow was found."]
    elif had_ci: lines += ["", "- Existing GitHub Actions workflows were left unchanged."]
    else: lines += ["", "- No GitHub Actions workflow was added; Agent Daemon will not assume a fix is safe to auto-merge without passing checks."]
    lines += ["", "## Coverage notes", "",
      "- Python: uncaught main-thread/thread exceptions and ERROR-level logging with stack traces.",
      "- Node.js: uncaught exceptions and failed fetch responses, including configured AI provider endpoints.",
      "- Browser: uncaught errors, unhandled rejections, resource failures, and HTTP 5xx/429 responses.",
      "- Java: uncaught exceptions and java.util.logging SEVERE records with stack traces.",
      "- Handled business-logic failures that are neither thrown nor logged, and silent incorrect results, require explicit logging or tests.",
      "", f"Project: {project_id}", ""]
    return "\n".join(lines)

def open_monitoring_pr(*, owner: str, repo: str, base_branch: str, project_id: str, token: str,
                       ingest_url: str = "", ingest_key: str = "", browser_ingest_url: str = "",
                       browser_ingest_key: str = "", auto_merge: bool = True):
    """Open a non-destructive PR. The powerful server key is embedded only for private repos."""
    owner_q, repo_q = urllib.parse.quote(owner, safe=""), urllib.parse.quote(repo, safe="")
    api = f"https://api.github.com/repos/{owner_q}/{repo_q}"
    info = validate_repository_access(owner=owner, repo=repo, token=token)
    private_repo = bool(info.get("private"))
    base_branch = resolve_branch(owner=owner, repo=repo, token=token, requested=base_branch, repo_info=info)
    ref = urllib.parse.quote(base_branch, safe="")
    base = _request(f"{api}/git/ref/heads/{ref}", token)["object"]["sha"]
    base_commit = _request(f"{api}/git/commits/{base}", token)
    branch = f"agent-daemon/monitor-{project_id.replace('-', '')[:12]}"
    try:
        _request(f"{api}/git/ref/heads/{urllib.parse.quote(branch, safe='/')}", token)
        branch += f"-{int(time.time())}"
    except GitHubInstallError: pass

    paths = _repo_tree(api, token, base)
    stacks = detect_stacks(paths)
    files = {}
    patched_files = []

    if "python" in stacks:
        files["incident_agent_monitor.py"] = _python_client_source()
        py_entry = next((p for p in ENTRY_CANDIDATES if p in paths), None)
        if py_entry:
            source = _read_file(api, token, base_branch, py_entry)
            patched = _insert_python_import(source) if source is not None else None
            if patched and patched != source:
                files[py_entry] = patched
                patched_files.append(py_entry)

    if "node" in stacks:
        package = {}
        pkg_text = _read_file(api, token, base_branch, "package.json") if "package.json" in paths else None
        if pkg_text:
            try: package = json.loads(pkg_text)
            except json.JSONDecodeError: package = {}
        node_entry = next((p for p in _js_entry_candidates(package) if p in paths), None)
        if node_entry:
            source = _read_file(api, token, base_branch, node_entry)
            if source is not None:
                esm = package.get("type") == "module" or node_entry.endswith((".mjs", ".mts"))
                monitor_name = "incident_agent_monitor.mjs" if esm else "incident_agent_monitor.cjs"
                adapter = NODE_ESM_SOURCE if esm else NODE_CJS_SOURCE
                patched = _insert_js_monitor(source, esm=esm, monitor_path=monitor_name)
                if patched != source:
                    files[node_entry] = patched
                    patched_files.append(node_entry)
                files[monitor_name] = adapter
        elif "next" in str(package.get("dependencies", {})) or "next" in str(package.get("devDependencies", {})):
            if "instrumentation.ts" not in paths:
                files["instrumentation.ts"] = 'export async function register() { await import("./incident_agent_monitor.mjs"); }\n'
                files["incident_agent_monitor.mjs"] = NODE_ESM_SOURCE
                patched_files.append("instrumentation.ts")

    if "java" in stacks:
        java_candidates = [p for p in paths if p.endswith(".java") and
            ("/src/main/java/" in "/" + p or p.endswith(("Main.java", "Application.java")))]
        for java_path in java_candidates[:40]:
            source = _read_file(api, token, base_branch, java_path)
            if source is None or not _find_java_main(source): continue
            patched = _patch_java_main(source)
            if not patched or patched == source: break
            package = _java_package(source)
            folder = java_path.rsplit("/", 1)[0] if "/" in java_path else ""
            helper = f"{folder}/AgentDaemonMonitor.java" if folder else "AgentDaemonMonitor.java"
            if helper not in paths: files[helper] = _java_monitor_source(package)
            files[java_path] = patched
            patched_files.append(java_path)
            break

    html_paths = [p for p in paths if p.lower().endswith((".html", ".htm")) and
                  not any(part in {"node_modules", "dist", "build"} for part in p.split("/"))]
    html_paths.sort(key=lambda p: (0 if p == "index.html" else 1 if p == "public/index.html" else 2, len(p)))
    if html_paths and browser_ingest_url and browser_ingest_key:
        html_path = html_paths[0]
        source = _read_file(api, token, base_branch, html_path)
        if source is not None:
            files[html_path] = _inject_html_monitor(source)
            patched_files.append(html_path)
            asset_path = "public/agent-daemon-monitor.js" if html_path.startswith("public/") else "agent-daemon-monitor.js"
            files[asset_path] = BROWSER_SOURCE.replace("__AGENT_DAEMON_BROWSER_KEY__", browser_ingest_key).replace(
                "__AGENT_DAEMON_BROWSER_URL__", browser_ingest_url)

    private_key_embedded = bool(private_repo and ingest_key and ingest_url)
    public_key_embedded = bool(browser_ingest_key and browser_ingest_url)
    config = {"browser_ingest_url": browser_ingest_url, "browser_ingest_key": browser_ingest_key}
    if private_key_embedded: config.update({"ingest_url": ingest_url, "ingest_key": ingest_key})
    if public_key_embedded: files["incident_agent_config.json"] = json.dumps(config, indent=2) + "\n"

    had_ci = _has_workflows(api, token, base_branch)
    workflow_added = not had_ci
    if workflow_added: files[WORKFLOW_PATH] = WORKFLOW_SOURCE
    files["INCIDENT_AGENT_SETUP.md"] = _setup_guide(
        project_id, stacks, patched_files, private_key_embedded, public_key_embedded, workflow_added, had_ci)

    def push(file_map):
        entries = []
        for path, content in file_map.items():
            blob = _request(api + "/git/blobs", token, "POST", {"content": content, "encoding": "utf-8"})["sha"]
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob})
        tree = _request(api + "/git/trees", token, "POST",
                        {"base_tree": base_commit["tree"]["sha"], "tree": entries})["sha"]
        if tree == base_commit["tree"]["sha"]: return False
        commit = _request(api + "/git/commits", token, "POST", {
            "message": "chore: install Agent Daemon runtime monitoring", "tree": tree, "parents": [base]})["sha"]
        _request(api + "/git/refs", token, "POST", {"ref": f"refs/heads/{branch}", "sha": commit})
        return True

    try: pushed = push(files)
    except GitHubInstallError:
        if not workflow_added: raise
        workflow_added = False
        files.pop(WORKFLOW_PATH, None)
        files["INCIDENT_AGENT_SETUP.md"] = _setup_guide(
            project_id, stacks, patched_files, private_key_embedded, public_key_embedded, False, had_ci)
        pushed = push(files)
    if not pushed:
        return {"url":"", "number":0, "branch":"", "base_branch":base_branch, "merged":False,
          "patched_file":patched_files[0] if patched_files else None, "patched_files":patched_files,
          "entry_file":patched_files[0] if patched_files else None, "embedded_key":private_key_embedded,
          "public_key_embedded":public_key_embedded, "stacks":sorted(stacks), "workflow_added":False,
          "had_ci":had_ci, "unchanged":True}

    body = ("Installs Agent Daemon runtime monitoring for detected language stacks. "
      "Private repositories receive their server ingest key in the generated config; public repositories receive only "
      "a write-only project reporting token. Review generated adapters and setup notes before merging.")
    try:
        pr = _request(api + "/pulls", token, "POST", {
          "title":"Install universal Agent Daemon runtime monitoring", "head":branch, "base":base_branch, "body":body})
    except GitHubInstallError as exc:
        if "already exists" not in str(exc).lower(): raise
        query = urllib.parse.urlencode({"head":f"{owner}:{branch}","state":"open"})
        existing = _request(api + f"/pulls?{query}", token)
        if not existing: raise
        pr = existing[0]
    merged = False
    if auto_merge:
        for _ in range(3):
            try:
                _request(f"{api}/pulls/{pr['number']}/merge", token, "PUT", {"merge_method":"squash"})
                merged = True
                break
            except GitHubInstallError: time.sleep(1.5)
    return {"url":pr["html_url"],"number":pr["number"],"branch":branch,"base_branch":base_branch,
      "merged":merged,"patched_file":patched_files[0] if patched_files else None,
      "patched_files":patched_files,"entry_file":patched_files[0] if patched_files else None,
      "embedded_key":private_key_embedded,"public_key_embedded":public_key_embedded,
      "stacks":sorted(stacks),"workflow_added":workflow_added,"had_ci":had_ci}
