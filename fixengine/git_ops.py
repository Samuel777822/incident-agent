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
