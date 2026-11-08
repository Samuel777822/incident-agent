"""GitHub access for the engine: download the repo to a scratch folder and open a multi-file PR (never push to main)."""
from __future__ import annotations

import io
import os
import re
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import httpx

import portal_remediation
from portal_remediation import RemediationError, _token

_REPO_PART = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def _validate(project: dict) -> tuple[str, str, str]:
    owner, repo, branch = str(project.get("repo_owner", "")), str(project.get("repo_name", "")), str(project.get("branch", "main"))
    if not _REPO_PART.fullmatch(owner) or not _REPO_PART.fullmatch(repo):
        raise RemediationError("Repository identity is invalid")
    if not branch or len(branch) > 250 or branch.startswith("-") or ".." in branch or "\\" in branch:
        raise RemediationError("Repository branch is invalid")
    return owner, repo, branch


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Agent-Daemon-Portal"}


def safe_extract_tar(data: bytes, dest: Path, max_files: int, max_bytes: int) -> int:
    count = total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar:
            if not member.isreg():
                continue                                    # no symlinks, hardlinks, devices
            parts = member.name.replace("\\", "/").split("/")[1:]   # drop the GitHub top folder
            if not parts or ".." in parts or parts[0] == "" or ".git" in parts:
                continue
            count += 1
            total += member.size
            if count > max_files or total > max_bytes:
                raise RemediationError("Repository is too large for the sandbox")
            target = dest.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src:
                target.write_bytes(src.read())
    return count


@contextmanager
def repo_snapshot(project: dict, cfg: dict):
    """Download the branch as a tarball into a scratch dir that is deleted afterwards."""
    owner, repo, branch = _validate(project)
    token = _token(project.get("github_token_ciphertext", ""))
    url = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/tarball/{quote(branch, safe='/')}"
    sb = cfg["sandbox"]
    try:
        with httpx.Client(headers=_headers(token), timeout=httpx.Timeout(60, connect=10), follow_redirects=True) as client:
            resp = client.get(url)
    except httpx.HTTPError:
        raise RemediationError("Could not download the repository") from None
    if resp.status_code != 200:
        raise RemediationError(f"GitHub refused the repository download (HTTP {resp.status_code})")
    with tempfile.TemporaryDirectory(prefix="fx-repo-", dir=os.getenv("FIXENGINE_SCRATCH") or None) as tmp:
        root = Path(tmp)
        safe_extract_tar(resp.content, root, int(sb["max_repo_files"]), int(sb["max_repo_mb"]) * 1024 * 1024)
        yield root


def recent_commits_text(project: dict, max_commits: int = 3, per_file: int = 1200, total: int = 3000) -> str:
    """Short diffs of the newest commits: what changed, not just the titles."""
    try:
        owner, repo, branch = _validate(project)
        token = _token(project.get("github_token_ciphertext", ""))
        api = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
        out, used = [], 0
        with httpx.Client(headers=_headers(token), timeout=httpx.Timeout(20, connect=8)) as client:
            listing = client.get(f"{api}/commits", params={"sha": branch, "per_page": max_commits})
            if listing.status_code != 200:
                return ""
            for item in listing.json()[:max_commits]:
                sha = str(item.get("sha", ""))
                detail = client.get(f"{api}/commits/{quote(sha, safe='')}")
                if detail.status_code != 200:
                    continue
                for f in (detail.json().get("files") or [])[:5]:
                    patch = str(f.get("patch") or "")
                    if not patch:
                        continue
                    block = f"--- commit {sha[:12]} changed {f.get('filename')} ---\n{patch[:per_file]}\n"
                    if used + len(block) > total:
                        return "\n".join(out)
                    out.append(block); used += len(block)
        return "\n".join(out)
    except Exception:
        return ""


