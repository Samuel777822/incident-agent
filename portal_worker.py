"""Tenant-aware diagnosis worker for portal incidents.

The worker reads repository files as evidence, may create a constrained fix PR,
and merges only auto-mode PRs with passing GitHub checks. It never executes
customer code or tests. Run with the portal service supervisor.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
import httpx

import portal_db
from diagnose import diagnose_incident
from run_diagnosis import build_evidence_text
from portal_remediation import submit_fix_pr, process_auto_merges

LOG = logging.getLogger("portal_worker")
_STOP = False
_REPO_PART = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class WorkerError(RuntimeError):
    """Safe-to-record worker error without secret material."""


def _stop(*_args):
    global _STOP
    _STOP = True


def _decrypt_token(ciphertext: str) -> str:
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise WorkerError("Token encryption is not configured")
    try:
        return Fernet(key.encode("ascii")).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeError, InvalidToken):
        raise WorkerError("Saved GitHub credential could not be decrypted") from None


def _repository_evidence(project: dict, traceback: str) -> tuple[str, dict[str, str]]:
    """Read a bounded set of source files and commit summaries through GitHub's API."""
    owner = str(project.get("repo_owner", ""))
    repo = str(project.get("repo_name", ""))
    branch = str(project.get("branch", "main"))
    if not _REPO_PART.fullmatch(owner) or not _REPO_PART.fullmatch(repo):
        raise WorkerError("Repository identity is invalid")
    if not branch or len(branch) > 250 or branch.startswith("-") or ".." in branch or "\\" in branch:
        raise WorkerError("Repository branch is invalid")
    token = _decrypt_token(str(project.get("github_token_ciphertext", "")))
    api = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    source_files = {}
    excluded = {".git", ".github", "tests", "test", "venv", ".venv", "node_modules"}
    try:
        with httpx.Client(headers=headers, timeout=httpx.Timeout(15, connect=8), follow_redirects=False) as client:
            tree_response = client.get(f"{api}/git/trees/{quote(branch, safe='')}?recursive=1")
            if tree_response.status_code == 404:
                raise WorkerError("Repository or selected branch was not found")
            if tree_response.status_code in (401, 403):
                raise WorkerError("GitHub rejected the saved token or its repository permissions")
            if tree_response.status_code == 409:
                raise WorkerError("Repository branch has no commit to inspect")
            if tree_response.status_code >= 400:
                raise WorkerError(f"GitHub repository read failed (HTTP {tree_response.status_code})")
            tree_data = tree_response.json()
            if tree_data.get("truncated"):
                raise WorkerError("Repository is too large for a complete safe file listing")
            tree = tree_data.get("tree", [])
            py_paths = []
            for item in tree:
                path = str(item.get("path", ""))
                parts = path.split("/")
                if item.get("type") != "blob" or any(p.lower() in excluded for p in parts[:-1]):
                    continue
                if parts[-1].startswith(".env") or parts[-1].lower() in {"secrets.py", "settings_secret.py"}:
                    continue
                if path.endswith(".py") and int(item.get("size", 0) or 0) <= 80000:
                    py_paths.append(path)
                elif parts[-1] in {"requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"} and int(item.get("size", 0) or 0) <= 20000:
                    py_paths.append(path)
            frame_basenames = re.findall(r'File ["\']([^"\']+)["\'], line \d+', traceback or "")
            frame_names = {path.replace("\\", "/").split("/")[-1] for path in frame_basenames}
            py_paths.sort(key=lambda p: (0 if p.split("/")[-1] in frame_names else 1,
                                         0 if p.endswith(".py") else 1, len(p), p))
            selected = py_paths[:20]
            total = 0
            for path in selected:
                response = client.get(f"{api}/contents/{quote(path, safe='/')}?ref={quote(branch, safe='')}")
                if response.status_code >= 400:
                    continue
                payload = response.json()
                if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
                    continue
                import base64
                raw = base64.b64decode(payload["content"], validate=False)
                if len(raw) > 80000 or total + len(raw) > 400000:
                    continue
                try:
                    source_files[path] = raw.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                total += len(raw)

            commits_response = client.get(f"{api}/commits?sha={quote(branch, safe='')}&per_page=5")
            commits = []
            if commits_response.status_code == 200:
                for commit in commits_response.json():
                    sha = str(commit.get("sha", ""))[:12]
                    message = str(commit.get("commit", {}).get("message", "")).splitlines()[0][:180]
                    date = str(commit.get("commit", {}).get("author", {}).get("date", ""))[:10]
                    commits.append(f"{sha} | {date} | {message}")
    except WorkerError:
        raise
    except (httpx.TimeoutException, httpx.NetworkError):
        raise WorkerError("GitHub request timed out or could not connect") from None
    except (ValueError, KeyError, TypeError):
        raise WorkerError("GitHub returned an unreadable repository response") from None
    finally:
        headers["Authorization"] = ""
        token = ""

    git_text = "RECENT COMMITS (newest first):\n" + ("\n".join(commits) if commits else "No commit history available.")
    evidence, _skipped = build_evidence_text(source_files, git_text, traceback)
    return evidence, source_files


