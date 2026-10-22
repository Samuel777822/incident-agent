import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # optional: only used to read a local .env file
    def load_dotenv(*_args, **_kwargs):
        return False

load_dotenv(Path(__file__).parent / ".env")

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "AI On-Call Engineer",
    "GIT_AUTHOR_EMAIL": "oncall-agent@users.noreply.github.com",
    "GIT_COMMITTER_NAME": "AI On-Call Engineer",
    "GIT_COMMITTER_EMAIL": "oncall-agent@users.noreply.github.com",
    "GIT_TERMINAL_PROMPT": "0",
}


def mask_token(text: str, token: str = None) -> str:
    token = token or os.getenv("GITHUB_TOKEN")
    if not text or not token:
        return text or ""
    return text.replace(token, "***")


def parse_github_owner_repo(repo_url):
    clean = (repo_url or "").strip()
    if not clean:
        return None, None
    m = re.search(r"github\.com[/:]([\w\.-]+)/([\w\.-]+?)(?:\.git)?/?$", clean)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^([\w\.-]+)/([\w\.-]+)$", clean)
    if m:
        return m.group(1), m.group(2)
    return None, None


def run_git(args, cwd, timeout=60):
    env = {**os.environ, **GIT_IDENTITY}
    token = os.getenv("GITHUB_TOKEN")
    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env, timeout=timeout
        )
    except subprocess.TimeoutExpired as err:
        raise RuntimeError(f"git {args[0]} timed out after {timeout}s") from err
    except Exception as exc:
        raise RuntimeError(f"git {args[0]} execution error: {mask_token(str(exc), token)}") from exc

    if proc.returncode != 0:
        err_msg = mask_token(proc.stderr.strip(), token)
        raise RuntimeError(f"git {args[0]} failed: {err_msg}")
    return proc.stdout.strip()


def create_fix_branch(repo_folder, incident_id, base_branch="master"):
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
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def get_ci_status(api, token, commit_sha):
    """Return success, pending, failed, or no_checks for a commit's GitHub CI."""
    checks = _github(f"{api}/commits/{commit_sha}/check-runs?per_page=100", token, None, "GET")
    statuses = _github(f"{api}/commits/{commit_sha}/status", token, None, "GET")
    runs = checks.get("check_runs") or []
    states = statuses.get("statuses") or []
    if not runs and not states:
        return "no_checks"
    if any(run.get("status") != "completed" for run in runs) or any(s.get("state") == "pending" for s in states):
        return "pending"
    if any(run.get("conclusion") not in ("success", "neutral", "skipped") for run in runs):
        return "failed"
    if any(s.get("state") != "success" for s in states):
        return "failed"
    return "success"


def wait_for_ci(api, token, commit_sha, on_update=None):
    """Wait briefly for checks to appear, then until they pass or time out."""
    timeout = max(0, int(os.getenv("AGENT_CI_WAIT_SECONDS", "600")))
    discovery = max(0, int(os.getenv("AGENT_CI_DISCOVERY_SECONDS", "30")))
    interval = max(1, int(os.getenv("AGENT_CI_POLL_SECONDS", "10")))
    started = time.monotonic()
    saw_checks = False
    last_status = None
    while True:
        status = get_ci_status(api, token, commit_sha)
        if status != "no_checks":
            saw_checks = True
        if status != last_status and on_update:
            on_update(status)
        last_status = status
        if status in ("success", "failed"):
            return status
        elapsed = time.monotonic() - started
        if status == "no_checks" and elapsed >= discovery:
            return "no_checks"
        if elapsed >= timeout:
            return "timed_out" if saw_checks else "no_checks"
        time.sleep(min(interval, max(0.0, timeout - elapsed)))


def open_and_maybe_merge_pr(
    repo_folder,
    repo_url,
    branch_name,
    base_branch="master",
    incident_id=None,
    title=None,
    body=None,
    auto_merge=False,
    on_ci_update=None,
):
    token = os.getenv("GITHUB_TOKEN", "").strip()
    owner, repo_name = parse_github_owner_repo(repo_url)
    if not token or not owner or not repo_name:
        print("[PR] GITHUB_TOKEN is missing or the repo URL is not a GitHub URL. No PR opened.")
        return None, False

    clean_target_url = f"https://github.com/{owner}/{repo_name}.git"
    try:
        # Push using http.extraHeader to avoid embedding token in command line or remote URL
        run_git(
            [
                "-c",
                f"http.extraHeader=Authorization: Bearer {token}",
                "push",
                clean_target_url,
                f"{branch_name}:{branch_name}",
                "--force",
            ],
            repo_folder,
        )
    except Exception as exc:
        print(f"[PR] Push to GitHub failed: {mask_token(str(exc), token)}. No PR opened.")
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
        text_masked = mask_token(text, token)
        if "A pull request already exists" in text:
            print("[PR] A pull request for this branch already exists.")
            return f"https://github.com/{owner}/{repo_name}/pulls", False
        print(f"[PR] GitHub refused the pull request ({err.code}): {text_masked[:300]}")
        return None, False
    except Exception as exc:
        print(f"[PR] Could not reach GitHub: {mask_token(str(exc), token)}")
        return None, False

    pr_url, number = pr.get("html_url"), pr.get("number")
    merged = False
    ci_status = "unknown"
    head_sha = (pr.get("head") or {}).get("sha")
    if number and head_sha:
        try:
            if auto_merge:
                ci_status = wait_for_ci(api, token, head_sha,
                    on_update=(lambda status: on_ci_update(status, pr_url, number)) if on_ci_update else None)
            else:
                ci_status = get_ci_status(api, token, head_sha)
            if on_ci_update:
                on_ci_update(ci_status, pr_url, number)
        except Exception as exc:
            ci_status = "unavailable"
            print(f"[PR] Could not read GitHub CI status: {mask_token(str(exc), token)}")
            if on_ci_update:
                on_ci_update(ci_status, pr_url, number)
    if auto_merge and number and ci_status == "success":
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
            print(f"[PR] Auto-merge failed: {mask_token(str(exc), token)}. The PR stays open for a human.")
    elif auto_merge and ci_status != "success":
        print(f"[PR] CI status is '{ci_status}'. Leaving the pull request open for review.")
    return pr_url, merged