def open_pr(project: dict, *, bug_id: str, incident_id: str, new_files: dict[str, str], diff: str, title: str, body: str) -> dict:
    """Open one PR changing several files. Idempotent: a retry reuses the same branch and PR."""
    owner, repo, base = _validate(project)
    token = _token(project.get("github_token_ciphertext", ""))
    import repo_guard
    repo_guard.ensure_private(project, token, action="fix pull request")   # public repo: PublicRepoError, nothing is written
    api = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
    branch = f"agent-daemon/fix-{bug_id[:14]}"
    call = portal_remediation._api
    with httpx.Client(headers=_headers(token), timeout=httpx.Timeout(25, connect=8), follow_redirects=False) as client:
        existing = call(client, "GET", f"{api}/pulls?state=open&head={quote(owner + ':' + branch, safe='')}")
        head_sha = ""
        if existing:
            pr = existing[0]
            head_sha = str((pr.get("head") or {}).get("sha", ""))
        else:
            ref = call(client, "GET", f"{api}/git/ref/heads/{quote(base, safe='/')}")
            base_sha = str(ref.get("object", {}).get("sha", ""))
            if not base_sha:
                raise RemediationError("Could not read the repository branch")
            commit = call(client, "GET", f"{api}/git/commits/{quote(base_sha, safe='')}")
            base_tree = str(commit.get("tree", {}).get("sha", ""))
            entries = []
            for path, content in new_files.items():
                blob = call(client, "POST", f"{api}/git/blobs", {"content": content, "encoding": "utf-8"})
                entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob.get("sha")})
            tree = call(client, "POST", f"{api}/git/trees", {"base_tree": base_tree, "tree": entries})
            new_commit = call(client, "POST", f"{api}/git/commits",
                              {"message": title, "tree": tree.get("sha"), "parents": [base_sha]})
            head_sha = str(new_commit.get("sha", ""))
            try:
                call(client, "POST", f"{api}/git/refs", {"ref": f"refs/heads/{branch}", "sha": new_commit.get("sha")})
            except RemediationError:
                call(client, "GET", f"{api}/git/ref/heads/{quote(branch, safe='/')}")   # branch already there from a retry
            pr = call(client, "POST", f"{api}/pulls", {"title": title, "head": branch, "base": base, "body": body})
    return {"url": pr.get("html_url", ""), "number": pr.get("number"), "branch": branch, "head_sha": head_sha,
            "path": ", ".join(new_files), "diff": diff, "ci_status": "pending"}


# ======================================================================================================================
# Direct push with proof (v3): test branch -> GitHub checks -> (red: back to the model) -> fast-forward the tracked branch.
# Nothing here opens a pull request unless the loop gives up (human review) or the branch is protected.
# ======================================================================================================================
_HTTP_CODE = re.compile(r"HTTP (\d{3})")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_LOG_TS = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ?", re.M)
_ERROR_LINE = re.compile(r"(error|failed|failure|exception|traceback|assert|cannot find|not found|exit code)", re.I)
FAILED_CONCLUSIONS = ("failure", "timed_out", "cancelled", "action_required", "startup_failure")


def http_code(exc) -> int:
    match = _HTTP_CODE.search(str(exc))
    return int(match.group(1)) if match else 0


def fix_branch_name(bug_id: str) -> str:
    return f"agent-daemon/fix-{str(bug_id)[:14]}"


def condense_log(text: str, limit: int = 3500) -> str:
    """The part of a CI log a model needs: no colours or timestamps, starting a little before the first error line."""
    text = _LOG_TS.sub("", _ANSI.sub("", text or "")).strip()
    if len(text) <= limit:
        return text
    lines = text.splitlines()
    first = next((i for i, line in enumerate(lines) if _ERROR_LINE.search(line)), None)
    if first is None:
        return text[-limit:]
    chunk = "\n".join(lines[max(0, first - 12):])
    return chunk[:limit] if len(chunk) > limit else chunk


def _api_root(project: dict) -> str:
    owner, repo, _branch = _validate(project)
    return f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"


def _tok(project: dict) -> str:
    return _token(project.get("github_token_ciphertext", ""))


def push_fix_branch(project: dict, *, bug_id: str, new_files: dict[str, str], title: str) -> dict:
    """Commit the proven-in-sandbox fix on top of the tracked branch's head and (force-)update our own test branch.
    A branch is not a pull request. GitHub Actions runs the customer's tests on it."""
    owner, repo, base = _validate(project)
    token = _tok(project)
    import repo_guard
    repo_guard.ensure_private(project, token, action="fix branch")     # public repo: PublicRepoError, nothing is written
    api = _api_root(project)
    branch = fix_branch_name(bug_id)
    call = portal_remediation._api
    with httpx.Client(headers=_headers(token), timeout=httpx.Timeout(30, connect=8), follow_redirects=False) as client:
        ref = call(client, "GET", f"{api}/git/ref/heads/{quote(base, safe='/')}")
        base_sha = str(ref.get("object", {}).get("sha", ""))
        if not base_sha:
            raise RemediationError("Could not read the repository branch")
        commit = call(client, "GET", f"{api}/git/commits/{quote(base_sha, safe='')}")
        base_tree = str(commit.get("tree", {}).get("sha", ""))
        entries = []
        for path, content in new_files.items():
            blob = call(client, "POST", f"{api}/git/blobs", {"content": content, "encoding": "utf-8"})
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob.get("sha")})
        tree = call(client, "POST", f"{api}/git/trees", {"base_tree": base_tree, "tree": entries})
        made = call(client, "POST", f"{api}/git/commits", {"message": title, "tree": tree.get("sha"), "parents": [base_sha]})
        head_sha = str(made.get("sha", ""))
        try:
            call(client, "POST", f"{api}/git/refs", {"ref": f"refs/heads/{branch}", "sha": head_sha})
        except RemediationError:     # a retry or a later round: our own branch moves to the new commit
            call(client, "PATCH", f"{api}/git/refs/heads/{quote(branch, safe='/')}", {"sha": head_sha, "force": True})
    return {"branch": branch, "head_sha": head_sha, "base_sha": base_sha}


