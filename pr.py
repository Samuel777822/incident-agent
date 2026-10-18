import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "AI On-Call Engineer",
    "GIT_AUTHOR_EMAIL": "oncall-agent@users.noreply.github.com",
    "GIT_COMMITTER_NAME": "AI On-Call Engineer",
    "GIT_COMMITTER_EMAIL": "oncall-agent@users.noreply.github.com",
    "GIT_TERMINAL_PROMPT": "0",
}


def parse_github_owner_repo(repo_url):
    m = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$", repo_url or "")
    if m:
        return m.group(1), m.group(2)
    return None, None


def run_git(args, cwd):
    env = {**os.environ, **GIT_IDENTITY}
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env
    )
    if proc.returncode != 0:
        text = f"git {args[0]} failed: {proc.stderr.strip()}"
        token = os.getenv("GITHUB_TOKEN")
        if token:
            text = text.replace(token, "***")
        raise RuntimeError(text)
    return proc.stdout.strip()


def create_fix_branch(repo_folder, incident_id, base_branch="main"):
    branch_name = f"fix/incident-{incident_id}"
    run_git(["checkout", base_branch], repo_folder)
    run_git(["reset", "--hard", f"origin/{base_branch}"], repo_folder)
    run_git(["checkout", "-B", branch_name], repo_folder)
    return branch_name


def commit_fix(repo_folder, file_path, incident_id, explanation):
    run_git(["add", file_path], repo_folder)
    run_git(
        ["commit", "-m", f"fix: resolve incident #{incident_id}\n\n{explanation}"],
        repo_folder,
    )


def _github(url, token, payload, method):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "AI-OnCall-Engineer",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method=method
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def open_and_maybe_merge_pr(
    repo_folder,
    repo_url,
    branch_name,
    base_branch="main",
    incident_id=None,
    title=None,
    body=None,
    auto_merge=False,
):
    token = os.getenv("GITHUB_TOKEN")
    owner, repo_name = parse_github_owner_repo(repo_url)
    if not token or not owner or not repo_name:
        print("[PR] GITHUB_TOKEN is missing or the repo URL is not a GitHub URL. No PR opened.")
        return None, False

    push_url = f"https://x-access-token:{token}@github.com/{owner}/{repo_name}.git"
    try:
        run_git(["push", push_url, f"{branch_name}:{branch_name}", "--force"], repo_folder)
    except Exception as exc:
        print(f"[PR] Push to GitHub failed: {exc}. No PR opened.")
        return None, False

    api = f"https://api.github.com/repos/{owner}/{repo_name}"
    try:
        pr = _github(
            f"{api}/pulls",
            token,
            {
                "title": title or f"fix: incident #{incident_id}",
                "head": branch_name,
                "base": base_branch,
                "body": body or f"Automated fix for incident #{incident_id}.",
            },
            "POST",
        )
    except urllib.error.HTTPError as err:
        text = err.read().decode("utf-8", errors="replace")
        if "A pull request already exists" in text:
            print("[PR] A pull request for this branch already exists.")
            return f"https://github.com/{owner}/{repo_name}/pulls", False
        print(f"[PR] GitHub refused the pull request ({err.code}): {text[:300]}")
        return None, False
    except Exception as exc:
        print(f"[PR] Could not reach GitHub: {exc}")
        return None, False

    pr_url, number = pr.get("html_url"), pr.get("number")
    merged = False
    if auto_merge and number:
        try:
            res = _github(
                f"{api}/pulls/{number}/merge",
                token,
                {
                    "commit_title": f"Merge pull request #{number} (auto-fix incident #{incident_id})",
                    "merge_method": "squash",
                },
                "PUT",
            )
            merged = bool(res.get("merged"))
        except Exception as exc:
            print(f"[PR] Auto-merge failed: {exc}. The PR stays open for a human.")
    return pr_url, merged
