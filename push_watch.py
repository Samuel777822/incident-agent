"""Push guard (architecture v3): catch a bug the moment the code reaches GitHub, before anybody deploys it.

The classic flow waits for a LIVE app to crash and report the error. Vibe coders and hackathon teams need the opposite: the bug
should be caught as soon as they push, fixed by the agent, and the fixed version pushed back to GitHub. This module does that:

    git push ──► GitHub webhook (or the worker's poll, as a fallback) ──► push_checks queue
             ──► worker downloads THAT commit ──► finds every stack in the repo (Python, JS/TS, Java, HTML/CSS)
             ──► runs install → build/type-check → tests → start-up check for each stack in the sandbox
             ──► green: GitHub commit status "success", done
             ──► red:   commit status "failure", an incident is opened, and the fix engine takes over
                        (router → model → patch → the SAME sandbox check must go green → fix branch + PR for human review)

Nothing here calls an AI model: a push check is free. Only a failing check spends tries, through the normal quota and budget guard.
The GitHub token is decrypted in memory only; customer code runs only inside the sandbox.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from urllib.parse import quote

import httpx

import portal_db
from fixengine import sandbox
from fixengine import config as fx_config
from fixengine.git_ops import _headers, _validate, repo_snapshot
from portal_remediation import RemediationError, _token

LOG = logging.getLogger("push_watch")
AGENT_MARK = "[agent-daemon]"
STATUS_CONTEXT = "Agent Daemon / push check"
FIX_BRANCH_PREFIX = "agent-daemon/"
MAX_CHECKS_PER_HOUR = int(os.getenv("PUSH_MAX_CHECKS_PER_HOUR", "12"))

STAGE_TEXT = {
    "queued": "Waiting in line",
    "downloading": "Downloading this commit from GitHub",
    "detecting": "Finding the projects in your repo",
    "testing": "Testing in the sandbox: install â†’ build â†’ tests â†’ start-up",
    "waiting_retry": "Paused for a moment, will retry by itself",
    "waiting_sandbox": "Waiting for the test sandbox to come online",
    "passed": "All checks passed",
    "failed": "Broken: the agent is on it",
    "skipped": "Nothing to test",
    "error": "Could not check this commit",
    "superseded": "Skipped: a newer push arrived",
}


def enabled() -> bool:
    return os.getenv("PUSH_CHECKS_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def sandbox_ready(cfg: dict | None = None) -> tuple[bool, str]:
    """Is there somewhere safe to run customer code? Never fake it: no sandbox means no check."""
    cfg = cfg or fx_config.load()
    mode = os.getenv("FIXENGINE_SANDBOX_MODE") or cfg["sandbox"]["mode"]
    if mode == "remote":
        ok = bool(os.getenv("FIXENGINE_SANDBOX_URL", "").strip() and os.getenv("FIXENGINE_SANDBOX_SECRET", "").strip())
        return ok, "" if ok else "FIXENGINE_SANDBOX_URL / FIXENGINE_SANDBOX_SECRET are not set"
    if mode == "local_unsafe":
        ok = os.getenv("FIXENGINE_ALLOW_UNSAFE_LOCAL") == "1"
        return ok, "" if ok else "local_unsafe sandbox needs FIXENGINE_ALLOW_UNSAFE_LOCAL=1"
    import shutil
    ok = shutil.which("docker") is not None
    return ok, "" if ok else "Docker is not available on this machine (use FIXENGINE_SANDBOX_MODE=remote)"


# ---------------------------------------------------------------------------------------------------- GitHub helpers
def _api(project: dict) -> str:
    owner, repo, _branch = _validate(project)
    return f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"


def webhook_url(project_id: str) -> str:
    base = os.getenv("PORTAL_BASE_URL", "").strip().rstrip("/")
    return f"{base}/webhooks/github/{project_id}"


def _encrypt(value: str) -> str:
    from cryptography.fernet import Fernet
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not configured")
    return Fernet(key.encode("ascii")).encrypt(value.encode()).decode("ascii")


def install_webhook(project: dict, token: str) -> dict:
    """Create (or refresh) the repository webhook that tells us about every push. Needs the classic `repo` scope.
    Returns {"ok": bool, "id": hook id, "error": text}. Polling still covers the project when this fails."""
    try:
        api = _api(project)
    except RemediationError as exc:
        return {"ok": False, "error": str(exc)}
    url = webhook_url(project["id"])
    secret = secrets.token_urlsafe(32)
    config = {"url": url, "content_type": "json", "secret": secret, "insecure_ssl": "0"}
    headers = _headers(token)
    try:
        with httpx.Client(headers=headers, timeout=httpx.Timeout(20, connect=8)) as client:
            hooks = client.get(f"{api}/hooks", params={"per_page": 100})
            if hooks.status_code in (401, 403, 404):
                return {"ok": False, "error": "GitHub did not allow this token to manage webhooks (it needs the repo scope and admin rights on the repository)."}
            existing = next((h for h in (hooks.json() if hooks.status_code == 200 else [])
                             if str((h.get("config") or {}).get("url", "")).rstrip("/") == url), None)
            body = {"name": "web", "active": True, "events": ["push"], "config": config}
            resp = (client.patch(f"{api}/hooks/{existing['id']}", json=body) if existing
                    else client.post(f"{api}/hooks", json=body))
            if resp.status_code not in (200, 201):
                return {"ok": False, "error": f"GitHub refused the webhook (HTTP {resp.status_code})."}
            hook_id = str(resp.json().get("id", ""))
    except httpx.HTTPError:
        return {"ok": False, "error": "Could not reach GitHub to add the webhook."}
    finally:
        headers["Authorization"] = ""
    portal_db.set_project_webhook(project["id"], hook_id, _encrypt(secret))
    return {"ok": True, "id": hook_id}


def verify_signature(project: dict, body: bytes, header: str) -> bool:
    """GitHub signs every delivery with the secret we gave it: X-Hub-Signature-256: sha256=<hex HMAC of the raw body>."""
    cipher = str(project.get("webhook_secret_ciphertext") or "")
    if not cipher or not header or not header.startswith("sha256="):
        return False
    try:
        secret = _token(cipher)
    except Exception:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip())


def parse_push(payload: dict, project: dict) -> dict | None:
    """The commit to check, or None when this push is not for us (another branch, a deletion, or our own fix branch)."""
    ref = str(payload.get("ref") or "")
    if not ref.startswith("refs/heads/") or payload.get("deleted"):
        return None
    branch = ref[len("refs/heads/"):]
    if branch.startswith(FIX_BRANCH_PREFIX) or branch != str(project.get("branch") or ""):
        return None
    head = payload.get("head_commit") or {}
    sha = str(head.get("id") or payload.get("after") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return None
    pusher = str((payload.get("pusher") or {}).get("name") or (head.get("author") or {}).get("username") or "")
    return {"sha": sha, "branch": branch, "pusher": pusher, "message": str(head.get("message") or "").splitlines()[0][:300] if head.get("message") else ""}


def set_commit_status(project: dict, sha: str, state: str, description: str) -> bool:
    """The coloured dot next to the commit on GitHub (pending / success / failure / error). Best effort."""
    try:
        token = _token(project.get("github_token_ciphertext", ""))
        api = _api(project)
    except Exception:
        return False
    headers = _headers(token)
    base = os.getenv("PORTAL_BASE_URL", "").strip().rstrip("/")
    body = {"state": state, "context": STATUS_CONTEXT, "description": description[:139]}
    if base:
        body["target_url"] = f"{base}/projects/{project.get('project_id') or project.get('id')}"
    try:
        with httpx.Client(headers=headers, timeout=httpx.Timeout(15, connect=8)) as client:
            return client.post(f"{api}/statuses/{quote(sha, safe='')}", json=body).status_code in (200, 201)
    except httpx.HTTPError:
        return False
    finally:
        headers["Authorization"] = ""


def branch_head(project: dict) -> dict | None:
    """{sha, message, author} of the tracked branch head, or None when GitHub cannot be read."""
    try:
        token = _token(project.get("github_token_ciphertext", ""))
        api = _api(project)
        _o, _r, branch = _validate(project)
    except Exception:
        return None
    headers = _headers(token)
    try:
        with httpx.Client(headers=headers, timeout=httpx.Timeout(15, connect=8)) as client:
            resp = client.get(f"{api}/commits/{quote(branch, safe='/')}")
            if resp.status_code != 200:
                return None
            data = resp.json()
            commit = data.get("commit") or {}
            return {"sha": str(data.get("sha", "")), "message": str(commit.get("message") or "").splitlines()[0][:300] if commit.get("message") else "",
                    "author": str((data.get("author") or {}).get("login") or (commit.get("author") or {}).get("name") or "")}
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        headers["Authorization"] = ""


# ---------------------------------------------------------------------------------------------------- intake
def enqueue(project: dict, sha: str, *, source: str, pusher: str = "", message: str = "") -> tuple[str, bool]:
    if portal_db.push_checks_last_hour(project["id"]) >= MAX_CHECKS_PER_HOUR:
        return "", False
    return portal_db.enqueue_push_check(project["id"], project["user_id"], sha, str(project.get("branch") or ""),
                                        source=source, pusher=pusher, commit_message=message)


def poll_once() -> int:
    """Fallback for missed webhooks and for repos where the webhook could not be installed: compare each branch head with
    the newest commit we already know. Cheap (one GitHub call per project)."""
    if not enabled():
        return 0
    queued = 0
    for project in portal_db.projects_to_poll():
        head = branch_head(project)
        if not head or not head["sha"]:
            continue
        known = {portal_db.latest_push_sha(project["id"]), str(project.get("last_checked_sha") or "")}
        if head["sha"] in known:
            continue
        try:
            _id, created = enqueue(project, head["sha"], source="poll", pusher=head["author"], message=head["message"])
            queued += int(created)
        except ValueError:
            continue
    return queued


# ---------------------------------------------------------------------------------------------------- the check itself
def _first_error_line(output: str) -> str:
    for line in (output or "").splitlines():
        text = line.strip()
        if not text or text.startswith(("[", "npm WARN", "WARNING", "Collecting", "Requirement already", "  ")):
            continue
        if re.search(r"(error|Error|ERROR|FAILED|failed|Exception|Traceback|cannot|not found|SyntaxError|TypeError)", text):
            return text[:200]
    return (output or "check failed").strip().splitlines()[-1][:200] if (output or "").strip() else "check failed"


def _signature(line: str) -> str:
    text = re.sub(r"0x[0-9a-f]+|\d+", "N", line)
    text = re.sub(r"['\"][^'\"]{0,80}['\"]", "'â€¦'", text)
    return ("Push check: " + text)[:180]


def _failure_summary(stacks: list[dict]) -> str:
    bad = [s for s in stacks if s.get("ok") is False]
    return ", ".join(f"{s['label']} failed at {s['phase'] or 'a step'}" for s in bad) or "the sandbox check failed"


def _record_report(check: dict, project: dict, stacks: list[dict], result, *, passed: bool, runner_name: str = "") -> None:
    """Write the health report for this check to the audit log (no schema change): for the first check after a repository
    is connected it is the BASELINE report, for later pushes a push report. Never raises: a report must not break a check."""
    try:
        totals = {"discovered": 0, "passed": 0, "failed": 0}
        for s in stacks:
            for k in totals:
                totals[k] += int((s.get("tests") or {}).get(k, 0))
        unknown = [s["label"] for s in stacks if s.get("has_tests") and not s.get("tests")]
        portal_db.audit(check["project_id"], "baseline_report" if check.get("source") == "connect" else "push_report", {
            "commit": check["sha"], "source": check.get("source", ""), "passed": bool(passed),
            "queued_at": check.get("created_at", ""), "started_at": check.get("started_at", ""), "reported_at": portal_db._now(),
            "stacks": [{k: s.get(k) for k in ("label", "language", "ok", "phase", "commands", "phases", "not_run", "has_tests", "tests", "notes")}
                       for s in stacks],
            "tests_total": totals, "tests_count_unknown_for": unknown,
            "runner": runner_name,
            "network": ("only the install phase had network access; build, test and start-up ran with --network none"
                        if runner_name in ("DockerRunner", "RemoteRunner") else "NOT isolated: this was a local development runner"),
            "output_tail": (result.output or "")[-1500:]})
    except Exception:
        LOG.exception("Could not record the health report for %s", str(check.get("sha", ""))[:7])


def run_check(check: dict, *, runner=None, snapshot=None, cfg: dict | None = None, notify_fn=None) -> str:
    """Check one pushed commit. Returns the final status: passed | failed | skipped | waiting (retry scheduled)."""
    cfg = cfg or fx_config.load()
    project = {"id": check["project_id"], "project_id": check["project_id"], "user_id": check["user_id"],
               "repo_owner": check["repo_owner"], "repo_name": check["repo_name"], "branch": check["sha"],
               "github_token_ciphertext": check["github_token_ciphertext"], "name": check.get("project_name", "")}
    ready, why = sandbox_ready(cfg) if runner is None else (True, "")
    snapshot = snapshot or (lambda p: repo_snapshot(p, cfg))
    if not ready:
        if not check.get("static_done"):
            # The code scan (retired AI models, ...) needs no sandbox: run it now, the sandbox part waits.
            try:
                with snapshot(project) as root:
                    static_scan(check, root)
            except Exception as exc:
                LOG.info("Static scan of %s postponed: %s", check["sha"][:7], exc.__class__.__name__)
        portal_db.retry_push_check(check["id"], 900, why)
        portal_db.set_push_check_stage(check["id"], "waiting_sandbox", why)
        return "waiting"
    runner = runner or sandbox.make_runner(cfg)
    portal_db.set_push_check_stage(check["id"], "downloading", f"commit {check['sha'][:7]}")
    try:
        with snapshot(project) as root:
            if not check.get("static_done"):
                try:
                    static_scan(check, root)
                except Exception:
                    LOG.exception("Static scan of %s failed", check["sha"][:7])
            portal_db.set_push_check_stage(check["id"], "detecting")
            from fixengine import repo_context
            files = repo_context.scan_repo(root, max_files=int(cfg["sandbox"]["max_repo_files"]))["files"]
            profile = sandbox.detect_profiles(root, files)
            stacks = sandbox.stack_summary(profile)
            if getattr(profile, "language", "none") == "none":
                portal_db.finish_push_check(check["id"], "skipped", output="; ".join(profile.notes), stacks=[],
                                            detail="No Python, JavaScript/TypeScript, Java or HTML project found")
                return "skipped"
            labels = ", ".join(s["label"] for s in stacks)
            portal_db.set_push_check_stage(check["id"], "testing", labels)
            set_commit_status(project, check["sha"], "pending", f"Testing {labels} in the Agent Daemon sandbox")
            result = sandbox.run_profile(runner, root, profile)
    except RemediationError as exc:
        portal_db.retry_push_check(check["id"], 300, str(exc)[:200])
        return "waiting"
    if result.system_fault:
        portal_db.retry_push_check(check["id"], 600, f"sandbox unavailable: {result.error}"[:200])
        return "waiting"
    stacks = sandbox.stack_report(profile, result)
    _record_report(check, project, stacks, result, passed=result.passed, runner_name=type(runner).__name__)
    if result.passed:
        portal_db.finish_push_check(check["id"], "passed", output=result.output, stacks=stacks, detail=f"{labels}: all green")
        set_commit_status(project, check["sha"], "success", f"{labels}: install, build, tests and start-up passed")
        portal_db.resolve_push_incidents(check["project_id"], f"commit {check['sha'][:7]} passed every check")
        return "passed"
    summary = _failure_summary(stacks)
    set_commit_status(project, check["sha"], "failure", summary)
    first = _first_error_line(result.output)
    message = f"Push {check['sha'][:7]} broke the build: {first}"
    traceback_text = (f"Commit {check['sha']} on {check.get('branch') or check.get('project_branch')}: {summary}\n\n"
                      f"{result.output}")[-6000:]
    incident_id, _new = portal_db.ingest_event(check["project_id"], timestamp=portal_db._now(), level="ERROR", message=message[:2000],
                                               traceback=traceback_text, signature=_signature(first))
    if incident_id:
        portal_db.mark_incident_source(incident_id, "push", check["sha"])
        own_fix = AGENT_MARK in str(check.get("commit_message") or "")
        if own_fix:
            portal_db.mark_remediation_needs_human(incident_id, check["project_id"],
                                                   "The agent's own fix was merged and the next check still failed. A person should look.")
            portal_db.set_incident_stage(incident_id, "needs_human", "the agent's own fix did not hold")
        elif check.get("mode") in ("pr", "auto"):
            portal_db.set_incident_stage(incident_id, "queued", "a fix starts in a few seconds")
        else:
            portal_db.set_incident_stage(incident_id, "queued", "report-only project: diagnosis only, no code changes")
    portal_db.finish_push_check(check["id"], "failed", output=result.output, stacks=stacks, incident_id=incident_id or "",
                                detail=summary)
    if notify_fn is None:
        notify_fn = _notify_owner
    try:
        notify_fn(check, summary, first, check.get("mode"))
    except Exception:
        LOG.exception("Could not email the owner about a failed push check")
    return "failed"


def static_scan(check: dict, root) -> list[dict]:
    """The code scan that runs on the first check after connecting and on every push: finds AI model ids that the provider
    has retired (the classic 'chatbot suddenly broken' bug that no build or test catches). Each finding becomes an incident
    and goes through the same fix pipeline (fixengine/model_fix.py). Findings that are gone are closed."""
    from fixengine import model_fix
    files = model_fix.read_repo(root)
    findings = model_fix.scan_files(files)
    keep = set()
    for f in findings:
        sig = model_fix.scan_signature(f["model"])
        keep.add(sig)
        where = ", ".join(f["files"][:6])
        message = (f"Your code uses the AI model {f['model']}, which the provider has retired (provider: {f['provider']}). "
                   f"Requests to it fail. Found in: {where}")
        incident_id, new = portal_db.ingest_event(check["project_id"], timestamp=portal_db._now(), level="ERROR", message=message[:2000],
                                                  traceback=f"Scan of commit {check['sha']}: {where}", signature=sig)
        if incident_id:
            portal_db.mark_incident_source(incident_id, "scan", check["sha"])
            portal_db.set_incident_stage(incident_id, "queued", f"retired AI model {f['model']}: a fix starts in a few seconds"
                                         if check.get("mode") in ("pr", "auto") else "report-only project: explanation only")
    portal_db.resolve_scan_incidents(check["project_id"], keep, f"commit {check['sha'][:7]} no longer uses a retired AI model")
    portal_db.mark_static_done(check["id"])
    if findings:
        LOG.info("Scan of %s found %s retired model(s)", check["sha"][:7], len(findings))
    return findings


def _notify_owner(check: dict, summary: str, first: str, mode: str) -> None:
    import notifications
    email = portal_db.get_user_email(check["user_id"])
    if not email:
        return
    base = os.getenv("PORTAL_BASE_URL", "").strip().rstrip("/")
    what_next = ("The agent is writing a fix now. It will be tested in the same sandbox and pushed to a new branch with a pull request"
                 + " for you to review and merge." if mode in ("pr", "auto")
                 else "Your project is in Report mode, so the agent only explains the problem.")
    notifications.notify_customer(
        email, f"Your push to {check.get('project_name') or 'your project'} broke: the agent is on it",
        f"Commit {check['sha'][:7]} ({check.get('commit_message') or 'no message'}) failed our sandbox check.\n\n"
        f"What failed: {summary}\nFirst error: {first}\n\n{what_next}\n\nWatch it live: {base}/dashboard", "push_failed")


def process_one(runner=None) -> bool:
    if not enabled():
        return False
    check = portal_db.claim_next_push_check()
    if not check:
        return False
    try:
        outcome = run_check(check, runner=runner)
        LOG.info("Push check %s for %s: %s", check["id"], check["sha"][:7], outcome)
    except Exception as exc:
        LOG.exception("Push check %s crashed", check["id"])
        portal_db.retry_push_check(check["id"], 600, exc.__class__.__name__)
    return True


def handle_webhook(project_id: str, event: str, body: bytes, signature: str) -> tuple[int, dict]:
    """Called by the web app for POST /webhooks/github/<project_id>. Returns (http status, json body)."""
    project = portal_db.get_project_any(project_id)
    if not project:
        return 404, {"error": "unknown project"}
    if not verify_signature(project, body, signature):
        return 401, {"error": "bad signature"}
    if event == "ping":
        return 200, {"ok": True, "pong": True}
    if event != "push":
        return 202, {"ok": True, "ignored": event}
    if project.get("watch_mode") not in ("push", "both") or project.get("paused"):
        return 202, {"ok": True, "ignored": "push checks are off for this project"}
    if project.get("gate_state") == portal_db.GATE_WAITING:
        return 202, {"ok": True, "ignored": "waiting for the repository to be made private"}
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return 400, {"error": "bad json"}
    push = parse_push(payload, project)
    if not push:
        return 202, {"ok": True, "ignored": "not the tracked branch"}
    try:
        check_id, created = enqueue(project, push["sha"], source="webhook", pusher=push["pusher"], message=push["message"])
    except ValueError:
        return 400, {"error": "bad commit"}
    if not check_id:
        return 429, {"error": "too many pushes this hour; the newest one will be checked by the poller"}
    return 202, {"ok": True, "check_id": check_id, "queued": created}