def checks_state(project: dict, sha: str) -> str:
    """'pending' | 'success' | 'failed' | 'no_checks' for one commit."""
    token = _tok(project)
    with httpx.Client(headers=_headers(token), timeout=httpx.Timeout(20, connect=8), follow_redirects=False) as client:
        return portal_remediation._check_status(client, _api_root(project), sha)


def failed_check_log(project: dict, sha: str, limit: int = 3500) -> str:
    """Plain text of what failed on GitHub for this commit: job logs of failed check runs, else their output, plus failed statuses."""
    token = _tok(project)
    api = _api_root(project)
    parts: list[str] = []
    with httpx.Client(headers=_headers(token), timeout=httpx.Timeout(30, connect=8), follow_redirects=True) as client:
        runs = portal_remediation._api(client, "GET", f"{api}/commits/{quote(sha, safe='')}/check-runs?per_page=100").get("check_runs") or []
        bad = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") in FAILED_CONCLUSIONS]
        for run in bad[:3]:
            text = ""
            try:
                resp = client.get(f"{api}/actions/jobs/{int(run.get('id'))}/logs")
                if resp.status_code == 200:
                    text = resp.text
            except (httpx.HTTPError, TypeError, ValueError):
                text = ""
            if not text:
                out = run.get("output") or {}
                text = "\n".join(str(out.get(k) or "") for k in ("title", "summary", "text"))
            parts.append(f"### GitHub check failed: {run.get('name', 'check')}\n{condense_log(text, limit // max(1, min(len(bad), 3)))}")
        try:
            statuses = portal_remediation._api(client, "GET", f"{api}/commits/{quote(sha, safe='')}/status").get("statuses") or []
        except RemediationError:
            statuses = []
        for st in statuses:
            if st.get("state") in ("failure", "error") and "Agent Daemon" not in str(st.get("context", "")):
                parts.append(f"### Status failed: {st.get('context')}\n{str(st.get('description') or '')[:400]}")
    return "\n\n".join(parts)[:limit * 2] or "GitHub reported a failed check but gave no log."


def fast_forward_base(project: dict, head_sha: str, base_sha: str) -> str:
    """Move the tracked branch to the tested commit. Never forced. 'ok' | 'moved' (someone pushed meanwhile) | 'protected'."""
    owner, repo, base = _validate(project)
    token = _tok(project)
    import repo_guard
    repo_guard.ensure_private(project, token, action="direct push")
    api = _api_root(project)
    call = portal_remediation._api
    with httpx.Client(headers=_headers(token), timeout=httpx.Timeout(25, connect=8), follow_redirects=False) as client:
        try:
            call(client, "PATCH", f"{api}/git/refs/heads/{quote(base, safe='/')}", {"sha": head_sha, "force": False})
            return "ok"
        except RemediationError as exc:
            code = http_code(exc)
            try:
                now_sha = str(call(client, "GET", f"{api}/git/ref/heads/{quote(base, safe='/')}").get("object", {}).get("sha", ""))
            except RemediationError:
                now_sha = base_sha
            if now_sha and now_sha != base_sha:
                return "moved"
            if code in (403, 422, 409):
                return "protected"
            raise


def delete_branch(project: dict, branch: str) -> None:
    try:
        token = _tok(project)
        with httpx.Client(headers=_headers(token), timeout=httpx.Timeout(15, connect=8), follow_redirects=False) as client:
            portal_remediation._api(client, "DELETE", f"{_api_root(project)}/git/refs/heads/{quote(branch, safe='/')}")
    except Exception:
        pass     # a leftover test branch is harmless


def open_pr_for_branch(project: dict, *, branch: str, title: str, body: str) -> dict:
    """The fallback: a pull request from our test branch (human review, or a protected branch)."""
    owner, repo, base = _validate(project)
    token = _tok(project)
    import repo_guard
    repo_guard.ensure_private(project, token, action="fix pull request")
    api = _api_root(project)
    call = portal_remediation._api
    with httpx.Client(headers=_headers(token), timeout=httpx.Timeout(25, connect=8), follow_redirects=False) as client:
        existing = call(client, "GET", f"{api}/pulls?state=open&head={quote(owner + ':' + branch, safe='')}")
        pr = existing[0] if existing else call(client, "POST", f"{api}/pulls", {"title": title, "head": branch, "base": base, "body": body})
    return {"url": pr.get("html_url", ""), "number": pr.get("number"), "branch": branch}
