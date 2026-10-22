"""Tenant-scoped GitHub fix PRs and CI-gated merges for portal incidents."""
from __future__ import annotations

import ast
import difflib
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

import httpx
from cryptography.fernet import Fernet, InvalidToken

import portal_db
from patcher import apply_patch, generate_patch, validate_patch


class RemediationError(RuntimeError):
    """Safe remediation failure."""


def _token(ciphertext: str) -> str:
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    try:
        return Fernet(key.encode("ascii")).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeError, InvalidToken):
        raise RemediationError("Saved GitHub credential could not be decrypted") from None


def _api(client, method: str, url: str, payload=None):
    try:
        response = client.request(method, url, json=payload)
    except httpx.HTTPError:
        raise RemediationError("GitHub request failed") from None
    if response.status_code >= 400:
        raise RemediationError(f"GitHub API rejected the request (HTTP {response.status_code})")
    try:
        return response.json() if response.content else {}
    except ValueError:
        raise RemediationError("GitHub returned an unreadable response") from None


def _repo(project):
    owner, name = str(project.get("repo_owner", "")), str(project.get("repo_name", ""))
    if not owner or not name or any(x in owner + name for x in ("/", "\\", "..")):
        raise RemediationError("Project repository is invalid")
    return f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(name, safe='')}"


def submit_fix_pr(project: dict, incident: dict, diagnosis: dict,
                  files_text: str, source_files: dict[str, str]) -> dict:
    """Generate a constrained patch and open a reviewable PR; never run customer code."""
    if not (diagnosis.get("category") == "code_bug"
            and diagnosis.get("confidence") == "high"
            and diagnosis.get("still_present_in_current_code") == "yes"
            and diagnosis.get("safe_to_auto_fix") is True):
        raise RemediationError("Diagnosis did not meet automatic-fix safety checks")
    if not source_files:
        raise RemediationError("No eligible Python files were available for a safe patch")

    with tempfile.TemporaryDirectory(prefix="incident-agent-") as tmp:
        root = Path(tmp).resolve()
        for relative, text in source_files.items():
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        patch = generate_patch(
            repo_folder=root, incident_message=incident.get("message", ""),
            traceback=incident.get("traceback", ""),
            root_cause=diagnosis.get("root_cause", ""),
            recommended_fix=diagnosis.get("recommended_fix", ""),
            files_text=files_text,
        )
        valid, reason = validate_patch(root, patch)
        if not valid:
            raise RemediationError(f"Generated patch rejected: {reason}")
        original = (root / patch["file_path"]).read_text(encoding="utf-8")
        changed = apply_patch(root, patch)
        try:
            ast.parse(changed, filename=patch["file_path"])
        except SyntaxError:
            raise RemediationError("Generated patch did not parse as Python") from None
        diff = "".join(difflib.unified_diff(
            original.splitlines(keepends=True), changed.splitlines(keepends=True),
            fromfile=f"a/{patch['file_path']}", tofile=f"b/{patch['file_path']}"))
        if not diff:
            raise RemediationError("Generated patch did not change the source file")

    token = _token(project.get("github_token_ciphertext", ""))
    api = _repo(project)
    owner = str(project["repo_owner"])
    base = str(project.get("branch", "main"))
    incident_id = str(incident["incident_id"])
    branch = f"agent-daemon/incident-{incident_id.replace('-', '')[:16]}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Agent-Daemon-Portal"}
    try:
        with httpx.Client(headers=headers, timeout=httpx.Timeout(25, connect=8),
                          follow_redirects=False) as client:
            existing = _api(client, "GET",
                f"{api}/pulls?state=open&head={quote(owner + ':' + branch, safe='')}")
            if existing:
                pr = existing[0]
            else:
                ref = _api(client, "GET", f"{api}/git/ref/heads/{quote(base, safe='/')}")
                base_sha = str(ref.get("object", {}).get("sha", ""))
                if not base_sha:
                    raise RemediationError("Could not read the selected repository branch")
                commit = _api(client, "GET", f"{api}/git/commits/{quote(base_sha, safe='')}")
                base_tree = str(commit.get("tree", {}).get("sha", ""))
                if not base_tree:
                    raise RemediationError("Could not read the repository tree")
                blob = _api(client, "POST", f"{api}/git/blobs",
                            {"content": changed, "encoding": "utf-8"})
                tree = _api(client, "POST", f"{api}/git/trees", {"base_tree": base_tree,
                    "tree": [{"path": patch["file_path"], "mode": "100644",
                              "type": "blob", "sha": blob.get("sha")}]})
                commit = _api(client, "POST", f"{api}/git/commits", {
                    "message": f"fix: incident {incident_id[:8]}",
                    "tree": tree.get("sha"), "parents": [base_sha]})
                try:
                    _api(client, "POST", f"{api}/git/refs",
                         {"ref": f"refs/heads/{branch}", "sha": commit.get("sha")})
                except RemediationError:
                    _api(client, "GET", f"{api}/git/ref/heads/{quote(branch, safe='/')}")
                pr = _api(client, "POST", f"{api}/pulls", {
                    "title": f"fix: incident {incident_id[:8]}",
                    "head": branch, "base": base,
                    "body": ("## Agent Daemon incident fix\n\n"
                        f"- Incident: {incident_id}\n"
                        f"- Root cause: {str(diagnosis.get('root_cause', ''))[:1000]}\n"
                        f"- Proposed change: {str(patch.get('explanation', ''))[:500]}\n\n"
                        "One Python source file is changed. Customer code and tests were not run. "
                        "Review the diff and ensure repository CI checks pass.")})
            return {"url": pr.get("html_url", ""), "number": pr.get("number"),
                    "branch": branch, "path": patch["file_path"], "diff": diff,
                    "ci_status": "pending"}
    finally:
        token = ""
        headers["Authorization"] = ""


