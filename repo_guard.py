"""Public-repository safety gate.

Anything Agent Daemon commits into a customer's repository (monitor files with the project's connection details, fixes,
merges) is only written while GitHub says the repository is PRIVATE. Every code path that writes to a repository calls
ensure_private() first. When a repository is (or becomes) public:
  * nothing is committed,
  * the project goes to the "waiting for private repo" state (visible on the dashboard and the project page),
  * the owner is emailed (at most once a day) with simple step-by-step instructions,
  * work that needs a commit is parked and continues by itself once the repository is private again.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import portal_db
from monitoring_installer import GitHubInstallError, PublicRepoError, is_private, validate_repository_access

LOG = logging.getLogger("repo_guard")
NOTIFY_EVERY_HOURS = 24


def _token(project: dict) -> str:
    from portal_remediation import _token as decrypt
    return decrypt(str(project.get("github_token_ciphertext") or ""))


def repo_info(project: dict, token: str | None = None) -> dict:
    """GitHub's repository record (raises GitHubInstallError when GitHub cannot be asked)."""
    token = token if token is not None else _token(project)
    return validate_repository_access(owner=str(project.get("repo_owner", "")), repo=str(project.get("repo_name", "")), token=token)


def ensure_private(project: dict, token: str | None = None, *, action: str = "commit") -> dict:
    """Return GitHub's repo record when the repository is private. Otherwise flag the project, notify the owner and raise
    PublicRepoError. A GitHub/API failure raises GitHubInstallError (callers retry later; nothing is written)."""
    info = repo_info(project, token)
    project_id = str(project.get("id") or project.get("project_id") or "")
    if is_private(info):
        if project_id and project.get("gate_state") == portal_db.GATE_WAITING:
            portal_db.set_gate_state(project_id, portal_db.GATE_ACTIVE)
        elif project_id:
            portal_db.set_gate_state(project_id, project.get("gate_state") or portal_db.GATE_ACTIVE)
        return info
    if project_id:
        flag_public(project, action=action)
    raise PublicRepoError("The repository is public, so Agent Daemon did not write anything to it.")


def flag_public(project: dict, *, action: str = "commit") -> None:
    """Put the project into the waiting state and tell the owner (rate limited)."""
    project_id = str(project.get("id") or project.get("project_id") or "")
    fresh = portal_db.get_project_any(project_id) or project
    was_active = fresh.get("gate_state") != portal_db.GATE_WAITING
    last = str(fresh.get("gate_notified_at") or "")
    due = True
    if last:
        try:
            stamp = datetime.fromisoformat(last)
            stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
            due = datetime.now(timezone.utc) - stamp > timedelta(hours=NOTIFY_EVERY_HOURS)
        except ValueError:
            due = True
    portal_db.set_gate_state(project_id, portal_db.GATE_WAITING, notified=due)
    portal_db.audit(project_id, "repo_public_paused", {"action": action, "was_active": was_active})
    if due:
        _notify(fresh, was_active)


def _notify(project: dict, was_active: bool) -> None:
    try:
        import notifications
        email = portal_db.get_user_email(project["user_id"])
        if not email:
            return
        base = os.getenv("PORTAL_BASE_URL", "").strip().rstrip("/")
        repo = f"{project.get('repo_owner')}/{project.get('repo_name')}"
        what = ("Your repository just became public, so Agent Daemon paused everything that writes to it "
                "(monitor updates and fixes) to keep your connection details safe."
                if was_active else
                "Your monitoring agent is ready to be installed into your code, but your repository is public.")
        notifications.notify_customer(
            email, f"Action needed: make {repo} private",
            f"{what}\n\nAnyone on the internet can see a public repository, including the connection details our monitor needs.\n\n"
            "How to make it private (2 minutes):\n"
            f"1. Open https://github.com/{repo}/settings (sign in if asked).\n"
            "2. Scroll all the way down to the red 'Danger Zone'.\n"
            "3. Click 'Change visibility', then choose 'Make private' / 'Change to private'.\n"
            "4. Confirm (GitHub may ask you to type the repository name or your password).\n"
            f"5. Come back to {base}/projects/{project.get('id')} and press \"I've made it private, install now\".\n\n"
            "Nothing was installed or changed in your repository.", "repo_public")
    except Exception:
        LOG.exception("Could not email the owner about a public repository")


def sweep_visibility(limit: int = 20, min_age_seconds: int = 1800) -> int:
    """Worker task: re-check installed projects every ~30 minutes. A repository that became public is paused and its
    project key is rotated (the old key was in the now-public code, so it is revoked)."""
    flagged = 0
    for project in portal_db.projects_for_visibility_check(min_age_seconds)[:limit]:
        try:
            ensure_private(project, action="periodic check")
        except PublicRepoError:
            flagged += 1
            _revoke_exposed_key(project)
        except Exception as exc:          # GitHub down, token revoked: try again next round, never crash the worker
            LOG.info("Visibility check skipped for %s: %s", project.get("id"), exc.__class__.__name__)
            portal_db.set_gate_state(project["id"], project.get("gate_state") or "")
    return flagged


def _revoke_exposed_key(project: dict) -> None:
    """The monitor's key was committed while the repo was private; now that the code is public, revoke it."""
    if not (project.get("monitor_installed_at") or project.get("install_pr_url")):
        return
    import hashlib
    import secrets
    try:
        from cryptography.fernet import Fernet
        key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
        new_key = "adi_" + secrets.token_urlsafe(32)
        cipher = Fernet(key.encode("ascii")).encrypt(new_key.encode()).decode("ascii") if key else ""
        portal_db.rotate_project_ingest_key(project["id"], project["user_id"], hashlib.sha256(new_key.encode()).hexdigest(), cipher)
        portal_db.audit(project["id"], "ingest_key_revoked_repo_public")
    except Exception:
        LOG.exception("Could not rotate the exposed key of %s", project.get("id"))


__all__ = ["ensure_private", "flag_public", "repo_info", "sweep_visibility", "PublicRepoError", "GitHubInstallError"]
