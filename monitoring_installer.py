"""Open a least-change monitoring pull request in a customer's repository."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


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
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise GitHubInstallError(f"GitHub API returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GitHubInstallError("Could not reach GitHub to create the installation pull request.") from exc


def _blob(api: str, token: str, content: str) -> str:
    return _request(api + "/git/blobs", token, "POST", {
        "content": content,
        "encoding": "utf-8",
    })["sha"]


def open_monitoring_pr(*, owner: str, repo: str, base_branch: str,
                       project_id: str, token: str):
    """Create a new branch and PR containing an opt-in Python logging hook.

    The PR never includes an ingest secret. The customer configures that secret
    in their own deployment environment after reviewing/merging the PR.
    """
    owner_q = urllib.parse.quote(owner, safe="")
    repo_q = urllib.parse.quote(repo, safe="")
    api = f"https://api.github.com/repos/{owner_q}/{repo_q}"
    ref = urllib.parse.quote(base_branch, safe="")
    base = _request(f"{api}/git/ref/heads/{ref}", token)["object"]["sha"]
    base_commit = _request(f"{api}/git/commits/{base}", token)
    branch = f"agent-daemon/install-{project_id.replace('-', '')[:12]}"
    module = '''"""Opt-in error reporting for Agent Daemon.\n\nCall report_exception() from an exception handler. No global hooks are installed.\n"""\nimport json\nimport os\nimport urllib.request\n\n\ndef report_exception(exc, *, context=None):\n    endpoint = os.environ.get("INCIDENT_AGENT_INGEST_URL", "").strip()\n    key = os.environ.get("INCIDENT_AGENT_INGEST_KEY", "").strip()\n    if not endpoint or not key:\n        return False\n    payload = {\n        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),\n        "level": "ERROR",\n        "message": str(exc)[:4000],\n        "traceback": "".join(__import__("traceback").format_exception(type(exc), exc, exc.__traceback__))[-12000:],\n        "context": context or {},\n    }\n    request = urllib.request.Request(\n        endpoint, data=json.dumps(payload).encode("utf-8"),\n        headers={"Content-Type": "application/json", "X-Ingest-Key": key}, method="POST",\n    )\n    try:\n        with urllib.request.urlopen(request, timeout=2):\n            return True\n    except Exception:\n        # Monitoring must not replace or delay the application's error handling.\n        return False\n'''
    guide = f'''# Agent Daemon monitoring setup\n\nThis pull request adds an explicit, opt-in Python error reporting helper. It does not install a global exception hook or change your application behavior.\n\n1. Review `incident_agent_monitor.py` and merge this pull request when ready.\n2. Add `INCIDENT_AGENT_INGEST_URL` using the `/ingest` URL shown by your Agent Daemon deployment.\n3. Add `INCIDENT_AGENT_INGEST_KEY` using the one-time project key from the Agent Daemon project setup. Do not commit either value.\n4. In an exception handler, call `report_exception(exc, context={{"route": request.path}})` and then keep your existing handling.\n5. Deploy and confirm the project receives a heartbeat/event.\n\nThe project identifier for this setup is `{project_id}`.\n'''
    entries = []
    for path, content in (("incident_agent_monitor.py", module), ("INCIDENT_AGENT_SETUP.md", guide)):
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": _blob(api, token, content)})
    tree = _request(api + "/git/trees", token, "POST", {
        "base_tree": base_commit["tree"]["sha"], "tree": entries,
    })["sha"]
    commit = _request(api + "/git/commits", token, "POST", {
        "message": "chore: add opt-in Agent Daemon monitoring helper",
        "tree": tree,
        "parents": [base],
    })["sha"]
    _request(api + "/git/refs", token, "POST", {
        "ref": f"refs/heads/{branch}", "sha": commit,
    })
    try:
        pr = _request(api + "/pulls", token, "POST", {
            "title": "Add opt-in Agent Daemon error monitoring",
            "head": branch,
            "base": base_branch,
            "body": "Adds a small, opt-in helper for forwarding handled Python exceptions to Agent Daemon. No credentials are included; configure them as deployment secrets after reviewing this PR.",
        })
    except GitHubInstallError as exc:
        if "already exists" not in str(exc).lower():
            raise
        query = urllib.parse.urlencode({"head": f"{owner}:{branch}", "state": "open"})
        existing = _request(api + f"/pulls?{query}", token)
        if not existing:
            raise
        pr = existing[0]
    return {"url": pr["html_url"], "number": pr["number"], "branch": branch}
