"""Open a least-change monitoring pull request in a customer's repository."""

from __future__ import annotations

import ast
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class GitHubInstallError(RuntimeError):
    pass


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
    """Check that a token is accepted and can see the repository. Returns GitHub's repo record."""
    owner_q = urllib.parse.quote(owner, safe="")
    repo_q = urllib.parse.quote(repo, safe="")
    return _request(f"https://api.github.com/repos/{owner_q}/{repo_q}", token)


def _blob(api: str, token: str, content: str) -> str:
    return _request(api + "/git/blobs", token, "POST", {
        "content": content,
        "encoding": "utf-8",
    })["sha"]


ENTRY_CANDIDATES = ("app.py", "main.py", "wsgi.py", "server.py", "run.py", "application.py", "manage.py", "index.py")
IMPORT_LINE = "import incident_agent_monitor  # noqa: F401  (Agent Daemon error monitoring)"


def _client_source() -> str:
    return Path(__file__).with_name("agent_monitor_client.py").read_text(encoding="utf-8")


def _insert_import(source: str):
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
    lines.insert(insert_at, IMPORT_LINE)
    return "\n".join(lines)


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


WORKFLOW_PATH = ".github/workflows/agent-daemon-tests.yml"
# Works for any Python repo: syntax check always, pytest only when tests exist (exit code 5 = none collected).
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


def _has_workflows(api: str, token: str, ref: str) -> bool:
    """True when the repository already has at least one GitHub Actions workflow file."""
    try:
        data = _request(f"{api}/contents/.github/workflows?ref={urllib.parse.quote(ref, safe='')}", token)
    except GitHubInstallError:
        return False
    return isinstance(data, list) and any(
        isinstance(item, dict) and str(item.get("name", "")).endswith((".yml", ".yaml")) for item in data)


def _setup_guide(project_id: str, patched_file, embedded: bool, workflow: bool = False, had_ci: bool = False) -> str:
    lines = ["# Agent Daemon monitoring", "",
             "This pull request was opened by Agent Daemon after you connected this repository.", "",
             "- `incident_agent_monitor.py` reports unhandled exceptions and logged errors, and sends a heartbeat every 5 minutes.",
             "- It never raises into your app and uses short timeouts.", ""]
    if patched_file:
        lines.append(f"- `{patched_file}` gets one added line, `{IMPORT_LINE}`, so monitoring starts with your app.")
    else:
        lines.append("- Add `import incident_agent_monitor` as the first import of your app's entry file.")
    if embedded:
        lines.append("- `incident_agent_config.json` holds this project's ingest URL and key. The key can only send events for this one project. Keep this repository private.")
    else:
        lines.append("- Set `INCIDENT_AGENT_INGEST_URL` and `INCIDENT_AGENT_INGEST_KEY` in your host's environment (shown on your Agent Daemon project page).")
    if workflow:
        lines.append(f"- `{WORKFLOW_PATH}` runs a syntax check and your pytest tests on every pull request. "
                     "Agent Daemon's Auto mode merges a fix only after this check passes.")
    elif had_ci:
        lines.append("- Your repository already has GitHub Actions workflows, so none was added. Auto mode relies on them.")
    else:
        lines.append("- No GitHub Actions workflow could be added (the token needs the Workflows read and write permission). "
                     "Without a passing check, Auto mode will not merge fixes.")
    lines += ["", f"Project: `{project_id}`", ""]
    return "\n".join(lines)


def open_monitoring_pr(*, owner: str, repo: str, base_branch: str, project_id: str, token: str,
                       ingest_url: str = "", ingest_key: str = "", auto_merge: bool = True):
    """Open (and try to merge) a PR that installs monitoring with no manual steps.

    When ingest_key is given it is written to incident_agent_config.json. Callers
    must only pass it for private repositories. If an entry file is found, one
    import line is added to it so monitoring starts automatically.
    """
    owner_q = urllib.parse.quote(owner, safe="")
    repo_q = urllib.parse.quote(repo, safe="")
    api = f"https://api.github.com/repos/{owner_q}/{repo_q}"
    info = validate_repository_access(owner=owner, repo=repo, token=token)
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

    base_files = {"incident_agent_monitor.py": _client_source()}
    embedded = bool(ingest_key and ingest_url)
    if embedded:
        base_files["incident_agent_config.json"] = json.dumps({"ingest_url": ingest_url, "ingest_key": ingest_key}, indent=2) + "\n"
    entry_name, entry_source = _find_entry_file(api, token, base_branch)
    patched_file = None
    if entry_name:
        patched = _insert_import(entry_source)
        if patched is not None and patched != entry_source:
            base_files[entry_name] = patched
            patched_file = entry_name
    had_ci = _has_workflows(api, token, base_branch)

    def build_files(with_workflow: bool) -> dict:
        out = dict(base_files)
        if with_workflow:
            out[WORKFLOW_PATH] = WORKFLOW_SOURCE
        out["INCIDENT_AGENT_SETUP.md"] = _setup_guide(project_id, patched_file, embedded, with_workflow, had_ci)
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
                "workflow_added": False, "had_ci": had_ci, "unchanged": True}
    body = ("Adds Agent Daemon error monitoring. Merging this pull request is the only step needed: "
            "monitoring starts the next time your app deploys. If your repository had no GitHub Actions workflow, one is "
            "added so Auto mode has a passing check to wait for.")
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
            "workflow_added": workflow_added, "had_ci": had_ci}
