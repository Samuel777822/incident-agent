"""The background worker: push checks, incidents, and reviewable fixes.

Every loop it:
  1. checks one pushed commit in the sandbox (push guard, architecture v3; free, no AI),
  2. works on one incident (the fix engine when FIXENGINE_ENABLED=1, otherwise the classic diagnosis),
  3. resumes decisions customers did not answer in time,
  4. every few minutes polls GitHub for pushes the webhook may have missed.
Customer code only ever runs inside the sandbox (see fixengine/sandbox.py), never on this machine.
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
import push_watch
from diagnose import diagnose_incident
from run_diagnosis import build_evidence_text
from portal_remediation import submit_fix_pr

LOG = logging.getLogger("portal_worker")
_STOP = False
_REPO_PART = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
SOURCE_EXT = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".html", ".htm", ".css", ".scss", ".vue", ".svelte")
MANIFEST_NAMES = {"requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "package.json", "tsconfig.json", "pom.xml",
                  "build.gradle", "build.gradle.kts"}


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


def _recent_diffs(client, api, shas, max_commits=2, per_file=1200, total=3000):
    """Diffs of the newest commits' source files, so the model sees WHAT changed, not just the commit title."""
    out, used = [], 0
    for full_sha in shas[:max_commits]:
        if not full_sha:
            continue
        resp = client.get(f"{api}/commits/{quote(full_sha, safe='')}")
        if resp.status_code != 200:
            continue
        for item in (resp.json().get("files") or [])[:5]:
            name, patch = str(item.get("filename", "")), str(item.get("patch") or "")
            if not patch or not name.endswith(SOURCE_EXT):
                continue
            block = f"--- commit {full_sha[:12]} changed {name} ---\n{patch[:per_file]}\n"
            if used + len(block) > total:
                return "\n".join(out)
            out.append(block)
            used += len(block)
    return "\n".join(out)


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
    excluded = {".git", ".github", "venv", ".venv", "node_modules"}
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
                if path.endswith(SOURCE_EXT) and int(item.get("size", 0) or 0) <= 80000:
                    py_paths.append(path)
                elif parts[-1] in MANIFEST_NAMES and int(item.get("size", 0) or 0) <= 20000:
                    py_paths.append(path)
            frame_basenames = re.findall(r'File ["\']([^"\']+)["\'], line \d+', traceback or "")
            frame_basenames += re.findall(r"([\w./-]+\.(?:py|js|jsx|ts|tsx|mjs|cjs|java|html|css))[:(]\d+", traceback or "")
            frame_names = {path.replace("\\", "/").split("/")[-1] for path in frame_basenames}
            py_paths.sort(key=lambda p: (0 if p.split("/")[-1] in frame_names else 1,
                                         0 if p.endswith(SOURCE_EXT) else 1, len(p), p))
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
            full_shas = []
            if commits_response.status_code == 200:
                for commit in commits_response.json():
                    full_sha = str(commit.get("sha", ""))
                    full_shas.append(full_sha)
                    sha = full_sha[:12]
                    message = str(commit.get("commit", {}).get("message", "")).splitlines()[0][:180]
                    date = str(commit.get("commit", {}).get("author", {}).get("date", ""))[:10]
                    commits.append(f"{sha} | {date} | {message}")
            recent_diffs = _recent_diffs(client, api, full_shas)
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
    if recent_diffs:
        git_text += "\n\nWHAT THE NEWEST COMMITS CHANGED (diffs):\n" + recent_diffs
    evidence, _skipped = build_evidence_text(source_files, git_text, traceback)
    return evidence, source_files


_ENGINE = None


def _engine():
    """The cost-controlled fix engine (fixengine/). Off unless FIXENGINE_ENABLED=1; the older flow is untouched."""
    global _ENGINE
    if _ENGINE is None:
        from fixengine import orchestrator
        if not orchestrator.enabled():
            return None
        _ENGINE = orchestrator.Engine()
    return _ENGINE


def _try_model_fix(incident: dict, event: dict) -> bool:
    """Retired / unknown AI model: fixed deterministically (no AI tries). True when the incident was handled here."""
    from fixengine import model_fix
    runner = None
    try:
        ready, _why = push_watch.sandbox_ready()
        if ready:
            from fixengine import config as fx_config, sandbox
            runner = sandbox.make_runner(fx_config.load())
    except Exception:
        runner = None
    try:
        outcome = model_fix.run(incident, event, runner=runner)
    except Exception as exc:
        LOG.exception("Model fix crashed on incident %s", incident["incident_id"])
        portal_db.fail_diagnosis(incident["incident_id"], incident["project_id"], exc.__class__.__name__)
        return True
    if outcome is None:
        if incident.get("source") == "scan":
            portal_db.mark_remediation_needs_human(incident["incident_id"], incident["project_id"],
                                                   "The scan finding could not be matched to a model name in the code.")
            return True
        return False
    LOG.info("Model fix for incident %s: %s", incident["incident_id"], outcome)
    return True