def process_one() -> bool:
    incident = portal_db.claim_next_incident(
        min_occurrences=int(os.getenv("WORKER_MIN_OCCURRENCES", "5")),
        min_age_seconds=int(os.getenv("WORKER_MIN_AGE_SECONDS", "30")),
        lease_seconds=int(os.getenv("WORKER_LEASE_SECONDS", "600")),
        max_attempts=int(os.getenv("WORKER_MAX_ATTEMPTS", "3")),
    )
    if not incident:
        return False
    incident_id = incident["incident_id"]
    project_id = incident["project_id"]
    event = incident.get("first_event")
    if not event:
        portal_db.fail_diagnosis(incident_id, project_id, "Incident has no event evidence")
        return True

    try:
        evidence, source_files = _repository_evidence(incident, event.get("traceback", ""))
        result = diagnose_incident(event.get("message", ""), event.get("traceback", ""), evidence)
        if not portal_db.complete_diagnosis(incident_id, project_id, result):
            raise WorkerError("Incident was no longer owned by this worker")
        LOG.info("Diagnosis completed for incident %s", incident_id)
        if incident.get("mode") in ("pr", "auto"):
            if not (result.get("category") == "code_bug"
                    and result.get("confidence") == "high"
                    and result.get("still_present_in_current_code") == "yes"
                    and result.get("safe_to_auto_fix") is True):
                portal_db.mark_remediation_needs_human(
                    incident_id, project_id,
                    "The issue did not meet the strict high-confidence, small Python code-fix safety checks.")
                return True
            try:
                work_item = {**incident, "message": event.get("message", ""),
                             "traceback": event.get("traceback", ""), "incident_id": incident_id}
                pr = submit_fix_pr(incident, work_item, result, evidence, source_files)
                if not pr.get("url") or not pr.get("number"):
                    raise WorkerError("GitHub did not return a pull request link")
                portal_db.record_remediation(
                    incident_id, project_id, branch=pr["branch"], file_path=pr["path"],
                    diff=pr["diff"], pr_url=pr["url"], pr_number=int(pr["number"]),
                    ci_status=pr.get("ci_status", "pending"))
                LOG.info("Fix PR opened for incident %s", incident_id)
            except Exception as exc:
                safe_message = str(exc) if isinstance(exc, WorkerError) else exc.__class__.__name__
                portal_db.mark_remediation_needs_human(incident_id, project_id, safe_message)
                LOG.warning("Fix PR deferred for incident %s (%s)", incident_id, safe_message)
    except ValueError as exc:
        portal_db.fail_diagnosis(incident_id, project_id, str(exc))
        LOG.error("Diagnosis configuration issue for incident %s: %s", incident_id, exc)
    except Exception as exc:
        safe_message = str(exc) if isinstance(exc, WorkerError) else exc.__class__.__name__
        portal_db.fail_diagnosis(incident_id, project_id, safe_message)
        LOG.warning("Diagnosis deferred for incident %s (%s)", incident_id, safe_message)
    return True


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    portal_db.init_db()
    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)
    poll_seconds = max(1, int(os.getenv("WORKER_POLL_SECONDS", "5")))
    LOG.info("Portal incident worker started")
    next_merge_poll = 0.0
    while not _STOP:
        try:
            portal_db.touch_worker()
        except Exception:
            LOG.exception("Could not record worker heartbeat")
        try:
            worked = process_one()
        except Exception:
            LOG.exception("Worker loop failed")
            worked = False
        now = time.monotonic()
        if now >= next_merge_poll and not _STOP:
            try:
                process_auto_merges()
            except Exception:
                LOG.exception("Auto-merge check failed")
            next_merge_poll = now + max(15, int(os.getenv("AUTO_MERGE_POLL_SECONDS", "30")))
        if not worked and not _STOP:
            time.sleep(min(poll_seconds, 5))
    LOG.info("Portal diagnosis worker stopped")


if __name__ == "__main__":
    main()