def _check_status(client, api: str, sha: str) -> str:
    checks = _api(client, "GET", f"{api}/commits/{quote(sha, safe='')}/check-runs?per_page=100")
    status = _api(client, "GET", f"{api}/commits/{quote(sha, safe='')}/status")
    runs, states = checks.get("check_runs") or [], status.get("statuses") or []
    if not runs and not states:
        return "no_checks"
    if any(run.get("status") != "completed" for run in runs) or any(x.get("state") == "pending" for x in states):
        return "pending"
    if any(run.get("conclusion") not in ("success", "neutral", "skipped") for run in runs):
        return "failed"
    if any(x.get("state") != "success" for x in states):
        return "failed"
    return "success"


def process_auto_merges() -> int:
    """Merge only open auto-mode PRs with at least one passing, completed CI check."""
    candidates = portal_db.list_auto_prs()
    for incident in candidates:
        token, headers = "", {}
        try:
            token = _token(incident.get("github_token_ciphertext", ""))
            api = _repo(incident)
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                       "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Agent-Daemon-Portal"}
            number = int(incident["pr_number"])
            with httpx.Client(headers=headers, timeout=httpx.Timeout(20, connect=8),
                              follow_redirects=False) as client:
                pr = _api(client, "GET", f"{api}/pulls/{number}")
                if pr.get("state") != "open":
                    continue
                head_sha = str(pr.get("head", {}).get("sha", ""))
                if not head_sha:
                    continue
                status = _check_status(client, api, head_sha)
                portal_db.update_portal_pr_status(incident["incident_id"], status)
                if status != "success":
                    continue
                latest = _api(client, "GET", f"{api}/pulls/{number}")
                if latest.get("state") != "open" or latest.get("head", {}).get("sha") != head_sha:
                    portal_db.update_portal_pr_status(incident["incident_id"], "pending")
                    continue
                merged = _api(client, "PUT", f"{api}/pulls/{number}/merge",
                              {"merge_method": "squash", "commit_title": f"Merge incident fix #{number}"})
                if merged.get("merged") is True:
                    portal_db.update_portal_pr_status(incident["incident_id"], "merged", merged=True)
        except Exception:
            portal_db.audit(incident["project_id"], "auto_merge_deferred",
                {"incident_id": incident["incident_id"], "reason": "GitHub check or merge request failed"})
        finally:
            token = ""
            headers["Authorization"] = ""
    return len(candidates)