def monitor_sweep() -> int:
    """Tell owners (once) when a server-side monitor stopped checking in or never checked in. Never silent."""
    import notifications
    sent = 0
    base = os.getenv("PORTAL_BASE_URL", "").strip().rstrip("/")
    for project in portal_db.projects_needing_monitor_alert():
        state = project["monitor"]
        portal_db.set_monitor_alerted(project["id"])
        portal_db.audit(project["id"], "monitor_" + state["state"], {"last_checkin": state.get("last_checkin", "")})
        LOG.warning("Project %s monitor state: %s", project["id"], state["state"])
        email = portal_db.get_user_email(project["user_id"])
        if not email:
            continue
        notifications.notify_customer(
            email, f"{project['name']}: {state['headline'].lower()}",
            f"Agent Daemon has not heard from the monitor in {project['repo_owner']}/{project['repo_name']}.\n\n{state['detail']}\n\n"
            "What to try, in order:\n1. Open your app in a browser to wake it up.\n2. If the monitoring pull request is still open on "
            "GitHub, merge it and re-deploy.\n3. Re-deploy your app from your hosting dashboard.\n\n"
            f"See the status on {base}/projects/{project['id']}", "monitor_offline")
        sent += 1
    return sent


def process_one() -> bool:
    incident = portal_db.claim_next_incident(
        min_occurrences=int(os.getenv("WORKER_MIN_OCCURRENCES", "1")),
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
        portal_db.set_incident_stage(incident_id, "diagnosing" if _engine() is None or incident.get("mode") not in ("pr", "auto") else "downloading")
    except Exception:
        pass
    if _try_model_fix(incident, event):
        return True
    if incident.get("mode") in ("pr", "auto") and _engine() is not None:
        try:
            outcome = _engine().handle_incident(incident)
            LOG.info("Fix engine finished incident %s: %s", incident_id, outcome)
        except Exception as exc:
            portal_db.fail_diagnosis(incident_id, project_id, exc.__class__.__name__)
            LOG.exception("Fix engine crashed on incident %s", incident_id)
        return True

    try:
        evidence, source_files = _repository_evidence(incident, event.get("traceback", ""))
        result = diagnose_incident(event.get("message", ""), event.get("traceback", ""), evidence)
        if not portal_db.complete_diagnosis(incident_id, project_id, result):
            raise WorkerError("Incident was no longer owned by this worker")
        LOG.info("Diagnosis completed for incident %s", incident_id)
        if incident.get("mode") in ("pr", "auto") and incident.get("source") == "push":
            portal_db.mark_remediation_needs_human(
                incident_id, project_id, "The automatic fixer is switched off (FIXENGINE_ENABLED=0), so only a diagnosis was made.")
            return True
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
    import config_check
    config_check.check("worker")
    portal_db.init_db()
    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)
    poll_seconds = max(1, int(os.getenv("WORKER_POLL_SECONDS", "5")))
    LOG.info("Portal incident worker started")
    next_push_poll = 0.0
    next_monitor_sweep = 0.0
    next_visibility_sweep = 0.0
    while not _STOP:
        try:
            portal_db.touch_worker()
        except Exception:
            LOG.exception("Could not record worker heartbeat")
        worked = False
        try:
            worked = push_watch.process_one() or worked
        except Exception:
            LOG.exception("Push check failed")
        try:
            worked = process_one() or worked
        except Exception:
            LOG.exception("Worker loop failed")
        try:
            if _engine() is not None:
                _engine().resume_expired_choices()
        except Exception:
            LOG.exception("Could not resume expired fix choices")
        now = time.monotonic()
        if now >= next_push_poll and not _STOP:
            try:
                queued = push_watch.poll_once()
                if queued:
                    LOG.info("Push poll queued %s new commit(s)", queued)
            except Exception:
                LOG.exception("Push poll failed")
            next_push_poll = now + max(60, int(os.getenv("PUSH_POLL_SECONDS", "180")))
        if now >= next_monitor_sweep and not _STOP:
            try:
                monitor_sweep()
            except Exception:
                LOG.exception("Monitor check-in sweep failed")
            next_monitor_sweep = now + 60
        if now >= next_visibility_sweep and not _STOP:
            try:
                import repo_guard
                flagged = repo_guard.sweep_visibility()
                if flagged:
                    LOG.warning("%s repository(ies) became public: installs and fixes paused", flagged)
            except Exception:
                LOG.exception("Repository visibility sweep failed")
            next_visibility_sweep = now + max(300, int(os.getenv("VISIBILITY_CHECK_SECONDS", "600")))
        if not worked and not _STOP:
            time.sleep(min(poll_seconds, 5))
    LOG.info("Portal diagnosis worker stopped")


if __name__ == "__main__":
    main()

